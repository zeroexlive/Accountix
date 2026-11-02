# Linux deployment

Status: **implemented, built and smoke-tested on Linux (Sprint 09).**

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
- Smoke test from source: `scripts/smoke_standalone.sh`.
