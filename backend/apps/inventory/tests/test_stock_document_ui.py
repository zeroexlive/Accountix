"""Sprint 14 — stock documents through the UI.

Receipts, issues and transfers are created as drafts from the form
(header + line formset), then posted from the detail page; the GL
journal is opt-in per ADR-013 (both accounts or neither). Numbers:
receipt 10 @ 100 -> 10/1000; issue 4 -> 6/600; transfer 3 ->
WH1 3/300 + WH2 3/300 with the total value preserved at 600.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.inventory import reporting
from apps.inventory.models import StockDocument, Warehouse
from apps.organizations.models import CompanyMembership
from apps.treasury.tests._helpers import build_world

User = get_user_model()
pytestmark = pytest.mark.django_db
D = Decimal


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="<redacted>")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _create_doc(
    client,
    w,
    *,
    doc_type,
    quantity,
    unit_cost="",
    warehouse=None,
    destination=None,
    purpose="NORMAL",
    doc_date="2026-06-01",
):
    payload = {
        "company": str(w.company.pk),
        "doc_type": doc_type,
        "purpose": purpose,
        "warehouse": str((warehouse or w.warehouse).pk),
        "destination_warehouse": str(destination.pk) if destination else "",
        "doc_date": doc_date,
        "description": "",
        "lines-TOTAL_FORMS": "1",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "1",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-product": str(w.product.pk),
        "lines-0-unit": "",
        "lines-0-quantity": str(quantity),
        "lines-0-unit_cost": str(unit_cost),
    }
    resp = client.post(reverse("stock_document_create"), payload)
    assert resp.status_code == 302, resp.content[:500]
    return StockDocument.objects.filter(company=w.company).latest("created_at")


def _balance(w, warehouse):
    return reporting.stock_balance(w.company, warehouse, w.product)


def test_stock_document_ui_flow_with_and_without_gl(client):
    w = build_world()
    _member_client(client, w.company)
    wh2 = Warehouse.objects.create(company=w.company, code="WH2", name="Second warehouse")

    # Receipt WITH the GL pair: stock 10/1000 and a journal.
    doc = _create_doc(client, w, doc_type="RECEIPT", quantity=10, unit_cost=100)
    assert doc.status == "DRAFT"
    resp = client.post(
        reverse("stock_document_post", args=[doc.pk]),
        {"inventory_account": str(w.inventory.pk), "offset_account": str(w.ap.pk)},
    )
    assert resp.status_code == 302
    doc.refresh_from_db()
    assert doc.status == "POSTED"
    assert doc.journal_entry is not None
    inv_line = doc.journal_entry.lines.get(account=w.inventory)
    assert inv_line.debit == D("1000") and inv_line.credit == D("0")
    assert _balance(w, w.warehouse) == {
        "quantity": D("10"),
        "value": D("1000"),
        "average_cost": D("100"),
    }

    # Issue 4 without GL accounts: 6/600, no journal.
    issue = _create_doc(client, w, doc_type="ISSUE", quantity=4, doc_date="2026-06-02")
    resp = client.post(reverse("stock_document_post", args=[issue.pk]), {})
    assert resp.status_code == 302
    issue.refresh_from_db()
    assert issue.status == "POSTED" and issue.journal_entry is None
    balance = _balance(w, w.warehouse)
    assert balance["quantity"] == D("6") and balance["value"] == D("600")

    # Transfer 3 to WH2: WH1 3/300, WH2 3/300, total value preserved.
    transfer = _create_doc(
        client, w, doc_type="TRANSFER", quantity=3, destination=wh2, doc_date="2026-06-03"
    )
    resp = client.post(reverse("stock_document_post", args=[transfer.pk]), {})
    assert resp.status_code == 302
    transfer.refresh_from_db()
    assert transfer.status == "POSTED"
    wh1 = _balance(w, w.warehouse)
    wh2_balance = _balance(w, wh2)
    assert wh1["quantity"] == D("3") and wh1["value"] == D("300")
    assert wh2_balance["quantity"] == D("3") and wh2_balance["value"] == D("300")
    assert wh1["value"] + wh2_balance["value"] == D("600")

    # Reversing the transfer restores WH1 and empties WH2.
    resp = client.post(reverse("stock_document_reverse", args=[transfer.pk]))
    assert resp.status_code == 302
    transfer.refresh_from_db()
    assert transfer.status == "REVERSED"
    assert _balance(w, w.warehouse)["quantity"] == D("6")
    assert _balance(w, wh2)["quantity"] == D("0")


def test_stock_document_ui_receipt_without_gl_has_no_journal(client):
    w = build_world()
    _member_client(client, w.company)
    doc = _create_doc(client, w, doc_type="RECEIPT", quantity=5, unit_cost=50)
    resp = client.post(reverse("stock_document_post", args=[doc.pk]), {})
    assert resp.status_code == 302
    doc.refresh_from_db()
    assert doc.status == "POSTED" and doc.journal_entry is None
    assert _balance(w, w.warehouse)["value"] == D("250")


def test_stock_document_ui_opening_stock_purpose(client):
    w = build_world()
    _member_client(client, w.company)
    doc = _create_doc(
        client, w, doc_type="RECEIPT", quantity=20, unit_cost=150, purpose="OPENING_STOCK"
    )
    assert doc.doc_type == "RECEIPT"
    assert doc.source_type == "opening_stock"


def test_stock_document_ui_oversell_issue_rejected(client):
    w = build_world()
    _member_client(client, w.company)
    doc = _create_doc(client, w, doc_type="RECEIPT", quantity=6, unit_cost=100)
    client.post(reverse("stock_document_post", args=[doc.pk]), {})
    issue = _create_doc(client, w, doc_type="ISSUE", quantity=7, doc_date="2026-06-02")
    resp = client.post(reverse("stock_document_post", args=[issue.pk]), {}, follow=True)
    assert resp.status_code == 200
    issue.refresh_from_db()
    assert issue.status == "DRAFT"
    assert "کافی نیست: درخواستی" in resp.content.decode()
    assert _balance(w, w.warehouse)["quantity"] == D("6")


def test_stock_document_ui_non_member_404(client):
    w = build_world()
    other = build_world(company_name="Other Co")
    _member_client(client, w.company, username="owner-w")
    doc = _create_doc(client, w, doc_type="RECEIPT", quantity=1, unit_cost=10)
    # A member of the other company sees nothing of it.
    _member_client(client, other.company, username="owner-other")
    assert client.get(reverse("stock_document_detail", args=[doc.pk])).status_code == 404
    assert client.post(reverse("stock_document_post", args=[doc.pk]), {}).status_code == 404
    assert client.post(reverse("stock_document_reverse", args=[doc.pk])).status_code == 404
