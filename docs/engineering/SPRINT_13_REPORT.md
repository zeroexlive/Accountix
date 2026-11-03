# Sprint 13 Report — Data-Entry Completion + Jalali Display

Sprint goal: finish the data-entry surface — the three Sprint 07
workflows whose pages were still read-only (fiscal closing, opening
balances, stock counts) — and make every displayed date Jalali.
Outcome: **all four scope items implemented and tested**; the web UI
now has no read-only business workflow left (only the statement /
report pages are view-only, by design: filters in, exports out). No
model changes; `makemigrations --check` reports "No changes
detected".

## Implemented (per scope item)

- **1. Fiscal closing UI** (organizations app) — a new fiscal-year
  detail page lists the year's periods with their status and, for
  closed periods, a link to the posted closing entry. "بستن دوره"
  opens a preview/confirm page showing the period's income-statement
  totals from `accounting.reporting.income_statement` (revenue,
  expenses, and the net result that will move), a retained-earnings
  picker (EQUITY, Sprint 12 eligibility rule) and the closing date
  the service will use (the period's last day); POST calls
  `close_fiscal_period`. "بازگشایی" is a POST that calls
  `reopen_fiscal_period` — the service flips the period back to OPEN
  and reverses the closing entry in one transaction, so reopening is
  still *only* possible through the reversal, and the UI never edits
  a period status itself. "بستن سال مالی" has its own confirm page
  (open periods listed) and calls `close_fiscal_year`, which closes
  each open period through the same period service and then flips
  the year. An activity-free period closes with no entry; the UI
  says so before and after.
- **2. Opening balances UI** (accounting app, sidebar: تراز
  افتتاحیه) — fiscal-year picker (default: the earliest year
  without an opening entry), an offset-account picker (EQUITY) and a
  line formset (account / debit / credit / optional party tag for
  opening AR-AP). POST calls `post_opening_balance`: unbalanced
  lines are the point of the page — the service appends the
  difference to the offset account (ADR-029). When an opening entry
  already exists for the chosen year, the page shows that fact and
  links to the entry instead of offering a duplicate form (the
  service is idempotent per year, but silently returning the old
  entry would mislead the user). The page also carries the
  opening-stock guidance: opening stock is *not* part of this entry
  — it enters as a stock receipt with source reference
  `opening_stock` (the Sprint 07 recipe), so the MWAC chain starts
  correctly; there is no stock-receipt form in the UI yet, so this is
  guidance text plus a link to the stock balances page.
- **3. Stock count UI** (inventory app) — list gains "انبارگردانی
  جدید" and detail links. Create (warehouse picker, count date,
  description) calls `create_inventory_count` with a line for every
  active stockable product of the company, counted seeded with the
  snapshot, so products with zero balance are counted too (found
  stock can be typed in, with a unit cost — the service's adjustment
  rule). The count page shows, per line, the snapshot quantity, the
  *live* ledger quantity and the counted input; saving goes through
  the new service below. The post action offers the two GL pickers
  (inventory: ASSET; variance: any eligible account) — both or
  neither (form-validated); with both, the net variance is booked by
  the service, without, only the stock adjustment posts (GL opt-in,
  ADR-013). A freeze violation (ADR-027) returns the service's
  message verbatim as a page error, on the page that shows snapshot
  vs live side by side. Posted counts show their adjustment document
  and variance journal and offer reversal (`reverse_inventory_count`).
- **4. Jalali display sweep** — new `jalali` template filter in
  `apps/core/templatetags/jalali.py` (ADR-040), applied to every
  date *display*: dashboard (period range, recent invoices/entries),
  journal list/detail, invoice lists/details/returns and the print
  templates (sales/purchase invoices, customer/supplier statements),
  payment and cheque pages (including due dates and allocation
  rows), stock movements, stock counts, fiscal year/period pages
  and the new Sprint 13 pages. Format `YYYY/MM/DD`, Latin digits
  (the UI's existing convention for amounts/codes). Storage,
  services and all inputs stay Gregorian; date-range filter labels
  gained «(میلادی)» and the count-date field carries the same hint.

## Service functions added (and why)

One, in `apps/inventory/services.py`:

- `update_inventory_count_lines(count, *, lines, user=None)` —
  `create_inventory_count` fixes a count's product set and snapshots
  at creation, but the physical count is typed in afterwards; there
  was no service to record it (the model only guards that POSTED
  counts are immutable). The new service updates counted
  quantities/unit costs of a DRAFT count's existing lines only,
  re-validating non-negative amounts, and records a
  `stock_count.lines_updated` audit event. Adding a product mid-count
  is rejected on purpose: its snapshot would be taken at a different
  moment than the rest — that is a fresh count.

Everything else reuses the Sprint 07 services unchanged:
`close_fiscal_period`, `reopen_fiscal_period`, `close_fiscal_year`,
`post_opening_balance`, `create_inventory_count`,
`post_inventory_count`, `reverse_inventory_count`.

## Jalali implementation choice

Pinned dependency `jdatetime>=5.0,<6.0` (pure Python; installed and
added to `pyproject.toml` dependencies, with an `ignore_missing_imports`
mypy override — it ships no `py.typed`). Verified conversions,
asserted by unit tests: 2026-03-21 ↔ 1405-01-01, 2026-03-20 ↔
1404-12-29 (1404 is a common year — Esfand has 29 days; the library
rejects 1404-12-30, cross-checked), 2024-03-20 ↔ 1403-01-01,
2025-01-01 ↔ 1403-10-12, plus datetime and `None` handling and the
`|default` chain behaviour. Rendered-page tests assert a known
invoice date appears as `1405/03/11` on its detail page and in its
print view, and that the Gregorian form does not appear as the
invoice's date display. One deliberate exception, documented in
ADR-040: journal-entry *descriptions* generated by services embed
ISO dates as text — that is content, not date display, and stays
untouched.

## Tested

Suite: **283 passed, 3 skipped** on SQLite (baseline 258 + 3;
25 new tests, 0 regressions). Gates: `manage.py check` clean,
mypy clean (161 files), `ruff check` clean, `ruff format --check`
clean, `makemigrations --check --dry-run` → "No changes detected".

Commands (repo root): `.venv/bin/python -m pytest`,
`.venv/bin/python backend/manage.py check --settings=config.settings.test`,
`cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .`,
`.venv/bin/python -m ruff check backend`,
`.venv/bin/python -m ruff format --check backend`,
`.venv/bin/python backend/manage.py makemigrations --check --dry-run --settings=config.settings.test`.

### Workflow evidence (test client, numeric)

- **Closing** (`organizations/tests/test_closing_ui.py`, 6 tests):
  seeded sale (revenue 1000, COGS 400) → preview shows net 600 →
  close via UI → period CLOSED, period balances of revenue and COGS
  are 0, retained earnings −600, closing entry POSTED and linked
  from the year page; a journal drafted for the closed period is
  refused at post via the journal UI and stays DRAFT with balances
  unmoved; reopen via UI → period OPEN, revenue back to −1000,
  closing entry REVERSED; empty period closes with no entry; year
  close via UI closes period + year with retained earnings −600;
  non-member gets 404 on detail, close and reopen, period untouched.
- **Opening balances** (`accounting/tests/test_opening_balance_ui.py`,
  4 tests): unbalanced form lines (Dr 7000 / Cr 1500 with a
  party-tagged AP line) → posted entry totals 7000 = 7000 with a
  Cr 5500 offset line, trial balance balanced; second visit shows
  the existing entry and a duplicate POST still yields exactly one
  entry; a two-sided line renders the service's error and persists
  nothing; non-member POST → 404.
- **Stock counts** (`inventory/tests/test_count_ui.py`, 5 tests):
  purchase 10 @ 100 → count created via UI (snapshot 10) → counted
  saved as 8 → posted with GL pickers → stock 8 / value 800,
  variance journal Dr expense 200 / Cr inventory GL 200; freeze
  violation (sale of 4 posted after the snapshot) → post rejected
  with the service's "moved since the count was taken" message on
  the page, count stays DRAFT, stock stays 6, page shows snapshot
  10 vs live 6; found stock (zero-balance product counted 5 @ cost
  50) posts to quantity 5 / value 250; non-member 404s; service
  tests pin `update_inventory_count_lines` (draft-only, negative
  rejected, product-not-in-count rejected).
- **Jalali** (`core/tests/test_jalali.py`, 10 tests): the
  conversion pairs above through the conversion function and
  through the template filter, plus rendered sales-invoice detail
  and print pages.

## Partially implemented

- Nothing in scope 1–4 is partial. Two narrowings, both deliberate:
  a count's product set is fixed at creation (missed product = fresh
  count — the snapshot semantics require it), and opening stock is
  guidance-only on the opening-balance page because the UI has no
  standalone stock-receipt form yet.

## Planned (not in this sprint)

- Bank reconciliation (largest unbuilt treasury feature) and cheque
  books (Sprint 06 limitations, unchanged).
- A standalone stock-document form (receipts/issues/transfers
  outside invoices and counts), which would also give opening stock
  a real UI path.
- `.po` translations for the English locale (labels are Persian-first
  in templates today).

## Blocked

- Nothing in the sprint scope is blocked. The GitHub sync follows
  Jason's one-commit instruction for this sprint (see the parent
  report for the push outcome).

## Known limitations

- The statement pages take Gregorian date-range inputs (labelled);
  entering a Jalali date anywhere is not supported — conversion is
  display-only by design (ADR-040).
- The frozen PyInstaller bundle is not rebuilt in this sprint; the
  new templates ship with the next bundle build (which now also
  needs `jdatetime` importable in the frozen environment — it is a
  normal project dependency, collected like the others).

## Recommended Sprint 14

**Bank reconciliation** — match treasury account movements against
bank statement lines (import or manual entry), mark cleared items,
and report the reconciled vs book balance per account: the largest
remaining treasury gap from Sprint 06. A smaller companion: the
standalone stock-document form (receipt/issue/transfer), which
closes the opening-stock UI path.
