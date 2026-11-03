"""Login throttling (Sprint 16, ADR-043) — django-axes policy tests.

Policy under test (config.settings.base): 5 failed logins for the same
(username, IP) combination lock that combination out for a 1-hour
cooloff; a successful login resets the counter; the lockout response is
the Persian lockout template with HTTP 403.

Axes state lives in the database (axes AccessAttempt rows). Every test
here runs in its own pytest-django transaction, and no other test in
the suite posts a wrong password, so no cross-test reset is needed —
these tests deliberately assert the full observable behaviour through
the real login view instead of mocking axes internals.
"""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from axes.models import AccessAttempt
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

User = get_user_model()

PASSWORD = "test-pass-12345"
NORMAL_ERROR = "نادرست"  # «نام کاربری یا گذرواژه نادرست است» on the login form
LOCKOUT_MARKER = "مسدود"  # «ورود موقتاً مسدود شد» on the lockout page


@pytest.fixture
def user(db):
    return User.objects.create_user(username="jason", password=PASSWORD)


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="sara", password=PASSWORD)


def attempt(client, username="jason", password="wrong-password", **extra):
    return client.post(reverse("login"), {"username": username, "password": password}, **extra)


def lock_out(client, username="jason"):
    """Drive the (username, this client's IP) combination into lockout."""
    for _ in range(settings.AXES_FAILURE_LIMIT):
        attempt(client, username=username)


@pytest.mark.django_db
def test_failures_below_limit_stay_normal_and_success_resets_counter(client, user):
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        resp = attempt(client)
        assert resp.status_code == 200
        body = resp.content.decode()
        assert NORMAL_ERROR in body
        assert LOCKOUT_MARKER not in body

    # Correct password still works below the limit…
    resp = attempt(client, password=PASSWORD)
    assert resp.status_code == 302
    # …and the success wiped the failure counter (reset-on-success).
    assert AccessAttempt.objects.count() == 0
    client.logout()

    # A fresh run of failures starts from zero: another limit-1 failures
    # must NOT lock (cumulatively they are 2× the limit if not reset).
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        resp = attempt(client)
        assert resp.status_code == 200
        assert LOCKOUT_MARKER not in resp.content.decode()
    resp = attempt(client, password=PASSWORD)
    assert resp.status_code == 302


@pytest.mark.django_db
def test_lockout_at_limit_refuses_even_the_correct_password(client, user):
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        assert attempt(client).status_code == 200

    # The attempt that reaches the limit gets the lockout page.
    resp = attempt(client)
    assert resp.status_code == 403
    body = resp.content.decode()
    assert LOCKOUT_MARKER in body
    assert NORMAL_ERROR not in body
    # The lockout page must not echo the username back.
    assert "jason" not in body

    # Correct password during the cooloff is refused the same way, and
    # the client is definitely not authenticated afterwards.
    resp = attempt(client, password=PASSWORD)
    assert resp.status_code == 403
    assert LOCKOUT_MARKER in resp.content.decode()
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 302
    assert "/login/" in resp.url


@pytest.mark.django_db
def test_lockout_expires_after_cooloff(client, user):
    lock_out(client)
    assert attempt(client, password=PASSWORD).status_code == 403

    # Simulate the cooloff elapsing: age the stored attempt beyond it.
    expired = timezone.now() - settings.AXES_COOLOFF_TIME - timedelta(minutes=5)
    AccessAttempt.objects.all().update(attempt_time=expired)

    resp = attempt(client, password=PASSWORD)
    assert resp.status_code == 302


@pytest.mark.django_db
def test_lockout_is_scoped_to_the_username_ip_combination(client, user, other_user):
    lock_out(client)  # jason @ 127.0.0.1 (the test client's default IP)

    # Same username, different IP: not locked.
    resp = attempt(client, password=PASSWORD, REMOTE_ADDR="10.20.30.40")
    assert resp.status_code == 302
    client.logout()

    # Different username, same (locked) IP: not locked.
    resp = attempt(client, username="sara", password=PASSWORD)
    assert resp.status_code == 302
    client.logout()

    # The locked combination itself is still locked.
    resp = attempt(client, password=PASSWORD)
    assert resp.status_code == 403


def test_axes_models_are_registered_in_admin():
    from axes.models import AccessAttempt as AttemptModel
    from axes.models import AccessLog

    assert AttemptModel in admin.site._registry
    assert AccessLog in admin.site._registry


def _import_settings(module, extra_env):
    """Import a settings module in a clean interpreter and report the
    axes wiring as plain text, so production/standalone are verified
    exactly as a deployment would load them."""
    backend_dir = Path(__file__).resolve().parents[3]
    code = (
        f"import {module} as s\n"
        "print('axes' in s.INSTALLED_APPS)\n"
        "print(s.MIDDLEWARE[-1])\n"
        "print(s.AUTHENTICATION_BACKENDS[0])\n"
        "print(s.AXES_FAILURE_LIMIT)\n"
        "print(s.AXES_LOCKOUT_PARAMETERS)\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines()


def test_production_settings_wire_axes(tmp_path):
    lines = _import_settings(
        "config.settings.production",
        {"DJANGO_SECRET_KEY": "settings-smoke-test-secret"},
    )
    assert lines == [
        "True",
        "axes.middleware.AxesMiddleware",
        "axes.backends.AxesStandaloneBackend",
        "5",
        "[['username', 'ip_address']]",
    ]


def test_standalone_settings_wire_axes(tmp_path):
    lines = _import_settings(
        "config.settings.standalone",
        {"ACCOUNTIX_DATA_DIR": str(tmp_path)},
    )
    assert lines[0] == "True"
    assert lines[1] == "axes.middleware.AxesMiddleware"
    assert lines[2] == "axes.backends.AxesStandaloneBackend"


def test_failure_limit_is_env_overridable(tmp_path):
    lines = _import_settings(
        "config.settings.production",
        {"DJANGO_SECRET_KEY": "settings-smoke-test-secret", "AXES_FAILURE_LIMIT": "7"},
    )
    assert lines[3] == "7"
