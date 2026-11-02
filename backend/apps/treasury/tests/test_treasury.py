"""Treasury tests (Sprint 06): payments, allocations, payment_status,
cheques, and the guard rails around all of them."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.accounting import reporting as acct_reporting
from apps.purchases import reporting as purchase_reporting
from apps.sales import reporting as sales_reporting
from apps.treasury import reporting as treasury_reporting
from apps.treasury import services as svc
from apps.treasury.models import PaymentAllocation
from apps.treasury.tests._helpers import DAY, D, build_world, post_purchase, post_sale

pytestmark = pytest.mark.django_db


def _receipt(w, amount, *, method="CASH", party=None, treasury=None, cheque=None):
    return svc.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=party or w.customer,
        treasury_account=treasury or w.cash_treasury,
        amount=D(amount),
        payment_date=DAY,
        method=method,
        cheque=cheque,
    )


def _post_receipt(w, payment):
    return svc.post_payment(payment, gl_accounts={"receivable": w.ar})


# ---------------------------------------------------------------------------
# Payments + allocations
# ---------------------------------------------------------------------------


def test_receipt_full_allocation_pays_invoice_and_zeroes_ar():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment = _post_receipt(w, _receipt(w, "1100"))
    svc.allocate_payment(payment, sale, D("1100"))
    sale.refresh_from_db()
    assert sale.payment_status == "PAID"
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("0")
    assert acct_reporting.account_balance(w.company, w.cash) == D("1100")
    assert treasury_reporting.invoice_outstanding(sale) == D("0")


def test_partial_allocations_move_through_partially_paid():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    p1 = _post_receipt(w, _receipt(w, "500"))
    svc.allocate_payment(p1, sale, D("500"))
    sale.refresh_from_db()
    assert sale.payment_status == "PARTIALLY_PAID"
    p2 = _post_receipt(w, _receipt(w, "600"))
    svc.allocate_payment(p2, sale, D("600"))
    sale.refresh_from_db()
    assert sale.payment_status == "PAID"


def test_over_allocation_to_invoice_rejected():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment = _post_receipt(w, _receipt(w, "1500"))
    with pytest.raises(ValidationError):
        svc.allocate_payment(payment, sale, D("1101"))


def test_allocation_beyond_payment_amount_rejected():
    w = build_world()
    post_purchase(w)
    sale1 = post_sale(w, "SINV-1")
    sale2 = post_sale(w, "SINV-2")
    payment = _post_receipt(w, _receipt(w, "1100"))
    svc.allocate_payment(payment, sale1, D("1100"))
    with pytest.raises(ValidationError):
        svc.allocate_payment(payment, sale2, D("1"))


def test_allocation_party_mismatch_rejected():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment = _post_receipt(w, _receipt(w, "100", party=w.customer2))
    with pytest.raises(ValidationError):
        svc.allocate_payment(payment, sale, D("100"))


def test_allocation_on_draft_payment_rejected():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment = _receipt(w, "100")
    with pytest.raises(ValidationError):
        svc.allocate_payment(payment, sale, D("100"))


def test_supplier_payment_pays_purchase_invoice_and_zeroes_ap():
    w = build_world()
    purchase = post_purchase(w)
    payment = svc.create_payment(
        company=w.company,
        direction="PAYMENT",
        party=w.supplier,
        treasury_account=w.bank_treasury,
        amount=D("1100"),
        payment_date=DAY,
        method="BANK_TRANSFER",
    )
    payment = svc.post_payment(payment, gl_accounts={"payable": w.ap})
    svc.allocate_payment(payment, purchase, D("1100"))
    purchase.refresh_from_db()
    assert purchase.payment_status == "PAID"
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("0")
    assert acct_reporting.account_balance(w.company, w.bank) == D("-1100")


def test_unallocated_remainder_stays_on_account():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment = _post_receipt(w, _receipt(w, "1100"))
    svc.allocate_payment(payment, sale, D("400"))
    sale.refresh_from_db()
    assert sale.payment_status == "PARTIALLY_PAID"
    assert svc.allocated_total_for_payment(payment) == D("400")
    assert payment.amount - svc.allocated_total_for_payment(payment) == D("700")
    # Open items still show the invoice with 700 outstanding.
    items = treasury_reporting.open_items(w.company, party=w.customer)
    assert len(items) == 1 and items[0]["outstanding"] == D("700")


def test_reverse_payment_restores_unpaid_and_subledger():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment = _post_receipt(w, _receipt(w, "1100"))
    svc.allocate_payment(payment, sale, D("1100"))
    svc.reverse_payment(payment, reason="entered in error")
    sale.refresh_from_db()
    payment.refresh_from_db()
    assert sale.payment_status == "UNPAID"
    assert payment.status == "REVERSED"
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("1100")
    assert acct_reporting.account_balance(w.company, w.cash) == D("0")
    # Allocation history is kept as VOID, not deleted (ADR-025).
    allocations = PaymentAllocation.objects.filter(payment=payment)
    assert allocations.count() == 1 and allocations.first().status == "VOID"


def test_repost_is_idempotent():
    w = build_world()
    payment = _post_receipt(w, _receipt(w, "100"))
    again = svc.post_payment(payment, gl_accounts={"receivable": w.ar})
    assert again.journal_entry_id == payment.journal_entry_id
    assert acct_reporting.account_balance(w.company, w.cash) == D("100")


def test_payment_status_field_is_the_only_mutable_one_on_posted_invoice():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    # payment_status alone may change on a POSTED invoice (ADR-024)...
    sale.payment_status = "PARTIALLY_PAID"
    sale.save()
    # ...but any other field may not.
    sale.description = "tampered"
    with pytest.raises(ValidationError):
        sale.save()


def test_closed_period_payment_rejected():
    w = build_world(period_status="CLOSED", company_name="Closed Co")
    payment = svc.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.cash_treasury,
        amount=D("100"),
        payment_date=DAY,
    )
    with pytest.raises(ValidationError):
        svc.post_payment(payment, gl_accounts={"receivable": w.ar})
    payment.refresh_from_db()
    assert payment.status == "DRAFT" and payment.journal_entry_id is None


def test_cross_company_allocation_rejected():
    w = build_world()
    other = build_world(company_name="Other Co")
    post_purchase(other)
    sale_other = post_sale(other)
    payment = _post_receipt(w, _receipt(w, "100"))
    with pytest.raises(ValidationError):
        svc.allocate_payment(payment, sale_other, D("100"))


def test_cross_company_treasury_account_rejected_at_creation():
    w = build_world()
    other = build_world(company_name="Other Co")
    with pytest.raises(ValidationError):
        svc.create_payment(
            company=w.company,
            direction="RECEIPT",
            party=w.customer,
            treasury_account=other.cash_treasury,
            amount=D("100"),
            payment_date=DAY,
        )


def test_bank_treasury_account_needs_bank_name():
    w = build_world()
    with pytest.raises(ValidationError):
        svc.create_treasury_account(
            company=w.company, kind="BANK", name="No-name bank", gl_account=w.bank
        )


# ---------------------------------------------------------------------------
# Cheques
# ---------------------------------------------------------------------------


def _cheque_receipt(w, amount="1100", number="CHQ-1"):
    payment = svc.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.bank_treasury,
        amount=D(amount),
        payment_date=DAY,
        method="CHEQUE",
        cheque={
            "bank_name": "Melli",
            "cheque_number": number,
            "due_date": date(2026, 6, 15),
            "sayad_id": "SY-123",
        },
    )
    payment = svc.post_payment(
        payment, gl_accounts={"receivable": w.ar, "cheques_in_hand": w.cheques_in_hand}
    )
    return payment, payment.cheques.first()


def test_received_cheque_is_in_hand_not_bank_until_cleared():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment, cheque = _cheque_receipt(w)
    # Value sits in cheques-in-hand; the bank has not moved.
    assert acct_reporting.account_balance(w.company, w.cheques_in_hand) == D("1100")
    assert acct_reporting.account_balance(w.company, w.bank) == D("0")
    svc.allocate_payment(payment, sale, D("1100"))
    svc.deposit_cheque(cheque)
    cheque.refresh_from_db()
    assert cheque.status == "DEPOSITED"
    svc.clear_cheque(cheque, bank_treasury_account=w.bank_treasury)
    cheque.refresh_from_db()
    sale.refresh_from_db()
    assert cheque.status == "CLEARED"
    assert acct_reporting.account_balance(w.company, w.bank) == D("1100")
    assert acct_reporting.account_balance(w.company, w.cheques_in_hand) == D("0")
    assert sale.payment_status == "PAID"
    # Illegal: clearing an already-cleared cheque.
    with pytest.raises(ValidationError):
        svc.clear_cheque(cheque, bank_treasury_account=w.bank_treasury)


def test_bounced_cheque_restores_receivable_and_unpaid():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment, cheque = _cheque_receipt(w)
    svc.allocate_payment(payment, sale, D("1100"))
    sale.refresh_from_db()
    assert sale.payment_status == "PAID"
    svc.bounce_cheque(cheque)
    cheque.refresh_from_db()
    sale.refresh_from_db()
    assert cheque.status == "BOUNCED"
    assert sale.payment_status == "UNPAID"
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("1100")
    assert acct_reporting.account_balance(w.company, w.cheques_in_hand) == D("0")
    # Illegal: clearing a bounced cheque.
    with pytest.raises(ValidationError):
        svc.clear_cheque(cheque, bank_treasury_account=w.bank_treasury)
    # And the payment of a bounced cheque cannot be reversed (would
    # double-count the bounce journal).
    with pytest.raises(ValidationError):
        svc.reverse_payment(payment)


def test_returned_cheque_restores_receivable():
    w = build_world()
    post_purchase(w)
    sale = post_sale(w)
    payment, cheque = _cheque_receipt(w)
    svc.allocate_payment(payment, sale, D("1100"))
    svc.return_cheque(cheque)
    cheque.refresh_from_db()
    sale.refresh_from_db()
    assert cheque.status == "RETURNED"
    assert sale.payment_status == "UNPAID"
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("1100")


def test_issued_cheque_posts_to_cheques_payable_then_clears_against_bank():
    w = build_world()
    purchase = post_purchase(w)
    payment = svc.create_payment(
        company=w.company,
        direction="PAYMENT",
        party=w.supplier,
        treasury_account=w.bank_treasury,
        amount=D("1100"),
        payment_date=DAY,
        method="CHEQUE",
        cheque={"bank_name": "Melli", "cheque_number": "ISS-1", "due_date": date(2026, 7, 1)},
    )
    payment = svc.post_payment(
        payment, gl_accounts={"payable": w.ap, "cheques_payable": w.cheques_payable}
    )
    cheque = payment.cheques.first()
    assert cheque.status == "DELIVERED"
    # AP settled via the holding account; the bank has not moved yet.
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("0")
    assert acct_reporting.account_balance(w.company, w.cheques_payable) == D("-1100")
    assert acct_reporting.account_balance(w.company, w.bank) == D("0")
    svc.allocate_payment(payment, purchase, D("1100"))
    svc.clear_cheque(cheque)
    cheque.refresh_from_db()
    purchase.refresh_from_db()
    assert cheque.status == "CLEARED"
    assert acct_reporting.account_balance(w.company, w.cheques_payable) == D("0")
    assert acct_reporting.account_balance(w.company, w.bank) == D("-1100")
    assert purchase.payment_status == "PAID"
