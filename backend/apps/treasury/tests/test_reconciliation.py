"""Sprint 14 — bank reconciliation services (ADR-041).

The pinned numeric scenario (also the ADR's worked example):

Book movements on the bank GL (June 2026):
  +1100  Jun  1  customer transfer receipt
  - 300  Jun  2  supplier transfer payment
  +1100  Jun  1  received cheque cleared (same day, same amount as
                 the receipt — deliberately ambiguous for auto-match)

Bank statement Jun 1-30, opening 0, stated closing 1850:
  +1100 TR-1 (Jun 1), +1100 CHQ-9 (Jun 1), -300 TR-2 (Jun 2),
  -50 FEE-1 (Jun 15, bank fee the books do not have yet)

Book balance 1900. Auto-match may only take the unambiguous -300.
The identity difference == outstanding_book_net is asserted at every
stage; completion is refused until the fee is booked and matched.
"""

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.accounting import reporting as acct_reporting
from apps.accounting import services as acct_services
from apps.treasury import reconciliation as recon
from apps.treasury import services as svc
from apps.treasury.tests._helpers import D, build_world

pytestmark = pytest.mark.django_db

JUN1 = date(2026, 6, 1)
JUN2 = date(2026, 6, 2)
JUN15 = date(2026, 6, 15)
JUN30 = date(2026, 6, 30)

CSV = (
    "date,description,reference,amount\n"
    "2026-06-01,Customer transfer,TR-1,1100\n"
    "2026-06-01,Cheque cleared,CHQ-9,1100\n"
    "2026-06-02,Supplier transfer,TR-2,-300\n"
    "2026-06-15,Bank fee,FEE-1,-50\n"
)


def _bank_world():
    """Book side: receipt +1100, payment -300, cleared cheque +1100."""
    w = build_world()
    receipt = svc.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.bank_treasury,
        amount=D("1100"),
        payment_date=JUN1,
        method="BANK_TRANSFER",
    )
    svc.post_payment(receipt, gl_accounts={"receivable": w.ar})
    payment = svc.create_payment(
        company=w.company,
        direction="PAYMENT",
        party=w.supplier,
        treasury_account=w.bank_treasury,
        amount=D("300"),
        payment_date=JUN2,
        method="BANK_TRANSFER",
    )
    svc.post_payment(payment, gl_accounts={"payable": w.ap})
    cheque_payment = svc.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.bank_treasury,
        amount=D("1100"),
        payment_date=JUN1,
        method="CHEQUE",
        cheque={
            "bank_name": "Melli",
            "cheque_number": "CHQ-77",
            "due_date": JUN1,
            "sayad_id": "SY-9",
        },
    )
    svc.post_payment(
        cheque_payment, gl_accounts={"receivable": w.ar, "cheques_in_hand": w.cheques_in_hand}
    )
    cheque = cheque_payment.cheques.first()
    # Posting the cheque must NOT touch the bank GL (value in hand).
    assert acct_reporting.account_balance(w.company, w.bank) == D("800")
    svc.clear_cheque(cheque, bank_treasury_account=w.bank_treasury, clearing_date=JUN1)
    assert acct_reporting.account_balance(w.company, w.bank) == D("1900")
    return w


def _statement(w):
    return recon.create_statement(
        company=w.company,
        treasury_account=w.bank_treasury,
        start_date=JUN1,
        end_date=JUN30,
        opening_balance=D("0"),
        closing_balance=D("1850"),
    )


def _book_line(w, signed, on):
    for jl in recon.book_movements(w.bank_treasury):
        if recon.signed_amount(jl) == D(signed) and jl.entry.entry_date == on:
            return jl
    raise AssertionError(f"no book movement {signed} on {on}")


def test_book_movements_cover_payments_and_cheque_clearing_only():
    w = _bank_world()
    movements = recon.book_movements(w.bank_treasury)
    assert [recon.signed_amount(jl) for jl in movements] == [D("1100"), D("1100"), D("-300")]
    # The cash treasury account has no movements on the bank GL.
    assert list(recon.book_movements(w.cash_treasury)) == []


def test_full_reconciliation_identity_scenario():
    w = _bank_world()
    statement = _statement(w)
    report = recon.import_statement_lines(statement, csv_text=CSV)
    assert report == {"imported": 4, "rejected": []}

    # Auto-match: only the -300 is unambiguous. Both +1100 lines have
    # two candidates within the window (receipt + cleared cheque).
    result = recon.auto_match(statement)
    assert result == {"matched": 1, "remaining": 3}

    summary = recon.reconciliation_summary(statement)
    assert summary["book_balance"] == D("1900")
    assert summary["statement_closing"] == D("1850")
    assert summary["matched_total"] == D("-300")
    assert summary["unmatched_statement_net"] == D("2150")
    assert summary["outstanding_book_net"] == D("2200")
    # The ADR-041 identity, plus its raw-gap form.
    assert summary["difference"] == summary["outstanding_book_net"] == D("2200")
    assert summary["book_balance"] - summary["statement_closing"] == (
        summary["outstanding_book_net"] - summary["unmatched_statement_net"]
    )

    with pytest.raises(ValidationError):
        recon.complete_statement(statement)

    lines = {line.reference: line for line in statement.lines.all()}
    fee_line = lines["FEE-1"]
    receipt_jl = _book_line(w, "1100", JUN1)
    # The fee has no book movement: matching it to the +1100 receipt
    # line fails on amount, and no -50 book movement exists at all.
    assert all(recon.signed_amount(jl) != D("-50") for jl in recon.book_movements(w.bank_treasury))
    with pytest.raises(ValidationError):
        recon.match_line(fee_line, receipt_jl)

    # The user disambiguates the two +1100 lines by hand.
    cheque_jl = [
        jl
        for jl in recon.book_movements(w.bank_treasury)
        if recon.signed_amount(jl) == D("1100") and jl.pk != receipt_jl.pk
    ][0]
    recon.match_line(lines["TR-1"], receipt_jl)
    recon.match_line(lines["CHQ-9"], cheque_jl)

    summary = recon.reconciliation_summary(statement)
    assert summary["unmatched_statement_net"] == D("-50")
    assert summary["outstanding_book_net"] == D("0")
    assert summary["difference"] == D("0")
    # Difference is zero but the fee line is unmatched: completing
    # over a bank movement the books lack is still refused.
    with pytest.raises(ValidationError):
        recon.complete_statement(statement)

    # A journal line cannot be claimed twice.
    with pytest.raises(ValidationError):
        recon.match_line(fee_line, receipt_jl)
    with pytest.raises(ValidationError):
        recon.match_line(lines["TR-1"], cheque_jl)

    # Book the bank fee through the accounting service (Dr expense /
    # Cr bank GL) — the only way a bank-only item enters the books.
    fee_entry = acct_services.post_journal_entry(
        company=w.company,
        entry_date=JUN15,
        lines=[
            {"account": w.expense, "debit": D("50")},
            {"account": w.bank, "credit": D("50")},
        ],
        description="Bank fee June",
        source_type="MANUAL",
        idempotency_key="test-bank-fee-1",
    )
    fee_jl = fee_entry.lines.get(account=w.bank)
    summary = recon.reconciliation_summary(statement)
    assert summary["book_balance"] == D("1850")
    assert summary["difference"] == summary["outstanding_book_net"] == D("-50")

    recon.match_line(fee_line, fee_jl)
    summary = recon.reconciliation_summary(statement)
    assert summary["matched_count"] == 4
    assert summary["unmatched_statement_net"] == D("0")
    assert summary["outstanding_book_net"] == D("0")
    assert summary["difference"] == D("0")

    statement = recon.complete_statement(statement)
    assert statement.status == "COMPLETED"

    # A completed statement is locked until reopened.
    fee_line.refresh_from_db()
    with pytest.raises(ValidationError):
        recon.unmatch_line(fee_line)
    recon.reopen_statement(statement)
    recon.unmatch_line(fee_line)
    fee_line.refresh_from_db()
    assert not fee_line.is_matched


def test_create_statement_requires_bank_account_of_same_company():
    w = build_world()
    with pytest.raises(ValidationError):
        recon.create_statement(
            company=w.company,
            treasury_account=w.cash_treasury,
            start_date=JUN1,
            end_date=JUN30,
            opening_balance=D("0"),
            closing_balance=D("0"),
        )
    other = build_world(company_name="Other Co")
    with pytest.raises(ValidationError):
        recon.create_statement(
            company=w.company,
            treasury_account=other.bank_treasury,
            start_date=JUN1,
            end_date=JUN30,
            opening_balance=D("0"),
            closing_balance=D("0"),
        )
    with pytest.raises(ValidationError):
        recon.create_statement(
            company=w.company,
            treasury_account=w.bank_treasury,
            start_date=JUN30,
            end_date=JUN1,
            opening_balance=D("0"),
            closing_balance=D("0"),
        )


def test_import_reports_bad_rows_and_imports_the_rest():
    w = _bank_world()
    statement = _statement(w)
    csv_text = (
        "date,description,reference,amount\n"
        "2026-06-01,Customer transfer,TR-1,1100\n"
        "not-a-date,Broken row,BR-1,10\n"
        "2026-06-02,Supplier transfer,TR-2,-300\n"
        "2026-06-03,Zero row,ZR-1,0\n"
        "2026-07-05,Outside period,OP-1,10\n"
    )
    report = recon.import_statement_lines(statement, csv_text=csv_text)
    assert report["imported"] == 2
    assert [r["row"] for r in report["rejected"]] == [3, 5, 6]
    assert statement.lines.count() == 2


def test_import_debit_credit_pair_columns():
    w = _bank_world()
    statement = _statement(w)
    csv_text = (
        "date,description,reference,debit,credit\n"
        "2026-06-01,Customer transfer,TR-1,,1100\n"
        "2026-06-02,Supplier transfer,TR-2,300,\n"
    )
    report = recon.import_statement_lines(statement, csv_text=csv_text)
    assert report == {"imported": 2, "rejected": []}
    amounts = sorted(line.amount for line in statement.lines.all())
    assert amounts == [D("-300"), D("1100")]


def test_duplicate_lines_rejected_on_import_and_manual_add():
    w = _bank_world()
    statement = _statement(w)
    csv_text = (
        "date,description,reference,amount\n"
        "2026-06-01,Customer transfer,TR-1,1100\n"
        "2026-06-01,Same again,TR-1,1100\n"
    )
    report = recon.import_statement_lines(statement, csv_text=csv_text)
    assert report["imported"] == 1
    assert [r["row"] for r in report["rejected"]] == [3]
    with pytest.raises(ValidationError):
        recon.add_statement_line(statement, line_date=JUN1, amount=D("1100"), reference="TR-1")
    # Same date+amount with a different reference is a different line.
    line = recon.add_statement_line(statement, line_date=JUN1, amount=D("1100"), reference="TR-9")
    assert line.is_matched is False


def test_manual_line_validation():
    w = _bank_world()
    statement = _statement(w)
    with pytest.raises(ValidationError):
        recon.add_statement_line(statement, line_date=JUN1, amount=D("0"))
    with pytest.raises(ValidationError):
        recon.add_statement_line(statement, line_date=date(2026, 7, 1), amount=D("10"))
