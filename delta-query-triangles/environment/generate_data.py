#!/usr/bin/env python3
"""Generate graph data in SQLite + Parquet formats and precompute expected triangle counts.

Uses delta-based algorithm (with brute-force validation checkpoints) to compute
expected values efficiently during Docker build.
"""
import random
import json
import csv
import sqlite3
import os
import sys
import tempfile
from collections import defaultdict

import duckdb

random.seed(42)

N = 50000
M = 500000
N_BATCHES = 200
MIN_BATCH = 15
MAX_BATCH = 35


def count_triangles_bf(fwd):
    """Brute force: count ordered triples (a,b,c) with a->b, b->c, a->c, all distinct."""
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


def compute_delta(old_fwd, old_rev, new_fwd, new_rev, consolidated):
    """Compute triangle count change for a batch of edge updates."""
    delta = 0

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

    for (b, c), diff in consolidated.items():
        orb = old_rev.get(b)
        if orb is None:
            continue
        for a in orb:
            if a != b and a != c:
                na = new_fwd.get(a)
                if na is not None and c in na:
                    delta += diff

    for (a, c), diff in consolidated.items():
        oa = old_fwd.get(a)
        if oa is None:
            continue
        for b in oa:
            if b != a and b != c:
                ob = old_fwd.get(b)
                if ob is not None and c in ob:
                    delta += diff

    return delta


def apply_changes_to_adj(fwd, rev, consolidated):
    """Return new adjacency dicts after applying consolidated changes."""
    nf = {}
    for a, s in fwd.items():
        nf[a] = set(s)
    nr = {}
    for b, s in rev.items():
        nr[b] = set(s)
    for (s, d), diff in consolidated.items():
        if diff > 0:
            nf.setdefault(s, set()).add(d)
            nr.setdefault(d, set()).add(s)
        else:
            if s in nf:
                nf[s].discard(d)
            if d in nr:
                nr[d].discard(s)
    return nf, nr


def main():
    print("Generating graph...", file=sys.stderr)
    edges = set()
    while len(edges) < M:
        a = random.randint(0, N - 1)
        b = random.randint(0, N - 1)
        if a != b:
            edges.add((a, b))

    os.makedirs("/app/data", exist_ok=True)

    # Write initial graph to SQLite
    print("Writing SQLite database...", file=sys.stderr)
    db_path = "/app/data/graph.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE edges (src INTEGER NOT NULL, dst INTEGER NOT NULL)")
    conn.executemany("INSERT INTO edges VALUES (?, ?)", sorted(edges))
    conn.execute("CREATE INDEX idx_src ON edges (src)")
    conn.execute("CREATE INDEX idx_dst ON edges (dst)")
    conn.execute("CREATE UNIQUE INDEX idx_edge ON edges (src, dst)")
    conn.commit()
    conn.close()

    fwd = defaultdict(set)
    rev = defaultdict(set)
    for a, b in edges:
        fwd[a].add(b)
        rev[b].add(a)

    print("Counting initial triangles (brute force)...", file=sys.stderr)
    tri_count = count_triangles_bf(fwd)
    print(f"Initial: {M} edges, {tri_count} triangles", file=sys.stderr)

    expected = [tri_count]
    current_edges = set(edges)
    all_batches = []

    for batch_idx in range(N_BATCHES):
        changes = []
        n_changes = random.randint(MIN_BATCH, MAX_BATCH)
        seen = set()

        for _ in range(n_changes):
            if random.random() < 0.35 and current_edges:
                e = random.choice(list(current_edges))
                if e not in seen:
                    seen.add(e)
                    current_edges.discard(e)
                    changes.append((e[0], e[1], -1))
            else:
                for _ in range(50):
                    a = random.randint(0, N - 1)
                    b = random.randint(0, N - 1)
                    if a != b and (a, b) not in current_edges and (a, b) not in seen:
                        seen.add((a, b))
                        current_edges.add((a, b))
                        changes.append((a, b, 1))
                        break

        # Adversarial: simultaneous triangle insertion
        if batch_idx == 25:
            t = (N - 10, N - 9, N - 8)
            for p in [(t[0], t[1]), (t[1], t[2]), (t[0], t[2])]:
                if p in current_edges:
                    current_edges.discard(p)
                    changes.append((p[0], p[1], -1))
            for p in [(t[0], t[1]), (t[1], t[2]), (t[0], t[2])]:
                current_edges.add(p)
                changes.append((p[0], p[1], 1))

        # Adversarial: simultaneous triangle deletion
        if batch_idx == 75:
            t = (N - 10, N - 9, N - 8)
            for p in [(t[0], t[1]), (t[1], t[2]), (t[0], t[2])]:
                if p in current_edges:
                    current_edges.discard(p)
                    changes.append((p[0], p[1], -1))

        # Adversarial: consolidation (insert + delete same edge = net zero)
        if batch_idx == 100:
            te = (N - 7, N - 6)
            if te not in current_edges:
                changes.append((te[0], te[1], 1))
                changes.append((te[0], te[1], -1))

        # Adversarial: split triangle across two batches
        if batch_idx == 150:
            t = (N - 5, N - 4, N - 3)
            for p in [(t[0], t[1]), (t[1], t[2])]:
                if p not in current_edges:
                    current_edges.add(p)
                    changes.append((p[0], p[1], 1))
        if batch_idx == 151:
            p = (N - 5, N - 3)
            if p not in current_edges:
                current_edges.add(p)
                changes.append((p[0], p[1], 1))

        all_batches.append(changes)

        # Consolidate
        net = defaultdict(int)
        for s, d, diff in changes:
            net[(s, d)] += diff
        consolidated = {k: v for k, v in net.items() if v != 0}

        # Build new adjacency
        new_fwd, new_rev = apply_changes_to_adj(fwd, rev, consolidated)

        # Compute delta
        d = compute_delta(fwd, rev, new_fwd, new_rev, consolidated)
        tri_count += d
        expected.append(tri_count)

        fwd = defaultdict(set, new_fwd)
        rev = defaultdict(set, new_rev)

        # Brute-force validation at checkpoints
        if batch_idx in (49, 99, 149, 199):
            print(f"Validating at batch {batch_idx}...", file=sys.stderr)
            bf = count_triangles_bf(fwd)
            assert bf == tri_count, (
                f"MISMATCH at batch {batch_idx}: bf={bf}, incr={tri_count}"
            )
            print(
                f"Batch {batch_idx}: verified ({tri_count} triangles)",
                file=sys.stderr,
            )

    # Write updates to Parquet via DuckDB
    print("Writing Parquet file...", file=sys.stderr)
    csv_fd, csv_path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(csv_fd, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["batch_id", "src", "dst", "diff"])
            for i, batch in enumerate(all_batches):
                for s, d, diff in batch:
                    writer.writerow([i, s, d, diff])

        con = duckdb.connect()
        con.execute(
            f"COPY (SELECT CAST(batch_id AS INTEGER) AS batch_id, "
            f"CAST(src AS INTEGER) AS src, "
            f"CAST(dst AS INTEGER) AS dst, "
            f"CAST(diff AS TINYINT) AS diff "
            f"FROM read_csv('{csv_path}')) "
            f"TO '/app/data/updates.parquet' (FORMAT 'parquet')"
        )
        con.close()
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)

    with open("/app/data/.expected.json", "w") as f:
        json.dump(expected, f)

    print(f"Done. {N_BATCHES} batches, final count: {tri_count}", file=sys.stderr)


if __name__ == "__main__":
    main()
