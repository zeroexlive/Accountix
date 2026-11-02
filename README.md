# Accountix

Accounting and inventory management software for small and medium-sized
commercial businesses. Initial target market: Iran. Architecture is prepared
for international markets without a rewrite.

> **Status (2026-11-03): Sprints 01-08 done; internal MVP reached.**
> Authentication, companies/memberships, fiscal years/periods, chart of
> accounts, the double-entry journal engine (posting/reversal, trial
> balance, general ledger), the inventory engine (ledger-based stock
> movements, MWAC), purchasing (parties, purchase invoices posting into
> inventory and payables, supplier subledger), sales (invoices issuing
> stock with revenue + COGS entries, customer subledger) and treasury
> (cash/bank accounts, receipts/payments with allocation to invoices,
> cheque register with clearing/bounce) exist and are tested
> (135 tests). Financial statements, fiscal closing and opening
> balances are **planned, not implemented** - see
> `docs/engineering/CURRENT_STATE.md` and `docs/product/PRD.md`.

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
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py runserver   # development only, never production
```

Open http://127.0.0.1:8000/login/ — UI defaults to Persian / RTL
(`lang="fa" dir="rtl"`), with English localization prepared via Django i18n.

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
