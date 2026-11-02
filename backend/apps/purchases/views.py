from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.accounting.models import Account
from apps.core.access import user_company_ids
from apps.core.pagination import apply_date_range, paginate
from apps.organizations.models import Company
from apps.purchases import reporting
from apps.purchases.models import PurchaseInvoice


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


@login_required
def purchase_invoice_detail(request, pk):
    invoice = get_object_or_404(
        PurchaseInvoice.objects.select_related("company", "supplier", "warehouse").prefetch_related(
            "lines__product", "returns__lines"
        ),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "purchases/invoice_detail.html", {"invoice": invoice})


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
