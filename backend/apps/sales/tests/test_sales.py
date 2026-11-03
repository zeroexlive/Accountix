from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import Account, JournalEntry
from apps.catalog.models import Product, Unit
from apps.inventory import reporting as inv_reporting
from apps.inventory import services as inv_services
from apps.inventory.models import StockMovement, Warehouse
from apps.organizations.models import Company, CompanyMembership, FiscalPeriod, FiscalYear
from apps.parties.models import Party
from apps.sales import reporting, services
from apps.sales.models import SalesInvoice

User = get_user_model()
D = Decimal
DAY = date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Fixtures (mirroring the purchases test fixtures)
# ---------------------------------------------------------------------------


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme")


@pytest.fixture
def other_company(db):
    return Company.objects.create(name="Other")


@pytest.fixture
def period(db, company):
    fy = FiscalYear.objects.create(
        company=company, name="FY", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    return FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fy,
        name="Year",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN",
    )


@pytest.fixture
def closed_period(db, other_company):
    fy = FiscalYear.objects.create(
        company=other_company,
        name="FY",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    return FiscalPeriod.objects.create(
        company=other_company,
        fiscal_year=fy,
        name="Year",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="CLOSED",
    )


@pytest.fixture
def customer(db, company):
    return Party.objects.create(company=company, code="CUS-1", name="Customer", kind="CUSTOMER")


@pytest.fixture
def pcs(db, company):
    return Unit.objects.create(company=company, code="PCS", name="Piece")


@pytest.fixture
def product(db, company, pcs):
    return Product.objects.create(company=company, sku="P-1", name="Widget", base_unit=pcs)


@pytest.fixture
def service_product(db, company, pcs):
    return Product.objects.create(
        company=company, sku="SVC-1", name="Consulting", base_unit=pcs, is_stockable=False
    )


@pytest.fixture
def warehouse(db, company):
    return Warehouse.objects.create(company=company, code="WH1", name="Main")


def acct(company, code, **kw):
    defaults = {
        "name": f"A{code}",
        "account_type": "ASSET",
        "normal_balance": "DEBIT",
        "is_postable": True,
        "is_active": True,
    }
    defaults.update(kw)
    return Account.objects.create(company=company, code=code, **defaults)


@pytest.fixture
def gl(db, company):
    return {
        "receivables": acct(company, "1200"),
        "revenue": acct(company, "4100", account_type="REVENUE", normal_balance="CREDIT"),
        "tax_payable": acct(company, "2200", account_type="LIABILITY", normal_balance="CREDIT"),
        "cogs": acct(company, "5100", account_type="EXPENSE"),
        "inventory": acct(company, "1300"),
    }


def seed_stock(company, warehouse, product, qty="10", cost="100"):
    return inv_services.receive_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity=D(qty),
        unit_cost=D(cost),
        doc_date=DAY,
    )


def make_invoice(company, customer, warehouse, lines, number="SINV-1", **kw):
    return services.create_sales_invoice(
        company=company,
        customer=customer,
        invoice_number=number,
        invoice_date=DAY,
        warehouse=warehouse,
        lines=lines,
        **kw,
    )


def stock(company, warehouse, product):
    return inv_reporting.stock_balance(company, warehouse, product)


def line(product, qty, price, **kw):
    row = {"product": product, "quantity": D(qty), "unit_price": D(price)}
    row.update(kw)
    return row


# ---------------------------------------------------------------------------
# Posting — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_post_sales_invoice_e2e(company, period, customer, warehouse, product, gl):
    seed_stock(company, warehouse, product)
    invoice = make_invoice(
        company, customer, warehouse, [line(product, "4", "250", tax_rate=D("0.1"))]
    )
    invoice = services.post_sales_invoice(invoice, gl_accounts=gl)

    assert invoice.status == "POSTED"
    assert invoice.subtotal == D("1000")
    assert invoice.tax_total == D("100")
    assert invoice.grand_total == D("1100")
    assert invoice.lines.get().tax_amount == D("100")
    # Stock issued at MWAC 100 -> COGS 400, remaining 6 / 600.
    row = stock(company, warehouse, product)
    assert row["quantity"] == D("6")
    assert row["value"] == D("600")
    # Revenue entry: Dr AR 1100 (party-tagged) / Cr revenue 1000 / Cr tax 100.
    entry = invoice.journal_entry
    assert entry is not None and entry.status == "POSTED"
    ar_line = entry.lines.get(account=gl["receivables"])
    assert ar_line.debit == D("1100") and ar_line.party_id == customer.id
    assert entry.lines.get(account=gl["revenue"]).credit == D("1000")
    assert entry.lines.get(account=gl["tax_payable"]).credit == D("100")
    # COGS entry: Dr COGS 400 / Cr inventory 400.
    cogs = invoice.cogs_journal_entry
    assert cogs is not None
    assert cogs.lines.get(account=gl["cogs"]).debit == D("400")
    assert cogs.lines.get(account=gl["inventory"]).credit == D("400")
    # Subledger == GL receivables balance.
    assert reporting.customer_balance(company, gl["receivables"], customer) == D("1100")
    assert acct_reporting.account_balance(company, gl["receivables"]) == D("1100")
    assert reporting.ar_total(company, gl["receivables"]) == D("1100")


@pytest.mark.django_db
def test_discount_and_tax_math_non_even(company, period, customer, warehouse, product, gl):
    seed_stock(company, warehouse, product, qty="10", cost="10")
    invoice = make_invoice(
        company,
        customer,
        warehouse,
        [line(product, "3", "33.33", discount_amount=D("1.00"), tax_rate=D("0.1"))],
    )
    invoice = services.post_sales_invoice(invoice, gl_accounts=gl)
    # gross 99.99, net 98.99, tax 9.899 -> 9.90, grand 108.89.
    assert invoice.subtotal == D("99.99")
    assert invoice.discount_total == D("1.00")
    assert invoice.tax_total == D("9.90")
    assert invoice.grand_total == D("108.89")
    assert invoice.journal_entry.lines.get(account=gl["revenue"]).credit == D("98.99")


@pytest.mark.django_db
def test_service_line_sale_has_revenue_without_stock_or_cogs(
    company, period, customer, warehouse, service_product, gl
):
    invoice = make_invoice(company, customer, warehouse, [line(service_product, "2", "500")])
    invoice = services.post_sales_invoice(invoice, gl_accounts=gl)
    assert invoice.status == "POSTED"
    assert invoice.stock_document is None
    assert invoice.cogs_journal_entry is None
    assert invoice.journal_entry.lines.get(account=gl["receivables"]).debit == D("1000")
    assert StockMovement.objects.filter(company=company).count() == 0


@pytest.mark.django_db
def test_post_without_gl_posts_stock_and_keeps_journals_null(
    company, period, customer, warehouse, product
):
    seed_stock(company, warehouse, product)
    invoice = make_invoice(company, customer, warehouse, [line(product, "3", "150")])
    invoice = services.post_sales_invoice(invoice)
    assert invoice.status == "POSTED"
    assert invoice.journal_entry is None and invoice.cogs_journal_entry is None
    assert stock(company, warehouse, product)["quantity"] == D("7")


@pytest.mark.django_db
def test_repost_is_idempotent(company, period, customer, warehouse, product, gl):
    seed_stock(company, warehouse, product)
    invoice = make_invoice(company, customer, warehouse, [line(product, "2", "100")])
    invoice = services.post_sales_invoice(invoice, gl_accounts=gl)
    entries = JournalEntry.objects.filter(company=company).count()
    movements = StockMovement.objects.filter(company=company).count()
    again = services.post_sales_invoice(invoice, gl_accounts=gl)
    assert again.journal_entry_id == invoice.journal_entry_id
    assert again.cogs_journal_entry_id == invoice.cogs_journal_entry_id
    assert JournalEntry.objects.filter(company=company).count() == entries
    assert StockMovement.objects.filter(company=company).count() == movements


# ---------------------------------------------------------------------------
# Posting — rejections
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_insufficient_stock_rejected_atomically(company, period, customer, warehouse, product, gl):
    seed_stock(company, warehouse, product, qty="2", cost="100")
    invoice = make_invoice(company, customer, warehouse, [line(product, "5", "200")])
    entries_before = JournalEntry.objects.filter(company=company).count()
    with pytest.raises(ValidationError, match="کافی نیست: درخواستی"):
        services.post_sales_invoice(invoice, gl_accounts=gl)
    invoice.refresh_from_db()
    assert invoice.status == "DRAFT"
    assert invoice.stock_document is None
    assert JournalEntry.objects.filter(company=company).count() == entries_before
    assert stock(company, warehouse, product)["quantity"] == D("2")


@pytest.mark.django_db
def test_cross_company_rejected(db, company, other_company, period, warehouse, product, pcs):
    other_customer = Party.objects.create(
        company=other_company, code="C-9", name="Foreign", kind="CUSTOMER"
    )
    customer = Party.objects.create(company=company, code="C-1", name="Local", kind="CUSTOMER")
    with pytest.raises(ValidationError, match="متعلق به شرکت دیگری است"):
        make_invoice(company, other_customer, warehouse, [line(product, "1", "10")])
    other_product = Product.objects.create(
        company=other_company, sku="X-1", name="Foreign widget", base_unit=pcs
    )
    with pytest.raises(ValidationError, match="متعلق به شرکت دیگری است"):
        make_invoice(company, customer, warehouse, [line(other_product, "1", "10")])
    other_warehouse = Warehouse.objects.create(company=other_company, code="WH9", name="Far")
    with pytest.raises(ValidationError, match="متعلق به شرکت دیگری است"):
        make_invoice(company, customer, other_warehouse, [line(product, "1", "10")])


@pytest.mark.django_db
def test_supplier_is_not_a_customer(company, period, warehouse, product):
    supplier = Party.objects.create(company=company, code="SUP-1", name="Sup", kind="SUPPLIER")
    with pytest.raises(ValidationError, match="مشتری نیست"):
        make_invoice(company, supplier, warehouse, [line(product, "1", "10")])


@pytest.mark.django_db
def test_closed_fiscal_period_rejected(db, closed_period, other_company):
    # other_company has only a CLOSED period covering the invoice date.
    pcs = Unit.objects.create(company=other_company, code="PCS", name="Piece")
    customer = Party.objects.create(company=other_company, code="C-1", name="Cust", kind="CUSTOMER")
    warehouse = Warehouse.objects.create(company=other_company, code="WH1", name="Main")
    product = Product.objects.create(
        company=other_company, sku="P-1", name="W", base_unit=pcs, is_stockable=False
    )
    invoice = services.create_sales_invoice(
        company=other_company,
        customer=customer,
        invoice_number="SINV-X",
        invoice_date=DAY,
        warehouse=warehouse,
        lines=[{"product": product, "quantity": D("1"), "unit_price": D("10")}],
    )
    gl = {
        "receivables": acct(other_company, "1200"),
        "revenue": acct(other_company, "4100", account_type="REVENUE", normal_balance="CREDIT"),
        "tax_payable": acct(
            other_company, "2200", account_type="LIABILITY", normal_balance="CREDIT"
        ),
        "cogs": acct(other_company, "5100", account_type="EXPENSE"),
        "inventory": acct(other_company, "1300"),
    }
    with pytest.raises(ValidationError):
        services.post_sales_invoice(invoice, gl_accounts=gl)
    invoice.refresh_from_db()
    assert invoice.status == "DRAFT"


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reversal_restores_stock_and_zeroes_balances(
    company, period, customer, warehouse, product, gl
):
    seed_stock(company, warehouse, product)
    invoice = make_invoice(
        company, customer, warehouse, [line(product, "4", "250", tax_rate=D("0.1"))]
    )
    invoice = services.post_sales_invoice(invoice, gl_accounts=gl)
    invoice = services.reverse_sales_invoice(invoice, reason="customer cancelled")
    assert invoice.status == "REVERSED"
    row = stock(company, warehouse, product)
    assert row["quantity"] == D("10") and row["value"] == D("1000")
    assert reporting.customer_balance(company, gl["receivables"], customer) == D("0")
    assert acct_reporting.account_balance(company, gl["revenue"]) == D("0")
    assert acct_reporting.account_balance(company, gl["cogs"]) == D("0")
    with pytest.raises(ValidationError, match="قبلاً برگشت خورده است"):
        services.reverse_sales_invoice(invoice)


# ---------------------------------------------------------------------------
# Returns (ADR-021: restored at the original sale's COGS cost)
# ---------------------------------------------------------------------------


def _posted_sale(company, customer, warehouse, product, gl, qty="10", price="200", **kw):
    invoice = make_invoice(
        company, customer, warehouse, [line(product, qty, price, **kw)], number="SINV-R"
    )
    return services.post_sales_invoice(invoice, gl_accounts=gl)


@pytest.mark.django_db
def test_sales_return_partial(company, period, customer, warehouse, product, gl):
    seed_stock(company, warehouse, product, qty="10", cost="100")
    invoice = _posted_sale(company, customer, warehouse, product, gl)
    assert stock(company, warehouse, product)["quantity"] == D("0")
    ret = services.create_sales_return(
        company=company,
        original_invoice=invoice,
        return_number="SRET-1",
        return_date=DAY,
        lines=[{"invoice_line": invoice.lines.get(), "quantity": D("3")}],
    )
    ret = services.post_sales_return(ret, gl_accounts=gl)
    assert ret.status == "POSTED"
    assert ret.net_total == D("600") and ret.total_amount == D("600")
    assert ret.cogs_value == D("300")
    row = stock(company, warehouse, product)
    assert row["quantity"] == D("3") and row["value"] == D("300")
    assert reporting.customer_balance(company, gl["receivables"], customer) == D("1400")
    # Over-return: 8 more exceeds the 7 remaining.
    ret2 = services.create_sales_return(
        company=company,
        original_invoice=invoice,
        return_number="SRET-2",
        return_date=DAY,
        lines=[{"invoice_line": invoice.lines.get(), "quantity": D("8")}],
    )
    with pytest.raises(ValidationError, match="مقدار برگشت کالای"):
        services.post_sales_return(ret2, gl_accounts=gl)


@pytest.mark.django_db
def test_sales_return_restores_at_original_cogs_not_current_mwac(
    company, period, customer, warehouse, product, gl
):
    seed_stock(company, warehouse, product, qty="10", cost="100")
    invoice = _posted_sale(company, customer, warehouse, product, gl, qty="4", price="200")
    # Move the average: receive 10 @ 300 -> stock 16, value 3600, MWAC 225.
    seed_stock(company, warehouse, product, qty="10", cost="300")
    assert inv_reporting.stock_balance(company, warehouse, product)["average_cost"] == D("225")
    ret = services.create_sales_return(
        company=company,
        original_invoice=invoice,
        return_number="SRET-1",
        return_date=DAY,
        lines=[{"invoice_line": invoice.lines.get(), "quantity": D("2")}],
    )
    ret = services.post_sales_return(ret, gl_accounts=gl)
    # ADR-021: restored at the original COGS cost (100), not MWAC (225).
    assert ret.cogs_value == D("200")
    row = stock(company, warehouse, product)
    assert row["quantity"] == D("18") and row["value"] == D("3800")
    # COGS account now carries only the 2 units still sold: 400 - 200.
    assert acct_reporting.account_balance(company, gl["cogs"]) == D("200")


# ---------------------------------------------------------------------------
# Quotations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_quotation_conversion(company, period, customer, warehouse, product, service_product):
    quotation = services.create_sales_quotation(
        company=company,
        customer=customer,
        quotation_number="Q-1",
        quotation_date=DAY,
        lines=[
            {"product": product, "quantity": D("2"), "unit_price": D("300")},
            {"product": service_product, "quantity": D("1"), "unit_price": D("50")},
        ],
    )
    invoice = services.convert_quotation_to_invoice(
        quotation, invoice_number="SINV-Q", invoice_date=DAY, warehouse=warehouse
    )
    assert invoice.status == "DRAFT"
    assert invoice.quotation_id == quotation.id
    assert invoice.customer_id == customer.id
    rows = list(invoice.lines.order_by("created_at"))
    assert len(rows) == 2
    assert rows[0].quantity == D("2") and rows[0].unit_price == D("300")
    quotation.refresh_from_db()
    assert quotation.status == "CONVERTED"
    with pytest.raises(ValidationError, match="قابل تبدیل به فاکتور است"):
        services.convert_quotation_to_invoice(
            quotation, invoice_number="SINV-Q2", invoice_date=DAY, warehouse=warehouse
        )


# ---------------------------------------------------------------------------
# Reporting + views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reporting_histories_and_statement(company, period, customer, warehouse, product, gl):
    seed_stock(company, warehouse, product)
    invoice = _posted_sale(company, customer, warehouse, product, gl, qty="2", price="100")
    assert reporting.customer_sales_history(company, customer)[0].id == invoice.id
    assert reporting.product_sales_history(company, product)[0].invoice_id == invoice.id
    statement = reporting.customer_statement(company, gl["receivables"], customer)
    assert statement["balance"] == D("200")
    assert statement["invoices"][0].id == invoice.id
    assert [c.id for c in reporting.customers(company)] == [customer.id]


@pytest.mark.django_db
def test_invoice_views_company_isolation(
    client, company, other_company, customer, warehouse, product
):
    user = User.objects.create_user(username="boss", password="pw")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    invoice = make_invoice(company, customer, warehouse, [line(product, "1", "10")])
    foreign_customer = Party.objects.create(
        company=other_company, code="C-9", name="Foreign", kind="CUSTOMER"
    )
    foreign_warehouse = Warehouse.objects.create(company=other_company, code="WH9", name="Far")
    pcs2 = Unit.objects.create(company=other_company, code="PCS", name="Piece")
    foreign_product = Product.objects.create(
        company=other_company, sku="X-1", name="FW", base_unit=pcs2
    )
    foreign_invoice = make_invoice(
        other_company,
        foreign_customer,
        foreign_warehouse,
        [line(foreign_product, "1", "10")],
        number="SINV-F",
    )
    client.force_login(user)
    listing = client.get(reverse("sales_invoice_list"))
    assert listing.status_code == 200
    assert invoice.invoice_number.encode() in listing.content
    assert foreign_invoice.invoice_number.encode() not in listing.content
    detail = client.get(reverse("sales_invoice_detail", args=[foreign_invoice.pk]))
    assert detail.status_code == 404
    assert SalesInvoice.objects.filter(pk=invoice.pk).exists()
