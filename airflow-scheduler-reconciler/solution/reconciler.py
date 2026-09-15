#!/usr/bin/env python3
"""
Airflow Scheduler Anomaly Reconciler

Analyzes an Airflow metadata database, scheduler logs, and DAG definitions
to detect scheduling anomalies in a dual-scheduler deployment.
"""

import sqlite3
import json
import re
import os
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = "/app/airflow.db"
CONFIG_PATH = "/app/config.json"
LOGS_DIR = "/app/logs"
REPORT_PATH = "/app/anomaly_report.json"


def load_config():
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    # Normalize reference_time to 'YYYY-MM-DD HH:MM:SS' for SQLite comparison
    rt = config["reference_time"]
    dt = datetime.fromisoformat(rt.replace("Z", "+00:00"))
    config["_ref_time_str"] = dt.strftime("%Y-%m-%d %H:%M:%S")
    config["_ref_time_dt"] = dt
    return config


def detect_zombie_tasks(conn, ref_time_str, threshold_seconds):
    """
    Detect tasks in 'running' state on workers whose heartbeat has gone stale.
    A zombie is a task that appears running but its worker is no longer alive.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ti.dag_id, ti.task_id, ti.run_id, ti.hostname,
               ti.start_date, wh.latest_heartbeat
        FROM task_instance ti
        JOIN worker_heartbeat wh ON ti.hostname = wh.hostname
        WHERE ti.state = 'running'
          AND (julianday(?) - julianday(wh.latest_heartbeat)) * 86400 > ?
    """, (ref_time_str, threshold_seconds))

    anomalies = []
    for row in cursor.fetchall():
        dag_id, task_id, run_id, hostname, start_date, last_hb = row
        anomalies.append({
            "type": "zombie_task",
            "dag_id": dag_id,
            "task_id": task_id,
            "run_id": run_id,
            "description": (
                f"Task {dag_id}.{task_id} in run {run_id} has been in 'running' "
                f"state on host {hostname} since {start_date}, but the worker's "
                f"last heartbeat was at {last_hb} (stale by "
                f"{_format_staleness(ref_time_str, last_hb)})"
            ),
            "severity": "critical",
        })
    return anomalies


def detect_missed_dataset_triggers(conn):
    """
    Detect dataset events queued for a consumer DAG that were never consumed,
    i.e., entries in dataset_dag_run_queue with no corresponding dag_run created
    after the queue entry's creation time.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT q.dataset_id, q.target_dag_id, q.created_at, d.uri
        FROM dataset_dag_run_queue q
        JOIN dataset d ON q.dataset_id = d.id
        WHERE NOT EXISTS (
            SELECT 1 FROM dag_run dr
            WHERE dr.dag_id = q.target_dag_id
              AND dr.execution_date >= q.created_at
        )
    """)

    anomalies = []
    for row in cursor.fetchall():
        dataset_id, target_dag_id, created_at, uri = row
        anomalies.append({
            "type": "missed_dataset_trigger",
            "dag_id": target_dag_id,
            "task_id": None,
            "run_id": None,
            "description": (
                f"Dataset '{uri}' event at {created_at} was queued to trigger "
                f"DAG '{target_dag_id}' but no corresponding DAG run was ever created. "
                f"Entry remains unconsumed in dataset_dag_run_queue."
            ),
            "severity": "high",
        })
    return anomalies


def detect_incorrect_data_intervals(conn):
    """
    Detect DAG runs where data_interval_start equals data_interval_end
    for DAGs with a schedule that implies a non-zero interval (e.g., @daily).
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT dr.dag_id, dr.run_id, dr.data_interval_start, dr.data_interval_end,
               d.schedule_interval
        FROM dag_run dr
        JOIN dag d ON dr.dag_id = d.dag_id
        WHERE d.schedule_interval = '@daily'
          AND dr.data_interval_start = dr.data_interval_end
    """)

    anomalies = []
    for row in cursor.fetchall():
        dag_id, run_id, di_start, di_end, schedule = row
        anomalies.append({
            "type": "incorrect_data_interval",
            "dag_id": dag_id,
            "task_id": None,
            "run_id": run_id,
            "description": (
                f"DAG run {dag_id}/{run_id} has data_interval_start == "
                f"data_interval_end ({di_start}), but DAG schedule is '{schedule}' "
                f"which requires a 24-hour data interval."
            ),
            "severity": "medium",
        })
    return anomalies


def detect_stuck_retries(conn, ref_time_str):
    """
    Detect tasks in 'up_for_retry' state whose retry should have started
    (end_date + retry_delay has passed) but no new attempt has been made.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT dag_id, task_id, run_id, try_number, max_retries,
               end_date, retry_delay_seconds
        FROM task_instance
        WHERE state = 'up_for_retry'
          AND try_number <= max_retries
          AND datetime(end_date, '+' || retry_delay_seconds || ' seconds') < ?
    """, (ref_time_str,))

    anomalies = []
    for row in cursor.fetchall():
        dag_id, task_id, run_id, try_num, max_retries, end_date, delay = row
        expected_retry = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S") + timedelta(seconds=delay)
        anomalies.append({
            "type": "stuck_retry",
            "dag_id": dag_id,
            "task_id": task_id,
            "run_id": run_id,
            "description": (
                f"Task {dag_id}.{task_id} in run {run_id} has been in 'up_for_retry' "
                f"state since {end_date}. Retry attempt {try_num + 1} of "
                f"{max_retries + 1} should have started at "
                f"{expected_retry.strftime('%Y-%m-%d %H:%M:%S')} but never did."
            ),
            "severity": "high",
        })
    return anomalies


def detect_duplicate_scheduling(logs_dir):
    """
    Parse scheduler logs from multiple scheduler instances to detect cases
    where the same TaskInstanceKey was dispatched by more than one scheduler,
    indicating a race condition.
    """
    tik_pattern = re.compile(
        r"Sending TaskInstanceKey\("
        r"dag_id='([^']+)', "
        r"task_id='([^']+)', "
        r"run_id='([^']+)', "
        r"try_number=(\d+)"
    )

    # Track which log files dispatched each (dag_id, task_id, run_id)
    scheduler_sends = defaultdict(set)

    for log_file in sorted(os.listdir(logs_dir)):
        if not log_file.endswith(".log"):
            continue
        filepath = os.path.join(logs_dir, log_file)
        with open(filepath) as f:
            for line in f:
                match = tik_pattern.search(line)
                if match:
                    key = (match.group(1), match.group(2), match.group(3))
                    scheduler_sends[key].add(log_file)

    anomalies = []
    for (dag_id, task_id, run_id), log_files in scheduler_sends.items():
        if len(log_files) > 1:
            anomalies.append({
                "type": "duplicate_scheduling",
                "dag_id": dag_id,
                "task_id": task_id,
                "run_id": run_id,
                "description": (
                    f"Task {dag_id}.{task_id} for run {run_id} was dispatched to "
                    f"the executor by multiple scheduler instances "
                    f"({', '.join(sorted(log_files))}), indicating a scheduler "
                    f"race condition."
                ),
                "severity": "high",
            })
    return anomalies


def detect_dependency_violations(conn):
    """
    Detect task instances in 'success' state whose upstream dependency
    (per the task_dependency table) is in 'failed' state within the same
    DAG run. This indicates state corruption.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT td.dag_id, td.task_id, td.upstream_task_id,
               ti.run_id, ti.state AS task_state,
               up_ti.state AS upstream_state
        FROM task_dependency td
        JOIN task_instance ti
            ON td.dag_id = ti.dag_id AND td.task_id = ti.task_id
        JOIN task_instance up_ti
            ON td.dag_id = up_ti.dag_id
            AND td.upstream_task_id = up_ti.task_id
            AND ti.run_id = up_ti.run_id
        WHERE ti.state = 'success'
          AND up_ti.state = 'failed'
    """)

    anomalies = []
    for row in cursor.fetchall():
        dag_id, task_id, upstream_task_id, run_id, state, upstream_state = row
        anomalies.append({
            "type": "dependency_violation",
            "dag_id": dag_id,
            "task_id": task_id,
            "run_id": run_id,
            "description": (
                f"Task {dag_id}.{task_id} is in '{state}' state but its upstream "
                f"dependency '{upstream_task_id}' is in '{upstream_state}' state "
                f"for run {run_id}. This violates the DAG dependency contract "
                f"and indicates metadata corruption."
            ),
            "severity": "critical",
        })
    return anomalies


def _format_staleness(ref_time_str, heartbeat_str):
    """Format the time difference between reference time and heartbeat."""
    ref = datetime.strptime(ref_time_str, "%Y-%m-%d %H:%M:%S")
    hb = datetime.strptime(heartbeat_str, "%Y-%m-%d %H:%M:%S")
    delta = ref - hb
    hours = delta.total_seconds() / 3600
    if hours >= 1:
        return f"{hours:.1f} hours"
    minutes = delta.total_seconds() / 60
    return f"{minutes:.0f} minutes"


def main():
    config = load_config()
    ref_time_str = config["_ref_time_str"]
    heartbeat_threshold = config.get("heartbeat_threshold_seconds", 1800)

    conn = sqlite3.connect(DB_PATH)

    anomalies = []
    anomalies.extend(detect_zombie_tasks(conn, ref_time_str, heartbeat_threshold))
    anomalies.extend(detect_missed_dataset_triggers(conn))
    anomalies.extend(detect_incorrect_data_intervals(conn))
    anomalies.extend(detect_stuck_retries(conn, ref_time_str))
    anomalies.extend(detect_duplicate_scheduling(LOGS_DIR))
    anomalies.extend(detect_dependency_violations(conn))

    conn.close()

    # Build summary
    by_type = defaultdict(int)
    for a in anomalies:
        by_type[a["type"]] += 1

    report = {
        "reference_time": config["reference_time"],
        "anomalies": anomalies,
        "summary": {
            "total": len(anomalies),
            "by_type": dict(by_type),
        },
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Anomaly report written to {REPORT_PATH}")
    print(f"Total anomalies found: {len(anomalies)}")
    for atype, count in sorted(by_type.items()):
        print(f"  {atype}: {count}")


if __name__ == "__main__":
    main()
