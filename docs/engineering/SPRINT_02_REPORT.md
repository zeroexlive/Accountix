# Sprint 02 Report — Accounting Engine (Phase 2)

Date: 2026-11-02. Base: Sprint 01 local commits `2ff50f5`, `bd683c5`.
Environment: Python 3.12.3, Django 5.2.18, SQLite (local/test). PostgreSQL
concurrency was **not** exercised — no PostgreSQL server was used.

## Implemented (verified by tests)
- Models + migration `accounting/0003`: `JournalEntry` (company, fiscal
  period FK, entry_date, description, status DRAFT/VALIDATED/POSTED/REVERSED,
  source_type/source_id, idempotency_key with partial unique constraint per
  company, `reversal_of` self-FK, posted_by/posted_at), `JournalLine`
  (entry, account PROTECT, Decimal(19,2) debit/credit, CheckConstraints:
  non-negative, one-side-only, non-zero), `JournalReversal` (OneToOne
  original + reversal, reversed_by, reason, reversed_at). ADR-009.
- Services (`apps/accounting/services.py`): `post_journal_entry(...)` and
  `reverse_journal_entry(...)`, both `transaction.atomic`; validation
  before any write; fiscal period resolved from entry date and required
  OPEN; accounts must be postable, active, same company; ≥2 lines; each
  line exactly one side > 0; totals must balance in Decimal.
- Idempotency: same (company, key) re-post returns the existing entry —
  no duplicate entry or lines (tested).
- Immutability: model save/delete guards on POSTED/REVERSED entries and
  their lines; only the POSTED→REVERSED flip by the reversal service passes.
- Audit: `journal.posted` and `journal.reversed` AuditEvents (tested).
- Reporting (`apps/accounting/reporting.py`): `trial_balance`,
  `general_ledger` (running balance), `account_balance` — derived only
  from lines of POSTED/REVERSED entries (ADR-010). No stored balances.
- Minimal UI: journal entry list and trial-balance pages (Persian RTL,
  membership-filtered), nav links added. Read-only; there is no posting
  form yet — posting happens through services (and Django admin/tests).

## Tested — exact evidence (2026-11-02, this machine)
| Command | Result |
|---|---|
| `manage.py makemigrations accounting` | Created `0003_journalentry_journalline_journalreversal_and_more` |
| `manage.py check --settings=config.settings.test` | "System check identified no issues (0 silenced)" |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `.venv/bin/python -m pytest` (repo root / backend) | **42 passed, 0 failed** (25 Sprint 01 + 17 new journal tests in `test_journal.py`) |
| `ruff check backend tests` | "All checks passed!" |
| `ruff format backend` | 3 files reformatted, then checks pass |

New tests cover: balanced posting, unbalanced rejection with full
rollback (0 entries/0 lines persist), <2 lines, both-sides line,
non-postable, inactive, cross-company account, missing fiscal period,
closed fiscal period, idempotency non-duplication, posted-entry/line
mutation + delete rejection, reversal balance/status/audit, double
reversal + reversing-a-reversal rejection, trial balance equality, GL
running balance, per-company reporting isolation, journal list view
isolation, draft reversal rejection.

## Partially implemented
- VALIDATED status exists in the lifecycle but the public service moves
  DRAFT→VALIDATED→POSTED inside one atomic call; there is no separate
  human validation step/UI yet.
- UI is read-only (list + trial balance). No entry creation form.
- `AccountingMapping` deliberately skipped (ADR-011).

## Planned
Balance sheet / income statement / subsidiary ledgers, opening balances,
closing entries, document numbering, PostgreSQL concurrency tests
(duplicate posting race, locking) — required before any production claim.

## Blocked / limitations
- PostgreSQL not run: SQLite locking differs; §6.3 atomicity is proven on
  SQLite only, concurrency invariants remain **untested**.
- Type checking (pyright/mypy) still not configured/run.
- GitHub push: file-by-file via the connector (push_files is blocked by a
  GitHub App 403 on the Git Data API — see SPRINT_01_REPORT / coordinator
  report). Push outcome for this sprint is recorded in the coordinator's
  delivery report, not claimed here sight-unseen.
