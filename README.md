# Accountix

Accounting and inventory management software for small and medium-sized
commercial businesses. Initial target market: Iran. Architecture is prepared
for international markets without a rewrite.

> **Status (2026-11-02): Sprints 01-06 done; internal MVP reached.**
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
`treasury` (Sprint 06); a placeholder package remains for `reporting`
(planned, not installed).
