#!/usr/bin/env python3
"""Create the metadata SQLite database with historical task execution data."""
import sqlite3
import os

DB_PATH = "/app/metadata.db"


def create_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # DAG run history table
    c.execute("""
        CREATE TABLE dag_run (
            dag_id TEXT NOT NULL,
            run_id TEXT NOT NULL PRIMARY KEY,
            execution_date TEXT NOT NULL,
            state TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT
        )
    """)

    # Scheduler event log table
    c.execute("""
        CREATE TABLE scheduler_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            dag_id TEXT,
            message TEXT
        )
    """)

    # Task execution records with timing and pool usage
    c.execute("""
        CREATE TABLE task_execution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dag_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            pool TEXT NOT NULL,
            pool_slots INTEGER NOT NULL,
            start_ts REAL NOT NULL,
            end_ts REAL NOT NULL,
            state TEXT NOT NULL DEFAULT 'success',
            FOREIGN KEY (run_id) REFERENCES dag_run(run_id)
        )
    """)

    # --- Populate dag_run ---
    dag_runs = [
        ("ingest_orders", "run_001", "2024-06-15T00:00:00", "success",
         "2024-06-15T00:00:00", "2024-06-15T00:15:00"),
        ("ingest_events", "run_002", "2024-06-15T00:01:40", "success",
         "2024-06-15T00:01:40", "2024-06-15T00:14:40"),
        ("reporting", "run_003", "2024-06-15T00:03:20", "success",
         "2024-06-15T00:03:20", "2024-06-15T00:23:20"),
        ("transform_orders", "run_004", "2024-06-15T01:00:00", "success",
         "2024-06-15T01:00:00", "2024-06-15T01:35:00"),
        ("transform_events", "run_005", "2024-06-15T01:01:40", "success",
         "2024-06-15T01:01:40", "2024-06-15T01:23:40"),
        ("feature_engineering", "run_006", "2024-06-15T00:56:40", "success",
         "2024-06-15T00:56:40", "2024-06-15T01:51:40"),
        ("quality_monitor", "run_007", "2024-06-15T01:03:20", "success",
         "2024-06-15T01:03:20", "2024-06-15T01:23:20"),
        ("train_model", "run_008", "2024-06-15T01:50:00", "success",
         "2024-06-15T01:50:00", "2024-06-15T03:15:00"),
        ("scoring", "run_009", "2024-06-15T01:56:40", "success",
         "2024-06-15T01:56:40", "2024-06-15T02:26:40"),
        ("data_remediation", "run_010", "2024-06-15T03:40:00", "success",
         "2024-06-15T03:40:00", "2024-06-15T03:59:40"),
        ("auto_retrain", "run_011", "2024-06-15T03:50:00", "success",
         "2024-06-15T03:50:00", "2024-06-15T04:05:00"),
        ("ingest_orders", "run_012", "2024-06-15T03:46:40", "success",
         "2024-06-15T03:46:40", "2024-06-15T03:55:00"),
        ("data_remediation", "run_013", "2024-06-15T03:48:20", "success",
         "2024-06-15T03:48:20", "2024-06-15T04:11:20"),
        ("transform_events", "run_015", "2024-06-15T04:43:20", "failed",
         "2024-06-15T04:43:20", "2024-06-15T04:50:00"),
    ]
    c.executemany(
        "INSERT INTO dag_run VALUES (?, ?, ?, ?, ?, ?)", dag_runs
    )

    # --- Populate scheduler_event ---
    scheduler_events = [
        (1718438400, "dag_triggered", "ingest_orders",
         "Cron trigger: */30 * * * *"),
        (1718438500, "dag_triggered", "ingest_events",
         "Cron trigger: */15 * * * *"),
        (1718438600, "dag_triggered", "reporting",
         "Dataset trigger: user_scores"),
        (1718439000, "dataset_produced", "ingest_orders",
         "Produced dataset: orders_raw"),
        (1718438980, "dataset_produced", "ingest_events",
         "Produced dataset: events_raw"),
        (1718441800, "dag_triggered", "feature_engineering",
         "Dataset trigger: orders_clean,events_processed"),
        (1718442000, "dag_triggered", "transform_orders",
         "Dataset trigger: orders_raw"),
        (1718442100, "dag_triggered", "transform_events",
         "Dataset trigger: events_raw"),
        (1718442200, "dag_triggered", "quality_monitor",
         "Dataset trigger: user_scores"),
        (1718443300, "dataset_produced", "feature_engineering",
         "Produced dataset: feature_store"),
        (1718445000, "dag_triggered", "train_model",
         "Dataset trigger: feature_store"),
        (1718445800, "dag_triggered", "scoring",
         "Cron trigger: 0 */4 * * *"),
        (1718449200, "dataset_produced", "train_model",
         "Produced dataset: model_artifact"),
        (1718447300, "dataset_produced", "scoring",
         "Produced dataset: user_scores"),
        (1718450400, "dag_triggered", "data_remediation",
         "Dataset trigger: data_corrections"),
        (1718451000, "dag_triggered", "auto_retrain",
         "Dataset trigger: quality_alerts"),
        (1718452000, "dag_triggered", "ingest_orders",
         "Cron trigger: */30 * * * *"),
        (1718452100, "dag_triggered", "data_remediation",
         "Dataset trigger: data_corrections"),
        (1718455000, "dag_triggered", "transform_events",
         "Dataset trigger: events_raw"),
    ]
    c.executemany(
        "INSERT INTO scheduler_event (timestamp, event_type, dag_id, message) "
        "VALUES (?, ?, ?, ?)",
        scheduler_events,
    )

    # --- Populate task_execution ---
    task_executions = [
        # === io_pool saturation window ===
        # Peak = 9 slots at t=[1718438600, 1718438980)
        # extract(3) + capture(4) + generate_report(2) = 9 > capacity(8)
        ("ingest_orders", "extract", "run_001", "io_pool", 3,
         1718438400, 1718439000, "success"),
        ("ingest_orders", "validate", "run_001", "io_pool", 1,
         1718439000, 1718439300, "success"),
        ("ingest_events", "capture", "run_002", "io_pool", 4,
         1718438500, 1718438980, "success"),
        ("ingest_events", "deduplicate", "run_002", "io_pool", 2,
         1718438980, 1718439280, "success"),
        ("reporting", "generate_report", "run_003", "io_pool", 2,
         1718438600, 1718439500, "success"),
        ("reporting", "distribute", "run_003", "io_pool", 1,
         1718439500, 1718439800, "success"),

        # === compute_pool saturation window ===
        # Peak = 13 slots at t=[1718442200, 1718442800)
        # join_sources(4) + clean(2) + sessionize(3) +
        # check_data_quality(2) + check_model_drift(2) = 13 > capacity(12)
        ("feature_engineering", "join_sources", "run_006", "compute_pool", 4,
         1718441800, 1718443300, "success"),
        ("transform_orders", "clean", "run_004", "compute_pool", 2,
         1718442000, 1718442900, "success"),
        ("transform_events", "sessionize", "run_005", "compute_pool", 3,
         1718442100, 1718442820, "success"),
        ("quality_monitor", "check_data_quality", "run_007", "compute_pool", 2,
         1718442200, 1718442800, "success"),
        ("quality_monitor", "check_model_drift", "run_007", "compute_pool", 2,
         1718442200, 1718443100, "success"),
        ("transform_events", "aggregate", "run_005", "compute_pool", 2,
         1718442820, 1718443420, "success"),
        ("transform_orders", "enrich", "run_004", "compute_pool", 3,
         1718442900, 1718444100, "success"),
        ("quality_monitor", "generate_corrections", "run_007", "compute_pool", 1,
         1718443100, 1718443400, "success"),
        ("feature_engineering", "compute_features", "run_006", "compute_pool", 5,
         1718443300, 1718445100, "success"),

        # === ml_pool saturation window ===
        # Peak = 6 slots at t=[1718446100, 1718447300)
        # train(3) + score_batch(3) = 6 > capacity(4)
        ("train_model", "prepare_data", "run_008", "ml_pool", 1,
         1718445000, 1718445600, "success"),
        ("train_model", "train", "run_008", "ml_pool", 3,
         1718445600, 1718449200, "success"),
        ("scoring", "load_model", "run_009", "ml_pool", 1,
         1718445800, 1718446100, "success"),
        ("scoring", "score_batch", "run_009", "ml_pool", 3,
         1718446100, 1718447300, "success"),
        ("scoring", "export_scores", "run_009", "ml_pool", 1,
         1718447300, 1718447600, "success"),
        ("train_model", "evaluate", "run_008", "ml_pool", 1,
         1718449200, 1718450100, "success"),

        # === Non-overlapping io_pool run (no saturation) ===
        ("data_remediation", "apply_corrections", "run_010", "io_pool", 2,
         1718450400, 1718451000, "success"),
        ("data_remediation", "revalidate", "run_010", "io_pool", 1,
         1718451000, 1718451480, "success"),
        ("data_remediation", "republish", "run_010", "io_pool", 2,
         1718451480, 1718451780, "success"),

        # === Non-overlapping ml_pool run (no saturation) ===
        ("auto_retrain", "analyze_drift", "run_011", "ml_pool", 1,
         1718451000, 1718451600, "success"),
        ("auto_retrain", "trigger_retrain", "run_011", "ml_pool", 1,
         1718451600, 1718451900, "success"),

        # === Later io_pool runs (non-saturating overlap: 3+2=5 < 8) ===
        ("ingest_orders", "extract", "run_012", "io_pool", 3,
         1718452000, 1718452600, "success"),
        ("ingest_orders", "validate", "run_012", "io_pool", 1,
         1718452600, 1718452900, "success"),
        ("data_remediation", "apply_corrections", "run_013", "io_pool", 2,
         1718452100, 1718452700, "success"),
        ("data_remediation", "revalidate", "run_013", "io_pool", 1,
         1718452700, 1718453180, "success"),
        ("data_remediation", "republish", "run_013", "io_pool", 2,
         1718453180, 1718453480, "success"),

        # === A failed run (still consumed slots during execution) ===
        ("transform_events", "sessionize", "run_015", "compute_pool", 3,
         1718455000, 1718455400, "failed"),
    ]
    c.executemany(
        "INSERT INTO task_execution "
        "(dag_id, task_id, run_id, pool, pool_slots, start_ts, end_ts, state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        task_executions,
    )

    # Indexes for efficient querying
    c.execute("CREATE INDEX idx_te_pool ON task_execution(pool)")
    c.execute("CREATE INDEX idx_te_start ON task_execution(start_ts)")
    c.execute("CREATE INDEX idx_te_run ON task_execution(run_id)")
    c.execute("CREATE INDEX idx_dr_dag ON dag_run(dag_id)")
    c.execute("CREATE INDEX idx_se_ts ON scheduler_event(timestamp)")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_db()
