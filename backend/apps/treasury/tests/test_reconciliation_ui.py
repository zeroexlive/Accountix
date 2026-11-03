"""Sprint 14 — bank reconciliation through the UI (ADR-041).

Create a statement, import its lines from CSV, auto-match, and try
to complete it while a bank fee is still unmatched — the detail page
must refuse; another company's statement is a 404 everywhere.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.organizations.models import CompanyMembership
from apps.treasury.models import BankStatement
from apps.treasury.tests._helpers import build_world
from apps.treasury.tests.test_reconciliation import CSV, _bank_world

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="<redacted>")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _create_statement_via_ui(client, w):
    resp = client.post(
        reverse("bank_statement_create"),
        {
            "company": str(w.company.pk),
            "treasury_account": str(w.bank_treasury.pk),
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
            "opening_balance": "0",
            "closing_balance": "1850",
            "source_note": "",
        },
    )
    assert resp.status_code == 302
    return BankStatement.objects.get(company=w.company)


def test_statement_ui_flow(client):
    w = _bank_world()
    _member_client(client, w.company)
    statement = _create_statement_via_ui(client, w)

    resp = client.post(
        reverse("bank_statement_import", args=[statement.pk]),
        {"file": SimpleUploadedFile("statement.csv", CSV.encode(), content_type="text/csv")},
    )
    assert resp.status_code == 302
    statement.refresh_from_db()
    assert statement.lines.count() == 4

    resp = client.post(reverse("bank_statement_auto_match", args=[statement.pk]))
    assert resp.status_code == 302
    matched = statement.lines.filter(matched_journal_line__isnull=False)
    assert matched.count() == 1
    assert matched.get().reference == "TR-2"

    detail = client.get(reverse("bank_statement_detail", args=[statement.pk]))
    assert detail.status_code == 200
    assert b"2200" in detail.content  # the reconciliation difference

    # Completion is refused while lines are unmatched.
    resp = client.post(reverse("bank_statement_complete", args=[statement.pk]), follow=True)
    assert resp.status_code == 200
    statement.refresh_from_db()
    assert statement.status == "OPEN"
    assert "unmatched" in resp.content.decode() or "تطبیق‌نشده" in resp.content.decode()


def test_statement_ui_manual_line_and_match(client):
    w = _bank_world()
    _member_client(client, w.company)
    statement = _create_statement_via_ui(client, w)
    resp = client.post(
        reverse("bank_statement_add_line", args=[statement.pk]),
        {
            "line_date": "2026-06-02",
            "description": "Supplier transfer",
            "reference": "TR-2",
            "amount": "-300",
        },
    )
    assert resp.status_code == 302
    line = statement.lines.get()
    detail = client.get(reverse("bank_statement_detail", args=[statement.pk]))
    assert detail.status_code == 200
    # The unmatched book-movements panel offers this line for matching.
    assert str(line.pk).encode() in detail.content


def test_statement_ui_other_company_is_404(client):
    w = _bank_world()
    other = build_world(company_name="Other Co")
    _member_client(client, w.company)
    statement = _create_statement_via_ui(client, w)

    stranger = User.objects.create_user(username="stranger", password="<redacted>")
    CompanyMembership.objects.create(user=stranger, company=other.company, role="OWNER")
    client.force_login(stranger)

    assert client.get(reverse("bank_statement_detail", args=[statement.pk])).status_code == 404
    assert client.post(reverse("bank_statement_auto_match", args=[statement.pk])).status_code == 404
    assert client.post(reverse("bank_statement_complete", args=[statement.pk])).status_code == 404
    assert (
        client.post(
            reverse("bank_statement_add_line", args=[statement.pk]),
            {"line_date": "2026-06-02", "description": "", "reference": "X", "amount": "1"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("bank_statement_create"),
            {
                "company": str(w.company.pk),
                "treasury_account": str(w.bank_treasury.pk),
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "opening_balance": "0",
                "closing_balance": "0",
                "source_note": "",
            },
        ).status_code
        == 404
    )
