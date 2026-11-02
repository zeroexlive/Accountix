"""Reporting queries — derived ONLY from journal lines of entries in the
ledger (POSTED and REVERSED entries; a REVERSED original is offset by its
POSTED reversal entry, so including both keeps the ledger net-correct).
No stored balance fields exist anywhere in Accountix.
"""

from decimal import Decimal

from django.db.models import Sum

from apps.accounting.models import JournalEntry, JournalLine

ZERO = Decimal("0")
LEDGER_STATUSES = [JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED]


def _lines(company, *, fiscal_period=None, account=None, date_from=None, date_to=None, party=None):
    qs = JournalLine.objects.filter(
        entry__company=company, entry__status__in=LEDGER_STATUSES
    ).select_related("entry", "account")
    if fiscal_period is not None:
        qs = qs.filter(entry__fiscal_period=fiscal_period)
    if account is not None:
        qs = qs.filter(account=account)
    if date_from is not None:
        qs = qs.filter(entry__entry_date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(entry__entry_date__lte=date_to)
    if party is not None:
        qs = qs.filter(party=party)
    return qs


def party_account_balance(company, account, party) -> Decimal:
    """Debit-minus-credit balance of one account restricted to lines tagged
    with one party — the subledger primitive (ADR-015). Sign convention is
    the account's own: a credit-normal AP account yields a negative number
    for amounts owed; callers flip the sign for presentation."""
    agg = _lines(company, account=account, party=party).aggregate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    return (agg["debit"] or ZERO) - (agg["credit"] or ZERO)


def trial_balance(company, *, fiscal_period=None):
    """Per-account debit/credit totals plus grand totals for a company."""
    rows = []
    total_debit = ZERO
    total_credit = ZERO
    grouped = (
        _lines(company, fiscal_period=fiscal_period)
        .values("account_id", "account__code", "account__name")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("account__code")
    )
    for row in grouped:
        debit = row["debit"] or ZERO
        credit = row["credit"] or ZERO
        total_debit += debit
        total_credit += credit
        rows.append(
            {
                "account_id": row["account_id"],
                "code": row["account__code"],
                "name": row["account__name"],
                "debit": debit,
                "credit": credit,
                "balance": debit - credit,
            }
        )
    return {
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_balanced": total_debit == total_credit,
    }


def general_ledger(company, account, *, fiscal_period=None):
    """Chronological lines for one account with a running (debit-credit) balance."""
    lines = []
    running = ZERO
    qs = _lines(company, fiscal_period=fiscal_period, account=account).order_by(
        "entry__entry_date", "created_at"
    )
    for line in qs:
        running += line.debit - line.credit
        lines.append(
            {
                "entry_id": line.entry_id,
                "date": line.entry.entry_date,
                "description": line.description or line.entry.description,
                "debit": line.debit,
                "credit": line.credit,
                "running_balance": running,
            }
        )
    return lines


def account_balance(company, account, *, fiscal_period=None, date_to=None) -> Decimal:
    agg = _lines(company, fiscal_period=fiscal_period, account=account, date_to=date_to).aggregate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    return (agg["debit"] or ZERO) - (agg["credit"] or ZERO)


# ---------------------------------------------------------------------------
# Sprint 07 — financial statements (derived, like everything above)
# ---------------------------------------------------------------------------


def _grouped_type_balances(
    company, *, fiscal_period=None, date_from=None, date_to=None, exclude_closing=False
):
    """Per-account debit/credit sums with the account type attached."""
    qs = _lines(company, fiscal_period=fiscal_period, date_from=date_from, date_to=date_to)
    if exclude_closing:
        qs = qs.exclude(entry__source_type="CLOSING")
    grouped = (
        qs.values("account_id", "account__code", "account__name", "account__account_type")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("account__code")
    )
    rows = []
    for row in grouped:
        rows.append(
            {
                "account_id": row["account_id"],
                "code": row["account__code"],
                "name": row["account__name"],
                "account_type": row["account__account_type"],
                "debit": row["debit"] or ZERO,
                "credit": row["credit"] or ZERO,
            }
        )
    return rows


def income_statement(
    company, *, fiscal_period=None, date_from=None, date_to=None, cogs_accounts=None
):
    """Income statement derived from posted journal lines (Sprint 07).

    Grouping is by ``Account.account_type`` only (REVENUE / EXPENSE); the
    chart has no separate COGS type, so cost of goods sold is the subset
    of expense accounts the *caller* designates via ``cogs_accounts``
    (Account objects or ids) — nothing is guessed from codes or names
    (ADR-030). Amounts are presented positive: revenue as credit−debit,
    expenses as debit−credit.

    Closing entries (source_type ``CLOSING``) are EXCLUDED: they are
    bookkeeping transfers into retained earnings, not operating results,
    so a closed period still reports its real revenue and expenses.
    """
    cogs_ids = set()
    for item in cogs_accounts or []:
        cogs_ids.add(getattr(item, "id", item))

    revenue_rows = []
    cogs_rows = []
    expense_rows = []
    for row in _grouped_type_balances(
        company,
        fiscal_period=fiscal_period,
        date_from=date_from,
        date_to=date_to,
        exclude_closing=True,
    ):
        if row["account_type"] == "REVENUE":
            amount = row["credit"] - row["debit"]
            if amount != ZERO:
                revenue_rows.append({**row, "amount": amount})
        elif row["account_type"] == "EXPENSE":
            amount = row["debit"] - row["credit"]
            if amount == ZERO:
                continue
            target = cogs_rows if row["account_id"] in cogs_ids else expense_rows
            target.append({**row, "amount": amount})

    revenue_total = sum((r["amount"] for r in revenue_rows), ZERO)
    cogs_total = sum((r["amount"] for r in cogs_rows), ZERO)
    expenses_total = sum((r["amount"] for r in expense_rows), ZERO)
    gross_profit = revenue_total - cogs_total
    return {
        "revenue_rows": revenue_rows,
        "revenue_total": revenue_total,
        "cogs_rows": cogs_rows,
        "cogs_total": cogs_total,
        "gross_profit": gross_profit,
        "expense_rows": expense_rows,
        "expenses_total": expenses_total,
        "net_income": gross_profit - expenses_total,
    }


def balance_sheet(company, *, as_of=None, fiscal_period=None):
    """Balance sheet derived from posted journal lines (Sprint 07).

    Assets/liabilities/equity come from account types and are presented
    on their normal side (assets debit−credit, liabilities and equity
    credit−debit). Equity accounts alone do not include the result of
    periods that have not been closed yet, so the statement carries an
    explicit ``current_period_result`` line — the net of ALL revenue and
    expense balances up to ``as_of`` (closing entries included: a closed
    period's result already sits in retained earnings and its
    income-statement accounts net to zero, contributing nothing here).
    With that line, Assets == Liabilities + Equity holds by construction
    and is asserted by tests in both the open and the closed state.
    """
    if fiscal_period is not None:
        if fiscal_period.company_id != company.id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Fiscal period belongs to a different company.")
        as_of = fiscal_period.end_date

    asset_rows = []
    liability_rows = []
    equity_rows = []
    result = ZERO
    for row in _grouped_type_balances(company, date_to=as_of):
        balance = row["debit"] - row["credit"]
        account_type = row["account_type"]
        if account_type == "ASSET":
            if balance != ZERO:
                asset_rows.append({**row, "amount": balance})
        elif account_type == "LIABILITY":
            if balance != ZERO:
                liability_rows.append({**row, "amount": -balance})
        elif account_type == "EQUITY":
            if balance != ZERO:
                equity_rows.append({**row, "amount": -balance})
        elif account_type in ("REVENUE", "EXPENSE"):
            result -= balance  # (credit − debit) across income accounts

    total_assets = sum((r["amount"] for r in asset_rows), ZERO)
    total_liabilities = sum((r["amount"] for r in liability_rows), ZERO)
    total_equity = sum((r["amount"] for r in equity_rows), ZERO)
    equity_with_result = total_equity + result
    return {
        "as_of": as_of,
        "asset_rows": asset_rows,
        "total_assets": total_assets,
        "liability_rows": liability_rows,
        "total_liabilities": total_liabilities,
        "equity_rows": equity_rows,
        "total_equity": total_equity,
        "current_period_result": result,
        "equity_with_result": equity_with_result,
        "total_liabilities_and_equity": total_liabilities + equity_with_result,
        "is_balanced": total_assets == total_liabilities + equity_with_result,
    }
