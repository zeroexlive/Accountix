# Sprint 04 Report — Purchasing & Parties (Phase 4)

Date: 2026-11-02. Base: Sprint 03 local commit `056cdb5`.
Environment: Python 3.12.3, Django 5.2.18, SQLite (local/test).
PostgreSQL was **not** available on this machine — the suite was not run
against it; this remains a stated limitation, not a silent skip.

## Implemented (verified by tests)
- **Parties app** (installed, migration `parties/0001`): `Party`
  (company-scoped; `kind` SUPPLIER/CUSTOMER/BOTH as a single row per
  counterparty; `code` unique per company; optional tax/registration
  identifiers as plain fields — no jurisdiction format hardcoded),
  `PartyContact`, `PartyAddress` (company scope inherited via the party).
  `parties.services.require_supplier` guards purchasing flows against
  cross-company, inactive, or non-supplier parties.
- **Purchases app** (installed, migration `purchases/0001`):
  `PurchaseOrder` + lines (DRAFT/APPROVED/CLOSED/CANCELLED; invoices may
  exist without an order), `PurchaseInvoice` + lines, `PurchaseReturn` +
  lines. Conventions per ADR-016: warehouse per invoice, invoice/return
  numbers unique per company, line-level absolute discount only,
  per-line tax **rate snapshot** + tax amount snapshot written at
  posting, totals snapshot on the invoice that always equals the sum of
  its lines, and `payment_status` as a dimension separate from posting
  `status` — it starts UNPAID and nothing in this sprint moves it
  (payments are treasury, Sprint 06). Posted invoices/returns and their
  lines are immutable (model guards; only the POSTED → REVERSED flip is
  allowed).
- **Posting service** (`purchases/services.py`, atomic,
  validate-before-write):
  - Totals with `Decimal`: per line gross (half-up cents), net =
    gross − discount, tax = net × rate; invoice totals are the sums.
  - Stockable lines are received through the inventory services at
    their **net** unit cost (stock value == accounting inventory
    debit); service lines create no movement.
  - GL is opt-in (ADR-013 discipline): caller supplies
    `gl_accounts={inventory, payables, tax, expense}`; the balanced
    entry Dr inventory (actual stock value) + Dr expense (net service
    lines) + Dr tax (tax total) = Cr payables (grand total) is posted
    via `accounting.services.post_journal_entry` with idempotency key
    `purchase-invoice:<id>`. Without accounts: stock posts, invoice
    keeps `journal_entry = NULL` (tested, documented — not silent).
    No account code is hardcoded anywhere.
  - Reversal reverses the stock receipt **and** the journal in one
    transaction (the inventory guard blocks it when stock was already
    issued; double reversal rejected); audit events
    `purchase.posted` / `purchase.reversed`.
  - Returns (`post_purchase_return`): cumulative quantity validation
    per invoice line (returned ≤ purchased − already returned), stock
    issued back at current MWAC, and — only when the original invoice
    was GL-posted and accounts are supplied again — Dr payables /
    Cr inventory for the relieved value, key `purchase-return:<id>`;
    audit event `purchase_return.posted`.
- **Supplier subledger (ADR-015, option (a))**: `JournalLine` gained a
  nullable `party` FK (migration `accounting/0004`); the accounting
  posting service validates and stores the tag, journal reversals copy
  it to the swapped lines, and `accounting.reporting.
  party_account_balance` is the primitive. `purchases/reporting.py`
  derives `supplier_balance`, `accounts_payable` and `ap_total` from
  those tagged lines only — no AP figure comes from invoice totals.
- **Inventory schema refinement (ADR-019)**: `StockDocumentLine.
  unit_cost` widened to `Decimal(19,6)` (migration `inventory/0002`) so
  net-of-discount unit costs (net ÷ quantity) do not round to cents and
  drift the receipt value.
- **Minimal UI** (read-only, Persian RTL, membership-filtered): party
  list (`/parties/`), purchase invoice list + detail
  (`/purchases/invoices/...`), AP summary (`/purchases/payables/`,
  company + payables-account picker). Nav links added. No posting forms.

## Tested — exact evidence (2026-11-02, this machine)
| Command | Result |
|---|---|
| `manage.py makemigrations parties purchases accounting inventory` | Created `parties/0001_initial`, `purchases/0001_initial`, `accounting/0004_journalline_party`, `inventory/0002_alter_stockdocumentline_unit_cost` |
| `manage.py check --settings=config.settings.test` | "System check identified no issues (0 silenced)" |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `manage.py migrate` (local settings, SQLite) | `parties.0001`, `accounting.0004`, `inventory.0002`, `purchases.0001` applied OK |
| `.venv/bin/python -m pytest` (repo root) | **99 passed, 0 failed** (74 prior + 25 new: parties 6, purchases 19) |
| `ruff check backend tests` | "All checks passed!" |
| `ruff format --check backend tests` | "101 files already formatted" |

New tests cover: party code uniqueness per company (+ reusable in
another company), kind flags, contacts/addresses, `require_supplier`
rejection of customers and cross-company parties, party list isolation;
the E2E purchase (2 stockable lines + 10% tax snapshot: subtotal 2000,
tax 200, grand 2200; stock and MWAC updated; journal balanced; AP credit
== grand total; AP line tagged with the supplier; **supplier subledger
== trial-balance AP balance**), exact discount math with inventory
valued net of discount, non-even net unit cost keeping the exact value
(3 @ 10.00 − 1.00 discount = 29.00 in stock), service line hitting the
expense account with no stock movement, the no-GL path (stock posted,
journal NULL), idempotent re-post (same journal/stock document, single
idempotency-keyed entry), order-linked and order-less invoices, reversal
restoring stock and AP to zero, reversal blocked after a partial issue
(with state unchanged), double-reversal rejection, partial return
reducing stock and AP exactly and over-return rejection, cross-company
supplier/product/warehouse rejection, closed-fiscal-period rejection
with the invoice left DRAFT and no stock document, totals snapshot ==
recomputed line sums (including per-line tax snapshots), purchase
history reports, and invoice list/detail company isolation (other
company's detail = 404).

## Partially implemented
- UI is read-only; no party/invoice/return forms yet.
- `PurchaseOrder` is master data only: no order→invoice conversion
  service and no received-quantity tracking against orders yet.
- Purchase returns cannot themselves be reversed (status REVERSED is
  reserved on the model; no service).
- Subledger caveat (ADR-015): manual journal lines on the payables
  account without a party tag are invisible to the AP subledger.

## Planned / not started
- Additional purchase costs / landed-cost allocation — **deliberately
  deferred** (ADR-017): not recorded, not allocated; revisit with
  allocation tests before sales COGS depends on valuation.
- Payment recording and allocation (treasury, Sprint 06) — the only
  writer allowed to move `payment_status`.
- `AccountingMapping` remains deferred (ADR-011): accounts are still
  caller-supplied per posting, never hardcoded.

## Blocked / limitations
- PostgreSQL not run — no server/binaries on this machine; concurrency
  invariants (simultaneous posting of the same invoice, MWAC races)
  remain proven on SQLite only.
- Purchase returns are valued at current MWAC; any difference against
  the original purchase price is not booked (no price-variance mapping
  exists — ADR-018).
- Type checking (pyright/mypy) still not configured/run.
- GitHub push: Sprint 04 core files are pushed file-by-file via the
  connector in one end-of-sprint sync and verified by read-back in the
  coordinator's delivery report; this file does not claim a push
  outcome sight-unseen. The separately tracked Sprint 01 leftover files
  were not touched.

## Recommended next phase — Sprint 05 (Sales, the internal MVP)
Parties already cover customers. Build `sales`: SalesQuotation (optional
flow), SalesInvoice/Line with the same conventions as purchases
(numbering, separate payment status, tax snapshots), posting that issues
stock at MWAC (COGS), posts Dr receivables (party-tagged customer
subledger, reusing ADR-015) / Cr revenue + tax, returns mirroring
purchase returns, and the end-to-end MVP test from the master prompt
§20.4: company → accounts → supplier → purchase → stock → sale → COGS →
receivable → trial balance reconciliation.
