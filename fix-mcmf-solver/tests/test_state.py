
import sys
import os
import json
import subprocess
import sqlite3
import pytest

sys.path.insert(0, '/app/solvers')


class TestPythonMCMFCorrectness:
    """Verify that mcmf.py has been fixed and produces correct results."""

    def test_chain_graph(self):
        """Simple chain: S -> A -> T. Tests basic augmentation."""
        from mcmf import MinCostMaxFlow
        solver = MinCostMaxFlow(3)
        solver.add_edge(0, 1, 5, 2)
        solver.add_edge(1, 2, 3, 3)
        flow, cost = solver.solve(0, 2)
        assert flow == 3, f"Expected flow=3, got {flow}"
        assert cost == 15, f"Expected cost=15, got {cost}"

    def test_diamond_graph(self):
        """Diamond with cross edge: tests multiple augmenting paths and
        reverse-edge traversal for flow rerouting."""
        from mcmf import MinCostMaxFlow
        solver = MinCostMaxFlow(4)
        solver.add_edge(0, 1, 3, 1)
        solver.add_edge(0, 2, 2, 4)
        solver.add_edge(1, 3, 2, 3)
        solver.add_edge(2, 3, 3, 1)
        solver.add_edge(1, 2, 2, 1)
        flow, cost = solver.solve(0, 3)
        assert flow == 5, f"Expected flow=5, got {flow}"
        assert cost == 21, f"Expected cost=21, got {cost}"

    def test_reverse_edge_costs(self):
        """Graph where optimal flow requires undoing initial flow via reverse
        edges, which only works if reverse edge costs are correctly negated."""
        from mcmf import MinCostMaxFlow
        solver = MinCostMaxFlow(4)
        solver.add_edge(0, 1, 1, 1)
        solver.add_edge(0, 2, 1, 100)
        solver.add_edge(1, 2, 1, 1)
        solver.add_edge(1, 3, 1, 100)
        solver.add_edge(2, 3, 1, 1)
        flow, cost = solver.solve(0, 3)
        assert flow == 2, f"Expected flow=2, got {flow}"
        assert cost == 202, f"Expected cost=202, got {cost}"


class TestCppSolver:
    """Verify C++ MCMF binary compiles and produces correct results."""

    def test_binary_exists(self):
        assert os.path.isfile('/app/solvers/mcmf'), \
            "C++ binary /app/solvers/mcmf not found"
        assert os.access('/app/solvers/mcmf', os.X_OK), \
            "C++ binary /app/solvers/mcmf is not executable"

    def test_cpp_chain_graph(self):
        """Same chain graph as Python test: 3 nodes, 2 edges, s=0, t=2."""
        input_data = "3 2 0 2\n0 1 5 2\n1 2 3 3\n"
        result = subprocess.run(
            ['/app/solvers/mcmf'], input=input_data,
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"C++ solver failed: {result.stderr}"
        parts = result.stdout.strip().split()
        assert len(parts) >= 2, f"Unexpected output: {result.stdout}"
        assert int(parts[0]) == 3, f"Expected flow=3, got {parts[0]}"
        assert int(parts[1]) == 15, f"Expected cost=15, got {parts[1]}"

    def test_cpp_diamond_graph(self):
        """Diamond graph: 4 nodes, 5 edges, s=0, t=3."""
        input_data = "4 5 0 3\n0 1 3 1\n0 2 2 4\n1 3 2 3\n2 3 3 1\n1 2 2 1\n"
        result = subprocess.run(
            ['/app/solvers/mcmf'], input=input_data,
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"C++ solver failed: {result.stderr}"
        parts = result.stdout.strip().split()
        assert int(parts[0]) == 5, f"Expected flow=5, got {parts[0]}"
        assert int(parts[1]) == 21, f"Expected cost=21, got {parts[1]}"


class TestInstanceSummary:
    """Verify jq-generated instance metadata."""

    def test_summary_exists(self):
        assert os.path.isfile('/app/instance_summary.json'), \
            "instance_summary.json not found"

    def test_summary_instance_1(self):
        with open('/app/instance_summary.json') as f:
            data = json.load(f)
        by_name = {d['name']: d for d in data}
        i = by_name['instance_1']
        assert i['num_sources'] == 2
        assert i['num_sinks'] == 2
        assert i['num_hubs'] == 0
        assert i['num_edges'] == 4
        assert i['total_supply'] == 9
        assert i['total_demand'] == 9

    def test_summary_instance_2(self):
        with open('/app/instance_summary.json') as f:
            data = json.load(f)
        by_name = {d['name']: d for d in data}
        i = by_name['instance_2']
        assert i['num_sources'] == 2
        assert i['num_sinks'] == 3
        assert i['num_hubs'] == 1
        assert i['num_edges'] == 7
        assert i['total_supply'] == 14
        assert i['total_demand'] == 14

    def test_summary_instance_3(self):
        with open('/app/instance_summary.json') as f:
            data = json.load(f)
        by_name = {d['name']: d for d in data}
        i = by_name['instance_3']
        assert i['num_sources'] == 2
        assert i['num_sinks'] == 2
        assert i['num_hubs'] == 0
        assert i['num_edges'] == 4
        assert i['total_supply'] == 8
        assert i['total_demand'] == 10


class TestOptimalResults:
    """Verify that optimal solutions are computed correctly."""

    def test_instance_1_result(self):
        path = '/app/results/instance_1.txt'
        assert os.path.exists(path), f"Result file {path} not found"
        with open(path) as f:
            parts = f.read().strip().split()
        assert int(parts[0]) == 9, f"Expected max_flow=9, got {parts[0]}"
        assert int(parts[1]) == 18, f"Expected min_cost=18, got {parts[1]}"

    def test_instance_2_result(self):
        path = '/app/results/instance_2.txt'
        assert os.path.exists(path), f"Result file {path} not found"
        with open(path) as f:
            parts = f.read().strip().split()
        assert int(parts[0]) == 14, f"Expected max_flow=14, got {parts[0]}"
        assert int(parts[1]) == 64, f"Expected min_cost=64, got {parts[1]}"

    def test_instance_3_result(self):
        path = '/app/results/instance_3.txt'
        assert os.path.exists(path), f"Result file {path} not found"
        with open(path) as f:
            parts = f.read().strip().split()
        assert int(parts[0]) == 8, f"Expected max_flow=8, got {parts[0]}"
        assert int(parts[1]) == 20, f"Expected min_cost=20, got {parts[1]}"


class TestEvaluations:
    """Verify proposed solution evaluations are correct."""

    def test_eval_instance_1_suboptimal(self):
        """Instance 1 proposed: feasible but suboptimal (cost 25 vs optimal 18)."""
        path = '/app/evaluations/instance_1.json'
        assert os.path.exists(path), f"Evaluation file {path} not found"
        with open(path) as f:
            data = json.load(f)
        assert data['feasible'] is True
        assert data['is_optimal'] is False
        assert data['cost_gap'] == 7
        assert data['optimal_flow'] == 9
        assert data['optimal_cost'] == 18
        assert data['proposed_flow'] == 9
        assert data['proposed_cost'] == 25

    def test_eval_instance_2_infeasible(self):
        """Instance 2 proposed: infeasible (hub throughput 9 exceeds capacity 7)."""
        path = '/app/evaluations/instance_2.json'
        assert os.path.exists(path), f"Evaluation file {path} not found"
        with open(path) as f:
            data = json.load(f)
        assert data['feasible'] is False
        assert data['is_optimal'] is False
        assert data['cost_gap'] == 0
        assert data['proposed_flow'] == 12
        assert data['proposed_cost'] == 47

    def test_eval_instance_3_optimal(self):
        """Instance 3 proposed: optimal (matches min cost exactly)."""
        path = '/app/evaluations/instance_3.json'
        assert os.path.exists(path), f"Evaluation file {path} not found"
        with open(path) as f:
            data = json.load(f)
        assert data['feasible'] is True
        assert data['is_optimal'] is True
        assert data['cost_gap'] == 0
        assert data['optimal_flow'] == 8
        assert data['optimal_cost'] == 20
        assert data['proposed_flow'] == 8
        assert data['proposed_cost'] == 20


class TestSQLiteDatabase:
    """Verify SQLite database is correctly populated."""

    def test_db_exists(self):
        assert os.path.isfile('/app/results.db'), "results.db not found"

    def test_instances_table(self):
        conn = sqlite3.connect('/app/results.db')
        cur = conn.execute(
            "SELECT name, num_sources, num_sinks, num_hubs, num_edges, "
            "total_supply, total_demand FROM instances ORDER BY name"
        )
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 3
        assert rows[0] == ('instance_1', 2, 2, 0, 4, 9, 9)
        assert rows[1] == ('instance_2', 2, 3, 1, 7, 14, 14)
        assert rows[2] == ('instance_3', 2, 2, 0, 4, 8, 10)

    def test_optimal_solutions_table(self):
        conn = sqlite3.connect('/app/results.db')
        cur = conn.execute(
            "SELECT name, max_flow, min_cost FROM optimal_solutions ORDER BY name"
        )
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 3
        assert rows[0] == ('instance_1', 9, 18)
        assert rows[1] == ('instance_2', 14, 64)
        assert rows[2] == ('instance_3', 8, 20)

    def test_evaluations_table(self):
        conn = sqlite3.connect('/app/results.db')
        cur = conn.execute(
            "SELECT name, proposed_flow, proposed_cost, is_feasible, "
            "is_optimal, cost_gap FROM evaluations ORDER BY name"
        )
        rows = cur.fetchall()
        conn.close()
        assert len(rows) == 3
        assert rows[0] == ('instance_1', 9, 25, 1, 0, 7)
        assert rows[1] == ('instance_2', 12, 47, 0, 0, 0)
        assert rows[2] == ('instance_3', 8, 20, 1, 1, 0)
