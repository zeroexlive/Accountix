# Accounting Rules

These rules govern the engine. **Sprint 01 status:** only the chart of
accounts exists; journal rules below are requirements for Sprint 02+, not
implemented behavior.

## Implemented in Sprint 01 (tested)
- Account codes are unique **per company** (DB constraint + tests).
- An account cannot be its own parent; parent must belong to the same
  company; hierarchy cycles are rejected (service validation + tests).
- Accounts have a type (Asset/Liability/Equity/Revenue/Expense), a normal
  balance (Debit/Credit), `is_postable` (default False) and `is_active`.

## Required invariants for the journal engine (Planned, Sprint 02)
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
