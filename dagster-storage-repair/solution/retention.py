#!/usr/bin/env python3
"""
Retention policy: prune events and ticks older than 30 days while preserving:
  - The latest ASSET_MATERIALIZATION event per (asset_key, partition_key)
  - Events belonging to non-terminal runs (STARTED / NOT_STARTED)
  - Events belonging to backfill-tagged runs
  - The 3 most recent ticks per job_origin_id

"""
import sqlite3

DB = "/app/dagster_storage.db"
RETENTION_DAYS = 30


def run_retention(db_path):
    conn = sqlite3.connect(db_path)

    # Determine cutoff relative to the latest event timestamp
    max_ts = conn.execute(
        "SELECT MAX(timestamp) FROM event_logs"
    ).fetchone()[0]
    cutoff = max_ts - RETENTION_DAYS * 86400

    # Identify the latest materialization event id for each
    # (asset_key, partition_key) group — these must be preserved.
    latest_mat_ids = conn.execute(
        "SELECT id FROM event_logs e1 "
        "WHERE e1.dagster_event_type = 'ASSET_MATERIALIZATION' "
        "AND e1.id = ("
        "  SELECT e2.id FROM event_logs e2 "
        "  WHERE e2.dagster_event_type = 'ASSET_MATERIALIZATION' "
        "  AND e2.asset_key = e1.asset_key "
        "  AND COALESCE(e2.partition_key, '') = COALESCE(e1.partition_key, '') "
        "  ORDER BY e2.timestamp DESC LIMIT 1"
        ")"
    ).fetchall()
    preserve_ids = set(row[0] for row in latest_mat_ids)

    # Delete old events, excluding:
    # - preserved latest materialization IDs
    # - events from non-terminal runs
    # - events from backfill-tagged runs
    if preserve_ids:
        placeholders = ",".join("?" * len(preserve_ids))
        conn.execute(
            "DELETE FROM event_logs "
            "WHERE timestamp < ? "
            "AND id NOT IN ({ph}) "
            "AND run_id NOT IN "
            "  (SELECT run_id FROM runs WHERE status IN ('STARTED','NOT_STARTED')) "
            "AND run_id NOT IN "
            "  (SELECT run_id FROM runs WHERE tags_json LIKE '%dagster/backfill%')"
            .format(ph=placeholders),
            [cutoff] + sorted(preserve_ids),
        )
    else:
        conn.execute(
            "DELETE FROM event_logs "
            "WHERE timestamp < ? "
            "AND run_id NOT IN "
            "  (SELECT run_id FROM runs WHERE status IN ('STARTED','NOT_STARTED')) "
            "AND run_id NOT IN "
            "  (SELECT run_id FROM runs WHERE tags_json LIKE '%dagster/backfill%')",
            (cutoff,),
        )

    # Tick retention: preserve the 3 most recent ticks per job_origin_id,
    # then prune old ticks
    preserve_tick_ids = set()
    for (origin,) in conn.execute(
        "SELECT DISTINCT job_origin_id FROM job_ticks"
    ).fetchall():
        top3 = conn.execute(
            "SELECT id FROM job_ticks WHERE job_origin_id = ? "
            "ORDER BY timestamp DESC LIMIT 3",
            (origin,),
        ).fetchall()
        preserve_tick_ids.update(row[0] for row in top3)

    if preserve_tick_ids:
        tp = ",".join("?" * len(preserve_tick_ids))
        conn.execute(
            "DELETE FROM job_ticks WHERE timestamp < ? AND id NOT IN ({})".format(tp),
            [cutoff] + sorted(preserve_tick_ids),
        )
    else:
        conn.execute("DELETE FROM job_ticks WHERE timestamp < ?", (cutoff,))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    run_retention(DB)
