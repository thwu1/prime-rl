
import json
import os
from collections import defaultdict, deque

import pytest


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    return data


# ================================================================
# Structural tests
# ================================================================

def test_results_is_dict(results):
    assert isinstance(results, dict)


def test_has_market_split_key(results):
    assert "market_split" in results


def test_has_independent_set_key(results):
    assert "independent_set" in results


def test_has_cvrp_key(results):
    assert "cvrp" in results


def test_has_topology_verify_key(results):
    assert "topology_verify" in results


# ================================================================
# Market Split verification
# ================================================================

def test_ms_num_constraints(results):
    ms = results["market_split"]
    assert ms["num_constraints"] == 4


def test_ms_num_variables(results):
    ms = results["market_split"]
    assert ms["num_variables"] == 20


def test_ms_rust_checker_built(results):
    ms = results["market_split"]
    assert ms["rust_checker_built"] is True


def test_ms_has_candidates(results):
    ms = results["market_split"]
    assert "candidates" in ms
    cands = ms["candidates"]
    assert len(cands) == 3


def test_ms_candidate_1_valid(results):
    cand = results["market_split"]["candidates"]["candidate_1.sol"]
    assert cand["valid"] is True


def test_ms_candidate_1_ones_count(results):
    cand = results["market_split"]["candidates"]["candidate_1.sol"]
    assert cand["ones_count"] == 11


def test_ms_candidate_1_rust_exit(results):
    cand = results["market_split"]["candidates"]["candidate_1.sol"]
    assert cand["rust_exit_code"] == 0


def test_ms_candidate_2_invalid(results):
    cand = results["market_split"]["candidates"]["candidate_2.sol"]
    assert cand["valid"] is False


def test_ms_candidate_2_ones_count(results):
    cand = results["market_split"]["candidates"]["candidate_2.sol"]
    assert cand["ones_count"] == 13


def test_ms_candidate_2_rust_exit(results):
    cand = results["market_split"]["candidates"]["candidate_2.sol"]
    assert cand["rust_exit_code"] == 1


def test_ms_candidate_3_valid(results):
    cand = results["market_split"]["candidates"]["candidate_3.sol"]
    assert cand["valid"] is True


def test_ms_candidate_3_ones_count(results):
    cand = results["market_split"]["candidates"]["candidate_3.sol"]
    assert cand["ones_count"] == 11


def test_ms_candidate_3_rust_exit(results):
    cand = results["market_split"]["candidates"]["candidate_3.sol"]
    assert cand["rust_exit_code"] == 0


# ================================================================
# Market Split QUBO analysis
# ================================================================

def test_ms_has_qubo(results):
    ms = results["market_split"]
    assert "qubo" in ms


def test_ms_qubo_dimension(results):
    qubo = results["market_split"]["qubo"]
    assert qubo["dimension"] == 20


def test_ms_qubo_num_nonzero(results):
    qubo = results["market_split"]["qubo"]
    assert qubo["num_nonzero"] == 210


def test_ms_qubo_min_coefficient(results):
    qubo = results["market_split"]["qubo"]
    assert qubo["min_coefficient"] == -215459


def test_ms_qubo_max_coefficient(results):
    qubo = results["market_split"]["qubo"]
    assert qubo["max_coefficient"] == 35306


def test_ms_qubo_constant_offset(results):
    qubo = results["market_split"]["qubo"]
    assert qubo["constant_offset"] == 806705


def test_ms_candidate_1_qubo_objective(results):
    cand = results["market_split"]["candidates"]["candidate_1.sol"]
    assert cand["qubo_objective"] == 0


def test_ms_candidate_2_qubo_objective(results):
    cand = results["market_split"]["candidates"]["candidate_2.sol"]
    assert cand["qubo_objective"] == 53245


def test_ms_candidate_3_qubo_objective(results):
    cand = results["market_split"]["candidates"]["candidate_3.sol"]
    assert cand["qubo_objective"] == 0


# ================================================================
# Independent Set verification
# ================================================================

def test_is_num_nodes(results):
    iset = results["independent_set"]
    assert iset["num_nodes"] == 17


def test_is_num_edges(results):
    iset = results["independent_set"]
    assert iset["num_edges"] == 39


def test_is_has_candidates(results):
    iset = results["independent_set"]
    assert "candidates" in iset
    assert len(iset["candidates"]) == 2


def test_is_candidate_1_valid(results):
    cand = results["independent_set"]["candidates"]["candidate_1.sol"]
    assert cand["valid"] is True


def test_is_candidate_1_set_size(results):
    cand = results["independent_set"]["candidates"]["candidate_1.sol"]
    assert cand["set_size"] == 10


def test_is_candidate_2_invalid(results):
    cand = results["independent_set"]["candidates"]["candidate_2.sol"]
    assert cand["valid"] is False


def test_is_candidate_2_set_size(results):
    cand = results["independent_set"]["candidates"]["candidate_2.sol"]
    assert cand["set_size"] == 7


# ================================================================
# CVRP verification
# ================================================================

def test_cvrp_instance_name(results):
    assert results["cvrp"]["instance_name"] == "QOB-n8-k3"


def test_cvrp_num_customers(results):
    assert results["cvrp"]["num_customers"] == 8


def test_cvrp_vehicle_capacity(results):
    assert results["cvrp"]["vehicle_capacity"] == 60


def test_cvrp_has_candidates(results):
    assert "candidates" in results["cvrp"]
    assert len(results["cvrp"]["candidates"]) == 2


def test_cvrp_candidate_1_valid(results):
    cand = results["cvrp"]["candidates"]["candidate_1.sol"]
    assert cand["valid"] is True


def test_cvrp_candidate_1_num_routes(results):
    cand = results["cvrp"]["candidates"]["candidate_1.sol"]
    assert cand["num_routes"] == 3


def test_cvrp_candidate_1_total_cost(results):
    cand = results["cvrp"]["candidates"]["candidate_1.sol"]
    assert cand["total_cost"] == 81


def test_cvrp_candidate_1_max_route_load(results):
    cand = results["cvrp"]["candidates"]["candidate_1.sol"]
    assert cand["max_route_load"] == 55


def test_cvrp_candidate_2_invalid(results):
    cand = results["cvrp"]["candidates"]["candidate_2.sol"]
    assert cand["valid"] is False


def test_cvrp_candidate_2_num_routes(results):
    cand = results["cvrp"]["candidates"]["candidate_2.sol"]
    assert cand["num_routes"] == 2


def test_cvrp_candidate_2_total_cost(results):
    cand = results["cvrp"]["candidates"]["candidate_2.sol"]
    assert cand["total_cost"] == 78


def test_cvrp_candidate_2_max_route_load(results):
    cand = results["cvrp"]["candidates"]["candidate_2.sol"]
    assert cand["max_route_load"] == 75


# ================================================================
# Topology verification
# ================================================================

def test_topo_required_nodes(results):
    tv = results["topology_verify"]
    assert tv["required_nodes"] == 20


def test_topo_required_max_degree(results):
    tv = results["topology_verify"]
    assert tv["required_max_degree"] == 4


def test_topo_has_candidates(results):
    tv = results["topology_verify"]
    assert "candidates" in tv
    assert len(tv["candidates"]) == 2


def test_topo_candidate_1_valid(results):
    cand = results["topology_verify"]["candidates"]["candidate_1.gph"]
    assert cand["valid"] is True


def test_topo_candidate_1_nodes(results):
    cand = results["topology_verify"]["candidates"]["candidate_1.gph"]
    assert cand["num_nodes"] == 20


def test_topo_candidate_1_edges(results):
    cand = results["topology_verify"]["candidates"]["candidate_1.gph"]
    assert cand["num_edges"] == 40


def test_topo_candidate_1_max_degree(results):
    cand = results["topology_verify"]["candidates"]["candidate_1.gph"]
    assert cand["max_degree"] == 4


def test_topo_candidate_1_diameter(results):
    cand = results["topology_verify"]["candidates"]["candidate_1.gph"]
    assert cand["diameter"] == 3


def test_topo_candidate_1_connected(results):
    cand = results["topology_verify"]["candidates"]["candidate_1.gph"]
    assert cand["connected"] is True


def test_topo_candidate_2_invalid(results):
    cand = results["topology_verify"]["candidates"]["candidate_2.gph"]
    assert cand["valid"] is False


def test_topo_candidate_2_max_degree(results):
    cand = results["topology_verify"]["candidates"]["candidate_2.gph"]
    assert cand["max_degree"] == 5


def test_topo_candidate_2_diameter(results):
    cand = results["topology_verify"]["candidates"]["candidate_2.gph"]
    assert cand["diameter"] == 3


# ================================================================
# Topology construction - independent verification
# ================================================================

def _parse_constructed_graph():
    """Parse the constructed DIMACS graph and return (n, adj)."""
    path = "/app/solutions/topo_25_3.gph"
    assert os.path.exists(path), f"Constructed graph not found at {path}"

    n = 0
    adj = defaultdict(set)
    edge_count = 0

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            parts = line.split()
            if parts[0] == "p":
                n = int(parts[2])
            elif parts[0] == "e":
                u, v = int(parts[1]), int(parts[2])
                adj[u].add(v)
                adj[v].add(u)
                edge_count += 1

    return n, adj, edge_count


def test_constructed_file_exists():
    assert os.path.exists("/app/solutions/topo_25_3.gph")


def test_constructed_node_count():
    n, adj, _ = _parse_constructed_graph()
    assert n == 25, f"Expected 25 nodes, got {n}"


def test_constructed_max_degree():
    n, adj, _ = _parse_constructed_graph()
    for node in range(1, n + 1):
        deg = len(adj[node])
        assert deg <= 3, f"Node {node} has degree {deg} > 3"


def test_constructed_connected():
    n, adj, _ = _parse_constructed_graph()
    visited = set()
    queue = deque([1])
    visited.add(1)
    while queue:
        node = queue.popleft()
        for neighbor in adj[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    assert len(visited) == n, (
        f"Graph is not connected: only {len(visited)} of {n} nodes reachable from node 1"
    )


def test_constructed_diameter():
    n, adj, _ = _parse_constructed_graph()
    diameter = 0
    for start in range(1, n + 1):
        dist = {start: 0}
        q = deque([start])
        while q:
            node = q.popleft()
            for neighbor in adj[node]:
                if neighbor not in dist:
                    dist[neighbor] = dist[node] + 1
                    q.append(neighbor)
        max_d = max(dist.values())
        diameter = max(diameter, max_d)
    assert diameter <= 10, f"Diameter {diameter} > 10"


def test_constructed_valid_node_ids():
    n, adj, _ = _parse_constructed_graph()
    all_nodes = set()
    for u in adj:
        all_nodes.add(u)
        all_nodes.update(adj[u])
    for node in all_nodes:
        assert 1 <= node <= n, f"Node {node} outside valid range [1, {n}]"
