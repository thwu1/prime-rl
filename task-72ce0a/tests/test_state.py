
"""Tests for protocol fuzzing campaign audit results."""

import json
import os
import pytest
from collections import defaultdict, deque, Counter

from scipy.stats import mannwhitneyu
import numpy as np

DATA_DIR = "/opt/campaign"
COVERAGE_DIR = os.path.join(DATA_DIR, "coverage")

_cache = {}


def _determine_expected_bitmap_size():
    """Determine expected bitmap size from the most common file size."""
    sizes = []
    for fname in os.listdir(COVERAGE_DIR):
        if fname.endswith(".bin"):
            sizes.append(os.path.getsize(os.path.join(COVERAGE_DIR, fname)))
    return Counter(sizes).most_common(1)[0][0]


def _load_data():
    if "data" in _cache:
        return _cache["data"]

    expected_size = _determine_expected_bitmap_size()

    executions = []
    with open(os.path.join(DATA_DIR, "runs.jsonl")) as f:
        for line in f:
            line = line.strip()
            if line:
                executions.append(json.loads(line))

    valid_executions = []
    corrupted_ids = []
    valid_bitmaps = {}

    for ex in executions:
        path = os.path.join(DATA_DIR, ex["edges_file"])
        if not os.path.exists(path) or os.path.getsize(path) != expected_size:
            corrupted_ids.append(ex["test_id"])
        else:
            valid_executions.append(ex)
            with open(path, "rb") as f:
                raw = f.read()
            edges = set()
            for i in range(len(raw)):
                if raw[i] > 0:
                    edges.add(i)
            valid_bitmaps[ex["test_id"]] = edges

    referenced_files = set()
    for ex in executions:
        referenced_files.add(os.path.basename(ex["edges_file"]))

    all_coverage_files = set(
        fn for fn in os.listdir(COVERAGE_DIR) if fn.endswith(".bin")
    )
    orphan_files = sorted(all_coverage_files - referenced_files)

    _cache["data"] = {
        "all_executions": executions,
        "valid_executions": valid_executions,
        "corrupted_ids": sorted(corrupted_ids),
        "orphan_files": orphan_files,
        "valid_bitmaps": valid_bitmaps,
        "expected_size": expected_size,
    }
    return _cache["data"]


def _compute_expected():
    if "expected" in _cache:
        return _cache["expected"]

    data = _load_data()
    valid_execs = data["valid_executions"]
    bitmaps = data["valid_bitmaps"]

    # --- Data quality ---
    data_quality = {
        "total_records": len(data["all_executions"]),
        "valid_records": len(valid_execs),
        "corrupted_records": data["corrupted_ids"],
        "orphan_coverage_files": data["orphan_files"],
    }

    # --- Protocol model ---
    states = set()
    transitions = set()
    for ex in valid_execs:
        seq = ex["states"]
        for s in seq:
            states.add(s)
        for i in range(len(seq) - 1):
            transitions.add((seq[i], seq[i + 1]))

    initial_candidates = Counter(ex["states"][0] for ex in valid_execs)
    initial_state = initial_candidates.most_common(1)[0][0]

    adj = defaultdict(set)
    for a, b in transitions:
        adj[a].add(b)

    dist = {initial_state: 0}
    queue = deque([initial_state])
    while queue:
        node = queue.popleft()
        for neighbor in sorted(adj[node]):
            if neighbor not in dist:
                dist[neighbor] = dist[node] + 1
                queue.append(neighbor)
    max_depth = max(dist.values()) if dist else 0

    protocol_model = {
        "num_states": len(states),
        "num_transitions": len(transitions),
        "initial_state": initial_state,
        "max_depth": max_depth,
    }

    # --- Effectiveness ---
    all_edges = set()
    for edges in bitmaps.values():
        all_edges.update(edges)
    total_unique_edges = len(all_edges)

    config_a_edges = []
    config_b_edges = []
    for ex in valid_execs:
        n = len(bitmaps[ex["test_id"]])
        if ex["config"] == "A":
            config_a_edges.append(n)
        else:
            config_b_edges.append(n)

    median_a = float(np.median(config_a_edges))
    median_b = float(np.median(config_b_edges))
    superior = "A" if median_a >= median_b else "B"

    u_stat, p_val = mannwhitneyu(
        config_a_edges, config_b_edges, alternative="two-sided"
    )

    effectiveness = {
        "total_unique_edges": total_unique_edges,
        "config_a_median_edges": median_a,
        "config_b_median_edges": median_b,
        "superior_config": superior,
        "p_value": float(p_val),
    }

    # --- Regression suite (greedy set cover) ---
    uncovered = set(all_edges)
    corpus = []
    remaining = set(bitmaps.keys())

    while uncovered and remaining:
        best_id = None
        best_count = -1
        for tid in sorted(remaining):
            count = len(bitmaps[tid] & uncovered)
            if count > best_count:
                best_count = count
                best_id = tid
        if best_count == 0:
            break
        corpus.append(best_id)
        uncovered -= bitmaps[best_id]
        remaining.discard(best_id)

    regression_suite = {
        "test_ids": sorted(corpus),
        "suite_size": len(corpus),
        "coverage_edges": total_unique_edges,
    }

    expected = {
        "data_quality": data_quality,
        "protocol_model": protocol_model,
        "effectiveness": effectiveness,
        "regression_suite": regression_suite,
    }
    _cache["expected"] = expected
    return expected


def _load_results():
    if "results" in _cache:
        return _cache["results"]
    with open("/app/audit.json") as f:
        _cache["results"] = json.load(f)
    return _cache["results"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists("/app/audit.json"), "/app/audit.json not found"

    def test_results_valid_json(self):
        r = _load_results()
        assert isinstance(r, dict)

    def test_required_sections(self):
        r = _load_results()
        for section in [
            "data_quality",
            "protocol_model",
            "effectiveness",
            "regression_suite",
        ]:
            assert section in r, "Missing section: {}".format(section)


class TestDataQuality:
    def test_total_records(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["data_quality"]["total_records"]
            == exp["data_quality"]["total_records"]
        ), "Expected {} total_records, got {}".format(
            exp["data_quality"]["total_records"],
            res["data_quality"]["total_records"],
        )

    def test_valid_records(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["data_quality"]["valid_records"]
            == exp["data_quality"]["valid_records"]
        ), "Expected {} valid_records, got {}".format(
            exp["data_quality"]["valid_records"],
            res["data_quality"]["valid_records"],
        )

    def test_corrupted_records(self):
        exp = _compute_expected()
        res = _load_results()
        assert sorted(res["data_quality"]["corrupted_records"]) == exp[
            "data_quality"
        ]["corrupted_records"], (
            "corrupted_records mismatch: expected {}, got {}".format(
                exp["data_quality"]["corrupted_records"],
                sorted(res["data_quality"]["corrupted_records"]),
            )
        )

    def test_orphan_coverage_files(self):
        exp = _compute_expected()
        res = _load_results()
        # Normalize to basenames in case agent provides full paths
        actual = sorted(
            os.path.basename(f)
            for f in res["data_quality"]["orphan_coverage_files"]
        )
        assert actual == exp["data_quality"]["orphan_coverage_files"], (
            "orphan_coverage_files mismatch: expected {}, got {}".format(
                exp["data_quality"]["orphan_coverage_files"], actual
            )
        )


class TestProtocolModel:
    def test_num_states(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["protocol_model"]["num_states"]
            == exp["protocol_model"]["num_states"]
        ), "Expected {} states, got {}".format(
            exp["protocol_model"]["num_states"],
            res["protocol_model"]["num_states"],
        )

    def test_num_transitions(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["protocol_model"]["num_transitions"]
            == exp["protocol_model"]["num_transitions"]
        ), "Expected {} transitions, got {}".format(
            exp["protocol_model"]["num_transitions"],
            res["protocol_model"]["num_transitions"],
        )

    def test_initial_state(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["protocol_model"]["initial_state"]
            == exp["protocol_model"]["initial_state"]
        ), "Expected initial_state {}, got {}".format(
            exp["protocol_model"]["initial_state"],
            res["protocol_model"]["initial_state"],
        )

    def test_max_depth(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["protocol_model"]["max_depth"]
            == exp["protocol_model"]["max_depth"]
        ), "Expected max_depth {}, got {}".format(
            exp["protocol_model"]["max_depth"],
            res["protocol_model"]["max_depth"],
        )


class TestEffectiveness:
    def test_total_unique_edges(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["effectiveness"]["total_unique_edges"]
            == exp["effectiveness"]["total_unique_edges"]
        ), "Expected {} total_unique_edges, got {}".format(
            exp["effectiveness"]["total_unique_edges"],
            res["effectiveness"]["total_unique_edges"],
        )

    def test_config_a_median(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            abs(
                res["effectiveness"]["config_a_median_edges"]
                - exp["effectiveness"]["config_a_median_edges"]
            )
            < 1.0
        ), "config_a_median_edges mismatch: expected {}, got {}".format(
            exp["effectiveness"]["config_a_median_edges"],
            res["effectiveness"]["config_a_median_edges"],
        )

    def test_config_b_median(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            abs(
                res["effectiveness"]["config_b_median_edges"]
                - exp["effectiveness"]["config_b_median_edges"]
            )
            < 1.0
        ), "config_b_median_edges mismatch: expected {}, got {}".format(
            exp["effectiveness"]["config_b_median_edges"],
            res["effectiveness"]["config_b_median_edges"],
        )

    def test_superior_config(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["effectiveness"]["superior_config"]
            == exp["effectiveness"]["superior_config"]
        ), "Expected superior_config '{}', got '{}'".format(
            exp["effectiveness"]["superior_config"],
            res["effectiveness"]["superior_config"],
        )

    def test_p_value_significance(self):
        """Verify p-value leads to the correct significance conclusion."""
        exp = _compute_expected()
        res = _load_results()
        exp_sig = exp["effectiveness"]["p_value"] < 0.05
        res_sig = res["effectiveness"]["p_value"] < 0.05
        assert exp_sig == res_sig, (
            "Significance conclusion mismatch: expected p={:.6f} (sig={}), "
            "got p={:.6f} (sig={})".format(
                exp["effectiveness"]["p_value"],
                exp_sig,
                res["effectiveness"]["p_value"],
                res_sig,
            )
        )

    def test_p_value_range(self):
        """Verify p-value is within reasonable range of expected."""
        exp = _compute_expected()
        res = _load_results()
        assert (
            abs(
                res["effectiveness"]["p_value"]
                - exp["effectiveness"]["p_value"]
            )
            < 0.02
        ), "p_value too far from expected: got {}, expected {}".format(
            res["effectiveness"]["p_value"],
            exp["effectiveness"]["p_value"],
        )


class TestRegressionSuite:
    def test_suite_covers_all_edges(self):
        """Verify the submitted suite covers every observed edge."""
        data = _load_data()
        bitmaps = data["valid_bitmaps"]
        res = _load_results()

        all_edges = set()
        for edges in bitmaps.values():
            all_edges.update(edges)

        suite_edges = set()
        for tid in res["regression_suite"]["test_ids"]:
            assert tid in bitmaps, "Unknown test_id in suite: {}".format(tid)
            suite_edges.update(bitmaps[tid])

        assert suite_edges == all_edges, "Suite misses {} edges".format(
            len(all_edges - suite_edges)
        )

    def test_suite_size(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["regression_suite"]["suite_size"]
            == exp["regression_suite"]["suite_size"]
        ), "Expected suite_size {}, got {}".format(
            exp["regression_suite"]["suite_size"],
            res["regression_suite"]["suite_size"],
        )

    def test_suite_test_ids(self):
        exp = _compute_expected()
        res = _load_results()
        assert sorted(res["regression_suite"]["test_ids"]) == sorted(
            exp["regression_suite"]["test_ids"]
        ), "Suite test_ids do not match expected solution"

    def test_coverage_edges(self):
        exp = _compute_expected()
        res = _load_results()
        assert (
            res["regression_suite"]["coverage_edges"]
            == exp["regression_suite"]["coverage_edges"]
        ), "Expected coverage_edges {}, got {}".format(
            exp["regression_suite"]["coverage_edges"],
            res["regression_suite"]["coverage_edges"],
        )
