"""Production index builder: hierarchical skip-level tables in DuckDB for
efficient ancestor queries via scan-and-join SQL patterns.

Reads tree data from the SQLite source database and creates auxiliary
index tables in the DuckDB analytics database.
"""
import sqlite3
import duckdb
import json
import hashlib

MAX_SKIP_LEVEL = 20


def _skip_level(node_id):
    """Deterministic skip level: count trailing 1-bits of SHA-256 digest."""
    digest = hashlib.sha256(node_id.to_bytes(4, byteorder='big')).digest()
    n = int.from_bytes(digest[:8], byteorder='big')
    level = 0
    while n & 1 and level < MAX_SKIP_LEVEL:
        level += 1
        n >>= 1
    return level


def build_index(tree_db_path, analytics_db_path):
    """Build multi-level skip tables in DuckDB.

    Reads tree structure from SQLite at tree_db_path.
    Creates skip_0 .. skip_L tables in DuckDB at analytics_db_path,
    where skip_k contains every node whose skip level >= k.
    Each row stores:
      - id: the node
      - next_level_ancestor: closest proper ancestor present in skip_{k+1}
      - ancestors_between: JSON array of node IDs strictly between this
        node and its next_level_ancestor along the parent-pointer path
    """
    # Read tree structure from SQLite
    s_conn = sqlite3.connect(tree_db_path)
    rows = s_conn.execute('SELECT id, parent_id FROM tree').fetchall()
    s_conn.close()

    parent_of = {}
    root_id = None
    for nid, pid in rows:
        parent_of[nid] = pid
        if pid is None:
            root_id = nid

    # Assign skip levels; root gets max level so it appears in all tables
    levels = {}
    actual_max = 0
    for nid in parent_of:
        if nid == root_id:
            continue
        lvl = _skip_level(nid)
        levels[nid] = lvl
        if lvl > actual_max:
            actual_max = lvl

    root_level = actual_max + 1
    levels[root_id] = root_level

    # Build skip tables in DuckDB
    d_conn = duckdb.connect(analytics_db_path)

    # Drop any existing skip tables from previous builds
    existing = d_conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name LIKE 'skip_%'"
    ).fetchall()
    for (name,) in existing:
        d_conn.execute(f'DROP TABLE IF EXISTS "{name}"')

    # Build skip tables level by level
    num_levels = 0
    for k in range(root_level + 1):
        nodes_at_k = [nid for nid, lvl in levels.items() if lvl >= k]
        if not nodes_at_k:
            break
        nodes_at_next = frozenset(
            nid for nid, lvl in levels.items() if lvl >= k + 1
        )

        d_conn.execute(f'''CREATE TABLE skip_{k} (
            id INTEGER PRIMARY KEY,
            next_level_ancestor INTEGER,
            ancestors_between VARCHAR
        )''')

        for nid in nodes_at_k:
            # Walk up parent chain to find closest ancestor in level k+1
            between = []
            current = parent_of[nid]
            while current is not None and current not in nodes_at_next:
                between.append(current)
                current = parent_of[current]
            d_conn.execute(
                f'INSERT INTO skip_{k} VALUES (?, ?, ?)',
                [nid, current, json.dumps(between)]
            )

        num_levels = k + 1

    # Store metadata
    d_conn.execute(
        'CREATE TABLE IF NOT EXISTS skip_meta '
        '(key VARCHAR PRIMARY KEY, value VARCHAR)'
    )
    d_conn.execute('DELETE FROM skip_meta')
    d_conn.execute(
        "INSERT INTO skip_meta VALUES ('num_levels', ?)",
        [str(num_levels)]
    )
    d_conn.execute(
        "INSERT INTO skip_meta VALUES ('root_id', ?)",
        [str(root_id)]
    )
    d_conn.close()
