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

## ADR-031 — Reporting is a derived presentation layer; the dashboard reuses the core route (accepted, Sprint 08)
The `reporting` app is installed with **no models and no migrations**: it
is a presentation/aggregation layer. Its dashboard service composes the
owning apps' reporting functions (accounting income statement, inventory
valuation/low-stock, treasury balances/open items/cheques) and adds only
two aggregations of its own, both derived from journal lines: (a) AR/AP
subledger totals summed per party over party-tagged lines on ASSET /
LIABILITY accounts respectively (ADR-015 aggregated — with a single
control account they equal the per-account subledger totals exactly,
asserted by test); (b) posted-invoice totals for a period. The one
dashboard route stays in `core` (the Sprint 01 URL): the core view
delegates figure computation to `reporting.services.dashboard_data`, so
there is exactly one dashboard. The dashboard passes `cogs_accounts=[]`
to the income statement: net income is unchanged (designated COGS
accounts are expense-type and remain inside expenses); the dashboard
shows no gross-profit figure — gross profit appears only on the income
statement page, where the user designates COGS accounts (ADR-030).

## ADR-032 — Exports are CSV + XLSX; PDF is print-to-PDF, no PDF stack (accepted, Sprint 08)
Exports use the stdlib `csv` module and `openpyxl` (added as a pinned
project dependency, Apache-2.0, already the de-facto spreadsheet
library) for trial balance and stock balances. No server-side PDF
library is added in this sprint: PDF reports would add a heavy
dependency (and, for Persian RTL text, a font/shaping problem that a
browser already solves). Instead, business documents (sales/purchase
invoices, customer/supplier statements) ship as dedicated print
templates on a print base layout with `@media print` CSS, and the
browser's print-to-PDF is the supported PDF path. Revisit a native PDF
engine only with a requirement for unattended/batch PDF generation,
and evaluate Arabic-script text shaping explicitly at that point.

## ADR-033 — Standalone settings serve static via WhiteNoise; cookies are not Secure on loopback HTTP (accepted, Sprint 09)
The packaged app gets its own settings module,
`config.settings.standalone`: DEBUG off, loopback-only ALLOWED_HOSTS,
SQLite in the per-user data directory, and a SECRET_KEY generated once
into that directory. Static files are collected into the data directory
and served by WhiteNoise (pinned dependency) — the simplest robust
option that works identically from source and in a frozen bundle,
without a separate static server. Session/CSRF cookies are
deliberately *not* marked Secure here, unlike
`config.settings.production`: standalone serves plain HTTP on
127.0.0.1 only, and a Secure cookie would never be returned by the
browser, breaking login. The threat model is a single-user local
machine; public deployments use the production settings.

## ADR-034 — Launcher process model: subprocess from source, in-process when frozen; backup gates migration (accepted, Sprint 09)
One launcher (`launcher/accountix_launcher.py`) serves both worlds.
From source it runs management commands and `backend/serve.py`
(Waitress) as subprocesses; frozen by PyInstaller it runs
`call_command` in-process and the server in a thread, because a bundle
has no child interpreter. `serve.py` only serves — migrations are the
launcher's job, sequenced as: single-instance health check (plus a pid
lock file as a secondary guard) → backup of an existing database →
migrate → collectstatic → serve → health poll → browser. A failed
backup or migration aborts startup with the database untouched; an
upgrade is therefore exactly "start the new launcher" (ADR-036). The
launcher also installs explicit SIGINT/SIGTERM handlers:
background-spawned processes inherit SIGINT masked, which once left a
supervising script unable to stop it (found by the Sprint 09 smoke
test, fixed the same day).

## ADR-035 — Backups are SQLite-API copies, integrity-verified, never trusted on write alone (accepted, Sprint 09)
`backup_db` copies SQLite via the sqlite3 backup API (consistent while
live) to `backups/accountix-<timestamp>.sqlite3` next to the database,
then verifies the copy (`PRAGMA integrity_check` + table count) before
reporting success. `restore_db` is guarded as the destructive action
it is: `--confirm` required, a `pre-restore-*` backup of the current
database first, verification before and after, and pending migrations
reported — never applied silently. PostgreSQL backup shells to
`pg_dump` (implemented, untested — no PostgreSQL on the dev machine);
PostgreSQL restore stays an operational `pg_restore` procedure.
Retention is explicit (`--keep N` on `backup_db`), not automatic.

## ADR-036 — The upgrade flow is launcher-driven; recovery is restore_db (accepted, Sprint 09)
Installing a new version never touches the data directory (it lives
outside the install dir, per `config/paths.py`). The first launch of
the new version backs up, migrates, and serves (ADR-034); recovery
from a bad upgrade is `restore_db` of the pre-upgrade backup plus the
previous version's launcher, as documented in
`docs/deployment/UPGRADE.md`. No separate updater, migration service,
or rollback machinery is built — the backup *is* the rollback.

## ADR-037 — Concurrency hardening: warehouse-row locking for stock posting; savepoint retry for journal idempotency (accepted, Sprint 10)
Sprint 10 ran the first real multi-threaded tests against PostgreSQL
16.2 (the Sprint 02+ gate that had never been exercised). Two of three
races failed before this ADR: (1) two concurrent sales invoices of 8
units against 10 in stock BOTH posted — the derived-balance plan in
`post_stock_document` was check-then-act with no common lock, so the
ledger would have gone negative; (2) concurrent `post_journal_entry`
calls with the same idempotency key were data-safe (the unique
constraint held) but the loser received a raw `IntegrityError` instead
of the winner's entry. Fixes, both small and local: stock posting now
takes `select_for_update` on the warehouse row(s) — in pk order, so
transfers cannot deadlock — before planning movements, serialising
posting per warehouse under READ COMMITTED; journal posting wraps the
entry creation in a nested atomic block (savepoint) when a key is
present and, on `IntegrityError`, returns the existing entry.
Allocations needed no fix: `allocate_payment` already locked the
payment and invoice rows before checking totals, and its race test
passed unchanged. All three concurrency tests now pass repeatedly on
PostgreSQL and skip cleanly on SQLite.

## ADR-038 — Design system v2: a token-based hand-written CSS shell; dashboard data stays derived (accepted, Sprint 11)
Sprint 11 rebuilt the screen UI after the owner's feedback that the
Sprint 01–10 interface was "too dry and soulless", using a modern
light SaaS dashboard as the visual reference. Decisions:
(1) **One hand-written CSS file, token-based.** `app.css` was rewritten
(not accreted) around design tokens — soft-gray canvas (`#f4f5f8`),
white cards (18px radius, diffuse shadows, hairline borders), a
near-black primary, one vivid accent (magenta, revenue) plus a soft
blue (expenses) and green/red/amber semantics. ADR-006 stands: no
Tailwind, no HTMX/Alpine vendoring.
(2) **Offline asset policy is a feature.** No CDN fonts, no icon
fonts, no JS chart libraries — icons are inline SVG, charts are pure
CSS bars, the font stack is Tahoma-first system fonts. The packaged
app must render identically with no network.
(3) **RTL mirroring, not translation.** The reference is LTR; the
layout is mirrored structurally (sidebar on the right, bars and
tables flow RTL) while all labels remain the existing Persian ones.
(4) **The shell is the base template.** Authenticated pages get a
sidebar + topbar + user card; anonymous pages (login) get a bare
centered shell. Print templates keep their own base and their
Sprint 08 output — the redesign is screen-only.
(5) **Honest widgets only.** The reference's decorative search,
share, customize and imports/exports buttons were NOT copied: every
control in the UI must work. Dashboard additions are two derived
helpers in `apps.reporting.services` — `period_series` (per-period
revenue/expenses from `income_statement`, sums pinned equal by
tests) and the KPI delta/performance computations (shares of
existing reports). A percentage is rendered only when its
denominator is non-zero; otherwise the panel shows an empty state.
No business logic and no stored data changed (ADR-031 spirit).

## ADR-039 — Data-entry UI writes exclusively through services; per-document GL selection; formsets without a JS requirement (accepted, Sprint 12)
Sprint 12 closed the headline v1.0 limitation — the web UI was
read-only for business documents — by adding create/edit/action
screens for parties, catalog, purchase and sales invoices and
returns, treasury accounts, payments, allocations, cheques and
manual journal entries. Decisions:
(1) **Views never post business logic.** Every state change goes
through the existing service functions of the owning app
(`post_purchase_invoice`, `post_payment`, `allocate_payment`,
`clear_cheque`, …). Forms collect input; services validate and
enforce. A service `ValidationError` is rendered as a form/non-field
error (create/post forms) or an error message (action endpoints) with
the service's own text — never swallowed, never a 500.
(2) **Per-document GL selection preserves ADR-011.** There is still
no account mapping and no hardcoded code anywhere. Each document's
post form offers the accounts its posting service needs, filtered to
the document company's *active, postable* accounts of the sensible
type (payables: LIABILITY; inventory/receivables/cash: ASSET;
revenue: REVENUE; COGS/expense: EXPENSE). The pickers' querysets are
the server-side enforcement: an id outside them fails form
validation, and the services re-validate the company before writing.
Which accounts a given document truly requires is computed from the
document itself (e.g. a tax account only when the invoice has tax).
(3) **The draft→post split for manual journals needed two thin
service functions.** Accounting previously exposed only the atomic
`post_journal_entry`. `create_journal_draft` validates the lines with
the same §6.3 `_validate_lines` used at posting time and saves a
DRAFT; `post_journal_draft` re-validates the stored lines and
requires an OPEN period. Every other document type already had a
create/post service pair, so no other service was added. Master data
(parties, units, categories, warehouses, products) follows the
Sprint 01 pattern instead: ModelForms whose model `clean()` runs the
service validation (ADR-002), with the company fixed on edit.
(4) **Line items are server-side formsets; JavaScript is optional.**
Document lines use Django formsets rendered with extra rows and
DELETE flags, fully usable with JS disabled. A small vanilla-JS
add-row clone (of the formset's `empty_form`) is the only script;
HTMX/Alpine remain unloaded (ADR-006) and Tailwind remains unused
(ADR-038).
(5) **Existing invariants are untouched.** Invoice `payment_status`
changes only inside the treasury recompute (ADR-024) because the UI
calls the treasury services; allocations are voided, never deleted
(ADR-025); received cheques sit in the cheques-in-hand holding
account until cleared (ADR-026) — the holding account is a
per-payment picker at posting time, exactly as the cheque model
requires. A POST naming a company outside the user's memberships is
a 404 on every create endpoint, and detail/action endpoints stay
membership-scoped.

## ADR-040 — Jalali dates are a display-only layer (accepted, Sprint 13)
Iranian users read dates in the Jalali (Persian) calendar, but the
ledger's chronology — period resolution, range filters, MWAC posting
order, cheque due-date semantics — is Gregorian by design and must
not move. Decision: **conversion happens only at render time.**
(1) Every stored date, every service and every form/filter input
stays Gregorian ISO, exactly as before; no model, service or parser
changed. (2) Templates render dates through a single `jalali`
template filter (`apps/core/templatetags/jalali.py`) producing
`YYYY/MM/DD` with Latin digits — the digit convention the UI already
uses for amounts and codes (mixing Persian digits into dates only
would make dates and amounts on the same row look inconsistent).
(3) The conversion delegates to the pinned pure-Python `jdatetime`
library rather than a hand-rolled algorithm: the Jalali leap-year
rule (2820-year cycle arithmetic) is exactly the kind of code that
drifts silently, and the library is the reference implementation;
its correctness here is pinned by tests on known pairs around the
1404/1405 boundary (1404 is a common year: 2026-03-20 ↔ 1404-12-29,
2026-03-21 ↔ 1405-01-01). (4) Because displays are now Jalali while
inputs stay Gregorian, date inputs that could be misread are
labelled «(میلادی)» or carry a help text saying so. (5) Service-
generated *text* (e.g. journal descriptions that embed an ISO date)
is content, not a date display, and is deliberately left untouched —
changing it would mean editing the services, which this layer
forswears.

## ADR-041 — Bank reconciliation at the GL level; link-only matching; difference identity (accepted, Sprint 14)
Reconciliation answers one question: do the books and the bank agree
about one bank account? Rather than bolting a second bookkeeping of
"bank movements" onto payments and cheques, the reconciliation is
defined directly on the ledger. (1) **Book movement**: for a BANK
treasury account, a book movement is a journal line on the account's
linked GL account whose entry is in the ledger set (POSTED or
REVERSED — the same set `accounting.reporting` uses, so a reversed
original and its reversal entry both appear and net out). By
construction this covers payments posted with method CASH or
BANK_TRANSFER on the bank account, received cheques *when they
clear* into the bank (Dr bank GL), issued cheques *when they clear*
(Cr bank GL), payment/journal reversals, and manual journals posted
straight to the bank GL — which is how bank-only items (fees,
charges, interest) enter the books. It deliberately does NOT cover
cheque *posting* (the value sits in the cheques-in-hand /
cheques-payable holding account until clearing — Sprint 06,
ADR-026), cheque deposit (register-only, no journal), or
bounce/return (holding + counterparty accounts only): none of those
touch the bank GL, so none of them can appear on a bank statement,
and no postings were invented to change that.
(2) **Sign mapping**: the bank GL account is debit-normal (an
asset), so a book movement's signed amount is `debit − credit`; a
statement line's `amount` is stored signed from the bank's
perspective with the same convention (+ = money in). A match
therefore requires exact equality of the two signed amounts — no
absolute-value matching, no tolerance.
(3) **The difference identity**: with `book` = the GL balance of the
bank account as of the statement end date, `S` = the bank's stated
closing, `U` = the net of unmatched statement lines and `O` = the
net of unmatched book movements ≤ end date, the summary reports
`difference = book − (S − U)`. The books and the statement both
enumerate the same underlying movements, so
`book − S = O − U + (opening gap)`, where the opening gap is the
book balance at the period start minus the bank's stated opening.
Under the chaining discipline — each statement's stated opening
equals the book balance at its start, which a cleanly completed
previous statement guarantees — the opening gap is zero and the
identity reduces to **`difference == O`**: the difference is exactly
the net of book movements the bank has not shown yet. When every
book movement ≤ end date is matched and every statement line is
matched, `O = 0` and `difference = 0` exactly.
Worked example (pinned in `test_reconciliation.py`): book movements
+1100 (receipt, Jun 1), −300 (payment, Jun 2), +1100 (cheque
cleared, Jun 1) → book = 1900. Statement (opening 0, closing 1850):
+1100, +1100, −300, and a −50 bank fee the books lack. Auto-match
takes only the −300 (each +1100 line has two candidates). Then
U = 2150, O = 2200, difference = 1900 − (1850 − 2150) = 2200 = O.
After the two +1100 lines are matched by hand (U = −50, O = 0,
difference = 0), booking the fee (Dr expense 50 / Cr bank 50) and
matching it gives U = O = difference = 0.
(4) **Completion rule**: a statement completes only when
`difference == 0` AND no statement line is unmatched. The second
clause is not redundant: difference can be zero while a bank-only
line (the fee above) is still unmatched, and closing over it would
freeze a real bank movement the books never recorded. Completing
locks all match/unmatch/import changes; reopening restores them.
(5) **Matching is link-only**: a match stores a OneToOne from the
statement line to the journal line (the database itself guarantees
a journal line is claimed at most once across all statements) and
never mutates the journal, the payment or the cheque behind it;
unmatching clears the link. Auto-match links a line only when
exactly one unmatched book movement has the equal signed amount
within ±7 days; ambiguity always falls back to the user.
(6) **Statement lines enter two ways**: manual entry, and CSV import
with a documented contract (header `date,description,reference,
amount` signed, or a `debit`+`credit` pair with
amount = credit − debit; ISO dates). Valid rows import in one
transaction; invalid rows are reported with their physical file
line numbers and reasons — never silently dropped, never a partial
silent mess. A (date, amount, reference) triple may occur at most
once per statement, on import and on manual entry alike.

## ADR-042 — Cheque books: account-level leaf-number uniqueness; consumption inside create_payment; used leaves are never resurrected (accepted, Sprint 15)
A cheque book is an inventory of physical paper: the leaves of the
books a bank hands over for ONE bank account, spent one by one on
ISSUED cheques. (Received cheques are other parties' paper — they
never had a book here and stay out of scope, in the model and in
the UI labels.) The Sprint 06 Cheque model already stores
`cheque_number` as a free string (today's Sayad printed number);
Sprint 15 adds the control layer around it, opt-in: nothing
changes for a company that never creates a book.
(1) **Leaf-number uniqueness is account-level**: a DB
`UniqueConstraint` on `(treasury_account, number)` across all
leaves — stronger than the `(book, number)` minimum. The Cheque
model itself keys cheques by `(company, direction, bank_name,
number)` and leaf numbers are the same printed numbers, so two
books of one account must never overlap; with account-level
uniqueness an overlapping range is impossible *by construction*,
not merely checked. `create_cheque_book` still pre-checks and
fails cleanly naming the first colliding number, and a second
`(book, position)` constraint keeps each book's sequence
well-ordered. Book creation validates: BANK account, active,
same company; 1 ≤ leaf_count ≤ 1000 (`MAX_LEAF_COUNT`); the whole
book is generated in one transaction. Leaf numbers are generated
by incrementing the trailing digit run of the first number,
preserving zero-padding ("0042" → "0043"); the number may outgrow
its width ("999" → "1000"), and a first number with no trailing
digits is allowed only for a one-leaf book.
(2) **Consumption happens where the Cheque row is created**:
`create_payment` (the row exists from DRAFT; `post_payment` never
creates cheques). The service gains an optional keyword
`leaf=None` — every existing caller and test is unaffected. With
a leaf: the payment must be an outgoing CHEQUE payment (issued
cheques only); the leaf is row-locked, must belong to the same
treasury account the payment draws on and be UNUSED; the cheque's
number is taken FROM the leaf, and a user-entered number that
conflicts with it is rejected (an equal one is accepted). On
success, inside the same transaction, the leaf flips to USED and
links to the cheque through a OneToOne (`ChequeLeaf.cheque`,
related name `leaf` on the cheque).
(3) **A used leaf is never resurrected.** Bouncing an issued
cheque, reversing its payment, or voiding anything else leaves
the leaf USED: the physical leaf left the book and was handed to
the payee — the paper is spent regardless of what the ledger
later does, and reissuing the same printed number would break
the uniqueness story in (1). Payments have no draft-discard flow
in this codebase (a DRAFT payment is only ever posted or
reversed), so there is no release path to build; consumption at
creation is the single, final consumption point. The only leaf
transition besides consumption is `void_leaf`: UNUSED → VOID for
damaged/misprinted paper, never on a USED leaf.
(4) **Book activeness is derived, never stored**: unused/used/
void counts come from annotated leaf counts
(`cheque_books_with_counts`, no N+1), so a book is "active"
exactly while it has UNUSED leaves. Books are never deleted.
Statement chaining (the second Sprint 15 piece) follows the same
derive-don't-store rule: `suggested_statement_opening` reads the
account's latest COMPLETED statement (by end date) and offers
`(end_date, closing_balance)` as the next statement's prefill —
OPEN statements are ignored because their closing is not yet
agreed with the bank, and the prefill is always editable.

## ADR-043 — Login throttling with django-axes: (username, IP) combination lockout, 1-hour cooloff, REMOTE_ADDR only (accepted, Sprint 16)
Release gate #20 (`RELEASE_READINESS.md`) recorded the one standing
security gap: no throttling existed on `/login/`, acceptable for the
loopback standalone scope but blocking for any internet-facing or
multi-user LAN deployment. Its recommendation was "reverse-proxy
rate limiting or `django-axes`". This ADR implements the second, so
the protection travels with the application (standalone, LAN and
internet profiles alike) instead of depending on each operator's
proxy being configured correctly. Hand-rolling attempt counters was
rejected: axes is the maintained, check-guarded implementation of
exactly this state machine, and it ships the admin + reset tooling
an operator needs.
(1) **Dependency and wiring**: `django-axes>=9,<10` (9.0.0 installed;
Django 5.2 / Python ≥3.11 compatible; ships `py.typed`, so no mypy
baseline entry was needed). Per the axes 9 installation docs:
`axes` in `INSTALLED_APPS`; `axes.backends.AxesStandaloneBackend`
FIRST in `AUTHENTICATION_BACKENDS` with `ModelBackend` second (the
standalone backend only monitors/refuses — credential checking and
permissions stay with ModelBackend); `axes.middleware.AxesMiddleware`
LAST in `MIDDLEWARE` (it only rewrites a locked-out login response).
All settings variants (test, local, production, standalone,
postgres_test) inherit the wiring from `base.py` — `manage.py check`
is clean under every one, with no axes W00x warnings.
(2) **Lockout parameters are the (username, IP address)
combination** — `AXES_LOCKOUT_PARAMETERS = [["username",
"ip_address"]]`. IP-only locking would lock a whole office behind
one NAT address because of one person's typos (this product's home
ground is SMB LANs); username-only locking would let an attacker
spray one account's password from many IPs (and lock the victim out
of every address at once). The combination throttles exactly the
attacker-controlled pair: a guessing client loses its own
(username, IP) pair, legitimate users elsewhere are unaffected.
This scoping is pinned by tests (same user/other IP and other
user/same IP both still log in during a lockout).
(3) **Policy values**: `AXES_FAILURE_LIMIT` = 5 and
`AXES_COOLOFF_TIME` = 1 hour, both env-overridable
(`AXES_FAILURE_LIMIT`, `AXES_COOLOFF_HOURS`) following the codebase's
environment pattern. During the cooloff even the CORRECT password
is refused — the lockout page is the response to the attempt that
reaches the limit and to every attempt until expiry; failed attempts
made during a lockout extend it (axes' documented default,
`AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT`). A successful
login resets the counter (`AXES_RESET_ON_SUCCESS`), proven by tests
that fail 4, succeed, then fail 4 more without locking.
(4) **Lockout UX**: `AXES_LOCKOUT_TEMPLATE` points at a Persian page
on the same auth-card layout as login (design system v2). It states
that entry is temporarily blocked and to retry later or contact the
administrator; it echoes no username and no countdown.
`AXES_HTTP_RESPONSE_CODE` is set to 403 explicitly: axes 9 changed
its default to 429, and 403 is the status this product documents
and tests.
(5) **Client IP = REMOTE_ADDR, period.** django-ipware is
deliberately NOT installed, so axes resolves the client IP from
`request.META["REMOTE_ADDR"]` and `X-Forwarded-For` is never read,
let alone trusted — a client cannot spoof its way out of a lockout
(or frame another address into one). `AXES_IPWARE_META_PRECEDENCE_ORDER`
is pinned to `("REMOTE_ADDR",)` so the intent is explicit in
settings. A deployment that terminates TLS at a reverse proxy must
opt in consciously: install `django-axes[ipware]` and configure
the proxy count / trusted proxy IPs / meta precedence order for
its own chain (documented in `docs/deployment/PRODUCTION.md`).
Without that opt-in a proxied deployment simply throttles per
proxy address — fail-closed, never fail-open.
(6) **Operations**: axes' own admin (Access attempts / Access logs)
is registered unchanged; an administrator unlocks a user by
deleting the Access attempt row in the admin, or from the shell
with `manage.py axes_reset_ip_username <ip> <username>` (or
`axes_reset` for all). No custom unlock code exists.
(7) **Scope is the login surface only.** DRF exposes no
authentication endpoints in this product (Sprint 10 finding), so
there is no API login to throttle; password policy, sessions and
the login form itself are untouched (below the limit, a failed
login renders exactly the same form error as before Sprint 16).
One test-suite consequence: `Client.login()` calls
`authenticate()` with no HTTP request, which the axes backend
refuses by design; the two pre-existing `test_auth.py` tests that
used it now POST real credentials through the login view instead —
the rest of the suite already used `force_login()` and is
unaffected.

## ADR-044 — Statement import: one pipeline, many parsers; CAMT.053 + OFX; create-from-file with totals identity (accepted, Sprint 18)
Sprint 14's statement import spoke exactly one format (CSV), and
banks mostly do not hand out Accountix-shaped CSVs. This ADR adds
the two standard bank formats — CAMT.053 (ISO 20022) and OFX — by
generalizing the importer rather than bolting on two more.
(1) **One pipeline, many parsers.** A parser (new module
`treasury/statement_files.py`) turns a file into the normalized
shape the CSV importer already embodied: raw row dicts in the CSV
contract shape (`date`/`description`/`reference`/`amount` strings,
amount signed from the bank's perspective, + = money in) in file
order, each tagged with a **locator** used in error reports — for
CSV the physical line number, for the XML formats the 1-based
transaction index. The downstream logic is shared verbatim:
`reconciliation._import_validated_rows` validates (date/amount
parsing, zero amount, period bounds, field lengths, the
(date, amount, reference) duplicate triple) and imports valid rows
in one transaction, reporting rejected rows with their locators —
never silently dropped. The Sprint 14 CSV entry point
(`import_statement_lines(statement, csv_text=...)`) keeps its
signature and byte-identical behaviour (its header validation
moved, messages unchanged, into `statement_files.parse_csv_text`);
the whole Sprint 14 test module passes untouched.
(2) **Detection is by content, never by extension.** OFX markers
(`OFXHEADER` / `<OFX`) first, then an XML root check for CAMT
(`Document` + camt.053 namespace or a `BkToCstmrStmt` element);
anything else falls through to CSV, whose header validation is the
clean file-level refusal garbage files get. Undecodable bytes get
the dedicated refusal the UI already rendered in Persian.
(3) **CAMT.053** is parsed with stdlib ElementTree matching on
local names, so any camt.053.001.0x namespace (or none) parses.
One file = one statement: several `<Stmt>` elements are a
file-level refusal (consistent with the CSV shape). Balances:
OPBD → opening, CLBD → closing, signed by `CdtDbtInd`. Period:
`<FrToDt>` when present, else the min/max entry booking dates.
Per entry: amount = `<Amt>` signed by `<CdtDbtInd>` (CRDT +, DBIT
−); date = `<BookgDt>` (`<Dt>` or the date part of `<DtTm>`);
reference = entry `<AcctSvcrRef>`, else the first TxDtls
`Refs/AcctSvcrRef`, else `Refs/EndToEndId` — with the literal
`NOTPROVIDED` treated as no reference, since honouring it would
make unrelated entries false duplicates; description =
`RmtInf/Ustrd` texts joined, else `AddtlNtryInf`, else the
BkTxCd domain/family codes. An entry with an unparseable amount
or date is a per-transaction rejection at its index; the rest
still import — the CSV partial-import semantics.
(4) **OFX: hand parser; `ofxparse` evaluated and rejected.** The
standard library was installed and run against crafted 1.x SGML
and 2.x XML fixtures. It parses both and returns Decimals, but it
fails two pinned requirements: it converts `DTPOSTED` timestamps
to UTC (`20260601103000[3:IRST]` → 07:30 UTC), so a posting near
midnight would silently land on the previous calendar day — this
product takes the calendar date **as written**, ignoring the
offset for the date; and it aborts the whole file on the first bad
`TRNAMT`/`DTPOSTED` (`OfxParserException`), where the pipeline
requires per-transaction rejections. The hand parser therefore
covers the bank-statement subset directly (it works unchanged on
1.x SGML and 2.x XML because OFX leaf values follow `<TAG>value`
in both, and `STMTTRN` aggregates are closed in both):
`TRNAMT` signed as-is → amount; `DTPOSTED` → the written date;
`FITID` → reference (bank-grade duplicate detection, unlike CSV's
free-text references); `NAME`/`MEMO` → description
(`NAME — MEMO` when both present). Header: `LEDGERBAL/BALAMT` →
closing balance, the `BANKTRANLIST` `DTSTART`/`DTEND` window →
period (`DTASOF` as period-end fallback). **OFX carries no
opening balance** — the chaining prefill or the user supplies it,
exactly as with CSV. No new dependency was adopted; the venv and
`pyproject.toml` are unchanged.
(5) **Header metadata composition.** Parsers also yield header
metadata (opening/closing balances, period) where the format has
it. The statement-create page gained a two-phase create-from-file
flow: uploading a file parses it, stashes the rows in the session,
and re-renders the create form with header initials composed as —
Sprint 15 chaining suggestion first, file metadata overlaid where
the file carries it (file wins), and the user's edits always last.
Confirming the form calls `create_statement_from_upload`, which
creates the statement and imports the rows in ONE transaction and
enforces the **totals identity at save**: opening + Σ imported
lines must equal the stated closing, otherwise everything rolls
back and the refusal names the three figures (with the file's
numbers still visible in the form) — a file whose closing
disagrees with its own lines is refused, never silently adjusted.
The detail-page import also accepts all formats now (lines only;
an existing statement's header is never rewritten by a file), and
its per-row error messages are labelled by physical line for CSV
(unchanged) and by transaction index for the XML formats.
(6) **Money integrity.** Amounts are `Decimal` end to end — CAMT
and OFX amounts are decimal strings in the files and are never
floated; row-level amount acceptance is exactly Sprint 14's shared
validation (no new 2-dp rule was invented here).
Known limits: multi-statement CAMT files are refused (one file =
one statement); OFX credit-card (`CCSTMTRS`) and investment
statements are out of scope (bank accounts only, like the rest of
reconciliation); the first `BANKTRANLIST`/`LEDGERBAL` wins in a
multi-account OFX file.
