"""Sprint 13 — opening balances through the UI (ADR-029).

Unbalanced form lines are the point of the page: the service appends
the difference on the user-picked offset account so the posted entry
balances by construction. One entry per fiscal year — a second visit
shows the existing entry instead of a duplicate form.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounting import reporting
from apps.accounting.models import JournalEntry
from apps.organizations.models import CompanyMembership
from apps.treasury.tests._helpers import _acct, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db
D = Decimal


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="pw")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _payload(w, equity, fy):
    return {
        "company": str(w.company.pk),
        "fiscal_year": str(fy.pk),
        "offset_account": str(equity.pk),
        "lines-TOTAL_FORMS": "3",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-account": str(w.cash.pk),
        "lines-0-debit": "5000",
        "lines-0-credit": "",
        "lines-0-party": "",
        "lines-1-account": str(w.inventory.pk),
        "lines-1-debit": "2000",
        "lines-1-credit": "",
        "lines-1-party": "",
        "lines-2-account": str(w.ap.pk),
        "lines-2-debit": "",
        "lines-2-credit": "1500",
        "lines-2-party": str(w.supplier.pk),
    }


def _setup():
    w = build_world()
    equity = _acct(w.company, "3100", "Opening equity", "EQUITY", "CREDIT")
    fy = w.company.fiscal_years.get()
    return w, equity, fy


def test_opening_balance_via_ui_balances_by_construction(client):
    w, equity, fy = _setup()
    _member_client(client, w.company)
    resp = client.post(reverse("opening_balance_create"), _payload(w, equity, fy))
    assert resp.status_code == 302
    entry = JournalEntry.objects.get(company=w.company, source_type="opening_balance")
    # Lines sum to Dr 7000 / Cr 1500; the offset takes Cr 5500.
    assert entry.total_debit() == entry.total_credit() == D("7000")
    offset_line = entry.lines.get(account=equity)
    assert offset_line.credit == D("5500")
    assert reporting.account_balance(w.company, w.cash) == D("5000")
    assert reporting.account_balance(w.company, equity) == D("-5500")
    assert reporting.account_balance(w.company, w.ap) == D("-1500")
    assert reporting.trial_balance(w.company)["is_balanced"]


def test_opening_balance_page_shows_existing_entry_on_second_visit(client):
    w, equity, fy = _setup()
    _member_client(client, w.company)
    client.post(reverse("opening_balance_create"), _payload(w, equity, fy))
    entry = JournalEntry.objects.get(company=w.company, source_type="opening_balance")

    resp = client.get(reverse("opening_balance_create"), {"company": w.company.pk})
    assert resp.status_code == 200
    assert resp.context["existing"].pk == entry.pk
    content = resp.content.decode()
    assert reverse("journal_detail", args=[entry.pk]) in content

    # A second POST cannot create a duplicate either.
    client.post(reverse("opening_balance_create"), _payload(w, equity, fy))
    assert (
        JournalEntry.objects.filter(
            company=w.company, idempotency_key=f"opening-balance:{fy.id}"
        ).count()
        == 1
    )


def test_opening_balance_two_sided_line_renders_service_error(client):
    w, equity, fy = _setup()
    _member_client(client, w.company)
    payload = _payload(w, equity, fy)
    payload["lines-0-credit"] = "5000"  # both sides on one line
    resp = client.post(reverse("opening_balance_create"), payload)
    assert resp.status_code == 200
    assert not JournalEntry.objects.filter(company=w.company).exists()
    errors = resp.context["form"].non_field_errors()
    assert any("یا بدهکار است یا بستانکار" in e for e in errors)


def test_opening_balance_non_member_cannot_post(client):
    w, equity, fy = _setup()
    other = build_world(company_name="Foreign Co")
    _member_client(client, other.company, username="outsider")
    resp = client.post(reverse("opening_balance_create"), _payload(w, equity, fy))
    assert resp.status_code == 404
    assert not JournalEntry.objects.filter(company=w.company).exists()
