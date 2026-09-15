"""Production query module: ancestor-path and LCA queries via
single-statement JOIN-based SQL over pre-built skip-level tables in DuckDB."""
import duckdb
import json


def _build_ancestor_sql(num_levels):
    """Generate a single SQL SELECT with LEFT JOINs across all skip levels."""
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
    """Reconstruct the full ancestor path from a multi-JOIN query result."""
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


def query_ancestors(db_path, node_id):
    """Return list of node IDs from node_id to root (inclusive, node first)."""
    conn = duckdb.connect(db_path, read_only=True)
    num_levels = int(
        conn.execute(
            "SELECT value FROM skip_meta WHERE key='num_levels'"
        ).fetchone()[0]
    )
    sql = _build_ancestor_sql(num_levels)
    row = conn.execute(sql, [node_id]).fetchone()
    conn.close()
    return _extract_path(node_id, row, num_levels)


def query_lca(db_path, node_a, node_b):
    """Return the lowest common ancestor of two nodes."""
    conn = duckdb.connect(db_path, read_only=True)
    num_levels = int(
        conn.execute(
            "SELECT value FROM skip_meta WHERE key='num_levels'"
        ).fetchone()[0]
    )
    sql = _build_ancestor_sql(num_levels)
    row_a = conn.execute(sql, [node_a]).fetchone()
    row_b = conn.execute(sql, [node_b]).fetchone()
    conn.close()
    path_a = _extract_path(node_a, row_a, num_levels)
    path_b_set = set(_extract_path(node_b, row_b, num_levels))
    for node in path_a:
        if node in path_b_set:
            return node
    return -1
