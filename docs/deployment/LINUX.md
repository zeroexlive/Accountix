# Linux deployment

Status: **implemented, built and smoke-tested on Linux (Sprint 09);
bundle rebuilt and re-smoked at Sprint 23 — see
`docs/engineering/SPRINT_23_REPORT.md`.**

- Data directory: `$XDG_DATA_HOME/accountix`, else
  `~/.local/share/accountix` (override: `ACCOUNTIX_DATA_DIR`).
- Run from source: `python launcher/accountix_launcher.py`
  (see LOCAL.md for the full startup sequence).
- Frozen bundle: `scripts/build_linux.sh` produces the PyInstaller
  onedir bundle `dist/accountix/accountix`. In Sprint 09 the bundle was
  built on this machine and smoke-run for real: first launch migrated a
  fresh data directory, `/health/` and `/login/` answered 200, static
  files were served by WhiteNoise, a second launch created the
  pre-migration backup in-process, and SIGINT shut it down cleanly.
  **Sprint 23 rebuild:** the bundle is current through Sprint 22; the
  spec now collects the django-axes submodules (its migrations,
  middleware and backend were missing from the frozen archive), and
  the smoke covered an authenticated session — real login, a failed
  login recorded by axes, Jalali dates, the data-entry / cheque-book /
  statement pages, and the English UI from the bundled catalogs.
  **Sprint 24:** the first-user gap is closed — a fresh bundle
  install opens a one-time setup page (create admin + first
  company in the browser), and the frozen binary accepts
  management commands via `accountix manage <args...>`
  (see LOCAL.md). The Sprint 24 rebuild's smoke ran that whole
  recipient journey bundle-only.
- Smoke test from source: `scripts/smoke_standalone.sh`.
- **Release artifact (Sprint 29, ADR-054):** after the build,
  `scripts/package_release.sh` packages `dist/accountix/` into
  `release/accountix-<VERSION>-linux.tar.gz` plus a
  `.sha256` sidecar in standard `sha256sum` format; `<VERSION>`
  is parsed from `backend/config/version.py` at package time,
  never hardcoded. The archive's single top-level folder
  `accountix-<VERSION>-linux/` holds the bundle (the `accountix`
  binary + `_internal/`) and the operator docs (`LOCAL.md`,
  `UPGRADE.md`). A recipient verifies with
  `(cd release && sha256sum -c accountix-<VERSION>-linux.tar.gz.sha256)`,
  extracts anywhere, and runs the extracted `accountix` — the
  LOCAL.md run story and the UPGRADE.md upgrade story apply
  unchanged. First packaged release: `accountix-1.0.0-linux.tar.gz`
  (30,287,244 bytes, SHA-256
  `222f5777de59252bbec073c2953e7dfe1f78a4ea9da0c574dd2da692399820e3`),
  smoked from a clean extraction; `release/` is gitignored like
  `dist/` (the artifact is identified by name + checksum, not
  committed).
