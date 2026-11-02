"""Dashboard aggregation (Sprint 08) — a pure presentation layer.

Every figure is computed at call time from the owning apps' reporting
services (accounting / inventory / treasury), which derive from journal
lines and stock movements. Nothing is stored, cached in a table, or
recomputed with new business logic here (ADR-031).

Two figures need a note:

- ``ar_total`` / ``ap_total`` are party-subledger totals in the ADR-015
  sense, aggregated across accounts: the receivables total is the sum,
  per party, of debit−credit over party-tagged journal lines on
  ASSET-type accounts; payables mirror that on LIABILITY-type accounts
  (credit−debit). With a single AR/AP control account — the normal
  chart — they equal ``sales.reporting.ar_total`` /
  ``purchases.reporting.ap_total`` for that account exactly, and the
  Sprint 08 tests assert that equality.
- The income-statement summary passes ``cogs_accounts=[]``: cost of
  goods sold is a caller-designated *subset* of expense accounts
  (ADR-030), so with no designation the net result is identical —
  designated COGS expenses simply stay inside the expenses total — and
  no gross-profit figure is produced. Gross profit is shown only on
  the income-statement page, where the user designates the accounts.
"""

from decimal import Decimal

from django.db.models import Sum

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import JournalLine
from apps.inventory import reporting as inv_reporting
from apps.organizations.models import FiscalPeriod
from apps.purchases.models import PurchaseInvoice
from apps.sales.models import SalesInvoice
from apps.treasury import reporting as treasury_reporting
from apps.treasury.models import TreasuryAccount

ZERO = Decimal("0")


def resolve_period(company, period=None):
    """The dashboard period: the caller's, else the latest OPEN period."""
    if period is not None:
        return period
    return (
        FiscalPeriod.objects.filter(company=company, status=FiscalPeriod.Status.OPEN)
        .order_by("-start_date")
        .first()
    )


def _party_tagged_total(company, *, account_type, credit_normal) -> Decimal:
    """Sum over parties of the signed balance of party-tagged journal
    lines on accounts of one type (the ADR-015 subledger, aggregated)."""
    grouped = (
        JournalLine.objects.filter(
            entry__company=company,
            entry__status__in=acct_reporting.LEDGER_STATUSES,
            account__account_type=account_type,
            party__isnull=False,
        )
        .values("party_id")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
    )
    total = ZERO
    for row in grouped:
        debit = row["debit"] or ZERO
        credit = row["credit"] or ZERO
        total += (credit - debit) if credit_normal else (debit - credit)
    return total


def _posted_invoice_total(model, company, period):
    qs = model.objects.filter(company=company, status="POSTED")
    if period is not None:
        qs = qs.filter(invoice_date__gte=period.start_date, invoice_date__lte=period.end_date)
    return qs.aggregate(total=Sum("grand_total"))["total"] or ZERO


def dashboard_data(company, *, period=None, recent_limit=10):
    """All dashboard figures for one company (see module docstring)."""
    period = resolve_period(company, period)

    treasury_rows = []
    cash_total = ZERO
    bank_total = ZERO
    for account in TreasuryAccount.objects.filter(company=company, is_active=True).order_by(
        "kind", "name"
    ):
        balance = treasury_reporting.treasury_account_balance(company, account)
        treasury_rows.append({"account": account, "balance": balance})
        if account.kind == TreasuryAccount.Kind.CASH:
            cash_total += balance
        else:
            bank_total += balance

    statement = acct_reporting.income_statement(company, fiscal_period=period, cogs_accounts=[])

    cheques = list(treasury_reporting.outstanding_cheques(company))
    open_items = treasury_reporting.open_items(company)
    low_stock_rows = inv_reporting.low_stock(company)

    from apps.accounting.models import JournalEntry

    return {
        "company": company,
        "period": period,
        "treasury_rows": treasury_rows,
        "cash_total": cash_total,
        "bank_total": bank_total,
        "treasury_total": cash_total + bank_total,
        "ar_total": _party_tagged_total(company, account_type="ASSET", credit_normal=False),
        "ap_total": _party_tagged_total(company, account_type="LIABILITY", credit_normal=True),
        "open_receivable_total": sum(
            (row["outstanding"] for row in open_items if row["kind"] == "SALES"), ZERO
        ),
        "open_payable_total": sum(
            (row["outstanding"] for row in open_items if row["kind"] == "PURCHASE"), ZERO
        ),
        "inventory_valuation": inv_reporting.inventory_valuation(company),
        "sales_total": _posted_invoice_total(SalesInvoice, company, period),
        "purchase_total": _posted_invoice_total(PurchaseInvoice, company, period),
        "revenue_total": statement["revenue_total"],
        "expenses_total": statement["expenses_total"] + statement["cogs_total"],
        "net_income": statement["net_income"],
        "income_statement": statement,
        "low_stock_rows": low_stock_rows,
        "low_stock_count": len(low_stock_rows),
        "outstanding_cheques_count": len(cheques),
        "outstanding_cheques_amount": sum((c.amount for c in cheques), ZERO),
        "outstanding_cheques": cheques,
        "recent_entries": list(
            JournalEntry.objects.filter(company=company).order_by("-entry_date", "-created_at")[
                :recent_limit
            ]
        ),
        "recent_sales": list(
            SalesInvoice.objects.filter(company=company)
            .select_related("customer")
            .order_by("-invoice_date", "-created_at")[:recent_limit]
        ),
        "recent_purchases": list(
            PurchaseInvoice.objects.filter(company=company)
            .select_related("supplier")
            .order_by("-invoice_date", "-created_at")[:recent_limit]
        ),
    }
