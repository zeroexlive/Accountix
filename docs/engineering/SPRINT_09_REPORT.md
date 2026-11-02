# Sprint 09 Report — Desktop Packaging & Backup (Phase 9)

Date: 2026-11-03. Environment: Linux, Python 3.12.3, Django 5.2.18.
Base: Sprint 08 complete (181 tests). This sprint makes Accountix
runnable as an offline-first desktop application and implements
backup/recovery (§19).

## Implemented

- **Shared data-location helper** (`backend/config/paths.py`): the one
  place that resolves the per-user data directory
  (`ACCOUNTIX_DATA_DIR` override → Windows `%LOCALAPPDATA%\Accountix`,
  macOS `~/Library/Application Support/Accountix`, Linux
  `$XDG_DATA_HOME/accountix` / `~/.local/share/accountix`), the DB /
  secret / backup / log / lock / static paths inside it, port
  resolution (`ACCOUNTIX_PORT`, default **8765**), health/login URLs,
  and the generate-once SECRET_KEY bootstrap (file mode 0600 where
  supported, never committed).
- **Standalone settings** (`config/settings/standalone.py`, ADR-033):
  DEBUG off, `ALLOWED_HOSTS=[127.0.0.1, localhost]`, SQLite in the data
  directory, SECRET_KEY from the data-dir key file, static collected
  into the data directory and served by **WhiteNoise** (added pinned,
  `whitenoise>=6.0,<7.0`). Cookies intentionally not Secure on loopback
  HTTP (production settings keep the Secure/HSTS posture for HTTPS).
- **Server entrypoint** (`backend/serve.py`): Waitress, bound to
  127.0.0.1 only, threads via `ACCOUNTIX_THREADS` (default 8). It only
  serves — migrations are the launcher's job.
- **Launcher** (`launcher/accountix_launcher.py`, ADR-034): resolves
  and creates the data dir; single-instance check via `/health/` (if
  it answers, open the browser and exit 0) with a pid lock file as a
  secondary guard (a live lock holder that never becomes healthy is
  reported with the remedy, not silently overridden); ensures the
  secret; **backs up an existing database and aborts untouched if the
  backup fails**; migrates; collects static; starts the server
  (subprocess from source, in-process thread when frozen); polls
  `/health/` up to 30 s; opens the browser (suppress with
  `--no-browser` / `ACCOUNTIX_NO_BROWSER=1`); clean shutdown on
  Ctrl+C/SIGTERM via explicitly installed signal handlers; everything
  also appended to `accountix.log` in the data dir.
- **Backup & restore** (`apps/core/backup.py` +
  `backup_db` / `restore_db` management commands, ADR-035):
  SQLite copies via the sqlite3 backup API into
  `<db dir>/backups/accountix-<YYYYMMDD-HHMMSS>.sqlite3`, verified by
  `PRAGMA integrity_check` + table count before success is claimed;
  `--keep N` prunes to the newest N. `restore_db` refuses without
  `--confirm`, verifies the input, first backs the current DB up to
  `pre-restore-<timestamp>`, replaces via a verified staging copy,
  runs Django's system check, and *reports* pending migrations without
  applying them. PostgreSQL: `backup_db` shells to `pg_dump`
  (implemented); restore stays an operational `pg_restore` procedure.
- **Packaging**: `launcher/accountix.spec` (onedir; templates/static/
  locale as files; `apps`/`config` collected as hidden imports) +
  `scripts/build_linux.sh` + `scripts/build_windows.bat`.
- **Docs**: deployment guides rewritten to reality (LOCAL, LINUX,
  WINDOWS, PRODUCTION), new `docs/deployment/UPGRADE.md` (ADR-036:
  the upgrade is "start the new launcher"; recovery is `restore_db`),
  ADR-033…036, README standalone quickstart.

## Tested (this machine, exact evidence)

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **196 passed, 0 failed** (181 prior + 15 new) |
| `manage.py check --settings=config.settings.test` | "System check identified no issues (0 silenced)" |
| `manage.py makemigrations --check --dry-run` | "No changes detected" (no new models this sprint) |
| `ruff check backend launcher tests` | "All checks passed!" |
| `ruff format --check backend launcher tests` | clean (143 files) |

New tests (15): per-OS data-dir resolution (env override, XDG,
Windows, macOS), secret created-once-and-reused, standalone settings
(data-dir DB path, DEBUG off, loopback hosts, WhiteNoise present, key
file matches settings), launcher pure logic (`needs_backup`,
browser decision), `wait_for_health` with an injected clock, and
`health_ok` against a real stub HTTP server; backup helpers
(round-trip copy + verify, missing-file rejection, naming + prune);
and a **subprocess round-trip of the real commands** on a temporary
data directory: migrate → create company → `backup_db` → mutate
(delete + junk company) → `restore_db` without `--confirm` refuses and
changes nothing → `restore_db --confirm` restores the original company
and leaves a `pre-restore-*` backup behind.

### Launcher smoke test (scripted, `scripts/smoke_standalone.sh`)

Ran green (exit 0, ~10 s). Verbatim key lines:

```
== first launch (fresh database)
[...] No existing database — first run, skipping backup.
[...] 164 static files copied to '/tmp/accountix-smoke-…/staticfiles', 154 post-processed.
[...] Server subprocess started (pid 12109).
[...] Accountix is ready at http://127.0.0.1:8877
health: {"status": "ok"}
login page: served
present: db.sqlite3 / secret_key.txt / accountix.log
[...] Interrupted — shutting down. / Server subprocess stopped.
== second launch (existing database -> backup expected)
[...] Existing database found — creating a pre-migration backup...
[...]   Backup written: /tmp/accountix-smoke-…/backups/accountix-20261103-013004.sqlite3 (1159168 bytes)
[...] Accountix is ready at http://127.0.0.1:8877
SMOKE OK
```

**Bug found by this smoke test and fixed:** the first run hung —
shells mask SIGINT for background jobs, Python inherits the mask, and
the launcher waiting on its server subprocess never saw Ctrl+C. The
launcher now installs explicit SIGINT/SIGTERM handlers (ADR-034); the
rerun shut down cleanly on SIGINT both times.

### PyInstaller — Linux: BUILT AND SMOKE-RUN (real, not theoretical)

- `pyinstaller launcher/accountix.spec` (PyInstaller 6.22.3) → build
  completed; `dist/accountix/accountix` (onedir).
- Two build defects were found by actually running the bundle and
  fixed: (1) `collect_submodules` in the spec resolved against the
  build interpreter's `sys.path`, silently omitting `config.settings.*`
  — fixed by inserting the backend dir into `sys.path` in the spec;
  (2) bundle data destinations kept a `backend/` prefix while Django's
  frozen `BASE_DIR` resolves to the bundle root, so templates were not
  found — fixed by mapping template/static/locale data to the bundle
  root.
- Frozen smoke (fresh data dir, port 8878): in-process migrate →
  `/health/` → `{"status": "ok"}`; `/login/` → **200**;
  `/static/css/app.css` → **200** (WhiteNoise from collected static);
  SIGINT → stopped cleanly. Second launch: in-process `backup_db`
  wrote `accountix-20261103-013607.sqlite3` (1159168 bytes) before
  migrating; health OK again.

## Partially implemented / written-but-untested

- **Windows: written only.** The launcher and spec are
  platform-neutral and `paths.py` implements the Windows data dir,
  but no Windows machine was available: `scripts/build_windows.bat`
  has never run, the frozen Windows binary has never been built or
  smoke-tested, and there is no installer (Inno Setup/MSI). Do not
  present Windows support as verified.
- **Frozen mode on Linux** is verified for the flows above (source and
  frozen share the launcher; frozen uses the in-process branch).
  Anything beyond — e.g. the already-running single-instance path
  inside a bundle, antivirus interference, code signing — is untested.
- **PostgreSQL backup/restore**: `pg_dump` path implemented in
  `backup_db`; this machine has no PostgreSQL/pg_dump, so it has
  never executed. SQLite is the only verified database path.
- Launcher UI strings are English log lines; the application UI
  remains Persian-first as before.

## Planned / not started

- Windows build + smoke on a real Windows machine; an installer.
- Release readiness (Phase 10): security review, PostgreSQL run and
  concurrency tests, type checking (pyright/mypy still not run),
  Python 3.13 verification, `docs/engineering/RELEASE_READINESS.md`.
- The Sprint 01 leftover files on GitHub (unchanged by this sprint).

## Security considerations

Standalone binds loopback only; the secret key is generated per
installation into the data directory and never committed; backup and
log files live in the same per-user directory as the database (OS
account permissions are the access control, same as the DB itself);
`restore_db`'s `--confirm` + automatic pre-restore backup guard the
one destructive operation in this sprint. Note the standalone cookie
posture (ADR-033) is a loopback-only decision — never expose the
standalone server through a proxy without switching to the production
settings.

## Recommended next phase — Sprint 10 (Production Hardening, Phase 10)

Security review, a real PostgreSQL run with concurrency tests, type
checking, Python 3.13 verification, Windows bundle verification, and
the formal `RELEASE_READINESS.md` gate before any v1.0 claim.
