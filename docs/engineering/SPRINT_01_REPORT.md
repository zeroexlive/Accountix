# Sprint 01 Report

Date: 2026-11-02. Branch: `main` (initial commit of a previously empty
repository). Environment: Python **3.12.3** (this machine has no 3.13 —
see CURRENT_STATE TD-4), Django **5.2.18**, SQLite for local/test runs,
pytest 8.4.2, Ruff 0.17.3. `uv` is not installed on this machine; venv +
pip were used (`pyproject.toml` declares all dependencies, no `uv.lock`).

## Implemented (verified)
- Settings split (base/local/test/production), env-only secrets, SQLite
  default, PostgreSQL via `DATABASE_URL`, logging, static config.
- Custom user model (`apps.users.User`, UUID pk) created **before** the
  first migrations; login/logout via Django auth views; session auth.
- Organizations: Company, Branch, CompanyMembership (roles as data),
  FiscalYear, FiscalPeriod — overlap/date-range/within-year validation in
  `apps/organizations/services.py`, invoked from model `clean()`.
- Accounting: `Account` (parent, code unique per company, type, normal
  balance, `is_postable`, active) with cycle/self-parent/cross-company
  parent rejection in `apps/accounting/services.py`.
- Core: UUID/timestamp abstract base, `user_company_ids` access helper,
  dashboard, `/health/` endpoint. Audit: `AuditEvent` + `record_event`.
- UI: Persian-first RTL templates (`lang="fa" dir="rtl"`), login,
  dashboard, company list/create/detail, fiscal year list/create,
  account list/create. All list/detail querysets are membership-filtered.
- Placeholder packages for parties/catalog/inventory/sales/purchases/
  treasury/reporting — no models, not installed. **Not features.**

## Partially implemented
- UI styling: hand-written CSS design system instead of Tailwind;
  HTMX/Alpine not loaded (ADR-006, offline honesty).
- Roles: stored on memberships, not yet enforced as permissions.
- Audit: model + helper only; no business operation writes events yet.
- CI: workflow file included, never executed on GitHub yet.

## Planned / not started
Journal entries & posting, inventory, sales, purchasing, treasury,
reporting, API endpoints, launcher/installers, backups, Jalali display,
translations (.po), concurrency tests on PostgreSQL, coverage measurement.

## Exact verification evidence (run 2026-11-02, this machine)
| Command | Result |
|---|---|
| `manage.py check --settings=config.settings.test` | "System check identified no issues (0 silenced)" |
| `manage.py migrate` (local settings, SQLite) | All migrations applied OK (users, organizations, accounting, audit + Django built-ins) |
| `manage.py makemigrations --check --dry-run` | "No changes detected" (exit 0) |
| `.venv/bin/python -m pytest` (repo root) | **25 passed in 0.78s, 0 failed** (auth 5, organizations 11, accounting 7, core 2) |
| `ruff check backend tests` | "All checks passed!" |
| `ruff format --check backend tests` | "75 files already formatted" |
| Live smoke test: `runserver` + `curl /health/` | `{"status": "ok"}` |
| Live smoke test: `curl /login/` | page contains `lang="fa"` (RTL layout served) |

Type checking (pyright/mypy): **not run** — not installed/configured in
Sprint 01; do not claim it passed.

## Security considerations
No secrets committed (`.env` ignored, prod settings reject dev key);
company isolation tested (non-member detail = 404, lists leak nothing);
CSRF/session defaults from Django; secure cookies + HSTS in production
settings.

## Known limitations
Python 3.13 unverified; no PostgreSQL run yet (driver installed, no server
on this machine was used); Tailwind/HTMX pending vendoring; push to GitHub
is via the connector's file-based snapshot (see git section of the
coordinator's delivery report — this file is written before the push
attempt and does not claim its outcome).

## Recommended next phase — Sprint 02 (Accounting Engine)
JournalEntry/JournalLine models, posting + reversal services with all
§6.3 invariants, fiscal-period posting gate, idempotency key, audit events
on posting, trial balance + general ledger derived from lines, invariant
and rollback tests, PostgreSQL test run.
