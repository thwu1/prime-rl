#!/usr/bin/env python3
"""Tests for the kernel schedule compiler with transpose-aware optimization.

Verifies that the optimizer produces valid, property-correct, cost-correct,
and globally optimal evaluation plans for matrix chain products with
structural properties and transposed operands.
"""


import json
import os
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Load reference data from SQLite database (independent verification)
# ---------------------------------------------------------------------------

def _load_propagation_rules():
    conn = sqlite3.connect("/app/input/benchmarks.db")
    c = conn.cursor()
    c.execute("SELECT left_prop, right_prop, result_prop FROM propagation_rules")
    rules = {(lp, rp): res for lp, rp, res in c.fetchall()}
    conn.close()
    return rules


def _load_transpose_map():
    conn = sqlite3.connect("/app/input/benchmarks.db")
    c = conn.cursor()
    c.execute("SELECT original_prop, transposed_prop FROM transpose_properties")
    tmap = {o: t for o, t in c.fetchall()}
    conn.close()
    return tmap


PROP_RULES = _load_propagation_rules()
TRANS_MAP = _load_transpose_map()


def propagate_properties(left_prop, right_prop):
    """Determine result property of C = A * B using DB rules."""
    return PROP_RULES.get((left_prop, right_prop), "general")


def is_structured(prop):
    return prop in ("symmetric", "upper_triangular", "lower_triangular")


def compute_cost(left_prop, right_prop, m, k, n):
    """Compute FLOP cost for C = A(m x k) * B(k x n) given properties.
    The cost hierarchy mirrors BLAS kernel selection:
      diagonal x diagonal -> element-wise (k FLOPs)
      diagonal x any      -> row/col scaling (m*n FLOPs)
      any x diagonal       -> row/col scaling (m*n FLOPs)
      structured present   -> exploits structure (m*n*k FLOPs)
      general x general    -> standard DGEMM (2*m*n*k FLOPs)
    """
    if left_prop == "diagonal" and right_prop == "diagonal":
        return k
    if left_prop == "diagonal":
        return m * n
    if right_prop == "diagonal":
        return m * n
    if is_structured(left_prop) or is_structured(right_prop):
        return m * n * k
    return 2 * m * n * k


def resolve_operands(chain):
    """Resolve transposed operands to effective dimensions and properties."""
    effective = []
    for op in chain["operands"]:
        mat = chain["matrices"][op["matrix"]]
        if op.get("transpose", False):
            rows, cols = mat["cols"], mat["rows"]
            prop = TRANS_MAP.get(mat["property"], mat["property"])
        else:
            rows, cols = mat["rows"], mat["cols"]
            prop = mat["property"]
        effective.append({
            "name": op["matrix"],
            "rows": rows,
            "cols": cols,
            "property": prop,
        })
    return effective


# ---------------------------------------------------------------------------
# Pre-computed optimal costs (verified by independent DP computation)
# ---------------------------------------------------------------------------

EXPECTED_OPTIMAL = {
    "basic": 9000,
    "diagonal_propagation": 2001000,
    "transpose_dims": 33000000,
    "diagonal_transpose": 500500,
    "triangular_transpose": 36060000,
    "complex_mixed": 96160000,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def input_data():
    with open("/app/input/chains.json") as f:
        return json.load(f)


@pytest.fixture
def output_data():
    output_path = "/app/output/plans.json"
    assert os.path.exists(output_path), (
        f"Output file {output_path} does not exist. "
        "The optimizer must write results to /app/output/plans.json."
    )
    with open(output_path) as f:
        data = json.load(f)
    return data


@pytest.fixture
def resolved_chains(input_data):
    """Pre-resolve all chains' transposes for test use."""
    resolved = {}
    for chain_id, chain in input_data["chains"].items():
        resolved[chain_id] = resolve_operands(chain)
    return resolved


# ---------------------------------------------------------------------------
# Test: Output format
# ---------------------------------------------------------------------------

class TestOutputFormat:
    def test_plans_key_exists(self, output_data):
        assert "plans" in output_data, (
            "Output JSON must contain a top-level 'plans' key"
        )

    def test_all_chains_present(self, output_data, input_data):
        for chain_id in input_data["chains"]:
            assert chain_id in output_data["plans"], (
                f"Missing plan for chain '{chain_id}'"
            )

    def test_steps_and_total_cost_present(self, output_data):
        for chain_id, plan in output_data["plans"].items():
            assert "steps" in plan, f"Plan '{chain_id}' missing 'steps' key"
            assert "total_cost" in plan, f"Plan '{chain_id}' missing 'total_cost'"
            assert isinstance(plan["steps"], list)
            assert isinstance(plan["total_cost"], (int, float))

    def test_step_fields_present(self, output_data):
        required_fields = {"left", "right", "result", "result_properties", "cost"}
        for chain_id, plan in output_data["plans"].items():
            for i, step in enumerate(plan["steps"]):
                for field in required_fields:
                    assert field in step, (
                        f"Step {i} in chain '{chain_id}' missing field '{field}'"
                    )


# ---------------------------------------------------------------------------
# Test: Dimensional consistency (transpose-aware)
# ---------------------------------------------------------------------------

class TestDimensionConsistency:
    def test_dimensions_match(self, output_data, resolved_chains):
        """Inner dimensions must match for every multiplication."""
        for chain_id, matrices in resolved_chains.items():
            plan = output_data["plans"][chain_id]
            dims = {m["name"]: (m["rows"], m["cols"]) for m in matrices}

            for i, step in enumerate(plan["steps"]):
                assert step["left"] in dims, (
                    f"Step {i} in '{chain_id}': unknown operand '{step['left']}'"
                )
                assert step["right"] in dims, (
                    f"Step {i} in '{chain_id}': unknown operand '{step['right']}'"
                )
                lr, lc = dims[step["left"]]
                rr, rc = dims[step["right"]]
                assert lc == rr, (
                    f"Dimension mismatch at step {i} in '{chain_id}': "
                    f"left '{step['left']}' is {lr}x{lc}, "
                    f"right '{step['right']}' is {rr}x{rc}"
                )
                dims[step["result"]] = (lr, rc)

    def test_all_matrices_consumed(self, output_data, resolved_chains):
        """Every original matrix must appear exactly once as an operand."""
        for chain_id, matrices in resolved_chains.items():
            plan = output_data["plans"][chain_id]
            matrix_names = {m["name"] for m in matrices}
            used = set()
            for step in plan["steps"]:
                if step["left"] in matrix_names:
                    used.add(step["left"])
                if step["right"] in matrix_names:
                    used.add(step["right"])
            assert used == matrix_names, (
                f"Chain '{chain_id}': expected {matrix_names}, used {used}"
            )

    def test_correct_step_count(self, output_data, resolved_chains):
        """n matrices require exactly n-1 multiplications."""
        for chain_id, matrices in resolved_chains.items():
            plan = output_data["plans"][chain_id]
            n = len(matrices)
            assert len(plan["steps"]) == n - 1, (
                f"Chain '{chain_id}': {n} matrices need {n - 1} steps, "
                f"got {len(plan['steps'])}"
            )


# ---------------------------------------------------------------------------
# Test: Property propagation correctness
# ---------------------------------------------------------------------------

class TestPropertyPropagation:
    def test_properties_correctly_propagated(self, output_data, resolved_chains):
        """Each step's result_properties must match propagation rules."""
        for chain_id, matrices in resolved_chains.items():
            plan = output_data["plans"][chain_id]
            computed_props = {m["name"]: m["property"] for m in matrices}

            for i, step in enumerate(plan["steps"]):
                left_prop = computed_props.get(step["left"])
                right_prop = computed_props.get(step["right"])
                assert left_prop is not None, (
                    f"Step {i} in '{chain_id}': unknown property "
                    f"for '{step['left']}'"
                )
                assert right_prop is not None, (
                    f"Step {i} in '{chain_id}': unknown property "
                    f"for '{step['right']}'"
                )
                expected_prop = propagate_properties(left_prop, right_prop)
                actual_props = step["result_properties"]
                if isinstance(actual_props, list):
                    actual_prop = actual_props[0] if actual_props else "general"
                else:
                    actual_prop = actual_props
                assert actual_prop == expected_prop, (
                    f"Property propagation error at step {i} in '{chain_id}': "
                    f"{step['left']}({left_prop}) x {step['right']}({right_prop}) "
                    f"should yield '{expected_prop}', got '{actual_prop}'"
                )
                computed_props[step["result"]] = expected_prop


# ---------------------------------------------------------------------------
# Test: Cost calculation correctness
# ---------------------------------------------------------------------------

class TestCostCalculation:
    def test_step_costs_match_model(self, output_data, resolved_chains):
        """Each step's cost must match the cost model."""
        for chain_id, matrices in resolved_chains.items():
            plan = output_data["plans"][chain_id]
            computed_props = {m["name"]: m["property"] for m in matrices}
            dims = {m["name"]: (m["rows"], m["cols"]) for m in matrices}

            for i, step in enumerate(plan["steps"]):
                left_prop = computed_props[step["left"]]
                right_prop = computed_props[step["right"]]
                m, k = dims[step["left"]]
                _, n = dims[step["right"]]
                expected_cost = compute_cost(left_prop, right_prop, m, k, n)
                assert step["cost"] == expected_cost, (
                    f"Cost error at step {i} in '{chain_id}': "
                    f"{step['left']}({left_prop}, {m}x{k}) x "
                    f"{step['right']}({right_prop}, {k}x{n}) "
                    f"should cost {expected_cost}, got {step['cost']}"
                )
                computed_props[step["result"]] = propagate_properties(
                    left_prop, right_prop
                )
                dims[step["result"]] = (m, n)

    def test_total_cost_is_sum_of_steps(self, output_data):
        """total_cost must equal the sum of all step costs."""
        for chain_id, plan in output_data["plans"].items():
            step_sum = sum(step["cost"] for step in plan["steps"])
            assert plan["total_cost"] == step_sum, (
                f"Chain '{chain_id}': total_cost={plan['total_cost']} but "
                f"sum of step costs={step_sum}"
            )


# ---------------------------------------------------------------------------
# Test: Optimality
# ---------------------------------------------------------------------------

class TestOptimality:
    @pytest.mark.parametrize(
        "chain_id,expected_cost", list(EXPECTED_OPTIMAL.items())
    )
    def test_achieves_optimal_cost(self, chain_id, expected_cost, output_data):
        """The total cost must match the known global optimum."""
        plan = output_data["plans"][chain_id]
        assert plan["total_cost"] == expected_cost, (
            f"Chain '{chain_id}': expected optimal cost {expected_cost}, "
            f"got {plan['total_cost']}"
        )


# ---------------------------------------------------------------------------
# Test: Ordering validity
# ---------------------------------------------------------------------------

class TestOrderingValidity:
    def test_operands_available_before_use(self, output_data, resolved_chains):
        """Each step's operands must be available."""
        for chain_id, matrices in resolved_chains.items():
            plan = output_data["plans"][chain_id]
            available = {m["name"] for m in matrices}
            for i, step in enumerate(plan["steps"]):
                assert step["left"] in available, (
                    f"Step {i} in '{chain_id}': '{step['left']}' not available"
                )
                assert step["right"] in available, (
                    f"Step {i} in '{chain_id}': '{step['right']}' not available"
                )
                available.add(step["result"])

    def test_preserves_chain_order(self, output_data, resolved_chains):
        """Only contiguous subchains may be multiplied."""
        for chain_id, matrices in resolved_chains.items():
            plan = output_data["plans"][chain_id]
            matrix_names = [m["name"] for m in matrices]
            ranges = {name: (idx, idx)
                      for idx, name in enumerate(matrix_names)}

            for step_idx, step in enumerate(plan["steps"]):
                left_range = ranges[step["left"]]
                right_range = ranges[step["right"]]
                assert left_range[1] + 1 == right_range[0], (
                    f"Non-contiguous multiplication at step {step_idx} "
                    f"in '{chain_id}': left covers [{left_range[0]},"
                    f"{left_range[1]}], right covers [{right_range[0]},"
                    f"{right_range[1]}]"
                )
                ranges[step["result"]] = (left_range[0], right_range[1])

    def test_final_result_covers_full_chain(self, output_data, resolved_chains):
        """The last step's result must cover the entire original chain."""
        for chain_id, matrices in resolved_chains.items():
            plan = output_data["plans"][chain_id]
            n = len(matrices)
            matrix_names = [m["name"] for m in matrices]
            ranges = {name: (idx, idx)
                      for idx, name in enumerate(matrix_names)}
            for step in plan["steps"]:
                lr = ranges.get(step["left"], (0, 0))
                rr = ranges.get(step["right"], (0, 0))
                ranges[step["result"]] = (lr[0], rr[1])
            last_result = plan["steps"][-1]["result"]
            final_range = ranges[last_result]
            assert final_range == (0, n - 1), (
                f"Chain '{chain_id}': final result covers {final_range}, "
                f"expected (0, {n - 1})"
            )


# ---------------------------------------------------------------------------
# Test: Database accessibility and structure
# ---------------------------------------------------------------------------

class TestDatabaseStructure:
    def test_benchmarks_db_exists(self):
        assert os.path.exists("/app/input/benchmarks.db"), (
            "benchmarks.db not found at /app/input/"
        )

    def test_db_has_required_tables(self):
        conn = sqlite3.connect("/app/input/benchmarks.db")
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in c.fetchall()}
        conn.close()
        assert "cost_measurements" in tables
        assert "propagation_rules" in tables
        assert "transpose_properties" in tables

    def test_cost_measurements_has_data(self):
        conn = sqlite3.connect("/app/input/benchmarks.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM cost_measurements")
        count = c.fetchone()[0]
        conn.close()
        assert count > 0, "cost_measurements table is empty"

    def test_propagation_rules_has_data(self):
        conn = sqlite3.connect("/app/input/benchmarks.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM propagation_rules")
        count = c.fetchone()[0]
        conn.close()
        assert count > 0, "propagation_rules table is empty"

    def test_transpose_properties_has_data(self):
        conn = sqlite3.connect("/app/input/benchmarks.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM transpose_properties")
        count = c.fetchone()[0]
        conn.close()
        assert count > 0, "transpose_properties table is empty"
