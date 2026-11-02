import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


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
    assert client.login(username="jason", password="test-pass-12345")
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_login_page_renders_rtl_persian(client):
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'lang="fa"' in body and 'dir="rtl"' in body


@pytest.mark.django_db
def test_logout(client, user):
    client.login(username="jason", password="test-pass-12345")
    resp = client.post(reverse("logout"))
    assert resp.status_code == 302
    resp2 = client.get(reverse("dashboard"))
    assert resp2.status_code == 302
