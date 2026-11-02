"""Database backup / restore helpers (master prompt section 19).

SQLite backups use the sqlite3 backup API, which produces a consistent
copy even while the database is live. Every copy is verified by opening
it and running ``PRAGMA integrity_check`` plus a table-count sanity
check — a successful file write alone is never treated as proof of a
recoverable backup.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

BACKUP_GLOB = "accountix-*.sqlite3"
PRE_RESTORE_GLOB = "pre-restore-*.sqlite3"


def timestamp_label(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def sqlite_backup(source: Path, dest: Path) -> Path:
    """Copy ``source`` to ``dest`` via the SQLite backup API."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def verify_sqlite(path: Path) -> tuple[bool, int, str]:
    """Return (ok, table_count, integrity_result) for a SQLite file."""
    if not path.exists():
        return False, 0, "missing"
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, 0, str(exc)
    return integrity == "ok" and tables > 0, int(tables), str(integrity)


def make_backup(db_path: Path, backups_dir: Path, prefix: str = "accountix") -> Path:
    """Create a verified, timestamped backup of a SQLite database."""
    dest = backups_dir / f"{prefix}-{timestamp_label()}.sqlite3"
    sqlite_backup(db_path, dest)
    ok, _tables, integrity = verify_sqlite(dest)
    if not ok:
        raise RuntimeError(f"Backup verification failed for {dest}: {integrity}")
    return dest


def list_backups(backups_dir: Path) -> list[Path]:
    """All backup files (regular + pre-restore), newest first."""
    if not backups_dir.exists():
        return []
    files = list(backups_dir.glob(BACKUP_GLOB)) + list(backups_dir.glob(PRE_RESTORE_GLOB))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def prune_backups(backups_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` backup files; return removed."""
    if keep < 0:
        raise ValueError("keep must be >= 0")
    removed = []
    for path in list_backups(backups_dir)[keep:]:
        path.unlink()
        removed.append(path)
    return removed
