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
from apps.parties.models import Party
from apps.sales import reporting, services
from apps.sales.forms import (
    SalesInvoiceForm,
    SalesInvoiceLineFormSet,
    SalesInvoicePostForm,
    SalesReturnForm,
    SalesReturnLineFormSet,
    SalesReturnPostForm,
)
from apps.sales.models import SalesInvoice, SalesReturn


@login_required
def sales_invoice_list(request):
    invoices = (
        SalesInvoice.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "customer", "warehouse")
        .order_by("-invoice_date", "-created_at")
    )
    if request.GET.get("status"):
        invoices = invoices.filter(status=request.GET["status"])
    if request.GET.get("payment_status"):
        invoices = invoices.filter(payment_status=request.GET["payment_status"])
    if request.GET.get("q"):
        q = request.GET["q"]
        invoices = invoices.filter(customer__name__icontains=q) | invoices.filter(
            customer__code__icontains=q
        )
    invoices = apply_date_range(invoices, request.GET, "invoice_date")
    page_obj, filter_query = paginate(request, invoices)
    return render(
        request,
        "sales/invoice_list.html",
        {
            "invoices": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": SalesInvoice.Status.choices,
            "payment_statuses": SalesInvoice.PaymentStatus.choices,
        },
    )


def _sales_post_requirements(invoice):
    """Which GL pickers the post form must require — mirrors the
    conditional requirements inside ``post_sales_invoice``."""
    rows, totals = services.compute_invoice_totals(invoice)
    require = set()
    if totals["subtotal"] - totals["discount_total"] > 0:
        require.add("revenue")
    if totals["tax_total"] > 0:
        require.add("tax_payable")
    if any(r["line"].product.is_stockable for r in rows):
        require.update(["cogs", "inventory"])
    return require


def _invoice_detail_context(invoice, post_form=None):
    context = {"invoice": invoice}
    if invoice.status == SalesInvoice.Status.DRAFT:
        context["post_form"] = post_form or SalesInvoicePostForm(
            company=invoice.company, require=_sales_post_requirements(invoice)
        )
    return context


@login_required
def sales_invoice_detail(request, pk):
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("company", "customer", "warehouse").prefetch_related(
            "lines__product", "returns__lines"
        ),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "sales/invoice_detail.html", _invoice_detail_context(invoice))


@login_required
def sales_invoice_create(request):
    companies, company = resolve_scoped_company(request)
    form = SalesInvoiceForm(request.POST or None, company=company, companies=companies)
    formset = SalesInvoiceLineFormSet(
        request.POST or None, prefix="lines", form_kwargs={"company": company}
    )
    if request.method == "POST" and company is not None and form.is_valid() and formset.is_valid():
        lines = [
            {
                "product": row["product"],
                "unit": row.get("unit"),
                "quantity": row["quantity"],
                "unit_price": row["unit_price"],
                "discount_amount": row.get("discount_amount") or 0,
                "tax_rate": row.get("tax_rate") or 0,
            }
            for row in formset.cleaned_data
            if row.get("product") and not row.get("DELETE")
        ]
        try:
            invoice = services.create_sales_invoice(
                company=company,
                customer=form.cleaned_data["customer"],
                invoice_number=form.cleaned_data["invoice_number"],
                invoice_date=form.cleaned_data["invoice_date"],
                warehouse=form.cleaned_data["warehouse"],
                description=form.cleaned_data["description"],
                lines=lines,
            )
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, _("فاکتور فروش به‌صورت پیش‌نویس ایجاد شد."))
            return redirect("sales_invoice_detail", pk=invoice.pk)
    return render(
        request,
        "sales/invoice_form.html",
        {"form": form, "lines": formset, "companies": companies, "company": company},
    )


@login_required
@require_POST
def sales_invoice_post(request, pk):
    invoice = get_object_or_404(SalesInvoice, pk=pk, company_id__in=user_company_ids(request.user))
    form = SalesInvoicePostForm(
        request.POST, company=invoice.company, require=_sales_post_requirements(invoice)
    )
    if form.is_valid():
        gl_accounts = {k: v for k, v in form.cleaned_data.items() if v is not None}
        try:
            services.post_sales_invoice(invoice, user=request.user, gl_accounts=gl_accounts)
        except ValidationError as exc:
            add_service_errors(form, exc)
        else:
            messages.success(request, _("فاکتور فروش ثبت نهایی شد."))
            return redirect("sales_invoice_detail", pk=invoice.pk)
    invoice.refresh_from_db()
    return render(
        request, "sales/invoice_detail.html", _invoice_detail_context(invoice, post_form=form)
    )


@login_required
@require_POST
def sales_invoice_reverse(request, pk):
    invoice = get_object_or_404(SalesInvoice, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.reverse_sales_invoice(
            invoice, user=request.user, reason=request.POST.get("reason", "")
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("فاکتور فروش برگشت خورد."))
    return redirect("sales_invoice_detail", pk=invoice.pk)


@login_required
def sales_return_create(request, pk):
    invoice = get_object_or_404(
        SalesInvoice.objects.prefetch_related("lines__product", "lines__unit"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    if invoice.status != SalesInvoice.Status.POSTED:
        messages.error(request, _("برگشت فقط برای فاکتور ثبت‌نهایی‌شده ممکن است."))
        return redirect("sales_invoice_detail", pk=invoice.pk)
    invoice_lines = list(invoice.lines.all())
    initial = [{"invoice_line": line.pk, "quantity": 0} for line in invoice_lines]
    form = SalesReturnForm(request.POST or None)
    formset = SalesReturnLineFormSet(
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
            ret = services.create_sales_return(
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
            messages.success(request, _("برگشت فروش به‌صورت پیش‌نویس ایجاد شد."))
            return redirect("sales_return_detail", pk=ret.pk)
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
        "sales/return_form.html",
        {"form": form, "lines": formset, "line_rows": line_rows, "invoice": invoice},
    )


def _return_detail_context(ret, post_form=None):
    context = {"return": ret, "invoice": ret.original_invoice}
    if ret.status == SalesReturn.Status.DRAFT and ret.original_invoice.journal_entry_id:
        context["post_form"] = post_form or SalesReturnPostForm(company=ret.company)
        context["needs_gl"] = True
    return context


@login_required
def sales_return_detail(request, pk):
    ret = get_object_or_404(
        SalesReturn.objects.select_related(
            "company", "original_invoice", "original_invoice__customer"
        ).prefetch_related("lines__product", "lines__unit"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "sales/return_detail.html", _return_detail_context(ret))


@login_required
@require_POST
def sales_return_post(request, pk):
    ret = get_object_or_404(SalesReturn, pk=pk, company_id__in=user_company_ids(request.user))
    post_form = None
    gl_accounts = None
    if ret.original_invoice.journal_entry_id:
        post_form = SalesReturnPostForm(request.POST, company=ret.company)
        if not post_form.is_valid():
            return render(
                request,
                "sales/return_detail.html",
                _return_detail_context(ret, post_form=post_form),
            )
        gl_accounts = {k: v for k, v in post_form.cleaned_data.items() if v is not None}
    try:
        services.post_sales_return(ret, user=request.user, gl_accounts=gl_accounts)
    except ValidationError as exc:
        if post_form is not None:
            add_service_errors(post_form, exc)
            return render(
                request,
                "sales/return_detail.html",
                _return_detail_context(ret, post_form=post_form),
            )
        messages.error(request, " ".join(exc.messages))
        return redirect("sales_return_detail", pk=ret.pk)
    messages.success(request, _("برگشت فروش ثبت نهایی شد."))
    return redirect("sales_return_detail", pk=ret.pk)


@login_required
@require_POST
def sales_return_reverse(request, pk):
    ret = get_object_or_404(SalesReturn, pk=pk, company_id__in=user_company_ids(request.user))
    try:
        services.reverse_sales_return(ret, user=request.user, reason=request.POST.get("reason", ""))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("برگشت فروش برگشت خورد."))
    return redirect("sales_return_detail", pk=ret.pk)


@login_required
def accounts_receivable_view(request):
    """AR summary: pick a company and its receivables account; balances
    are the GL subledger (party-tagged journal lines), not invoice sums."""
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
            rows = reporting.accounts_receivable(company, account)
    return render(
        request,
        "sales/ar_summary.html",
        {
            "companies": companies,
            "company": company,
            "accounts": accounts,
            "account": account,
            "rows": rows,
        },
    )


@login_required
def customer_statement_view(request):
    """Customer statement: pick company, receivables account and customer."""
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    company = None
    account = None
    statement = None
    accounts = Account.objects.none()
    customers = Party.objects.none()
    company_id = request.GET.get("company")
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
        accounts = Account.objects.filter(company=company).order_by("code")
        customers = reporting.customers(company)
        account_id = request.GET.get("account")
        customer_id = request.GET.get("customer")
        if account_id and customer_id:
            account = get_object_or_404(accounts, pk=account_id)
            customer = get_object_or_404(customers, pk=customer_id)
            statement = reporting.customer_statement(company, account, customer)
    return render(
        request,
        "sales/customer_statement.html",
        {
            "companies": companies,
            "company": company,
            "accounts": accounts,
            "customers": customers,
            "account": account,
            "statement": statement,
        },
    )


@login_required
def sales_invoice_print(request, pk):
    """Print-friendly sales invoice (Sprint 08): same membership-scoped
    queryset as the detail view, rendered on the print base template —
    the browser's print-to-PDF is the PDF path (ADR-032)."""
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("company", "customer", "warehouse").prefetch_related(
            "lines__product", "lines__unit"
        ),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "sales/invoice_print.html", {"invoice": invoice})


@login_required
def customer_statement_print(request):
    """Print-friendly customer statement: identical selection logic and
    data to ``customer_statement_view``, on the print base template."""
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    statement = None
    company_id = request.GET.get("company")
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
        accounts = Account.objects.filter(company=company)
        customers = reporting.customers(company)
        account_id = request.GET.get("account")
        customer_id = request.GET.get("customer")
        if account_id and customer_id:
            account = get_object_or_404(accounts, pk=account_id)
            customer = get_object_or_404(customers, pk=customer_id)
            statement = reporting.customer_statement(company, account, customer)
    if statement is None:
        from django.http import Http404

        raise Http404("Select a company, account and customer first.")
    return render(request, "sales/customer_statement_print.html", {"statement": statement})
