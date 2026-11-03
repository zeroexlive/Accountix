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
from django.utils.translation import gettext_lazy as _


def _require_administer_role(company, user) -> None:
    """Defense-in-depth for the ADMINISTER-tier services (ADR-050).

    The views gate fiscal closing and opening balances at the
    ADMINISTER tier; the services repeat the assertion whenever a
    user is supplied, so no future caller can widen the surface by
    accident. ``user=None`` marks a trusted internal call (the
    user-less service API predates the web UI) and skips the check.
    A PermissionDenied — not a ValidationError — propagates: this is
    an authorization stop, not form feedback.
    """
    if user is None:
        return
    from apps.core.access import ADMINISTER_ROLES, require_company_role

    require_company_role(user, company, ADMINISTER_ROLES)


def validate_account_hierarchy(account) -> None:
    parent = account.parent
    if parent is None:
        return
    if account.pk and parent.pk == account.pk:
        raise ValidationError(_("An account cannot be its own parent."))
    if parent.company_id != account.company_id:
        raise ValidationError(_("Parent account belongs to a different company."))
    # Cycle detection: walk ancestors of the proposed parent.
    seen: set = set()
    node = parent
    while node is not None:
        if account.pk and node.pk == account.pk:
            raise ValidationError(_("Account hierarchy would contain a cycle."))
        if node.pk in seen:  # pre-existing corrupt cycle guard
            raise ValidationError(_("Existing account hierarchy contains a cycle."))
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
        raise ValidationError(
            _("%(field)s is not a valid decimal amount.") % {"field": field}
        ) from None
    if amount.is_nan() or amount.is_infinite():
        raise ValidationError(_("%(field)s is not a finite amount.") % {"field": field})
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
        raise ValidationError(
            _("No fiscal period of this company contains %(entry_date)s.")
            % {"entry_date": entry_date}
        )
    return period


def _resolve_party(company, raw_party, idx):
    """Resolve the optional subledger party tag of a line (ADR-015)."""
    if raw_party is None:
        return None
    from apps.parties.models import Party

    party = (
        raw_party if isinstance(raw_party, Party) else Party.objects.filter(pk=raw_party).first()
    )
    if party is None:
        raise ValidationError(_("Line %(line)s: party not found.") % {"line": idx + 1})
    if party.company_id != company.id:
        raise ValidationError(
            _("Line %(line)s: party belongs to a different company.") % {"line": idx + 1}
        )
    return party


def _validate_lines(company, raw_lines):
    """Validate raw line dicts and return [(account, debit, credit, desc, party)]."""
    from apps.accounting.models import Account

    if raw_lines is None or len(raw_lines) < 2:
        raise ValidationError(_("A journal entry needs at least two lines."))
    validated = []
    total_debit = ZERO
    total_credit = ZERO
    for idx, raw in enumerate(raw_lines):
        account = raw.get("account")
        if not isinstance(account, Account):
            account_id = raw.get("account_id", account)
            account = Account.objects.filter(pk=account_id).first()
            if account is None:
                raise ValidationError(_("Line %(line)s: account not found.") % {"line": idx + 1})
        if account.company_id != company.id:
            raise ValidationError(
                _("Line %(line)s: account belongs to a different company.") % {"line": idx + 1}
            )
        if not account.is_postable:
            raise ValidationError(
                _("Line %(line)s: account %(code)s is not postable.")
                % {"line": idx + 1, "code": account.code}
            )
        if not account.is_active:
            raise ValidationError(
                _("Line %(line)s: account %(code)s is inactive.")
                % {"line": idx + 1, "code": account.code}
            )
        debit = _to_decimal(raw.get("debit", ZERO), f"Line {idx + 1} debit")
        credit = _to_decimal(raw.get("credit", ZERO), f"Line {idx + 1} credit")
        if debit < ZERO or credit < ZERO:
            raise ValidationError(
                _("Line %(line)s: amounts cannot be negative.") % {"line": idx + 1}
            )
        if debit > ZERO and credit > ZERO:
            raise ValidationError(
                _("Line %(line)s: a line is either debit or credit, not both.") % {"line": idx + 1}
            )
        if debit == ZERO and credit == ZERO:
            raise ValidationError(
                _("Line %(line)s: a line cannot be zero on both sides.") % {"line": idx + 1}
            )
        total_debit += debit
        total_credit += credit
        party = _resolve_party(company, raw.get("party"), idx)
        validated.append((account, debit, credit, raw.get("description", ""), party))
    if total_debit != total_credit:
        raise ValidationError(
            _("Journal entry is not balanced: debit %(debit)s != credit %(credit)s.")
            % {"debit": total_debit, "credit": total_credit}
        )
    if total_debit == ZERO:
        raise ValidationError(_("Journal entry total cannot be zero."))
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

    Concurrency (Sprint 10, ADR-037): the check above races when two
    callers post the same key simultaneously — both miss, both insert,
    and the unique constraint (company, idempotency_key) rejects the
    loser with a raw IntegrityError. The entry creation therefore runs
    in a nested atomic block (savepoint): on IntegrityError the loser
    re-reads and returns the winner's entry, so concurrent idempotent
    posting is safe *and* clean on PostgreSQL.
    """
    from django.db import IntegrityError

    from apps.accounting.models import JournalEntry, JournalLine
    from apps.audit.services import record_event

    key = idempotency_key or None
    if key:
        existing = JournalEntry.objects.filter(company=company, idempotency_key=key).first()
        if existing is not None:
            return existing

    period = resolve_fiscal_period(company, entry_date)
    if period.status != "OPEN":
        raise ValidationError(_("Fiscal period is closed; posting is not allowed."))
    if period.company_id != company.id:
        raise ValidationError(_("Fiscal period belongs to a different company."))

    validated = _validate_lines(company, lines)

    if key:
        try:
            with transaction.atomic():
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
        except IntegrityError:
            existing = JournalEntry.objects.filter(company=company, idempotency_key=key).first()
            if existing is not None:
                return existing
            raise
    else:
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
    for account, debit, credit, line_desc, party in validated:
        JournalLine.objects.create(
            entry=entry,
            account=account,
            debit=debit,
            credit=credit,
            description=line_desc,
            party=party,
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
        raise ValidationError(_("A reversal entry cannot itself be reversed."))
    if entry.status == JournalEntry.Status.REVERSED:
        raise ValidationError(_("This entry has already been reversed."))
    if entry.status != JournalEntry.Status.POSTED:
        raise ValidationError(_("Only a POSTED entry can be reversed."))
    if JournalReversal.objects.filter(original_entry=entry).exists():
        raise ValidationError(_("This entry has already been reversed."))

    rev_date = reversal_date or entry.entry_date
    period = resolve_fiscal_period(entry.company, rev_date)
    if period.status != "OPEN":
        raise ValidationError(_("Fiscal period for the reversal date is closed."))

    original_lines = list(entry.lines.select_related("account").all())
    if len(original_lines) < 2:
        raise ValidationError(_("Entry has fewer than two lines and cannot be reversed."))

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
            party_id=line.party_id,  # keep the subledger tag so balances net out
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


# ---------------------------------------------------------------------------
# Sprint 12 — manual journal drafts (data-entry UI, ADR-039)
# ---------------------------------------------------------------------------


@transaction.atomic
def create_journal_draft(
    *,
    company,
    entry_date,
    lines,
    description="",
    user=None,
    idempotency_key=None,
):
    """Create a DRAFT journal entry for the manual-entry UI.

    Lines go through the exact §6.3 validation used at posting time
    (``_validate_lines``: at least two lines, postable/active/same-company
    accounts, one-sided amounts, balanced totals), so an invalid draft is
    rejected before anything is written. The fiscal period must exist for
    the date but need not be OPEN — the open-period gate is enforced when
    the draft is posted (:func:`post_journal_draft`).

    Unlike :func:`post_journal_entry`, an idempotency key that is already
    taken raises ValidationError instead of returning the existing entry:
    the form user must be told their key collides, not silently handed
    someone else's draft.
    """
    from apps.accounting.models import JournalEntry, JournalLine
    from apps.audit.services import record_event

    key = idempotency_key or None
    if key and JournalEntry.objects.filter(company=company, idempotency_key=key).exists():
        raise ValidationError(
            _("An entry with this idempotency key already exists for this company.")
        )
    period = resolve_fiscal_period(company, entry_date)
    validated = _validate_lines(company, lines)
    entry = JournalEntry.objects.create(
        company=company,
        fiscal_period=period,
        entry_date=entry_date,
        description=description,
        status=JournalEntry.Status.DRAFT,
        source_type="MANUAL",
        source_id="",
        idempotency_key=key,
    )
    for account, debit, credit, line_desc, party in validated:
        JournalLine.objects.create(
            entry=entry,
            account=account,
            debit=debit,
            credit=credit,
            description=line_desc,
            party=party,
        )
    record_event(
        action="journal.draft_created",
        entity_type="JournalEntry",
        company=company,
        user=user,
        entity_id=entry.id,
    )
    return entry


@transaction.atomic
def post_journal_draft(entry, *, user=None):
    """Post a DRAFT entry created by :func:`create_journal_draft`.

    The stored lines are re-validated end to end (§6.3) and the period
    containing the entry date must be OPEN — accounts may have been
    deactivated or the period closed since the draft was saved, and a
    stale draft must not slip past either gate. Re-posting a POSTED
    entry returns it unchanged (the ``post_*`` convention of the other
    apps); a REVERSED entry cannot be posted.
    """
    from apps.accounting.models import JournalEntry
    from apps.audit.services import record_event

    entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.status == JournalEntry.Status.POSTED:
        return entry
    if entry.status not in (JournalEntry.Status.DRAFT, JournalEntry.Status.VALIDATED):
        raise ValidationError(_("Only a DRAFT journal entry can be posted."))
    period = resolve_fiscal_period(entry.company, entry.entry_date)
    if period.status != "OPEN":
        raise ValidationError(_("Fiscal period is closed; posting is not allowed."))
    raw_lines = [
        {
            "account": line.account,
            "debit": line.debit,
            "credit": line.credit,
            "description": line.description,
            "party": line.party,
        }
        for line in entry.lines.select_related("account", "party").all()
    ]
    _validate_lines(entry.company, raw_lines)
    if entry.fiscal_period_id != period.id:
        entry.fiscal_period = period
    entry.status = JournalEntry.Status.POSTED
    entry.posted_by = user
    entry.posted_at = timezone.now()
    entry.save()
    record_event(
        action="journal.posted",
        entity_type="JournalEntry",
        company=entry.company,
        user=user,
        entity_id=entry.id,
        total_debit=str(entry.total_debit()),
        total_credit=str(entry.total_credit()),
    )
    return entry


# ---------------------------------------------------------------------------
# Sprint 07 — opening balances
# ---------------------------------------------------------------------------


def _parse_opening_line(company, raw, idx):
    """Normalize one opening-balance line (dict or tuple) and validate the
    account/party/amount shape. Returns (account, debit, credit, party)."""
    from apps.accounting.models import Account

    if isinstance(raw, dict):
        account = raw.get("account")
        debit = raw.get("debit", ZERO)
        credit = raw.get("credit", ZERO)
        party = raw.get("party")
    elif isinstance(raw, (list, tuple)) and len(raw) in (3, 4):
        account, debit, credit = raw[0], raw[1], raw[2]
        party = raw[3] if len(raw) == 4 else None
    else:
        raise ValidationError(
            _("Opening line %(line)s: expected a dict or tuple.") % {"line": idx + 1}
        )
    if not isinstance(account, Account):
        account = Account.objects.filter(pk=account).first()
        if account is None:
            raise ValidationError(
                _("Opening line %(line)s: account not found.") % {"line": idx + 1}
            )
    if account.company_id != company.id:
        raise ValidationError(
            _("Opening line %(line)s: account belongs to a different company.") % {"line": idx + 1}
        )
    if not account.is_postable:
        raise ValidationError(
            _("Opening line %(line)s: account %(code)s is not postable.")
            % {"line": idx + 1, "code": account.code}
        )
    if not account.is_active:
        raise ValidationError(
            _("Opening line %(line)s: account %(code)s is inactive.")
            % {"line": idx + 1, "code": account.code}
        )
    debit = _to_decimal(debit, f"Opening line {idx + 1} debit")
    credit = _to_decimal(credit, f"Opening line {idx + 1} credit")
    if debit < ZERO or credit < ZERO:
        raise ValidationError(
            _("Opening line %(line)s: amounts cannot be negative.") % {"line": idx + 1}
        )
    if debit > ZERO and credit > ZERO:
        raise ValidationError(
            _("Opening line %(line)s: a line is either debit or credit.") % {"line": idx + 1}
        )
    if debit == ZERO and credit == ZERO:
        raise ValidationError(
            _("Opening line %(line)s: a line cannot be zero on both sides.") % {"line": idx + 1}
        )
    party = _resolve_party(company, party, idx)
    return account, debit, credit, party


@transaction.atomic
def post_opening_balance(*, company, fiscal_year, lines, offset_account, user=None):
    """Post the opening balance of a fiscal year as ONE journal entry.

    The entry is dated the first day of the fiscal year's FIRST period
    (which must be OPEN) and carries source_type ``opening_balance`` with
    idempotency key ``opening-balance:<fiscal_year id>`` — re-posting
    returns the existing entry unchanged. The caller supplies the offset
    (retained earnings / opening-balance equity) account; the service
    adds one offset line so the constructed entry balances exactly:
    the excess of debits becomes a credit to the offset account and vice
    versa. No account is hardcoded.
    """
    _require_administer_role(company, user)
    from apps.accounting.models import Account, JournalEntry

    key = f"opening-balance:{fiscal_year.id}"
    existing = JournalEntry.objects.filter(company=company, idempotency_key=key).first()
    if existing is not None:
        return existing

    if fiscal_year.company_id != company.id:
        raise ValidationError(_("Fiscal year belongs to a different company."))
    period = fiscal_year.periods.order_by("start_date", "created_at").first()
    if period is None:
        raise ValidationError(_("The fiscal year has no periods."))
    if period.company_id != company.id:
        raise ValidationError(_("Fiscal period belongs to a different company."))
    if period.status != "OPEN":
        raise ValidationError(
            _("The first fiscal period is closed; opening balance cannot be posted.")
        )

    if not isinstance(offset_account, Account):
        offset_account = Account.objects.filter(pk=offset_account).first()
        if offset_account is None:
            raise ValidationError(_("Offset account not found."))
    if offset_account.company_id != company.id:
        raise ValidationError(_("Offset account belongs to a different company."))
    if not offset_account.is_postable or not offset_account.is_active:
        raise ValidationError(_("Offset account is not postable/active."))

    if not lines:
        raise ValidationError(_("An opening balance needs at least one line."))
    parsed = [_parse_opening_line(company, raw, idx) for idx, raw in enumerate(lines)]
    total_debit = sum((p[1] for p in parsed), ZERO)
    total_credit = sum((p[2] for p in parsed), ZERO)

    journal_lines = [
        {"account": account, "debit": debit, "credit": credit, "party": party}
        for account, debit, credit, party in parsed
    ]
    diff = total_debit - total_credit
    if diff > ZERO:
        journal_lines.append({"account": offset_account, "credit": diff})
    elif diff < ZERO:
        journal_lines.append({"account": offset_account, "debit": -diff})
    if len(journal_lines) < 2:
        raise ValidationError(_("An opening balance needs at least two journal lines."))

    return post_journal_entry(
        company=company,
        entry_date=period.start_date,
        lines=journal_lines,
        description=f"Opening balance — {fiscal_year.name}",
        user=user,
        source_type="opening_balance",
        source_id=str(fiscal_year.id),
        idempotency_key=key,
    )


# ---------------------------------------------------------------------------
# Sprint 07 — fiscal period closing / reopening
# ---------------------------------------------------------------------------


def _closing_entry_for_period(company, period):
    """The currently POSTED closing entry of a period, if any. Closing
    entries are tracked by (source_type, source_id) + the idempotency key
    family ``closing:<period id>`` — no schema change on FiscalPeriod."""
    from apps.accounting.models import JournalEntry

    return (
        JournalEntry.objects.filter(
            company=company,
            source_type="CLOSING",
            source_id=str(period.id),
            status=JournalEntry.Status.POSTED,
        )
        .order_by("created_at")
        .first()
    )


@transaction.atomic
def close_fiscal_period(*, company, period, retained_earnings, user=None):
    """Close a fiscal period (Sprint 07).

    Computes the period's revenue/expense balances from posted lines,
    posts ONE closing entry dated the period's last day (key
    ``closing:<period id>``) that zeroes every income-statement account
    into the caller-supplied retained-earnings account, and only then
    flips the period to CLOSED — after which the posting gate rejects
    new postings into it. A period with no income-statement activity
    closes without an entry. Returns the closing entry or None.
    """
    _require_administer_role(company, user)
    from django.db.models import Sum

    from apps.accounting.models import Account, JournalEntry, JournalLine
    from apps.audit.services import record_event
    from apps.organizations.models import FiscalPeriod

    period = FiscalPeriod.objects.select_for_update().get(pk=period.pk)
    if period.company_id != company.id:
        raise ValidationError(_("Fiscal period belongs to a different company."))
    if period.status == FiscalPeriod.Status.CLOSED:
        raise ValidationError(_("This fiscal period is already closed."))
    if _closing_entry_for_period(company, period) is not None:
        raise ValidationError(_("This fiscal period already has an active closing entry."))

    if not isinstance(retained_earnings, Account):
        retained_earnings = Account.objects.filter(pk=retained_earnings).first()
        if retained_earnings is None:
            raise ValidationError(_("Retained earnings account not found."))
    if retained_earnings.company_id != company.id:
        raise ValidationError(_("Retained earnings account belongs to a different company."))
    if not retained_earnings.is_postable or not retained_earnings.is_active:
        raise ValidationError(_("Retained earnings account is not postable/active."))

    grouped = (
        JournalLine.objects.filter(
            entry__company=company,
            entry__fiscal_period=period,
            entry__status__in=[JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED],
            account__account_type__in=[Account.AccountType.REVENUE, Account.AccountType.EXPENSE],
        )
        .values("account_id")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
    )
    balances = []
    for row in grouped:
        balance = (row["debit"] or ZERO) - (row["credit"] or ZERO)
        if balance != ZERO:
            balances.append((row["account_id"], balance))

    closing_entry = None
    if balances:
        accounts = {
            account.id: account
            for account in Account.objects.filter(id__in=[b[0] for b in balances])
        }
        journal_lines = []
        net_income = ZERO
        for account_id, balance in balances:
            account = accounts[account_id]
            if balance > ZERO:  # net debit (expense-like): credit it to zero
                journal_lines.append({"account": account, "credit": balance})
            else:  # net credit (revenue-like): debit it to zero
                journal_lines.append({"account": account, "debit": -balance})
            net_income -= balance
        if net_income > ZERO:
            journal_lines.append({"account": retained_earnings, "credit": net_income})
        elif net_income < ZERO:
            journal_lines.append({"account": retained_earnings, "debit": -net_income})
        prior_closings = JournalEntry.objects.filter(
            company=company, source_type="CLOSING", source_id=str(period.id)
        ).count()
        key = (
            f"closing:{period.id}"
            if prior_closings == 0
            else f"closing:{period.id}:{prior_closings + 1}"
        )
        closing_entry = post_journal_entry(
            company=company,
            entry_date=period.end_date,
            lines=journal_lines,
            description=f"Closing entry — {period.name}",
            user=user,
            source_type="CLOSING",
            source_id=str(period.id),
            idempotency_key=key,
        )

    period.status = FiscalPeriod.Status.CLOSED
    period.save()
    record_event(
        action="fiscal_period.closed",
        entity_type="FiscalPeriod",
        company=company,
        user=user,
        entity_id=period.id,
        closing_entry_id=str(closing_entry.id) if closing_entry else "",
    )
    return closing_entry


@transaction.atomic
def reopen_fiscal_period(*, company, period, user=None):
    """Reopen a CLOSED period: flip it back to OPEN and reverse its
    closing entry (never delete it), restoring the period's balances.
    The flip happens inside the same transaction, before the reversal,
    because the reversal entry is dated inside the period and the
    posting gate requires the period to be OPEN. Returns the reversal
    entry, or None when the period had no closing entry."""
    _require_administer_role(company, user)
    from apps.audit.services import record_event
    from apps.organizations.models import FiscalPeriod

    period = FiscalPeriod.objects.select_for_update().get(pk=period.pk)
    if period.company_id != company.id:
        raise ValidationError(_("Fiscal period belongs to a different company."))
    if period.status != FiscalPeriod.Status.CLOSED:
        raise ValidationError(_("Only a CLOSED fiscal period can be reopened."))

    closing_entry = _closing_entry_for_period(company, period)
    period.status = FiscalPeriod.Status.OPEN
    period.save()

    reversal = None
    if closing_entry is not None:
        reversal = reverse_journal_entry(
            entry=closing_entry,
            user=user,
            reason=f"Fiscal period {period.name} reopened",
            reversal_date=period.end_date,
        )
    record_event(
        action="fiscal_period.reopened",
        entity_type="FiscalPeriod",
        company=company,
        user=user,
        entity_id=period.id,
        closing_entry_id=str(closing_entry.id) if closing_entry else "",
    )
    return reversal


@transaction.atomic
def close_fiscal_year(*, company, fiscal_year, retained_earnings, user=None):
    """Close a fiscal year: close every still-OPEN period of the year via
    ``close_fiscal_period`` (already-CLOSED periods are skipped), then
    flip the year's status to CLOSED. Returns the closing entries that
    were posted (periods without activity contribute none)."""
    _require_administer_role(company, user)
    from apps.audit.services import record_event
    from apps.organizations.models import FiscalYear

    fiscal_year = FiscalYear.objects.select_for_update().get(pk=fiscal_year.pk)
    if fiscal_year.company_id != company.id:
        raise ValidationError(_("Fiscal year belongs to a different company."))

    entries = []
    for period in fiscal_year.periods.order_by("start_date", "created_at"):
        if period.status == "CLOSED":
            continue
        entry = close_fiscal_period(
            company=company, period=period, retained_earnings=retained_earnings, user=user
        )
        if entry is not None:
            entries.append(entry)

    if fiscal_year.status != FiscalYear.Status.CLOSED:
        fiscal_year.status = FiscalYear.Status.CLOSED
        fiscal_year.save()
    record_event(
        action="fiscal_year.closed",
        entity_type="FiscalYear",
        company=company,
        user=user,
        entity_id=fiscal_year.id,
        closing_entries=str(len(entries)),
    )
    return entries
