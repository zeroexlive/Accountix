# Accounting Rules

These rules govern the engine. **Status:** chart of accounts (Sprint 01)
and the journal engine (Sprint 02) are implemented and tested as described
below. Financial statements beyond trial balance / general ledger are
still planned.

## Implemented in Sprint 01 (tested)
- Account codes are unique **per company** (DB constraint + tests).
- An account cannot be its own parent; parent must belong to the same
  company; hierarchy cycles are rejected (service validation + tests).
- Accounts have a type (Asset/Liability/Equity/Revenue/Expense), a normal
  balance (Debit/Credit), `is_postable` (default False) and `is_active`.

## Journal engine — implemented in Sprint 02 (`apps/accounting/services.py`)
- `post_journal_entry(company, entry_date, lines, ...)` resolves the fiscal
  period from the date, requires it OPEN, validates every line/account,
  checks balance, then creates + posts atomically. Rejection persists
  nothing (tested rollback).
- `reverse_journal_entry(entry, ...)` creates a NEW posted entry with
  debit/credit swapped, links it via `reversal_of` + a `JournalReversal`
  record, and flips the original to REVERSED. Double reversal and
  reversing a reversal are rejected. AuditEvents are written for both
  operations (`journal.posted`, `journal.reversed`).
- Idempotency: `(company, idempotency_key)` is unique (partial DB
  constraint, null keys exempt); re-posting with the same key returns the
  existing entry without duplicating.
- Immutability: model `save`/`delete` guards reject changes to POSTED /
  REVERSED entries and their lines — the single allowed mutation is the
  POSTED → REVERSED status flip performed by the reversal service.
- Reporting (`apps/accounting/reporting.py`): trial balance, general
  ledger and account balance are derived only from journal lines of
  POSTED/REVERSED entries (ADR-010). There are no stored balance fields.

## Required invariants (the checklist the implementation enforces)
1. Every posted entry is balanced: total debit == total credit, in Decimal.
2. Posted entries have ≥ 2 lines and only postable, active accounts.
3. No postings into closed fiscal periods without authorization.
4. Posted entries are immutable; correction is by reversal referencing the
   original entry. History is never rewritten.
5. Lifecycle: DRAFT → VALIDATED → POSTED → REVERSED.
6. Posting is atomic and idempotent: a duplicate posting request must not
   create duplicate records.
7. No cross-company references: entry, lines, accounts and period must all
   belong to one company; client-supplied company ids are never trusted.
8. Reports (journal, GL, trial balance, balance sheet, income statement,
   AR/AP) are derived from journal lines — never from hand-maintained
   balance fields.
9. Money is `Decimal` / `DecimalField` only. Floats are forbidden.
10. Currency: ISO 4217, company default IRR; toman is display-only
    (10 rials = 1 toman) with explicit rounding at presentation.

## Fiscal closing — implemented in Sprint 07 (ADR-028)
1. `close_fiscal_period` computes each revenue/expense-type account's
   balance **for that period** from posted lines and posts ONE closing
   journal entry (`source_type='CLOSING'`, key `closing:<period id>`,
   dated the period's last day) zeroing them into a caller-supplied
   postable retained-earnings account: a net income appears as a credit
   to retained earnings, a net loss as a debit.
2. The period flips to `CLOSED` only **after** the closing entry posts;
   afterwards the posting gate rejects any new entry dated in it.
   Closing an already-closed period is rejected.
3. A period with no revenue/expense activity closes with **no entry**
   (documented choice, tested).
4. `reopen_fiscal_period` never deletes: it flips the period to `OPEN`
   and reverses the closing entry in the same transaction. Re-closing
   afterwards posts a fresh closing entry (key `closing:<id>:<n>`).
5. `close_fiscal_year` closes every still-open period in start-date
   order via the same service, then flips the year status to `CLOSED`.

## Opening balances — implemented in Sprint 07 (ADR-029)
1. `post_opening_balance(company, fiscal_year, lines, offset_account)`
   posts ONE journal entry (`source_type='opening_balance'`, key
   `opening-balance:<fiscal year id>`) dated the fiscal year's **first**
   period start; that period must be `OPEN`.
2. The service balances the entry itself: excess debits are credited
   (excess credits debited) to the caller-supplied offset account
   (retained earnings / opening-balance equity), so the posted entry is
   balanced by construction. Input lines are one-sided, postable,
   active, same-company; party tagging opens AP/AR balances.
3. Idempotent per fiscal year: re-posting returns the existing entry.
4. Opening **stock** is separate — see INVENTORY_RULES §11 (a receipt
   with source reference `opening_stock`, not a model).

## Financial statements — implemented in Sprint 07 (ADR-030)
1. Income statement (`reporting.income_statement`): revenue accounts
   presented credit-positive, expense accounts debit-positive. COGS is
   the caller-designated subset of expense accounts (`cogs_accounts=`;
   the type taxonomy has no COGS class and codes/names are never
   guessed). Gross profit = revenue − COGS; net income = gross profit −
   other expenses. **Closing entries are excluded**, so a closed period
   still reports its real operating result.
2. Balance sheet (`reporting.balance_sheet`, as of a date / period
   end): assets debit-positive; liabilities and equity credit-positive.
   Equity includes a computed **current period result** line — the net
   of all revenue/expense balances with closing entries **included** —
   so Assets == Liabilities + Equity + Result at any date: before
   closing the result is the open profit; after closing the income
   accounts net to zero, the result line is 0, and the profit sits in
   retained earnings. `is_balanced` reports the identity check.
