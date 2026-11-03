"""Sprint 12 — golden-path E2E through the UI only (the sprint proof).

Stage fixtures are only the company, its fiscal period and the chart
of accounts. Every business object — supplier, unit, warehouse,
product, purchase invoice, customer, sales invoice, treasury
account, receipt, allocation — is created and posted through the web
forms and action endpoints, with numeric assertions at each step:

purchase 10 @ 100 (+10% tax) → stock 10 / AP 1100
sale 4 @ 250 (+10% tax)      → stock 6 / AR 1100 / COGS 400
receipt 1100 allocated       → sales invoice payment_status == PAID
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounting import reporting as acct_reporting
from apps.inventory import reporting as inv_reporting
from apps.organizations.models import Company, CompanyMembership, FiscalPeriod, FiscalYear
from apps.parties.models import Party
from apps.purchases import reporting as purchase_reporting
from apps.purchases.models import PurchaseInvoice
from apps.sales import reporting as sales_reporting
from apps.sales.models import SalesInvoice
from apps.treasury.models import Payment, TreasuryAccount
from apps.treasury.tests._helpers import _acct

D = Decimal
DAY = date(2026, 6, 1)
User = get_user_model()
pytestmark = pytest.mark.django_db


class Stage:
    pass


def _stage(client):
    s = Stage()
    s.company = Company.objects.create(name="E2E Co")
    fy = FiscalYear.objects.create(
        company=s.company, name="FY2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    FiscalPeriod.objects.create(
        company=s.company,
        fiscal_year=fy,
        name="2026",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN",
    )
    c = s.company
    s.cash = _acct(c, "1100", "Cash", "ASSET", "DEBIT")
    s.cheques_in_hand = _acct(c, "1150", "Cheques in hand", "ASSET", "DEBIT")
    s.ar = _acct(c, "1200", "Accounts receivable", "ASSET", "DEBIT")
    s.inventory = _acct(c, "1300", "Inventory", "ASSET", "DEBIT")
    s.tax_in = _acct(c, "1350", "Input VAT", "ASSET", "DEBIT")
    s.ap = _acct(c, "2100", "Accounts payable", "LIABILITY", "CREDIT")
    s.tax_out = _acct(c, "2200", "Output VAT payable", "LIABILITY", "CREDIT")
    s.revenue = _acct(c, "4100", "Sales revenue", "REVENUE", "CREDIT")
    s.cogs = _acct(c, "5100", "Cost of goods sold", "EXPENSE", "DEBIT")
    s.expense = _acct(c, "6100", "Operating expense", "EXPENSE", "DEBIT")
    user = User.objects.create_user(username="boss", password="x")
    CompanyMembership.objects.create(user=user, company=c, role="OWNER")
    client.force_login(user)
    return s


def _party_payload(company, kind, code, name):
    return {
        "company": str(company.pk),
        "kind": kind,
        "code": code,
        "name": name,
        "legal_name": "",
        "tax_id": "",
        "registration_number": "",
        "email": "",
        "phone": "",
        "is_active": "on",
        "contacts-TOTAL_FORMS": "1",
        "contacts-INITIAL_FORMS": "0",
        "contacts-MIN_NUM_FORMS": "0",
        "contacts-MAX_NUM_FORMS": "1000",
        "contacts-0-full_name": "",
        "contacts-0-role": "",
        "contacts-0-phone": "",
        "contacts-0-email": "",
        "addresses-TOTAL_FORMS": "1",
        "addresses-INITIAL_FORMS": "0",
        "addresses-MIN_NUM_FORMS": "0",
        "addresses-MAX_NUM_FORMS": "1000",
        "addresses-0-label": "",
        "addresses-0-line1": "",
        "addresses-0-line2": "",
        "addresses-0-city": "",
        "addresses-0-province": "",
        "addresses-0-postal_code": "",
        "addresses-0-country": "",
    }


def _gl_balance(stage, code):
    tb = acct_reporting.trial_balance(stage.company)
    for row in tb["rows"]:
        if row["code"] == code:
            return row["balance"]
    return D("0")


def test_full_cycle_through_the_ui(client):
    s = _stage(client)
    c = s.company

    # --- master data via UI forms -------------------------------------
    resp = client.post(reverse("party_create"), _party_payload(c, "SUPPLIER", "SUP-E2E", "Sup"))
    assert resp.status_code == 302
    supplier = Party.objects.get(company=c, code="SUP-E2E")

    resp = client.post(
        reverse("unit_create"),
        {"company": str(c.pk), "code": "PCS", "name": "Piece", "is_active": "on"},
    )
    assert resp.status_code == 302
    from apps.catalog.models import Product, Unit

    unit = Unit.objects.get(company=c, code="PCS")

    resp = client.post(
        reverse("warehouse_create"),
        {"company": str(c.pk), "code": "WH-E2E", "name": "Main", "is_active": "on"},
    )
    assert resp.status_code == 302
    from apps.inventory.models import Warehouse

    warehouse = Warehouse.objects.get(company=c, code="WH-E2E")

    resp = client.post(
        reverse("product_create"),
        {
            "company": str(c.pk),
            "category": "",
            "base_unit": str(unit.pk),
            "sku": "P-E2E",
            "barcode": "",
            "name": "Widget",
            "description": "",
            "is_stockable": "on",
            "is_active": "on",
            "min_stock_level": "0",
            "default_purchase_price": "",
            "default_sale_price": "",
        },
    )
    assert resp.status_code == 302
    product = Product.objects.get(company=c, sku="P-E2E")

    # --- purchase via UI: 10 @ 100, tax 10% ---------------------------
    resp = client.post(
        reverse("purchase_invoice_create"),
        {
            "company": str(c.pk),
            "supplier": str(supplier.pk),
            "invoice_number": "PINV-E2E",
            "invoice_date": DAY.isoformat(),
            "warehouse": str(warehouse.pk),
            "description": "",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-product": str(product.pk),
            "lines-0-unit": "",
            "lines-0-quantity": "10",
            "lines-0-unit_cost": "100",
            "lines-0-discount_amount": "0",
            "lines-0-tax_rate": "0.1",
        },
    )
    purchase = PurchaseInvoice.objects.get(company=c, invoice_number="PINV-E2E")
    assert resp.status_code == 302
    assert purchase.status == "DRAFT"
    resp = client.post(
        reverse("purchase_invoice_post", args=[purchase.pk]),
        {
            "payables": str(s.ap.pk),
            "inventory": str(s.inventory.pk),
            "tax": str(s.tax_in.pk),
            "expense": "",
        },
    )
    assert resp.status_code == 302
    purchase.refresh_from_db()
    assert purchase.status == "POSTED"
    stock = inv_reporting.stock_balance(c, warehouse, product)
    assert stock["quantity"] == D("10")
    assert stock["value"] == D("1000")
    assert purchase_reporting.supplier_balance(c, s.ap, supplier) == D("1100")

    # --- customer + sale via UI: 4 @ 250, tax 10% ----------------------
    resp = client.post(reverse("party_create"), _party_payload(c, "CUSTOMER", "CUS-E2E", "Cus"))
    assert resp.status_code == 302
    customer = Party.objects.get(company=c, code="CUS-E2E")

    resp = client.post(
        reverse("sales_invoice_create"),
        {
            "company": str(c.pk),
            "customer": str(customer.pk),
            "invoice_number": "SINV-E2E",
            "invoice_date": DAY.isoformat(),
            "warehouse": str(warehouse.pk),
            "description": "",
            "lines-TOTAL_FORMS": "1",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-product": str(product.pk),
            "lines-0-unit": "",
            "lines-0-quantity": "4",
            "lines-0-unit_price": "250",
            "lines-0-discount_amount": "0",
            "lines-0-tax_rate": "0.1",
        },
    )
    sale = SalesInvoice.objects.get(company=c, invoice_number="SINV-E2E")
    assert resp.status_code == 302
    resp = client.post(
        reverse("sales_invoice_post", args=[sale.pk]),
        {
            "receivables": str(s.ar.pk),
            "revenue": str(s.revenue.pk),
            "tax_payable": str(s.tax_out.pk),
            "cogs": str(s.cogs.pk),
            "inventory": str(s.inventory.pk),
        },
    )
    assert resp.status_code == 302
    sale.refresh_from_db()
    assert sale.status == "POSTED"
    assert sale.payment_status == "UNPAID"
    stock = inv_reporting.stock_balance(c, warehouse, product)
    assert stock["quantity"] == D("6")
    assert stock["value"] == D("600")
    assert sales_reporting.customer_balance(c, s.ar, customer) == D("1100")
    assert _gl_balance(s, "5100") == D("400")  # COGS: 4 @ MWAC 100
    assert _gl_balance(s, "4100") == D("-1000")  # revenue credit balance

    # --- treasury account + receipt via UI ------------------------------
    resp = client.post(
        reverse("treasury_account_create"),
        {
            "company": str(c.pk),
            "kind": "CASH",
            "name": "Main cash",
            "bank_name": "",
            "account_number": "",
            "gl_account": str(s.cash.pk),
        },
    )
    assert resp.status_code == 302
    cash_account = TreasuryAccount.objects.get(company=c, name="Main cash")

    resp = client.post(
        reverse("payment_create"),
        {
            "company": str(c.pk),
            "direction": "RECEIPT",
            "party": str(customer.pk),
            "treasury_account": str(cash_account.pk),
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
        },
    )
    payment = Payment.objects.get(company=c, party=customer)
    assert resp.status_code == 302
    resp = client.post(reverse("payment_post", args=[payment.pk]), {"receivable": str(s.ar.pk)})
    assert resp.status_code == 302
    payment.refresh_from_db()
    assert payment.status == "POSTED"
    assert _gl_balance(s, "1100") == D("1100")

    # --- allocation via UI → invoice PAID --------------------------------
    resp = client.post(reverse("payment_allocate", args=[payment.pk]), {"amount_0": "1100"})
    assert resp.status_code == 302
    sale.refresh_from_db()
    assert sale.payment_status == "PAID"
    # The whole cycle balanced end to end.
    tb = acct_reporting.trial_balance(c)
    assert tb["is_balanced"]
    assert tb["total_debit"] == tb["total_credit"]
