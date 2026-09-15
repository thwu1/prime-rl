"""Initialize the materialization database with sample pipeline state.

Creates warehouse.db with materialization records representing the current
state of a three-stage pipeline: raw -> summary -> report.
"""

import sqlite3
import os

DB_PATH = "/app/warehouse.db"


def init_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        "CREATE TABLE materializations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "asset_key TEXT NOT NULL, "
        "partition_key TEXT NOT NULL, "
        "run_id TEXT NOT NULL, "
        "timestamp REAL NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX idx_mat_asset_partition "
        "ON materializations(asset_key, partition_key)"
    )

    # ---- Raw asset: initial materialization ----
    # All 12 raw partitions materialized at t=1704067200 (2024-01-01 00:00:00 UTC)
    for day in ["2024-01-01", "2024-01-02", "2024-01-03"]:
        for source in ["A", "B"]:
            for metric in ["x", "y"]:
                pk = f"day={day}|metric={metric}|source={source}"
                ts = 1704067200.0

                # One record uses millisecond timestamp format
                if pk == "day=2024-01-02|metric=y|source=B":
                    ts = 1704067200000.0

                conn.execute(
                    "INSERT INTO materializations "
                    "(asset_key, partition_key, run_id, timestamp) "
                    "VALUES (?, ?, ?, ?)",
                    ("raw", pk, "run-001", ts)
                )

    # ---- Raw asset: re-materializations for day 2024-01-01 ----
    # All 4 partitions for day 2024-01-01 re-materialized at t=1704326400
    # (2024-01-04 00:00:00 UTC) -- these are ADDITIONAL records
    for source in ["A", "B"]:
        for metric in ["x", "y"]:
            pk = f"day=2024-01-01|metric={metric}|source={source}"
            conn.execute(
                "INSERT INTO materializations "
                "(asset_key, partition_key, run_id, timestamp) "
                "VALUES (?, ?, ?, ?)",
                ("raw", pk, "run-005", 1704326400.0)
            )

    # ---- Raw asset: one re-materialization for day 2024-01-03 ----
    # Creates a second record for this partition key
    conn.execute(
        "INSERT INTO materializations "
        "(asset_key, partition_key, run_id, timestamp) "
        "VALUES (?, ?, ?, ?)",
        ("raw", "day=2024-01-03|metric=x|source=A", "run-005", 1704326400.0)
    )

    # ---- Summary asset ----
    # All daily partitions at t=1704153600 (2024-01-02 00:00:00 UTC)
    for day in ["2024-01-01", "2024-01-02", "2024-01-03"]:
        conn.execute(
            "INSERT INTO materializations "
            "(asset_key, partition_key, run_id, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("summary", day, "run-002", 1704153600.0)
        )

    # ---- Report asset ----
    # All daily partitions at t=1704240000 (2024-01-03 00:00:00 UTC)
    for day in ["2024-01-01", "2024-01-02", "2024-01-03"]:
        conn.execute(
            "INSERT INTO materializations "
            "(asset_key, partition_key, run_id, timestamp) "
            "VALUES (?, ?, ?, ?)",
            ("report", day, "run-003", 1704240000.0)
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
