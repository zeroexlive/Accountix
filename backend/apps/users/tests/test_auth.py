import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

# NOTE (Sprint 16): these tests log in by POSTing real credentials to
# the login view instead of Client.login(). Since django-axes guards
# authentication (ADR-043), its backend requires the HTTP request by
# design and raises for the request-less authenticate() call that
# Client.login() performs. Posting through the view exercises the same
# credential path an operator's browser takes.


@pytest.fixture
def user(db):
    return User.objects.create_user(username="jason", password="test-pass-12345")


@pytest.mark.django_db
def test_custom_user_model_is_active():
    assert User._meta.label == "users.User"


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 302
    assert "/login/" in resp.url


@pytest.mark.django_db
def test_login_and_dashboard(client, user):
    resp = client.post(reverse("login"), {"username": "jason", "password": "test-pass-12345"})
    assert resp.status_code == 302
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_login_page_renders_rtl_persian(client, user):
    # The `user` fixture matters: with an empty user table /login/
    # redirects to the first-run setup instead (Sprint 24, ADR-049).
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'lang="fa"' in body and 'dir="rtl"' in body


@pytest.mark.django_db
def test_logout(client, user):
    client.post(reverse("login"), {"username": "jason", "password": "test-pass-12345"})
    resp = client.post(reverse("logout"))
    assert resp.status_code == 302
    resp2 = client.get(reverse("dashboard"))
    assert resp2.status_code == 302
