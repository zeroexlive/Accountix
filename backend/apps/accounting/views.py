from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounting import reporting
from apps.accounting.forms import AccountForm
from apps.accounting.models import Account, JournalEntry
from apps.core.access import user_company_ids
from apps.organizations.models import Company


@login_required
def account_list(request):
    accounts = Account.objects.filter(company_id__in=user_company_ids(request.user)).select_related(
        "company", "parent"
    )
    return render(request, "accounting/account_list.html", {"accounts": accounts})


@login_required
def journal_list(request):
    entries = JournalEntry.objects.filter(
        company_id__in=user_company_ids(request.user)
    ).select_related("company", "fiscal_period")
    return render(request, "accounting/journal_list.html", {"entries": entries})


@login_required
def trial_balance_view(request):
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    company = None
    result = None
    company_id = request.GET.get("company")
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
        result = reporting.trial_balance(company)
    return render(
        request,
        "accounting/trial_balance.html",
        {"companies": companies, "company": company, "result": result},
    )


@login_required
def income_statement_view(request):
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    company = None
    result = None
    company_id = request.GET.get("company")
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
        result = reporting.income_statement(company)
    return render(
        request,
        "accounting/income_statement.html",
        {"companies": companies, "company": company, "result": result},
    )


@login_required
def balance_sheet_view(request):
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    company = None
    result = None
    company_id = request.GET.get("company")
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
        result = reporting.balance_sheet(company)
    return render(
        request,
        "accounting/balance_sheet.html",
        {"companies": companies, "company": company, "result": result},
    )


@login_required
def account_create(request):
    form = AccountForm(request.POST or None)
    allowed = Company.objects.filter(id__in=user_company_ids(request.user))
    form.fields["company"].queryset = allowed
    form.fields["parent"].queryset = Account.objects.filter(
        company_id__in=user_company_ids(request.user)
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("account_list")
    return render(request, "accounting/account_form.html", {"form": form})
