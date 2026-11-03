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
  Known gap: creating the very first user still needs a source
  checkout (`createsuperuser` against the data directory, see
  LOCAL.md's management-command pattern).
- Smoke test from source: `scripts/smoke_standalone.sh`.
