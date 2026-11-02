"""Accounting application services.

Sprint 01: chart-of-accounts hierarchy validation.
Sprint 02: journal posting and reversal enforcing the §6.3 invariants —
everything runs inside ``transaction.atomic`` and all validation happens
before any row is written, so a rejected posting persists nothing.
"""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone


def validate_account_hierarchy(account) -> None:
    parent = account.parent
    if parent is None:
        return
    if account.pk and parent.pk == account.pk:
        raise ValidationError("An account cannot be its own parent.")
    if parent.company_id != account.company_id:
        raise ValidationError("Parent account belongs to a different company.")
    # Cycle detection: walk ancestors of the proposed parent.
    seen: set = set()
    node = parent
    while node is not None:
        if account.pk and node.pk == account.pk:
            raise ValidationError("Account hierarchy would contain a cycle.")
        if node.pk in seen:  # pre-existing corrupt cycle guard
            raise ValidationError("Existing account hierarchy contains a cycle.")
        seen.add(node.pk)
        node = node.parent


# ---------------------------------------------------------------------------
# Sprint 02 — journal posting & reversal
# ---------------------------------------------------------------------------

ZERO = Decimal("0")


def _to_decimal(value, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{field} is not a valid decimal amount.") from None
    if amount.is_nan() or amount.is_infinite():
        raise ValidationError(f"{field} is not a finite amount.")
    return amount


def resolve_fiscal_period(company, entry_date):
    """Return the fiscal period of ``company`` containing ``entry_date``.

    Raises ValidationError when no period contains the date.
    """
    from apps.organizations.models import FiscalPeriod

    period = (
        FiscalPeriod.objects.filter(
            company=company, start_date__lte=entry_date, end_date__gte=entry_date
        )
        .order_by("start_date")
        .first()
    )
    if period is None:
        raise ValidationError(f"No fiscal period of this company contains {entry_date}.")
    return period


def _validate_lines(company, raw_lines):
    """Validate raw line dicts and return [(account, debit, credit, desc)]."""
    from apps.accounting.models import Account

    if raw_lines is None or len(raw_lines) < 2:
        raise ValidationError("A journal entry needs at least two lines.")
    validated = []
    total_debit = ZERO
    total_credit = ZERO
    for idx, raw in enumerate(raw_lines):
        account = raw.get("account")
        if not isinstance(account, Account):
            account_id = raw.get("account_id", account)
            account = Account.objects.filter(pk=account_id).first()
            if account is None:
                raise ValidationError(f"Line {idx + 1}: account not found.")
        if account.company_id != company.id:
            raise ValidationError(f"Line {idx + 1}: account belongs to a different company.")
        if not account.is_postable:
            raise ValidationError(f"Line {idx + 1}: account {account.code} is not postable.")
        if not account.is_active:
            raise ValidationError(f"Line {idx + 1}: account {account.code} is inactive.")
        debit = _to_decimal(raw.get("debit", ZERO), f"Line {idx + 1} debit")
        credit = _to_decimal(raw.get("credit", ZERO), f"Line {idx + 1} credit")
        if debit < ZERO or credit < ZERO:
            raise ValidationError(f"Line {idx + 1}: amounts cannot be negative.")
        if debit > ZERO and credit > ZERO:
            raise ValidationError(f"Line {idx + 1}: a line is either debit or credit, not both.")
        if debit == ZERO and credit == ZERO:
            raise ValidationError(f"Line {idx + 1}: a line cannot be zero on both sides.")
        total_debit += debit
        total_credit += credit
        validated.append((account, debit, credit, raw.get("description", "")))
    if total_debit != total_credit:
        raise ValidationError(
            f"Journal entry is not balanced: debit {total_debit} != credit {total_credit}."
        )
    if total_debit == ZERO:
        raise ValidationError("Journal entry total cannot be zero.")
    return validated


@transaction.atomic
def post_journal_entry(
    *,
    company,
    entry_date,
    lines,
    description="",
    user=None,
    source_type="",
    source_id="",
    idempotency_key=None,
):
    """Create and post a balanced journal entry atomically.

    Idempotency: if ``idempotency_key`` is given and an entry already exists
    for (company, key), that entry is returned unchanged — no duplicate is
    created. All validation runs before any row is written.
    """
    from apps.accounting.models import JournalEntry, JournalLine
    from apps.audit.services import record_event

    key = idempotency_key or None
    if key:
        existing = JournalEntry.objects.filter(company=company, idempotency_key=key).first()
        if existing is not None:
            return existing

    period = resolve_fiscal_period(company, entry_date)
    if period.status != "OPEN":
        raise ValidationError("Fiscal period is closed; posting is not allowed.")
    if period.company_id != company.id:
        raise ValidationError("Fiscal period belongs to a different company.")

    validated = _validate_lines(company, lines)

    entry = JournalEntry.objects.create(
        company=company,
        fiscal_period=period,
        entry_date=entry_date,
        description=description,
        status=JournalEntry.Status.VALIDATED,
        source_type=source_type,
        source_id=source_id,
        idempotency_key=key,
    )
    for account, debit, credit, line_desc in validated:
        JournalLine.objects.create(
            entry=entry, account=account, debit=debit, credit=credit, description=line_desc
        )
    entry.status = JournalEntry.Status.POSTED
    entry.posted_by = user
    entry.posted_at = timezone.now()
    entry.save()
    record_event(
        action="journal.posted",
        entity_type="JournalEntry",
        company=company,
        user=user,
        entity_id=entry.id,
        total_debit=str(entry.total_debit()),
        total_credit=str(entry.total_credit()),
    )
    return entry


@transaction.atomic
def reverse_journal_entry(*, entry, user=None, reason="", reversal_date=None):
    """Reverse a POSTED entry with a new, balanced, swapped entry.

    History is preserved: the original stays in the ledger with status
    REVERSED, the reversal entry is POSTED, and a JournalReversal record
    links them. Reversing twice, or reversing a reversal entry, is rejected.
    """
    from apps.accounting.models import JournalEntry, JournalLine, JournalReversal
    from apps.audit.services import record_event

    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.reversal_of_id is not None:
        raise ValidationError("A reversal entry cannot itself be reversed.")
    if entry.status == JournalEntry.Status.REVERSED:
        raise ValidationError("This entry has already been reversed.")
    if entry.status != JournalEntry.Status.POSTED:
        raise ValidationError("Only a POSTED entry can be reversed.")
    if JournalReversal.objects.filter(original_entry=entry).exists():
        raise ValidationError("This entry has already been reversed.")

    rev_date = reversal_date or entry.entry_date
    period = resolve_fiscal_period(entry.company, rev_date)
    if period.status != "OPEN":
        raise ValidationError("Fiscal period for the reversal date is closed.")

    original_lines = list(entry.lines.select_related("account").all())
    if len(original_lines) < 2:
        raise ValidationError("Entry has fewer than two lines and cannot be reversed.")

    reversal = JournalEntry.objects.create(
        company=entry.company,
        fiscal_period=period,
        entry_date=rev_date,
        description=f"Reversal of {entry.entry_date}: {entry.description}".strip(),
        status=JournalEntry.Status.VALIDATED,
        source_type="REVERSAL",
        source_id=str(entry.id),
        idempotency_key=f"reversal:{entry.id}",
        reversal_of=entry,
    )
    for line in original_lines:
        JournalLine.objects.create(
            entry=reversal,
            account=line.account,
            debit=line.credit,
            credit=line.debit,
            description=line.description,
        )
    reversal.status = JournalEntry.Status.POSTED
    reversal.posted_by = user
    reversal.posted_at = timezone.now()
    reversal.save()

    JournalReversal.objects.create(
        original_entry=entry, reversal_entry=reversal, reversed_by=user, reason=reason
    )

    entry.status = JournalEntry.Status.REVERSED
    entry.save()  # model guard permits exactly this transition

    record_event(
        action="journal.reversed",
        entity_type="JournalEntry",
        company=entry.company,
        user=user,
        entity_id=entry.id,
        reversal_entry_id=str(reversal.id),
        reason=reason,
    )
    return reversal
