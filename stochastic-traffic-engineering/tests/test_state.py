
import json
import os
import math
import pytest
import numpy as np
from collections import defaultdict


def load_topology():
    with open("/app/topology.json") as f:
        return json.load(f)


def load_demands():
    with open("/app/demands.json") as f:
        return json.load(f)


def load_config():
    with open("/app/config.json") as f:
        return json.load(f)


def load_solution():
    with open("/app/solution.json") as f:
        return json.load(f)


def compute_capacity_distribution(wavelengths):
    """Enumerate all 2^k states to get exact capacity distribution."""
    k = len(wavelengths)
    cap_prob = defaultdict(float)
    for mask in range(2**k):
        cap = 0
        prob = 1.0
        for i in range(k):
            if mask & (1 << i):
                cap += wavelengths[i]["capacity"]
                prob *= 1.0 - wavelengths[i]["failure_prob"]
            else:
                prob *= wavelengths[i]["failure_prob"]
        cap_prob[cap] += prob
    return dict(cap_prob)


def compute_safe_capacity(wavelengths, alpha):
    """Largest f such that P(C >= f) >= alpha."""
    cap_prob = compute_capacity_distribution(wavelengths)
    caps_desc = sorted(cap_prob.keys(), reverse=True)
    cum_prob = 0.0
    for cap in caps_desc:
        cum_prob += cap_prob[cap]
        if cum_prob >= alpha:
            return cap
    return 0


def compute_prob_at_least(wavelengths, threshold):
    """Compute P(C >= threshold) exactly."""
    cap_prob = compute_capacity_distribution(wavelengths)
    return sum(p for c, p in cap_prob.items() if c >= threshold)


def build_edge_set(topo):
    edges = set()
    edge_to_link = {}
    for link in topo["links"]:
        u, v = link["endpoints"]
        edges.add((u, v))
        edges.add((v, u))
        edge_to_link[(u, v)] = link["id"]
        edge_to_link[(v, u)] = link["id"]
    return edges, edge_to_link


def get_link_map(topo):
    return {link["id"]: link for link in topo["links"]}


def compute_link_flows(sol, edge_to_link):
    """Compute total flow per link from solution."""
    link_flows = defaultdict(float)
    for alloc in sol["allocations"]:
        for path_entry in alloc["paths"]:
            path = path_entry["nodes"]
            flow = path_entry["flow"]
            for i in range(len(path) - 1):
                lid = edge_to_link[(path[i], path[i + 1])]
                link_flows[lid] += flow
    return dict(link_flows)


class TestSolutionStructure:
    def test_solution_exists(self):
        assert os.path.exists("/app/solution.json"), "solution.json not found at /app/"

    def test_solution_format(self):
        sol = load_solution()
        assert "allocations" in sol, "Missing 'allocations' key"
        assert isinstance(sol["allocations"], list), "'allocations' must be a list"
        for alloc in sol["allocations"]:
            assert "demand_id" in alloc, "Missing 'demand_id' in allocation"
            assert "paths" in alloc, "Missing 'paths' in allocation"
            assert isinstance(alloc["paths"], list), "'paths' must be a list"
            for pe in alloc["paths"]:
                assert "nodes" in pe, "Missing 'nodes' in path entry"
                assert "flow" in pe, "Missing 'flow' in path entry"
                assert isinstance(pe["nodes"], list), "'nodes' must be a list"
                assert len(pe["nodes"]) >= 2, "Path must have at least 2 nodes"
                assert isinstance(pe["flow"], (int, float)), "'flow' must be numeric"
                assert pe["flow"] >= -0.001, "Flow must be non-negative"

    def test_all_demands_present(self):
        demands = load_demands()
        sol = load_solution()
        expected = {d["id"] for d in demands["demands"]}
        actual = {a["demand_id"] for a in sol["allocations"]}
        assert expected == actual, f"Expected demands {expected}, got {actual}"


class TestPathValidity:
    def test_paths_in_graph(self):
        topo = load_topology()
        sol = load_solution()
        edges, _ = build_edge_set(topo)
        nodes = set(topo["nodes"])
        for alloc in sol["allocations"]:
            for pe in alloc["paths"]:
                path = pe["nodes"]
                for node in path:
                    assert node in nodes, f"Node '{node}' not in topology"
                for i in range(len(path) - 1):
                    assert (path[i], path[i + 1]) in edges, (
                        f"No link between {path[i]} and {path[i+1]}"
                    )

    def test_paths_are_simple(self):
        sol = load_solution()
        for alloc in sol["allocations"]:
            for pe in alloc["paths"]:
                path = pe["nodes"]
                assert len(set(path)) == len(path), (
                    f"Path {path} for demand {alloc['demand_id']} is not simple"
                )

    def test_path_endpoints_match_demand(self):
        demands = load_demands()
        sol = load_solution()
        demand_map = {d["id"]: d for d in demands["demands"]}
        for alloc in sol["allocations"]:
            did = alloc["demand_id"]
            d = demand_map[did]
            for pe in alloc["paths"]:
                path = pe["nodes"]
                if pe["flow"] > 0.001:
                    assert path[0] == d["source"], (
                        f"Demand {did}: path starts at {path[0]}, expected {d['source']}"
                    )
                    assert path[-1] == d["destination"], (
                        f"Demand {did}: path ends at {path[-1]}, expected {d['destination']}"
                    )


class TestConstraints:
    def test_demand_volume_not_exceeded(self):
        demands = load_demands()
        sol = load_solution()
        demand_map = {d["id"]: d for d in demands["demands"]}
        for alloc in sol["allocations"]:
            did = alloc["demand_id"]
            total = sum(pe["flow"] for pe in alloc["paths"])
            vol = demand_map[did]["volume"]
            assert total <= vol + 0.01, (
                f"Demand {did}: total flow {total:.2f} exceeds volume {vol}"
            )

    def test_link_safe_capacity_not_exceeded(self):
        topo = load_topology()
        config = load_config()
        sol = load_solution()
        alpha = config["availability"]
        _, edge_to_link = build_edge_set(topo)
        link_map = get_link_map(topo)

        safe_caps = {}
        for lid, link in link_map.items():
            safe_caps[lid] = compute_safe_capacity(link["wavelengths"], alpha)

        link_flows = compute_link_flows(sol, edge_to_link)
        for lid, flow in link_flows.items():
            sc = safe_caps[lid]
            assert flow <= sc + 0.01, (
                f"Link {lid}: flow {flow:.2f} exceeds safe capacity {sc}"
            )

    def test_availability_exact(self):
        """Verify P(C >= total_flow) >= alpha for each link using exact Poisson binomial."""
        topo = load_topology()
        config = load_config()
        sol = load_solution()
        alpha = config["availability"]
        _, edge_to_link = build_edge_set(topo)
        link_map = get_link_map(topo)

        link_flows = compute_link_flows(sol, edge_to_link)
        for lid, flow in link_flows.items():
            if flow < 0.01:
                continue
            avail = compute_prob_at_least(link_map[lid]["wavelengths"], flow)
            assert avail >= alpha - 1e-9, (
                f"Link {lid}: exact availability {avail:.6f} < {alpha} "
                f"(flow={flow:.2f})"
            )


class TestAvailabilityMonteCarlo:
    def test_monte_carlo_verification(self):
        """Statistical verification of availability constraints."""
        topo = load_topology()
        config = load_config()
        sol = load_solution()
        alpha = config["availability"]
        _, edge_to_link = build_edge_set(topo)
        link_map = get_link_map(topo)

        link_flows = compute_link_flows(sol, edge_to_link)
        n_sim = 50000
        rng = np.random.default_rng(42)

        for lid, flow in link_flows.items():
            if flow < 0.01:
                continue
            link = link_map[lid]
            wls = link["wavelengths"]
            caps = np.array([w["capacity"] for w in wls])
            fail_probs = np.array([w["failure_prob"] for w in wls])

            survival = rng.random((n_sim, len(wls))) > fail_probs
            link_caps = (survival * caps).sum(axis=1)
            violations = (link_caps < flow).sum()
            empirical_avail = 1.0 - violations / n_sim

            margin = 3.5 * math.sqrt((1 - alpha) * alpha / n_sim)
            assert empirical_avail >= alpha - margin, (
                f"Link {lid}: MC availability {empirical_avail:.4f} too low "
                f"(threshold={alpha - margin:.4f}, flow={flow:.2f})"
            )


class TestOptimality:
    def test_near_optimal_throughput(self):
        """Total flow must be >= 85% of LP optimal."""
        from scipy.optimize import linprog
        from collections import deque

        topo = load_topology()
        demands_data = load_demands()
        config = load_config()
        sol = load_solution()
        alpha = config["availability"]

        # Build graph
        adj = defaultdict(list)
        link_map = get_link_map(topo)
        _, edge_to_link = build_edge_set(topo)
        for link in topo["links"]:
            u, v = link["endpoints"]
            adj[u].append((v, link["id"]))
            adj[v].append((u, link["id"]))

        # Compute safe capacities
        safe_caps = {}
        for lid, link in link_map.items():
            safe_caps[lid] = compute_safe_capacity(link["wavelengths"], alpha)

        # Find paths per demand via BFS
        def find_paths(src, dst, max_hops=6, max_paths=20):
            paths = []
            queue = deque([(src, [src], {src})])
            while queue and len(paths) < max_paths:
                node, path, visited = queue.popleft()
                if len(path) > max_hops + 1:
                    continue
                if node == dst:
                    paths.append(path)
                    continue
                for neighbor, lid in sorted(adj[node]):
                    if neighbor not in visited:
                        queue.append(
                            (neighbor, path + [neighbor], visited | {neighbor})
                        )
            return paths

        # Build LP variables
        var_info = []
        for d in demands_data["demands"]:
            paths = find_paths(d["source"], d["destination"])
            for pi, path in enumerate(paths):
                plinks = []
                for i in range(len(path) - 1):
                    plinks.append(edge_to_link[(path[i], path[i + 1])])
                var_info.append((d["id"], pi, path, plinks))

        n_vars = len(var_info)
        assert n_vars > 0, "No paths found for any demand"

        c = [-1.0] * n_vars
        A_ub = []
        b_ub = []

        demand_vols = {d["id"]: d["volume"] for d in demands_data["demands"]}
        demand_ids = [d["id"] for d in demands_data["demands"]]

        for did in demand_ids:
            row = [1.0 if var_info[i][0] == did else 0.0 for i in range(n_vars)]
            A_ub.append(row)
            b_ub.append(demand_vols[did])

        all_link_ids = list(link_map.keys())
        for lid in all_link_ids:
            row = [1.0 if lid in var_info[i][3] else 0.0 for i in range(n_vars)]
            if any(r > 0 for r in row):
                A_ub.append(row)
                b_ub.append(float(safe_caps[lid]))

        bounds = [(0, None)] * n_vars
        result = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
        assert result.success, f"Reference LP solver failed: {result.message}"
        ref_optimal = -result.fun

        agent_flow = sum(
            pe["flow"] for a in sol["allocations"] for pe in a["paths"]
        )
        assert agent_flow >= 0.85 * ref_optimal, (
            f"Total flow {agent_flow:.2f} < 85% of optimal {ref_optimal:.2f} "
            f"(minimum={0.85 * ref_optimal:.2f})"
        )

    def test_positive_throughput(self):
        """Solution must route a meaningful amount of flow."""
        sol = load_solution()
        total = sum(pe["flow"] for a in sol["allocations"] for pe in a["paths"])
        assert total > 100.0, f"Total flow {total:.2f} is too low"
