
import json
import math
import os
import re
import subprocess

import pytest

REPORT_PATH = "/app/report.json"
CONFIG_PATH = "/app/prometheus/prometheus.yml"
RULES_DIR = "/app/prometheus/rules"
REL_TOL = 0.001  # 0.1% relative tolerance for float comparisons


def load_report():
    with open(REPORT_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Expected p99 values computed via standard histogram percentile algorithm
# (these are unchanged because summing per-instance bucket counts across
#  all 3 replicas reconstructs the original aggregate distribution)
# ---------------------------------------------------------------------------

EXPECTED_TTFT_P99 = [
    2.5 + 2.5 * 15 / 18,
    5.0 + 2.5 * 5 / 10,
    10.0 + 5.0 * 15 / 17,
    30.0,
    2.5 + 2.5 * 22 / 23,
]

EXPECTED_E2E_P99 = [
    30.0 + 10.0 * 15 / 18,
    40.0 + 10.0 * 2 / 8,
    50.0 + 10.0 * 5 / 11,
    60.0,
    30.0 + 10.0 * 18 / 20,
]

EXPECTED_TPOT_P99 = [
    0.15 + 0.05 * 200 / 800,
    0.15 + 0.05 * 1000 / 1200,
    0.2 + 0.1 * 1000 / 1500,
    0.3 + 0.1 * 500 / 900,
    0.15 + 0.05 * 500 / 1000,
]

EXPECTED_COMPLIANT = [True, True, False, False, True]

EXPECTED_QUEUE = [50.0, 200.0, 1500.0, 3000.0, 100.0]
EXPECTED_CACHE = [0.85, 0.65, 0.05, 0.01, 0.70]
EXPECTED_THROUGHPUT = [120.5, 100.2, 45.3, 25.7, 95.8]


# ===== Prometheus configuration validation tests =====

class TestPrometheusConfig:
    def test_config_exists(self):
        assert os.path.exists(CONFIG_PATH), "prometheus.yml not found at /app/prometheus/prometheus.yml"

    def test_config_passes_promtool_validation(self):
        result = subprocess.run(
            ["promtool", "check", "config", CONFIG_PATH],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"promtool check config failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ===== Prometheus recording rules validation tests =====

class TestPrometheusRules:
    def test_rules_directory_exists(self):
        assert os.path.isdir(RULES_DIR), "Rules directory /app/prometheus/rules/ not found"

    def test_rules_files_present(self):
        yml_files = [
            f for f in os.listdir(RULES_DIR) if f.endswith((".yml", ".yaml"))
        ]
        assert len(yml_files) > 0, "No .yml rule files found in /app/prometheus/rules/"

    def test_rules_pass_promtool_validation(self):
        for fname in os.listdir(RULES_DIR):
            if not fname.endswith((".yml", ".yaml")):
                continue
            path = os.path.join(RULES_DIR, fname)
            result = subprocess.run(
                ["promtool", "check", "rules", path],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, (
                f"promtool check rules failed for {fname}:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

    def test_rules_contain_histogram_percentile_expressions(self):
        all_content = ""
        for fname in os.listdir(RULES_DIR):
            if fname.endswith((".yml", ".yaml")):
                with open(os.path.join(RULES_DIR, fname)) as fh:
                    all_content += fh.read()
        assert "histogram_quantile" in all_content, (
            "Rules must define histogram percentile computations using histogram_quantile()"
        )

    def test_rules_contain_multi_instance_aggregation(self):
        """Rules must aggregate histogram buckets across instances before computing percentiles."""
        all_content = ""
        for fname in os.listdir(RULES_DIR):
            if fname.endswith((".yml", ".yaml")):
                with open(os.path.join(RULES_DIR, fname)) as fh:
                    all_content += fh.read()
        assert re.search(r'sum\s*(by|without)\s*\(', all_content, re.IGNORECASE), (
            "Recording rules must aggregate histograms across instances "
            "(e.g., sum by (le)) before computing percentiles"
        )


# ===== Report structure tests =====

class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "report.json not found at /app/report.json"

    def test_valid_json(self):
        report = load_report()
        assert isinstance(report, dict)

    def test_has_snapshots(self):
        report = load_report()
        assert "snapshots" in report
        assert len(report["snapshots"]) == 5

    def test_has_error_budget(self):
        report = load_report()
        assert "error_budget" in report

    def test_has_overall_healthy(self):
        report = load_report()
        assert "overall_healthy" in report

    def test_snapshot_fields(self):
        report = load_report()
        required = {
            "file", "ttft_p99", "e2e_p99", "tpot_p99",
            "queue_depth", "cache_hit_rate", "gen_throughput",
            "slo_violations", "compliant",
        }
        for i, snap in enumerate(report["snapshots"]):
            missing = required - set(snap.keys())
            assert not missing, f"Snapshot {i+1} missing fields: {missing}"


# ===== Percentile accuracy tests =====

class TestPercentileAccuracy:
    """Verify p99 values match expected within tolerance."""

    def test_ttft_p99(self):
        report = load_report()
        for i, snap in enumerate(report["snapshots"]):
            expected = EXPECTED_TTFT_P99[i]
            actual = snap["ttft_p99"]
            assert math.isclose(actual, expected, rel_tol=REL_TOL), (
                f"Snapshot {i+1} TTFT p99: expected {expected:.6f}, got {actual:.6f}"
            )

    def test_e2e_p99(self):
        report = load_report()
        for i, snap in enumerate(report["snapshots"]):
            expected = EXPECTED_E2E_P99[i]
            actual = snap["e2e_p99"]
            assert math.isclose(actual, expected, rel_tol=REL_TOL), (
                f"Snapshot {i+1} E2E p99: expected {expected:.6f}, got {actual:.6f}"
            )

    def test_tpot_p99(self):
        report = load_report()
        for i, snap in enumerate(report["snapshots"]):
            expected = EXPECTED_TPOT_P99[i]
            actual = snap["tpot_p99"]
            assert math.isclose(actual, expected, rel_tol=REL_TOL), (
                f"Snapshot {i+1} TPOT p99: expected {expected:.6f}, got {actual:.6f}"
            )


# ===== Gauge extraction tests =====

class TestGaugeValues:
    def test_queue_depth(self):
        report = load_report()
        for i, snap in enumerate(report["snapshots"]):
            assert math.isclose(snap["queue_depth"], EXPECTED_QUEUE[i], rel_tol=REL_TOL), (
                f"Snapshot {i+1} queue_depth"
            )

    def test_cache_hit_rate(self):
        report = load_report()
        for i, snap in enumerate(report["snapshots"]):
            assert math.isclose(snap["cache_hit_rate"], EXPECTED_CACHE[i], rel_tol=REL_TOL), (
                f"Snapshot {i+1} cache_hit_rate"
            )

    def test_gen_throughput(self):
        report = load_report()
        for i, snap in enumerate(report["snapshots"]):
            assert math.isclose(snap["gen_throughput"], EXPECTED_THROUGHPUT[i], rel_tol=REL_TOL), (
                f"Snapshot {i+1} gen_throughput"
            )


# ===== SLO compliance tests =====

class TestSLOCompliance:
    def test_overall_compliance_per_snapshot(self):
        report = load_report()
        for i, snap in enumerate(report["snapshots"]):
            assert snap["compliant"] == EXPECTED_COMPLIANT[i], (
                f"Snapshot {i+1}: expected compliant={EXPECTED_COMPLIANT[i]}, "
                f"got {snap['compliant']}"
            )

    def test_snapshot_1_no_violations(self):
        report = load_report()
        assert report["snapshots"][0]["slo_violations"] == []

    def test_snapshot_2_no_violations(self):
        report = load_report()
        assert report["snapshots"][1]["slo_violations"] == []

    def test_snapshot_3_violations(self):
        """Snapshot 3: TTFT, queue, cache, throughput violated; E2E and TPOT pass."""
        report = load_report()
        violations = set(report["snapshots"][2]["slo_violations"])
        assert "ttft_p99" in violations
        assert "queue_depth" in violations
        assert "cache_hit_rate" in violations
        assert "gen_throughput" in violations
        assert "e2e_p99" not in violations
        assert "tpot_p99" not in violations

    def test_snapshot_4_all_violated(self):
        """Snapshot 4: all six SLOs violated."""
        report = load_report()
        violations = set(report["snapshots"][3]["slo_violations"])
        expected = {
            "ttft_p99", "e2e_p99", "tpot_p99",
            "queue_depth", "cache_hit_rate", "gen_throughput",
        }
        assert violations == expected, f"Expected all SLO violations, got {violations}"

    def test_snapshot_5_no_violations(self):
        report = load_report()
        assert report["snapshots"][4]["slo_violations"] == []


# ===== Error budget tests =====

class TestErrorBudget:
    def test_ttft_over_budget(self):
        eb = load_report()["error_budget"]
        assert eb["ttft_p99"]["within_budget"] is False
        assert math.isclose(eb["ttft_p99"]["violation_pct"], 40.0, abs_tol=0.1)

    def test_e2e_within_budget(self):
        eb = load_report()["error_budget"]
        assert eb["e2e_p99"]["within_budget"] is True
        assert math.isclose(eb["e2e_p99"]["violation_pct"], 20.0, abs_tol=0.1)

    def test_tpot_within_budget(self):
        eb = load_report()["error_budget"]
        assert eb["tpot_p99"]["within_budget"] is True
        assert math.isclose(eb["tpot_p99"]["violation_pct"], 20.0, abs_tol=0.1)

    def test_queue_over_budget(self):
        eb = load_report()["error_budget"]
        assert eb["queue_depth"]["within_budget"] is False
        assert math.isclose(eb["queue_depth"]["violation_pct"], 40.0, abs_tol=0.1)

    def test_cache_over_budget(self):
        eb = load_report()["error_budget"]
        assert eb["cache_hit_rate"]["within_budget"] is False
        assert math.isclose(eb["cache_hit_rate"]["violation_pct"], 40.0, abs_tol=0.1)

    def test_throughput_over_budget(self):
        eb = load_report()["error_budget"]
        assert eb["gen_throughput"]["within_budget"] is False
        assert math.isclose(eb["gen_throughput"]["violation_pct"], 40.0, abs_tol=0.1)

    def test_overall_not_healthy(self):
        report = load_report()
        assert report["overall_healthy"] is False
