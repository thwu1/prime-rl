#!/usr/bin/env python3
"""Create SQLite database from hierarchy JSON."""
import json
import sqlite3

def main():
    with open("/data/hierarchy.json") as f:
        data = json.load(f)

    conn = sqlite3.connect("/app/hierarchy.db")

    conn.execute("""
        CREATE TABLE types (
            canonical_name TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            modifiers TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE inheritance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_name TEXT NOT NULL,
            parent_name TEXT NOT NULL,
            relation TEXT NOT NULL,
            FOREIGN KEY (child_name) REFERENCES types(canonical_name)
        )
    """)

    conn.execute("""
        CREATE TABLE methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_name TEXT NOT NULL,
            name TEXT NOT NULL,
            parameter_types TEXT NOT NULL,
            return_type TEXT NOT NULL,
            modifiers TEXT NOT NULL,
            FOREIGN KEY (type_name) REFERENCES types(canonical_name)
        )
    """)

    conn.execute("""
        CREATE TABLE constructors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_name TEXT NOT NULL,
            parameter_types TEXT NOT NULL,
            modifiers TEXT NOT NULL,
            FOREIGN KEY (type_name) REFERENCES types(canonical_name)
        )
    """)

    for t in data["types"]:
        conn.execute(
            "INSERT INTO types VALUES (?, ?, ?)",
            (t["canonical_name"], t["kind"], json.dumps(t["modifiers"]))
        )

        for ext in t.get("extends", []):
            conn.execute(
                "INSERT INTO inheritance (child_name, parent_name, relation) VALUES (?, ?, ?)",
                (t["canonical_name"], ext, "extends")
            )

        for impl in t.get("implements", []):
            conn.execute(
                "INSERT INTO inheritance (child_name, parent_name, relation) VALUES (?, ?, ?)",
                (t["canonical_name"], impl, "implements")
            )

        for m in t.get("methods", []):
            conn.execute(
                "INSERT INTO methods (type_name, name, parameter_types, return_type, modifiers) VALUES (?, ?, ?, ?, ?)",
                (t["canonical_name"], m["name"], json.dumps(m["parameter_types"]),
                 m["return_type"], json.dumps(m["modifiers"]))
            )

        for c in t.get("constructors", []):
            conn.execute(
                "INSERT INTO constructors (type_name, parameter_types, modifiers) VALUES (?, ?, ?)",
                (t["canonical_name"], json.dumps(c["parameter_types"]), json.dumps(c["modifiers"]))
            )

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
