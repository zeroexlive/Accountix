"""Sprint 12 — treasury through the UI (scope E, ADR-039).

Accounts, payments, allocations and cheque transitions all go
through ``treasury.services``; the invoice ``payment_status`` moves
only via the service recompute (ADR-024) and allocations are voided,
never deleted (ADR-025). Cheques sit in-hand until cleared (ADR-026).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounting import reporting as acct_reporting
from apps.organizations.models import CompanyMembership
from apps.treasury.models import Cheque, Payment, PaymentAllocation, TreasuryAccount
from apps.treasury.tests._helpers import DAY, D, build_world, post_purchase, post_sale

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="x")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _gl_balance(w, code):
    tb = acct_reporting.trial_balance(w.company)
    for row in tb["rows"]:
        if row["code"] == code:
            return row["balance"]
    return D("0")


def _payment_payload(w, **overrides):
    payload = {
        "company": str(w.company.pk),
        "direction": "RECEIPT",
        "party": str(w.customer.pk),
        "treasury_account": str(w.cash_treasury.pk),
        "method": "CASH",
        "amount": "1100",
        "payment_date": DAY.isoformat(),
        "reference": "",
        "description": "",
        "cheque_bank_name": "",
        "cheque_number": "",
        "sayad_id": "",
        "cheque_issue_date": "",
        "cheque_due_date": "",
    }
    payload.update(overrides)
    return payload


def _create_and_post_receipt(client, w, **overrides):
    resp = client.post(reverse("payment_create"), _payment_payload(w, **overrides))
    payment = Payment.objects.get(company=w.company, party=w.customer)
    assert resp.status_code == 302
    assert payment.status == "DRAFT"
    post = {"receivable": str(w.ar.pk)}
    if overrides.get("method") == "CHEQUE":
        post["cheques_in_hand"] = str(w.cheques_in_hand.pk)
    resp = client.post(reverse("payment_post", args=[payment.pk]), post)
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.status == "POSTED"
    return payment


def test_treasury_account_create_via_ui(client):
    w = build_world()
    _member_client(client, w.company)
    resp = client.post(
        reverse("treasury_account_create"),
        {
            "company": str(w.company.pk),
            "kind": "BANK",
            "name": "Second bank",
            "bank_name": "Saderat",
            "account_number": "010203",
            "gl_account": str(w.bank.pk),
        },
    )
    assert resp.status_code == 302
    account = TreasuryAccount.objects.get(company=w.company, name="Second bank")
    assert account.kind == "BANK"
    assert account.gl_account_id == w.bank.pk


def test_receipt_allocate_marks_invoice_paid(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)
    sale = post_sale(w)
    assert sale.payment_status == "UNPAID"
    payment = _create_and_post_receipt(client, w)
    resp = client.post(reverse("payment_allocate", args=[payment.pk]), {"amount_0": "1100"})
    assert resp.status_code == 302
    sale.refresh_from_db()
    assert sale.payment_status == "PAID"
    allocation = PaymentAllocation.objects.get(payment=payment)
    assert allocation.amount == D("1100")
    assert allocation.status == "ACTIVE"


def test_over_allocation_rejected_invoice_stays_unpaid(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)
    sale = post_sale(w)
    payment = _create_and_post_receipt(client, w)
    resp = client.post(
        reverse("payment_allocate", args=[payment.pk]), {"amount_0": "1200"}, follow=True
    )
    assert resp.status_code == 200
    assert [str(m) for m in resp.context["messages"]]
    sale.refresh_from_db()
    assert sale.payment_status == "UNPAID"
    assert not PaymentAllocation.objects.filter(payment=payment).exists()


def test_void_allocation_reopens_invoice(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)
    sale = post_sale(w)
    payment = _create_and_post_receipt(client, w)
    client.post(reverse("payment_allocate", args=[payment.pk]), {"amount_0": "1100"})
    allocation = PaymentAllocation.objects.get(payment=payment)
    resp = client.post(
        reverse("allocation_void", args=[payment.pk, allocation.pk]), {"reason": "mistake"}
    )
    assert resp.status_code == 302
    allocation.refresh_from_db()
    assert allocation.status == "VOID"
    sale.refresh_from_db()
    assert sale.payment_status == "UNPAID"


def test_payment_reverse_voids_allocations(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)
    sale = post_sale(w)
    payment = _create_and_post_receipt(client, w)
    client.post(reverse("payment_allocate", args=[payment.pk]), {"amount_0": "1100"})
    resp = client.post(reverse("payment_reverse", args=[payment.pk]), {"reason": "returned"})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.status == "REVERSED"
    sale.refresh_from_db()
    assert sale.payment_status == "UNPAID"
    assert _gl_balance(w, "1100") == D("0")  # cash receipt fully reversed


def test_cheque_receipt_sits_in_hand_then_clears(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)
    sale = post_sale(w)
    payment = _create_and_post_receipt(
        client,
        w,
        method="CHEQUE",
        cheque_bank_name="Melli",
        cheque_number="CHQ-1",
        cheque_due_date="2026-06-20",
    )
    cheque = Cheque.objects.get(payment=payment)
    assert cheque.status == "RECEIVED"
    # In-hand is not money: bank and cash unchanged, holding account up.
    assert _gl_balance(w, "1110") == D("0")
    assert _gl_balance(w, "1150") == D("1100")
    client.post(reverse("payment_allocate", args=[payment.pk]), {"amount_0": "1100"})
    sale.refresh_from_db()
    assert sale.payment_status == "PAID"

    resp = client.post(
        reverse("cheque_clear", args=[cheque.pk]),
        {"bank_treasury_account": str(w.bank_treasury.pk), "clearing_date": "2026-06-21"},
    )
    assert resp.status_code == 302
    cheque.refresh_from_db()
    assert cheque.status == "CLEARED"
    assert _gl_balance(w, "1110") == D("1100")
    assert _gl_balance(w, "1150") == D("0")
    sale.refresh_from_db()
    assert sale.payment_status == "PAID"


def test_cheque_bounce_reopens_invoice(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)
    sale = post_sale(w)
    payment = _create_and_post_receipt(
        client,
        w,
        method="CHEQUE",
        cheque_bank_name="Melli",
        cheque_number="CHQ-2",
        cheque_due_date="2026-06-20",
    )
    cheque = Cheque.objects.get(payment=payment)
    client.post(reverse("payment_allocate", args=[payment.pk]), {"amount_0": "1100"})
    sale.refresh_from_db()
    assert sale.payment_status == "PAID"
    resp = client.post(reverse("cheque_bounce", args=[cheque.pk]), {"bounce_date": "2026-06-22"})
    assert resp.status_code == 302
    cheque.refresh_from_db()
    assert cheque.status == "BOUNCED"
    sale.refresh_from_db()
    assert sale.payment_status == "UNPAID"
    assert _gl_balance(w, "1150") == D("0")


def test_supplier_payment_allocates_to_purchase(client):
    w = build_world()
    _member_client(client, w.company)
    purchase = post_purchase(w)
    resp = client.post(
        reverse("payment_create"),
        _payment_payload(w, direction="PAYMENT", party=str(w.supplier.pk)),
    )
    payment = Payment.objects.get(company=w.company, party=w.supplier)
    assert resp.status_code == 302
    resp = client.post(reverse("payment_post", args=[payment.pk]), {"payable": str(w.ap.pk)})
    assert resp.status_code == 302
    resp = client.post(reverse("payment_allocate", args=[payment.pk]), {"amount_0": "1100"})
    assert resp.status_code == 302
    purchase.refresh_from_db()
    assert purchase.payment_status == "PAID"


def test_treasury_non_member_access_is_404(client):
    w = build_world()
    _member_client(client, w.company)
    payment = _create_and_post_receipt(client, w)
    outsider = User.objects.create_user(username="outsider", password="x")
    client.force_login(outsider)
    resp = client.get(reverse("payment_detail", args=[payment.pk]))
    assert resp.status_code == 404
    resp = client.post(reverse("payment_create"), _payment_payload(w))
    assert resp.status_code == 404
    assert Payment.objects.filter(company=w.company).count() == 1
