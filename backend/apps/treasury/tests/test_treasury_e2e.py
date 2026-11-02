"""Treasury end-to-end test (Sprint 06).

Replays the Sprint 05 MVP chain and then settles it the real way:

    purchase (stock in, AP up) -> sale (stock out, COGS, AR up)
      -> pay the supplier PARTIALLY by bank transfer
      -> receive the customer's money as a CHEQUE, allocate it,
         deposit it, clear it
      -> trial balance balanced; AP/AR subledgers reconcile;
         payment_status values match the allocations exactly.

This replaces the MVP test's manual-journal payment stub: here the
receipt is a real Payment with a real allocation, and the sales
invoice's payment_status is asserted to move - by treasury, the only
writer allowed to move it (ADR-024).
"""

from datetime import date

import pytest

from apps.accounting import reporting as acct_reporting
from apps.purchases import reporting as purchase_reporting
from apps.sales import reporting as sales_reporting
from apps.treasury import services as svc
from apps.treasury.tests._helpers import DAY, D, build_world, post_purchase, post_sale

pytestmark = pytest.mark.django_db


def test_treasury_end_to_end():
    w = build_world()
    purchase = post_purchase(w)  # grand 1100, AP 1100
    sale = post_sale(w)  # grand 1100, AR 1100, stock 6/600

    # -- Pay the supplier partially (500 of 1100) by bank transfer ----------
    pay = svc.create_payment(
        company=w.company,
        direction="PAYMENT",
        party=w.supplier,
        treasury_account=w.bank_treasury,
        amount=D("500"),
        payment_date=DAY,
        method="BANK_TRANSFER",
    )
    pay = svc.post_payment(pay, gl_accounts={"payable": w.ap})
    svc.allocate_payment(pay, purchase, D("500"))
    purchase.refresh_from_db()
    assert purchase.payment_status == "PARTIALLY_PAID"
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("600")

    # -- Receive the customer's 1100 as a cheque, allocate, clear -----------
    receipt = svc.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.bank_treasury,
        amount=D("1100"),
        payment_date=DAY,
        method="CHEQUE",
        cheque={
            "bank_name": "Melli",
            "cheque_number": "E2E-1",
            "due_date": date(2026, 6, 20),
            "sayad_id": "SY-E2E",
        },
    )
    receipt = svc.post_payment(
        receipt, gl_accounts={"receivable": w.ar, "cheques_in_hand": w.cheques_in_hand}
    )
    cheque = receipt.cheques.first()
    svc.allocate_payment(receipt, sale, D("1100"))
    svc.deposit_cheque(cheque)
    svc.clear_cheque(cheque, bank_treasury_account=w.bank_treasury)

    sale.refresh_from_db()
    cheque.refresh_from_db()
    assert sale.payment_status == "PAID"
    assert cheque.status == "CLEARED"

    # -- Reconciliations ------------------------------------------------------
    tb = acct_reporting.trial_balance(w.company)
    assert tb["is_balanced"]
    assert tb["total_debit"] == tb["total_credit"]
    # AR fully settled by the cleared cheque; AP still owes 600.
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("0")
    assert sales_reporting.ar_total(w.company, w.ar) == D("0")
    assert acct_reporting.account_balance(w.company, w.ar) == D("0")
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("600")
    assert purchase_reporting.ap_total(w.company, w.ap) == D("600")
    # Bank: -500 supplier payment + 1100 cleared cheque = +600.
    assert acct_reporting.account_balance(w.company, w.bank) == D("600")
    assert acct_reporting.account_balance(w.company, w.cheques_in_hand) == D("0")
    # Outstanding cheques register is empty now.
    from apps.treasury import reporting as treasury_reporting

    assert list(treasury_reporting.outstanding_cheques(w.company)) == []
