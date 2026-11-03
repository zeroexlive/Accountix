from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.access import (
    ADMINISTER_ROLES,
    GOVERN_ROLES,
    require_company_role,
    user_company_ids,
)
from apps.core.forms import add_service_errors
from apps.organizations import services as org_services
from apps.organizations.forms import (
    AttachMemberForm,
    CompanyForm,
    CreateMemberUserForm,
    FiscalCloseForm,
    FiscalYearForm,
    MemberRoleForm,
)
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


# ---------------------------------------------------------------------------
# Sprint 26 — members UI (GOVERN tier, ADR-051; services: org_services)
# ---------------------------------------------------------------------------


def _governed_company(request, pk):
    """Resolve a members-page company with the ADR-050 ordering:
    membership scoping first (a non-member 404s — existence never
    leaks), then the GOVERN gate (a member below OWNER gets 403)."""
    company = get_object_or_404(Company, pk=pk, id__in=user_company_ids(request.user))
    require_company_role(request.user, company, GOVERN_ROLES)
    return company


def _governed_membership(request, pk, member_pk):
    """Company + one of ITS memberships: a membership id from another
    company 404s on the company-scoped fetch, whoever asks."""
    company = _governed_company(request, pk)
    membership = get_object_or_404(CompanyMembership, pk=member_pk, company=company)
    return company, membership


def _render_members(request, company, attach_form=None, create_form=None):
    return render(
        request,
        "organizations/company_members.html",
        {
            "company": company,
            "memberships": CompanyMembership.objects.filter(company=company)
            .select_related("user")
            .order_by("user__username"),
            "attach_form": attach_form
            if attach_form is not None
            else AttachMemberForm(company=company),
            "create_form": create_form if create_form is not None else CreateMemberUserForm(),
            "role_choices": CompanyMembership.Role.choices,
        },
    )


@login_required
def company_members(request, pk):
    company = _governed_company(request, pk)
    return _render_members(request, company)


@login_required
@require_POST
def company_member_add_existing(request, pk):
    company = _governed_company(request, pk)
    form = AttachMemberForm(request.POST, company=company)
    if form.is_valid():
        try:
            org_services.add_member(
                actor=request.user,
                company=company,
                user=form.user,
                role=form.cleaned_data["role"],
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, _("عضو به شرکت افزوده شد."))
            return redirect("company_members", pk=company.pk)
    return _render_members(request, company, attach_form=form)


@login_required
@require_POST
def company_member_add_new(request, pk):
    company = _governed_company(request, pk)
    form = CreateMemberUserForm(request.POST)
    if form.is_valid():
        try:
            org_services.create_member(
                actor=request.user,
                company=company,
                username=form.cleaned_data["username"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                password=form.cleaned_data["password1"],
                role=form.cleaned_data["role"],
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, _("کاربر ساخته و به شرکت افزوده شد."))
            return redirect("company_members", pk=company.pk)
    return _render_members(request, company, create_form=form)


@login_required
@require_POST
def company_member_role(request, pk, member_pk):
    company, membership = _governed_membership(request, pk, member_pk)
    form = MemberRoleForm(request.POST)
    if form.is_valid():
        try:
            org_services.change_member_role(
                actor=request.user, membership=membership, new_role=form.cleaned_data["role"]
            )
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, _("نقش عضو به‌روزرسانی شد."))
    else:
        messages.error(request, _("نقش نامعتبر است."))
    return redirect("company_members", pk=company.pk)


@login_required
@require_POST
def company_member_deactivate(request, pk, member_pk):
    company, membership = _governed_membership(request, pk, member_pk)
    try:
        org_services.deactivate_member(actor=request.user, membership=membership)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("عضویت غیرفعال شد."))
    return redirect("company_members", pk=company.pk)


@login_required
@require_POST
def company_member_reactivate(request, pk, member_pk):
    company, membership = _governed_membership(request, pk, member_pk)
    org_services.reactivate_member(actor=request.user, membership=membership)
    messages.success(request, _("عضویت دوباره فعال شد."))
    return redirect("company_members", pk=company.pk)


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
        # ADMINISTER tier (ADR-050): fiscal structure is owner/admin work.
        require_company_role(request.user, form.cleaned_data["company"], ADMINISTER_ROLES)
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
    require_company_role(request.user, period.company, ADMINISTER_ROLES)
    if period.status == FiscalPeriod.Status.CLOSED:
        messages.info(request, _("این دوره قبلاً بسته شده است."))
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
                messages.success(request, _("دوره بسته شد و سند اختتامیه ثبت شد."))
            else:
                messages.success(request, _("دوره بسته شد؛ فعالیتی نداشت و سندی ثبت نشد."))
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
    require_company_role(request.user, period.company, ADMINISTER_ROLES)
    try:
        accounting_services.reopen_fiscal_period(
            company=period.company, period=period, user=request.user
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("دوره بازگشایی شد و سند اختتامیه برگشت خورد."))
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
    require_company_role(request.user, year.company, ADMINISTER_ROLES)
    if year.status == FiscalYear.Status.CLOSED:
        messages.info(request, _("این سال مالی قبلاً بسته شده است."))
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
                _("سال مالی بسته شد؛ %(count)s سند اختتامیه ثبت شد.") % {"count": len(entries)},
            )
            return redirect("fiscal_year_detail", pk=year.pk)
    return render(
        request,
        "organizations/fiscal_year_close.html",
        {"year": year, "open_periods": open_periods, "form": form},
    )
