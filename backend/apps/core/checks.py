"""System check: compiled translation catalogs (Sprint 31, ADR-058).

The bidirectional i18n footgun: catalogs ship as .po sources and
Django reads only the compiled .mo. A clone whose .mo files are
missing or older than their .po silently renders SOURCE strings —
Persian-source strings appear in en mode, English-source strings
in fa mode — which reads exactly like "the translations are
broken" in BOTH directions at once. The launcher and the test
suite compile automatically; a plain ``runserver`` does not.

This check (Warning, never an error) fires under ``manage.py
check`` / ``runserver`` when any catalog under LOCALE_PATHS is
missing or stale, and stays silent when everything is compiled
and fresh — which includes the frozen bundle (it ships .mo) and
the test suite (conftest compiles in the crawl fixtures).
"""

from pathlib import Path

from django.conf import settings
from django.core.checks import Warning as CheckWarning
from django.core.checks import register


@register("i18n")
def catalogs_compiled(app_configs, **kwargs):
    issues = []
    for base in settings.LOCALE_PATHS:
        for po in sorted(Path(base).rglob("django.po")):
            mo = po.with_suffix(".mo")
            if not mo.exists() or mo.stat().st_mtime < po.stat().st_mtime:
                issues.append(
                    CheckWarning(
                        f"Translation catalog is missing or stale: {po} "
                        f"(compiled file: {mo}). Untranslated source strings "
                        "will leak into both languages. Run "
                        "`python manage.py compilemessages` or start the "
                        "dev server via scripts/dev_run.sh.",
                        id="accountix.W001",
                    )
                )
    return issues
