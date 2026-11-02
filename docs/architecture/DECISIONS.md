# Architecture Decision Records

## ADR-001 — Modular monolith (accepted)
Single deployable Django application organized by business domain. No
microservices until a demonstrated requirement exists (master prompt §5.1).

## ADR-002 — Service layer for cross-record rules (accepted)
Overlap, hierarchy/cycle and (later) posting rules live in per-app
`services.py`, invoked from model `clean()` and views/forms. Views, templates
and signals contain no complex business logic (§5.3).

## ADR-003 — SQLite local / PostgreSQL production via DATABASE_URL (accepted)
Default is a SQLite file at the project root (or `ACCOUNTIX_DATA_DIR`);
a `postgres://` `DATABASE_URL` switches engines. Parser is hand-rolled in
`config/settings/base.py` to avoid an extra dependency for two backends.

## ADR-004 — FiscalYear/FiscalPeriod live in `organizations` (accepted)
They are company-scoped master data; `accounting` consumes them from
Sprint 02. Alternative (accounting) was considered; organizations avoids a
circular dependency because accounting already depends on Company.

## ADR-005 — Account posting flag named `is_postable` (accepted)
Prompt wording "posting eligibility" is implemented as `is_postable`
(default False: an account must be explicitly made postable).

## ADR-006 — No Tailwind/HTMX/Alpine CDN (accepted, temporary)
Offline-first (§16) forbids depending on a CDN at runtime. Sprint 01 ships a
small hand-written CSS file. Tailwind and HTMX/Alpine will be **vendored**
locally in a later sprint; until then the UI is server-rendered only.

## ADR-007 — Python >=3.12 locally, 3.13 targeted (accepted with caveat)
This development machine provides Python 3.12.3 only. Django 5.2 LTS supports
it. 3.13 must be added to CI before any 3.13 support claim (see CURRENT_STATE TD-4).

## ADR-009 — Reversal modelled twice: link + record (accepted, Sprint 02)
A reversal entry points to its original via `JournalEntry.reversal_of`, and a
dedicated `JournalReversal` row (original, reversal, reversed_by, reason,
reversed_at; OneToOne on both sides) preserves who/why/when. The double
model costs one small table and makes double-reversal structurally hard.

## ADR-010 — Ledger statuses for reporting (accepted, Sprint 02)
Reporting sums lines of entries with status POSTED **or** REVERSED: a
reversed original remains in the ledger because its POSTED reversal entry
offsets it exactly. Excluding REVERSED originals while including reversals
would corrupt balances. No stored balance fields; everything is derived.

## ADR-011 — AccountingMapping deferred (accepted, Sprint 02)
No `AccountingMapping` model yet: nothing maps to accounts until sales /
purchasing / treasury land (Sprints 04–06). Adding it now would be a table
with no writer and no reader.

## ADR-008 — Money is Decimal, currency is ISO 4217 (accepted)
Default company currency `IRR`. Toman is a display unit (1 toman = 10 rials)
with explicit conversion at presentation time — never a stored currency.

## ADR-012 — StockBalance is derived, not a table (accepted, Sprint 03)
No `StockBalance` model exists. Balances, valuation, movement history and
low-stock are aggregations of the append-only `StockMovement` ledger in
`apps/inventory/reporting.py` — the same derivation discipline as
accounting balances from journal lines (ADR-010). A cached balance table
may be added later only as a rebuildable projection with reconciliation
tests; the ledger stays authoritative.

## ADR-013 — Inventory→GL posting is explicit opt-in (accepted, Sprint 03)
Stock services post **no** journal by default. A caller may pass
`gl_accounts=(inventory_account, offset_account)` for a RECEIPT (debit
inventory / credit offset) or ISSUE (debit offset / credit inventory);
the journal is created through `accounting.services.post_journal_entry`
with idempotency key `stock-doc:<document id>` and linked from the stock
document. No account codes are hardcoded anywhere in inventory — account
mapping remains deferred (ADR-011) until purchasing/sales define it.

## ADR-014 — Parties deferred past Sprint 03 (accepted, Sprint 03)
Stock documents carry a free `source_type`/`source_id` reference (the
JournalEntry pattern) instead of a party FK. Purchasing (Sprint 04) is the
first flow that genuinely needs suppliers, and it will introduce the
parties app then; inventory does not need it now.

## ADR-015 — Supplier subledger via a party tag on JournalLine (accepted, Sprint 04)
`JournalLine` gains a nullable `party` FK (migration `accounting/0004`).
Posting services may tag a line with its counterparty; purchasing tags
the payables line of every purchase/return entry. Supplier balances are
then **derived from journal lines** (`accounting.reporting.
party_account_balance`, wrapped by `purchases.reporting`), so the sum of
supplier balances reconciles with the payables account in the trial
balance by construction — no parallel AP balance table, consistent with
ADR-010/012. Reversals copy the tag onto the swapped lines so balances
net to zero. Chosen over the alternative (deriving AP from invoice
totals), which would have created a second, non-GL source of truth.
Caveat, documented in `purchases/reporting.py`: a manual journal line on
the payables account without a party tag is invisible to the subledger.

## ADR-016 — Purchase document conventions (accepted, Sprint 04)
Invoice and return numbers are unique **per company** (not per supplier).
The warehouse sits **per invoice**, not per line. Discount is **line
level only**, an absolute amount; the invoice discount total is the sum
of line discounts and inventory is valued net of discount. Tax is a
per-line **rate snapshot** with the computed amount stored at posting;
no rate is hardcoded (prompt §12.4), and which account receives the tax
debit is caller-supplied — no jurisdiction's VAT treatment is baked in.
`payment_status` is a dimension separate from posting `status` (§8); it
starts UNPAID and only treasury (Sprint 06) may move it.

## ADR-017 — Additional purchase costs deferred (accepted, Sprint 04)
Freight and other landed-cost allocation into stock value is **not**
built in Sprint 04. A proportional allocation that is not fully tested
would silently corrupt MWAC; purchase services therefore reject nothing
and book nothing for such costs — invoices carry product lines only.
Revisit when purchasing matures, with allocation tests, before sales
COGS depends on the valuation.

## ADR-018 — Purchase returns are valued at the moving average (accepted, Sprint 04)
A purchase return issues stock back to the supplier at the **current
MWAC** (that is the value that actually leaves the ledger), and the
payables debit equals that same value, keeping the return entry balanced
without inventing accounts. The difference against the original purchase
price is not booked: no price-variance account mapping exists yet
(ADR-011 still applies to mappings). Return quantities are validated
cumulatively: returned ≤ purchased − already returned, per invoice line.

## ADR-019 — StockDocumentLine.unit_cost widened to 6 dp (accepted, Sprint 04)
Purchasing values receipts net of discount, i.e. it passes a unit cost of
`net total / quantity`, which rarely has an exact 2 dp form. With the
field at 2 dp the stored cost rounded (33.3266… → 33.33) and the receipt
value drifted by cents, unbalancing the purchase journal. The field is
widened to `Decimal(19,6)` (migration `inventory/0002`); movement values
remain 2 dp money, and the journal balance check remains the guard that
rejects any residual drift atomically.
