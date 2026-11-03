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

## ADR-045 — i18n groundwork: Persian-source gettext, cookie-carried language, chrome-only scope (accepted, Sprint 19)
Until this sprint the UI was Persian-only in practice: settings had
carried `USE_I18N = True`, `LANGUAGE_CODE = "fa"` and a
`LocaleMiddleware` since Sprint 01, but no template string was
wrapped, no catalog existed and no language could be selected. This
ADR builds the real gettext pipeline and translates the **chrome**
end to end; it is explicitly groundwork, not a full translation.
(1) **The msgid is the Persian literal.** Template source strings
are Persian, so `{% trans %}`/`{% blocktrans %}` wrap the Persian
text exactly as it stands and the fa catalog's msgstrs stay empty
on purpose: an untranslated msgid renders as itself, which *is*
Persian. Consequences: the fa rendering is byte-identical to the
pre-i18n UI (the whole suite is the regression net), a wrapped
string that is missing from en.po degrades to Persian instead of
blank, and the working rule for new strings is "write Persian in
the template, wrap it, translate in en.po". English is the only
real translation today (103 strings, 100% of the wrapped set).
(2) **No URL prefixes.** `i18n_patterns` was rejected: it would
change every URL in the product and churn every test and bookmark.
The language rides in Django's language cookie via
`LocaleMiddleware` (Session → Locale → Common) and the stock
`set_language` view at `/i18n/setlang/`; a no-JS POST form (the
language switcher) sits in the sidebar footer and on the
login/lockout pages, offering the other language under its own
name (endonym convention — language names are not translated).
The choice persists across pages and across login.
(3) **Chrome scope boundary.** Wrapped and translated: `base.html`
(sidebar sections, all 22 nav labels, brand, user card, logout),
`registration/login.html`, `registration/lockout.html`, and the
dashboard template's static labels (card/panel titles, KPI labels,
table headers, empty states — never dynamic data: no service or
model string is wrapped, so journal descriptions, party names and
status codes render as stored in both languages). Everything else —
all business pages — is deliberately still unwrapped Persian and
shows as Persian in English mode too. Completing it is a named
follow-up: a string-wrapping sweep over the remaining templates
plus their en.po translations. Print templates stay fa/RTL on
purpose: they are Persian business documents.
(4) **Direction follows the language.** `base.html` emits
`lang`/`dir` from the active language (`fa` → `fa`/`rtl`,
unchanged; `en` → `en`/`ltr`). The v2 CSS was audited for LTR:
the load-bearing rules already used logical properties (sidebar
`border-inline-end`, `margin-inline-start`, `text-align: end`);
the two physical holdouts that broke table/text alignment —
`th, td { text-align: right }` and the user-chip's asymmetric
physical padding — were converted to logical equivalents with
identical RTL rendering. A pixel-perfect LTR design pass is
future work, not part of this groundwork.
(5) **Dates branch in one place.** The `jalali` filter (ADR-040)
is now language-aware in its single implementation: active
language fa (or unset) → the Jalali rendering, unchanged; any
other active language → the stored Gregorian date in ISO
`YYYY-MM-DD`. The filter keeps its name — renaming it would touch
every template for cosmetic gain; the naming debt is recorded
here.
(6) **Catalogs: `.po` committed, `.mo` built.** Compiled catalogs
are artifacts, not sources (`*.mo` is gitignored): the GitHub sync
path is a UTF-8 text snapshot and cannot carry binaries, and a
stale `.mo` shadowing a newer `.po` is a classic silent failure.
Compilation is wired where the app is built or started: the
standalone launcher runs `compilemessages` after
migrate/collectstatic on a **best-effort** basis (log and
continue — it needs the gettext `msgfmt` binary, which end-user
machines typically lack, and a missing catalog only costs a
language its translation, never the app; this deliberately
differs from migration failure, which aborts startup); the
PyInstaller build scripts run it as a hard prerequisite so the
bundle ships `.mo` files beside the `.po` sources (the spec
already bundles `backend/locale`); developers run it after
checkout (DEVELOPMENT.md). The i18n tests compile the catalogs in
their own setup, so they pass on a fresh clone.
Toolchain note: `makemessages`/`compilemessages` need the GNU
gettext tools (`msgfmt`, `xgettext`) on the machine — installed
here via apt (`gettext` 0.21); see DEVELOPMENT.md.

## ADR-046 — i18n sweep: full UI coverage, English-source services/choices catalogued, zero-migration choice labels (accepted, Sprint 20)
Sprint 19 (ADR-045) built the pipeline and translated the chrome;
this ADR records the sweep that completes English mode for the
whole web UI, plus two source-language facts the sweep established.
(1) **Coverage.** Every remaining in-scope template (all business
pages; the print templates stay Persian per ADR-045), form labels
and help texts, view flash messages, and the dashboard performance
labels built in `reporting` services are wrapped and translated:
1032 msgids in each catalog, en at 1032/1032, fa msgstrs empty by
design (ADR-045's fallback rule). Extraction is a fixpoint — a
repeated `makemessages` run produces no diff — and a scripted
census finds zero unwrapped static UI literals in scope (the only
residual hits are the endonym language switcher, the `٪` numeric
glyph, one stored void-reason data value in a hidden field, and
multi-line-call false positives). English mode is verified by a
crawl test module: list/detail/form pages of every app render
English UI labels with the Persian originals absent.
(2) **Service messages are English-source.** The codebase has
always written service-layer `ValidationError` texts in English
and rendered them verbatim into the Persian UI. The sweep wraps
them with `gettext_lazy` and named placeholders (no f-strings
inside `_()`), so their rendered text is byte-identical in both
languages today — the whole suite, which asserts many of these
messages exactly, is the proof — and they are now catalogued
(273 msgids referenced from service modules) should a future
sprint choose to translate them into Persian.
(3) **Choice labels: wrapped, zero migrations.** Model
`TextChoices` labels are likewise English source literals. Before
applying anything, wrapping one app's labels in `gettext_lazy`
was tested against `makemigrations --check`: **no changes
detected**, because Django's migration serializer evaluates lazy
proxies to their string values. The wrap was then applied to all
89 choice labels in seven `models.py` files and the full check
still reports no changes — no label migrations exist. Choice
labels therefore enter the catalogs with English msgids; fa
renders the English label exactly as before (the Persian UI has
always shown status vocabulary as English labels or raw codes),
en renders English. As with (2), the gain is cataloguing, not a
rendering change.
Convention refined from ADR-045: **the msgid is the source
literal in the language the source is written in** — Persian for
templates, forms and view messages; English for services and
choice labels. Fa falls back to the msgid in both cases, which is
what makes every step of this programme byte-identical in the
default UI. One terminology adjudication: where two apps proposed
different English for one Persian msgid, the globally consistent
term won (the سند family is "Document", matching the glossary's
"Stock documents"; context-bearing compounds keep their own
msgids, e.g. journal-specific "entry" compounds are distinct
strings and unaffected).
Test-hygiene note: a test module that POSTs to `set_language`
must reset the thread's active language afterwards (the view
activates it in-process); the Sprint 20 crawl module carries an
autouse `translation.deactivate_all()` teardown fixture, without
which the default-language jalali tests fail in full-suite order.

## ADR-047 — English-source vocabulary translated into Persian in fa.po (accepted, Sprint 21)
Sprint 20 (ADR-046) catalogued the English-source UI vocabulary —
service `ValidationError` texts and model choice labels — but left
the rendering unchanged: the default Persian UI kept showing those
strings in English, exactly as it had since Sprint 01. Whether to
change that was left as a product decision. **Decision (Jason,
2026-11-03, taken with the Sprint 20 report in front of him): the
default UI becomes fully Persian** — the English-source msgids get
real Persian translations in `fa.po`. No source-code string
changes; `en.po` is byte-untouched (English keeps rendering the
source text) and `makemessages` is not re-run (there is nothing
new to extract). Scope, identified programmatically as the msgids
containing no Arabic-script characters: **339 of the 1032 msgids**
(75 referenced from models, 261 from service modules, 2 from
templates, 2 from views, 1 from accounting reporting — the
category counts sum to 341 because two msgids are each referenced
from two categories). That set covers every service
error, every choice label (account types, document/invoice/
payment/cheque/leaf/statement statuses, roles, methods, kinds) and
the few English format patterns. Persian-source msgids keep empty
fa msgstrs (ADR-045 fallback: the msgid *is* the Persian text).
Terminology follows the existing Persian UI glossary (سند حسابداری
for journal entry, قابل ثبت for postable, قابل انبارش for
stockable, حقوق صاحبان سرمایه for equity, سود (زیان) انباشته for
retained earnings, حساب دفتر کل for GL account); placeholders —
all named `%(name)s`/`%(name)r`, 45 distinct names, no positional
or brace forms exist — are preserved character-for-character.
Stored-data strings are not in the catalog and stay untouched:
journal/audit descriptions and interpolated data values (status
codes, SKUs) render as stored in both languages, as before.
(1) **Fallback without a compiled `fa.mo` is the old behaviour.**
If catalogs are not compiled, the 339 entries fall back to their
English msgids — the pre-Sprint-21 UI, no breakage — while the
693 Persian-source entries render Persian regardless (their msgid
is Persian). Compilation is now required for **both** languages on
a dev checkout; the launcher still compiles best-effort and the
bundle builds compile as a hard step, so end users need nothing.
(2) **The test suite self-compiles.** The suite asserts on
rendered messages in both languages, so it now depends on a
compiled `fa.mo`; a session-scoped autouse fixture in the root
`conftest.py` runs `compilemessages` once per run, keeping the
suite green on a fresh clone with no manual step (verified by
deleting every `.mo` and re-running). The fixture also clears
Django's per-process translation caches
(`trans_real._translations` / `_default`) after compiling:
anything that resolves the default language before the fixture
runs (app loading, collection) otherwise caches a catalog
*without* the project strings, English-source assertions then
pass spuriously against the English fallback, and the Persian
rendering is never actually exercised — found the hard way in
this sprint, when the suite first "passed" with the translations
silently inactive in-process. The Sprint 19/20 modules keep their
own module-scoped compile fixtures (harmless duplicates).
(3) **Assertion-migration note.** Test assertions on the migrated
messages were swapped to the exact fa.po strings — same assertion
strength throughout. One mechanical subtlety:
`ValidationError.__str__` is the *repr* of its message list, and
Python's repr escapes the zero-width non-joiner (a non-printable
format character) as the literal sequence `\u200c`; a
`pytest.raises(match=…)` pattern containing a real ZWNJ can
therefore never match a Persian service message. Migrated
patterns use ZWNJ-free fragments of the same messages (or assert
on rendered page content, which carries the real character).
Flagged, not fixed: the fa catalog header carries
`Plural-Forms: nplurals=2; plural=(n > 1)` — a makemessages
default — although the CLDR rule for Persian is `nplurals=1;
plural=0`. The catalog contains no plural msgids today, so the
header is inert; correct it in the header (and re-check both
catalogs) if pluralized strings are ever introduced.

## ADR-048 — LTR design policy: logical properties, one numeric rule, directional-icon flips, language-scoped type (accepted, Sprint 22)
Sprint 19 (ADR-045) made English mode *unbroken*: the v2
stylesheet was already logical-property based and its two physical
holdouts were converted. Sprint 22 is the systematic design pass
over the result, and this ADR freezes what it established as
standing policy so future CSS does not re-introduce RTL-only
assumptions.
(1) **Logical properties only.** A scripted census of
`static/css/app.css` and every non-print template found **zero**
physical direction declarations left (no `margin/padding-left/
right`, no `left:`/`right:` insets, no physical `text-align`, no
floats, no physical border sides or corner radii, no
`translateX`, no `background-position`, no hardcoded `order`).
New styles use the logical forms (`-inline-start/-end`,
`text-align: start/end`, `inset-inline-*`); a physical direction
property needs a stated exception in review. Box-shadows are
direction-agnostic by construction here (every x-offset is 0),
and grid/flex tracks mirror with `dir` — neither needs per-mode
rules.
(2) **One numeric rule, both directions.** Figure columns —
amounts, quantities, counts, balances, debit/credit, totals —
carry the `num` class (`text-align: end` + tabular numerals):
figures align to the inline-end in RTL and LTR alike, so a column
of numbers lines up the same way in both modes. Sprint 22 applied
the hook across the display tables (it existed in CSS since
Sprint 11 but no template used it). Identifiers (account codes,
SKUs, invoice, cheque and leaf numbers) and dates are **not**
figures: they stay start-aligned text. Data-entry input grids are
out of the rule (typed input keeps start alignment in both
modes); display figures inside forms (e.g. return-form quantity
columns) are in it. Deliberate consequence, recorded here so it
is never mistaken for a regression: in Persian, figure columns
move from the cell's right edge to its left edge — the single
intentional fa visual change of the sprint; everything else in
fa is pixel-identical.
(3) **Directional icons flip; other icons never do.** An icon
whose meaning *is* a direction (chevron, back/forward arrow)
carries `.flip-rtl` and is mirrored under `[dir="ltr"]` by
`transform: scaleX(-1)`. Trend arrows (↑/↓ KPI deltas, the
trending-up nav glyph), circular/transfer arrows and
representational icons (book, box, card, clock, scales…) are
never flipped. The Sprint 22 audit of all 24 shell SVGs found no
current icon qualifying; the rule ships so the policy is
executable the day such an icon is added. Pagination ‹ › are
translated string content, not CSS: the en strings already carry
LTR-correct glyphs.
(4) **Type is language-scoped.** English gets a Latin-first
stack (`system-ui, "Segoe UI", Roboto, …` with Tahoma as a late
fallback) and tabular numerals for KPI/legend/performance
figures, both under `html[lang="en"]` selectors only. Shared
rules must not encode tuning for one script that the other
inherits.
(5) **Direction differences live in selectors, not in physical
properties.** Anything that must differ by direction is written
under `[dir="ltr"]` / `html[lang="en"]` (or the rtl mirror), so
the Persian rendering provably cannot change: neither selector
matches `<html lang="fa" dir="rtl">`.
Print templates stay out of all of this (Persian documents,
ADR-045).

**Addendum to (2) — Jason's decision, 2026-11-03 (after the
Sprint 22 report):** the inline-end alignment is superseded.
Reviewing the deliberate Persian consequence, Jason chose the
pre-Sprint-22 Persian rendering: figure columns now align to the
inline-START (`td.num,th.num` is `text-align: start` + tabular
numerals) — the right edge in Persian, the left edge in English.
The Sprint 22 `num` hook coverage (111 cells across 32 templates)
is unchanged; only the alignment edge moved. Standing rule from
now on: numeric columns are start-aligned in both modes.

## ADR-049 — First-user bootstrap: login-anchored setup redirect + launcher manage passthrough (accepted, Sprint 24)
Sprint 23's frozen smoke surfaced a release-relevant gap that had
existed since Sprint 09: a recipient of only the bundle could not
create the first user — the frozen binary had no management entry
point and no setup screen; the only path was a source checkout
running `createsuperuser` against the data directory. This ADR
closes it with two mechanisms.
(1) **The trigger lives on the login view, not in middleware.**
`SetupAwareLoginView` (users app) redirects GET and POST `/login/`
to `/setup/` while setup is available; `first_run_setup` re-checks
the same predicate on every request and redirects away (login for
anonymous, dashboard for authenticated) the moment it stops being
available, processing nothing. The funnel argument: the launcher
opens the browser at `/login/` (`config.paths.login_url`), the
dashboard is `login_required` with `LOGIN_URL = "login"`, and a
zero-user install has no authenticated sessions — so every real
first-run journey reaches the login view, and the root chain
(dashboard → login → setup) is pinned by test. Deliberately NOT
middleware: health, static, `set_language`, the admin and every
other surface keep byte-identical anonymous behaviour. (Django
admin's own `/admin/login/` is not redirected — it is not the
product's entry point, and its user is created by the setup or by
`createsuperuser` like any other.)
(2) **Availability = kill switch on AND user table empty.**
`FIRST_RUN_SETUP_ENABLED` (env `ACCOUNTIX_FIRST_RUN_SETUP`,
default on) exists because the zero-user window is
first-come-first-served by design: whoever reaches a fresh install
first becomes its admin. That is safe in the bundle's world
(loopback-only standalone, ADR-033) and in a LAN install reached
first by its installer; a deployment exposed to a network before
its first login must pre-create the admin or disable setup first
(docs/deployment/PRODUCTION.md says so in those words). With the
switch off, `/setup/` redirects to `/login/` even at zero users
and source-mode `createsuperuser` remains the bootstrap.
(3) **The installer is staff + superuser AND an OWNER member.**
The first user is the person installing the product: Django-level
superuser so nothing in the admin/ops surface (including the axes
unlock path, ADR-043) is closed to them, and an OWNER
`CompanyMembership` because OWNER is the product-level authority
every company-scoped page checks. Both in one transaction with
the company; a failed step creates nothing.
(4) **Company creation reuses the organizations UI's own path.**
The setup form takes the company name only, and the view creates
the company through `CompanyForm` — the same form
`organizations.views.company_create` saves — with the remaining
fields at their model defaults (the values that form renders as
initials, e.g. `default_currency="IRR"`), followed by the same
OWNER membership creation. Nothing else is seeded: company
creation anywhere in the product seeds no chart of accounts and
no fiscal year (accounts and fiscal years are created per company
in their own UIs), so setup seeds none either — the new admin's
next steps are the product's ordinary ones.
(5) **Passwords are never weakened for the bootstrap.**
`FirstRunSetupForm` extends `UserCreationForm`: confirmation
matching and the full `AUTH_PASSWORD_VALIDATORS` set (Sprint 10)
run as form validation; an invalid POST creates no user and no
company (pinned by test). After creation the admin is logged in
(explicit `ModelBackend` — the just-created user was not
authenticated, and axes' backend is for credential checks) and
lands on the dashboard with a success flash.
(6) **The launcher gains a management passthrough, no more.**
`accountix manage [--data-dir PATH] <args...>` is dispatched
before argparse in `accountix_launcher.main`: it resolves the
data directory and secret exactly like a normal launch
(`config.paths`), then runs the command — source mode as a
`manage.py` subprocess with inherited stdio (interactive commands
like `createsuperuser` prompt normally) and the command's exit
code as the launcher's; frozen mode via
`execute_from_command_line` in-process (manage.py's own entry
point), translating `SystemExit` back into the exit code. It
starts no server, opens no browser and takes no instance lock;
state-mutating commands follow the standing operator rule from
the backup/restore docs — stop the server first. No new locking
or safety machinery is built here.

## ADR-050 — Role-permission enforcement: membership tiers on every mutating endpoint (accepted, Sprint 25)
Since Sprint 01 every company-scoped page checked *membership* and
nothing else: any member of a company — including a VIEWER — could
post journals, close fiscal periods and void cheque leaves. The
roles on `CompanyMembership` (OWNER, ADMIN, ACCOUNTANT, SALES,
PURCHASES, WAREHOUSE, CASHIER, VIEWER; field default VIEWER) were
display data. This ADR makes them the authorization model, closing
CURRENT_STATE §10 item 5. The matrix (one row per operation class):

| Operation class | OWNER | ADMIN | ACCOUNTANT | SALES | PURCHASES | WAREHOUSE | CASHIER | VIEWER |
|---|---|---|---|---|---|---|---|---|
| READ — lists, details, dashboard, reports, exports, print | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| OPERATE — create/edit drafts, post/reverse documents, payments + allocations, cheque actions, stock documents + counts, statement import + matching, master data (parties, products, units, categories, warehouses, cheque books) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| ADMINISTER — fiscal period close/reopen, fiscal year close, fiscal year creation, opening balances, chart of accounts, treasury accounts | ✓ | ✓ | — | — | — | — | — | — |
| GOVERN — membership management (invite / role change / removal) | ✓ | — | — | — | — | — | — | — |

(1) **One helper home.** All checks live in `apps/core/access.py`:
`tier constants (READ_/OPERATE_/ADMINISTER_/GOVERN_ROLES) spelled as
role values so the module stays import-cycle free, pinned against
`CompanyMembership.Role` by a unit test so the two cannot drift;
`membership_for(user, company)` (active memberships only, cached on
the per-request user instance); `require_company_role` raising
`PermissionDenied`; `require_posted_company_role` for the
form-carried-company master-data views; and the
`scoped_company_role_required(*roles)` decorator for the
`resolve_scoped_company` create views. No view hand-rolls a check:
object views add one line after their membership-scoped fetch,
form-company views check the validated company, scoped creates take
the decorator. When a scoped create cannot resolve a company yet
(multi-company user has not chosen one), the view can only render
its chooser — every save path in those views is already guarded by
`company is not None` — so the decorator gates exactly when a
company is resolved.
(2) **403 never leaks existence.** Membership scoping runs first,
exactly as before: a non-member's request 404s on the scoped
queryset (or inside the resolver / posted-company lookup) before
any role check runs. A member below the tier gets 403 rendering
`templates/403.html` — a Persian permission-denied page in the app
shell (strings wrapped per ADR-045/046; catalogs 1041 msgids, en
100%). Read endpoints are unchanged: membership only, every role.
(3) **Defense in depth in the sensitive services.** The four
ADMINISTER services that already accept `user=`
(`post_opening_balance`, `close_fiscal_period`,
`reopen_fiscal_period`, `close_fiscal_year` in accounting) assert
the tier internally via `_require_administer_role`, raising
`PermissionDenied` (not `ValidationError` — an authorization stop,
not form feedback; the views deliberately do not catch it).
`user=None` remains the trusted internal path: the user-less
service API predates the web UI and its callers are server-side
code and tests; the web layer always passes the request user and
is itself gated, so no request path reaches these services
unchecked.
(4) **UI surfacing is presentation, never the boundary.** A
context processor (`apps.core.context_processors.company_roles`)
exposes each membership's role, the primary membership and
anywhere-flags; the shell shows company + role label (the
catalogued choice label) beside the username, falling back to the
previous generic label for membership-less users. Detail/list
templates hide the buttons and action forms the current company
role cannot use (per-object via the `company_can` template tag in
`apps/core/templatetags/access_tags.py`). Tests prove the POST is
denied with nothing persisted even though the button is hidden.
(5) **GOVERN gates nothing yet — deliberately.** No
membership-management UI exists (organizations URLs carry company
and fiscal-year pages only), so there is no surface to gate and
none was built; membership assignment remains the Django admin,
which is the operator's own tool and out of scope for product
roles. The follow-up is a members UI: GOVERN-gated, with the guard
that the last OWNER of a company cannot be demoted or removed.
Company creation stays global and ungated (the creator becomes
OWNER of the new company); company *settings edits* do not exist
as a surface either (companies are created, never edited, in the
UI), so the ADMINISTER row's "company settings" entry is reserved
for when such a page lands.

## ADR-051 — Members UI: GOVERN gets a surface, deactivation is removal, the last OWNER is guarded (accepted, Sprint 26)

ADR-050 (5) left the GOVERN tier defined but unapplied — no
members UI existed, so membership assignment stayed with the
Django admin. This ADR builds that surface in the organizations
app: a per-company members page (roster + add + role change +
(de)activation) under `companies/<pk>/members/…`, gated GOVERN
end to end with the ADR-050 ordering (membership scoping first:
non-member → 404; member below OWNER → 403), and linked only for
OWNERs (company detail page + company list rows, via the Sprint
25 `company_can` tag).

(1) **Two add paths, no invites.** The product is offline-first,
so there is no email-invite flow. An OWNER either attaches an
EXISTING system user by exact username, or creates a NEW user
inline (username, first/last name, password) and attaches them in
the same transaction. The create path reuses the Sprint 24 setup
pattern (ADR-049): a `UserCreationForm` subclass, so the full
AUTH_PASSWORD_VALIDATORS set and the username-uniqueness check
run as form validation — a weak password or a duplicate username
is a form error and nothing is created. The new user gets no
staff/superuser flags: product authority is the membership alone,
and they can log in immediately. Already-a-member — on either
path, active or deactivated — is a friendly form error; the
service repeats the check so the model's unique constraint never
leaks as an IntegrityError.

(2) **All mutations are services that assert GOVERN themselves.**
`add_member`, `create_member`, `change_member_role`,
`deactivate_member`, `reactivate_member` live in
`apps/organizations/services.py`, take the actor, and repeat the
tier assertion via `_require_govern_role` — the ADR-050 (3)
defense-in-depth posture, with the same convention: `actor=None`
is the trusted internal path, and a failure is `PermissionDenied`,
never a `ValidationError`. Role changes take effect on the
member's very next request because enforcement resolves the role
per request from the membership row (proven by test: an
ACCOUNTANT's OPERATE POST succeeds, the OWNER demotes them to
VIEWER, the identical POST then 403s).

(3) **The last-owner guard.** Demoting or deactivating a
membership that is the company's sole remaining ACTIVE OWNER is
refused with a `ValidationError` (a Persian message, catalogued)
and nothing changes. The guard counts active owners *excluding*
the target row, so it applies identically when the actor targets
themselves, and lifts as soon as a second active owner exists.
Without it, one misclick could leave a company with nobody able
to govern it — an unrecoverable state for an offline install
short of database surgery.

(4) **Deactivation is the removal path; there is no hard
delete.** Membership rows carry history (who held which role,
when) and may be referenced by audit trails, so removal flips
`is_active` off and keeps the row. That is sufficient as a
security boundary because Sprint 25 already made every scoped
queryset and role lookup see ACTIVE memberships only: a
deactivated user's access to the company becomes 404
immediately, and reactivation restores the previous role with no
re-entry of data. The roster keeps inactive rows visible (with a
reactivate action) so the state is never a surprise.

(5) **Scope kept.** The Django admin remains able to edit
memberships directly — it is the operator's own tool, outside
product roles by design (ADR-050 (5)). Password resets for
members are not part of this surface (an admin task, via the
launcher's `manage changepassword` passthrough); self-service
profile editing is a separate future surface. No model changes
were needed — `CompanyMembership.created_at` (from the shared
timestamp base) is the roster's "joined" date — so this sprint
ships no migration.

## ADR-052 — Self-service account surface: self-only by construction, the username is immutable here, version 1.0.0 gets one home (accepted, Sprint 27)

ADR-051 (5) left password resets as an operator task and profile
editing as a future surface. This ADR builds that surface in the
users app (the auth-owning app): `/profile/` and
`/profile/password/`, linked from the shell's user-identity area
for every signed-in user regardless of role or company.

(1) **Self-only by construction.** Neither URL carries a user id
and neither view accepts one: the subject is always
`request.user`. There is therefore nothing to scope, nothing to
404, and no way to render or modify another user's data through
this surface — isolation is a property of the route shape, not of
a check that could be forgotten. Both pages are login-required
(anonymous → the standard login redirect) and role-independent:
a VIEWER edits their own profile exactly like an OWNER.

(2) **The username is not editable.** It is the login identity,
the django-axes lockout key (ADR-043 keys on username+IP), and
the identifier audit trails refer to. The profile form
(`ProfileForm`) simply has no username field — the template shows
it read-only — so a POST smuggling a `username` value is ignored
by construction (proven by test). Editable: first name, last
name, email. Email is safe to edit because nothing treats it as
identity: authentication and axes key on the username alone, the
model's email is non-unique, and no flow reads it.

(3) **Password change is Django's built-in machinery.**
`AccountPasswordChangeView` subclasses the stock
`PasswordChangeView` (+ `LoginRequiredMixin`,
`SuccessMessageMixin`): the current password is required, the
new password passes the full `AUTH_PASSWORD_VALIDATORS` set,
and on success `update_session_auth_hash` keeps THIS session
signed in while every other session's stored hash goes stale —
other devices/browsers must sign in again with the new password.
Failed attempts here do NOT interact with the axes lockout:
`PasswordChangeForm` verifies the current password via
`user.check_password()` directly — no `authenticate()` call, no
`user_login_failed` signal, and axes counts failures exclusively
from that signal. Proven two ways in Sprint 27: source inspection
(`django/contrib/auth/forms.py`, `axes/signals.py`) and a test
that fails the change six times (past the limit of 5) and then
logs in successfully. Axes behaviour is unchanged either way —
the lockout remains a login-surface control.

(4) **The product version has one home.** `config/version.py`
holds `__version__ = "1.0.0"` — the first release-grade state
(all Linux gates closed, see `docs/engineering/RELEASE_STATUS.md`).
A context processor exposes it to templates; it renders subtly
in the sidebar footer and on the login page. The module ships
inside the application package tree, so source runs and the
frozen PyInstaller bundle read the same value (verified in the
Sprint 27 frozen smoke). `pyproject.toml`'s `[project] version`
mirrors it for packaging metadata only.

(5) **Scope kept.** No model changes, no migration. An operator
can still reset a member's password via the launcher's `manage
changepassword` passthrough (unchanged); this surface is for a
signed-in user changing their OWN credentials with knowledge of
the current password — it is not a recovery flow, and a
forgotten-password flow remains out of scope for the offline
product (the operator path covers it).

## ADR-053 — Design system v3 "Bento": self-hosted webfonts + Lucide sprite, bento tiles, zero-external as a test (accepted, Sprint 28)
The owner judged DS v2 (ADR-038) still "too dry and soulless" and
commissioned a third design system with hard requirements: proper
Persian AND English fonts, proper SVG icons, a modern bento look —
and everything self-hosted, zero external dependencies. ADR-038's
"system fonts + hand-drawn inline SVG" asset policy is superseded
by this ADR; its honest-widgets rule (5) stands untouched.
(1) **Webfonts, vendored.** Vazirmatn 33.003 (Persian) and Inter
4.1 (Latin), woff2 only, weights 400/500/700/800, from the official
GitHub releases, vendored into `backend/static/fonts/` with their
OFL texts and a `static/THIRD_PARTY_NOTICES.md` recording versions,
source URLs and sha256 per file (total font payload 659,264
bytes). `@font-face` with `font-display: swap`. ONE combined stack
— `"Inter", "Vazirmatn", Tahoma, …` — so per-character fallback
renders Latin in Inter and Persian glyphs in Vazirmatn in BOTH
locales; the Sprint 22 `html[lang="en"]` body stack (ADR-048 (4))
is retired, because a stack that differs per language is no longer
needed when the fonts themselves are script-specialized. What
stays language-scoped: negative letter-spacing, now applied to
Latin display type only (`html[lang="en"]`), since spacing must
never touch Arabic-script joining. Tabular figures are unscoped
now (both fonts carry `tnum`): `.kpi-value`/`.lg-value`/
`.perf-pct` get `font-variant-numeric: tabular-nums` in both
scripts, as `td.num` already had.
(2) **Icons: one Lucide sprite.** Lucide 1.67.0 (ISC) as a
generated SVG sprite, `backend/static/icons.svg` — 36 `<symbol>`s
built from the official release's `icons/*.svg` by
`scripts/build_icon_sprite.py` (the regeneration route is part of
the deliverable). Templates reference it as
`<svg class="icon"><use href="{% static 'icons.svg' %}#i-…"/></svg>`;
symbols carry Lucide's native presentation (stroke 2, round caps)
so instances size/color via CSS (`currentColor`). Every hand-drawn
inline SVG is gone (28 in the shell + the auth pages' brand marks).
The ADR-048 flip audit was repeated over the Lucide set: no icon's
meaning is a page direction (log-out and the transfer/data-flow
arrows fall in ADR-048's never-flip categories), so `.flip-rtl`
still ships with an empty flip list. The sprite is served by
WhiteNoise like any static file — no inline `<symbol>` payload is
repeated per page.
(3) **Bento tokens.** Radius scale — tiles 24px, inner cards
16px, controls 12px; layered soft shadows; a floating shell
(sidebar and topbar are rounded tiles on the canvas, sticky
sidebar); a CSS-only canvas texture (three soft radial brand
tints — no images, no gradients-as-assets); tinted icon chips
(magenta/blue/violet/green/amber soft backgrounds) heading tiles;
the brand identity is unchanged (magenta revenue, blue expenses)
with violet/amber as restrained tile accents. Tables get a
pill-shaped soft header row and the existing hover; forms get
12px controls and a blue focus ring. Logical properties only —
the Sprint 22 census discipline was re-run on the rewritten
stylesheet: zero physical direction declarations.
(4) **The dashboard is a true bento grid** — KPI tile row,
chart tile (2fr) beside the performance tile (1fr), a
quick-actions tile (330px) beside recent sales, an 8-tile mini
stat grid, then the Sprint 11 bottom stacks. Every tile is backed
by the same `dashboard_data` the Sprint 11 tests pin: the helpers,
the numbers and the honest empty states are untouched — this is a
re-skin and a rearrangement, not new data. Quick actions are the
five create routes (sales/purchase invoice, journal, payment,
product — their headings reuse the create pages' already-
catalogued strings), shown only when the user's role reaches
OPERATE in the dashboard's company (`company_can`, ADR-050
pattern): a VIEWER gets every read tile and no action tile, and
the sales tile spans the freed column. One new msgid was needed
(the tile heading «دسترسی سریع» / "Quick actions"), catalogued
additively; the catalogues' remaining diff is `#:` location churn
from the template rewrites.
(5) **Zero external is a pinned property, not a convention.** A
test scans every template and `app.css` for `http://`, `https://`,
protocol-relative and CDN references, asserts every CSS `url()`
is a relative vendored-font path, asserts every template `<use>`
target exists in the sprite (and every sprite symbol is used,
no duplicate ids, no `<svg viewBox` left in templates), and
asserts the eight font files are the ones `@font-face` declares
with wOF2 magic. Print templates are untouched (they use no DS
assets beyond the shared stylesheet, whose print block is
preserved verbatim).
(6) **Scope kept.** No models, no migration, no view or service
changes; other pages inherit the v3 tokens through `app.css`
without template restructuring (icon swaps + the dashboard are
the only template edits, plus the auth pages' brand mark).
Verification without a browser: this environment has no headless
browser, so the visual claim rests on served-output evidence —
the standalone launcher and the frozen bundle both served the
login/setup/dashboard pages (fa/rtl and en/ltr) with all fonts
and the sprite at 200 with correct content types and zero
external URLs in the served HTML; a human eye-check remains the
final pixel check, as with Sprint 22.
