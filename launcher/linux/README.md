# Linux launcher

There is no Linux-specific launcher code. The single cross-platform
entry point is `launcher/accountix_launcher.py`; on Linux it runs from
source (`python launcher/accountix_launcher.py`) or frozen by
PyInstaller (see `scripts/build_linux.sh`) as `dist/accountix/accountix`.

Linux specifics live in `backend/config/paths.py`: the data directory
defaults to `$XDG_DATA_HOME/accountix` or `~/.local/share/accountix`.
Status: **built and smoke-tested on Linux** (Sprint 09).
