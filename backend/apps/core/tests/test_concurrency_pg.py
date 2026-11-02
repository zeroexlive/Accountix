"""PostgreSQL concurrency tests (Sprint 10).

These tests exercise real multi-threaded races against the posting
services. They are meaningless on SQLite (which serialises writers at
the file level and whose test DB here is in-memory), so the whole
module skips unless the configured database is PostgreSQL. Run with:

    DATABASE_URL=postgresql://... .venv/bin/python -m pytest \
        --ds=config.settings.postgres_test \
        backend/apps/core/tests/test_concurrency_pg.py

Every test uses ``transaction=True`` so setup data is committed and
visible to the worker threads, each of which uses its own connection.
"""

import threading
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.accounting import services as acct_services
from apps.accounting.models import Account, JournalEntry
from apps.catalog.models import Product, Unit
from apps.inventory import reporting as inv_reporting
from apps.inventory import services as inv_services
from apps.organizations.models import Company, FiscalPeriod, FiscalYear
from apps.parties.models import Party
from apps.sales import services as sales_services
from apps.sales.models import SalesInvoice
from apps.treasury import services as treasury_services
from apps.treasury.models import PaymentAllocation

D = Decimal
DAY = date(2026, 6, 1)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Concurrency tests require PostgreSQL (SQLite serialises writers).",
    ),
]


def _acct(company, code, account_type, normal_balance):
    return Account.objects.create(
        company=company,
        code=code,
        name=f"A{code}",
        account_type=account_type,
        normal_balance=normal_balance,
        is_postable=True,
        is_active=True,
    )


class World:
    pass


def build_world():
    w = World()
    w.company = Company.objects.create(name="Race Co")
    fy = FiscalYear.objects.create(
        company=w.company, name="FY", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    FiscalPeriod.objects.create(
        company=w.company,
        fiscal_year=fy,
        name="Year",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN",
    )
    c = w.company
    w.cash = _acct(c, "1000", "ASSET", "DEBIT")
    w.ar = _acct(c, "1200", "ASSET", "DEBIT")
    w.inventory_acct = _acct(c, "1300", "ASSET", "DEBIT")
    w.tax_out = _acct(c, "2200", "LIABILITY", "CREDIT")
    w.revenue = _acct(c, "4000", "REVENUE", "CREDIT")
    w.cogs = _acct(c, "5100", "EXPENSE", "DEBIT")
    w.customer = Party.objects.create(company=c, code="CUS-1", name="Customer", kind="CUSTOMER")
    pcs = Unit.objects.create(company=c, code="PCS", name="Piece")
    w.product = Product.objects.create(company=c, sku="P-1", name="Widget", base_unit=pcs)
    from apps.inventory.models import Warehouse

    w.warehouse = Warehouse.objects.create(company=c, code="WH1", name="Main")
    w.gl_sales = {
        "receivables": w.ar,
        "revenue": w.revenue,
        "tax_payable": w.tax_out,
        "cogs": w.cogs,
        "inventory": w.inventory_acct,
    }
    return w


def run_concurrently(fn, n=2):
    """Run ``fn(i)`` in ``n`` threads released simultaneously.

    Returns a list of ("ok", value) / ("error", exception) per thread.
    """
    barrier = threading.Barrier(n)
    results = [None] * n

    def worker(i):
        try:
            barrier.wait(timeout=10)
            results[i] = ("ok", fn(i))
        except Exception as exc:  # noqa: BLE001 - collected and asserted by caller
            results[i] = ("error", exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(r is not None for r in results), "a worker thread did not finish"
    return results


def test_concurrent_journal_post_same_idempotency_key(w=None):
    w = build_world()
    lines = [
        {"account": w.cash, "debit": D("100")},
        {"account": w.revenue, "credit": D("100")},
    ]

    def attempt(_i):
        return acct_services.post_journal_entry(
            company=w.company,
            entry_date=DAY,
            lines=lines,
            description="Race",
            idempotency_key="race-key-1",
        )

    results = run_concurrently(attempt)
    errors = [r[1] for r in results if r[0] == "error"]
    assert errors == [], f"both callers should succeed idempotently, got errors: {errors!r}"
    entries = JournalEntry.objects.filter(company=w.company, idempotency_key="race-key-1")
    assert entries.count() == 1
    entry = entries.get()
    assert entry.status == "POSTED"
    assert entry.lines.count() == 2
    returned_ids = {str(r[1].id) for r in results}
    assert returned_ids == {str(entry.id)}


def test_concurrent_sales_invoices_never_oversell_stock():
    w = build_world()
    inv_services.receive_stock(
        company=w.company,
        warehouse=w.warehouse,
        product=w.product,
        quantity=D("10"),
        unit_cost=D("100"),
        doc_date=DAY,
    )
    invoices = [
        sales_services.create_sales_invoice(
            company=w.company,
            customer=w.customer,
            invoice_number=f"SINV-R{i}",
            invoice_date=DAY,
            warehouse=w.warehouse,
            lines=[{"product": w.product, "quantity": D("8"), "unit_price": D("250")}],
        )
        for i in range(2)
    ]

    def attempt(i):
        return sales_services.post_sales_invoice(invoices[i], gl_accounts=w.gl_sales)

    results = run_concurrently(attempt)
    oks = [r for r in results if r[0] == "ok"]
    errors = [r[1] for r in results if r[0] == "error"]
    assert len(oks) == 1, f"exactly one invoice may post, results: {results!r}"
    assert len(errors) == 1 and isinstance(errors[0], ValidationError), (
        f"the loser must fail cleanly with ValidationError, got: {errors!r}"
    )
    statuses = sorted(
        SalesInvoice.objects.filter(pk__in=[i.pk for i in invoices]).values_list(
            "status", flat=True
        )
    )
    assert statuses == ["DRAFT", "POSTED"]
    balance = inv_reporting.stock_balance(w.company, w.warehouse, w.product)
    assert balance["quantity"] == D("2")
    assert balance["value"] == D("200")
    assert balance["quantity"] >= 0


def test_concurrent_allocations_never_exceed_invoice_total():
    w = build_world()
    inv_services.receive_stock(
        company=w.company,
        warehouse=w.warehouse,
        product=w.product,
        quantity=D("10"),
        unit_cost=D("100"),
        doc_date=DAY,
    )
    invoice = sales_services.create_sales_invoice(
        company=w.company,
        customer=w.customer,
        invoice_number="SINV-A1",
        invoice_date=DAY,
        warehouse=w.warehouse,
        lines=[{"product": w.product, "quantity": D("4"), "unit_price": D("250")}],
    )
    invoice = sales_services.post_sales_invoice(invoice, gl_accounts=w.gl_sales)
    assert invoice.grand_total == D("1000")

    treasury_acct = treasury_services.create_treasury_account(
        company=w.company, kind="CASH", name="Cash", gl_account=w.cash
    )
    payments = []
    for i in range(2):
        p = treasury_services.create_payment(
            company=w.company,
            direction="RECEIPT",
            party=w.customer,
            treasury_account=treasury_acct,
            amount=D("1000"),
            payment_date=DAY,
            method="CASH",
            reference=f"RCPT-{i}",
        )
        payments.append(treasury_services.post_payment(p, gl_accounts={"receivable": w.ar}))

    def attempt(i):
        return treasury_services.allocate_payment(payments[i], invoice, D("1000"))

    results = run_concurrently(attempt)
    oks = [r for r in results if r[0] == "ok"]
    errors = [r[1] for r in results if r[0] == "error"]
    assert len(oks) == 1, f"exactly one allocation may succeed, results: {results!r}"
    assert len(errors) == 1 and isinstance(errors[0], ValidationError), (
        f"the loser must fail cleanly with ValidationError, got: {errors!r}"
    )
    total = treasury_services.allocated_total_for_invoice(SalesInvoice.objects.get(pk=invoice.pk))
    assert total == D("1000")
    invoice.refresh_from_db()
    assert invoice.payment_status == "PAID"
    assert (
        PaymentAllocation.objects.filter(
            sales_invoice=invoice, status=PaymentAllocation.Status.ACTIVE
        ).count()
        == 1
    )
