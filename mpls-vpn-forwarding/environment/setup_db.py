#!/usr/bin/env python3
"""Create the SQLite topology database at /app/network.db."""

import sqlite3
import os

DB_PATH = "/app/network.db"
os.makedirs("/app", exist_ok=True)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""
CREATE TABLE routers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    loopback TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('PE', 'P'))
)""")

c.execute("""
CREATE TABLE links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    router_a_id INTEGER NOT NULL REFERENCES routers(id),
    router_b_id INTEGER NOT NULL REFERENCES routers(id),
    metric INTEGER NOT NULL,
    bandwidth_mbps INTEGER NOT NULL
)""")

routers = [
    ("PE1", "10.0.0.1", "PE"),
    ("PE2", "10.0.0.2", "PE"),
    ("PE3", "10.0.0.3", "PE"),
    ("P1", "10.0.0.11", "P"),
    ("P2", "10.0.0.12", "P"),
    ("P3", "10.0.0.13", "P"),
    ("P4", "10.0.0.14", "P"),
]
for name, lo, role in routers:
    c.execute("INSERT INTO routers (name, loopback, role) VALUES (?, ?, ?)",
              (name, lo, role))

router_ids = {}
for row in c.execute("SELECT id, name FROM routers"):
    router_ids[row[1]] = row[0]

links = [
    ("PE1", "P1", 10, 10000),
    ("PE1", "P3", 25, 1000),
    ("P1", "P2", 10, 10000),
    ("P1", "P4", 10, 5000),
    ("P2", "PE3", 10, 10000),
    ("P3", "P4", 10, 5000),
    ("P4", "PE3", 10, 2000),
    ("P3", "PE2", 10, 5000),
]
for a, b, metric, bw in links:
    c.execute(
        "INSERT INTO links (router_a_id, router_b_id, metric, bandwidth_mbps) VALUES (?, ?, ?, ?)",
        (router_ids[a], router_ids[b], metric, bw))

conn.commit()
conn.close()
print(f"Created {DB_PATH}")
