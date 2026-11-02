"""Purchasing reporting.

Supplier balances are a **GL subledger** (ADR-015): they are derived only
from journal lines on the payables account that carry a party tag, never
from invoice totals. Purchase invoices tag their payables line with the
supplier at posting; purchase returns tag their payables debit the same
way; invoice reversals keep the tag on the swapped lines — so the sum of
all supplier balances reconciles with the payables account balance in
the trial balance (asserted by test). The one honest caveat: a *manual*
journal line on the payables account without a party tag is invisible
to this subledger by construction.
"""

from decimal import Decimal

from django.db.models import Sum

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import JournalLine
from apps.parties.models import Party
from apps.purchases.models import PurchaseInvoice, PurchaseInvoiceLine

ZERO = Decimal("0")


def supplier_balance(company, ap_account, supplier) -> Decimal:
    """Amount owed to one supplier: credit-minus-debit on the tagged lines
    (positive = we owe the supplier)."""
    return -acct_reporting.party_account_balance(company, ap_account, supplier)


def accounts_payable(company, ap_account):
    """One row per supplier with a non-zero balance on the payables account."""
    grouped = (
        JournalLine.objects.filter(
            entry__company=company,
            entry__status__in=acct_reporting.LEDGER_STATUSES,
            account=ap_account,
            party__isnull=False,
        )
        .values("party_id", "party__code", "party__name")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("party__code")
    )
    rows = []
    for row in grouped:
        balance = (row["credit"] or ZERO) - (row["debit"] or ZERO)
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


def ap_total(company, ap_account) -> Decimal:
    """Sum of all supplier subledger balances (reconciles with the GL)."""
    return sum((row["balance"] for row in accounts_payable(company, ap_account)), ZERO)


def supplier_purchase_history(company, supplier):
    """Posted purchase invoices of one supplier, newest first."""
    return list(
        PurchaseInvoice.objects.filter(company=company, supplier=supplier, status="POSTED")
        .select_related("warehouse")
        .order_by("-invoice_date", "-created_at")
    )


def product_purchase_history(company, product):
    """Posted purchase invoice lines for one product, newest first."""
    return list(
        PurchaseInvoiceLine.objects.filter(
            invoice__company=company, invoice__status="POSTED", product=product
        )
        .select_related("invoice", "invoice__supplier")
        .order_by("-invoice__invoice_date", "-created_at")
    )


def suppliers(company):
    return Party.objects.filter(company=company, kind__in=["SUPPLIER", "BOTH"], is_active=True)
