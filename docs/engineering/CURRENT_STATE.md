# Current State — Repository Assessment (Phase 0)

Date: 2026-11-02 (last updated Sprint 11, 2026-11-03). Assessor: Muse development coordinator (subagent).
Repository: `zeroexlive/Accountix` (private, "Accountant software").

## 1. Evidence for the starting point (verified, not assumed)

The master prompt warns not to assume the repository is empty. It was
checked through the GitHub connector before any code was written:

| Check (2026-11-02, parent session, re-verified by this agent) | Result |
|---|---|
| `github status` | `auth_status: connected`, user `zeroexlive` (id 84627588) |
| `search_repositories` for `repo:zeroexlive/Accountix` | 1 repo, id 1443168275, private, created 2026-11-02T15:55:17Z, default branch `main` |
| `get_file_contents` (root) | Error: `409 Git Repository is empty` |
| `list_commits` | Error: `409 Git Repository is empty` |
| `list_issues` | 0 issues |

Conclusion: there were **no files, branches with history, models, migrations,
tests, docs, workflows, or frontend/launcher code to inspect** — sections of
the Phase 0 audit that require existing code are therefore "none present",
not "reviewed and clean".

## 2. Current project architecture (after Sprint 01, this commit)

Modular monolith, single Django project under `backend/`:

- `config/settings/` split: `base`, `local`, `test`, `production`.
  Secrets from environment only; SQLite default; PostgreSQL when
  `DATABASE_URL` is a postgres URL (hand-rolled parser, no extra dep).
- Installed apps: `core` (UUID/timestamp base model, company-access helpers,
  dashboard, health endpoint), `users` (custom user, UUID pk, defined before
  first migration), `organizations` (Company, Branch, CompanyMembership,
  FiscalYear, FiscalPeriod), `accounting` (Account only), `audit`
  (AuditEvent + `record_event` helper).
- Update (Sprint 02/03): `accounting` also carries the journal engine;
  `catalog` (Unit, ProductCategory, Product, ProductUnitConversion) and
  `inventory` (Warehouse, StockDocument/Line, StockMovement,
  StockDocumentReversal) are installed since Sprint 03.
- Update (Sprint 04): `parties` (Party, PartyContact, PartyAddress) and
  `purchases` (PurchaseOrder/Line, PurchaseInvoice/Line, PurchaseReturn/
  Line) are installed; `JournalLine` gained a nullable party tag for
  subledgers (ADR-015).
- Update (Sprint 05): `sales` (SalesQuotation/Line, SalesInvoice/Line,
  SalesReturn/Line) is installed; sales posting issues stock at MWAC and
  posts revenue + COGS entries (ADR-020), returns restore at the original
  COGS cost (ADR-021). The internal MVP purchase-to-sale workflow passes
  end-to-end (see `SPRINT_05_REPORT.md`).
- Update (Sprint 06): `treasury` (TreasuryAccount, Payment,
  PaymentAllocation, Cheque) is installed; receipts/payments post
  party-tagged journals, allocations are the only writer of invoice
  `payment_status` (ADR-024), and the cheque register implements the
  in-hand/clearing/bounce model (ADR-026).
- Update (Sprint 07): `inventory` gained `InventoryCount`/`InventoryCountLine`
  (snapshot + warehouse-freeze counting, ADR-027); purchase and sales
  returns are now reversible; `accounting` gained opening balances
  (ADR-029), fiscal period/year closing with reopen-via-reversal
  (ADR-028), and derived income statement + balance sheet (ADR-030)
  with read-only Persian RTL pages for both statements and counts.
- Update (Sprint 08): `reporting` is installed as a model-free
  presentation layer (ADR-031): the core dashboard renders its
  aggregation service, list pages gained GET filters + pagination,
  CSV/XLSX exports landed under `/reports/exports/`, and invoices and
  party statements gained print templates (browser print-to-PDF is the
  PDF path, ADR-032).
- Update (Sprint 09): standalone desktop mode is implemented —
  `config.settings.standalone` + `config/paths.py` (per-user data
  directory, generated secret key), `backend/serve.py` (Waitress on
  127.0.0.1), the cross-platform launcher with backup-gated migrations
  (ADR-033/034), `backup_db`/`restore_db` management commands
  (ADR-035), and a PyInstaller spec + Linux/Windows build scripts.
  The Linux bundle was built and smoke-run for real (fresh launch,
  second-launch backup, clean SIGINT shutdown); the Windows bundle is
  written but untested on Windows.
- Update (Sprint 10): production hardening + the release gate are
  done — see `SPRINT_10_REPORT.md` and `RELEASE_READINESS.md`
  (verdict: **Ready with documented limitations**). The full suite
  now runs green on PostgreSQL 16.2 as well as SQLite, and on Python
  3.13.18 as well as 3.12.3 (202 passed on SQLite / 205 on PG).
  Threaded concurrency tests found and fixed a critical stock
  overselling race and a journal-idempotency race (ADR-037); mypy is
  a clean gate; password validators are configured; DRF is on
  3.18.3; the PG `pg_dump` backup path executed for the first time.
  Headline remaining limitation: the web UI is read-only for
  business documents (setup forms + admin only), Windows is still
  unverified, and there is no login rate limiting.
- Update (Sprint 11): the screen UI was rebuilt on design system v2
  (ADR-038) after the owner's "too dry and soulless" feedback — see
  `SPRINT_11_REPORT.md`. Sidebar shell (RTL-mirrored), topbar, KPI
  cards with previous-period delta badges, a pure-CSS revenue vs
  expenses bar chart per fiscal period, a performance panel of
  derived shares, status pills and a centered login card. Two new
  derived helpers in the reporting app (`period_series`, KPI deltas)
  are pinned equal to `income_statement` by tests; no business logic
  changed. Print output is untouched.
- Update (Sprint 12): the data-entry UI is done — see
  `SPRINT_12_REPORT.md` and ADR-039. The web UI is no longer
  read-only: parties, catalog (products/units/categories/warehouses),
  purchase and sales invoices and returns, treasury accounts,
  payments, allocations, cheque actions (deposit/clear/bounce/
  return) and manual journal entries are all created, posted and
  reversed from the UI, exclusively through the existing services
  (per-document GL account pickers, ADR-011; `payment_status` still
  only via the treasury recompute, ADR-024). Two thin accounting
  service functions (`create_journal_draft` / `post_journal_draft`)
  were the only service additions. Suite: 258 passed + 3 skipped on
  SQLite, mypy clean, no model changes. This closes limitation #1 of
  `RELEASE_READINESS.md`; that Sprint 10 document keeps its verdict
  as written — the limitation it records is now historical (the
  remaining readiness items are unchanged: PG restore drill and
  Windows bundle still NOT VERIFIED, no login rate limiting).
- Update (Sprint 13): data entry is complete and dates display in
  Jalali — see `SPRINT_13_REPORT.md`, ADR-039 patterns and ADR-040.
  The three Sprint 07 workflows that still had read-only pages now
  have UI: fiscal period closing (preview with the period's
  income-statement totals + retained-earnings picker →
  `close_fiscal_period`), reopening via `reopen_fiscal_period` (the
  service reverses the closing entry; the UI never flips a status),
  whole-year closing via `close_fiscal_year`, opening balances via
  `post_opening_balance` (one entry per fiscal year; the page links
  to the existing entry instead of offering a duplicate), and stock
  counts end to end (create snapshots all stockable products →
  counted quantities edited on the count page via the one new
  service `update_inventory_count_lines` → post with optional GL
  variance booking; the ADR-027 freeze rejection surfaces verbatim,
  with snapshot vs live quantities side by side). Dates: every
  displayed date renders Jalali (`YYYY/MM/DD`, Latin digits) through
  the `jalali` template filter in `apps/core/templatetags` backed by
  the pinned `jdatetime` dependency; storage, services and all form
  inputs stay Gregorian, and filter date inputs are labelled
  «(میلادی)». No page remains read-only except the statement/report
  pages themselves (filters + exports, by design). Suite: 283 passed
  + 3 skipped on SQLite, mypy clean, no model changes.
- Update (Sprint 14): bank reconciliation and stock document forms —
  see `SPRINT_14_REPORT.md` and ADR-041. Reconciliation is defined at
  the GL level (a book movement is a posted journal line on the bank
  treasury account's GL account, which covers bank payments and
  cheque clearings — and only flows that actually touch the bank GL);
  statements enter manually or by CSV import with per-row error
  reporting, auto-match links only unambiguous exact matches,
  matching is link-only (OneToOne to the journal line), the summary
  uses difference = book − (stated closing − unmatched statement
  net), and completion is locked until the difference is exactly
  zero with no unmatched line. Stock documents (receipt / issue /
  transfer / adjustment) now have create → draft → post/reverse UI
  with the ADR-013 GL opt-in, including the «موجودی اول دوره»
  purpose that stamps the Sprint 07 `opening_stock` receipt; the
  opening-balance page's opening-stock guidance links to the new
  form. This sprint HAS a migration
  (`treasury/0002_bankstatement_bankstatementline`). Suite: 298
  passed + 3 skipped on SQLite, mypy clean.
- UI: Django templates, Persian-first RTL layout, hand-written CSS design
  system v2 in `backend/static/css/app.css`. **Honest limitation:** Tailwind is
  not integrated yet, and HTMX/Alpine are not loaded (no vendored copies; a
  CDN would break the offline-first claim). Interactivity is server-rendered.
  Since Sprint 12 the web UI is fully writable for business documents
  (data entry through the service layer only — see ADR-039), and since
  Sprint 13 also for opening balances, stock counts and fiscal
  closing. Displayed dates are Jalali (ADR-040); inputs stay
  Gregorian. Only the statement/report pages are read-only views
  (they take filters and produce exports, by design).

## 3. Existing functionality (implemented + tested in Sprint 01)

Login/logout (session auth), login-required dashboard, company
list/create/detail with membership-scoped querysets (creating a company
grants the creator an OWNER membership), fiscal year list/create, chart of
accounts list/create, `/health/` endpoint, Django admin registrations.

## 4. Missing functionality (planned — does NOT exist yet)

_Update 2026-11-02 (Sprint 02): journal entries/lines, posting & reversal
services, trial balance and general ledger are now implemented and tested
(42 tests total) — see `SPRINT_02_REPORT.md`. The paragraph below is the
remaining gap list._

_Update 2026-11-02 (Sprint 03): catalog (products/units/conversions) and
the inventory ledger (warehouses, stock documents, MWAC movements,
derived balances, opt-in GL posting) are implemented and tested
(74 tests total) — see `SPRINT_03_REPORT.md`._

_Update 2026-11-02 (Sprint 04): parties and purchasing are implemented
and tested (99 tests total) — purchase invoices post into inventory and
(optionally) the GL, supplier balances are a journal-line subledger —
see `SPRINT_04_REPORT.md`. Additional purchase costs (landed-cost
allocation) are deferred (ADR-017); no payment recording exists yet, so
every posted invoice stays UNPAID until treasury._

Reporting/PDF/Excel exports, API endpoints (DRF is
installed but exposes nothing yet), desktop launcher (only directory
skeleton), backups, MkDocs/OpenAPI, CI workflow execution on GitHub
(a workflow file is included but has never run), Persian `.po` translations,
Jalali date display, toman/rial display conversion.

## 5. Technical debt

- TD-1: Fiscal validation lives in organizations; accounting will consume it
  in Sprint 02 — keep one source of truth, do not duplicate.
- TD-2: Split 0001/0002 migrations generated by cross-app dependencies are
  normal Django output but should be reviewed before any squash.
- TD-3: `is_postable` naming: prompt says "posting eligibility"; field kept
  as `is_postable`, documented in DECISIONS.md ADR-005.
- TD-4: ~~Python 3.13 unverified~~ — resolved in Sprint 10: the full
  suite passes on Python 3.13.18 (uv-installed) as well as 3.12.3.
  `requires-python = ">=3.12"` stands.
- TD-5: No `uv.lock`: `uv` is not installed on this machine; pip + venv was
  used and `pyproject.toml` declares all dependencies. Generate `uv.lock`
  when uv becomes available.
- TD-6: Audit events are only written when a service calls `record_event`;
  since Sprint 02/03 the journal and stock posting/reversal services do
  write them (`journal.posted/reversed`, `stock.posted/reversed`).

## 6. Security concerns

- No secrets in the repo; `.env` git-ignored; production settings refuse the
  dev secret key and force secure cookies/HSTS.
- Company isolation is enforced by membership-filtered querysets and tested
  (non-member detail view returns 404, list views leak nothing).
- Sprint 10 update: dependency scanning (pip-audit) and deploy checks
  were run and triaged (see RELEASE_READINESS.md gates 5–8, 17–20);
  password validators were found absent and are now configured.
- Not yet done: role-based permission checks beyond membership (roles exist
  as data only) and **login rate limiting** (documented gap; acceptable
  for loopback standalone, blocking for internet-facing deployment).

## 7. Database concerns

- Money: no monetary fields exist yet; when they land they must be
  `DecimalField` (rules in ACCOUNTING_RULES.md). No floats anywhere.
- SQLite vs PostgreSQL locking differences are noted in settings and rules;
  concurrency tests were **run for the first time in Sprint 10** against
  PostgreSQL 16.2 (embedded `pgserver` instance — this machine has no
  system PostgreSQL): two races failed pre-fix and were fixed (ADR-037).
  PostgreSQL restore (`pg_restore`) has still never been executed.
- All business models use UUID primary keys, explicit FKs, unique
  constraints per company (branch code, membership, account code).

## 8. Documentation gaps

This commit creates the required doc set, but deployment guides are brief
stubs, the user guide covers only getting started, and API docs do not exist
because there is no API yet. Docs deliberately label planned features as
planned.

## 9. Test coverage assessment

298 pytest tests passing on SQLite with 3 skipped (Sprint 01: 25 — authentication 5,
organizations/fiscal 11, accounting accounts 7, core/health/audit 2;
Sprint 02: +17 journal/posting/reversal/reporting; Sprint 03: +32
catalog/inventory tests; Sprint 04: +25 parties/purchasing tests;
Sprint 05: +16 sales tests including the §20.4 MVP end-to-end test;
Sprint 06: +20 treasury tests including a treasury end-to-end test that
settles the MVP chain with real payments, allocations and a cleared
cheque; Sprint 07: +30 counts, reversible returns, opening balances,
fiscal closing/reopening, statements and their read-only pages;
Sprint 08: +16 reporting/dashboard/filter/export/print tests;
Sprint 09: +15 standalone-settings, data-dir, launcher-logic, health
polling and backup/restore tests, including a subprocess round-trip of
the real management commands; Sprint 10: +9 tests (3 PostgreSQL
concurrency — they skip on SQLite — 5 password-validator/security
settings, 1 open-items query-count); Sprint 11: +12 dashboard-v2
tests (series equality, delta cases, performance percentages and
empty states, sidebar link integrity, print markers); Sprint 12:
+44 data-entry UI tests (golden-path buy→sell→pay E2E through the
forms, per-area UI flows, negative/permission paths); Sprint 13:
+25 (Jalali conversion pairs + rendered pages, closing/reopen via
UI, opening balances via UI, stock-count UI incl. the freeze
rejection and the draft-lines service); Sprint 14:
+15 (reconciliation services incl. the difference-identity scenario,
reconciliation UI, stock-document UI) — see the sprint reports for exact
commands). Coverage tooling (pytest-cov) is configured as a dev
dependency but a coverage percentage was **not measured in Sprint 01** — do
not quote one. No integration/E2E/concurrency/security suites yet.

## 10. Recommended corrective actions & implementation priorities

1. ~~Sprint 02: accounting engine~~ — done. Sprint 03 (inventory) — done.
   Sprint 04 (purchasing + parties) — done. ~~Sprint 05 sales~~ — done
   (internal MVP reached). ~~Sprint 06 treasury~~ — done (payments,
   allocations, cheques; the only writer of `payment_status`).
   ~~Sprint 07 advanced inventory & accounting~~ — done (stock counting
   with snapshot + warehouse-freeze, reversible purchase/sales returns,
   opening balances, fiscal period/year closing with reopen-via-reversal,
   income statement + balance sheet with the result-line identity).
   ~~Sprint 08 reporting & UX~~ — done (derived dashboard, filters,
   CSV/XLSX exports, print templates). ~~Sprint 09 desktop packaging~~
   — done (standalone settings, launcher, backup/restore, Linux
   PyInstaller bundle built + smoke-run; Windows written-only).
   ~~Sprint 10 production hardening~~ — done (PostgreSQL suite +
   concurrency fixes, mypy gate, Python 3.13 verified, security
   review, RELEASE_READINESS.md verdict "Ready with documented
   limitations"). ~~Data-entry UI for business documents~~ — done
   (Sprints 12–13, including opening balances, stock counts, fiscal
   closing and Jalali display). ~~Bank reconciliation + stock
   document forms~~ — done (Sprint 14, ADR-041; the largest unbuilt
   treasury feature is closed). Post-v1.0 candidates: cheque books,
   Windows verification, login rate limiting, PG restore drill, .po
   translations.
2. Run the included GitHub Actions workflow once the code is on GitHub;
   add Python 3.13 to the matrix.
3. Vendor Tailwind + HTMX/Alpine locally; remove the CSS stopgap gradually.
4. Generate `uv.lock`; add coverage measurement to CI.
5. Add role permission checks when the first role-sensitive operation lands.
