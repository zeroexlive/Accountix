"""Sprint 12 — sales invoices and returns through the UI (scope D).

Mirror of the purchase UI tests, plus the sales-specific negative:
posting an invoice for more than the available stock must surface
the service error, leave the invoice DRAFT and the stock untouched.
Returns restore stock at the original COGS (ADR-021).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.inventory import reporting as inv_reporting
from apps.organizations.models import CompanyMembership
from apps.purchases import services as purchase_services
from apps.sales import reporting as sales_reporting
from apps.sales.models import SalesInvoice, SalesReturn
from apps.treasury.tests._helpers import DAY, D, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="x")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _seed_stock(w, qty="10"):
    purchase = purchase_services.create_purchase_invoice(
        company=w.company,
        supplier=w.supplier,
        invoice_number="SEED-P",
        invoice_date=DAY,
        warehouse=w.warehouse,
        lines=[{"product": w.product, "quantity": D(qty), "unit_cost": D("100")}],
    )
    return purchase_services.post_purchase_invoice(
        purchase, gl_accounts={"inventory": w.inventory, "payables": w.ap}
    )


def _create_payload(w, quantity="4"):
    return {
        "company": str(w.company.pk),
        "customer": str(w.customer.pk),
        "invoice_number": "SINV-UI-1",
        "invoice_date": DAY.isoformat(),
        "warehouse": str(w.warehouse.pk),
        "description": "",
        "lines-TOTAL_FORMS": "1",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-product": str(w.product.pk),
        "lines-0-unit": "",
        "lines-0-quantity": quantity,
        "lines-0-unit_price": "250",
        "lines-0-discount_amount": "0",
        "lines-0-tax_rate": "0.1",
    }


def _post_payload(w):
    return {
        "receivables": str(w.ar.pk),
        "revenue": str(w.revenue.pk),
        "tax_payable": str(w.tax_out.pk),
        "cogs": str(w.cogs.pk),
        "inventory": str(w.inventory.pk),
    }


def _stock(w):
    return inv_reporting.stock_balance(w.company, w.warehouse, w.product)


def _create_and_post(client, w, quantity="4"):
    resp = client.post(reverse("sales_invoice_create"), _create_payload(w, quantity))
    invoice = SalesInvoice.objects.get(company=w.company, invoice_number="SINV-UI-1")
    assert resp.status_code == 302
    resp = client.post(reverse("sales_invoice_post", args=[invoice.pk]), _post_payload(w))
    assert resp.status_code == 302
    invoice.refresh_from_db()
    return invoice


def test_sales_create_and_post_via_ui(client):
    w = build_world()
    _member_client(client, w.company)
    _seed_stock(w)
    resp = client.post(reverse("sales_invoice_create"), _create_payload(w))
    invoice = SalesInvoice.objects.get(company=w.company, invoice_number="SINV-UI-1")
    assert resp.status_code == 302
    assert invoice.status == "DRAFT"

    resp = client.post(reverse("sales_invoice_post", args=[invoice.pk]), _post_payload(w))
    assert resp.status_code == 302
    invoice.refresh_from_db()
    assert invoice.status == "POSTED"
    assert invoice.grand_total == D("1100")
    stock = _stock(w)
    assert stock["quantity"] == D("6")
    assert stock["value"] == D("600")
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("1100")


def test_sales_oversell_post_fails_and_stays_draft(client):
    w = build_world()
    _member_client(client, w.company)
    _seed_stock(w, qty="2")
    resp = client.post(reverse("sales_invoice_create"), _create_payload(w, quantity="5"))
    invoice = SalesInvoice.objects.get(company=w.company, invoice_number="SINV-UI-1")
    assert resp.status_code == 302
    resp = client.post(reverse("sales_invoice_post", args=[invoice.pk]), _post_payload(w))
    assert resp.status_code == 200  # service error rendered on the detail page
    invoice.refresh_from_db()
    assert invoice.status == "DRAFT"
    assert _stock(w)["quantity"] == D("2")
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("0")


def test_sales_return_restores_stock_at_original_cogs(client):
    w = build_world()
    _member_client(client, w.company)
    _seed_stock(w)
    invoice = _create_and_post(client, w)
    line = invoice.lines.first()
    resp = client.post(
        reverse("sales_return_create", args=[invoice.pk]),
        {
            "return_number": "SRET-1",
            "return_date": DAY.isoformat(),
            "description": "",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-invoice_line": str(line.pk),
            "lines-0-quantity": "1",
        },
    )
    ret = SalesReturn.objects.get(company=w.company, return_number="SRET-1")
    assert resp.status_code == 302
    resp = client.post(
        reverse("sales_return_post", args=[ret.pk]),
        {
            "receivables": str(w.ar.pk),
            "revenue": str(w.revenue.pk),
            "tax_payable": str(w.tax_out.pk),
            "inventory": str(w.inventory.pk),
            "cogs": str(w.cogs.pk),
        },
    )
    assert resp.status_code == 302
    ret.refresh_from_db()
    assert ret.status == "POSTED"
    assert ret.cogs_value == D("100")
    stock = _stock(w)
    assert stock["quantity"] == D("7")
    assert stock["value"] == D("700")
    # AR falls by the returned net + its tax: 1100 - 275 = 825.
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("825")


def test_sales_invoice_reverse_via_ui(client):
    w = build_world()
    _member_client(client, w.company)
    _seed_stock(w)
    invoice = _create_and_post(client, w)
    resp = client.post(reverse("sales_invoice_reverse", args=[invoice.pk]), {"reason": "void"})
    assert resp.status_code == 302
    invoice.refresh_from_db()
    assert invoice.status == "REVERSED"
    assert _stock(w)["quantity"] == D("10")
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("0")


def test_sales_create_non_member_is_404(client):
    w = build_world()
    outsider = User.objects.create_user(username="outsider", password="x")
    client.force_login(outsider)
    resp = client.post(reverse("sales_invoice_create"), _create_payload(w))
    assert resp.status_code == 404
    assert not SalesInvoice.objects.filter(company=w.company).exists()
