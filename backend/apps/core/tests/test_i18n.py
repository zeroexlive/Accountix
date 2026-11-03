"""Sprint 19 — i18n groundwork: bilingual fa/en chrome (ADR-045).

Persian is the source language (template msgids ARE the Persian
literals), so a fresh client renders exactly the Persian UI that
Sprints 11–18 shipped, with ``dir="rtl"``. Switching to English via
Django's ``set_language`` view (language cookie, no URL prefixes)
renders the wrapped chrome — base shell, login/lockout, dashboard
labels — in English with ``dir="ltr"``; business-page content that
has not been wrapped yet stays Persian in both modes by design.

The compiled catalogs are build artifacts (``*.mo`` is gitignored),
so this module compiles them from the committed ``.po`` sources in
its own setup: the English assertions must pass on a fresh clone
with nothing but the gettext tools installed.
"""

import datetime
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template import Context, Template
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module", autouse=True)
def compiled_catalogs():
    call_command("compilemessages", verbosity=0)


@pytest.fixture
def user(db):
    return User.objects.create_user(username="boss", password="pw")


def _set_language(client, language):
    return client.post(reverse("set_language"), {"language": language, "next": "/"})


def test_default_client_renders_persian_rtl_chrome(client, user):
    client.force_login(user)
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert '<html lang="fa" dir="rtl">' in content
    # Sidebar chrome in Persian, exactly as before this sprint.
    assert "تراز آزمایشی" in content  # trial balance nav label
    assert "دفترچه‌های چک" in content  # cheque books nav label
    assert "<title>داشبورد | اکانتیکس</title>" in content
    # The switcher offers the other language, labelled by its endonym.
    assert reverse("set_language") in content
    assert ">English</button>" in content


def test_login_page_default_is_persian(client):
    resp = client.get(reverse("login"))
    content = resp.content.decode()
    assert '<html lang="fa" dir="rtl">' in content
    assert "ورود به سیستم" in content
    assert ">English</button>" in content


def test_switch_to_english_renders_english_ltr_and_persists(client, user):
    client.force_login(user)
    _set_language(client, "en")
    resp = client.get(reverse("dashboard"))
    content = resp.content.decode()
    assert '<html lang="en" dir="ltr">' in content
    assert "<title>Dashboard | Accountix</title>" in content
    assert "Trial balance" in content  # nav label translated
    assert "Cheque books" in content
    assert "Log out" in content  # sidebar user card
    assert "تراز آزمایشی" not in content  # no Persian chrome left over
    # The switcher now offers Persian.
    assert ">فارسی</button>" in content

    # The cookie persists across logout, onto the login page…
    # (through the real logout view: the test client's own logout()
    # wipes its whole cookie jar, which a browser does not do).
    assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == "en"
    client.post(reverse("logout"))
    resp = client.get(reverse("login"))
    content = resp.content.decode()
    assert '<html lang="en" dir="ltr">' in content
    assert "Sign in" in content
    assert "ورود به سیستم" not in content

    # …and across a real login back onto the dashboard.
    resp = client.post(reverse("login"), {"username": "boss", "password": "pw"})
    assert resp.status_code == 302
    content = client.get(reverse("dashboard")).content.decode()
    assert '<html lang="en" dir="ltr">' in content
    assert "Trial balance" in content


def test_switch_back_to_fa_restores_persian_rtl(client, user):
    client.force_login(user)
    _set_language(client, "en")
    assert '<html lang="en" dir="ltr">' in client.get(reverse("dashboard")).content.decode()
    _set_language(client, "fa")
    content = client.get(reverse("dashboard")).content.decode()
    assert '<html lang="fa" dir="rtl">' in content
    assert "تراز آزمایشی" in content


def test_jalali_filter_language_branches():
    template = Template("{% load jalali %}{{ value|jalali }}")
    day = datetime.date(2026, 3, 20)  # 1404/12/29 in Jalali
    with translation.override("fa"):
        assert template.render(Context({"value": day})) == "1404/12/29"
    with translation.override("en"):
        # English mode: the stored Gregorian date, neutral ISO form.
        assert template.render(Context({"value": day})) == "2026-03-20"
    with translation.override("fa"):
        assert template.render(Context({"value": None})) == ""


def test_untranslated_msgid_falls_back_to_persian_source():
    # The fa-source convention (ADR-045): a wrapped string with no
    # entry in en.po renders as its Persian msgid, never blank.
    probe = "رشته‌ای که عمداً در کاتالوگ انگلیسی نیست"
    with translation.override("en"):
        assert gettext(probe) == probe


def _import_settings(module, extra_env):
    """Import a settings module in a clean interpreter and report the
    i18n wiring as plain text (same pattern as the Sprint 16 axes
    settings smoke tests)."""
    backend_dir = Path(__file__).resolve().parents[3]
    code = (
        f"import {module} as s\n"
        "print(s.USE_I18N)\n"
        "print(s.LANGUAGE_CODE)\n"
        "print([code for code, _name in s.LANGUAGES])\n"
        "mw = s.MIDDLEWARE\n"
        "loc = mw.index('django.middleware.locale.LocaleMiddleware')\n"
        "ses = mw.index('django.contrib.sessions.middleware.SessionMiddleware')\n"
        "com = mw.index('django.middleware.common.CommonMiddleware')\n"
        "print(ses < loc < com)\n"
        "print([str(p) for p in s.LOCALE_PATHS])\n"
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


def test_production_settings_wire_i18n():
    lines = _import_settings(
        "config.settings.production",
        {"DJANGO_SECRET_KEY": "settings-smoke-test-secret"},
    )
    assert lines[0] == "True"
    assert lines[1] == "fa"
    assert lines[2] == "['fa', 'en']"
    assert lines[3] == "True"  # Session < Locale < Common
    assert lines[4].endswith("locale']")


def test_standalone_settings_wire_i18n(tmp_path):
    lines = _import_settings(
        "config.settings.standalone",
        {"ACCOUNTIX_DATA_DIR": str(tmp_path)},
    )
    assert lines[0] == "True"
    assert lines[1] == "fa"
    assert lines[2] == "['fa', 'en']"
    assert lines[3] == "True"
