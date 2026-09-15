"""
Tests for the cost-based join order optimizer.

Verifies that the optimizer produces optimal join plans with correct
costs and cardinalities for 8 queries of increasing complexity.

"""

import json
import math
import sys
import pytest

sys.path.insert(0, "/app")


def load_stats():
    with open("/opt/task_data/stats.json") as f:
        return json.load(f)


def load_queries():
    with open("/opt/task_data/queries.json") as f:
        return json.load(f)["queries"]


@pytest.fixture(scope="module")
def optimizer_module():
    """Import the agent's optimizer module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("optimizer", "/app/optimizer.py")
    if spec is None:
        pytest.fail("Could not find /app/optimizer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def stats():
    return load_stats()


@pytest.fixture(scope="module")
def queries():
    return load_queries()


# Expected results computed from reference implementation.
# Format: (query_id, expected_total_cost, expected_estimated_rows)
EXPECTED = [
    ("q1", 11000.0, 10000.0),
    ("q2", 121000.0, 100000.0),
    ("q3", 12000.0, 5000.0),
    ("q4", 117000.0, 50000.0),
    ("q5", 71000.0, 50000.0),
    ("q6", 66500.0, 25000.0),
    ("q7", 105000.0, 10000.0),
    ("q8", 102600.0, 4000.0),
]


def collect_tables(plan):
    """Collect all table names from a plan tree."""
    tables = set()
    if "table" in plan and plan["table"] is not None:
        tables.add(plan["table"])
    if "left" in plan and plan["left"] is not None:
        tables.update(collect_tables(plan["left"]))
    if "right" in plan and plan["right"] is not None:
        tables.update(collect_tables(plan["right"]))
    return tables


def count_joins(plan):
    """Count the number of join nodes in the plan."""
    if "table" in plan and plan["table"] is not None:
        return 0
    count = 1
    if "left" in plan and plan["left"] is not None:
        count += count_joins(plan["left"])
    if "right" in plan and plan["right"] is not None:
        count += count_joins(plan["right"])
    return count


def validate_plan_structure(plan, expected_tables):
    """Validate that the plan is a well-formed binary tree covering all tables."""
    tables_in_plan = collect_tables(plan)
    assert tables_in_plan == set(expected_tables), (
        f"Plan tables {tables_in_plan} != expected {set(expected_tables)}"
    )

    n_tables = len(expected_tables)
    n_joins = count_joins(plan)
    assert n_joins == n_tables - 1, (
        f"Expected {n_tables - 1} joins for {n_tables} tables, got {n_joins}"
    )

    assert "estimated_rows" in plan, "Root plan node missing 'estimated_rows'"
    assert "total_cost" in plan, "Root plan node missing 'total_cost'"
    assert plan["estimated_rows"] > 0, "Root estimated_rows must be positive"
    assert plan["total_cost"] >= 0, "Root total_cost must be non-negative"


TOLERANCE = 0.01  # 1% relative tolerance


@pytest.mark.parametrize("qid,expected_cost,expected_rows", EXPECTED)
def test_optimizer_cost(
    optimizer_module, stats, queries, qid, expected_cost, expected_rows
):
    """Test that the optimizer produces the correct optimal cost."""
    query = next(q for q in queries if q["id"] == qid)
    plan = optimizer_module.optimize(stats, query)

    # Structural validation
    validate_plan_structure(plan, query["tables"])

    # Cost validation
    actual_cost = plan["total_cost"]
    if expected_cost == 0:
        assert actual_cost == 0, f"[{qid}] Expected cost 0, got {actual_cost}"
    else:
        rel_error = abs(actual_cost - expected_cost) / expected_cost
        assert rel_error < TOLERANCE, (
            f"[{qid}] Cost mismatch: expected {expected_cost:.2f}, "
            f"got {actual_cost:.2f} (rel error {rel_error:.4f})"
        )


@pytest.mark.parametrize("qid,expected_cost,expected_rows", EXPECTED)
def test_optimizer_cardinality(
    optimizer_module, stats, queries, qid, expected_cost, expected_rows
):
    """Test that the optimizer produces the correct output cardinality."""
    query = next(q for q in queries if q["id"] == qid)
    plan = optimizer_module.optimize(stats, query)

    actual_rows = plan["estimated_rows"]
    if expected_rows == 0:
        assert actual_rows == 0, f"[{qid}] Expected rows 0, got {actual_rows}"
    else:
        rel_error = abs(actual_rows - expected_rows) / expected_rows
        assert rel_error < TOLERANCE, (
            f"[{qid}] Cardinality mismatch: expected {expected_rows:.2f}, "
            f"got {actual_rows:.2f} (rel error {rel_error:.4f})"
        )


def test_optimizer_q1_trivial(optimizer_module, stats, queries):
    """Q1 has only 2 tables - verify the plan structure is minimal."""
    query = next(q for q in queries if q["id"] == "q1")
    plan = optimizer_module.optimize(stats, query)
    assert "left" in plan and "right" in plan, "Q1 must be a single join node"
    left = plan["left"]
    right = plan["right"]
    left_table = left.get("table")
    right_table = right.get("table")
    assert {left_table, right_table} == {"R", "S"}, (
        f"Q1 leaf tables must be R and S, got {left_table} and {right_table}"
    )


def test_optimizer_consistency(optimizer_module, stats, queries):
    """Verify that node_cost + children costs = total_cost for all queries."""
    for query in queries:
        plan = optimizer_module.optimize(stats, query)
        _check_cost_consistency(plan, query["id"])


def _check_cost_consistency(plan, qid):
    """Recursively verify cost consistency in the plan tree."""
    if "table" in plan and plan["table"] is not None:
        assert plan["total_cost"] == 0.0, (
            f"[{qid}] Leaf node {plan['table']} should have total_cost=0"
        )
        return

    left = plan["left"]
    right = plan["right"]
    _check_cost_consistency(left, qid)
    _check_cost_consistency(right, qid)

    node_cost = plan.get("node_cost", 0)
    expected_total = left["total_cost"] + right["total_cost"] + node_cost
    actual_total = plan["total_cost"]
    if expected_total > 0:
        rel_error = abs(actual_total - expected_total) / expected_total
        assert rel_error < 0.001, (
            f"[{qid}] Cost inconsistency: node_cost={node_cost}, "
            f"left_total={left['total_cost']}, right_total={right['total_cost']}, "
            f"expected_total={expected_total}, actual_total={actual_total}"
        )


def test_optimizer_node_cost_formula(optimizer_module, stats, queries):
    """Verify that each join node's cost equals left_rows + right_rows."""
    for query in queries:
        plan = optimizer_module.optimize(stats, query)
        _check_node_cost_formula(plan, query["id"])


def _check_node_cost_formula(plan, qid):
    if "table" in plan and plan["table"] is not None:
        return

    left = plan["left"]
    right = plan["right"]
    _check_node_cost_formula(left, qid)
    _check_node_cost_formula(right, qid)

    expected_node_cost = left["estimated_rows"] + right["estimated_rows"]
    actual_node_cost = plan.get("node_cost", 0)
    if expected_node_cost > 0:
        rel_error = abs(actual_node_cost - expected_node_cost) / expected_node_cost
        assert rel_error < 0.001, (
            f"[{qid}] node_cost should be left_rows + right_rows = "
            f"{left['estimated_rows']} + {right['estimated_rows']} = "
            f"{expected_node_cost}, got {actual_node_cost}"
        )


def test_optimizer_filter_applied_q5(optimizer_module, stats, queries):
    """Q5 has filter T.t_val >= 500. Verify T's leaf rows are ~50000."""
    query = next(q for q in queries if q["id"] == "q5")
    plan = optimizer_module.optimize(stats, query)
    t_rows = _find_table_rows(plan, "T")
    assert t_rows is not None, "Table T not found in plan"
    rel_error = abs(t_rows - 50000.0) / 50000.0
    assert rel_error < TOLERANCE, (
        f"T should have ~50000 rows after filter t_val >= 500, got {t_rows}"
    )


def test_optimizer_filter_applied_q6(optimizer_module, stats, queries):
    """Q6 has filter R.r_val >= 50 and T.t_val >= 500."""
    query = next(q for q in queries if q["id"] == "q6")
    plan = optimizer_module.optimize(stats, query)

    r_rows = _find_table_rows(plan, "R")
    assert r_rows is not None, "Table R not found in plan"
    rel_error = abs(r_rows - 500.0) / 500.0
    assert rel_error < TOLERANCE, (
        f"R should have ~500 rows after filter r_val >= 50, got {r_rows}"
    )

    t_rows = _find_table_rows(plan, "T")
    assert t_rows is not None, "Table T not found in plan"
    rel_error = abs(t_rows - 50000.0) / 50000.0
    assert rel_error < TOLERANCE, (
        f"T should have ~50000 rows after filter t_val >= 500, got {t_rows}"
    )


def test_optimizer_filter_applied_q8(optimizer_module, stats, queries):
    """Q8 has filter R.r_val >= 80 and S.s_val < 200."""
    query = next(q for q in queries if q["id"] == "q8")
    plan = optimizer_module.optimize(stats, query)

    r_rows = _find_table_rows(plan, "R")
    assert r_rows is not None, "Table R not found in plan"
    rel_error = abs(r_rows - 200.0) / 200.0
    assert rel_error < TOLERANCE, (
        f"R should have ~200 rows after filter r_val >= 80, got {r_rows}"
    )

    s_rows = _find_table_rows(plan, "S")
    assert s_rows is not None, "Table S not found in plan"
    rel_error = abs(s_rows - 2000.0) / 2000.0
    assert rel_error < TOLERANCE, (
        f"S should have ~2000 rows after filter s_val < 200, got {s_rows}"
    )


def _find_table_rows(plan, table_name):
    """Find the estimated_rows for a specific table leaf in the plan."""
    if "table" in plan and plan["table"] == table_name:
        return plan["estimated_rows"]
    if "left" in plan and plan["left"] is not None:
        result = _find_table_rows(plan["left"], table_name)
        if result is not None:
            return result
    if "right" in plan and plan["right"] is not None:
        result = _find_table_rows(plan["right"], table_name)
        if result is not None:
            return result
    return None
