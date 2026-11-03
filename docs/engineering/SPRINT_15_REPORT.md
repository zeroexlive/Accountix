# Sprint 15 Report — Cheque Books + Statement Chaining Prefill

Executor: subagent (sole writer). Baseline inherited from Sprint 14:
local HEAD `67cca80`, remote head `acbf6d7` (trees identical),
298 passed + 3 skipped on SQLite, mypy clean (165 files), treasury
at migration 0002. Sprint 15 closes the LAST open Sprint 06
follow-up (cheque books) and the Sprint 14 follow-up (statement
chaining prefill). **This sprint HAS a migration:
`treasury/0003_chequebook_chequeleaf` — run `manage.py migrate`
once after pulling (the standalone launcher migrates
automatically).**

## Implemented

- **Models** (`treasury/models.py`, migration `treasury/0003`):
  `ChequeBook` (company FK; `treasury_account` FK PROTECT;
  optional `label`; `first_number`; `leaf_count`) and `ChequeLeaf`
  (company + treasury_account denormalized per codebase pattern;
  `book` FK CASCADE; `number`; `position`; status
  UNUSED/USED/VOID; `cheque` nullable OneToOne → Cheque, related
  name `leaf`). Constraints: **account-level uniqueness**
  `UniqueConstraint(treasury_account, number)` — the stronger
  choice: overlapping book ranges for one bank account are
  impossible by construction — plus `UniqueConstraint(book,
  position)`. No stored book status: activeness is derived from
  leaf counts (ADR-042).
- **Services** (`treasury/cheque_books.py`):
  `generate_leaf_numbers` (trailing digit run increments,
  zero-padding preserved, may outgrow width; digit-less start
  allowed only for a one-leaf book), `create_cheque_book`
  (validates BANK + active + same company; 1..1000 leaves;
  collision pre-check naming the first colliding number; one
  transaction, `bulk_create`; audit events
  `cheque_book.created` / `cheque_leaf.voided`), `void_leaf`
  (UNUSED → VOID only), `consume_leaf` (row-locked), and the
  annotated count queries `cheque_books_with_counts` /
  `book_counts` (no N+1).
- **Consumption** — found in the code: the Cheque row is created
  inside `create_payment` (at DRAFT creation; `post_payment`
  never creates cheques), so that is where the leaf attaches.
  `create_payment` gains an optional keyword `leaf=None` (all
  existing callers/tests untouched). With a leaf: method must be
  CHEQUE and direction PAYMENT (issued only); leaf must belong to
  the payment's treasury account and be UNUSED; the cheque number
  is taken FROM the leaf and a conflicting entered number is
  rejected; on success the leaf flips to USED and links, in the
  same transaction. Lifecycle (ADR-042): bounce of an issued
  cheque and payment reversal deliberately do NOT resurrect the
  leaf — the physical paper was handed out. The codebase has no
  payment draft-discard flow, so there is no release path.
- **UI** (design system v2, Persian/RTL): sidebar gains
  «دفترچه‌های چک» (placed in خزانه‌داری, labelled for issued
  cheques; list and create pages state explicitly that received
  cheques are other parties' paper and have no book). Book list
  with per-account filter and derived counts; create form
  (BANK accounts only, first number, leaf count); detail page
  showing the full generated range (first → last leaf), remaining
  counts, a leaves table (status pill, linked cheque/payment when
  USED, void button with confirm on UNUSED). Payment form: an
  optional leaf picker grouped by book appears only when the
  company has UNUSED leaves; otherwise the form is exactly as
  before. Cheque detail shows the leaf/book when linked.
- **Statement chaining prefill** (Part 2):
  `reconciliation.suggested_statement_opening(account)` returns
  `(latest.end_date, latest.closing_balance)` from the account's
  latest COMPLETED statement (OPEN statements ignored) or `None`.
  `bank_statement_create` accepts `?account=<id>`: on GET it
  preselects the account and prefills start date + opening
  balance as form initials — a prefill, always editable; the
  statement list links «صورت‌حساب جدید برای این حساب» when an
  account filter is active.
- **Docs**: ADR-042; this report; CURRENT_STATE (Sprint 15
  update, §9 count 318, §10 — cheque books struck from
  candidates; **Sprint 06 follow-ups now ALL closed**); README
  (318 tests, Sprint 15 note, migration note).

## Tested

- New tests: **+20** — `treasury/tests/test_cheque_books.py` (16:
  25-leaf range 1001..1025 with remaining 25; zero-padding
  "0042"→"0044" and prefix "SH-099"→"SH-100"; overlapping book
  rejected naming "1010" with nothing created; non-BANK account,
  count 0 and 1001 rejected; digit-less start rules; consumption
  → leaf USED + OneToOne + cheque number == leaf number;
  matching entered number accepted, conflicting rejected with
  leaf still UNUSED; leaf reuse rejected, second cheque not
  created; leaf of another account rejected; leaf on RECEIPT and
  on CASH method rejected; no-leaf cheque path unchanged; void
  rules; **bounce keeps leaf USED; payment reversal keeps leaf
  USED**; mixed counts 25 − 3 used − 1 void = 21 remaining, also
  through the annotated queryset; chaining: None with no
  completed statement, OPEN ignored, latest completed chosen) and
  `treasury/tests/test_cheque_books_ui.py` (4: create → detail
  range + void via UI; payment-with-leaf via UI consumes it and
  the cheque detail names the book; non-member 404 on
  detail/void, no creation, no consumption; statement prefill via
  `?account=` with and without a completed statement).
- Full suite: **318 passed, 3 skipped** on SQLite (baseline 298 +
  3; +20 new, zero regressions — the existing treasury suite,
  including all no-leaf cheque flows, passes unchanged).
- `manage.py check --settings=config.settings.test` — no issues.
- `makemigrations --check --dry-run` — no changes detected
  (`treasury/0003_chequebook_chequeleaf` generated and included).
- mypy: `Success: no issues found in 168 source files`
  (was 165; +cheque_books.py and the two new test modules).
- ruff check: all checks passed; ruff format --check: 168 files
  already formatted.

## Partially implemented

- None. The leaf-picker hint of "the generated range end" is
  server-computed and confirmed on the book detail page (per the
  brief's allowance); there is no live JS preview, consistent
  with the no-JS server-side convention (ADR-039).

## Planned / not done (by design)

- Received-cheque "books" — out of scope by definition (other
  parties' paper).
- Leaf release on draft discard — no such flow exists for
  payments; consumption at creation is final (ADR-042).
- Statement import remains CSV-only; CAMT/OFX stays a future
  candidate.

## Blocked

- Nothing in scope. Standing items unchanged: PostgreSQL restore
  drill not verified (ops procedure), Windows bundle not verified
  (no Windows machine), no login rate limiting (blocks
  internet-facing deployment only).

## GitHub sync

- One commit via the connector's dedicated `github push-files`
  subcommand — message "Sprint 15: cheque books + statement
  chaining prefill" — with blob-SHA read-back verification
  (details in the executor's handoff; sync outcome recorded
  there, not pre-claimed here).

## Handoff notes for Jason

1. **Migration**: after `git pull`, run `manage.py migrate` once
   (`treasury/0003`). The standalone launcher does this
   automatically.
2. Existing books/data: none needed — cheque books are opt-in;
   payments without a leaf behave exactly as before.
3. **Sprint 06 follow-ups are now fully closed**: bank
   reconciliation (Sprint 14) + cheque books (Sprint 15).
   Suggested Sprint 16 candidates: login rate limiting (the last
   release-gate gap for internet-facing deployment), the PG
   restore drill, .po translations, or CAMT/OFX statement import.
