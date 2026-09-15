#!/usr/bin/env python3
"""Build the cluster topology SQLite database at /app/cluster.db."""
import sqlite3
import os

os.makedirs("/app", exist_ok=True)
conn = sqlite3.connect("/app/cluster.db")
c = conn.cursor()

c.execute("""
CREATE TABLE nodes (
    rank INTEGER PRIMARY KEY,
    hostname TEXT NOT NULL,
    cores INTEGER NOT NULL,
    gpus INTEGER NOT NULL DEFAULT 0
)
""")

c.execute("""
CREATE TABLE node_properties (
    rank INTEGER NOT NULL,
    property TEXT NOT NULL,
    PRIMARY KEY (rank, property),
    FOREIGN KEY (rank) REFERENCES nodes(rank)
)
""")

c.execute("""
CREATE TABLE node_topology (
    rank INTEGER PRIMARY KEY,
    rack TEXT NOT NULL,
    switch_id TEXT NOT NULL,
    FOREIGN KEY (rank) REFERENCES nodes(rank)
)
""")

nodes = [
    (0, "standard0", 4, 0), (1, "standard1", 4, 0),
    (2, "standard2", 4, 0), (3, "standard3", 4, 0),
    (4, "highmem0", 4, 0),  (5, "highmem1", 4, 0),
    (6, "highmem2", 4, 0),  (7, "highmem3", 4, 0),
    (8, "gpu0", 4, 2),      (9, "gpu1", 4, 2),
    (10, "gpu2", 4, 2),     (11, "gpu3", 4, 2),
    (12, "gpumem0", 4, 2),  (13, "gpumem1", 4, 2),
    (14, "gpumem2", 4, 2),  (15, "gpumem3", 4, 2),
]
c.executemany("INSERT INTO nodes VALUES (?, ?, ?, ?)", nodes)

props = (
    [(r, "standard") for r in range(0, 4)]
    + [(r, "highmem") for r in range(4, 8)]
    + [(r, "highmem") for r in range(12, 16)]
    + [(r, "gpu") for r in range(8, 16)]
)
c.executemany("INSERT INTO node_properties VALUES (?, ?)", props)

topo = (
    [(r, "rack-a", "sw-a1") for r in range(0, 4)]
    + [(r, "rack-a", "sw-a2") for r in range(4, 8)]
    + [(r, "rack-b", "sw-b1") for r in range(8, 12)]
    + [(r, "rack-b", "sw-b2") for r in range(12, 16)]
)
c.executemany("INSERT INTO node_topology VALUES (?, ?, ?)", topo)

conn.commit()
conn.close()
