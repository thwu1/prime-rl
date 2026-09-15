"""
Tests for the CEB cardinality estimation evaluation pipeline.

Runs the multi-tool pipeline and validates output against a reference
implementation that independently computes correct values in Python.
"""


import json
import math
import os
import subprocess
from collections import defaultdict

import pytest

NILJ_CONSTANT = 0.001
QUERY_DIR = "/app/data/queries"
REPORT_PATH = "/app/results/report.json"


# ── Reference implementation ───────────────────────────────────────────────


def ref_edge_cost(c1, c2, len1, len2):
    """Correct cost model C edge cost."""
    if len1 == 1:
        nilj = c2 + NILJ_CONSTANT * c1
    elif len2 == 1:
        nilj = c1 + NILJ_CONSTANT * c2
    else:
        raise ValueError("One node must be a single table")
    return min(nilj, c1 * c2)


def ref_evaluate_query(qdata):
    """Reference evaluator for a single query."""
    subplans = qdata["subplans"]

    tuples = {}
    for key, cards in subplans.items():
        parts = tuple(key.split(","))
        tuples[parts] = cards

    by_size = defaultdict(list)
    for parts in tuples:
        by_size[len(parts)].append(parts)

    # Build subset graph edges
    sg_edges = []
    sizes = sorted(by_size.keys())
    for size in sizes:
        if size <= 1:
            continue
        for sup in by_size[size]:
            for sub in by_size.get(size - 1, []):
                if set(sub) < set(sup):
                    sg_edges.append((sup, sub))

    max_size = max(sizes)
    final = by_size[max_size][0]

    def make_costs(use_est):
        costs = {}
        ck = "estimated" if use_est else "actual"
        for sup, sub in sg_edges:
            diff = tuple(sorted(set(sup) - set(sub)))
            c1 = max(tuples[sub][ck], 1)
            c2 = max(tuples[diff][ck], 1)
            costs[(sup, sub)] = ref_edge_cost(c1, c2, len(sub), len(diff))
        return costs

    true_c = make_costs(False)
    est_c = make_costs(True)

    def dp_shortest(costs):
        dist = {}
        parent = {}
        for nd in by_size.get(1, []):
            dist[nd] = 1.0
        for sz in sizes:
            if sz <= 1:
                continue
            for nd in by_size[sz]:
                best = float("inf")
                bp = None
                for sup, sub in sg_edges:
                    if sup == nd and sub in dist:
                        d = costs.get((sup, sub), float("inf")) + dist[sub]
                        if d < best:
                            best = d
                            bp = sub
                if bp is not None:
                    dist[nd] = best
                    parent[nd] = bp
        return dist, parent

    true_dist, _ = dp_shortest(true_c)
    _, est_parent = dp_shortest(est_c)

    opt_cost = true_dist[final] - 1.0

    # Reconstruct estimated path
    path = [final]
    cur = final
    while cur in est_parent:
        cur = est_parent[cur]
        path.append(cur)

    # TRUE cost of estimated path (excluding SOURCE edge)
    est_true_cost = 0.0
    for i in range(len(path) - 1):
        edge = (path[i], path[i + 1])
        if edge in true_c:
            est_true_cost += true_c[edge]

    # Q-errors with zero clamping
    qerrors = []
    for key, cards in subplans.items():
        a = max(cards["actual"], 1)
        e = max(cards["estimated"], 1)
        qerrors.append(max(a / e, e / a))

    return opt_cost, est_true_cost, qerrors


def percentile_linear(data, p):
    """Linear interpolation percentile."""
    n = len(data)
    if n <= 1:
        return data[0] if n == 1 else 0.0
    k = (n - 1) * p / 100.0
    f = int(math.floor(k))
    c = min(int(math.ceil(k)), n - 1)
    if f == c:
        return data[f]
    return data[f] * (c - k) + data[c] * (k - f)


def compute_reference():
    """Compute full reference results across all queries."""
    all_qerrors = []
    plan_costs = []

    for fname in sorted(os.listdir(QUERY_DIR)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(QUERY_DIR, fname)) as f:
            qdata = json.load(f)
        opt, est, qerrs = ref_evaluate_query(qdata)
        all_qerrors.extend(qerrs)
        plan_costs.append(
            {
                "name": qdata["name"],
                "opt_cost": opt,
                "est_cost": est,
                "relative_cost": est / opt if opt > 0 else float("inf"),
            }
        )

    all_qerrors.sort()
    n = len(all_qerrors)
    total_opt = sum(p["opt_cost"] for p in plan_costs)
    total_est = sum(p["est_cost"] for p in plan_costs)

    return {
        "qerror_stats": {
            "count": n,
            "mean": sum(all_qerrors) / n,
            "median": percentile_linear(all_qerrors, 50),
            "p90": percentile_linear(all_qerrors, 90),
            "p95": percentile_linear(all_qerrors, 95),
            "p99": percentile_linear(all_qerrors, 99),
        },
        "plan_costs": plan_costs,
        "total_opt_cost": total_opt,
        "total_est_cost": total_est,
        "total_relative_cost": total_est / total_opt if total_opt > 0 else None,
    }


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def pipeline_result():
    """Run the pipeline and return the report."""
    result = subprocess.run(
        ["bash", "/app/analyze.sh"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Pipeline failed with exit code {result.returncode}.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    assert os.path.exists(REPORT_PATH), "report.json not generated"
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def reference():
    """Compute reference results."""
    return compute_reference()


# ── Tests ──────────────────────────────────────────────────────────────────


class TestPipelineRuns:
    def test_report_exists(self, pipeline_result):
        assert pipeline_result is not None

    def test_report_has_required_keys(self, pipeline_result):
        assert "qerror_stats" in pipeline_result
        assert "plan_costs" in pipeline_result
        assert "total_opt_cost" in pipeline_result
        assert "total_est_cost" in pipeline_result
        assert "total_relative_cost" in pipeline_result


class TestQErrorStats:
    def test_qerror_count(self, pipeline_result, reference):
        """All subplans from all queries must be counted."""
        assert pipeline_result["qerror_stats"]["count"] == reference["qerror_stats"]["count"]

    def test_qerror_mean(self, pipeline_result, reference):
        actual = pipeline_result["qerror_stats"]["mean"]
        expected = reference["qerror_stats"]["mean"]
        assert abs(actual - expected) < 0.1, f"mean: got {actual}, expected {expected}"

    def test_qerror_median(self, pipeline_result, reference):
        actual = pipeline_result["qerror_stats"]["median"]
        expected = reference["qerror_stats"]["median"]
        assert abs(actual - expected) < 0.1, f"median: got {actual}, expected {expected}"

    def test_qerror_p90(self, pipeline_result, reference):
        actual = pipeline_result["qerror_stats"]["p90"]
        expected = reference["qerror_stats"]["p90"]
        assert abs(actual - expected) < 0.5, f"p90: got {actual}, expected {expected}"

    def test_qerror_p95(self, pipeline_result, reference):
        actual = pipeline_result["qerror_stats"]["p95"]
        expected = reference["qerror_stats"]["p95"]
        assert abs(actual - expected) < 1.0, f"p95: got {actual}, expected {expected}"

    def test_qerror_p99(self, pipeline_result, reference):
        actual = pipeline_result["qerror_stats"]["p99"]
        expected = reference["qerror_stats"]["p99"]
        assert abs(actual - expected) < 5.0, f"p99: got {actual}, expected {expected}"


class TestPlanCosts:
    def test_all_queries_present(self, pipeline_result, reference):
        report_names = {p["name"] for p in pipeline_result["plan_costs"]}
        ref_names = {p["name"] for p in reference["plan_costs"]}
        assert report_names == ref_names, f"Missing queries: {ref_names - report_names}"

    def test_per_query_opt_costs(self, pipeline_result, reference):
        report_map = {p["name"]: p for p in pipeline_result["plan_costs"]}
        for ref_pc in reference["plan_costs"]:
            name = ref_pc["name"]
            assert name in report_map, f"Missing {name}"
            actual = report_map[name]["opt_cost"]
            expected = ref_pc["opt_cost"]
            rel_err = abs(actual - expected) / max(abs(expected), 1e-9)
            assert rel_err < 0.01, (
                f"opt_cost for {name}: got {actual}, expected {expected} (rel_err={rel_err:.4f})"
            )

    def test_per_query_est_costs(self, pipeline_result, reference):
        report_map = {p["name"]: p for p in pipeline_result["plan_costs"]}
        for ref_pc in reference["plan_costs"]:
            name = ref_pc["name"]
            assert name in report_map, f"Missing {name}"
            actual = report_map[name]["est_cost"]
            expected = ref_pc["est_cost"]
            rel_err = abs(actual - expected) / max(abs(expected), 1e-9)
            assert rel_err < 0.01, (
                f"est_cost for {name}: got {actual}, expected {expected} (rel_err={rel_err:.4f})"
            )

    def test_per_query_relative_costs(self, pipeline_result, reference):
        report_map = {p["name"]: p for p in pipeline_result["plan_costs"]}
        for ref_pc in reference["plan_costs"]:
            name = ref_pc["name"]
            assert name in report_map, f"Missing {name}"
            actual = report_map[name]["relative_cost"]
            expected = ref_pc["relative_cost"]
            assert abs(actual - expected) < 0.05, (
                f"relative_cost for {name}: got {actual}, expected {expected}"
            )

    def test_total_opt_cost(self, pipeline_result, reference):
        actual = pipeline_result["total_opt_cost"]
        expected = reference["total_opt_cost"]
        rel_err = abs(actual - expected) / max(abs(expected), 1e-9)
        assert rel_err < 0.01, f"total_opt_cost: got {actual}, expected {expected}"

    def test_total_est_cost(self, pipeline_result, reference):
        actual = pipeline_result["total_est_cost"]
        expected = reference["total_est_cost"]
        rel_err = abs(actual - expected) / max(abs(expected), 1e-9)
        assert rel_err < 0.01, f"total_est_cost: got {actual}, expected {expected}"

    def test_total_relative_cost(self, pipeline_result, reference):
        actual = pipeline_result["total_relative_cost"]
        expected = reference["total_relative_cost"]
        assert abs(actual - expected) < 0.05, (
            f"total_relative_cost: got {actual}, expected {expected}"
        )


class TestCostModelSemantics:
    """Verify that the cost model formula is correct by checking specific edge costs."""

    def test_nilj_formula_single_table_node1(self):
        """When node1 is single table: NILJ = card2 + 0.001*card1."""
        cost = ref_edge_cost(1000, 500, 1, 1)
        assert abs(cost - 501.0) < 0.01, f"Expected 501.0, got {cost}"

    def test_nilj_formula_single_table_node2(self):
        """When node2 is single table (and node1 is multi-table):
        NILJ = card1 + 0.001*card2."""
        cost = ref_edge_cost(3000, 200, 2, 1)
        assert abs(cost - 3000.2) < 0.01, f"Expected 3000.2, got {cost}"

    def test_hash_join_wins_when_cheaper(self):
        """Hash join should be selected when it's cheaper than NILJ."""
        cost = ref_edge_cost(1, 100, 1, 1)
        assert abs(cost - 100.0) < 0.01, f"Expected 100.0, got {cost}"


class TestZeroCardinality:
    """Verify zero cardinality handling."""

    def test_pipeline_handles_zero_cardinality(self, pipeline_result):
        """q004 has zero actual cardinalities; pipeline must not crash."""
        names = {p["name"] for p in pipeline_result["plan_costs"]}
        assert "q004" in names, "q004 missing — pipeline likely crashed on zero cardinalities"

    def test_qerror_with_zero_clamped(self):
        """Q-error for actual=0, estimated=50 should clamp actual to 1."""
        a = max(0, 1)
        e = max(50, 1)
        qe = max(a / e, e / a)
        assert abs(qe - 50.0) < 0.01
