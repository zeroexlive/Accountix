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
  remains an operational `pg_restore` procedure that has **never been
  executed** — run a restore drill in staging before trusting it.
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
verified once (above); PostgreSQL restore is documented-but-unrun.

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
