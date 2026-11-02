from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounting import reporting
from apps.accounting.forms import AccountForm
from apps.accounting.models import Account, JournalEntry
from apps.core.access import user_company_ids
from apps.core.pagination import apply_date_range, paginate
from apps.organizations.models import Company, FiscalPeriod


def _member_company(request):
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    company_id = request.GET.get("company")
    if not company_id:
        return companies, None
    return companies, get_object_or_404(companies, pk=company_id)


def _member_period(request, company):
    period_id = request.GET.get("period")
    if not period_id or company is None:
        return None
    return get_object_or_404(FiscalPeriod.objects.filter(company=company), pk=period_id)


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
    if request.GET.get("status"):
        entries = entries.filter(status=request.GET["status"])
    entries = apply_date_range(entries, request.GET, "entry_date")
    entries = entries.order_by("entry_date", "created_at")
    page_obj, filter_query = paginate(request, entries)
    return render(
        request,
        "accounting/journal_list.html",
        {
            "entries": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": JournalEntry.Status.choices,
        },
    )


@login_required
def trial_balance_view(request):
    companies, company = _member_company(request)
    result = None
    period = _member_period(request, company)
    periods = FiscalPeriod.objects.filter(company=company) if company else []
    if company is not None:
        result = reporting.trial_balance(company, fiscal_period=period)
    return render(
        request,
        "accounting/trial_balance.html",
        {
            "companies": companies,
            "company": company,
            "periods": periods,
            "period": period,
            "result": result,
        },
    )


@login_required
def income_statement_view(request):
    companies, company = _member_company(request)
    result = None
    period = _member_period(request, company)
    periods = FiscalPeriod.objects.filter(company=company) if company else []
    expense_accounts = (
        Account.objects.filter(company=company, account_type="EXPENSE").order_by("code")
        if company
        else []
    )
    selected_cogs = []
    if company is not None:
        cogs_ids = request.GET.getlist("cogs")
        selected_cogs = list(
            Account.objects.filter(company=company, account_type="EXPENSE", pk__in=cogs_ids)
        )
        result = reporting.income_statement(
            company,
            fiscal_period=period,
            date_from=request.GET.get("date_from") or None,
            date_to=request.GET.get("date_to") or None,
            cogs_accounts=selected_cogs,
        )
    return render(
        request,
        "accounting/income_statement.html",
        {
            "companies": companies,
            "company": company,
            "periods": periods,
            "period": period,
            "expense_accounts": expense_accounts,
            "selected_cogs_ids": [str(a.pk) for a in selected_cogs],
            "result": result,
        },
    )


@login_required
def balance_sheet_view(request):
    companies, company = _member_company(request)
    result = None
    period = _member_period(request, company)
    periods = FiscalPeriod.objects.filter(company=company) if company else []
    if company is not None:
        as_of = request.GET.get("as_of") or None
        if period is not None:
            result = reporting.balance_sheet(company, fiscal_period=period)
        else:
            result = reporting.balance_sheet(company, as_of=as_of)
    return render(
        request,
        "accounting/balance_sheet.html",
        {
            "companies": companies,
            "company": company,
            "periods": periods,
            "period": period,
            "result": result,
        },
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
