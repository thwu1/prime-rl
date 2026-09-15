A SQLite database at `/app/data/sensor_data.db` was tracking IoT sensor readings in WAL mode when its server crashed. The main database file reflects the last-checkpointed state (schema only, no data rows); the WAL file (`/app/data/sensor_data.db-wal`) contains all subsequent transactions with the actual sensor data. The crash corrupted some WAL frames, making the WAL unplayable by SQLite's built-in recovery. The `litestream` CLI (v0.3.13) is pre-installed.

## Part 1 — WAL Recovery

Create `/app/wal_recovery.py` that parses the raw WAL binary, detects corruption, and recovers the database to the last fully committed valid transaction. The tool must work directly with the binary WAL format — SQLite's built-in WAL replay will refuse to process this file because of the corruption.

Invoke as: `python3 /app/wal_recovery.py /app/data/sensor_data.db`

Required outputs:

- `/app/data/recovered.db` — a valid SQLite database (must pass `PRAGMA integrity_check`) containing data through the last uncorrupted committed transaction. Pages from uncommitted or corrupted transactions must not be applied.
- `/app/data/wal_report.json` with this structure:

```json
{
  "header": {
    "magic": "<int>",
    "page_size": "<int>",
    "checkpoint_seq": "<int>",
    "salt1": "<int>",
    "salt2": "<int>",
    "version": "<int>"
  },
  "total_frames": "<int: total frames in WAL file>",
  "valid_frames": "<int: frames passing validation before first failure>",
  "corrupted_frames": "<int: count of detected invalid frames>",
  "valid_transactions": "<int: fully committed transactions with all valid frames>",
  "first_invalid_frame": "<int (0-based) or null>",
  "frames": [
    {"index": "<int>", "page_number": "<int>", "is_commit": "<bool>", "checksum_valid": "<bool>"}
  ]
}
```

## Part 2 — Litestream Replication Validation

Using Litestream's file-based replication, demonstrate that the recovered database can be reliably replicated and restored with additional data. The recovered database (`recovered.db`) must remain unmodified — work on a separate copy.

Create:

- `/app/litestream.yml` — Litestream YAML configuration for file-based replication to `/app/data/replica/`.
- `/app/validate_replication.sh` — a script that produces all required outputs below. The replica-restored database must contain both the original sensor data and additional validation sensor records inserted after replication was established.

Invoke as: `bash /app/validate_replication.sh`

Required outputs:

- `/app/data/replica/` — Litestream replica directory containing generation data
- `/app/data/replica_restored.db` — database restored from the Litestream file replica (must pass integrity check and contain all sensor data plus validation records)
- `/app/data/replication_report.json` with this structure:

```json
{
  "litestream_version": "<string>",
  "replica_path": "/app/data/replica/",
  "source_row_count": "<int: sensor rows in recovered DB before validation inserts>",
  "validation_rows_inserted": "<int>",
  "restored_row_count": "<int: total rows in restored DB>",
  "data_consistent": "<bool>",
  "integrity_check": "ok"
}
```