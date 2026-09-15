#!/usr/bin/env python3
"""Parse OBO ontology file and build term graph in SQLite database.

Reads OBO 1.2 format, extracts terms, parent relationships, and alt_ids,
then computes transitive ancestor closure and stores everything in SQLite.
"""
import sqlite3
import sys


def parse_and_load(obo_path, db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    with open("/app/pipeline/schema.sql") as sf:
        conn.executescript(sf.read())

    current_id = None
    current_name = None
    current_parents = []
    current_alts = []
    in_term = False
    is_obsolete = False

    with open(obo_path) as f:
        for line in f:
            line = line.rstrip("\n")
            stripped = line.strip()

            if stripped == "[Term]":
                if in_term and current_id and not is_obsolete:
                    _store_term(conn, current_id, current_name,
                                current_parents, current_alts)
                in_term = True
                current_id = None
                current_name = None
                current_parents = []
                current_alts = []
                is_obsolete = False

            elif stripped.startswith("[") and stripped.endswith("]"):
                if in_term and current_id and not is_obsolete:
                    _store_term(conn, current_id, current_name,
                                current_parents, current_alts)
                in_term = False

            elif in_term:
                if stripped.startswith("id: "):
                    current_id = stripped[4:].strip()
                elif stripped.startswith("name: "):
                    current_name = stripped[6:].strip()
                elif stripped.startswith("alt_id: "):
                    current_alts.append(stripped[8:].strip())
                elif stripped.startswith("is_a: "):
                    parent = stripped[6:].split("!")[0].strip()
                    current_parents.append(parent)
                elif stripped == "is_obsolete: true":
                    is_obsolete = True

    # Handle last term in file
    if in_term and current_id and not is_obsolete:
        _store_term(conn, current_id, current_name,
                    current_parents, current_alts)

    # Compute transitive ancestor closure
    _compute_ancestors(conn)

    conn.commit()
    conn.close()


def _store_term(conn, term_id, name, parent_list, alt_list):
    """Store a term and its relationships in the database."""
    conn.execute(
        "INSERT OR IGNORE INTO terms (id, name) VALUES (?, ?)",
        (term_id, name or "")
    )
    for parent in parent_list:
        conn.execute(
            "INSERT OR IGNORE INTO parents (child_id, parent_id) VALUES (?, ?)",
            (term_id, parent)
        )
    # NOTE: alt_ids are stored as standalone terms with the same name
    # rather than as aliases in the alt_ids table, so downstream
    # consumers can look them up directly by ID.
    for alt in alt_list:
        conn.execute(
            "INSERT OR IGNORE INTO terms (id, name) VALUES (?, ?)",
            (alt, name or "")
        )


def _compute_ancestors(conn):
    """Compute transitive ancestor sets for all terms using iterative DFS."""
    conn.execute("DELETE FROM ancestors")
    terms = [r[0] for r in conn.execute("SELECT id FROM terms").fetchall()]

    for term in terms:
        # Every term is its own ancestor
        conn.execute(
            "INSERT OR IGNORE INTO ancestors (term_id, ancestor_id) VALUES (?, ?)",
            (term, term)
        )
        # Walk upward through parent links
        stack = [term]
        visited = {term}
        while stack:
            current = stack.pop()
            # Fetch parent for current node
            row = conn.execute(
                "SELECT parent_id FROM parents WHERE child_id = ? LIMIT 1",
                (current,)
            ).fetchone()
            if row and row[0] not in visited:
                visited.add(row[0])
                conn.execute(
                    "INSERT OR IGNORE INTO ancestors "
                    "(term_id, ancestor_id) VALUES (?, ?)",
                    (term, row[0])
                )
                stack.append(row[0])


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <ontology.obo> <output.db>",
              file=sys.stderr)
        sys.exit(1)
    parse_and_load(sys.argv[1], sys.argv[2])
    print("Ontology graph built successfully.")
