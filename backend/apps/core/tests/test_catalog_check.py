"""Sprint 31 (ADR-058) — the accountix.W001 catalog-freshness check.

The check must fire exactly when a clone would mislead its owner:
.mo missing, or .po newer than .mo. And it must stay silent in the
two states that are already correct — the working tree right after
compilemessages (the test suite's normal state) and, by the same
freshness logic, the frozen bundle which ships compiled catalogs.
"""

import os
import shutil

from django.test import override_settings

from apps.core.checks import catalogs_compiled


def _catalog_tree(tmp_path, *, mo_age_offset):
    """A minimal locale tree: one .po, and a .mo whose mtime is
    `mo_age_offset` seconds relative to the .po (None = no .mo)."""
    lc = tmp_path / "fa" / "LC_MESSAGES"
    lc.mkdir(parents=True)
    po = lc / "django.po"
    po.write_text('msgid "x"\nmsgstr ""\n', encoding="utf-8")
    if mo_age_offset is not None:
        mo = lc / "django.mo"
        mo.write_bytes(b"\xde\x12\x04\x95")
        t = po.stat().st_mtime + mo_age_offset
        os.utime(mo, (t, t))
    return tmp_path


def test_missing_mo_fires_w001(tmp_path):
    root = _catalog_tree(tmp_path, mo_age_offset=None)
    with override_settings(LOCALE_PATHS=[root]):
        issues = catalogs_compiled(None)
    assert [i.id for i in issues] == ["accountix.W001"]


def test_stale_mo_fires_w001(tmp_path):
    root = _catalog_tree(tmp_path, mo_age_offset=-60)
    with override_settings(LOCALE_PATHS=[root]):
        issues = catalogs_compiled(None)
    assert [i.id for i in issues] == ["accountix.W001"]


def test_fresh_mo_is_silent(tmp_path):
    root = _catalog_tree(tmp_path, mo_age_offset=+60)
    with override_settings(LOCALE_PATHS=[root]):
        assert catalogs_compiled(None) == []


def test_real_tree_is_silent_after_compile():
    # The crawl fixtures compile the real catalogs; in the suite's
    # normal state the repo tree itself must not trip the warning.
    assert catalogs_compiled(None) == []


def test_shutil_copy_of_repo_catalogs_is_silent(tmp_path):
    # Mirrors the bundle layout: .po + compiled .mo side by side,
    # copied together (mtimes preserved) — no warning.
    from django.conf import settings

    src = settings.BASE_DIR / "locale"
    dst = tmp_path / "locale"
    shutil.copytree(src, dst, copy_function=shutil.copy2)
    with override_settings(LOCALE_PATHS=[dst]):
        assert catalogs_compiled(None) == []
