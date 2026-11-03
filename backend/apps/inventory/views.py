from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.catalog.forms import ProductCategoryForm, ProductForm, UnitForm
from apps.catalog.models import Product, ProductCategory
from apps.core.access import (
    member_companies,
    require_posted_company_member,
    resolve_scoped_company,
    user_company_ids,
)
from apps.core.pagination import apply_date_range, paginate
from apps.inventory import reporting
from apps.inventory.forms import WarehouseForm
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
    from apps.inventory.models import InventoryCount

    counts = (
        InventoryCount.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "warehouse")
        .prefetch_related("lines")
    )
    return render(request, "inventory/count_list.html", {"counts": counts})


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
