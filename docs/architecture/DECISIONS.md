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

## ADR-020 — Sales invoices post two journal entries: revenue and COGS (accepted, Sprint 05)
A posted sales invoice creates **two** journal entries rather than one
combined entry: (1) the revenue entry — Dr receivables (grand total,
party-tagged with the customer), Cr revenue (net), Cr tax payable (tax) —
and (2) the COGS entry — Dr COGS / Cr inventory at the stock issue
document's movement value. The stock issue is a separately valued fact
produced by the inventory engine; keeping its entry separate mirrors how
the inventory GL opt-in already works, lets each entry be reversed and
audited on its own idempotency key (`sales-invoice:<id>` /
`sales-invoice-cogs:<id>`), and keeps the receivables subledger line in
exactly one entry. Both entries are posted inside the invoice's single
atomic transaction, so the split costs no consistency. Sales returns
mirror the split (`sales-return:<id>` / `sales-return-cogs:<id>`).

## ADR-021 — Sales returns restore stock at the original sale's COGS cost (accepted, Sprint 05)
Unlike purchase returns (current MWAC, ADR-018), a sales return receives
the goods back at the **unit cost at which they left** in the original
sale — read from the original issue document's movements. The exact cost
of the specific sale is known data, so using it makes the COGS reversal
exact: after a partial return, the COGS account carries precisely the
cost of the units still sold, even if later purchases moved the average
in between. Purchase returns cannot do this (the supplier takes goods
back at ledger value, and no original-cost claim exists against a
supplier's invoice line beyond what was paid — ADR-018 stands). The
asymmetry is deliberate and documented here so it is not "fixed" by
accident.


## ADR-022 - Treasury accounts are one table with a kind discriminator (accepted, Sprint 06)
Master prompt section 13.2 lists `CashAccount` and `BankAccount` as separate
entities. They are modelled as ONE `TreasuryAccount` table with
`kind` CASH/BANK (bank name/account number nullable, required by the service
layer for BANK): the two are the same concept - a company store of money
mapped to exactly one GL account - and payments need a single FK target.
The GL link lives on the treasury account itself, which is what lets
treasury post journals with no hardcoded account codes (ADR-011/013
discipline extended from caller-supplied to data-supplied mapping).

## ADR-023 - Allocations exist only on POSTED payments (accepted, Sprint 06)
Money first, allocation second: a DRAFT payment allocates nothing. This
keeps every allocation backed by a posted journal, makes reversal order
unambiguous (allocations are voided before the journal is reversed), and
matches how invoices allocate nothing before they post.

## ADR-024 - payment_status is the sanctioned exception to invoice immutability (accepted, Sprint 06)
Since Sprint 04/05, `payment_status` could not legally move: the posted-
invoice guard allowed only the POSTED -> REVERSED flip. The guard in both
sales and purchases now also permits a save on a POSTED invoice where
`payment_status` is the ONLY changed field (ADR-016's promise that only
treasury may move it is now enforceable rather than aspirational). The
only writer is `treasury.services.recompute_payment_status`, which derives
the value from ACTIVE allocations: UNPAID (0), PARTIALLY_PAID (0 < x <
grand total), PAID (x == grand total). Returns are not affected (they
carry no payment_status).

## ADR-025 - Allocations are voided, never deleted (accepted, Sprint 06)
Reversing a payment, bouncing/returning its cheque, or an explicit
deallocation marks `PaymentAllocation` rows VOID with timestamp and
reason; rows are never deleted and VOID rows never count toward totals.
Allocation history is audit history.

## ADR-026 - Cheque accounting model (accepted, Sprint 06)
A received cheque is NOT cash: at receipt posting it debits a
caller-supplied cheques-in-hand account (Cr receivables, party-tagged)
instead of the bank/cash GL account. Deposit changes only the register
status. Clearing posts Dr bank (a BANK treasury account's GL) / Cr
cheques-in-hand, key `cheque-clear:<id>`. Bouncing (or returning the
cheque to its issuer) posts the mirror - Dr receivables (party-tagged) /
Cr cheques-in-hand, keys `cheque-bounce:<id>` / `cheque-return:<id>` -
and voids the linked payment's allocations, so invoices fall back toward
UNPAID. Issued cheques are symmetric: at posting they credit a
caller-supplied cheques-payable account (Dr payables, party-tagged) and
the bank does not move; clearing posts Dr cheques-payable / Cr the GL of
the bank treasury account the cheque was drawn on; an issued bounce
restores the payable (Dr cheques-payable / Cr payables, party-tagged)
and voids allocations. A payment whose cheque already CLEARED or
BOUNCED cannot be reversed - those are terminal financial events with
their own journals. Transitions are a closed state machine in
`treasury.services`; illegal transitions are rejected and tested. The
Sayad id is a plain optional field: no registry validation is performed
or claimed.

## ADR-027 — Inventory counts snapshot the derived balance and freeze the warehouse (accepted, Sprint 07)
An InventoryCount line snapshots `system_qty` from the derived stock
balance at creation (ADR-012: there is no stored balance to read).
Posting re-derives every touched product's balance and REJECTS the
count if it no longer equals the snapshot: by the time a count is
posted, its warehouse must have been frozen since counting — posting a
stale count would book other documents' movements as variance. The fix
is to void the count and recount, never to silently re-snapshot.
Variances post as ONE ADJUSTMENT stock document (source
`INVENTORY_COUNT`) valued at the current MWAC; a positive variance for
a product with zero stock needs an explicit unit cost on the line (the
existing adjustment rule). The optional GL entry books the NET variance
value once (gain: Dr inventory / Cr variance; loss mirrored), key
`stock-count:<id>`. Reversal creates a POSTED reversal count with
system/counted swapped, linked via `reversal_of`, and reverses the
stock document and journal — counts are never edited or deleted after
posting.

## ADR-028 — Fiscal closing is a journal entry; reopening reverses it (accepted, Sprint 07)
Closing a period posts ONE closing journal entry (source_type
`CLOSING`, key `closing:<period id>`, dated the period's last day)
zeroing each revenue/expense account's PERIOD balance into a
caller-supplied retained-earnings account, and only then flips the
period to CLOSED — the existing posting gate does the rest. A period
with no income-statement activity closes with NO entry (tested,
documented choice). Reopening flips the period back to OPEN and
reverses the closing entry inside the same transaction (the flip must
come first: the reversal itself is a posting into that period); nothing
is ever deleted. Because the closing entry is later REVERSED when a
period reopens, `_closing_entry_for_period` only tracks POSTED closing
entries, and a re-close after reopen posts a fresh entry with key
`closing:<id>:<n>`. Fiscal-year closing closes each open period through
the same service, then flips the year's status to CLOSED.

## ADR-029 — Opening balances are one offset-balanced journal entry (accepted, Sprint 07)
`post_opening_balance` posts ONE entry (source_type `opening_balance`,
key `opening-balance:<fiscal year id>`, idempotent per fiscal year)
dated the fiscal year's first period start, requiring that period
OPEN. The service itself balances the entry: the difference between the
given debits and credits is appended as a single line on a
caller-supplied offset account (retained earnings / opening-balance
equity), so the entry is balanced BY CONSTRUCTION and can never be
posted unbalanced. Lines are validated one-sided, postable, active and
same-company, with optional party tagging for opening AP/AR. Opening
STOCK is deliberately NOT a model: it is an inventory receipt with
source reference `opening_stock` plus the Sprint 03 GL opt-in (Dr
inventory / Cr opening equity) — documented as a recipe in
INVENTORY_RULES and covered by a test.

## ADR-030 — Statements: balance-sheet result line; income statement excludes closing entries (accepted, Sprint 07)
Both statements are derived from journal lines only. The balance sheet
computes a "current period result" line — the net of ALL revenue and
expense balances with closing entries INCLUDED — and shows it inside
equity, so Assets == Liabilities + Equity + Result holds by
construction at any date: before closing the result is the open
period's profit; after closing the income accounts net to zero (the
result already sits in retained earnings) and the line is zero. The
income statement takes the opposite view and EXCLUDES closing entries
(source_type `CLOSING`), so a closed period still reports its real
operating result instead of zeros. COGS is not inferred from account
codes or names (the type taxonomy has no COGS class): callers designate
COGS accounts explicitly via `cogs_accounts=`; without designation all
expenses group together and gross profit equals net income. Amounts are
presented positive on their normal-balance side in both statements.
