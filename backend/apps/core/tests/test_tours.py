# ruff: noqa: F811  (the imported `world` fixture IS the test parameter)
"""Sprint 30 — guided tours (ADR-057).

Everything server-side is pinned here: the per-page JSON payload
(present, valid, bilingual), the anchor contract (every step's
anchor exists in the OWNER rendering of its page), the VIEWER
contract (the anchors missing from a role-restricted rendering are
exactly the ones the engine will skip), the shell button's
hidden-until-JS contract, and the self-hosted engine file. The
interactive stepping itself needs a browser and is NOT covered —
see the sprint report's limitations.
"""

import json
import re

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.urls import reverse

from apps.core.tests.test_i18n_fa_crawl import world  # noqa: F401  (fixture)
from apps.core.tours import TOURS
from apps.organizations.models import CompanyMembership

User = get_user_model()
pytestmark = pytest.mark.django_db

ANCHOR_RE = re.compile(r'data-tour="([^"]+)"')
PAYLOAD_RE = re.compile(r'<script id="tour-data"[^>]*>(.*?)</script>', re.DOTALL)


def _pages(w):
    c = w.company
    return {
        "dashboard": reverse("dashboard"),
        "sales_invoice_list": reverse("sales_invoice_list"),
        "sales_invoice_create": reverse("sales_invoice_create"),
        "purchase_invoice_list": reverse("purchase_invoice_list"),
        "payment_list": reverse("payment_list"),
        "cheque_list": reverse("cheque_list"),
        "bank_statement_detail": reverse("bank_statement_detail", args=[w.statement.pk]),
        "product_list": reverse("product_list"),
        "stock_documents": reverse("stock_documents"),
        "income_statement": reverse("income_statement") + f"?company={c.pk}",
        "fiscal_year_detail": reverse("fiscal_year_detail", args=[w.fiscal_year.pk]),
        "company_members": reverse("company_members", args=[c.pk]),
        "profile": reverse("profile"),
    }


def _payload(html):
    match = PAYLOAD_RE.search(html)
    assert match, "tour-data script missing"
    return json.loads(match.group(1))


def test_registry_covers_exactly_the_tested_pages(world):
    assert set(TOURS) == set(_pages(world))


def test_every_covered_page_serves_valid_tour_with_live_anchors(client, world):
    client.force_login(world.user)
    for name, url in _pages(world).items():
        resp = client.get(url)
        assert resp.status_code == 200, name
        html = resp.content.decode()
        payload = _payload(html)
        steps = payload["steps"]
        assert 4 <= len(steps) <= 8, (name, len(steps))
        for key in ("next", "prev", "finish", "close", "counter"):
            assert payload["ui"][key], (name, key)
        present = set(ANCHOR_RE.findall(html))
        for step in steps:
            assert step["title"] and step["body"], (name, step)
            assert step["anchor"] in present, (name, step["anchor"])


def test_uncovered_page_has_button_but_no_payload(client, world):
    client.force_login(world.user)
    resp = client.get(reverse("journal_list"))
    html = resp.content.decode()
    assert 'id="tour-data"' not in html
    # The start button still ships (hidden) and the engine script is
    # loaded — the engine simply never reveals the button here.
    assert "data-tour-start" in html and "hidden" in html
    assert "js/tour.js" in html


def test_shell_button_ships_hidden_with_persian_label(client, world):
    client.force_login(world.user)
    resp = client.get(reverse("dashboard"))
    html = resp.content.decode()
    assert re.search(r"<button[^>]*data-tour-start[^>]*hidden", html)
    assert "راهنمای صفحه" in html


def test_viewer_dashboard_skips_exactly_the_operate_anchors(client, world):
    viewer = User.objects.create_user(username="viewer", password="x")
    CompanyMembership.objects.create(user=viewer, company=world.company, role="VIEWER")
    client.force_login(viewer)
    resp = client.get(reverse("dashboard"))
    html = resp.content.decode()
    payload = _payload(html)  # the tour itself is available to VIEWER
    step_anchors = {step["anchor"] for step in payload["steps"]}
    present = set(ANCHOR_RE.findall(html))
    # Quick actions are OPERATE-only (Sprint 28 honesty rule): that
    # anchor, and ONLY that anchor, is missing for the engine to skip.
    assert step_anchors - present == {"quick-actions"}
    assert present - step_anchors == set()


def test_tour_engine_is_self_hosted_and_wired():
    path = finders.find("js/tour.js")
    assert path, "tour.js must resolve through the static finders"
    js = open(path, encoding="utf-8").read()
    assert "data-tour-start" in js
    assert "Escape" in js and "ArrowLeft" in js and "ArrowRight" in js
    assert "prefers-reduced-motion" in js  # smooth scroll is opt-in


def test_dashboard_tour_is_english_in_en_mode(client, world):
    from django.utils import translation

    client.force_login(world.user)
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
    try:
        resp = client.get(reverse("dashboard"))
    finally:
        # An en-mode request leaves 'en' active in the test thread;
        # don't leak it into other tests' fixture-time service calls.
        translation.deactivate()
    html = resp.content.decode()
    payload = _payload(html)
    assert payload["ui"]["next"] == "Next"
    assert payload["ui"]["finish"] == "End tour"
    titles = {step["title"] for step in payload["steps"]}
    assert "Select company" in titles  # the picker's pre-existing catalog string
    assert "Revenue and expenses chart" in titles  # a Sprint 30 tour string
    assert "انتخاب شرکت" not in titles


def test_hidden_attribute_wins_the_css_cascade():
    """Sprint 31 (ADR-059) — the tour activation root cause: the
    shell ships the start button `hidden`, but the design system's
    global `button,.btn{display:inline-block}` author rule beats
    the UA stylesheet's `[hidden]{display:none}` on origin alone,
    so the button rendered visible-but-dead on every page. The
    global `[hidden]` !important rule restores the contract; the
    DOM-level proof (real cascade + click-through in jsdom) lives
    in scripts/tour_dom_check/."""
    from pathlib import Path

    css = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "[hidden]{display:none !important}" in css


def test_tour_css_classes_exist():
    from pathlib import Path

    css = (Path(settings.BASE_DIR) / "static" / "css" / "app.css").read_text(encoding="utf-8")
    for cls in (".tour-root", ".tour-spot", ".tour-card", ".tour-nav", ".tour-start"):
        assert cls in css, cls
    # The spotlight glide is gated like every other movement.
    motion = css[css.index("@media (prefers-reduced-motion: no-preference)") :]
    assert ".tour-spot{transition:" in motion
