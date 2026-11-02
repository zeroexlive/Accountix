"""Inventory counts (Sprint 07) + the opening-stock recipe test.

Counts snapshot the derived system quantity at creation, post their
variances as one ADJUSTMENT stock document at the current MWAC, and can
optionally post the net variance value to the GL. A count whose
warehouse moved after the snapshot is rejected (frozen-warehouse rule).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import Account
from apps.catalog.models import Product, Unit
from apps.inventory import reporting, services
from apps.inventory.models import InventoryCount, StockMovement, Warehouse
from apps.organizations.models import Company, FiscalPeriod, FiscalYear

D = Decimal
DAY = date(2026, 6, 1)


@pytest.fixture
def company(db):
    company = Company.objects.create(name="Count Co")
    fy = FiscalYear.objects.create(
        company=company, name="FY2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fy,
        name="2026",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN",
    )
    return company


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
def warehouse(db, company):
    return Warehouse.objects.create(company=company, code="WH1", name="Main")


def _acct(company, code, name, account_type, normal_balance):
    return Account.objects.create(
        company=company,
        code=code,
        name=name,
        account_type=account_type,
        normal_balance=normal_balance,
        is_postable=True,
        is_active=True,
    )


@pytest.fixture
def gl(company):
    return {
        "inventory": _acct(company, "1300", "Inventory", "ASSET", "DEBIT"),
        "variance": _acct(company, "6200", "Inventory variance", "EXPENSE", "DEBIT"),
        "equity": _acct(company, "3100", "Opening equity", "EQUITY", "CREDIT"),
    }


def receive(company, warehouse, product, qty, cost):
    return services.receive_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity=D(qty),
        unit_cost=D(cost),
        doc_date=DAY,
    )


def make_count(company, warehouse, lines):
    return services.create_inventory_count(
        company=company, warehouse=warehouse, count_date=DAY, lines=lines
    )


# ---------------------------------------------------------------------------
# Posting variances
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_count_posts_positive_and_negative_variances(company, warehouse, product, product2):
    receive(company, warehouse, product, "10", "100")  # 10 @ 100
    receive(company, warehouse, product2, "5", "50")  # 5 @ 50
    count = make_count(
        company,
        warehouse,
        [
            {"product": product, "counted_qty": D("8")},  # -2 @ MWAC 100 = -200
            {"product": product2, "counted_qty": D("7")},  # +2 @ MWAC 50 = +100
        ],
    )
    assert count.lines.get(product=product).system_qty == D("10")
    assert count.lines.get(product=product).variance == D("-2")

    count = services.post_inventory_count(count)
    assert count.status == "POSTED"
    assert count.stock_document.doc_type == "ADJUSTMENT"

    row = reporting.stock_balance(company, warehouse, product)
    assert row["quantity"] == D("8") and row["value"] == D("800")
    row = reporting.stock_balance(company, warehouse, product2)
    assert row["quantity"] == D("7") and row["value"] == D("350")


@pytest.mark.django_db
def test_zero_variance_lines_create_no_movements(company, warehouse, product, product2):
    receive(company, warehouse, product, "10", "100")
    count = make_count(
        company,
        warehouse,
        [
            {"product": product, "counted_qty": D("10")},  # exact
            {"product": product2, "counted_qty": D("3"), "unit_cost": D("25")},  # +3, new stock
        ],
    )
    count = services.post_inventory_count(count)
    movements = StockMovement.objects.filter(document=count.stock_document)
    assert movements.count() == 1  # only product2 moved
    assert movements.get().product == product2
    row = reporting.stock_balance(company, warehouse, product2)
    assert row["quantity"] == D("3") and row["value"] == D("75")


@pytest.mark.django_db
def test_all_zero_variance_count_posts_without_document(company, warehouse, product):
    receive(company, warehouse, product, "4", "100")
    count = make_count(company, warehouse, [{"product": product, "counted_qty": D("4")}])
    count = services.post_inventory_count(count)
    assert count.status == "POSTED"
    assert count.stock_document is None
    assert count.journal_entry is None


@pytest.mark.django_db
def test_positive_variance_without_stock_needs_unit_cost(company, warehouse, product):
    count = make_count(company, warehouse, [{"product": product, "counted_qty": D("5")}])
    with pytest.raises(ValidationError):
        services.post_inventory_count(count)
    count.refresh_from_db()
    assert count.status == "DRAFT"
    assert StockMovement.objects.filter(company=company).count() == 0


@pytest.mark.django_db
def test_count_rejected_when_stock_moved_after_snapshot(company, warehouse, product):
    receive(company, warehouse, product, "10", "100")
    count = make_count(company, warehouse, [{"product": product, "counted_qty": D("10")}])
    services.issue_stock(
        company=company, warehouse=warehouse, product=product, quantity=D("1"), doc_date=DAY
    )
    with pytest.raises(ValidationError):
        services.post_inventory_count(count)


@pytest.mark.django_db
def test_count_cross_company_warehouse_rejected(company, warehouse, product):
    other = Company.objects.create(name="Other")
    count_company_lines = [{"product": product, "counted_qty": D("1")}]
    with pytest.raises(ValidationError):
        services.create_inventory_count(
            company=other, warehouse=warehouse, count_date=DAY, lines=count_company_lines
        )


# ---------------------------------------------------------------------------
# GL opt-in
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_count_gl_net_loss(company, warehouse, product, gl):
    receive(company, warehouse, product, "10", "100")
    count = make_count(company, warehouse, [{"product": product, "counted_qty": D("8")}])
    count = services.post_inventory_count(count, gl_accounts=gl)
    # Net variance -200: Dr variance 200 / Cr inventory 200.
    assert count.journal_entry is not None
    assert acct_reporting.account_balance(company, gl["variance"]) == D("200")
    assert acct_reporting.account_balance(company, gl["inventory"]) == D("-200")
    tb = acct_reporting.trial_balance(company)
    assert tb["is_balanced"]


@pytest.mark.django_db
def test_count_gl_net_gain(company, warehouse, product, gl):
    receive(company, warehouse, product, "10", "100")
    count = make_count(company, warehouse, [{"product": product, "counted_qty": D("12")}])
    count = services.post_inventory_count(count, gl_accounts=gl)
    # Net variance +200: Dr inventory 200 / Cr variance 200.
    assert acct_reporting.account_balance(company, gl["inventory"]) == D("200")
    assert acct_reporting.account_balance(company, gl["variance"]) == D("-200")


@pytest.mark.django_db
def test_count_without_gl_posts_no_journal(company, warehouse, product):
    receive(company, warehouse, product, "10", "100")
    count = make_count(company, warehouse, [{"product": product, "counted_qty": D("9")}])
    count = services.post_inventory_count(count)
    assert count.journal_entry is None


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_count_reversal_restores_balances_and_gl(company, warehouse, product, gl):
    receive(company, warehouse, product, "10", "100")
    count = make_count(company, warehouse, [{"product": product, "counted_qty": D("8")}])
    count = services.post_inventory_count(count, gl_accounts=gl)
    reversal = services.reverse_inventory_count(count)
    count.refresh_from_db()
    assert count.status == "REVERSED"
    assert reversal.status == "POSTED"
    assert reversal.reversal_of_id == count.id
    row = reporting.stock_balance(company, warehouse, product)
    assert row["quantity"] == D("10") and row["value"] == D("1000")
    assert acct_reporting.account_balance(company, gl["variance"]) == D("0")
    assert acct_reporting.account_balance(company, gl["inventory"]) == D("0")
    with pytest.raises(ValidationError):
        services.reverse_inventory_count(count)  # double reversal
    with pytest.raises(ValidationError):
        services.reverse_inventory_count(reversal)  # reversing a reversal


# ---------------------------------------------------------------------------
# Opening stock recipe (documented, built from existing services)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_opening_stock_via_receipt_with_gl(company, warehouse, product, gl):
    """Opening stock is NOT a separate model: it is a receipt whose source
    reference is 'opening_stock', with the Sprint 03 GL opt-in crediting
    the opening-equity account (INVENTORY_RULES / SPRINT_07_REPORT)."""
    doc = services.receive_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity=D("20"),
        unit_cost=D("150"),
        doc_date=date(2026, 1, 1),
        source_type="opening_stock",
        source_id="FY2026",
        gl_accounts=(gl["inventory"], gl["equity"]),
    )
    assert doc.source_type == "opening_stock"
    row = reporting.stock_balance(company, warehouse, product)
    assert row["quantity"] == D("20") and row["value"] == D("3000")
    assert reporting.inventory_valuation(company) == D("3000")
    assert acct_reporting.account_balance(company, gl["inventory"]) == D("3000")
    assert acct_reporting.account_balance(company, gl["equity"]) == D("-3000")
    assert InventoryCount.objects.filter(company=company).count() == 0
