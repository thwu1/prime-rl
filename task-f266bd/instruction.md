A transactional database system experienced two successive crashes. The second crash occurred while the system was actively recovering from the first, leaving the database in a partially-recovered state.

The relevant data is spread across multiple sources and formats:

- **WAL**: `/app/wal.db` — a SQLite database containing the write-ahead log, checkpoint snapshots, and a master record
- **Crash diagnostics**: `/app/diagnostics.tar.gz` — a compressed archive captured at the second crash, containing the system state report and data format documentation
- **Page store**: `/app/pages.bin` — a binary file containing the initial baseline value for every database page

Determine the correct fully-recovered state of this database and produce `/app/recovery_output.json`.

Refer to `/app/schema.md` for the WAL database schema and required output format.