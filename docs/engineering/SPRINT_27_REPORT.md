# Sprint 27 Report — Self-Service Account Surface + Release Polish + Bundle Rebuild (ADR-052)

Date: 2026-11-03. Environment: Linux, Python 3.12.3, Django 5.2,
gettext 0.21 present. Base: Sprint 26 complete (430 tests; bundle
current through Sprint 26). Three parts, in order: (1) the
self-service account surface ADR-051 (5) left open — a signed-in
user's own profile + password change; (2) polish — a VIEWER
dashboard/shell audit and the current release-status picture;
(3) a PyInstaller bundle rebuild + frozen smoke carrying all of
it. Full rationale: **ADR-052**.

## Implemented

### Part 1 — Self-service account surface (users app)

- **Routes**: `profile/` and `profile/password/` in
  `apps/users/urls.py` — the users app owns auth (login/logout/
  setup/lockout live here). Deliberately NOT company-scoped and
  carrying NO user id: the subject is always `request.user`, so
  the surface is self-only by construction (ADR-052 (1)). Both
  login-required (anonymous → the standard redirect to /login/).
- **Profile** (`profile` FBV + `ProfileForm`, a ModelForm on the
  user): first name, last name, email. **Email verdict: editable.**
  Evidence: the User model is plain `AbstractUser` + UUID pk;
  authentication (ModelBackend) and the axes lockout
  (`AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]`) key
  on the username alone; the model's email is non-unique and no
  code path reads it as identity (the only other email hit in the
  codebase is a party-form test payload). It is a plain
  `EmailField` on the form, so an invalid address is a form
  error. **The username is NOT editable** — it is the login
  identity, the axes key, and the audit reference (ADR-052 (2)):
  the form has no username field and the template shows it
  read-only, so a smuggled `username` POST value is ignored by
  construction.
- **Password change** (`AccountPasswordChangeView` =
  `LoginRequiredMixin` + `SuccessMessageMixin` + Django's stock
  `PasswordChangeView` — the users app already hosts a CBV, the
  login view): current password required; the new password runs
  through the full `AUTH_PASSWORD_VALIDATORS` set via
  `PasswordChangeForm`; on success the stock view calls
  `update_session_auth_hash`, so the CURRENT session stays signed
  in while other sessions' hashes go stale and must re-login
  (ADR-052 (3)), and a Persian success message lands on the
  profile page.
- **Axes interaction — finding, no behaviour changed.** Failed
  password-change attempts do NOT count toward the django-axes
  login lockout. Evidence: axes counts failures exclusively from
  Django's `user_login_failed` signal (`axes/signals.py` →
  handler); that signal is sent by the authentication flow, while
  `PasswordChangeForm.clean_old_password`
  (`django/contrib/auth/forms.py`) verifies the current password
  via `user.check_password()` directly — no `authenticate()`
  call, no signal. Proven additionally by test (below).
- **Discoverability**: «پروفایل من» + «تغییر گذرواژه» links in the
  sidebar's user-identity area (under the user card, with
  active-state styling) and the topbar user-chip now links to
  the profile. Visible to every signed-in user regardless of
  role/company.
- **Name reflection**: the changed full name renders where names
  are displayed — the members roster (`username — Full Name`,
  Sprint 26) is proven by test to show the new name after a
  profile rename; the profile page itself re-renders the saved
  values in the shell.
- **i18n**: 11 new msgids, purely additive (semantic po diff:
  0 removed, 0 altered; second makemessages = fixpoint). All
  xgettext fuzzy guesses in en replaced with real translations —
  catalogs now hold 1083 msgids, en 1083/1083 translated,
  0 fuzzy, `msgfmt --check` clean on both catalogs.

### Part 2 — Polish

- **VIEWER audit — method**: a temporary crawl test (deleted
  after use; its fixes are pinned by permanent tests) signed in
  as a VIEWER of a populated world (`build_world`), rendered the
  dashboard + 17 representative shell pages, extracted every
  internal href/form-action, followed them one more level
  (detail pages), and GET every unique target as the VIEWER.
  Round 1 (35 targets): **two real findings** —
  (a) the product LIST rendered a per-row «ویرایش» link to
  `product_edit` that 403s for a VIEWER (Sprint 25 guarded the
  list's create buttons but missed the row link), and
  (b) at depth 2, the party DETAIL page rendered its «ویرایش»
  button unconditionally — `party_edit` 403s for a VIEWER.
  **Fixes, in the Sprint 25 pattern**: product_list wraps the row
  link in a per-row `{% company_can p.company "OPERATE" %}` (the
  list is cross-company, so the check is per product's company);
  party_detail wraps the button in
  `{% company_can party.company "OPERATE" as can_act %}`.
  Server gates unchanged. Round 2 (34 targets): clean — the only
  non-200 left is `GET /logout/` → 405, the POST-only logout form
  working as designed. Everything else on the dashboard/shell —
  sidebar nav, KPI/report links, company chooser, detail links —
  is a READ surface a VIEWER may legitimately open (company
  creation stays global/ungated per ADR-050).
- **Release status addendum**: NEW `docs/engineering/
  RELEASE_STATUS.md` — the current gate picture in Sprint 10's
  numbering (RELEASE_READINESS.md untouched, historical): every
  Linux gate closed/verified with its sprint (incl. gates closed
  since Sprint 10: #15 PG restore VERIFIED in Sprint 17, #20
  login rate limiting in Sprint 16, #12 bundle rebuilt/smoked in
  23/24/26/27, #17 extended by role enforcement in 25/26), the
  Sprint 10 limitations' dispositions, and the **Windows bundle
  as the sole remaining NOT VERIFIED item** with exactly what
  verification requires (a Windows machine, `scripts\
  build_windows.bat`, the frozen-smoke checklist). Linked from
  CURRENT_STATE + README.
- **Version stamp**: `backend/config/version.py` —
  `__version__ = "1.0.0"`, the ONE source of truth (ADR-052 (4));
  a `app_version` context processor exposes it; it renders in
  the sidebar footer («نسخه 1.0.0») and on the login page.
  `pyproject.toml`'s `[project] version` mirrors it for
  packaging metadata only. The module ships inside the app
  package tree, so source and frozen bundle read the same value
  — proven in the frozen smoke (both renderings).

### Part 3 — Bundle rebuild

- `scripts/build_linux.sh` exit 0; no spec/script changes
  needed. Bundle: **116 MB, 3,834 files** (Sprint 26: 116 MB /
  3,832; +2 = the two account templates) at `dist/accountix/`
  (gitignored, never synced).
- **Spec audit**: `_internal/templates/users/{profile,
  password_change}.html` present as data files; both app `.mo`
  catalogues shipped; the version module rides the PYZ as code
  (proven by rendering, below).

## Tested

- **New module `apps/users/tests/test_account_surface.py` —
  15 tests**: anonymous profile/password → 302 to login; profile
  GET shows current values and contains NO `name="username"`
  input; POST persists name+email and the dashboard carries both
  shell links; username-smuggle POST → username unchanged, the
  legitimate fields still save; invalid email → form error,
  nothing saved; profile rename reflects on the members roster
  («Reza Karimi»); self-only — user A's page renders A's data and
  never user B's (who also exists in the same DB); a VIEWER uses
  both pages fully; password: wrong current → form error +
  password unchanged, weak new (`1234`) → validator errors +
  unchanged, success → 302, the SAME session GETs the dashboard
  200 without re-login, a fresh client's real login POST with
  the OLD password fails (login form re-rendered, dashboard
  still behind redirect) and with the NEW password succeeds;
  **axes proof** — six failed password changes (past
  AXES_FAILURE_LIMIT=5) followed by logout + a real login POST →
  302 success, NOT locked out; version renders on the login
  page and in the shell.
- **Audit regression test** (+1 in
  `apps/core/tests/test_role_permissions.py`): the VIEWER's
  product list and party detail contain neither edit URL, the
  GETs behind them still 403, and the OWNER sees both links.
- **Full suite: 446 passed + 3 skipped** (baseline 430 + 3,
  plus the 16 new) — zero regressions, zero fixture changes.
- **Frozen smoke** (fresh `/tmp/s27/data`, port 8881, curl,
  bundle binary only):

  | Step | Result |
  |---|---|
  | Launch (fresh dir) | health 200 |
  | GET /login/ (zero users) | 302 → /setup/ |
  | POST /setup/ (admin + `Smoke Co`) | 302 → / |
  | GET / (dashboard) | 200; sidebar footer shows «نسخه 1.0.0» |
  | GET /profile/ | 200 |
  | POST /profile/ (first=Smoke, last=Adminian, email set) | 302 → /profile/ |
  | GET members page | 200; roster shows "Smoke Adminian" |
  | GET /profile/password/ | 200 |
  | POST wrong current password | 200 with form error, password unchanged |
  | POST correct change | 302 → /profile/ |
  | GET / (same session) | 200 — session survived |
  | POST /logout/ | 302 |
  | GET /login/ (fresh jar) | 200; version «1.0.0» on the login page |
  | POST login with OLD password | 200, Persian bad-credentials error; dashboard still 302-gated |
  | POST login with NEW password | 302 → /; dashboard 200 |
  | `accountix manage --data-dir … check` (frozen) | "System check identified no issues", **exit 0** |
  | DB inspection | 48 migrations applied by the bundle; admin row carries the new name/email, staff=1/superuser=1, OWNER membership active |

- Gates (exact commands, from `backend/` unless noted):
  `.venv/bin/python -m pytest` (repo root) → 446 passed,
  3 skipped; `manage.py check` under `config.settings.local`,
  `.test`, `.standalone`, `.postgres_test` → no issues; under
  `.production` (with `DJANGO_SECRET_KEY` set, as that module
  requires by design) → no issues;
  `manage.py makemigrations --check --dry-run` → "No changes
  detected" (**no model changes this sprint — no migration**);
  `mypy --config-file ../pyproject.toml .` → Success, 187 files;
  `ruff check .` → all passed; `ruff format --check .` → 187
  files already formatted; `msgfmt --check` on both catalogs →
  clean.

## Partially implemented

- Nothing partial in the brief's scope. Accepted boundaries,
  documented in ADR-052 (5): this is not a recovery flow — a
  forgotten password still needs the operator path (`manage
  changepassword`); the Django admin can still edit users
  directly (operator's tool, as with memberships in ADR-051).

## Planned (follow-ups)

- **Windows bundle verification** — unchanged, still the only
  NOT VERIFIED release-gate item; needs a Windows machine (the
  exact checklist is now written in RELEASE_STATUS.md).
- Role-scoped dashboards (optional polish, from Sprint 26's
  list): the VIEWER audit found the shared dashboard honest for
  a read-only role — every control on it works for a VIEWER —
  so a role-specific landing stays a nice-to-have, not a fix.

## Blocked

- Nothing blocked this sprint. No sync blockers expected: the
  change set is code/templates/styles/catalogs/docs only (dist/
  and .venv-build/ are gitignored), and the end-of-sprint sync
  rides the established one-commit `github push-files` route.
