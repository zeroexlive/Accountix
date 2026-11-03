"""Sprint 27 — self-service account surface (ADR-052).

Profile + password change for the signed-in user themself. The
routes carry NO user id: the subject is always ``request.user``, so
these tests prove (a) the pages work for every role incl. VIEWER,
(b) the username cannot be smuggled into a change, (c) the password
flow's session semantics — this session survives, the old password
dies, the new one works — through REAL login POSTs (Sprint 16: axes
makes Client.login() unusable), and (d) failed password-change
attempts never feed the axes login lockout.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.organizations.models import Company, CompanyMembership

User = get_user_model()
pytestmark = pytest.mark.django_db

OLD_PASSWORD = "Old!Pass-2026-xyz"
NEW_PASSWORD = "New!Pass-2026-abc"


def _login(client, username, password):
    return client.post(reverse("login"), {"username": username, "password": password})


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="jason",
        password=OLD_PASSWORD,
        first_name="Jason",
        last_name="Ahmadi",
        email="jason@example.com",
    )


# -- anonymous -------------------------------------------------------


def test_anonymous_profile_redirects_to_login(client, user):
    resp = client.get(reverse("profile"))
    assert resp.status_code == 302
    assert "/login/" in resp.url


def test_anonymous_password_change_redirects_to_login(client, user):
    resp = client.get(reverse("password_change"))
    assert resp.status_code == 302
    assert "/login/" in resp.url


# -- profile ----------------------------------------------------------


def test_profile_get_shows_current_values(client, user):
    _login(client, "jason", OLD_PASSWORD)
    resp = client.get(reverse("profile"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "jason" in body  # username, read-only
    assert 'value="Jason"' in body
    assert 'value="Ahmadi"' in body
    assert 'value="jason@example.com"' in body
    # The form has no username input at all — nothing to smuggle into.
    assert 'name="username"' not in body


def test_profile_post_persists_and_shell_links_present(client, user):
    _login(client, "jason", OLD_PASSWORD)
    resp = client.post(
        reverse("profile"),
        {"first_name": "Reza", "last_name": "Karimi", "email": "reza@example.com"},
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.get_full_name() == "Reza Karimi"
    assert user.email == "reza@example.com"
    # Shell discoverability: profile + password links ride every page.
    body = client.get(reverse("dashboard")).content.decode()
    assert reverse("profile") in body
    assert reverse("password_change") in body


def test_profile_post_cannot_smuggle_username_change(client, user):
    _login(client, "jason", OLD_PASSWORD)
    resp = client.post(
        reverse("profile"),
        {
            "username": "hacked",
            "first_name": "Reza",
            "last_name": "Karimi",
            "email": "reza@example.com",
        },
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.username == "jason"
    assert user.first_name == "Reza"  # the legitimate fields still save


def test_profile_invalid_email_rejected(client, user):
    _login(client, "jason", OLD_PASSWORD)
    resp = client.post(
        reverse("profile"),
        {"first_name": "Jason", "last_name": "Ahmadi", "email": "not-an-email"},
    )
    assert resp.status_code == 200  # form error, nothing saved
    user.refresh_from_db()
    assert user.email == "jason@example.com"


def test_profile_name_change_reflects_on_members_roster(client, user):
    company = Company.objects.create(name="Roster Co")
    CompanyMembership.objects.create(company=company, user=user, role=CompanyMembership.Role.OWNER)
    _login(client, "jason", OLD_PASSWORD)
    client.post(
        reverse("profile"),
        {"first_name": "Reza", "last_name": "Karimi", "email": ""},
    )
    body = client.get(reverse("company_members", kwargs={"pk": company.pk})).content.decode()
    assert "Reza Karimi" in body


def test_profile_is_self_only_by_construction(client, user):
    other = User.objects.create_user(
        username="sara", password=OLD_PASSWORD, email="sara@example.com"
    )
    _login(client, "jason", OLD_PASSWORD)
    body = client.get(reverse("profile")).content.decode()
    assert "jason@example.com" in body
    assert "sara@example.com" not in body
    assert other.username not in body


def test_viewer_can_use_both_pages(client, db):
    viewer = User.objects.create_user(username="viewer1", password=OLD_PASSWORD)
    company = Company.objects.create(name="View Co")
    CompanyMembership.objects.create(
        company=company, user=viewer, role=CompanyMembership.Role.VIEWER
    )
    _login(client, "viewer1", OLD_PASSWORD)
    assert client.get(reverse("profile")).status_code == 200
    assert client.get(reverse("password_change")).status_code == 200
    resp = client.post(reverse("profile"), {"first_name": "Nazanin", "last_name": "", "email": ""})
    assert resp.status_code == 302
    viewer.refresh_from_db()
    assert viewer.first_name == "Nazanin"


# -- password change ---------------------------------------------------


def test_password_change_wrong_current_rejected(client, user):
    _login(client, "jason", OLD_PASSWORD)
    resp = client.post(
        reverse("password_change"),
        {
            "old_password": "not-the-password-1",
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )
    assert resp.status_code == 200
    assert resp.context["form"].errors  # form error, password unchanged
    user.refresh_from_db()
    assert user.check_password(OLD_PASSWORD)


def test_password_change_weak_new_rejected_by_validators(client, user):
    _login(client, "jason", OLD_PASSWORD)
    resp = client.post(
        reverse("password_change"),
        {"old_password": OLD_PASSWORD, "new_password1": "1234", "new_password2": "1234"},
    )
    assert resp.status_code == 200
    assert "new_password2" in resp.context["form"].errors
    user.refresh_from_db()
    assert user.check_password(OLD_PASSWORD)


def test_password_change_success_session_and_login_semantics(client, user):
    _login(client, "jason", OLD_PASSWORD)
    resp = client.post(
        reverse("password_change"),
        {
            "old_password": OLD_PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )
    assert resp.status_code == 302
    # This session stays signed in (update_session_auth_hash).
    assert client.get(reverse("dashboard")).status_code == 200
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    # A fresh client: the OLD password no longer logs in…
    from django.test import Client

    fresh = Client()
    resp_old = _login(fresh, "jason", OLD_PASSWORD)
    assert resp_old.status_code == 200  # login form re-rendered with error
    assert fresh.get(reverse("dashboard")).status_code == 302
    # …and the NEW password does.
    resp_new = _login(fresh, "jason", NEW_PASSWORD)
    assert resp_new.status_code == 302
    assert fresh.get(reverse("dashboard")).status_code == 200


def test_failed_password_changes_do_not_feed_axes_lockout(client, user):
    """PasswordChangeForm checks the current password via
    user.check_password() — no authenticate(), no user_login_failed
    signal — so any number of failures here must NOT count toward
    the axes login lockout (AXES_FAILURE_LIMIT is 5)."""
    _login(client, "jason", OLD_PASSWORD)
    for _ in range(6):
        resp = client.post(
            reverse("password_change"),
            {
                "old_password": "wrong-again-123",
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
            },
        )
        assert resp.status_code == 200
    client.post(reverse("logout"))
    resp = _login(client, "jason", OLD_PASSWORD)
    assert resp.status_code == 302  # not locked out — login still works
    assert client.get(reverse("dashboard")).status_code == 200


# -- version stamp ------------------------------------------------------


def test_version_renders_on_login_page(client, user):
    from config.version import __version__

    body = client.get(reverse("login")).content.decode()
    assert __version__ == "1.0.0"
    assert "1.0.0" in body


def test_version_renders_in_shell(client, user):
    _login(client, "jason", OLD_PASSWORD)
    body = client.get(reverse("dashboard")).content.decode()
    assert "1.0.0" in body
