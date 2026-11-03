"""Sprint 22 — LTR design pass for English mode (ADR-048).

Sprint 19 made ``dir="ltr"`` *unbroken* (the stylesheet was already
logical-property based; two physical holdouts were converted). This
module pins the Sprint 22 design layer on top of it:

- the served stylesheet carries the direction rules: since Sprint 28
  (ADR-053) both locales share ONE self-hosted webfont stack
  (``"Inter", "Vazirmatn", …`` — per-character fallback replaced the
  Sprint 22 ``html[lang="en"]`` system stack, which is why those pins
  moved to ``test_design_v3.py``), tabular numerals for display
  figures in both scripts, and the ``[dir="ltr"] .flip-rtl``
  directional-icon mirroring rule (ADR-048's icon policy);
- the numeric-column rule — figure columns carry the ``num`` hook and
  align to the inline-start in BOTH directions (``td.num`` is
  ``text-align: start``: the right edge in Persian, the left edge in
  English — Jason's post-Sprint-22 decision, see the ADR-048
  addendum, superseding the sprint's original inline-end rule) — is
  exercised on a real page in English and in Persian, so the hook is
  proven present under ``dir="ltr"`` and under ``dir="rtl"`` alike.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.finders import find
from django.core.management import call_command
from django.urls import reverse

from apps.accounting import services as accounting_services
from apps.organizations.models import CompanyMembership
from apps.treasury.tests._helpers import DAY, D, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module", autouse=True)
def compiled_catalogs():
    call_command("compilemessages", verbosity=0)


@pytest.fixture(autouse=True)
def reset_active_language():
    yield
    from django.utils import translation

    translation.deactivate_all()


@pytest.fixture
def world(db):
    w = build_world()
    w.user = User.objects.create_user(username="boss", password="<redacted>")
    CompanyMembership.objects.create(user=w.user, company=w.company, role="OWNER")
    w.entry = accounting_services.create_journal_draft(
        company=w.company,
        entry_date=DAY,
        description="LTR entry",
        lines=[
            {"account": w.cash, "debit": D("100"), "credit": D("0")},
            {"account": w.revenue, "debit": D("0"), "credit": D("100")},
        ],
    )
    return w


def _css_text():
    path = find("css/app.css")
    assert path, "app.css must be findable via staticfiles"
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_stylesheet_ships_ltr_design_rules():
    css = _css_text()
    # Sprint 28 (ADR-053): one combined self-hosted stack for both
    # locales — Latin falls to Inter, Persian to Vazirmatn per glyph.
    # The Sprint 22 html[lang="en"] system stack is superseded; the
    # webfont pins themselves live in test_design_v3.py.
    assert '"Inter","Vazirmatn"' in css
    assert 'html[lang="en"] body' not in css
    # Tabular numerals for display figures (both scripts now).
    assert ".kpi-value,.lg-value,.perf-pct" in css
    assert "font-variant-numeric:tabular-nums" in css
    # Directional-icon mirroring rule (ADR-048 policy mechanism).
    assert '[dir="ltr"] .flip-rtl' in css
    assert "transform:scaleX(-1)" in css
    # The numeric-column rule itself: inline-start alignment.
    assert "td.num,th.num{text-align:start" in css


def test_numeric_columns_carry_num_hook_in_english(client, world):
    client.force_login(world.user)
    client.post(reverse("set_language"), {"language": "en", "next": "/"})
    resp = client.get(reverse("journal_list"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert '<html lang="en" dir="ltr">' in content
    # Debit/credit headers and figure cells carry the numeric hook.
    assert '<th class="num">Debit</th>' in content
    assert '<th class="num">Credit</th>' in content
    assert '<td class="num">100.00</td>' in content


def test_numeric_columns_carry_num_hook_in_persian(client, world):
    client.force_login(world.user)
    resp = client.get(reverse("journal_list"))
    assert resp.status_code == 200
    content = resp.content.decode()
    assert '<html lang="fa" dir="rtl">' in content
    # Same hook under RTL: td.num aligns the figures to the inline-start
    # (the right in RTL) — one rule, both directions (ADR-048 addendum).
    assert '<th class="num">بدهکار</th>' in content
    assert '<td class="num">100.00</td>' in content
