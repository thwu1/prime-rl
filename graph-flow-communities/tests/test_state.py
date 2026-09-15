
import json
import os
import re
import sqlite3
import subprocess
from collections import defaultdict, deque

import pytest


def load_json(path):
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results():
    return load_json("/app/results.json")


@pytest.fixture(scope="module")
def network():
    conn = sqlite3.connect("/app/network.db")
    c = conn.cursor()
    metadata = {k: v for k, v in c.execute("SELECT key, value FROM metadata").fetchall()}
    edges = [
        {"from": r[0], "to": r[1], "capacity": r[2], "cost": r[3]}
        for r in c.execute(
            "SELECT from_node, to_node, capacity, cost FROM edges"
        ).fetchall()
    ]
    conn.close()
    return {
        "num_nodes": metadata["num_nodes"],
        "source": metadata["source"],
        "sink": metadata["sink"],
        "edges": edges,
    }


# ===================== MCMF Tests =====================


class TestMCMF:
    def test_max_flow_value(self, results):
        """The min-cut {0..4} vs {5..19} has capacity 6+8+3=17."""
        assert results["mcmf"]["max_flow"] == 17

    def test_flow_conservation(self, results, network):
        edge_flows = results["mcmf"]["edge_flows"]
        source = network["source"]
        sink = network["sink"]

        net = defaultdict(int)
        for u, v, f in edge_flows:
            net[u] -= f
            net[v] += f

        assert net[source] == -results["mcmf"]["max_flow"], (
            f"Source net outflow {-net[source]} != max_flow {results['mcmf']['max_flow']}"
        )
        assert net[sink] == results["mcmf"]["max_flow"], (
            f"Sink net inflow {net[sink]} != max_flow {results['mcmf']['max_flow']}"
        )
        for node in range(network["num_nodes"]):
            if node != source and node != sink:
                assert net[node] == 0, f"Flow not conserved at node {node}: net={net[node]}"

    def test_capacity_constraints(self, results, network):
        cap = {}
        for e in network["edges"]:
            cap[(e["from"], e["to"])] = e["capacity"]

        for u, v, f in results["mcmf"]["edge_flows"]:
            assert f > 0, f"Non-positive flow {f} reported on edge ({u},{v})"
            assert (u, v) in cap, f"Edge ({u},{v}) not in graph"
            assert f <= cap[(u, v)], (
                f"Flow {f} exceeds capacity {cap[(u, v)]} on edge ({u},{v})"
            )

    def test_cost_consistency(self, results, network):
        cost_map = {}
        for e in network["edges"]:
            cost_map[(e["from"], e["to"])] = e["cost"]

        computed_cost = sum(
            f * cost_map[(u, v)] for u, v, f in results["mcmf"]["edge_flows"]
        )
        assert computed_cost == results["mcmf"]["min_cost"], (
            f"Reported min_cost {results['mcmf']['min_cost']} != "
            f"computed from edge_flows {computed_cost}"
        )

    def test_no_augmenting_path_in_residual(self, results, network):
        """After max flow, no s-t path should exist in the residual graph."""
        source = network["source"]
        sink = network["sink"]

        flow_map = defaultdict(int)
        for u, v, f in results["mcmf"]["edge_flows"]:
            flow_map[(u, v)] = f

        residual = defaultdict(list)
        for e in network["edges"]:
            u, v = e["from"], e["to"]
            f = flow_map.get((u, v), 0)
            if e["capacity"] - f > 0:
                residual[u].append(v)
            if f > 0:
                residual[v].append(u)

        visited = set()
        queue = deque([source])
        visited.add(source)
        while queue:
            u = queue.popleft()
            for v in residual[u]:
                if v not in visited:
                    visited.add(v)
                    queue.append(v)

        assert sink not in visited, (
            "Sink reachable from source in residual graph - flow is not maximum"
        )


# ===================== Community Tests =====================


class TestCommunities:
    def test_valid_partition(self, results, network):
        assignment = results["communities"]["assignment"]
        for i in range(network["num_nodes"]):
            assert str(i) in assignment, f"Node {i} not assigned to any community"

        for k, v in assignment.items():
            assert isinstance(v, int) and v >= 0, (
                f"Invalid community id {v} for node {k}"
            )

    def test_modularity_recomputation(self, results, network):
        assignment = results["communities"]["assignment"]
        n = network["num_nodes"]

        adj = defaultdict(lambda: defaultdict(float))
        for e in network["edges"]:
            u, v, w = e["from"], e["to"], e["capacity"]
            adj[u][v] += w
            adj[v][u] += w

        total_2m = sum(adj[u][v] for u in range(n) for v in adj[u])
        assert total_2m > 0, "Graph has no edges"

        k = {u: sum(adj[u].values()) for u in range(n)}

        Q = 0.0
        for u in range(n):
            for v in adj[u]:
                if assignment[str(u)] == assignment[str(v)]:
                    Q += adj[u][v] - k[u] * k[v] / total_2m
        Q /= total_2m

        assert abs(Q - results["communities"]["modularity"]) < 1e-4, (
            f"Modularity mismatch: recomputed {Q:.6f}, "
            f"reported {results['communities']['modularity']:.6f}"
        )

    def test_modularity_quality(self, results):
        assert results["communities"]["modularity"] > 0.3, (
            f"Modularity {results['communities']['modularity']:.4f} is too low "
            f"for a graph with clear community structure"
        )

    def test_num_communities_consistent(self, results):
        assignment = results["communities"]["assignment"]
        actual = len(set(assignment.values()))
        assert actual == results["communities"]["num_communities"], (
            f"Reported num_communities {results['communities']['num_communities']} "
            f"!= actual distinct communities {actual}"
        )
        assert actual >= 2, "Must detect at least 2 communities"


# ===================== Shortest Path Tests =====================


class TestShortestPaths:
    def test_five_paths(self, results):
        assert len(results["shortest_paths"]) == 5, (
            f"Expected 5 shortest paths, got {len(results['shortest_paths'])}"
        )

    def test_paths_valid_and_simple(self, results, network):
        edge_set = set()
        for e in network["edges"]:
            edge_set.add((e["from"], e["to"]))

        source = network["source"]
        sink = network["sink"]

        for idx, entry in enumerate(results["shortest_paths"]):
            path = entry["path"]
            assert path[0] == source, f"Path {idx} doesn't start at source"
            assert path[-1] == sink, f"Path {idx} doesn't end at sink"
            assert len(path) == len(set(path)), f"Path {idx} is not simple"
            for i in range(len(path) - 1):
                assert (path[i], path[i + 1]) in edge_set, (
                    f"Path {idx} uses non-existent edge ({path[i]},{path[i + 1]})"
                )

    def test_costs_correct(self, results, network):
        cost_map = {}
        for e in network["edges"]:
            cost_map[(e["from"], e["to"])] = e["cost"]

        for idx, entry in enumerate(results["shortest_paths"]):
            path = entry["path"]
            computed = sum(
                cost_map[(path[i], path[i + 1])] for i in range(len(path) - 1)
            )
            assert computed == entry["cost"], (
                f"Path {idx} cost mismatch: computed {computed}, reported {entry['cost']}"
            )

    def test_paths_ordered(self, results):
        paths = results["shortest_paths"]
        for i in range(len(paths) - 1):
            assert paths[i]["cost"] <= paths[i + 1]["cost"], (
                f"Paths not in non-decreasing cost order: "
                f"path {i} cost {paths[i]['cost']} > path {i + 1} cost {paths[i + 1]['cost']}"
            )

    def test_paths_distinct(self, results):
        tuples = [tuple(e["path"]) for e in results["shortest_paths"]]
        assert len(tuples) == len(set(tuples)), "Duplicate paths found"

    def test_first_path_is_shortest(self, results, network):
        """Verify the first path cost is achievable via Dijkstra."""
        n = network["num_nodes"]
        source = network["source"]
        sink = network["sink"]

        import heapq

        adj = defaultdict(list)
        for e in network["edges"]:
            adj[e["from"]].append((e["to"], e["cost"]))

        dist = [float("inf")] * n
        dist[source] = 0
        pq = [(0, source)]

        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, c in adj[u]:
                nd = d + c
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))

        assert results["shortest_paths"][0]["cost"] == dist[sink], (
            f"First path cost {results['shortest_paths'][0]['cost']} != "
            f"Dijkstra shortest {dist[sink]}"
        )


# ===================== Cross-Analysis Tests =====================


class TestCrossAnalysis:
    def test_cross_community_flow_fraction(self, results):
        assignment = results["communities"]["assignment"]
        edge_flows = results["mcmf"]["edge_flows"]

        cross_flow = 0
        total_flow = 0
        for u, v, f in edge_flows:
            total_flow += f
            if assignment[str(u)] != assignment[str(v)]:
                cross_flow += f

        if total_flow > 0:
            expected = cross_flow / total_flow
        else:
            expected = 0.0

        assert abs(results["cross_community_flow_fraction"] - expected) < 1e-6, (
            f"Cross-community flow fraction mismatch: "
            f"expected {expected:.6f}, got {results['cross_community_flow_fraction']:.6f}"
        )

    def test_cross_community_fraction_range(self, results):
        frac = results["cross_community_flow_fraction"]
        assert 0.0 <= frac <= 1.0, (
            f"Cross-community flow fraction {frac} out of range [0, 1]"
        )

    def test_bottleneck_edge_exists(self, results, network):
        bn = results["bottleneck_edge"]
        found = False
        for e in network["edges"]:
            if e["from"] == bn["from"] and e["to"] == bn["to"]:
                found = True
                assert bn["capacity"] == e["capacity"], (
                    f"Bottleneck capacity {bn['capacity']} != "
                    f"graph capacity {e['capacity']}"
                )
                break
        assert found, f"Bottleneck edge ({bn['from']},{bn['to']}) not in graph"

    def test_bottleneck_is_inter_community(self, results):
        assignment = results["communities"]["assignment"]
        bn = results["bottleneck_edge"]
        assert assignment[str(bn["from"])] != assignment[str(bn["to"])], (
            "Bottleneck edge endpoints are in the same community"
        )

    def test_bottleneck_has_max_inter_flow(self, results):
        assignment = results["communities"]["assignment"]
        bn = results["bottleneck_edge"]
        edge_flows = results["mcmf"]["edge_flows"]

        max_inter_flow = 0
        for u, v, f in edge_flows:
            if assignment[str(u)] != assignment[str(v)]:
                max_inter_flow = max(max_inter_flow, f)

        assert bn["flow"] == max_inter_flow, (
            f"Bottleneck flow {bn['flow']} != max inter-community flow {max_inter_flow}"
        )

    def test_bottleneck_flow_in_edge_flows(self, results):
        bn = results["bottleneck_edge"]
        found = False
        for u, v, f in results["mcmf"]["edge_flows"]:
            if u == bn["from"] and v == bn["to"]:
                found = True
                assert f == bn["flow"], (
                    f"Bottleneck reported flow {bn['flow']} != edge_flows flow {f}"
                )
                break
        assert found, "Bottleneck edge not found in edge_flows"


# ===================== DOT File Tests =====================


class TestDotFile:
    def test_dot_file_exists(self):
        assert os.path.exists("/app/flow_graph.dot"), "flow_graph.dot not found"

    def test_dot_valid_syntax(self):
        """Verify graphviz can parse and render the DOT file."""
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/flow_graph.dot"],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"dot rendering failed: {result.stderr.decode()}"
        )

    def test_dot_is_digraph(self):
        with open("/app/flow_graph.dot") as f:
            content = f.read()
        assert "digraph" in content, "DOT file must contain a digraph declaration"

    def test_dot_contains_all_nodes(self, results):
        with open("/app/flow_graph.dot") as f:
            content = f.read()

        assignment = results["communities"]["assignment"]
        for node_id in range(20):
            comm_id = assignment[str(node_id)]
            assert re.search(rf'\b{node_id}\b\s*\[', content), (
                f"Node {node_id} not declared in DOT file"
            )
            assert re.search(
                rf'\b{node_id}\b\s*\[.*label\s*=\s*"[^"]*C{comm_id}"', content
            ), f"Node {node_id} missing correct community label C{comm_id}"

    def test_dot_contains_flow_edges(self, results):
        with open("/app/flow_graph.dot") as f:
            content = f.read()

        for u, v, flow in results["mcmf"]["edge_flows"]:
            assert re.search(rf'\b{u}\b\s*->\s*\b{v}\b\s*\[', content), (
                f"Edge {u}->{v} with flow {flow} not in DOT file"
            )

    def test_dot_flow_labels(self, results, network):
        with open("/app/flow_graph.dot") as f:
            content = f.read()

        cap_map = {}
        for e in network["edges"]:
            cap_map[(e["from"], e["to"])] = e["capacity"]

        for u, v, flow in results["mcmf"]["edge_flows"]:
            cap = cap_map[(u, v)]
            assert re.search(
                rf'\b{u}\b\s*->\s*\b{v}\b\s*\[.*label\s*=\s*"{flow}/{cap}"', content
            ), f"Edge {u}->{v} missing correct flow label {flow}/{cap}"

    def test_dot_community_colors_differ(self, results):
        with open("/app/flow_graph.dot") as f:
            content = f.read()

        assignment = results["communities"]["assignment"]
        comm_colors = {}
        for node_id in range(20):
            comm_id = assignment[str(node_id)]
            match = re.search(
                rf'\b{node_id}\b\s*\[.*fillcolor\s*=\s*"([^"]+)"', content
            )
            assert match, f"Node {node_id} missing fillcolor attribute"
            color = match.group(1)
            if comm_id in comm_colors:
                assert comm_colors[comm_id] == color, (
                    f"Inconsistent color for community {comm_id}: "
                    f"node {node_id} has {color}, expected {comm_colors[comm_id]}"
                )
            else:
                comm_colors[comm_id] = color

        colors_used = list(comm_colors.values())
        assert len(set(colors_used)) == len(colors_used), (
            "Different communities must have different fillcolors"
        )


# ===================== Analysis DB Tests =====================


class TestAnalysisDB:
    @pytest.fixture(scope="class")
    def adb(self):
        conn = sqlite3.connect("/app/analysis.db")
        yield conn
        conn.close()

    def test_db_exists(self):
        assert os.path.exists("/app/analysis.db"), "analysis.db not found"

    def test_community_assignments(self, adb, results):
        c = adb.cursor()
        rows = dict(
            c.execute("SELECT node_id, community_id FROM community_assignments").fetchall()
        )
        assert len(rows) == 20, f"Expected 20 community_assignments rows, got {len(rows)}"

        assignment = results["communities"]["assignment"]
        for node_id in range(20):
            assert node_id in rows, (
                f"Node {node_id} missing from community_assignments table"
            )
            assert rows[node_id] == assignment[str(node_id)], (
                f"Node {node_id}: DB community {rows[node_id]} "
                f"!= JSON community {assignment[str(node_id)]}"
            )

    def test_shortest_paths_table(self, adb, results):
        c = adb.cursor()
        rows = c.execute(
            "SELECT rank, path, cost FROM shortest_paths ORDER BY rank"
        ).fetchall()
        assert len(rows) == 5, f"Expected 5 shortest_paths rows, got {len(rows)}"

        for i, (rank, path_str, cost) in enumerate(rows):
            expected = results["shortest_paths"][i]
            assert cost == expected["cost"], (
                f"Path rank {rank}: DB cost {cost} != JSON cost {expected['cost']}"
            )
            path_nodes = [int(x.strip()) for x in path_str.split(",")]
            assert path_nodes == expected["path"], (
                f"Path rank {rank}: DB path {path_nodes} != JSON path {expected['path']}"
            )

    def test_edge_flows_table(self, adb, results):
        c = adb.cursor()
        rows = c.execute(
            "SELECT from_node, to_node, flow, capacity FROM edge_flows"
        ).fetchall()

        expected = {(u, v): f for u, v, f in results["mcmf"]["edge_flows"]}
        actual = {(r[0], r[1]): r[2] for r in rows}

        assert len(actual) == len(expected), (
            f"Expected {len(expected)} edge_flows rows, got {len(actual)}"
        )

        for (u, v), flow in expected.items():
            assert (u, v) in actual, f"Edge ({u},{v}) missing from edge_flows table"
            assert actual[(u, v)] == flow, (
                f"Edge ({u},{v}): DB flow {actual[(u, v)]} != JSON flow {flow}"
            )

    def test_metrics_table(self, adb, results):
        c = adb.cursor()
        metrics = dict(c.execute("SELECT key, value FROM metrics").fetchall())

        expected_keys = [
            "max_flow",
            "min_cost",
            "modularity",
            "num_communities",
            "cross_community_flow_fraction",
        ]
        for key in expected_keys:
            assert key in metrics, f"Metric '{key}' missing from metrics table"

        assert abs(metrics["max_flow"] - results["mcmf"]["max_flow"]) < 1e-6
        assert abs(metrics["min_cost"] - results["mcmf"]["min_cost"]) < 1e-6
        assert abs(metrics["modularity"] - results["communities"]["modularity"]) < 1e-4
        assert abs(
            metrics["num_communities"] - results["communities"]["num_communities"]
        ) < 1e-6
        assert abs(
            metrics["cross_community_flow_fraction"]
            - results["cross_community_flow_fraction"]
        ) < 1e-6

    def test_edge_flows_capacity_consistent(self, adb, network):
        """Verify capacities in analysis.db match the source graph."""
        c = adb.cursor()
        rows = c.execute(
            "SELECT from_node, to_node, capacity FROM edge_flows"
        ).fetchall()

        cap_map = {}
        for e in network["edges"]:
            cap_map[(e["from"], e["to"])] = e["capacity"]

        for from_node, to_node, cap in rows:
            assert (from_node, to_node) in cap_map, (
                f"Edge ({from_node},{to_node}) in analysis.db not in source graph"
            )
            assert cap == cap_map[(from_node, to_node)], (
                f"Edge ({from_node},{to_node}): analysis.db capacity {cap} "
                f"!= source capacity {cap_map[(from_node, to_node)]}"
            )
