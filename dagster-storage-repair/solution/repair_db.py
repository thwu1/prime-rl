#!/usr/bin/env python3
"""
Repair all integrity violations in dagster_storage.db.

"""
import sqlite3

DB = "/app/dagster_storage.db"


def repair(db_path):
    conn = sqlite3.connect(db_path)

    # 1. Delete orphaned events (run_id not in runs table)
    conn.execute(
        "DELETE FROM event_logs "
        "WHERE run_id NOT IN (SELECT run_id FROM runs)"
    )

    # 2. Resolve zombie runs: STARTED with no update for >24 h
    max_ts = conn.execute(
        "SELECT MAX(update_timestamp) FROM runs"
    ).fetchone()[0]
    conn.execute(
        "UPDATE runs SET status = 'FAILURE', "
        "  end_time = COALESCE(end_time, update_timestamp) "
        "WHERE status = 'STARTED' AND update_timestamp < ?",
        (max_ts - 86400,),
    )

    # 3. Remove duplicate materializations — keep highest id per group
    conn.execute(
        "DELETE FROM event_logs "
        "WHERE dagster_event_type = 'ASSET_MATERIALIZATION' "
        "AND id NOT IN ("
        "  SELECT MAX(id) FROM event_logs "
        "  WHERE dagster_event_type = 'ASSET_MATERIALIZATION' "
        "  GROUP BY asset_key, COALESCE(partition_key, ''), run_id"
        ")"
    )

    # 4. Fix stale asset_keys metadata
    conn.execute(
        "UPDATE asset_keys SET "
        "  last_materialization_timestamp = ("
        "    SELECT MAX(e.timestamp) FROM event_logs e "
        "    WHERE e.asset_key = asset_keys.asset_key "
        "    AND e.dagster_event_type = 'ASSET_MATERIALIZATION'"
        "  ), "
        "  last_run_id = ("
        "    SELECT e.run_id FROM event_logs e "
        "    WHERE e.asset_key = asset_keys.asset_key "
        "    AND e.dagster_event_type = 'ASSET_MATERIALIZATION' "
        "    ORDER BY e.timestamp DESC LIMIT 1"
        "  )"
    )

    # 5. Resolve orphaned ticks (STARTED for >2 h)
    max_evt_ts = conn.execute(
        "SELECT MAX(timestamp) FROM event_logs"
    ).fetchone()[0]
    conn.execute(
        "UPDATE job_ticks SET status = 'FAILURE', "
        "  end_timestamp = COALESCE(end_timestamp, timestamp) "
        "WHERE status = 'STARTED' AND timestamp < ?",
        (max_evt_ts - 7200,),
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    repair(DB)
