#!/usr/bin/env python3
"""Initialise the policy database with sample data.

Creates /app/data/policies.db with quota and rate-limit policies for
several projects.
"""

import os
import sqlite3
import sys

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "policies.db")


def create_database(db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            policy_id         TEXT PRIMARY KEY,
            project_id        TEXT NOT NULL,
            api_name          TEXT NOT NULL,
            max_requests      INTEGER,
            current_usage     INTEGER DEFAULT 0,
            rate_limit        REAL,
            rate_limit_window REAL,
            enabled           INTEGER DEFAULT 1
        )
    """)

    policies = [
        ("pol-std-001", "project-alpha", "compute.googleapis.com",
         10000, 5234, 100.0, 60.0, 1),
        ("pol-std-002", "project-alpha", "storage.googleapis.com",
         50000, 12000, 500.0, 60.0, 1),
        ("pol-quota-7f3a9b", "project-alpha", "compute.googleapis.com",
         None, 0, None, None, 1),
        ("pol-std-003", "project-beta", "*",
         100000, 45000, 1000.0, 60.0, 1),
        ("pol-std-004", "project-gamma", "bigquery.googleapis.com",
         5000, 2100, 50.0, 60.0, 1),
        ("pol-std-005", "project-delta", "compute.googleapis.com",
         20000, 8900, 200.0, 60.0, 1),
        ("pol-std-006", "project-alpha", "bigquery.googleapis.com",
         30000, 9100, 300.0, 60.0, 1),
        ("pol-std-007", "project-epsilon", "storage.googleapis.com",
         80000, 22000, 800.0, 60.0, 1),
        ("pol-std-008", "project-zeta", "*",
         200000, 95000, 2000.0, 120.0, 1),
    ]

    conn.executemany(
        "INSERT OR REPLACE INTO policies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        policies,
    )
    conn.commit()
    conn.close()
    print(f"Database created at {db_path} with {len(policies)} policies")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    create_database(path)
