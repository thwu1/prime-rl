"""
Tests for the multi-operator cost-based query optimizer.

Verifies optimal plans for 5 star-schema queries, checking costs, cardinalities,
operator selection (hash join vs sort-merge join, seq scan vs index scan),
filter pushdown, and graphviz DOT/PNG output.

"""

import json
import os
import subprocess
import pytest


# Analytically computed expected values from the cost model
EXPECTED = {
    "q1": {"total_cost": 302500.0, "root_card": 10000000},
    "q2": {"total_cost": 298138.0, "root_card": 200000},
    "q3": {"total_cost": 301413.0, "root_card": 200000},
    "q4": {"total_cost": 225091.0, "root_card": 10000000},
    "q5": {"total_cost": 256580.275, "root_card": 20000},
}

COST_TOLERANCE = 0.02
CARD_TOLERANCE = 0.01


def _get_children(plan):
    if "children" in plan:
        return plan["children"]
    children = []
    for key in ("left", "probe", "probe_side"):
        if key in plan:
            children.append(plan[key])
            break
    for key in ("right", "build", "build_side"):
        if key in plan:
            children.append(plan[key])
            break
    if "child" in plan and not children:
        children.append(plan["child"])
    return children


def _get_card(plan):
    for key in ("est_card", "est_cardinality", "cardinality", "card"):
        if key in plan:
            return plan[key]
    return None


def _get_cost(plan):
    for key in ("est_cost", "cost", "operator_cost", "node_cost"):
        if key in plan:
            return plan[key]
    return 0


def _get_op(plan):
    for key in ("op", "operator", "type", "node_type"):
        if key in plan:
            return plan[key]
    return None


def _compute_total_cost(plan):
    cost = _get_cost(plan)
    for child in _get_children(plan):
        cost += _compute_total_cost(child)
    return cost


def _get_leaf_tables(plan):
    op = _get_op(plan)
    if op in ("SeqScan", "Scan", "TableScan", "SequentialScan", "IndexScan"):
        table = plan.get("table", plan.get("table_name", ""))
        return {table} if table else set()
    tables = set()
    for child in _get_children(plan):
        tables |= _get_leaf_tables(child)
    return tables


def _has_join_descendant(plan):
    for child in _get_children(plan):
        op = _get_op(child)
        if op in ("HashJoin", "SortMergeJoin", "Join", "hash_join", "merge_join"):
            return True
        if _has_join_descendant(child):
            return True
    return False


def _check_filter_pushdown(plan):
    op = _get_op(plan)
    if op in ("Filter", "filter", "Predicate"):
        assert not _has_join_descendant(plan), (
            f"Filter not pushed down: filter node has a join descendant"
        )
    for child in _get_children(plan):
        _check_filter_pushdown(child)


def _find_deepest_join(plan, depth=0):
    best_node = None
    best_depth = -1
    op = _get_op(plan)
    if op in ("HashJoin", "SortMergeJoin", "Join", "hash_join", "merge_join"):
        best_node = plan
        best_depth = depth
    for child in _get_children(plan):
        node, d = _find_deepest_join(child, depth + 1)
        if node is not None and d > best_depth:
            best_node = node
            best_depth = d
    return best_node, best_depth


def _collect_join_ops(plan):
    """Collect all join operator types in the plan."""
    ops = []
    op = _get_op(plan)
    if op in ("HashJoin", "SortMergeJoin", "Join", "hash_join", "merge_join",
              "sort_merge_join", "MergeJoin"):
        ops.append(op)
    for child in _get_children(plan):
        ops.extend(_collect_join_ops(child))
    return ops


def _collect_scan_ops(plan):
    """Collect (op_type, table_name) for all scan nodes."""
    scans = []
    op = _get_op(plan)
    if op in ("SeqScan", "Scan", "TableScan", "SequentialScan",
              "IndexScan", "index_scan"):
        table = plan.get("table", plan.get("table_name", ""))
        scans.append((op, table))
    for child in _get_children(plan):
        scans.extend(_collect_scan_ops(child))
    return scans


def _find_scan_for_table(plan, target_table):
    """Find the scan node for a specific table."""
    op = _get_op(plan)
    if op in ("SeqScan", "Scan", "TableScan", "SequentialScan",
              "IndexScan", "index_scan"):
        table = plan.get("table", plan.get("table_name", ""))
        if table == target_table:
            return plan
    for child in _get_children(plan):
        result = _find_scan_for_table(child, target_table)
        if result is not None:
            return result
    return None


@pytest.fixture(scope="module", autouse=True)
def run_optimizer():
    result = subprocess.run(
        ["python3", "/app/main.py"],
        capture_output=True, text=True, timeout=120, cwd="/app"
    )
    assert result.returncode == 0, (
        f"Optimizer failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


@pytest.fixture(scope="module")
def plans():
    loaded = {}
    for qid in EXPECTED:
        path = f"/app/output/{qid}_plan.json"
        assert os.path.exists(path), f"Output file {path} not found"
        with open(path) as f:
            loaded[qid] = json.load(f)
    return loaded


class TestOutputExists:
    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_output_file_exists(self, qid):
        path = f"/app/output/{qid}_plan.json"
        assert os.path.exists(path), f"Missing output: {path}"

    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_output_valid_json(self, qid):
        path = f"/app/output/{qid}_plan.json"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict), "Output must be a JSON object"


class TestTotalCost:
    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_total_cost_optimal(self, qid, plans):
        expected = EXPECTED[qid]["total_cost"]
        data = plans[qid]
        plan_tree = data.get("plan", data)
        tree_cost = _compute_total_cost(plan_tree)
        rel_err = abs(tree_cost - expected) / expected
        assert rel_err < COST_TOLERANCE, (
            f"{qid}: tree total cost {tree_cost:.1f} differs from expected "
            f"{expected:.1f} by {rel_err*100:.2f}%"
        )
        if "total_cost" in data:
            reported_cost = data["total_cost"]
            assert abs(reported_cost - tree_cost) / max(tree_cost, 1) < 0.005, (
                f"{qid}: reported total_cost {reported_cost:.1f} inconsistent "
                f"with tree cost {tree_cost:.1f}"
            )


class TestCardinality:
    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_root_cardinality(self, qid, plans):
        expected = EXPECTED[qid]["root_card"]
        plan_tree = plans[qid].get("plan", plans[qid])
        actual = _get_card(plan_tree)
        assert actual is not None, f"{qid}: root node missing cardinality"
        rel_err = abs(actual - expected) / expected
        assert rel_err < CARD_TOLERANCE, (
            f"{qid}: root cardinality {actual} differs from expected "
            f"{expected} by {rel_err*100:.2f}%"
        )


class TestFilterPushdown:
    @pytest.mark.parametrize("qid", ["q2", "q3", "q5"])
    def test_filters_below_joins(self, qid, plans):
        plan_tree = plans[qid].get("plan", plans[qid])
        _check_filter_pushdown(plan_tree)


class TestJoinOperatorSelection:
    """Verify correct join algorithm selection based on physical properties."""

    @pytest.mark.parametrize("qid", ["q1", "q2", "q3"])
    def test_hash_only_queries(self, qid, plans):
        """q1-q3 should use only HashJoin (no sorted inputs on join columns)."""
        plan_tree = plans[qid].get("plan", plans[qid])
        join_ops = _collect_join_ops(plan_tree)
        assert len(join_ops) > 0, f"{qid}: no join operators found"
        for op in join_ops:
            assert op in ("HashJoin", "hash_join"), (
                f"{qid}: expected only HashJoin but found {op}"
            )

    def test_q4_uses_merge_join(self, plans):
        """q4 (orders ⋈ dates): both sorted on date_id → SortMergeJoin optimal."""
        plan_tree = plans["q4"].get("plan", plans["q4"])
        join_ops = _collect_join_ops(plan_tree)
        assert len(join_ops) == 1, f"q4: expected 1 join, got {len(join_ops)}"
        assert join_ops[0] in ("SortMergeJoin", "MergeJoin", "sort_merge_join", "merge_join"), (
            f"q4: expected SortMergeJoin but got {join_ops[0]}"
        )

    def test_q5_has_merge_join(self, plans):
        """q5 must use SortMergeJoin for the orders-dates join."""
        plan_tree = plans["q5"].get("plan", plans["q5"])
        join_ops = _collect_join_ops(plan_tree)
        merge_ops = [op for op in join_ops
                     if op in ("SortMergeJoin", "MergeJoin", "sort_merge_join", "merge_join")]
        assert len(merge_ops) >= 1, (
            f"q5: expected at least one SortMergeJoin, got join ops: {join_ops}"
        )

    def test_q5_merge_join_involves_dates(self, plans):
        """q5's SortMergeJoin must be the orders-dates join."""
        plan_tree = plans["q5"].get("plan", plans["q5"])
        # Find the merge join node
        merge_node = self._find_merge_join(plan_tree)
        assert merge_node is not None, "q5: no merge join node found"
        tables = _get_leaf_tables(merge_node)
        assert "orders" in tables, (
            f"q5: merge join should involve 'orders', got {sorted(tables)}"
        )
        assert "dates" in tables, (
            f"q5: merge join should involve 'dates', got {sorted(tables)}"
        )

    def _find_merge_join(self, plan):
        op = _get_op(plan)
        if op in ("SortMergeJoin", "MergeJoin", "sort_merge_join", "merge_join"):
            return plan
        for child in _get_children(plan):
            result = self._find_merge_join(child)
            if result is not None:
                return result
        return None


class TestScanOperatorSelection:
    """Verify correct scan type: IndexScan vs SeqScan."""

    @pytest.mark.parametrize("qid", ["q2", "q3"])
    def test_products_uses_index_scan(self, qid, plans):
        """Filtered products (selectivity 1/50 < 0.15) should use IndexScan."""
        plan_tree = plans[qid].get("plan", plans[qid])
        scan = _find_scan_for_table(plan_tree, "products")
        assert scan is not None, f"{qid}: no scan node for products"
        op = _get_op(scan)
        assert op in ("IndexScan", "index_scan"), (
            f"{qid}: products should use IndexScan but uses {op}"
        )

    def test_q5_products_uses_index_scan(self, plans):
        plan_tree = plans["q5"].get("plan", plans["q5"])
        scan = _find_scan_for_table(plan_tree, "products")
        assert scan is not None, "q5: no scan node for products"
        op = _get_op(scan)
        assert op in ("IndexScan", "index_scan"), (
            f"q5: products should use IndexScan but uses {op}"
        )

    def test_q5_dates_uses_seq_scan(self, plans):
        """q5 dates: SeqScan+Filter preserves date_id sort → enables merge join.
        IndexScan would sort on 'year' instead, blocking the cheaper merge join.
        """
        plan_tree = plans["q5"].get("plan", plans["q5"])
        scan = _find_scan_for_table(plan_tree, "dates")
        assert scan is not None, "q5: no scan node for dates"
        op = _get_op(scan)
        assert op in ("SeqScan", "Scan", "TableScan", "SequentialScan"), (
            f"q5: dates must use SeqScan (not IndexScan) to preserve "
            f"date_id sort order for merge join, but uses {op}"
        )


class TestPlanStructure:
    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_plan_covers_all_tables(self, qid, plans):
        with open("/data/queries.json") as f:
            queries = {q["id"]: q for q in json.load(f)}
        expected_tables = set(queries[qid]["tables"])
        plan_tree = plans[qid].get("plan", plans[qid])
        actual_tables = _get_leaf_tables(plan_tree)
        assert expected_tables == actual_tables, (
            f"{qid}: plan tables {sorted(actual_tables)} != "
            f"expected {sorted(expected_tables)}"
        )

    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_all_costs_positive(self, qid, plans):
        plan_tree = plans[qid].get("plan", plans[qid])
        self._check_positive_costs(plan_tree, qid)

    def _check_positive_costs(self, plan, qid):
        cost = _get_cost(plan)
        assert cost > 0, f"{qid}: node {_get_op(plan)} has non-positive cost {cost}"
        for child in _get_children(plan):
            self._check_positive_costs(child, qid)

    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_cardinalities_positive(self, qid, plans):
        plan_tree = plans[qid].get("plan", plans[qid])
        self._check_positive_cards(plan_tree, qid)

    def _check_positive_cards(self, plan, qid):
        card = _get_card(plan)
        assert card is not None and card > 0, (
            f"{qid}: node {_get_op(plan)} has invalid cardinality {card}"
        )
        for child in _get_children(plan):
            self._check_positive_cards(child, qid)


class TestGraphvizOutput:
    """Verify DOT and PNG plan visualizations."""

    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_dot_file_exists(self, qid):
        path = f"/app/output/{qid}_plan.dot"
        assert os.path.exists(path), f"Missing DOT file: {path}"

    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_dot_file_valid(self, qid):
        path = f"/app/output/{qid}_plan.dot"
        with open(path) as f:
            content = f.read()
        assert "digraph" in content.lower() or "graph" in content.lower(), (
            f"{qid}: DOT file missing 'digraph' or 'graph' keyword"
        )
        assert "->" in content, (
            f"{qid}: DOT file has no edges (missing '->')"
        )

    @pytest.mark.parametrize("qid", ["q1", "q2", "q3", "q4", "q5"])
    def test_png_file_exists(self, qid):
        path = f"/app/output/{qid}_plan.png"
        assert os.path.exists(path), f"Missing PNG file: {path}"
        assert os.path.getsize(path) > 0, f"PNG file is empty: {path}"
