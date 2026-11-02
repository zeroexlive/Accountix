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
from apps.inventory.models import Warehouse
from apps.organizations.models import Company, CompanyMembership, FiscalPeriod, FiscalYear
from apps.parties.models import Party
from apps.purchases import reporting, services
from apps.purchases.models import PurchaseInvoice, PurchaseOrder

User = get_user_model()
D = Decimal
DAY = date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Fixtures
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
def supplier(db, company):
    return Party.objects.create(company=company, code="SUP-1", name="Supplier", kind="SUPPLIER")


@pytest.fixture
def pcs(db, company):
    return Unit.objects.create(company=company, code="PCS", name="Piece")


@pytest.fixture
def product(db, company, pcs):
    return Product.objects.create(company=company, sku="P-1", name="Widget", base_unit=pcs)


@pytest.fixture
def product2(db, company, pcs):
    return Product.objects.create(company=company, sku="P-2", name="Gadget", base_unit=pcs)


@pytest.fixture
def service_product(db, company, pcs):
    return Product.objects.create(
        company=company, sku="SVC-1", name="Freight service", base_unit=pcs, is_stockable=False
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
        "inventory": acct(company, "1300"),
        "payables": acct(company, "2100", account_type="LIABILITY", normal_balance="CREDIT"),
        "tax": acct(company, "1350"),
        "expense": acct(company, "6100", account_type="EXPENSE"),
    }


def make_invoice(company, supplier, warehouse, lines, number="INV-1", **kw):
    return services.create_purchase_invoice(
        company=company,
        supplier=supplier,
        invoice_number=number,
        invoice_date=DAY,
        warehouse=warehouse,
        lines=lines,
        **kw,
    )


def stock(company, warehouse, product):
    return inv_reporting.stock_balance(company, warehouse, product)


# ---------------------------------------------------------------------------
# End-to-end posting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_e2e_purchase_posts_stock_journal_and_subledger(
    company, period, supplier, warehouse, product, product2, gl
):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [
            {"product": product, "quantity": D("10"), "unit_cost": D("100"), "tax_rate": D("0.1")},
            {"product": product2, "quantity": D("4"), "unit_cost": D("250"), "tax_rate": D("0.1")},
        ],
    )
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)

    # Totals: subtotal 2000, tax 200, grand 2200.
    assert invoice.status == "POSTED"
    assert invoice.payment_status == "UNPAID"
    assert invoice.subtotal == D("2000.00")
    assert invoice.tax_total == D("200.00")
    assert invoice.grand_total == D("2200.00")

    # Stock received at cost; MWAC == purchase cost.
    assert stock(company, warehouse, product)["quantity"] == D("10")
    assert stock(company, warehouse, product)["value"] == D("1000.00")
    assert stock(company, warehouse, product2)["value"] == D("1000.00")

    # Journal balanced; AP credit == grand total; lines tagged with supplier.
    entry = invoice.journal_entry
    assert entry is not None and entry.status == "POSTED"
    assert entry.total_debit() == entry.total_credit() == D("2200.00")
    ap_lines = entry.lines.filter(account=gl["payables"])
    assert ap_lines.get().credit == D("2200.00")
    assert ap_lines.get().party == supplier
    inv_line = entry.lines.get(account=gl["inventory"])
    assert inv_line.debit == D("2000.00")
    assert entry.lines.get(account=gl["tax"]).debit == D("200.00")

    # Supplier subledger == AP account balance in the trial balance.
    tb = acct_reporting.trial_balance(company)
    assert tb["is_balanced"]
    ap_row = next(r for r in tb["rows"] if r["account_id"] == gl["payables"].id)
    assert -ap_row["balance"] == D("2200.00")
    assert reporting.supplier_balance(company, gl["payables"], supplier) == D("2200.00")
    assert reporting.ap_total(company, gl["payables"]) == -ap_row["balance"]


@pytest.mark.django_db
def test_discount_math_exact_and_inventory_net_of_discount(
    company, period, supplier, warehouse, product, gl
):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [
            {
                "product": product,
                "quantity": D("10"),
                "unit_cost": D("100"),
                "discount_amount": D("100"),
                "tax_rate": D("0.1"),
            }
        ],
    )
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)
    # gross 1000 - discount 100 = net 900; tax 90; grand 990.
    assert invoice.subtotal == D("1000.00")
    assert invoice.discount_total == D("100.00")
    assert invoice.tax_total == D("90.00")
    assert invoice.grand_total == D("990.00")
    row = stock(company, warehouse, product)
    assert row["value"] == D("900.00")  # stock valued net of discount
    assert row["average_cost"] == D("90")
    entry = invoice.journal_entry
    assert entry.lines.get(account=gl["inventory"]).debit == D("900.00")
    assert entry.lines.get(account=gl["payables"]).credit == D("990.00")


@pytest.mark.django_db
def test_discount_non_even_division_keeps_exact_value(
    company, period, supplier, warehouse, product, gl
):
    # 3 @ 10.00 with 1.00 discount -> net 29.00, unit net cost 9.666...
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [
            {
                "product": product,
                "quantity": D("3"),
                "unit_cost": D("10"),
                "discount_amount": D("1"),
            }
        ],
    )
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)
    row = stock(company, warehouse, product)
    assert row["quantity"] == D("3")
    assert row["value"] == D("29.00")
    assert invoice.journal_entry.lines.get(account=gl["inventory"]).debit == D("29.00")


@pytest.mark.django_db
def test_service_line_no_stock_but_hits_expense(
    company, period, supplier, warehouse, service_product, gl
):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": service_product, "quantity": D("1"), "unit_cost": D("500")}],
    )
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)
    assert invoice.stock_document is None
    assert stock(company, warehouse, service_product)["quantity"] == D("0")
    entry = invoice.journal_entry
    assert entry.lines.get(account=gl["expense"]).debit == D("500.00")
    assert entry.lines.get(account=gl["payables"]).credit == D("500.00")


@pytest.mark.django_db
def test_no_gl_path_posts_stock_with_null_journal(company, supplier, warehouse, product):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": product, "quantity": D("5"), "unit_cost": D("80")}],
    )
    invoice = services.post_purchase_invoice(invoice)  # no gl_accounts
    assert invoice.status == "POSTED"
    assert invoice.journal_entry is None
    assert invoice.stock_document is not None
    assert stock(company, warehouse, product)["value"] == D("400.00")
    assert reporting.supplier_balance.__module__  # reporting importable


@pytest.mark.django_db
def test_repost_is_idempotent(company, period, supplier, warehouse, product, gl):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": product, "quantity": D("5"), "unit_cost": D("80")}],
    )
    first = services.post_purchase_invoice(invoice, gl_accounts=gl)
    second = services.post_purchase_invoice(first, gl_accounts=gl)
    assert second.journal_entry_id == first.journal_entry_id
    assert second.stock_document_id == first.stock_document_id
    entries = JournalEntry.objects.filter(
        company=company, idempotency_key=f"purchase-invoice:{invoice.id}"
    )
    assert entries.count() == 1
    assert stock(company, warehouse, product)["quantity"] == D("5")


@pytest.mark.django_db
def test_invoice_without_order_works_and_order_can_be_linked(
    company, period, supplier, warehouse, product, gl
):
    order = PurchaseOrder.objects.create(
        company=company, supplier=supplier, order_number="PO-1", order_date=DAY
    )
    PurchaseOrder_line = order.lines.create(product=product, quantity=D("2"), unit_price=D("100"))
    assert PurchaseOrder_line.pk is not None
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": product, "quantity": D("2"), "unit_cost": D("100")}],
        purchase_order=order,
    )
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)
    assert invoice.purchase_order_id == order.id
    assert invoice.grand_total == D("200.00")


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reversal_restores_stock_and_ap_to_zero(company, period, supplier, warehouse, product, gl):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": product, "quantity": D("10"), "unit_cost": D("100")}],
    )
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)
    invoice = services.reverse_purchase_invoice(invoice)
    assert invoice.status == "REVERSED"
    assert stock(company, warehouse, product)["quantity"] == D("0")
    assert stock(company, warehouse, product)["value"] == D("0.00")
    assert reporting.supplier_balance(company, gl["payables"], supplier) == D("0")
    tb = acct_reporting.trial_balance(company)
    assert tb["is_balanced"] and tb["total_debit"] == tb["total_credit"]


@pytest.mark.django_db
def test_reversal_blocked_after_stock_issued(company, period, supplier, warehouse, product, gl):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": product, "quantity": D("10"), "unit_cost": D("100")}],
    )
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)
    inv_services.issue_stock(
        company=company, warehouse=warehouse, product=product, quantity=D("4"), doc_date=DAY
    )
    with pytest.raises(ValidationError):
        services.reverse_purchase_invoice(invoice)
    invoice.refresh_from_db()
    assert invoice.status == "POSTED"
    assert stock(company, warehouse, product)["quantity"] == D("6")


@pytest.mark.django_db
def test_double_reversal_rejected(company, period, supplier, warehouse, product, gl):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": product, "quantity": D("2"), "unit_cost": D("100")}],
    )
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)
    invoice = services.reverse_purchase_invoice(invoice)
    with pytest.raises(ValidationError):
        services.reverse_purchase_invoice(invoice)


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


def _posted_invoice_with_stock(company, period, supplier, warehouse, product, gl, qty="10"):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": product, "quantity": D(qty), "unit_cost": D("100")}],
    )
    return services.post_purchase_invoice(invoice, gl_accounts=gl)


@pytest.mark.django_db
def test_partial_return_reduces_stock_and_ap(company, period, supplier, warehouse, product, gl):
    invoice = _posted_invoice_with_stock(company, period, supplier, warehouse, product, gl)
    line = invoice.lines.get()
    ret = services.create_purchase_return(
        company=company,
        original_invoice=invoice,
        return_number="RET-1",
        return_date=DAY,
        lines=[{"invoice_line": line, "quantity": D("3")}],
    )
    ret = services.post_purchase_return(ret, gl_accounts=gl)
    assert ret.status == "POSTED"
    assert ret.total_amount == D("300.00")
    assert stock(company, warehouse, product)["quantity"] == D("7")
    assert reporting.supplier_balance(company, gl["payables"], supplier) == D("700.00")
    ret_entry = ret.journal_entry
    assert ret_entry.lines.get(account=gl["payables"]).debit == D("300.00")
    assert ret_entry.lines.get(account=gl["payables"]).party == supplier
    assert ret_entry.lines.get(account=gl["inventory"]).credit == D("300.00")


@pytest.mark.django_db
def test_over_return_rejected(company, period, supplier, warehouse, product, gl):
    invoice = _posted_invoice_with_stock(company, period, supplier, warehouse, product, gl)
    line = invoice.lines.get()
    ret = services.create_purchase_return(
        company=company,
        original_invoice=invoice,
        return_number="RET-1",
        return_date=DAY,
        lines=[{"invoice_line": line, "quantity": D("8")}],
    )
    services.post_purchase_return(ret, gl_accounts=gl)
    ret2 = services.create_purchase_return(
        company=company,
        original_invoice=invoice,
        return_number="RET-2",
        return_date=DAY,
        lines=[{"invoice_line": line, "quantity": D("3")}],  # 8 + 3 > 10
    )
    with pytest.raises(ValidationError):
        services.post_purchase_return(ret2, gl_accounts=gl)
    assert stock(company, warehouse, product)["quantity"] == D("2")


# ---------------------------------------------------------------------------
# Isolation & period gates
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cross_company_supplier_rejected(company, other_company, warehouse, product):
    foreign = Party.objects.create(company=other_company, code="F-1", name="Foreign")
    with pytest.raises(ValidationError):
        make_invoice(
            company,
            foreign,
            warehouse,
            [{"product": product, "quantity": D("1"), "unit_cost": D("10")}],
        )
    assert PurchaseInvoice.objects.count() == 0


@pytest.mark.django_db
def test_cross_company_product_rejected(
    company, other_company, supplier, warehouse, pcs, gl, period
):
    foreign_product = Product.objects.create(
        company=other_company,
        sku="X-1",
        name="X",
        base_unit=Unit.objects.create(company=other_company, code="PCS", name="Piece"),
    )
    with pytest.raises(ValidationError):
        make_invoice(
            company,
            supplier,
            warehouse,
            [{"product": foreign_product, "quantity": D("1"), "unit_cost": D("10")}],
        )


@pytest.mark.django_db
def test_cross_company_warehouse_rejected(company, other_company, supplier, product):
    foreign_wh = Warehouse.objects.create(company=other_company, code="WHX", name="X")
    with pytest.raises(ValidationError):
        make_invoice(
            company,
            supplier,
            foreign_wh,
            [{"product": product, "quantity": D("1"), "unit_cost": D("10")}],
        )


@pytest.mark.django_db
def test_closed_fiscal_period_rejected(
    db, closed_period, supplier, warehouse, product, gl, other_company
):
    # other_company has only a CLOSED period covering the invoice date.
    invoice = services.create_purchase_invoice(
        company=other_company,
        supplier=Party.objects.create(
            company=other_company, code="S-1", name="Sup", kind="SUPPLIER"
        ),
        invoice_number="INV-X",
        invoice_date=DAY,
        warehouse=Warehouse.objects.create(company=other_company, code="WH1", name="Main"),
        lines=[
            {
                "product": Product.objects.create(
                    company=other_company,
                    sku="P-1",
                    name="W",
                    base_unit=Unit.objects.create(company=other_company, code="PCS", name="Piece"),
                ),
                "quantity": D("1"),
                "unit_cost": D("10"),
            }
        ],
    )
    foreign_gl = {
        "inventory": acct(other_company, "1300"),
        "payables": acct(other_company, "2100", account_type="LIABILITY", normal_balance="CREDIT"),
    }
    with pytest.raises(ValidationError):
        services.post_purchase_invoice(invoice, gl_accounts=foreign_gl)
    invoice.refresh_from_db()
    assert invoice.status == "DRAFT"
    assert invoice.stock_document is None


@pytest.mark.django_db
def test_unbalanced_impossible_and_totals_equal_line_sums(
    company, period, supplier, warehouse, product, product2, gl
):
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [
            {
                "product": product,
                "quantity": D("3"),
                "unit_cost": D("33.33"),
                "discount_amount": D("0.01"),
                "tax_rate": D("0.09"),
            },
            {"product": product2, "quantity": D("7"), "unit_cost": D("12.10")},
        ],
    )
    rows, totals = services.compute_invoice_totals(invoice)
    invoice = services.post_purchase_invoice(invoice, gl_accounts=gl)
    assert invoice.subtotal == totals["subtotal"]
    assert invoice.discount_total == totals["discount_total"]
    assert invoice.tax_total == totals["tax_total"]
    assert invoice.grand_total == totals["grand_total"]
    for line in invoice.lines.all():
        row = next(r for r in rows if r["line"].id == line.id)
        assert line.tax_amount == row["tax"]
    tb = acct_reporting.trial_balance(company)
    assert tb["is_balanced"]


@pytest.mark.django_db
def test_purchase_history_reports(company, period, supplier, warehouse, product, gl):
    invoice = _posted_invoice_with_stock(company, period, supplier, warehouse, product, gl)
    history = reporting.supplier_purchase_history(company, supplier)
    assert [i.id for i in history] == [invoice.id]
    lines = reporting.product_purchase_history(company, product)
    assert len(lines) == 1 and lines[0].invoice_id == invoice.id


@pytest.mark.django_db
def test_invoice_views_company_isolation(
    client, company, other_company, supplier, warehouse, product
):
    user = User.objects.create_user(username="u1", password="pw")
    CompanyMembership.objects.create(company=company, user=user, role="OWNER")
    invoice = make_invoice(
        company,
        supplier,
        warehouse,
        [{"product": product, "quantity": D("1"), "unit_cost": D("10")}],
    )
    other_supplier = Party.objects.create(company=other_company, code="O-1", name="Other")
    other_wh = Warehouse.objects.create(company=other_company, code="WH9", name="Other")
    other_pcs = Unit.objects.create(company=other_company, code="PCS", name="Piece")
    other_product = Product.objects.create(
        company=other_company, sku="OP-1", name="OP", base_unit=other_pcs
    )
    other_invoice = services.create_purchase_invoice(
        company=other_company,
        supplier=other_supplier,
        invoice_number="OTHER-1",
        invoice_date=DAY,
        warehouse=other_wh,
        lines=[{"product": other_product, "quantity": D("1"), "unit_cost": D("10")}],
    )
    client.force_login(user)
    listing = client.get(reverse("purchase_invoice_list"))
    assert invoice.invoice_number in listing.content.decode()
    assert "OTHER-1" not in listing.content.decode()
    detail = client.get(reverse("purchase_invoice_detail", args=[other_invoice.pk]))
    assert detail.status_code == 404
