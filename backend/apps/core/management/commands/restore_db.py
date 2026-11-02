"""``manage.py restore_db`` — restore a SQLite database from a backup.

This is a destructive operation, guarded accordingly:

- ``--confirm`` is required; without it the command refuses and changes
  nothing.
- The application must be stopped (a live server holds the DB open);
  this command does not try to detect that — stop the launcher first.
- Before replacing anything, the *current* database is backed up to a
  ``pre-restore-<timestamp>`` file, so a bad restore is itself undoable.
- The restored database is integrity-checked, and pending migrations
  are *reported* — never applied silently. Run ``manage.py migrate``
  (or just start the launcher, which backs up and migrates) afterwards.

Only SQLite restore is implemented; PostgreSQL restore goes through
``pg_restore`` operationally (see docs/deployment/PRODUCTION.md).
"""

from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.core.backup import make_backup, sqlite_backup, verify_sqlite


class Command(BaseCommand):
    help = "Restore the SQLite database from a backup file (requires --confirm)."

    def add_arguments(self, parser):
        parser.add_argument("--input", required=True, help="Backup file to restore from.")
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required acknowledgement that the current database will be replaced.",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError(
                "Refusing to restore without --confirm. The current database "
                "would be replaced. Stop the application first, then re-run "
                "with --confirm."
            )
        db = settings.DATABASES["default"]
        if not db["ENGINE"].endswith("sqlite3"):
            raise CommandError(
                "restore_db currently supports SQLite only; use pg_restore for PostgreSQL."
            )
        source_backup = Path(options["input"])
        ok, tables, integrity = verify_sqlite(source_backup)
        if not ok:
            raise CommandError(
                f"Backup {source_backup} failed verification ({integrity}); not restoring."
            )
        db_path = Path(str(db["NAME"]))
        connection.close()  # release our own handle before replacing the file

        if db_path.exists():
            safety = make_backup(db_path, db_path.parent / "backups", prefix="pre-restore")
            self.stdout.write(f"Current database backed up to: {safety}")

        tmp = db_path.with_suffix(".restore-tmp")
        sqlite_backup(source_backup, tmp)
        ok, _tables, integrity = verify_sqlite(tmp)
        if not ok:
            tmp.unlink(missing_ok=True)
            raise CommandError(f"Staged restore copy failed verification ({integrity}).")
        os.replace(tmp, db_path)
        # Remove stale journal files so the restored DB is authoritative.
        for suffix in ("-wal", "-shm", "-journal"):
            stale = Path(str(db_path) + suffix)
            if stale.exists():
                stale.unlink()

        self.stdout.write(
            self.style.SUCCESS(f"Restored {source_backup} ({tables} tables) -> {db_path}")
        )
        call_command("check")
        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(plan)} migration(s) are pending on the restored database. "
                    "They were NOT applied. Run `manage.py migrate` (the launcher "
                    "does this, after a backup) to bring it up to date."
                )
            )
        else:
            self.stdout.write("No pending migrations on the restored database.")
