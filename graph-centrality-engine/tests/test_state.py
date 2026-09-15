
import os
import subprocess
import pytest
import networkx as nx


EXECUTABLE = "/app/graph_analytics"
DATA_DIR = "/app/data"
GRAPHS = ["small", "path", "cycle", "disconnected", "random"]

BC_TOL = 1e-4
PR_TOL = 1e-4


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_nx(name):
    """Load a directed graph from the edge-list file into NetworkX."""
    path = os.path.join(DATA_DIR, f"{name}.txt")
    g = nx.DiGraph()
    with open(path) as fh:
        n, m = map(int, fh.readline().split())
        g.add_nodes_from(range(n))
        for _ in range(m):
            u, v = map(int, fh.readline().split())
            g.add_edge(u, v)
    return g


def _reference_pagerank(g, damping=0.85, epsilon=1e-12, max_iter=500):
    """Push-based power-iteration PageRank matching the task specification.

    Dangling nodes (out-degree 0) redistribute rank uniformly.
    Convergence: L1 norm of rank-vector difference < epsilon.
    """
    nodes = sorted(g.nodes())
    n = len(nodes)
    inv_n = 1.0 / n
    pr = {v: inv_n for v in nodes}

    for _ in range(max_iter):
        # dangling-node rank mass
        dangling = sum(pr[v] for v in nodes if g.out_degree(v) == 0)

        # base rank: teleport + dangling redistribution
        base = (1.0 - damping) * inv_n + damping * dangling * inv_n
        new_pr = {v: base for v in nodes}

        # push rank along outgoing edges
        for u in nodes:
            deg = g.out_degree(u)
            if deg == 0:
                continue
            contrib = damping * pr[u] / deg
            for v in g.successors(u):
                new_pr[v] += contrib

        # convergence check (L1 norm)
        diff = sum(abs(new_pr[v] - pr[v]) for v in nodes)
        pr = new_pr
        if diff < epsilon:
            break

    return pr


def _run(graph_name, *args):
    """Run the C executable and return stdout."""
    graph_path = os.path.join(DATA_DIR, f"{graph_name}.txt")
    cmd = [EXECUTABLE, graph_path] + [str(a) for a in args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"graph_analytics failed (rc={result.returncode}).\n"
        f"cmd: {' '.join(cmd)}\nstderr: {result.stderr[:500]}"
    )
    return result.stdout


def _parse_int(output):
    vals = {}
    for line in output.strip().splitlines():
        v, d = line.split()
        vals[int(v)] = int(d)
    return vals


def _parse_float(output):
    vals = {}
    for line in output.strip().splitlines():
        parts = line.split()
        vals[int(parts[0])] = float(parts[1])
    return vals


# ---------------------------------------------------------------------------
# BFS tests
# ---------------------------------------------------------------------------

class TestBFS:
    @pytest.fixture(autouse=True)
    def _check_exe(self):
        assert os.path.isfile(EXECUTABLE), f"Executable not found: {EXECUTABLE}"

    @pytest.mark.parametrize("graph_name", GRAPHS)
    def test_bfs_from_vertex_0(self, graph_name):
        g = _load_nx(graph_name)
        computed = _parse_int(_run(graph_name, "bfs", 0))
        for v in g.nodes():
            try:
                expected = nx.shortest_path_length(g, 0, v)
            except nx.NetworkXNoPath:
                expected = -1
            assert computed[v] == expected, (
                f"BFS({graph_name}, src=0): vertex {v}: "
                f"got {computed[v]}, expected {expected}"
            )

    def test_bfs_multiple_sources(self):
        """BFS from several sources on the small graph."""
        g = _load_nx("small")
        for src in [0, 3, 6]:
            computed = _parse_int(_run("small", "bfs", src))
            for v in g.nodes():
                try:
                    expected = nx.shortest_path_length(g, src, v)
                except nx.NetworkXNoPath:
                    expected = -1
                assert computed[v] == expected, (
                    f"BFS(small, src={src}): vertex {v}: "
                    f"got {computed[v]}, expected {expected}"
                )

    def test_bfs_unreachable(self):
        """Disconnected graph: vertices in other components must be -1."""
        g = _load_nx("disconnected")
        computed = _parse_int(_run("disconnected", "bfs", 0))
        for v in g.nodes():
            try:
                expected = nx.shortest_path_length(g, 0, v)
            except nx.NetworkXNoPath:
                expected = -1
            assert computed[v] == expected


# ---------------------------------------------------------------------------
# Betweenness Centrality tests
# ---------------------------------------------------------------------------

class TestBetweennessCentrality:
    @pytest.fixture(autouse=True)
    def _check_exe(self):
        assert os.path.isfile(EXECUTABLE), f"Executable not found: {EXECUTABLE}"

    @pytest.mark.parametrize("graph_name", GRAPHS)
    def test_bc_values(self, graph_name):
        g = _load_nx(graph_name)
        ref = nx.betweenness_centrality(g, normalized=False)
        computed = _parse_float(_run(graph_name, "bc"))
        for v in g.nodes():
            assert abs(computed[v] - ref[v]) < BC_TOL, (
                f"BC({graph_name}): vertex {v}: "
                f"got {computed[v]:.10f}, expected {ref[v]:.10f}"
            )

    def test_bc_path_endpoints(self):
        """First and last vertex of a directed path have BC = 0."""
        computed = _parse_float(_run("path", "bc"))
        n = len(computed)
        assert computed[0] == pytest.approx(0.0, abs=BC_TOL)
        assert computed[n - 1] == pytest.approx(0.0, abs=BC_TOL)

    def test_bc_cycle_uniform(self):
        """All vertices in a directed cycle must have equal BC."""
        computed = _parse_float(_run("cycle", "bc"))
        vals = list(computed.values())
        for v in vals:
            assert v == pytest.approx(vals[0], abs=BC_TOL)


# ---------------------------------------------------------------------------
# PageRank tests
# ---------------------------------------------------------------------------

class TestPageRank:
    DAMPING = 0.85
    EPS = "1e-10"
    MAX_ITER = 500

    @pytest.fixture(autouse=True)
    def _check_exe(self):
        assert os.path.isfile(EXECUTABLE), f"Executable not found: {EXECUTABLE}"

    @pytest.mark.parametrize("graph_name", GRAPHS)
    def test_pagerank_values(self, graph_name):
        g = _load_nx(graph_name)
        ref = _reference_pagerank(g, damping=self.DAMPING,
                                  epsilon=1e-12, max_iter=500)
        computed = _parse_float(
            _run(graph_name, "pagerank", self.DAMPING, self.EPS, self.MAX_ITER)
        )
        for v in g.nodes():
            assert abs(computed[v] - ref[v]) < PR_TOL, (
                f"PageRank({graph_name}): vertex {v}: "
                f"got {computed[v]:.10f}, expected {ref[v]:.10f}"
            )

    @pytest.mark.parametrize("graph_name", GRAPHS)
    def test_pagerank_sums_to_one(self, graph_name):
        computed = _parse_float(
            _run(graph_name, "pagerank", self.DAMPING, self.EPS, self.MAX_ITER)
        )
        total = sum(computed.values())
        assert total == pytest.approx(1.0, abs=1e-3), (
            f"PageRank({graph_name}) sums to {total}, expected ~1.0"
        )

    def test_pagerank_cycle_uniform(self):
        """Directed cycle: all vertices have equal PageRank = 1/N."""
        computed = _parse_float(
            _run("cycle", "pagerank", self.DAMPING, self.EPS, self.MAX_ITER)
        )
        n = len(computed)
        expected = 1.0 / n
        for v in computed:
            assert computed[v] == pytest.approx(expected, abs=PR_TOL)

    def test_pagerank_dangling_nodes(self):
        """Disconnected graph with isolated vertices (dangling nodes)."""
        g = _load_nx("disconnected")
        ref = _reference_pagerank(g, damping=self.DAMPING,
                                  epsilon=1e-12, max_iter=500)
        computed = _parse_float(
            _run("disconnected", "pagerank", self.DAMPING, self.EPS, self.MAX_ITER)
        )
        for v in g.nodes():
            assert abs(computed[v] - ref[v]) < PR_TOL, (
                f"PageRank(disconnected): vertex {v}: "
                f"got {computed[v]:.10f}, expected {ref[v]:.10f}"
            )
