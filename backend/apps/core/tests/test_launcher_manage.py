"""Launcher management passthrough (Sprint 24, ADR-049):
``accountix manage <args...>`` dispatches to Django management
against the standalone data directory, propagates the exit code,
and never starts the server."""

import importlib.util
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
# Dispatch parsing (pure)
# ---------------------------------------------------------------------------


def test_parse_manage_invocation_recognises_manage():
    launcher = _load_launcher()
    assert launcher.parse_manage_invocation(["manage", "check"]) == (["check"], None)
    assert launcher.parse_manage_invocation(["manage", "backup_db", "--keep", "3"]) == (
        ["backup_db", "--keep", "3"],
        None,
    )
    assert launcher.parse_manage_invocation(["manage"]) == ([], None)


def test_parse_manage_invocation_consumes_data_dir_flag():
    launcher = _load_launcher()
    assert launcher.parse_manage_invocation(["manage", "--data-dir", "/tmp/x", "check"]) == (
        ["check"],
        "/tmp/x",
    )
    assert launcher.parse_manage_invocation(["manage", "--data-dir=/tmp/x", "check"]) == (
        ["check"],
        "/tmp/x",
    )
    # A --data-dir later in the args belongs to Django, untouched.
    assert launcher.parse_manage_invocation(["manage", "backup_db", "--data-dir", "/tmp/y"]) == (
        ["backup_db", "--data-dir", "/tmp/y"],
        None,
    )


def test_parse_manage_invocation_ignores_server_args():
    launcher = _load_launcher()
    assert launcher.parse_manage_invocation([]) is None
    assert launcher.parse_manage_invocation(["--port", "9000"]) is None
    assert launcher.parse_manage_invocation(["--no-browser"]) is None
    assert launcher.parse_manage_invocation(["manager", "check"]) is None


def test_main_dispatches_manage_without_starting_server(monkeypatch):
    launcher = _load_launcher()
    calls = []

    def fake_run_manage(manage_args, data_dir_override=None):
        calls.append((manage_args, data_dir_override))
        return 7

    monkeypatch.setattr(launcher, "run_manage_command", fake_run_manage)
    assert launcher.main(["manage", "--data-dir", "/tmp/x", "check"]) == 7
    assert calls == [(["check"], "/tmp/x")]


# ---------------------------------------------------------------------------
# Real passthrough runs (source mode: manage.py subprocess)
# ---------------------------------------------------------------------------


def test_manage_check_runs_and_returns_zero(tmp_path):
    launcher = _load_launcher()
    code = launcher.main(["manage", "--data-dir", str(tmp_path), "check"])
    assert code == 0
    # Startup side effects shared with a normal launch happened in
    # the data dir (secret bootstrap)…
    assert paths.secret_key_path(tmp_path).exists()
    # …but no server: no instance lock was taken.
    assert not paths.lock_path(tmp_path).exists()


def test_manage_unknown_command_returns_nonzero(tmp_path):
    launcher = _load_launcher()
    code = launcher.main(["manage", "--data-dir", str(tmp_path), "definitely_not_a_command"])
    assert code != 0


def test_manage_without_command_is_a_usage_error(tmp_path):
    launcher = _load_launcher()
    assert launcher.main(["manage"]) == 2
