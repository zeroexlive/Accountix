from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.catalog.models import Product
from apps.core.access import user_company_ids
from apps.core.pagination import apply_date_range, paginate
from apps.inventory import reporting
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
