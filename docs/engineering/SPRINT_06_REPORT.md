# Sprint 06 Report - Treasury & Cheques (Phase 6)

Date: 2026-11-02. Base: Sprint 05 local commit `13b9d30` (internal MVP).
Environment: Python 3.12.3, Django 5.2.18, SQLite (local/test).
PostgreSQL was **not** available on this machine - invariants are proven
on SQLite only; this remains a stated limitation, not a silent skip.

## Implemented (verified by tests)

- **Treasury app** (installed, migration `treasury/0001`):
  - `TreasuryAccount` - ONE table, `kind` CASH/BANK (ADR-022, a stated
    deviation from the section 13.2 two-model listing), each row linked
    to its GL `Account`. That link is the mapping: treasury posts with
    no hardcoded account codes.
  - `Payment` - direction RECEIPT/PAYMENT, party, treasury account,
    method CASH/BANK_TRANSFER/CHEQUE, amount > 0 (DB check), status
    DRAFT/POSTED/REVERSED with the posted-document immutability guard.
    The AR/AP account used is supplied by the caller at posting and
    stored as `counterparty_account` for later reversal/bounce/clearing.
  - `PaymentAllocation` - exactly one target (sales XOR purchase
    invoice, DB check), amount > 0, status ACTIVE/VOID.
  - `Cheque` - direction RECEIVED/ISSUED, bank name, number (unique per
    company+direction+bank), optional plain `sayad_id` (no registry
    validation performed or claimed), amount, issue/due dates, status
    state machine, `holding_account`, clearing/bounce journal links.
- **Posting service** (`post_payment`, atomic, validate-before-write,
  idempotent re-post): RECEIPT Dr treasury GL (or cheques-in-hand for a
  cheque) / Cr receivable **party-tagged**; PAYMENT Dr payable
  **party-tagged** / Cr treasury GL (or cheques-payable for a cheque);
  key `payment:<id>`; audit event `payment.posted`.
- **Allocations** (`allocate_payment`, ADR-023): only on POSTED
  payments, only to POSTED invoices, direction must match target type,
  invoice party must equal payment party, same company, and neither the
  payment's total nor the invoice's grand total may be over-allocated
  (unallocated remainder stays on account - allowed and tested).
- **`payment_status` writer rule delivered** (ADR-024): treasury's
  `recompute_payment_status` is the only writer; it derives UNPAID /
  PARTIALLY_PAID / PAID from ACTIVE allocations. The sales/purchases
  immutability guards gained exactly one sanctioned exception -
  `payment_status` as the sole changed field on a POSTED invoice -
  tested both ways (payment_status-only save passes, any other field
  change on a posted invoice still raises).
- **Reversal** (`reverse_payment`): voids the payment's allocations
  (kept as VOID rows, ADR-025), recomputes affected invoices, reverses
  the journal, flips the payment. A payment whose cheque is CLEARED or
  BOUNCED cannot be reversed (terminal events with their own journals).
- **Cheque lifecycle** (ADR-026): received cheques sit in
  cheques-in-hand (bank does not move) -> `deposit_cheque` (register
  only) -> `clear_cheque` Dr bank / Cr in-hand, key `cheque-clear:<id>`;
  `bounce_cheque` Dr receivables (party-tagged) / Cr in-hand, key
  `cheque-bounce:<id>`, voids the payment's allocations so invoices fall
  back toward UNPAID; `return_cheque` is the same finance with its own
  status/key. Issued cheques post Cr cheques-payable, clear Dr
  cheques-payable / Cr the payment's bank GL, and an issued bounce
  restores the payable symmetrically. Illegal transitions (clearing a
  bounced or already-cleared cheque) are rejected and tested.
- **Reporting** (`treasury/reporting.py`, all derived): treasury
  balances from GL lines, outstanding cheques by due date, per-invoice
  outstanding (grand total - ACTIVE allocations), open items, party
  statement with allocations.
- **Minimal UI** (read-only, Persian RTL, membership-filtered):
  treasury accounts with derived balances, payments list, cheques list
  with due dates/status, open-items page. Nav links added. No forms.

## Tested - exact evidence (2026-11-02, this machine)

| Command | Result |
|---|---|
| `manage.py makemigrations treasury` | Created `treasury/0001_initial` |
| `manage.py check --settings=config.settings.test` | "System check identified no issues (0 silenced)" |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `manage.py migrate` (local settings, SQLite) | `treasury.0001` applied OK |
| `.venv/bin/python -m pytest` (repo root) | **135 passed, 0 failed** (115 prior + 20 new: treasury 19 + treasury E2E 1) |
| `ruff check backend tests` | "All checks passed!" |
| `ruff format --check backend tests` | "118 files already formatted" |

New tests cover: full allocation -> invoice PAID + AR subledger 0;
partial allocations through PARTIALLY_PAID to PAID; over-allocation to
an invoice and beyond a payment's amount; party mismatch; allocation
on a DRAFT payment; supplier payment -> purchase invoice PAID + AP
subledger 0; unallocated remainder + open-items outstanding; payment
reversal restoring UNPAID/subledger with the allocation kept as VOID;
idempotent re-post; the ADR-024 guard exception both ways; closed-period
rejection leaving the payment DRAFT; cross-company allocation and
treasury-account rejection; bank account requiring a bank name;
received cheque in-hand (bank unmoved) -> deposit -> clear (bank up,
in-hand 0) + double-clear rejected; bounce after full allocation -> AR
restored, invoice back to UNPAID, cheque BOUNCED, clear-after-bounce and
payment-reversal-after-bounce rejected; returned cheque restoring the
receivable; issued cheque Cr cheques-payable (bank unmoved) -> clearing
Dr payable / Cr bank; and the treasury end-to-end test.

### Treasury end-to-end test (`apps/treasury/tests/test_treasury_e2e.py`)

Replays the MVP chain (purchase 1100 AP / sale 1100 AR), pays the
supplier 500 by bank transfer (invoice PARTIALLY_PAID, AP subledger
600), receives the customer's 1100 as a cheque, allocates it in full,
deposits and clears it (invoice PAID, cheque CLEARED), then asserts:
trial balance balanced, AR subledger == AR account == 0, AP subledger
== 600, bank == +600 (-500 + 1100), cheques-in-hand == 0, no
outstanding cheques. This replaces the Sprint 05 manual-journal
payment stub with real treasury records.

## Partially implemented

- UI is read-only; no payment/cheque forms yet.
- `return_cheque` stores its reversal journal in the cheque's
  `bounce_journal_entry` field (it is the cheque's reversal journal;
  the register distinguishes the event by status and journal
  source_type/key, not by a separate FK).
- Cheque deposit has no GL effect by design (register status only);
  banks that require a "cheques under collection" account would need
  a caller-supplied account at deposit - not built.

## Planned / not started

- Bank reconciliation, cheque book inventory, post-dated cheque
  reminders/reporting beyond the outstanding list.
- Sprint 07 (Phase 7/8): multi-warehouse operations at UI level, stock
  counting, returns completion, fiscal closing, opening balances,
  financial statements (balance sheet, income statement).

## Blocked / limitations

- PostgreSQL not run - no server/binaries on this machine; concurrency
  invariants (e.g. two allocations racing one invoice) remain proven on
  SQLite only, inside single transactions with row locks that SQLite
  serializes.
- Type checking (pyright/mypy) still not configured/run.
- Python 3.12.3 on this machine (prompt targets 3.13).
- GitHub push: Sprint 06 core files are pushed file-by-file via the
  connector in one end-of-sprint sync and verified by read-back in the
  coordinator's delivery report; this file does not claim a push
  outcome sight-unseen. The separately tracked Sprint 01 leftover files
  were not touched, so a fresh GitHub clone is still not runnable
  end-to-end; the local tree remains the source of truth.

## Recommended next phase - Sprint 07 (Advanced Inventory & Accounting, Phase 7/8)

Multi-warehouse transfers surfaced properly, stock counting
(InventoryCount) with variance posting, completion of the returns
matrix (reversible returns), fiscal period closing with closing
entries, opening balances, and the first financial statements
(balance sheet, income statement) derived from the trial balance.
