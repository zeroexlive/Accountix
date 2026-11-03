#!/usr/bin/env python
"""Accountix launcher — single cross-platform entry point (master prompt §17).

Works in two modes:

- **Source mode** (``python launcher/accountix_launcher.py``): Django
  management commands and the Waitress server run as subprocesses of the
  current interpreter.
- **Frozen mode** (PyInstaller bundle): the same steps run in-process
  (``django.setup()`` + ``call_command``) and the server runs in a
  thread. This branch is exercised by the Linux build smoke test when a
  bundle is produced; on other platforms it is written-but-untested.

Startup sequence:

1. Resolve (and create) the per-user data directory (config.paths).
2. Single-instance check: if the health endpoint already answers, just
   open the browser and exit — never start a second server. A pid lock
   file in the data directory is a secondary guard.
3. Ensure the standalone SECRET_KEY file exists.
4. If a database already exists, back it up (``backup_db``). If the
   backup fails, abort — the database is left untouched and no server
   starts. Then run migrations, then collectstatic (into the data dir).
   If migrations fail, abort the same way. Finally compile the
   translation catalogs (``compilemessages``) on a best-effort basis:
   its failure only logs a warning (see prepare_database / ADR-045).
5. Start the server (Waitress, 127.0.0.1 only), poll ``/health/`` until
   ready (timeout → abort with the log path), open the default browser
   at the login page unless disabled.
6. On Ctrl+C / termination, shut the server down cleanly.

Disable the browser with ``--no-browser`` or ``ACCOUNTIX_NO_BROWSER=1``.
Port: ``--port`` or ``ACCOUNTIX_PORT`` (default 8765).
Data dir: ``--data-dir`` or ``ACCOUNTIX_DATA_DIR`` or the per-OS default.
All output is also appended to ``accountix.log`` in the data directory.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path


class LauncherError(Exception):
    """Fatal, human-readable launcher failure."""


# --------------------------------------------------------------------------
# Locations (pure / testable)
# --------------------------------------------------------------------------


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def backend_dir() -> Path:
    return bundle_root() / "backend"


def _load_paths_module():
    """Import config.paths with the backend dir on sys.path."""
    backend = str(backend_dir())
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from config import paths

    return paths


def should_open_browser(no_browser_flag: bool, env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    if no_browser_flag:
        return False
    return env.get("ACCOUNTIX_NO_BROWSER", "").strip().lower() not in ("1", "true", "yes")


def needs_backup(db_path: Path) -> bool:
    """A backup is due before migrating when a non-empty database exists."""
    try:
        return db_path.exists() and db_path.stat().st_size > 0
    except OSError:
        return False


# --------------------------------------------------------------------------
# Health checking (pure logic, transport injectable for tests)
# --------------------------------------------------------------------------


def health_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_for_health(
    url: str,
    timeout: float = 30.0,
    interval: float = 0.25,
    check=health_ok,
    sleep=time.sleep,
    clock=time.monotonic,
) -> bool:
    deadline = clock() + timeout
    while True:
        if check(url):
            return True
        if clock() >= deadline:
            return False
        sleep(interval)


# --------------------------------------------------------------------------
# Lock file (secondary single-instance guard)
# --------------------------------------------------------------------------


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


def read_lock_pid(lock_file: Path) -> int | None:
    try:
        return int(lock_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# Django command execution
# --------------------------------------------------------------------------


def _child_env(data_dir: Path, port: int) -> dict:
    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.standalone"
    env["ACCOUNTIX_DATA_DIR"] = str(data_dir)
    env["ACCOUNTIX_PORT"] = str(port)
    return env


def run_django_command(argv: list[str], data_dir: Path, port: int, log) -> None:
    """Run a management command; raise LauncherError on failure.

    Source mode: subprocess. Frozen mode: in-process call_command
    (there is no child interpreter inside a PyInstaller bundle).
    """
    env = _child_env(data_dir, port)
    log(f"$ manage.py {' '.join(argv)}")
    if is_frozen():
        os.environ.update(env)
        import django
        from django.core.management import call_command

        django.setup()
        try:
            call_command(*argv)
        except Exception as exc:  # noqa: BLE001 - surfaced as LauncherError
            raise LauncherError(f"manage.py {' '.join(argv)} failed: {exc}") from exc
        return
    manage_py = backend_dir() / "manage.py"
    result = subprocess.run(
        [sys.executable, str(manage_py), *argv],
        cwd=str(backend_dir()),
        env=env,
        capture_output=True,
        text=True,
    )
    for line in (result.stdout + result.stderr).splitlines():
        log(f"  {line}")
    if result.returncode != 0:
        raise LauncherError(f"manage.py {' '.join(argv)} failed with exit code {result.returncode}")


def prepare_database(db_path: Path, data_dir: Path, port: int, log) -> None:
    """Backup (when a DB exists) -> migrate -> collectstatic -> compilemessages.

    Any failure in backup/migrate/collectstatic raises LauncherError
    *before* the server is started, and a failed backup means
    migrations never run: the database is left exactly as it was.

    compilemessages is deliberately different — best effort, log and
    continue (Sprint 19, ADR-045): it needs the gettext ``msgfmt``
    binary, which end-user machines typically do not have, and a
    missing ``.mo`` only means a language falls back to the Persian
    source strings. It must never brick startup the way a failed
    migration must. In a frozen bundle the catalogs are compiled at
    build time (scripts/build_*), so this step is a no-op refresh.
    """
    if needs_backup(db_path):
        log("Existing database found — creating a pre-migration backup...")
        run_django_command(["backup_db"], data_dir, port, log)
    else:
        log("No existing database — first run, skipping backup.")
    run_django_command(["migrate", "--noinput"], data_dir, port, log)
    run_django_command(["collectstatic", "--noinput"], data_dir, port, log)
    try:
        run_django_command(["compilemessages"], data_dir, port, log)
    except LauncherError as exc:
        log(
            f"WARNING: translation catalogs not compiled ({exc}); continuing — "
            "the UI falls back to Persian where no compiled catalog exists."
        )


# --------------------------------------------------------------------------
# Server process
# --------------------------------------------------------------------------


def start_server(data_dir: Path, port: int, log):
    """Start Waitress. Returns (kind, handle): subprocess or thread."""
    if is_frozen():
        import threading

        backend = str(backend_dir())
        if backend not in sys.path:
            sys.path.insert(0, backend)
        os.environ.update(_child_env(data_dir, port))
        import serve

        thread = threading.Thread(target=serve.main, name="accountix-server", daemon=True)
        thread.start()
        log("Server started in-process (frozen mode).")
        return "thread", thread
    env = _child_env(data_dir, port)
    proc = subprocess.Popen(
        [sys.executable, str(backend_dir() / "serve.py")],
        cwd=str(backend_dir()),
        env=env,
    )
    log(f"Server subprocess started (pid {proc.pid}).")
    return "subprocess", proc


def stop_server(kind: str, handle, log) -> None:
    if kind == "subprocess":
        handle.terminate()
        try:
            handle.wait(timeout=10)
        except subprocess.TimeoutExpired:
            handle.kill()
            handle.wait(timeout=5)
        log("Server subprocess stopped.")
    # A frozen-mode server thread is a daemon; process exit ends it.


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def _install_signal_handlers() -> None:
    """Make Ctrl+C / termination reliable in every launch context.

    Shells that start background processes mask SIGINT (POSIX sets it to
    SIG_IGN for async jobs without job control), and Python inherits that
    disposition — without an explicit handler, Ctrl+C would never arrive
    and a supervising script could not stop the launcher. Installing the
    handlers here makes SIGINT and SIGTERM both take the normal
    KeyboardInterrupt shutdown path (which stops the server subprocess).
    """
    import signal

    def _raise_keyboard_interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)


def main(argv: list[str] | None = None) -> int:
    _install_signal_handlers()
    parser = argparse.ArgumentParser(prog="accountix", description="Accountix launcher")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    paths = _load_paths_module()
    if args.data_dir:
        os.environ["ACCOUNTIX_DATA_DIR"] = args.data_dir
    data_dir = paths.ensure_data_dir()
    port = args.port or paths.configured_port()
    health = paths.health_url(port)
    login = paths.login_url(port)
    log_file = paths.log_path(data_dir)

    def log(message: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
        print(line, flush=True)
        try:
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    log(f"Accountix launcher — data dir: {data_dir}, port: {port}")

    # 1) Already running? Just open the browser.
    if health_ok(health):
        log("Accountix is already running — opening the browser.")
        if should_open_browser(args.no_browser):
            webbrowser.open(login)
        return 0

    # 2) Lock-file guard: another launcher may be mid-startup.
    lock_file = paths.lock_path(data_dir)
    other_pid = read_lock_pid(lock_file)
    if other_pid and other_pid != os.getpid() and pid_alive(other_pid):
        log(f"Another launcher (pid {other_pid}) seems to be starting Accountix; waiting...")
        if wait_for_health(health, timeout=15.0):
            if should_open_browser(args.no_browser):
                webbrowser.open(login)
            return 0
        log(
            f"ERROR: another Accountix launcher (pid {other_pid}) holds the lock "
            f"but the server is not responding. If no other copy is running, "
            f"delete {lock_file} and try again."
        )
        return 1
    lock_file.write_text(str(os.getpid()), encoding="utf-8")

    server = None
    try:
        # 3) Secret key, 4) backup + migrate + collectstatic.
        paths.get_or_create_secret_key(data_dir)
        prepare_database(paths.database_path(data_dir), data_dir, port, log)

        # 5) Server + health wait + browser.
        server = start_server(data_dir, port, log)
        if not wait_for_health(health, timeout=30.0):
            log(f"ERROR: the server did not become ready within 30s. See log: {log_file}")
            return 2
        log(f"Accountix is ready at {paths.base_url(port)}")
        if should_open_browser(args.no_browser):
            webbrowser.open(login)

        kind, handle = server
        if kind == "subprocess":
            handle.wait()
            return handle.returncode or 0
        # Frozen mode: block until interrupted.
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            log("Interrupted — shutting down.")
            return 0
    except KeyboardInterrupt:
        log("Interrupted — shutting down.")
        return 0
    except LauncherError as exc:
        log(f"ERROR: {exc}")
        log("Accountix was NOT started. Your database was left untouched.")
        return 1
    finally:
        if server is not None:
            stop_server(server[0], server[1], log)
        try:
            if read_lock_pid(lock_file) == os.getpid():
                lock_file.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
