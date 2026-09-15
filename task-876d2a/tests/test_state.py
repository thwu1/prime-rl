
import subprocess
import json
import os
import pytest


def run_engine(*args):
    """Run the metrics engine CLI tool and return the CompletedProcess."""
    result = subprocess.run(
        ["python3", "/app/metrics_engine.py"] + list(args),
        capture_output=True, text=True, cwd="/app",
        timeout=30
    )
    return result


class TestGenerateLimits:
    """Test limit generation from reference metrics."""

    def test_gcd_multiplicative_limits(self):
        """Multiplicative limits: value * 1.2 for instance count, area, utilization."""
        result = run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_gcd_mult_limits.json"
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        with open("/tmp/test_gcd_mult_limits.json") as f:
            limits = json.load(f)

        # IFP::instance_count: 363 * 1.2 = 435.6
        assert abs(float(limits["IFP::instance_count"]) - 435.6) < 0.01

        # DPL::design_area: 586 * 1.2 = 703.2
        assert abs(float(limits["DPL::design_area"]) - 703.2) < 0.01

        # DPL::utilization: 9.2 * 1.2 = 11.04
        assert abs(float(limits["DPL::utilization"]) - 11.04) < 0.01

    def test_gcd_int_truncation(self):
        """int() truncation: int(2 * 1.2) = 2, int(0 * 1.2) = 0."""
        result = run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_gcd_int_limits.json"
        )
        assert result.returncode == 0

        with open("/tmp/test_gcd_int_limits.json") as f:
            limits = json.load(f)

        assert int(float(limits["RSZ::repair_design_buffer_count"])) == 2
        assert int(float(limits["RSZ::hold_buffer_count"])) == 0

    def test_gcd_min_function_positive_input(self):
        """min(0, positive * 1.2) = 0 for positive slack values."""
        result = run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_gcd_min_pos_limits.json"
        )
        assert result.returncode == 0

        with open("/tmp/test_gcd_min_pos_limits.json") as f:
            limits = json.load(f)

        assert float(limits["RSZ::max_slew_slack"]) == 0.0
        assert float(limits["RSZ::max_fanout_slack"]) == 0.0
        assert float(limits["DRT::max_slew_slack"]) == 0.0
        assert float(limits["DRT::max_fanout_slack"]) == 0.0

    def test_gcd_min_function_negative_input(self):
        """min(0, negative * 1.2) produces more negative limit."""
        result = run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_gcd_min_neg_limits.json"
        )
        assert result.returncode == 0

        with open("/tmp/test_gcd_min_neg_limits.json") as f:
            limits = json.load(f)

        # DRT::max_capacitance_slack: min(0, -30.268 * 1.2) = -36.322
        cap_limit = float(limits["DRT::max_capacitance_slack"])
        assert cap_limit < 0
        assert abs(cap_limit - (-36.322)) < 0.01

    def test_gcd_slack_depends_on_clock_period(self):
        """Slack limits use $clock_period: value - clock_period * 0.1."""
        result = run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_gcd_slack_limits.json"
        )
        assert result.returncode == 0

        with open("/tmp/test_gcd_slack_limits.json") as f:
            limits = json.load(f)

        # RSZ::worst_slack_min: 0.04803 - 0.485*0.1 = -0.000470
        assert abs(float(limits["RSZ::worst_slack_min"]) - (-0.000470)) < 0.001

        # RSZ::worst_slack_max: -0.02541 - 0.0485 = -0.07391
        assert abs(float(limits["RSZ::worst_slack_max"]) - (-0.07391)) < 0.001

        # DRT::worst_slack_min: 0.04666 - 0.0485 = -0.00184
        assert abs(float(limits["DRT::worst_slack_min"]) - (-0.00184)) < 0.001

        # DRT::worst_slack_max: -0.04397 - 0.0485 = -0.09247
        assert abs(float(limits["DRT::worst_slack_max"]) - (-0.09247)) < 0.001

    def test_gcd_tns_depends_on_clock_and_instances(self):
        """TNS limits reference both $clock_period AND $instance_count."""
        result = run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_gcd_tns_limits.json"
        )
        assert result.returncode == 0

        with open("/tmp/test_gcd_tns_limits.json") as f:
            limits = json.load(f)

        # RSZ::tns_max: -0.16072 - 0.0485 * 36.3 = -1.9213
        assert abs(float(limits["RSZ::tns_max"]) - (-1.9213)) < 0.01

        # DRT::tns_max: -0.5492 - 0.0485 * 36.3 = -2.3097
        assert abs(float(limits["DRT::tns_max"]) - (-2.3097)) < 0.01

    def test_gcd_strict_non_regression_limits(self):
        """DRT::drv and ANT::errors use $value directly (no margin)."""
        result = run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_gcd_strict_limits.json"
        )
        assert result.returncode == 0

        with open("/tmp/test_gcd_strict_limits.json") as f:
            limits = json.load(f)

        assert float(limits["DRT::drv"]) == 0.0
        assert float(limits["GRT::ANT::errors"]) == 0.0
        assert float(limits["DRT::ANT::errors"]) == 0.0

    def test_aes_tns_scaling_with_larger_design(self):
        """AES design has much larger instance count and clock period, affecting TNS limits."""
        result = run_engine(
            "generate-limits",
            "/app/runs/aes_nangate45.metrics.json",
            "-o", "/tmp/test_aes_limits.json"
        )
        assert result.returncode == 0

        with open("/tmp/test_aes_limits.json") as f:
            limits = json.load(f)

        # RSZ::tns_max: -45.72 - 2.0*0.1*12180*0.1 = -45.72 - 243.6 = -289.32
        assert abs(float(limits["RSZ::tns_max"]) - (-289.32)) < 0.1

        # DRT::tns_max: -62.85 - 243.6 = -306.45
        assert abs(float(limits["DRT::tns_max"]) - (-306.45)) < 0.1

        # IFP::instance_count: 12180 * 1.2 = 14616
        assert abs(float(limits["IFP::instance_count"]) - 14616.0) < 0.1

        # DRT::clock_period limit = $value = 2.0
        assert abs(float(limits["DRT::clock_period"]) - 2.0) < 0.001

    def test_all_22_metrics_present(self):
        """All 22 metric definitions should produce limits."""
        result = run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_gcd_22_limits.json"
        )
        assert result.returncode == 0

        with open("/tmp/test_gcd_22_limits.json") as f:
            limits = json.load(f)

        assert len(limits) == 22


class TestCheckMetrics:
    """Test metric validation against limits."""

    def test_self_check_passes(self):
        """A run checked against its own generated limits must pass."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_selfcheck_limits.json"
        )
        result = run_engine(
            "check",
            "/app/runs/gcd_nangate45.metrics.json",
            "/tmp/test_selfcheck_limits.json"
        )
        assert result.returncode == 0

        output = json.loads(result.stdout)
        assert output["overall"] == "pass"
        for m in output["metrics"]:
            assert m["status"] == "pass", f"{m['name']} should pass self-check"

    def test_aes_self_check_passes(self):
        """AES design self-check should also pass."""
        run_engine(
            "generate-limits",
            "/app/runs/aes_nangate45.metrics.json",
            "-o", "/tmp/test_aes_selfcheck_limits.json"
        )
        result = run_engine(
            "check",
            "/app/runs/aes_nangate45.metrics.json",
            "/tmp/test_aes_selfcheck_limits.json"
        )
        assert result.returncode == 0

        output = json.loads(result.stdout)
        assert output["overall"] == "pass"

    def test_degraded_fails_overall(self):
        """Degraded run checked against baseline limits must fail."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_degraded_limits.json"
        )
        result = run_engine(
            "check",
            "/app/runs/gcd_nangate45_degraded.metrics.json",
            "/tmp/test_degraded_limits.json"
        )
        assert result.returncode != 0

        output = json.loads(result.stdout)
        assert output["overall"] == "fail"

    def test_degraded_exactly_10_failures(self):
        """Degraded run should have exactly 10 failing metrics."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_degraded_count_limits.json"
        )
        result = run_engine(
            "check",
            "/app/runs/gcd_nangate45_degraded.metrics.json",
            "/tmp/test_degraded_count_limits.json"
        )

        output = json.loads(result.stdout)
        failures = [m for m in output["metrics"] if m["status"] == "fail"]
        assert len(failures) == 10

    def test_degraded_exact_failure_set(self):
        """Verify the precise set of metrics that fail in the degraded run."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_degraded_set_limits.json"
        )
        result = run_engine(
            "check",
            "/app/runs/gcd_nangate45_degraded.metrics.json",
            "/tmp/test_degraded_set_limits.json"
        )

        output = json.loads(result.stdout)
        failing_names = {m["name"] for m in output["metrics"] if m["status"] == "fail"}

        expected_failures = {
            "RSZ::repair_design_buffer_count",
            "RSZ::max_capacitance_slack",
            "RSZ::worst_slack_max",
            "RSZ::tns_max",
            "DRT::drv",
            "DRT::worst_slack_max",
            "DRT::tns_max",
            "DRT::clock_skew",
            "DRT::max_capacitance_slack",
            "DRT::ANT::errors",
        }

        assert failing_names == expected_failures

    def test_check_output_has_required_fields(self):
        """Check output must contain overall, metrics array, and errors array."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_check_fields_limits.json"
        )
        result = run_engine(
            "check",
            "/app/runs/gcd_nangate45.metrics.json",
            "/tmp/test_check_fields_limits.json"
        )

        output = json.loads(result.stdout)
        assert "overall" in output
        assert "metrics" in output
        assert "errors" in output
        assert isinstance(output["metrics"], list)
        assert isinstance(output["errors"], list)

        # Each metric entry must have required fields
        for m in output["metrics"]:
            assert "name" in m
            assert "value" in m
            assert "limit" in m
            assert "cmp_op" in m
            assert "status" in m


class TestMarginReport:
    """Test margin calculation."""

    def test_all_margins_nonnegative_self_check(self):
        """All margins must be non-negative for a self-check."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_margin_nonneg_limits.json"
        )
        result = run_engine(
            "margin-report",
            "/app/runs/gcd_nangate45.metrics.json",
            "/tmp/test_margin_nonneg_limits.json"
        )
        assert result.returncode == 0

        report = json.loads(result.stdout)
        for m in report["metrics"]:
            assert m["margin"] >= -1e-10, (
                f"{m['name']} should have non-negative margin, got {m['margin']}"
            )
            assert m["status"] == "pass"

    def test_margin_less_than_operator(self):
        """For '<' operator, margin = limit - value."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_margin_lt_limits.json"
        )
        result = run_engine(
            "margin-report",
            "/app/runs/gcd_nangate45.metrics.json",
            "/tmp/test_margin_lt_limits.json"
        )
        assert result.returncode == 0

        report = json.loads(result.stdout)
        metrics_by_name = {m["name"]: m for m in report["metrics"]}

        # DPL::design_area: cmp_op <, margin = 703.2 - 586 = 117.2
        area = metrics_by_name["DPL::design_area"]
        assert abs(area["margin"] - 117.2) < 0.5

        # IFP::instance_count: cmp_op <, margin = 435.6 - 363 = 72.6
        inst = metrics_by_name["IFP::instance_count"]
        assert abs(inst["margin"] - 72.6) < 0.5

    def test_margin_greater_than_operator(self):
        """For '>' operator, margin = value - limit."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_margin_gt_limits.json"
        )
        result = run_engine(
            "margin-report",
            "/app/runs/gcd_nangate45.metrics.json",
            "/tmp/test_margin_gt_limits.json"
        )
        assert result.returncode == 0

        report = json.loads(result.stdout)
        metrics_by_name = {m["name"]: m for m in report["metrics"]}

        # RSZ::worst_slack_min: value=0.04803, limit=-0.000470
        # margin = value - limit = 0.04803 - (-0.000470) = 0.0485
        slack = metrics_by_name["RSZ::worst_slack_min"]
        assert abs(slack["margin"] - 0.0485) < 0.001

    def test_degraded_margin_negative_for_failures(self):
        """Failing metrics must have negative margin."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_margin_neg_limits.json"
        )
        result = run_engine(
            "margin-report",
            "/app/runs/gcd_nangate45_degraded.metrics.json",
            "/tmp/test_margin_neg_limits.json"
        )
        assert result.returncode == 0

        report = json.loads(result.stdout)
        metrics_by_name = {m["name"]: m for m in report["metrics"]}

        # DRT::drv: cmp_op <=, value=3, limit=0, margin = 0 - 3 = -3
        drv = metrics_by_name["DRT::drv"]
        assert drv["status"] == "fail"
        assert abs(drv["margin"] - (-3.0)) < 0.01

        # DRT::clock_skew: cmp_op <=, value=0.008, limit=0.003924
        # margin = 0.003924 - 0.008 = -0.004076
        skew = metrics_by_name["DRT::clock_skew"]
        assert skew["status"] == "fail"
        assert skew["margin"] < 0

    def test_margin_report_has_required_fields(self):
        """Each margin entry must have all required fields."""
        run_engine(
            "generate-limits",
            "/app/runs/gcd_nangate45.metrics.json",
            "-o", "/tmp/test_margin_fields_limits.json"
        )
        result = run_engine(
            "margin-report",
            "/app/runs/gcd_nangate45.metrics.json",
            "/tmp/test_margin_fields_limits.json"
        )
        assert result.returncode == 0

        report = json.loads(result.stdout)
        assert "metrics" in report
        for m in report["metrics"]:
            assert "name" in m
            assert "value" in m
            assert "limit" in m
            assert "cmp_op" in m
            assert "margin" in m
            assert "status" in m


class TestCompare:
    """Test run comparison."""

    def test_delta_calculation(self):
        """Delta = value2 - value1."""
        result = run_engine(
            "compare",
            "/app/runs/gcd_nangate45.metrics.json",
            "/app/runs/gcd_nangate45_degraded.metrics.json"
        )
        assert result.returncode == 0

        comparison = json.loads(result.stdout)
        metrics_by_name = {m["name"]: m for m in comparison["metrics"]}

        # DRT::drv: 3 - 0 = 3
        drv = metrics_by_name["DRT::drv"]
        assert abs(drv["delta"] - 3.0) < 0.001

        # DPL::design_area: 610 - 586 = 24
        area = metrics_by_name["DPL::design_area"]
        assert abs(area["delta"] - 24.0) < 0.1

        # DRT::ANT::errors: 1 - 0 = 1
        ant = metrics_by_name["DRT::ANT::errors"]
        assert abs(ant["delta"] - 1.0) < 0.001

    def test_percent_change_nonzero_base(self):
        """Percentage change for non-zero base values."""
        result = run_engine(
            "compare",
            "/app/runs/gcd_nangate45.metrics.json",
            "/app/runs/gcd_nangate45_degraded.metrics.json"
        )
        assert result.returncode == 0

        comparison = json.loads(result.stdout)
        metrics_by_name = {m["name"]: m for m in comparison["metrics"]}

        # DPL::design_area: (610 - 586) / 586 * 100 = 4.0956%
        area = metrics_by_name["DPL::design_area"]
        assert area["percent_change"] is not None
        assert abs(area["percent_change"] - 4.096) < 0.1

    def test_percent_change_null_for_zero_base(self):
        """Percent change must be null/None when base value is zero."""
        result = run_engine(
            "compare",
            "/app/runs/gcd_nangate45.metrics.json",
            "/app/runs/gcd_nangate45_degraded.metrics.json"
        )
        assert result.returncode == 0

        comparison = json.loads(result.stdout)
        metrics_by_name = {m["name"]: m for m in comparison["metrics"]}

        # DRT::drv: base is 0 -> percent_change must be null
        drv = metrics_by_name["DRT::drv"]
        assert drv["percent_change"] is None

        # GRT::ANT::errors: base is 0 -> percent_change must be null
        grt_ant = metrics_by_name["GRT::ANT::errors"]
        assert grt_ant["percent_change"] is None

    def test_compare_has_required_fields(self):
        """Each compare entry must have all required fields."""
        result = run_engine(
            "compare",
            "/app/runs/gcd_nangate45.metrics.json",
            "/app/runs/gcd_nangate45_degraded.metrics.json"
        )
        assert result.returncode == 0

        comparison = json.loads(result.stdout)
        assert "metrics" in comparison
        for m in comparison["metrics"]:
            assert "name" in m
            assert "value1" in m
            assert "value2" in m
            assert "delta" in m
            assert "percent_change" in m

    def test_compare_identical_runs(self):
        """Comparing a run with itself should yield zero deltas."""
        result = run_engine(
            "compare",
            "/app/runs/gcd_nangate45.metrics.json",
            "/app/runs/gcd_nangate45.metrics.json"
        )
        assert result.returncode == 0

        comparison = json.loads(result.stdout)
        for m in comparison["metrics"]:
            assert abs(m["delta"]) < 1e-10, f"{m['name']} delta should be 0"
