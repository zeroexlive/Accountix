# Sprint 07 Report — Advanced Inventory & Accounting

Date: 2026-11-02. Scope: stock counting, reversible returns, opening
balances, fiscal closing, first financial statements (master prompt
Phase 7 + §6.4/§13.2). Baseline: Sprint 06 complete, 135 pytest passing
(local commits `3218d28` + `9621dca`).

## Implemented

- **Inventory counts (`inventory`, ADR-027).** `InventoryCount` +
  `InventoryCountLine` (migration `inventory/0003`): lines snapshot the
  derived `system_qty` at creation; `variance = counted − system`.
  `post_inventory_count` enforces the **warehouse-freeze rule** (rejects
  when the live balance no longer equals the snapshot), then posts ONE
  ADJUSTMENT stock document (source `INVENTORY_COUNT`) with only the
  non-zero variance lines at current MWAC; a positive variance with
  zero stock needs an explicit line `unit_cost`. Optional GL books the
  **net** variance value once (gain Dr inventory / Cr variance; loss
  mirrored), key `stock-count:<id>`. `reverse_inventory_count` reverses
  journal + stock document and stores a POSTED reversal count with
  system/counted swapped and `reversal_of` set. Posted counts/lines are
  immutable (model guards); a read-only count list page was added.
- **Reversible returns (returns matrix completed).**
  `reverse_purchase_return` / `reverse_sales_return` mirror invoice
  reversal: journals and stock documents are reversed atomically and
  the return flips to REVERSED; double reversal and reversing drafts
  are rejected. Returned-quantity tallies sum POSTED returns only, so a
  reversed return frees the quantity — verified by return-3 →
  reverse → return-3-again tests in both apps.
- **Opening balances (`accounting`, ADR-029).**
  `post_opening_balance(company, fiscal_year, lines, offset_account)`
  posts ONE entry (`source_type='opening_balance'`, key
  `opening-balance:<fiscal year id>`) dated the fiscal year's first
  period start, requiring that period OPEN. The service balances the
  entry by appending the difference to the caller-supplied offset
  account, so the entry is balanced by construction; lines are
  validated one-sided/postable/active/same-company with optional party
  tagging. Idempotent per fiscal year. **Opening stock** is a documented
  recipe, not a model: receipt with source reference `opening_stock` +
  the Sprint 03 GL opt-in (INVENTORY_RULES §11), covered by a test.
- **Fiscal closing (`accounting` services, ADR-028).**
  `close_fiscal_period` posts ONE closing entry (`source_type='CLOSING'`,
  key `closing:<period id>`, dated the period end) zeroing each
  revenue/expense account's period balance into a caller-supplied
  retained-earnings account, then flips the period to CLOSED — the
  existing posting gate then rejects new postings into it. A period
  with no income-statement activity closes with **no entry** (chosen +
  tested). `reopen_fiscal_period` flips the period OPEN and reverses
  the closing entry in the same transaction — nothing is deleted; a
  re-close posts a fresh entry (`closing:<id>:<n>`).
  `close_fiscal_year` closes each open period in start order and flips
  the year to CLOSED (the model's status field supports it — no schema
  change was needed anywhere in closing).
- **Financial statements (`accounting/reporting.py`, ADR-030).**
  `income_statement` (period or date range): revenue credit-positive,
  expenses debit-positive, COGS = caller-designated expense accounts
  (`cogs_accounts=` — never guessed from codes/names), gross profit and
  net income; **closing entries excluded** so closed periods still
  report operating results. `balance_sheet` (as-of / period end):
  assets / liabilities / equity from account types with a computed
  **current period result** line (income balances with closing entries
  included), so Assets == Liabilities + Equity + Result holds before
  closing (result = open profit) and after (result = 0, profit inside
  retained earnings). Read-only Persian RTL pages for both statements.

## Tested (evidence)

Commands run from the repository root unless noted:

- `.venv/bin/python -m pytest` → **165 passed** (135 prior + 30 new:
  counts 11, purchase-return reversal 3, sales-return reversal 3,
  accounting closing/statements 10, statement/count pages 3), 0 failed.
- New-test highlights: count ±variances → movements + derived balances;
  zero-variance lines create nothing; count GL nets for gain and loss;
  count reversal restores stock + GL; stale-snapshot count rejected;
  opening-stock recipe via receipt + GL; opening balance balances,
  lands in the first period, blocked when that period is closed,
  idempotent, cross-company rejected; full closing chain (sale →
  close → revenue/expense zeroed, net income 600 inside retained
  earnings → posting into the closed period rejected → reopen reverses
  and restores → re-close posts a new entry); closing an inactive
  period posts no entry but closes; fiscal-year closing across two
  periods; on a rich dataset (opening balance + purchase + sale +
  partial supplier payment + cleared customer cheque) the income
  statement's net income equals an independent raw-line recomputation
  (600) and the balance-sheet identity holds pre-closing
  (6300 = 700 + 5000 + 600) and post-closing (6300 = 700 + 5600 + 0).
- `manage.py check --settings=config.settings.test` → no issues.
- `manage.py makemigrations --check --dry-run` → "No changes detected".
- `manage.py migrate --settings=config.settings.local` →
  `inventory.0003` applied OK.
- `.venv/bin/python -m ruff check backend tests` → all checks passed;
  `ruff format --check` → clean (123 files).

## Partially implemented

- Statements UI is read-only with a company selector only (no period
  selector yet, no COGS designation in the UI — the page shows all
  expenses grouped together); filtering/exports belong to Sprint 08.
- The income statement's COGS split exists only at the service API
  (`cogs_accounts=`); the chart of accounts has no COGS account type
  (documented in ADR-030 rather than silently extended).

## Planned (not in this sprint)

- Sprint 08 (Reporting & UX): dashboard, advanced filtering incl.
  period selectors on statements, PDF/Excel exports, print templates.
- Bank reconciliation, cheque books, DRF API, role-based permissions,
  Jalali display, Tailwind/HTMX vendoring — unchanged from Sprint 06.

## Blocked / limitations

- **PostgreSQL is not available on this machine** (no server/binaries):
  all tests ran on SQLite; concurrent-posting behaviour on PostgreSQL
  remains unverified — a continuing, known limitation.
- Runtime is Python **3.12.3** (3.13 targeted by the master prompt but
  not installed here); Django 5.2.18. Type checking (pyright/mypy) was
  not run.
- GitHub sync: performed once at sprint end, core files only, verified
  by read-back content match (see the delivery note accompanying this
  report). The pre-existing Sprint 01 leftover gap on GitHub (local-only
  migrations/templates/tests from Sprint 01) is unchanged and tracked
  separately — the GitHub copy is still not a runnable clone; the local
  tree remains the source of truth.
