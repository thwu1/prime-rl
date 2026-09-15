#!/usr/bin/env python3
"""Set up the broken benchmark environment for the repair task."""

import sqlite3
import json
import zlib
import base64
import random
import os


def main():
    random.seed(20240613)

    for d in ['/app/output', '/app/logs', '/app/scripts']:
        os.makedirs(d, exist_ok=True)

    # === Tree utilities ===

    def gen_random_tree(n, seed):
        rng = random.Random(seed)
        return [(i, rng.randint(1, i - 1), rng.randint(1, 10000))
                for i in range(2, n + 1)]

    def gen_chain_tree(n, seed):
        rng = random.Random(seed)
        return [(i, i - 1, rng.randint(1, 10000)) for i in range(2, n + 1)]

    def build(n, edges):
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
        LOG = max(1, n.bit_length())
        up = [[0] * (n + 1) for _ in range(LOG)]
        for i in range(1, n + 1):
            up[0][i] = par[i]
        for k in range(1, LOG):
            for i in range(1, n + 1):
                up[k][i] = up[k - 1][up[k - 1][i]]
        return par, ew, dep, up, LOG

    def _lca(u, v, dep, up, LOG):
        if dep[u] < dep[v]:
            u, v = v, u
        d = dep[u] - dep[v]
        for k in range(LOG):
            if (d >> k) & 1:
                u = up[k][u]
        if u == v:
            return u
        for k in range(LOG - 1, -1, -1):
            if up[k][u] != up[k][v]:
                u = up[k][u]
                v = up[k][v]
        return up[0][u]

    def _path(u, v, dep, up, LOG, par):
        l = _lca(u, v, dep, up, LOG)
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

    def gen_queries(n, edges, nq, seed):
        rng = random.Random(seed)
        par, ew, dep, up, LOG = build(n, edges)
        qs = []
        for _ in range(nq):
            qt = rng.choice(['D', 'S', 'M', 'L', 'K'])
            u = rng.randint(1, n)
            v = rng.randint(1, n)
            if qt == 'K':
                d = dep[u] + dep[v] - 2 * dep[_lca(u, v, dep, up, LOG)]
                k = rng.randint(0, max(d, 0))
                qs.append((qt, u, v, k))
            else:
                qs.append((qt, u, v))
        return qs

    def solve_qs(n, edges, queries):
        par, ew, dep, up, LOG = build(n, edges)
        res = []
        for q in queries:
            qt, u, v = q[0], q[1], q[2]
            if qt == 'D':
                a = dep[u] + dep[v] - 2 * dep[_lca(u, v, dep, up, LOG)]
            elif qt == 'S':
                l = _lca(u, v, dep, up, LOG)
                s = 0
                x = u
                while x != l:
                    s += ew[x]
                    x = par[x]
                x = v
                while x != l:
                    s += ew[x]
                    x = par[x]
                a = s
            elif qt == 'M':
                l = _lca(u, v, dep, up, LOG)
                m = 0
                x = u
                while x != l:
                    m = max(m, ew[x])
                    x = par[x]
                x = v
                while x != l:
                    m = max(m, ew[x])
                    x = par[x]
                a = m
            elif qt == 'L':
                a = _lca(u, v, dep, up, LOG)
            elif qt == 'K':
                a = _path(u, v, dep, up, LOG, par)[q[3]]
            res.append(a)
        return res

    def encrypt_qs(plain, answers, init_la):
        enc = []
        la = init_la
        for i, q in enumerate(plain):
            qt = q[0]
            if qt == 'K':
                enc.append({"type": qt, "params": [q[1] ^ la, q[2] ^ la, q[3] ^ la]})
            else:
                enc.append({"type": qt, "params": [q[1] ^ la, q[2] ^ la]})
            la = answers[i]
        return enc

    # === Create database ===

    db = sqlite3.connect('/app/benchmark.db')
    cur = db.cursor()

    cur.execute('''CREATE TABLE trees (
        id INTEGER PRIMARY KEY,
        node_count INTEGER NOT NULL,
        edge_data TEXT NOT NULL,
        format_version INTEGER NOT NULL DEFAULT 1
    )''')

    cur.execute('''CREATE TABLE query_sets (
        id INTEGER PRIMARY KEY,
        tree_id INTEGER NOT NULL,
        query_data TEXT NOT NULL,
        encoding TEXT NOT NULL DEFAULT 'plain',
        initial_last_ans INTEGER NOT NULL DEFAULT 0
    )''')

    cur.execute('''CREATE TABLE results_cache (
        query_set_id INTEGER PRIMARY KEY,
        status TEXT NOT NULL DEFAULT 'pending',
        computed_output TEXT,
        error_log TEXT
    )''')

    # Generate trees
    trees = {
        1: (50, gen_random_tree(50, 1001)),
        2: (200, gen_random_tree(200, 1002)),
        3: (500, gen_random_tree(500, 1003)),
        4: (1100, gen_chain_tree(1100, 1004)),
    }

    for tid, (n, edges) in trees.items():
        if tid == 2:
            data = json.dumps([[c, p, w] for c, p, w in edges])
            fv = 2
        else:
            data = json.dumps([{"c": c, "p": p, "w": w} for c, p, w in edges])
            fv = 1
        cur.execute("INSERT INTO trees VALUES (?,?,?,?)", (tid, n, data, fv))

    # Generate query sets
    qs_cfg = [
        (1, 1, 60, 101, 'plain', 0),
        (2, 1, 80, 102, 'plain', 0),
        (3, 2, 60, 201, 'zlib_base64', 42),
        (4, 2, 80, 202, 'plain', 0),
        (5, 3, 70, 301, 'plain', 0),
        (6, 3, 90, 302, 'zlib_base64', 0),
        (7, 4, 60, 401, 'plain', 42),
        (8, 4, 80, 402, 'plain', 0),
    ]

    expected = {}
    for qs_id, tid, nq, seed, enc, init_la in qs_cfg:
        n, edges = trees[tid]
        plain = gen_queries(n, edges, nq, seed)
        answers = solve_qs(n, edges, plain)
        encrypted = encrypt_qs(plain, answers, init_la)

        qdata = json.dumps(encrypted)
        if enc == 'zlib_base64':
            qdata = base64.b64encode(zlib.compress(qdata.encode())).decode()

        cur.execute("INSERT INTO query_sets VALUES (?,?,?,?,?)",
                    (qs_id, tid, qdata, enc, init_la))
        expected[str(qs_id)] = answers

    # Dangling query set referencing nonexistent tree
    cur.execute("INSERT INTO query_sets VALUES (?,?,?,?,?)",
                (9, 99, '[]', 'plain', 0))
    expected["9"] = []

    # Stale/wrong results cache entries
    cur.execute("INSERT INTO results_cache VALUES (?,?,?,?)",
                (1, 'done', json.dumps([a + 1 for a in expected["1"]]), None))
    cur.execute("INSERT INTO results_cache VALUES (?,?,?,?)",
                (5, 'error', None, 'RecursionError: maximum recursion depth exceeded'))
    cur.execute("INSERT INTO results_cache VALUES (?,?,?,?)",
                (7, 'error', None, 'RecursionError: maximum recursion depth exceeded'))
    cur.execute("INSERT INTO results_cache VALUES (?,?,?,?)",
                (9, 'error', None, 'Tree not found: id=99'))

    db.commit()
    db.close()

    # === Write buggy extract.py ===

    with open('/app/scripts/extract.py', 'w') as f:
        f.write(r'''#!/usr/bin/env python3
"""Extract and decrypt queries from benchmark database."""
import sqlite3
import json
import configparser
import sys


def load_config():
    config = configparser.ConfigParser()
    config.read('/app/config.ini')
    return config


def decrypt_query_params(encrypted_queries):
    """Decrypt XOR-encrypted query parameters using lastAns chain.
    Note: this only peels the first layer; full solve needs answer feedback."""
    last_ans = 0
    decrypted = []
    for q in encrypted_queries:
        qt = q["type"]
        params = q["params"]
        if qt == "K":
            u = params[0] ^ last_ans
            v = params[1] ^ last_ans
            k = params[2] ^ last_ans
            decrypted.append({"type": qt, "u": u, "v": v, "k": k})
        else:
            u = params[0] ^ last_ans
            v = params[1] ^ last_ans
            decrypted.append({"type": qt, "u": u, "v": v})
    return decrypted


def main():
    config = load_config()
    db_path = config.get('database', 'path')

    db = sqlite3.connect(db_path)
    cur = db.cursor()

    qs_id = int(sys.argv[1]) if len(sys.argv) > 1 else None

    if qs_id:
        cur.execute("SELECT query_data, encoding FROM query_sets WHERE id = ?",
                    (qs_id,))
        rows = [(qs_id,) + row for row in cur.fetchall()]
    else:
        cur.execute("SELECT id, query_data, encoding FROM query_sets")
        rows = cur.fetchall()

    for row in rows:
        sid, qdata, encoding = row[0], row[1], row[2]
        # Only handles plain encoding
        queries = json.loads(qdata)
        decrypted = decrypt_query_params(queries)
        print(json.dumps({"query_set_id": sid, "queries": decrypted}))

    db.close()


if __name__ == "__main__":
    main()
''')

    # === Write buggy solver.py ===

    with open('/app/scripts/solver.py', 'w') as f:
        f.write(r'''#!/usr/bin/env python3
"""Solve tree path queries from benchmark database."""
import sqlite3
import json
import configparser
import sys


def load_config():
    config = configparser.ConfigParser()
    config.read('/app/config.ini')
    return config


def parse_tree(edge_data_json):
    """Parse edge data from JSON. Expects dict format."""
    edges = json.loads(edge_data_json)
    parsed = []
    for e in edges:
        parsed.append((e["c"], e["p"], e["w"]))
    return parsed


def build_tree(n, edges):
    par = [0] * (n + 1)
    ew = [0] * (n + 1)
    ch = [[] for _ in range(n + 1)]
    for c, p, w in edges:
        par[c] = p
        ew[c] = w
        ch[p].append(c)

    dep = [0] * (n + 1)

    def dfs(u):
        for v in ch[u]:
            dep[v] = dep[u] + 1
            dfs(v)

    dfs(1)

    LOG = max(1, n.bit_length())
    up = [[0] * (n + 1) for _ in range(LOG)]
    for i in range(1, n + 1):
        up[0][i] = par[i]
    for k in range(1, LOG):
        for i in range(1, n + 1):
            up[k][i] = up[k - 1][up[k - 1][i]]
    return par, ew, dep, up, LOG


def lca(u, v, dep, up, LOG):
    if dep[u] < dep[v]:
        u, v = v, u
    d = dep[u] - dep[v]
    for k in range(LOG):
        if (d >> k) & 1:
            u = up[k][u]
    if u == v:
        return u
    for k in range(LOG - 1, -1, -1):
        if up[k][u] != up[k][v]:
            u = up[k][u]
            v = up[k][v]
    return up[0][u]


def get_path(u, v, dep, up, LOG, par):
    l = lca(u, v, dep, up, LOG)
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


def solve(n, edges, encrypted_queries, initial_last_ans=0):
    par, ew, dep, up, LOG = build_tree(n, edges)

    last_ans = 0
    results = []

    for q in encrypted_queries:
        qt = q["type"]
        params = q["params"]

        if qt == "K":
            u = params[0] ^ last_ans
            v = params[1] ^ last_ans
            k = params[2] ^ last_ans
        else:
            u = params[0] ^ last_ans
            v = params[1] ^ last_ans

        if qt == "D":
            ans = dep[u] + dep[v] - 2 * dep[lca(u, v, dep, up, LOG)]
        elif qt == "S":
            l = lca(u, v, dep, up, LOG)
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
            l = lca(u, v, dep, up, LOG)
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
            ans = lca(u, v, dep, up, LOG)
        elif qt == "K":
            path = get_path(u, v, dep, up, LOG, par)
            ans = path[k]

        results.append(ans)
        last_ans = ans

    return results


def main():
    config = load_config()
    db_path = config.get('database', 'path')
    tree_table = config.get('database', 'tree_table')

    db = sqlite3.connect(db_path)
    cur = db.cursor()

    qs_id = int(sys.argv[1])

    cur.execute("SELECT tree_id, query_data, encoding FROM query_sets WHERE id = ?",
                (qs_id,))
    tree_id, qdata, encoding = cur.fetchone()

    cur.execute("SELECT node_count, edge_data FROM {} WHERE id = ?".format(tree_table),
                (tree_id,))
    row = cur.fetchone()
    if row is None:
        print(json.dumps([]))
        return

    n, edge_data = row
    edges = parse_tree(edge_data)
    queries = json.loads(qdata)

    results = solve(n, edges, queries)
    print(json.dumps(results))

    db.close()


if __name__ == "__main__":
    main()
''')

    # === Write broken pipeline script ===

    with open('/app/scripts/run_all.sh', 'w') as f:
        f.write('''#!/bin/bash
# Benchmark pipeline - processes all query sets and assembles results
# Status: BROKEN after server migration

CONFIG=/app/config.ini
DB_PATH=$(grep "^path" $CONFIG | cut -d= -f2 | tr -d ' ')
OUTPUT_DIR=/app/output

mkdir -p $OUTPUT_DIR

echo "Starting benchmark pipeline..."
echo "Database: $DB_PATH"

# Get all query set IDs
QS_IDS=$(sqlite3 $DB_PATH "SELECT id FROM query_batches ORDER BY id")

RESULTS="{"
FIRST=1

for QS_ID in $QS_IDS; do
    echo "Processing query set $QS_ID..."
    RESULT=$(python3 /app/scripts/solver.py $QS_ID 2>/tmp/err_${QS_ID}.log)
    if [ $? -ne 0 ]; then
        echo "  ERROR: $(tail -1 /tmp/err_${QS_ID}.log)"
        continue
    fi
    if [ $FIRST -eq 1 ]; then
        FIRST=0
    else
        RESULTS="$RESULTS,"
    fi
    RESULTS="$RESULTS \\"$QS_ID\\": $RESULT"
    echo "  OK"
done

RESULTS="$RESULTS}"
echo "$RESULTS" > $OUTPUT_DIR/results.json
echo "Results written to $OUTPUT_DIR/results.json"
''')
    os.chmod('/app/scripts/run_all.sh', 0o755)

    # === Write config with wrong table name ===

    with open('/app/config.ini', 'w') as f:
        f.write('''[database]
path = /app/benchmark.db
tree_table = tree_problems
query_table = query_sets

[solver]
max_recursion = 1000
timeout_seconds = 30

[output]
directory = /app/output
format = json
''')

    # === Write diagnostic log ===

    with open('/app/logs/last_run.log', 'w') as f:
        f.write('''=== Benchmark Pipeline Diagnostic ===
Date: 2024-05-20 (post-migration)
Operator: admin

$ bash /app/scripts/run_all.sh
  Error: no results from sqlite3 query.

$ python3 /app/scripts/solver.py 1
  sqlite3.OperationalError: no such table: tree_problems
  (config.ini tree_table value appears to be stale after migration)

After editing config.ini tree_table to match actual schema:

$ python3 /app/scripts/solver.py 1
  Completed (60 results)

$ python3 /app/scripts/solver.py 3
  TypeError: list indices must be integers or slices, not str
  (tree edge_data format mismatch?)

$ python3 /app/scripts/solver.py 4
  TypeError: list indices must be integers or slices, not str
  (same issue as QS 3 - trees 3 and 4 use same tree_id=2)

$ python3 /app/scripts/solver.py 5
  Completed (70 results)

$ python3 /app/scripts/solver.py 6
  json.decoder.JSONDecodeError: Expecting value: line 1 column 1
  (query_data blob is not plain JSON - check encoding column?)

$ python3 /app/scripts/solver.py 8
  RecursionError: maximum recursion depth exceeded
  (deep tree structure overwhelms recursive DFS)

Not all query sets tested. Multiple distinct root causes identified.
[ABANDONED - needs thorough debugging or full rewrite of solver pipeline]
''')


if __name__ == '__main__':
    main()
