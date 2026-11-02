# Production deployment — Planned.
Target shape: HTTPS reverse proxy → Waitress/Gunicorn-class WSGI server →
Django (`config.settings.production`) → PostgreSQL (`DATABASE_URL`).
Production settings already refuse the dev secret key and enable secure
cookies/HSTS.

Backup/restore (§19) status after Sprint 09: SQLite backup/restore is
implemented and tested (see LOCAL.md). `backup_db` also implements the
PostgreSQL path via `pg_dump`, and restore for PostgreSQL is an
operational `pg_restore` procedure — **neither has been exercised on a
machine with PostgreSQL installed**; treat them as unverified until the
Phase 10 hardening sprint runs them for real.

Do not deploy real financial data until Phase 10 hardening is complete.
