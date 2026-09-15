#!/usr/bin/env python3
"""Incremental triangle counting with SQLite + Parquet data sources."""
import json
import sqlite3
from collections import defaultdict

import duckdb


def load_edges_from_sqlite(db_path):
    """Read initial edges from SQLite database."""
    conn = sqlite3.connect(db_path)
    edges = conn.execute("SELECT src, dst FROM edges").fetchall()
    conn.close()
    return edges


def load_updates_from_parquet(parquet_path):
    """Read update batches from Parquet file via DuckDB."""
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT batch_id, src, dst, diff "
        f"FROM read_parquet('{parquet_path}') "
        f"ORDER BY batch_id"
    ).fetchall()
    con.close()

    batches = defaultdict(list)
    for batch_id, src, dst, diff in rows:
        batches[batch_id].append((int(src), int(dst), int(diff)))
    n_batches = max(batches.keys()) + 1 if batches else 0
    return [batches.get(i, []) for i in range(n_batches)]


def count_triangles_initial(fwd):
    """Brute force triangle count for the initial graph state."""
    count = 0
    for a, na in fwd.items():
        for b in na:
            fb = fwd.get(b)
            if fb is None:
                continue
            for c in fb:
                if c != a and c in na:
                    count += 1
    return count


def process_batch(fwd, rev, changes):
    """Process one batch of edge changes incrementally.

    Uses a three-way decomposition of the triangle join with a consistent
    old/new state ordering to avoid double-counting when multiple edges of
    the same triangle change within a single batch.

    Returns the change in triangle count. Updates fwd/rev in-place.
    """
    # Consolidate: sum diffs for duplicate edges, discard net-zero
    net = defaultdict(int)
    for s, d, diff in changes:
        net[(s, d)] += diff
    consolidated = {k: v for k, v in net.items() if v != 0}

    if not consolidated:
        return 0

    # Build post-batch adjacency (new state)
    new_fwd = {a: set(s) for a, s in fwd.items()}
    new_rev = {b: set(s) for b, s in rev.items()}

    for (s, d), diff in consolidated.items():
        if diff > 0:
            new_fwd.setdefault(s, set()).add(d)
            new_rev.setdefault(d, set()).add(s)
        else:
            if s in new_fwd:
                new_fwd[s].discard(d)
            if d in new_rev:
                new_rev[d].discard(s)

    delta = 0

    # Each changed edge (x, y) with diff d is tested in three roles:
    #
    # Role 1 — first edge (a=x, b=y):
    #   find c via new_fwd[b], verify a->c in new_fwd[a]
    for (a, b), diff in consolidated.items():
        nb = new_fwd.get(b)
        if nb is None:
            continue
        na = new_fwd.get(a)
        if na is None:
            continue
        for c in nb:
            if c != a and c != b and c in na:
                delta += diff

    # Role 2 — second edge (b=x, c=y):
    #   find a via old rev[b], verify a->c in new_fwd[a]
    for (b, c), diff in consolidated.items():
        orb = rev.get(b)
        if orb is None:
            continue
        for a in orb:
            if a != b and a != c:
                na = new_fwd.get(a)
                if na is not None and c in na:
                    delta += diff

    # Role 3 — third edge (a=x, c=y):
    #   find b via old fwd[a], verify b->c in old fwd[b]
    for (a, c), diff in consolidated.items():
        oa = fwd.get(a)
        if oa is None:
            continue
        for b in oa:
            if b != a and b != c:
                ob = fwd.get(b)
                if ob is not None and c in ob:
                    delta += diff

    # Update graph state in-place
    fwd.clear()
    fwd.update(new_fwd)
    rev.clear()
    rev.update(new_rev)

    return delta


def main():
    edges = load_edges_from_sqlite("/app/data/graph.db")
    batches = load_updates_from_parquet("/app/data/updates.parquet")

    # Build initial adjacency structures
    fwd = {}
    rev = {}
    for a, b in edges:
        fwd.setdefault(a, set()).add(b)
        rev.setdefault(b, set()).add(a)

    # Initial triangle count (brute force — acceptable one-time cost)
    tri_count = count_triangles_initial(fwd)
    results = [tri_count]

    # Process each batch incrementally
    for batch in batches:
        d = process_batch(fwd, rev, batch)
        tri_count += d
        results.append(tri_count)

    with open("/app/results.json", "w") as f:
        json.dump(results, f)


if __name__ == "__main__":
    main()
