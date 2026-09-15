"""
Tests for Min-Cost Maximum Flow via LP Formulation.
Verifies correctness of results AND that GLPK/GMPL was actually used.
"""

import json
import os
import glob
import pytest
from collections import defaultdict

NETWORK_FILE = "/app/network_data.json"
RESULTS_FILE = "/app/results.json"
ARTIFACTS_DIR = "/app/lp_artifacts"

EXPECTED = {
    "simple": {"max_flow": 5, "min_cost": 15},
    "medium": {"max_flow": 7, "min_cost": 44},
    "reroute": {"max_flow": 5, "min_cost": 37},
    "supply_chain": {"max_flow": 17, "min_cost": 130},
}

ALL_CASES = list(EXPECTED.keys())


@pytest.fixture(scope="session")
def network_data():
    with open(NETWORK_FILE, "r") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def results():
    with open(RESULTS_FILE, "r") as f:
        return json.load(f)


def get_test_case(data, name):
    for tc in data["test_cases"]:
        if tc["name"] == name:
            return tc
    return None


def _check_flow_conservation(tc_result, tc_network):
    edge_flows = tc_result["edge_flows"]
    source = tc_network["source"]
    sink = tc_network["sink"]
    num_nodes = tc_network["num_nodes"]

    inflow = defaultdict(int)
    outflow = defaultdict(int)

    for key, flow in edge_flows.items():
        u, v = map(int, key.split(","))
        outflow[u] += flow
        inflow[v] += flow

    for node in range(num_nodes):
        if node == source or node == sink:
            continue
        assert inflow[node] == outflow[node], (
            f"Flow conservation violated at node {node}: "
            f"in={inflow[node]}, out={outflow[node]}"
        )


def _check_edge_capacity_constraints(tc_result, tc_network):
    edge_flows = tc_result["edge_flows"]

    edge_caps = {}
    for edge in tc_network["edges"]:
        key = f"{edge['from']},{edge['to']}"
        edge_caps[key] = edge["capacity"]

    for key, flow in edge_flows.items():
        assert flow >= 0, f"Negative flow on edge {key}: {flow}"
        assert key in edge_caps, f"Flow on non-existent edge {key}"
        assert flow <= edge_caps[key], (
            f"Edge capacity violated on {key}: flow={flow}, cap={edge_caps[key]}"
        )


def _check_node_capacity_constraints(tc_result, tc_network):
    edge_flows = tc_result["edge_flows"]
    node_caps = {int(k): v for k, v in tc_network.get("node_capacities", {}).items()}
    source = tc_network["source"]
    sink = tc_network["sink"]

    node_throughput = defaultdict(int)
    for key, flow in edge_flows.items():
        _, v = map(int, key.split(","))
        node_throughput[v] += flow

    for node, cap in node_caps.items():
        if node == source or node == sink:
            continue
        assert node_throughput[node] <= cap, (
            f"Node capacity violated at node {node}: "
            f"throughput={node_throughput[node]}, cap={cap}"
        )


def _check_cost_consistency(tc_result, tc_network):
    edge_flows = tc_result["edge_flows"]
    edge_costs = {}
    for edge in tc_network["edges"]:
        key = f"{edge['from']},{edge['to']}"
        edge_costs[key] = edge["cost"]

    computed_cost = sum(flow * edge_costs[key] for key, flow in edge_flows.items())
    assert computed_cost == tc_result["min_cost"], (
        f"Reported cost {tc_result['min_cost']} != computed cost {computed_cost}"
    )


def _check_flow_total_consistency(tc_result, tc_network):
    edge_flows = tc_result["edge_flows"]
    source = tc_network["source"]

    total_out = sum(
        flow
        for key, flow in edge_flows.items()
        if int(key.split(",")[0]) == source
    )
    assert total_out == tc_result["max_flow"], (
        f"Reported max_flow {tc_result['max_flow']} != "
        f"actual source outflow {total_out}"
    )


# ─── GLPK artifact tests ──────────────────────────────────────────────


class TestGLPKArtifacts:
    """Verify that GLPK/GMPL was actually used to solve the problem."""

    def test_artifacts_dir_exists(self):
        assert os.path.isdir(ARTIFACTS_DIR), (
            f"{ARTIFACTS_DIR} directory missing — "
            "the problem must be solved using glpsol with GMPL models"
        )

    @pytest.mark.parametrize("tc_name", ALL_CASES)
    def test_gmpl_model_files_exist(self, tc_name):
        mod_files = glob.glob(f"{ARTIFACTS_DIR}/{tc_name}*.mod")
        assert len(mod_files) >= 1, (
            f"No GMPL model file (.mod) found for test case '{tc_name}' "
            f"in {ARTIFACTS_DIR}"
        )

    @pytest.mark.parametrize("tc_name", ALL_CASES)
    def test_gmpl_model_contains_lp_constructs(self, tc_name):
        mod_files = glob.glob(f"{ARTIFACTS_DIR}/{tc_name}*.mod")
        assert mod_files, f"No .mod files for {tc_name}"
        combined = ""
        for mod_file in mod_files:
            with open(mod_file) as f:
                combined += f.read()
        assert "var " in combined or "var\n" in combined or "var\t" in combined, (
            f"GMPL model for '{tc_name}' missing variable declarations"
        )
        assert "solve" in combined, (
            f"GMPL model for '{tc_name}' missing solve statement"
        )
        has_objective = "maximize" in combined or "minimize" in combined
        assert has_objective, (
            f"GMPL model for '{tc_name}' missing objective function"
        )

    @pytest.mark.parametrize("tc_name", ALL_CASES)
    def test_solution_files_exist(self, tc_name):
        sol_files = glob.glob(f"{ARTIFACTS_DIR}/{tc_name}*.sol")
        assert len(sol_files) >= 1, (
            f"No glpsol solution file (.sol) found for test case '{tc_name}' "
            f"in {ARTIFACTS_DIR}"
        )

    @pytest.mark.parametrize("tc_name", ALL_CASES)
    def test_solution_files_nonempty(self, tc_name):
        sol_files = glob.glob(f"{ARTIFACTS_DIR}/{tc_name}*.sol")
        for sol_file in sol_files:
            size = os.path.getsize(sol_file)
            assert size > 100, (
                f"Solution file {sol_file} is suspiciously small ({size} bytes)"
            )


# ─── Format tests ───────────────────────────────────────────────────


class TestResultsFormat:
    def test_results_file_loads(self, results):
        assert results is not None

    def test_has_all_test_cases(self, results):
        assert "test_cases" in results
        names = {tc["name"] for tc in results["test_cases"]}
        assert names == set(ALL_CASES), (
            f"Expected test cases {set(ALL_CASES)}, got {names}"
        )


# ─── Per-case correctness tests ───────────────────────────────────


@pytest.mark.parametrize("tc_name", ALL_CASES)
class TestCorrectness:
    def test_max_flow(self, results, tc_name):
        tc = get_test_case(results, tc_name)
        assert tc is not None, f"Missing test case '{tc_name}'"
        assert tc["max_flow"] == EXPECTED[tc_name]["max_flow"], (
            f"max_flow for '{tc_name}': expected {EXPECTED[tc_name]['max_flow']}, "
            f"got {tc['max_flow']}"
        )

    def test_min_cost(self, results, tc_name):
        tc = get_test_case(results, tc_name)
        assert tc is not None, f"Missing test case '{tc_name}'"
        assert tc["min_cost"] == EXPECTED[tc_name]["min_cost"], (
            f"min_cost for '{tc_name}': expected {EXPECTED[tc_name]['min_cost']}, "
            f"got {tc['min_cost']}"
        )

    def test_flow_conservation(self, results, network_data, tc_name):
        tc_r = get_test_case(results, tc_name)
        tc_n = get_test_case(network_data, tc_name)
        _check_flow_conservation(tc_r, tc_n)

    def test_edge_capacity(self, results, network_data, tc_name):
        tc_r = get_test_case(results, tc_name)
        tc_n = get_test_case(network_data, tc_name)
        _check_edge_capacity_constraints(tc_r, tc_n)

    def test_node_capacity(self, results, network_data, tc_name):
        tc_r = get_test_case(results, tc_name)
        tc_n = get_test_case(network_data, tc_name)
        _check_node_capacity_constraints(tc_r, tc_n)

    def test_cost_consistency(self, results, network_data, tc_name):
        tc_r = get_test_case(results, tc_name)
        tc_n = get_test_case(network_data, tc_name)
        _check_cost_consistency(tc_r, tc_n)

    def test_flow_total_consistency(self, results, network_data, tc_name):
        tc_r = get_test_case(results, tc_name)
        tc_n = get_test_case(network_data, tc_name)
        _check_flow_total_consistency(tc_r, tc_n)
