
"""
Verification tests for the SGLang SLO burn-rate alert evaluator.
Tests promtool rule validation, jq interval computation, analyzer percentiles,
severity classification, and error-budget burn-rate calculations.

Expected values are derived from the Prometheus histogram_quantile algorithm
applied to delta histogram data computed from the provided scrape files.
"""

import json
import math
import os
import subprocess
import pytest


REPORT_PATH = "/app/report.json"
INTERVALS_DIR = "/app/intervals"
RULES_PATH = "/app/rules/sglang_slos.yml"


@pytest.fixture(scope="module")
def report():
    assert os.path.isfile(REPORT_PATH), f"{REPORT_PATH} does not exist"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ---------------------------------------------------------------------------
# promtool rule validation
# ---------------------------------------------------------------------------

class TestPromtoolRules:
    def test_rules_check_passes(self):
        result = subprocess.run(
            ["promtool", "check", "rules", RULES_PATH],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"promtool check rules failed:\n{result.stdout}\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# jq interval output validation
# ---------------------------------------------------------------------------

class TestIntervalFiles:
    @pytest.fixture(autouse=True)
    def _load_intervals(self):
        self.intervals = []
        for i in range(3):
            path = f"{INTERVALS_DIR}/interval_{i}.json"
            assert os.path.isfile(path), f"{path} does not exist"
            with open(path) as f:
                self.intervals.append(json.load(f))

    def test_interval_0_ttft_first_bucket_delta(self):
        ttft = self.intervals[0]["histogram_deltas"]["sglang:time_to_first_token_seconds"]
        first = ttft["delta_buckets"][0]
        assert math.isclose(first["delta"], 16.0, rel_tol=0.01)

    def test_interval_0_request_count_delta(self):
        ttft = self.intervals[0]["histogram_deltas"]["sglang:time_to_first_token_seconds"]
        assert math.isclose(ttft["request_count_delta"], 80.0, rel_tol=0.01)

    def test_interval_1_request_count_delta(self):
        ttft = self.intervals[1]["histogram_deltas"]["sglang:time_to_first_token_seconds"]
        assert math.isclose(ttft["request_count_delta"], 40.0, rel_tol=0.01)

    def test_interval_2_request_count_delta(self):
        ttft = self.intervals[2]["histogram_deltas"]["sglang:time_to_first_token_seconds"]
        assert math.isclose(ttft["request_count_delta"], 30.0, rel_tol=0.01)

    def test_interval_2_histogram_reset_detected(self):
        ttft = self.intervals[2]["histogram_deltas"]["sglang:time_to_first_token_seconds"]
        assert ttft["reset_detected"] is True

    def test_interval_2_counter_reset_detected(self):
        assert self.intervals[2]["counter_reset_detected"] is True

    def test_interval_0_no_reset(self):
        assert self.intervals[0]["counter_reset_detected"] is False


# ---------------------------------------------------------------------------
# Report structure tests
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_has_intervals(self, report):
        assert "intervals" in report
        assert isinstance(report["intervals"], list)

    def test_has_summary(self, report):
        assert "summary" in report
        assert isinstance(report["summary"], dict)

    def test_interval_count(self, report):
        assert len(report["intervals"]) == 3

    def test_interval_fields(self, report):
        required = {
            "start_ts", "end_ts", "duration_sec",
            "counter_reset_detected",
            "request_rate_per_sec",
            "prompt_token_rate_per_sec",
            "generation_token_rate_per_sec",
            "percentiles", "slo_verdicts", "severity",
        }
        for i, interval in enumerate(report["intervals"]):
            missing = required - set(interval.keys())
            assert not missing, f"Interval {i} missing fields: {missing}"

    def test_percentile_fields(self, report):
        required = {"ttft_p99", "e2e_p99", "tpot_p95"}
        for i, interval in enumerate(report["intervals"]):
            missing = required - set(interval["percentiles"].keys())
            assert not missing, f"Interval {i} percentiles missing: {missing}"

    def test_slo_verdict_fields(self, report):
        required = {"ttft_p99", "e2e_p99", "tpot_p95", "request_throughput"}
        for i, interval in enumerate(report["intervals"]):
            missing = required - set(interval["slo_verdicts"].keys())
            assert not missing, f"Interval {i} slo_verdicts missing: {missing}"

    def test_summary_fields(self, report):
        required = {
            "total_intervals", "intervals_passing_all_slos",
            "intervals_with_violations", "violated_slo_names",
            "error_budget",
        }
        missing = required - set(report["summary"].keys())
        assert not missing, f"Summary missing fields: {missing}"

    def test_error_budget_fields(self, report):
        required = {
            "observation_window_seconds",
            "per_slo_burn_rates",
            "overall_burn_rate",
        }
        eb = report["summary"]["error_budget"]
        missing = required - set(eb.keys())
        assert not missing, f"Error budget missing fields: {missing}"

    def test_burn_rate_slo_fields(self, report):
        required = {"ttft_p99", "e2e_p99", "tpot_p95", "request_throughput"}
        br = report["summary"]["error_budget"]["per_slo_burn_rates"]
        missing = required - set(br.keys())
        assert not missing, f"Burn rate missing SLO fields: {missing}"


# ---------------------------------------------------------------------------
# Interval 0: scrapes 1718000000 -> 1718000030  (normal, all SLOs pass)
# ---------------------------------------------------------------------------

class TestInterval0:
    @pytest.fixture(autouse=True)
    def _interval(self, report):
        self.iv = report["intervals"][0]

    def test_timestamps(self):
        assert self.iv["start_ts"] == 1718000000
        assert self.iv["end_ts"] == 1718000030
        assert self.iv["duration_sec"] == 30

    def test_no_counter_reset(self):
        assert self.iv["counter_reset_detected"] is False

    # Request rate = 80 requests / 30s = 2.6667
    def test_request_rate(self):
        assert math.isclose(self.iv["request_rate_per_sec"], 80.0 / 30.0, rel_tol=0.01)

    # Prompt token rate = 16000 / 30 = 533.33
    def test_prompt_token_rate(self):
        assert math.isclose(self.iv["prompt_token_rate_per_sec"], 16000.0 / 30.0, rel_tol=0.01)

    # Gen token rate = 14000 / 30 = 466.67
    def test_gen_token_rate(self):
        assert math.isclose(self.iv["generation_token_rate_per_sec"], 14000.0 / 30.0, rel_tol=0.01)

    # TTFT p99 = 2.5 + 2.5 * (79.2 - 79) / (80 - 79) = 3.0
    def test_ttft_p99(self):
        assert math.isclose(self.iv["percentiles"]["ttft_p99"], 3.0, abs_tol=0.05)

    # E2E p99 = 30.0 + 30.0 * (79.2 - 74) / (80 - 74) = 56.0
    def test_e2e_p99(self):
        assert math.isclose(self.iv["percentiles"]["e2e_p99"], 56.0, abs_tol=0.1)

    # TPOT p95 = 0.075 + 0.025 * 60000/62000 = 0.09919...
    def test_tpot_p95(self):
        expected = 0.075 + 0.025 * (60000.0 / 62000.0)
        assert math.isclose(self.iv["percentiles"]["tpot_p95"], expected, abs_tol=0.003)

    def test_all_slos_pass(self):
        for name, verdict in self.iv["slo_verdicts"].items():
            assert verdict is True, f"SLO {name} should pass in interval 0"

    def test_severity_nominal(self):
        assert self.iv["severity"] == "nominal"


# ---------------------------------------------------------------------------
# Interval 1: scrapes 1718000030 -> 1718000060  (degraded, TTFT + TPOT fail)
# ---------------------------------------------------------------------------

class TestInterval1:
    @pytest.fixture(autouse=True)
    def _interval(self, report):
        self.iv = report["intervals"][1]

    def test_timestamps(self):
        assert self.iv["start_ts"] == 1718000030
        assert self.iv["end_ts"] == 1718000060
        assert self.iv["duration_sec"] == 30

    def test_no_counter_reset(self):
        assert self.iv["counter_reset_detected"] is False

    # Request rate = 40 / 30 = 1.333
    def test_request_rate(self):
        assert math.isclose(self.iv["request_rate_per_sec"], 40.0 / 30.0, rel_tol=0.01)

    # Prompt token rate = 8000 / 30 = 266.67
    def test_prompt_token_rate(self):
        assert math.isclose(self.iv["prompt_token_rate_per_sec"], 8000.0 / 30.0, rel_tol=0.01)

    # Gen token rate = 6000 / 30 = 200.0
    def test_gen_token_rate(self):
        assert math.isclose(self.iv["generation_token_rate_per_sec"], 200.0, rel_tol=0.01)

    # TTFT p99 = 10.0 + 20.0 * (39.6 - 35) / (40 - 35) = 28.4
    def test_ttft_p99(self):
        assert math.isclose(self.iv["percentiles"]["ttft_p99"], 28.4, abs_tol=0.1)

    # E2E p99 = 30.0 + 30.0 * (39.6 - 30) / (40 - 30) = 58.8
    def test_e2e_p99(self):
        assert math.isclose(self.iv["percentiles"]["e2e_p99"], 58.8, abs_tol=0.1)

    # TPOT p95 = 0.15 + 0.05 * 5000/10000 = 0.175
    def test_tpot_p95(self):
        assert math.isclose(self.iv["percentiles"]["tpot_p95"], 0.175, abs_tol=0.005)

    # TTFT p99 = 28.4 >= 5.0 -> FAIL
    def test_ttft_slo_fails(self):
        assert self.iv["slo_verdicts"]["ttft_p99"] is False

    # E2E p99 = 58.8 < 60.0 -> PASS
    def test_e2e_slo_passes(self):
        assert self.iv["slo_verdicts"]["e2e_p99"] is True

    # TPOT p95 = 0.175 >= 0.1 -> FAIL
    def test_tpot_slo_fails(self):
        assert self.iv["slo_verdicts"]["tpot_p95"] is False

    # Request throughput = 1.333 >= 1.0 -> PASS
    def test_throughput_slo_passes(self):
        assert self.iv["slo_verdicts"]["request_throughput"] is True

    # TTFT p99 = 28.4 >= 2 * 5.0 = 10.0 -> critical
    def test_severity_critical(self):
        assert self.iv["severity"] == "critical"


# ---------------------------------------------------------------------------
# Interval 2: scrapes 1718000060 -> 1718000090  (counter reset, recovery)
# ---------------------------------------------------------------------------

class TestInterval2:
    @pytest.fixture(autouse=True)
    def _interval(self, report):
        self.iv = report["intervals"][2]

    def test_timestamps(self):
        assert self.iv["start_ts"] == 1718000060
        assert self.iv["end_ts"] == 1718000090
        assert self.iv["duration_sec"] == 30

    def test_counter_reset_detected(self):
        assert self.iv["counter_reset_detected"] is True

    # Request rate = 30 / 30 = 1.0
    def test_request_rate(self):
        assert math.isclose(self.iv["request_rate_per_sec"], 1.0, rel_tol=0.01)

    # Prompt token rate = 5000 / 30 = 166.67
    def test_prompt_token_rate(self):
        assert math.isclose(self.iv["prompt_token_rate_per_sec"], 5000.0 / 30.0, rel_tol=0.01)

    # Gen token rate = 4000 / 30 = 133.33
    def test_gen_token_rate(self):
        assert math.isclose(self.iv["generation_token_rate_per_sec"], 4000.0 / 30.0, rel_tol=0.01)

    # TTFT p99 = 1.0 + 1.5 * (29.7 - 29) / (30 - 29) = 2.05
    def test_ttft_p99(self):
        assert math.isclose(self.iv["percentiles"]["ttft_p99"], 2.05, abs_tol=0.05)

    # E2E p99 = 30.0 + 30.0 * (29.7 - 29) / (30 - 29) = 51.0
    def test_e2e_p99(self):
        assert math.isclose(self.iv["percentiles"]["e2e_p99"], 51.0, abs_tol=0.1)

    # TPOT p95 = 0.075 + 0.025 * 2000/2200 = 0.09773
    def test_tpot_p95(self):
        expected = 0.075 + 0.025 * (2000.0 / 2200.0)
        assert math.isclose(self.iv["percentiles"]["tpot_p95"], expected, abs_tol=0.003)

    def test_all_slos_pass(self):
        for name, verdict in self.iv["slo_verdicts"].items():
            assert verdict is True, f"SLO {name} should pass in interval 2"

    def test_severity_nominal(self):
        assert self.iv["severity"] == "nominal"


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------

class TestSummary:
    @pytest.fixture(autouse=True)
    def _summary(self, report):
        self.summary = report["summary"]

    def test_total_intervals(self):
        assert self.summary["total_intervals"] == 3

    def test_passing_intervals(self):
        assert self.summary["intervals_passing_all_slos"] == 2

    def test_violating_intervals(self):
        assert self.summary["intervals_with_violations"] == 1

    def test_violated_slo_names(self):
        violated = sorted(self.summary["violated_slo_names"])
        assert violated == ["tpot_p95", "ttft_p99"]


# ---------------------------------------------------------------------------
# Error-budget burn-rate tests
# ---------------------------------------------------------------------------

class TestErrorBudget:
    @pytest.fixture(autouse=True)
    def _budget(self, report):
        self.eb = report["summary"]["error_budget"]

    def test_observation_window(self):
        assert self.eb["observation_window_seconds"] == 90

    # burn_rate = (1/3) / (1 - 0.999) = (1/3) / 0.001 = 333.333...
    def test_ttft_burn_rate(self):
        expected = (1.0 / 3.0) / 0.001
        assert math.isclose(
            self.eb["per_slo_burn_rates"]["ttft_p99"], expected, rel_tol=0.01
        ), f"Expected ttft burn rate ~{expected}, got {self.eb['per_slo_burn_rates']['ttft_p99']}"

    def test_tpot_burn_rate(self):
        expected = (1.0 / 3.0) / 0.001
        assert math.isclose(
            self.eb["per_slo_burn_rates"]["tpot_p95"], expected, rel_tol=0.01
        ), f"Expected tpot burn rate ~{expected}, got {self.eb['per_slo_burn_rates']['tpot_p95']}"

    def test_e2e_burn_rate_zero(self):
        assert self.eb["per_slo_burn_rates"]["e2e_p99"] == 0.0

    def test_throughput_burn_rate_zero(self):
        assert self.eb["per_slo_burn_rates"]["request_throughput"] == 0.0

    def test_overall_burn_rate(self):
        expected = (1.0 / 3.0) / 0.001
        assert math.isclose(
            self.eb["overall_burn_rate"], expected, rel_tol=0.01
        ), f"Expected overall burn rate ~{expected}, got {self.eb['overall_burn_rate']}"

    def test_overall_is_max_of_per_slo(self):
        rates = self.eb["per_slo_burn_rates"]
        max_rate = max(rates.values())
        assert math.isclose(
            self.eb["overall_burn_rate"], max_rate, rel_tol=0.001
        ), "Overall burn rate should be the maximum of per-SLO rates"


# ---------------------------------------------------------------------------
# Severity classification tests (cross-interval)
# ---------------------------------------------------------------------------

class TestSeverityClassification:
    def test_severity_values_valid(self, report):
        valid = {"nominal", "degraded", "critical"}
        for i, iv in enumerate(report["intervals"]):
            assert iv["severity"] in valid, (
                f"Interval {i} severity '{iv['severity']}' not in {valid}"
            )

    def test_nominal_intervals_have_all_passing(self, report):
        for i, iv in enumerate(report["intervals"]):
            if iv["severity"] == "nominal":
                assert all(iv["slo_verdicts"].values()), (
                    f"Interval {i} is nominal but has failing SLOs"
                )

    def test_critical_has_2x_violation(self, report):
        """Interval 1 is critical because TTFT p99 = 28.4 >= 2 * 5.0 = 10.0"""
        iv = report["intervals"][1]
        assert iv["severity"] == "critical"
        # Verify the TTFT value that triggers critical classification
        ttft = iv["percentiles"]["ttft_p99"]
        assert ttft >= 10.0, (
            f"Critical interval should have TTFT >= 2x threshold (10.0), got {ttft}"
        )

    def test_severity_distribution(self, report):
        severities = [iv["severity"] for iv in report["intervals"]]
        assert severities.count("nominal") == 2
        assert severities.count("critical") == 1
        assert severities.count("degraded") == 0
