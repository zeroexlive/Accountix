# Sprint 17 Report — PostgreSQL Restore Drill (staging)

Date: 2026-11-03. Environment: Linux, Python 3.12.3 (project venv),
Django 5.2, PostgreSQL 16.2 (embedded `pgserver` 0.1.4 binaries from
the project venv — the Sprint 10 route; no system PostgreSQL exists
on this machine). Base: Sprint 16 complete (326 tests). This sprint
is an **operations drill**, not a feature sprint: it executes, for
the first time ever, release gate #15 of `RELEASE_READINESS.md`
("Restore — PostgreSQL: NOT VERIFIED — deliberately an operational
`pg_restore` procedure (ADR-035); it has never been executed").
The readiness document itself is a Sprint 10 artifact and is **not**
edited; the closure is recorded here and in `CURRENT_STATE.md`,
following the Sprint 12/16 precedent. All drill artifacts (cluster,
scripts, snapshots, dump) live outside the repo in
`~/workspace/drill-pg17/`; nothing drill-specific is committed.

## Environment (as stood up)

- Cluster initialised with the bundled `initdb` and run with
  `pg_ctl` as a dedicated `pgserver` system user (recreated — it
  had not survived since Sprint 10; the Sprint 10 `chmod o+rX` fix
  on the package dirs was reapplied), listening on 127.0.0.1:54329,
  trust auth (throwaway staging only). `SELECT version()` →
  **PostgreSQL 16.2** on x86_64-pc-linux-gnu.
- Production shape as closely as the embedded server allows: a
  dedicated login role `accountix` owning both databases
  (`accountix_drill_src`, `accountix_drill_dst`); the app connected
  as that role via `DATABASE_URL` with
  `config.settings.postgres_test` (base settings + `DATABASE_URL`,
  the documented PG profile).
- `manage.py migrate` applied all 48 migrations (incl.
  `axes.0001`–`0010`, `treasury.0003`) — verified directly in the
  database: 58 public tables, 48 `django_migrations` rows.
  (Drill-log note: this session's first, backgrounded `migrate`
  invocation reported success but its effects were not present when
  the database was inspected; the migration was re-run in the
  foreground and verified by table count before seeding. A tooling
  artifact of the session, not an application issue — every later
  step was verified against the database itself.)

## Implemented

- **The drill itself** (below), executed end to end against a real
  PostgreSQL with data seeded exclusively through the app's own
  service layer.
- **Documentation fix — the restore procedure now exists.**
  PRODUCTION.md previously called PostgreSQL restore
  "documented-but-unrun", but a full-text search of the repo found
  **no procedure at all**: no `pg_restore` invocation, no flags, no
  target-database step (the only mentions were ADR-035's one-line
  definition and the gate table's "never been executed"). An
  operator following the docs would have had to improvise the whole
  restore. PRODUCTION.md now carries a "PostgreSQL backup & restore"
  section with the exact drill-verified commands (backup,
  `pg_restore --list` sanity check, create-empty-target,
  `pg_restore --clean --if-exists`, `manage.py check` + login
  verification), and its two stale status passages ("never been
  executed", "documented-but-unrun") are corrected.
- **Code fix (one line) — `backup_db`'s default PostgreSQL filename
  no longer lies.** Without `--output`, the command wrote the
  custom-format (binary) `pg_dump` archive to
  `accountix-<timestamp>.sql`. A `.sql` name invites the classic
  operator error of feeding the archive to `psql`. It now writes
  `accountix-<timestamp>.dump`; the misleading-name rationale is in
  a code comment and the behaviour is pinned by a new test
  (`test_postgres_default_backup_name_is_dump_not_sql`, pg_dump
  mocked — the live path is this drill).

## Tested (the drill, step by step, with evidence)

1. **Seed (source DB, via services only)** — mirroring the test
   suite's own seed path (`treasury/tests/_helpers.py`): superuser
   + company OWNER user; company + FY2026 + open period; 12-account
   chart; supplier/customer, product, warehouse; cash + bank
   treasury accounts; purchase invoice posted (10 @ 100 + 10% tax =
   1100); sales invoice posted (4 @ 250 + 10% = 1100); a bank
   receipt of 1100 posted and allocated → sale **PAID**; a
   25-leaf cheque book on the bank account and an issued cheque of
   500 consuming leaf **1001** (leaf → USED), posted and allocated
   → purchase **PARTIALLY_PAID**; one posted manual journal
   (Dr expense 75 / Cr cash 75); one failed login so the axes
   tables carry a real row (`axes_accessattempt` = 1).
2. **Baseline fingerprint (source)** — scripted, deterministic:
   row counts for all **58 tables (420 rows total)**; trial balance
   via the reporting service: **4275.00 debit = 4275.00 credit,
   balanced** (hand-checkable from the seed: 1100 purchase + 1100
   sale + 400 COGS + 1100 receipt + 500 cheque + 75 journal); stock
   balance **6 units, value 600.00, MWAC 100**; sale PAID; purchase
   PARTIALLY_PAID; leaf 1001 USED linked to cheque "1001".
3. **Backup (documented path)** — `manage.py backup_db --output
   accountix-drill.dump` (pg_dump/pg_restore from the bundled
   binaries on PATH): "Backup written: … (258443 bytes)", exit 0,
   ≈0.9 s wall clock for the whole management command.
   `pg_restore --list`: **546 TOC entries**, format CUSTOM, dumped
   from/by PostgreSQL 16.2, empty stderr.
4. **`restore_db` PostgreSQL path (also-ran)** — pointed at the PG
   configuration with `--confirm`, it refuses cleanly and changes
   nothing: `CommandError: restore_db currently supports SQLite
   only; use pg_restore for PostgreSQL.` (exit 1). Verdict: the
   command is honest, not a dead path — the dead end was its
   pointer target (PRODUCTION.md) lacking the procedure, fixed
   above.
5. **Restore (ADR-035 procedure)** — fresh empty
   `accountix_drill_dst` created (owner `accountix`), then exactly:

   ```
   pg_restore --clean --if-exists \
       -d postgresql://accountix@127.0.0.1:54329/accountix_drill_dst \
       accountix-drill.dump
   ```

   **Exit code 0; stdout and stderr both completely empty** —
   nothing to classify: with `--if-exists`, restoring into an empty
   database produces no drop errors and no warnings, and exit 0
   certifies no object failed. Wall clock **19.65 s** (measured
   around the `pg_restore` process; on this embedded instance the
   time is DDL/index work — the dataset is 420 rows, so do not read
   it as a data-throughput figure).
6. **App-level verification (restored DB)** —
   - `manage.py check`: "System check identified no issues".
   - The identical fingerprint script re-run against the restored
     database: **byte-identical JSON to the source baseline** —
     every table count, TB totals, stock, both payment statuses,
     leaf status/link. No differences, itemised or otherwise.
   - Real login through the test client with the seeded company
     user's restored credentials: POST /login/ → **302**;
     GET / (dashboard) → **200**; GET the seeded sales invoice's
     detail page → **200**.
   - Sequence sanity: a NEW journal entry posted successfully in
     the restored database (status POSTED); a post-restore failed
     login wrote new axes rows with no key collisions
     (`axes_accessattempt` sequence advanced to id 3,
     `axes_accesslog` ids 1–2 from the restored logins,
     `django_migrations` max(id) 48, sessions created). No manual
     sequence repair was needed anywhere.
7. **Regression gates** (for the one-line code fix): full suite
   **327 passed, 3 skipped** on SQLite (326 baseline + the new
   backup-name test; exit code 0), mypy clean (169 files),
   `ruff check` clean, `ruff format --check` clean (169 files).

## Partially implemented / accepted

- The staging instance is an embedded single-node PostgreSQL 16.2
  on the dev VM with trust auth and drill-only credentials — the
  same "real server, not a production-sized deployment" caveat
  Sprint 10 recorded. The procedure is server-shape-independent
  (createdb + pg_restore + check), but a drill against the real
  production host remains an operator task at deploy time.
- Restore timing (19.65 s) reflects this VM's embedded instance;
  the dataset is deliberately small (420 rows). A volumetrics drill
  (millions of journal lines) was not in scope.

## Planned / not started

- **Windows bundle verification** — now the *only* remaining
  NOT VERIFIED release-gate item; it needs a Windows machine, which
  this environment does not have.
- The PyInstaller bundle has not been rebuilt since Sprint 11; it
  predates the data-entry UI, Jalali display, cheque books, axes
  and this sprint's docs. Rebuilding + smoke-running it is the
  natural Sprint 18.

## Blocked

- Nothing.

## GitHub sync

Docs + the one-line fix + its test, synced as ONE commit via the
connector's `github push-files` subcommand (hash and blob-SHA
verification recorded in the executor's handoff, not pre-claimed
here).

## Handoff notes for Jason

- Nothing to run after pulling: no migrations, no behaviour change
  except that a default-named PostgreSQL backup file now ends in
  `.dump` instead of `.sql` (same binary content).
- Operating a real restore: follow "PostgreSQL backup & restore"
  in `docs/deployment/PRODUCTION.md` — it is now the exact
  procedure this drill executed and verified.
