# Sprint 11 Report — UI Redesign (Design System v2)

Date: 2026-11-03. Base: Sprint 10 complete (202 passed + 3 skipped on
SQLite). Trigger: the owner's feedback that the Sprint 01–10 interface
was "too dry and soulless", with a modern light SaaS dashboard as the
visual reference. This sprint is presentation-only: **no business
logic, no models, no migrations** — the only new Python is two
derived display helpers in the reporting app, pinned equal to the
existing services by tests (ADR-038).

## Implemented

- **Design system v2** — `backend/static/css/app.css` rewritten as one
  coherent token system (not accreted): canvas `#f4f5f8`, white cards
  (18px radius, diffuse layered shadows, hairline borders), near-black
  primary buttons, magenta accent (revenue `#d6336c`), soft blue
  (expenses `#5b8def`), green/red/amber soft-badge semantics,
  Tahoma-first system font stack. Components: sidebar nav with
  section labels and active pill, topbar with page title + user chip,
  sidebar user card, KPI cards with delta badges, filter/form grid,
  tables (muted soft header, row hover), status pills, pagination,
  soft flash alerts, empty states, centered login card, responsive
  breakpoints (sidebar stacks on narrow screens).
- **App shell in `base.html`** — authenticated pages render a sidebar
  (structurally on the **right** under RTL, mirroring the LTR
  reference) grouped as: داشبورد / حسابداری / انبار / خرید و فروش /
  خزانه‌داری / گزارش‌ها / سازمان — every href verified against the
  URLconf (a test reverses all 22 names and asserts the hrefs render).
  Icons are inline SVG (stroke style, currentColor). Anonymous pages
  get a bare centered shell so the login page is a clean card.
- **Dashboard rebuild** (`templates/core/dashboard.html`):
  - KPI row: درآمد دوره / فروش دوره / خرید دوره with **delta badges
    vs the previous fiscal period** (↑ green / ↓ red, 1-decimal %),
    plus موجودی نقد و بانک (point-in-time: cash/bank split as the
    sub-label instead of a badge). No previous period or a zero
    previous value → no badge, ever (the value is None in the data).
  - Chart card «درآمد و هزینه»: grouped CSS bars per fiscal period
    of the current fiscal year (magenta revenue / blue expenses),
    legend with year totals, values in `title` attributes.
  - «عملکرد» panel: four progress rows — وصول مطالبات (collected
    share of posted sales), تسویه بدهی (settled share of posted
    purchases), چک‌های دریافتی وصول‌شده (cleared share by amount of
    cleared + outstanding received cheques), سلامت موجودی
    (1 − low-stock / products-with-stock). Each row shows the raw
    numbers in its caption; a zero denominator renders an honest
    empty-state sentence instead of a percentage.
  - Recent sales invoices as a table card with **payment-status
    pills** (PAID green / PARTIALLY_PAID amber / UNPAID red-soft) —
    the same pills were added to the sales/purchase invoice lists.
  - Nothing from Sprint 08 was dropped: AR/AP subledger totals,
    inventory valuation, net income (with its COGS note), open-item
    totals, outstanding cheques, low-stock count + warning table,
    treasury accounts, recent journal entries and recent purchases
    all remain, restyled.
- **Login page** restyled as a centered card on the soft canvas with
  the brand mark and a soft error alert.
- **Pagination** partial restyled (pill links), same URLs/params.

## Derived helpers added (reporting app, ADR-038)

- `period_series(company, fiscal_year)` — per-period revenue/expenses
  via `income_statement(..., cogs_accounts=[])` (closing entries
  excluded per ADR-030; COGS stays inside expenses, the dashboard
  convention), with bar heights precomputed as % of the peak bar.
- `previous_period(company, period)` + `_delta_pct` — the immediately
  preceding period by start date; delta is None when there is no
  previous period or its value is zero.
- `_performance(...)` — the four panel shares from existing reports
  (`open_items` totals, `_posted_invoice_total`, `outstanding_cheques`,
  `stock_balances`, `low_stock`); `_percent` returns None on a zero
  denominator.
- `dashboard_data` gained keys only (`previous_period`, `kpis`,
  `fiscal_year`, `period_series`, `series_*_total`, `performance`);
  every Sprint 08 key is unchanged.

## Tested (exact evidence)

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **214 passed, 3 skipped** (202 baseline + 12 new; skips are the PG-only concurrency tests) |
| `pytest backend/apps/reporting` | all green (16 Sprint 08 + 12 new) |
| `manage.py check --settings=config.settings.test` | no issues |
| `manage.py makemigrations --check --dry-run` | "No changes detected" (no models touched) |
| `ruff check backend launcher tests` | all passed |
| `ruff format --check` | clean (148 files) |
| `mypy` (backend, pyproject config) | "Success: no issues found in 140 source files" |
| `scripts/smoke_standalone.sh` | "SMOKE OK" — the packaged source-mode launcher still serves with the new shell |

New tests (`apps/reporting/tests/test_dashboard_v2.py`, 12):
`period_series` per-period figures **and** sums asserted equal to
`income_statement` over the fiscal-year range (2500 revenue / 750
expenses on a two-period journal dataset) with bar heights checked;
delta helper unit cases (up +50.0, down −50.0, flat 0.0, zero-previous
None, no-previous None); dashboard KPIs on a two-fiscal-year world
(revenue/sales delta +100.0%, purchases 0.0, `previous_period` is the
2025 period); badge markup absent when there is no previous period;
rendered performance percentages asserted as numbers (collections
**45.5%** from 500/1100, settlements **0.0%**, cheques **75.0%** from
300 cleared / 100 outstanding, inventory health **100.0%**); all four
percentages None + empty-state sentences rendered on an unposted
world; all 22 sidebar URL names reverse and their hrefs appear in the
dashboard HTML; all 22 main pages return 200 with the sidebar shell
(+ invoice detail pages); login page uses the auth card and has no
sidebar; print view still returns SINV-1 + 1100 + the print layout
with **no** app shell (print untouched). A temporary spot-check also
rendered company detail/create, account create and fiscal-year create
(200 + shell) and was removed after passing.

Rendering was verified through the Django test client (status +
context + content markers) and the standalone smoke — there is no
screenshot tooling in this environment, so no pixel-level claim is
made.

## Partially implemented

- Per-page topbar titles: only the dashboard sets `page_title`;
  other pages keep their in-content `<h1>` (now styled) and the
  topbar falls back to the product name.
- Statement/list pages inherit the design system centrally (cards,
  tables, forms, pills) but their markup was not individually
  rebuilt; the COGS multi-select and date filters keep their Sprint
  08 structure inside the new form grid.

## Planned / not started

- Data-entry UI for business documents (still the headline product
  limitation — unchanged by this sprint), Jalali display dates,
  `.po` translations, dark mode, vendored HTMX/Alpine (ADR-006).

## Blocked

- Nothing blocked. (The frozen PyInstaller bundle was not rebuilt
  this sprint; the release-artifact rebuild noted in Sprint 10 still
  applies and will pick up the new templates/CSS automatically.)

## Deliberately NOT copied from the reference

Fake/decorative controls: the reference's global search, Share,
Customize Widget, Imports and per-card "⋯" menus do nothing in the
mock — none were copied. Every control in the redesigned UI works:
navigation, the company selector, filters, exports and print links
are the real Sprint 01–10 routes. The reference's "than last week"
captions became real previous-period comparisons with the previous
value shown; its Performance panel became real derived shares
instead of target/KPI/satisfaction inventions (we have no targets,
teams or satisfaction data — inventing them would be fake data).
Avatars in the reference's table became payment-status pills, which
is the information an accountant actually needs in that column slot.
