"""Per-user data locations for the standalone (packaged) application.

This module is the single source of truth for where Accountix keeps its
data when it runs as a local desktop application. It is used by
``config.settings.standalone``, ``backend/serve.py`` and the launcher
(``launcher/accountix_launcher.py``), and it must stay importable without
Django being configured.

Resolution order for the data directory:

1. ``ACCOUNTIX_DATA_DIR`` environment variable (explicit override).
2. Per-OS default:

   - Windows: ``%LOCALAPPDATA%\\Accountix``
   - macOS:   ``~/Library/Application Support/Accountix``
   - Linux:   ``$XDG_DATA_HOME/accountix`` or ``~/.local/share/accountix``

Persistent data always lives *outside* the installation directory so an
upgrade never touches the database, secret key, backups or logs.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

APP_NAME = "Accountix"
DEFAULT_PORT = 8765


def default_data_dir(
    platform: str | None = None, env: dict | None = None, home: Path | None = None
) -> Path:
    """Return the default per-user data directory for the platform."""
    env = os.environ if env is None else env
    override = env.get("ACCOUNTIX_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home
    if platform.startswith("win"):
        local_app_data = env.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        return base / APP_NAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    xdg_data_home = env.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg_data_home) if xdg_data_home else home / ".local" / "share"
    return base / "accountix"


def data_dir() -> Path:
    """The resolved data directory (not created as a side effect)."""
    return default_data_dir()


def ensure_data_dir(path: Path | None = None) -> Path:
    """Create the data directory (and parents) if needed and return it."""
    path = data_dir() if path is None else path
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path(path: Path | None = None) -> Path:
    return (data_dir() if path is None else path) / "db.sqlite3"


def secret_key_path(path: Path | None = None) -> Path:
    return (data_dir() if path is None else path) / "secret_key.txt"


def backups_dir(path: Path | None = None) -> Path:
    return (data_dir() if path is None else path) / "backups"


def log_path(path: Path | None = None) -> Path:
    return (data_dir() if path is None else path) / "accountix.log"


def lock_path(path: Path | None = None) -> Path:
    return (data_dir() if path is None else path) / "accountix.lock"


def static_root(path: Path | None = None) -> Path:
    """Where collectstatic writes inside the data dir (writable when frozen)."""
    return (data_dir() if path is None else path) / "staticfiles"


def get_or_create_secret_key(path: Path | None = None) -> str:
    """Return the standalone SECRET_KEY, generating and storing it once.

    The key lives in a file inside the data directory (mode 0600 where the
    OS supports it). It is never written into the repository or the bundle.
    """
    key_file = secret_key_path(path)
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key:
            return key
    ensure_data_dir(key_file.parent)
    key = secrets.token_urlsafe(50)
    key_file.write_text(key + "\n", encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass  # best effort (e.g. Windows ACLs)
    return key


def configured_port(env: dict | None = None) -> int:
    env = os.environ if env is None else env
    raw = env.get("ACCOUNTIX_PORT", "").strip()
    if raw:
        try:
            port = int(raw)
        except ValueError:
            return DEFAULT_PORT
        if 1 <= port <= 65535:
            return port
    return DEFAULT_PORT


def base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def health_url(port: int) -> str:
    return base_url(port) + "/health/"


def login_url(port: int) -> str:
    return base_url(port) + "/login/"
