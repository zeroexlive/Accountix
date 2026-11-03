"""Shared pytest fixtures for the whole suite.

Since Sprint 21 (ADR-047) the *default* language depends on a
compiled catalog: fa.po carries real Persian translations for the
English-source service messages and choice labels, and without a
compiled ``fa.mo`` those strings silently fall back to the English
msgids — roughly half the suite asserts on the rendered text.
Compiled catalogs are build artifacts (``*.mo`` is gitignored), so
this session fixture compiles them once per test run from the
committed ``.po`` sources, keeping the suite green on a fresh
clone with no manual step. It needs the GNU gettext tools
(``msgfmt``) on the machine — the documented dev prerequisite
(DEVELOPMENT.md). The Sprint 19/20 i18n modules keep their own
module-scoped fixtures; compiling twice is harmless.
"""

import pytest
from django.core.management import call_command
from django.utils.translation import trans_real


@pytest.fixture(scope="session", autouse=True)
def compiled_message_catalogs():
    call_command("compilemessages", verbosity=0)
    # Django caches one translation object per language for the
    # whole process. On a fresh clone (no .mo at startup) anything
    # that resolves the default language before this fixture runs —
    # app loading, collection — caches a catalog *without* the
    # project strings, and the freshly compiled catalog would never
    # be seen: English-source strings would keep rendering in
    # English and the Persian assertions would pass spuriously.
    # Drop the caches so the next lookup re-reads the compiled
    # catalogs from disk.
    trans_real._translations.clear()
    trans_real._default = None
