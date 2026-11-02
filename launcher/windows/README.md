# Windows launcher

There is no Windows-specific launcher code. The single cross-platform
entry point is `launcher/accountix_launcher.py`; on Windows it is frozen
by PyInstaller (see `scripts/build_windows.bat`) into
`dist/accountix/accountix.exe`.

Windows specifics live in `backend/config/paths.py`: the data directory
defaults to `%LOCALAPPDATA%\Accountix`. Status: **written, not yet built
or run on a Windows machine** (Sprint 09 was developed on Linux).
