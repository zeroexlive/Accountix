"""Sprint 07 — opening balances, fiscal closing/reopening, statements.

Everything asserted here is derived from journal lines: opening entries
balance by construction, closing zeroes the income-statement accounts
into retained earnings, the balance-sheet identity (Assets ==
Liabilities + Equity + current result) holds before AND after closing.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db.models import Sum

from apps.accounting import reporting
from apps.accounting.models import JournalEntry, JournalLine
from apps.accounting.services import (
    close_fiscal_period,
    close_fiscal_year,
    post_journal_entry,
    post_opening_balance,
    reopen_fiscal_period,
)
from apps.organizations.models import Company, FiscalPeriod, FiscalYear
from apps.treasury import services as treasury_services
from apps.treasury.tests._helpers import _acct, build_world, post_purchase, post_sale

D = Decimal
DAY = date(2026, 6, 1)
pytestmark = pytest.mark.django_db


def _equity(company):
    return _acct(company, "3100", "Retained earnings", "EQUITY", "CREDIT")


# ---------------------------------------------------------------------------
# Opening balances
# ---------------------------------------------------------------------------


def test_opening_balance_balances_and_lands_in_first_period():
    w = build_world()
    equity = _equity(w.company)
    period = w.company.fiscal_periods.get()
    entry = post_opening_balance(
        company=w.company,
        fiscal_year=period.fiscal_year,
        lines=[
            {"account": w.cash, "debit": D("5000")},
            {"account": w.inventory, "debit": D("2000")},
            {"account": w.ap, "credit": D("1500"), "party": w.supplier},
        ],
        offset_account=equity,
    )
    assert entry.status == "POSTED"
    assert entry.source_type == "opening_balance"
    assert entry.entry_date == period.start_date
    assert entry.fiscal_period_id == period.id
    assert entry.total_debit() == entry.total_credit() == D("7000")
    # Offset line: excess debits 5500 credited to equity.
    offset_line = entry.lines.get(account=equity)
    assert offset_line.credit == D("5500") and offset_line.debit == D("0")
    # Trial balance reflects the opening position.
    assert reporting.account_balance(w.company, w.cash) == D("5000")
    assert reporting.account_balance(w.company, equity) == D("-5500")
    assert reporting.account_balance(w.company, w.ap) == D("-1500")
    assert reporting.trial_balance(w.company)["is_balanced"]


def test_opening_balance_is_idempotent_per_fiscal_year():
    w = build_world()
    equity = _equity(w.company)
    fy = w.company.fiscal_years.get()
    kwargs = dict(
        company=w.company,
        fiscal_year=fy,
        lines=[{"account": w.cash, "debit": D("100")}],
        offset_account=equity,
    )
    first = post_opening_balance(**kwargs)
    second = post_opening_balance(**kwargs)
    assert first.id == second.id
    assert JournalEntry.objects.filter(idempotency_key=f"opening-balance:{fy.id}").count() == 1


def test_opening_balance_rejects_cross_company_and_two_sided_lines():
    w = build_world()
    equity = _equity(w.company)
    fy = w.company.fiscal_years.get()
    other = build_world(company_name="Other Co")
    with pytest.raises(ValidationError):
        post_opening_balance(
            company=w.company,
            fiscal_year=fy,
            lines=[{"account": other.cash, "debit": D("100")}],
            offset_account=equity,
        )
    with pytest.raises(ValidationError):
        post_opening_balance(
            company=w.company,
            fiscal_year=fy,
            lines=[{"account": w.cash, "debit": D("100"), "credit": D("100")}],
            offset_account=equity,
        )


def test_opening_balance_blocked_when_first_period_closed():
    w = build_world(period_status="CLOSED")
    equity = _equity(w.company)
    with pytest.raises(ValidationError):
        post_opening_balance(
            company=w.company,
            fiscal_year=w.company.fiscal_years.get(),
            lines=[{"account": w.cash, "debit": D("100")}],
            offset_account=equity,
        )


# ---------------------------------------------------------------------------
# Fiscal period closing / reopening
# ---------------------------------------------------------------------------


def test_close_period_zeroes_income_accounts_into_retained_earnings():
    w = build_world()
    equity = _equity(w.company)
    period = w.company.fiscal_periods.get()
    post_purchase(w)
    post_sale(w)

    closing = close_fiscal_period(company=w.company, period=period, retained_earnings=equity)
    assert closing is not None and closing.status == "POSTED"
    assert closing.lines.get(account=w.revenue).debit == D("1000")
    assert closing.lines.get(account=w.cogs).credit == D("400")
    assert closing.lines.get(account=equity).credit == D("600")

    period.refresh_from_db()
    assert period.status == "CLOSED"
    assert reporting.account_balance(w.company, w.revenue) == D("0")
    assert reporting.account_balance(w.company, w.cogs) == D("0")
    assert reporting.account_balance(w.company, equity) == D("-600")
    assert reporting.trial_balance(w.company, fiscal_period=period)["is_balanced"]

    # The posting gate now rejects new entries into the closed period.
    with pytest.raises(ValidationError):
        post_journal_entry(
            company=w.company,
            entry_date=DAY,
            lines=[
                {"account": w.cash, "debit": D("10")},
                {"account": w.ar, "credit": D("10")},
            ],
        )
    # Double closing is rejected.
    with pytest.raises(ValidationError):
        close_fiscal_period(company=w.company, period=period, retained_earnings=equity)


def test_reopen_reverses_closing_and_restores_balances():
    w = build_world()
    equity = _equity(w.company)
    period = w.company.fiscal_periods.get()
    post_purchase(w)
    post_sale(w)
    closing = close_fiscal_period(company=w.company, period=period, retained_earnings=equity)

    reversal = reopen_fiscal_period(company=w.company, period=period)
    assert reversal is not None
    period.refresh_from_db()
    closing.refresh_from_db()
    assert period.status == "OPEN"
    assert closing.status == "REVERSED"
    assert reporting.account_balance(w.company, w.revenue) == D("-1000")
    assert reporting.account_balance(w.company, w.cogs) == D("400")
    assert reporting.account_balance(w.company, equity) == D("0")

    # Closing again after a reopen posts a NEW closing entry.
    closing2 = close_fiscal_period(company=w.company, period=period, retained_earnings=equity)
    assert closing2.id != closing.id
    assert reporting.account_balance(w.company, equity) == D("-600")


def test_close_period_without_activity_closes_without_entry():
    w = build_world()
    equity = _equity(w.company)
    period = w.company.fiscal_periods.get()
    result = close_fiscal_period(company=w.company, period=period, retained_earnings=equity)
    assert result is None
    period.refresh_from_db()
    assert period.status == "CLOSED"
    # Reopening a period that had no closing entry just flips it back.
    assert reopen_fiscal_period(company=w.company, period=period) is None
    period.refresh_from_db()
    assert period.status == "OPEN"


def test_close_fiscal_year_closes_all_periods():
    company = Company.objects.create(name="Year Co")
    fy = FiscalYear.objects.create(
        company=company,
        name="FY2026",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN",
    )
    p1 = FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fy,
        name="H1",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        status="OPEN",
    )
    p2 = FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fy,
        name="H2",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 12, 31),
        status="OPEN",
    )
    cash = _acct(company, "1100", "Cash", "ASSET", "DEBIT")
    revenue = _acct(company, "4100", "Revenue", "REVENUE", "CREDIT")
    expense = _acct(company, "6100", "Expense", "EXPENSE", "DEBIT")
    equity = _acct(company, "3100", "Retained earnings", "EQUITY", "CREDIT")
    post_journal_entry(
        company=company,
        entry_date=date(2026, 2, 1),
        lines=[{"account": cash, "debit": D("1000")}, {"account": revenue, "credit": D("1000")}],
    )
    post_journal_entry(
        company=company,
        entry_date=date(2026, 8, 1),
        lines=[{"account": expense, "debit": D("300")}, {"account": cash, "credit": D("300")}],
    )
    entries = close_fiscal_year(company=company, fiscal_year=fy, retained_earnings=equity)
    assert len(entries) == 2
    p1.refresh_from_db()
    p2.refresh_from_db()
    fy.refresh_from_db()
    assert p1.status == p2.status == "CLOSED"
    assert fy.status == "CLOSED"
    # Net income 1000 - 300 = 700 now sits in retained earnings.
    assert reporting.account_balance(company, equity) == D("-700")
    assert reporting.account_balance(company, revenue) == D("0")
    assert reporting.account_balance(company, expense) == D("0")


# ---------------------------------------------------------------------------
# Financial statements
# ---------------------------------------------------------------------------


def _rich_dataset():
    """Opening balance + purchase + sale + supplier payment + cleared
    customer cheque — the Sprint 06 E2E chain plus an opening position."""
    w = build_world()
    equity = _equity(w.company)
    post_opening_balance(
        company=w.company,
        fiscal_year=w.company.fiscal_years.get(),
        lines=[{"account": w.cash, "debit": D("5000")}],
        offset_account=equity,
    )
    purchase = post_purchase(w)
    sale = post_sale(w)
    pay = treasury_services.create_payment(
        company=w.company,
        direction="PAYMENT",
        party=w.supplier,
        treasury_account=w.bank_treasury,
        amount=D("500"),
        payment_date=DAY,
        method="BANK_TRANSFER",
    )
    pay = treasury_services.post_payment(pay, gl_accounts={"payable": w.ap})
    treasury_services.allocate_payment(pay, purchase, D("500"))
    receipt = treasury_services.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.bank_treasury,
        amount=D("1100"),
        payment_date=DAY,
        method="CHEQUE",
        cheque={"bank_name": "Melli", "cheque_number": "S07-1", "due_date": date(2026, 6, 20)},
    )
    receipt = treasury_services.post_payment(
        receipt, gl_accounts={"receivable": w.ar, "cheques_in_hand": w.cheques_in_hand}
    )
    cheque = receipt.cheques.first()
    treasury_services.allocate_payment(receipt, sale, D("1100"))
    treasury_services.deposit_cheque(cheque)
    treasury_services.clear_cheque(cheque, bank_treasury_account=w.bank_treasury)
    return w, equity


def test_income_statement_matches_raw_lines():
    w, equity = _rich_dataset()
    stmt = reporting.income_statement(w.company, cogs_accounts=[w.cogs])
    assert stmt["revenue_total"] == D("1000")
    assert stmt["cogs_total"] == D("400")
    assert stmt["gross_profit"] == D("600")
    assert stmt["expenses_total"] == D("0")
    assert stmt["net_income"] == D("600")
    # Independent recomputation straight from raw journal lines.
    agg = (
        JournalLine.objects.filter(entry__company=w.company)
        .exclude(entry__source_type="CLOSING")
        .values("account__account_type")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
    )
    raw_net = D("0")
    for row in agg:
        if row["account__account_type"] == "REVENUE":
            raw_net += (row["credit"] or D("0")) - (row["debit"] or D("0"))
        elif row["account__account_type"] == "EXPENSE":
            raw_net -= (row["debit"] or D("0")) - (row["credit"] or D("0"))
    assert stmt["net_income"] == raw_net


def test_balance_sheet_identity_before_and_after_closing():
    w, equity = _rich_dataset()
    sheet = reporting.balance_sheet(w.company)
    assert sheet["total_assets"] == D("6300")  # cash 5000 + bank 600 + inv 600 + tax-in 100
    assert sheet["total_liabilities"] == D("700")  # AP 600 + output VAT 100
    assert sheet["total_equity"] == D("5000")
    assert sheet["current_period_result"] == D("600")
    assert sheet["is_balanced"]
    assert sheet["total_assets"] == sheet["total_liabilities_and_equity"]

    period = w.company.fiscal_periods.get()
    close_fiscal_period(company=w.company, period=period, retained_earnings=equity)
    sheet = reporting.balance_sheet(w.company)
    # The result moved into retained earnings; the identity still holds.
    assert sheet["current_period_result"] == D("0")
    assert sheet["total_equity"] == D("5600")
    assert sheet["is_balanced"]
    assert sheet["total_assets"] == D("6300")

    # The income statement still reports the period's operating result
    # (closing entries are excluded from it by design, ADR-030).
    stmt = reporting.income_statement(w.company, fiscal_period=period, cogs_accounts=[w.cogs])
    assert stmt["net_income"] == D("600")
    assert stmt["revenue_total"] == D("1000")
