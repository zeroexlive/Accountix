from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounting.models import Account
from apps.core.access import resolve_scoped_company, user_company_ids
from apps.core.forms import add_service_errors
from apps.core.pagination import apply_date_range, paginate
from apps.organizations.models import Company
from apps.purchases import reporting, services
from apps.purchases.forms import (
    PurchaseInvoiceForm,
    PurchaseInvoiceLineFormSet,
    PurchaseInvoicePostForm,
    PurchaseReturnForm,
    PurchaseReturnLineFormSet,
    PurchaseReturnPostForm,
)
from apps.purchases.models import PurchaseInvoice, PurchaseReturn


@login_required
def purchase_invoice_list(request):
    invoices = (
        PurchaseInvoice.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "supplier", "warehouse")
        .order_by("-invoice_date", "-created_at")
    )
    if request.GET.get("status"):
        invoices = invoices.filter(status=request.GET["status"])
    if request.GET.get("payment_status"):
        invoices = invoices.filter(payment_status=request.GET["payment_status"])
    if request.GET.get("q"):
        q = request.GET["q"]
        invoices = invoices.filter(supplier__name__icontains=q) | invoices.filter(
            supplier__code__icontains=q
        )
    invoices = apply_date_range(invoices, request.GET, "invoice_date")
    page_obj, filter_query = paginate(request, invoices)
    return render(
        request,
        "purchases/invoice_list.html",
        {
            "invoices": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": PurchaseInvoice.Status.choices,
            "payment_statuses": PurchaseInvoice.PaymentStatus.choices,
        },
    )


def _purchase_post_requirements(invoice):
    """Which GL pickers the post form must require for this invoice —
    mirrors the conditional requirements inside the posting service."""
    rows, totals = services.compute_invoice_totals(invoice)
    require = set()
    if any(r["line"].product.is_stockable and r["net"] > 0 for r in rows):
        require.add("inventory")
    if any(not r["line"].product.is_stockable and r["net"] > 0 for r in rows):
        require.add("expense")
    if totals["tax_total"] > 0:
        require.add("tax")
    return require


def _invoice_detail_context(invoice, post_form=None):
    context = {"invoice": invoice}
    if invoice.status == PurchaseInvoice.Status.DRAFT:
        context["post_form"] = post_form or PurchaseInvoicePostForm(
            company=invoice.company, require=_purchase_post_requirements(invoice)
        )
    return context


@login_required
def purchase_invoice_detail(request, pk):
    invoice = get_object_or_404(
        PurchaseInvoice.objects.select_related("company", "supplier", "warehouse").prefetch_related(
            "lines__product", "returns__lines"
        ),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "purchases/invoice_detail.html", _invoice_detail_context(invoice))


@login_required
def purchase_invoice_create(request):
    companies, company = resolve_scoped_company(request)
    form = PurchaseInvoiceForm(request.POST or None, company=company, companies=companies)
    formset = PurchaseInvoiceLineFormSet(
        request.POST or None, prefix="lines", form_kwargs={"company": company}
    )
    if request.method == "POST" and company is not None and form.is_valid() and formset.is_valid():
        lines = [
            {
                "product": row["product"],
                "unit": row.get("unit"),
                "quantity": row["quantity"],
                "unit_cost": row["unit_cost"],
                "discount_amount": row.get("discount_amount") or 0,
                "tax_rate": row.get("tax_rate") or 0,
            }
            for row in formset.cleaned_data
            if row.get("product") and not row.get("DELETE")
        ]
        try:
            invoice = services.create_purchase_invoice(
                company=company,
                supplier=form.cleaned_data["supplier"],
                invoice_number=form.cleaned_data["invoice_number"],
                invoice_date=form.cleaned_data["invoice_date"],
                warehouse=form.cleaned_data["warehouse"],
                description=form.cleaned_data["description"],
                lines=lines,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, _("فاکتور خرید به‌صورت پیش‌نویس ایجاد شد."))
            return redirect("purchase_invoice_detail", pk=invoice.pk)
    return render(
        request,
        "purchases/invoice_form.html",
        {"form": form, "lines": formset, "companies": companies, "company": company},
    )


@login_required
@require_POST
def purchase_invoice_post(request, pk):
    invoice = get_object_or_404(
        PurchaseInvoice, pk=pk, company_id__in=user_company_ids(request.user)
    )
    form = PurchaseInvoicePostForm(
        request.POST, company=invoice.company, require=_purchase_post_requirements(invoice)
    )
    if form.is_valid():
        gl_accounts = {k: v for k, v in form.cleaned_data.items() if v is not None}
        try:
            services.post_purchase_invoice(invoice, user=request.user, gl_accounts=gl_accounts)
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, _("فاکتور خرید ثبت نهایی شد."))
            return redirect("purchase_invoice_detail", pk=invoice.pk)
    invoice.refresh_from_db()
    return render(
        request, "purchases/invoice_detail.html", _invoice_detail_context(invoice, post_form=form)
    )


@login_required
@require_POST
def purchase_invoice_reverse(request, pk):
    invoice = get_object_or_404(
        PurchaseInvoice, pk=pk, company_id__in=user_company_ids(request.user)
    )
    try:
        services.reverse_purchase_invoice(
            invoice, user=request.user, reason=request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("فاکتور خرید برگشت خورد."))
    return redirect("purchase_invoice_detail", pk=invoice.pk)


@login_required
def purchase_return_create(request, pk):
    invoice = get_object_or_404(
        PurchaseInvoice.objects.prefetch_related("lines__product", "lines__unit"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    if invoice.status != PurchaseInvoice.Status.POSTED:
        messages.error(request, _("برگشت فقط برای فاکتور ثبت‌نهایی‌شده ممکن است."))
        return redirect("purchase_invoice_detail", pk=invoice.pk)
    invoice_lines = list(invoice.lines.all())
    initial = [{"invoice_line": line.pk, "quantity": 0} for line in invoice_lines]
    form = PurchaseReturnForm(request.POST or None)
    formset = PurchaseReturnLineFormSet(
        request.POST or None,
        prefix="lines",
        initial=initial,
        form_kwargs={"invoice": invoice},
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        lines = [
            {"invoice_line": row["invoice_line"], "quantity": row["quantity"]}
            for row in formset.cleaned_data
            if row.get("invoice_line") and row.get("quantity")
        ]
        try:
            ret = services.create_purchase_return(
                company=invoice.company,
                original_invoice=invoice,
                return_number=form.cleaned_data["return_number"],
                return_date=form.cleaned_data["return_date"],
                description=form.cleaned_data["description"],
                lines=lines,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, _("برگشت خرید به‌صورت پیش‌نویس ایجاد شد."))
            return redirect("purchase_return_detail", pk=ret.pk)
    line_rows = [
        {
            "form": row_form,
            "invoice_line": line,
            "returned": services.returned_quantity(line),
            "remaining": line.quantity - services.returned_quantity(line),
        }
        for row_form, line in zip(formset.forms, invoice_lines, strict=True)
    ]
    return render(
        request,
        "purchases/return_form.html",
        {"form": form, "lines": formset, "line_rows": line_rows, "invoice": invoice},
    )


def _return_detail_context(ret, post_form=None):
    context = {"return": ret, "invoice": ret.original_invoice}
    if ret.status == PurchaseReturn.Status.DRAFT and ret.original_invoice.journal_entry_id:
        context["post_form"] = post_form or PurchaseReturnPostForm(company=ret.company)
        context["needs_gl"] = True
    return context


@login_required
def purchase_return_detail(request, pk):
    ret = get_object_or_404(
        PurchaseReturn.objects.select_related(
            "company", "original_invoice", "original_invoice__supplier"
        ).prefetch_related("lines__product", "lines__unit"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "purchases/return_detail.html", _return_detail_context(ret))


@login_required
@require_POST
def purchase_return_post(request, pk):
    ret = get_object_or_404(PurchaseReturn, pk=pk, company_id__in=user_company_ids(request.user))
    post_form = None
    gl_accounts = None
    if ret.original_invoice.journal_entry_id:
        post_form = PurchaseReturnPostForm(request.POST, company=ret.company)
        if not post_form.is_valid():
            return render(
                request,
                "purchases/return_detail.html",
                _return_detail_context(ret, post_form=post_form),
            )
        gl_accounts = {k: v for k, v in post_form.cleaned_data.items() if v is not None}
    try:
        services.post_purchase_return(ret, user=request.user, gl_accounts=gl_accounts)
    except ValidationError as exc:
        if post_form is not None:
            add_service_errors(post_form, exc)
            return render(
                request,
                "purchases/return_detail.html",
                _return_detail_context(ret, post_form=post_form),
            )
        messages.error(request, " ".join(exc.messages))
        return redirect("purchase_return_detail", pk=ret.pk)
    messages.success(request, _("برگشت خرید ثبت نهایی شد."))
    return redirect("purchase_return_detail", pk=ret.pk)


@login_required
@require_POST
def purchase_return_reverse(request, pk):
    ret = get_object_or_404(PurchaseReturn, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.reverse_purchase_return(
            ret, user=request.user, reason=request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("برگشت خرید برگشت خورد."))
    return redirect("purchase_return_detail", pk=ret.pk)


@login_required
def accounts_payable_view(request):
    """AP summary: pick a company and its payables account; balances are
    the GL subledger (party-tagged journal lines), not invoice sums."""
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    company = None
    account = None
    rows = None
    accounts = Account.objects.none()
    company_id = request.GET.get("company")
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
        accounts = Account.objects.filter(company=company).order_by("code")
        account_id = request.GET.get("account")
        if account_id:
            account = get_object_or_404(accounts, pk=account_id)
            rows = reporting.accounts_payable(company, account)
    return render(
        request,
        "purchases/ap_summary.html",
        {
            "companies": companies,
            "company": company,
            "accounts": accounts,
            "account": account,
            "rows": rows,
        },
    )


@login_required
def purchase_invoice_print(request, pk):
    """Print-friendly purchase invoice (Sprint 08), print base template."""
    invoice = get_object_or_404(
        PurchaseInvoice.objects.select_related("company", "supplier", "warehouse").prefetch_related(
            "lines__product", "lines__unit"
        ),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "purchases/invoice_print.html", {"invoice": invoice})


@login_required
def supplier_statement_print(request):
    """Print-friendly supplier statement: the GL subledger balance
    (ADR-015) plus the supplier's posted purchase invoices."""
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    company_id = request.GET.get("company")
    if not company_id or not request.GET.get("account") or not request.GET.get("supplier"):
        from django.http import Http404

        raise Http404("Select a company, account and supplier first.")
    company = get_object_or_404(companies, pk=company_id)
    account = get_object_or_404(Account.objects.filter(company=company), pk=request.GET["account"])
    supplier = get_object_or_404(reporting.suppliers(company), pk=request.GET["supplier"])
    statement = {
        "supplier": supplier,
        "balance": reporting.supplier_balance(company, account, supplier),
        "invoices": reporting.supplier_purchase_history(company, supplier),
    }
    return render(request, "purchases/supplier_statement_print.html", {"statement": statement})
