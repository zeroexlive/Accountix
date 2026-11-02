from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.catalog.models import Product
from apps.core.access import user_company_ids
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
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
        rows = reporting.stock_balances(company)
    return render(
        request,
        "inventory/stock_balances.html",
        {"companies": companies, "company": company, "rows": rows},
    )
