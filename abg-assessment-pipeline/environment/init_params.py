#!/usr/bin/env python3
"""Initialize the clinical parameters database from SQL definition."""
import os
import sqlite3

DB_PATH = "/app/clinical_params.db"
SQL_PATH = "/app/clinical_params.sql"


def init():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    with open(SQL_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


if __name__ == "__main__":
    init()
