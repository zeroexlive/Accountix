# Sprint 16 Report — Login Rate Limiting (django-axes)

Date: 2026-11-03. Environment: Linux, Python 3.12.3 (project venv),
Django 5.2, django-axes 9.0.0. Base: Sprint 15 complete (318 tests).
This sprint closes **release gate #20** of `RELEASE_READINESS.md`
("Login rate limiting — GAP (documented)… blocking for any
internet-facing or multi-user LAN deployment — recommendation:
reverse-proxy rate limiting or `django-axes`"). The readiness
document itself is a Sprint 10 artifact and is **not** edited; the
closure is recorded here and in `CURRENT_STATE.md`, following the
Sprint 12 precedent. Full rationale: **ADR-043**.

## Implemented

- **Dependency**: `django-axes>=9,<10` added to `pyproject.toml`
  (resolved: 9.0.0, the current major for Django 5.2; it ships
  `py.typed`, so no mypy baseline entry was needed). Installed
  WITHOUT the `[ipware]` extra on purpose (see IP policy below).
- **Wiring** (all in `config/settings/base.py`, inherited by test /
  local / production / standalone / postgres_test), exactly per the
  axes 9 installation docs:
  - `INSTALLED_APPS += "axes"`.
  - `AUTHENTICATION_BACKENDS = ["axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend"]` — axes' backend
    first (it monitors and refuses locked-out clients; ModelBackend
    still performs the credential check and permissions).
  - `AxesMiddleware` appended LAST in `MIDDLEWARE` (the documented
    position; it only rewrites a locked-out login response).
- **Policy** (settings block in `base.py`, env-overridable in the
  codebase's `os.environ.get` pattern):
  - `AXES_FAILURE_LIMIT = 5` (env `AXES_FAILURE_LIMIT`)
  - `AXES_COOLOFF_TIME = timedelta(hours=1)` (env `AXES_COOLOFF_HOURS`)
  - `AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]` — the
    combination: IP-only would punish a whole NAT'd office for one
    user's typos; username-only would let an attacker spray one
    account from many IPs and lock the victim out everywhere.
  - `AXES_RESET_ON_SUCCESS = True`.
  - `AXES_LOCKOUT_TEMPLATE = "registration/lockout.html"`.
  - `AXES_HTTP_RESPONSE_CODE = 403` — axes 9 changed its default
    to 429; 403 is set explicitly and pinned by tests.
  - `AXES_IPWARE_META_PRECEDENCE_ORDER = ("REMOTE_ADDR",)`.
- **Client-IP policy**: django-ipware is not installed, so axes
  resolves the client IP from `request.META["REMOTE_ADDR"]` only.
  `X-Forwarded-For` is never read/trusted by default — a client
  cannot spoof its way out of (or into) a lockout. A reverse-proxy
  deployment must opt in explicitly (ipware extra + proxy count /
  trusted IPs / meta order); documented in ADR-043 and
  `docs/deployment/PRODUCTION.md`.
- **Lockout UX**: new `templates/registration/lockout.html` — the
  same auth-card layout as the Sprint 11 login page, Persian text
  («ورود موقتاً مسدود شد»), explains the temporary block and the
  admin-contact route, links back to login, echoes **no username**
  and no countdown/internal counters. Below the limit, a failed
  login renders exactly the same form error as before this sprint.
- **Ops surface (no custom code)**: axes' admin is registered as
  shipped (Access attempts / Access logs, verified by test); an
  admin unlocks by deleting the attempt row there, or via
  `manage.py axes_reset_ip_username <ip> <username>` /
  `axes_reset`. `docs/deployment/PRODUCTION.md` gained the
  throttling section (defaults, env overrides, proxy opt-in
  warning, unlock procedure) and its stale "no login rate
  limiting" bullet was corrected.
- **Docs**: ADR-043 appended to `DECISIONS.md`; `CURRENT_STATE.md`
  updated (§2 Sprint 16 entry, §6 gap removed, §9 count 326 +
  Sprint 16 tally, §10 candidate struck); README status line and
  test count updated. `RELEASE_READINESS.md` untouched.

## Tested (exact evidence)

New file `backend/apps/users/tests/test_login_throttling.py`
(8 tests), all through the real login view with the test client:

- **(a) Below limit + reset-on-success**: 4 wrong passwords → each
  HTTP 200 with the normal Persian form error, no lockout marker;
  correct password → 302 and `AccessAttempt` rows are gone (counter
  reset proven in the DB); after logout, 4 more wrong passwords
  still do not lock (they would total 8 ≥ 5 without the reset) and
  a correct login succeeds again.
- **(b) Lockout at the limit**: the 5th wrong password returns
  **HTTP 403** with the lockout page (marker «مسدود», normal form
  error absent, username not echoed in the body); the correct
  password during the cooloff returns 403 with the lockout page
  again, and the client is not authenticated afterwards
  (dashboard still redirects to login).
- **(c) Cooloff expiry**: after lockout, ageing the stored
  attempt's `attempt_time` past the 1-hour cooloff lets the correct
  password in (302).
- **(d) Scoping**: with (jason, 127.0.0.1) locked, jason logs in
  from a different `REMOTE_ADDR` (302), a different user logs in
  from the locked IP (302), and the locked combination itself is
  still refused (403).
- **(f) Settings smoke**: `config.settings.production` and
  `config.settings.standalone` are imported in clean subprocesses
  (production with a `DJANGO_SECRET_KEY`, standalone with a temp
  `ACCOUNTIX_DATA_DIR`) and report axes installed, the middleware
  last, the backend first, limit 5 and the combination parameters;
  a third subprocess proves `AXES_FAILURE_LIMIT=7` in the
  environment overrides the default.
- **(g) Admin registration**: `AccessAttempt` and `AccessLog` are
  in `admin.site._registry` (axes' shipped admin, unmodified).

Commands (repo root, 2026-11-03):

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **326 passed, 3 skipped** (318 baseline + 8 new; 3 skips = PG-only concurrency tests) |
| `manage.py check` under test / local / postgres_test / production / standalone settings | "System check identified no issues" under **all five** (no axes W00x warnings) |
| `manage.py makemigrations --check --dry-run` | "No changes detected" — no project model changes; axes' own 10 migrations are package files (applied cleanly to the dev DB: `axes.0001`…`axes.0010`) |
| `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` | "Success: no issues found in 169 source files" |
| `ruff check backend` / `ruff format --check backend` | clean / 169 files formatted |

## Partially implemented / accepted

- **Test-client compatibility (the one friction found):**
  `Client.login()` calls `authenticate()` with no HTTP request,
  which `AxesStandaloneBackend` refuses by design
  (`AxesBackendRequestParameterRequired`). Blast radius measured by
  a full-suite run: exactly **2 failures**, both in
  `test_auth.py` — the rest of the suite already uses
  `force_login()`. Countermeasure (minimal, no production shim, no
  conftest hack): those two tests now POST real credentials
  through the login view — same assertions' intent, stronger
  evidence. Axes state cannot leak between tests: every test runs
  in its own pytest-django transaction and no other test posts a
  wrong password (grepped).
- Failed attempts made *during* a lockout extend the cooloff
  (axes' documented default
  `AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT=True`) — accepted
  as the anti-spray behaviour; an admin reset is the escape hatch.

## Planned / not started

- PG restore drill (staging) and Windows bundle verification —
  the two remaining NOT VERIFIED items of the release gate;
  unchanged by this sprint.
- Optional future work: per-deployment tuning of the limit/cooloff
  needs no code (env vars); progressive lockout tiers
  (`AXES_LOCKOUT_TIERS`) exist in axes 9 if ever wanted.

## Blocked

- Nothing.

## GitHub sync

- One commit via the connector's dedicated `github push-files`
  subcommand — message "Sprint 16: login rate limiting with
  django-axes (gate #20)" — with blob-SHA read-back verification
  (details in the executor's handoff; sync outcome recorded
  there, not pre-claimed here).

## Handoff notes for Jason

- **Run `manage.py migrate` once after pulling** — it creates the
  `axes_*` tables (package migrations `axes.0001`–`0010`); the
  standalone launcher migrates automatically as always.
- Behaviour change to expect: after 5 wrong passwords, that
  username+IP pair is locked for an hour and even the right
  password is refused with a Persian lockout page; unlock early
  via admin → Axes → Access attempts (delete the row) or
  `manage.py axes_reset_ip_username <ip> <username>`.
