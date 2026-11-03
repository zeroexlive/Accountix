# Local deployment (standalone desktop mode)

Status: **implemented and smoke-tested on Linux (Sprint 09).**
For development setup see `docs/engineering/DEVELOPMENT.md`.

Standalone mode is the offline-first local installation from the master
prompt (§16–§17): one machine, SQLite, no internet needed at runtime,
the Django development server is never used.

## How it runs

```
accountix_launcher.py
  -> resolves the per-user data directory (config/paths.py)
  -> single-instance check via /health/ (+ pid lock file)
  -> SECRET_KEY file created once in the data directory
  -> backup_db (only when a database already exists)
  -> manage.py migrate            (abort on failure, DB untouched)
  -> manage.py collectstatic      (into the data directory)
  -> backend/serve.py             (Waitress, 127.0.0.1 only, default port 8765)
  -> polls /health/ -> opens the browser at /login/
```

Components:

- Settings: `backend/config/settings/standalone.py` — DEBUG off,
  `ALLOWED_HOSTS = [127.0.0.1, localhost]`, SQLite in the data
  directory, static files served by WhiteNoise from a `collectstatic`
  run into the data directory (ADR-033). Session/CSRF cookies are not
  marked Secure: the app is plain HTTP on loopback only (a Secure
  cookie would break login); public HTTPS deployments use
  `config.settings.production` instead.
- Server: `backend/serve.py` — Waitress only, binds `127.0.0.1`,
  never `0.0.0.0` by default. Port via `ACCOUNTIX_PORT`, threads via
  `ACCOUNTIX_THREADS`.
- Data directory (outside any install dir): `ACCOUNTIX_DATA_DIR`
  override, else per-OS (see LINUX.md / WINDOWS.md). Contains
  `db.sqlite3`, `secret_key.txt`, `backups/`, `staticfiles/`,
  `accountix.log`, `accountix.lock`.

## Run from source

```bash
python launcher/accountix_launcher.py            # add --no-browser / --port N as needed
```

## First run: creating the admin and the first company (Sprint 24)

On a fresh data directory there are no users yet, so the browser
the launcher opens at `/login/` is redirected to a one-time setup
page at `/setup/`: it creates the administrator (staff + superuser)
and the first company (through the same CompanyForm the companies
UI uses, with an OWNER membership) in one step and logs the admin
in. The page exists only while the user table is empty — the
moment the first user exists it redirects away for everyone, and
login is the ordinary login page again. Password rules are the
full Django validator set; nothing is created when the form is
invalid. The window is first-come-first-served by design (see
ADR-049): on a machine only the installer can reach, that is the
point; for network-exposed deployments see the warning in
PRODUCTION.md (`ACCOUNTIX_FIRST_RUN_SETUP=0` disables setup).

## Management commands through the launcher (Sprint 24)

The launcher binary doubles as the management entry point — this
is how a bundle-only recipient runs `backup_db`, `restore_db`,
`axes_reset` or `createsuperuser` without a source checkout:

```bash
accountix manage check
accountix manage createsuperuser
accountix manage backup_db
accountix manage --data-dir /other/dir axes_reset   # --data-dir right after `manage` is the launcher's
```

(In source mode the same works as
`python launcher/accountix_launcher.py manage check`.)
The command runs against the standalone data directory with the
standalone settings and its exit code is passed through. No server
is started. Stop the app before state-mutating commands
(`restore_db` above all), exactly as the next section requires
for the direct `manage.py` route.

## Backup & restore (§19)

```bash
# with DJANGO_SETTINGS_MODULE=config.settings.standalone and
# ACCOUNTIX_DATA_DIR set (the launcher's environment):
python backend/manage.py backup_db               # verified, timestamped copy in <data dir>/backups/
python backend/manage.py backup_db --keep 10     # ... and prune to the newest 10
python backend/manage.py restore_db --input <backup file> --confirm
```

`restore_db` refuses without `--confirm`, backs up the current database
to a `pre-restore-*` file first, verifies integrity before and after,
and reports (never silently applies) pending migrations. Stop the app
before restoring. See UPGRADE.md for the upgrade/recovery flow.

## Smoke test

`scripts/smoke_standalone.sh` exercises the whole path (two launches,
health + login checks, second-launch backup) against a throwaway data
directory.
