#!/usr/bin/env python3
"""Create the historical evaluation database for prior challenge rounds."""

import sqlite3
import os

DB_PATH = "/app/data/historical.db"

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""CREATE TABLE rounds (
    round_id INTEGER PRIMARY KEY,
    round_name TEXT NOT NULL
)""")

c.execute("""CREATE TABLE systems (
    system_id INTEGER PRIMARY KEY,
    system_name TEXT UNIQUE NOT NULL
)""")

c.execute("""CREATE TABLE results (
    round_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    PRIMARY KEY (round_id, system_id, metric_name),
    FOREIGN KEY (round_id) REFERENCES rounds(round_id),
    FOREIGN KEY (system_id) REFERENCES systems(system_id)
)""")

c.executemany("INSERT INTO rounds VALUES (?, ?)", [
    (1, "BioASQ Round 1"),
    (2, "BioASQ Round 2"),
    (3, "BioASQ Round 3"),
])

c.executemany("INSERT INTO systems VALUES (?, ?)", [
    (1, "alpha"),
    (2, "beta"),
    (3, "gamma"),
])

historical_data = [
    # Alpha - Round 1
    (1, 1, "yesno_macro_f1", 0.72),
    (1, 1, "factoid_mrr", 0.70),
    (1, 1, "list_mean_f1", 0.68),
    (1, 1, "map", 0.65),
    (1, 1, "gmap", 0.55),
    # Alpha - Round 2
    (2, 1, "yesno_macro_f1", 0.78),
    (2, 1, "factoid_mrr", 0.75),
    (2, 1, "list_mean_f1", 0.72),
    (2, 1, "map", 0.70),
    (2, 1, "gmap", 0.60),
    # Alpha - Round 3
    (3, 1, "yesno_macro_f1", 0.74),
    (3, 1, "factoid_mrr", 0.73),
    (3, 1, "list_mean_f1", 0.71),
    (3, 1, "map", 0.68),
    (3, 1, "gmap", 0.58),
    # Beta - Round 1
    (1, 2, "yesno_macro_f1", 0.90),
    (1, 2, "factoid_mrr", 0.80),
    (1, 2, "list_mean_f1", 0.92),
    (1, 2, "map", 0.82),
    (1, 2, "gmap", 0.75),
    # Beta - Round 2
    (2, 2, "yesno_macro_f1", 0.95),
    (2, 2, "factoid_mrr", 0.85),
    (2, 2, "list_mean_f1", 0.96),
    (2, 2, "map", 0.85),
    (2, 2, "gmap", 0.80),
    # Beta - Round 3
    (3, 2, "yesno_macro_f1", 1.00),
    (3, 2, "factoid_mrr", 0.82),
    (3, 2, "list_mean_f1", 0.98),
    (3, 2, "map", 0.88),
    (3, 2, "gmap", 0.82),
    # Gamma - Round 1
    (1, 3, "yesno_macro_f1", 0.55),
    (1, 3, "factoid_mrr", 0.52),
    (1, 3, "list_mean_f1", 0.50),
    (1, 3, "map", 0.40),
    (1, 3, "gmap", 0.30),
    # Gamma - Round 2
    (2, 3, "yesno_macro_f1", 0.60),
    (2, 3, "factoid_mrr", 0.48),
    (2, 3, "list_mean_f1", 0.55),
    (2, 3, "map", 0.42),
    (2, 3, "gmap", 0.32),
    # Gamma - Round 3
    (3, 3, "yesno_macro_f1", 0.58),
    (3, 3, "factoid_mrr", 0.50),
    (3, 3, "list_mean_f1", 0.58),
    (3, 3, "map", 0.45),
    (3, 3, "gmap", 0.35),
]

c.executemany("INSERT INTO results VALUES (?, ?, ?, ?)", historical_data)

conn.commit()
conn.close()

print(f"Historical database created at {DB_PATH}")
