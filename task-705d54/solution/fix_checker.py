#!/usr/bin/env python3
"""
Corrected Joos 1W Type Hierarchy Checker - Semantic Rules (6-14)
Fixes bugs in rules 6-8 and implements rules 9-14 with full
effective method computation.

"""

import sqlite3
import json
import os

DB_PATH = "/app/hierarchy.db"
OUTPUT_PATH = "/app/py_violations.json"

_VISITING = object()


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


def check_rule7(conn):
    """FIX: Group by (name, parameter_types), not just name."""
    rows = conn.execute("""
        SELECT m.type_name
        FROM methods m
        GROUP BY m.type_name, m.name, m.parameter_types
        HAVING COUNT(*) > 1
    """).fetchall()
    return [(r["type_name"], 7) for r in rows]


def check_rule8(conn):
    rows = conn.execute("""
        SELECT c.type_name
        FROM constructors c
        GROUP BY c.type_name, c.parameter_types
        HAVING COUNT(*) > 1
    """).fetchall()
    return [(r["type_name"], 8) for r in rows]


def compute_effective_methods(conn, type_name, cyclic, type_names, cache):
    """
    Compute effective method set following ALL inheritance relationships.
    """
    if type_name in cache:
        val = cache[type_name]
        if val is _VISITING:
            return {}
        return val
    if type_name in cyclic:
        cache[type_name] = {}
        return {}

    cache[type_name] = _VISITING
    effective = {}

    # Follow ALL inheritance (extends + implements)
    parents = conn.execute("""
        SELECT parent_name FROM inheritance
        WHERE child_name = ?
    """, (type_name,)).fetchall()

    for parent_row in parents:
        parent = parent_row["parent_name"]
        if parent not in type_names:
            continue
        parent_eff = compute_effective_methods(
            conn, parent, cyclic, type_names, cache)
        for sig, m in parent_eff.items():
            if sig not in effective:
                effective[sig] = m

    own_methods = conn.execute("""
        SELECT name, parameter_types, return_type, modifiers
        FROM methods WHERE type_name = ?
    """, (type_name,)).fetchall()

    for m in own_methods:
        sig = (m["name"], m["parameter_types"])
        effective[sig] = {
            "name": m["name"],
            "parameter_types": m["parameter_types"],
            "return_type": m["return_type"],
            "modifiers": json.loads(m["modifiers"]),
            "declared_in": type_name
        }

    cache[type_name] = effective
    return effective


def check_rules_9_to_14(conn, cyclic):
    violations = []
    eff_cache = {}
    type_names = get_type_names(conn)

    structurally_invalid = set()
    for r in conn.execute("""
        SELECT DISTINCT i.child_name
        FROM inheritance i
        JOIN types child ON child.canonical_name = i.child_name
        JOIN types parent ON parent.canonical_name = i.parent_name
        WHERE child.kind = 'class'
          AND i.relation = 'extends'
          AND parent.kind = 'interface'
    """).fetchall():
        structurally_invalid.add(r["child_name"])

    types_list = conn.execute(
        "SELECT canonical_name, kind, modifiers FROM types").fetchall()

    for t in types_list:
        name = t["canonical_name"]
        kind = t["kind"]
        modifiers = json.loads(t["modifiers"])

        if name in cyclic or name in structurally_invalid:
            continue

        declared = {}
        own_methods = conn.execute("""
            SELECT name, parameter_types, return_type, modifiers
            FROM methods WHERE type_name = ?
        """, (name,)).fetchall()

        for m in own_methods:
            sig = (m["name"], m["parameter_types"])
            declared[sig] = {
                "name": m["name"],
                "parameter_types": m["parameter_types"],
                "return_type": m["return_type"],
                "modifiers": json.loads(m["modifiers"]),
                "declared_in": name
            }

        # Collect inherited from ALL parents' effective methods
        inherited = {}
        all_parents = conn.execute("""
            SELECT parent_name FROM inheritance WHERE child_name = ?
        """, (name,)).fetchall()

        for parent_row in all_parents:
            parent = parent_row["parent_name"]
            if parent not in type_names:
                continue
            parent_eff = compute_effective_methods(
                conn, parent, cyclic, type_names, eff_cache)
            for sig, m in parent_eff.items():
                if sig not in inherited:
                    inherited[sig] = []
                if not any(e["declared_in"] == m["declared_in"]
                           for e in inherited[sig]):
                    inherited[sig].append(m)

        # Rule 9
        for sig, methods in inherited.items():
            if sig in declared:
                continue
            return_types = {m["return_type"] for m in methods}
            if len(return_types) > 1:
                violations.append((name, 9))

        # Rule 10
        if kind == "class" and "abstract" not in modifiers:
            type_eff = compute_effective_methods(
                conn, name, cyclic, type_names, eff_cache)
            has_abstract = any(
                "abstract" in m.get("modifiers", [])
                for m in type_eff.values()
            )
            if has_abstract:
                violations.append((name, 10))

        # Rules 11-14: check against FULL inherited, not direct parent only
        for sig, m in declared.items():
            if sig not in inherited:
                continue
            for sup_m in inherited[sig]:
                # Rule 11: non-static must not replace static
                if ("static" not in m["modifiers"]
                        and "static" in sup_m["modifiers"]):
                    violations.append((name, 11))
                # Rule 12
                if m["return_type"] != sup_m["return_type"]:
                    violations.append((name, 12))
                # Rule 13: protected must not replace public
                if ("protected" in m["modifiers"]
                        and "public" in sup_m["modifiers"]):
                    violations.append((name, 13))
                # Rule 14
                if "final" in sup_m["modifiers"]:
                    violations.append((name, 14))

    return violations


def main():
    conn = get_connection()
    all_violations = []

    r6, cyclic = check_rule6_cycles(conn)
    all_violations.extend(r6)

    all_violations.extend(check_rule7(conn))
    all_violations.extend(check_rule8(conn))

    all_violations.extend(check_rules_9_to_14(conn, cyclic))

    result = [{"type": n, "rule": r} for n, r in all_violations]

    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Checker completed: {len(result)} semantic violations found")
    conn.close()


if __name__ == "__main__":
    main()
