from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from apps.core.access import user_company_ids
from apps.organizations.models import Company


def health(request):
    return JsonResponse({"status": "ok"})


@login_required
def dashboard(request):
    """The one dashboard route (core) rendering the reporting app's
    aggregation (Sprint 08): ``apps.reporting.services.dashboard_data``
    derives every card from the owning apps' reports — core keeps the
    URL, reporting owns the figures; there is no second dashboard."""
    from apps.reporting.services import dashboard_data

    companies = Company.objects.filter(id__in=user_company_ids(request.user), is_active=True)
    company = None
    data = None
    company_id = request.GET.get("company")
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
    elif companies:
        company = companies.first()
    if company is not None:
        data = dashboard_data(company)
    return render(
        request,
        "core/dashboard.html",
        {"companies": companies, "company": company, "dashboard": data},
    )
