from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.accounting.models import Account
from apps.core.access import user_company_ids
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
    return render(request, "sales/invoice_list.html", {"invoices": invoices})


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
