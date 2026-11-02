from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.accounting.models import Account
from apps.core.access import user_company_ids
from apps.core.pagination import apply_date_range, paginate
from apps.organizations.models import Company
from apps.parties.models import Party
from apps.sales import reporting
from apps.sales.models import SalesInvoice


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


@login_required
def sales_invoice_detail(request, pk):
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("company", "customer", "warehouse").prefetch_related(
            "lines__product", "returns__lines"
        ),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "sales/invoice_detail.html", {"invoice": invoice})


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
