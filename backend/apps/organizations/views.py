from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.access import user_company_ids
from apps.organizations.forms import CompanyForm, FiscalYearForm
from apps.organizations.models import Company, CompanyMembership, FiscalYear


@login_required
def company_list(request):
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    return render(request, "organizations/company_list.html", {"companies": companies})


@login_required
@transaction.atomic
def company_create(request):
    form = CompanyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        company = form.save()
        CompanyMembership.objects.create(
            company=company, user=request.user, role=CompanyMembership.Role.OWNER
        )
        return redirect("company_list")
    return render(request, "organizations/company_form.html", {"form": form})


@login_required
def fiscal_year_list(request):
    years = FiscalYear.objects.filter(company_id__in=user_company_ids(request.user)).select_related(
        "company"
    )
    return render(request, "organizations/fiscal_year_list.html", {"years": years})


@login_required
def fiscal_year_create(request):
    form = FiscalYearForm(request.POST or None)
    form.fields["company"].queryset = Company.objects.filter(id__in=user_company_ids(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("fiscal_year_list")
    return render(request, "organizations/fiscal_year_form.html", {"form": form})


@login_required
def company_detail(request, pk):
    company = get_object_or_404(Company, pk=pk, id__in=user_company_ids(request.user))
    return render(request, "organizations/company_detail.html", {"company": company})
