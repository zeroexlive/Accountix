"""Sprint 15 — cheque books (ADR-042).

Books are the leaf inventory of one BANK treasury account for
ISSUED cheques: account-level number uniqueness, opt-in consumption
inside ``create_payment``, and no resurrection of used leaves —
ever. Plus the Sprint 14 follow-up: statement chaining prefill.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.treasury import cheque_books, reconciliation, services
from apps.treasury.models import Cheque, ChequeBook, ChequeLeaf
from apps.treasury.tests._helpers import DAY, build_world

pytestmark = pytest.mark.django_db


def _book(w, first="1001", count=25, account=None, label="دفترچه اول"):
    return cheque_books.create_cheque_book(
        company=w.company,
        treasury_account=account or w.bank_treasury,
        first_number=first,
        leaf_count=count,
        label=label,
    )


def _leaf(book, number):
    return book.leaves.get(number=number)


def _issue_payment(w, *, amount="500", leaf=None, cheque_number="", account=None):
    return services.create_payment(
        company=w.company,
        direction="PAYMENT",
        party=w.supplier,
        treasury_account=account or w.bank_treasury,
        amount=amount,
        payment_date=DAY,
        method="CHEQUE",
        cheque={
            "bank_name": "Melli",
            "cheque_number": cheque_number,
            "due_date": DAY,
        },
        leaf=leaf,
    )


# ---------------------------------------------------------------------------
# Generation + creation validation
# ---------------------------------------------------------------------------


def test_book_of_25_from_1001_generates_the_whole_range():
    w = build_world()
    book = _book(w)
    numbers = list(book.leaves.values_list("number", flat=True))
    assert numbers == [str(n) for n in range(1001, 1026)]
    assert cheque_books.book_counts(book) == (25, 0, 0)


def test_generation_preserves_prefix_and_zero_padding():
    w = build_world()
    book = _book(w, first="0042", count=3)
    assert list(book.leaves.values_list("number", flat=True)) == ["0042", "0043", "0044"]
    book2 = _book(w, first="SH-099", count=2, label="دوم")
    assert list(book2.leaves.values_list("number", flat=True)) == ["SH-099", "SH-100"]


def test_overlapping_book_is_rejected_and_names_the_collision():
    w = build_world()
    _book(w)
    with pytest.raises(ValidationError, match="1010"):
        _book(w, first="1010", count=5, label="متداخل")
    assert ChequeBook.objects.filter(company=w.company).count() == 1
    assert ChequeLeaf.objects.filter(company=w.company).count() == 25


def test_book_creation_validation():
    w = build_world()
    with pytest.raises(ValidationError, match="خزانه بانکی هستند"):
        _book(w, account=w.cash_treasury)
    with pytest.raises(ValidationError, match="به یک برگ نیاز دارد"):
        _book(w, count=0)
    with pytest.raises(ValidationError, match="1000"):
        _book(w, count=1001)
    with pytest.raises(ValidationError, match="با رقم پایان یابد"):
        _book(w, first="ABC", count=2)
    # A digit-less first number is fine for a one-leaf book.
    single = _book(w, first="ABC", count=1, label="تکی")
    assert list(single.leaves.values_list("number", flat=True)) == ["ABC"]


# ---------------------------------------------------------------------------
# Consumption inside create_payment
# ---------------------------------------------------------------------------


def test_issued_cheque_consumes_its_leaf():
    w = build_world()
    book = _book(w)
    leaf = _leaf(book, "1001")
    payment = _issue_payment(w, leaf=leaf)
    cheque = payment.cheques.get()
    assert cheque.cheque_number == "1001"
    assert cheque.direction == "ISSUED"
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.USED
    assert leaf.cheque_id == cheque.id
    assert cheque.leaf.id == leaf.id
    assert cheque_books.book_counts(book) == (24, 1, 0)


def test_entered_number_matching_the_leaf_is_accepted_conflict_rejected():
    w = build_world()
    book = _book(w)
    ok_leaf = _leaf(book, "1001")
    payment = _issue_payment(w, leaf=ok_leaf, cheque_number="1001")
    assert payment.cheques.get().cheque_number == "1001"

    leaf = _leaf(book, "1002")
    with pytest.raises(ValidationError, match="مطابقت ندارد"):
        _issue_payment(w, leaf=leaf, cheque_number="9999")
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.UNUSED
    assert Cheque.objects.filter(company=w.company).count() == 1


def test_a_used_leaf_cannot_be_consumed_twice():
    w = build_world()
    book = _book(w)
    leaf = _leaf(book, "1001")
    _issue_payment(w, leaf=leaf)
    with pytest.raises(ValidationError, match="USED"):
        _issue_payment(w, leaf=leaf)
    assert Cheque.objects.filter(company=w.company).count() == 1


def test_leaf_of_another_account_is_rejected():
    from apps.treasury.tests._helpers import _acct

    w = build_world()
    other_gl = _acct(w.company, "1120", "Bank 2", "ASSET", "DEBIT")
    other_bank = services.create_treasury_account(
        company=w.company, kind="BANK", name="Second bank", gl_account=other_gl, bank_name="Saderat"
    )
    book = _book(w, account=other_bank)
    leaf = _leaf(book, "1001")
    with pytest.raises(ValidationError, match="حساب بانکی دیگری"):
        _issue_payment(w, leaf=leaf)  # payment draws on w.bank_treasury
    assert Cheque.objects.filter(company=w.company).count() == 0


def test_leaf_is_rejected_for_receipts_and_non_cheque_methods():
    w = build_world()
    book = _book(w)
    leaf = _leaf(book, "1001")
    with pytest.raises(ValidationError, match="دریافتی کاغذ"):
        services.create_payment(
            company=w.company,
            direction="RECEIPT",
            party=w.customer,
            treasury_account=w.bank_treasury,
            amount="100",
            payment_date=DAY,
            method="CHEQUE",
            cheque={"bank_name": "Melli", "cheque_number": "1001", "due_date": DAY},
            leaf=leaf,
        )
    with pytest.raises(ValidationError, match="پرداخت با چک"):
        services.create_payment(
            company=w.company,
            direction="PAYMENT",
            party=w.supplier,
            treasury_account=w.bank_treasury,
            amount="100",
            payment_date=DAY,
            method="CASH",
            leaf=leaf,
        )
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.UNUSED
    assert Cheque.objects.filter(company=w.company).count() == 0


def test_cheque_without_leaf_behaves_exactly_as_before():
    w = build_world()
    payment = _issue_payment(w, cheque_number="777")
    cheque = payment.cheques.get()
    assert cheque.cheque_number == "777"
    assert not hasattr(cheque, "leaf") or getattr(cheque, "leaf", None) is None
    assert ChequeLeaf.objects.filter(company=w.company).count() == 0


# ---------------------------------------------------------------------------
# Void + lifecycle: nothing resurrects a used leaf
# ---------------------------------------------------------------------------


def test_void_leaf_rules():
    w = build_world()
    book = _book(w)
    leaf = _leaf(book, "1001")
    cheque_books.void_leaf(leaf)
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.VOID
    assert cheque_books.book_counts(book) == (24, 0, 1)
    with pytest.raises(ValidationError, match="قابل ابطال است"):
        cheque_books.void_leaf(leaf)
    used = _leaf(book, "1002")
    _issue_payment(w, leaf=used)
    with pytest.raises(ValidationError, match="قابل ابطال است"):
        cheque_books.void_leaf(used)


def _post_issued(w, payment):
    return services.post_payment(
        payment,
        gl_accounts={"payable": w.ap, "cheques_payable": w.cheques_payable},
    )


def test_bounce_of_an_issued_cheque_keeps_the_leaf_used():
    w = build_world()
    book = _book(w)
    leaf = _leaf(book, "1001")
    payment = _post_issued(w, _issue_payment(w, leaf=leaf))
    cheque = payment.cheques.get()
    services.bounce_cheque(cheque)
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.USED
    assert leaf.cheque_id == cheque.id


def test_payment_reversal_keeps_the_leaf_used():
    w = build_world()
    book = _book(w)
    leaf = _leaf(book, "1001")
    payment = _post_issued(w, _issue_payment(w, leaf=leaf))
    services.reverse_payment(payment)
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.USED
    assert payment.cheques.get().status == Cheque.Status.REVERSED


def test_mixed_counts_after_use_and_void():
    w = build_world()
    book = _book(w)
    for number in ("1001", "1002", "1003"):
        _issue_payment(w, leaf=_leaf(book, number))
    cheque_books.void_leaf(_leaf(book, "1004"))
    assert cheque_books.book_counts(book) == (21, 3, 1)
    annotated = cheque_books.cheque_books_with_counts(company=w.company).get(pk=book.pk)
    assert annotated.unused_count == 21
    assert annotated.used_count == 3
    assert annotated.void_count == 1
    assert annotated.total_count == 25


# ---------------------------------------------------------------------------
# Statement chaining prefill (Part 2)
# ---------------------------------------------------------------------------


def _statement(w, start, end, closing, *, complete=False):
    statement = reconciliation.create_statement(
        company=w.company,
        treasury_account=w.bank_treasury,
        start_date=start,
        end_date=end,
        opening_balance="0",
        closing_balance=closing,
    )
    if complete:
        # No lines and a closing equal to the (zero) book balance:
        # difference is zero, so completion is legal.
        reconciliation.complete_statement(statement)
    return statement


def test_suggested_opening_is_none_without_a_completed_statement():
    w = build_world()
    assert reconciliation.suggested_statement_opening(w.bank_treasury) is None
    _statement(w, date(2026, 6, 1), date(2026, 6, 30), "0")
    assert reconciliation.suggested_statement_opening(w.bank_treasury) is None


def test_suggested_opening_comes_from_the_latest_completed_statement():
    w = build_world()
    _statement(w, date(2026, 6, 1), date(2026, 6, 30), "0", complete=True)
    # A later OPEN statement must not shadow the completed one.
    _statement(w, date(2026, 7, 1), date(2026, 7, 31), "0")
    suggestion = reconciliation.suggested_statement_opening(w.bank_treasury)
    assert suggestion == (date(2026, 6, 30), Decimal("0"))
