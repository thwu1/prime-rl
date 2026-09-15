#!/usr/bin/env python3
"""Create the lexicon SQLite database from source JSON during Docker build."""
import json
import sqlite3
import os

os.makedirs("/app/data", exist_ok=True)

with open("/tmp/lexicon_source.json") as f:
    data = json.load(f)

conn = sqlite3.connect("/app/data/lexicon.db")
c = conn.cursor()

c.execute("""
CREATE TABLE code_systems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
)
""")

c.execute("""
CREATE TABLE terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('CONDITION', 'SYMPTOM', 'MEDICATION')),
    code TEXT NOT NULL,
    code_system_id INTEGER NOT NULL REFERENCES code_systems(id)
)
""")

c.execute("""
CREATE TABLE synonyms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term_id INTEGER NOT NULL REFERENCES terms(id),
    form TEXT NOT NULL
)
""")

c.execute("CREATE INDEX idx_synonyms_term_id ON synonyms(term_id)")
c.execute("CREATE INDEX idx_synonyms_form ON synonyms(form COLLATE NOCASE)")
c.execute("CREATE INDEX idx_terms_canonical ON terms(canonical COLLATE NOCASE)")

# Create FTS5 virtual table for efficient term lookup
c.execute("""
CREATE VIRTUAL TABLE terms_fts USING fts5(
    form,
    term_id UNINDEXED,
    canonical UNINDEXED,
    entity_type UNINDEXED,
    code UNINDEXED,
    code_system_name UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
)
""")

# Insert code systems
code_systems = {}
for term in data["terms"]:
    cs = term["code_system"]
    if cs not in code_systems:
        c.execute("INSERT INTO code_systems (name) VALUES (?)", (cs,))
        code_systems[cs] = c.lastrowid

# Insert terms, synonyms, and FTS5 entries
for term in data["terms"]:
    cs_id = code_systems[term["code_system"]]
    c.execute(
        "INSERT INTO terms (canonical, type, code, code_system_id) VALUES (?, ?, ?, ?)",
        (term["canonical"], term["type"], term["code"], cs_id)
    )
    term_id = c.lastrowid

    all_forms = [term["canonical"]] + term.get("synonyms", [])
    for form in all_forms:
        c.execute("INSERT INTO synonyms (term_id, form) VALUES (?, ?)",
                  (term_id, form))
        c.execute(
            "INSERT INTO terms_fts (form, term_id, canonical, entity_type, code, code_system_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (form, str(term_id), term["canonical"], term["type"], term["code"], term["code_system"])
        )

conn.commit()
conn.close()
