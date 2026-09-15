
import json
import pytest
from collections import defaultdict


# ---------------------------------------------------------------------------
# Reference graph construction (same structure as graph_gen.py)
# ---------------------------------------------------------------------------

def _generate_expected_edges():
    edges = set()

    def add_clique(nodes):
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                edges.add((min(nodes[i], nodes[j]), max(nodes[i], nodes[j])))

    def add_edge(u, v):
        edges.add((min(u, v), max(u, v)))

    add_clique(list(range(1, 9)))      # K8
    add_clique(list(range(9, 16)))     # K7
    add_clique(list(range(16, 22)))    # K6
    add_clique(list(range(22, 27)))    # K5a
    add_clique(list(range(27, 31)))    # K4
    add_clique([31, 32, 33])           # Triangle A
    add_clique([34, 35, 36])           # Triangle B
    add_clique(list(range(37, 42)))    # K5b
    add_edge(42, 43)                   # Lone edge
    for u, v in [(8, 9), (15, 16), (21, 22), (26, 27), (30, 31), (33, 34)]:
        add_edge(u, v)

    return edges


# ---------------------------------------------------------------------------
# Reference algorithms
# ---------------------------------------------------------------------------

def _adj(edges):
    a = defaultdict(set)
    for u, v in edges:
        a[u].add(v)
        a[v].add(u)
    return a


def _all_nodes(edges):
    nodes = set()
    for u, v in edges:
        nodes.update([u, v])
    return nodes


def _triangles(edges):
    a = _adj(edges)
    total = 0
    for u, v in edges:
        total += len(a[u] & a[v])
    return total // 3


def _ktruss(edge_set, k):
    remaining = set(edge_set)
    while True:
        a = _adj(remaining)
        drop = {(u, v) for u, v in remaining if len(a[u] & a[v]) < k - 2}
        if not drop:
            break
        remaining -= drop
    return remaining


def _trussness(edges):
    result = {}
    prev = set(edges)
    k = 3
    while prev:
        cur = _ktruss(prev, k)
        for e in prev - cur:
            result[e] = k - 1
        prev = cur
        k += 1
    return result


def _components(edges):
    if not edges:
        return 0
    a = _adj(edges)
    nodes = _all_nodes(edges)
    seen = set()
    count = 0
    for n in nodes:
        if n in seen:
            continue
        count += 1
        stack = [n]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(a[x] - seen)
    return count


def _core_decomposition(edges):
    """Matula-Beck k-core peeling: process nodes by min degree, decrement only if greater."""
    a = _adj(edges)
    nodes = _all_nodes(edges)
    deg = {n: len(a[n]) for n in nodes}
    coreness = {}
    remaining = set(nodes)

    while remaining:
        u = min(remaining, key=lambda n: deg[n])
        core_val = deg[u]
        coreness[u] = core_val
        remaining.remove(u)
        for v in a[u]:
            if v in remaining and deg[v] > core_val:
                deg[v] -= 1

    return coreness


def _bron_kerbosch(R, P, X, adj, cliques):
    """Bron-Kerbosch with pivot for maximal clique enumeration."""
    if not P and not X:
        cliques.append(frozenset(R))
        return
    pivot = max(P | X, key=lambda u: len(adj[u] & P))
    candidates = list(P - adj[pivot])
    for v in candidates:
        _bron_kerbosch(R | {v}, P & adj[v], X & adj[v], adj, cliques)
        P = P - {v}
        X = X | {v}


def _maximal_cliques(edges, min_size=3):
    a = _adj(edges)
    nodes = _all_nodes(edges)
    cliques = []
    _bron_kerbosch(set(), set(nodes), set(), a, cliques)
    return [c for c in cliques if len(c) >= min_size]


def _articulation_points(edges):
    """Tarjan's algorithm for articulation points."""
    a = _adj(edges)
    nodes = _all_nodes(edges)
    visited = set()
    disc = {}
    low = {}
    parent = {}
    ap = set()
    timer = [0]

    def dfs(u):
        children = 0
        visited.add(u)
        disc[u] = low[u] = timer[0]
        timer[0] += 1
        for v in sorted(a[u]):
            if v not in visited:
                children += 1
                parent[v] = u
                dfs(v)
                low[u] = min(low[u], low[v])
                if parent.get(u) is None and children > 1:
                    ap.add(u)
                if parent.get(u) is not None and low[v] >= disc[u]:
                    ap.add(u)
            elif v != parent.get(u):
                low[u] = min(low[u], disc[v])

    import sys
    sys.setrecursionlimit(200)
    for n in sorted(nodes):
        if n not in visited:
            parent[n] = None
            dfs(n)
    return ap


def _bridges(edges):
    """Tarjan's bridge-finding algorithm."""
    a = _adj(edges)
    nodes = _all_nodes(edges)
    visited = set()
    disc = {}
    low = {}
    parent = {}
    bridge_set = set()
    timer = [0]

    def dfs(u):
        visited.add(u)
        disc[u] = low[u] = timer[0]
        timer[0] += 1
        for v in sorted(a[u]):
            if v not in visited:
                parent[v] = u
                dfs(v)
                low[u] = min(low[u], low[v])
                if low[v] > disc[u]:
                    bridge_set.add((min(u, v), max(u, v)))
            elif v != parent.get(u):
                low[u] = min(low[u], disc[v])

    import sys
    sys.setrecursionlimit(200)
    for n in sorted(nodes):
        if n not in visited:
            parent[n] = None
            dfs(n)
    return bridge_set


def _diameter(edges):
    """BFS-based diameter (max over all components)."""
    a = _adj(edges)
    nodes = _all_nodes(edges)
    max_dist = 0
    for start in nodes:
        dist = {start: 0}
        queue = [start]
        while queue:
            u = queue.pop(0)
            for v in a[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    queue.append(v)
        if dist:
            max_dist = max(max_dist, max(dist.values()))
    return max_dist


# ---------------------------------------------------------------------------
# Compute all expected values
# ---------------------------------------------------------------------------

def _expected():
    edges = _generate_expected_edges()
    nodes = _all_nodes(edges)

    tc = _triangles(edges)
    tn = _trussness(edges)
    mk = max(tn.values())

    truss_hist = defaultdict(int)
    for v in tn.values():
        truss_hist[v] += 1

    ktruss_comps = {}
    for k in range(2, mk + 1):
        kt = _ktruss(edges, k)
        if kt:
            ktruss_comps[str(k)] = _components(kt)

    coreness = _core_decomposition(edges)
    degeneracy = max(coreness.values())
    core_hist = defaultdict(int)
    for c in coreness.values():
        core_hist[c] += 1

    max_cliques = _maximal_cliques(edges, min_size=3)
    clique_number = max(len(c) for c in max_cliques)
    num_maximal_cliques = len(max_cliques)

    diam = _diameter(edges)
    ap = _articulation_points(edges)
    br = _bridges(edges)

    densest = set()
    for e, kv in tn.items():
        if kv == mk:
            densest.add(e[0])
            densest.add(e[1])

    return {
        "num_nodes": len(nodes),
        "num_edges": len(edges),
        "triangle_count": tc,
        "max_trussness": mk,
        "trussness_histogram": {str(k): c for k, c in sorted(truss_hist.items())},
        "degeneracy": degeneracy,
        "core_histogram": {str(k): c for k, c in sorted(core_hist.items())},
        "clique_number": clique_number,
        "num_maximal_cliques": num_maximal_cliques,
        "diameter": diam,
        "num_articulation_points": len(ap),
        "num_bridges": len(br),
        "num_connected_components": _components(edges),
        "ktruss_components": ktruss_comps,
        "densest_subgraph_nodes": sorted(densest),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def expected():
    return _expected()


@pytest.fixture(scope="module")
def results():
    with open('/app/results.json') as f:
        return json.load(f)


class TestGraphReconstruction:
    """Verify correct data integration across all formats."""

    def test_results_file_exists(self):
        import os
        assert os.path.isfile('/app/results.json'), "results.json not found"

    def test_num_nodes(self, results, expected):
        assert results["num_nodes"] == expected["num_nodes"], \
            f"Expected {expected['num_nodes']} nodes, got {results['num_nodes']}"

    def test_num_edges(self, results, expected):
        assert results["num_edges"] == expected["num_edges"], \
            f"Expected {expected['num_edges']} edges, got {results['num_edges']}"


class TestTriangleCounting:

    def test_triangle_count(self, results, expected):
        assert results["triangle_count"] == expected["triangle_count"], \
            f"Expected {expected['triangle_count']} triangles, got {results['triangle_count']}"


class TestTrussDecomposition:

    def test_max_trussness(self, results, expected):
        assert results["max_trussness"] == expected["max_trussness"]

    def test_trussness_histogram_keys(self, results, expected):
        assert set(results["trussness_histogram"].keys()) == set(
            expected["trussness_histogram"].keys()
        ), "Trussness histogram has wrong set of keys"

    def test_trussness_histogram_values(self, results, expected):
        for k, v in expected["trussness_histogram"].items():
            assert results["trussness_histogram"].get(k) == v, (
                f"Trussness histogram mismatch at k={k}: "
                f"expected {v}, got {results['trussness_histogram'].get(k)}"
            )

    def test_trussness_total_edges(self, results, expected):
        total = sum(results["trussness_histogram"].values())
        assert total == results["num_edges"], \
            f"Histogram edge total {total} != num_edges {results['num_edges']}"

    def test_ktruss_components_keys(self, results, expected):
        assert set(results["ktruss_components"].keys()) == set(
            expected["ktruss_components"].keys()
        ), "ktruss_components has wrong set of keys"

    def test_ktruss_components_values(self, results, expected):
        for k, v in expected["ktruss_components"].items():
            assert results["ktruss_components"].get(k) == v, (
                f"ktruss_components mismatch at k={k}: "
                f"expected {v}, got {results['ktruss_components'].get(k)}"
            )

    def test_densest_subgraph_nodes(self, results, expected):
        assert results["densest_subgraph_nodes"] == expected["densest_subgraph_nodes"]


class TestCoreDecomposition:

    def test_degeneracy(self, results, expected):
        assert results["degeneracy"] == expected["degeneracy"], \
            f"Expected degeneracy {expected['degeneracy']}, got {results['degeneracy']}"

    def test_core_histogram_keys(self, results, expected):
        assert set(results["core_histogram"].keys()) == set(
            expected["core_histogram"].keys()
        ), "Core histogram has wrong set of keys"

    def test_core_histogram_values(self, results, expected):
        for k, v in expected["core_histogram"].items():
            assert results["core_histogram"].get(k) == v, (
                f"Core histogram mismatch at k={k}: "
                f"expected {v}, got {results['core_histogram'].get(k)}"
            )

    def test_core_total_nodes(self, results, expected):
        total = sum(results["core_histogram"].values())
        assert total == results["num_nodes"], \
            f"Core histogram total {total} != num_nodes {results['num_nodes']}"


class TestCliqueAnalysis:

    def test_clique_number(self, results, expected):
        assert results["clique_number"] == expected["clique_number"], \
            f"Expected clique number {expected['clique_number']}, got {results['clique_number']}"

    def test_num_maximal_cliques(self, results, expected):
        assert results["num_maximal_cliques"] == expected["num_maximal_cliques"], \
            f"Expected {expected['num_maximal_cliques']} maximal cliques (size>=3), got {results['num_maximal_cliques']}"


class TestStructuralProperties:

    def test_diameter(self, results, expected):
        assert results["diameter"] == expected["diameter"], \
            f"Expected diameter {expected['diameter']}, got {results['diameter']}"

    def test_num_articulation_points(self, results, expected):
        assert results["num_articulation_points"] == expected["num_articulation_points"], \
            f"Expected {expected['num_articulation_points']} articulation points, got {results['num_articulation_points']}"

    def test_num_bridges(self, results, expected):
        assert results["num_bridges"] == expected["num_bridges"], \
            f"Expected {expected['num_bridges']} bridges, got {results['num_bridges']}"

    def test_num_connected_components(self, results, expected):
        assert results["num_connected_components"] == expected["num_connected_components"], \
            f"Expected {expected['num_connected_components']} components, got {results['num_connected_components']}"


class TestConsistency:
    """Cross-check relationships between different metrics."""

    def test_clique_number_le_degeneracy_plus_one(self, results):
        assert results["clique_number"] <= results["degeneracy"] + 1, \
            "Clique number should be <= degeneracy + 1"

    def test_max_trussness_le_clique_number(self, results):
        assert results["max_trussness"] <= results["clique_number"], \
            "Max trussness should be <= clique number"

    def test_bridges_le_edges(self, results):
        assert results["num_bridges"] <= results["num_edges"]

    def test_articulation_lt_nodes(self, results):
        assert results["num_articulation_points"] < results["num_nodes"]
