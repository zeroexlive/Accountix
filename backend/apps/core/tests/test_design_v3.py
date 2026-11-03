"""Sprint 28 — Design System v3 "Bento" asset + shell pins (ADR-053).

DS v3's load-bearing claims are verifiable without a browser, and
this module pins exactly those claims:

- the eight vendored woff2 files (Inter + Vazirmatn, 400/500/700/800)
  are findable through staticfiles, carry the wOF2 magic, and are
  the files the stylesheet's @font-face rules actually point at;
- every ``<use>`` reference in every template names a symbol that
  exists in the self-hosted Lucide sprite, every sprite symbol is
  used at least once, and the sprite has no duplicate ids;
- ZERO external assets: no template and not app.css references any
  http(s) or protocol-relative asset, and every CSS ``url()`` is a
  relative path to a vendored font;
- the bento dashboard renders for a member (sprite icons + quick
  actions for an OPERATE role), and a VIEWER gets the same tiles
  without the quick-actions tile (Sprint 25 pattern).
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.finders import find
from django.urls import reverse

from apps.organizations.models import Company, CompanyMembership

User = get_user_model()
pytestmark = pytest.mark.django_db

FONT_FILES = [
    "fonts/inter-400.woff2",
    "fonts/inter-500.woff2",
    "fonts/inter-700.woff2",
    "fonts/inter-800.woff2",
    "fonts/vazirmatn-400.woff2",
    "fonts/vazirmatn-500.woff2",
    "fonts/vazirmatn-700.woff2",
    "fonts/vazirmatn-800.woff2",
]

TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"


def _read_static(rel):
    path = find(rel)
    assert path, f"{rel} must be findable via staticfiles"
    return Path(path).read_bytes()


def _css_text():
    return _read_static("css/app.css").decode("utf-8")


def _template_texts():
    return {
        p.relative_to(TEMPLATES_DIR).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(TEMPLATES_DIR.rglob("*.html"))
    }


# ---------------------------------------------------------------------------
# Fonts — vendored, valid woff2, and the ones the CSS declares
# ---------------------------------------------------------------------------


def test_font_files_are_vendored_woff2():
    for rel in FONT_FILES:
        data = _read_static(rel)
        assert data[:4] == b"wOF2", rel
        assert len(data) > 10_000, rel


def test_font_face_rules_point_at_vendored_files():
    css = _css_text()
    faces = re.findall(r"@font-face\{([^}]+)\}", css)
    assert len(faces) == 8
    for face in faces:
        assert "font-display:swap" in face
    urls = sorted(re.findall(r'url\("(\.\./fonts/[^"]+)"\)', css))
    assert urls == sorted(f"../{rel}" for rel in FONT_FILES)
    families = {re.search(r'font-family:"(\w+)"', f).group(1) for f in faces}
    assert families == {"Inter", "Vazirmatn"}
    weights = sorted(re.findall(r"font-weight:(\d+)", css)[:8])
    assert weights == ["400", "400", "500", "500", "700", "700", "800", "800"]


def test_combined_font_stack_is_the_body_font():
    css = _css_text()
    assert '--font:"Inter","Vazirmatn",Tahoma' in css
    assert "font-family:var(--font)" in css


# ---------------------------------------------------------------------------
# Icon sprite — every reference resolves, every symbol is used
# ---------------------------------------------------------------------------


def _sprite_ids():
    svg = _read_static("icons.svg").decode("utf-8")
    return re.findall(r'<symbol id="(i-[a-z0-9-]+)"', svg)


def test_every_template_icon_reference_exists_in_sprite():
    ids = _sprite_ids()
    assert len(ids) == len(set(ids)), "sprite symbol ids must be unique"
    known = set(ids)
    for name, text in _template_texts().items():
        for ref in re.findall(r"#(i-[a-z0-9-]+)", text):
            assert ref in known, f"{name} references missing sprite symbol {ref}"


def test_every_sprite_symbol_is_used():
    used = set()
    for text in _template_texts().values():
        used.update(re.findall(r"#(i-[a-z0-9-]+)", text))
    assert set(_sprite_ids()) == used


def test_no_inline_svg_left_in_templates():
    for name, text in _template_texts().items():
        assert "<svg viewBox" not in text, f"{name} still hand-draws an icon"


# ---------------------------------------------------------------------------
# Zero external assets — templates + stylesheet
# ---------------------------------------------------------------------------

FORBIDDEN = [
    "http://",
    "https://",
    "//cdn",
    "url(http",
    "url(//",
    'src="//',
    "src='//",
    'href="//',
    "href='//",
]


def test_zero_external_asset_references():
    for name, text in _template_texts().items():
        for needle in FORBIDDEN:
            assert needle not in text, f"{name} references an external asset: {needle}"
    css = _css_text()
    for needle in FORBIDDEN:
        assert needle not in css, f"app.css references an external asset: {needle}"
    # Every CSS url() is one of the vendored relative font paths.
    for url in re.findall(r'url\("([^"]+)"\)', css):
        assert url.startswith("../fonts/"), url


# ---------------------------------------------------------------------------
# Bento dashboard — renders with icons; quick actions follow OPERATE
# ---------------------------------------------------------------------------


def _member_client(client, role):
    user = User.objects.create_user(username=f"u-{role}", password="pw-12345678")
    company = Company.objects.create(name=f"Co-{role}")
    CompanyMembership.objects.create(user=user, company=company, role=role)
    client.force_login(user)
    return client


def test_dashboard_bento_renders_with_sprite_icons(client):
    client = _member_client(client, "OWNER")
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert 'class="bento-kpis"' in content
    assert 'class="bento-main"' in content
    assert 'class="bento-minis"' in content
    assert "icons.svg#i-trending-up" in content
    assert "icons.svg#i-gauge" in content
    # Quick actions tile: all five create routes are linked.
    for name in (
        "sales_invoice_create",
        "purchase_invoice_create",
        "journal_create",
        "payment_create",
        "product_create",
    ):
        assert f'href="{reverse(name)}"' in content, name


def test_dashboard_viewer_gets_tiles_without_quick_actions(client):
    client = _member_client(client, "VIEWER")
    resp = client.get(reverse("dashboard"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert 'class="bento-kpis"' in content  # read tiles render for every role
    assert "icons.svg#i-trending-up" in content
    assert f'href="{reverse("sales_invoice_create")}"' not in content
    assert f'href="{reverse("journal_create")}"' not in content
