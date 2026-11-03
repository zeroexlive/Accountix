"""Sprint 13 — fiscal closing / reopening through the UI (ADR-028).

The UI delegates to the accounting closing services: closing posts
one closing entry moving the period result into the user-picked
retained-earnings account and locks the period; reopening works only
through the service, which reverses the closing entry. All figures
below come from the seeded sale: revenue 1000, COGS 400, net 600.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounting import reporting
from apps.accounting.models import JournalEntry
from apps.organizations.models import CompanyMembership, FiscalPeriod, FiscalYear
from apps.treasury.tests._helpers import _acct, build_world, post_purchase, post_sale

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="pw")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _world_with_sale():
    w = build_world()
    w.retained = _acct(w.company, "3100", "Retained earnings", "EQUITY", "CREDIT")
    post_purchase(w)
    post_sale(w)
    return w


def _period(w):
    return w.company.fiscal_periods.get()


def test_close_period_via_ui_moves_result_and_locks(client):
    w = _world_with_sale()
    _member_client(client, w.company)
    period = _period(w)

    preview = client.get(reverse("fiscal_period_close", args=[period.pk]))
    assert preview.status_code == 200
    assert preview.context["result"]["net_income"] == 600

    resp = client.post(
        reverse("fiscal_period_close", args=[period.pk]),
        {"retained_earnings": str(w.retained.pk)},
    )
    assert resp.status_code == 302

    period.refresh_from_db()
    assert period.status == FiscalPeriod.Status.CLOSED
    # Income-statement accounts are zeroed inside the period…
    assert reporting.account_balance(w.company, w.revenue, fiscal_period=period) == 0
    assert reporting.account_balance(w.company, w.cogs, fiscal_period=period) == 0
    # …and the net result (600 profit) sits in retained earnings.
    assert reporting.account_balance(w.company, w.retained, fiscal_period=period) == -600
    closing = JournalEntry.objects.get(
        company=w.company, source_type="CLOSING", source_id=str(period.id)
    )
    assert closing.status == "POSTED"

    # The year detail page links the closing entry.
    detail = client.get(reverse("fiscal_year_detail", args=[period.fiscal_year_id]))
    assert detail.status_code == 200
    assert str(closing.pk) in detail.content.decode()


def test_posting_into_closed_period_via_journal_ui_is_rejected(client):
    w = _world_with_sale()
    _member_client(client, w.company)
    period = _period(w)
    client.post(
        reverse("fiscal_period_close", args=[period.pk]),
        {"retained_earnings": str(w.retained.pk)},
    )
    payload = {
        "company": str(w.company.pk),
        "entry_date": "2026-06-01",
        "description": "too late",
        "idempotency_key": "",
        "lines-TOTAL_FORMS": "2",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-account": str(w.cash.pk),
        "lines-0-debit": "10",
        "lines-0-credit": "0",
        "lines-0-description": "",
        "lines-0-party": "",
        "lines-1-account": str(w.revenue.pk),
        "lines-1-debit": "0",
        "lines-1-credit": "10",
        "lines-1-description": "",
        "lines-1-party": "",
    }
    resp = client.post(reverse("journal_create"), payload)
    assert resp.status_code == 302
    entry = JournalEntry.objects.get(company=w.company, description="too late")
    resp = client.post(reverse("journal_post", args=[entry.pk]), follow=True)
    assert resp.status_code == 200
    entry.refresh_from_db()
    assert entry.status == "DRAFT"
    # The rejected posting moved nothing (cash is untouched by the seed).
    assert reporting.account_balance(w.company, w.cash) == 0


def test_reopen_via_ui_reverses_closing_and_restores_balances(client):
    w = _world_with_sale()
    _member_client(client, w.company)
    period = _period(w)
    client.post(
        reverse("fiscal_period_close", args=[period.pk]),
        {"retained_earnings": str(w.retained.pk)},
    )
    resp = client.post(reverse("fiscal_period_reopen", args=[period.pk]))
    assert resp.status_code == 302
    period.refresh_from_db()
    assert period.status == FiscalPeriod.Status.OPEN
    assert reporting.account_balance(w.company, w.revenue, fiscal_period=period) == -1000
    assert reporting.account_balance(w.company, w.retained, fiscal_period=period) == 0
    closing = JournalEntry.objects.get(
        company=w.company, source_type="CLOSING", source_id=str(period.id)
    )
    assert closing.status == "REVERSED"


def test_close_empty_period_via_ui_creates_no_entry(client):
    w = build_world()
    _member_client(client, w.company)
    period = _period(w)
    retained = _acct(w.company, "3100", "Retained earnings", "EQUITY", "CREDIT")
    resp = client.post(
        reverse("fiscal_period_close", args=[period.pk]),
        {"retained_earnings": str(retained.pk)},
    )
    assert resp.status_code == 302
    period.refresh_from_db()
    assert period.status == FiscalPeriod.Status.CLOSED
    assert not JournalEntry.objects.filter(company=w.company, source_type="CLOSING").exists()


def test_close_fiscal_year_via_ui(client):
    w = _world_with_sale()
    _member_client(client, w.company)
    year = w.company.fiscal_years.get()
    resp = client.post(
        reverse("fiscal_year_close", args=[year.pk]),
        {"retained_earnings": str(w.retained.pk)},
    )
    assert resp.status_code == 302
    year.refresh_from_db()
    assert year.status == FiscalYear.Status.CLOSED
    assert _period(w).status == FiscalPeriod.Status.CLOSED
    assert reporting.account_balance(w.company, w.retained) == -600


def test_closing_pages_404_for_non_member(client):
    w = _world_with_sale()
    other = build_world(company_name="Foreign Co")
    _member_client(client, other.company, username="outsider")
    period = _period(w)
    year = w.company.fiscal_years.get()
    assert client.get(reverse("fiscal_year_detail", args=[year.pk])).status_code == 404
    assert client.get(reverse("fiscal_period_close", args=[period.pk])).status_code == 404
    assert (
        client.post(
            reverse("fiscal_period_close", args=[period.pk]),
            {"retained_earnings": str(w.retained.pk)},
        ).status_code
        == 404
    )
    assert client.post(reverse("fiscal_period_reopen", args=[period.pk])).status_code == 404
    period.refresh_from_db()
    assert period.status == FiscalPeriod.Status.OPEN
