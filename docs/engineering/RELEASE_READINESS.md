# Release Readiness — Accountix v1.0 Gate

Date: 2026-11-03 (Sprint 10, Phase 10 — Production Hardening).
Environment where evidence was produced: Linux dev machine,
Python 3.12.3 (project venv) and Python 3.13.18 (uv-installed,
scratch venv), Django 5.2.18, SQLite (in-memory tests + file DB),
PostgreSQL 16.2 (embedded binaries via the `pgserver` pip package,
run as a dedicated local instance on 127.0.0.1:54329 — no system
PostgreSQL and no Docker exist on this machine; `apt-get update`
was started but the embedded route succeeded first and superseded it).

Every status below is backed by the command and result quoted.
"NOT VERIFIED" means exactly that — it was not run here, and no
wording in this document should be read as claiming otherwise.

## Gate table

| # | Gate | Status | Evidence (2026-11-03) |
|---|------|--------|-----------------------|
| 1 | Test suite — SQLite, Python 3.12 | PASS | `.venv/bin/python -m pytest` → **202 passed, 3 skipped** (the 3 skips are the PostgreSQL-only concurrency tests, skipping by design) |
| 2 | Test suite — PostgreSQL 16.2, Python 3.12 | PASS | `DATABASE_URL=postgresql://postgres@127.0.0.1:54329/accountix_test .venv/bin/python -m pytest --ds=config.settings.postgres_test` → **205 passed** |
| 3 | Concurrency invariants (PostgreSQL, threaded) | PASS (after fixes) | `test_concurrency_pg.py` → **3 passed**, repeated 3× plus full-suite runs. Pre-fix evidence: journal-idempotency race FAILED (loser got a raw `IntegrityError`; no duplicate was created — the constraint held), stock race FAILED critically (two invoices of 8 against stock of 10 **both posted**), allocation race passed unmodified. Fixes in ADR-037; no assertion was weakened |
| 4 | Migrations clean | PASS | `manage.py makemigrations --check --dry-run` → "No changes detected" (this sprint added no models) |
| 5 | Django deploy checks — production settings | PASS with 1 accepted warning | With a proper ≥50-char secret: only `security.W021` (HSTS preload not enabled). W021 is accepted: submitting a domain to the browser preload list is an operator decision at deploy time, not a code default. (With a short test secret, W009 also fires — an operator secret-quality issue, already guarded by production.py refusing the dev key) |
| 6 | Django deploy checks — standalone settings | ACCEPTED BY DESIGN | 4 warnings (W004 HSTS, W008 SSL redirect, W012/W016 Secure cookies), each a direct consequence of ADR-033: standalone serves plain HTTP on 127.0.0.1 only, where HSTS/SSL-redirect/Secure cookies would break the app. Never expose the standalone server beyond loopback |
| 7 | Dependency audit (pip-audit) | PASS with 1 documented exception | Initially: 7 findings in 2 packages. **djangorestframework 3.16.1 → 3.18.3** (pin widened to `>=3.18,<3.19`) fixes all 5 DRF findings (incl. CVE-2026-73228, CVE-2026-73229); DRF exposes no API endpoints and `rest_framework.authtoken` is not installed, so exposure was already minimal; full suite re-run green after the upgrade. Remaining: **pytest 8.4.2, PYSEC-2026-1845 / CVE-2025-71176** (predictable `/tmp/pytest-of-{user}` dirs; local DoS class). Dev-only tool, never shipped in the bundle; the fix requires pytest 9 (major) — accepted for v1.0, upgrade scheduled with the pytest-9 compatibility pass |
| 8 | Type checking (mypy + django-stubs) | PASS | Config in `pyproject.toml` (`[tool.mypy]`), run: `cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .` → **"Success: no issues found in 139 source files"**. Before triage: 13 errors in 5 files — 10 fixed in code (a `Mapping` annotation in `config/paths.py`; `ClassVar` annotations on the sales line-guard mixin), 3 baselined as per-module `ignore_missing_imports` for waitress/openpyxl, which ship neither stubs nor `py.typed`. No blanket suppressions |
| 9 | Python 3.12 verified | PASS | System interpreter of the dev machine; all suites above |
| 10 | Python 3.13 verified | PASS | Python **3.13.18** (uv `python install 3.13` into a scratch dir; the 3.12 venv was not touched): full suite → **202 passed, 3 skipped** on SQLite; concurrency module on PostgreSQL → **3 passed** |
| 11 | Launcher smoke — source mode (Linux) | PASS | `scripts/smoke_standalone.sh` re-run in Sprint 10 → "SMOKE OK" (fresh launch, second-launch pre-migration backup, health OK, clean shutdown) |
| 12 | Launcher smoke — frozen PyInstaller bundle (Linux) | PASS (Sprint 09) | Built and smoke-run in Sprint 09 (`/health/`, `/login/`, static all 200). Not rebuilt in Sprint 10; Sprint 10 code changes are service-layer only, but a rebuild is part of cutting the actual release artifacts |
| 13 | Backup/restore round-trip — SQLite | PASS | Sprint 09 subprocess round-trip tests (refusal without `--confirm`, pre-restore backup, data restored) — still green in the suite |
| 14 | Backup — PostgreSQL (`backup_db` via pg_dump) | PASS | Against the local PG 16.2: `manage.py backup_db --output …` → "Backup written: … (217379 bytes)"; `pg_restore --list` reads the archive (473 TOC entries). First time this path has ever executed |
| 15 | Restore — PostgreSQL | NOT VERIFIED | Deliberately an operational `pg_restore` procedure (ADR-035); it has never been executed. Run it once in staging before relying on PostgreSQL backups |
| 16 | Windows bundle | NOT VERIFIED | No Windows machine exists in this environment. Build script and launcher are written and platform-neutral (Sprint 09), the bundle has never been built or run on Windows |
| 17 | Membership scoping of views/exports/prints | PASS | All `views.py` modules use `login_required`; every list/detail/export/print queryset is filtered by `user_company_ids` (spot-verified for the Sprint 08/09 surfaces: reporting exports, print views, stock movements). Isolation is covered by tests across sprints (non-member detail/export → 404, cross-company lists empty). Greps: `csrf_exempt` → 0 hits; `.raw(`/`.extra(`/`cursor.execute` → 0 hits |
| 18 | Password validation | PASS (after fix) | Finding: `AUTH_PASSWORD_VALIDATORS` was **absent** — Django applied none. Fix: the four standard validators now configured in `config/settings/base.py`, pinned by 5 new tests in `apps/users/tests/test_security_settings.py` |
| 19 | Secrets hygiene | PASS | No committed secrets (grep: only env lookups, the dev placeholder that production refuses, and test-only keys). `.gitignore` covers `.env`, `*.sqlite3`, and — added in Sprint 10 — `secret_key.txt` and `backups/` |
| 20 | Login rate limiting | GAP (documented) | **Not implemented.** No throttling exists on `/login/`. Acceptable for the standalone loopback scope (single-user machine, OS account is the boundary); **blocking for any internet-facing or multi-user LAN deployment** — recommendation: reverse-proxy rate limiting or `django-axes` before such a deployment |
| 21 | Performance smoke (dev machine) | PASS | `scripts/perf_smoke.py` (file SQLite; 200 journal entries, 50 posted sales invoices): trial balance 1 query / ~3 ms; stock balances 1 query / ~1 ms; dashboard 17 queries / ~26 ms (service), ~30 ms per warm HTTP request. One real N+1 found and fixed: treasury `open_items` ran 2 aggregates per invoice (dashboard = 116 queries); grouped rewrite → constant query count, pinned by `test_open_items_queries.py`. Nothing exceeded 2 s; numbers are dev-machine only |
| 22 | Docs match reality | PASS | README, CURRENT_STATE, PRODUCTION, this document and SPRINT_10_REPORT updated in Sprint 10 |

## Verdict

**Ready with documented limitations** — for the v1.0 scope stated
below. This is not an unqualified "ready for v1.0":

The accounting/inventory/treasury engine, the standalone packaging,
and the backup story are verified on SQLite **and** PostgreSQL, on
Python 3.12 **and** 3.13, including the concurrency invariants that
had never been exercised before this sprint (two real defects were
found and fixed with tests — see gate 3). What keeps this from a
clean "Ready" is the limitation list, headed by the UI scope:

### Blocking / high-severity limitations (must be understood before calling this v1.0)

1. **The web UI is read-only for business documents.** Setup forms
   exist for companies, fiscal years and chart-of-accounts, and
   everything else operational — sales/purchase invoices, payments,
   cheques, stock documents — is list/detail/print/export only.
   Documents are created and posted through the service layer /
   Django admin, not through web forms. If "v1.0" is expected to be
   an end-user product where staff key in invoices in the browser,
   the verdict for that expectation is **Not ready** until a
   data-entry UI sprint lands. As a verified engine + admin-driven
   system, it is ready with this limitation stated.
2. **Windows is unverified** (gate 16). The primary target market
   runs Windows; the bundle must be built and smoke-tested on a real
   Windows machine before any Windows distribution claim.
3. **No login rate limiting** (gate 20) — blocks internet-facing
   deployment, not the loopback standalone scope.

### Other documented limitations

4. PostgreSQL restore never executed (gate 15); PostgreSQL backup
   verified once, on the embedded 16.2 instance.
5. pytest dev-only CVE accepted (gate 7).
6. Frozen Linux bundle not rebuilt after Sprint 10's service-layer
   fixes (gate 12) — rebuild when cutting release artifacts.
7. Performance figures are single-machine SQLite smoke numbers, not
   a load test; no PostgreSQL performance pass was run.

## What v1.0 explicitly does NOT include

- Data-entry web forms for business documents (see limitation 1)
- Bank reconciliation; cheque books
- Jalali (Persian calendar) display dates; `.po` translation files
  (UI strings are Persian-first in templates; English locale exists
  as settings, not as translated content)
- Tailwind/HTMX/Alpine front-end stack (ADR-006 debt: hand-written
  CSS, server-rendered pages)
- A public REST API (DRF is installed, secured and current, and
  exposes no endpoints)
- Native PDF generation (print-to-PDF via the browser, ADR-032)
- Login rate limiting / account lockout
- Role-based permissions beyond company membership (roles exist as
  data only)
- Additional (landed) purchase costs (ADR-017) and purchase price
  variance booking (ADR-018)
- Backdated stock revaluation (movements apply in posting order)
