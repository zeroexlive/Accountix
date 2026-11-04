# Release Status — Accountix (current gate picture)

Date: 2026-11-03 (Sprint 29). This addendum supersedes the *status*
picture of `RELEASE_READINESS.md` (Sprint 10) without editing it:
that document stays as the historical Sprint 10 gate record, and
this file records where each gate stands now. Statuses below are
backed by the sprint reports named next to them.

## Release 1.1.0

**Released 2026-11-04** — tagged `v1.1.0`. Release notes:
`RELEASE_NOTES_1.1.0.md`. Linux artifact
`accountix-1.1.0-linux.tar.gz` (30,349,731 bytes), SHA-256
`d5367412a62bb32fe1f4a977c5eeac91d189e10174a4678ea5c16aa223e3ea4e`.
Adds guided tours, SVG dashboard charts with reduced-motion-safe
animation, and the Persian UI leak closure (Sprint 30); no database
migrations since 1.0.0. Suite at release: 476 passed, 3 skipped.

## Release 1.0.0

**Released 2026-11-04** — tagged `v1.0.0`. Release notes:
`RELEASE_NOTES_1.0.0.md`. Linux artifact
`accountix-1.0.0-linux.tar.gz`, SHA-256
`222f5777de59252bbec073c2953e7dfe1f78a4ea9da0c574dd2da692399820e3`.

## Verdict

**Release-grade on Linux; one platform gate open.** Every gate
that can be exercised in this environment is closed and verified —
including, since Sprint 29, the packaged release artifact and the
in-place upgrade path (see below). The single remaining NOT
VERIFIED item is the Windows bundle — it has never been built or
run on a Windows machine, because no Windows machine exists in
this environment.

## Gate picture (Sprint 10 numbering, current status)

| # | Gate | Status now | Closed / verified in |
|---|------|-----------|----------------------|
| 1 | Test suite — SQLite | PASS — 455 passed, 3 skipped at Sprint 28, unchanged at Sprint 29 (was 202 + 3) | every sprint; `SPRINT_28_REPORT.md` |
| 2 | Test suite — PostgreSQL 16.2 | PASS | Sprint 10 (205 passed incl. concurrency) |
| 3 | Concurrency invariants (PostgreSQL) | PASS (ADR-037 fixes) | Sprint 10 |
| 4 | Migrations clean | PASS — `makemigrations --check` at every sprint gate | ongoing |
| 5 | Deploy checks — production settings | PASS with 1 accepted warning (W021 HSTS preload — operator decision) | Sprint 10 |
| 6 | Deploy checks — standalone settings | ACCEPTED BY DESIGN (ADR-033, loopback HTTP) | Sprint 10 |
| 7 | Dependency audit | PASS with 1 accepted exception (pytest dev-only CVE, not shipped) | Sprint 10 |
| 8 | Type checking (mypy) | PASS — clean at every sprint gate (185+ files) | Sprint 10, ongoing |
| 9/10 | Python 3.12 / 3.13 verified | PASS | Sprint 10 |
| 11 | Launcher smoke — source mode (Linux) | PASS | Sprint 10 |
| 12 | Frozen Linux bundle | PASS — rebuilt + full frozen smoke in Sprints 23, 24, 26, 27, 28; since Sprint 29 also shipped as a versioned release artifact (`accountix-1.0.0-linux.tar.gz` + `.sha256`, ADR-054) and smoked from a clean extraction | Sprints 23/24/26/27/28/29 |
| 13 | Backup/restore — SQLite | PASS | Sprint 09/10 |
| 14 | Backup — PostgreSQL | PASS | Sprint 10 |
| 15 | Restore — PostgreSQL | **VERIFIED** (was NOT VERIFIED at Sprint 10) — pg_dump/pg_restore drill executed end to end; the operator procedure is written in `docs/deployment/PRODUCTION.md` | Sprint 17 |
| 16 | Windows bundle | **NOT VERIFIED** — see below | — |
| 17 | Membership scoping of views/exports/prints | PASS, extended: role-tier enforcement on every mutating endpoint (ADR-050) + members UI with last-OWNER guard (ADR-051) | Sprints 25/26 |
| 18 | Password validation | PASS — full `AUTH_PASSWORD_VALIDATORS` on setup, member creation, and self-service password change (ADR-052) | Sprints 10/24/26/27 |
| 19 | Secrets hygiene | PASS | Sprint 10 |
| 20 | Login rate limiting | **CLOSED** (was a GAP at Sprint 10) — django-axes: 5 failures, username+IP, 1 h cooloff, Persian lockout page (ADR-043) | Sprint 16 |
| 21 | Performance smoke | PASS (dev-machine SQLite numbers; no load test) | Sprint 10 |
| 22 | Docs match reality | PASS — sprint reports + CURRENT_STATE kept current every sprint; this addendum | ongoing |

## In-place upgrade — VERIFIED (Sprint 29)

**In-place upgrade: VERIFIED (Sprint 29)** — a data directory
populated by the packaged binary (setup, a members-UI user,
posted purchase/sale/receipt/journal) was copied, rolled back one
real migration (`treasury.0003`), and relaunched with the
packaged binary, which wrote the verified pre-migration backup
before applying the pending migration and left every pre-existing
figure (a Sprint 17-style fingerprint: 54 counted tables / 338
rows, trial balance 3775.00 = 3775.00, sale PAID, stock 6 units /
600.00, memberships + roles) identical afterwards, with the
pre-upgrade credentials still logging in and the re-migrated
cheque-books page loading. The release artifact itself is
`accountix-1.0.0-linux.tar.gz` (30,287,244 bytes, SHA-256
`222f5777de59252bbec073c2953e7dfe1f78a4ea9da0c574dd2da692399820e3`),
verified by `sha256sum -c` and smoked from a clean extraction;
full drill evidence in `SPRINT_29_REPORT.md`, decision record
ADR-054.

### Sprint 10 limitations — disposition

- "Web UI read-only for business documents" (the headline
  limitation): **closed** — full data-entry UI (Sprints 12–13).
- "No login rate limiting": **closed** (Sprint 16, gate 20).
- Bank reconciliation, cheque books: **shipped** (Sprints 14–15).
- Jalali display + full fa/en localization: **shipped** (Sprints
  13, 19–22).
- Role-based permissions beyond membership: **shipped** (Sprints
  25–26, ADR-050/051).
- CAMT.053/OFX statement import: **shipped** (Sprint 18).
- First-user bootstrap for bundle recipients: **shipped**
  (Sprint 24, ADR-049).
- Still true by design: no public REST API (DRF installed, no
  endpoints), no native PDF (browser print-to-PDF, ADR-032),
  Tailwind/HTMX/Alpine not vendored (hand-written CSS, ADR-006),
  additional purchase costs (ADR-017) and purchase price variance
  (ADR-018) out of scope, backdated stock revaluation not done.

## The one open gate: Windows bundle (gate 16)

**What exists:** `scripts/build_windows.bat` (venv + editable
install + `compilemessages` + PyInstaller with the shared
`launcher/accountix.spec`), the launcher's Windows notes in
`docs/deployment/WINDOWS.md`, and a spec that has absorbed every
Linux-side fix since Sprint 09 (axes submodule collection,
catalogue shipping, template collection — all platform-neutral).

**What verification requires** (none of it possible here):

1. A real Windows machine (or VM) with Python 3.12 and the gettext
   tools available for the build step.
2. Run `scripts\build_windows.bat` to completion; confirm
   `dist\accountix\accountix.exe` is produced.
3. The frozen smoke, mirroring the Linux runs: launch with a fresh
   data dir → `/health/` 200 → `/login/` redirects to `/setup/` →
   complete the first-run setup → dashboard renders (fa/RTL) →
   switch to English (en catalogues work) → one OPERATE journey
   (create + post a journal entry) → members page: create a VIEWER
   and prove their OPERATE POST is 403 → `accountix manage check`
   exits 0.
4. Record the result in this file and in the sprint report of
   whichever sprint runs it.

Until that run happens, no Windows distribution claim should be
made: the Linux bundle is the only verified standalone artifact.
