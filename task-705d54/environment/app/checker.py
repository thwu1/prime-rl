#!/usr/bin/env python3
"""
Joos 1W Type Hierarchy Checker - Semantic Rules (6-14)
Reads type hierarchy from SQLite database and SQL views.
Outputs detected violations to py_violations.json.

Structural rules (1-5) are handled by SQL views; see views.sql.
"""

import sqlite3
import json
import sys
import os

DB_PATH = "/app/hierarchy.db"
OUTPUT_PATH = "/app/py_violations.json"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_type_names(conn):
    return set(r["canonical_name"] for r in
               conn.execute("SELECT canonical_name FROM types").fetchall())


def check_rule6_cycles(conn):
    """Detect inheritance cycles using v_hierarchy_edges view."""
    edges = {}
    for r in conn.execute("SELECT canonical_name FROM types").fetchall():
        edges[r["canonical_name"]] = []

    for r in conn.execute(
        "SELECT child_name, parent_name FROM v_hierarchy_edges"
    ).fetchall():
        edges.setdefault(r["child_name"], []).append(r["parent_name"])

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in edges}
    cyclic = set()

    def dfs(name, path):
        if name not in color:
            return
        color[name] = GRAY
        path.append(name)
        for nb in edges.get(name, []):
            if nb not in color:
                continue
            if color[nb] == GRAY:
                idx = path.index(nb)
                for n in path[idx:]:
                    cyclic.add(n)
            elif color[nb] == WHITE:
                dfs(nb, path)
        path.pop()
        color[name] = BLACK

    for name in edges:
        if color.get(name) == WHITE:
            dfs(name, [])

    return [(n, 6) for n in cyclic], cyclic


def check_rule7_duplicate_methods(conn):
    """No duplicate method declarations in a type.
    Two methods are duplicates if they share the same signature
    (name + parameter types). Overloaded methods (same name, different
    parameter types) are permitted per JLS 8.4."""
    rows = conn.execute("""
        SELECT m.type_name
        FROM methods m
        GROUP BY m.type_name, m.name
        HAVING COUNT(*) > 1
    """).fetchall()
    return [(r["type_name"], 7) for r in rows]


def check_rule8_duplicate_constructors(conn):
    """No duplicate constructor signatures."""
    rows = conn.execute("""
        SELECT c.type_name
        FROM constructors c
        GROUP BY c.type_name, c.parameter_types
        HAVING COUNT(*) > 1
    """).fetchall()
    return [(r["type_name"], 8) for r in rows]


def compute_effective_methods(conn, type_name, cyclic, type_names, cache):
    """
    Compute the effective method set for a type per JLS 8.4.6 and 9.2.

    The effective method set is the union of methods inherited from all
    supertypes, with locally declared methods replacing inherited methods
    of the same signature. This function must:
    - Traverse all supertypes via both extends AND implements relationships
    - Be cycle-safe (skip types in the cyclic set, guard against re-entry)
    - Handle diamond inheritance (deduplicate by originating declaration)

    Returns dict: (method_name, param_types_json) -> method_info dict
    where method_info = {
        name: str, parameter_types: str (JSON),
        return_type: str, modifiers: list[str],
        declared_in: str (canonical name of declaring type)
    }
    """
    # Effective method computation not yet implemented.
    # See JLS 8.4.6 for class method inheritance and 9.2 for interfaces.
    return {}


def check_override_rules(conn, cyclic):
    """
    Check inheritance-dependent rules 9-14 per JLS 8.4.6 and 9.2.

    Requires a working compute_effective_methods implementation.

    For each non-cyclic, structurally-valid type:
      Rule  9: If a type inherits (without declaring) two methods with the
               same signature but different return types, it is an error.
      Rule 10: A concrete (non-abstract) class must not contain any abstract
               method in its effective method set.
      Rule 11: A non-static declared method must not replace a static
               inherited method.
      Rule 12: A declared method that replaces an inherited method must have
               the same return type.
      Rule 13: A declared method must not narrow access (protected replacing
               public is an error).
      Rule 14: A declared method must not replace a final inherited method.

    Rules 11-14 must check against ALL inherited methods with matching
    signature from the full supertype chain, not just direct parent
    declarations, since final/static/public methods may be declared
    several levels up.

    Skip types in the cyclic set and types with structural violations
    (e.g. class extends interface) since their inheritance chain is broken.
    """
    # Override rule checking not yet implemented.
    return []


def main():
    conn = get_connection()
    all_violations = []

    rule6_violations, cyclic = check_rule6_cycles(conn)
    all_violations.extend(rule6_violations)

    all_violations.extend(check_rule7_duplicate_methods(conn))
    all_violations.extend(check_rule8_duplicate_constructors(conn))

    all_violations.extend(check_override_rules(conn, cyclic))

    result = [{"type": name, "rule": rule} for name, rule in all_violations]

    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Checker completed: {len(result)} semantic violations found")
    conn.close()


if __name__ == "__main__":
    main()
