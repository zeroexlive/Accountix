from decimal import Decimal

from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.forms import ProductCategoryForm, ProductForm, UnitForm
from apps.catalog.models import Product, ProductCategory
from apps.core.access import (
    member_companies,
    require_posted_company_member,
    resolve_scoped_company,
    user_company_ids,
)
from apps.core.forms import add_service_errors
from apps.core.pagination import apply_date_range, paginate
from apps.inventory import reporting, services
from apps.inventory.forms import (
    CountLineFormSet,
    CountPostForm,
    InventoryCountCreateForm,
    WarehouseForm,
)
from apps.inventory.models import InventoryCount
from apps.organizations.models import Company


@login_required
def product_list(request):
    products = (
        Product.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "category", "base_unit")
        .order_by("sku")
    )
    return render(request, "inventory/product_list.html", {"products": products})


@login_required
def product_create(request):
    """Product create (Sprint 12). The company is chosen first (the
    shared chooser pattern) because the category/unit pickers are
    scoped to it; the form itself also carries the company as a hidden
    field so a forged id outside the memberships 404s in
    ``resolve_scoped_company`` before any validation runs."""
    companies, company = resolve_scoped_company(request)
    form = ProductForm(
        request.POST or None,
        company=company,
        initial={"company": company} if company else None,
    )
    form.fields["company"].queryset = companies
    form.fields["company"].widget = django_forms.HiddenInput()
    if request.method == "POST" and company is not None and form.is_valid():
        form.save()
        messages.success(request, "کالا ایجاد شد.")
        return redirect("product_list")
    return render(
        request,
        "inventory/product_form.html",
        {"form": form, "companies": companies, "company": company, "product": None},
    )


@login_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk, company_id__in=user_company_ids(request.user))
    form = ProductForm(request.POST or None, instance=product, company=product.company)
    form.fields["company"].queryset = member_companies(request.user)
    form.fields["company"].disabled = True
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "کالا ذخیره شد.")
        return redirect("product_list")
    return render(
        request,
        "inventory/product_form.html",
        {"form": form, "companies": None, "company": product.company, "product": product},
    )


@login_required
def unit_create(request):
    if request.method == "POST":
        require_posted_company_member(request)
    form = UnitForm(request.POST or None)
    form.fields["company"].queryset = member_companies(request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "واحد ایجاد شد.")
        return redirect("product_list")
    return render(request, "inventory/unit_form.html", {"form": form})


@login_required
def category_create(request):
    if request.method == "POST":
        require_posted_company_member(request)
    form = ProductCategoryForm(request.POST or None)
    companies = member_companies(request.user)
    form.fields["company"].queryset = companies
    form.fields["parent"].queryset = ProductCategory.objects.filter(
        company_id__in=user_company_ids(request.user)
    ).order_by("code")
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "دسته‌بندی ایجاد شد.")
        return redirect("product_list")
    return render(request, "inventory/category_form.html", {"form": form})


@login_required
def warehouse_create(request):
    if request.method == "POST":
        require_posted_company_member(request)
    form = WarehouseForm(request.POST or None)
    form.fields["company"].queryset = member_companies(request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "انبار ایجاد شد.")
        return redirect("product_list")
    return render(request, "inventory/warehouse_form.html", {"form": form})


@login_required
def inventory_count_list(request):
    counts = (
        InventoryCount.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "warehouse")
        .prefetch_related("lines")
    )
    return render(request, "inventory/count_list.html", {"counts": counts})


@login_required
def inventory_count_create(request):
    """Start a stock count (Sprint 13): the service snapshots every
    active stockable product's balance in the chosen warehouse and
    seeds the counted quantity with the snapshot — the physical count
    is then typed in on the count page."""
    companies, company = resolve_scoped_company(request)
    form = InventoryCountCreateForm(
        request.POST or None,
        companies=companies,
        company=company,
        initial={"company": company} if company else None,
    )
    if request.method == "POST" and company is not None and form.is_valid():
        warehouse = form.cleaned_data["warehouse"]
        balances = {
            row["product_id"]: row["quantity"]
            for row in reporting.stock_balances(company, warehouse=warehouse)
        }
        products = Product.objects.filter(
            company=company, is_active=True, is_stockable=True
        ).order_by("sku")
        lines = [
            {"product": product, "counted_qty": balances.get(product.id, Decimal("0"))}
            for product in products
        ]
        try:
            count = services.create_inventory_count(
                company=company,
                warehouse=warehouse,
                count_date=form.cleaned_data["count_date"],
                lines=lines,
                description=form.cleaned_data["description"],
                user=request.user,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "انبارگردانی ایجاد شد؛ مقادیر شمارش‌شده را وارد کنید.")
            return redirect("inventory_count_detail", pk=count.pk)
    return render(
        request,
        "inventory/count_form.html",
        {"form": form, "companies": companies, "company": company},
    )


def _scoped_count(request, pk):
    return get_object_or_404(
        InventoryCount.objects.select_related("company", "warehouse"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )


@login_required
def inventory_count_detail(request, pk):
    count = _scoped_count(request, pk)
    lines = list(count.lines.select_related("product").all())
    rows = []
    line_forms = CountLineFormSet(
        initial=[{"counted_qty": line.counted_qty, "unit_cost": line.unit_cost} for line in lines],
        prefix="lines",
    )
    for line, line_form in zip(lines, line_forms, strict=True):
        current = reporting.stock_balance(count.company, count.warehouse, line.product)["quantity"]
        rows.append({"line": line, "current_qty": current, "form": line_form})
    post_form = CountPostForm(company=count.company)
    return render(
        request,
        "inventory/count_detail.html",
        {
            "count": count,
            "rows": rows,
            "line_forms": line_forms,
            "post_form": post_form,
        },
    )


@login_required
@require_POST
def inventory_count_save(request, pk):
    """Save the typed-in counted quantities of a DRAFT count through
    ``update_inventory_count_lines`` (Sprint 13)."""
    count = _scoped_count(request, pk)
    lines = list(count.lines.select_related("product").all())
    formset = CountLineFormSet(request.POST, prefix="lines")
    if formset.is_valid() and len(formset) == len(lines):
        updates = [
            {
                "product": line.product,
                "counted_qty": line_form.cleaned_data.get("counted_qty"),
                "unit_cost": line_form.cleaned_data.get("unit_cost"),
            }
            for line, line_form in zip(lines, formset, strict=True)
        ]
        try:
            services.update_inventory_count_lines(count, lines=updates, user=request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "مقادیر شمارش ذخیره شد.")
    else:
        messages.error(request, "مقادیر شمارش معتبر نیست؛ بررسی کنید.")
    return redirect("inventory_count_detail", pk=count.pk)


@login_required
@require_POST
def inventory_count_post(request, pk):
    """Post a count: the ADR-027 warehouse-freeze rule lives in the
    service — a balance that moved since the snapshot rejects the
    post and its message is shown verbatim on the count page."""
    count = _scoped_count(request, pk)
    form = CountPostForm(request.POST, company=count.company)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("inventory_count_detail", pk=count.pk)
    gl_accounts = None
    if form.cleaned_data.get("inventory_account") is not None:
        gl_accounts = {
            "inventory": form.cleaned_data["inventory_account"],
            "variance": form.cleaned_data["variance_account"],
        }
    try:
        services.post_inventory_count(count, user=request.user, gl_accounts=gl_accounts)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "انبارگردانی ثبت نهایی شد.")
    return redirect("inventory_count_detail", pk=count.pk)


@login_required
@require_POST
def inventory_count_reverse(request, pk):
    count = _scoped_count(request, pk)
    try:
        services.reverse_inventory_count(
            count, user=request.user, reason=request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "انبارگردانی برگشت خورد.")
    return redirect("inventory_count_detail", pk=count.pk)


@login_required
def stock_balance_list(request):
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    company = None
    rows = None
    company_id = request.GET.get("company")
    warehouses = []
    warehouse = None
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
        from apps.inventory.models import Warehouse

        warehouses = Warehouse.objects.filter(company=company).order_by("code")
        if request.GET.get("warehouse"):
            warehouse = get_object_or_404(warehouses, pk=request.GET["warehouse"])
        rows = reporting.stock_balances(company, warehouse=warehouse)
        q = request.GET.get("q", "").strip().lower()
        if q:
            rows = [r for r in rows if q in r["sku"].lower() or q in r["name"].lower()]
    return render(
        request,
        "inventory/stock_balances.html",
        {
            "companies": companies,
            "company": company,
            "rows": rows,
            "warehouses": warehouses,
            "warehouse": warehouse,
        },
    )


@login_required
def stock_movement_list(request):
    """Stock movement ledger list (Sprint 08): membership-filtered,
    with warehouse / product-search / date filters and pagination."""
    from apps.inventory.models import StockMovement, Warehouse

    movements = (
        StockMovement.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "warehouse", "product", "document")
        .order_by("-movement_date", "-created_at")
    )
    warehouses = Warehouse.objects.filter(company_id__in=user_company_ids(request.user)).order_by(
        "code"
    )
    if request.GET.get("warehouse"):
        warehouse = get_object_or_404(warehouses, pk=request.GET["warehouse"])
        movements = movements.filter(warehouse=warehouse)
    if request.GET.get("q"):
        q = request.GET["q"]
        movements = movements.filter(product__sku__icontains=q) | movements.filter(
            product__name__icontains=q
        )
    movements = apply_date_range(movements, request.GET, "movement_date")
    page_obj, filter_query = paginate(request, movements)
    return render(
        request,
        "inventory/movement_list.html",
        {
            "movements": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "warehouses": warehouses,
        },
    )
