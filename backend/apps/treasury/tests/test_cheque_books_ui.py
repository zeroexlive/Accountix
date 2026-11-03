"""Sprint 15 — cheque books through the UI (ADR-042) and the
statement chaining prefill (Sprint 14 follow-up).

Books are created/voided through ``treasury.cheque_books`` services;
a payment that names a leaf consumes it inside ``create_payment``;
another company's book is a 404 everywhere.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.organizations.models import CompanyMembership
from apps.treasury import cheque_books, reconciliation
from apps.treasury.models import ChequeLeaf, Payment
from apps.treasury.tests._helpers import DAY, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="<redacted>")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _outsider_client(client, username="outsider"):
    user = User.objects.create_user(username=username, password="<redacted>")
    client.force_login(user)
    return client


def _create_book_via_ui(client, w, **overrides):
    payload = {
        "company": str(w.company.pk),
        "treasury_account": str(w.bank_treasury.pk),
        "label": "دفترچه اول",
        "first_number": "1001",
        "leaf_count": "25",
    }
    payload.update(overrides)
    return client.post(reverse("cheque_book_create"), payload)


def test_book_create_detail_and_void_via_ui(client):
    w = build_world()
    _member_client(client, w.company)
    resp = _create_book_via_ui(client, w)
    assert resp.status_code == 302
    book = w.company.cheque_books.get()
    assert resp.url == reverse("cheque_book_detail", args=[book.pk])

    resp = client.get(reverse("cheque_book_detail", args=[book.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "1001" in body and "1025" in body  # the full generated range
    assert "مصرف‌نشده" in body

    leaf = book.leaves.get(number="1007")
    resp = client.post(reverse("cheque_leaf_void", args=[leaf.pk]))
    assert resp.status_code == 302
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.VOID
    assert cheque_books.book_counts(book) == (24, 0, 1)

    resp = client.get(reverse("cheque_book_list"))
    assert resp.status_code == 200
    assert "دفترچه اول" in resp.content.decode()


def test_payment_with_leaf_via_ui_consumes_it(client):
    w = build_world()
    _member_client(client, w.company)
    book = cheque_books.create_cheque_book(
        company=w.company,
        treasury_account=w.bank_treasury,
        first_number="1001",
        leaf_count=25,
    )
    leaf = book.leaves.get(number="1003")
    resp = client.post(
        reverse("payment_create"),
        {
            "company": str(w.company.pk),
            "direction": "PAYMENT",
            "party": str(w.supplier.pk),
            "treasury_account": str(w.bank_treasury.pk),
            "method": "CHEQUE",
            "amount": "500",
            "payment_date": DAY.isoformat(),
            "reference": "",
            "description": "",
            "cheque_bank_name": "Melli",
            "cheque_number": "",
            "sayad_id": "",
            "cheque_issue_date": "",
            "cheque_due_date": DAY.isoformat(),
            "leaf": str(leaf.pk),
        },
    )
    assert resp.status_code == 302
    payment = Payment.objects.get(company=w.company)
    cheque = payment.cheques.get()
    assert cheque.cheque_number == "1003"
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.USED
    assert leaf.cheque_id == cheque.id

    # The cheque detail page names the book the leaf came from.
    resp = client.get(reverse("cheque_detail", args=[cheque.pk]))
    assert resp.status_code == 200
    assert "برگ دفترچه" in resp.content.decode()


def test_non_member_gets_404_and_cannot_consume(client):
    w = build_world()
    book = cheque_books.create_cheque_book(
        company=w.company,
        treasury_account=w.bank_treasury,
        first_number="1001",
        leaf_count=25,
    )
    leaf = book.leaves.get(number="1001")
    _outsider_client(client)

    assert client.get(reverse("cheque_book_detail", args=[book.pk])).status_code == 404
    assert client.post(reverse("cheque_leaf_void", args=[leaf.pk])).status_code == 404
    _create_book_via_ui(client, w)
    assert w.company.cheque_books.count() == 1  # nothing new was created

    client.post(
        reverse("payment_create"),
        {
            "company": str(w.company.pk),
            "direction": "PAYMENT",
            "party": str(w.supplier.pk),
            "treasury_account": str(w.bank_treasury.pk),
            "method": "CHEQUE",
            "amount": "500",
            "payment_date": DAY.isoformat(),
            "reference": "",
            "description": "",
            "cheque_bank_name": "Melli",
            "cheque_number": "",
            "sayad_id": "",
            "cheque_issue_date": "",
            "cheque_due_date": DAY.isoformat(),
            "leaf": str(leaf.pk),
        },
    )
    assert Payment.objects.filter(company=w.company).count() == 0
    leaf.refresh_from_db()
    assert leaf.status == ChequeLeaf.Status.UNUSED


def test_statement_create_prefills_from_latest_completed_statement(client):
    w = build_world()
    _member_client(client, w.company)
    statement = reconciliation.create_statement(
        company=w.company,
        treasury_account=w.bank_treasury,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        opening_balance="0",
        closing_balance="0",
    )
    reconciliation.complete_statement(statement)

    resp = client.get(reverse("bank_statement_create"), {"account": str(w.bank_treasury.pk)})
    assert resp.status_code == 200
    form = resp.context["form"]
    assert form.initial["treasury_account"] == w.bank_treasury
    assert form.initial["start_date"] == date(2026, 6, 30)
    assert form.initial["opening_balance"] == Decimal("0")

    # Without a completed statement there is no prefill beyond the account.
    w2 = build_world(company_name="Second Co")
    _member_client(client, w2.company, username="boss2")
    resp = client.get(reverse("bank_statement_create"), {"account": str(w2.bank_treasury.pk)})
    form = resp.context["form"]
    assert form.initial.get("start_date") is None
    assert form.initial.get("opening_balance") is None
