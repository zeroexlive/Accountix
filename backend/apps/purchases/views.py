from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.accounting.models import Account
from apps.core.access import user_company_ids
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
    return render(request, "purchases/invoice_list.html", {"invoices": invoices})


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
