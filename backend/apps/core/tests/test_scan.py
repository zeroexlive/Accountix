"""Sprint 31 (ADR-060) — barcode/QR scanning: lookup endpoint,
phone pairing lifecycle, and the security posture around both.

The world mirrors the i18n crawls' builders: one company with a
barcoded product, a second company whose product shares the same
barcode string (cross-company isolation is the point), an OWNER,
a VIEWER, and a non-member.
"""

import hashlib
import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.catalog.models import Product, Unit
from apps.core.models import ScanSession, ScanSubmission
from apps.organizations.models import Company, CompanyMembership

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def world(db):
    class W:
        pass

    w = W()
    w.company = Company.objects.create(name="Scan Co")
    w.other = Company.objects.create(name="Other Co")
    unit = Unit.objects.create(company=w.company, code="PCS", name="Piece")
    other_unit = Unit.objects.create(company=w.other, code="PCS", name="Piece")
    w.product = Product.objects.create(
        company=w.company,
        sku="SKU-1",
        barcode="1234567890123",
        name="Barcoded Widget",
        base_unit=unit,
        default_sale_price="250.00",
        default_purchase_price="100.00",
    )
    w.plain = Product.objects.create(
        company=w.company, sku="SKU-2", name="No Barcode", base_unit=unit
    )
    w.foreign = Product.objects.create(
        company=w.other,
        sku="SKU-9",
        barcode="1234567890123",  # same barcode, different company
        name="Foreign Widget",
        base_unit=other_unit,
    )
    w.owner = User.objects.create_user(username="owner", password="Str0ng!Pass1")
    CompanyMembership.objects.create(user=w.owner, company=w.company, role="OWNER")
    w.viewer = User.objects.create_user(username="viewer", password="Str0ng!Pass1")
    CompanyMembership.objects.create(user=w.viewer, company=w.company, role="VIEWER")
    w.outsider = User.objects.create_user(username="outsider", password="Str0ng!Pass1")
    return w


def _create_session(client, world, user=None):
    client.force_login(user or world.owner)
    resp = client.post(reverse("scan_session_create"), {"company": str(world.company.pk)})
    assert resp.status_code == 200, resp.content
    data = resp.json()
    raw = data["phone_url"].rstrip("/").split("/")[-1]
    return data, raw


# --- Lookup ---------------------------------------------------------


def test_lookup_by_barcode_and_sku(client, world):
    client.force_login(world.owner)
    resp = client.get(
        reverse("scan_lookup"), {"code": "1234567890123", "company": world.company.pk}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(world.product.pk)
    assert data["sku"] == "SKU-1"
    assert data["sale_price"] == "250.00"
    assert data["purchase_price"] == "100.00"
    assert data["unit_id"] == str(world.product.base_unit_id)

    resp = client.get(reverse("scan_lookup"), {"code": "SKU-2", "company": world.company.pk})
    assert resp.status_code == 200
    assert resp.json()["id"] == str(world.plain.pk)


def test_lookup_barcode_wins_over_sku(client, world):
    # Another product whose SKU equals the first product's barcode:
    # the barcode match must win (scan semantics).
    Product.objects.create(
        company=world.company,
        sku="1234567890123",
        name="SKU Twin",
        base_unit=world.product.base_unit,
    )
    client.force_login(world.owner)
    resp = client.get(
        reverse("scan_lookup"), {"code": "1234567890123", "company": world.company.pk}
    )
    assert resp.json()["id"] == str(world.product.pk)


def test_lookup_unknown_code_is_translated_404(client, world):
    client.force_login(world.owner)
    resp = client.get(reverse("scan_lookup"), {"code": "NOPE", "company": world.company.pk})
    assert resp.status_code == 404
    assert resp.json()["error"]  # a message, in the active language


def test_lookup_never_leaks_other_company(client, world):
    client.force_login(world.owner)
    resp = client.get(reverse("scan_lookup"), {"code": "SKU-9", "company": world.company.pk})
    assert resp.status_code == 404  # exists — in the OTHER company


def test_lookup_requires_operate_and_login(client, world):
    resp = client.get(reverse("scan_lookup"), {"code": "SKU-1", "company": world.company.pk})
    assert resp.status_code == 302  # anonymous -> login
    client.force_login(world.viewer)
    resp = client.get(reverse("scan_lookup"), {"code": "SKU-1", "company": world.company.pk})
    assert resp.status_code == 403  # VIEWER may not operate


def test_lookup_foreign_company_404s(client, world):
    client.force_login(world.owner)
    resp = client.get(reverse("scan_lookup"), {"code": "SKU-9", "company": world.other.pk})
    assert resp.status_code == 404  # not a member of Other Co


# --- Pairing lifecycle ------------------------------------------------


def test_pairing_full_flow(client, world):
    data, raw = _create_session(client, world)
    session = ScanSession.objects.get()
    # Only the hash is stored — the raw token appears nowhere in the DB.
    assert session.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in session.token_hash

    page = client.get(reverse("scan_phone_page", args=[raw]))
    assert page.status_code == 200
    body = page.content.decode()
    assert "Scan Co" in body
    assert "Foreign Widget" not in body  # nothing beyond company + creator

    submit = client.post(
        reverse("scan_phone_submit", args=[raw]),
        data=json.dumps({"code": "1234567890123"}),
        content_type="application/json",
    )
    assert submit.status_code == 200
    assert submit.json()["product"]["name"] == "Barcoded Widget"

    results = client.get(data["results_url"])
    assert results.status_code == 200
    payload = results.json()
    assert payload["live"] is True
    assert len(payload["results"]) == 1
    assert payload["results"][0]["product"]["id"] == str(world.product.pk)

    again = client.get(data["results_url"])
    assert again.json()["results"] == []  # consumed exactly once
    assert ScanSubmission.objects.get().consumed is True


def test_phone_submit_unknown_and_cross_company_codes_404(client, world):
    _data, raw = _create_session(client, world)
    for code in ("NOPE", "SKU-9"):  # unknown, and other company's SKU
        resp = client.post(
            reverse("scan_phone_submit", args=[raw]),
            data=json.dumps({"code": code}),
            content_type="application/json",
        )
        assert resp.status_code == 404, code
    assert ScanSubmission.objects.count() == 0


def test_phone_wrong_expired_and_revoked_tokens_404(client, world):
    data, raw = _create_session(client, world)
    assert client.get(reverse("scan_phone_page", args=["bogus-token"])).status_code == 404
    assert (
        client.post(
            reverse("scan_phone_submit", args=["bogus-token"]),
            data=json.dumps({"code": "SKU-1"}),
            content_type="application/json",
        ).status_code
        == 404
    )

    session = ScanSession.objects.get()
    session.expires_at = timezone.now() - timedelta(seconds=1)
    session.save()
    assert client.get(reverse("scan_phone_page", args=[raw])).status_code == 404

    session.expires_at = timezone.now() + timedelta(minutes=5)
    session.save()
    resp = client.post(data["revoke_url"])
    assert resp.status_code == 200
    assert client.get(reverse("scan_phone_page", args=[raw])).status_code == 404
    results = client.get(data["results_url"])
    assert results.json()["live"] is False


def test_session_creation_requires_operate(client, world):
    client.force_login(world.viewer)
    resp = client.post(reverse("scan_session_create"), {"company": str(world.company.pk)})
    assert resp.status_code == 403
    client.logout()
    resp = client.post(reverse("scan_session_create"), {"company": str(world.company.pk)})
    assert resp.status_code == 302


def test_session_creation_cap(client, world):
    client.force_login(world.owner)
    for _ in range(3):
        resp = client.post(
            reverse("scan_session_create"), {"company": str(world.company.pk)}
        )
        assert resp.status_code == 200
    resp = client.post(reverse("scan_session_create"), {"company": str(world.company.pk)})
    assert resp.status_code == 429


def test_submission_cap(client, world):
    _data, raw = _create_session(client, world)
    session = ScanSession.objects.get()
    ScanSubmission.objects.bulk_create(
        ScanSubmission(session=session, product=world.product, code="SKU-1")
        for _ in range(120)
    )
    resp = client.post(
        reverse("scan_phone_submit", args=[raw]),
        data=json.dumps({"code": "SKU-1"}),
        content_type="application/json",
    )
    assert resp.status_code == 429


def test_results_are_private_to_the_creator(client, world):
    data, _raw = _create_session(client, world)
    client.force_login(world.outsider)
    assert client.get(data["results_url"]).status_code == 404
    assert client.post(data["revoke_url"]).status_code == 404


def test_invoice_forms_render_the_scan_widget(client, world):
    client.force_login(world.owner)
    for url_name in ("sales_invoice_create", "purchase_invoice_create"):
        resp = client.get(reverse(url_name), {"company": world.company.pk})
        assert resp.status_code == 200, url_name
        body = resp.content.decode()
        assert "data-scan-root" in body, url_name
        assert "js/scan.js" in body, url_name
        assert "vendor/jsQR.js" in body, url_name
