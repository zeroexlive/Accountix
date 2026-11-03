# Production deployment

Target shape: HTTPS reverse proxy → Waitress/Gunicorn-class WSGI server →
Django (`config.settings.production`) → PostgreSQL (`DATABASE_URL`).
Production settings already refuse the dev secret key and enable secure
cookies/HSTS.

## Sprint 10 verification status (2026-11-03)

- The **full test suite passes against PostgreSQL 16.2** (205 tests,
  `--ds=config.settings.postgres_test` with `DATABASE_URL` set), and
  the threaded concurrency invariants hold after ADR-037. The
  PostgreSQL used was an embedded instance (the `pgserver` pip
  package) on the dev machine — a real server with real locking, but
  not a production-sized deployment.
- `backup_db`'s PostgreSQL path (`pg_dump`, custom format) **has now
  been executed** and produced a verified-readable archive. Restore
  was **executed and verified in the Sprint 17 staging drill**
  (2026-11-03): a seeded PostgreSQL 16.2 database was dumped,
  restored into a fresh empty database with the procedure below, and
  the restored database matched the source fingerprint exactly
  (all 58 table row counts, trial balance, stock, payment statuses),
  passed `manage.py check`, accepted a real login, and took new
  postings — see `docs/engineering/SPRINT_17_REPORT.md`. Release
  gate #15 is therefore VERIFIED; `RELEASE_READINESS.md` itself is a
  Sprint 10 artifact and keeps its historical table.
- Deploy check (`check --deploy`, production settings, real secret):
  the only warning is `security.W021` (HSTS preload). Preload
  submission is an operator decision; enable `SECURE_HSTS_PRELOAD`
  only when the domain and all subdomains are permanently HTTPS.
- Password validators are configured (Sprint 10 fix). Login rate
  limiting is implemented in the application with `django-axes`
  (Sprint 16, ADR-043) — see the throttling section below; an
  additional proxy-level limit stays welcome as defence in depth
  but is no longer a precondition for exposure.
- See `docs/engineering/RELEASE_READINESS.md` for the full gate table
  and the v1.0 verdict ("Ready with documented limitations").

Backup/restore (§19) status: SQLite backup/restore is implemented
and tested (see LOCAL.md). PostgreSQL backup is implemented and
verified (Sprint 10), and PostgreSQL restore is implemented as the
operational procedure below and verified end-to-end in the
Sprint 17 drill.

## Login throttling (django-axes, Sprint 16)

Failed logins are throttled in the application itself, in every
settings profile (production, standalone, local). Defaults:

- **Limit:** 5 failed attempts (`AXES_FAILURE_LIMIT` env var).
- **Scope:** the (username, IP address) combination — one user's
  failures never lock out a colleague, and one address cannot lock
  a username for the whole network.
- **Cooloff:** 1 hour (`AXES_COOLOFF_HOURS` env var, fractional
  values allowed). During the cooloff even the correct password is
  refused with the Persian lockout page (HTTP 403); further failed
  attempts extend the cooloff. A successful login resets the
  counter to zero.

**Unlocking a user:** sign in to the Django admin → *Axes → Access
attempts* and delete the locked (username, IP) row, or from a shell
on the server: `python manage.py axes_reset_ip_username <ip>
<username>` (or `python manage.py axes_reset` to clear all
attempts). Access attempts and successful logins are also listed
under *Axes → Access logs* for audit.

**Reverse proxies — read this before trusting `X-Forwarded-For`:**
by default the client IP is `REMOTE_ADDR` and forwarded headers
are ignored (django-ipware is not installed). If your proxy is the
only client the app ever sees, every user shares one throttling
identity (the proxy's address). To throttle per real client IP
behind your own proxy, opt in explicitly: install
`django-axes[ipware]`, then set `AXES_IPWARE_PROXY_COUNT`,
`AXES_IPWARE_PROXY_TRUSTED_IPS` and
`AXES_IPWARE_META_PRECEDENCE_ORDER` to match your chain — and make
sure the proxy overwrites/strips the headers from clients,
otherwise clients can spoof addresses and defeat the lockout.
Never copy someone else's header settings without that check.

## PostgreSQL backup & restore (procedure verified in the Sprint 17 drill)

PostgreSQL restore is an **operational procedure** (ADR-035), not an
app command: `restore_db` is SQLite-only by design and, pointed at a
PostgreSQL configuration, refuses with a pointer here. The backup is
a **custom-format** `pg_dump` archive — a binary file for
`pg_restore`. Never feed it to `psql`.

1. **Back up** (production settings, `DATABASE_URL` set,
   `pg_dump`/`pg_restore` on `PATH`):

   ```bash
   python backend/manage.py backup_db --output /safe/path/accountix-YYYYMMDD.dump
   pg_restore --list /safe/path/accountix-YYYYMMDD.dump   # sanity: the archive reads back
   ```

   Without `--output`, `backup_db` writes
   `backups/accountix-<timestamp>.dump` next to the working
   directory. `backup_db` shells out to
   `pg_dump --format=custom --file <dest> "$DATABASE_URL"`.

2. **Create the target database empty**, owned by the role the
   application connects as:

   ```bash
   createdb -h <host> -U postgres -O <app-role> accountix_restored
   # or: CREATE DATABASE accountix_restored OWNER <app-role>;
   ```

   Restore into a *fresh* database whenever possible; do not restore
   over the live production database.

3. **Restore** into it:

   ```bash
   pg_restore --clean --if-exists \
       -d "postgresql://<app-role>@<host>:5432/accountix_restored" \
       /safe/path/accountix-YYYYMMDD.dump
   ```

   Drill result on an empty target: **exit code 0 and no output on
   stderr at all** — `--if-exists` suppresses the "object does not
   exist" drop errors a bare `--clean` would emit there. The same
   flags make the command safe to re-run over a populated target
   (objects are dropped and recreated); in that case treat any
   stderr output line by line: `pg_restore` exits non-zero only when
   an object actually failed to restore.

4. **Verify before pointing traffic at it:**

   ```bash
   DATABASE_URL=postgresql://<app-role>@<host>:5432/accountix_restored \
       python backend/manage.py check
   ```

   Then start the app against the restored database, sign in, and
   open the dashboard. Restored sequences are sane (the drill posted
   a new journal entry and wrote new login-attempt rows in the
   restored database with no key collisions), so no manual sequence
   repair is needed. If the backup predates a schema change, run
   `manage.py migrate` after the restore — the restore itself never
   migrates.
