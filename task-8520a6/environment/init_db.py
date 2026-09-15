#!/usr/bin/env python3

"""Initialize the sessions SQLite database with schema and sample data."""

import sqlite3

DB_PATH = "/app/sessions.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("""
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    initial_text TEXT NOT NULL
)
""")

c.execute("""
CREATE TABLE operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    seq INTEGER NOT NULL,
    op_type TEXT NOT NULL CHECK(op_type IN ('insert', 'delete', 'undo', 'redo')),
    offset INTEGER,
    length INTEGER,
    text TEXT,
    branch INTEGER DEFAULT 0
)
""")

# Session alpha: basic insert + delete
c.execute("INSERT INTO sessions VALUES (?, ?)", ("session_alpha", "Hello World"))
c.execute(
    "INSERT INTO operations (session_id, seq, op_type, offset, text) VALUES (?, ?, ?, ?, ?)",
    ("session_alpha", 1, "insert", 5, " Beautiful"),
)
c.execute(
    "INSERT INTO operations (session_id, seq, op_type, offset, length) VALUES (?, ?, ?, ?, ?)",
    ("session_alpha", 2, "delete", 15, 6),
)

# Session beta: branching via undo
c.execute("INSERT INTO sessions VALUES (?, ?)", ("session_beta", "ABCDEF"))
c.execute(
    "INSERT INTO operations (session_id, seq, op_type, offset, text) VALUES (?, ?, ?, ?, ?)",
    ("session_beta", 1, "insert", 3, "X"),
)
c.execute(
    "INSERT INTO operations (session_id, seq, op_type) VALUES (?, ?, ?)",
    ("session_beta", 2, "undo"),
)
c.execute(
    "INSERT INTO operations (session_id, seq, op_type, offset, text) VALUES (?, ?, ?, ?, ?)",
    ("session_beta", 3, "insert", 0, "Y"),
)

conn.commit()
conn.close()
