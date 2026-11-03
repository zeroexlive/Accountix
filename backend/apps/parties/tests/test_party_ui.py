"""Sprint 12 — party create/edit through the UI (scope A, ADR-039)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.organizations.models import CompanyMembership
from apps.parties.models import Party
from apps.treasury.tests._helpers import build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="x")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _payload(w, **overrides):
    data = {
        "company": str(w.company.pk),
        "kind": "SUPPLIER",
        "code": "SUP-9",
        "name": "New Supplier",
        "legal_name": "",
        "tax_id": "",
        "registration_number": "",
        "email": "",
        "phone": "",
        "is_active": "on",
        "contacts-TOTAL_FORMS": "1",
        "contacts-INITIAL_FORMS": "0",
        "contacts-MIN_NUM_FORMS": "0",
        "contacts-MAX_NUM_FORMS": "1000",
        "contacts-0-full_name": "Ali Ahmadi",
        "contacts-0-role": "Sales",
        "contacts-0-phone": "09120000000",
        "contacts-0-email": "",
        "contacts-0-is_primary": "on",
        "addresses-TOTAL_FORMS": "1",
        "addresses-INITIAL_FORMS": "0",
        "addresses-MIN_NUM_FORMS": "0",
        "addresses-MAX_NUM_FORMS": "1000",
        "addresses-0-label": "Office",
        "addresses-0-line1": "No. 1, First St",
        "addresses-0-line2": "",
        "addresses-0-city": "Tehran",
        "addresses-0-province": "",
        "addresses-0-postal_code": "",
        "addresses-0-country": "",
    }
    data.update(overrides)
    return data


def test_party_create_with_contact_and_address(client):
    w = build_world()
    _member_client(client, w.company)
    resp = client.post(reverse("party_create"), _payload(w))
    party = Party.objects.get(company=w.company, code="SUP-9")
    assert resp.status_code == 302
    assert resp.url == reverse("party_detail", args=[party.pk])
    assert party.kind == "SUPPLIER"
    assert party.contacts.count() == 1
    assert party.contacts.first().full_name == "Ali Ahmadi"
    assert party.addresses.count() == 1
    assert party.addresses.first().city == "Tehran"


def test_party_create_without_inlines(client):
    w = build_world()
    _member_client(client, w.company)
    payload = _payload(
        w,
        **{
            "contacts-0-full_name": "",
            "contacts-0-role": "",
            "contacts-0-phone": "",
            "addresses-0-label": "",
            "addresses-0-line1": "",
            "addresses-0-city": "",
        },
    )
    del payload["contacts-0-is_primary"]  # an unchecked box sends nothing
    resp = client.post(reverse("party_create"), payload)
    assert resp.status_code == 302
    party = Party.objects.get(company=w.company, code="SUP-9")
    assert party.contacts.count() == 0
    assert party.addresses.count() == 0


def test_party_edit_updates_name_and_keeps_company(client):
    w = build_world()
    _member_client(client, w.company)
    party = w.supplier
    payload = _payload(
        w,
        code=party.code,
        name="Renamed Supplier",
        **{
            "contacts-TOTAL_FORMS": "1",
            "contacts-INITIAL_FORMS": "0",
            "addresses-TOTAL_FORMS": "1",
            "addresses-INITIAL_FORMS": "0",
            "contacts-0-full_name": "",
            "contacts-0-role": "",
            "contacts-0-phone": "",
            "addresses-0-label": "",
            "addresses-0-line1": "",
            "addresses-0-city": "",
        },
    )
    del payload["contacts-0-is_primary"]
    resp = client.post(reverse("party_edit", args=[party.pk]), payload)
    assert resp.status_code == 302
    party.refresh_from_db()
    assert party.name == "Renamed Supplier"
    assert party.company_id == w.company.pk


def test_party_create_non_member_company_is_404(client):
    w = build_world()
    outsider = User.objects.create_user(username="outsider", password="x")
    client.force_login(outsider)
    resp = client.post(reverse("party_create"), _payload(w))
    assert resp.status_code == 404
    assert not Party.objects.filter(company=w.company, code="SUP-9").exists()


def test_party_detail_of_other_company_is_404(client):
    w = build_world()
    other = build_world(company_name="Other Co")
    _member_client(client, w.company)
    resp = client.get(reverse("party_detail", args=[other.supplier.pk]))
    assert resp.status_code == 404
    resp = client.get(reverse("party_edit", args=[other.supplier.pk]))
    assert resp.status_code == 404
