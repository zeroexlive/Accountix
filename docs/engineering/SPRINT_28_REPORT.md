# Sprint 28 Report — Design System v3 "Bento": self-hosted fonts + Lucide icons

Date: 2026-11-03. Base: Sprint 27 complete (446 passed + 3 skipped).
Trigger: the owner's verdict, for the second time (first: Sprint
11), that the UI is still "dry and soulless" — with explicit
requirements this time: proper Persian AND English fonts, proper
SVG icons, a modern Bento design system, and **everything
self-hosted, zero external dependencies** (offline-first is a
product invariant). Presentation-only sprint: **no business logic,
no models, no migrations, no view/service changes** (ADR-053).

## Implemented

### Part 1 — Self-hosted assets (all from official releases, via curl)

**Fonts** — `backend/static/fonts/`, woff2 only, `font-display: swap`:

| Family | Upstream | Weights | Files | Bytes |
|---|---|---|---|---|
| Vazirmatn | rastikerdar/vazirmatn **v33.003** | 400/500/700/800 | `vazirmatn-{400,500,700,800}.woff2` | 203,952 |
| Inter | rsms/inter **v4.1** | 400/500/700/800 | `inter-{400,500,700,800}.woff2` | 455,312 |

Total font payload **659,264 bytes** (~644 KiB, under the ~700 KB
cap; 800 is used — headings/KPI numerals are weight 800). Every
file's wOF2 magic was verified on disk. Per-file sha256 (also in
`backend/static/THIRD_PARTY_NOTICES.md`, with release-archive
sha256s and source URLs):

- `inter-400.woff2` `e06f6b1b…b0ae085` · `inter-500.woff2` `0ff3e946…cf2a48`
- `inter-700.woff2` `fa888127…a8d95ea` · `inter-800.woff2` `6f750258…f714e34`
- `vazirmatn-400.woff2` `e3821013…3db3d91` · `vazirmatn-500.woff2` `3333e311…52db48`
- `vazirmatn-700.woff2` `836fae7d…585627` · `vazirmatn-800.woff2` `cd67558b…3b45b02`

Licenses: both fonts are SIL OFL 1.1 — full texts vendored as
`fonts/OFL-Vazirmatn.txt` and `fonts/OFL-Inter.txt`.

**Font stack** — ONE combined stack for both locales:
`"Inter", "Vazirmatn", Tahoma, "Segoe UI", Arial, sans-serif`.
Per-character fallback renders Latin in Inter and Persian glyphs
in Vazirmatn in fa and en alike; the Sprint 22 `html[lang="en"]`
body stack is retired (ADR-053 (1)). Negative letter-spacing is
now scoped to `html[lang="en"]` display type only (Arabic-script
joining is never spaced). Tabular figures are unscoped:
`.kpi-value`/`.lg-value`/`.perf-pct` carry
`font-variant-numeric: tabular-nums` + `font-feature-settings:
"tnum" 1` (both fonts ship tnum), as `td.num` already did.

**Icons** — Lucide **1.67.0** (ISC; license vendored as
`static/icons-LICENSE.txt`, fetched from the official repo at the
release tag) as ONE sprite, `backend/static/icons.svg`
(12,622 bytes, **36 symbols**), generated from the release's
`icons/*.svg` by the committed `scripts/build_icon_sprite.py`.
Templates use `<svg class="icon" aria-hidden="true"><use
href="{% static 'icons.svg' %}#i-<name>"/></svg>`; symbols carry
Lucide's native stroke-2 presentation, instances size/color via
CSS. All 31 hand-drawn inline SVGs are gone: 28 in `base.html`
(brand + 26 nav + logout) mapped to Lucide equivalents
(layout-dashboard, list, book-open, milestone, package, layers,
repeat, clipboard-list, file-text, users, shopping-cart,
credit-card, receipt-text, hand-coins, scroll-text, wallet,
refresh-cw, banknote, clock, landmark, notebook-pen, chart-column,
trending-up, scale, building, calendar, log-out, book) and the
brand mark in login/setup/lockout. Dashboard adds gauge, inbox,
plus, file-plus, coins, arrow-down-left, arrow-up-right and
triangle-alert. The ADR-048 flip audit was repeated over the
Lucide set — no icon qualifies (log-out / transfer arrows are in
the never-flip categories), so `.flip-rtl` still ships with an
empty flip list.

### Part 2 — Bento DS v3 (ADR-053) + dashboard rebuild

`app.css` rewritten as one system (510 lines): radius scale
(tiles 24px / inner cards 16px / controls 12px), layered soft
shadows, a **floating shell** (sidebar + topbar are rounded tiles
on the canvas; sticky sidebar), a **CSS-only canvas texture**
(three soft radial brand tints, no images), a gradient brand mark
and avatar, a dark active nav pill, tinted **icon chips**
(magenta/blue/violet/green/amber) heading tiles, pill-shaped soft
table headers + row hover, 12px form controls with a blue focus
ring, gradient chart bars. The rewritten stylesheet was censused
with the Sprint 22 script: **zero** physical direction
declarations (no margin/padding-left/right, no left/right insets,
no physical text-align, no floats, no physical borders,
no translateX/background-position) — logical properties only.

**Dashboard as a true bento grid** (`bento-kpis` / `bento-main` /
`bento-split` / `bento-minis`): KPI tile row with icon chips ·
chart tile (2fr) beside the performance tile (1fr) · quick-actions
tile (330px) beside recent sales · 8 mini stat tiles with chips ·
the Sprint 11 bottom stacks unchanged. Tile map (every tile backed
by the same `dashboard_data` keys as DS v2 — no helper changed):

| Tile | Data source (unchanged) |
|---|---|
| درآمد دوره / فروش دوره / خرید دوره | `dashboard.kpis.{revenue,sales,purchases}` (+ delta badges, previous-period sub-labels) |
| موجودی نقد و بانک | `treasury_total` + cash/bank split |
| درآمد و هزینه (chart) | `period_series` via `period_series()` — sums still pinned == `income_statement` |
| عملکرد | `performance` rows (derived shares, honest empty states) |
| دسترسی سریع (quick actions) | the five create routes — links only, no data |
| آخرین فاکتورهای فروش | `recent_sales` (+ payment-status pills) |
| 8 mini tiles | `ar_total`, `ap_total`, `inventory_valuation`, `net_income`, `open_receivable_total`, `open_payable_total`, `outstanding_cheques_*`, `low_stock_count` |
| Bottom stacks | `treasury_rows`, `low_stock_rows`, `recent_entries`, `recent_purchases` |

Quick actions follow the Sprint 25 pattern: rendered only when
`company_can … "OPERATE"` holds for the dashboard company (a
VIEWER's sales tile spans the freed column via `:only-child`).
Labels reuse the create pages' catalogued strings; exactly ONE
new msgid («دسترسی سریع» / "Quick actions") was added, wrapped
and catalogued additively in both .po files (semantic po diff:
+1 entry, 0 removed, 0 changed, 0 fuzzy, msgfmt clean; the rest
of the po diff is `#:` location churn from the template
rewrites). Login/setup/lockout got the new fonts (via the shared
stylesheet) and a 28px-radius bento auth card with the gradient
brand mark. All other pages inherit v3 tokens via `app.css` only.
Print templates untouched; the print block is preserved verbatim.

### Part 3 — Bundle rebuild + frozen smoke

`scripts/build_linux.sh` exit 0, no spec/script changes (the spec
already ships `backend/static` wholesale). **Bundle: 112,313,950
bytes (116 MB), 3,847 files** — Sprint 27 was 116 MB / 3,834
files, so **+13 files** (8 fonts + sprite + 2 OFL texts + Lucide
license + notices) and the font+sprite payload (+671,886 bytes)
inside the same rounded size. Dist audit: all 8 woff2 +
`icons.svg` + licenses present under `_internal/static/`, app
`.mo` catalogs for both locales shipped.

## Tested (exact evidence)

| Command / run | Result |
|---|---|
| `.venv/bin/python -m pytest` | **455 passed, 3 skipped** (446 baseline + 9 new, zero regressions) |
| `manage.py check` — local / test / standalone / postgres_test / production | no issues under all five |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `mypy` (pyproject config) | "Success: no issues found in 188 source files" |
| `ruff check backend launcher tests scripts` | all passed |
| `ruff format --check` | 199 files already formatted (1 new file reformatted during the sprint) |
| `msgfmt --check` (fa + en catalogs) | clean; semantic po diff +1 msgid only |

**New tests** (`backend/apps/core/tests/test_design_v3.py`, 9):
the 8 font files are findable via staticfiles with wOF2 magic and
>10 KB each; the stylesheet declares exactly 8 `@font-face` rules
with `font-display: swap` whose `url()`s are exactly the 8 vendored
files, families {Inter, Vazirmatn}, weights {400,500,700,800}×2;
the combined stack is the body font; **every** `<use>` reference
in **every** template resolves to a sprite symbol, every sprite
symbol is used, ids are unique, and no template contains an inline
`<svg viewBox` anymore; **zero-external scan**: no template and
not `app.css` contains `http://`, `https://`, `//cdn`,
protocol-relative src/href or `url(http…` — and every CSS `url()`
starts with `../fonts/`; the bento dashboard renders (grids +
sprite refs + all five quick-action hrefs) for an OWNER, and for
a VIEWER renders the same tiles with **no** quick-action hrefs.
The Sprint 11 dashboard tests pass **unchanged** — period-series
equality with `income_statement`, delta cases, rendered
percentages (45.5٪ etc.) and empty states are all still pinned
against the same helpers.

**Assertion changes (itemized, all in
`backend/apps/core/tests/test_i18n_ltr.py`):** the Sprint 22 font
pins asserted the *superseded* design, so they moved: dropped
`'html[lang="en"] body' in css`, `"system-ui" in css` and
`'"Segoe UI",Roboto' in css` (the en system stack ADR-053
retires) — replaced by `'"Inter","Vazirmatn"' in css` and
`'html[lang="en"] body' not in css`; dropped
`'html[lang="en"] .kpi-value'` (tabular figures are unscoped now)
— replaced by `'.kpi-value,.lg-value,.perf-pct' in css`. The
flip-rtl, scaleX and `td.num` pins are unchanged, as is the whole
numeric-hook behaviour in both languages.

**Served evidence (no headless browser exists in this
environment, so no screenshot claim is made):** the standalone
launcher in source mode served, over real HTTP — `/login/` 302 →
`/setup/` 200 (`lang="fa" dir="rtl"`, sprite brand mark), setup
POST → dashboard 200 with all four bento grids, 28+ sprite
references, quick actions and tinted chips in the HTML, **zero**
non-localhost URLs in the served page; all fonts 200 with
`font/woff2` and wOF2 magic, sprite 200 `image/svg+xml`; after
`set_language`, the dashboard renders `lang="en" dir="ltr"` with
the "Quick actions" heading. The frozen bundle repeated the same
journey binary-only (below).

**Frozen smoke** (fresh data dir, port 8893, bundle binary only):
health 200 → /login/ 302 → /setup/ (fa/rtl) → setup POST 302 →
dashboard 200 (bento grids, sprite refs, quick-list, tinted chips
present; **0 external URLs** in the served HTML) → all 8 fonts
fetched through the frozen server: 200, `font/woff2`, exact
vendored byte counts, wOF2 magic → `icons.svg` 200
`image/svg+xml` → `app.css` 200 with all 8 `@font-face` rules
(the relative `../fonts/…` URLs resolve against the collected
static root) → en dashboard 200 `dir="ltr"` with "Quick actions"
rendered from the bundled .mo → server stopped →
`accountix manage check` exit 0.

## Partially implemented

- No pixel-level verification: this environment has no headless
  browser or screenshot tooling (checked: no chromium/firefox
  binary, no Playwright). The visual claim rests on the served
  output evidence above + the computed-style pins in tests; a
  human eye-check of the dashboard + login in fa and en remains
  the final check — stated plainly, as in Sprint 22.
- Table headers are not sticky: no scrollable table container
  exists in the product today, so there was nothing to make
  sticky (the brief's "where it exists" case is empty).

## Planned / not started

- The previously recommended Sprint 28 packaging pass
  (versioned release artifact + upgrade smoke on a real existing
  dataset) was superseded by this sprint and remains the natural
  next candidate.
- Windows bundle verification — unchanged, still the only NOT
  VERIFIED release-gate item (needs a Windows machine).

## Blocked

- Nothing.

## GitHub sync

- One commit via the connector's dedicated `github push-files`
  subcommand — message "Sprint 28: Bento design system v3 —
  Vazirmatn/Inter fonts, Lucide icons (ADR-053)" — **including
  the binary font files**, with blob-SHA read-back verification
  of every file, binaries included (outcome recorded in the
  executor's handoff; if the connector refuses or corrupts any
  binary, the fallback is the manifest route: the binaries stay
  out of the commit and `THIRD_PARTY_NOTICES.md` + this report
  carry their versions, source URLs and sha256s for manual
  vendoring — the bundle built locally carries the fonts
  regardless).
