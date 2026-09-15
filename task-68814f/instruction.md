A SIMDB database instance crashed mid-operation. The following artifacts are available:

- `/app/data.db` -- corrupted main database file
- `/app/wal.log` -- write-ahead log from the crash window
- `/app/backup.sqlite` -- SQLite backup of the pre-WAL database state (multiple tables)
- `/app/engine/` -- SIMDB engine source code (storage, WAL, config, and recovery modules)
- `/app/check_integrity.py` -- basic structural integrity checker

The `simdb-ctl` command-line utility is available in the system PATH for database inspection, WAL analysis, and strict validation.

Produce a recovered database at `/app/recovered.db` that passes `simdb-ctl validate /app/recovered.db` and reflects the correct post-recovery state -- only durably committed WAL transactions applied to the pre-WAL base state, with all pages (including those not referenced in the WAL) present and correct.