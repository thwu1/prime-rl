#!/usr/bin/env python3
"""
Generate dagster_storage.db with planted integrity issues for the benchmark task.

"""
import sqlite3
import random
import json
import os
from datetime import datetime, timedelta

DB_PATH = "/app/dagster_storage.db"
BASE_TIME = 1700000000.0  # Fixed reference: ~2023-11-14 22:13:20 UTC
DAY = 86400.0
SEED = 42

ASSET_KEYS = [
    "raw_events", "raw_users", "raw_transactions",
    "cleaned_events", "cleaned_users", "cleaned_transactions",
    "daily_event_aggregates", "daily_user_metrics", "daily_transaction_summary",
    "hourly_event_counts", "user_profiles", "user_segments",
    "weekly_reports", "monthly_summaries", "dashboard_cache",
]

PARTITIONED_DAILY = {
    "raw_events", "raw_users", "raw_transactions",
    "cleaned_events", "cleaned_users", "cleaned_transactions",
    "daily_event_aggregates", "daily_user_metrics", "daily_transaction_summary",
    "hourly_event_counts",
}

PARTITIONED_WEEKLY = {"weekly_reports", "user_segments"}

# Assets whose asset_keys entry will be intentionally stale
STALE_ASSETS = {
    "cleaned_events", "daily_user_metrics", "user_profiles",
    "weekly_reports", "hourly_event_counts", "dashboard_cache",
    "monthly_summaries", "user_segments",
}

PIPELINE_NAMES = ["etl_pipeline", "analytics_pipeline", "reporting_pipeline"]
JOB_NAMES = ["event_sensor", "user_sensor", "schedule_daily", "schedule_weekly"]


def create_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT UNIQUE NOT NULL,
        pipeline_name TEXT NOT NULL,
        status TEXT NOT NULL,
        create_timestamp REAL NOT NULL,
        update_timestamp REAL NOT NULL,
        start_time REAL,
        end_time REAL,
        tags_json TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS event_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        dagster_event_type TEXT,
        step_key TEXT,
        asset_key TEXT,
        partition_key TEXT,
        timestamp REAL NOT NULL,
        event_body_json TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS asset_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_key TEXT UNIQUE NOT NULL,
        last_materialization_timestamp REAL,
        last_run_id TEXT,
        tags_json TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS job_ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_origin_id TEXT NOT NULL,
        job_name TEXT NOT NULL,
        status TEXT NOT NULL,
        tick_type TEXT NOT NULL,
        timestamp REAL NOT NULL,
        tick_body_json TEXT DEFAULT '{}',
        end_timestamp REAL
    );
    """)


def generate_data(conn):
    rng = random.Random(SEED)
    base_date = datetime(2023, 11, 14)

    all_events = []
    asset_mat_times = {ak: [] for ak in ASSET_KEYS}

    # ---- Normal runs (200 total) ----
    normal_runs = []
    for i in range(200):
        run_id = "run_{:04d}".format(i)
        pipeline = rng.choice(PIPELINE_NAMES)
        create_ts = BASE_TIME - rng.uniform(1 * DAY, 90 * DAY)
        duration = rng.uniform(60, 3600)
        status = rng.choices(["SUCCESS", "FAILURE"], weights=[3, 1])[0]
        start_ts = create_ts + rng.uniform(1, 10)
        end_ts = start_ts + duration
        normal_runs.append(
            (run_id, pipeline, status, create_ts, end_ts, start_ts, end_ts, "{}")
        )

        n_assets = rng.randint(1, 5)
        selected = rng.sample(ASSET_KEYS, min(n_assets, len(ASSET_KEYS)))
        ts = start_ts
        for asset in selected:
            step_key = asset + "_step"
            ts += rng.uniform(0.1, 5)
            all_events.append(
                (run_id, "ENGINE_EVENT", "STEP_START", step_key, None, None, ts, "{}")
            )
            for _ in range(rng.randint(20, 80)):
                ts += rng.uniform(0.01, 0.5)
                all_events.append(
                    (run_id, "ENGINE_EVENT", "STEP_OUTPUT", step_key, None, None, ts, "{}")
                )
            ts += rng.uniform(0.1, 5)
            partition = None
            if asset in PARTITIONED_DAILY:
                day_offset = int((BASE_TIME - create_ts) / DAY)
                pdate = base_date - timedelta(days=day_offset)
                partition = pdate.strftime("%Y-%m-%d")
            elif asset in PARTITIONED_WEEKLY:
                day_offset = int((BASE_TIME - create_ts) / DAY)
                pdate = base_date - timedelta(days=day_offset)
                pdate = pdate - timedelta(days=pdate.weekday())
                partition = pdate.strftime("%Y-%m-%d")

            if status == "SUCCESS":
                body = json.dumps({"asset_key": asset, "partition": partition})
                all_events.append(
                    (run_id, "ENGINE_EVENT", "ASSET_MATERIALIZATION",
                     step_key, asset, partition, ts, body)
                )
                asset_mat_times[asset].append((ts, run_id, partition))

            ts += rng.uniform(0.1, 2)
            evt = "STEP_SUCCESS" if status == "SUCCESS" else "STEP_FAILURE"
            all_events.append(
                (run_id, "ENGINE_EVENT", evt, step_key, None, None, ts, "{}")
            )

    conn.executemany(
        "INSERT INTO runs VALUES (NULL,?,?,?,?,?,?,?,?)", normal_runs
    )

    # ---- Zombie runs (10 — STARTED, old, never completed) ----
    zombie_runs = []
    for i in range(10):
        run_id = "zombie_run_{:03d}".format(i)
        create_ts = BASE_TIME - rng.uniform(8 * DAY, 60 * DAY)
        zombie_runs.append(
            (run_id, rng.choice(PIPELINE_NAMES), "STARTED",
             create_ts, create_ts, create_ts + 1, None, "{}")
        )
        ts = create_ts + 1
        for _ in range(rng.randint(3, 10)):
            ts += rng.uniform(0.1, 5)
            all_events.append(
                (run_id, "ENGINE_EVENT", "STEP_START",
                 "some_step", None, None, ts, "{}")
            )
    conn.executemany("INSERT INTO runs VALUES (NULL,?,?,?,?,?,?,?,?)", zombie_runs)

    # ---- Backfill runs (5 — old, tagged as backfill, should survive retention) ----
    backfill_runs = []
    for i in range(5):
        run_id = "backfill_run_{:03d}".format(i)
        create_ts = BASE_TIME - rng.uniform(40 * DAY, 70 * DAY)
        duration = rng.uniform(300, 7200)
        start_ts = create_ts + rng.uniform(1, 10)
        end_ts = start_ts + duration
        tags = json.dumps({"dagster/backfill": "true"})
        backfill_runs.append(
            (run_id, rng.choice(PIPELINE_NAMES), "SUCCESS",
             create_ts, end_ts, start_ts, end_ts, tags)
        )
        ts = start_ts
        selected = rng.sample(ASSET_KEYS, rng.randint(2, 5))
        for asset in selected:
            step_key = asset + "_step"
            ts += rng.uniform(0.1, 5)
            partition = None
            if asset in PARTITIONED_DAILY:
                day_offset = int((BASE_TIME - create_ts) / DAY)
                pdate = base_date - timedelta(days=day_offset)
                partition = pdate.strftime("%Y-%m-%d")
            elif asset in PARTITIONED_WEEKLY:
                day_offset = int((BASE_TIME - create_ts) / DAY)
                pdate = base_date - timedelta(days=day_offset)
                pdate = pdate - timedelta(days=pdate.weekday())
                partition = pdate.strftime("%Y-%m-%d")
            body = json.dumps({"asset_key": asset, "partition": partition,
                               "backfill": True})
            all_events.append(
                (run_id, "ENGINE_EVENT", "ASSET_MATERIALIZATION",
                 step_key, asset, partition, ts, body)
            )
            asset_mat_times[asset].append((ts, run_id, partition))
            ts += rng.uniform(0.1, 5)
            all_events.append(
                (run_id, "ENGINE_EVENT", "STEP_SUCCESS",
                 step_key, None, None, ts, "{}")
            )
    conn.executemany("INSERT INTO runs VALUES (NULL,?,?,?,?,?,?,?,?)", backfill_runs)

    # ---- Orphaned events (200 — reference non-existent runs) ----
    for i in range(200):
        run_id = "deleted_run_{:04d}".format(i)
        ts = BASE_TIME - rng.uniform(1 * DAY, 80 * DAY)
        etype = rng.choice(
            ["STEP_START", "STEP_SUCCESS", "STEP_OUTPUT", "ASSET_MATERIALIZATION"]
        )
        asset = rng.choice(ASSET_KEYS) if etype == "ASSET_MATERIALIZATION" else None
        all_events.append(
            (run_id, "ENGINE_EVENT", etype, "orphan_step", asset, None, ts, "{}")
        )

    # ---- Duplicate materializations (30) ----
    existing_mats = [
        (e[0], e[4], e[5], e[6])
        for e in all_events
        if e[2] == "ASSET_MATERIALIZATION" and e[4] is not None
        and e[0].startswith("run_")
    ]
    if len(existing_mats) > 30:
        for run_id, asset, partition, ts in rng.sample(existing_mats, 30):
            body = json.dumps({"asset_key": asset, "partition": partition, "dup": True})
            all_events.append(
                (run_id, "ENGINE_EVENT", "ASSET_MATERIALIZATION",
                 asset + "_step", asset, partition, ts + 0.001, body)
            )

    # ---- Insert all events ----
    conn.executemany(
        "INSERT INTO event_logs VALUES (NULL,?,?,?,?,?,?,?,?)", all_events
    )

    # ---- Asset keys table (some intentionally stale) ----
    for asset in ASSET_KEYS:
        times = sorted(asset_mat_times[asset], key=lambda x: x[0])
        if times:
            actual_latest = times[-1]
            if asset in STALE_ASSETS and len(times) > 1:
                stale = times[-2]
                conn.execute(
                    "INSERT INTO asset_keys VALUES (NULL,?,?,?,'{}')",
                    (asset, stale[0], stale[1]),
                )
            else:
                conn.execute(
                    "INSERT INTO asset_keys VALUES (NULL,?,?,?,'{}')",
                    (asset, actual_latest[0], actual_latest[1]),
                )
        else:
            conn.execute(
                "INSERT INTO asset_keys VALUES (NULL,?,NULL,NULL,'{}')", (asset,)
            )

    # ---- Job ticks (400 normal + 15 orphaned + 5 audit-only) ----
    ticks = []
    for i in range(400):
        jname = rng.choice(JOB_NAMES)
        jorigin = "origin_" + jname
        ttype = "SENSOR" if "sensor" in jname else "SCHEDULE"
        ts = BASE_TIME - rng.uniform(0.5 * DAY, 90 * DAY)
        status = rng.choices(["SUCCESS", "FAILURE", "SKIPPED"], weights=[6, 2, 2])[0]
        end_ts = ts + rng.uniform(0.5, 30)
        ticks.append((jorigin, jname, status, ttype, ts, "{}", end_ts))

    for i in range(15):
        jname = rng.choice(JOB_NAMES)
        jorigin = "origin_" + jname
        ttype = "SENSOR" if "sensor" in jname else "SCHEDULE"
        ts = BASE_TIME - rng.uniform(3 * 3600, 60 * DAY)
        ticks.append((jorigin, jname, "STARTED", ttype, ts, "{}", None))

    # Audit origin: only old ticks (tests tick retention top-3 preservation)
    for i in range(5):
        ts = BASE_TIME - rng.uniform(40 * DAY, 80 * DAY)
        end_ts = ts + rng.uniform(1, 30)
        ticks.append(("origin_audit_job", "audit_job", "SUCCESS",
                       "SCHEDULE", ts, "{}", end_ts))

    conn.executemany(
        "INSERT INTO job_ticks VALUES (NULL,?,?,?,?,?,?,?)", ticks
    )

    conn.commit()


if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    create_schema(conn)
    generate_data(conn)
    conn.close()

    conn = sqlite3.connect(DB_PATH)
    for t in ["runs", "event_logs", "asset_keys", "job_ticks"]:
        n = conn.execute("SELECT COUNT(*) FROM " + t).fetchone()[0]
        print("{}: {}".format(t, n))
    conn.close()
