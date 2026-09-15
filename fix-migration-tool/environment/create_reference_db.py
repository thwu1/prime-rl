#!/usr/bin/env python3
"""Create a reference production database with all migrations correctly applied.

This script bypasses the (broken) migration tool and creates the database
directly, recording correct checksums for each migration file.
"""
import sqlite3
import hashlib
import re
import os
import datetime

DB_PATH = '/app/production.db'
MIGRATIONS_DIR = '/app/migrations'


def compute_checksum(filepath):
    """Compute the correct checksum (with re.MULTILINE flag)."""
    with open(filepath) as f:
        content = f.read()
    stripped = re.sub(r'^--.*$', '', content, flags=re.MULTILINE)
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    return hashlib.sha256(stripped.encode('utf-8')).hexdigest()


def extract_migration_id(filepath):
    """Extract migration ID from the -- migration: header."""
    with open(filepath) as f:
        for line in f:
            m = re.match(r'^--\s*migration:\s*(.+)$', line.strip())
            if m:
                return m.group(1).strip()
    return os.path.splitext(os.path.basename(filepath))[0]


conn = sqlite3.connect(DB_PATH)

# Create all tables (matching the migration SQL exactly)
conn.execute('''CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)''')

conn.execute('''CREATE TABLE posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
)''')

conn.execute('''CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_by INTEGER,
    FOREIGN KEY (created_by) REFERENCES users(id)
)''')

conn.execute('''CREATE TABLE post_tags (
    post_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (post_id, tag_id),
    FOREIGN KEY (post_id) REFERENCES posts(id),
    FOREIGN KEY (tag_id) REFERENCES tags(id)
)''')

# Insert seed data
conn.execute("INSERT INTO users (username, email) VALUES ('admin', 'admin@example.com')")
conn.execute("INSERT INTO users (username, email) VALUES ('editor', 'editor@example.com')")
conn.execute("INSERT INTO posts (user_id, title, body) VALUES (1, 'Welcome Post', 'Hello; welcome to the platform!')")
conn.execute("INSERT INTO tags (name, created_by) VALUES ('announcements', 1)")
conn.execute("INSERT INTO post_tags (post_id, tag_id) VALUES (1, 1)")

# Create the migration tracking table
conn.execute('''CREATE TABLE _schema_migrations (
    migration_id TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
)''')

# Record all migrations as applied with correct checksums
now = datetime.datetime.now().isoformat()
for filename in sorted(os.listdir(MIGRATIONS_DIR)):
    if filename.endswith('.sql'):
        filepath = os.path.join(MIGRATIONS_DIR, filename)
        mid = extract_migration_id(filepath)
        checksum = compute_checksum(filepath)
        conn.execute(
            "INSERT INTO _schema_migrations (migration_id, checksum, applied_at, status) "
            "VALUES (?, ?, ?, 'applied')",
            (mid, checksum, now)
        )

conn.commit()
conn.close()
print(f"Reference database created at {DB_PATH}")
