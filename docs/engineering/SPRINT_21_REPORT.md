# Sprint 21 Report — Persian Translations for English-Source Vocabulary (ADR-047)

Date: 2026-11-03. Base: Sprint 20 complete (363 tests, catalogs at
1032 msgids, en 1032/1032, fa msgstrs all empty). This sprint
executes the product decision recorded in ADR-047 (Jason,
2026-11-03): the default Persian UI's service error messages and
status/choice labels — English-source strings that have rendered
in English since Sprint 01 — are translated into Persian in
`fa.po`. **No source-code string changes; `en.po` is
byte-untouched; `makemessages` was not re-run** (nothing new to
extract).

## Implemented

- **Translation set, identified programmatically**: msgids in
  `backend/locale/fa/LC_MESSAGES/django.po` containing no
  Arabic-script characters → **339 of 1032 msgids**. Cross-check
  by catalog reference: models 75, service modules 261, templates
  2, views 2, accounting/reporting 1 (the counts sum to 341
  because two msgids are each referenced from two categories). The
  set covers all service `ValidationError` texts, all model
  choice labels (account types, normal balance, document /
  invoice / payment / cheque / leaf / statement statuses,
  membership roles, treasury kinds/directions/methods) and three
  English format patterns (`%(noun)s %(row)s: %(reason)s` etc.,
  whose structure carries over unchanged). The other 693
  Persian-source msgids keep empty fa msgstrs by ADR-045 design
  (fallback = the Persian msgid itself).
- **Translations**: formal written Persian in the existing UI
  register, terminology anchored on the Persian glossary already
  in the product — سند حسابداری (journal entry), دفتر روزنامه
  (journal), دوره مالی / سال مالی (fiscal period/year), حساب دفتر
  کل (GL account), قابل ثبت (postable — the UI's own word), قابل
  انبارش (stockable — likewise), حقوق صاحبان سرمایه (equity),
  سود (زیان) انباشته (retained earnings), سند انبار, انبارگردانی,
  دفترچه چک / برگ, ردیف صورت‌حساب, گردش دفتری (book movement),
  پیش‌فاکتور (quotation). One English concept → one Persian term
  across all strings (e.g. every "belongs to a different company"
  is «متعلق به شرکت دیگری است», every DRAFT/POSTED status word is
  پیش‌نویس/ثبت‌شده). Status labels kept short for pills (باز,
  بسته, فعال, پرداخت‌شده, وصول‌شده, برگشتی…). Error messages are
  complete sentences carrying exactly the source information.
  Filled positionally by script (msgids decoded from the file
  itself — ZWNJ-safe) and hand-reviewed in full. The fa.po header
  comment was rewritten: it previously (and now wrongly) said
  "do not translate this file"; it now documents the two
  source-language classes and the compile requirement.
- **Placeholder inventory**: all placeholders in the 339 are
  named (`%(name)s`, incl. `%(name)r` repr forms) — 45 distinct
  names; **zero positional, zero brace placeholders**. Verified
  mechanically: every translation's placeholder multiset equals
  its msgid's. **Plurals: the catalog contains no plural msgids**,
  so no plural forms were needed; the fa header's
  `Plural-Forms: nplurals=2; plural=(n > 1)` deviates from the
  Persian CLDR rule (`nplurals=1; plural=0`) — flagged in
  ADR-047, inert until a pluralized string exists.
- **Test-suite compile infrastructure (root `conftest.py`, new)**:
  a session-scoped autouse fixture runs `compilemessages` once per
  test session, then clears Django's per-process translation
  caches (`trans_real._translations`, `_default`). The cache clear
  is load-bearing, not defensive: on a fresh clone, whatever
  resolves the default language before the fixture runs caches a
  catalog *without* the project strings, and the suite then
  "passes" with the Persian translations silently inactive
  (English-source assertions match the English fallback). With
  the clear, the full failure class below surfaced — and was
  migrated. The Sprint 19/20 module fixtures stay as they were.
- **Assertion migration**: 23 tests failed, all in the single
  expected class ("assertion expected the English string; the UI
  now renders its fa.po translation"). **29 assertion sites**
  across 7 files were swapped to the exact Persian strings from
  fa.po — pure expectation swaps, same strength, no deletions:
  `sales/tests/test_sales.py` (8), `treasury/tests/
  test_cheque_books.py` (9), `treasury/tests/
  test_statement_files.py` (7), `treasury/tests/
  test_statement_import_ui.py` (2),
  `accounting/tests/test_opening_balance_ui.py` (1),
  `inventory/tests/test_count_ui.py` (1), `inventory/tests/
  test_stock_document_ui.py` (1). Note: several
  `pytest.raises(match=…)` patterns use ZWNJ-free fragments of
  the same messages — `str(ValidationError)` is the *repr* of the
  message list and Python's repr escapes U+200C as the literal
  `\u200c`, so a pattern containing a real ZWNJ can never match
  (see ADR-047). Page-content assertions keep full ZWNJ text.
- **One pinning test added** (`core/tests/test_i18n.py`):
  a service error msgid with placeholders and a model choice
  label render in Persian under `fa` and in English under `en`.
- **Docs**: ADR-047; this report; CURRENT_STATE §2/§9 updates;
  README + DEVELOPMENT wording — `compilemessages` after checkout
  is now required for **both** languages (without it, fa falls
  back to the English source strings for the 339 entries: the
  pre-Sprint-21 behaviour, graceful, no breakage; the launcher
  and bundle builds already compile automatically).

## Tested (exact evidence)

| Command | Result |
|---|---|
| `rm` every `*.mo` under `backend/`, then `.venv/bin/python -m pytest` (junit-verified) | **364 passed, 3 skipped, 0 failures** (363 baseline + 1 new pinning test) — fresh-clone proof: the root fixture compiles the catalogs itself |
| `msgfmt --check --statistics` on fa.po | clean; 339 translated, 693 untranslated (the Persian-source set, by design) |
| `msgfmt --check --statistics` on en.po | clean; 1032 translated — and `git diff` shows en.po **byte-untouched** |
| Round-trip re-parse of the new fa.po | all 339 msgstrs decode to exactly the intended translations; all 693 others still empty; `git diff` touches **zero msgid lines** |
| `manage.py check` under test/local/production/standalone/postgres_test | no issues, all five |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` | Success, 175 source files |
| `ruff check backend conftest.py` / `ruff format --check backend conftest.py` | clean / 176 files formatted |
| Leftover-English census (scripted) | see below |

Census detail: scanning the whole test tree for fragments (≥14
chars) of all 339 English msgids leaves exactly **3 hits**, all
intentional: the new pinning test's fa/en pair and the Sprint 20
crawl's English-mode assertion. A complementary short-phrase scan
finds no assertion hits at all; the only remaining English
`match=` patterns in migrated areas are `match="1000"` (the
interpolated max-leaves value) and `match="USED"` (the
interpolated raw status **code** inside the message) — data/code
assertions, correctly unchanged. Stored-data strings (journal /
audit descriptions) were never in the catalog and are untouched.

Environment note: this dev machine had no gettext tools at sprint
start (they did not persist from Sprint 19's install); GNU gettext
0.21 was reinstalled via the scoped-apt route documented in
DEVELOPMENT.md (main-only source list, `Acquire::Languages=none`).

## Partially implemented / accepted

- **fa Plural-Forms header** still says `nplurals=2;
  plural=(n > 1)` (a makemessages default) instead of the
  Persian CLDR `nplurals=1; plural=0` — flagged in ADR-047;
  inert today (no plural msgids in either catalog).
- Interpolated **data values stay as stored** inside the now-
  Persian messages (status codes like USED/VOID, SKUs, account
  codes, the English `label` nouns in the purchases/sales model
  guards) — data, not UI vocabulary, per ADR-045's rule.

## Planned / not started

- Nothing from this sprint's scope. Standing items unchanged:
  Windows bundle still NOT VERIFIED (no Windows machine in this
  environment); the PyInstaller bundle is still the pre-Sprint-12
  build.

## Blocked

- Nothing.
