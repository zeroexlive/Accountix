# Sprint 19 Report — i18n Groundwork: Bilingual fa/en Chrome with gettext

Date: 2026-11-03. Environment: Linux, Python 3.12.3 (project venv),
Django 5.2, GNU gettext 0.21 (installed this sprint — see Step 0).
Base: Sprint 18 complete (346 tests). This sprint builds the real
gettext pipeline — settings, catalogs, language switching, direction
handling — and translates the application **chrome** end to end.
It is groundwork by design (ADR-045): the business pages are *not*
translated yet, and this report says so plainly wherever it matters.

## Step 0 — toolchain (done first, it shaped the sprint)

`msgfmt`/`xgettext` were **absent** from the machine. The stock
route — a full `apt-get update` — proved unusable in practice: it
had fetched 409 MB of package lists into `partial/` in 17 minutes
without finishing (all components + all translations + two mirrors,
one of them crawling; the store process had used 9 s of CPU when
killed). The working route was a **scoped apt update**: a
`main`-only source file pointing at the azure archive mirror,
`Acquire::Languages=none`, state kept in a scratch dir — 4.6 MB in
5 s — after which `apt-get install gettext` installed gettext
0.21-14ubuntu2 normally (`/usr/bin/msgfmt`, `/usr/bin/xgettext`).
On a normal dev machine the plain sequence works:
`apt-get update && apt-get install -y gettext`; the prerequisite is
now recorded in `docs/engineering/DEVELOPMENT.md`. With working
binaries confirmed, the sprint proceeded; no catalog was fabricated
by hand at any point — extraction is xgettext's output, and the one
script used in the sprint only *filled msgstr values* into that
output by entry order (decoding msgids from the file itself so no
Persian character could be retyped wrong).

## Implemented

- **Settings** (`config/settings/base.py`): the i18n wiring mostly
  pre-existed (Sprint 01) and is now actually used — `USE_I18N =
  True`, `LANGUAGE_CODE = "fa"`, `LOCALE_PATHS =
  [BASE_DIR / "locale"]`, `LocaleMiddleware` already in the
  documented position (Session → Locale → Common; position pinned
  by the new settings smoke tests). Changes made: `LANGUAGES`
  verbose name for fa is now «فارسی», and a comment block records
  the ADR-045 conventions. **No URL prefixes** — `config/urls.py`
  gained only `path("i18n/", include("django.conf.urls.i18n"))`
  for the stock `set_language` view.
- **Wrapped chrome — 103 msgids** (the complete inventory):
  `templates/base.html` (document title default, brand + tagline,
  all 6 sidebar section heads, all 22 nav labels, «کاربر سیستم»,
  logout title/aria-label, page-title default),
  `templates/registration/login.html` (5 strings),
  `templates/registration/lockout.html` (5 strings),
  `templates/core/dashboard.html` (the rest: title, company filter
  labels, period note, KPI labels and «دوره قبل:»/«صندوق:»/«بانک:»
  prefixes, chart card title/legend/bar tooltips, performance
  title, all card titles, table headers, empty states,
  «{{ count }} فقره» as a `blocktrans`).
  Dynamic data is never wrapped: service-generated performance
  labels/captions, period and fiscal-year names, invoice statuses
  and all model text render as stored in both languages.
- **Catalogs**: `backend/locale/en/LC_MESSAGES/django.po` —
  **103/103 wrapped strings translated** (msgfmt --check clean);
  `backend/locale/fa/LC_MESSAGES/django.po` — same msgids, all
  msgstr empty **by design** (the msgid is the Persian source;
  the file's header comment documents the rule). `.mo` files are
  gitignored build artifacts (see Partially/accepted for why).
- **Language switcher** (`templates/_language_switcher.html`):
  no-JS POST form to `set_language` with `next` = the current full
  path; rendered in the sidebar footer and in the auth shell (so
  login and lockout pages carry it too). The button offers the
  *other* language under its own name — «English» in fa mode,
  «فارسی» in en mode (endonym convention, deliberately unwrapped).
- **Direction**: `base.html` emits
  `<html lang="…" dir="…">` from `{% get_current_language %}` /
  `{% get_current_language_bidi %}` — fa renders byte-identical
  `lang="fa" dir="rtl"`; en renders `lang="en" dir="ltr"`.
- **CSS LTR audit** (`backend/static/css/app.css`): the shell was
  already mostly logical (`border-inline-end` on the sidebar,
  `margin-inline-start:auto` on topbar/card actions,
  `text-align:end` on numeric cells). Two physical holdouts were
  converted with identical RTL rendering: `th, td { text-align:
  right }` → `text-align: start`, and the user-chip's asymmetric
  physical padding → `padding-inline-start/end`. Switcher styles
  added (`.side-lang`, `.auth-lang` corner placement via
  `inset-inline-end`, full-width sidebar button). Flex layout
  flips with `dir` automatically, so the sidebar moves to the
  left in LTR without further rules. Print templates untouched
  (Persian documents — ADR-045).
- **Date filter** (`apps/core/templatetags/jalali.py`): the
  `jalali` filter now branches on the active language in its one
  implementation — fa or unset → Jalali `YYYY/MM/DD` (unchanged,
  `to_jalali` untouched); otherwise → the stored Gregorian date
  as ISO `YYYY-MM-DD` (new `to_gregorian_iso`, same pass-through
  contract for `None`/non-dates). The filter keeps its name;
  the naming debt is recorded in ADR-045.
- **Compile pipeline**: `.gitignore` gains `*.mo`. The standalone
  launcher's `prepare_database` now runs `compilemessages` after
  collectstatic **best effort** — a failure logs a WARNING and
  startup continues (msgfmt is absent on typical end-user
  machines; a missing catalog must never brick the app, unlike a
  failed migration which still aborts). `scripts/build_linux.sh`
  and `scripts/build_windows.bat` run `compilemessages` as a hard
  build step before PyInstaller (the spec already bundles
  `backend/locale`, so bundles ship fresh `.mo` files).

## Tested (exact evidence)

New file `backend/apps/core/tests/test_i18n.py` (8 tests). The
module compiles the catalogs in its own module-scoped fixture
(`call_command("compilemessages")`), so the English assertions
pass on a fresh clone where no `.mo` exists yet:

- **Default fa chrome**: dashboard for a fresh client renders
  `<html lang="fa" dir="rtl">`, the Persian `<title>`, Persian nav
  labels, and the switcher offering «English»; login page likewise
  Persian/RTL.
- **Switch to en**: POST to `set_language` → dashboard renders
  `<html lang="en" dir="ltr">`, `Dashboard | Accountix` title,
  English nav labels («Trial balance», «Cheque books»), «Log out»,
  and *no* Persian chrome string («تراز آزمایشی» absent); the
  switcher now offers «فارسی». The `django_language` cookie value
  is asserted directly.
- **Persistence across login**: after logging out through the real
  logout view (the test client's own `logout()` wipes its whole
  cookie jar — a test-harness artifact a browser does not share)
  the login page is still English/LTR, and after a real credential
  login the dashboard is still English.
- **Switch back**: en → fa restores `lang="fa" dir="rtl"` and the
  Persian labels.
- **jalali filter branches** (unit): under `translation.override
  ("fa")` 2026-03-20 → `1404/12/29`; under `("en")` → `2026-03-20`;
  `None` → `""` under fa. All Sprint 13 jalali tests pass
  unchanged.
- **Fallback**: `gettext()` of a deliberately uncatalogued Persian
  string under en returns the Persian msgid itself — the
  fa-source convention degrading safely.
- **Settings smoke** (subprocess imports, Sprint 16 pattern):
  `config.settings.production` and `config.settings.standalone`
  both report `USE_I18N=True`, `LANGUAGE_CODE='fa'`,
  `LANGUAGES=['fa','en']`, LocaleMiddleware strictly between
  Session and Common, and the project `LOCALE_PATHS`.

Commands (repo root, 2026-11-03):

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **354 passed, 3 skipped** (346 baseline + 8 new; 3 skips = PG-only concurrency tests) — zero regressions: every pre-existing Persian assertion, including the Sprint 16 lockout page and Sprint 13 Jalali pages, passes byte-identical under the fa fallback |
| `manage.py check` under test / local / production / standalone / postgres_test settings | "System check identified no issues" under **all five** |
| `manage.py makemigrations --check --dry-run` | "No changes detected" (no model changes) |
| `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` | "Success: no issues found in 174 source files" |
| `ruff check backend launcher` / `ruff format --check` | clean / 178 files formatted |
| Launcher smoke (source mode, temp data dir, port 8799) | startup ran `compilemessages` in sequence ("already compiled and up to date"), `Accountix is ready`, `/health/` 200, `/login/` 200 with `<html lang="fa" dir="rtl">` |
| `msgfmt --check` on both committed `.po` files | clean, no warnings |

## Partially implemented / accepted

- **Business pages are NOT translated — by design, and visibly
  so.** Only the chrome set above is wrapped. In English mode the
  sidebar, login/lockout and dashboard labels are English while
  every business page (invoices, treasury, reports, forms…) still
  renders its Persian literals, and dashboard cards still show
  service-generated Persian labels (performance rows) and raw data.
  This is the ADR-045 boundary Jason approved ("زیرساخت ترجمه" —
  infrastructure); the completion is a dedicated wrapping-sweep
  sprint, for which the pipeline, conventions and catalog now
  exist.
- **`.mo` files are not in the sync** (and are gitignored): the
  connector's push path builds a UTF-8 text snapshot and cannot
  carry binaries. Consequence, stated plainly: after `git pull`,
  a dev checkout has no compiled catalogs until `compilemessages`
  runs (DEVELOPMENT.md step) — until then even English selection
  falls back to Persian chrome (safe, never broken). The launcher
  and the bundle builds compile automatically as described.
- **LTR is sane, not polished.** Direction flips and the shell
  lays out correctly (sidebar left, tables start-aligned), but no
  pixel-level LTR design pass was done: e.g. letter-spacing tuned
  for Persian, chart/perf internals and any remaining
  physical-property cosmetics on unwrapped pages were left alone.
- The `jalali` filter name now undersells what it does in English
  mode (renders Gregorian ISO). Renaming was rejected (every
  template would churn); recorded as naming debt in ADR-045.

## Planned / not started

- String-wrapping sweep of the remaining templates + en.po
  translations (the follow-up that makes English mode complete),
  including form labels/errors produced by project code.
- A pixel-perfect LTR design pass, if English mode becomes a
  shipped priority.
- Windows bundle verification — still the only NOT VERIFIED
  release-gate item (unchanged by this sprint).

## Blocked

- Nothing. (The Step 0 toolchain detour is documented above; it
  cost time, not scope.)

## GitHub sync

- One commit via the connector's dedicated `github push-files`
  subcommand — message "Sprint 19: i18n groundwork — bilingual
  fa/en chrome with gettext" — with blob-SHA read-back
  verification (details in the executor's handoff; sync outcome
  recorded there, not pre-claimed here).

## Handoff notes for Jason

- **Nothing to run after pulling for the default Persian app** —
  it works exactly as before. To see English locally: install the
  gettext tools once, run `manage.py compilemessages` in
  `backend/`, restart, and use the «English» button at the bottom
  of the sidebar (or on the login page).
- New dev-machine prerequisite: GNU gettext (`msgfmt`/`xgettext`)
  for `makemessages`/`compilemessages` — see DEVELOPMENT.md.
- Behaviour to expect: the language choice is stored in a cookie
  (`django_language`), applies to the chrome only for now, and
  dates switch with it (Jalali in Persian mode, ISO Gregorian in
  English mode).
