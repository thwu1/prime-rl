#!/usr/bin/env python3
"""Persist checkpoint state to disk for pipeline inspection."""

import json
import os
import sqlite3

from streaming import Transaction
from pipeline import FraudDetectionPipeline

CHECKPOINT_DIR = "/app/checkpoints"
DATA_DIR = os.path.join(CHECKPOINT_DIR, "data")
DB_PATH = os.path.join(CHECKPOINT_DIR, "meta.db")

os.makedirs(DATA_DIR, exist_ok=True)

# Sample transactions — all small amounts to populate keyed state
events = [
    Transaction(10, 0.50, 1000, "s0"),
    Transaction(11, 0.90, 2000, "s1"),
    Transaction(22, 0.30, 3000, "s2"),
    Transaction(33, 0.70, 4000, "s3"),
    Transaction(44, 0.60, 5000, "s4"),
    Transaction(55, 0.80, 6000, "s5"),
]

db = sqlite3.connect(DB_PATH)
db.execute(
    "CREATE TABLE checkpoints ("
    "  id INTEGER PRIMARY KEY,"
    "  parallelism INTEGER NOT NULL,"
    "  checkpoint_id INTEGER NOT NULL,"
    "  source_offset INTEGER,"
    "  num_operators INTEGER,"
    "  total_state_entries INTEGER,"
    "  alert_count INTEGER"
    ")"
)
db.execute(
    "CREATE TABLE operator_states ("
    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "  checkpoint_ref INTEGER NOT NULL,"
    "  operator_id TEXT NOT NULL,"
    "  state_file TEXT NOT NULL,"
    "  num_backend_keys INTEGER DEFAULT 0,"
    "  watermark INTEGER,"
    "  num_alerts INTEGER DEFAULT 0,"
    "  FOREIGN KEY (checkpoint_ref) REFERENCES checkpoints(id)"
    ")"
)
db.execute(
    "CREATE TABLE state_keys ("
    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "  checkpoint_ref INTEGER NOT NULL,"
    "  operator_id TEXT NOT NULL,"
    "  composite_key TEXT NOT NULL,"
    "  raw_key TEXT NOT NULL,"
    "  state_name TEXT NOT NULL,"
    "  FOREIGN KEY (checkpoint_ref) REFERENCES checkpoints(id)"
    ")"
)

row_id = 0
for parallelism in [2, 3, 4]:
    pipeline = FraudDetectionPipeline(events, parallelism=parallelism)
    pipeline.run(checkpoint_interval=len(events))

    result = pipeline.coordinator.get_latest_completed()
    if result is None:
        continue

    cp_id, states = result
    row_id += 1

    total_entries = 0
    alert_count = 0
    source_offset = None
    num_ops = 0

    for task_id, state in states.items():
        filename = "p%d_cp%d_%s.json" % (parallelism, cp_id, task_id)
        filepath = os.path.join(DATA_DIR, filename)
        with open(filepath, "w") as f:
            json.dump(state, f, indent=2, default=str)

        if task_id.startswith("source"):
            source_offset = state.get("offset", 0)
            db.execute(
                "INSERT INTO operator_states"
                " (checkpoint_ref, operator_id, state_file,"
                "  num_backend_keys, watermark, num_alerts)"
                " VALUES (?, ?, ?, 0, NULL, 0)",
                (row_id, task_id, filename),
            )
        elif "backend" in state:
            num_ops += 1
            backend = state["backend"]
            total_entries += len(backend)
            alert_count += state.get("num_alerts", 0)

            for composite_key in backend:
                parts = composite_key.split(":", 1)
                raw_key = parts[0]
                state_name = parts[1] if len(parts) > 1 else ""
                db.execute(
                    "INSERT INTO state_keys"
                    " (checkpoint_ref, operator_id,"
                    "  composite_key, raw_key, state_name)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (row_id, task_id, composite_key, raw_key, state_name),
                )

            db.execute(
                "INSERT INTO operator_states"
                " (checkpoint_ref, operator_id, state_file,"
                "  num_backend_keys, watermark, num_alerts)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    task_id,
                    filename,
                    len(backend),
                    state.get("watermark"),
                    state.get("num_alerts", 0),
                ),
            )

    db.execute(
        "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            row_id,
            parallelism,
            cp_id,
            source_offset,
            num_ops,
            total_entries,
            alert_count,
        ),
    )

db.commit()
db.close()

print("Checkpoint data persisted to %s" % CHECKPOINT_DIR)
