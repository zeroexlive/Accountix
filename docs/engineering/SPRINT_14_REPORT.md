# Sprint 14 Report — Bank Reconciliation + Stock Document Forms

Sprint goal: close the largest unbuilt treasury feature — bank
reconciliation (standing limitation since Sprint 06) — and give the
Sprint 03 stock-document services a UI, so opening stock (the Sprint
07 recipe) finally has the form the Sprint 13 opening-balance page
could only describe in guidance text.
Outcome: **both parts implemented and tested**. Suite: **298 passed
+ 3 skipped** on SQLite (baseline 283 + 3; **+15 new tests**), mypy
clean (165 files), `ruff check` + `ruff format --check` clean,
`manage.py check` clean. **This sprint HAS a migration**
(`treasury/0002_bankstatement_bankstatementline`) — run
`manage.py migrate` once after pulling.

## Implemented

- **1. Bank reconciliation** (treasury app, ADR-041) — reconciliation
  is defined at the GL level: a *book movement* for a BANK treasury
  account is a posted-ledger journal line on its linked GL account
  (entries POSTED/REVERSED — the `accounting.reporting` ledger set).
  Verified from the code, the flows that create such lines are:
  payments posted with method CASH/BANK_TRANSFER on the bank account;
  received-cheque **clearing** (Dr the destination bank GL, key
  `cheque-clear:<id>`); issued-cheque **clearing** (Cr the drawn bank
  GL); reversals of any of these; and manual journals posted straight
  to the bank GL — the route by which bank-only items (fees) enter
  the books. Flows that create **no** bank-GL line and are therefore
  correctly invisible to reconciliation: cheque *posting* (value sits
  in the cheques-in-hand / cheques-payable holding account), cheque
  deposit (register-only), bounce/return (holding + counterparty
  only). No postings were invented to change this.
  - Models: `BankStatement` (company, BANK treasury account,
    start/end dates, opening/closing balances *as stated by the
    bank*, source note, OPEN/COMPLETED) and `BankStatementLine`
    (signed amount from the bank's perspective; `matched_journal_line`
    is a **OneToOne** to `accounting.JournalLine`, so the database
    guarantees a book movement is claimed at most once across all
    statements; matched_at/by audit fields; check constraint
    amount ≠ 0). Migration `treasury/0002` (depends on
    accounting 0004, organizations 0002, treasury 0001).
  - Services (`apps/treasury/reconciliation.py`, new module):
    `create_statement` (BANK kind + same company + active + date
    order validated); `add_statement_line` and
    `import_statement_lines` — manual entry plus a documented CSV
    contract (header `date,description,reference,amount` signed, or
    a `debit`+`credit` pair with amount = credit − debit; ISO dates;
    line dates inside the statement period). Valid rows import in
    one transaction; rejected rows are reported with physical file
    line numbers and reasons. Duplicate guard: an identical
    (date, amount, reference) triple within one statement is rejected
    on import and on manual add. `match_line` / `unmatch_line`
    (link-only — matching never mutates the journal, payment or
    cheque; validation covers OPEN statement, same GL account and
    company, ledger status, not-already-matched, exact signed-amount
    equality). `auto_match`: a line is linked only when **exactly
    one** unmatched book movement has the equal signed amount within
    ±7 days; ambiguity is left to the user.
    `reconciliation_summary` (derived only): book balance from
    `accounting.reporting.account_balance` as of the end date,
    matched totals, unmatched statement lines + net, outstanding
    book movements + net, and
    **difference = book_balance − (statement_closing − unmatched_statement_net)**.
    Under the chaining discipline (stated opening = book balance at
    period start), difference ≡ outstanding_book_net — derived with
    a worked example in ADR-041 and pinned in tests.
    `complete_statement` requires difference == 0 **and** zero
    unmatched statement lines (an unmatched line is a bank movement
    the books lack; closing over it would freeze it unrecorded);
    COMPLETED locks all changes until `reopen_statement`. Audit
    events for create/line/import/match/unmatch/auto-match/
    complete/reopen.
  - UI (treasury sidebar: تطبیق بانکی): statement list (filterable
    by bank account) + create form (BANK-only account picker);
    detail page with the summary card (book balance, stated closing,
    matched count/total, unmatched-statement net, outstanding net,
    DIFFERENCE — green pill at 0), statement-lines panel (matched
    badge → link to the journal entry, unmatch button), unmatched
    book-movements panel with a per-row match control, auto-match /
    complete / reopen POST actions, manual line form and CSV import
    form. Dates display Jalali (ADR-040); inputs stay Gregorian and
    are labelled. All views membership-scoped; another company's
    statement is a 404 on every route.
- **2. Stock document forms** (inventory app) — sidebar اسناد انبار:
  list, create form, detail page. The create form offers the
  service's document types (receipt / issue / transfer / adjustment)
  plus a purpose picker: «موجودی اول دوره» forces a receipt with
  `source_type="opening_stock"` (the Sprint 07 recipe — no separate
  ADR needed, the mapping is presentational). Warehouse +
  destination warehouse (transfers), date, description, and a
  server-side line formset (product / unit / quantity / unit cost —
  cost asked for receipts; issues and transfers are MWAC-costed by
  the service). The detail page posts with the ADR-013 GL opt-in
  (inventory + offset account pickers, both-or-neither; only
  receipts/issues book a journal) and reverses through
  `reverse_stock_document`. No new services: create → draft → post
  all go through `apps.inventory.services` (ADR-039). The Sprint 13
  opening-balance page's opening-stock guidance now links to this
  form instead of only to the stock balances page.

## Tested

- **Reconciliation identity scenario** (`treasury/tests/test_reconciliation.py`,
  7 tests): book = receipt +1100 (Jun 1) + cleared cheque +1100
  (Jun 1) − payment 300 (Jun 2) = **1900**; statement closing stated
  **1850** with lines +1100/+1100/−300/fee −50. Auto-match takes only
  the −300 (both +1100 lines are ambiguous: two candidates in the
  window) — matched 1, remaining 3. Summary: U = 2150, O = 2200,
  **difference = 2200 = outstanding_book_net** (identity asserted,
  plus the raw form book − S = O − U). Manual match of the two
  +1100 lines → difference 0 but completion still refused (fee line
  unmatched); matching the fee is impossible before it is booked
  (no −50 book movement; amount-mismatch rejection asserted). Fee
  booked via `post_journal_entry` (Dr expense 50 / Cr bank 50) →
  difference −50 = O; matched → difference 0, complete succeeds.
  Unmatch on COMPLETED refused until reopen; double-match of one
  journal line rejected both directions. Also: cheque posting alone
  leaves the bank GL untouched (balance 800 before clearing, 1900
  after); CSV with bad rows (rows 3, 5, 6 rejected by file line
  number; 2 valid rows imported); debit/credit-pair CSV; duplicate
  rejected on import and on manual add; create validation
  (cash account / other company / reversed dates).
- **Reconciliation UI** (`test_reconciliation_ui.py`, 3 tests):
  create via form → CSV upload (4 lines) → auto-match (only TR-2) →
  detail shows difference 2200 → complete refused, statement stays
  OPEN; manual line add renders in the match panel; another
  company's statement is 404 on detail, auto-match, complete,
  add-line and create.
- **Stock documents UI** (`inventory/tests/test_stock_document_ui.py`,
  5 tests): receipt 10 @ 100 posted **with** GL → stock 10/1000,
  journal Dr inventory 1000; issue 4 without GL → 6/600, no journal;
  transfer 3 → WH1 3/300, WH2 3/300, total value preserved 600;
  transfer reversal restores WH1 6 and empties WH2; receipt without
  GL → no journal (5 @ 50 = 250); opening-stock purpose stamps
  `source_type="opening_stock"`; oversell issue 7 > 6 → service error
  on the page, document stays DRAFT, stock unchanged at 6;
  non-member 404 on detail/post/reverse.
- Gates (repo root):
  `.venv/bin/python -m pytest` → **298 passed, 3 skipped**;
  `.venv/bin/python backend/manage.py check --settings=config.settings.test` → clean;
  `makemigrations --check --dry-run` → "No changes detected";
  `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` → clean (165 files);
  `.venv/bin/python -m ruff check backend` → clean;
  `.venv/bin/python -m ruff format --check backend` → clean.

## Partially implemented

- None within the sprint scope. Statement import is CSV-only (bank
  export formats such as CAMT/OFX are not parsed); auto-match is
  amount+window only (no reference/fuzzy matching — by design,
  ambiguity belongs to the user).

## Planned / not in this sprint

- Cheque books (cheque inventory / leaf tracking) — the remaining
  Sprint 06 follow-up; still open.
- A second-statement chaining helper (prefilling the next
  statement's opening from the last completed statement) — the
  identity assumes the discipline; the UI does not yet prefill it.

## Blocked

- Nothing in this sprint. Standing items unchanged: Windows bundle
  and PostgreSQL restore NOT VERIFIED; no login rate limiting;
  `.github/workflows/ci.yml` + 5 zero-byte `.gitkeep` files remain
  unsyncable via the connector (cosmetic; the app runs without them).

## Migration note for Jason

Sprint 14 adds `treasury/0002_bankstatement_bankstatementline`.
After `git pull`, run `manage.py migrate` once (the standalone
launcher migrates automatically). No data migration; the two new
tables start empty.
