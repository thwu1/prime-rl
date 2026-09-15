"""
Tests for the IR retrieval diagnosis and optimization task.
Verifies diagnosis accuracy, optimized run quality, metrics comparison,
and optimal configuration justification.
"""

import json
import os
import subprocess
import sys

import pytest

RESULTS_DIR = "/app/results"
RUNS_DIR = "/app/runs"
QRELS_FILE = "/app/qrels.txt"
QUERIES_FILE = "/app/queries.tsv"
TARGETS_FILE = "/app/targets.json"
EVAL_TOOL = "/app/tools/evaluate.py"

EXPECTED_QUERY_COUNT = 8
BASELINE_RUNS = ["run_A", "run_B", "run_C"]
METRIC_KEYS = ["map", "ndcg_cut_10", "recall_1000"]


def _run_eval(run_path):
    """Run evaluation tool on a run file and return metrics dict."""
    result = subprocess.run(
        [sys.executable, EVAL_TOOL, "--qrels", QRELS_FILE, "--run", run_path, "-c"],
        capture_output=True, text=True,
    )
    metrics = {}
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 3:
            try:
                metrics[parts[0].strip()] = float(parts[2].strip())
            except ValueError:
                pass
    return metrics


def _load_targets():
    with open(TARGETS_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------
class TestDiagnosis:
    def test_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "diagnosis.json")), \
            "diagnosis.json not found"

    def test_structure(self):
        with open(os.path.join(RESULTS_DIR, "diagnosis.json")) as f:
            data = json.load(f)
        for run in BASELINE_RUNS:
            assert run in data, "Missing '%s' in diagnosis.json" % run
            for mk in METRIC_KEYS:
                assert mk in data[run], "Missing metric '%s' for '%s'" % (mk, run)
                assert isinstance(data[run][mk], (int, float)), \
                    "%s for %s should be numeric" % (mk, run)

    def test_metrics_accuracy(self):
        """Independently evaluate each baseline and verify reported metrics."""
        with open(os.path.join(RESULTS_DIR, "diagnosis.json")) as f:
            diagnosis = json.load(f)
        for run_name in BASELINE_RUNS:
            run_path = os.path.join(RUNS_DIR, run_name + ".txt")
            if not os.path.isfile(run_path):
                pytest.skip("Baseline %s not found" % run_path)
            actual = _run_eval(run_path)
            if not actual:
                pytest.skip("Eval returned no output for %s" % run_name)
            for mk in METRIC_KEYS:
                if mk in actual:
                    reported = diagnosis[run_name][mk]
                    assert abs(reported - actual[mk]) < 0.005, (
                        "Metric mismatch for %s/%s: "
                        "reported=%.4f, actual=%.4f"
                        % (run_name, mk, reported, actual[mk])
                    )

    def test_meets_targets_consistency(self):
        """If meets_targets is present, verify it's logically correct."""
        with open(os.path.join(RESULTS_DIR, "diagnosis.json")) as f:
            diagnosis = json.load(f)
        targets = _load_targets()
        for run_name in BASELINE_RUNS:
            if "meets_targets" not in diagnosis[run_name]:
                continue
            mt = diagnosis[run_name]["meets_targets"]
            for mk in METRIC_KEYS:
                if mk in mt and mk in targets:
                    expected = diagnosis[run_name][mk] >= targets[mk]
                    assert mt[mk] == expected, (
                        "meets_targets[%s] for %s is %s "
                        "but metric=%.4f, target=%s"
                        % (mk, run_name, mt[mk], diagnosis[run_name][mk], targets[mk])
                    )

    def test_deficiency_present(self):
        """Each run must have a non-empty deficiency description."""
        with open(os.path.join(RESULTS_DIR, "diagnosis.json")) as f:
            diagnosis = json.load(f)
        for run_name in BASELINE_RUNS:
            assert "deficiency" in diagnosis[run_name], \
                "Missing 'deficiency' for %s" % run_name
            assert isinstance(diagnosis[run_name]["deficiency"], str), \
                "deficiency for %s must be a string" % run_name
            assert len(diagnosis[run_name]["deficiency"].strip()) > 10, \
                "deficiency for %s is too short" % run_name


# ---------------------------------------------------------------------------
# Optimized run
# ---------------------------------------------------------------------------
class TestOptimizedRun:
    def test_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "optimized_run.txt")
        ), "optimized_run.txt not found"

    def test_trec_format(self):
        path = os.path.join(RESULTS_DIR, "optimized_run.txt")
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) > 0, "optimized_run.txt is empty"
        for i, line in enumerate(lines[:60]):
            parts = line.strip().split()
            assert len(parts) == 6, (
                "Line %d: expected 6 TREC fields, got %d" % (i + 1, len(parts))
            )
            assert parts[1] == "Q0", "Field 2 should be 'Q0', got '%s'" % parts[1]

    def test_covers_all_queries(self):
        path = os.path.join(RESULTS_DIR, "optimized_run.txt")
        with open(path) as f:
            qids = {line.strip().split()[0] for line in f if line.strip()}
        for qid in range(1, EXPECTED_QUERY_COUNT + 1):
            assert str(qid) in qids, "Missing results for query %d" % qid

    def test_meets_all_targets(self):
        """The optimized run must meet every effectiveness target."""
        targets = _load_targets()
        metrics = _run_eval(
            os.path.join(RESULTS_DIR, "optimized_run.txt")
        )
        assert metrics, "Eval returned no metrics for optimized_run.txt"
        for mk, target_val in targets.items():
            actual_val = metrics.get(mk, 0)
            assert actual_val >= target_val - 0.01, (
                "Optimized run fails target %s: %.4f < %s"
                % (mk, actual_val, target_val)
            )

    def test_outperforms_all_baselines(self):
        """Optimized run MAP must be >= every baseline's MAP."""
        opt = _run_eval(os.path.join(RESULTS_DIR, "optimized_run.txt"))
        if not opt:
            pytest.skip("Could not evaluate optimized run")
        for run_name in BASELINE_RUNS:
            run_path = os.path.join(RUNS_DIR, run_name + ".txt")
            if not os.path.isfile(run_path):
                continue
            baseline = _run_eval(run_path)
            if not baseline:
                continue
            assert opt.get("map", 0) >= baseline.get("map", 0) - 0.005, (
                "Optimized MAP (%.4f) should >= %s MAP (%.4f)"
                % (opt.get("map", 0), run_name, baseline.get("map", 0))
            )


# ---------------------------------------------------------------------------
# Metrics comparison
# ---------------------------------------------------------------------------
class TestMetricsComparison:
    def test_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "metrics_comparison.json")
        ), "metrics_comparison.json not found"

    def test_minimum_entries(self):
        with open(os.path.join(RESULTS_DIR, "metrics_comparison.json")) as f:
            data = json.load(f)
        assert len(data) >= 7, (
            "metrics_comparison must have >= 7 entries "
            "(3 baselines + 4 custom), got %d" % len(data)
        )

    def test_metrics_structure(self):
        with open(os.path.join(RESULTS_DIR, "metrics_comparison.json")) as f:
            data = json.load(f)
        for config_name, metrics in data.items():
            for mk in METRIC_KEYS:
                assert mk in metrics, (
                    "Missing metric '%s' in config '%s'" % (mk, config_name)
                )
                assert isinstance(metrics[mk], (int, float)), (
                    "%s for '%s' must be numeric" % (mk, config_name)
                )

    def test_baselines_included(self):
        """The comparison must include entries for all three baselines."""
        with open(os.path.join(RESULTS_DIR, "metrics_comparison.json")) as f:
            data = json.load(f)
        keys_lower = {k.lower().replace("-", "_") for k in data.keys()}
        found = 0
        for key in keys_lower:
            if any(tag in key for tag in ["run_a", "run_b", "run_c",
                                          "baseline_a", "baseline_b",
                                          "baseline_c"]):
                found += 1
        assert found >= 3, (
            "Expected entries for all 3 baselines, found %d. Keys: %s"
            % (found, list(data.keys()))
        )

    def test_baseline_metrics_accuracy(self):
        """Spot-check that reported baseline metrics are correct."""
        with open(os.path.join(RESULTS_DIR, "metrics_comparison.json")) as f:
            data = json.load(f)
        for run_name in BASELINE_RUNS:
            run_path = os.path.join(RUNS_DIR, run_name + ".txt")
            if not os.path.isfile(run_path):
                continue
            actual = _run_eval(run_path)
            if not actual:
                continue
            entry = None
            for key, val in data.items():
                kl = key.lower().replace("-", "_")
                if run_name.lower() in kl:
                    entry = val
                    break
            if entry is None:
                continue
            for mk in METRIC_KEYS:
                if mk in actual and mk in entry:
                    assert abs(entry[mk] - actual[mk]) < 0.005, (
                        "Comparison metric mismatch for %s/%s: "
                        "reported=%.4f, actual=%.4f"
                        % (run_name, mk, entry[mk], actual[mk])
                    )


# ---------------------------------------------------------------------------
# Optimal config
# ---------------------------------------------------------------------------
class TestOptimalConfig:
    def test_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "optimal_config.json")
        ), "optimal_config.json not found"

    def test_has_rationale(self):
        with open(os.path.join(RESULTS_DIR, "optimal_config.json")) as f:
            data = json.load(f)
        assert "rationale" in data, "Missing 'rationale' in optimal_config"
        assert isinstance(data["rationale"], str), "rationale must be string"
        assert len(data["rationale"].strip()) >= 30, (
            "rationale is too short (need >= 30 chars)"
        )

    def test_has_parameters(self):
        with open(os.path.join(RESULTS_DIR, "optimal_config.json")) as f:
            data = json.load(f)
        assert "parameters" in data, "Missing 'parameters' in optimal_config"
        assert isinstance(data["parameters"], dict), "parameters must be dict"
        assert len(data["parameters"]) > 0, "parameters must be non-empty"

    def test_metrics_match_optimized_run(self):
        """Config's claimed metrics must match the actual optimized run."""
        with open(os.path.join(RESULTS_DIR, "optimal_config.json")) as f:
            config = json.load(f)
        actual = _run_eval(os.path.join(RESULTS_DIR, "optimized_run.txt"))
        if not actual:
            pytest.skip("Could not evaluate optimized run")
        for mk in METRIC_KEYS:
            if mk in config and mk in actual:
                assert abs(config[mk] - actual[mk]) < 0.01, (
                    "Config metric mismatch for %s: "
                    "claimed=%.4f, actual=%.4f"
                    % (mk, config[mk], actual[mk])
                )
