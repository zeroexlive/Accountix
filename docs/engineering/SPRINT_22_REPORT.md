# Sprint 22 Report — LTR Design Pass for English Mode

Date: 2026-11-03. Environment: Linux, Python 3.12.3 (project
venv), Django 5.2. Base: Sprint 21 complete (364 tests). This
sprint is the systematic LTR design pass that Sprint 19
(ADR-045) explicitly deferred: English mode (`dir="ltr"`) should
look *designed*, not merely unbroken — while Persian RTL stays
pixel-identical except for one deliberate, brief-mandated change
(the numeric rule, below). Standing policy recorded as
**ADR-048**. Print templates are out of scope (Persian
documents, ADR-045).

## Implemented

### Census first (scripted, `backend/static/css/app.css` + all 68 non-print templates)

| Construct | Hits | Class |
|---|---|---|
| `margin-left/right`, `padding-left/right` | 0 | — |
| `left:` / `right:` insets | 0 | — |
| `text-align: left/right` | 0 (`start`/`end` used throughout) | — |
| `float` / physical `clear` | 0 | — |
| `border-left/right*`, corner-specific radii | 0 (`border-inline-end` sidebar, `border-inline-start` action card) | — |
| `border-radius` declarations | 21 — all single-value except `.bar` (`5px 5px 0 0`, equal top corners) | (b) symmetric |
| `box-shadow` (2 tokens + 4 uses) | 6 — every x-offset is `0` | (b) direction-agnostic |
| `translateX`, `background-position`, physical `direction`, hardcoded `order` | 0 | — |
| Logical direction declarations already in use | 20 lines | (a) done in Sprints 11/19 |
| Template inline `style=` | 3 — all dynamic `%` heights/widths (chart bars, progress fill) | (b) values, not directions |
| Hardcoded `dir=` attributes in templates | 0 (only base.html's dynamic `<html>` tag) | — |

So the stylesheet needed **zero (a)-class conversions** — Sprint
19 had already taken the last two. This sprint's work is the
(c)-class design layer plus activating the numeric rule:

- **English typography** (`html[lang="en"]`-scoped, so no fa
  computed style can change): body font stack becomes Latin-first
  — `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica
  Neue", Arial, Tahoma, sans-serif` (Tahoma demoted to late
  fallback); `.kpi-value`, `.lg-value`, `.perf-pct` get
  `font-variant-numeric: tabular-nums` so English display figures
  line up. No letter-spacing changes anywhere (the existing
  `-.01em` on headings/KPI values is shared, pre-existing, and
  was left exactly as-is).
- **Directional-icon mechanism**: `[dir="ltr"] .flip-rtl
  { transform: scaleX(-1) }` ships with the ADR-048 policy
  (flip only icons whose meaning is a direction). **Flip list:
  empty** — see the audit under Tested.
- **The numeric rule, activated.** `td.num/th.num`
  (`text-align: end` + tabular numerals) existed in the CSS
  since Sprint 11, but the census found **zero templates using
  it**: every figure column in the product was start-aligned.
  The rule from the brief — figure columns align to the
  inline-end in both directions — is now applied via the hook:
  **111 `class="num"` additions across 32 templates** (scripted
  pass, every replacement count-verified, then diff-reviewed):
  trial balance, journal list/detail, income statement, balance
  sheet, fiscal-period close figures, stock balances, stock
  movements, stock document list/detail (incl. lines count),
  inventory count list/detail, purchase/sales invoice lists and
  details (quantity, unit price/cost, discount, tax rate/amount,
  totals, returns tables), AP/AR summaries, customer statement,
  return forms' *display* quantity columns, treasury account/
  payment/cheque lists, open items, statement list/detail
  (summary figures + line amounts + book-movement amounts),
  payment detail (allocations + allocation grid figures),
  cheque-book list counts, dashboard (recent invoice totals,
  treasury balances, low-stock quantities).
  Identifiers were deliberately **not** hooked: account codes,
  SKUs, invoice/cheque/leaf numbers, dates, statuses stay
  start-aligned text columns. Data-entry input grids (journal/
  invoice/document/party formsets, count-form input cells,
  allocation amount input) keep start-aligned inputs in both
  modes; display figures inside forms are hooked.
  **Deliberate fa consequence** (the sprint's one intentional
  Persian visual change, mandated by the brief's "one consistent
  rule both directions"): under RTL, `text-align: end` computes
  to the *left*, so fa figure columns now align to the left edge
  of their cells instead of the right. Columns still line up —
  on the opposite edge. Recorded in ADR-048 so it is never
  mistaken for a regression.

### Per-component checklist (CSS/template inspection; no screenshot tooling exists)

- **Sidebar** — PASS. Flex places it at the left in LTR;
  `border-inline-end` becomes the inner (right) border; no
  shadow by design (border-only shell, both modes); user card's
  logout form (`margin-inline-start: auto`) lands on the far
  side; language switcher sits full-width beneath it.
- **Topbar / page-head actions** — PASS. `.top-actions` and
  `.card-head .head-side` use `margin-inline-start: auto` (+
  `text-align: end` on head-side): actions hug the inline-end
  in both modes.
- **KPI cards** — PASS. Delta badge offset is
  `margin-inline-start`; ↑/↓ trend arrows are not flipped
  (ADR-048 exclusion); English figures are tabular (new rule).
- **Dashboard bar chart** — PASS. Bar groups lay out from
  inline-start with direction (first period at the left in
  LTR, at the right in RTL); the rev/exp pair is centered in
  its group (symmetric, class b) and labels center under the
  group; bar top radii are equal-cornered.
- **Performance progress bars** — PASS. The fill is a block
  child with a `%` width, so it anchors at the inline-start
  automatically (left in LTR, right in RTL); track/fill radii
  are fully rounded (symmetric).
- **Tables** — PASS with the numeric-rule change above: text
  columns `start`, figure columns `end` + tabular, both modes.
- **Status pills** — PASS. Inline-block, symmetric padding, no
  directional element; they sit inside start-aligned cells.
- **Forms** — PASS. The card form grid puts the label column
  on the inline-start side in both modes (grid follows `dir`);
  `.errorlist` indents with `padding-inline-start`; inline
  (filter) forms are flex rows in reading order; help/error
  text is start-aligned. Entry grids intentionally keep
  start-aligned inputs (ADR-048 scope call).
- **Pagination** — PASS. The flex row follows direction, so
  Previous sits at the inline-start; the ‹ › glyphs are
  translated string content — en renders `‹ Previous` /
  `Next ›` (LTR-correct as translated in Sprint 20), fa is
  byte-unchanged.
- **Cheque-book leaf grid** — PASS. Plain table, mirrors with
  `dir`; leaf counts now carry `.num`; leaf *numbers* stay
  start-aligned (identifiers).
- **Reconciliation (statement detail)** — PASS. Summary-card
  figures hooked; statement-lines and unmatched-book-movement
  tables mirror; match forms are inline flex in reading
  order; the two stacked cards need no column-order rule.
- **Statement summary card** — PASS (same table; difference
  pill is content, symmetric).
- **Login / lockout auth card** — PASS, and smoke-tested live
  (below). Centered shell; the language switcher sits at
  `inset-inline-end` (top-left in RTL → top-right in LTR);
  brand centered; error box centered.
- **Messages / alerts** — PASS. `.msg` and the non-field error
  list have no icon and symmetric padding; text start-aligned.
- **Empty states** — PASS. Centered text and icon in both
  modes.

### Icon & glyph audit (base.html's 24 SVGs + auth logo)

Flipped: **none** — no current icon qualifies under the
ADR-048 rule. Audited and deliberately not flipped:
trending-up polyline (income-statement nav) and KPI ↑/↓ —
trend arrows, excluded by the rule; refresh/transfer circular
arrows (payments, stock movements) — bidirectional/rotational;
logout arrow — as authored it points toward the inline-end
under LTR, i.e. already correct; list icon (accounts) —
representational, bullets on the LTR-correct side as authored;
book/box/users/card/clock/bank/calendar/scales/chart glyphs —
representational or symmetric. Glyphs in text: pagination
‹ › (per-language strings, above); the `→` between warehouse
and destination in `inventory/document_detail.html` is a
data-flow arrow that reads correctly in LTR as authored (its
RTL rendering is pre-existing and untouched).

## Tested (exact evidence)

New module `backend/apps/core/tests/test_i18n_ltr.py` (3 tests,
same fixtures style as Sprints 19/20):

- **Stylesheet ships the LTR rules**: via the staticfiles
  finder, the real `app.css` contains `html[lang="en"] body`
  with `system-ui` / `"Segoe UI",Roboto`, the en tabular-figure
  rule, `[dir="ltr"] .flip-rtl` with `scaleX(-1)`, and the
  `td.num,th.num{text-align:end…}` numeric rule.
- **Numeric hook live in English**: journal list with the
  language cookie set to en → 200, `dir="ltr"`, `<th
  class="num">Debit</th>` / `Credit` and `<td
  class="num">100.00</td>` in the HTML.
- **Numeric hook live in Persian**: same page by default →
  200, `dir="rtl"`, `<th class="num">بدهکار</th>` and the same
  figure cell — the hook (and hence inline-end alignment) is
  present in both modes.

Commands (repo root, 2026-11-03):

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` (junit) | **367 passed, 3 skipped**, 0 failures/errors (370 total; 364 baseline + 3 new) |
| `manage.py check` under test / local / production / standalone / postgres_test | "System check identified no issues" under **all five** |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `manage.py makemessages -l fa -l en` twice | md5 of both `.po` files **identical before, after run 1 and after run 2** (fa `605e8fdd…`, en `79246d49…`); `git status` clean for `backend/locale/` — catalogs provably untouched |
| `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` | "Success: no issues found in 176 source files" |
| `ruff check backend launcher` / `ruff format --check backend launcher` | clean / 180 files formatted |
| Standalone smoke (launcher, source mode, temp data dir, port 8879) | `/health/` 200 `{"status": "ok"}`; `/login/` fa → `<html lang="fa" dir="rtl">` + Persian title; `/login/` with `django_language=en` cookie → `<html lang="en" dir="ltr">` + `Sign in \| Accountix`; served `app.css` contains the new rules |

RTL-identity argument: every new CSS rule is scoped to
`html[lang="en"]` or `[dir="ltr"]`, neither of which matches a
Persian page; the only shared-stylesheet edit removed two lines
of a stale comment. Template edits add `class="num"` attributes
only — no text, no string, no structure change (makemessages
md5 proof above; the full Persian suite is green unchanged).
The one intentional fa visual delta is the numeric alignment
described under Implemented.

## Partially implemented / accepted

- **No pixel-level verification exists.** Alignment equivalence
  is argued from CSS computed values (logical properties +
  selector scoping), not from rendered screenshots — there is
  no browser/pixel-diff tooling in this environment. A human
  eye over an English session (dashboard chart, wide statement
  tables, the reconciliation page) remains the final check;
  that is stated plainly rather than papered over.
- Form **entry** grids keep start-aligned inputs in both modes
  (typing affordance; ADR-048 scope call) — their display
  columns are hooked, their input columns are not.
- The `.flip-rtl` mechanism ships with an empty flip list: the
  audit found no qualifying icon today. It is policy +
  mechanism for the first chevron/back-arrow that lands.

## Planned / not started

- Rebuild the PyInstaller bundle (still the pre-Sprint-12
  build — now also missing both i18n designs and this LTR
  pass) — the standing release-artifact candidate.
- A human visual QA pass over English mode, if Jason wants
  pixel-level assurance beyond the computed-value argument.
- fa `Plural-Forms` header correction (Sprint 21 flag) — with
  the first pluralized string, unchanged by this sprint.

## Blocked

- Nothing.

## GitHub sync

- One commit via the connector's dedicated `github push-files`
  subcommand — message "Sprint 22: LTR design pass for English
  mode" — with blob-SHA read-back verification (details in the
  executor's handoff; sync outcome recorded there, not
  pre-claimed here).

## Handoff notes for Jason

- Nothing to run after pulling: no migration, no new settings.
  English mode picks the design up from the served stylesheet;
  Persian mode is unchanged except figure columns aligning to
  the inline-end (left edge in RTL) under the one numeric rule
  — see ADR-048 (2).
