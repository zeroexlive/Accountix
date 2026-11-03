import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounting import reporting, services
from apps.accounting.forms import AccountForm, JournalEntryForm, JournalLineFormSet
from apps.accounting.models import Account, JournalEntry
from apps.core.access import resolve_scoped_company, user_company_ids
from apps.core.forms import add_service_errors
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
def journal_create(request):
    """Manual journal entry: header + line formset → DRAFT via the
    accounting service (Sprint 12, ADR-039). §6.3 line rules are
    enforced by ``create_journal_draft``; its messages come back as
    form errors verbatim."""
    companies, company = resolve_scoped_company(request)
    form = JournalEntryForm(request.POST or None, companies=companies)
    lines = JournalLineFormSet(
        request.POST or None, prefix="lines", form_kwargs={"company": company}
    )
    if request.method == "POST" and company is not None and form.is_valid() and lines.is_valid():
        line_dicts = []
        for line_form in lines:
            if line_form.cleaned_data.get("DELETE"):
                continue
            account = line_form.cleaned_data.get("account")
            if account is None:
                continue
            line_dicts.append(
                {
                    "account": account,
                    "debit": line_form.cleaned_data.get("debit") or 0,
                    "credit": line_form.cleaned_data.get("credit") or 0,
                    "description": line_form.cleaned_data.get("description", ""),
                    "party": line_form.cleaned_data.get("party"),
                }
            )
        key = form.cleaned_data["idempotency_key"] or f"manual:{uuid.uuid4()}"
        try:
            entry = services.create_journal_draft(
                company=company,
                entry_date=form.cleaned_data["entry_date"],
                lines=line_dicts,
                description=form.cleaned_data["description"],
                user=request.user,
                idempotency_key=key,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "سند دستی به‌صورت پیش‌نویس ایجاد شد.")
            return redirect("journal_detail", pk=entry.pk)
    return render(
        request,
        "accounting/journal_form.html",
        {"form": form, "lines": lines, "companies": companies, "company": company},
    )


@login_required
def journal_detail(request, pk):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("company", "fiscal_period", "reversal_of"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    lines = entry.lines.select_related("account", "party").all()
    return render(
        request,
        "accounting/journal_detail.html",
        {"entry": entry, "lines": lines},
    )


@login_required
@require_POST
def journal_post(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.post_journal_draft(entry, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "سند ثبت نهایی شد.")
    return redirect("journal_detail", pk=entry.pk)


@login_required
@require_POST
def journal_reverse(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.reverse_journal_entry(
            entry=entry, user=request.user, reason=request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "سند برگشت خورد.")
    return redirect("journal_detail", pk=entry.pk)


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
