# Accountix

Accounting and inventory management software for small and medium-sized
commercial businesses. Initial target market: Iran. Architecture is prepared
for international markets without a rewrite.

> **Status (2026-11-03): Sprints 01-14 done; release verdict "Ready
> with documented limitations" (`docs/engineering/RELEASE_READINESS.md`).**
> Authentication, companies/memberships, fiscal years/periods, chart of
> accounts, the double-entry journal engine (posting/reversal, trial
> balance, general ledger), the inventory engine (ledger-based stock
> movements, MWAC), purchasing, sales, treasury (allocations, Iranian
> cheque workflows), bank reconciliation, financial statements, fiscal
> closing, opening balances, a reporting dashboard with CSV/XLSX
> exports and print templates, a standalone launcher with
> backup/restore, and a PostgreSQL-verified, type-checked codebase
> (354 tests on SQLite).
> Sprint 11 rebuilt the web UI on design system v2 (ADR-038): a
> Persian RTL sidebar shell, KPI delta badges, a CSS-only revenue vs
> expenses chart and a performance panel — all figures derived from
> the same reporting services. Sprint 12 (ADR-039) closed the old
> headline limitation: the web UI now does full data entry — parties,
> catalog, purchase/sales invoices and returns, treasury, cheque
> actions and manual journals — always through the service layer,
> never around it. Sprint 13 completed data entry (opening balances,
> stock counts, fiscal closing/reopening from the fiscal-year pages)
> and made every displayed date Jalali (ADR-040; storage and inputs
> stay Gregorian). Sprint 14 added bank reconciliation at the GL
> level (ADR-041: statement entry from CSV/CAMT.053/OFX files or
> manually, unambiguous-only
> auto-match, link-only matching, completion locked at zero
> difference) and stock document forms (receipt/issue/transfer with
> the ADR-013 GL opt-in and an opening-stock purpose) — see
> `docs/engineering/CURRENT_STATE.md`. Sprint 15 closed the last
> Sprint 06 follow-up: cheque books (ADR-042 — per-bank-account
> leaf inventory with account-level number uniqueness, consumed
> opt-in inside `create_payment`, never resurrected by bounce or
> reversal) and statement chaining prefill (the next statement's
> start/opening prefilled from the latest completed one). Note:
> Sprints 14–15 add database migrations (`treasury/0002`,
> `treasury/0003`); run `manage.py migrate` after pulling.
> Sprint 16 closed release gate #20 — login rate limiting:
> django-axes throttles failed logins per (username, IP) with a
> one-hour cooloff and a Persian lockout page (ADR-043); the axes
> package brings its own migrations, so run `manage.py migrate`
> after pulling this sprint too.
> Sprint 18 generalized statement import (ADR-044): one parser
> pipeline now reads CSV, CAMT.053 and OFX bank files (detected by
> content), and the statement-create page can build a statement
> straight from a bank file — header prefilled for review, rows
> imported on confirm, totals identity enforced. No migration and
> no new dependency in this sprint.
> Sprint 19 laid the i18n groundwork (ADR-045): real gettext
> catalogs with Persian as the source language, an English
> translation of the application chrome (shell, navigation,
> login/lockout, dashboard labels), a cookie-based language
> switcher (no URL prefixes) and language-aware direction and
> date display. Sprint 20 completed the sweep (ADR-046): every
> business page, form label, flash message and form error is
> wrapped and translated (1032 msgids, English 100%), so English
> mode is now complete for the web UI; only the print templates
> stay Persian, as Persian business documents. No migration in
> either sprint.

## Stack

Python (3.12 verified locally; 3.13 targeted — see CURRENT_STATE), Django
5.2 LTS, Django REST Framework, Django Templates, Tailwind-planned UI with a
hand-written offline CSS design system in Sprint 01, SQLite (local) /
PostgreSQL (production, via `DATABASE_URL`), Waitress, pytest, Ruff.

## Quick start (development)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # set DJANGO_SECRET_KEY
cd backend
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py compilemessages   # needs the gettext tools; see docs/engineering/DEVELOPMENT.md
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py runserver   # development only, never production
```

Open http://127.0.0.1:8000/login/ — the UI defaults to Persian / RTL
(`lang="fa" dir="rtl"`). A complete English UI can be selected
with the language button in the sidebar footer or on the login
page; the choice is stored in a cookie. Every page, form, flash
message and form error renders in English; printed documents
stay Persian (ADR-045/046).

## Quick start (standalone desktop mode)

The offline-first local installation (Sprint 09): Waitress + SQLite in
a per-user data directory, no development server, no internet needed.

```bash
.venv/bin/python launcher/accountix_launcher.py
```

The launcher backs up any existing database, migrates, starts the app
on http://127.0.0.1:8765 and opens your browser. Data lives outside the
install directory (`~/.local/share/accountix` on Linux,
`%LOCALAPPDATA%\Accountix` on Windows; override with
`ACCOUNTIX_DATA_DIR`). A frozen bundle can be built with
`scripts/build_linux.sh` / `scripts/build_windows.bat`. Full details:
`docs/deployment/LOCAL.md`; upgrades and recovery:
`docs/deployment/UPGRADE.md`.

## Tests

```bash
.venv/bin/python -m pytest      # from the repository root
.venv/bin/ruff check backend tests
cd backend && ../.venv/bin/python manage.py makemigrations --check --dry-run
```

## Documentation

- Product: `docs/product/PRD.md`
- Architecture: `docs/architecture/ARCHITECTURE.md`, `ERD.md`, `DECISIONS.md`
- Engineering: `docs/engineering/CURRENT_STATE.md`, `DEVELOPMENT.md`,
  `TESTING.md`, `SPRINT_01_REPORT.md`, `SPRINT_01_BACKLOG.md`
- Domain rules: `docs/accounting/ACCOUNTING_RULES.md`,
  `docs/inventory/INVENTORY_RULES.md`
- Deployment & user guide: `docs/deployment/`, `docs/user-guide/`

## Layout

Modular monolith: `backend/apps/` contains `core`, `users`, `organizations`,
`accounting`, `audit` (implemented in Sprint 01), `catalog`, `inventory`
(Sprint 03), `parties`, `purchases` (Sprint 04), `sales` (Sprint 05) and
`treasury` (Sprint 06); Sprint 07 added inventory counts, fiscal
closing and financial statements, and Sprint 08 installed `reporting`
as a model-free presentation layer (dashboard aggregation, filters,
CSV/XLSX exports, print templates).
