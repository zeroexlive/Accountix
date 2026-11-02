"""Sales reporting.

Customer balances are a **GL subledger** (ADR-015): they are derived only
from journal lines on the receivables account that carry a party tag,
never from invoice totals. Sales invoices tag their receivables line with
the customer at posting; sales returns tag their receivables credit the
same way; invoice reversals keep the tag on the swapped lines — so the
sum of all customer balances reconciles with the receivables account
balance in the trial balance (asserted by test, including the MVP
end-to-end test). As in purchasing, a *manual* journal line on the
receivables account without a party tag is invisible to this subledger.
"""

from decimal import Decimal

from django.db.models import Sum

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import JournalLine
from apps.parties.models import Party
from apps.sales.models import SalesInvoice, SalesInvoiceLine

ZERO = Decimal("0")


def customer_balance(company, ar_account, customer) -> Decimal:
    """Amount the customer owes: debit-minus-credit on the tagged lines
    (the receivables account is debit-normal, so no sign flip — unlike
    the payables subledger)."""
    return acct_reporting.party_account_balance(company, ar_account, customer)


def accounts_receivable(company, ar_account):
    """One row per customer with a non-zero balance on the receivables account."""
    grouped = (
        JournalLine.objects.filter(
            entry__company=company,
            entry__status__in=acct_reporting.LEDGER_STATUSES,
            account=ar_account,
            party__isnull=False,
        )
        .values("party_id", "party__code", "party__name")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("party__code")
    )
    rows = []
    for row in grouped:
        balance = (row["debit"] or ZERO) - (row["credit"] or ZERO)
        if balance != ZERO:
            rows.append(
                {
                    "party_id": row["party_id"],
                    "code": row["party__code"],
                    "name": row["party__name"],
                    "balance": balance,
                }
            )
    return rows


def ar_total(company, ar_account) -> Decimal:
    """Sum of all customer subledger balances (reconciles with the GL)."""
    return sum((row["balance"] for row in accounts_receivable(company, ar_account)), ZERO)


def customer_sales_history(company, customer):
    """Posted sales invoices of one customer, newest first."""
    return list(
        SalesInvoice.objects.filter(company=company, customer=customer, status="POSTED")
        .select_related("warehouse")
        .order_by("-invoice_date", "-created_at")
    )


def customer_statement(company, ar_account, customer):
    """Statement data for one customer: invoices, returns, GL balance.

    The balance is the subledger figure (tagged journal lines); the
    invoice/return lists are the operational documents behind it.
    """
    from apps.sales.models import SalesReturn

    return {
        "customer": customer,
        "balance": customer_balance(company, ar_account, customer),
        "invoices": customer_sales_history(company, customer),
        "returns": list(
            SalesReturn.objects.filter(
                company=company, original_invoice__customer=customer, status="POSTED"
            )
            .select_related("original_invoice")
            .order_by("-return_date", "-created_at")
        ),
    }


def product_sales_history(company, product):
    """Posted sales invoice lines for one product, newest first."""
    return list(
        SalesInvoiceLine.objects.filter(
            invoice__company=company, invoice__status="POSTED", product=product
        )
        .select_related("invoice", "invoice__customer")
        .order_by("-invoice__invoice_date", "-created_at")
    )


def customers(company):
    return Party.objects.filter(company=company, kind__in=["CUSTOMER", "BOTH"], is_active=True)
