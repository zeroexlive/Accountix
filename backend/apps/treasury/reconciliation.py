"""Bank reconciliation services (Sprint 14, ADR-041).

Reconciliation happens at the GL level. For a BANK treasury account,
a **book movement** is a posted-ledger journal line on the account's
linked GL account — the same ledger set the accounting reports use
(entries POSTED or REVERSED; a reversed original and its reversal
entry both appear and net out). That definition covers, by
construction:

- payments posted with method CASH or BANK_TRANSFER on the bank
  account (Dr/Cr the bank GL at posting);
- received cheques when they *clear* (Dr the destination bank GL)
  and issued cheques when they *clear* (Cr the drawn bank GL);
- payment/journal reversals (the reversal entry's lines);
- manual journal entries posted straight to the bank GL — which is
  how bank-only items (fees, charges, interest) enter the books.

It deliberately does NOT cover cheque *posting* (the value sits in
the cheques-in-hand / cheques-payable holding account until
clearing), cheque deposit (register-only, no journal), or
bounce/return (holding + counterparty accounts only): none of those
touch the bank GL, so none of them can appear on a bank statement.

Sign mapping: the bank GL account is debit-normal (an asset), so a
book movement's signed amount is ``debit - credit``; a statement
line's ``amount`` uses the bank's perspective with the same sign
(positive = money in). A match therefore requires exact equality of
the two signed amounts.

Matching is link-only: it never mutates the journal line, the
payment or the cheque behind it. A journal line can be matched at
most once across all statements (a database OneToOne enforces it).
"""

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounting import reporting as accounting_reporting
from apps.accounting.models import JournalEntry, JournalLine

ZERO = Decimal("0")
AUTO_MATCH_WINDOW_DAYS = 7

LEDGER_STATUSES = [JournalEntry.Status.POSTED, JournalEntry.Status.REVERSED]


# ---------------------------------------------------------------------------
# Book side
# ---------------------------------------------------------------------------


def signed_amount(journal_line) -> Decimal:
    """A book movement's amount from the bank's perspective."""
    return journal_line.debit - journal_line.credit


def book_movements(treasury_account, *, date_to=None):
    """Posted-ledger journal lines on the treasury account's GL
    account, chronological — the book side of the reconciliation."""
    qs = (
        JournalLine.objects.filter(
            account=treasury_account.gl_account,
            entry__company=treasury_account.company,
            entry__status__in=LEDGER_STATUSES,
        )
        .select_related("entry", "account")
        .order_by("entry__entry_date", "created_at")
    )
    if date_to is not None:
        qs = qs.filter(entry__entry_date__lte=date_to)
    return qs


def _matched_journal_line_ids():
    from apps.treasury.models import BankStatementLine

    return set(
        BankStatementLine.objects.filter(matched_journal_line__isnull=False).values_list(
            "matched_journal_line_id", flat=True
        )
    )


def unmatched_book_movements(treasury_account, *, date_to=None):
    """Book movements no statement line has claimed yet."""
    matched_ids = _matched_journal_line_ids()
    return [
        line
        for line in book_movements(treasury_account, date_to=date_to)
        if line.id not in matched_ids
    ]


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


def _require_open(statement):
    from apps.treasury.models import BankStatement

    if statement.status != BankStatement.Status.OPEN:
        raise ValidationError("The statement is completed; reopen it before changing matches.")


@transaction.atomic
def create_statement(
    *,
    company,
    treasury_account,
    start_date,
    end_date,
    opening_balance,
    closing_balance,
    source_note="",
    user=None,
):
    from apps.audit.services import record_event
    from apps.treasury.models import BankStatement, TreasuryAccount

    if treasury_account is None or treasury_account.company_id != company.id:
        raise ValidationError("Treasury account belongs to a different company (or is missing).")
    if treasury_account.kind != TreasuryAccount.Kind.BANK:
        raise ValidationError("Bank reconciliation needs a BANK treasury account.")
    if not treasury_account.is_active:
        raise ValidationError("Treasury account is inactive.")
    if end_date < start_date:
        raise ValidationError("Statement end date is before its start date.")
    statement = BankStatement.objects.create(
        company=company,
        treasury_account=treasury_account,
        start_date=start_date,
        end_date=end_date,
        opening_balance=Decimal(str(opening_balance)),
        closing_balance=Decimal(str(closing_balance)),
        source_note=source_note,
    )
    record_event(
        action="bank_statement.created",
        entity_type="BankStatement",
        company=company,
        user=user,
        entity_id=statement.id,
        treasury_account_id=str(treasury_account.id),
    )
    return statement


def _assert_not_duplicate(statement, *, line_date, amount, reference, seen=None):
    from apps.treasury.models import BankStatementLine

    triple = (line_date, amount, reference)
    if seen is not None and triple in seen:
        raise ValidationError(
            f"Duplicate statement line ({line_date}, {amount}, {reference!r}) in the import."
        )
    if BankStatementLine.objects.filter(
        statement=statement, line_date=line_date, amount=amount, reference=reference
    ).exists():
        raise ValidationError(
            f"A statement line with this date, amount and reference already exists "
            f"({line_date}, {amount}, {reference!r})."
        )


@transaction.atomic
def add_statement_line(statement, *, line_date, amount, description="", reference="", user=None):
    """Add one line to an OPEN statement by hand."""
    from apps.audit.services import record_event
    from apps.treasury.models import BankStatementLine

    statement = type(statement).objects.select_for_update().get(pk=statement.pk)
    _require_open(statement)
    amount = Decimal(str(amount))
    if amount == ZERO:
        raise ValidationError("A statement line cannot be zero.")
    if not (statement.start_date <= line_date <= statement.end_date):
        raise ValidationError("The line date is outside the statement period.")
    _assert_not_duplicate(statement, line_date=line_date, amount=amount, reference=reference)
    line = BankStatementLine.objects.create(
        company=statement.company,
        statement=statement,
        line_date=line_date,
        description=description,
        reference=reference,
        amount=amount,
    )
    record_event(
        action="bank_statement.line_added",
        entity_type="BankStatementLine",
        company=statement.company,
        user=user,
        entity_id=line.id,
        statement_id=str(statement.id),
        amount=str(amount),
    )
    return line


def _parse_import_row(row, *, statement, seen):
    """Validate one CSV data row; returns (values, error_reason)."""
    raw_date = (row.get("date") or "").strip()
    try:
        line_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        return None, f"Unparseable date {raw_date!r} (expected YYYY-MM-DD)."
    if "amount" in row and (row.get("amount") or "").strip() != "":
        try:
            amount = Decimal((row.get("amount") or "").strip())
        except InvalidOperation:
            return None, f"Unparseable amount {row.get('amount')!r}."
    else:
        # Debit/credit pair: bank credit is money in (+), bank debit out (-).
        def _col(name):
            raw = (row.get(name) or "").strip()
            if raw == "":
                return ZERO
            try:
                return Decimal(raw)
            except InvalidOperation:
                raise ValueError(f"Unparseable {name} {raw!r}.") from None

        try:
            amount = _col("credit") - _col("debit")
        except ValueError as exc:
            return None, str(exc)
    if amount == ZERO:
        return None, "Amount is zero."
    if not (statement.start_date <= line_date <= statement.end_date):
        return None, "Line date is outside the statement period."
    description = (row.get("description") or "").strip()
    reference = (row.get("reference") or "").strip()
    if len(reference) > 64:
        return None, "Reference is longer than 64 characters."
    if len(description) > 500:
        return None, "Description is longer than 500 characters."
    try:
        _assert_not_duplicate(
            statement, line_date=line_date, amount=amount, reference=reference, seen=seen
        )
    except ValidationError as exc:
        return None, " ".join(exc.messages)
    return {
        "line_date": line_date,
        "amount": amount,
        "description": description,
        "reference": reference,
    }, None


@transaction.atomic
def import_statement_lines(statement, *, csv_text, user=None):
    """Import statement lines from CSV text.

    Column contract (header row required, names case-insensitive):
    ``date,description,reference,amount`` where ``amount`` is signed
    from the bank's perspective (+ money in, - money out); instead of
    ``amount``, a ``debit`` + ``credit`` column pair is accepted
    (amount = credit - debit). Dates are ISO ``YYYY-MM-DD``.

    Valid rows are imported in one transaction; invalid rows are
    skipped and reported — nothing is silently dropped. The report's
    ``row`` numbers are the file's physical line numbers (the header
    is line 1, so the first data row is line 2).
    """
    from apps.audit.services import record_event
    from apps.treasury.models import BankStatementLine

    statement = type(statement).objects.select_for_update().get(pk=statement.pk)
    _require_open(statement)
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise ValidationError("The CSV file is empty or has no header row.")
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    fields = set(reader.fieldnames)
    if "date" not in fields:
        raise ValidationError("The CSV needs a 'date' column.")
    if "amount" not in fields and not {"debit", "credit"} <= fields:
        raise ValidationError("The CSV needs an 'amount' column (or 'debit' + 'credit').")

    seen = set()
    valid = []
    rejected = []
    for row in reader:
        values, reason = _parse_import_row(
            {key.strip().lower(): value for key, value in row.items() if key},
            statement=statement,
            seen=seen,
        )
        if reason is not None:
            rejected.append({"row": reader.line_num, "reason": reason})
        else:
            seen.add((values["line_date"], values["amount"], values["reference"]))
            valid.append(values)
    for values in valid:
        BankStatementLine.objects.create(company=statement.company, statement=statement, **values)
    record_event(
        action="bank_statement.lines_imported",
        entity_type="BankStatement",
        company=statement.company,
        user=user,
        entity_id=statement.id,
        imported=str(len(valid)),
        rejected=str(len(rejected)),
    )
    return {"imported": len(valid), "rejected": rejected}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _apply_match(statement_line, journal_line, *, user):
    statement_line.matched_journal_line = journal_line
    statement_line.matched_at = timezone.now()
    statement_line.matched_by = user
    statement_line.save(
        update_fields=["matched_journal_line", "matched_at", "matched_by", "updated_at"]
    )


@transaction.atomic
def match_line(statement_line, journal_line, *, user=None):
    """Manually link one statement line to one book movement."""
    from apps.audit.services import record_event
    from apps.treasury.models import BankStatementLine

    statement_line = BankStatementLine.objects.select_for_update().get(pk=statement_line.pk)
    statement = statement_line.statement
    _require_open(statement)
    if statement_line.matched_journal_line_id is not None:
        raise ValidationError("This statement line is already matched; unmatch it first.")
    if journal_line is None or journal_line.account_id != statement.treasury_account.gl_account_id:
        raise ValidationError("The book movement is not on this statement's bank GL account.")
    if journal_line.entry.company_id != statement.company_id:
        raise ValidationError("The book movement belongs to a different company.")
    if journal_line.entry.status not in LEDGER_STATUSES:
        raise ValidationError("Only posted journal lines can be matched.")
    if BankStatementLine.objects.filter(matched_journal_line=journal_line).exists():
        raise ValidationError("This book movement is already matched to another statement line.")
    if signed_amount(journal_line) != statement_line.amount:
        raise ValidationError(
            f"Amounts do not agree: statement {statement_line.amount} vs "
            f"book {signed_amount(journal_line)}."
        )
    _apply_match(statement_line, journal_line, user=user)
    record_event(
        action="bank_statement.matched",
        entity_type="BankStatementLine",
        company=statement.company,
        user=user,
        entity_id=statement_line.id,
        journal_line_id=str(journal_line.id),
        amount=str(statement_line.amount),
    )
    return statement_line


@transaction.atomic
def unmatch_line(statement_line, *, user=None):
    from apps.audit.services import record_event
    from apps.treasury.models import BankStatementLine

    statement_line = BankStatementLine.objects.select_for_update().get(pk=statement_line.pk)
    _require_open(statement_line.statement)
    if statement_line.matched_journal_line_id is None:
        raise ValidationError("This statement line is not matched.")
    statement_line.matched_journal_line = None
    statement_line.matched_at = None
    statement_line.matched_by = None
    statement_line.save(
        update_fields=["matched_journal_line", "matched_at", "matched_by", "updated_at"]
    )
    record_event(
        action="bank_statement.unmatched",
        entity_type="BankStatementLine",
        company=statement_line.company,
        user=user,
        entity_id=statement_line.id,
    )
    return statement_line


@transaction.atomic
def auto_match(statement, *, user=None):
    """Match every statement line that has exactly ONE candidate book
    movement: unmatched, equal signed amount, book date within
    ±WINDOW days of the line date. Ambiguous lines (zero or several
    candidates) are left for manual matching."""
    from apps.audit.services import record_event
    from apps.treasury.models import BankStatementLine

    statement = type(statement).objects.select_for_update().get(pk=statement.pk)
    _require_open(statement)
    account = statement.treasury_account
    candidates = unmatched_book_movements(account)
    matched = 0
    lines = list(
        BankStatementLine.objects.filter(
            statement=statement, matched_journal_line__isnull=True
        ).order_by("line_date", "created_at")
    )
    for line in lines:
        pool = [
            jl
            for jl in candidates
            if signed_amount(jl) == line.amount
            and abs((jl.entry.entry_date - line.line_date).days) <= AUTO_MATCH_WINDOW_DAYS
        ]
        if len(pool) == 1:
            _apply_match(line, pool[0], user=user)
            candidates.remove(pool[0])
            matched += 1
    record_event(
        action="bank_statement.auto_matched",
        entity_type="BankStatement",
        company=statement.company,
        user=user,
        entity_id=statement.id,
        matched=str(matched),
    )
    return {"matched": matched, "remaining": len(lines) - matched}


# ---------------------------------------------------------------------------
# Summary + completion
# ---------------------------------------------------------------------------


def reconciliation_summary(statement):
    """Derived reconciliation state of one statement (ADR-041).

    difference = book_balance − (statement_closing − unmatched_statement_net)

    where book_balance is the GL balance of the bank account as of
    the statement end date. Under the chaining discipline (each
    statement's stated opening equals the book balance at its start,
    which a cleanly completed previous statement guarantees) the
    identity reduces to ``difference == outstanding_book_net``: the
    difference is exactly the net of book movements the bank has not
    shown yet. When every book movement ≤ end_date is matched and
    every statement line is matched, difference is exactly zero.
    """
    account = statement.treasury_account
    company = statement.company
    book_balance = accounting_reporting.account_balance(
        company, account.gl_account, date_to=statement.end_date
    )
    lines = list(statement.lines.select_related("matched_journal_line").all())
    matched_lines = [line for line in lines if line.is_matched]
    unmatched_lines = [line for line in lines if not line.is_matched]
    unmatched_statement_net = sum((line.amount for line in unmatched_lines), ZERO)
    outstanding = unmatched_book_movements(account, date_to=statement.end_date)
    outstanding_rows = [
        {
            "journal_line": jl,
            "entry": jl.entry,
            "date": jl.entry.entry_date,
            "description": jl.description or jl.entry.description,
            "amount": signed_amount(jl),
        }
        for jl in outstanding
    ]
    outstanding_net = sum((row["amount"] for row in outstanding_rows), ZERO)
    difference = book_balance - (statement.closing_balance - unmatched_statement_net)
    return {
        "book_balance": book_balance,
        "statement_opening": statement.opening_balance,
        "statement_closing": statement.closing_balance,
        "matched_count": len(matched_lines),
        "matched_total": sum((line.amount for line in matched_lines), ZERO),
        "unmatched_statement_lines": unmatched_lines,
        "unmatched_statement_net": unmatched_statement_net,
        "outstanding_book": outstanding_rows,
        "outstanding_book_net": outstanding_net,
        "difference": difference,
    }


@transaction.atomic
def complete_statement(statement, *, user=None):
    """Complete a statement: only when the reconciliation difference
    is exactly zero AND no statement line is left unmatched (an
    unmatched line is a bank movement the books do not have; closing
    over it would freeze it unrecorded — ADR-041)."""
    from apps.audit.services import record_event
    from apps.treasury.models import BankStatement

    statement = BankStatement.objects.select_for_update().get(pk=statement.pk)
    if statement.status == BankStatement.Status.COMPLETED:
        raise ValidationError("This statement is already completed.")
    summary = reconciliation_summary(statement)
    if summary["unmatched_statement_lines"]:
        raise ValidationError(
            "The statement still has unmatched lines; book and match them before completing."
        )
    if summary["difference"] != ZERO:
        raise ValidationError(
            f"Reconciliation difference is {summary['difference']}, not zero; "
            "match the outstanding book movements before completing."
        )
    statement.status = BankStatement.Status.COMPLETED
    statement.save(update_fields=["status", "updated_at"])
    record_event(
        action="bank_statement.completed",
        entity_type="BankStatement",
        company=statement.company,
        user=user,
        entity_id=statement.id,
    )
    return statement


@transaction.atomic
def reopen_statement(statement, *, user=None):
    from apps.audit.services import record_event
    from apps.treasury.models import BankStatement

    statement = BankStatement.objects.select_for_update().get(pk=statement.pk)
    if statement.status != BankStatement.Status.COMPLETED:
        raise ValidationError("Only a completed statement can be reopened.")
    statement.status = BankStatement.Status.OPEN
    statement.save(update_fields=["status", "updated_at"])
    record_event(
        action="bank_statement.reopened",
        entity_type="BankStatement",
        company=statement.company,
        user=user,
        entity_id=statement.id,
    )
    return statement
