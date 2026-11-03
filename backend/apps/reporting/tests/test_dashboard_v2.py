"""Sprint 11 — dashboard v2 tests (ADR-038).

The redesigned dashboard adds exactly two kinds of derived data —
period-over-period KPI deltas and a per-period revenue/expenses
series — plus a performance panel of shares. Every figure is pinned
against the owning apps' existing services on the same dataset: the
series sums must equal ``income_statement`` over the same range, the
percentages are asserted as numbers (not just "page renders"), and
zero denominators must produce the honest empty state, never a
fabricated percentage.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounting import reporting as acct_reporting
from apps.accounting import services as acct_services
from apps.accounting.models import Account
from apps.organizations.models import Company, FiscalPeriod, FiscalYear
from apps.purchases import services as purchase_services
from apps.reporting import services as dash
from apps.reporting.tests.test_reporting import _member_client, _seed_with_cash_receipt
from apps.sales import services as sales_services
from apps.treasury.models import Cheque
from apps.treasury.tests._helpers import D, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


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


def _two_period_world():
    """Company + one fiscal year with two periods + cash/revenue/
    expense accounts, nothing posted yet."""
    company = Company.objects.create(name="Series Co")
    fy = FiscalYear.objects.create(
        company=company, name="FY2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    p1 = FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fy,
        name="P1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
    )
    p2 = FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fy,
        name="P2",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 12, 31),
    )
    cash = _acct(company, "1100", "Cash", "ASSET", "DEBIT")
    revenue = _acct(company, "4100", "Revenue", "REVENUE", "CREDIT")
    expense = _acct(company, "6100", "Expense", "EXPENSE", "DEBIT")
    return company, fy, p1, p2, cash, revenue, expense


def _post(company, when, lines):
    return acct_services.post_journal_entry(company=company, entry_date=when, lines=lines)


# ---------------------------------------------------------------------------
# period_series — equality with income_statement
# ---------------------------------------------------------------------------


def test_period_series_sums_equal_income_statement():
    company, fy, p1, p2, cash, revenue, expense = _two_period_world()
    _post(
        company,
        date(2026, 3, 1),
        [{"account": cash, "debit": D("1000")}, {"account": revenue, "credit": D("1000")}],
    )
    _post(
        company,
        date(2026, 3, 2),
        [{"account": expense, "debit": D("250")}, {"account": cash, "credit": D("250")}],
    )
    _post(
        company,
        date(2026, 9, 1),
        [{"account": cash, "debit": D("1500")}, {"account": revenue, "credit": D("1500")}],
    )
    _post(
        company,
        date(2026, 9, 2),
        [{"account": expense, "debit": D("500")}, {"account": cash, "credit": D("500")}],
    )

    series = dash.period_series(company, fy)
    assert [row["label"] for row in series] == ["P1", "P2"]
    assert series[0]["revenue"] == D("1000") and series[0]["expenses"] == D("250")
    assert series[1]["revenue"] == D("1500") and series[1]["expenses"] == D("500")

    whole = acct_reporting.income_statement(
        company, date_from=fy.start_date, date_to=fy.end_date, cogs_accounts=[]
    )
    assert sum((r["revenue"] for r in series), D("0")) == whole["revenue_total"] == D("2500")
    assert (
        sum((r["expenses"] for r in series), D("0"))
        == (whole["expenses_total"] + whole["cogs_total"])
        == D("750")
    )

    # Bar heights are relative to the largest bar (P2 revenue = peak).
    assert series[1]["revenue_height"] == 100.0
    assert series[0]["revenue_height"] == pytest.approx(66.67, abs=0.01)
    assert series[0]["expenses_height"] == pytest.approx(16.67, abs=0.01)


def test_period_series_without_fiscal_year_is_empty():
    company, *_ = _two_period_world()
    assert dash.period_series(company, None) == []


# ---------------------------------------------------------------------------
# Delta helper — up / down / zero-previous / no-previous
# ---------------------------------------------------------------------------


def test_delta_pct_cases():
    assert dash._delta_pct(D("150"), D("100")) == D("50.0")
    assert dash._delta_pct(D("50"), D("100")) == D("-50.0")
    assert dash._delta_pct(D("100"), D("100")) == D("0.0")
    assert dash._delta_pct(D("100"), D("0")) is None  # zero previous: no badge
    assert dash._delta_pct(D("100"), None) is None  # no previous period


def _post_purchase_on(w, when, number):
    purchase = purchase_services.create_purchase_invoice(
        company=w.company,
        supplier=w.supplier,
        invoice_number=number,
        invoice_date=when,
        warehouse=w.warehouse,
        lines=[
            {"product": w.product, "quantity": D("10"), "unit_cost": D("100"), "tax_rate": D("0.1")}
        ],
    )
    return purchase_services.post_purchase_invoice(
        purchase,
        gl_accounts={
            "inventory": w.inventory,
            "payables": w.ap,
            "tax": w.tax_in,
            "expense": w.expense,
        },
    )


def _post_sale_on(w, when, number, qty):
    sale = sales_services.create_sales_invoice(
        company=w.company,
        customer=w.customer,
        invoice_number=number,
        invoice_date=when,
        warehouse=w.warehouse,
        lines=[
            {"product": w.product, "quantity": D(qty), "unit_price": D("250"), "tax_rate": D("0.1")}
        ],
    )
    return sales_services.post_sales_invoice(
        sale,
        gl_accounts={
            "receivables": w.ar,
            "revenue": w.revenue,
            "tax_payable": w.tax_out,
            "cogs": w.cogs,
            "inventory": w.inventory,
        },
    )


def test_dashboard_kpi_deltas_against_previous_period():
    w = build_world()
    FiscalYear.objects.create(
        company=w.company, name="FY2025", start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
    )
    fy25 = FiscalYear.objects.get(company=w.company, name="FY2025")
    prev = FiscalPeriod.objects.create(
        company=w.company,
        fiscal_year=fy25,
        name="2025",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        status="OPEN",
    )
    _post_purchase_on(w, date(2025, 6, 1), "PINV-25")
    _post_sale_on(w, date(2025, 6, 2), "SINV-25", "4")  # revenue 1000, total 1100
    _post_purchase_on(w, date(2026, 6, 1), "PINV-26")
    _post_sale_on(w, date(2026, 6, 2), "SINV-26", "8")  # revenue 2000, total 2200

    data = dash.dashboard_data(w.company)
    assert data["previous_period"] == prev
    assert data["kpis"]["revenue"] == {
        "current": D("2000"),
        "previous": D("1000"),
        "delta_pct": D("100.0"),
    }
    assert data["kpis"]["sales"]["delta_pct"] == D("100.0")
    assert data["kpis"]["purchases"]["delta_pct"] == D("0.0")


def test_dashboard_without_previous_period_omits_badges(client):
    w, purchase, sale = _seed_with_cash_receipt()
    data = dash.dashboard_data(w.company)
    assert data["previous_period"] is None
    for key in ("revenue", "sales", "purchases"):
        assert data["kpis"][key]["previous"] is None
        assert data["kpis"][key]["delta_pct"] is None

    client = _member_client(client, w.company)
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    assert b'class="delta' not in resp.content  # no fabricated badges


# ---------------------------------------------------------------------------
# Rendered dashboard — KPI values, chart totals, performance numbers
# ---------------------------------------------------------------------------


def test_dashboard_render_values_chart_and_performance(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    data = resp.context["dashboard"]

    # Chart series: the single period carries the seeded figures.
    assert data["series_revenue_total"] == D("1000")
    assert data["series_expenses_total"] == D("400")  # COGS stays in expenses
    assert b"bar rev" in resp.content and b"bar exp" in resp.content

    perf = {row["key"]: row for row in data["performance"]}
    # 500 of the 1100 sale collected -> 45.5%; nothing of the purchase paid.
    assert perf["collections"]["percent"] == Decimal("45.5")
    assert perf["settlements"]["percent"] == Decimal("0.0")
    assert perf["cheques"]["percent"] is None  # no cheques at all
    # One stocked product, none below its (zero) minimum -> healthy.
    assert perf["inventory_health"]["percent"] == Decimal("100.0")
    assert "45.5٪".encode() in resp.content
    assert "هنوز چک دریافتی ثبت نشده است.".encode() in resp.content

    # KPI cards show the same figures as Sprint 08 asserted.
    assert data["kpis"]["sales"]["current"] == D("1100")
    assert data["treasury_total"] == D("500")


def test_performance_cheque_share_by_amount():
    w, purchase, sale = _seed_with_cash_receipt()
    Cheque.objects.create(
        company=w.company,
        direction="RECEIVED",
        cheque_number="CHQ-CLEARED",
        amount=D("300"),
        due_date=date(2026, 5, 1),
        status="CLEARED",
    )
    Cheque.objects.create(
        company=w.company,
        direction="RECEIVED",
        cheque_number="CHQ-OPEN",
        amount=D("100"),
        due_date=date(2026, 7, 1),
        status="RECEIVED",
    )
    data = dash.dashboard_data(w.company)
    perf = {row["key"]: row for row in data["performance"]}
    assert perf["cheques"]["percent"] == Decimal("75.0")  # 300 / (300 + 100)


def test_performance_zero_denominators_render_empty_states(client):
    w = build_world()  # nothing posted: no invoices, no cheques, no stock
    data = dash.dashboard_data(w.company)
    perf = {row["key"]: row for row in data["performance"]}
    assert all(row["percent"] is None for row in perf.values())

    client = _member_client(client, w.company)
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    for row in data["performance"]:
        assert row["empty"].encode() in resp.content


# ---------------------------------------------------------------------------
# Shell — sidebar links resolve, main pages render, print untouched
# ---------------------------------------------------------------------------

SIDEBAR_URL_NAMES = [
    "dashboard",
    "company_list",
    "fiscal_year_list",
    "account_list",
    "journal_list",
    "trial_balance",
    "income_statement",
    "balance_sheet",
    "product_list",
    "stock_balances",
    "stock_movements",
    "inventory_counts",
    "party_list",
    "purchase_invoice_list",
    "accounts_payable",
    "sales_invoice_list",
    "accounts_receivable",
    "customer_statement",
    "treasury_account_list",
    "payment_list",
    "cheque_list",
    "treasury_open_items",
]


def test_sidebar_links_all_resolve_and_render(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(reverse("dashboard"))
    content = resp.content.decode()
    for name in SIDEBAR_URL_NAMES:
        path = reverse(name)  # raises NoReverseMatch on a dead link
        assert f'href="{path}"' in content, name


def test_main_pages_render_with_new_shell(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    for name in SIDEBAR_URL_NAMES:
        resp = client.get(reverse(name))
        assert resp.status_code == 200, name
        assert b'class="sidebar"' in resp.content, name
    resp = client.get(reverse("sales_invoice_detail", args=[sale.pk]))
    assert resp.status_code == 200
    resp = client.get(reverse("purchase_invoice_detail", args=[purchase.pk]))
    assert resp.status_code == 200


def test_login_page_uses_auth_card(client):
    # A user must exist: with an empty user table /login/ redirects
    # to the first-run setup instead (Sprint 24, ADR-049).
    User.objects.create_user(username="someone", password="pw-12345678")
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    assert b"auth-card" in resp.content
    assert b'class="sidebar"' not in resp.content


def test_print_views_unchanged_markers(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(reverse("sales_invoice_print", args=[sale.pk]))
    assert resp.status_code == 200
    assert b"SINV-1" in resp.content
    assert b"1100" in resp.content
    assert b"print-doc" in resp.content  # still the print base layout
    assert b'class="sidebar"' not in resp.content  # print has no app shell
