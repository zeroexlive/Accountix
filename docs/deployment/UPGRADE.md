# Upgrading a standalone installation

The upgrade path is the launcher itself (ADR-036). There is no separate
updater and no silent schema change.

## Upgrade

1. Install the new version (new bundle directory / new source checkout).
   The data directory is untouched — it lives outside the install
   directory by design.
2. Start the new version's launcher. It will, in order:
   - detect the existing database,
   - write a verified pre-migration backup to
     `<data dir>/backups/accountix-<timestamp>.sqlite3`,
   - run migrations,
   - collect static files, start the server, and open the browser.
3. If the backup or any migration fails, the launcher aborts *before*
   starting the server and the database is left exactly as it was.
   The error and the full log are in `<data dir>/accountix.log`.

## Recovery (an upgrade went wrong)

1. Stop the application (close the launcher).
2. Pick the pre-upgrade backup from `<data dir>/backups/`.
3. Restore it (this first backs up the current, broken database to a
   `pre-restore-*` file, so the recovery is itself undoable):

   ```bash
   DJANGO_SETTINGS_MODULE=config.settings.standalone \
   ACCOUNTIX_DATA_DIR=<data dir> \
   python backend/manage.py restore_db --input <backup file> --confirm
   ```

4. Start the *previous* version's launcher (it will migrate only if the
   restored database needs it, after its own backup).

## Retention

Backups are never deleted automatically unless `--keep N` is passed to
`backup_db`. For a single-machine business, keeping the last handful of
pre-upgrade backups plus one off-machine copy is the intended practice;
automated scheduling/retention policy is operational, not built in.
