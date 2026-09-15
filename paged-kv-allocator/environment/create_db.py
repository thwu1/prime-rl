#!/usr/bin/env python3
"""Create the initial workload SQLite database."""
import sqlite3

DB_PATH = "/app/workload.db"

conn = sqlite3.connect(DB_PATH)
conn.execute("""
    CREATE TABLE operations (
        step_id INTEGER PRIMARY KEY AUTOINCREMENT,
        op_type TEXT NOT NULL,
        seq_id TEXT,
        prompt_length INTEGER,
        num_tokens INTEGER,
        source_seq_id TEXT,
        new_seq_id TEXT
    )
""")
conn.execute("""
    CREATE TABLE block_hashes (
        step_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        block_hash TEXT NOT NULL,
        PRIMARY KEY (step_id, position),
        FOREIGN KEY (step_id) REFERENCES operations(step_id)
    )
""")

workload = [
    {"op": "prefill", "seq_id": "s0", "prompt_length": 10},
    {"op": "prefill", "seq_id": "s1", "prompt_length": 7},
    {"op": "fork", "source_seq_id": "s0", "new_seq_id": "s0_a"},
    {"op": "fork", "source_seq_id": "s0", "new_seq_id": "s0_b"},
    {"op": "decode", "seq_id": "s0", "num_tokens": 6},
    {"op": "decode", "seq_id": "s0_a", "num_tokens": 2},
    {"op": "fork", "source_seq_id": "s0_a", "new_seq_id": "s0_a1"},
    {"op": "decode", "seq_id": "s0_a", "num_tokens": 4},
    {"op": "decode", "seq_id": "s0_a1", "num_tokens": 4},
    {"op": "decode", "seq_id": "s0_b", "num_tokens": 6},
    {"op": "fork", "source_seq_id": "s1", "new_seq_id": "s1_a"},
    {"op": "decode", "seq_id": "s1", "num_tokens": 3},
    {"op": "decode", "seq_id": "s1_a", "num_tokens": 3},
    {"op": "free", "seq_id": "s0"},
    {"op": "free", "seq_id": "s0_a"},
    {"op": "free", "seq_id": "s0_a1"},
    {"op": "free", "seq_id": "s0_b"},
    {"op": "free", "seq_id": "s1"},
    {"op": "free", "seq_id": "s1_a"},
]

for entry in workload:
    cursor = conn.execute(
        "INSERT INTO operations (op_type, seq_id, prompt_length, num_tokens, "
        "source_seq_id, new_seq_id) VALUES (?, ?, ?, ?, ?, ?)",
        (
            entry.get("op"),
            entry.get("seq_id"),
            entry.get("prompt_length"),
            entry.get("num_tokens"),
            entry.get("source_seq_id"),
            entry.get("new_seq_id"),
        ),
    )

conn.commit()
conn.close()
