#!/usr/bin/env python3
"""Analyze .coverage SQLite database to produce test impact analysis.

Queries the arc, context, and file tables to produce:
  1. test_file_map.json  — test context -> list of covered source files
  2. fragile_lines.json  — source file -> lines covered by exactly 1 context
"""

import json
import os
import sqlite3
from collections import defaultdict

DB_PATH = '/app/.coverage'
RESULTS_DIR = '/app/results'


def build_test_file_map(conn):
    """Map each non-empty test context to the source files it covers."""
    cursor = conn.execute("""
        SELECT DISTINCT c.context, f.path
        FROM arc a
        JOIN context c ON a.context_id = c.id
        JOIN file f ON a.file_id = f.id
        WHERE c.context != ''
        ORDER BY c.context, f.path
    """)

    result = defaultdict(list)
    for context, path in cursor:
        result[context].append(path)

    return dict(result)


def build_fragile_lines(conn):
    """Find lines covered by exactly one test context.

    A line is identified by its fromno (source line of an arc).
    Only positive line numbers are considered (negative numbers
    represent code-object entry/exit in coverage.py).
    """
    cursor = conn.execute("""
        SELECT f.path, a.fromno
        FROM arc a
        JOIN file f ON a.file_id = f.id
        JOIN context c ON a.context_id = c.id
        WHERE c.context != '' AND a.fromno > 0
        GROUP BY f.path, a.fromno
        HAVING COUNT(DISTINCT a.context_id) = 1
        ORDER BY f.path, a.fromno
    """)

    result = defaultdict(set)
    for path, lineno in cursor:
        result[path].add(lineno)

    return {path: sorted(lines) for path, lines in result.items()}


def main():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"Coverage database not found at {DB_PATH}. "
            f"Run 'coverage run -m pytest' first."
        )

    os.makedirs(RESULTS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    try:
        test_file_map = build_test_file_map(conn)
        with open(os.path.join(RESULTS_DIR, 'test_file_map.json'), 'w') as f:
            json.dump(test_file_map, f, indent=2, sort_keys=True)

        fragile = build_fragile_lines(conn)
        with open(os.path.join(RESULTS_DIR, 'fragile_lines.json'), 'w') as f:
            json.dump(fragile, f, indent=2, sort_keys=True)
    finally:
        conn.close()

    print(f"Results written to {RESULTS_DIR}/")
    print(f"  test_file_map.json: {len(test_file_map)} test contexts")
    total_fragile = sum(len(v) for v in fragile.values())
    print(
        f"  fragile_lines.json: {total_fragile} fragile lines "
        f"across {len(fragile)} files"
    )


if __name__ == '__main__':
    main()
