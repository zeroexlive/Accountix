"""Standalone-mode tests: data-dir resolution, secret bootstrap, settings,
launcher pure logic and health polling (Sprint 09)."""

import importlib
import importlib.util
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from config import paths

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_launcher():
    spec = importlib.util.spec_from_file_location(
        "accountix_launcher", REPO_ROOT / "launcher" / "accountix_launcher.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Data directory resolution
# ---------------------------------------------------------------------------


def test_data_dir_env_override_wins(tmp_path):
    env = {"ACCOUNTIX_DATA_DIR": str(tmp_path / "custom")}
    assert paths.default_data_dir(platform="linux", env=env) == tmp_path / "custom"


def test_data_dir_linux_xdg(tmp_path):
    env = {"XDG_DATA_HOME": str(tmp_path / "xdg")}
    result = paths.default_data_dir(platform="linux", env=env, home=tmp_path)
    assert result == tmp_path / "xdg" / "accountix"


def test_data_dir_linux_default(tmp_path):
    result = paths.default_data_dir(platform="linux", env={}, home=tmp_path)
    assert result == tmp_path / ".local" / "share" / "accountix"


def test_data_dir_windows_localappdata(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    result = paths.default_data_dir(platform="win32", env=env, home=tmp_path)
    assert result == tmp_path / "Local" / "Accountix"


def test_data_dir_macos(tmp_path):
    result = paths.default_data_dir(platform="darwin", env={}, home=tmp_path)
    assert result == tmp_path / "Library" / "Application Support" / "Accountix"


# ---------------------------------------------------------------------------
# Secret key bootstrap
# ---------------------------------------------------------------------------


def test_secret_key_created_once_and_reused(tmp_path):
    first = paths.get_or_create_secret_key(tmp_path)
    second = paths.get_or_create_secret_key(tmp_path)
    assert first and first == second
    assert paths.secret_key_path(tmp_path).read_text(encoding="utf-8").strip() == first


# ---------------------------------------------------------------------------
# Standalone settings
# ---------------------------------------------------------------------------


def test_standalone_settings_use_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ACCOUNTIX_DATA_DIR", str(tmp_path))
    sys.modules.pop("config.settings.standalone", None)
    module = importlib.import_module("config.settings.standalone")
    try:
        assert module.DEBUG is False
        assert module.ALLOWED_HOSTS == ["127.0.0.1", "localhost"]
        assert module.DATABASES["default"]["NAME"] == str(tmp_path / "db.sqlite3")
        assert str(module.STATIC_ROOT).startswith(str(tmp_path))
        assert any("whitenoise" in mw.lower() for mw in module.MIDDLEWARE)
        key_file = tmp_path / "secret_key.txt"
        assert key_file.exists()
        assert module.SECRET_KEY == key_file.read_text(encoding="utf-8").strip()
        assert module.SECRET_KEY != "dev-only-insecure-key-change-me"
    finally:
        sys.modules.pop("config.settings.standalone", None)


# ---------------------------------------------------------------------------
# Launcher pure logic
# ---------------------------------------------------------------------------


def test_launcher_needs_backup(tmp_path):
    launcher = _load_launcher()
    db = tmp_path / "db.sqlite3"
    assert launcher.needs_backup(db) is False
    db.write_bytes(b"")
    assert launcher.needs_backup(db) is False
    db.write_bytes(b"sqlite-data")
    assert launcher.needs_backup(db) is True


def test_launcher_browser_decision():
    launcher = _load_launcher()
    assert launcher.should_open_browser(False, {}) is True
    assert launcher.should_open_browser(True, {}) is False
    assert launcher.should_open_browser(False, {"ACCOUNTIX_NO_BROWSER": "1"}) is False


def test_wait_for_health_with_fake_check():
    launcher = _load_launcher()
    attempts = {"n": 0}

    def flaky(url):
        attempts["n"] += 1
        return attempts["n"] >= 3

    ticks = {"t": 0.0}

    def clock():
        return ticks["t"]

    def sleep(seconds):
        ticks["t"] += seconds

    assert (
        launcher.wait_for_health(
            "http://127.0.0.1:1/health/",
            timeout=5,
            interval=0.1,
            check=flaky,
            sleep=sleep,
            clock=clock,
        )
        is True
    )
    assert (
        launcher.wait_for_health(
            "http://127.0.0.1:1/health/",
            timeout=0.2,
            interval=0.1,
            check=lambda url: False,
            sleep=sleep,
            clock=clock,
        )
        is False
    )


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health/":
            body = b'{"status": "ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def test_health_ok_against_stub_server():
    launcher = _load_launcher()
    server = HTTPServer(("127.0.0.1", 0), _HealthHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert launcher.health_ok(f"http://127.0.0.1:{port}/health/") is True
        assert launcher.health_ok(f"http://127.0.0.1:{port}/missing/") is False
    finally:
        server.shutdown()
    assert launcher.health_ok(f"http://127.0.0.1:{port}/health/", timeout=0.5) is False
