"""Sprint 18 — CAMT.053 / OFX statement import through the UI
(ADR-044): the two-phase create-from-file flow (upload → prefilled
editable header → create + import with the totals identity) and
the generalized detail-page import with per-transaction errors.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.organizations.models import CompanyMembership
from apps.treasury.models import BankStatement
from apps.treasury.tests._helpers import build_world
from apps.treasury.tests._statement_files import CAMT_BROKEN, CAMT_CLEAN, OFX1

User = get_user_model()
pytestmark = pytest.mark.django_db

D = Decimal


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="<redacted>")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _messages(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def _preview(client, w, content, filename):
    return client.post(
        reverse("bank_statement_create"),
        {
            "company": str(w.company.pk),
            "treasury_account": str(w.bank_treasury.pk),
            "statement_file": SimpleUploadedFile(filename, content, content_type="text/xml"),
        },
    )


def _create_post(w, **overrides):
    data = {
        "company": str(w.company.pk),
        "treasury_account": str(w.bank_treasury.pk),
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "opening_balance": "0",
        "closing_balance": "0",
        "source_note": "",
    }
    data.update(overrides)
    return data


def test_create_from_camt_file_prefills_header_then_creates(client):
    w = build_world()
    _member_client(client, w.company)

    resp = _preview(client, w, CAMT_CLEAN.encode(), "statement.xml")
    assert resp.status_code == 200
    form = resp.context["form"]
    assert form.initial["treasury_account"] == w.bank_treasury
    assert form.initial["start_date"] == date(2026, 6, 1)
    assert form.initial["end_date"] == date(2026, 6, 30)
    assert form.initial["opening_balance"] == D("100.00")
    assert form.initial["closing_balance"] == D("900.00")
    preview = resp.context["file_preview"]
    assert preview["format"] == "camt053"
    assert preview["row_count"] == 2
    assert preview["rejected"] == []

    resp = client.post(
        reverse("bank_statement_create"),
        _create_post(w, opening_balance="100", closing_balance="900"),
    )
    assert resp.status_code == 302
    statement = BankStatement.objects.get(company=w.company)
    assert statement.opening_balance == D("100")
    assert statement.closing_balance == D("900")
    assert sorted(line.amount for line in statement.lines.all()) == [D("-300"), D("1100")]


def test_create_from_ofx_file_prefills_closing_and_period_only(client):
    w = build_world()
    _member_client(client, w.company)

    resp = _preview(client, w, OFX1.encode(), "statement.ofx")
    assert resp.status_code == 200
    form = resp.context["form"]
    assert form.initial["start_date"] == date(2026, 6, 1)
    assert form.initial["end_date"] == date(2026, 6, 30)
    assert form.initial["closing_balance"] == D("1749.75")
    # OFX carries no opening balance and there is no completed
    # statement to chain from: the field stays for the user.
    assert form.initial.get("opening_balance") is None

    resp = client.post(
        reverse("bank_statement_create"),
        _create_post(w, opening_balance="1000", closing_balance="1749.75"),
    )
    assert resp.status_code == 302
    statement = BankStatement.objects.get(company=w.company)
    assert statement.lines.count() == 3


def test_create_from_file_with_tampered_closing_is_refused(client):
    w = build_world()
    _member_client(client, w.company)
    assert _preview(client, w, CAMT_CLEAN.encode(), "statement.xml").status_code == 200

    resp = client.post(
        reverse("bank_statement_create"),
        _create_post(w, opening_balance="100", closing_balance="950"),
    )
    assert resp.status_code == 200
    assert "جمع‌های صورت‌حساب سازگار نیستند" in resp.content.decode()
    # The refusal is atomic: no statement, no lines.
    assert BankStatement.objects.filter(company=w.company).count() == 0
    # The file preview stays on the page so the figures can be fixed.
    assert resp.context["file_preview"]["format"] == "camt053"


def test_detail_import_ofx_then_duplicate_reimport(client):
    w = build_world()
    _member_client(client, w.company)
    resp = client.post(
        reverse("bank_statement_create"),
        _create_post(w, opening_balance="1000", closing_balance="1749.75"),
    )
    assert resp.status_code == 302
    statement = BankStatement.objects.get(company=w.company)

    resp = client.post(
        reverse("bank_statement_import", args=[statement.pk]),
        {"file": SimpleUploadedFile("statement.ofx", OFX1.encode(), content_type="text/plain")},
    )
    assert resp.status_code == 302
    assert statement.lines.count() == 3
    assert sorted(line.reference for line in statement.lines.all()) == [
        "202606010001",
        "202606020001",
        "202606150001",
    ]

    resp = client.post(
        reverse("bank_statement_import", args=[statement.pk]),
        {"file": SimpleUploadedFile("statement.ofx", OFX1.encode(), content_type="text/plain")},
        follow=True,
    )
    assert resp.status_code == 200
    assert statement.lines.count() == 3
    # XML-format rejections are labelled by transaction index.
    assert any("تراکنش 1" in message for message in _messages(resp))


def test_detail_import_camt_reports_broken_transaction_by_index(client):
    w = build_world()
    _member_client(client, w.company)
    resp = client.post(reverse("bank_statement_create"), _create_post(w))
    assert resp.status_code == 302
    statement = BankStatement.objects.get(company=w.company)

    resp = client.post(
        reverse("bank_statement_import", args=[statement.pk]),
        {"file": SimpleUploadedFile("statement.xml", CAMT_BROKEN.encode())},
        follow=True,
    )
    assert resp.status_code == 200
    assert statement.lines.count() == 2
    messages = _messages(resp)
    assert any("تراکنش 3" in message and "قابل خواندن نیست" in message for message in messages)


def test_import_post_by_non_member_is_404(client):
    w = build_world()
    other = build_world(company_name="Other Co")
    _member_client(client, w.company)
    resp = client.post(reverse("bank_statement_create"), _create_post(w))
    assert resp.status_code == 302
    statement = BankStatement.objects.get(company=w.company)

    stranger = User.objects.create_user(username="stranger", password="<redacted>")
    CompanyMembership.objects.create(user=stranger, company=other.company, role="OWNER")
    client.force_login(stranger)
    resp = client.post(
        reverse("bank_statement_import", args=[statement.pk]),
        {"file": SimpleUploadedFile("statement.xml", CAMT_CLEAN.encode())},
    )
    assert resp.status_code == 404
    assert statement.lines.count() == 0
