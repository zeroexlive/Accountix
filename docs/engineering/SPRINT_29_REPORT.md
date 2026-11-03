# Sprint 29 Report — Release packaging: a versioned artifact + the in-place upgrade, proven

Date: 2026-11-03. Base: Sprint 28 complete (455 passed + 3 skipped).
Scope: (1) turn the Linux bundle into a versioned, distributable
release artifact, (2) prove the ADR-036 in-place upgrade story end
to end on real populated data. **No application code changed** —
this is a packaging + verification sprint (ADR-054); the suite is
the regression net.

## Implemented

### Part 1 — Versioned release artifact (ADR-054)

- **`scripts/package_release.sh`** (new, sibling of
  `build_linux.sh`, same conventions): reads the version by
  parsing `__version__` from `backend/config/version.py` at
  package time (never hardcoded), stages the bundle from
  `dist/accountix/` plus the operator docs, and writes to the
  (now gitignored) `release/` directory:
  - `accountix-<VERSION>-linux.tar.gz` — a single top-level
    folder `accountix-<VERSION>-linux/` containing the runnable
    `accountix` binary, `_internal/`, and the operator docs an
    installer/upgrader needs (`LOCAL.md`, `UPGRADE.md`);
  - `accountix-<VERSION>-linux.tar.gz.sha256` — standard
    `sha256sum` format (bare file name), so a recipient verifies
    with `sha256sum -c` wherever the pair lands.
  It refuses to run without a built bundle (points at
  `build_linux.sh`). `.gitignore` gains `release/` — the artifact
  is a build product, identified by name + checksum, never
  committed (like `dist/`).
- **Windows parity (written-only):** `scripts/build_windows.bat`
  gains a clearly commented NOT VERIFIED packaging block that
  mirrors the naming — `release\accountix-<VERSION>-windows.zip`
  via `Compress-Archive`, single top folder, version parsed from
  `backend\config\version.py` the same way.
- **The artifact of this sprint**, produced from a *fresh* full
  route (`scripts/build_linux.sh` → `scripts/package_release.sh`),
  not from the stale dist:
  - Path: `release/accountix-1.0.0-linux.tar.gz` (repo working
    tree; gitignored)
  - Size: **30,287,244 bytes** (the bundle inside it:
    112,313,950 bytes / 3,847 files, byte-size-identical to
    Sprint 28's rebuild, as expected with no app changes)
  - SHA-256: `222f5777de59252bbec073c2953e7dfe1f78a4ea9da0c574dd2da692399820e3`

### Part 2 — Upgrade smoke (operator story, on the packaged artifact)

All steps below ran the **extracted archive's binary**
(`/tmp/s29-extract/accountix-1.0.0-linux/accountix`), never
`dist/`. HTTP steps were driven with a stdlib cookie/CSRF driver;
data seeding went through the binary's own `manage shell` running
the app's services (the Sprint 17 seed path, minus every
treasury.0003-dependent object — no cheque books, no leaves).

**Fixture (the "old installation"):** fresh data dir → `/setup/`
creates admin + *Upgrade Test Co* → a member `accountant`
(ACCOUNTANT) created through the members UI's create-new path →
seeded business data: FY2026 + open period, a 12-account chart,
supplier/customer, product/warehouse, cash + bank treasury
accounts; purchase `PINV-1` posted (1100.00, UNPAID); sale
`SINV-1` posted (1100.00); a bank receipt of 1100.00 posted and
allocated → sale **PAID**; one manual journal (75) posted —
5 journal entries, all POSTED.

**Fingerprint** (Sprint 17 approach; row counts for every table +
key aggregates as canonical JSON; `django_migrations` and
`django_session` excluded as volatile by design):

| | Populated | After rollback (baseline) | After upgrade |
|---|---|---|---|
| Counted tables / rows | 56 / 338 | 54 / 338 | 56 / 338 |
| Trial balance | 3775.00 = 3775.00 ✓ | 3775.00 = 3775.00 ✓ | 3775.00 = 3775.00 ✓ |
| Sale SINV-1 | 1100.00, PAID | 1100.00, PAID | 1100.00, PAID |
| Purchase PINV-1 | 1100.00, UNPAID | 1100.00, UNPAID | 1100.00, UNPAID |
| Stock (Widget @ WH1) | 6 units / 600.00 | 6 / 600.00 | 6 / 600.00 |
| Memberships | admin OWNER, accountant ACCOUNTANT | same | same |

## Tested (exact evidence)

**Artifact route**

| Step | Evidence |
|---|---|
| Fresh build | `scripts/build_linux.sh` exit 0. (First attempt failed at the compilemessages step — `msgfmt` missing: the build machine's gettext is a documented prerequisite (DEVELOPMENT.md) and does not persist in this environment; reinstalled gettext 0.21 via the documented scoped-apt route, then the full route ran clean.) |
| Packaging | `scripts/package_release.sh` printed the artifact + checksum paths; archive listing shows exactly one top-level folder (`accountix-1.0.0-linux/`) |
| Checksum | `(cd release && sha256sum -c accountix-1.0.0-linux.tar.gz.sha256)` → `accountix-1.0.0-linux.tar.gz: OK` |
| Extraction smoke (extracted binary, fresh data dir, port 8895) | `/health/` 200 `{"status": "ok"}` → `/login/` 302 → `/setup/` 200 → setup POST 302 → dashboard 200 with **1.0.0** in the sidebar footer → fonts from the frozen server: `vazirmatn-400.woff2` 200, wOF2 magic, 50,684 bytes and `inter-700.woff2` 200, wOF2, 114,840 bytes (the exact vendored sizes) → logout 302 → `/login/` 200 with **1.0.0** on the page |

**Upgrade drill** (copy of the populated dir, schema rolled back
with the binary's own passthrough: `manage migrate treasury 0002`
→ `Unapplying treasury.0003_chequebook_chequeleaf... OK`; the
populated-vs-baseline fingerprint diff was *exactly* the two
dropped 0003 tables at 0 rows — all business data untouched by
the rollback):

| ADR-036 claim | Evidence |
|---|---|
| (a) Backup before migration | `backups/` did not exist in the copy before launch; after launch it holds `accountix-20261103-235139.sqlite3`, **1,314,816 bytes** — the exact pre-upgrade DB size. `accountix.log` ordering: `Existing database found — creating a pre-migration backup...` → `$ manage.py backup_db` → `$ manage.py migrate --noinput` → `Accountix is ready` |
| (b) Pending migration applied by the launcher | launcher output: `Applying treasury.0003_chequebook_chequeleaf... OK`; `manage showmigrations treasury` → 0001/0002/0003 all `[X]` |
| (c) Healthy after upgrade | `/health/` 200 on the upgrade launch |
| (d) Old credentials + members survive | post-upgrade relaunch: admin login with the pre-upgrade password → 302; the roster lists `accountant` (fingerprint pins role ACCOUNTANT, active); the member's own login → 302 |
| (e) Old data unchanged | post-upgrade fingerprint taken **before any post-upgrade login**: diff vs the rolled-back baseline over every pre-existing table and aggregate — **none**; the only additions are `treasury_chequebook` / `treasury_chequeleaf`, present and empty |
| (f) The re-migrated feature works | `GET /treasury/cheque-books/` → 200 for the upgraded admin |
| Failure posture (optional check, taken) | a data dir whose `db.sqlite3` is a *directory*: launch exits **1** with `ERROR: manage.py backup_db failed: unable to open database file` + `Accountix was NOT started. Your database was left untouched.`; the directory posing as the DB is intact and no migration ran |

**Regression gates** (app code untouched; exact commands):

| Command | Result |
|---|---|
| `.venv/bin/python -m pytest` | **455 passed, 3 skipped** (baseline held exactly) |
| `manage.py check` — local / test / standalone / postgres_test / production (secret set) | no issues under all five |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `mypy --config-file ../pyproject.toml .` (from `backend/`, the established invocation) | "Success: no issues found in 188 source files" |
| `ruff check backend launcher tests scripts` | all passed |
| `ruff format --check backend launcher tests scripts` | 199 files already formatted |
| `bash -n scripts/package_release.sh` | syntax OK |

## Partially implemented

- Windows packaging parity exists only as the written,
  commented block in `build_windows.bat` — **NOT VERIFIED**,
  like the whole Windows route. Nothing about that status
  changed this sprint; it still needs a Windows machine
  (RELEASE_STATUS.md lists exactly what verification requires).

## Planned / not started

- Distribution channel for the artifact (where releases are
  published for operators) — an operator decision, not code.
- Windows bundle verification — unchanged, still the only
  NOT VERIFIED release-gate item.

## Blocked

- Nothing.

## Release recommendation

With this sprint, everything on the Linux route is verified:
the suite, the gates, the packaged artifact (checksummed,
smoked from extraction), and the in-place upgrade from an
older-schema data directory with data intact. **1.0.0 is ready
to tag** on the strength of the Linux artifact; the tag should
record the artifact's SHA-256 above. The single open item is
platform-shaped, not code-shaped: the Windows bundle remains
NOT VERIFIED until a Windows machine runs its build + smoke.
