"""
Tests for the benchmark comparison engine.

Verifies output structure, statistical correctness, SQLite persistence,
and edge case handling through output properties — without prescribing
specific internal algorithms.
"""


import pytest
import json
import os
import sys
import sqlite3
import math

sys.path.insert(0, "/app")


@pytest.fixture(scope="module")
def _run_main_pipeline():
    """Run the main comparison once for the module."""
    from benchmark_compare import compare_benchmarks
    output_path = "/tmp/test_main_report.json"
    compare_benchmarks("/data/run_a.json", "/data/run_b.json", output_path)
    return output_path


@pytest.fixture(scope="module")
def main_report(_run_main_pipeline):
    """Load the JSON report from the main comparison."""
    with open(_run_main_pipeline) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def main_db(_run_main_pipeline):
    """Connect to the SQLite DB created by the main comparison."""
    conn = sqlite3.connect("/app/benchmark.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ============================================================
# Output Schema Tests
# ============================================================

class TestOutputSchema:
    def test_top_level_keys(self, main_report):
        for key in ["baseline_label", "candidate_label", "alpha", "metrics", "overall_verdict"]:
            assert key in main_report, f"Missing top-level key: {key}"

    def test_alpha_value(self, main_report):
        assert abs(main_report["alpha"] - 0.05) < 1e-10

    def test_labels(self, main_report):
        assert main_report["baseline_label"] == "baseline"
        assert main_report["candidate_label"] == "candidate"

    def test_metric_names(self, main_report):
        expected = {"wall_time_ns", "cpu_cycles", "cache_misses", "peak_rss_bytes"}
        assert set(main_report["metrics"].keys()) == expected

    def test_run_stats_keys(self, main_report):
        required = {"mean", "median", "std_dev", "q1", "q3", "n", "outlier_indices"}
        for metric_name, m in main_report["metrics"].items():
            for side in ["baseline", "candidate"]:
                for key in required:
                    assert key in m[side], f"Missing {side}.{key} in {metric_name}"

    def test_comparison_keys(self, main_report):
        required = {"mean_diff", "pct_change", "test_statistic", "degrees_of_freedom",
                     "p_value_raw", "p_value_adjusted", "effect_size", "effect_size_class",
                     "ci_lower", "ci_upper", "verdict"}
        for metric_name, m in main_report["metrics"].items():
            for key in required:
                assert key in m["comparison"], f"Missing comparison.{key} in {metric_name}"

    def test_sample_counts(self, main_report):
        for metric_name, m in main_report["metrics"].items():
            assert m["baseline"]["n"] == 20, f"{metric_name}: baseline n != 20"
            assert m["candidate"]["n"] == 20, f"{metric_name}: candidate n != 20"


# ============================================================
# Directional Results Tests
# ============================================================

class TestDirectionalResults:
    def test_wall_time_regression(self, main_report):
        """Candidate wall time is clearly higher than baseline — must detect regression."""
        wt = main_report["metrics"]["wall_time_ns"]
        assert wt["comparison"]["pct_change"] > 0, "Wall time pct_change should be positive (regression)"
        assert wt["comparison"]["p_value_raw"] < 0.05, "Wall time regression should be significant"
        assert wt["comparison"]["verdict"] == "regression"

    def test_cpu_cycles_improvement(self, main_report):
        """Candidate CPU cycles are lower — must detect improvement."""
        cc = main_report["metrics"]["cpu_cycles"]
        assert cc["comparison"]["pct_change"] < 0, "CPU cycles pct_change should be negative (improvement)"
        assert cc["comparison"]["verdict"] == "improvement"

    def test_peak_rss_improvement(self, main_report):
        """Candidate peak RSS is lower — must detect improvement."""
        rss = main_report["metrics"]["peak_rss_bytes"]
        assert rss["comparison"]["pct_change"] < 0, "Peak RSS pct_change should be negative"
        assert rss["comparison"]["verdict"] == "improvement"

    def test_overall_verdict_is_regression(self, main_report):
        """At least one metric regressed, so overall should be regression."""
        assert main_report["overall_verdict"] == "regression"

    def test_mean_diff_sign_matches_pct_change(self, main_report):
        """mean_diff and pct_change should have the same sign."""
        for metric_name, m in main_report["metrics"].items():
            comp = m["comparison"]
            if abs(comp["mean_diff"]) > 1e-10:
                assert (comp["mean_diff"] > 0) == (comp["pct_change"] > 0), \
                    f"{metric_name}: mean_diff and pct_change sign mismatch"


# ============================================================
# Outlier Detection Tests
# ============================================================

class TestOutlierDetection:
    def test_cache_misses_outlier_detected(self, main_report):
        """Candidate cache_misses sample at index 15 (value 18500 vs ~7000 avg) must be flagged."""
        cm = main_report["metrics"]["cache_misses"]
        assert 15 in cm["candidate"]["outlier_indices"], \
            f"Index 15 should be an outlier; got indices: {cm['candidate']['outlier_indices']}"

    def test_baseline_no_extreme_outliers(self, main_report):
        """Baseline data has no extreme outliers — outlier list should be short."""
        for metric_name, m in main_report["metrics"].items():
            assert len(m["baseline"]["outlier_indices"]) <= 2, \
                f"{metric_name}: baseline has too many outliers"


# ============================================================
# Statistical Property Tests
# ============================================================

class TestStatisticalProperties:
    def test_p_value_bounds(self, main_report):
        """All p-values must be in [0, 1]."""
        for metric_name, m in main_report["metrics"].items():
            comp = m["comparison"]
            assert 0 <= comp["p_value_raw"] <= 1, \
                f"{metric_name}: raw p-value {comp['p_value_raw']} out of [0,1]"
            assert 0 <= comp["p_value_adjusted"] <= 1, \
                f"{metric_name}: adjusted p-value {comp['p_value_adjusted']} out of [0,1]"

    def test_adjusted_geq_raw(self, main_report):
        """Adjusted p-values must be >= raw p-values (correction only inflates)."""
        for metric_name, m in main_report["metrics"].items():
            comp = m["comparison"]
            assert comp["p_value_adjusted"] >= comp["p_value_raw"] - 1e-10, \
                f"{metric_name}: adjusted {comp['p_value_adjusted']} < raw {comp['p_value_raw']}"

    def test_ci_ordering(self, main_report):
        """CI lower must be strictly less than CI upper."""
        for metric_name, m in main_report["metrics"].items():
            comp = m["comparison"]
            assert comp["ci_lower"] < comp["ci_upper"], \
                f"{metric_name}: CI [{comp['ci_lower']}, {comp['ci_upper']}] not ordered"

    def test_effect_size_bounds(self, main_report):
        """Non-parametric dominance effect size must be in [-1, 1]."""
        for metric_name, m in main_report["metrics"].items():
            es = m["comparison"]["effect_size"]
            assert -1.0 <= es <= 1.0, f"{metric_name}: effect size {es} out of [-1, 1]"

    def test_effect_size_class_valid(self, main_report):
        valid = {"negligible", "small", "medium", "large"}
        for metric_name, m in main_report["metrics"].items():
            assert m["comparison"]["effect_size_class"] in valid, \
                f"{metric_name}: invalid effect size class '{m['comparison']['effect_size_class']}'"

    def test_wall_time_large_effect(self, main_report):
        """Wall time data has complete separation — effect must be large."""
        wt = main_report["metrics"]["wall_time_ns"]
        assert wt["comparison"]["effect_size_class"] == "large"

    def test_degrees_of_freedom_positive(self, main_report):
        """Degrees of freedom must be positive."""
        for metric_name, m in main_report["metrics"].items():
            df = m["comparison"]["degrees_of_freedom"]
            assert df > 0, f"{metric_name}: degrees_of_freedom {df} <= 0"

    def test_degrees_of_freedom_fractional(self, main_report):
        """For unequal-variance test, df should generally not be an exact integer."""
        # At least one metric should have non-integer df (indicates variance-aware test)
        has_fractional = False
        for metric_name, m in main_report["metrics"].items():
            df = m["comparison"]["degrees_of_freedom"]
            if abs(df - round(df)) > 0.01:
                has_fractional = True
                break
        assert has_fractional, "All df are integers — the test should handle unequal variances"

    def test_std_dev_nonnegative(self, main_report):
        """Standard deviations must be non-negative."""
        for metric_name, m in main_report["metrics"].items():
            for side in ["baseline", "candidate"]:
                assert m[side]["std_dev"] >= 0, \
                    f"{metric_name} {side}: negative std_dev"

    def test_q1_leq_median_leq_q3(self, main_report):
        """Quartiles must be ordered: Q1 <= median <= Q3."""
        for metric_name, m in main_report["metrics"].items():
            for side in ["baseline", "candidate"]:
                assert m[side]["q1"] <= m[side]["median"] <= m[side]["q3"], \
                    f"{metric_name} {side}: quartile ordering violated"


# ============================================================
# SQLite Structure Tests
# ============================================================

class TestSQLiteStructure:
    def test_database_exists(self, main_db):
        assert os.path.exists("/app/benchmark.db"), "SQLite database not found"

    def test_runs_table_count(self, main_db):
        cursor = main_db.execute("SELECT COUNT(*) FROM runs")
        count = cursor.fetchone()[0]
        assert count == 2, f"Expected 2 runs, got {count}"

    def test_samples_table_count(self, main_db):
        cursor = main_db.execute("SELECT COUNT(*) FROM samples")
        count = cursor.fetchone()[0]
        assert count == 40, f"Expected 40 samples (20+20), got {count}"

    def test_metric_stats_table_count(self, main_db):
        cursor = main_db.execute("SELECT COUNT(*) FROM metric_stats")
        count = cursor.fetchone()[0]
        assert count == 8, f"Expected 8 metric_stats (4 metrics x 2 runs), got {count}"

    def test_comparisons_table_count(self, main_db):
        cursor = main_db.execute("SELECT COUNT(*) FROM comparisons")
        count = cursor.fetchone()[0]
        assert count == 4, f"Expected 4 comparisons (4 metrics), got {count}"


# ============================================================
# SQLite Data Integrity Tests
# ============================================================

class TestSQLiteData:
    def test_run_labels(self, main_db):
        cursor = main_db.execute("SELECT label FROM runs ORDER BY id")
        labels = [row[0] for row in cursor.fetchall()]
        assert "baseline" in labels, "Missing 'baseline' run label"
        assert "candidate" in labels, "Missing 'candidate' run label"

    def test_baseline_first_sample(self, main_db):
        """Verify first baseline sample was stored correctly."""
        cursor = main_db.execute(
            "SELECT wall_time_ns FROM samples WHERE run_id = 1 AND sample_index = 0"
        )
        row = cursor.fetchone()
        assert row is not None, "First baseline sample not found"
        assert abs(row[0] - 4850000) < 1, f"Expected 4850000, got {row[0]}"

    def test_candidate_outlier_sample(self, main_db):
        """Verify the outlier sample (index 15, cache_misses=18500) was stored."""
        cursor = main_db.execute(
            "SELECT cache_misses FROM samples WHERE run_id = 2 AND sample_index = 15"
        )
        row = cursor.fetchone()
        assert row is not None, "Candidate sample at index 15 not found"
        assert abs(row[0] - 18500) < 1, f"Expected 18500, got {row[0]}"

    def test_comparison_verdicts_match_report(self, main_db, main_report):
        """SQLite comparison verdicts must match the JSON report."""
        cursor = main_db.execute("SELECT metric_name, verdict FROM comparisons")
        db_verdicts = {row[0]: row[1] for row in cursor.fetchall()}
        for metric_name, m in main_report["metrics"].items():
            assert metric_name in db_verdicts, f"Missing {metric_name} in comparisons table"
            assert db_verdicts[metric_name] == m["comparison"]["verdict"], \
                f"{metric_name}: DB verdict '{db_verdicts[metric_name]}' != report verdict '{m['comparison']['verdict']}'"

    def test_metric_stats_stored(self, main_db):
        """Verify metric statistics are stored for all metrics and both runs."""
        cursor = main_db.execute(
            "SELECT run_id, metric_name FROM metric_stats ORDER BY run_id, metric_name"
        )
        rows = cursor.fetchall()
        metrics_by_run = {}
        for row in rows:
            run_id = row[0]
            if run_id not in metrics_by_run:
                metrics_by_run[run_id] = set()
            metrics_by_run[run_id].add(row[1])
        expected = {"wall_time_ns", "cpu_cycles", "cache_misses", "peak_rss_bytes"}
        for run_id in [1, 2]:
            assert run_id in metrics_by_run, f"No metric_stats for run_id {run_id}"
            assert metrics_by_run[run_id] == expected, \
                f"run_id {run_id}: expected metrics {expected}, got {metrics_by_run[run_id]}"

    def test_comparison_p_values_in_db(self, main_db):
        """Verify p-values stored in DB are valid."""
        cursor = main_db.execute("SELECT metric_name, p_value_raw, p_value_adjusted FROM comparisons")
        for row in cursor.fetchall():
            assert 0 <= row[1] <= 1, f"{row[0]}: raw p-value {row[1]} out of [0,1]"
            assert 0 <= row[2] <= 1, f"{row[0]}: adjusted p-value {row[2]} out of [0,1]"
            assert row[2] >= row[1] - 1e-10, f"{row[0]}: adjusted < raw"


# ============================================================
# Edge Case Tests
# ============================================================

class TestEdgeCases:
    def test_small_samples(self):
        """Engine must handle n=3 samples without crashing."""
        from benchmark_compare import compare_benchmarks
        output_path = "/tmp/test_edge_small.json"
        compare_benchmarks("/data/edge_small.json", "/data/edge_small.json", output_path)
        assert os.path.exists(output_path)
        with open(output_path) as f:
            report = json.load(f)
        for metric_name, m in report["metrics"].items():
            assert 0 <= m["comparison"]["p_value_raw"] <= 1, \
                f"{metric_name}: p-value out of range with small samples"

    def test_zero_variance(self):
        """Engine must handle zero-variance metrics (e.g., constant values) without crashing."""
        from benchmark_compare import compare_benchmarks
        output_path = "/tmp/test_edge_zv.json"
        compare_benchmarks("/data/edge_zero_var.json", "/data/edge_small.json", output_path)
        assert os.path.exists(output_path)
        with open(output_path) as f:
            report = json.load(f)
        for metric_name, m in report["metrics"].items():
            assert 0 <= m["comparison"]["p_value_raw"] <= 1, \
                f"{metric_name}: p-value out of range with zero variance"

    def test_identical_inputs_no_change(self):
        """Comparing a file to itself must yield no_change for all metrics."""
        from benchmark_compare import compare_benchmarks
        output_path = "/tmp/test_identical.json"
        compare_benchmarks("/data/run_a.json", "/data/run_a.json", output_path)
        with open(output_path) as f:
            report = json.load(f)
        assert report["overall_verdict"] == "no_change"
        for metric_name, m in report["metrics"].items():
            assert m["comparison"]["verdict"] == "no_change", \
                f"{metric_name}: verdict should be no_change for identical data"
            assert abs(m["comparison"]["pct_change"]) < 1e-10
            assert abs(m["comparison"]["mean_diff"]) < 1e-10

    def test_identical_inputs_p_values_high(self):
        """Identical inputs must produce p-values close to 1.0."""
        from benchmark_compare import compare_benchmarks
        output_path = "/tmp/test_identical_p.json"
        compare_benchmarks("/data/run_a.json", "/data/run_a.json", output_path)
        with open(output_path) as f:
            report = json.load(f)
        for metric_name, m in report["metrics"].items():
            assert m["comparison"]["p_value_raw"] >= 0.99, \
                f"{metric_name}: p-value for identical data should be ~1.0, got {m['comparison']['p_value_raw']}"

    def test_identical_inputs_negligible_effect(self):
        """Identical inputs must produce negligible effect size."""
        from benchmark_compare import compare_benchmarks
        output_path = "/tmp/test_identical_es.json"
        compare_benchmarks("/data/run_a.json", "/data/run_a.json", output_path)
        with open(output_path) as f:
            report = json.load(f)
        for metric_name, m in report["metrics"].items():
            assert abs(m["comparison"]["effect_size"]) < 0.01, \
                f"{metric_name}: effect size for identical data should be ~0, got {m['comparison']['effect_size']}"
            assert m["comparison"]["effect_size_class"] == "negligible"

    def test_identical_inputs_ci_contains_zero(self):
        """CI for identical inputs must contain zero."""
        from benchmark_compare import compare_benchmarks
        output_path = "/tmp/test_identical_ci.json"
        compare_benchmarks("/data/run_a.json", "/data/run_a.json", output_path)
        with open(output_path) as f:
            report = json.load(f)
        for metric_name, m in report["metrics"].items():
            comp = m["comparison"]
            assert comp["ci_lower"] <= 0 <= comp["ci_upper"], \
                f"{metric_name}: CI [{comp['ci_lower']}, {comp['ci_upper']}] should contain 0 for identical data"

    def test_output_structure_edge_cases(self):
        """Edge case outputs must still conform to the full schema."""
        from benchmark_compare import compare_benchmarks
        output_path = "/tmp/test_edge_schema.json"
        compare_benchmarks("/data/edge_small.json", "/data/edge_zero_var.json", output_path)
        with open(output_path) as f:
            report = json.load(f)
        required_comp_keys = {"mean_diff", "pct_change", "test_statistic", "degrees_of_freedom",
                              "p_value_raw", "p_value_adjusted", "effect_size", "effect_size_class",
                              "ci_lower", "ci_upper", "verdict"}
        for metric_name, m in report["metrics"].items():
            for key in required_comp_keys:
                assert key in m["comparison"], f"Missing comparison.{key} in {metric_name} (edge case)"
