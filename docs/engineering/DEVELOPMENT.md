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
cd backend && ../.venv/bin/python manage.py migrate && ../.venv/bin/python manage.py compilemessages && ../.venv/bin/python manage.py runserver
```

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
