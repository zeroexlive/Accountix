# Sprint 01 — Backlog & Scope

Objective (master prompt §24): reliable foundation — startup, auth,
companies, fiscal years/periods, memberships, basic chart of accounts,
initial RTL UI, tests, developer docs.

| # | Task (§24) | Status | Evidence |
|---|---|---|---|
| 1 | Environment & configuration: settings split, SQLite + PostgreSQL via env, logging, static, test settings | Done | `backend/config/settings/*`, `.env.example` |
| 2 | Custom user before first migration; login/logout; session auth; auth tests | Done | `apps/users`, 5 auth tests |
| 3 | Company / Branch / CompanyMembership + isolation | Done | `apps/organizations`, isolation tests |
| 4 | FiscalYear / FiscalPeriod: range, non-overlap, lifecycle, within-year periods | Done | services + 11 org/fiscal tests (incl. period tests) |
| 5 | Initial Account: parent, code unique per company, type, normal balance, postable, active; no cycles/cross-company parents | Done | `apps/accounting`, 7 tests |
| 6 | Initial UI: base layout (fa/RTL), login, dashboard shell, company + fiscal-year + chart-of-accounts screens | Done (server-rendered) | `backend/templates/`, `static/css/app.css`; Tailwind/HTMX deferred — ADR-006 |
| 7 | Tests: auth, isolation, membership, fiscal validation, hierarchy, uniqueness, migration check | Done | 25 passed; `makemigrations --check` clean |
| 8 | Docs: README, development guide, ERD, ADRs, sprint report | Done | this doc set |

Out of scope for Sprint 01 (explicitly): journal posting, inventory,
sales, purchasing, treasury, reporting, launcher packaging, API endpoints.
Sprint 01 report with exact test/lint evidence: `SPRINT_01_REPORT.md`.
