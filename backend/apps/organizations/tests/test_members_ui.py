"""Sprint 26 — members UI: GOVERN gating, the two add paths, the
last-owner guard, and immediate effect (ADR-051).

The GOVERN tier (Sprint 25, ADR-050) finally has a surface: only a
company's OWNER sees the members page and drives its actions; a
non-member still gets 404 everywhere (existence never leaks);
roles changed here govern the member's very next request, and
deactivation — the removal path, there is no hard delete — cuts
access at once.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from apps.accounting.models import JournalEntry
from apps.organizations import services as org_services
from apps.organizations.models import Company, CompanyMembership
from apps.treasury.tests._helpers import DAY, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db

STRONG_PASSWORD = "Str0ng!Pass-26"


def _company(name="Acme"):
    return Company.objects.create(name=name)


def _user(username):
    return User.objects.create_user(username=username, password="x")


def _member(company, username, role, **kwargs):
    user = _user(username)
    membership = CompanyMembership.objects.create(company=company, user=user, role=role, **kwargs)
    return user, membership


def _owner_company(name="Acme"):
    company = _company(name)
    owner, membership = _member(company, f"owner-{name}", "OWNER")
    return company, owner, membership


def _members_url(company):
    return reverse("company_members", args=[company.pk])


def _journal_payload(w):
    return {
        "company": str(w.company.pk),
        "entry_date": DAY.isoformat(),
        "description": "members test",
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


# ---------------------------------------------------------------------------
# GOVERN gating — the page and every action are OWNER-only
# ---------------------------------------------------------------------------


def test_members_page_renders_roster_for_owner(client):
    company, owner, _own = _owner_company()
    _member(company, "clerk", "ACCOUNTANT")
    client.force_login(owner)
    resp = client.get(_members_url(company))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "clerk" in body
    assert "حسابدار" in body  # the catalogued role label, rendered in fa
    assert reverse("company_member_add_existing", args=[company.pk]) in body
    assert reverse("company_member_add_new", args=[company.pk]) in body


@pytest.mark.parametrize("role", ["ADMIN", "ACCOUNTANT", "VIEWER"])
def test_members_page_is_403_for_non_owner_members(client, role):
    company, _owner, _own = _owner_company()
    member, _m = _member(company, f"member-{role}", role)
    client.force_login(member)
    assert client.get(_members_url(company)).status_code == 403


def test_members_page_is_404_for_non_member(client):
    company, _owner, _own = _owner_company()
    outsider = _user("outsider")
    client.force_login(outsider)
    assert client.get(_members_url(company)).status_code == 404


def test_member_actions_are_403_for_admin_and_change_nothing(client):
    company, _owner, _own = _owner_company()
    admin, _m = _member(company, "admin", "ADMIN")
    target, target_m = _member(company, "target", "VIEWER")
    _user("candidate")
    client.force_login(admin)

    resp = client.post(
        reverse("company_member_add_existing", args=[company.pk]),
        {"username": "candidate", "role": "VIEWER"},
    )
    assert resp.status_code == 403
    assert not CompanyMembership.objects.filter(company=company, user__username="candidate")

    resp = client.post(
        reverse("company_member_role", args=[company.pk, target_m.pk]), {"role": "CASHIER"}
    )
    assert resp.status_code == 403
    resp = client.post(reverse("company_member_deactivate", args=[company.pk, target_m.pk]))
    assert resp.status_code == 403
    target_m.refresh_from_db()
    assert target_m.role == "VIEWER" and target_m.is_active


# ---------------------------------------------------------------------------
# Add path (a) — attach an existing user by exact username
# ---------------------------------------------------------------------------


def test_attach_existing_user_happy_path(client):
    company, owner, _own = _owner_company()
    _user("clerk")
    client.force_login(owner)
    resp = client.post(
        reverse("company_member_add_existing", args=[company.pk]),
        {"username": "clerk", "role": "ACCOUNTANT"},
    )
    assert resp.status_code == 302
    membership = CompanyMembership.objects.get(company=company, user__username="clerk")
    assert membership.role == "ACCOUNTANT" and membership.is_active


def test_attach_unknown_username_is_a_form_error(client):
    company, owner, _own = _owner_company()
    client.force_login(owner)
    resp = client.post(
        reverse("company_member_add_existing", args=[company.pk]),
        {"username": "ghost", "role": "VIEWER"},
    )
    assert resp.status_code == 200
    assert "کاربری با این نام کاربری یافت نشد." in resp.content.decode()
    assert CompanyMembership.objects.filter(company=company).count() == 1  # only the owner


def test_attach_already_member_is_a_form_error_not_an_integrity_error(client):
    company, owner, _own = _owner_company()
    client.force_login(owner)
    resp = client.post(
        reverse("company_member_add_existing", args=[company.pk]),
        {"username": owner.username, "role": "VIEWER"},
    )
    assert resp.status_code == 200
    assert "این کاربر از قبل عضو این شرکت است." in resp.content.decode()
    assert CompanyMembership.objects.filter(company=company).count() == 1


def test_attach_deactivated_member_points_at_reactivation_not_readd(client):
    company, owner, _own = _owner_company()
    user, _m = _member(company, "former", "VIEWER", is_active=False)
    client.force_login(owner)
    resp = client.post(
        reverse("company_member_add_existing", args=[company.pk]),
        {"username": user.username, "role": "CASHIER"},
    )
    assert resp.status_code == 200  # a form error, never a 500 from the constraint
    assert CompanyMembership.objects.filter(company=company, user=user).count() == 1


def test_attach_invalid_role_is_a_form_error(client):
    company, owner, _own = _owner_company()
    _user("clerk")
    client.force_login(owner)
    resp = client.post(
        reverse("company_member_add_existing", args=[company.pk]),
        {"username": "clerk", "role": "SUPERUSER"},
    )
    assert resp.status_code == 200
    assert not CompanyMembership.objects.filter(company=company, user__username="clerk")


# ---------------------------------------------------------------------------
# Add path (b) — create a new user inline
# ---------------------------------------------------------------------------


def _create_payload(**overrides):
    payload = {
        "username": "newbie",
        "first_name": "New",
        "last_name": "Bie",
        "password1": STRONG_PASSWORD,
        "password2": STRONG_PASSWORD,
        "role": "VIEWER",
    }
    payload.update(overrides)
    return payload


def test_create_new_user_happy_path_and_real_login(client):
    company, owner, _own = _owner_company()
    client.force_login(owner)
    resp = client.post(reverse("company_member_add_new", args=[company.pk]), _create_payload())
    assert resp.status_code == 302
    user = User.objects.get(username="newbie")
    assert user.get_full_name() == "New Bie"
    assert not user.is_staff and not user.is_superuser  # authority is the membership alone
    membership = CompanyMembership.objects.get(company=company, user=user)
    assert membership.role == "VIEWER" and membership.is_active

    fresh = Client()
    resp = fresh.post(reverse("login"), {"username": "newbie", "password": STRONG_PASSWORD})
    assert resp.status_code == 302
    assert fresh.get(reverse("dashboard")).status_code == 200


def test_create_new_user_weak_password_is_rejected_by_the_validators(client):
    company, owner, _own = _owner_company()
    client.force_login(owner)
    resp = client.post(
        reverse("company_member_add_new", args=[company.pk]),
        _create_payload(password1="1234", password2="1234"),
    )
    assert resp.status_code == 200
    assert not User.objects.filter(username="newbie").exists()
    assert CompanyMembership.objects.filter(company=company).count() == 1


def test_create_new_user_duplicate_username_is_a_form_error(client):
    company, owner, _own = _owner_company()
    client.force_login(owner)
    resp = client.post(
        reverse("company_member_add_new", args=[company.pk]),
        _create_payload(username=owner.username),
    )
    assert resp.status_code == 200
    assert User.objects.filter(username=owner.username).count() == 1
    assert CompanyMembership.objects.filter(company=company).count() == 1


# ---------------------------------------------------------------------------
# Role changes take effect immediately
# ---------------------------------------------------------------------------


def test_role_change_governs_the_members_very_next_request(client):
    w = build_world()
    owner, _own = _member(w.company, "boss", "OWNER")
    target, target_m = _member(w.company, "clerk", "ACCOUNTANT")

    member_client = Client()
    member_client.force_login(target)
    resp = member_client.post(reverse("journal_create"), _journal_payload(w))
    assert resp.status_code == 302  # ACCOUNTANT is OPERATE tier
    assert JournalEntry.objects.filter(company=w.company).count() == 1

    client.force_login(owner)
    resp = client.post(
        reverse("company_member_role", args=[w.company.pk, target_m.pk]), {"role": "VIEWER"}
    )
    assert resp.status_code == 302

    resp = member_client.post(reverse("journal_create"), _journal_payload(w))
    assert resp.status_code == 403  # demoted: the same POST now stops at the gate
    assert JournalEntry.objects.filter(company=w.company).count() == 1


# ---------------------------------------------------------------------------
# The last-owner guard
# ---------------------------------------------------------------------------


def test_sole_owner_cannot_demote_themselves(client):
    company, owner, own = _owner_company()
    client.force_login(owner)
    resp = client.post(reverse("company_member_role", args=[company.pk, own.pk]), {"role": "ADMIN"})
    assert resp.status_code == 302  # back to the page, with the refusal as a message
    own.refresh_from_db()
    assert own.role == "OWNER"


def test_sole_owner_cannot_deactivate_themselves(client):
    company, owner, own = _owner_company()
    client.force_login(owner)
    client.post(reverse("company_member_deactivate", args=[company.pk, own.pk]))
    own.refresh_from_db()
    assert own.is_active and own.role == "OWNER"


def test_second_owner_lifts_the_guard(client):
    company, owner, own = _owner_company()
    other, other_m = _member(company, "co-owner", "OWNER")
    client.force_login(owner)

    resp = client.post(
        reverse("company_member_role", args=[company.pk, other_m.pk]), {"role": "ADMIN"}
    )
    assert resp.status_code == 302
    other_m.refresh_from_db()
    assert other_m.role == "ADMIN"

    # …and the demoted co-owner's old row can now be deactivated, and a
    # self-demotion is fine too while another active owner remains.
    # (other_m is ADMIN now, so re-promote first via the service-free path:)
    CompanyMembership.objects.filter(pk=other_m.pk).update(role="OWNER")
    client.post(reverse("company_member_deactivate", args=[company.pk, own.pk]))
    own.refresh_from_db()
    assert not own.is_active  # owner deactivated themselves; co-owner still governs


def test_service_layer_repeats_the_guard_and_the_govern_assertion(client):
    company, owner, own = _owner_company()
    _admin, admin_m = _member(company, "admin", "ADMIN")

    with pytest.raises(ValidationError):
        org_services.change_member_role(actor=owner, membership=own, new_role="VIEWER")
    with pytest.raises(ValidationError):
        org_services.deactivate_member(actor=owner, membership=own)
    own.refresh_from_db()
    assert own.role == "OWNER" and own.is_active

    with pytest.raises(PermissionDenied):
        org_services.change_member_role(actor=_admin, membership=admin_m, new_role="CASHIER")
    with pytest.raises(PermissionDenied):
        org_services.add_member(actor=_admin, company=company, user=_user("x1"), role="VIEWER")
    admin_m.refresh_from_db()
    assert admin_m.role == "ADMIN"

    # actor=None is the trusted internal path (ADR-051, as in ADR-050 (3)).
    org_services.change_member_role(actor=None, membership=admin_m, new_role="CASHIER")
    admin_m.refresh_from_db()
    assert admin_m.role == "CASHIER"


# ---------------------------------------------------------------------------
# Deactivation is the removal path; reactivation restores access
# ---------------------------------------------------------------------------


def test_deactivation_cuts_access_immediately_and_reactivation_restores_it(client):
    company, owner, _own = _owner_company()
    member, membership = _member(company, "clerk", "ACCOUNTANT")
    detail_url = reverse("company_detail", args=[company.pk])

    member_client = Client()
    member_client.force_login(member)
    assert member_client.get(detail_url).status_code == 200

    client.force_login(owner)
    client.post(reverse("company_member_deactivate", args=[company.pk, membership.pk]))
    membership.refresh_from_db()
    assert not membership.is_active
    assert member_client.get(detail_url).status_code == 404  # invisible, as if never a member

    client.post(reverse("company_member_reactivate", args=[company.pk, membership.pk]))
    membership.refresh_from_db()
    assert membership.is_active and membership.role == "ACCOUNTANT"
    assert member_client.get(detail_url).status_code == 200


# ---------------------------------------------------------------------------
# Cross-company scoping
# ---------------------------------------------------------------------------


def test_membership_id_from_another_company_is_404(client):
    company_a, owner_a, _own = _owner_company("A Co")
    company_b = _company("B Co")
    _user_b, membership_b = _member(company_b, "b-clerk", "VIEWER")

    client.force_login(owner_a)
    assert client.get(_members_url(company_b)).status_code == 404
    resp = client.post(
        reverse("company_member_role", args=[company_a.pk, membership_b.pk]),
        {"role": "OWNER"},
    )
    assert resp.status_code == 404
    membership_b.refresh_from_db()
    assert membership_b.role == "VIEWER"


def test_full_name_column_and_inactive_rows_render(client):
    company, owner, _own = _owner_company()
    user, _m = _member(company, "former", "VIEWER", is_active=False)
    user.first_name, user.last_name = "Old", "Member"
    user.save()
    client.force_login(owner)
    body = client.get(_members_url(company)).content.decode()
    assert "Old Member" in body
    assert "غیرفعال" in body  # inactive rows stay visible, with a reactivate action
