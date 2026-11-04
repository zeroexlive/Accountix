"""Sprint 31 (ADR-058) — the en-mode mirror of the fa leak crawl.

Jason's second direction: Persian sentences inside English
pages. Sprint 30 audited fa only; this module crawls the SAME
populated world — built under en, with English user data, so data
never pollutes the audit — as an OWNER in en mode over the same
64 GET pages + 10 POST flows, and fails on any Arabic-script run
in visible text or user-facing attributes.

Pre-sprint census (proper PO parse, multiline-aware): en.po has
ZERO empty msgstr and fa.po zero real gaps — the "~96 empty en
entries" figure from a naive single-line count was an artifact of
multiline msgstrs. What this crawl therefore hunts is class E2/E3:
Persian literals that never entered the catalogs at all, strings
rendered outside gettext, and JSON payloads (tour data included).

The whole exception surface is EN_ALLOWLIST below, each entry
justified. Stored descriptions keep their creation language
(ADR-055 class 5) — the world here is created under en, so its
stored descriptions are English by construction.
"""

import json
import re

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse

from apps.core.tests.test_i18n_fa_crawl import TextHarvest, build_crawl_world, page_urls
from apps.treasury.tests._helpers import DAY

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module", autouse=True)
def compiled_catalogs():
    call_command("compilemessages", verbosity=0)


@pytest.fixture
def world(db):
    return build_crawl_world("en")


ARABIC_RUN = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]+")
ARABIC_LETTER = re.compile(r"[\u0621-\u064A\u066E-\u06D3\u06FA-\u06FC\u06FF]")

# The entire exception surface for the en crawl.
EN_ALLOWLIST = (
    # The language switcher names the other language with its own
    # endonym — «فارسی» on an English page is deliberate, standard
    # practice (mirrors "English" in the fa crawl's allowlist).
    "فارسی",
)


def arabic_hits(html):
    parser = TextHarvest()
    parser.feed(html)
    hits = set()
    for chunk in parser.chunks:
        text = " ".join(chunk.split())
        for m in ARABIC_RUN.finditer(text):
            run = m.group(0)
            if len(ARABIC_LETTER.findall(run)) < 2:
                continue  # stray single letter/digit fragments are noise
            if any(allowed in run or allowed in text for allowed in EN_ALLOWLIST):
                # Only the allowlisted token itself is exempt; a run
                # that merely CONTAINS it alongside other Persian is
                # still a leak unless the run is exactly the token.
                if run.strip() in EN_ALLOWLIST:
                    continue
            hits.add(run)
    return hits


def _client_en(client, user):
    client.force_login(user)
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    return client


def test_en_crawl_get_pages_are_persian_free(client, world):
    _client_en(client, world.user)
    failures = {}
    for name, url in page_urls(world):
        resp = client.get(url)
        if resp.status_code != 200:
            failures[name] = {f"<HTTP {resp.status_code}>"}
            continue
        hits = arabic_hits(resp.content.decode())
        if hits:
            failures[name] = hits
    assert failures == {}


def test_en_crawl_post_error_pages_are_persian_free(client, world):
    from django.core.files.uploadedfile import SimpleUploadedFile

    w = world
    failures = {}

    def check(name, resp):
        hits = arabic_hits(resp.content.decode())
        if hits:
            failures[name] = hits

    client.logout()
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    resp = client.post(
        reverse("login"), {"username": "boss", "password": "wrong-pass"}, follow=True
    )
    check("login_bad", resp)

    _client_en(client, w.user)
    resp = client.post(
        reverse("password_change"),
        {"old_password": "not-the-password", "new_password1": "123", "new_password2": "456"},
        follow=True,
    )
    check("password_change_err", resp)
    resp = client.post(
        reverse("password_change"),
        {
            "old_password": "Str0ng!Pass1",
            "new_password1": "password",
            "new_password2": "password",
        },
        follow=True,
    )
    check("password_change_weak", resp)
    resp = client.post(
        reverse("profile"),
        {"first_name": "Boss", "last_name": "Sample", "email": "not-an-email"},
        follow=True,
    )
    check("profile_err", resp)
    resp = client.post(
        reverse("company_member_add_new", args=[w.company.pk]),
        {
            "username": "newbie",
            "first_name": "",
            "last_name": "",
            "password1": "123",
            "password2": "1234",
            "role": "VIEWER",
        },
        follow=True,
    )
    check("member_add_new_err", resp)
    resp = client.post(
        reverse("journal_create"),
        {
            "company": str(w.company.pk),
            "entry_date": DAY.isoformat(),
            "description": "Unbalanced entry",
            "idempotency_key": "",
            "lines-TOTAL_FORMS": "2",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-account": str(w.cash.pk),
            "lines-0-debit": "100",
            "lines-0-credit": "0",
            "lines-0-party": "",
            "lines-0-description": "",
            "lines-1-account": str(w.revenue.pk),
            "lines-1-debit": "0",
            "lines-1-credit": "50",
            "lines-1-party": "",
            "lines-1-description": "",
        },
        follow=True,
    )
    check("journal_create_err", resp)
    resp = client.post(reverse("purchase_invoice_create"), {}, follow=True)
    check("purchase_create_empty", resp)
    resp = client.post(
        reverse("bank_statement_import", args=[w.statement.pk]),
        {"file": SimpleUploadedFile("s.csv", b"garbage,content\n1,2\n", content_type="text/csv")},
        follow=True,
    )
    check("statement_import_garbage", resp)
    resp = client.post(reverse("account_create"), {}, follow=True)
    check("account_create_empty", resp)
    resp = client.post(reverse("company_create"), {}, follow=True)
    check("company_create_empty", resp)

    assert failures == {}


def test_en_anonymous_login_page_is_persian_free(client, world):
    # The pre-auth surface is part of the product language too.
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    resp = client.get(reverse("login"))
    assert resp.status_code == 200
    assert arabic_hits(resp.content.decode()) == set()


PAYLOAD_RE = re.compile(r'<script id="tour-data"[^>]*>(.*?)</script>', re.DOTALL)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def test_en_tour_payloads_are_persian_free(client, world):
    _client_en(client, world.user)
    c = world.company
    pages = {
        "dashboard": reverse("dashboard"),
        "sales_invoice_list": reverse("sales_invoice_list"),
        "profile": reverse("profile"),
        "company_members": reverse("company_members", args=[c.pk]),
    }
    failures = {}
    for name, url in pages.items():
        resp = client.get(url)
        assert resp.status_code == 200, name
        match = PAYLOAD_RE.search(resp.content.decode())
        assert match, f"tour payload missing on {name}"
        payload = json.loads(match.group(1))
        bad = {s for s in _strings(payload) if ARABIC_LETTER.search(s)}
        if bad:
            failures[name] = bad
    assert failures == {}
