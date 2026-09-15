#!/usr/bin/env python3
"""
Add indexes to dagster_storage.db so the seven canonical queries
defined in /app/queries.py use index scans instead of full table scans.

"""
import sqlite3

DB = "/app/dagster_storage.db"


def optimize(db_path):
    conn = sqlite3.connect(db_path)

    indexes = [
        # Query 1: events by run_id ordered by timestamp
        "CREATE INDEX IF NOT EXISTS idx_events_run_ts "
        "ON event_logs(run_id, timestamp)",

        # Query 2: latest materialization for an asset
        "CREATE INDEX IF NOT EXISTS idx_events_asset_type_ts "
        "ON event_logs(asset_key, dagster_event_type, timestamp)",

        # Query 3: ticks by job_origin_id after a timestamp
        "CREATE INDEX IF NOT EXISTS idx_ticks_origin_ts "
        "ON job_ticks(job_origin_id, timestamp)",

        # Query 4: events by type within a time range
        "CREATE INDEX IF NOT EXISTS idx_events_type_ts "
        "ON event_logs(dagster_event_type, timestamp)",

        # Query 5: events by asset + partition ordered by timestamp
        "CREATE INDEX IF NOT EXISTS idx_events_asset_part_ts "
        "ON event_logs(asset_key, partition_key, timestamp)",

        # Query 6: latest materialization timestamp per asset (GROUP BY)
        # Requires dagster_event_type as leading column for equality filter,
        # then asset_key for grouping, then timestamp for MAX
        "CREATE INDEX IF NOT EXISTS idx_events_type_asset_ts "
        "ON event_logs(dagster_event_type, asset_key, timestamp)",

        # Query 7: event counts by type in a time window
        # Requires timestamp as leading column for range filter
        "CREATE INDEX IF NOT EXISTS idx_events_ts "
        "ON event_logs(timestamp)",
    ]

    for sql in indexes:
        conn.execute(sql)

    conn.execute("ANALYZE")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    optimize(DB)
