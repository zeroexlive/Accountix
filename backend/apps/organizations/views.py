from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.access import user_company_ids
from apps.core.forms import add_service_errors
from apps.organizations.forms import CompanyForm, FiscalCloseForm, FiscalYearForm
from apps.organizations.models import (
    Company,
    CompanyMembership,
    FiscalPeriod,
    FiscalYear,
)


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


# ---------------------------------------------------------------------------
# Sprint 13 — fiscal closing UI (services: apps.accounting.services, ADR-028)
# ---------------------------------------------------------------------------


def _posted_closing_entries(company, periods):
    """Map period id → its currently POSTED closing entry (display only;
    the write path is the closing service)."""
    from apps.accounting.models import JournalEntry

    entries = JournalEntry.objects.filter(
        company=company,
        source_type="CLOSING",
        source_id__in=[str(p.id) for p in periods],
        status=JournalEntry.Status.POSTED,
    )
    return {entry.source_id: entry for entry in entries}


@login_required
def fiscal_year_detail(request, pk):
    year = get_object_or_404(
        FiscalYear.objects.select_related("company"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    periods = list(year.periods.all())
    closing = _posted_closing_entries(year.company, periods)
    rows = [{"period": period, "closing_entry": closing.get(str(period.id))} for period in periods]
    return render(
        request,
        "organizations/fiscal_year_detail.html",
        {"year": year, "rows": rows},
    )


@login_required
def fiscal_period_close(request, pk):
    """Close one period: a preview page (income-statement totals that
    will move to retained earnings) whose POST calls the closing
    service. The closing entry is dated the period's last day by the
    service; an activity-free period closes with no entry."""
    from apps.accounting import reporting
    from apps.accounting import services as accounting_services

    period = get_object_or_404(
        FiscalPeriod.objects.select_related("company", "fiscal_year"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    if period.status == FiscalPeriod.Status.CLOSED:
        messages.info(request, "این دوره قبلاً بسته شده است.")
        return redirect("fiscal_year_detail", pk=period.fiscal_year_id)
    result = reporting.income_statement(period.company, fiscal_period=period)
    form = FiscalCloseForm(request.POST or None, company=period.company)
    if request.method == "POST" and form.is_valid():
        try:
            entry = accounting_services.close_fiscal_period(
                company=period.company,
                period=period,
                retained_earnings=form.cleaned_data["retained_earnings"],
                user=request.user,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            if entry is not None:
                messages.success(request, "دوره بسته شد و سند اختتامیه ثبت شد.")
            else:
                messages.success(request, "دوره بسته شد؛ فعالیتی نداشت و سندی ثبت نشد.")
            return redirect("fiscal_year_detail", pk=period.fiscal_year_id)
    return render(
        request,
        "organizations/fiscal_period_close.html",
        {"period": period, "result": result, "form": form},
    )


@login_required
@require_POST
def fiscal_period_reopen(request, pk):
    """Reopen a closed period. ADR-028: the only way back is reversing
    the closing entry — ``reopen_fiscal_period`` does the status flip
    and the reversal in one transaction; the UI never edits the
    period status itself."""
    from apps.accounting import services as accounting_services

    period = get_object_or_404(FiscalPeriod, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        accounting_services.reopen_fiscal_period(
            company=period.company, period=period, user=request.user
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "دوره بازگشایی شد و سند اختتامیه برگشت خورد.")
    return redirect("fiscal_year_detail", pk=period.fiscal_year_id)


@login_required
def fiscal_year_close(request, pk):
    """Close a whole fiscal year: every still-OPEN period goes through
    the same period-closing service, then the year flips to CLOSED."""
    from apps.accounting import services as accounting_services

    year = get_object_or_404(
        FiscalYear.objects.select_related("company"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    if year.status == FiscalYear.Status.CLOSED:
        messages.info(request, "این سال مالی قبلاً بسته شده است.")
        return redirect("fiscal_year_detail", pk=year.pk)
    open_periods = [p for p in year.periods.all() if p.status == FiscalPeriod.Status.OPEN]
    form = FiscalCloseForm(request.POST or None, company=year.company)
    if request.method == "POST" and form.is_valid():
        try:
            entries = accounting_services.close_fiscal_year(
                company=year.company,
                fiscal_year=year,
                retained_earnings=form.cleaned_data["retained_earnings"],
                user=request.user,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(
                request,
                f"سال مالی بسته شد؛ {len(entries)} سند اختتامیه ثبت شد.",
            )
            return redirect("fiscal_year_detail", pk=year.pk)
    return render(
        request,
        "organizations/fiscal_year_close.html",
        {"year": year, "open_periods": open_periods, "form": form},
    )
