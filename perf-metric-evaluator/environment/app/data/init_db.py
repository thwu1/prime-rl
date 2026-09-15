#!/usr/bin/env python3
"""Initialize SQLite database from JSON benchmark data.

Reads the benchmark results JSON and creates a normalized SQLite database
with tables for tasks, benchmarks, attempts, timings, and config.
"""
import json
import sqlite3


def init_db():
    with open("/tmp/init_data.json") as f:
        data = json.load(f)

    conn = sqlite3.connect("/app/data/benchmark.db")
    c = conn.cursor()

    c.execute("""CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY,
        description TEXT
    )""")

    c.execute("""CREATE TABLE benchmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT REFERENCES tasks(task_id),
        seq INTEGER,
        base_time REAL,
        human_time REAL
    )""")

    c.execute("""CREATE TABLE config (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    c.execute("""CREATE TABLE attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        model_id TEXT,
        attempt_num INTEGER,
        correct INTEGER,
        patch TEXT
    )""")

    c.execute("""CREATE TABLE timings (
        attempt_id INTEGER REFERENCES attempts(id),
        benchmark_id INTEGER REFERENCES benchmarks(id),
        model_time REAL,
        PRIMARY KEY (attempt_id, benchmark_id)
    )""")

    for key, value in data["config"].items():
        c.execute("INSERT INTO config VALUES (?, ?)", (key, str(value)))

    for task in data["tasks"]:
        c.execute("INSERT INTO tasks VALUES (?, ?)",
                  (task["task_id"], task["description"]))
        base_times = task.get("base_times", [None] * len(task["human_times"]))
        for seq, (bt, ht) in enumerate(zip(base_times, task["human_times"])):
            c.execute(
                "INSERT INTO benchmarks (task_id, seq, base_time, human_time) VALUES (?, ?, ?, ?)",
                (task["task_id"], seq, bt, ht))

    c.execute("SELECT id, task_id, seq FROM benchmarks ORDER BY task_id, seq")
    benchmark_map = {}
    for bid, tid, seq in c.fetchall():
        benchmark_map[(tid, seq)] = bid

    for model_id, tasks in data["model_results"].items():
        for task_id, task_data in tasks.items():
            for attempt in task_data["attempts"]:
                c.execute(
                    "INSERT INTO attempts (task_id, model_id, attempt_num, correct, patch) VALUES (?, ?, ?, ?, ?)",
                    (task_id, model_id, attempt["attempt"],
                     1 if attempt["correct"] else 0,
                     attempt.get("patch", "")))
                attempt_id = c.lastrowid
                for seq, mt in enumerate(attempt["times"]):
                    bid = benchmark_map[(task_id, seq)]
                    c.execute("INSERT INTO timings VALUES (?, ?, ?)",
                              (attempt_id, bid, mt))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
