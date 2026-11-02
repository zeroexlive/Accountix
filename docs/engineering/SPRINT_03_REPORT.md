# Sprint 03 Report — Inventory Engine (Phase 3)

Date: 2026-11-02. Base: Sprint 02 local commit `1348104`.
Environment: Python 3.12.3, Django 5.2.18, SQLite (local/test).
PostgreSQL was **not** available on this machine (no `psql`/`pg_isready`
binaries, no server) — the suite was not run against it; this remains a
stated limitation, not a silent skip.

## Implemented (verified by tests)
- **Catalog app** (now in `INSTALLED_APPS`, migration `catalog/0001`):
  `Unit` (code unique per company), `ProductCategory` (parent hierarchy
  with cycle/cross-company validation), `Product` (SKU unique per
  company, barcode, category, base unit, `is_stockable` service flag,
  active, `min_stock_level` Decimal(19,3), reference purchase/sale
  prices), `ProductUnitConversion` (product-scoped, factor > 0,
  same-company validation). `catalog.services.convert_quantity` applies
  a direct conversion or its inverse and rejects unknown pairs.
- **Inventory app** (migration `inventory/0001`): `Warehouse` (code
  unique per company), `StockDocument` + `StockDocumentLine` (types
  RECEIPT/ISSUE/TRANSFER/ADJUSTMENT; status DRAFT/POSTED/REVERSED;
  `source_type`/`source_id`; `reversal_of`; optional `journal_entry`
  link), `StockMovement` — the authoritative, append-only ledger
  (model guards reject update/delete) — and `StockDocumentReversal`
  (OneToOne pair, mirroring ADR-009). **No StockBalance table**
  (ADR-012).
- **Services** (`apps/inventory/services.py`): `create_stock_document`,
  `post_stock_document`, wrappers `receive_stock`, `issue_stock`,
  `transfer_stock`, `adjust_stock`, and `reverse_stock_document`. All
  atomic; the full movement plan (incl. availability checks against a
  running per-(warehouse, product) balance) is computed before any
  movement is written, and the single-line wrappers wrap create+post in
  one transaction so a rejected posting leaves no orphan draft.
- **Valuation — Moving Weighted Average Cost** per (company, warehouse,
  product): receipts at line cost (priced per line unit, converted to
  base unit), issues at current average, full issue takes the full
  remaining value (zero qty ⇒ zero value), transfers preserve company
  total quantity/value at the source average, adjustments signed
  (positive at supplied cost/current average, negative like an issue).
  Negative stock is prevented for issues, transfers, negative
  adjustments and stock-reducing reversals.
- **Reversal**: exact negating movements in a new POSTED document,
  original → REVERSED, `StockDocumentReversal` record; double reversal
  and reversing a reversal rejected; reversal that would drive stock
  negative rejected.
- **GL integration (explicit opt-in, ADR-013)**: `gl_accounts=
  (inventory, offset)` on RECEIPT/ISSUE posts a balanced journal via the
  Sprint 02 service with idempotency key `stock-doc:<id>`; the document
  stores the entry, and reversing the document reverses the journal in
  the same transaction. Default path posts **no** journal (tested).
  No hardcoded account codes; `AccountingMapping` stays deferred.
- **Reporting** (`apps/inventory/reporting.py`), all derived from
  movements: `stock_balance`, `stock_balances`, `inventory_valuation`,
  `movement_history`, `low_stock`.
- **Audit**: `stock.posted` / `stock.reversed` events.
- **Minimal UI**: read-only Persian RTL product list and stock-balance
  pages (`/inventory/products/`, `/inventory/stock/`), membership
  filtered, nav links added. No posting forms — posting is via services.
- **Parties deferred (ADR-014)**: stock documents use the free
  source reference, exactly like journal entries; parties lands with
  purchasing in Sprint 04.

## Tested — exact evidence (2026-11-02, this machine)
| Command | Result |
|---|---|
| `manage.py makemigrations catalog inventory` | Created `catalog/0001_initial`, `inventory/0001_initial` |
| `manage.py check --settings=config.settings.test` | "System check identified no issues (0 silenced)" |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `.venv/bin/python -m pytest` (repo root) | **74 passed, 0 failed** (42 prior + 32 new: catalog 7, inventory 25) |
| `ruff check backend tests` | "All checks passed!" |
| `ruff format --check backend tests` | "88 files already formatted" |
| `manage.py migrate` (local settings, SQLite) | `catalog.0001`, `inventory.0001` applied OK |

New tests cover: SKU uniqueness per company (+ allowed in another
company), cross-company unit/category/conversion rejection, category
cycle, conversion direct/inverse/missing, receipt balance, exact MWAC
across two receipts (10@100 + 10@200 → avg 150), issue at average,
full-issue zero-value invariant, issue-beyond-available rollback (no
movements, no orphan draft), multi-line document rollback, transfer
total preservation + insufficient-transfer rejection, adjustments +/−,
positive adjustment without stock requiring a cost, reversal restoring
balances, double-reversal and reversing-a-reversal rejection, reversal
blocked after issue, posted document/movement immutability,
cross-company warehouse/product rejection, non-stockable rejection,
unit conversion applied to movements (2 boxes × 12 @ 1200/box →
24 pcs, value 2400, base cost 100), balance == movement sums
reconciliation, movement history, low-stock report, GL default-off,
GL opt-in balanced + idempotent, GL reversal on stock reversal,
product-list view company isolation, stock view login requirement.

## Partially implemented
- UI is read-only; no product/warehouse/document forms yet.
- Negative-stock override (audited company setting per prompt §7.4)
  does not exist — prevention is absolute for now.
- `InventoryCount`/`InventoryCountLine` (physical counting) not built;
  adjustments cover the manual-correction need in this sprint.
- `ProductPrice` history table from the ERD not built; reference prices
  live on `Product` until sales/purchasing need price history.

## Planned
Sprint 04 (Purchasing): parties, purchase orders/invoices posting into
inventory + payables via the GL opt-in pattern, supplier balances.
Then sales (COGS from MWAC), treasury, reporting statements, document
numbering, PostgreSQL concurrency tests (still an open quality gate),
backdated revaluation rules.

## Blocked / limitations
- PostgreSQL not run — no server/binaries on this machine; MWAC and
  negative-stock invariants are proven on SQLite only, concurrency
  (simultaneous issues of the same stock) untested.
- Backdating: movements apply in posting order at the current average;
  backdated revaluation is not implemented (INVENTORY_RULES rule 7).
- Type checking (pyright/mypy) still not configured/run.
- GitHub push: Sprint 03 core files are pushed file-by-file via the
  connector and verified by read-back in the coordinator's delivery
  report; this file does not claim a push outcome sight-unseen.
