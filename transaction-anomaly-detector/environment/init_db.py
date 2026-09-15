#!/usr/bin/env python3
"""Initialize SQLite database with transaction history workloads."""
import sqlite3
import json

db = sqlite3.connect("/app/data/workload.db")
cur = db.cursor()

cur.executescript("""
CREATE TABLE workloads (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE txns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workload_id INTEGER REFERENCES workloads(id),
    txn_seq INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('committed', 'aborted'))
);
CREATE TABLE ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id INTEGER REFERENCES txns(id),
    op_idx INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('append', 'read')),
    register TEXT NOT NULL,
    payload TEXT
);
""")

# --- workload: h_g1b ---
cur.execute(
    "INSERT INTO workloads (id, name, description) VALUES (1, 'h_g1b', 'intermediate read workload')"
)
h_g1b = [
    (1, "committed", [("append", "x", "1"), ("append", "x", "2")]),
    (2, "committed", [("read", "x", "[1]")]),
    (3, "committed", [("read", "x", "[1, 2]")]),
]
for txn_seq, outcome, ops in h_g1b:
    cur.execute(
        "INSERT INTO txns (workload_id, txn_seq, outcome) VALUES (1, ?, ?)",
        (txn_seq, outcome),
    )
    tid = cur.lastrowid
    for i, (op_type, reg, payload) in enumerate(ops):
        cur.execute(
            "INSERT INTO ops (txn_id, op_idx, type, register, payload) VALUES (?, ?, ?, ?, ?)",
            (tid, i, op_type, reg, payload),
        )

# --- workload: h_complex ---
cur.execute(
    "INSERT INTO workloads (id, name, description) VALUES (2, 'h_complex', 'multi-anomaly workload')"
)
h_complex = [
    (1, "aborted",   [("append", "p", "50")]),
    (2, "committed", [("read", "p", "[50]"), ("append", "q", "1")]),
    (3, "committed", [("read", "q", "[1]")]),
    (4, "committed", [("read", "s", None), ("append", "r", "7")]),
    (5, "committed", [("read", "r", None), ("append", "s", "8")]),
    (6, "committed", [("read", "r", "[7]"), ("read", "s", "[8]")]),
    (7, "committed", [("append", "u", "1"), ("append", "v", "10")]),
    (8, "committed", [("read", "v", None), ("append", "u", "2")]),
    (9, "committed", [("read", "u", "[1, 2]"), ("read", "v", "[10]")]),
]
for txn_seq, outcome, ops in h_complex:
    cur.execute(
        "INSERT INTO txns (workload_id, txn_seq, outcome) VALUES (2, ?, ?)",
        (txn_seq, outcome),
    )
    tid = cur.lastrowid
    for i, (op_type, reg, payload) in enumerate(ops):
        cur.execute(
            "INSERT INTO ops (txn_id, op_idx, type, register, payload) VALUES (?, ?, ?, ?, ?)",
            (tid, i, op_type, reg, payload),
        )

db.commit()
db.close()
