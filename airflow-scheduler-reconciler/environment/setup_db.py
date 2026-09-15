#!/usr/bin/env python3
"""Set up the simulated Airflow metadata database with normal and anomalous data."""
import sqlite3
import os

DB_PATH = "/app/airflow.db"


def create_tables(conn):
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE dag (
            dag_id TEXT PRIMARY KEY,
            schedule_interval TEXT,
            is_active INTEGER DEFAULT 1,
            timetable_description TEXT
        );

        CREATE TABLE dag_run (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dag_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            execution_date TEXT NOT NULL,
            data_interval_start TEXT,
            data_interval_end TEXT,
            state TEXT,
            external_trigger INTEGER DEFAULT 0,
            UNIQUE(dag_id, run_id)
        );

        CREATE TABLE task_instance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dag_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            execution_date TEXT,
            start_date TEXT,
            end_date TEXT,
            state TEXT,
            hostname TEXT,
            try_number INTEGER DEFAULT 1,
            max_retries INTEGER DEFAULT 0,
            queued_dttm TEXT,
            retry_delay_seconds INTEGER DEFAULT 300
        );

        CREATE TABLE dataset (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uri TEXT UNIQUE NOT NULL,
            extra TEXT
        );

        CREATE TABLE dataset_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            source_dag_id TEXT NOT NULL,
            source_task_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            extra TEXT
        );

        CREATE TABLE dataset_dag_run_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            target_dag_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE worker_heartbeat (
            hostname TEXT PRIMARY KEY,
            latest_heartbeat TEXT NOT NULL
        );

        CREATE TABLE task_dependency (
            dag_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            upstream_task_id TEXT NOT NULL,
            PRIMARY KEY (dag_id, task_id, upstream_task_id)
        );
    """)


def populate_dags(conn):
    c = conn.cursor()
    dags = [
        ("etl_pipeline", "@daily", 1, "Run once a day at midnight"),
        ("ml_training", "dataset", 1, "Triggered by dataset /data/features.parquet"),
        ("report_generator", "@daily", 1, "Run once a day at midnight"),
        ("data_quality", "dataset", 1, "Triggered by dataset /data/raw_input.csv"),
        ("model_serving", "dataset", 1, "Triggered by dataset /data/model.pkl"),
    ]
    c.executemany("INSERT INTO dag VALUES (?, ?, ?, ?)", dags)


def populate_datasets(conn):
    c = conn.cursor()
    datasets = [
        (1, "/data/raw_input.csv", None),
        (2, "/data/features.parquet", None),
        (3, "/data/warehouse", None),
        (4, "/data/model.pkl", None),
    ]
    c.executemany("INSERT INTO dataset VALUES (?, ?, ?)", datasets)


def populate_task_dependencies(conn):
    c = conn.cursor()
    deps = [
        # etl_pipeline: extract >> transform >> load >> validate
        ("etl_pipeline", "transform_data", "extract_data"),
        ("etl_pipeline", "load_data", "transform_data"),
        ("etl_pipeline", "validate_data", "load_data"),
        # ml_training: prepare >> train >> evaluate
        ("ml_training", "train_model", "prepare_features"),
        ("ml_training", "evaluate_model", "train_model"),
        # report_generator: aggregate >> render >> notify
        ("report_generator", "render_report", "aggregate_metrics"),
        ("report_generator", "send_notification", "render_report"),
        # data_quality: completeness >> [accuracy, freshness]
        ("data_quality", "check_accuracy", "check_completeness"),
        ("data_quality", "check_freshness", "check_completeness"),
        # model_serving: validate >> deploy >> smoke_test
        ("model_serving", "deploy_model", "validate_model"),
        ("model_serving", "smoke_test", "deploy_model"),
    ]
    c.executemany("INSERT INTO task_dependency VALUES (?, ?, ?)", deps)


def populate_dag_runs(conn):
    c = conn.cursor()
    runs = [
        # etl_pipeline - Jan 14 to 17
        (1, "etl_pipeline", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-13 00:00:00", "2024-01-14 00:00:00", "success", 0),
        (2, "etl_pipeline", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-14 00:00:00", "2024-01-15 00:00:00", "success", 0),
        (3, "etl_pipeline", "scheduled__2024-01-16T00:00:00+00:00",
         "2024-01-16 00:00:00", "2024-01-15 00:00:00", "2024-01-16 00:00:00", "success", 0),
        (4, "etl_pipeline", "scheduled__2024-01-17T00:00:00+00:00",
         "2024-01-17 00:00:00", "2024-01-16 00:00:00", "2024-01-17 00:00:00", "running", 0),

        # report_generator - Jan 14 to 17
        (5, "report_generator", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-13 00:00:00", "2024-01-14 00:00:00", "success", 0),
        (6, "report_generator", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-14 00:00:00", "2024-01-15 00:00:00", "success", 0),
        (7, "report_generator", "scheduled__2024-01-16T00:00:00+00:00",
         "2024-01-16 00:00:00", "2024-01-15 00:00:00", "2024-01-16 00:00:00", "running", 0),
        # ANOMALY: incorrect data interval (start == end for @daily DAG)
        (8, "report_generator", "scheduled__2024-01-17T00:00:00+00:00",
         "2024-01-17 00:00:00", "2024-01-17 00:00:00", "2024-01-17 00:00:00", "running", 0),

        # ml_training - Jan 14, 15 (NO Jan 16 = missed trigger)
        (9, "ml_training", "dataset_triggered__2024-01-14T03:15:00+00:00",
         "2024-01-14 03:15:00", "2024-01-14 03:15:00", "2024-01-14 03:15:00", "success", 1),
        (10, "ml_training", "dataset_triggered__2024-01-15T03:30:00+00:00",
         "2024-01-15 03:30:00", "2024-01-15 03:30:00", "2024-01-15 03:30:00", "running", 1),

        # data_quality - Jan 14, 15
        (11, "data_quality", "dataset_triggered__2024-01-14T02:30:00+00:00",
         "2024-01-14 02:30:00", "2024-01-14 02:30:00", "2024-01-14 02:30:00", "success", 1),
        (12, "data_quality", "dataset_triggered__2024-01-15T06:00:00+00:00",
         "2024-01-15 06:00:00", "2024-01-15 06:00:00", "2024-01-15 06:00:00", "running", 1),

        # model_serving - Jan 14 only
        (13, "model_serving", "dataset_triggered__2024-01-14T04:30:00+00:00",
         "2024-01-14 04:30:00", "2024-01-14 04:30:00", "2024-01-14 04:30:00", "success", 1),
    ]
    c.executemany("INSERT INTO dag_run VALUES (?, ?, ?, ?, ?, ?, ?, ?)", runs)


def populate_task_instances(conn):
    c = conn.cursor()
    # Columns: dag_id, task_id, run_id, execution_date, start_date, end_date,
    #          state, hostname, try_number, max_retries, queued_dttm, retry_delay_seconds
    instances = [
        # === etl_pipeline Jan 14 (all success) ===
        ("etl_pipeline", "extract_data", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-14 00:05:00", "2024-01-14 00:20:00",
         "success", "worker-alpha", 1, 0, "2024-01-14 00:00:15", 300),
        ("etl_pipeline", "transform_data", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-14 00:25:00", "2024-01-14 01:00:00",
         "success", "worker-beta", 1, 0, "2024-01-14 00:20:30", 300),
        ("etl_pipeline", "load_data", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-14 01:05:00", "2024-01-14 01:30:00",
         "success", "worker-alpha", 1, 0, "2024-01-14 01:00:10", 300),
        ("etl_pipeline", "validate_data", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-14 01:35:00", "2024-01-14 01:45:00",
         "success", "worker-beta", 1, 0, "2024-01-14 01:30:15", 300),

        # === etl_pipeline Jan 15 (success, but extract had duplicate scheduling) ===
        ("etl_pipeline", "extract_data", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-15 00:01:23", "2024-01-15 00:20:00",
         "success", "worker-beta", 2, 0, "2024-01-15 00:01:18", 300),
        ("etl_pipeline", "transform_data", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-15 00:25:00", "2024-01-15 01:00:00",
         "success", "worker-alpha", 1, 0, "2024-01-15 00:20:30", 300),
        ("etl_pipeline", "load_data", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-15 01:05:00", "2024-01-15 01:30:00",
         "success", "worker-beta", 1, 0, "2024-01-15 01:00:10", 300),
        ("etl_pipeline", "validate_data", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-15 01:35:00", "2024-01-15 01:45:00",
         "success", "worker-alpha", 1, 0, "2024-01-15 01:30:15", 300),

        # === etl_pipeline Jan 16 (all success) ===
        ("etl_pipeline", "extract_data", "scheduled__2024-01-16T00:00:00+00:00",
         "2024-01-16 00:00:00", "2024-01-16 00:05:00", "2024-01-16 00:20:00",
         "success", "worker-gamma", 1, 0, "2024-01-16 00:00:15", 300),
        ("etl_pipeline", "transform_data", "scheduled__2024-01-16T00:00:00+00:00",
         "2024-01-16 00:00:00", "2024-01-16 00:25:00", "2024-01-16 01:00:00",
         "success", "worker-delta", 1, 0, "2024-01-16 00:20:30", 300),
        ("etl_pipeline", "load_data", "scheduled__2024-01-16T00:00:00+00:00",
         "2024-01-16 00:00:00", "2024-01-16 01:05:00", "2024-01-16 01:30:00",
         "success", "worker-gamma", 1, 0, "2024-01-16 01:00:10", 300),
        ("etl_pipeline", "validate_data", "scheduled__2024-01-16T00:00:00+00:00",
         "2024-01-16 00:00:00", "2024-01-16 01:35:00", "2024-01-16 01:45:00",
         "success", "worker-delta", 1, 0, "2024-01-16 01:30:15", 300),

        # === etl_pipeline Jan 17 (running, load_data = ZOMBIE) ===
        ("etl_pipeline", "extract_data", "scheduled__2024-01-17T00:00:00+00:00",
         "2024-01-17 00:00:00", "2024-01-17 00:05:00", "2024-01-17 00:20:00",
         "success", "worker-alpha", 1, 0, "2024-01-17 00:00:15", 300),
        ("etl_pipeline", "transform_data", "scheduled__2024-01-17T00:00:00+00:00",
         "2024-01-17 00:00:00", "2024-01-17 00:25:00", "2024-01-17 01:00:00",
         "success", "worker-beta", 1, 0, "2024-01-17 00:20:30", 300),
        # ANOMALY: zombie_task - running on worker-epsilon whose heartbeat is stale
        ("etl_pipeline", "load_data", "scheduled__2024-01-17T00:00:00+00:00",
         "2024-01-17 00:00:00", "2024-01-17 02:00:00", None,
         "running", "worker-epsilon", 1, 0, "2024-01-17 01:00:10", 300),

        # === report_generator Jan 14 (all success) ===
        ("report_generator", "aggregate_metrics", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-14 00:10:00", "2024-01-14 00:30:00",
         "success", "worker-delta", 1, 0, "2024-01-14 00:00:20", 300),
        ("report_generator", "render_report", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-14 00:35:00", "2024-01-14 00:50:00",
         "success", "worker-alpha", 1, 0, "2024-01-14 00:30:10", 300),
        ("report_generator", "send_notification", "scheduled__2024-01-14T00:00:00+00:00",
         "2024-01-14 00:00:00", "2024-01-14 00:55:00", "2024-01-14 01:00:00",
         "success", "worker-delta", 1, 0, "2024-01-14 00:50:10", 300),

        # === report_generator Jan 15 (all success) ===
        ("report_generator", "aggregate_metrics", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-15 00:10:00", "2024-01-15 00:30:00",
         "success", "worker-beta", 1, 0, "2024-01-15 00:00:20", 300),
        ("report_generator", "render_report", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-15 00:35:00", "2024-01-15 00:50:00",
         "success", "worker-gamma", 1, 0, "2024-01-15 00:30:10", 300),
        ("report_generator", "send_notification", "scheduled__2024-01-15T00:00:00+00:00",
         "2024-01-15 00:00:00", "2024-01-15 00:55:00", "2024-01-15 01:00:00",
         "success", "worker-beta", 1, 0, "2024-01-15 00:50:10", 300),

        # === report_generator Jan 16 (render_report = ZOMBIE) ===
        ("report_generator", "aggregate_metrics", "scheduled__2024-01-16T00:00:00+00:00",
         "2024-01-16 00:00:00", "2024-01-16 00:10:00", "2024-01-16 00:30:00",
         "success", "worker-delta", 1, 0, "2024-01-16 00:00:20", 300),
        # ANOMALY: zombie_task - running on worker-gamma whose heartbeat is stale
        ("report_generator", "render_report", "scheduled__2024-01-16T00:00:00+00:00",
         "2024-01-16 00:00:00", "2024-01-16 02:30:00", None,
         "running", "worker-gamma", 1, 0, "2024-01-16 00:30:10", 300),

        # === report_generator Jan 17 (running, has incorrect interval on dag_run) ===
        ("report_generator", "aggregate_metrics", "scheduled__2024-01-17T00:00:00+00:00",
         "2024-01-17 00:00:00", "2024-01-17 00:10:00", None,
         "running", "worker-alpha", 1, 0, "2024-01-17 00:00:20", 300),

        # === ml_training Jan 14 (all success) ===
        ("ml_training", "prepare_features", "dataset_triggered__2024-01-14T03:15:00+00:00",
         "2024-01-14 03:15:00", "2024-01-14 03:20:00", "2024-01-14 03:30:00",
         "success", "worker-alpha", 1, 0, "2024-01-14 03:15:35", 300),
        ("ml_training", "train_model", "dataset_triggered__2024-01-14T03:15:00+00:00",
         "2024-01-14 03:15:00", "2024-01-14 03:35:00", "2024-01-14 04:00:00",
         "success", "worker-beta", 1, 0, "2024-01-14 03:30:10", 300),
        ("ml_training", "evaluate_model", "dataset_triggered__2024-01-14T03:15:00+00:00",
         "2024-01-14 03:15:00", "2024-01-14 04:05:00", "2024-01-14 04:15:00",
         "success", "worker-alpha", 1, 0, "2024-01-14 04:00:10", 300),

        # === ml_training Jan 15 (DEPENDENCY VIOLATION: evaluate=success but train=failed) ===
        ("ml_training", "prepare_features", "dataset_triggered__2024-01-15T03:30:00+00:00",
         "2024-01-15 03:30:00", "2024-01-15 03:35:00", "2024-01-15 03:45:00",
         "success", "worker-gamma", 1, 0, "2024-01-15 03:30:35", 300),
        # train_model FAILED
        ("ml_training", "train_model", "dataset_triggered__2024-01-15T03:30:00+00:00",
         "2024-01-15 03:30:00", "2024-01-15 03:50:00", "2024-01-15 04:10:00",
         "failed", "worker-delta", 1, 0, "2024-01-15 03:45:10", 300),
        # ANOMALY: evaluate_model succeeded despite upstream train_model failing
        ("ml_training", "evaluate_model", "dataset_triggered__2024-01-15T03:30:00+00:00",
         "2024-01-15 03:30:00", "2024-01-15 04:15:00", "2024-01-15 04:25:00",
         "success", "worker-gamma", 1, 0, "2024-01-15 04:10:10", 300),

        # === data_quality Jan 14 (all success) ===
        ("data_quality", "check_completeness", "dataset_triggered__2024-01-14T02:30:00+00:00",
         "2024-01-14 02:30:00", "2024-01-14 02:35:00", "2024-01-14 02:45:00",
         "success", "worker-beta", 1, 3, "2024-01-14 02:30:15", 300),
        ("data_quality", "check_accuracy", "dataset_triggered__2024-01-14T02:30:00+00:00",
         "2024-01-14 02:30:00", "2024-01-14 02:50:00", "2024-01-14 03:00:00",
         "success", "worker-delta", 1, 0, "2024-01-14 02:45:10", 300),
        ("data_quality", "check_freshness", "dataset_triggered__2024-01-14T02:30:00+00:00",
         "2024-01-14 02:30:00", "2024-01-14 02:50:00", "2024-01-14 02:55:00",
         "success", "worker-alpha", 1, 0, "2024-01-14 02:45:10", 300),

        # === data_quality Jan 15 (STUCK RETRY on check_completeness) ===
        # ANOMALY: up_for_retry since Jan 15 06:30 but retry never started
        ("data_quality", "check_completeness", "dataset_triggered__2024-01-15T06:00:00+00:00",
         "2024-01-15 06:00:00", "2024-01-15 06:05:00", "2024-01-15 06:30:00",
         "up_for_retry", "worker-epsilon", 1, 3, "2024-01-15 06:00:30", 300),

        # === model_serving Jan 14 (all success) ===
        ("model_serving", "validate_model", "dataset_triggered__2024-01-14T04:30:00+00:00",
         "2024-01-14 04:30:00", "2024-01-14 04:35:00", "2024-01-14 04:45:00",
         "success", "worker-delta", 1, 0, "2024-01-14 04:30:35", 300),
        ("model_serving", "deploy_model", "dataset_triggered__2024-01-14T04:30:00+00:00",
         "2024-01-14 04:30:00", "2024-01-14 04:50:00", "2024-01-14 05:00:00",
         "success", "worker-alpha", 1, 0, "2024-01-14 04:45:10", 300),
        ("model_serving", "smoke_test", "dataset_triggered__2024-01-14T04:30:00+00:00",
         "2024-01-14 04:30:00", "2024-01-14 05:05:00", "2024-01-14 05:15:00",
         "success", "worker-beta", 1, 0, "2024-01-14 05:00:10", 300),
    ]
    c.executemany(
        """INSERT INTO task_instance
           (dag_id, task_id, run_id, execution_date, start_date, end_date,
            state, hostname, try_number, max_retries, queued_dttm, retry_delay_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        instances,
    )


def populate_dataset_events(conn):
    c = conn.cursor()
    events = [
        # Jan 14 events
        (1, 1, "etl_pipeline", "extract_data", "2024-01-14 02:15:00", None),
        (2, 2, "etl_pipeline", "transform_data", "2024-01-14 03:00:00", None),
        (3, 3, "etl_pipeline", "load_data", "2024-01-14 03:30:00", None),
        (4, 4, "ml_training", "train_model", "2024-01-14 04:15:00", None),
        # Jan 15 events
        (5, 1, "etl_pipeline", "extract_data", "2024-01-15 02:15:00", None),
        (6, 2, "etl_pipeline", "transform_data", "2024-01-15 03:00:00", None),
        (7, 3, "etl_pipeline", "load_data", "2024-01-15 03:30:00", None),
        # Jan 16 events
        (8, 1, "etl_pipeline", "extract_data", "2024-01-16 02:15:00", None),
        # This features.parquet event should trigger ml_training but DIDN'T
        (9, 2, "etl_pipeline", "transform_data", "2024-01-16 03:15:00", None),
        (10, 3, "etl_pipeline", "load_data", "2024-01-16 03:45:00", None),
    ]
    c.executemany("INSERT INTO dataset_event VALUES (?, ?, ?, ?, ?, ?)", events)


def populate_dataset_dag_run_queue(conn):
    c = conn.cursor()
    # ANOMALY: unconsumed queue entry - ml_training should have been triggered
    c.execute(
        "INSERT INTO dataset_dag_run_queue (dataset_id, target_dag_id, created_at) VALUES (?, ?, ?)",
        (2, "ml_training", "2024-01-16 03:15:00"),
    )


def populate_worker_heartbeats(conn):
    c = conn.cursor()
    heartbeats = [
        ("worker-alpha", "2024-01-17 07:55:00"),   # alive
        ("worker-beta", "2024-01-17 07:58:00"),     # alive
        ("worker-gamma", "2024-01-16 02:45:00"),    # DEAD - ~29h stale
        ("worker-delta", "2024-01-17 07:50:00"),    # alive
        ("worker-epsilon", "2024-01-17 02:05:00"),  # DEAD - ~6h stale
    ]
    c.executemany("INSERT INTO worker_heartbeat VALUES (?, ?)", heartbeats)


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    populate_dags(conn)
    populate_datasets(conn)
    populate_task_dependencies(conn)
    populate_dag_runs(conn)
    populate_task_instances(conn)
    populate_dataset_events(conn)
    populate_dataset_dag_run_queue(conn)
    populate_worker_heartbeats(conn)
    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
