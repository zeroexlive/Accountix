"""``manage.py backup_db`` — create a verified database backup.

SQLite (the standalone/local database): the copy is made with the
sqlite3 backup API (consistent while the app is live) and verified with
``PRAGMA integrity_check`` before success is reported.

PostgreSQL: shells out to ``pg_dump``. Verified once in Sprint 10
against PostgreSQL 16.2 (archive produced and read back with
``pg_restore --list``); restore stays an operational procedure — see
docs/deployment/PRODUCTION.md.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.backup import make_backup, prune_backups, timestamp_label, verify_sqlite


def default_backups_dir(db_path: Path) -> Path:
    """Backups live next to the database (in the data dir when standalone)."""
    return db_path.parent / "backups"


class Command(BaseCommand):
    help = "Create a verified backup of the configured database."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="", help="Explicit destination file path.")
        parser.add_argument(
            "--keep",
            type=int,
            default=None,
            help="After backing up, keep only the newest N backup files.",
        )

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        engine = db["ENGINE"]
        if engine.endswith("sqlite3"):
            path = self._backup_sqlite(db, options)
        elif "postgresql" in engine:
            path = self._backup_postgres(db, options)
        else:
            raise CommandError(f"backup_db does not support engine {engine!r}")
        size = path.stat().st_size
        self.stdout.write(self.style.SUCCESS(f"Backup written: {path} ({size} bytes)"))
        if options.get("keep") is not None:
            removed = prune_backups(path.parent, options["keep"])
            for old in removed:
                self.stdout.write(f"Pruned old backup: {old}")

    def _backup_sqlite(self, db, options) -> Path:
        source = Path(str(db["NAME"]))
        if str(db["NAME"]) == ":memory:" or not source.exists():
            raise CommandError(f"SQLite database not found at {source}")
        if options["output"]:
            dest = Path(options["output"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            from apps.core.backup import sqlite_backup

            sqlite_backup(source, dest)
            ok, _tables, integrity = verify_sqlite(dest)
            if not ok:
                raise CommandError(f"Backup verification failed: {integrity}")
            return dest
        return make_backup(source, default_backups_dir(source))

    def _backup_postgres(self, db, options) -> Path:
        # Verified in Sprint 10 against PostgreSQL 16.2 (pgserver instance).
        if options["output"]:
            dest = Path(options["output"])
        else:
            base = Path(str(db["NAME"])).parent if db["NAME"] else Path.cwd()
            dest = base / "backups" / f"accountix-{timestamp_label()}.sql"
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = os.environ.get("DATABASE_URL", "")
        if not url.startswith(("postgres://", "postgresql://")):
            user = quote(str(db.get("USER", "")), safe="")
            password = quote(str(db.get("PASSWORD", "")), safe="")
            auth = f"{user}:{password}@" if user else ""
            url = (
                f"postgresql://{auth}{db.get('HOST', '127.0.0.1')}:"
                f"{db.get('PORT', '5432')}/{db.get('NAME', 'accountix')}"
            )
        try:
            subprocess.run(
                ["pg_dump", "--format=custom", "--file", str(dest), url],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise CommandError("pg_dump not found on PATH") from exc
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"pg_dump failed: {exc.stderr.strip()}") from exc
        return dest
