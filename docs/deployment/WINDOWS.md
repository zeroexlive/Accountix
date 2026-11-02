# Windows deployment

Status: **written, NOT built or run on Windows yet (Sprint 09 was
developed on Linux).** Everything below describes the design as coded;
the first Windows build is a Sprint 10 verification task.

- The launcher is the same cross-platform entry point
  (`launcher/accountix_launcher.py`); the PyInstaller spec is
  platform-neutral. Build with `scripts/build_windows.bat`, producing
  `dist\accountix\accountix.exe` (onedir).
- Data directory: `%LOCALAPPDATA%\Accountix` (override:
  `ACCOUNTIX_DATA_DIR`), outside the install directory.
- Startup requirements from the master prompt §17 are implemented in
  the launcher: single-instance check via the health endpoint, pid
  lock file, secret key file, backup before migrations with abort on
  failure, Waitress bound to 127.0.0.1 only, health-endpoint wait,
  default-browser launch, logging to the data directory, clean
  shutdown on Ctrl+C.
- No installer (Inno Setup / MSI) exists yet; distribution is the
  onedir bundle as a zip. An installer is packaging polish, not a
  runtime requirement.
