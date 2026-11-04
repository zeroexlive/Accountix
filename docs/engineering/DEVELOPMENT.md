# Development Guide

## Environment
- Python: 3.12 verified on the dev machine; 3.13 targeted (CI must verify).
  Django 5.2 LTS supports both.
- This machine has no `uv`: use venv + pip. When uv is available, generate
  `uv.lock` from `pyproject.toml` and prefer `uv sync`.
- GNU gettext tools (`msgfmt`, `xgettext`) are a dev-machine prerequisite
  since Sprint 19 (ADR-045): Django's `makemessages`/`compilemessages`
  shell out to them. Debian/Ubuntu: `apt-get install -y gettext`
  (a plain `apt-get update` first; on very slow mirrors a scoped update —
  `main` component only, `Acquire::Languages=none` — is enough). Only the
  `.po` catalogs are committed; after checkout, compile them once (below)
  or translations silently fall back to the source strings — English
  mode falls back to the Persian source strings, and (since Sprint 21,
  ADR-047) Persian mode falls back to the English source strings for
  service messages and choice labels, whose Persian lives only in
  `fa.po`. The standalone launcher compiles best-effort at startup and
  the bundle builds compile as a hard step, so end users need nothing.
  The test suite compiles the catalogs itself (root `conftest.py`).

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
scripts/dev_run.sh            # THE way to run a clone (Sprint 31, ADR-058)
# scripts/dev_run.sh 0.0.0.0:8765   # extra args pass through to runserver
```

`scripts/dev_run.sh` is the documented startup for a source clone.
It exists because the compile step is invisible when skipped: a
plain `runserver` on an uncompiled clone renders source strings in
BOTH languages at once (Persian inside English pages and English
inside Persian pages — Sprint 31 reproduced both directions from a
fresh copy). The script, in order:

1. verifies `msgfmt` exists — hard fail with the install hint
   (bilingual message) if not;
2. `manage.py compilemessages` — catalogs fresh;
3. `manage.py migrate` — schema current;
4. `exec manage.py runserver "$@"`.

The manual equivalent is exactly those commands:

```bash
cd backend && ../.venv/bin/python manage.py compilemessages && ../.venv/bin/python manage.py migrate && ../.venv/bin/python manage.py runserver
```

As a second line of defense, `manage.py check` (and therefore
`runserver`) warns with id `accountix.W001` whenever a catalog's
`.mo` is missing or older than its `.po`, naming the fix. The
warning is silent when catalogs are compiled and fresh — including
inside the frozen bundle, which ships `.mo` files.

## Vendored font binaries (Sprint 28, ADR-053)

The eight woff2 files under `backend/static/fonts/` (Inter +
Vazirmatn, 400/500/700/800) are binary artifacts: they are tracked
in the local repository but cannot travel through the connector's
UTF-8 `push-files` sync route, so the GitHub copy of the tree does
not contain them. A clone missing them still runs — `@font-face`
simply falls back to the system stack — but to restore the DS v3
typography, re-vendor them from the official releases and verify
each file against the sha256 table in
`backend/static/THIRD_PARTY_NOTICES.md`:

```bash
# Vazirmatn v33.003 (fonts/webfonts/) and Inter v4.1 (web/)
cp Vazirmatn-Regular.woff2   backend/static/fonts/vazirmatn-400.woff2
cp Vazirmatn-Medium.woff2    backend/static/fonts/vazirmatn-500.woff2
cp Vazirmatn-Bold.woff2      backend/static/fonts/vazirmatn-700.woff2
cp Vazirmatn-ExtraBold.woff2 backend/static/fonts/vazirmatn-800.woff2
cp Inter-Regular.woff2       backend/static/fonts/inter-400.woff2
cp Inter-Medium.woff2        backend/static/fonts/inter-500.woff2
cp Inter-Bold.woff2          backend/static/fonts/inter-700.woff2
cp Inter-ExtraBold.woff2     backend/static/fonts/inter-800.woff2
```

The PyInstaller bundle built from a tree that has the fonts ships
them normally (the spec bundles `backend/static` wholesale).

## Settings
`config.settings.local` (default via manage.py), `.test` (in-memory SQLite,
fast hashers — pytest uses it automatically), `.production` (requires
`DJANGO_SECRET_KEY`, secure cookies/HSTS). PostgreSQL: set
`DATABASE_URL=postgres://user:pass@host:5432/dbname`.

## Conventions
- Business rules spanning records go in `apps/<app>/services.py`, never in
  views/templates/signals. Views filter every queryset by the user's
  company memberships (`apps.core.access.user_company_ids`).
- Money: Decimal only. Codes/identifiers/commits in English; UI in Persian
  first (fa/RTL) with Django i18n for English.
- Run before committing: `pytest`, `ruff check backend tests`,
  `ruff format backend tests`, `manage.py makemigrations --check --dry-run`.

## Git workflow
Feature branch per phase → tests green → PR → merge only on verified CI.
Sprint 01 was committed directly on `main` locally as the initial commit of
an empty repository; that exception does not set a precedent.
