# Sprint 30 Report — fa leak closure, SVG charts + motion, guided tours

Three workstreams on Jason's 2026-11-04 feedback, on top of the
1.0.0 release (version **unchanged** — a 1.1.0 decision is Jason's).
ADRs: 055 (leaks), 056 (charts/motion), 057 (tours).

## Workstream A — fa leak closure (ADR-055)

**Method.** A crawl harness (now the permanent test) built a fully
populated world from the suite's builders with all user data in
Persian (company «شرکت بازرگانی نمونه», Persian account/party/
product names, a PAID sale, cheques in hand/deposited/bounced, a
bank statement with lines, a cheque book, low stock, two members)
and crawled **64 GET pages + 10 POST error flows** as OWNER in fa
mode, harvesting visible text plus `placeholder`/`title`/
`aria-label`/`alt` attributes and submit values. Detector: runs of
≥2 consecutive Latin words; then a strict-zone pass (any pure-alpha
Latin token ≥3 letters inside label/th/button/option/legend/h1–h3).

**Leak census (before fixes: 9 pages / 22 distinct sentence hits on
GET, more under the strict-zone pass; after fixes: ZERO).**

| Class | Count | Examples | Fix |
|---|---|---|---|
| (1) Empty fa msgstr (English-source) | **0 found** | — | Verified mechanically against the committed catalog: none existed. The leaks were other classes. (A dev clone without compiled `.mo` still falls back to English for all English-source strings — `compilemessages` is the standing fix there; launcher + tests compile automatically.) |
| (2a) Multi-line `{# #}` comments rendering as visible text | 3 templates | base.html DS-v3 comment, `_line_formset_js.html`, `_company_chooser.html` | Converted to `{% comment %}` blocks. Root cause proven on Django 5.2.18: `{# #}` is single-line only; a multi-line block renders literally (before this fix the crawl saw 61 pages / 762 hits, nearly all from these comments). |
| (2b) Auto-generated form labels (no `verbose_name` anywhere) | 4 forms | 'Account type', 'Normal balance', 'Default currency', 'Start date' | Full `Meta.labels` on AccountForm, CompanyForm, FiscalYearForm, FiscalPeriodForm (+8 new catalog msgids). |
| (2c) Raw enum codes instead of `get_FOO_display` | 24 render sites + 11 blocktrans interpolations + 2 `__str__`s | "PAID", "POSTED", "RECEIPT", `TreasuryAccount.__str__` → "[BANK]", payment-detail journal "[POSTED]" | Display-label swaps in templates; `TreasuryAccount.__str__` and `JournalEntry.__str__` use `get_kind_display()`/`get_status_display()`; treasury open-items rows gained a translated `kind_label`. Print templates excluded by design (ADR-045). |
| (2d) Raw booleans | 8 renders in 7 templates | "True"/"False" in قابل ثبت / فعال / متوازن columns | `{% if %}…{% trans "بله" %}…{% trans "خیر" %}` rendering. |
| (3) Framework strings | **0 leaks** | failed-login error, password-validator errors/help, "This field is required.", UserCreationForm errors, statement-import errors | None needed: Django's bundled fa catalog covers every framework string exercised by the 10 POST flows (evidence: the POST crawl is clean). |
| (4) f-string service strings | 25 sites | "Purchase invoice PINV-1", "Cheque CHQ-2 cleared", "Stock receipt <uuid>", "Opening balance — …" | Gettext templates with named placeholders across accounting/inventory/purchases/sales/treasury services + `BankStatementLine.__str__`; fa translations added (below). Payment fallback now uses `get_direction_display()`. |
| (5) Stored-data history | out of scope to rewrite | Journals written before this sprint keep their creation-language text | Verified contract instead: records created under fa store Persian; under en store English (data-layer test pins both). |

**Catalog work.** +33 msgids in workstream A (25 service templates,
8 form labels), +2 in B, +92 in C → **1,212 entries per catalog**.
fa discipline held: English-source msgids got Persian translations
(25), Persian-source msgids keep empty fa msgstr; en.po got real
translations for every Persian-source addition and msgid-verbatim
entries for English-source ones. **Zero pre-existing entries changed
in either catalog** (verified by full-catalog diff; only the
POT-Creation-Date header churned). Placeholder multisets verified
mechanically for every entry in both catalogs: **0 mismatches**.
makemessages' fuzzy guesses were caught and corrected by hand in
every case (9 in A, 2 in B, 32 tour entries in C) — final state:
**0 fuzzy** in both files, `msgfmt --check` clean on both.

**Regression (permanent).** `apps/core/tests/test_i18n_fa_crawl.py`:
the same crawl as three tests (GET pages, POST error flows,
stored-description language contract). Allowlist, defensible line by
line: file-format labels (CSV, CAMT.053, OFX, XLSX, PDF — the
product's own vocabulary); COGS and SKU (deliberate bilingual
labels «…(COGS)» / «کد کالا (SKU)»); "English" (the language
switcher names the other language in its own script); "Accountix"
and "Muse Spark" (brand + build attribution proper names).
Digit-bearing tokens are exempt as user-data identifiers (SINV-1,
CHQ-2…); the world's own data codes (unit codes like PCS) are
exempt as data. Admin-only `__str__`s (ReversalLink, audit) were
examined and left — they render only in the operator's Django
admin. Plural-Forms header: catalog still has **zero plural
msgids**, so the header is inert and stays (per the brief).

**Assertion change (1):** `test_count_list_page_shows_posted_count`
asserted the raw bytes `POSTED` on the count list; it now asserts
the rendered Persian label «ثبت‌شده» (and that `POSTED` is gone) —
the Sprint 21-style swap for an intentional rendering change.

## Workstream B — SVG charts + motion (ADR-056)

**Implemented.** `apps/reporting/charts.py`:
- `area_chart(series)` — revenue-vs-expenses SVG geometry from the
  same `period_series` rows: polylines, area paths, dots (with the
  raw values for `<title>` tooltips), peak label, x labels. Returns
  `None` for no-rows / zero-peak; the template distinguishes
  "no periods" from "periods but nothing recorded yet" (new msgid).
  Single period → centred degenerate point + sliver area.
- `donut_segments(parts)` / `percent_ring(percent)` — cumulative
  rounding makes arcs sum to the circumference exactly. The four
  `_performance` shares are independent ratios, not parts of a
  whole, so each row gets its own two-segment ring (achieved vs
  remainder) instead of a fabricated combined donut; labels, exact
  percents and captions are unchanged; zero denominators keep the
  existing empty state (`percent=None` → `ring=None`).
- The CSS bar chart (`.bar-*`, `.progress`) was used only by the
  dashboard and is removed cleanly. `dashboard_data` now carries
  `chart` + per-row `ring`; Sprint 11's `period_series` heights
  remain as pinned derived data.

**Numeric pins (tests).** Inverting every plotted y recovers the
`period_series` values; the peak dot sits exactly at the plot top;
endpoints at the plot edges; area paths close on the baseline;
donut arcs sum to `2πr` (abs 0.011) and offsets chain; ring dash
for 45.5% equals 0.455 × circumference; `dashboard_data` pins
(chart peak == series revenue total; collections ring share ==
45.5; cheques ring is None). **Sprint 11 numeric assertions pass
unchanged**; one markup assertion (`b"bar rev"`) became the SVG
equivalent, documented in the test.

**Motion inventory (all CSS, no JS).** Inside
`@media (prefers-reduced-motion: no-preference)` only: `tile-in`
entrance (fade + 6px rise, 220 ms, stagger ≤30 ms steps) for KPI/
main/split/mini cards; `draw-line` (250 ms, `pathLength=1`
dashoffset) for the chart lines; `fade-in` for areas/dots;
`ring-in` scale for rings; the pre-existing card hover lift
(transform transition) **moved into** the block. String-level CSS
tests pin: no `@keyframes` / `animation:` / transform-bearing
`transition:` outside the block. Colour-only sub-150 ms hover
transitions from earlier sprints animate no geometry and remain —
the boundary is recorded in ADR-056.

**Sprite-test exception.** Sprint 28's "no inline SVG" test gains
one scoped exception for the dashboard's data chart + rings
(per-request geometry cannot be a sprite symbol); icons remain
sprite-only, and the test now asserts exactly one bare chart SVG
on the dashboard. The zero-external scan was extended to
`tour.js` in workstream C.

## Workstream C — Guided tours (ADR-057)

**Engine.** `static/js/tour.js` (6,073 B, vanilla, self-hosted,
`node --check` clean): spotlight via a fixed div with a
`box-shadow` cutout + accent outline; tooltip card with title,
body, «گام i از n» counter and prev/next/finish/close buttons —
**all strings come from the page's rendered JSON** (no hardcoded
text in the JS); Esc exits; arrows navigate with RTL mapping
(ArrowLeft = next in fa, mirrored in LTR); click outside ends;
`scrollIntoView` smooth unless reduced-motion; steps with absent
anchors are filtered at start and skipped again at show time;
positioning tracks resize/scroll and flips above the target near
the viewport bottom. Styles in `app.css` (`.tour-*`); the
spotlight glide transition sits inside the ADR-056 motion block.

**Shell contract.** `base.html` topbar renders «راهنمای صفحه»
(milestone sprite icon — the sprite has no compass/circle-help
and regenerating it needs the Lucide release dir, not vendored)
with the `hidden` attribute; the engine reveals it only when a
payload exists and ≥1 anchor is present. No JS → no button; no
payload → no button. The payload is rendered by the `tour_data`
context processor from the `apps/core/tours.py` registry
(keyed by URL name) via `json_script`.

**Coverage — 13 pages, 56 steps, 116 catalog strings.**

| Page | Steps | Anchors |
|---|---|---|
| dashboard | 7 | company-picker, kpis, chart, performance, quick-actions, recent-sales, minis |
| sales_invoice_list | 4 | create, filters, table ×2 |
| sales_invoice_create | 4 | head, lines ×2, submit |
| purchase_invoice_list | 4 | create, filters, table ×2 |
| payment_list | 4 | create, filters, table ×2 |
| cheque_list | 4 | filters ×2, table ×2 |
| bank_statement_detail | 5 | summary, lines, candidates, add-line, import |
| product_list | 4 | actions ×2, table ×2 |
| stock_documents | 4 | create ×2, table ×2 |
| income_statement | 4 | filters ×2, cogs, result |
| fiscal_year_detail | 4 | periods ×3, close-year |
| company_members | 4 | members ×2, add-existing, add-new |
| profile | 4 | profile-form ×2, password ×2 |

**Anchor/role contract (tested).** OWNER rendering: every step
anchor exists on its page. VIEWER dashboard: payload present;
the anchors missing from the rendering are **exactly**
`{quick-actions}` (OPERATE-gated since Sprint 28) — the set the
engine skips. Uncovered pages ship the hidden button + engine
script but no payload (tested on journal_list). en mode: the
dashboard payload contains the English UI strings and step titles
(tested, incl. the pre-existing «Select company» catalog win).

**Catalog discipline for C.** +92 msgids, all Persian-source:
fa msgstrs empty by convention, en translations written for all
92 (24 further tour strings already existed in the catalog and
were left untouched); 0 existing entries changed; 0 fuzzy;
msgfmt clean.

## Part D — Bundle + frozen smoke

`scripts/build_linux.sh` rebuilt the plain bundle (the released
1.0.0 artifact was **not** re-packaged; `package_release.sh` not
re-run). Frozen smoke against a fresh data dir
(`ACCOUNTIX_DATA_DIR=/tmp/accx30-smoke`):

- `/login/` → 302 → `/setup/` (zero-user bootstrap alive in the
  bundle); setup POST (admin + «شرکت نمونه دود») → 302 → dashboard
  carrying the tour payload and the chart's honest "no periods"
  empty state.
- Seeded through the frozen binary's own `manage shell` (fiscal
  year + 2 periods + 3 accounts + 3 posted journal entries:
  revenue 1000/1500, expense 250): the dashboard renders the SVG
  chart with revenue polyline **`8,76.7 712,16`** — exactly the
  geometry the source tests pin for values 1000/1500 against peak
  1500 (y = 198 − v/1500 × 182). The tour payload parses as JSON
  with Persian UI strings («بعدی»/«پایان تور»/«گام {i} از {n}»)
  and step titles; performance rows show the honest empty texts
  (the seed has no invoices, so every percent is None and no ring
  is rendered — by design); no "Sales invoice"-style English and
  no raw PAID/POSTED on the fa dashboard.
- `/static/js/tour.js` → 200 (6,195 B as served), app.css → 200.
- Sales invoice list in the frozen app: payload with 4 steps;
  the `table` anchor is absent on the empty list — the engine's
  skip contract, live.
- `manage check` → "System check identified no issues", exit 0.

## Gates

- Full suite: **479 tests — 476 passed, 3 skipped, 0 failed**
  (baseline 455 + 3 → +21 net new: 3 crawl + 10 charts/motion +
  8 tours; see CURRENT_STATE's ledger).
- `manage.py check` clean under base, standalone and test
  settings; `makemigrations --check` → no changes (no model
  changes this sprint).
- `mypy` clean (193 files); `ruff check backend tests` clean.
- `msgfmt --check` clean on both catalogs; 0 fuzzy; catalogs at
  1,212 msgids each; placeholder multisets verified (0 mismatches).
- Zero-external test green, now also covering `tour.js`.

## Limitations

- No headless browser exists in this environment: tour stepping,
  chart pixels and motion timing are verified server-side /
  string-level / by construction only. Jason's eye is the final
  check (same standing limit as Sprint 28's pixels).
- Stored descriptions written before Sprint 30 keep their
  creation language (class 5); only new records follow the
  active language.
- The released 1.0.0 artifact is untouched; `dist/` was rebuilt
  for Jason's own testing. Windows bundle remains NOT VERIFIED
  (standing release gate).
