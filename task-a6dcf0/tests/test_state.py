"""Tests for the benchmark pipeline repair task."""

import os
import json
import zlib
import base64
import sqlite3
import pytest


# === Independent reference solver ===

def _build_tree(n, edges):
    """Build tree structures using iterative DFS."""
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


def _lca(u, v, dep, up, lg):
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


def _get_path(u, v, dep, up, lg, par):
    l = _lca(u, v, dep, up, lg)
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


def _parse_edges(edge_data_json, format_version):
    """Parse edge data handling both dict and list formats."""
    edges_raw = json.loads(edge_data_json)
    parsed = []
    for e in edges_raw:
        if isinstance(e, dict):
            parsed.append((e["c"], e["p"], e["w"]))
        elif isinstance(e, list):
            parsed.append((e[0], e[1], e[2]))
    return parsed


def _decode_query_data(qdata, encoding):
    """Decode query data based on encoding type."""
    if encoding == 'zlib_base64':
        raw = base64.b64decode(qdata)
        decompressed = zlib.decompress(raw)
        return json.loads(decompressed.decode('utf-8'))
    else:
        return json.loads(qdata)


def _solve_encrypted(n, edges, encrypted_queries, initial_last_ans):
    """Solve XOR-encrypted queries on a tree."""
    par, ew, dep, up, lg = _build_tree(n, edges)

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
            ans = dep[u] + dep[v] - 2 * dep[_lca(u, v, dep, up, lg)]
        elif qt == "S":
            l = _lca(u, v, dep, up, lg)
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
            l = _lca(u, v, dep, up, lg)
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
            ans = _lca(u, v, dep, up, lg)
        elif qt == "K":
            path = _get_path(u, v, dep, up, lg, par)
            ans = path[k]

        results.append(ans)
        la = ans

    return results


def compute_all_expected():
    """Compute expected results for all query sets from the database."""
    db = sqlite3.connect('/app/benchmark.db')
    cur = db.cursor()

    cur.execute("SELECT id, tree_id, query_data, encoding, initial_last_ans "
                "FROM query_sets ORDER BY id")
    query_sets = cur.fetchall()

    expected = {}
    for qs_id, tree_id, qdata, encoding, init_la in query_sets:
        cur.execute("SELECT node_count, edge_data, format_version "
                    "FROM trees WHERE id = ?", (tree_id,))
        tree_row = cur.fetchone()

        if tree_row is None:
            expected[str(qs_id)] = []
            continue

        n, edge_data, fv = tree_row
        edges = _parse_edges(edge_data, fv)
        queries = _decode_query_data(qdata, encoding)

        if not queries:
            expected[str(qs_id)] = []
            continue

        results = _solve_encrypted(n, edges, queries, init_la)
        expected[str(qs_id)] = results

    db.close()
    return expected


# === Cached expected results ===

_cached_expected = None


def get_expected():
    global _cached_expected
    if _cached_expected is None:
        _cached_expected = compute_all_expected()
    return _cached_expected


# === Tests ===

def test_results_file_exists():
    """Agent must produce /app/output/results.json."""
    assert os.path.isfile('/app/output/results.json'), \
        "results.json not found at /app/output/results.json"


def test_valid_json():
    """Output must be valid JSON."""
    if not os.path.isfile('/app/output/results.json'):
        pytest.skip("results.json missing")
    with open('/app/output/results.json') as f:
        content = f.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        pytest.fail("results.json is not valid JSON: {}".format(e))
    assert isinstance(data, dict), "results.json must be a JSON object (dict)"


def test_all_query_sets_present():
    """All 9 query set IDs must be present as keys."""
    if not os.path.isfile('/app/output/results.json'):
        pytest.skip("results.json missing")
    with open('/app/output/results.json') as f:
        data = json.load(f)
    expected_ids = set(str(i) for i in range(1, 10))
    actual_ids = set(data.keys())
    missing = expected_ids - actual_ids
    assert not missing, "Missing query set IDs: {}".format(sorted(missing))


def test_missing_tree_handled():
    """Query set 9 (nonexistent tree) must map to empty list."""
    if not os.path.isfile('/app/output/results.json'):
        pytest.skip("results.json missing")
    with open('/app/output/results.json') as f:
        data = json.load(f)
    if "9" not in data:
        pytest.skip("query set 9 not in results")
    assert data["9"] == [], \
        "Query set 9 references nonexistent tree, expected [], got {}".format(
            data["9"][:5])


def test_result_counts():
    """Each query set must have the correct number of answers."""
    if not os.path.isfile('/app/output/results.json'):
        pytest.skip("results.json missing")
    with open('/app/output/results.json') as f:
        data = json.load(f)
    expected = get_expected()
    errors = []
    for qs_id in sorted(expected.keys(), key=int):
        if qs_id not in data:
            errors.append("QS {}: missing".format(qs_id))
            continue
        exp_len = len(expected[qs_id])
        act_len = len(data[qs_id])
        if exp_len != act_len:
            errors.append("QS {}: expected {} results, got {}".format(
                qs_id, exp_len, act_len))
    assert not errors, "Result count mismatches:\n" + "\n".join(errors)


def test_query_set_1_correct():
    """Query set 1 answers must be exactly correct."""
    _check_qs("1")


def test_query_set_2_correct():
    """Query set 2 answers must be exactly correct."""
    _check_qs("2")


def test_query_set_3_correct():
    """Query set 3 (zlib_base64 encoded, init_la=42) must be correct."""
    _check_qs("3")


def test_query_set_4_correct():
    """Query set 4 (list-format tree) must be correct."""
    _check_qs("4")


def test_query_set_5_correct():
    """Query set 5 answers must be exactly correct."""
    _check_qs("5")


def test_query_set_6_correct():
    """Query set 6 (zlib_base64 encoded) must be correct."""
    _check_qs("6")


def test_query_set_7_correct():
    """Query set 7 (deep chain tree, init_la=42) must be correct."""
    _check_qs("7")


def test_query_set_8_correct():
    """Query set 8 (deep chain tree) must be correct."""
    _check_qs("8")


def _check_qs(qs_id):
    """Helper: verify a single query set's results."""
    if not os.path.isfile('/app/output/results.json'):
        pytest.skip("results.json missing")
    with open('/app/output/results.json') as f:
        data = json.load(f)
    if qs_id not in data:
        pytest.fail("Query set {} not found in results".format(qs_id))

    expected = get_expected()
    exp = expected[qs_id]
    act = data[qs_id]

    if len(act) != len(exp):
        pytest.fail("QS {}: expected {} results, got {}".format(
            qs_id, len(exp), len(act)))

    mismatches = []
    for i, (a, e) in enumerate(zip(act, exp)):
        if a != e:
            mismatches.append((i, e, a))
    if mismatches:
        first = mismatches[0]
        pytest.fail(
            "QS {}: {} mismatches. First at index {}: expected {}, got {}".format(
                qs_id, len(mismatches), first[0], first[1], first[2]))
