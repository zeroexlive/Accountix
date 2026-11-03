# Sprint 20 Report — i18n Sweep: English Mode Complete (ADR-046)

Date: 2026-11-03. Base: Sprint 19 complete (354 tests, en.po at 103
chrome msgids). This sprint is the named follow-up of ADR-045: the
string-wrapping sweep over the whole UI surface, so English mode is
no longer chrome-only. Print templates stay Persian (ADR-045 —
they are Persian business documents) and were excluded by path:
`print_base.html`, `purchases/invoice_print.html`,
`purchases/supplier_statement_print.html`,
`sales/invoice_print.html`, `sales/customer_statement_print.html`.

## Implemented

- **Templates**: all 62 remaining in-scope templates wrapped
  ({% trans %} / {% blocktrans %} with named placeholders;
  sentences never split around variables): accounting (9) +
  shared partials (pagination, company chooser), inventory (13),
  organizations (8), parties (3), purchases (6), sales (7),
  treasury (14) — headings,
  table headers, buttons/links, inline form labels, help/guide
  texts, empty states, filter labels, confirm() texts, the
  «(میلادی)» input markers, and link texts pointing at print
  pages («نسخه چاپی» is UI text even though its target is not).
- **Forms**: labels, help_texts and form-declared choice labels
  wrapped with `gettext_lazy` across all eight forms modules
  (treasury/forms.py alone carried 61 Persian literals).
- **Views**: all `messages.*` flash texts and Persian context
  literals wrapped with call-time `gettext` (incl. the statement
  import report's «ردیف/تراکنش» row nouns and interpolated
  messages converted to named-placeholder form).
- **Reporting**: the dashboard performance panel's 12 Persian
  label/caption/empty strings (built in `apps/reporting/services.py`)
  wrapped with call-time `gettext` + named placeholders — the only
  Persian-source Python strings outside templates/forms/views.
- **Services**: every `ValidationError` text in the service
  modules (accounting, catalog, inventory, organizations, parties,
  purchases, sales, treasury services + reconciliation +
  cheque_books + statement_files' per-row rejection reasons, and
  model `clean()` ValidationErrors) wrapped with `gettext_lazy`;
  f-strings converted to `%(name)s` placeholders. These texts are
  **English-source** (the codebase convention since Sprint 01:
  services speak English, views render them verbatim), so wrapping
  changes no rendered byte in either language — it catalogues them.
- **Choice labels (ADR-046)**: investigated on one app first —
  wrapping a `TextChoices` label in `gettext_lazy` produced
  `makemigrations` "No changes detected" (the migration serializer
  evaluates lazy proxies by value). Applied to all **89 labels**
  in the seven models files that define choices; the full
  `makemigrations --check` afterwards still reports no changes.
  **Zero migrations in this sprint.** Labels are English-source,
  so — exactly like service messages — rendering is unchanged in
  both modes; the labels are now in the catalogs.
- **Catalogs**: msgids 103 → **1032** in both locales. Per-category
  unique-msgid counts by catalog reference (a msgid referenced from
  two categories counts in both): templates 532, forms 128,
  views 67, services 273, models 75. en.po: **1032/1032 translated,
  0 empty, 0 fuzzy** (`msgfmt --check` clean). fa.po: all msgstrs
  empty by ADR-045 design. Sprint 19's 103 translations were
  machine-verified to survive extraction unchanged. Nine
  cross-group terminology conflicts (same Persian msgid, two
  proposed English renderings) were adjudicated once, globally:
  the سند family unified on "Document" (glossary precedent:
  "Stock documents"); first-seen glossary-consistent renderings
  kept for the rest ("Back to list", "Receivables/Payables
  account", "No items", "+ New line").
- **Tests**: new `apps/core/tests/test_i18n_sweep.py` — 9 tests:
  an English-mode crawl (list + detail + form pages for
  accounting, organizations, parties, inventory, purchases, sales,
  treasury incl. reconciliation and cheque books) asserting
  per-page English UI labels present and their Persian originals
  absent; a wrapped service error rendered in English (unbalanced
  journal: "Journal entry is not balanced: debit 100 != credit
  50."); a success flash and an info flash rendered in English.
  The module carries an autouse `translation.deactivate_all()`
  teardown: `set_language` activates the language in-process, and
  without the reset the default-language jalali test fails in
  full-suite order (found by the suite, fixed in the new module —
  no existing test was touched).

## Tested (exact evidence)

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **363 passed, 3 skipped** (354 baseline + 9 new; zero regressions) |
| `manage.py check` under test/local/production/standalone/postgres_test | no issues, all five |
| `manage.py makemigrations --check --dry-run` | "No changes detected" — no model changes, no label migrations |
| `makemessages` run twice consecutively | identical md5 for both .po files — extraction is a fixpoint (nothing missed) |
| `msgfmt --check --statistics` on en.po | 1032 translated messages, 0 untranslated, 0 fuzzy |
| `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` | Success, 175 source files |
| `ruff check backend` / `ruff format --check backend` | clean / 175 files formatted |
| Residual-literal census (scripted) | 0 unwrapped static UI literals in scope (see below) |

Census detail (the only Arabic-script hits left in in-scope
templates/Python, each with its reason): the language switcher's
endonym labels (deliberately untranslated, ADR-045); the `٪`
percent glyph attached to KPI numbers (a numeric glyph shipped
since Sprint 11, not a word); one hidden form field whose value
«ابطال از رابط کاربری» is a stored void-reason **data value**,
not display text; four multi-line `_(` calls in reporting/services
the line-based scanner cannot see (verified wrapped by hand).

Per-group fa regression nets (run by the group workers before the
merge): accounting 55 passed, inventory+catalog 57, parties+
purchases+sales 63, treasury+organizations 97 — then the full
suite above on the merged tree.

## Partially implemented / accepted

- **fa rendering of status vocabulary**: unchanged by design —
  choice labels and service errors were English in the Persian UI
  before this sprint and still are; they are now catalogued, so a
  future sprint *could* translate them into Persian via fa.po.
  That would be a product decision (it changes the default UI),
  not a bug fix, and is not done here.
- **Stored-data strings stay unwrapped**: service-built journal /
  audit descriptions ("Purchase invoice …", "Reversal of …",
  cheque clearing descriptions, the OFX `name — memo` join) are
  persisted data rendered as stored in both languages (ADR-045
  rule, reaffirmed). The hidden void-reason value above is the
  same class.
- Two English `Http404` texts in the print views were left
  unwrapped (attached to the ADR-045-excluded print flows; they
  are developer-facing error pages, not UI chrome).

## Planned / not started

- LTR pixel-perfect design pass (unchanged from ADR-045: LTR is
  sane, not polished).
- Translating service/choice strings into Persian in fa.po —
  only if Jason wants the default UI's status/error vocabulary
  in Persian (see above).
- The PyInstaller bundle is still stale (pre-Sprint 12) — it will
  pick up the catalogs when next built, since the spec bundles
  `backend/locale` and the build scripts compile messages.

## Blocked

- Nothing.

## GitHub sync

- One commit via the connector's dedicated `github push-files`
  subcommand — message "Sprint 20: full UI translation sweep —
  en mode complete" — with blob-SHA read-back verification
  (details in the executor's handoff; sync outcome recorded
  there, not pre-claimed here).

## Handoff notes for Jason

- Nothing to run after pulling for the default Persian app (no
  migration). To see the complete English UI locally:
  `manage.py compilemessages` once (needs the gettext tools) and
  use the language button — every page, form, flash and form
  error is now English; only printed documents stay Persian.
