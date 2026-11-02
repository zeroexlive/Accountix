# Sprint 08 Report — Reporting & UX (Phase 8)

Date: 2026-11-03. Scope: dashboard, advanced filtering, PDF/Excel
exports, print templates, UI refinement (master prompt Phase 8 + §15).
Baseline: Sprint 07 complete, 165 pytest passing (local commits
`0ed1ef6` + `071f89a`). Guiding principle, kept throughout: **no new
business logic and no new stored data** — reporting is a presentation
and aggregation layer over the existing derived reporting services.

## Implemented

- **Reporting app installed** (`apps.reporting` in `INSTALLED_APPS`) —
  deliberately model-free (`makemigrations --check` reports "No changes
  detected"; there are no reporting migrations). It carries a dashboard
  aggregation service, export views, and its own test module (ADR-031).
- **Dashboard** — the single Sprint 01 core route now renders
  `reporting.services.dashboard_data(company)` (core keeps the URL,
  reporting owns the figures). Per selected company (member companies
  only): cash total, bank total (per-account rows from treasury GL
  balances), AR and AP party-subledger totals, inventory valuation,
  posted sales/purchase totals for the current (latest OPEN) fiscal
  period, income-statement revenue/expenses/net for that period,
  open-item totals for receivables and payables, outstanding-cheque
  count + amount, low-stock count with the warning list, and the 10
  most recent journal entries, sales invoices and purchase invoices.
  Every figure is sourced from the owning app's reporting service —
  see "Tested" for the equality assertions.
  - **COGS on the dashboard (ADR-031):** the summary passes
    `cogs_accounts=[]`. COGS accounts are expense-type, so the net
    result is identical with or without the split; the dashboard
    therefore shows revenue, expenses and net income and *no*
    gross-profit figure. Gross profit appears only on the income
    statement page, where COGS accounts are designated (below).
  - The AR/AP totals aggregate the ADR-015 party-tagged subledger
    across accounts (tagged lines on ASSET accounts for receivables,
    LIABILITY for payables); with a single control account they equal
    the per-account subledger totals exactly (asserted by test).
- **Filters + pagination** (GET parameters, server-side, applied to the
  already membership-scoped querysets; shared helper
  `apps/core/pagination.py`, page size 25):
  - Income statement page: fiscal-period select, date-from/date-to,
    and a **COGS account multi-select** (EXPENSE accounts of the
    company) — gross profit renders when accounts are designated.
    This closes the known Sprint 07 UI gap (the service supported all
    of it; the page did not).
  - Balance sheet page: fiscal-period select (balance up to period
    end) and an as-of date. Trial balance page: period select.
  - Journal list: status + date range; paginated.
  - Sales / purchase invoice lists: posting status, payment status,
    party search (name or code), date range; paginated.
  - Stock balances: warehouse select + product search (SKU/name).
  - **New stock-movements list page** (`/inventory/movements/`):
    warehouse, product search, movement-date range; paginated.
  - Payments: status, method, date range; paginated. Cheques: status,
    direction, due-date range; paginated.
- **Exports** under `/reports/exports/`, same membership scoping (a
  foreign company is a 404) and the same filter parameters as the
  pages:
  - CSV (stdlib `csv`): trial balance (with period), general ledger
    for one account (with period), stock balances (with warehouse),
    AR/AP open items.
  - XLSX (`openpyxl`, added as a pinned project dependency): trial
    balance and stock balances, with numeric cells.
  - **PDF: not added as a library** — print templates + browser
    print-to-PDF are the PDF path (ADR-032, rationale in DECISIONS).
- **Print templates** — pattern: dedicated `/print/` routes rendering
  on a print base layout (no navigation; `@media print` rules added to
  the existing hand-written CSS, RTL Persian): sales invoice print,
  purchase invoice print, customer statement print, supplier statement
  print (the last built from the ADR-015 supplier subledger balance +
  purchase history; Print buttons were added to the invoice detail
  pages and the customer statement page). Each printout shows the
  company header data present on the Company model (name, legal name,
  registration number, currency), party info, document lines and the
  totals snapshots.
- **UI polish inside the existing design system only:** dashboard card
  grid (`.cards`/`.kpi`), pagination control partial template, nav
  gains the stock-movements entry; empty states on all new pages.
  Tailwind/HTMX vendoring was *not* introduced (ADR-006 debt remains,
  see limitations).

## Tested (evidence)

Commands run from the repository root, 2026-11-03:

- `.venv/bin/python -m pytest` → **181 passed** (165 prior + 16 new in
  `apps/reporting/tests/test_reporting.py`), 0 failed.
- `manage.py check --settings=config.settings.test` → "System check
  identified no issues (0 silenced)".
- `manage.py makemigrations --check --dry-run` → "No changes detected"
  — no new migrations in this sprint, as designed.
- `ruff check backend tests` → "All checks passed!";
  `ruff format --check backend tests` → clean (129 files).

New-test highlights:

- Dashboard equality: on a seeded dataset (purchase 1100 → sale 1100 →
  500 cash receipt allocated), every dashboard figure is asserted equal
  to the owning service's value — cash 500, AR subledger 600 ==
  `sales.reporting.ar_total`, AP 1100 == `purchases.reporting.ap_total`,
  inventory valuation 600, revenue 1000, net income 600 (with
  `cogs_rows == []`), open receivable 600 / payable 1100; low-stock
  warning triggers at quantity 6 < minimum 10; a foreign company id on
  the dashboard is a 404.
- Statement filters: period selection reproduces the period figures;
  a date range starting after all activity yields zeros; designating
  the COGS account shows cogs_total 400 and gross_profit 600 with net
  income unchanged; balance sheet with an as-of date before all
  activity is zero and balanced.
- List filters: sales invoices by `payment_status` (PARTIALLY_PAID
  matches, PAID matches none), party search, date range; journal
  pagination (30 draft entries → 25 + 5) and status filter; stock
  movement list count/search/warehouse filters.
- Exports on content: CSV trial balance's TOTAL row has debits ==
  credits == the service's `total_debit`; the XLSX workbook parses
  with openpyxl and its total row matches the same figure; stock CSV
  shows quantity 6 / value 600 for the seeded product and the XLSX
  contains the SKU; open-items CSV shows outstanding 600 (sales, after
  the 500 allocation) and 1100 (purchase); general-ledger CSV's final
  running balance equals the AR balance 600. All four export endpoints
  return 404 for a foreign company.
- Print views: sales/purchase invoice print return 200 and contain the
  invoice number (and grand total); customer and supplier statement
  prints return 200 with the party code; invoice print views return
  404 for a non-member.

## Partially implemented

- Exports cover trial balance, general ledger, stock balances and open
  items. Income statement / balance sheet have no export buttons yet
  (their data is one service call away; deliberately out of this
  sprint's export list).
- Print coverage is invoices + party statements; journal-entry and
  cheque printouts were not built.

## Planned / not started

- Native (server-side) PDF generation — deferred by ADR-032 until an
  unattended/batch requirement exists.
- Tailwind/HTMX vendoring (ADR-006) — still open Phase 8 debt.
- Dashboard period picker: the dashboard always uses the latest OPEN
  period (the service accepts an explicit period; the page does not
  expose the choice yet).

## Blocked / limitations

- PostgreSQL is not available on this machine (known, continuing):
  everything is verified on SQLite only; concurrency remains untested.
- Python 3.12.3 (3.13 targeted, not installed); Django 5.2.18;
  type checking (pyright/mypy) not run.
- GitHub sync happens once, at the end of this sprint, per Jason's
  workflow rule; the Sprint 01 leftover files are untouched, so the
  GitHub copy is still not a runnable clone and the local tree remains
  the source of truth.
