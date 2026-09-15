#!/usr/bin/env python3
"""Build /app/terminology.db from /app/terminology/valueset_bundle.json."""
import json
import sqlite3

with open("/app/terminology/valueset_bundle.json") as f:
    bundle = json.load(f)

db = sqlite3.connect("/app/terminology.db")
db.execute("PRAGMA journal_mode=WAL")
db.execute("""
CREATE TABLE value_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    oid TEXT,
    title TEXT NOT NULL,
    version TEXT
)
""")
db.execute("""
CREATE TABLE codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    value_set_id INTEGER NOT NULL REFERENCES value_sets(id),
    system TEXT NOT NULL,
    code TEXT NOT NULL,
    display TEXT,
    version TEXT
)
""")
db.execute("CREATE INDEX idx_codes_lookup ON codes(value_set_id, system, code)")
db.execute("CREATE INDEX idx_vs_title ON value_sets(title)")
db.execute("CREATE INDEX idx_vs_url ON value_sets(url)")

for entry in bundle.get("entry", []):
    res = entry.get("resource", {})
    if res.get("resourceType") != "ValueSet":
        continue
    url = res.get("url", "")
    title = res.get("title", "")
    oid = url.rsplit("/", 1)[-1] if "/" in url else ""
    version = res.get("version", "")
    cur = db.execute(
        "INSERT INTO value_sets (url, oid, title, version) VALUES (?, ?, ?, ?)",
        (url, oid, title, version),
    )
    vs_id = cur.lastrowid
    for item in res.get("expansion", {}).get("contains", []):
        db.execute(
            "INSERT INTO codes (value_set_id, system, code, display, version) VALUES (?, ?, ?, ?, ?)",
            (vs_id, item.get("system", ""), item.get("code", ""), item.get("display", ""), item.get("version", "")),
        )

db.commit()

# Verify
count = db.execute("SELECT COUNT(*) FROM value_sets").fetchone()[0]
code_count = db.execute("SELECT COUNT(*) FROM codes").fetchone()[0]
print(f"Created terminology.db: {count} value sets, {code_count} codes")
db.close()
