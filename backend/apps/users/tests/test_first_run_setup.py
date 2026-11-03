"""First-run setup (Sprint 24, ADR-049).

While the user table is empty (and the kill switch is on), the login
view hands every request to /setup/, where the installer creates the
first admin + company in one transaction. Once any user exists the
setup page is dead. These tests pin that lifecycle; the ordinary
login behaviour with users present stays covered by test_auth.py.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from apps.organizations.models import Company, CompanyMembership

User = get_user_model()

pytestmark = pytest.mark.django_db

STRONG = "Tr7!qzvx-2941"
SETUP_DATA = {
    "username": "admin",
    "password1": STRONG,
    "password2": STRONG,
    "company_name": "شرکت نمونه",
}


def test_login_redirects_to_setup_with_zero_users(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 302
    assert resp.url == reverse("setup")


def test_login_post_redirects_to_setup_with_zero_users(client):
    resp = client.post(reverse("login"), {"username": "x", "password": "y"})
    assert resp.status_code == 302
    assert resp.url == reverse("setup")


def test_root_chain_ends_at_setup_with_zero_users(client):
    resp = client.get(reverse("dashboard"), follow=True)
    assert resp.status_code == 200
    assert resp.redirect_chain[0][0].startswith(reverse("login"))
    assert resp.redirect_chain[-1][0] == reverse("setup")
    assert b"auth-card" in resp.content


def test_setup_page_renders_persian_auth_card(client):
    resp = client.get(reverse("setup"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'lang="fa"' in body and 'dir="rtl"' in body
    assert "auth-card" in body
    assert "راه‌اندازی اولیه" in body


def test_weak_password_creates_nothing(client):
    resp = client.post(reverse("setup"), {**SETUP_DATA, "password1": "1234", "password2": "1234"})
    assert resp.status_code == 200  # form re-rendered with errors
    assert resp.context["form"].errors
    assert User.objects.count() == 0
    assert Company.objects.count() == 0
    assert CompanyMembership.objects.count() == 0


def test_password_mismatch_creates_nothing(client):
    resp = client.post(reverse("setup"), {**SETUP_DATA, "password2": STRONG + "x"})
    assert resp.status_code == 200
    assert resp.context["form"].errors
    assert User.objects.count() == 0
    assert Company.objects.count() == 0


def test_valid_setup_creates_admin_company_membership_and_logs_in(client):
    resp = client.post(reverse("setup"), SETUP_DATA)
    assert resp.status_code == 302
    assert resp.url == reverse("dashboard")

    user = User.objects.get(username="admin")
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.check_password(STRONG)

    company = Company.objects.get(name="شرکت نمونه")
    membership = CompanyMembership.objects.get(user=user, company=company)
    assert membership.role == CompanyMembership.Role.OWNER

    # The POST already logged the admin in: the dashboard and a
    # company-scoped page render for them.
    assert client.get(reverse("dashboard")).status_code == 200
    resp = client.get(reverse("company_list"))
    assert resp.status_code == 200
    assert "شرکت نمونه" in resp.content.decode()


def test_setup_is_dead_once_a_user_exists(client):
    client.post(reverse("setup"), SETUP_DATA)

    # Anonymous: bounced to the (now ordinary) login page.
    anon = Client()
    resp = anon.get(reverse("setup"))
    assert resp.status_code == 302
    assert resp.url == reverse("login")
    resp = anon.post(reverse("setup"), {**SETUP_DATA, "username": "second"})
    assert resp.status_code == 302

    # Logged-in admin: bounced to the dashboard.
    resp = client.get(reverse("setup"))
    assert resp.status_code == 302
    assert resp.url == reverse("dashboard")
    resp = client.post(reverse("setup"), {**SETUP_DATA, "username": "second"})
    assert resp.status_code == 302

    # Nothing extra was created by any of those requests.
    assert User.objects.count() == 1
    assert Company.objects.count() == 1

    # And login is the ordinary page again.
    assert anon.get(reverse("login")).status_code == 200


def test_setup_page_renders_in_english_when_selected(client):
    client.cookies["django_language"] = "en"
    resp = client.get(reverse("setup"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert '<html lang="en" dir="ltr">' in body
    assert "First-run setup" in body
    assert "Create administrator and company" in body


@override_settings(FIRST_RUN_SETUP_ENABLED=False)
def test_kill_switch_disables_setup_even_with_zero_users(client):
    resp = client.get(reverse("setup"))
    assert resp.status_code == 302
    assert resp.url == reverse("login")
    resp = client.post(reverse("setup"), SETUP_DATA)
    assert resp.status_code == 302
    assert User.objects.count() == 0
    # Login renders normally (no setup redirect) so the documented
    # source-mode createsuperuser path remains the bootstrap.
    assert client.get(reverse("login")).status_code == 200
