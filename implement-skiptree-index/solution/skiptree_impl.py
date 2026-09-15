#!/usr/bin/env python3
"""
Skiptree: a skip-list-inspired multi-level index for efficient ancestor
queries on trees stored as parent pointers in SQLite.

Usage:
    python3 skiptree.py build
    python3 skiptree.py ancestors <node_id>
    python3 skiptree.py lca <node_a> <node_b>
"""

import sys
import json
import sqlite3
import hashlib

DB_PATH = '/app/tree.db'
MAX_SKIP_LEVEL = 20


def compute_skip_level(node_id):
    """Deterministic skip level: count trailing 1-bits of SHA-256 digest."""
    digest = hashlib.sha256(node_id.to_bytes(4, byteorder='big')).digest()
    n = int.from_bytes(digest[:8], byteorder='big')
    level = 0
    while n & 1 and level < MAX_SKIP_LEVEL:
        level += 1
        n >>= 1
    return level


def cmd_build():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    c = conn.cursor()

    # Load tree into memory
    rows = c.execute('SELECT id, parent_id FROM tree').fetchall()
    parent_of = {}
    root_id = None
    for nid, pid in rows:
        parent_of[nid] = pid
        if pid is None:
            root_id = nid

    # Compute skip levels; root gets max level to ensure it's in all tables
    levels = {}
    actual_max = 0
    for nid in parent_of:
        if nid == root_id:
            continue
        lvl = compute_skip_level(nid)
        levels[nid] = lvl
        if lvl > actual_max:
            actual_max = lvl

    root_level = actual_max + 1
    levels[root_id] = root_level
    max_level = root_level

    # Drop any existing skip tables
    old_tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'skip_%'"
    ).fetchall()
    for (name,) in old_tables:
        c.execute(f'DROP TABLE IF EXISTS "{name}"')
    conn.commit()

    # Build skip tables level by level
    num_levels = 0
    for k in range(max_level + 1):
        nodes_at_k = [nid for nid, lvl in levels.items() if lvl >= k]
        if not nodes_at_k:
            break

        nodes_at_k_plus_1 = frozenset(
            nid for nid, lvl in levels.items() if lvl >= k + 1
        )

        c.execute(f'''CREATE TABLE skip_{k} (
            id INTEGER PRIMARY KEY,
            next_level_ancestor INTEGER,
            ancestors_between TEXT
        )''')

        batch = []
        for nid in nodes_at_k:
            # Walk up parent chain to find closest ancestor in level k+1
            between = []
            current = parent_of[nid]
            while current is not None and current not in nodes_at_k_plus_1:
                between.append(current)
                current = parent_of[current]
            nla = current  # None if no ancestor at next level

            batch.append((nid, nla, json.dumps(between)))

        c.executemany(f'INSERT INTO skip_{k} VALUES (?, ?, ?)', batch)
        conn.commit()
        num_levels = k + 1

    # Store metadata
    c.execute(
        'CREATE TABLE IF NOT EXISTS skip_meta '
        '(key TEXT PRIMARY KEY, value TEXT)'
    )
    c.execute('DELETE FROM skip_meta')
    c.execute(
        'INSERT INTO skip_meta VALUES (?, ?)',
        ('num_levels', str(num_levels))
    )
    c.execute(
        'INSERT INTO skip_meta VALUES (?, ?)',
        ('root_id', str(root_id))
    )
    conn.commit()
    conn.close()


def _build_ancestor_sql(num_levels):
    """Generate the single-statement LEFT JOIN SQL for ancestor queries."""
    select_cols = []
    from_parts = []

    for k in range(num_levels):
        alias = f's{k}'
        select_cols.append(f'{alias}.ancestors_between')
        select_cols.append(f'{alias}.next_level_ancestor')

        if k == 0:
            from_parts.append(f'skip_0 {alias}')
        else:
            prev = f's{k - 1}'
            from_parts.append(
                f'LEFT JOIN skip_{k} {alias} '
                f'ON {alias}.id = {prev}.next_level_ancestor'
            )

    return (
        f"SELECT {', '.join(select_cols)} "
        f"FROM {' '.join(from_parts)} "
        f"WHERE s0.id = ?"
    )


def _extract_path(node_id, row, num_levels):
    """Reconstruct the ancestor path from a multi-JOIN query result."""
    if row is None:
        return []

    path = [node_id]
    for k in range(num_levels):
        ab_json = row[k * 2]
        nla = row[k * 2 + 1]

        if ab_json is not None:
            between = json.loads(ab_json)
            path.extend(between)

        if nla is not None:
            path.append(nla)
        else:
            break

    return path


def cmd_ancestors(node_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    num_levels = int(
        c.execute(
            "SELECT value FROM skip_meta WHERE key='num_levels'"
        ).fetchone()[0]
    )

    sql = _build_ancestor_sql(num_levels)
    row = c.execute(sql, (node_id,)).fetchone()
    conn.close()

    path = _extract_path(node_id, row, num_levels)
    print(json.dumps(path))


def cmd_lca(node_a, node_b):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    num_levels = int(
        c.execute(
            "SELECT value FROM skip_meta WHERE key='num_levels'"
        ).fetchone()[0]
    )

    sql = _build_ancestor_sql(num_levels)

    row_a = c.execute(sql, (node_a,)).fetchone()
    row_b = c.execute(sql, (node_b,)).fetchone()
    conn.close()

    path_a = _extract_path(node_a, row_a, num_levels)
    path_b_set = set(_extract_path(node_b, row_b, num_levels))

    for node in path_a:
        if node in path_b_set:
            print(node)
            return

    print(-1)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(
            "Usage: skiptree.py {build|ancestors|lca} [args...]",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]

    if command == 'build':
        cmd_build()
    elif command == 'ancestors':
        if len(sys.argv) != 3:
            print(
                "Usage: skiptree.py ancestors <node_id>", file=sys.stderr
            )
            sys.exit(1)
        cmd_ancestors(int(sys.argv[2]))
    elif command == 'lca':
        if len(sys.argv) != 4:
            print(
                "Usage: skiptree.py lca <node_a> <node_b>", file=sys.stderr
            )
            sys.exit(1)
        cmd_lca(int(sys.argv[2]), int(sys.argv[3]))
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
