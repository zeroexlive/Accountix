# Sprint 18 Report — CAMT.053 + OFX Bank-Statement Import

Date: 2026-11-03. Environment: Linux, Python 3.12.3 (project venv),
Django 5.2. Base: Sprint 17 complete (327 tests). Goal: extend
Sprint 14's CSV-only statement import to the two standard bank
formats — CAMT.053 (ISO 20022) and OFX — through ONE generalized
pipeline, and give the file's own header (balances, period) a
create-from-file flow with the totals identity enforced at save.
Full rationale: **ADR-044**. Outcome: **implemented and tested**.
Suite: **346 passed + 3 skipped** on SQLite (baseline 327 + 3;
**+19 new tests**), mypy clean (173 files), `ruff check` +
`ruff format --check` clean, `manage.py check` clean,
`makemigrations --check` → "No changes detected" (**no migration,
no model changes, no new dependency**).

## Implemented

- **Parser pipeline** (new module `apps/treasury/statement_files.py`).
  Every parser yields the normalized shape the Sprint 14 CSV
  importer embodied: raw row dicts in the CSV contract shape
  (`date`/`description`/`reference`/`amount` strings, amount signed
  from the bank's perspective) in file order, each tagged with a
  **locator** — CSV: physical line number; XML formats: 1-based
  transaction index — plus parser-level rejections in the same
  locator space (same reason strings as the CSV validator) and
  optional header metadata (opening/closing balances, period).
  `reconciliation._import_validated_rows` is the single downstream:
  raw parse → shared validation (zero amount, period bounds, field
  lengths, duplicate (date, amount, reference) triple) → import in
  one transaction with per-row reporting. `import_statement_lines`
  (CSV) keeps its signature and byte-identical behaviour — its
  header validation moved into `statement_files.parse_csv_text`
  with unchanged messages; **the Sprint 14 test modules are
  untouched and green**. New service entry points:
  `import_statement_file(statement, content=...)` (any format;
  report adds `format` + `metadata`) and
  `create_statement_from_upload(...)` (below).
- **Format detection by content sniffing** (extension never
  consulted): `OFXHEADER` / `<OFX` markers → OFX; XML root
  `Document` with a camt.053 namespace or a `BkToCstmrStmt`
  element → CAMT.053; anything else falls through to CSV, whose
  header validation is the clean file-level refusal for garbage.
  Undecodable bytes raise `UndecodableStatementFile`; the views
  keep rendering the exact Persian UTF-8 message Sprint 14 had.
- **CAMT.053 parser** (stdlib ElementTree, namespace-agnostic
  local-name matching — camt.053.001.02/.08 and namespace-free
  files all parse). One file = one `<Stmt>` (several → file-level
  refusal naming the count). OPBD/CLBD balances signed by
  `CdtDbtInd`; period from `<FrToDt>` else min/max entry dates.
  Entry mapping: `<Amt>` signed by `<CdtDbtInd>`; `<BookgDt>`
  (`<Dt>` or `<DtTm>` date part); reference = entry `AcctSvcrRef`
  → first TxDtls `Refs/AcctSvcrRef` → `Refs/EndToEndId`
  (`NOTPROVIDED` treated as no reference); description =
  `RmtInf/Ustrd` joined → `AddtlNtryInf` → BkTxCd domain codes.
  Broken amount/date → per-transaction rejection, rest imports.
- **OFX parser — hand-written; `ofxparse` rejected with evidence**
  (see Partially/Blocked notes below). A tolerant subset parser
  (regex/block based; works unchanged on 1.x SGML and 2.x XML):
  `TRNAMT` signed as-is, `DTPOSTED` → the calendar date **as
  written** (time and `[offset:tz]` suffix ignored for the date),
  `FITID` → reference, `NAME`/`MEMO` → description
  (`NAME — MEMO`); header: `LEDGERBAL/BALAMT` → closing,
  `DTSTART`/`DTEND` → period, `DTASOF` as period-end fallback.
  OFX has no opening balance — chaining/user supplies it, as with
  CSV. OFX 1.x bodies that are not UTF-8 fall back to latin-1
  decoding (CHARSET:1252 reality).
- **Create-from-file flow** (statement create page): an upload
  card parses the file, stashes the rows in the session, and
  re-renders the create form with header initials composed as
  chaining suggestion first, file metadata overlaid where present
  (file wins; OFX's missing opening leaves the chaining value),
  user edits last — all editable. Confirming calls
  `create_statement_from_upload`: statement creation + row import
  in ONE transaction, enforcing **opening + Σ imported lines ==
  closing** at save; a disagreement rolls everything back and the
  refusal names the three figures while the form keeps the file's
  numbers visible. The file preview (name, format, row count,
  file balances, per-transaction rejections) stays on the page
  after a refusal so the figures can be corrected.
- **Detail-page import generalized**: the same upload now accepts
  all three formats (lines only; an existing header is never
  rewritten by a file). Accepted-row rendering is unchanged for
  CSV («ردیف N»); XML-format rejections render with their
  transaction index («تراکنش N»). Import form: `accept`
  attribute `.csv,.ofx,.qfx,.xml` and Persian help text listing
  the three formats and the one-file-one-statement rule; the
  detail template heading now reads «بارگذاری از فایل صورت‌حساب».

## Tested (exact evidence)

New fixtures `treasury/tests/_statement_files.py` (hand-crafted,
minimal-but-valid; balances add up where the create flow is used)
and 19 new tests in `test_statement_files.py` (12) +
`test_statement_import_ui.py` (7):

- **CAMT golden**: OPBD/CLBD metadata; 3 entries — CRDT with
  entry `AcctSvcrRef` + `Ustrd`, DBIT with only `AddtlNtryInf`
  (reference via TxDtls `Refs/AcctSvcrRef`) — asserted exactly
  (date, Decimal amount string, reference, description); the
  third entry's broken amount is rejected at **index 3**
  ("Unparseable amount 'not-a-number'.") while the other two
  parse; period falls back to entry dates. CAMT_CLEAN asserts
  `FrToDt` period and the `EndToEndId` reference fallback; a
  namespace-free CAMT parses identically; a two-`<Stmt>` file is
  refused ("2 statements").
- **OFX golden**: 1.x SGML fixture — 3 STMTTRN incl. a −50.25 fee,
  FITIDs as references, `LEDGERBAL` closing 1749.75, DTSTART/DTEND
  period, opening `None`; `DTPOSTED 20260601103000[3:IRST]` yields
  **2026-06-01** (date as written — the assertion that kills the
  ofxparse option). 2.x XML fixture — 2 transactions asserted
  exactly. A broken `TRNAMT` rejects only transaction 2; 1 and 3
  still parse.
- **Garbage**: an HTML page → the CSV-class refusal
  ("The CSV needs a 'date' column."); PNG bytes →
  `UndecodableStatementFile`.
- **Service E2E**: CAMT_BROKEN into an existing statement →
  imported 2, rejected [3], exact DB lines; OFX re-import → all 3
  rows rejected as duplicates (FITID references), nothing
  double-imported. `create_statement_from_upload`: CAMT_CLEAN
  creates statement + 2 lines with the file header; **tampered
  closing (901) → ValidationError "totals do not agree" and zero
  statements persist** (atomic rollback asserted); OFX with a
  user-supplied opening (1000) + LEDGERBAL closing creates 3 lines.
- **UI E2E**: CAMT preview → form initials are exactly the file's
  period/opening/closing and `file_preview` context is correct →
  confirm creates the statement with 2 lines (Σ = 800);
  OFX preview prefills closing + period but leaves opening empty
  (no chaining source) → confirm with opening 1000 creates 3
  lines; tampered closing through the UI → 200 with the refusal
  on the page, no statement, preview retained; detail-page OFX
  import → 3 lines with FITID references, re-import renders
  «تراکنش 1» duplicate messages and imports nothing; detail-page
  CAMT import renders «تراکنش 3: Unparseable amount …» and imports
  the other 2; a non-member's import POST is a 404.
- **Regression**: the full suite — 346 passed, 3 skipped — with
  Sprint 14's `test_reconciliation.py` / `test_reconciliation_ui.py`
  and Sprint 15's chaining-prefill test **unmodified**.

Commands (repo root, 2026-11-03):

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **346 passed, 3 skipped** |
| `manage.py check --settings=config.settings.test` | "System check identified no issues" |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` | "Success: no issues found in 173 source files" |
| `ruff check backend` / `ruff format --check backend` | clean / 173 files formatted |

## Partially implemented / accepted

- **`ofxparse` was evaluated and rejected** (ADR-044 point 4):
  installed 0.21 in the venv and run against the crafted fixtures
  — it parses both OFX generations and returns `Decimal`s, but
  (a) it converts `DTPOSTED` to UTC (`20260601103000[3:IRST]` →
  07:30 UTC), which can shift the calendar date across midnight,
  violating the date-as-written rule; (b) one bad `TRNAMT` or
  `DTPOSTED` raises `OfxParserException` and aborts the whole
  file, violating per-transaction error reporting. The package
  (and its BeautifulSoup4/lxml deps) was uninstalled again;
  `pyproject.toml` is unchanged — no new dependency, no mypy
  baseline entry needed.
- Multi-statement CAMT files are **refused** (one file = one
  statement), by design and with a clear message.

## Planned / not started

- OFX credit-card (`CCSTMTRS`) and investment statements — out of
  scope (reconciliation is bank-account only).
- CAMT.052 (intraday) — same shape as .053 in the entry/balance
  elements; not parsed until a real bank file demands it.
- Standing items unchanged: Windows bundle NOT VERIFIED (the only
  remaining release-gate item); PyInstaller bundle rebuild still
  pending (stale since Sprint 11).

## Blocked

- Nothing.

## GitHub sync

- One commit via the connector's dedicated `github push-files`
  subcommand — message "Sprint 18: CAMT.053 and OFX statement
  import" — with blob-SHA read-back verification (details in the
  executor's handoff; sync outcome recorded there, not
  pre-claimed here).

## Handoff notes for Jason

- **Nothing to run after pulling**: no migration, no new
  dependency, no settings change. Statement files from the bank
  (CSV / CAMT.053 / OFX / QFX) can be uploaded either on the
  statement-create page (header + lines in one go, totals must
  agree) or into an existing statement from its detail page
  (lines only), exactly where the CSV upload already lived.
