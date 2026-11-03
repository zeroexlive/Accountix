from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.access import resolve_scoped_company, user_company_ids
from apps.core.forms import add_service_errors
from apps.core.pagination import apply_date_range, paginate
from apps.treasury import reporting, services
from apps.treasury.forms import (
    AllocationForm,
    ChequeClearForm,
    PaymentForm,
    PaymentPostForm,
    TreasuryAccountForm,
)
from apps.treasury.models import Cheque, Payment, PaymentAllocation, TreasuryAccount


@login_required
def treasury_account_list(request):
    accounts = TreasuryAccount.objects.filter(
        company_id__in=user_company_ids(request.user)
    ).select_related("company", "gl_account")
    rows = [
        {
            "account": account,
            "balance": reporting.treasury_account_balance(account.company, account),
        }
        for account in accounts
    ]
    return render(request, "treasury/account_list.html", {"rows": rows})


@login_required
def payment_list(request):
    payments = (
        Payment.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "party", "treasury_account")
        .order_by("-payment_date", "-created_at")
    )
    if request.GET.get("status"):
        payments = payments.filter(status=request.GET["status"])
    if request.GET.get("method"):
        payments = payments.filter(method=request.GET["method"])
    payments = apply_date_range(payments, request.GET, "payment_date")
    page_obj, filter_query = paginate(request, payments)
    return render(
        request,
        "treasury/payment_list.html",
        {
            "payments": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": Payment.Status.choices,
            "methods": Payment.Method.choices,
        },
    )


@login_required
def cheque_list(request):
    cheques = (
        Cheque.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "payment__party")
        .order_by("due_date")
    )
    if request.GET.get("status"):
        cheques = cheques.filter(status=request.GET["status"])
    if request.GET.get("direction"):
        cheques = cheques.filter(direction=request.GET["direction"])
    cheques = apply_date_range(cheques, request.GET, "due_date")
    # apply_date_range uses date_from/date_to on due_date; treasury uses it as due range.
    page_obj, filter_query = paginate(request, cheques)
    return render(
        request,
        "treasury/cheque_list.html",
        {
            "cheques": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": Cheque.Status.choices,
            "directions": Cheque.Direction.choices,
        },
    )


@login_required
def treasury_account_create(request):
    companies, company = resolve_scoped_company(request)
    form = TreasuryAccountForm(request.POST or None, company=company, companies=companies)
    if request.method == "POST" and company is not None and form.is_valid():
        try:
            services.create_treasury_account(
                company=company,
                kind=form.cleaned_data["kind"],
                name=form.cleaned_data["name"],
                gl_account=form.cleaned_data["gl_account"],
                bank_name=form.cleaned_data["bank_name"],
                account_number=form.cleaned_data["account_number"],
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "حساب خزانه ایجاد شد.")
            return redirect("treasury_account_list")
    return render(
        request,
        "treasury/account_form.html",
        {"form": form, "companies": companies, "company": company},
    )


@login_required
def payment_create(request):
    companies, company = resolve_scoped_company(request)
    direction = request.POST.get("direction") or request.GET.get("direction") or None
    form = PaymentForm(
        request.POST or None, company=company, companies=companies, direction=direction
    )
    if request.method == "POST" and company is not None and form.is_valid():
        data = form.cleaned_data
        cheque = None
        if data["method"] == Payment.Method.CHEQUE:
            cheque = {
                "bank_name": data["cheque_bank_name"],
                "cheque_number": data["cheque_number"],
                "sayad_id": data["sayad_id"],
                "issue_date": data["cheque_issue_date"],
                "due_date": data["cheque_due_date"],
            }
        try:
            payment = services.create_payment(
                company=company,
                direction=data["direction"],
                party=data["party"],
                treasury_account=data["treasury_account"],
                amount=data["amount"],
                payment_date=data["payment_date"],
                method=data["method"],
                reference=data["reference"],
                description=data["description"],
                cheque=cheque,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "دریافت/پرداخت به‌صورت پیش‌نویس ایجاد شد.")
            return redirect("payment_detail", pk=payment.pk)
    return render(
        request,
        "treasury/payment_form.html",
        {"form": form, "companies": companies, "company": company},
    )


def _payment_open_items(payment):
    """Open invoices of the payment's party that this payment may be
    allocated to (receipts → sales invoices, payments → purchases)."""
    items = reporting.open_items(payment.company, party=payment.party)
    wanted = "SALES" if payment.direction == Payment.Direction.RECEIPT else "PURCHASE"
    return [item for item in items if item["kind"] == wanted]


def _payment_detail_context(payment, post_form=None, allocation_form=None):
    context = {
        "payment": payment,
        "allocations": payment.allocations.select_related(
            "sales_invoice", "purchase_invoice"
        ).all(),
        "cheque": payment.cheques.first(),
        "allocated_total": services.allocated_total_for_payment(payment),
        "unallocated": payment.amount - services.allocated_total_for_payment(payment),
    }
    if payment.status == Payment.Status.DRAFT:
        context["post_form"] = post_form or PaymentPostForm(payment=payment)
    if payment.status == Payment.Status.POSTED:
        items = _payment_open_items(payment)
        form = allocation_form or AllocationForm(items=items)
        context["open_items"] = items
        context["allocation_form"] = form
        context["allocation_rows"] = [
            {"item": item, "field": form[f"amount_{idx}"]} for idx, item in enumerate(items)
        ]
    return context


@login_required
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("company", "party", "treasury_account"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "treasury/payment_detail.html", _payment_detail_context(payment))


@login_required
@require_POST
def payment_post(request, pk):
    payment = get_object_or_404(Payment, pk=pk, company_id__in=user_company_ids(request.user))
    form = PaymentPostForm(request.POST, payment=payment)
    if form.is_valid():
        gl_accounts = {k: v for k, v in form.cleaned_data.items() if v is not None}
        try:
            services.post_payment(payment, user=request.user, gl_accounts=gl_accounts)
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, "دریافت/پرداخت ثبت نهایی شد.")
            return redirect("payment_detail", pk=payment.pk)
    payment.refresh_from_db()
    return render(
        request, "treasury/payment_detail.html", _payment_detail_context(payment, post_form=form)
    )


@login_required
@require_POST
def payment_allocate(request, pk):
    payment = get_object_or_404(Payment, pk=pk, company_id__in=user_company_ids(request.user))
    items = _payment_open_items(payment)
    form = AllocationForm(request.POST, items=items)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return redirect("payment_detail", pk=payment.pk)
    allocated_any = False
    for idx, item in enumerate(items):
        amount = form.cleaned_data.get(f"amount_{idx}")
        if not amount:
            continue
        try:
            services.allocate_payment(payment, item["invoice"], amount, user=request.user)
            allocated_any = True
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, f"{item['invoice'].invoice_number}: {message}")
    if allocated_any:
        messages.success(request, "تخصیص‌ها ثبت شد و وضعیت پرداخت فاکتورها به‌روز شد.")
    return redirect("payment_detail", pk=payment.pk)


@login_required
@require_POST
def allocation_void(request, pk, alloc_pk):
    payment = get_object_or_404(Payment, pk=pk, company_id__in=user_company_ids(request.user))
    allocation = get_object_or_404(PaymentAllocation, pk=alloc_pk, payment=payment)
    try:
        services.void_allocation(
            allocation, user=request.user, reason=request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "تخصیص باطل شد.")
    return redirect("payment_detail", pk=payment.pk)


@login_required
@require_POST
def payment_reverse(request, pk):
    payment = get_object_or_404(Payment, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.reverse_payment(payment, user=request.user, reason=request.POST.get("reason", ""))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "دریافت/پرداخت برگشت خورد.")
    return redirect("payment_detail", pk=payment.pk)


def _action_date(request, field_name):
    """Parse an optional action date (clearing/bounce/return) from POST."""
    raw = request.POST.get(field_name)
    if not raw:
        return None
    try:
        return django_forms.DateField().clean(raw)
    except ValidationError:
        return "INVALID"


@login_required
def cheque_detail(request, pk):
    cheque = get_object_or_404(
        Cheque.objects.select_related("company", "payment", "payment__party", "holding_account"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    clear_form = ChequeClearForm(company=cheque.company)
    return render(
        request, "treasury/cheque_detail.html", {"cheque": cheque, "clear_form": clear_form}
    )


@login_required
@require_POST
def cheque_deposit(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.deposit_cheque(cheque, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "چک به بانک واگذار شد.")
    return redirect("cheque_detail", pk=cheque.pk)


@login_required
@require_POST
def cheque_clear(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company_id__in=user_company_ids(request.user))
    clearing_date = _action_date(request, "clearing_date")
    if clearing_date == "INVALID":
        messages.error(request, "تاریخ وصول معتبر نیست.")
        return redirect("cheque_detail", pk=cheque.pk)
    bank_account = None
    if cheque.direction == Cheque.Direction.RECEIVED:
        form = ChequeClearForm(request.POST, company=cheque.company)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect("cheque_detail", pk=cheque.pk)
        bank_account = form.cleaned_data["bank_treasury_account"]
        clearing_date = form.cleaned_data["clearing_date"] or clearing_date
    try:
        services.clear_cheque(
            cheque,
            user=request.user,
            bank_treasury_account=bank_account,
            clearing_date=clearing_date,
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "چک وصول شد.")
    return redirect("cheque_detail", pk=cheque.pk)


@login_required
@require_POST
def cheque_bounce(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company_id__in=user_company_ids(request.user))
    bounce_date = _action_date(request, "bounce_date")
    if bounce_date == "INVALID":
        messages.error(request, "تاریخ برگشت معتبر نیست.")
        return redirect("cheque_detail", pk=cheque.pk)
    try:
        services.bounce_cheque(cheque, user=request.user, bounce_date=bounce_date)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "چک برگشتی ثبت شد.")
    return redirect("cheque_detail", pk=cheque.pk)


@login_required
@require_POST
def cheque_return(request, pk):
    cheque = get_object_or_404(Cheque, pk=pk, company_id__in=user_company_ids(request.user))
    return_date = _action_date(request, "return_date")
    if return_date == "INVALID":
        messages.error(request, "تاریخ عودت معتبر نیست.")
        return redirect("cheque_detail", pk=cheque.pk)
    try:
        services.return_cheque(cheque, user=request.user, return_date=return_date)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "چک به صادرکننده عودت داده شد.")
    return redirect("cheque_detail", pk=cheque.pk)


@login_required
def open_items_view(request):
    from apps.organizations.models import Company

    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    items = []
    for company in companies:
        items.extend(reporting.open_items(company))
    return render(request, "treasury/open_items.html", {"items": items})
