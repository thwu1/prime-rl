"""Tests for DDSketch pipeline evaluation report correctness."""
import json
import csv
import math
import os
import sqlite3
import yaml
from collections import defaultdict


EVAL_PATH = "/app/output/evaluation.json"
REPORT_PATH = "/app/output/report.json"
CONFIG_PATH = "/app/config.yaml"
DB_PATH = "/app/output/benchmark.db"
SCHEMA_PATH = "/app/schema/output_schema.json"
REPORT_TXT_PATH = "/app/output/benchmark_report.txt"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_raw_data():
    """Load all CSV data grouped by window_id."""
    data_dir = "/app/data"
    window_data = defaultdict(list)
    total = 0
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".csv"):
            continue
        with open(os.path.join(data_dir, fname)) as f:
            reader = csv.DictReader(f)
            for row in reader:
                wid = int(row["window_id"])
                lat = float(row["latency_ms"])
                window_data[wid].append(lat)
                total += 1
    return window_data, total


def exact_quantile(data, q):
    """Compute exact quantile using ceiling rank method."""
    sorted_data = sorted(data)
    n = len(sorted_data)
    rank = int(math.ceil(q * n))
    return sorted_data[min(rank - 1, n - 1)]


# ============================================================
# Test: Output Files Exist
# ============================================================

class TestOutputExists:
    def test_report_file_exists(self):
        assert os.path.exists(REPORT_PATH), \
            "Pipeline report {} not found".format(REPORT_PATH)

    def test_evaluation_file_exists(self):
        assert os.path.exists(EVAL_PATH), \
            "Evaluation report {} not found".format(EVAL_PATH)

    def test_benchmark_db_exists(self):
        assert os.path.exists(DB_PATH), \
            "Benchmark database {} not found".format(DB_PATH)

    def test_evaluation_is_valid_json(self):
        with open(EVAL_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_required_top_level_keys(self):
        with open(EVAL_PATH) as f:
            data = json.load(f)
        assert "pipeline_report" in data, "Missing 'pipeline_report'"
        assert "slo_evaluation" in data, "Missing 'slo_evaluation'"
        assert "benchmark" in data, "Missing 'benchmark'"


# ============================================================
# Test: Pipeline Report Consistency
# ============================================================

class TestReportConsistency:
    def setup_method(self):
        with open(EVAL_PATH) as f:
            self.eval_data = json.load(f)
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def test_pipeline_report_matches_report_json(self):
        """The pipeline_report section in evaluation.json should match report.json."""
        embedded = self.eval_data["pipeline_report"]
        assert embedded["sketch_stats"] == self.report["sketch_stats"]
        assert len(embedded["windows"]) == len(self.report["windows"])
        for wid_str in self.report["windows"]:
            assert wid_str in embedded["windows"]
            assert embedded["windows"][wid_str]["total_count"] == \
                self.report["windows"][wid_str]["total_count"]
            for q_str in ["0.5", "0.9", "0.95", "0.99"]:
                assert abs(embedded["windows"][wid_str]["quantiles"][q_str] -
                          self.report["windows"][wid_str]["quantiles"][q_str]) < 1e-6


# ============================================================
# Test: Pipeline Quantile Accuracy
# ============================================================

class TestQuantileAccuracy:
    """Verify sketch quantiles are within relative-error bounds of exact values."""

    def setup_method(self):
        with open(REPORT_PATH) as f:
            self.output = json.load(f)
        config = load_config()
        self.window_data, self.total = load_raw_data()
        self.alpha = config["sketch"]["accuracy"]

    def test_total_ingested_count(self):
        assert self.output["sketch_stats"]["total_values_ingested"] == self.total

    def test_per_window_counts(self):
        for wid in range(20):
            w = self.output["windows"][str(wid)]
            expected = len(self.window_data[wid])
            assert w["total_count"] == expected, \
                "Window {}: expected count {}, got {}".format(wid, expected, w["total_count"])

    def test_p50_accuracy(self):
        self._check_quantile_accuracy(0.5)

    def test_p90_accuracy(self):
        self._check_quantile_accuracy(0.9)

    def test_p95_accuracy(self):
        self._check_quantile_accuracy(0.95)

    def test_p99_accuracy(self):
        self._check_quantile_accuracy(0.99)

    def _check_quantile_accuracy(self, q):
        tolerance = 3 * self.alpha
        q_str = str(q)
        for wid in range(20):
            exact = exact_quantile(self.window_data[wid], q)
            estimated = self.output["windows"][str(wid)]["quantiles"][q_str]
            if exact > 0:
                rel_error = abs(estimated - exact) / exact
                assert rel_error <= tolerance, \
                    "Window {}, q={}: exact={:.4f}, estimated={:.4f}, " \
                    "rel_error={:.6f} > tolerance={:.4f}".format(
                        wid, q, exact, estimated, rel_error, tolerance)

    def test_collapsed_quantiles_reasonable(self):
        tolerance = 0.15
        normal_windows = [w for w in range(20) if w not in (12, 17)]
        for wid in normal_windows:
            for q in [0.5, 0.9, 0.95, 0.99]:
                q_str = str(q)
                exact = exact_quantile(self.window_data[wid], q)
                estimated = self.output["windows"][str(wid)]["collapsed_quantiles"][q_str]
                if exact > 0:
                    rel_error = abs(estimated - exact) / exact
                    assert rel_error <= tolerance, \
                        "Collapsed: Window {}, q={}: rel_error={:.6f} > {:.2f}".format(
                            wid, q, rel_error, tolerance)

    def test_quantile_monotonicity(self):
        for wid in range(20):
            q = self.output["windows"][str(wid)]["quantiles"]
            assert float(q["0.5"]) <= float(q["0.9"]) + 1e-6
            assert float(q["0.9"]) <= float(q["0.95"]) + 1e-6
            assert float(q["0.95"]) <= float(q["0.99"]) + 1e-6


# ============================================================
# Test: Pipeline Anomaly Detection
# ============================================================

class TestAnomalyDetection:
    def setup_method(self):
        with open(REPORT_PATH) as f:
            self.output = json.load(f)

    def test_window_12_anomalous(self):
        anomaly_windows = {a["window_id"] for a in self.output["anomalies"]}
        assert 12 in anomaly_windows, \
            "Window 12 should be anomalous. Detected: {}".format(sorted(anomaly_windows))

    def test_window_17_anomalous(self):
        anomaly_windows = {a["window_id"] for a in self.output["anomalies"]}
        assert 17 in anomaly_windows, \
            "Window 17 should be anomalous. Detected: {}".format(sorted(anomaly_windows))

    def test_anomaly_entries_have_required_fields(self):
        for a in self.output["anomalies"]:
            assert "window_id" in a
            assert "quantile" in a
            assert "previous_value" in a
            assert "current_value" in a
            assert "relative_change" in a
            assert isinstance(a["window_id"], int)
            assert a["relative_change"] > 0

    def test_no_false_positives_in_normal_windows(self):
        anomaly_windows = {a["window_id"] for a in self.output["anomalies"]}
        normal_windows = set(range(1, 11))
        false_positives = anomaly_windows & normal_windows
        assert len(false_positives) == 0, \
            "False positive anomalies in windows: {}".format(sorted(false_positives))


# ============================================================
# Test: Pipeline Sketch Stats
# ============================================================

class TestSketchStats:
    def setup_method(self):
        with open(REPORT_PATH) as f:
            self.output = json.load(f)
        self.config = load_config()

    def test_collapsed_bucket_count_within_bound(self):
        stats = self.output["sketch_stats"]
        max_b = self.config["sketch"]["max_buckets"]
        assert stats["collapsed_max_buckets_used"] <= max_b

    def test_uncollapsed_uses_more_buckets(self):
        stats = self.output["sketch_stats"]
        assert stats["max_buckets_used"] >= stats["collapsed_max_buckets_used"]

    def test_uncollapsed_exceeds_max_buckets(self):
        stats = self.output["sketch_stats"]
        max_b = self.config["sketch"]["max_buckets"]
        assert stats["max_buckets_used"] > max_b

    def test_total_ingested_matches(self):
        stats = self.output["sketch_stats"]
        expected = 5 * 20 * 10000
        assert stats["total_values_ingested"] == expected


# ============================================================
# Test: SLO Evaluation
# ============================================================

class TestSLOEvaluation:
    def setup_method(self):
        with open(EVAL_PATH) as f:
            self.eval_data = json.load(f)
        self.slo = self.eval_data["slo_evaluation"]
        self.report = self.eval_data["pipeline_report"]
        self.config = load_config()

    def test_has_required_fields(self):
        for key in ["target_p99_ms", "ewma_decay", "overall_compliance_pct",
                     "windows", "breach_windows"]:
            assert key in self.slo, "SLO evaluation missing '{}'".format(key)

    def test_target_matches_config(self):
        assert self.slo["target_p99_ms"] == self.config["slo"]["target_p99_ms"]
        assert self.slo["ewma_decay"] == self.config["slo"]["ewma_decay"]

    def test_has_all_20_windows(self):
        for i in range(20):
            assert str(i) in self.slo["windows"], \
                "SLO missing window '{}'".format(i)

    def test_window_fields_present(self):
        for i in range(20):
            w = self.slo["windows"][str(i)]
            for key in ["p99", "compliant", "breach_severity", "ewma_score"]:
                assert key in w, "SLO window {} missing '{}'".format(i, key)

    def test_compliance_flags_match_pipeline(self):
        target = self.slo["target_p99_ms"]
        for wid in range(20):
            wid_str = str(wid)
            p99 = self.report["windows"][wid_str]["quantiles"]["0.99"]
            expected_compliant = p99 <= target
            assert self.slo["windows"][wid_str]["compliant"] == expected_compliant, \
                "Window {}: p99={:.4f}, target={}, expected compliant={}, got={}".format(
                    wid, p99, target, expected_compliant,
                    self.slo["windows"][wid_str]["compliant"])

    def test_breach_windows(self):
        assert set(self.slo["breach_windows"]) == {12, 17}, \
            "Expected breach windows {{12, 17}}, got {}".format(self.slo["breach_windows"])

    def test_overall_compliance_pct(self):
        assert self.slo["overall_compliance_pct"] == 90.0, \
            "Expected 90.0% compliance, got {}".format(self.slo["overall_compliance_pct"])

    def test_ewma_computation(self):
        target = self.slo["target_p99_ms"]
        decay = self.slo["ewma_decay"]
        ewma = 1.0
        for wid in range(20):
            wid_str = str(wid)
            p99 = self.report["windows"][wid_str]["quantiles"]["0.99"]
            indicator = 1.0 if p99 <= target else 0.0
            ewma = decay * indicator + (1.0 - decay) * ewma
            reported_ewma = self.slo["windows"][wid_str]["ewma_score"]
            assert abs(round(ewma, 4) - reported_ewma) < 1e-4, \
                "Window {}: expected EWMA {:.4f}, got {:.4f}".format(
                    wid, round(ewma, 4), reported_ewma)

    def test_breach_severity_correct(self):
        target = self.slo["target_p99_ms"]
        for wid in range(20):
            wid_str = str(wid)
            p99 = self.report["windows"][wid_str]["quantiles"]["0.99"]
            slo_w = self.slo["windows"][wid_str]
            if p99 > target:
                expected = (p99 - target) / target
                assert abs(slo_w["breach_severity"] - round(expected, 4)) < 1e-3, \
                    "Window {}: expected severity {:.4f}, got {:.4f}".format(
                        wid, expected, slo_w["breach_severity"])
            else:
                assert slo_w["breach_severity"] == 0.0, \
                    "Compliant window {} has non-zero severity".format(wid)

    def test_p99_values_match_pipeline(self):
        for wid in range(20):
            wid_str = str(wid)
            pipeline_p99 = self.report["windows"][wid_str]["quantiles"]["0.99"]
            slo_p99 = self.slo["windows"][wid_str]["p99"]
            assert abs(pipeline_p99 - slo_p99) < 1e-4, \
                "Window {}: pipeline p99={}, slo p99={}".format(wid, pipeline_p99, slo_p99)


# ============================================================
# Test: Benchmark Database
# ============================================================

class TestBenchmarkDatabase:
    def setup_method(self):
        self.config = load_config()

    def test_database_exists(self):
        assert os.path.exists(DB_PATH), "Benchmark DB not found at {}".format(DB_PATH)

    def test_has_benchmark_table(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='benchmark'")
        result = cur.fetchone()
        conn.close()
        assert result is not None, "Table 'benchmark' not found in database"

    def test_has_correct_columns(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(benchmark)")
        columns = {row[1] for row in cur.fetchall()}
        conn.close()
        expected = {"alpha", "max_buckets", "max_relative_error",
                    "mean_relative_error", "memory_buckets",
                    "p99_max_relative_error"}
        missing = expected - columns
        assert len(missing) == 0, "Missing columns: {}".format(missing)

    def test_has_correct_row_count(self):
        config = self.config
        expected = len(config["benchmark"]["alpha_values"]) * \
                   len(config["benchmark"]["max_buckets_values"])
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM benchmark")
        count = cur.fetchone()[0]
        conn.close()
        assert count == expected, \
            "Expected {} rows, got {}".format(expected, count)

    def test_all_config_pairs_present(self):
        config = self.config
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for alpha in config["benchmark"]["alpha_values"]:
            for mb in config["benchmark"]["max_buckets_values"]:
                cur.execute(
                    "SELECT COUNT(*) FROM benchmark WHERE alpha=? AND max_buckets=?",
                    (alpha, mb))
                assert cur.fetchone()[0] == 1, \
                    "Missing config alpha={}, max_buckets={}".format(alpha, mb)
        conn.close()

    def test_data_matches_evaluation_json(self):
        with open(EVAL_PATH) as f:
            eval_data = json.load(f)
        results = eval_data["benchmark"]["results"]

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for r in results:
            cur.execute(
                "SELECT max_relative_error, mean_relative_error, memory_buckets, "
                "p99_max_relative_error "
                "FROM benchmark WHERE alpha=? AND max_buckets=?",
                (r["alpha"], r["max_buckets"]))
            row = cur.fetchone()
            assert row is not None, \
                "Config (alpha={}, max_buckets={}) not in DB".format(
                    r["alpha"], r["max_buckets"])
            assert abs(row[0] - r["max_relative_error"]) < 1e-5, \
                "max_relative_error mismatch for ({}, {}): DB={}, JSON={}".format(
                    r["alpha"], r["max_buckets"], row[0], r["max_relative_error"])
            assert abs(row[1] - r["mean_relative_error"]) < 1e-5, \
                "mean_relative_error mismatch for ({}, {})".format(
                    r["alpha"], r["max_buckets"])
            assert row[2] == r["memory_buckets"], \
                "memory_buckets mismatch for ({}, {})".format(
                    r["alpha"], r["max_buckets"])
            assert abs(row[3] - r["p99_max_relative_error"]) < 1e-5, \
                "p99_max_relative_error mismatch for ({}, {}): DB={}, JSON={}".format(
                    r["alpha"], r["max_buckets"], row[3], r["p99_max_relative_error"])
        conn.close()


# ============================================================
# Test: Benchmark Results Structure
# ============================================================

class TestBenchmarkResults:
    def setup_method(self):
        with open(EVAL_PATH) as f:
            self.eval_data = json.load(f)
        self.benchmark = self.eval_data["benchmark"]
        self.config = load_config()

    def test_configurations_tested_count(self):
        expected = len(self.config["benchmark"]["alpha_values"]) * \
                   len(self.config["benchmark"]["max_buckets_values"])
        assert self.benchmark["configurations_tested"] == expected

    def test_results_count(self):
        assert len(self.benchmark["results"]) == self.benchmark["configurations_tested"]

    def test_result_fields_present(self):
        for r in self.benchmark["results"]:
            for key in ["alpha", "max_buckets", "max_relative_error",
                        "mean_relative_error", "memory_buckets",
                        "p99_max_relative_error"]:
                assert key in r, "Result missing field '{}'".format(key)

    def test_errors_non_negative(self):
        for r in self.benchmark["results"]:
            assert r["max_relative_error"] >= 0, \
                "Negative max_relative_error: {}".format(r)
            assert r["mean_relative_error"] >= 0, \
                "Negative mean_relative_error: {}".format(r)
            assert r["p99_max_relative_error"] >= 0, \
                "Negative p99_max_relative_error: {}".format(r)

    def test_memory_within_configured_limit(self):
        for r in self.benchmark["results"]:
            assert r["memory_buckets"] <= r["max_buckets"], \
                "memory_buckets ({}) > max_buckets ({})".format(
                    r["memory_buckets"], r["max_buckets"])

    def test_mean_error_leq_max_error(self):
        for r in self.benchmark["results"]:
            assert r["mean_relative_error"] <= r["max_relative_error"] + 1e-6, \
                "mean_error ({}) > max_error ({})".format(
                    r["mean_relative_error"], r["max_relative_error"])

    def test_p99_error_leq_max_error(self):
        """p99-specific max error must be <= overall max error."""
        for r in self.benchmark["results"]:
            assert r["p99_max_relative_error"] <= r["max_relative_error"] + 1e-6, \
                "p99_max_relative_error ({}) > max_relative_error ({}) for alpha={}, mb={}".format(
                    r["p99_max_relative_error"], r["max_relative_error"],
                    r["alpha"], r["max_buckets"])

    def test_all_config_pairs_represented(self):
        seen = set()
        for r in self.benchmark["results"]:
            seen.add((r["alpha"], r["max_buckets"]))
        for alpha in self.config["benchmark"]["alpha_values"]:
            for mb in self.config["benchmark"]["max_buckets_values"]:
                assert (alpha, mb) in seen, \
                    "Missing result for alpha={}, max_buckets={}".format(alpha, mb)


# ============================================================
# Test: Pareto Optimal and Recommendation (p99-focused)
# ============================================================

class TestParetoOptimal:
    def setup_method(self):
        with open(EVAL_PATH) as f:
            self.eval_data = json.load(f)
        self.results = self.eval_data["benchmark"]["results"]
        self.pareto = self.eval_data["benchmark"]["pareto_optimal"]
        self.recommendation = self.eval_data["benchmark"]["recommendation"]

    def _is_dominated(self, config, all_configs):
        """Check if config is dominated by any other config on
        (p99_max_relative_error, memory_buckets) dimensions."""
        for other in all_configs:
            if (other["p99_max_relative_error"] <= config["p99_max_relative_error"] and
                other["memory_buckets"] <= config["memory_buckets"] and
                (other["p99_max_relative_error"] < config["p99_max_relative_error"] or
                 other["memory_buckets"] < config["memory_buckets"])):
                return True
        return False

    def test_pareto_set_non_empty(self):
        assert len(self.pareto) > 0, "Pareto-optimal set is empty"

    def test_pareto_configs_not_dominated(self):
        """Each reported Pareto-optimal config must actually be non-dominated."""
        for p in self.pareto:
            matching = [r for r in self.results
                        if r["alpha"] == p["alpha"] and r["max_buckets"] == p["max_buckets"]]
            assert len(matching) == 1, \
                "Pareto config ({}, {}) not found in results".format(
                    p["alpha"], p["max_buckets"])
            config = matching[0]
            assert not self._is_dominated(config, self.results), \
                "Pareto config ({}, {}) is actually dominated on " \
                "(p99_max_relative_error, memory_buckets)".format(
                    p["alpha"], p["max_buckets"])

    def test_pareto_set_complete(self):
        """No non-Pareto config should be non-dominated."""
        pareto_set = {(p["alpha"], p["max_buckets"]) for p in self.pareto}
        for r in self.results:
            key = (r["alpha"], r["max_buckets"])
            if key not in pareto_set:
                assert self._is_dominated(r, self.results), \
                    "Config ({}, {}) is non-dominated on " \
                    "(p99_max_relative_error, memory_buckets) but not in Pareto set".format(
                        r["alpha"], r["max_buckets"])

    def test_recommendation_is_pareto_optimal(self):
        pareto_set = {(p["alpha"], p["max_buckets"]) for p in self.pareto}
        rec = (self.recommendation["alpha"], self.recommendation["max_buckets"])
        assert rec in pareto_set, \
            "Recommendation {} not in Pareto set {}".format(rec, pareto_set)

    def test_recommendation_has_lowest_p99_error(self):
        """Recommendation should be the Pareto config with lowest p99_max_relative_error."""
        rec_alpha = self.recommendation["alpha"]
        rec_mb = self.recommendation["max_buckets"]
        rec_result = None
        for r in self.results:
            if r["alpha"] == rec_alpha and r["max_buckets"] == rec_mb:
                rec_result = r
                break
        assert rec_result is not None

        pareto_set = {(p["alpha"], p["max_buckets"]) for p in self.pareto}
        for r in self.results:
            if (r["alpha"], r["max_buckets"]) in pareto_set:
                assert r["p99_max_relative_error"] >= rec_result["p99_max_relative_error"] - 1e-6, \
                    "Pareto config ({}, {}) has lower p99 error ({}) than " \
                    "recommendation ({})".format(
                        r["alpha"], r["max_buckets"], r["p99_max_relative_error"],
                        rec_result["p99_max_relative_error"])

    def test_recommendation_has_reason(self):
        assert isinstance(self.recommendation["reason"], str)
        assert len(self.recommendation["reason"]) > 0


# ============================================================
# Test: Schema Structural Compliance
# ============================================================

class TestSchemaCompliance:
    """Verify the evaluation report has the correct structure per schema."""

    def setup_method(self):
        with open(EVAL_PATH) as f:
            self.eval_data = json.load(f)

    def test_pipeline_report_structure(self):
        pr = self.eval_data["pipeline_report"]
        assert "windows" in pr
        assert "anomalies" in pr
        assert "sketch_stats" in pr
        assert isinstance(pr["anomalies"], list)
        stats = pr["sketch_stats"]
        assert isinstance(stats["max_buckets_used"], int)
        assert isinstance(stats["collapsed_max_buckets_used"], int)
        assert isinstance(stats["total_values_ingested"], int)

    def test_slo_evaluation_structure(self):
        slo = self.eval_data["slo_evaluation"]
        assert isinstance(slo["target_p99_ms"], (int, float))
        assert isinstance(slo["ewma_decay"], (int, float))
        assert 0 <= slo["ewma_decay"] <= 1
        assert isinstance(slo["overall_compliance_pct"], (int, float))
        assert 0 <= slo["overall_compliance_pct"] <= 100
        assert isinstance(slo["breach_windows"], list)
        for wid in range(20):
            w = slo["windows"][str(wid)]
            assert isinstance(w["p99"], (int, float))
            assert isinstance(w["compliant"], bool)
            assert isinstance(w["breach_severity"], (int, float))
            assert w["breach_severity"] >= 0
            assert isinstance(w["ewma_score"], (int, float))
            assert 0 <= w["ewma_score"] <= 1

    def test_benchmark_structure(self):
        bm = self.eval_data["benchmark"]
        assert isinstance(bm["configurations_tested"], int)
        assert isinstance(bm["results"], list)
        assert isinstance(bm["pareto_optimal"], list)
        assert isinstance(bm["recommendation"], dict)
        for r in bm["results"]:
            assert isinstance(r["alpha"], (int, float))
            assert isinstance(r["max_buckets"], int)
            assert isinstance(r["max_relative_error"], (int, float))
            assert isinstance(r["mean_relative_error"], (int, float))
            assert isinstance(r["memory_buckets"], int)
            assert isinstance(r["p99_max_relative_error"], (int, float))
        for p in bm["pareto_optimal"]:
            assert isinstance(p["alpha"], (int, float))
            assert isinstance(p["max_buckets"], int)
        assert isinstance(bm["recommendation"]["alpha"], (int, float))
        assert isinstance(bm["recommendation"]["max_buckets"], int)
        assert isinstance(bm["recommendation"]["reason"], str)


# ============================================================
# Test: Merge Correctness (via quantile accuracy on merged data)
# ============================================================

class TestMergeCorrectness:
    def setup_method(self):
        self.window_data, _ = load_raw_data()
        with open(REPORT_PATH) as f:
            self.output = json.load(f)
        config = load_config()
        self.alpha = config["sketch"]["accuracy"]

    def test_merged_quantiles_match_exact(self):
        tolerance = 3 * self.alpha
        for wid in [0, 3, 7, 10, 15, 19]:
            data = self.window_data[wid]
            for q in [0.5, 0.9, 0.99]:
                exact = exact_quantile(data, q)
                estimated = self.output["windows"][str(wid)]["quantiles"][str(q)]
                if exact > 0:
                    rel_error = abs(estimated - exact) / exact
                    assert rel_error <= tolerance, \
                        "Merge: Window {}, q={}: rel_error={:.6f}".format(
                            wid, q, rel_error)


# ============================================================
# Test: SQL View — pareto_frontier
# ============================================================

class TestSQLView:
    """Verify the pareto_frontier SQL view exists and is correct."""

    def test_pareto_view_exists(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='pareto_frontier'")
        result = cur.fetchone()
        conn.close()
        assert result is not None, \
            "SQL view 'pareto_frontier' not found in {}".format(DB_PATH)

    def test_pareto_view_matches_json(self):
        """The SQL view must return the same configs as the Pareto set in evaluation.json."""
        with open(EVAL_PATH) as f:
            eval_data = json.load(f)
        pareto_json = {(p["alpha"], p["max_buckets"])
                       for p in eval_data["benchmark"]["pareto_optimal"]}

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT alpha, max_buckets FROM pareto_frontier")
        pareto_view = {(row[0], row[1]) for row in cur.fetchall()}
        conn.close()

        assert pareto_view == pareto_json, \
            "View pareto_frontier {} != JSON pareto_optimal {}".format(
                pareto_view, pareto_json)

    def test_pareto_view_non_dominated(self):
        """Each config in the view must be non-dominated on
        (p99_max_relative_error, memory_buckets)."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT alpha, max_buckets, p99_max_relative_error, memory_buckets "
            "FROM pareto_frontier")
        pareto = cur.fetchall()
        cur.execute(
            "SELECT alpha, max_buckets, p99_max_relative_error, memory_buckets "
            "FROM benchmark")
        all_configs = cur.fetchall()
        conn.close()

        for p in pareto:
            for c in all_configs:
                if c[0] == p[0] and c[1] == p[1]:
                    continue
                dominated = (c[2] <= p[2] and c[3] <= p[3] and
                             (c[2] < p[2] or c[3] < p[3]))
                assert not dominated, \
                    "View config (alpha={}, mb={}) dominated by ({}, {})".format(
                        p[0], p[1], c[0], c[1])

    def test_pareto_view_has_required_columns(self):
        """View must expose the Pareto analysis dimensions."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT * FROM pareto_frontier LIMIT 1")
        col_names = [desc[0] for desc in cur.description]
        conn.close()
        for col in ["alpha", "max_buckets", "p99_max_relative_error", "memory_buckets"]:
            assert col in col_names, \
                "View missing column '{}'".format(col)


# ============================================================
# Test: Benchmark Report (sqlite3 CLI output)
# ============================================================

class TestBenchmarkReport:
    """Verify the benchmark_report.txt was generated with expected structure."""

    def test_report_exists(self):
        assert os.path.exists(REPORT_TXT_PATH), \
            "Benchmark report not found at {}".format(REPORT_TXT_PATH)

    def test_has_summary_header(self):
        with open(REPORT_TXT_PATH) as f:
            content = f.read()
        assert "=== Benchmark Summary ===" in content, \
            "Report missing '=== Benchmark Summary ===' header"

    def test_has_pareto_header(self):
        with open(REPORT_TXT_PATH) as f:
            content = f.read()
        assert "=== Pareto Frontier ===" in content, \
            "Report missing '=== Pareto Frontier ===' header"

    def test_has_column_names(self):
        with open(REPORT_TXT_PATH) as f:
            content = f.read()
        for col in ["alpha", "max_buckets", "max_relative_error",
                     "mean_relative_error", "memory_buckets",
                     "p99_max_relative_error"]:
            assert col in content, \
                "Report missing column name '{}'".format(col)

    def test_summary_contains_all_alphas(self):
        with open(REPORT_TXT_PATH) as f:
            content = f.read()
        config = load_config()
        for alpha in config["benchmark"]["alpha_values"]:
            assert str(alpha) in content, \
                "Alpha value {} not found in report".format(alpha)

    def test_pareto_section_has_data(self):
        with open(REPORT_TXT_PATH) as f:
            content = f.read()
        parts = content.split("=== Pareto Frontier ===")
        assert len(parts) == 2, \
            "Report should have exactly one '=== Pareto Frontier ===' separator"
        pareto_section = parts[1].strip()
        assert len(pareto_section) > 0, "Pareto section is empty"
        lines = [l.strip() for l in pareto_section.split("\n") if l.strip()]
        data_lines = [l for l in lines
                      if any(c.isdigit() for c in l)
                      and not l.startswith("alpha")
                      and not all(c in '-| ' for c in l)]
        assert len(data_lines) >= 1, \
            "Pareto section has no data rows"
