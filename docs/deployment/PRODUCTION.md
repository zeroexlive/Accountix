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
- Password validators are configured (Sprint 10 fix). There is **no
  login rate limiting**: put rate limiting at the reverse proxy (or
  add `django-axes`) before exposing the app beyond a trusted LAN.
- See `docs/engineering/RELEASE_READINESS.md` for the full gate table
  and the v1.0 verdict ("Ready with documented limitations").

Backup/restore (§19) status: SQLite backup/restore is implemented
and tested (see LOCAL.md). PostgreSQL backup is implemented and
verified once (above); PostgreSQL restore is documented-but-unrun.
