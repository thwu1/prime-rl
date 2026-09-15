
import json
import os
import subprocess
import pytest
import yaml


@pytest.fixture(scope="session")
def report():
    """Load the generated report."""
    report_path = "/app/report.json"
    assert os.path.exists(report_path), "report.json was not created"
    with open(report_path) as f:
        return json.load(f)


def approx(expected, rel_tol=0.02):
    """Check approximate equality with 2% relative tolerance."""
    return pytest.approx(expected, rel=rel_tol)


# ---------------------------------------------------------------------------
# Counter rate tests
# ---------------------------------------------------------------------------

class TestCounterRates:
    def test_has_counter_rates(self, report):
        assert "counter_rates" in report

    def test_prompt_tokens_rate_interval_0_1(self, report):
        rates = report["counter_rates"]
        metric = "sglang:prompt_tokens_total"
        assert metric in rates
        assert rates[metric]["interval_0_1"] == approx(1000.0)

    def test_prompt_tokens_rate_interval_1_2_counter_reset(self, report):
        rates = report["counter_rates"]
        metric = "sglang:prompt_tokens_total"
        assert rates[metric]["interval_1_2"] == approx(416.6667)

    def test_generation_tokens_rate_interval_0_1(self, report):
        rates = report["counter_rates"]
        metric = "sglang:generation_tokens_total"
        assert metric in rates
        assert rates[metric]["interval_0_1"] == approx(600.0)

    def test_generation_tokens_rate_interval_1_2(self, report):
        rates = report["counter_rates"]
        metric = "sglang:generation_tokens_total"
        assert rates[metric]["interval_1_2"] == approx(400.0)


# ---------------------------------------------------------------------------
# Interval percentile tests — TTFT
# ---------------------------------------------------------------------------

class TestIntervalPercentilesTTFT:
    METRIC = "sglang:time_to_first_token_seconds"

    def _get(self, report, interval, pct):
        return report["interval_percentiles"][self.METRIC][interval][pct]

    def test_ttft_interval_0_1_p50(self, report):
        assert self._get(report, "interval_0_1", "p50") == approx(0.23333)

    def test_ttft_interval_0_1_p95(self, report):
        assert self._get(report, "interval_0_1", "p95") == approx(0.88571)

    def test_ttft_interval_0_1_p99(self, report):
        assert self._get(report, "interval_0_1", "p99") == approx(1.8)

    def test_ttft_interval_1_2_p50(self, report):
        assert self._get(report, "interval_1_2", "p50") == approx(1.66832)

    def test_ttft_interval_1_2_p95(self, report):
        assert self._get(report, "interval_1_2", "p95") == approx(4.46144)

    def test_ttft_interval_1_2_p99(self, report):
        assert self._get(report, "interval_1_2", "p99") == approx(4.96676)


# ---------------------------------------------------------------------------
# Interval percentile tests — E2E latency
# ---------------------------------------------------------------------------

class TestIntervalPercentilesE2E:
    METRIC = "sglang:e2e_request_latency_seconds"

    def _get(self, report, interval, pct):
        return report["interval_percentiles"][self.METRIC][interval][pct]

    def test_e2e_interval_0_1_p50(self, report):
        assert self._get(report, "interval_0_1", "p50") == approx(8.125)

    def test_e2e_interval_0_1_p95(self, report):
        assert self._get(report, "interval_0_1", "p95") == approx(29.0)

    def test_e2e_interval_0_1_p99(self, report):
        assert self._get(report, "interval_0_1", "p99") == approx(48.5)

    def test_e2e_interval_1_2_p50(self, report):
        assert self._get(report, "interval_1_2", "p50") == approx(38.65385)

    def test_e2e_interval_1_2_p95(self, report):
        assert self._get(report, "interval_1_2", "p95") == approx(57.46479)

    def test_e2e_interval_1_2_p99(self, report):
        assert self._get(report, "interval_1_2", "p99") == approx(59.60563)


# ---------------------------------------------------------------------------
# SLO evaluation tests
# ---------------------------------------------------------------------------

class TestSLOEvaluation:
    def test_has_slo_evaluation(self, report):
        assert "slo_evaluation" in report

    def test_ttft_slo_interval_results(self, report):
        slo = report["slo_evaluation"]["ttft_p99"]
        assert slo["interval_results"] == [True, False]

    def test_ttft_slo_compliance(self, report):
        slo = report["slo_evaluation"]["ttft_p99"]
        assert slo["compliance_ratio"] == approx(0.5)

    def test_ttft_slo_burn_rate(self, report):
        slo = report["slo_evaluation"]["ttft_p99"]
        assert slo["burn_rate"] == approx(50.0)

    def test_ttft_slo_alert_critical(self, report):
        slo = report["slo_evaluation"]["ttft_p99"]
        assert slo["alert_level"] == "critical"

    def test_e2e_slo_interval_results(self, report):
        slo = report["slo_evaluation"]["e2e_p95"]
        assert slo["interval_results"] == [True, False]

    def test_e2e_slo_compliance(self, report):
        slo = report["slo_evaluation"]["e2e_p95"]
        assert slo["compliance_ratio"] == approx(0.5)

    def test_e2e_slo_burn_rate(self, report):
        slo = report["slo_evaluation"]["e2e_p95"]
        assert slo["burn_rate"] == approx(100.0)

    def test_e2e_slo_alert_critical(self, report):
        slo = report["slo_evaluation"]["e2e_p95"]
        assert slo["alert_level"] == "critical"


# ---------------------------------------------------------------------------
# Structural / sanity tests
# ---------------------------------------------------------------------------

class TestStructure:
    def test_report_is_valid_json(self, report):
        assert isinstance(report, dict)

    def test_has_all_top_level_keys(self, report):
        for key in ["counter_rates", "interval_percentiles", "slo_evaluation"]:
            assert key in report, f"Missing top-level key: {key}"

    def test_interval_percentiles_has_both_histograms(self, report):
        pcts = report["interval_percentiles"]
        assert "sglang:time_to_first_token_seconds" in pcts
        assert "sglang:e2e_request_latency_seconds" in pcts

    def test_counter_rates_has_both_counters(self, report):
        rates = report["counter_rates"]
        assert "sglang:prompt_tokens_total" in rates
        assert "sglang:generation_tokens_total" in rates

    def test_all_percentile_keys_present(self, report):
        for metric in report["interval_percentiles"]:
            for interval in ["interval_0_1", "interval_1_2"]:
                data = report["interval_percentiles"][metric][interval]
                for p in ["p50", "p95", "p99"]:
                    assert p in data, f"Missing {p} in {metric}/{interval}"


# ---------------------------------------------------------------------------
# Recording rules tests
# ---------------------------------------------------------------------------

class TestRecordingRules:
    def test_file_exists(self):
        assert os.path.exists("/app/recording_rules.yml"), "recording_rules.yml not found"

    def test_promtool_validates(self):
        result = subprocess.run(
            ["/usr/local/bin/promtool", "check", "rules", "/app/recording_rules.yml"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"promtool check rules failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_contains_histogram_quantile(self):
        with open("/app/recording_rules.yml") as f:
            content = f.read()
        assert "histogram_quantile" in content, (
            "Recording rules should use histogram_quantile for percentile computations"
        )

    def test_contains_rate_function(self):
        with open("/app/recording_rules.yml") as f:
            content = f.read()
        assert "rate(" in content, "Recording rules should use rate() for counter rates"

    def test_references_ttft_histogram(self):
        with open("/app/recording_rules.yml") as f:
            content = f.read()
        assert "time_to_first_token_seconds" in content

    def test_references_e2e_histogram(self):
        with open("/app/recording_rules.yml") as f:
            content = f.read()
        assert "e2e_request_latency_seconds" in content

    def test_references_counter_metrics(self):
        with open("/app/recording_rules.yml") as f:
            content = f.read()
        assert "prompt_tokens_total" in content
        assert "generation_tokens_total" in content

    def test_has_rule_groups(self):
        with open("/app/recording_rules.yml") as f:
            content = yaml.safe_load(f)
        assert "groups" in content, "Missing 'groups' key"
        assert len(content["groups"]) > 0, "No rule groups defined"
        total_rules = 0
        for group in content["groups"]:
            assert "rules" in group, f"Group '{group.get('name')}' missing 'rules'"
            total_rules += len(group["rules"])
        assert total_rules >= 4, f"Expected at least 4 recording rules, found {total_rules}"


# ---------------------------------------------------------------------------
# Alerting rules tests
# ---------------------------------------------------------------------------

class TestAlertingRules:
    def test_file_exists(self):
        assert os.path.exists("/app/alerting_rules.yml"), "alerting_rules.yml not found"

    def test_promtool_validates(self):
        result = subprocess.run(
            ["/usr/local/bin/promtool", "check", "rules", "/app/alerting_rules.yml"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"promtool check rules failed:\n{result.stdout}\n{result.stderr}"
        )

    def test_has_alert_definitions(self):
        with open("/app/alerting_rules.yml") as f:
            content = yaml.safe_load(f)
        assert "groups" in content
        alert_count = 0
        for group in content["groups"]:
            for rule in group.get("rules", []):
                if "alert" in rule:
                    alert_count += 1
        assert alert_count >= 2, f"Expected at least 2 alert rules, found {alert_count}"

    def test_has_severity_labels(self):
        with open("/app/alerting_rules.yml") as f:
            content = yaml.safe_load(f)
        for group in content["groups"]:
            for rule in group.get("rules", []):
                if "alert" in rule:
                    assert "labels" in rule, f"Alert '{rule['alert']}' missing labels"
                    assert "severity" in rule["labels"], (
                        f"Alert '{rule['alert']}' missing severity label"
                    )

    def test_has_critical_and_warning(self):
        with open("/app/alerting_rules.yml") as f:
            content = yaml.safe_load(f)
        severities = set()
        for group in content["groups"]:
            for rule in group.get("rules", []):
                if "alert" in rule:
                    severities.add(rule.get("labels", {}).get("severity"))
        assert "critical" in severities, "No critical-severity alert found"
        assert "warning" in severities, "No warning-severity alert found"

    def test_references_burn_rate_thresholds(self):
        with open("/app/alerting_rules.yml") as f:
            content = f.read()
        assert "14.4" in content, "Missing critical burn rate threshold (14.4)"
        assert "6.0" in content, "Missing warning burn rate threshold (6.0)"

    def test_references_slo_metrics(self):
        with open("/app/alerting_rules.yml") as f:
            content = f.read()
        assert "time_to_first_token_seconds" in content, (
            "Missing TTFT metric in alerting rules"
        )
        assert "e2e_request_latency_seconds" in content, (
            "Missing E2E metric in alerting rules"
        )
