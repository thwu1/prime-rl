
import json
import os
import pytest


@pytest.fixture(scope="module")
def results():
    results_path = "/app/results.json"
    assert os.path.isfile(results_path), "results.json not found at /app/results.json"
    with open(results_path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must contain a JSON object"
    return data


class TestRootCause:
    """Verify the identified root cause function."""

    def test_key_exists(self, results):
        assert "root_cause" in results

    def test_value(self, results):
        assert results["root_cause"] == "spin_lock", (
            f"Expected root cause 'spin_lock', got '{results['root_cause']}'"
        )


class TestRegressionCategory:
    """Verify the regression is correctly classified."""

    def test_key_exists(self, results):
        assert "regression_category" in results

    def test_value(self, results):
        assert results["regression_category"] == "lock_contention", (
            f"Expected 'lock_contention', got '{results['regression_category']}'"
        )


class TestOnsetWindow:
    """Verify change point detection."""

    def test_key_exists(self, results):
        assert "onset_window" in results

    def test_value(self, results):
        assert results["onset_window"] == 1, (
            f"Expected onset window 1, got {results['onset_window']}"
        )


class TestInclusiveFractionSeries:
    """Verify inclusive sample fraction time series for root cause."""

    EXPECTED = [0.0, 0.0514, 0.1563, 0.326, 0.4586]

    def test_key_exists(self, results):
        assert "inclusive_fraction_series" in results

    def test_length(self, results):
        assert len(results["inclusive_fraction_series"]) == 5

    def test_values(self, results):
        series = results["inclusive_fraction_series"]
        for i, (got, exp) in enumerate(zip(series, self.EXPECTED)):
            assert abs(got - exp) < 0.001, (
                f"Window t{i}: expected inclusive fraction ~{exp}, got {got}"
            )


class TestSelfFractionSeries:
    """Verify exclusive sample fraction time series for root cause."""

    EXPECTED = [0.0, 0.0514, 0.1563, 0.2463, 0.2923]

    def test_key_exists(self, results):
        assert "self_fraction_series" in results

    def test_length(self, results):
        assert len(results["self_fraction_series"]) == 5

    def test_values(self, results):
        series = results["self_fraction_series"]
        for i, (got, exp) in enumerate(zip(series, self.EXPECTED)):
            assert abs(got - exp) < 0.001, (
                f"Window t{i}: expected self fraction ~{exp}, got {got}"
            )


class TestCascadingFunctions:
    """Verify identification of cascading (descendant) new functions."""

    EXPECTED = ["futex_wait", "sched_yield"]

    def test_key_exists(self, results):
        assert "cascading_functions" in results

    def test_is_list(self, results):
        assert isinstance(results["cascading_functions"], list)

    def test_values(self, results):
        result = sorted(results["cascading_functions"])
        assert result == self.EXPECTED, (
            f"Expected {self.EXPECTED}, got {result}"
        )


class TestGrowthClassification:
    """Verify classification of functions new to the degraded profiles."""

    EXPECTED = {
        "alloc": "independent",
        "futex_wait": "causal_descendant",
        "health_check": "independent",
        "mmap": "independent",
        "sched_yield": "causal_descendant",
        "spin_lock": "root_cause",
        "tcp_probe": "independent",
    }

    def test_key_exists(self, results):
        assert "growth_classification" in results

    def test_is_dict(self, results):
        assert isinstance(results["growth_classification"], dict)

    def test_all_new_functions_present(self, results):
        result = results["growth_classification"]
        for func in self.EXPECTED:
            assert func in result, f"Missing classification for new function '{func}'"

    def test_no_extra_functions(self, results):
        result = results["growth_classification"]
        assert set(result.keys()) == set(self.EXPECTED.keys()), (
            f"Unexpected functions: {set(result.keys()) - set(self.EXPECTED.keys())}"
        )

    def test_classifications(self, results):
        result = results["growth_classification"]
        for func, expected_class in self.EXPECTED.items():
            assert result.get(func) == expected_class, (
                f"Function '{func}': expected '{expected_class}', got '{result.get(func)}'"
            )


class TestPropagationAncestors:
    """Verify identification of all ancestor functions of the root cause."""

    EXPECTED = [
        "acquire", "db_pool", "handle", "products",
        "route", "search", "server", "users"
    ]

    def test_key_exists(self, results):
        assert "propagation_ancestors" in results

    def test_is_list(self, results):
        assert isinstance(results["propagation_ancestors"], list)

    def test_values(self, results):
        result = sorted(results["propagation_ancestors"])
        assert result == self.EXPECTED, (
            f"Expected {self.EXPECTED}, got {result}"
        )


class TestSubsystemRegressionShare:
    """Verify per-subsystem attribution of the regression."""

    EXPECTED = {"gc": 0.0319, "monitor": 0.0126, "server": 0.9555}

    def test_key_exists(self, results):
        assert "subsystem_regression_share" in results

    def test_is_dict(self, results):
        assert isinstance(results["subsystem_regression_share"], dict)

    def test_subsystems_present(self, results):
        result = results["subsystem_regression_share"]
        for key in self.EXPECTED:
            assert key in result, f"Missing subsystem '{key}'"

    def test_no_extra_subsystems(self, results):
        result = results["subsystem_regression_share"]
        assert set(result.keys()) == set(self.EXPECTED.keys()), (
            f"Unexpected subsystems: {set(result.keys()) - set(self.EXPECTED.keys())}"
        )

    def test_values(self, results):
        result = results["subsystem_regression_share"]
        for sub, exp in self.EXPECTED.items():
            assert abs(result[sub] - exp) < 0.002, (
                f"Subsystem '{sub}': expected ~{exp}, got {result[sub]}"
            )

    def test_sum_to_one(self, results):
        result = results["subsystem_regression_share"]
        total = sum(result.values())
        assert abs(total - 1.0) < 0.01, (
            f"Shares sum to {total}, expected ~1.0"
        )


class TestPearsonCtxSwitches:
    """Verify Pearson correlation computation."""

    EXPECTED = 0.991

    def test_key_exists(self, results):
        assert "pearson_ctx_switches" in results

    def test_value(self, results):
        result = results["pearson_ctx_switches"]
        assert isinstance(result, (int, float))
        assert abs(result - self.EXPECTED) < 0.005, (
            f"Expected Pearson ~{self.EXPECTED}, got {result}"
        )


class TestDiffSvgGenerated:
    """Verify differential flame graph SVG was generated using the toolkit."""

    def test_key_exists(self, results):
        assert "diff_svg_path" in results

    def test_file_exists(self, results):
        path = results["diff_svg_path"]
        assert os.path.isfile(path), (
            f"Differential SVG not found at {path}"
        )

    def test_is_valid_svg(self, results):
        path = results["diff_svg_path"]
        with open(path) as f:
            content = f.read()
        assert "<svg" in content, "File does not appear to be a valid SVG"
        assert "</svg>" in content, "SVG file appears truncated"

    def test_contains_expected_functions(self, results):
        path = results["diff_svg_path"]
        with open(path) as f:
            content = f.read()
        assert "spin_lock" in content, (
            "SVG should contain the root cause function 'spin_lock'"
        )
        assert "server" in content, (
            "SVG should contain the 'server' subsystem"
        )
