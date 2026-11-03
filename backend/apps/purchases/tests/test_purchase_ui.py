"""Sprint 12 — purchase invoices and returns through the UI (scope C).

Create produces a DRAFT through the service; posting goes through
the existing atomic stock + AP service with per-document GL accounts
(ADR-011). Assertions are numeric: stock quantities/values and the
AP subledger (ADR-015).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.inventory import reporting as inv_reporting
from apps.organizations.models import CompanyMembership
from apps.purchases import reporting as purchase_reporting
from apps.purchases.models import PurchaseInvoice, PurchaseReturn
from apps.treasury.tests._helpers import DAY, D, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="x")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _create_payload(w, **line_overrides):
    line = {
        "product": str(w.product.pk),
        "unit": "",
        "quantity": "10",
        "unit_cost": "100",
        "discount_amount": "0",
        "tax_rate": "0.1",
    }
    line.update(line_overrides)
    payload = {
        "company": str(w.company.pk),
        "supplier": str(w.supplier.pk),
        "invoice_number": "PINV-UI-1",
        "invoice_date": DAY.isoformat(),
        "warehouse": str(w.warehouse.pk),
        "description": "",
        "lines-TOTAL_FORMS": "1",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
    }
    for field, value in line.items():
        payload[f"lines-0-{field}"] = value
    return payload


def _post_payload(w, **overrides):
    payload = {
        "payables": str(w.ap.pk),
        "inventory": str(w.inventory.pk),
        "tax": str(w.tax_in.pk),
        "expense": "",
    }
    payload.update(overrides)
    return payload


def _stock(w):
    return inv_reporting.stock_balance(w.company, w.warehouse, w.product)


def _create_and_post(client, w):
    resp = client.post(reverse("purchase_invoice_create"), _create_payload(w))
    invoice = PurchaseInvoice.objects.get(company=w.company, invoice_number="PINV-UI-1")
    assert resp.status_code == 302
    resp = client.post(reverse("purchase_invoice_post", args=[invoice.pk]), _post_payload(w))
    assert resp.status_code == 302
    invoice.refresh_from_db()
    return invoice


def test_purchase_create_and_post_via_ui(client):
    w = build_world()
    _member_client(client, w.company)
    resp = client.post(reverse("purchase_invoice_create"), _create_payload(w))
    invoice = PurchaseInvoice.objects.get(company=w.company, invoice_number="PINV-UI-1")
    assert resp.status_code == 302
    assert invoice.status == "DRAFT"
    assert _stock(w)["quantity"] == D("0")

    resp = client.post(reverse("purchase_invoice_post", args=[invoice.pk]), _post_payload(w))
    assert resp.status_code == 302
    invoice.refresh_from_db()
    assert invoice.status == "POSTED"
    assert invoice.grand_total == D("1100")
    stock = _stock(w)
    assert stock["quantity"] == D("10")
    assert stock["value"] == D("1000")
    # AP subledger: supplier owes nothing; the company owes the supplier 1100.
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("1100")


def test_purchase_post_cross_company_account_rejected(client):
    w = build_world()
    other = build_world(company_name="Other Co")
    _member_client(client, w.company)
    client.post(reverse("purchase_invoice_create"), _create_payload(w))
    invoice = PurchaseInvoice.objects.get(company=w.company, invoice_number="PINV-UI-1")
    resp = client.post(
        reverse("purchase_invoice_post", args=[invoice.pk]),
        _post_payload(w, payables=str(other.ap.pk)),
    )
    assert resp.status_code == 200  # form error, not a post
    invoice.refresh_from_db()
    assert invoice.status == "DRAFT"
    assert _stock(w)["quantity"] == D("0")


def test_purchase_return_via_ui(client):
    w = build_world()
    _member_client(client, w.company)
    invoice = _create_and_post(client, w)
    line = invoice.lines.first()
    resp = client.post(
        reverse("purchase_return_create", args=[invoice.pk]),
        {
            "return_number": "PRET-1",
            "return_date": DAY.isoformat(),
            "description": "",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-invoice_line": str(line.pk),
            "lines-0-quantity": "3",
        },
    )
    ret = PurchaseReturn.objects.get(company=w.company, return_number="PRET-1")
    assert resp.status_code == 302
    assert ret.status == "DRAFT"
    resp = client.post(
        reverse("purchase_return_post", args=[ret.pk]),
        {"payables": str(w.ap.pk), "inventory": str(w.inventory.pk)},
    )
    assert resp.status_code == 302
    ret.refresh_from_db()
    assert ret.status == "POSTED"
    stock = _stock(w)
    assert stock["quantity"] == D("7")
    assert stock["value"] == D("700")
    # Returns reverse AP at the goods value (3 @ 100 = 300), per the
    # Sprint 04 service semantics: AP falls from 1100 to 800.
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("800")


def test_purchase_return_above_remaining_rejected_at_post(client):
    """The returned-quantity cap is a posting rule of the service
    (Sprint 04): the draft may be created, posting 11 of 10 must fail
    and leave stock and AP untouched."""
    w = build_world()
    _member_client(client, w.company)
    invoice = _create_and_post(client, w)
    line = invoice.lines.first()
    resp = client.post(
        reverse("purchase_return_create", args=[invoice.pk]),
        {
            "return_number": "PRET-BIG",
            "return_date": DAY.isoformat(),
            "description": "",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-invoice_line": str(line.pk),
            "lines-0-quantity": "11",
        },
    )
    ret = PurchaseReturn.objects.get(company=w.company, return_number="PRET-BIG")
    assert resp.status_code == 302
    resp = client.post(
        reverse("purchase_return_post", args=[ret.pk]),
        {"payables": str(w.ap.pk), "inventory": str(w.inventory.pk)},
        follow=True,
    )
    ret.refresh_from_db()
    assert ret.status == "DRAFT"
    assert _stock(w)["quantity"] == D("10")
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("1100")
    messages = [str(m) for m in resp.context["messages"]]
    assert messages  # the service error was surfaced, not swallowed


def test_purchase_invoice_reverse_via_ui(client):
    w = build_world()
    _member_client(client, w.company)
    invoice = _create_and_post(client, w)
    resp = client.post(
        reverse("purchase_invoice_reverse", args=[invoice.pk]), {"reason": "entered twice"}
    )
    assert resp.status_code == 302
    invoice.refresh_from_db()
    assert invoice.status == "REVERSED"
    assert _stock(w)["quantity"] == D("0")
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("0")


def test_purchase_create_non_member_is_404(client):
    w = build_world()
    outsider = User.objects.create_user(username="outsider", password="x")
    client.force_login(outsider)
    resp = client.post(reverse("purchase_invoice_create"), _create_payload(w))
    assert resp.status_code == 404
    assert not PurchaseInvoice.objects.filter(company=w.company).exists()
