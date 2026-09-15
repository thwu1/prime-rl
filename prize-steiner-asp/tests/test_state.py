"""
Tests for the PCST ASP-Core-2 encoding.
Verifies correctness and optimality on all benchmark instances.
"""

import os
import re
import clingo
import pytest

ENCODING_PATH = "/app/encoding.lp"
INSTANCES_DIR = "/app/instances"

EXPECTED_PROFITS = {
    "inst_01.lp": 16,
    "inst_02.lp": 51,
    "inst_03.lp": 110,
    "inst_04.lp": 50,
}


def parse_instance(path):
    """Parse an ASP instance file to extract prizes and edges."""
    with open(path) as f:
        content = f.read()
    prizes = {}
    edges = {}
    for m in re.finditer(r"prize\(\s*(\d+)\s*,\s*(\d+)\s*\)", content):
        prizes[int(m.group(1))] = int(m.group(2))
    for m in re.finditer(r"edge\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", content):
        u, v, w = int(m.group(1)), int(m.group(2)), int(m.group(3))
        edges[(min(u, v), max(u, v))] = w
    return prizes, edges


def run_clingo(instance_path):
    """Run clingo with the encoding on an instance.

    Returns (opt_cost, atoms_set, optimum_found).
    """
    ctl = clingo.Control(["0"])
    ctl.load(ENCODING_PATH)
    ctl.load(instance_path)
    ctl.ground([("base", [])])

    state = {"best_atoms": set(), "best_cost": None}

    def on_model(model):
        state["best_atoms"] = set(str(a) for a in model.symbols(shown=True))
        if model.cost:
            state["best_cost"] = model.cost[0]

    result = ctl.solve(on_model=on_model)
    optimum_found = bool(result.satisfiable) and bool(result.exhausted)

    return state["best_cost"], state["best_atoms"], optimum_found


def extract_solution(atoms):
    """Extract tree nodes and edges from answer set atoms."""
    tree_nodes = set()
    tree_edges = set()
    for atom in atoms:
        m = re.match(r"in_tree\((\d+)\)", atom)
        if m:
            tree_nodes.add(int(m.group(1)))
            continue
        m = re.match(r"use_edge\((\d+),(\d+)\)", atom)
        if m:
            tree_edges.add((int(m.group(1)), int(m.group(2))))
    return tree_nodes, tree_edges


def validate_connected_tree(tree_nodes, tree_edges, instance_prizes, instance_edges):
    """Validate that the solution forms a valid connected subtree.

    Returns computed profit.
    """
    if not tree_nodes:
        assert not tree_edges, "Edges present without tree nodes"
        return 0

    # All edge endpoints must be in the tree
    for u, v in tree_edges:
        assert u in tree_nodes, f"Edge ({u},{v}): endpoint {u} not in tree"
        assert v in tree_nodes, f"Edge ({u},{v}): endpoint {v} not in tree"

    # All edges must correspond to valid instance edges
    for u, v in tree_edges:
        canon = (min(u, v), max(u, v))
        assert canon in instance_edges, f"Edge ({u},{v}) not in instance graph"

    # Connectivity check via BFS
    if len(tree_nodes) > 1:
        assert tree_edges, "Multiple tree nodes but no edges — disconnected"
        adj = {n: set() for n in tree_nodes}
        for u, v in tree_edges:
            adj[u].add(v)
            adj[v].add(u)

        start = min(tree_nodes)
        visited = set()
        queue = [start]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            for nbr in adj[node]:
                if nbr not in visited:
                    queue.append(nbr)

        assert visited == tree_nodes, (
            f"Tree not connected: BFS from {start} reached {sorted(visited)}, "
            f"but tree contains {sorted(tree_nodes)}"
        )

    # Tree structure: n-1 edges for n nodes
    if len(tree_nodes) > 0:
        assert len(tree_edges) == len(tree_nodes) - 1, (
            f"Expected {len(tree_nodes) - 1} edges for {len(tree_nodes)} nodes, "
            f"got {len(tree_edges)}"
        )

    # Compute profit independently
    total_prize = sum(instance_prizes.get(n, 0) for n in tree_nodes)
    total_cost = sum(
        instance_edges[(min(u, v), max(u, v))] for u, v in tree_edges
    )
    return total_prize - total_cost


class TestEncodingExists:
    def test_encoding_file_exists(self):
        assert os.path.exists(ENCODING_PATH), (
            f"Encoding file not found at {ENCODING_PATH}"
        )

    def test_encoding_file_not_empty(self):
        assert os.path.getsize(ENCODING_PATH) > 0, "Encoding file is empty"

    def test_encoding_contains_weak_constraints(self):
        with open(ENCODING_PATH) as f:
            content = f.read()
        assert ":~" in content, (
            "Encoding must use weak constraints (:~) for optimization"
        )


class TestOptimalSolutions:
    @pytest.mark.parametrize(
        "instance_name,expected_profit", list(EXPECTED_PROFITS.items())
    )
    def test_optimum_found(self, instance_name, expected_profit):
        """Verify clingo proves optimality."""
        instance_path = os.path.join(INSTANCES_DIR, instance_name)
        _, _, optimum_found = run_clingo(instance_path)
        assert optimum_found, (
            f"{instance_name}: clingo did not prove optimum"
        )

    @pytest.mark.parametrize(
        "instance_name,expected_profit", list(EXPECTED_PROFITS.items())
    )
    def test_optimal_profit_value(self, instance_name, expected_profit):
        """Verify the optimal profit matches the expected value."""
        instance_path = os.path.join(INSTANCES_DIR, instance_name)
        opt_cost, _, _ = run_clingo(instance_path)

        assert opt_cost is not None, (
            f"{instance_name}: could not obtain optimization cost"
        )
        profit = -opt_cost
        assert profit == expected_profit, (
            f"{instance_name}: expected profit {expected_profit}, got {profit}"
        )


class TestSolutionValidity:
    @pytest.mark.parametrize("instance_name", list(EXPECTED_PROFITS.keys()))
    def test_valid_connected_tree(self, instance_name):
        """Verify the answer set is a valid connected subtree."""
        instance_path = os.path.join(INSTANCES_DIR, instance_name)
        prizes, edges = parse_instance(instance_path)

        _, atoms, _ = run_clingo(instance_path)
        assert atoms, f"{instance_name}: no answer set atoms found"

        tree_nodes, tree_edges = extract_solution(atoms)
        validate_connected_tree(tree_nodes, tree_edges, prizes, edges)

    @pytest.mark.parametrize(
        "instance_name,expected_profit", list(EXPECTED_PROFITS.items())
    )
    def test_profit_consistency(self, instance_name, expected_profit):
        """Verify independently computed profit matches clingo's report."""
        instance_path = os.path.join(INSTANCES_DIR, instance_name)
        prizes, edges = parse_instance(instance_path)

        opt_cost, atoms, _ = run_clingo(instance_path)
        tree_nodes, tree_edges = extract_solution(atoms)

        computed_profit = validate_connected_tree(
            tree_nodes, tree_edges, prizes, edges
        )
        assert computed_profit == expected_profit, (
            f"{instance_name}: computed profit {computed_profit} != "
            f"expected {expected_profit}"
        )
        if opt_cost is not None:
            assert computed_profit == -opt_cost, (
                f"{instance_name}: computed profit {computed_profit} != "
                f"reported optimization {-opt_cost}"
            )
