"""Page dumper for the tour DOM check (Sprint 31, ADR-059).

Run explicitly as a pytest module (it lives outside testpaths on
purpose — it is a developer tool, not a suite test):

    TOUR_DUMP_DIR=/tmp/tour-harness/pages \
        pytest scripts/tour_dom_check/dump_pages.py

It renders REAL pages with the crawl world (the populated fixture
from the i18n crawls) in fa and en and writes the HTML next to the
harness, which then executes the real tour.js against it in jsdom.
"""

import os
from pathlib import Path

import pytest
from apps.core.tests.test_i18n_fa_crawl import build_crawl_world
from django.conf import settings
from django.urls import reverse

pytestmark = pytest.mark.django_db

PAGES = {
    "dashboard": lambda w: reverse("dashboard"),
    "sales_invoice_list": lambda w: reverse("sales_invoice_list"),
    "sales_invoice_create": lambda w: reverse("sales_invoice_create"),
}


def _dump(client, world, lang, outdir):
    client.force_login(world.user)
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = lang
    for name, url_of in PAGES.items():
        resp = client.get(url_of(world))
        assert resp.status_code == 200, (lang, name, resp.status_code)
        html = resp.content.decode()
        assert 'id="tour-data"' in html, (lang, name, "payload missing")
        (outdir / f"{name}.{lang}.html").write_text(html, encoding="utf-8")


def _outdir(tmp_path):
    outdir = Path(os.environ.get("TOUR_DUMP_DIR", str(tmp_path / "pages")))
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def test_dump_tour_pages_fa(client, db, tmp_path):
    _dump(client, build_crawl_world("fa"), "fa", _outdir(tmp_path))


def test_dump_tour_pages_en(client, db, tmp_path):
    _dump(client, build_crawl_world("en"), "en", _outdir(tmp_path))
