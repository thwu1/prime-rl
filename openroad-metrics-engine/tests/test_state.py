
import json
import subprocess
import sys
import os
import tempfile
import pytest

sys.path.insert(0, '/app')


def _load_floats(path):
    """Load JSON file and convert all values to float."""
    with open(path) as f:
        data = json.load(f)
    return {k: float(v) for k, v in data.items()}


class TestExpressionEvaluator:
    """Tests for the expression evaluation engine."""

    @pytest.fixture
    def evaluator(self):
        from metrics_engine import ExpressionEvaluator
        return ExpressionEvaluator()

    def test_simple_arithmetic(self, evaluator):
        assert evaluator.evaluate("2 + 3", {}) == pytest.approx(5.0)
        assert evaluator.evaluate("10 - 4", {}) == pytest.approx(6.0)
        assert evaluator.evaluate("3 * 4", {}) == pytest.approx(12.0)
        assert evaluator.evaluate("10 / 4", {}) == pytest.approx(2.5)

    def test_variable_substitution(self, evaluator):
        assert evaluator.evaluate("value * 1.2", {"value": 100}) == pytest.approx(120.0)
        assert evaluator.evaluate("value * 1.2", {"value": 363}) == pytest.approx(435.6)
        result = evaluator.evaluate(
            "value - clock_period * .1",
            {"value": 0.048, "clock_period": 0.485}
        )
        assert result == pytest.approx(-0.0005, abs=1e-6)

    def test_multi_variable_expression(self, evaluator):
        result = evaluator.evaluate(
            "value - clock_period * .1 * instance_count * .1",
            {"value": -0.161, "clock_period": 0.485, "instance_count": 363}
        )
        assert result == pytest.approx(-1.92155, abs=1e-4)

    def test_min_function_positive(self, evaluator):
        assert evaluator.evaluate("min(0, value * 1.2)", {"value": 37.07}) == pytest.approx(0.0)
        assert evaluator.evaluate("min(0, value * 1.2)", {"value": 100.0}) == pytest.approx(0.0)

    def test_min_function_negative(self, evaluator):
        assert evaluator.evaluate("min(0, value * 1.2)", {"value": -3.2}) == pytest.approx(-3.84)
        assert evaluator.evaluate("min(0, value * 1.2)", {"value": -8.4}) == pytest.approx(-10.08)
        assert evaluator.evaluate("min(0, value * 1.2)", {"value": -12.3}) == pytest.approx(-14.76)

    def test_int_function(self, evaluator):
        assert evaluator.evaluate("int(value * 1.2)", {"value": 2}) == 2
        assert evaluator.evaluate("int(value * 1.2)", {"value": 184}) == 220
        assert evaluator.evaluate("int(value * 1.2)", {"value": 520}) == 624
        assert evaluator.evaluate("int(value * 1.2)", {"value": 0}) == 0

    def test_identity_expression(self, evaluator):
        assert evaluator.evaluate("value", {"value": 42.0}) == pytest.approx(42.0)
        assert evaluator.evaluate("value", {"value": 0.0}) == pytest.approx(0.0)

    def test_operator_precedence(self, evaluator):
        # Multiplication binds tighter than subtraction
        result = evaluator.evaluate(
            "value - clock_period * .1",
            {"value": 0.095, "clock_period": 2.0}
        )
        assert result == pytest.approx(-0.105)


class TestMetricsChecker:
    """Tests for the metrics limit checker."""

    @pytest.fixture
    def checker(self):
        from metrics_engine import MetricsChecker
        with open('/app/metric_defs.json') as f:
            defs = json.load(f)
        return MetricsChecker(defs)

    def test_compute_limits_gcd(self, checker):
        golden = _load_floats('/app/designs/gcd_nangate45/golden.json')
        limits = checker.compute_limits(golden)

        assert limits["IFP::instance_count"] == pytest.approx(435.6)
        assert limits["DPL::design_area"] == pytest.approx(703.2)
        assert limits["DPL::utilization"] == pytest.approx(11.04)
        assert limits["RSZ::repair_design_buffer_count"] == pytest.approx(2)
        assert limits["RSZ::max_slew_slack"] == pytest.approx(0.0)
        assert limits["RSZ::max_fanout_slack"] == pytest.approx(0.0)
        assert limits["RSZ::max_capacitance_slack"] == pytest.approx(0.0)
        assert limits["RSZ::worst_slack_min"] == pytest.approx(-0.0005, abs=1e-5)
        assert limits["RSZ::worst_slack_max"] == pytest.approx(-0.0735, abs=1e-4)
        assert limits["RSZ::tns_max"] == pytest.approx(-1.92155, abs=1e-3)
        assert limits["RSZ::hold_buffer_count"] == pytest.approx(0)
        assert limits["GRT::ANT::errors"] == pytest.approx(0)
        assert limits["DRT::drv"] == pytest.approx(0)
        assert limits["DRT::worst_slack_min"] == pytest.approx(-0.0015, abs=1e-5)
        assert limits["DRT::worst_slack_max"] == pytest.approx(-0.0925, abs=1e-4)
        assert limits["DRT::tns_max"] == pytest.approx(-2.30955, abs=1e-3)
        assert limits["DRT::clock_skew"] == pytest.approx(0.003924, abs=1e-5)
        assert limits["DRT::max_slew_slack"] == pytest.approx(0.0)
        assert limits["DRT::max_capacitance_slack"] == pytest.approx(0.0)
        assert limits["DRT::max_fanout_slack"] == pytest.approx(0.0)
        assert limits["DRT::clock_period"] == pytest.approx(0.485)
        assert limits["DRT::ANT::errors"] == pytest.approx(0)

    def test_compute_limits_ibex_negative_golden(self, checker):
        """Limits when golden values are negative (edge case for min())."""
        golden = _load_floats('/app/designs/ibex_sky130/golden.json')
        limits = checker.compute_limits(golden)

        # Negative golden with min(0, value * 1.2) produces negative limit
        assert limits["RSZ::max_slew_slack"] == pytest.approx(-3.84, abs=1e-4)
        assert limits["RSZ::max_capacitance_slack"] == pytest.approx(-10.08, abs=1e-4)
        assert limits["DRT::max_slew_slack"] == pytest.approx(-6.0, abs=1e-4)
        assert limits["DRT::max_capacitance_slack"] == pytest.approx(-14.76, abs=1e-4)

        # Nonzero golden with identity expr "value"
        assert limits["GRT::ANT::errors"] == pytest.approx(5)
        assert limits["DRT::drv"] == pytest.approx(2)
        assert limits["DRT::ANT::errors"] == pytest.approx(3)

        # Large clock_period affects slack tolerance
        assert limits["RSZ::worst_slack_min"] == pytest.approx(-1.450, abs=1e-3)
        assert limits["DRT::tns_max"] == pytest.approx(-2780.0, abs=1.0)

    def test_compute_limits_aes(self, checker):
        golden = _load_floats('/app/designs/aes_nangate45/golden.json')
        limits = checker.compute_limits(golden)

        assert limits["IFP::instance_count"] == pytest.approx(26574.0)
        assert limits["RSZ::repair_design_buffer_count"] == pytest.approx(220)
        assert limits["RSZ::hold_buffer_count"] == pytest.approx(42)
        assert limits["RSZ::worst_slack_min"] == pytest.approx(-0.105, abs=1e-4)
        assert limits["RSZ::worst_slack_max"] == pytest.approx(-0.380, abs=1e-3)
        assert limits["RSZ::tns_max"] == pytest.approx(-485.4, abs=1.0)
        assert limits["DRT::clock_skew"] == pytest.approx(0.030, abs=1e-4)

    def test_check_gcd_run1_one_failure(self, checker):
        golden = _load_floats('/app/designs/gcd_nangate45/golden.json')
        run1 = _load_floats('/app/designs/gcd_nangate45/run1.json')
        result = checker.check_run(golden, run1)

        failures = [m for m in result["metrics"] if not m["passed"]]
        assert len(failures) == 1
        assert failures[0]["name"] == "RSZ::repair_design_buffer_count"
        assert result["summary"]["failed"] == 1
        assert result["summary"]["total"] == 22
        assert result["summary"]["passed"] == 21

    def test_check_gcd_run2_timing_failures(self, checker):
        golden = _load_floats('/app/designs/gcd_nangate45/golden.json')
        run2 = _load_floats('/app/designs/gcd_nangate45/run2.json')
        result = checker.check_run(golden, run2)

        failures = [m for m in result["metrics"] if not m["passed"]]
        failed_names = sorted([f["name"] for f in failures])
        expected = sorted([
            "RSZ::worst_slack_min",
            "RSZ::worst_slack_max",
            "RSZ::tns_max",
            "DRT::worst_slack_min",
            "DRT::worst_slack_max",
            "DRT::tns_max",
            "DRT::clock_skew",
        ])
        assert failed_names == expected
        assert result["summary"]["failed"] == 7

    def test_check_aes_run1_violations(self, checker):
        golden = _load_floats('/app/designs/aes_nangate45/golden.json')
        run1 = _load_floats('/app/designs/aes_nangate45/run1.json')
        result = checker.check_run(golden, run1)

        failures = [m for m in result["metrics"] if not m["passed"]]
        failed_names = sorted([f["name"] for f in failures])
        expected = sorted([
            "RSZ::max_slew_slack",
            "GRT::ANT::errors",
            "DRT::drv",
            "DRT::max_slew_slack",
            "DRT::ANT::errors",
        ])
        assert failed_names == expected
        assert result["summary"]["failed"] == 5

    def test_check_ibex_run1_edge_cases(self, checker):
        golden = _load_floats('/app/designs/ibex_sky130/golden.json')
        run1 = _load_floats('/app/designs/ibex_sky130/run1.json')
        result = checker.check_run(golden, run1)

        failures = [m for m in result["metrics"] if not m["passed"]]
        failed_names = sorted([f["name"] for f in failures])
        expected = sorted([
            "RSZ::max_slew_slack",
            "DRT::clock_skew",
            "DRT::max_slew_slack",
        ])
        assert failed_names == expected
        assert result["summary"]["failed"] == 3

    def test_check_boundary_pass(self, checker):
        """Metrics exactly at limit should pass for <= and >=."""
        golden = _load_floats('/app/designs/ibex_sky130/golden.json')
        limits = checker.compute_limits(golden)

        # GRT::ANT::errors golden=5 limit=5 (<=): 5 <= 5 -> pass
        assert checker.check_metric("GRT::ANT::errors", 5, limits["GRT::ANT::errors"]) is True
        # DRT::clock_period golden=10 limit=10 (<=): 10 <= 10 -> pass
        assert checker.check_metric("DRT::clock_period", 10.0, limits["DRT::clock_period"]) is True
        # DRT::drv golden=2 limit=2 (<=): 2 <= 2 -> pass
        assert checker.check_metric("DRT::drv", 2, limits["DRT::drv"]) is True

    def test_check_result_structure(self, checker):
        """Verify the check_run result has the expected structure."""
        golden = _load_floats('/app/designs/gcd_nangate45/golden.json')
        run1 = _load_floats('/app/designs/gcd_nangate45/run1.json')
        result = checker.check_run(golden, run1)

        assert "metrics" in result
        assert "summary" in result
        assert "total" in result["summary"]
        assert "passed" in result["summary"]
        assert "failed" in result["summary"]
        assert "pass_rate" in result["summary"]

        for m in result["metrics"]:
            assert "name" in m
            assert "actual" in m
            assert "limit" in m
            assert "comparison" in m
            assert "passed" in m
            assert isinstance(m["passed"], bool)

    def test_pass_rate_calculation(self, checker):
        golden = _load_floats('/app/designs/gcd_nangate45/golden.json')
        run1 = _load_floats('/app/designs/gcd_nangate45/run1.json')
        result = checker.check_run(golden, run1)
        expected_rate = 21 / 22
        assert result["summary"]["pass_rate"] == pytest.approx(expected_rate, abs=1e-4)


class TestRegressionAnalyzer:
    """Tests for multi-run regression analysis."""

    @pytest.fixture
    def analyzer(self):
        from metrics_engine import MetricsChecker, RegressionAnalyzer
        with open('/app/metric_defs.json') as f:
            defs = json.load(f)
        checker = MetricsChecker(defs)
        return RegressionAnalyzer(checker)

    def test_analyze_gcd_two_runs(self, analyzer):
        golden = _load_floats('/app/designs/gcd_nangate45/golden.json')
        run1 = _load_floats('/app/designs/gcd_nangate45/run1.json')
        run2 = _load_floats('/app/designs/gcd_nangate45/run2.json')

        result = analyzer.analyze(golden, [run1, run2])

        assert len(result["runs"]) == 2
        assert result["runs"][0]["summary"]["failed"] == 1
        assert result["runs"][1]["summary"]["failed"] == 7

        # No metric fails in BOTH runs
        # run1 fails: RSZ::repair_design_buffer_count
        # run2 fails: 7 timing metrics (different set)
        assert len(result["systematic_failures"]) == 0

        # Severity: 8 failures / 44 total checks
        assert result["severity_score"] == pytest.approx(8 / 44, abs=1e-4)

    def test_analyze_systematic_failures(self, analyzer):
        """Metrics failing in all runs are flagged as systematic."""
        golden = _load_floats('/app/designs/ibex_sky130/golden.json')

        run_a = dict(golden)
        run_a["RSZ::max_slew_slack"] = -4.0   # fails (limit = -3.84)
        run_a["DRT::max_slew_slack"] = -6.5    # fails (limit = -6.0)

        run_b = dict(golden)
        run_b["RSZ::max_slew_slack"] = -5.0    # also fails
        run_b["DRT::max_slew_slack"] = -7.0    # also fails

        result = analyzer.analyze(golden, [run_a, run_b])
        systematic = result["systematic_failures"]
        assert "RSZ::max_slew_slack" in systematic
        assert "DRT::max_slew_slack" in systematic
        assert systematic["RSZ::max_slew_slack"] == 2
        assert systematic["DRT::max_slew_slack"] == 2


class TestCLI:
    """Tests for the command-line interface."""

    def test_cli_limits(self):
        result = subprocess.run(
            ["python3", "/app/metrics_engine.py", "limits",
             "/app/designs/gcd_nangate45/golden.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        limits = json.loads(result.stdout)
        assert limits["IFP::instance_count"] == pytest.approx(435.6)
        assert limits["RSZ::max_slew_slack"] == pytest.approx(0.0)
        assert limits["DRT::clock_skew"] == pytest.approx(0.003924, abs=1e-5)

    def test_cli_check(self):
        result = subprocess.run(
            ["python3", "/app/metrics_engine.py", "check",
             "/app/designs/gcd_nangate45/golden.json",
             "/app/designs/gcd_nangate45/run1.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["summary"]["failed"] == 1
        assert report["summary"]["total"] == 22

    def test_cli_analyze(self):
        result = subprocess.run(
            ["python3", "/app/metrics_engine.py", "analyze",
             "/app/designs/gcd_nangate45/golden.json",
             "/app/designs/gcd_nangate45/run1.json",
             "/app/designs/gcd_nangate45/run2.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        analysis = json.loads(result.stdout)
        assert len(analysis["runs"]) == 2
        assert analysis["severity_score"] == pytest.approx(8 / 44, abs=1e-4)

    def test_cli_custom_defs(self):
        """--defs flag overrides default metric definitions."""
        custom_defs = {
            "variable_map": {},
            "metrics": [
                {"name": "test::metric_a", "comparison": "<",
                 "tolerance_expr": "value * 2.0"},
                {"name": "test::metric_b", "comparison": ">=",
                 "tolerance_expr": "min(0, value)"}
            ]
        }
        golden = {"test::metric_a": 10.0, "test::metric_b": -5.0}
        run = {"test::metric_a": 15.0, "test::metric_b": -3.0}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as df:
            json.dump(custom_defs, df)
            defs_path = df.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as gf:
            json.dump(golden, gf)
            golden_path = gf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as rf:
            json.dump(run, rf)
            run_path = rf.name

        try:
            result = subprocess.run(
                ["python3", "/app/metrics_engine.py", "check",
                 golden_path, run_path, "--defs", defs_path],
                capture_output=True, text=True, cwd="/app"
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            report = json.loads(result.stdout)

            # metric_a: actual=15, limit=10*2=20, 15 < 20 -> PASS
            # metric_b: actual=-3, limit=min(0,-5)=-5, -3 >= -5 -> PASS
            assert report["summary"]["passed"] == 2
            assert report["summary"]["failed"] == 0
        finally:
            os.unlink(defs_path)
            os.unlink(golden_path)
            os.unlink(run_path)

    def test_cli_handles_string_values(self):
        """String metric values in JSON are correctly converted to numbers."""
        result = subprocess.run(
            ["python3", "/app/metrics_engine.py", "limits",
             "/app/designs/gcd_nangate45/golden.json"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        limits = json.loads(result.stdout)
        # gcd_nangate45/golden.json stores values as strings
        assert isinstance(limits["IFP::instance_count"], (int, float))
        assert limits["IFP::instance_count"] == pytest.approx(435.6)
