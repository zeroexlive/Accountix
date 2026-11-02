#!/usr/bin/env python
"""Performance smoke (Sprint 10) — dev-machine numbers, not a benchmark.

Seeds a file-backed SQLite database with ~200 journal entries and ~50
posted sales invoices (plus their stock receipts), then times the
three heaviest read paths through the real HTTP views (trial balance,
dashboard, stock balances) and counts the queries of the underlying
service calls.

Usage (from the repo root):

    ACCOUNTIX_PERF_DB=/tmp/perf.sqlite3 .venv/bin/python scripts/perf_smoke.py

The database file is deleted and recreated on every run. Timings are
wall-clock on whatever machine runs it — label them as such.
"""

import os
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

DB_PATH = Path(os.environ.get("ACCOUNTIX_PERF_DB", "/tmp/perf.sqlite3"))

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

# Point the test settings at a file DB we can migrate + seed.
settings.DATABASES["default"]["NAME"] = str(DB_PATH)
settings.ALLOWED_HOSTS = ["testserver", "127.0.0.1", "localhost"]

from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

D = Decimal
DAY = date(2026, 6, 1)


def seed():
    from apps.accounting import services as acct_services
    from apps.accounting.models import Account
    from apps.catalog.models import Product, Unit
    from apps.inventory import services as inv_services
    from apps.inventory.models import Warehouse
    from apps.organizations.models import Company, CompanyMembership, FiscalPeriod, FiscalYear
    from apps.parties.models import Party
    from apps.sales import services as sales_services
    from django.contrib.auth import get_user_model

    def acct(company, code, t, nb):
        return Account.objects.create(
            company=company,
            code=code,
            name=code,
            account_type=t,
            normal_balance=nb,
            is_postable=True,
            is_active=True,
        )

    company = Company.objects.create(name="Perf Co")
    fy = FiscalYear.objects.create(
        company=company, name="FY", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fy,
        name="Year",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN",
    )
    cash = acct(company, "1000", "ASSET", "DEBIT")
    ar = acct(company, "1200", "ASSET", "DEBIT")
    inv_acct = acct(company, "1300", "ASSET", "DEBIT")
    tax = acct(company, "2200", "LIABILITY", "CREDIT")
    revenue = acct(company, "4000", "REVENUE", "CREDIT")
    cogs = acct(company, "5100", "EXPENSE", "DEBIT")
    customer = Party.objects.create(company=company, code="C1", name="Cust", kind="CUSTOMER")
    pcs = Unit.objects.create(company=company, code="PCS", name="Piece")
    product = Product.objects.create(company=company, sku="P1", name="Widget", base_unit=pcs)
    warehouse = Warehouse.objects.create(company=company, code="WH", name="Main")

    user = get_user_model().objects.create_user(username="perf", password="perf-pass-123")
    CompanyMembership.objects.create(company=company, user=user, role="OWNER")

    for i in range(200):
        acct_services.post_journal_entry(
            company=company,
            entry_date=DAY,
            lines=[{"account": cash, "debit": D("100")}, {"account": revenue, "credit": D("100")}],
            description=f"Perf entry {i}",
        )
    inv_services.receive_stock(
        company=company,
        warehouse=warehouse,
        product=product,
        quantity=D("100000"),
        unit_cost=D("10"),
        doc_date=DAY,
    )
    gl = {
        "receivables": ar,
        "revenue": revenue,
        "tax_payable": tax,
        "cogs": cogs,
        "inventory": inv_acct,
    }
    for i in range(50):
        inv_obj = sales_services.create_sales_invoice(
            company=company,
            customer=customer,
            invoice_number=f"SINV-{i}",
            invoice_date=DAY,
            warehouse=warehouse,
            lines=[{"product": product, "quantity": D("5"), "unit_price": D("25")}],
        )
        sales_services.post_sales_invoice(inv_obj, gl_accounts=gl)
    return company, user


def timed(label, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    print(f"{label}: {elapsed * 1000:.0f} ms")
    return result, elapsed


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    call_command("migrate", run_syncdb=True, verbosity=0)
    company, user = seed()
    print(f"seeded company {company.id}: 200 journal entries, 50 sales invoices")

    from apps.accounting import reporting as acct_reporting
    from apps.inventory import reporting as inv_reporting
    from apps.reporting import services as reporting_services

    timed("service trial_balance", lambda: acct_reporting.trial_balance(company))
    with CaptureQueriesContext(connection) as ctx:
        acct_reporting.trial_balance(company)
    print(f"service trial_balance queries: {len(ctx)}")

    timed("service dashboard_data", lambda: reporting_services.dashboard_data(company))
    with CaptureQueriesContext(connection) as ctx:
        reporting_services.dashboard_data(company)
    print(f"service dashboard_data queries: {len(ctx)}")

    timed("service stock_balances", lambda: inv_reporting.stock_balances(company))
    with CaptureQueriesContext(connection) as ctx:
        inv_reporting.stock_balances(company)
    print(f"service stock_balances queries: {len(ctx)}")

    client = Client()
    client.force_login(user)
    client.get("/")  # warm-up: template/static loaders, first-request cost excluded
    timed("HTTP GET / (dashboard)", lambda: client.get("/"))
    timed("HTTP GET / (dashboard, again)", lambda: client.get("/"))
    timed(
        "HTTP GET /accounting/trial-balance/?company=",
        lambda: client.get(f"/accounting/trial-balance/?company={company.id}"),
    )
    timed("HTTP GET /inventory/stock/", lambda: client.get("/inventory/stock/"))


if __name__ == "__main__":
    main()
