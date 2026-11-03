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


# ---------------------------------------------------------------------------
# Sprint 11 — derived display helpers for the redesigned dashboard.
# Both helpers are pure derivations over the services above / the owning
# apps' reporting (ADR-038): nothing is stored, and the Sprint 11 tests
# pin their sums equal to ``income_statement`` over the same range.
# ---------------------------------------------------------------------------


def previous_period(company, period):
    """The fiscal period immediately before ``period`` (by start date),
    or None when there is no earlier period or no period at all."""
    if period is None:
        return None
    return (
        FiscalPeriod.objects.filter(company=company, start_date__lt=period.start_date)
        .exclude(pk=period.pk)
        .order_by("-start_date", "-end_date")
        .first()
    )


def _delta_pct(current, previous):
    """Percentage change of ``current`` vs ``previous`` (1 decimal).

    Returns None — the badge is omitted, never fabricated — when there
    is no previous period or the previous value is zero (division by
    zero would make any percentage meaningless)."""
    if previous is None or previous == ZERO:
        return None
    return ((current - previous) * Decimal("100") / previous).quantize(Decimal("0.1"))


def _percent(part, whole):
    """``part`` as a percentage of ``whole`` (1 decimal), or None when
    the denominator is zero — the UI renders an honest empty state."""
    if whole == ZERO:
        return None
    return (part * Decimal("100") / whole).quantize(Decimal("0.1"))


def period_series(company, fiscal_year):
    """Revenue vs expenses per fiscal period of one fiscal year.

    Each period's figures come from ``income_statement`` with
    ``cogs_accounts=[]`` — the dashboard convention (ADR-030/031):
    designated-COGS expenses stay inside the expenses total, closing
    entries are excluded, so the series sums equal the income
    statement over the fiscal year's whole date range. Bar heights
    are precomputed as percentages of the largest bar so the template
    stays arithmetic-free."""
    if fiscal_year is None:
        return []
    rows = []
    periods = FiscalPeriod.objects.filter(company=company, fiscal_year=fiscal_year).order_by(
        "start_date"
    )
    for period in periods:
        statement = acct_reporting.income_statement(company, fiscal_period=period, cogs_accounts=[])
        rows.append(
            {
                "period": period,
                "label": period.name,
                "revenue": statement["revenue_total"],
                "expenses": statement["expenses_total"] + statement["cogs_total"],
            }
        )
    peak = max([row["revenue"] for row in rows] + [row["expenses"] for row in rows] + [ZERO])
    for row in rows:
        if peak > ZERO:
            row["revenue_height"] = float(row["revenue"] * Decimal("100") / peak)
            row["expenses_height"] = float(row["expenses"] * Decimal("100") / peak)
        else:
            row["revenue_height"] = 0.0
            row["expenses_height"] = 0.0
    return rows


def _performance(company, *, open_receivable_total, open_payable_total, low_stock_count):
    """Progress-bar rows for the dashboard "performance" panel.

    Every percentage is a share derived from existing reports; a zero
    denominator yields ``percent=None`` so the panel shows an empty
    state for that row instead of a fabricated 0%."""
    from apps.treasury.models import Cheque

    sales_all = _posted_invoice_total(SalesInvoice, company, None)
    purchases_all = _posted_invoice_total(PurchaseInvoice, company, None)
    sales_collected = sales_all - open_receivable_total
    purchases_settled = purchases_all - open_payable_total

    outstanding_received = treasury_reporting.outstanding_cheques(
        company, direction=Cheque.Direction.RECEIVED
    )
    outstanding_received_amount = sum((c.amount for c in outstanding_received), ZERO)
    cleared_received_amount = (
        Cheque.objects.filter(
            company=company,
            direction=Cheque.Direction.RECEIVED,
            status=Cheque.Status.CLEARED,
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    cheques_base = cleared_received_amount + outstanding_received_amount

    stocked_product_ids = {
        row["product_id"] for row in inv_reporting.stock_balances(company) if row["quantity"] > ZERO
    }
    products_with_stock = len(stocked_product_ids)
    if products_with_stock:
        health = _percent(
            Decimal(products_with_stock - low_stock_count), Decimal(products_with_stock)
        )
        if health is not None and health < ZERO:
            health = ZERO
    else:
        health = None

    return [
        {
            "key": "collections",
            "label": "وصول مطالبات از مشتریان",
            "percent": _percent(sales_collected, sales_all),
            "caption": f"{sales_collected} از {sales_all} فاکتورهای فروش وصول شده است.",
            "empty": "هنوز فاکتور فروش ثبت‌شده‌ای وجود ندارد.",
        },
        {
            "key": "settlements",
            "label": "تسویه بدهی به تأمین‌کنندگان",
            "percent": _percent(purchases_settled, purchases_all),
            "caption": f"{purchases_settled} از {purchases_all} فاکتورهای خرید تسویه شده است.",
            "empty": "هنوز فاکتور خرید ثبت‌شده‌ای وجود ندارد.",
        },
        {
            "key": "cheques",
            "label": "چک‌های دریافتی وصول‌شده (بر اساس مبلغ)",
            "percent": _percent(cleared_received_amount, cheques_base),
            "caption": f"{cleared_received_amount} وصول شده و {outstanding_received_amount} در انتظار وصول است.",
            "empty": "هنوز چک دریافتی ثبت نشده است.",
        },
        {
            "key": "inventory_health",
            "label": "سلامت موجودی انبار",
            "percent": health,
            "caption": f"{low_stock_count} کالای کم‌موجودی از {products_with_stock} کالای دارای موجودی.",
            "empty": "هنوز کالای دارای موجودی ثبت نشده است.",
        },
    ]


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

    open_receivable_total = sum(
        (row["outstanding"] for row in open_items if row["kind"] == "SALES"), ZERO
    )
    open_payable_total = sum(
        (row["outstanding"] for row in open_items if row["kind"] == "PURCHASE"), ZERO
    )
    sales_total = _posted_invoice_total(SalesInvoice, company, period)
    purchase_total = _posted_invoice_total(PurchaseInvoice, company, period)

    # Sprint 11: KPI deltas vs the previous period + chart series +
    # performance panel — all derived here, nothing stored (ADR-038).
    prev = previous_period(company, period)
    if prev is not None:
        prev_statement = acct_reporting.income_statement(
            company, fiscal_period=prev, cogs_accounts=[]
        )
        prev_revenue = prev_statement["revenue_total"]
        prev_sales = _posted_invoice_total(SalesInvoice, company, prev)
        prev_purchases = _posted_invoice_total(PurchaseInvoice, company, prev)
    else:
        prev_revenue = prev_sales = prev_purchases = None
    kpis = {
        "revenue": {
            "current": statement["revenue_total"],
            "previous": prev_revenue,
            "delta_pct": _delta_pct(statement["revenue_total"], prev_revenue),
        },
        "sales": {
            "current": sales_total,
            "previous": prev_sales,
            "delta_pct": _delta_pct(sales_total, prev_sales),
        },
        "purchases": {
            "current": purchase_total,
            "previous": prev_purchases,
            "delta_pct": _delta_pct(purchase_total, prev_purchases),
        },
    }
    fiscal_year = period.fiscal_year if period is not None else None
    series = period_series(company, fiscal_year)

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
        "open_receivable_total": open_receivable_total,
        "open_payable_total": open_payable_total,
        "inventory_valuation": inv_reporting.inventory_valuation(company),
        "sales_total": sales_total,
        "purchase_total": purchase_total,
        "previous_period": prev,
        "kpis": kpis,
        "fiscal_year": fiscal_year,
        "period_series": series,
        "series_revenue_total": sum((row["revenue"] for row in series), ZERO),
        "series_expenses_total": sum((row["expenses"] for row in series), ZERO),
        "performance": _performance(
            company,
            open_receivable_total=open_receivable_total,
            open_payable_total=open_payable_total,
            low_stock_count=len(low_stock_rows),
        ),
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
