"""Initialize the evaluation SQLite database with normalized schema."""
import os
import sqlite3

DB_PATH = "/app/eval.db"


def create_schema(cur):
    cur.execute("""
        CREATE TABLE models (
            model_id TEXT PRIMARY KEY,
            release_date TEXT NOT NULL,
            training_cutoff TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE pricing (
            model_id TEXT NOT NULL REFERENCES models(model_id),
            tier TEXT NOT NULL CHECK(tier IN ('input', 'cached_input', 'output')),
            price_per_mtok REAL NOT NULL,
            PRIMARY KEY (model_id, tier)
        )
    """)
    cur.execute("""
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            repo TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE runs (
            model_id TEXT NOT NULL REFERENCES models(model_id),
            task_id TEXT NOT NULL REFERENCES tasks(task_id),
            run_id INTEGER NOT NULL,
            resolved INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            cached_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            PRIMARY KEY (model_id, task_id, run_id)
        )
    """)


def insert_data(cur):
    models = [
        ("alpha-v1", "2025-01-15", "2024-12-01"),
        ("beta-2", "2025-04-01", "2025-02-01"),
        ("gamma-3b", "2025-06-15", "2025-04-01"),
        ("delta-coder", "2025-08-01", "2025-06-01"),
        ("epsilon-7b", "2025-10-01", "2025-08-01"),
    ]
    cur.executemany("INSERT INTO models VALUES (?,?,?)", models)

    pricing = [
        ("alpha-v1", "input", 3.0),
        ("alpha-v1", "cached_input", 0.3),
        ("alpha-v1", "output", 15.0),
        ("beta-2", "input", 2.0),
        ("beta-2", "cached_input", 0.5),
        ("beta-2", "output", 10.0),
        ("gamma-3b", "input", 1.5),
        ("gamma-3b", "cached_input", 0.15),
        ("gamma-3b", "output", 7.5),
        ("delta-coder", "input", 5.0),
        ("delta-coder", "cached_input", 0.5),
        ("delta-coder", "output", 25.0),
        ("epsilon-7b", "input", 0.5),
        ("epsilon-7b", "cached_input", 0.05),
        ("epsilon-7b", "output", 2.5),
    ]
    cur.executemany("INSERT INTO pricing VALUES (?,?,?)", pricing)

    tasks = [
        ("task-001", "org-a/repo-1", "2024-11-15"),
        ("task-002", "org-b/repo-2", "2024-12-20"),
        ("task-003", "org-c/repo-3", "2025-01-10"),
        ("task-004", "org-d/repo-4", "2025-02-28"),
        ("task-005", "org-e/repo-5", "2025-03-20"),
        ("task-006", "org-f/repo-6", "2025-05-01"),
        ("task-007", "org-g/repo-7", "2025-06-10"),
        ("task-008", "org-h/repo-8", "2025-07-15"),
        ("task-009", "org-i/repo-9", "2025-08-20"),
        ("task-010", "org-j/repo-10", "2025-09-25"),
    ]
    cur.executemany("INSERT INTO tasks VALUES (?,?,?)", tasks)

    # Per-model: task success counts (out of 5 runs), tokens per run
    run_specs = {
        "alpha-v1": {
            "successes": [2, 0, 1, 0, 1, 0, 1, 0, 0, 0],
            "input": 800000, "cached": 480000, "output": 40000,
        },
        "beta-2": {
            "successes": [3, 2, 1, 1, 2, 1, 0, 0, 0, 0],
            "input": 1000000, "cached": 700000, "output": 50000,
        },
        "gamma-3b": {
            "successes": [4, 3, 3, 2, 3, 3, 2, 1, 0, 0],
            "input": 1200000, "cached": 960000, "output": 55000,
        },
        "delta-coder": {
            "successes": [5, 4, 3, 3, 4, 4, 3, 2, 2, 0],
            "input": 1500000, "cached": 1275000, "output": 60000,
        },
        "epsilon-7b": {
            "successes": [5, 5, 4, 3, 4, 5, 4, 3, 0, 1],
            "input": 2000000, "cached": 1800000, "output": 70000,
        },
    }

    task_ids = [f"task-{i:03d}" for i in range(1, 11)]

    for model_id, spec in run_specs.items():
        for task_idx, task_id in enumerate(task_ids):
            num_success = spec["successes"][task_idx]
            for run_id in range(1, 6):
                resolved = 1 if run_id <= num_success else 0
                cur.execute(
                    "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                    (model_id, task_id, run_id, resolved,
                     spec["input"], spec["cached"], spec["output"]),
                )


if __name__ == "__main__":
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    create_schema(cur)
    insert_data(cur)
    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")
