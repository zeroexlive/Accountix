# Sprint 10 Report — Production Hardening & Release Gate (Phase 10)

Date: 2026-11-03. Environment: Linux, Python 3.12.3 (project venv) +
3.13.18 (scratch venv), Django 5.2.18.
Base: Sprint 09 complete (196 tests). This sprint is a **gate**, not a
feature sprint: it exercised the quality gates that had never been run
(PostgreSQL, concurrency, type checking, deploy checks, dependency
audit), fixed what was small and principled, and wrote the formal
`RELEASE_READINESS.md`. Verdict: **Ready with documented limitations**
(scoped — see the readiness document; the headline limitation is that
the web UI is read-only for business documents).

## Implemented (fixes)

- **Concurrency fix — stock overselling (CRITICAL, ADR-037).**
  `post_stock_document` now locks the warehouse row(s)
  (`select_for_update`, pk order) before planning movements. Before
  the fix, two concurrent sales invoices of 8 units against 10 in
  stock **both posted** on PostgreSQL.
- **Concurrency fix — journal idempotency (ADR-037).**
  `post_journal_entry` wraps entry creation in a savepoint when an
  idempotency key is present and returns the winner's entry on
  `IntegrityError`, instead of leaking a raw database error. The
  unique constraint already prevented duplicates; the failure was
  cleanliness, not correctness.
- **Performance fix — `open_items` N+1.** Treasury open-items ran two
  allocation aggregates per invoice (dashboard: 116 queries at 50
  invoices). Rewritten with one grouped aggregate per invoice kind;
  dashboard is now 17 queries, pinned by a query-count test.
- **Security fix — password validators.** `AUTH_PASSWORD_VALIDATORS`
  was entirely absent (Django default = none). The four standard
  validators are now set in `config/settings/base.py` + 5 tests.
- **Security fix — dependency upgrade.** djangorestframework
  3.16.1 → **3.18.3** (pin `>=3.18,<3.19`), clearing all 5 pip-audit
  findings for the package; suite re-run green.
- **Type-checking gate.** mypy + django-stubs added as dev
  dependencies with config in `pyproject.toml`; 10 of the initial 13
  errors fixed in code (`Mapping` annotation in `config/paths.py`,
  `ClassVar` annotations on the sales line-guard mixin).
- **PostgreSQL test settings** (`config/settings/postgres_test.py`):
  base settings + `DATABASE_URL`, nothing else — the same code paths
  as production.
- **`.gitignore` hardening:** `secret_key.txt` and `backups/` can no
  longer be committed if a data dir is pointed inside the checkout.

## Tested (exact evidence)

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` (SQLite, 3.12) | **202 passed, 3 skipped** (196 prior + 5 security + 1 query-count; 3 skips = PG-only concurrency) |
| PG full suite (see below) | **205 passed** on PostgreSQL 16.2 |
| `pytest --ds=config.settings.postgres_test backend/apps/core/tests/test_concurrency_pg.py` | **3 passed** (×3 repeat runs + full-suite runs, no flakes) |
| Same concurrency module, pre-fix | **2 failed, 1 passed** — journal race: `IntegrityError` on the unique constraint; stock race: both invoices POSTED (oversell); allocation race: passed unmodified |
| Python 3.13.18 full suite (SQLite) | **202 passed, 3 skipped**; concurrency on PG under 3.13: **3 passed** |
| `mypy --config-file ../pyproject.toml .` (from `backend/`) | **Success: no issues in 139 source files** (13 errors in 5 files before triage) |
| `manage.py check --deploy` (production, proper secret) | 1 warning: W021 (accepted, operator decision) |
| `manage.py check --deploy` (standalone) | 4 warnings, all ADR-033 loopback consequences (accepted) |
| `pip-audit` | Before: 7 findings / 2 packages. After DRF upgrade: 1 unique finding (pytest, dev-only, documented) |
| PG `backup_db` | `Backup written: … (217379 bytes)`; `pg_restore --list` OK (473 TOC entries) — first-ever execution of the PG path |
| `scripts/perf_smoke.py` | trial balance 1 query/~3 ms; stock balances 1 query; dashboard 17 queries/~26 ms service, ~30 ms warm HTTP (was 116 queries/~67 ms) |
| `scripts/smoke_standalone.sh` (re-run) | "SMOKE OK" — Sprint 10 changes did not break standalone |
| `manage.py check` / `makemigrations --check --dry-run` | clean / "No changes detected" |
| `ruff check` + `ruff format --check` | clean (148 files) |

### How PostgreSQL was stood up (for the record)

No Docker, no system PostgreSQL binaries exist on this machine and
`apt-get update` did not complete promptly (started in the
background; the embedded route succeeded first and superseded it).
The route that worked: `pip install pgserver` (embedded PostgreSQL
16.2 binaries). Two environment fixes were needed: the bundled
`libpq` in `pgserver.libs/` was not readable by the dedicated
`pgserver` system user the package drops privileges to (fixed with
`chmod o+rX` on the package dirs), after which the cluster was
initialised and run manually with `initdb`/`pg_ctl` as that user on
127.0.0.1:54329 with trust auth, database `accountix_test`.
Python 3.13 was obtained with `pip install uv` +
`uv python install 3.13` (3.13.18) into a scratch directory; the
project's 3.12 venv was never modified for it. Sprint tooling added
to the venv (not project dependencies): `pgserver`, `uv`,
`pip-audit`.

### Concurrency results, test by test

1. **Same idempotency key, 2 threads** — pre-fix FAIL (raw
   `IntegrityError` for the loser; exactly one entry existed, so no
   data corruption) → post-fix PASS (both callers return the one
   POSTED entry).
2. **Two sales invoices drawing the same stock (8 + 8 > 10)** —
   pre-fix FAIL, both POSTED (would-be negative stock) → post-fix
   PASS (exactly one POSTED, loser gets a clean `ValidationError`,
   balance ends at quantity 2 / value 200, never negative).
3. **Two payments allocating the same invoice beyond its total** —
   PASS before and after, no change needed: `allocate_payment`
   already locked payment + invoice rows before checking totals
   (one allocation of 1000 stands, invoice PAID, loser gets
   `ValidationError`).

## Partially implemented / accepted

- **mypy baseline:** only per-module `ignore_missing_imports` for
  waitress and openpyxl (no stubs/`py.typed` exist). Everything else
  type-checks clean. Untyped function bodies are not deep-checked
  (mypy default) — enabling `check_untyped_defs` is future work.
- **HSTS preload (W021)** not enabled in code: preload submission is
  an operator decision; documented in the readiness gate.
- **pytest CVE-2025-71176** accepted for v1.0 (dev-only, fix needs
  the pytest 9 major upgrade).

## Planned / not started (post-v1.0 candidates — see readiness doc)

Data-entry UI for business documents; Windows build + smoke on a
real Windows machine (+ installer); login rate limiting
(`django-axes` or proxy-level) before any non-loopback deployment;
PostgreSQL restore drill in staging; pytest 9 upgrade; Jalali
display + `.po` translations; bank reconciliation and cheque books;
frozen-bundle rebuild with the release artifacts.

## Blocked

- **Windows verification** — no Windows machine exists in this
  environment; nothing about Windows can be evidenced from here.
- **PostgreSQL restore** — not blocked technically, but deliberately
  not executed: it is an operator procedure (ADR-035) and belongs in
  a staging drill, recorded as NOT VERIFIED in the gate.

## Security considerations (review summary)

Deploy checks triaged above; `csrf_exempt` and raw-SQL greps are
clean (0 hits); all views are `login_required` and membership-scoped
(spot-verified on the newest Sprint 08/09 surfaces; isolation tests
exist across sprints); secrets come from the environment or the
generated data-dir key file only. The one standing gap is login rate
limiting (documented in gate 20 of RELEASE_READINESS.md) — fine for
loopback standalone, blocking for internet-facing deployment.
