#!/usr/bin/env python3
"""Generate benchmark evaluation data across multiple storage formats.

Creates:
  - SQLite database with model and task metadata
  - CSV file with inter-task code similarity annotations
  - Parquet files for run results (via DuckDB)
"""
import csv
import os
import sqlite3

import duckdb

DATA_DIR = "/app/data"

MODELS = [
    {"name": "model-alpha", "release_date": "2025-05-01", "provider": "provider-a", "context_window": 128000},
    {"name": "model-beta", "release_date": "2025-08-15", "provider": "provider-b", "context_window": 128000},
    {"name": "model-gamma", "release_date": "2025-11-01", "provider": "provider-a", "context_window": 128000},
    {"name": "model-delta", "release_date": "2026-02-01", "provider": "provider-c", "context_window": 256000},
    {"name": "model-epsilon", "release_date": "2026-04-01", "provider": "provider-b", "context_window": 256000},
    {"name": "model-zeta", "release_date": "2026-05-15", "provider": "provider-c", "context_window": 512000},
]

TASKS = [
    {"id": "owner-a__repo-1-101", "created_at": "2025-03-10", "repo": "owner-a/repo-1", "language": "python"},
    {"id": "owner-a__repo-1-115", "created_at": "2025-04-22", "repo": "owner-a/repo-1", "language": "python"},
    {"id": "owner-b__repo-2-201", "created_at": "2025-06-05", "repo": "owner-b/repo-2", "language": "javascript"},
    {"id": "owner-b__repo-2-218", "created_at": "2025-07-18", "repo": "owner-b/repo-2", "language": "javascript"},
    {"id": "owner-c__repo-3-301", "created_at": "2025-09-02", "repo": "owner-c/repo-3", "language": "python"},
    {"id": "owner-c__repo-3-322", "created_at": "2025-10-15", "repo": "owner-c/repo-3", "language": "python"},
    {"id": "owner-d__repo-4-401", "created_at": "2025-11-28", "repo": "owner-d/repo-4", "language": "rust"},
    {"id": "owner-d__repo-4-419", "created_at": "2026-02-01", "repo": "owner-d/repo-4", "language": "rust"},
    {"id": "owner-e__repo-5-501", "created_at": "2026-02-12", "repo": "owner-e/repo-5", "language": "go"},
    {"id": "owner-e__repo-5-515", "created_at": "2026-03-20", "repo": "owner-e/repo-5", "language": "go"},
    {"id": "owner-f__repo-6-601", "created_at": "2026-04-08", "repo": "owner-f/repo-6", "language": "python"},
    {"id": "owner-f__repo-6-612", "created_at": "2026-05-15", "repo": "owner-f/repo-6", "language": "python"},
]

TASK_IDS = [t["id"] for t in TASKS]

SIMILARITY_PAIRS = [
    ("owner-a__repo-1-101", "owner-c__repo-3-301", 0.85),
    ("owner-a__repo-1-115", "owner-d__repo-4-401", 0.91),
    ("owner-b__repo-2-201", "owner-e__repo-5-501", 0.78),
    ("owner-b__repo-2-218", "owner-d__repo-4-419", 0.83),
    ("owner-c__repo-3-301", "owner-f__repo-6-601", 0.82),
    ("owner-c__repo-3-322", "owner-f__repo-6-601", 0.95),
    ("owner-e__repo-5-515", "owner-f__repo-6-612", 0.72),
]

# Results: model -> list of 12 lists (per task), each inner list has 5 run results
RESULTS = {
    "model-alpha": [
        [1, 0, 1, 0, 1],
        [0, 1, 0, 0, 1],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
    ],
    "model-beta": [
        [1, 1, 1, 0, 1],
        [1, 0, 1, 0, 1],
        [0, 1, 0, 0, 1],
        [0, 0, 1, 0, 0],
        [1, 0, 0, 1, 0],
        [0, 0, 0, 0, 1],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
    ],
    "model-gamma": [
        [1, 1, 1, 1, 1],
        [1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1],
        [1, 1, 0, 1, 1],
        [0, 1, 1, 0, 1],
        [1, 0, 1, 0, 1],
        [0, 1, 0, 1, 0],
        [0, 0, 0, 0, 1],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0],
    ],
    "model-delta": [
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 1, 0, 1, 1],
        [1, 1, 1, 0, 1],
        [0, 1, 1, 0, 1],
        [1, 0, 1, 1, 1],
        [1, 0, 0, 1, 0],
        [0, 0, 1, 0, 0],
        [0, 0, 0, 0, 1],
        [0, 0, 0, 0, 0],
    ],
    "model-epsilon": [
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 0, 1],
        [1, 1, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [0, 1, 1, 1, 0],
        [1, 0, 1, 1, 1],
        [0, 1, 0, 0, 1],
        [0, 0, 0, 0, 0],
    ],
    "model-zeta": [
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1],
        [1, 0, 1, 1, 1],
        [1, 1, 1, 0, 1],
        [0, 1, 1, 1, 0],
        [1, 0, 0, 1, 0],
    ],
}


def create_sqlite_db():
    """Create SQLite database with model and task metadata."""
    db_path = os.path.join(DATA_DIR, "benchmark.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE models (
            name TEXT PRIMARY KEY,
            release_date TEXT NOT NULL,
            provider TEXT NOT NULL,
            context_window INTEGER NOT NULL
        )
    """)
    for m in MODELS:
        cursor.execute(
            "INSERT INTO models VALUES (?, ?, ?, ?)",
            (m["name"], m["release_date"], m["provider"], m["context_window"]),
        )

    cursor.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            repo TEXT NOT NULL,
            language TEXT NOT NULL
        )
    """)
    for t in TASKS:
        cursor.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?)",
            (t["id"], t["created_at"], t["repo"], t["language"]),
        )

    conn.commit()
    conn.close()


def create_similarity_csv():
    """Create CSV file with inter-task code similarity annotations."""
    csv_path = os.path.join(DATA_DIR, "similarity.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["task_a", "task_b", "jaccard_similarity"])
        for task_a, task_b, score in SIMILARITY_PAIRS:
            writer.writerow([task_a, task_b, score])


def create_parquet_files():
    """Create Parquet run result files using DuckDB.

    Each model gets a Parquet file with columns:
      instance_id VARCHAR, r1..r5 BOOLEAN (nullable)

    NULL in a run column indicates a missing or error entry
    (should be treated as resolved=false by the pipeline).
    """
    runs_dir = os.path.join(DATA_DIR, "runs")
    os.makedirs(runs_dir, exist_ok=True)

    conn = duckdb.connect()

    for model in MODELS:
        model_name = model["name"]

        values = []
        for task_idx, task_id in enumerate(TASK_IDS):
            run_values = []
            for run_idx in range(5):
                # Edge case: missing entry (model-gamma run 2 task 515)
                if (model_name == "model-gamma" and run_idx == 1
                        and task_id == "owner-e__repo-5-515"):
                    run_values.append("NULL::BOOLEAN")
                    continue

                # Edge case: error status without resolved key
                if (model_name == "model-beta" and run_idx == 3
                        and task_id == "owner-b__repo-2-201"):
                    run_values.append("NULL::BOOLEAN")
                    continue

                result = RESULTS[model_name][task_idx][run_idx]
                run_values.append("true" if result else "false")

            values.append(
                f"('{task_id}', {', '.join(run_values)})"
            )

        values_str = ", ".join(values)
        parquet_path = os.path.join(runs_dir, f"{model_name}.parquet")

        conn.execute(f"""
            COPY (
                SELECT * FROM (VALUES {values_str})
                AS t(instance_id, r1, r2, r3, r4, r5)
            ) TO '{parquet_path}' (FORMAT PARQUET)
        """)

    conn.close()


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    create_sqlite_db()
    create_similarity_csv()
    create_parquet_files()
    print("Data generation complete.")


if __name__ == "__main__":
    main()
