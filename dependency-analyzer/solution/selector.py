#!/usr/bin/env python3
"""Incremental Test Impact Analyzer.

Integrates git history, Python AST import resolution, and SQLite
to produce test impact analysis with risk-based prioritization.
"""

import ast
import json
import math
import os
import sqlite3
import subprocess
import sys


def main():
    if len(sys.argv) < 3:
        print("Usage: selector.py <repo_path> <commit_range>", file=sys.stderr)
        sys.exit(1)

    repo_path = os.path.abspath(sys.argv[1])
    commit_range = sys.argv[2]
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)

    db_path = os.path.join(output_dir, "project.db")
    json_path = os.path.join(output_dir, "analysis.json")
    dot_path = os.path.join(output_dir, "deps.dot")

    # Collect all Python files (skip .git)
    all_py_files = set()
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            if f.endswith(".py"):
                rel = os.path.relpath(os.path.join(root, f), repo_path)
                all_py_files.add(rel)

    # Extract git history
    commits = extract_commits(repo_path)
    file_changes = extract_file_changes(repo_path)

    # Parse imports
    dependencies = parse_all_imports(repo_path, all_py_files)

    # Create and populate database
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    create_schema(conn)
    populate_data(conn, commits, file_changes, dependencies)

    # Derive source file set from filesystem
    source_files = sorted(f for f in all_py_files if is_source_file(f))

    # Compute test cones via recursive CTE
    compute_test_cones_cte(conn)

    # Compute risk scores
    compute_risk_scores(conn, source_files)

    # Generate impact report
    impact = generate_impact(conn, repo_path, commit_range)

    # Export JSON
    export_json(conn, json_path, impact, source_files)

    # Generate DOT graph
    generate_dot(conn, dot_path)

    conn.close()


# ── Helpers ──────────────────────────────────────────────────────


def is_source_file(path):
    if not path.endswith(".py"):
        return False
    bn = os.path.basename(path)
    if bn == "__init__.py":
        return False
    if bn.startswith("test_") or bn.endswith("_test.py"):
        return False
    return True


def is_test_file(path):
    if not path.endswith(".py"):
        return False
    bn = os.path.basename(path)
    return bn.startswith("test_") or bn.endswith("_test.py")


# ── Git Extraction ───────────────────────────────────────────────


def extract_commits(repo_path):
    result = subprocess.run(
        ["git", "-C", repo_path, "log", "--reverse",
         "--format=%H\t%an\t%ct\t%s"],
        capture_output=True, text=True, check=True,
    )
    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t", 3)
        commits.append((parts[0], parts[1], int(parts[2]), parts[3]))
    return commits


def extract_file_changes(repo_path):
    result = subprocess.run(
        ["git", "-C", repo_path, "log", "--reverse",
         "--format=COMMIT:%H", "--numstat"],
        capture_output=True, text=True, check=True,
    )
    changes = []
    current_hash = None
    for line in result.stdout.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("COMMIT:"):
            current_hash = stripped[7:]
        elif current_hash and "\t" in stripped:
            parts = stripped.split("\t")
            if len(parts) >= 3 and parts[0] != "-":
                changes.append((
                    current_hash, parts[2], int(parts[0]), int(parts[1])
                ))
    return changes


# ── AST Import Parsing ───────────────────────────────────────────


def resolve_import(module_name, all_py_files):
    parts = module_name.split(".")
    candidate = "/".join(parts) + ".py"
    if candidate in all_py_files:
        return candidate
    candidate = "/".join(parts) + "/__init__.py"
    if candidate in all_py_files:
        return candidate
    return None


def parse_all_imports(repo_path, all_py_files):
    dependencies = []
    seen = set()

    for py_file in sorted(all_py_files):
        bn = os.path.basename(py_file)
        if bn == "__init__.py":
            continue

        full_path = os.path.join(repo_path, py_file)
        try:
            with open(full_path) as f:
                source = f.read()
            tree = ast.parse(source, filename=py_file)
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    t = resolve_import(alias.name, all_py_files)
                    if t and is_source_file(t) and t != py_file:
                        key = (py_file, t)
                        if key not in seen:
                            seen.add(key)
                            dependencies.append((py_file, t, "import"))

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    t = resolve_import(node.module, all_py_files)
                    if t and is_source_file(t) and t != py_file:
                        key = (py_file, t)
                        if key not in seen:
                            seen.add(key)
                            dependencies.append((py_file, t, "from_import"))

    return dependencies


# ── SQLite ───────────────────────────────────────────────────────


def create_schema(conn):
    c = conn.cursor()
    c.execute("""CREATE TABLE commits (
        hash TEXT PRIMARY KEY,
        author TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        message TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE file_changes (
        commit_hash TEXT NOT NULL,
        file_path TEXT NOT NULL,
        insertions INTEGER NOT NULL,
        deletions INTEGER NOT NULL,
        FOREIGN KEY (commit_hash) REFERENCES commits(hash)
    )""")
    c.execute("""CREATE TABLE dependencies (
        source_file TEXT NOT NULL,
        target_file TEXT NOT NULL,
        import_type TEXT NOT NULL
            CHECK(import_type IN ('import', 'from_import')),
        PRIMARY KEY (source_file, target_file)
    )""")
    c.execute("""CREATE TABLE test_cones (
        test_file TEXT NOT NULL,
        source_file TEXT NOT NULL,
        depth INTEGER NOT NULL,
        PRIMARY KEY (test_file, source_file)
    )""")
    c.execute("""CREATE TABLE risk_scores (
        file_path TEXT PRIMARY KEY,
        change_frequency INTEGER NOT NULL,
        total_churn INTEGER NOT NULL,
        dependent_test_count INTEGER NOT NULL,
        risk_score REAL NOT NULL
    )""")
    conn.commit()


def populate_data(conn, commits, file_changes, dependencies):
    c = conn.cursor()
    c.executemany("INSERT INTO commits VALUES (?, ?, ?, ?)", commits)
    c.executemany("INSERT INTO file_changes VALUES (?, ?, ?, ?)", file_changes)
    c.executemany(
        "INSERT OR IGNORE INTO dependencies VALUES (?, ?, ?)", dependencies
    )
    conn.commit()


def compute_test_cones_cte(conn):
    c = conn.cursor()
    c.execute("""
        WITH RECURSIVE cone(test_file, reached, depth) AS (
            -- Base: direct imports from test files
            SELECT d.source_file, d.target_file, 1
            FROM dependencies d
            WHERE (d.source_file LIKE 'tests/test\\_%' ESCAPE '\\'
                   OR d.source_file LIKE '%\\_test.py' ESCAPE '\\')

            UNION

            -- Recursive: follow imports from reached source files
            SELECT c.test_file, d.target_file, c.depth + 1
            FROM cone c
            JOIN dependencies d ON d.source_file = c.reached
            WHERE NOT (d.source_file LIKE 'tests/test\\_%' ESCAPE '\\'
                       OR d.source_file LIKE '%\\_test.py' ESCAPE '\\')
        )
        INSERT INTO test_cones (test_file, source_file, depth)
        SELECT test_file, reached, MIN(depth)
        FROM cone
        WHERE NOT (reached LIKE 'tests/test\\_%' ESCAPE '\\'
                   OR reached LIKE '%\\_test.py' ESCAPE '\\')
          AND reached NOT LIKE '%/__init__.py'
        GROUP BY test_file, reached
    """)
    conn.commit()


def compute_risk_scores(conn, source_files):
    c = conn.cursor()

    for sf in source_files:
        c.execute(
            "SELECT COUNT(DISTINCT commit_hash) FROM file_changes "
            "WHERE file_path = ?",
            (sf,),
        )
        change_freq = c.fetchone()[0]

        c.execute(
            "SELECT COALESCE(SUM(insertions + deletions), 0) "
            "FROM file_changes WHERE file_path = ?",
            (sf,),
        )
        total_churn = c.fetchone()[0]

        c.execute(
            "SELECT COUNT(DISTINCT test_file) FROM test_cones "
            "WHERE source_file = ?",
            (sf,),
        )
        dep_test_count = c.fetchone()[0]

        risk = change_freq * math.log(1 + total_churn) * (1 + dep_test_count)

        c.execute(
            "INSERT INTO risk_scores VALUES (?, ?, ?, ?, ?)",
            (sf, change_freq, total_churn, dep_test_count, risk),
        )

    conn.commit()


# ── Impact Analysis ──────────────────────────────────────────────


def generate_impact(conn, repo_path, commit_range):
    c = conn.cursor()

    result = subprocess.run(
        ["git", "-C", repo_path, "diff", "--name-only", commit_range],
        capture_output=True, text=True, check=True,
    )
    all_changed = [
        f.strip() for f in result.stdout.strip().split("\n") if f.strip()
    ]
    changed_source = sorted(f for f in all_changed if is_source_file(f))

    affected = set()
    for cf in changed_source:
        c.execute(
            "SELECT DISTINCT test_file FROM test_cones WHERE source_file = ?",
            (cf,),
        )
        for row in c.fetchall():
            affected.add(row[0])

    priorities = {}
    for test in affected:
        placeholders = ",".join("?" * len(changed_source))
        c.execute(
            f"SELECT MAX(r.risk_score) "
            f"FROM test_cones tc "
            f"JOIN risk_scores r ON tc.source_file = r.file_path "
            f"WHERE tc.test_file = ? AND tc.source_file IN ({placeholders})",
            [test] + changed_source,
        )
        row = c.fetchone()
        priorities[test] = row[0] if row and row[0] else 0.0

    execution_order = sorted(affected, key=lambda t: (-priorities[t], t))

    return {
        "commit_range": commit_range,
        "changed_files": changed_source,
        "affected_tests": sorted(affected),
        "execution_order": execution_order,
    }


# ── Export ───────────────────────────────────────────────────────


def export_json(conn, json_path, impact, source_files):
    c = conn.cursor()

    # Dependency graph: source-to-source only
    c.execute("""
        SELECT source_file, target_file FROM dependencies
        WHERE NOT (source_file LIKE 'tests/test\\_%' ESCAPE '\\'
                   OR source_file LIKE '%\\_test.py' ESCAPE '\\')
          AND source_file NOT LIKE '%/__init__.py'
        ORDER BY source_file, target_file
    """)
    dep_graph = {}
    for src, tgt in c.fetchall():
        dep_graph.setdefault(src, []).append(tgt)

    # Include all source files (even those with no deps or not imported)
    for sf in source_files:
        if sf not in dep_graph:
            dep_graph[sf] = []

    # Test cones
    c.execute(
        "SELECT test_file, source_file FROM test_cones "
        "ORDER BY test_file, source_file"
    )
    test_cones = {}
    for tf, sf in c.fetchall():
        test_cones.setdefault(tf, []).append(sf)

    # Risk ranking
    c.execute(
        "SELECT * FROM risk_scores ORDER BY risk_score DESC, file_path ASC"
    )
    risk_ranking = []
    for row in c.fetchall():
        risk_ranking.append({
            "file": row[0],
            "change_frequency": row[1],
            "total_churn": row[2],
            "dependent_test_count": row[3],
            "risk_score": round(row[4], 4),
        })

    data = {
        "dependency_graph": dict(sorted(dep_graph.items())),
        "test_cones": dict(sorted(test_cones.items())),
        "risk_ranking": risk_ranking,
        "impact_report": impact,
    }

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)


def generate_dot(conn, dot_path):
    c = conn.cursor()
    c.execute("""
        SELECT source_file, target_file FROM dependencies
        WHERE NOT (source_file LIKE 'tests/test\\_%' ESCAPE '\\'
                   OR source_file LIKE '%\\_test.py' ESCAPE '\\')
          AND source_file NOT LIKE '%/__init__.py'
        ORDER BY source_file, target_file
    """)
    edges = c.fetchall()

    lines = [
        "digraph dependencies {",
        "    rankdir=LR;",
        "    node [shape=box];",
    ]
    for src, tgt in edges:
        lines.append(f'    "{src}" -> "{tgt}";')
    lines.append("}")

    with open(dot_path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
