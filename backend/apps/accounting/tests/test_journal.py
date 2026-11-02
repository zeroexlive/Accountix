from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounting import reporting, services
from apps.accounting.models import Account, JournalEntry, JournalLine, JournalReversal
from apps.audit.models import AuditEvent
from apps.organizations.models import Company, CompanyMembership, FiscalPeriod, FiscalYear

User = get_user_model()
D = Decimal


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
def cash(db, company):
    return acct(company, "1000")


@pytest.fixture
def revenue(db, company):
    return acct(company, "4000", account_type="REVENUE", normal_balance="CREDIT")


def balanced_lines(cash, revenue, amount="100.00"):
    return [
        {"account": cash, "debit": D(amount)},
        {"account": revenue, "credit": D(amount)},
    ]


@pytest.mark.django_db
def test_balanced_posting_succeeds(company, period, cash, revenue):
    entry = services.post_journal_entry(
        company=company,
        entry_date=date(2026, 6, 1),
        lines=balanced_lines(cash, revenue),
        description="Sale",
    )
    assert entry.status == "POSTED"
    assert entry.fiscal_period == period
    assert entry.total_debit() == D("100.00") == entry.total_credit()
    assert entry.posted_at is not None
    assert AuditEvent.objects.filter(action="journal.posted", entity_id=str(entry.id)).exists()


@pytest.mark.django_db
def test_unbalanced_rejected_and_rolls_back(company, period, cash, revenue):
    lines = [{"account": cash, "debit": D("100")}, {"account": revenue, "credit": D("90")}]
    with pytest.raises(ValidationError):
        services.post_journal_entry(company=company, entry_date=date(2026, 6, 1), lines=lines)
    assert JournalEntry.objects.count() == 0
    assert JournalLine.objects.count() == 0


@pytest.mark.django_db
def test_fewer_than_two_lines_rejected(company, period, cash):
    with pytest.raises(ValidationError):
        services.post_journal_entry(
            company=company,
            entry_date=date(2026, 6, 1),
            lines=[{"account": cash, "debit": D("100")}],
        )
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db
def test_line_with_both_sides_rejected(company, period, cash, revenue):
    lines = [
        {"account": cash, "debit": D("100"), "credit": D("100")},
        {"account": revenue, "credit": D("100")},
    ]
    with pytest.raises(ValidationError):
        services.post_journal_entry(company=company, entry_date=date(2026, 6, 1), lines=lines)


@pytest.mark.django_db
def test_non_postable_account_rejected(company, period, cash, revenue):
    cash.is_postable = False
    cash.save()
    with pytest.raises(ValidationError):
        services.post_journal_entry(
            company=company, entry_date=date(2026, 6, 1), lines=balanced_lines(cash, revenue)
        )
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db
def test_inactive_account_rejected(company, period, cash, revenue):
    revenue.is_active = False
    revenue.save()
    with pytest.raises(ValidationError):
        services.post_journal_entry(
            company=company, entry_date=date(2026, 6, 1), lines=balanced_lines(cash, revenue)
        )


@pytest.mark.django_db
def test_cross_company_account_rejected(company, period, cash, other_company):
    foreign = acct(other_company, "1000")
    lines = [{"account": cash, "debit": D("5")}, {"account": foreign, "credit": D("5")}]
    with pytest.raises(ValidationError):
        services.post_journal_entry(company=company, entry_date=date(2026, 6, 1), lines=lines)
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db
def test_missing_fiscal_period_rejected(company, cash, revenue):
    # No FiscalYear/Period exists for this company at all.
    with pytest.raises(ValidationError):
        services.post_journal_entry(
            company=company, entry_date=date(2026, 6, 1), lines=balanced_lines(cash, revenue)
        )


@pytest.mark.django_db
def test_closed_fiscal_period_rejected(company, period, cash, revenue):
    period.status = "CLOSED"
    period.save()
    with pytest.raises(ValidationError):
        services.post_journal_entry(
            company=company, entry_date=date(2026, 6, 1), lines=balanced_lines(cash, revenue)
        )
    assert JournalEntry.objects.count() == 0


@pytest.mark.django_db
def test_idempotency_key_does_not_duplicate(company, period, cash, revenue):
    kwargs = {
        "company": company,
        "entry_date": date(2026, 6, 1),
        "lines": balanced_lines(cash, revenue),
        "idempotency_key": "invoice-42",
    }
    first = services.post_journal_entry(**kwargs)
    second = services.post_journal_entry(**kwargs)
    assert first.pk == second.pk
    assert JournalEntry.objects.count() == 1
    assert JournalLine.objects.count() == 2


@pytest.mark.django_db
def test_posted_entry_mutation_rejected(company, period, cash, revenue):
    entry = services.post_journal_entry(
        company=company, entry_date=date(2026, 6, 1), lines=balanced_lines(cash, revenue)
    )
    entry.description = "tampered"
    with pytest.raises(ValidationError):
        entry.save()
    line = entry.lines.first()
    line.debit = D("999")
    with pytest.raises(ValidationError):
        line.save()
    with pytest.raises(ValidationError):
        entry.delete()


@pytest.mark.django_db
def test_reversal_balances_and_marks_original(company, period, cash, revenue):
    entry = services.post_journal_entry(
        company=company,
        entry_date=date(2026, 6, 1),
        lines=balanced_lines(cash, revenue),
        description="Sale",
    )
    reversal = services.reverse_journal_entry(entry=entry, reason="wrong amount")
    entry.refresh_from_db()
    assert entry.status == "REVERSED"
    assert reversal.status == "POSTED"
    assert reversal.reversal_of_id == entry.id
    assert reversal.total_debit() == D("100.00") == reversal.total_credit()
    # Net effect on the ledger is zero.
    assert reporting.account_balance(company, cash) == D("0")
    assert reporting.account_balance(company, revenue) == D("0")
    assert JournalReversal.objects.filter(original_entry=entry, reversal_entry=reversal).exists()
    assert AuditEvent.objects.filter(action="journal.reversed", entity_id=str(entry.id)).exists()


@pytest.mark.django_db
def test_double_reversal_rejected(company, period, cash, revenue):
    entry = services.post_journal_entry(
        company=company, entry_date=date(2026, 6, 1), lines=balanced_lines(cash, revenue)
    )
    reversal = services.reverse_journal_entry(entry=entry)
    with pytest.raises(ValidationError):
        services.reverse_journal_entry(entry=entry)
    with pytest.raises(ValidationError):
        services.reverse_journal_entry(entry=reversal)


@pytest.mark.django_db
def test_trial_balance_and_general_ledger(company, period, cash, revenue):
    services.post_journal_entry(
        company=company, entry_date=date(2026, 6, 1), lines=balanced_lines(cash, revenue, "250.00")
    )
    tb = reporting.trial_balance(company)
    assert tb["is_balanced"]
    assert tb["total_debit"] == D("250.00") == tb["total_credit"]
    gl = reporting.general_ledger(company, cash)
    assert len(gl) == 1 and gl[0]["running_balance"] == D("250.00")
    assert reporting.account_balance(company, revenue) == D("-250.00")


@pytest.mark.django_db
def test_reporting_isolated_per_company(company, period, cash, revenue, other_company):
    services.post_journal_entry(
        company=company, entry_date=date(2026, 6, 1), lines=balanced_lines(cash, revenue)
    )
    tb_other = reporting.trial_balance(other_company)
    assert tb_other["rows"] == [] and tb_other["total_debit"] == D("0")


@pytest.mark.django_db
def test_journal_list_view_isolated(client, company, period, cash, revenue):
    services.post_journal_entry(
        company=company,
        entry_date=date(2026, 6, 1),
        lines=balanced_lines(cash, revenue),
        description="SecretSale",
    )
    stranger = User.objects.create_user(username="stranger", password="x")
    client.force_login(stranger)
    resp = client.get(reverse("journal_list"))
    assert b"SecretSale" not in resp.content
    member = User.objects.create_user(username="member", password="x")
    CompanyMembership.objects.create(company=company, user=member, role="ACCOUNTANT")
    client.force_login(member)
    resp = client.get(reverse("journal_list"))
    assert b"SecretSale" in resp.content


@pytest.mark.django_db
def test_draft_entry_cannot_be_reversed(company, period, cash, revenue):
    fy_period = period
    entry = JournalEntry.objects.create(
        company=company, fiscal_period=fy_period, entry_date=date(2026, 6, 1), description="draft"
    )
    with pytest.raises(ValidationError):
        services.reverse_journal_entry(entry=entry)
