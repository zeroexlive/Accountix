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
