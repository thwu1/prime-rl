#!/usr/bin/env python3
"""Setup script to create SQLite corpus database from JSON."""

import json
import os
import sqlite3

CORPUS_JSON = "/tmp/corpus.json"
DB_PATH = "/app/data/corpus.db"

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

with open(CORPUS_JSON) as f:
    corpus = json.load(f)

conn = sqlite3.connect(DB_PATH)

conn.execute("""
    CREATE TABLE documents (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        body TEXT NOT NULL
    )
""")

conn.execute("""
    CREATE TABLE document_metadata (
        doc_id INTEGER PRIMARY KEY,
        category TEXT NOT NULL,
        word_count INTEGER NOT NULL,
        FOREIGN KEY (doc_id) REFERENCES documents(id)
    )
""")

categories = {
    1: "machine_learning", 2: "deep_learning", 3: "security",
    4: "security", 5: "databases", 6: "databases",
    7: "distributed_systems", 8: "distributed_systems",
    9: "data_engineering", 10: "architecture", 11: "devops",
    12: "cloud", 13: "systems", 14: "compilers",
    15: "machine_learning", 16: "nlp", 17: "operating_systems",
    18: "security", 19: "computer_vision", 20: "nlp",
}

for doc in corpus:
    conn.execute(
        "INSERT INTO documents (id, title, body) VALUES (?, ?, ?)",
        (doc["id"], doc["title"], doc["body"]),
    )

    if doc["id"] in categories:
        word_count = len(doc["body"].split())
        conn.execute(
            "INSERT INTO document_metadata (doc_id, category, word_count) VALUES (?, ?, ?)",
            (doc["id"], categories[doc["id"]], word_count),
        )

conn.commit()
conn.close()
