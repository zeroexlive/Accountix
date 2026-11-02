"""Sprint 08 — Reporting & UX tests.

Dashboard figures are asserted EQUAL to the values produced by the
owning apps' reporting services on the same dataset (the dashboard is a
presentation layer, ADR-031); exports are asserted on content, not just
status codes; print views and filters are asserted on what a member
sees and what a non-member cannot see.
"""

import csv
import io

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import JournalEntry
from apps.inventory import reporting as inv_reporting
from apps.organizations.models import CompanyMembership, FiscalPeriod
from apps.purchases import reporting as purchase_reporting
from apps.reporting import services as dash_services
from apps.sales import reporting as sales_reporting
from apps.treasury import services as treasury_services
from apps.treasury.tests._helpers import DAY, D, build_world, post_purchase, post_sale

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="pw")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _seed_with_cash_receipt():
    """World + posted purchase + posted sale + a 500 cash receipt
    allocated to the sale. Returns (world, purchase, sale)."""
    w = build_world()
    purchase = post_purchase(w)
    sale = post_sale(w)
    receipt = treasury_services.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.cash_treasury,
        amount=D("500"),
        payment_date=DAY,
        method="CASH",
    )
    receipt = treasury_services.post_payment(receipt, gl_accounts={"receivable": w.ar})
    treasury_services.allocate_payment(receipt, sale, D("500"))
    return w, purchase, sale


# ---------------------------------------------------------------------------
# Dashboard aggregation equals the underlying services
# ---------------------------------------------------------------------------


def test_dashboard_figures_equal_source_services():
    w, purchase, sale = _seed_with_cash_receipt()
    data = dash_services.dashboard_data(w.company)

    assert data["cash_total"] == D("500")
    assert data["bank_total"] == D("0")
    assert data["ar_total"] == sales_reporting.ar_total(w.company, w.ar) == D("600")
    assert data["ap_total"] == purchase_reporting.ap_total(w.company, w.ap) == D("1100")
    assert data["inventory_valuation"] == inv_reporting.inventory_valuation(w.company) == D("600")
    assert data["sales_total"] == sale.grand_total == D("1100")
    assert data["purchase_total"] == purchase.grand_total == D("1100")
    statement = acct_reporting.income_statement(w.company, cogs_accounts=[])
    assert data["revenue_total"] == statement["revenue_total"] == D("1000")
    assert data["net_income"] == statement["net_income"] == D("600")
    # COGS accounts are expense-type: with no designation they remain in
    # expenses and the net result is unchanged; no gross profit is made.
    assert data["income_statement"]["cogs_rows"] == []
    assert data["open_receivable_total"] == D("600")
    assert data["open_payable_total"] == D("1100")
    assert data["outstanding_cheques_count"] == 0
    assert data["period"] is not None


def test_dashboard_low_stock_and_view(client):
    w, purchase, sale = _seed_with_cash_receipt()
    w.product.min_stock_level = D("10")
    w.product.save()
    data = dash_services.dashboard_data(w.company)
    assert data["low_stock_count"] == 1  # 6 in stock, minimum 10

    client = _member_client(client, w.company)
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    assert resp.context["dashboard"]["net_income"] == D("600")
    assert b"P-1" in resp.content  # low-stock warning row


def test_dashboard_requires_membership(client):
    w = build_world()
    other = build_world(company_name="Foreign Co")
    client = _member_client(client, w.company)
    resp = client.get(reverse("dashboard"), {"company": other.company.pk})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Statement filters (period / date range / COGS designation)
# ---------------------------------------------------------------------------


def test_income_statement_period_and_date_filters(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    period = FiscalPeriod.objects.get(company=w.company)

    resp = client.get(reverse("income_statement"), {"company": w.company.pk, "period": period.pk})
    assert resp.context["result"]["revenue_total"] == D("1000")

    resp = client.get(
        reverse("income_statement"), {"company": w.company.pk, "date_from": "2026-07-01"}
    )
    assert resp.context["result"]["revenue_total"] == D("0")
    assert resp.context["result"]["net_income"] == D("0")


def test_income_statement_cogs_designation_shows_gross_profit(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(
        reverse("income_statement"), {"company": w.company.pk, "cogs": [str(w.cogs.pk)]}
    )
    result = resp.context["result"]
    assert result["cogs_total"] == D("400")
    assert result["gross_profit"] == D("600")
    assert result["net_income"] == D("600")


def test_balance_sheet_as_of_filter(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(reverse("balance_sheet"), {"company": w.company.pk, "as_of": "2026-01-15"})
    result = resp.context["result"]
    assert result["total_assets"] == D("0")
    assert result["is_balanced"]


# ---------------------------------------------------------------------------
# List filters + pagination
# ---------------------------------------------------------------------------


def test_invoice_list_filters(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)

    resp = client.get(reverse("sales_invoice_list"), {"payment_status": "PARTIALLY_PAID"})
    assert [inv.invoice_number for inv in resp.context["invoices"]] == ["SINV-1"]
    resp = client.get(reverse("sales_invoice_list"), {"payment_status": "PAID"})
    assert len(resp.context["invoices"]) == 0
    resp = client.get(reverse("sales_invoice_list"), {"q": "Customer"})
    assert len(resp.context["invoices"]) == 1
    resp = client.get(reverse("sales_invoice_list"), {"date_from": "2026-07-01"})
    assert len(resp.context["invoices"]) == 0
    resp = client.get(reverse("purchase_invoice_list"), {"q": "Supplier"})
    assert len(resp.context["invoices"]) == 1


def test_journal_pagination(client):
    w = build_world()
    period = FiscalPeriod.objects.get(company=w.company)
    for i in range(30):
        JournalEntry.objects.create(
            company=w.company, fiscal_period=period, entry_date=DAY, description=f"Draft {i}"
        )
    client = _member_client(client, w.company)
    resp = client.get(reverse("journal_list"))
    assert len(resp.context["page_obj"]) == 25
    resp = client.get(reverse("journal_list"), {"page": 2})
    assert len(resp.context["page_obj"]) == 5
    resp = client.get(reverse("journal_list"), {"status": "POSTED"})
    assert len(resp.context["page_obj"]) == 0


def test_stock_movement_list_filters(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(reverse("stock_movements"))
    assert resp.status_code == 200
    assert len(resp.context["page_obj"]) == 2  # receipt + issue for P-1
    resp = client.get(reverse("stock_movements"), {"q": "NOPE"})
    assert len(resp.context["page_obj"]) == 0
    resp = client.get(reverse("stock_movements"), {"warehouse": w.warehouse.pk})
    assert len(resp.context["page_obj"]) == 2


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


def _csv_rows(response):
    return list(csv.reader(io.StringIO(response.content.decode("utf-8"))))


def test_trial_balance_csv_sums_and_headers(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(reverse("export_trial_balance_csv"), {"company": w.company.pk})
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "trial-balance.csv" in resp["Content-Disposition"]
    rows = _csv_rows(resp)
    total_row = rows[-1]
    assert total_row[0] == "TOTAL"
    assert D(total_row[2]) == D(total_row[3])  # debits == credits
    service = acct_reporting.trial_balance(w.company)
    assert D(total_row[2]) == service["total_debit"]


def test_trial_balance_xlsx_cells(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(reverse("export_trial_balance_xlsx"), {"company": w.company.pk})
    assert resp.status_code == 200
    assert "trial-balance.xlsx" in resp["Content-Disposition"]
    workbook = load_workbook(io.BytesIO(resp.content))
    sheet = workbook.active
    codes = [row[0].value for row in sheet.iter_rows()]
    assert "4100" in codes  # revenue account row present
    total_row = list(sheet.iter_rows())[-1]
    assert total_row[2].value == total_row[3].value
    assert D(str(total_row[2].value)) == acct_reporting.trial_balance(w.company)["total_debit"]


def test_stock_balances_and_open_items_csv(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)

    resp = client.get(reverse("export_stock_balances_csv"), {"company": w.company.pk})
    rows = _csv_rows(resp)
    data_rows = [r for r in rows[1:] if r and r[1] == "P-1"]
    assert len(data_rows) == 1
    assert D(data_rows[0][3]) == D("6")  # quantity after sale
    assert D(data_rows[0][4]) == D("600")  # value

    resp = client.get(reverse("export_stock_balances_xlsx"), {"company": w.company.pk})
    sheet = load_workbook(io.BytesIO(resp.content)).active
    assert any(row[1].value == "P-1" for row in sheet.iter_rows())

    resp = client.get(reverse("export_open_items_csv"), {"company": w.company.pk})
    rows = _csv_rows(resp)
    by_number = {r[1]: r for r in rows[1:]}
    assert D(by_number["SINV-1"][7]) == D("600")  # 1100 - 500 allocated
    assert D(by_number["PINV-1"][7]) == D("1100")


def test_general_ledger_csv(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)
    resp = client.get(
        reverse("export_general_ledger_csv"), {"company": w.company.pk, "account": w.ar.pk}
    )
    rows = _csv_rows(resp)
    assert rows[-1][4] == "600.00" or D(rows[-1][4]) == D("600")  # running balance ends at AR


def test_exports_reject_foreign_company(client):
    w = build_world()
    other = build_world(company_name="Foreign Co")
    client = _member_client(client, w.company)
    for name in (
        "export_trial_balance_csv",
        "export_trial_balance_xlsx",
        "export_stock_balances_csv",
        "export_open_items_csv",
    ):
        resp = client.get(reverse(name), {"company": other.company.pk})
        assert resp.status_code == 404, name


# ---------------------------------------------------------------------------
# Print views
# ---------------------------------------------------------------------------


def test_invoice_print_views(client):
    w, purchase, sale = _seed_with_cash_receipt()
    client = _member_client(client, w.company)

    resp = client.get(reverse("sales_invoice_print", args=[sale.pk]))
    assert resp.status_code == 200
    assert b"SINV-1" in resp.content
    assert b"1100" in resp.content

    resp = client.get(reverse("purchase_invoice_print", args=[purchase.pk]))
    assert resp.status_code == 200
    assert b"PINV-1" in resp.content

    resp = client.get(
        reverse("customer_statement_print"),
        {"company": w.company.pk, "account": w.ar.pk, "customer": w.customer.pk},
    )
    assert resp.status_code == 200
    assert b"CUS-1" in resp.content

    resp = client.get(
        reverse("supplier_statement_print"),
        {"company": w.company.pk, "account": w.ap.pk, "supplier": w.supplier.pk},
    )
    assert resp.status_code == 200
    assert b"SUP-1" in resp.content


def test_print_views_404_for_non_member(client):
    w, purchase, sale = _seed_with_cash_receipt()
    other = build_world(company_name="Foreign Co")
    client = _member_client(client, other.company, username="outsider")
    assert client.get(reverse("sales_invoice_print", args=[sale.pk])).status_code == 404
    assert client.get(reverse("purchase_invoice_print", args=[purchase.pk])).status_code == 404
