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


def _lines(company, *, fiscal_period=None, account=None, date_to=None, party=None):
    qs = JournalLine.objects.filter(
        entry__company=company, entry__status__in=LEDGER_STATUSES
    ).select_related("entry", "account")
    if fiscal_period is not None:
        qs = qs.filter(entry__fiscal_period=fiscal_period)
    if account is not None:
        qs = qs.filter(account=account)
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
