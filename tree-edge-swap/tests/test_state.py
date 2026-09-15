"""
Tests for network topology link-swap optimization.
Verifies correctness, validity, and optimality of results in the SQLite database,
plus audit report and change visualization deliverables.
"""

import sqlite3
import json
import os
import re
import pytest
from collections import deque

DB_PATH = '/app/netops.db'


def get_topology_ids():
    """Get all topology IDs from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('SELECT topology_id FROM topologies ORDER BY topology_id')
        ids = [row[0] for row in cur.fetchall()]
        conn.close()
        return ids
    except Exception:
        return []


def read_topology(conn, tid):
    """Read topology from the database."""
    cur = conn.cursor()
    cur.execute('SELECT node_count FROM topologies WHERE topology_id = ?', (tid,))
    n = cur.fetchone()[0]
    cur.execute('SELECT src_node, dst_node FROM links WHERE topology_id = ?', (tid,))
    edges = [(r[0], r[1]) for r in cur.fetchall()]
    adj = [[] for _ in range(n + 1)]
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)
    return n, adj, edges


def read_result(conn, tid):
    """Read optimization result for a topology."""
    cur = conn.cursor()
    cur.execute('''SELECT min_diameter, remove_src, remove_dst, add_src, add_dst
                   FROM optimization_results WHERE topology_id = ?''', (tid,))
    row = cur.fetchone()
    return row


def bfs_farthest(start, adj, n):
    dist = [-1] * (n + 1)
    dist[start] = 0
    q = deque([start])
    far, mx = start, 0
    while q:
        u = q.popleft()
        if dist[u] > mx:
            mx, far = dist[u], u
        for v in adj[u]:
            if dist[v] == -1:
                dist[v] = dist[u] + 1
                q.append(v)
    return far, mx


def compute_diameter_bfs(adj, n):
    e1, _ = bfs_farthest(1, adj, n)
    _, diam = bfs_farthest(e1, adj, n)
    return diam


def is_connected(adj, n):
    vis = bytearray(n + 1)
    vis[1] = 1
    q = deque([1])
    cnt = 1
    while q:
        u = q.popleft()
        for v in adj[u]:
            if not vis[v]:
                vis[v] = 1
                cnt += 1
                q.append(v)
    return cnt == n


def compute_optimal_diameter(n, adj, edges):
    """Compute the minimum possible diameter after one edge swap. O(N) algorithm."""
    if n <= 2:
        return n - 1

    root = 1
    par = [0] * (n + 1)
    par[root] = -1
    order = []
    vis = bytearray(n + 1)
    vis[root] = 1
    q = deque([root])
    while q:
        u = q.popleft()
        order.append(u)
        for v in adj[u]:
            if not vis[v]:
                vis[v] = 1
                par[v] = u
                q.append(v)

    ch = [[] for _ in range(n + 1)]
    for v in order[1:]:
        ch[par[v]].append(v)

    d1 = [0] * (n + 1)
    d2 = [0] * (n + 1)
    d3 = [0] * (n + 1)
    d1c = [0] * (n + 1)
    d2c = [0] * (n + 1)
    sd = [0] * (n + 1)

    for v in reversed(order):
        b1 = b2 = b3 = 0
        c1 = c2 = 0
        mxsd = 0
        for c in ch[v]:
            val = d1[c] + 1
            if sd[c] > mxsd:
                mxsd = sd[c]
            if val > b1:
                b3, b2, c2, b1, c1 = b2, b1, c1, val, c
            elif val > b2:
                b3, b2, c2 = b2, val, c
            elif val > b3:
                b3 = val
        d1[v], d1c[v] = b1, c1
        d2[v], d2c[v] = b2, c2
        d3[v] = b3
        sd[v] = max(mxsd, b1 + b2)

    sm1 = [0] * (n + 1)
    sm1c = [0] * (n + 1)
    sm2 = [0] * (n + 1)
    for v in order:
        b1 = b2 = 0
        c1 = 0
        for c in ch[v]:
            if sd[c] >= b1:
                b2, b1, c1 = b1, sd[c], c
            elif sd[c] > b2:
                b2 = sd[c]
        sm1[v], sm1c[v], sm2[v] = b1, c1, b2

    up = [0] * (n + 1)
    cd = [0] * (n + 1)
    for v in order:
        if par[v] == -1:
            continue
        p = par[v]
        bd = d2[p] if d1c[p] == v else d1[p]
        up[v] = 1 + max(up[p], bd)

        if d1c[p] == v:
            t1, t2 = d2[p], d3[p]
        elif d2c[p] == v:
            t1, t2 = d1[p], d3[p]
        else:
            t1, t2 = d1[p], d2[p]

        ssd = sm2[p] if sm1c[p] == v else sm1[p]
        cd[v] = max(cd[p], up[p] + bd, t1 + t2, ssd)

    best = float('inf')
    for v in order[1:]:
        ds, dc = sd[v], cd[v]
        ans = max(ds, dc, (ds + 1) // 2 + (dc + 1) // 2 + 1)
        if ans < best:
            best = ans

    return best


# =====================================================================
# Parameterized database result tests
# =====================================================================

@pytest.fixture(params=get_topology_ids())
def topology_id(request):
    return request.param


def test_result_exists(topology_id):
    """Result row must exist in optimization_results for each topology."""
    conn = sqlite3.connect(DB_PATH)
    row = read_result(conn, topology_id)
    conn.close()
    assert row is not None, f"No result in optimization_results for topology {topology_id}"


def test_result_format(topology_id):
    """Result must have valid node references."""
    conn = sqlite3.connect(DB_PATH)
    row = read_result(conn, topology_id)
    if row is None:
        conn.close()
        pytest.skip("Result row missing")
    diam, rs, rd, ads, add = row
    n, _, _ = read_topology(conn, topology_id)
    conn.close()
    assert isinstance(diam, int) and diam >= 0, "min_diameter must be non-negative integer"
    for node in [rs, rd, ads, add]:
        assert 1 <= node <= n, f"Node {node} out of range [1, {n}]"


def test_valid_swap(topology_id):
    """The link swap must produce a valid spanning tree."""
    conn = sqlite3.connect(DB_PATH)
    row = read_result(conn, topology_id)
    if row is None:
        conn.close()
        pytest.skip("Result row missing")
    diam, rs, rd, ads, add = row
    n, adj, edges = read_topology(conn, topology_id)
    conn.close()

    # Check removed link exists in original
    edge_set = set()
    for u, v in edges:
        edge_set.add((u, v))
        edge_set.add((v, u))
    assert (rs, rd) in edge_set or (rd, rs) in edge_set, \
        f"Link ({rs}, {rd}) does not exist in original topology"

    # Build modified adjacency list
    new_adj = [[] for _ in range(n + 1)]
    for u, v in edges:
        if (u == rs and v == rd) or (u == rd and v == rs):
            continue
        new_adj[u].append(v)
        new_adj[v].append(u)
    new_adj[ads].append(add)
    new_adj[add].append(ads)

    assert is_connected(new_adj, n), "Modified topology is not connected"
    total_edges = sum(len(new_adj[v]) for v in range(1, n + 1)) // 2
    assert total_edges == n - 1, f"Modified topology has {total_edges} links, expected {n - 1}"


def test_diameter_correct(topology_id):
    """The claimed min_diameter must match the actual diameter of the modified tree."""
    conn = sqlite3.connect(DB_PATH)
    row = read_result(conn, topology_id)
    if row is None:
        conn.close()
        pytest.skip("Result row missing")
    claimed_diam, rs, rd, ads, add = row
    n, adj, edges = read_topology(conn, topology_id)
    conn.close()

    new_adj = [[] for _ in range(n + 1)]
    for u, v in edges:
        if (u == rs and v == rd) or (u == rd and v == rs):
            continue
        new_adj[u].append(v)
        new_adj[v].append(u)
    new_adj[ads].append(add)
    new_adj[add].append(ads)

    actual_diam = compute_diameter_bfs(new_adj, n)
    assert actual_diam == claimed_diam, \
        f"Claimed diameter {claimed_diam} but actual is {actual_diam}"


def test_diameter_optimal(topology_id):
    """The claimed diameter must equal the globally optimal minimum."""
    conn = sqlite3.connect(DB_PATH)
    row = read_result(conn, topology_id)
    if row is None:
        conn.close()
        pytest.skip("Result row missing")
    claimed_diam = row[0]
    n, adj, edges = read_topology(conn, topology_id)
    conn.close()

    optimal = compute_optimal_diameter(n, adj, edges)
    assert claimed_diam == optimal, \
        f"Claimed diameter {claimed_diam} but optimal is {optimal}"


# =====================================================================
# Audit report tests
# =====================================================================

AUDIT_PATH = '/app/reports/audit.json'


def test_audit_report_exists():
    """Audit report must exist at /app/reports/audit.json."""
    assert os.path.isfile(AUDIT_PATH), \
        f"Audit report not found at {AUDIT_PATH}"


def test_audit_report_structure():
    """Audit report must have correct JSON structure."""
    if not os.path.isfile(AUDIT_PATH):
        pytest.skip("Audit report missing")
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    assert 'topologies' in data, "Missing 'topologies' key"
    topos = data['topologies']
    assert isinstance(topos, list), "'topologies' must be a list"
    assert len(topos) == 5, f"Expected 5 topologies, got {len(topos)}"
    ids = [t['id'] for t in topos]
    assert ids == sorted(ids), "Topologies must be sorted by id"
    for t in topos:
        for key in ['id', 'name', 'node_count', 'original_diameter',
                     'optimized_diameter', 'swap']:
            assert key in t, f"Missing key '{key}' in topology entry"
        assert isinstance(t['swap'], dict), "'swap' must be an object"
        for key in ['remove_src', 'remove_dst', 'add_src', 'add_dst']:
            assert key in t['swap'], f"Missing key '{key}' in swap object"


def test_audit_report_values():
    """Audit report values must match database and computed diameters."""
    if not os.path.isfile(AUDIT_PATH):
        pytest.skip("Audit report missing")
    with open(AUDIT_PATH) as f:
        data = json.load(f)
    conn = sqlite3.connect(DB_PATH)
    for t in data['topologies']:
        tid = t['id']
        # Check optimized_diameter matches DB
        row = read_result(conn, tid)
        assert row is not None, f"No DB result for topology {tid}"
        assert t['optimized_diameter'] == row[0], \
            f"Topology {tid}: audit optimized_diameter {t['optimized_diameter']} != DB {row[0]}"
        # Check swap values match DB
        assert t['swap']['remove_src'] == row[1]
        assert t['swap']['remove_dst'] == row[2]
        assert t['swap']['add_src'] == row[3]
        assert t['swap']['add_dst'] == row[4]
        # Check original_diameter via recomputation
        n, adj, edges = read_topology(conn, tid)
        orig_diam = compute_diameter_bfs(adj, n)
        assert t['original_diameter'] == orig_diam, \
            f"Topology {tid}: audit original_diameter {t['original_diameter']} != computed {orig_diam}"
    conn.close()


# =====================================================================
# Change visualization tests
# =====================================================================

DOT_PATH = '/app/reports/topology_changes.dot'
SVG_PATH = '/app/reports/topology_changes.svg'


def test_dot_file_exists():
    """DOT file must exist at /app/reports/topology_changes.dot."""
    assert os.path.isfile(DOT_PATH), \
        f"DOT file not found at {DOT_PATH}"


def test_dot_file_content():
    """DOT file must contain correct edge style annotations."""
    if not os.path.isfile(DOT_PATH):
        pytest.skip("DOT file missing")
    with open(DOT_PATH) as f:
        content = f.read()
    assert 'graph' in content.lower(), "DOT file must contain 'graph' keyword"
    assert 'style=dashed' in content, "DOT file must have dashed style for removed edge"
    assert 'color=red' in content, "DOT file must have red color for removed edge"
    assert 'style=bold' in content, "DOT file must have bold style for added edge"
    assert 'color=green' in content, "DOT file must have green color for added edge"


def test_dot_file_edges_match_db():
    """DOT file removed/added edges must match topology 1 database result."""
    if not os.path.isfile(DOT_PATH):
        pytest.skip("DOT file missing")
    conn = sqlite3.connect(DB_PATH)
    row = read_result(conn, 1)
    if row is None:
        conn.close()
        pytest.skip("No DB result for topology 1")
    _, rs, rd, ads, add_node = row
    conn.close()

    with open(DOT_PATH) as f:
        content = f.read()

    # Find edges with dashed+red (removed edge) — match either attribute order
    red_edges = re.findall(
        r'(\d+)\s*--\s*(\d+)\s*\[(?=.*?dashed)(?=.*?red)[^\]]*\]', content)
    assert len(red_edges) >= 1, "Must have at least one red dashed edge in DOT"
    found_removed = any(
        (int(a) == rs and int(b) == rd) or (int(a) == rd and int(b) == rs)
        for a, b in red_edges)
    assert found_removed, \
        f"Removed edge ({rs}, {rd}) not found with dashed/red style in DOT"

    # Find edges with bold+green (added edge)
    green_edges = re.findall(
        r'(\d+)\s*--\s*(\d+)\s*\[(?=.*?bold)(?=.*?green)[^\]]*\]', content)
    assert len(green_edges) >= 1, "Must have at least one green bold edge in DOT"
    found_added = any(
        (int(a) == ads and int(b) == add_node) or (int(a) == add_node and int(b) == ads)
        for a, b in green_edges)
    assert found_added, \
        f"Added edge ({ads}, {add_node}) not found with bold/green style in DOT"


def test_svg_file_exists():
    """SVG file must exist at /app/reports/topology_changes.svg."""
    assert os.path.isfile(SVG_PATH), \
        f"SVG file not found at {SVG_PATH}"


def test_svg_file_valid():
    """SVG file must be a valid SVG document."""
    if not os.path.isfile(SVG_PATH):
        pytest.skip("SVG file missing")
    with open(SVG_PATH) as f:
        content = f.read()
    assert '<svg' in content, "SVG file must contain <svg tag"
