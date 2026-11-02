from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.urls import reverse

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import Account, JournalEntry
from apps.accounting.services import post_journal_entry
from apps.catalog.models import Product, ProductUnitConversion, Unit
from apps.inventory import reporting, services
from apps.inventory.models import StockDocument, StockMovement, Warehouse
from apps.organizations.models import Company, CompanyMembership, FiscalPeriod, FiscalYear

User = get_user_model()

D = Decimal
DAY = date(2026, 6, 1)


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme")


@pytest.fixture
def other_company(db):
    return Company.objects.create(name="Other")


@pytest.fixture
def pcs(db, company):
    return Unit.objects.create(company=company, code="PCS", name="Piece")


@pytest.fixture
def product(db, company, pcs):
    return Product.objects.create(company=company, sku="P-1", name="Widget", base_unit=pcs)


@pytest.fixture
def warehouse(db, company):
    return Warehouse.objects.create(company=company, code="WH1", name="Main")


@pytest.fixture
def warehouse2(db, company):
    return Warehouse.objects.create(company=company, code="WH2", name="Second")


def receive(company, warehouse, product, qty, cost, **kw):
    return services.receive_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity=D(qty),
        unit_cost=D(cost),
        doc_date=DAY,
        **kw,
    )


def balance(company, warehouse, product):
    return reporting.stock_balance(company, warehouse, product)


# ---------------------------------------------------------------------------
# Valuation / MWAC
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_receipt_increases_balance(company, warehouse, product):
    receive(company, warehouse, product, "10", "100")
    row = balance(company, warehouse, product)
    assert row["quantity"] == D("10")
    assert row["value"] == D("1000.00")
    assert row["average_cost"] == D("100")


@pytest.mark.django_db
def test_mwac_two_receipts_exact_average(company, warehouse, product):
    receive(company, warehouse, product, "10", "100")
    receive(company, warehouse, product, "10", "200")
    row = balance(company, warehouse, product)
    assert row["quantity"] == D("20")
    assert row["value"] == D("3000.00")
    assert row["average_cost"] == D("150")


@pytest.mark.django_db
def test_issue_at_average_cost(company, warehouse, product):
    receive(company, warehouse, product, "10", "100")
    receive(company, warehouse, product, "10", "200")
    doc = services.issue_stock(
        company=company, warehouse=warehouse, product=product, quantity=D("5"), doc_date=DAY
    )
    movement = doc.movements.get()
    assert movement.unit_cost == D("150")
    assert movement.value_delta == D("-750.00")
    row = balance(company, warehouse, product)
    assert row["quantity"] == D("15")
    assert row["value"] == D("2250.00")
    assert row["average_cost"] == D("150")


@pytest.mark.django_db
def test_full_issue_takes_all_value(company, warehouse, product):
    receive(company, warehouse, product, "3", "33.33")
    services.issue_stock(
        company=company, warehouse=warehouse, product=product, quantity=D("3"), doc_date=DAY
    )
    row = balance(company, warehouse, product)
    assert row["quantity"] == D("0")
    assert row["value"] == D("0.00")


# ---------------------------------------------------------------------------
# Negative stock prevention + rollback
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_issue_beyond_available_rejected_full_rollback(company, warehouse, product):
    receive(company, warehouse, product, "5", "100")
    movements_before = StockMovement.objects.count()
    docs_before = StockDocument.objects.count()
    with pytest.raises(ValidationError):
        services.issue_stock(
            company=company, warehouse=warehouse, product=product, quantity=D("6"), doc_date=DAY
        )
    assert StockMovement.objects.count() == movements_before
    assert StockDocument.objects.count() == docs_before  # wrapper is atomic: no orphan DRAFT
    assert balance(company, warehouse, product)["quantity"] == D("5")


@pytest.mark.django_db
def test_multiline_issue_rolls_back_first_line(company, warehouse, warehouse2, product, pcs):
    other = Product.objects.create(company=company, sku="P-2", name="Gadget", base_unit=pcs)
    receive(company, warehouse, product, "10", "100")
    receive(company, warehouse, other, "1", "50")
    doc = services.create_stock_document(
        doc_type="ISSUE",
        company=company,
        warehouse=warehouse,
        doc_date=DAY,
        lines=[
            {"product": product, "quantity": D("4")},
            {"product": other, "quantity": D("2")},  # only 1 available
        ],
    )
    with pytest.raises(ValidationError):
        services.post_stock_document(doc)
    assert StockMovement.objects.filter(document=doc).count() == 0
    assert balance(company, warehouse, product)["quantity"] == D("10")


# ---------------------------------------------------------------------------
# Transfer / adjustment
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transfer_preserves_total_quantity_and_value(company, warehouse, warehouse2, product):
    receive(company, warehouse, product, "10", "120")
    services.transfer_stock(
        company=company,
        warehouse=warehouse,
        destination_warehouse=warehouse2,
        product=product,
        quantity=D("4"),
        doc_date=DAY,
    )
    src = balance(company, warehouse, product)
    dst = balance(company, warehouse2, product)
    assert src["quantity"] == D("6") and dst["quantity"] == D("4")
    assert src["value"] + dst["value"] == D("1200.00")
    assert dst["average_cost"] == D("120")
    assert reporting.inventory_valuation(company) == D("1200.00")


@pytest.mark.django_db
def test_transfer_beyond_available_rejected(company, warehouse, warehouse2, product):
    receive(company, warehouse, product, "2", "100")
    with pytest.raises(ValidationError):
        services.transfer_stock(
            company=company,
            warehouse=warehouse,
            destination_warehouse=warehouse2,
            product=product,
            quantity=D("3"),
            doc_date=DAY,
        )


@pytest.mark.django_db
def test_adjustment_plus_and_minus(company, warehouse, product):
    receive(company, warehouse, product, "10", "100")
    services.adjust_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity_delta=D("5"),
        doc_date=DAY,
        reason="Count found extra",
    )
    row = balance(company, warehouse, product)
    assert row["quantity"] == D("15") and row["value"] == D("1500.00")
    doc = services.adjust_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity_delta=D("-3"),
        doc_date=DAY,
        reason="Damage",
    )
    assert doc.description == "Damage"
    row = balance(company, warehouse, product)
    assert row["quantity"] == D("12") and row["value"] == D("1200.00")


@pytest.mark.django_db
def test_positive_adjustment_without_stock_needs_cost(company, warehouse, product):
    with pytest.raises(ValidationError):
        services.adjust_stock(
            company=company,
            warehouse=warehouse,
            product=product,
            quantity_delta=D("5"),
            doc_date=DAY,
            reason="Opening count",
        )
    services.adjust_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity_delta=D("5"),
        unit_cost=D("80"),
        doc_date=DAY,
        reason="Opening count",
    )
    assert balance(company, warehouse, product)["value"] == D("400.00")


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reversal_restores_balances(company, warehouse, product):
    doc = receive(company, warehouse, product, "10", "100")
    reversal = services.reverse_stock_document(doc, reason="Wrong receipt")
    assert reversal.status == "POSTED"
    doc.refresh_from_db()
    assert doc.status == "REVERSED"
    row = balance(company, warehouse, product)
    assert row["quantity"] == D("0") and row["value"] == D("0.00")


@pytest.mark.django_db
def test_double_reversal_and_reversing_reversal_rejected(company, warehouse, product):
    doc = receive(company, warehouse, product, "10", "100")
    reversal = services.reverse_stock_document(doc)
    with pytest.raises(ValidationError):
        services.reverse_stock_document(doc)
    with pytest.raises(ValidationError):
        services.reverse_stock_document(reversal)


@pytest.mark.django_db
def test_reversal_blocked_when_stock_already_issued(company, warehouse, product):
    doc = receive(company, warehouse, product, "10", "100")
    services.issue_stock(
        company=company, warehouse=warehouse, product=product, quantity=D("8"), doc_date=DAY
    )
    with pytest.raises(ValidationError):
        services.reverse_stock_document(doc)
    assert balance(company, warehouse, product)["quantity"] == D("2")


@pytest.mark.django_db
def test_posted_document_and_movements_immutable(company, warehouse, product):
    doc = receive(company, warehouse, product, "10", "100")
    doc.description = "tamper"
    with pytest.raises(ValidationError):
        doc.save()
    movement = doc.movements.get()
    movement.quantity_delta = D("999")
    with pytest.raises(ValidationError):
        movement.save()
    with pytest.raises(ValidationError):
        movement.delete()


# ---------------------------------------------------------------------------
# Company isolation / stockability / units
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cross_company_warehouse_rejected(company, other_company, product):
    foreign_wh = Warehouse.objects.create(company=other_company, code="WHX", name="Foreign")
    with pytest.raises(ValidationError):
        receive(company, foreign_wh, product, "1", "10")


@pytest.mark.django_db
def test_cross_company_product_rejected(company, other_company, warehouse):
    foreign_unit = Unit.objects.create(company=other_company, code="PCS", name="Piece")
    foreign_product = Product.objects.create(
        company=other_company, sku="F-1", name="Foreign", base_unit=foreign_unit
    )
    with pytest.raises(ValidationError):
        receive(company, warehouse, foreign_product, "1", "10")


@pytest.mark.django_db
def test_non_stockable_product_rejected(company, warehouse, pcs):
    service_product = Product.objects.create(
        company=company, sku="SVC-1", name="Consulting", base_unit=pcs, is_stockable=False
    )
    with pytest.raises(ValidationError):
        receive(company, warehouse, service_product, "1", "10")


@pytest.mark.django_db
def test_unit_conversion_applied(company, warehouse, product, pcs):
    box = Unit.objects.create(company=company, code="BOX", name="Box")
    ProductUnitConversion.objects.create(
        company=company, product=product, from_unit=box, to_unit=pcs, factor=D("12")
    )
    doc = services.receive_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity=D("2"),
        unit_cost=D("1200"),  # per box
        unit=box,
        doc_date=DAY,
    )
    movement = doc.movements.get()
    assert movement.quantity_delta == D("24")
    assert movement.value_delta == D("2400.00")
    assert movement.unit_cost == D("100")
    row = balance(company, warehouse, product)
    assert row["quantity"] == D("24") and row["average_cost"] == D("100")


# ---------------------------------------------------------------------------
# Reconciliation / reporting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_balances_reconcile_with_movement_sums(company, warehouse, warehouse2, product):
    receive(company, warehouse, product, "10", "100")
    receive(company, warehouse, product, "6", "130")
    services.issue_stock(
        company=company, warehouse=warehouse, product=product, quantity=D("4"), doc_date=DAY
    )
    services.transfer_stock(
        company=company,
        warehouse=warehouse,
        destination_warehouse=warehouse2,
        product=product,
        quantity=D("3"),
        doc_date=DAY,
    )
    for wh in (warehouse, warehouse2):
        agg = StockMovement.objects.filter(
            company=company, warehouse=wh, product=product
        ).aggregate(qty=Sum("quantity_delta"), val=Sum("value_delta"))
        row = balance(company, wh, product)
        assert row["quantity"] == agg["qty"]
        assert row["value"] == agg["val"]
    history = reporting.movement_history(company, product)
    assert len(history) == 5  # 2 receipts + 1 issue + 2 transfer legs


@pytest.mark.django_db
def test_low_stock_report(company, warehouse, product):
    product.min_stock_level = D("25")
    product.save()
    receive(company, warehouse, product, "20", "100")
    rows = reporting.low_stock(company)
    assert [r["sku"] for r in rows] == ["P-1"]
    receive(company, warehouse, product, "10", "100")
    assert reporting.low_stock(company) == []


# ---------------------------------------------------------------------------
# GL integration (explicit opt-in only)
# ---------------------------------------------------------------------------


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
def gl_accounts(db, company):
    inventory = Account.objects.create(
        company=company,
        code="1100",
        name="Inventory",
        account_type="ASSET",
        normal_balance="DEBIT",
        is_postable=True,
    )
    offset = Account.objects.create(
        company=company,
        code="2100",
        name="Goods received clearing",
        account_type="LIABILITY",
        normal_balance="CREDIT",
        is_postable=True,
    )
    return inventory, offset


@pytest.mark.django_db
def test_default_receipt_posts_no_journal(company, warehouse, product):
    receive(company, warehouse, product, "10", "100")
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db
def test_gl_optin_receipt_balanced_and_idempotent(company, warehouse, product, period, gl_accounts):
    doc = receive(company, warehouse, product, "10", "100", gl_accounts=gl_accounts)
    assert doc.journal_entry is not None
    entry = doc.journal_entry
    assert entry.status == "POSTED"
    assert entry.total_debit() == D("1000.00") == entry.total_credit()
    tb = acct_reporting.trial_balance(company)
    assert tb["is_balanced"]
    # Re-posting with the same derived idempotency key returns the same entry.
    again = post_journal_entry(
        company=company,
        entry_date=DAY,
        lines=[
            {"account": gl_accounts[0], "debit": D("1000")},
            {"account": gl_accounts[1], "credit": D("1000")},
        ],
        idempotency_key=f"stock-doc:{doc.id}",
    )
    assert again.pk == entry.pk
    assert JournalEntry.objects.filter(company=company).count() == 1


@pytest.mark.django_db
def test_gl_stock_reversal_also_reverses_journal(company, warehouse, product, period, gl_accounts):
    doc = receive(company, warehouse, product, "10", "100", gl_accounts=gl_accounts)
    services.reverse_stock_document(doc)
    doc.refresh_from_db()
    assert doc.journal_entry.status == "REVERSED"
    tb = acct_reporting.trial_balance(company)
    assert tb["is_balanced"]
    assert tb["total_debit"] == D("2000.00")  # original + reversal legs
    inventory_row = next(r for r in tb["rows"] if r["code"] == "1100")
    assert inventory_row["balance"] == D("0.00")
    assert reporting.inventory_valuation(company) == D("0.00")


# ---------------------------------------------------------------------------
# Views (membership-filtered, read-only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_product_list_view_isolated(client, company, product):
    stranger = User.objects.create_user(username="stranger", password="x")
    client.force_login(stranger)
    resp = client.get(reverse("product_list"))
    assert b"P-1" not in resp.content
    member = User.objects.create_user(username="member", password="x")
    CompanyMembership.objects.create(company=company, user=member, role="ACCOUNTANT")
    client.force_login(member)
    resp = client.get(reverse("product_list"))
    assert b"P-1" in resp.content


@pytest.mark.django_db
def test_stock_balances_view_requires_login(client):
    resp = client.get(reverse("stock_balances"))
    assert resp.status_code == 302
