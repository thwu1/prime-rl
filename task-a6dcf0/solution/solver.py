#!/usr/bin/env python3
"""Correct solver for the benchmark pipeline repair task.

Reads the SQLite database, handles all encodings and formats,
solves XOR-encrypted tree path queries, and writes results.json.
"""

import sqlite3
import json
import zlib
import base64
import os
import sys


def build_tree(n, edges):
    """Build tree structures using iterative DFS (no recursion limit issues)."""
    par = [0] * (n + 1)
    ew = [0] * (n + 1)
    ch = [[] for _ in range(n + 1)]
    for c, p, w in edges:
        par[c] = p
        ew[c] = w
        ch[p].append(c)

    dep = [0] * (n + 1)
    stk = [1]
    while stk:
        u = stk.pop()
        for v in ch[u]:
            dep[v] = dep[u] + 1
            stk.append(v)

    lg = max(1, n.bit_length())
    up = [[0] * (n + 1) for _ in range(lg)]
    for i in range(1, n + 1):
        up[0][i] = par[i]
    for k in range(1, lg):
        for i in range(1, n + 1):
            up[k][i] = up[k - 1][up[k - 1][i]]

    return par, ew, dep, up, lg


def lca(u, v, dep, up, lg):
    if dep[u] < dep[v]:
        u, v = v, u
    d = dep[u] - dep[v]
    for k in range(lg):
        if (d >> k) & 1:
            u = up[k][u]
    if u == v:
        return u
    for k in range(lg - 1, -1, -1):
        if up[k][u] != up[k][v]:
            u = up[k][u]
            v = up[k][v]
    return up[0][u]


def get_path(u, v, dep, up, lg, par):
    l = lca(u, v, dep, up, lg)
    pu = []
    x = u
    while x != l:
        pu.append(x)
        x = par[x]
    pu.append(l)
    pv = []
    x = v
    while x != l:
        pv.append(x)
        x = par[x]
    return pu + pv[::-1]


def parse_edges(edge_data_json, format_version):
    """Parse edge data, handling both dict (fv=1) and list (fv=2) formats."""
    raw = json.loads(edge_data_json)
    edges = []
    for e in raw:
        if isinstance(e, dict):
            edges.append((e["c"], e["p"], e["w"]))
        elif isinstance(e, list):
            edges.append((e[0], e[1], e[2]))
    return edges


def decode_queries(qdata, encoding):
    """Decode query data based on the encoding field."""
    if encoding == 'zlib_base64':
        decoded = base64.b64decode(qdata)
        decompressed = zlib.decompress(decoded)
        return json.loads(decompressed.decode('utf-8'))
    else:
        return json.loads(qdata)


def solve_encrypted(n, edges, encrypted_queries, initial_last_ans):
    """Solve XOR-encrypted tree path queries."""
    par, ew, dep, up, lg = build_tree(n, edges)

    la = initial_last_ans
    results = []

    for q in encrypted_queries:
        qt = q["type"]
        params = q["params"]

        if qt == "K":
            u = params[0] ^ la
            v = params[1] ^ la
            k = params[2] ^ la
        else:
            u = params[0] ^ la
            v = params[1] ^ la

        if qt == "D":
            ans = dep[u] + dep[v] - 2 * dep[lca(u, v, dep, up, lg)]
        elif qt == "S":
            l = lca(u, v, dep, up, lg)
            s = 0
            x = u
            while x != l:
                s += ew[x]
                x = par[x]
            x = v
            while x != l:
                s += ew[x]
                x = par[x]
            ans = s
        elif qt == "M":
            l = lca(u, v, dep, up, lg)
            m = 0
            x = u
            while x != l:
                m = max(m, ew[x])
                x = par[x]
            x = v
            while x != l:
                m = max(m, ew[x])
                x = par[x]
            ans = m
        elif qt == "L":
            ans = lca(u, v, dep, up, lg)
        elif qt == "K":
            path = get_path(u, v, dep, up, lg, par)
            ans = path[k]

        results.append(ans)
        la = ans

    return results


def main():
    db = sqlite3.connect('/app/benchmark.db')
    cur = db.cursor()

    # Discover all query sets
    cur.execute("SELECT id, tree_id, query_data, encoding, initial_last_ans "
                "FROM query_sets ORDER BY id")
    query_sets = cur.fetchall()

    all_results = {}

    for qs_id, tree_id, qdata, encoding, init_la in query_sets:
        # Look up the tree
        cur.execute("SELECT node_count, edge_data, format_version "
                    "FROM trees WHERE id = ?", (tree_id,))
        tree_row = cur.fetchone()

        if tree_row is None:
            all_results[str(qs_id)] = []
            continue

        n, edge_data, fv = tree_row
        edges = parse_edges(edge_data, fv)
        queries = decode_queries(qdata, encoding)

        if not queries:
            all_results[str(qs_id)] = []
            continue

        results = solve_encrypted(n, edges, queries, init_la)
        all_results[str(qs_id)] = results

    db.close()

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/results.json', 'w') as f:
        json.dump(all_results, f)


if __name__ == '__main__':
    main()
