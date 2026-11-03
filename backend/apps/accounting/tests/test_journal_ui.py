"""Sprint 12 — manual journal entry through the UI (ADR-039).

Golden path: create a draft via the form, post it from the detail
page, watch the trial balance move, reverse it, watch the account
balances return to zero. Plus the negative paths: an unbalanced
entry is rejected by the service and rendered as a form error, and a
non-member cannot create or even open another company's entry.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounting import reporting
from apps.accounting.models import JournalEntry
from apps.organizations.models import CompanyMembership
from apps.treasury.tests._helpers import DAY, D, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="x")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _create_payload(w, debit="500", credit="500"):
    return {
        "company": str(w.company.pk),
        "entry_date": DAY.isoformat(),
        "description": "UI entry",
        "idempotency_key": "",
        "lines-TOTAL_FORMS": "2",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-account": str(w.cash.pk),
        "lines-0-debit": debit,
        "lines-0-credit": "0",
        "lines-0-description": "",
        "lines-0-party": "",
        "lines-1-account": str(w.revenue.pk),
        "lines-1-debit": "0",
        "lines-1-credit": credit,
        "lines-1-description": "",
        "lines-1-party": "",
    }


def _balances(w):
    tb = reporting.trial_balance(w.company)
    return {row["code"]: row["balance"] for row in tb["rows"]}


def test_journal_ui_golden_path(client):
    w = build_world()
    _member_client(client, w.company)
    resp = client.get(reverse("journal_create"))
    assert resp.status_code == 200
    resp = client.post(reverse("journal_create"), _create_payload(w))
    entry = JournalEntry.objects.get(company=w.company)
    assert resp.status_code == 302
    assert resp.url == reverse("journal_detail", args=[entry.pk])
    assert entry.status == JournalEntry.Status.DRAFT
    assert _balances(w).get("1100", D("0")) == D("0")

    resp = client.post(reverse("journal_post", args=[entry.pk]))
    assert resp.status_code == 302
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.POSTED
    balances = _balances(w)
    assert balances["1100"] == D("500")
    assert balances["4100"] == D("-500")

    resp = client.post(reverse("journal_reverse", args=[entry.pk]), {"reason": "wrong"})
    assert resp.status_code == 302
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.REVERSED
    balances = _balances(w)
    assert balances["1100"] == D("0")
    assert balances["4100"] == D("0")


def test_journal_ui_unbalanced_rejected_with_form_error(client):
    w = build_world()
    _member_client(client, w.company)
    resp = client.post(reverse("journal_create"), _create_payload(w, credit="400"))
    assert resp.status_code == 200
    assert resp.context["form"].non_field_errors()
    assert JournalEntry.objects.filter(company=w.company).count() == 0


def test_journal_ui_cross_company_account_rejected(client):
    w = build_world()
    other = build_world(company_name="Other Co")
    _member_client(client, w.company)
    payload = _create_payload(w)
    payload["lines-0-account"] = str(other.cash.pk)
    resp = client.post(reverse("journal_create"), payload)
    assert resp.status_code == 200
    assert JournalEntry.objects.filter(company=w.company).count() == 0


def test_journal_ui_non_member_gets_404(client):
    w = build_world()
    outsider = User.objects.create_user(username="outsider", password="x")
    client.force_login(outsider)
    resp = client.post(reverse("journal_create"), _create_payload(w))
    assert resp.status_code == 404
    assert JournalEntry.objects.filter(company=w.company).count() == 0


def test_journal_detail_of_other_company_is_404(client):
    w = build_world()
    other = build_world(company_name="Other Co")
    _member_client(client, w.company)
    # Build the foreign entry through the service on the other world.
    from apps.accounting import services

    entry = services.create_journal_draft(
        company=other.company,
        entry_date=DAY,
        lines=[
            {"account": other.cash, "debit": D("10"), "credit": D("0")},
            {"account": other.revenue, "debit": D("0"), "credit": D("10")},
        ],
    )
    resp = client.get(reverse("journal_detail", args=[entry.pk]))
    assert resp.status_code == 404
    resp = client.post(reverse("journal_post", args=[entry.pk]))
    assert resp.status_code == 404
