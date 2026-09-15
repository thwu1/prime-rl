#!/usr/bin/env python3
"""Fix corrupted quota policy data in the configuration database."""
import sqlite3
import json

DB_PATH = "/app/data/config.db"

conn = sqlite3.connect(DB_PATH)

# Find and fix policies with null rules
cursor = conn.execute("SELECT policy_id, name, rules FROM quota_policies WHERE active = 1")
fixed = 0
for row in cursor.fetchall():
    parsed = json.loads(row[2])
    if parsed is None or not isinstance(parsed, list):
        conn.execute(
            "UPDATE quota_policies SET rules = ?, updated_at = CURRENT_TIMESTAMP WHERE policy_id = ?",
            (json.dumps([]), row[0])
        )
        fixed += 1
        print(f"Fixed policy '{row[1]}' (id={row[0]}): rules was {row[2]}, set to []")

conn.commit()

# Verify
cursor = conn.execute("SELECT name, rules FROM quota_policies WHERE active = 1")
for row in cursor.fetchall():
    parsed = json.loads(row[1])
    assert isinstance(parsed, list), f"Policy '{row[0]}' still broken: {row[1]}"

conn.close()
print(f"Database fix complete. Fixed {fixed} policy(ies).")
