# Sprint 24 Report — First-User Bootstrap (setup flow + manage passthrough)

Date: 2026-11-03. Environment: Linux, Python 3.12.3, Django 5.2,
gettext 0.21 (reinstalled via the documented scoped-apt route — the
environment had lost it again; see DEVELOPMENT.md). Base: Sprint 23
complete (367 tests; bundle rebuilt but unable to create its first
user). This sprint closes that gap with the two mechanisms Sprint 23
recommended, then rebuilds the bundle and proves the whole
recipient journey **bundle-only**. Full rationale: **ADR-049**.

## Implemented

### Part 1 — First-run setup (web app)

- **Trigger (no middleware)**: `SetupAwareLoginView` (users app,
  stock `LoginView` + the existing template) redirects GET **and**
  POST `/login/` → `/setup/` while setup is available. The funnel
  was verified against the code, not assumed: the launcher opens
  the browser at `/login/` (`config/paths.py: login_url`), the
  dashboard is `login_required` with `LOGIN_URL="login"`, and a
  zero-user install has no sessions — every first-run journey
  reaches the login view. The root chain (dashboard → login →
  setup) is pinned by test. Every other anonymous surface (health,
  static, `set_language`) is untouched.
- **Guard**: `first_run_setup_available()` = `FIRST_RUN_SETUP_ENABLED`
  **and** no user rows. It is evaluated on every request by both
  the login view and the setup view, so the window closes the
  moment the first user exists; afterwards anon requests redirect
  to login, authenticated ones to the dashboard, and nothing is
  processed (pinned by test, incl. POSTs).
- **Form + transaction**: `FirstRunSetupForm(UserCreationForm)` —
  username + password1/password2 + `company_name`. Password
  confirmation and the full `AUTH_PASSWORD_VALIDATORS` set run as
  form validation (`_post_clean` → `validate_password`); an invalid
  POST creates nothing. A valid POST creates, in ONE
  `transaction.atomic`: the user with `is_staff=True,
  is_superuser=True` (the installer is the owner; ADR-049 (3)),
  the company **through the organizations UI's own `CompanyForm`**
  (name from the form; other fields at their model defaults — the
  values that form renders as initials), and
  `CompanyMembership(role=OWNER)` — exactly the effects of
  `organizations.views.company_create`. Company creation seeds
  nothing else anywhere in the product (no chart/fiscal-year
  seeding exists at company level), so setup seeds nothing extra.
  The admin is then logged in (explicit ModelBackend) and lands on
  the dashboard with a success flash.
- **Kill switch**: `FIRST_RUN_SETUP_ENABLED` in base settings, env
  `ACCOUNTIX_FIRST_RUN_SETUP` (default on; `0/false/no/off`
  disables). Off ⇒ `/setup/` redirects to login even at zero users
  and `createsuperuser` remains the bootstrap. PRODUCTION.md now
  carries the plain warning: the zero-user window is
  first-come-first-served; pre-create or disable before any
  network exposure.
- **i18n**: template in the `registration/` family on the auth-card
  shell (language switcher included via base). 6 new Persian
  msgids (setup title, heading, explainer, submit button,
  company-name label, success flash); catalogs regenerated —
  **1032 → 1038 msgids**, en.po filled for all 6 (1038/1038,
  `msgfmt --check` clean, 0 fuzzy), fa by ADR-045 design.
  A semantic diff of both catalogs against Sprint 23 proved the 6
  additions are the ONLY changes (0 removed, 0 altered); a second
  `makemessages` run was a fixpoint.

### Part 2 — Launcher manage passthrough

- `accountix manage [--data-dir PATH] <args...>` is dispatched in
  `accountix_launcher.main` **before** argparse
  (`parse_manage_invocation` consumes an optional `--data-dir`
  immediately after `manage`; later `--data-dir` tokens belong to
  Django untouched). `run_manage_command` resolves the data dir
  and secret via `config.paths` exactly like a launch, then:
  source mode → `manage.py` subprocess with **inherited stdio**
  (interactive `createsuperuser` prompts work), exit code returned
  verbatim; frozen mode → `execute_from_command_line` in-process
  with `SystemExit` translated back into the exit code. No server,
  no browser, no instance lock; the docs restate the standing
  operator rule (stop the server for state-mutating commands —
  the `restore_db` guidance that already existed). Usage error
  (bare `manage`) exits 2.

### Part 3 — Bundle rebuild

- `scripts/build_linux.sh` as shipped, exit 0, ~90 s of PyInstaller
  time after venv/pip setup. **No spec changes were needed**: the
  setup view is project code (already collected), the passthrough
  lives in the entry script, and the rebuilt archive ships the new
  `registration/setup.html` + compiled catalogs (build script's
  hard `compilemessages` step). Bundle: **116 MB, 3,830 files**
  (Sprint 23: 3,829), left in `dist/` (gitignored, never synced).

## Tested

### In-process (new tests: +17 → 384 total)

`apps/users/tests/test_first_run_setup.py` (10): zero-user GET and
POST `/login/` → 302 `/setup/`; root chain dashboard→login→setup
ends 200 on the auth card; setup page renders fa/RTL; weak password
(`1234`) and mismatched confirmation → form errors with **zero**
users/companies/memberships afterwards; valid POST → 302 dashboard,
user is staff+superuser with the set password, company exists,
membership role is OWNER, dashboard **and** company list render 200
for the new admin; after creation, anon GET/POST `/setup/` →
login, logged-in GET/POST `/setup/` → dashboard, counts stay 1/1,
login page is ordinary again; English rendering of the setup page
(`First-run setup`, `Create administrator and company`, LTR);
kill switch off → setup unreachable at zero users and login
renders normally.

`apps/core/tests/test_launcher_manage.py` (7): argv parsing
(manage variants, `--data-dir` both forms consumed only in pole
position, non-manage argv ignored); dispatch via `main()` with the
command runner stubbed (returns its code, server never engaged);
**real runs** — `main(["manage", "--data-dir", tmp, "check"])`
returns 0 with the secret bootstrapped in the data dir and **no
instance lock file created** (no server path taken); unknown
command returns non-zero; bare `manage` returns 2.

Existing tests touched (2 files + 1): three pre-existing tests
rendered `/login/` with an empty user table and asserted 200 —
that state is precisely what the setup redirect changes, so
`test_i18n.py::test_login_page_default_is_persian`,
`test_dashboard_v2.py::test_login_page_uses_auth_card` and
`test_auth.py::test_login_page_renders_rtl_persian` now create a
user first (their assertions are unchanged).

### Frozen smoke (fresh data dir `/tmp/s24/data`, port 8879, curl)

| Step | Result |
|---|---|
| Launch (fresh dir) | ready in ~15 s; health 200 |
| GET /login/ (zero users) | **302 → /setup/** |
| GET / | 302 → /login/?next=/ (chain continues to setup via login) |
| GET /setup/ | 200, `lang="fa" dir="rtl"`, setup heading present |
| POST /setup/ (admin + `Smoke Co`) | 302 → / |
| GET / (dashboard) | 200 fa/RTL, logged in by the setup POST |
| GET /organizations/companies/ | 200, lists `Smoke Co` |
| GET /setup/ (logged in) | 302 → / (setup dead) |
| POST /logout/ | 302 → /login/ |
| GET /setup/ (anonymous) | 302 → /login/ |
| GET /login/ | 200, ordinary login page |
| POST /login/ (setup credentials) | 302 → /; GET / 200 |
| SIGINT | clean shutdown, port closed |
| `accountix manage --data-dir … check` (frozen) | `System check identified no issues`, **exit 0** |
| `accountix manage --data-dir … axes_reset` (frozen) | `No attempts found.`, **exit 0** |
| `accountix manage --data-dir … bogus_command` | **exit 1** (propagation in frozen mode) |
| DB inspection | 48 migrations (axes ×10, treasury 0001–0003); `users_user`: admin, staff=1, superuser=1; company `Smoke Co`, currency IRR; membership OWNER |

### Gates (exact commands)

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **384 passed, 3 skipped** (367 baseline + 17 new) |
| `manage.py check` under test/local/production/standalone/postgres_test | no issues, all five |
| `manage.py makemigrations --check --dry-run` | "No changes detected" (no model changes) |
| `msgfmt --check` fa + en catalogs | clean; en 1038/1038 translated, 0 fuzzy |
| `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` | Success, 181 source files |
| `ruff check backend launcher` / `ruff format --check` | clean |
| `scripts/build_linux.sh` | exit 0; bundle 116 MB / 3,830 files |

## Partially implemented / accepted

- The passthrough intentionally builds **no locking**: a `manage`
  run concurrent with a live server is the operator's
  responsibility, as the backup/restore docs already framed it.
- First-launch `compilemessages` breadth (Sprint 23 note) is
  unchanged — harmless, out of this sprint's scope.

## Planned / not started

- Windows bundle build + smoke on a real Windows machine — still
  the only **NOT VERIFIED** release-gate item. (The setup view and
  passthrough are platform-neutral code; the passthrough's frozen
  branch is the same in-process pattern the Windows launcher
  already uses for its server — but nothing here ran on Windows.)
- An installer (Inno Setup/MSI) — unchanged from Sprint 09.

## Handoff notes for Jason

- Pull as usual; **no migration**. Run `compilemessages` once on a
  dev checkout if you want the setup page's English strings (the
  launcher and the bundle handle it themselves).
- The rebuilt bundle in `dist/accountix/` now bootstraps itself:
  first launch → setup page → admin + company → dashboard, and
  `dist/accountix/accountix manage …` runs management commands
  against its data directory.
