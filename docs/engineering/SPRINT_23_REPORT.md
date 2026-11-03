# Sprint 23 Report — PyInstaller Bundle Rebuild & Frozen Smoke Run

Date: 2026-11-03. Environment: Linux, Python 3.12.3, PyInstaller 6.22.3,
gettext 0.21 present on the build machine. Base: Sprint 22 + the
numeric-alignment follow-up complete (367 tests; local HEAD d6e1ca8).
The Linux bundle in `dist/` dated from **Sprint 09** — it predated the
data-entry UI (12), Jalali display (13), bank reconciliation (14),
cheque books (15), django-axes (16), the PG restore drill fixes (17),
CAMT/OFX import (18) and the whole bilingual layer (19–22). This
sprint rebuilds it from the current tree and smoke-runs the **frozen
binary** end-to-end. The Windows bundle remains **NOT VERIFIED**
(nothing here ran on Windows; the one spec change below is in the
shared spec, so it carries over to a future Windows build textually).

## Implemented

- **One spec change** (`launcher/accountix.spec`):
  `collect_submodules("axes")` added to `hiddenimports`, with the
  reason recorded in a comment. Nothing else in the build inputs
  changed; `scripts/build_linux.sh` ran as shipped.
- **Docs**: this report; `CURRENT_STATE.md` bundle-freshness update +
  the §10 candidate struck; `docs/deployment/LINUX.md` status line
  refreshed to Sprint 23.

## The defect the rebuild census found (and the fix's evidence)

The first build (script as-is) completed cleanly — and would have
shipped a bundle whose login flow was broken. A census of the frozen
PYZ archive (`pyi-archive_viewer -r`) showed:

| Module group | In PYZ (build 1) | Why |
|---|---|---|
| `apps.*` + `config.*` (incl. all project migrations, e.g. `treasury.0003`) | present | the spec's `collect_submodules` |
| `django.contrib.*` migrations | present | PyInstaller's Django hook |
| `axes` / `axes.models` | present | import graph |
| `axes.migrations.*` (0001–0010) | **absent** | loaded by Django by name |
| `axes.middleware`, `axes.backends`, `axes.handlers.*` | **absent** | referenced from settings by string only |
| `openpyxl.*` | present (176 modules) | import graph |
| `jdatetime` | present | single-module package; 1 entry is complete |
| `rest_framework.*` | top package only | acceptable: no project code imports DRF submodules (grep-verified); DRF is installed-but-unused |

PyInstaller's Django hook also logged `No django root directory
could be found!` (the analysis entry point is the launcher, not a
Django project), so no INSTALLED_APPS-driven collection happened.
After the spec fix, the rebuilt archive contains `axes.migrations`
0001_initial … 0010_accessattemptexpiration, `axes.backends`,
`axes.middleware`, `axes.handlers.*` (7) and `axes.management.*` (9).

## Tested — build evidence

| Check | Result |
|---|---|
| `scripts/build_linux.sh` (as-is, build 1) | exit 0, ≈160 s wall (fresh `.venv-build`, pip install, compilemessages hard step, PyInstaller) |
| Rebuild after the spec fix | exit 0, ≈160 s wall |
| Bundle size | **116 MB**, 3,829 files (`dist/accountix/`, main binary ≈11.8 MB) — Sprint 09: 75 MB |
| Project `.mo` in bundle | `_internal/locale/fa/LC_MESSAGES/django.mo` **and** `…/en/…` present (compiled by the build script's hard step; `.mo` is gitignored and never travels via git) |
| Current CSS in bundle statics | `html[lang="en"]` rules present; `td.num,th.num{text-align:start` (Sprint 22 + follow-up) present |
| Build warnings | 3, all benign (Django-root notice above; two `Hidden import … not found` for Django backend internals that don't exist in Django 5.2) |

## Tested — frozen smoke run (the binary treated as a user machine)

Fresh data dir `/tmp/s23/data`, port 8879, `ACCOUNTIX_NO_BROWSER=1`.

**Run 1 (fresh database).** Startup log shows the documented
sequence: no existing DB → skip backup → `migrate --noinput` →
`collectstatic` → best-effort `compilemessages` → server in-process
(frozen mode) → ready. Verified against the created SQLite file:
**48 migrations applied**, including **axes 0001–0010 (all ten)** and
**treasury.0003_chequebook_chequeleaf**. `/health/` 200;
`/login/` 200 with `<html lang="fa" dir="rtl">`. SIGINT →
`Interrupted — shutting down.`, port closed.
First-launch time-to-ready in this dev environment was under a
minute, dominated by the launcher's best-effort `compilemessages`
walking every locale tree visible from the working directory (the
repo's `.venv`/`.venv-build` plus the bundle's own Django tree);
run 2, with catalogs already compiled, was ready in seconds. On a
clean user machine there is no repo tree to walk.

**First user (the gap, and the documented path around it).** The
frozen binary exposes **no management-command entry point** — its
only interface is the launcher flags. The documented first-user path
is source-mode `manage.py createsuperuser` (README quick start);
`docs/deployment/LOCAL.md` documents running management commands
against a standalone data dir with
`DJANGO_SETTINGS_MODULE=config.settings.standalone` +
`ACCOUNTIX_DATA_DIR` set. Following exactly that pattern, the smoke
created the superuser (`createsuperuser --noinput`, env credentials)
plus a minimal company/fiscal-year/period/membership fixture via
`manage.py shell` — all against the bundle-created database. **The
gap stands as a finding (below): a recipient of only the bundle,
with no source checkout, has no way to create the first user.**

**Run 2 (existing database) + full HTTP smoke** against the frozen
server (curl, cookie jar, real CSRF form posts):

| Request | Result | What it proved |
|---|---|---|
| startup | `Backup written: …/backups/accountix-20261103-181425.sqlite3 (1314816 bytes)` before migrate | backup-gated migration works frozen |
| POST /login/ wrong password | 200 (form error); afterwards `axes_accessattempt` has **1 row** in the frozen DB | django-axes middleware+backend+tables live in the bundle; successful login then reset the counter (axes logged the deletion) |
| POST /login/ correct credentials | 302 → `/` | real authentication in the frozen app |
| GET / (fa) | 200, `lang="fa" dir="rtl"` | dashboard renders |
| GET /organizations/fiscal-years/ | 200, contains `1404/10/11` | **jdatetime works frozen** (Jalali render of 2026-01-01) |
| GET /sales/invoices/new/ | 200 | Sprint 12 data-entry UI |
| GET /treasury/cheque-books/ | 200 | Sprint 15 cheque books |
| GET /treasury/statements/ | 200 | Sprint 14/18 reconciliation |
| GET /inventory/documents/new/ | 200 | Sprint 14 stock documents |
| POST /i18n/setlang/ (en) → GET / | 302 → 200, `lang="en" dir="ltr"`, "Dashboard" present, 0 occurrences of «داشبورد» | **bundled .mo catalogs drive a fully English UI** |
| GET /accounting/journal/ (en) | 200, `dir="ltr"` | bilingual business page frozen |
| GET /static/css/app.css | 200; contains `html[lang="en"]` ×2 and `td.num,th.num{text-align:start` | WhiteNoise serving the current collected CSS |
| SIGINT | `Interrupted — shutting down.`, port closed | clean lifecycle |

Data dir after the smoke (5.1 MB): `db.sqlite3`, `secret_key.txt`,
`accountix.log`, `backups/…sqlite3`, `staticfiles/` (incl. `css/`).

## Partially implemented / findings

- **First-user creation from the bundle alone is impossible**
  (release-relevant gap, pre-existing since Sprint 09, surfaced
  here because this is the first authenticated frozen smoke): the
  launcher has no management passthrough and no first-run setup
  screen. Today the only path is a source checkout running
  `createsuperuser` against the data dir (documented for dev in the
  README; the LOCAL.md env pattern makes it work for standalone
  data dirs). **Recommendation (Sprint 24 candidate):** give the
  launcher a management passthrough (e.g. `accountix manage
  createsuperuser`) or a first-run "create admin" setup page when
  the user table is empty. Not fixed in this sprint: the brief was
  rebuild + smoke, and the smoke's authenticated half was completed
  via the documented operator path.
- First-launch `compilemessages` in the launcher walks locale trees
  beyond the project's own (observed: the build machine's venv
  trees). Best-effort by ADR-045 design and harmless, but it makes
  first launch slower than it needs to be; scoping it to the
  project catalog is a small future tidy-up.

## Planned / not started

- Windows bundle build + smoke on a real Windows machine — still
  the only **NOT VERIFIED** release-gate item.
- First-user bootstrap for bundle recipients (finding above).
- An installer (Inno Setup/MSI) — unchanged from Sprint 09.

## Gates

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **367 passed, 3 skipped** (baseline held; the only code change is the spec) |
| `ruff check backend launcher` | All checks passed |
| `ruff format --check launcher/accountix.spec` | clean |
| `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` | Success, 176 source files |
| `git status` before docs | only `launcher/accountix.spec` modified |

## Handoff notes for Jason

- The rebuilt bundle is at `dist/accountix/accountix` (left in
  place; `dist/` is gitignored build output and is **not** part of
  the GitHub sync — only the spec fix and docs are).
- Bundle contents are current through Sprint 22 + the numeric
  follow-up. It still needs a source checkout nearby for the very
  first admin user (finding above).
