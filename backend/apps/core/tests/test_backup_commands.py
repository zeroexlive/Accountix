"""Backup/restore tests (Sprint 09, master prompt section 19).

Helper-level tests run in-process on plain SQLite files. The command
round-trip runs the real management commands in subprocesses against
the standalone settings with a temporary data directory — the exact
path an end user's launcher exercises.
"""

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from apps.core.backup import list_backups, make_backup, prune_backups, sqlite_backup, verify_sqlite

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _make_db(path: Path, rows: int = 3) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE item (id INTEGER PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO item (name) VALUES (?)", [(f"row-{i}",) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def test_sqlite_backup_and_verify(tmp_path):
    source = _make_db(tmp_path / "db.sqlite3")
    dest = sqlite_backup(source, tmp_path / "backups" / "copy.sqlite3")
    ok, tables, integrity = verify_sqlite(dest)
    assert ok and integrity == "ok" and tables >= 1
    conn = sqlite3.connect(str(dest))
    assert conn.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 3
    conn.close()


def test_verify_rejects_missing_file(tmp_path):
    ok, tables, _ = verify_sqlite(tmp_path / "nope.sqlite3")
    assert ok is False and tables == 0


def test_make_backup_naming_and_prune(tmp_path):
    source = _make_db(tmp_path / "db.sqlite3")
    backups = tmp_path / "backups"
    created = []
    for _ in range(4):
        created.append(make_backup(source, backups))
        time.sleep(1.05)  # distinct timestamps + mtimes
    assert all(p.name.startswith("accountix-") for p in created)
    assert len(list_backups(backups)) == 4
    removed = prune_backups(backups, keep=2)
    assert len(removed) == 2
    remaining = list_backups(backups)
    assert remaining == created[-2:][::-1] or set(remaining) == set(created[-2:])


# ---------------------------------------------------------------------------
# Full command round-trip via subprocess (standalone settings, temp dir)
# ---------------------------------------------------------------------------


def _run_manage(args: list[str], data_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.standalone"
    env["ACCOUNTIX_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _shell(data_dir: Path, code: str) -> str:
    result = _run_manage(["shell", "-c", code], data_dir)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.skipif(os.environ.get("ACCOUNTIX_SKIP_SLOW_TESTS") == "1", reason="slow test opt-out")
def test_backup_restore_command_roundtrip(tmp_path):
    data_dir = tmp_path / "data"
    result = _run_manage(["migrate", "--noinput"], data_dir)
    assert result.returncode == 0, result.stderr

    _shell(
        data_dir,
        "from apps.organizations.models import Company; Company.objects.create(name='BackupCo')",
    )

    result = _run_manage(["backup_db"], data_dir)
    assert result.returncode == 0, result.stderr
    backups = list((data_dir / "backups").glob("accountix-*.sqlite3"))
    assert len(backups) == 1
    backup_file = backups[0]

    # Mutate: remove the original company, add junk.
    _shell(
        data_dir,
        "from apps.organizations.models import Company; "
        "Company.objects.all().delete(); Company.objects.create(name='JunkCo')",
    )

    # Restore without --confirm must refuse and change nothing.
    result = _run_manage(["restore_db", "--input", str(backup_file)], data_dir)
    assert result.returncode != 0
    assert "Refusing" in (result.stdout + result.stderr)
    names = _shell(
        data_dir,
        "from apps.organizations.models import Company; "
        "print(list(Company.objects.values_list('name', flat=True)))",
    )
    assert "JunkCo" in names

    # Confirmed restore: original data returns; a pre-restore backup exists.
    result = _run_manage(["restore_db", "--input", str(backup_file), "--confirm"], data_dir)
    assert result.returncode == 0, result.stderr
    assert list((data_dir / "backups").glob("pre-restore-*.sqlite3"))
    names = _shell(
        data_dir,
        "from apps.organizations.models import Company; "
        "print(list(Company.objects.values_list('name', flat=True)))",
    )
    assert "BackupCo" in names and "JunkCo" not in names
