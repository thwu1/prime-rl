
"""
Verification tests for the bivariate bicycle code analysis task.
Checks code parameter correctness and physical consistency of simulation results.
"""

import json
import os
import pytest


RESULTS_PATH = "/app/results.json"
SPEC_PATH = "/app/code_spec.json"

# Known parameters for the [[72, 12, 6]] BB code
EXPECTED_N = 72
EXPECTED_K = 12
EXPECTED_HX_RANK = 30
EXPECTED_HZ_RANK = 30
EXPECTED_STABILIZER_WEIGHT = 6

# Tolerance for monotonicity check (accounts for statistical noise at 10000 shots)
MONO_TOLERANCE = 0.035


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture
def spec():
    with open(SPEC_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    """Verify the results file has the required structure."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_top_level_keys(self, results):
        assert "code_parameters" in results, "Missing 'code_parameters' key"
        assert "logical_error_rates" in results, "Missing 'logical_error_rates' key"

    def test_code_parameters_keys(self, results):
        cp = results["code_parameters"]
        required = ["n", "k", "hx_rank", "hz_rank", "css_valid", "stabilizer_weight"]
        for key in required:
            assert key in cp, f"Missing code_parameters.{key}"

    def test_logical_error_rates_keys(self, results, spec):
        ler = results["logical_error_rates"]
        for p in spec["error_rates"]:
            key = str(p)
            assert key in ler, f"Missing logical_error_rates['{key}']"


class TestCodeParameters:
    """Verify the constructed code has correct parameters."""

    def test_n(self, results):
        assert results["code_parameters"]["n"] == EXPECTED_N, (
            f"Expected n={EXPECTED_N}, got {results['code_parameters']['n']}"
        )

    def test_k(self, results):
        assert results["code_parameters"]["k"] == EXPECTED_K, (
            f"Expected k={EXPECTED_K}, got {results['code_parameters']['k']}"
        )

    def test_hx_rank(self, results):
        assert results["code_parameters"]["hx_rank"] == EXPECTED_HX_RANK, (
            f"Expected hx_rank={EXPECTED_HX_RANK}, got {results['code_parameters']['hx_rank']}"
        )

    def test_hz_rank(self, results):
        assert results["code_parameters"]["hz_rank"] == EXPECTED_HZ_RANK, (
            f"Expected hz_rank={EXPECTED_HZ_RANK}, got {results['code_parameters']['hz_rank']}"
        )

    def test_css_valid(self, results):
        assert results["code_parameters"]["css_valid"] is True, (
            "CSS condition Hx @ Hz^T = 0 (mod 2) should hold"
        )

    def test_stabilizer_weight(self, results):
        assert results["code_parameters"]["stabilizer_weight"] == EXPECTED_STABILIZER_WEIGHT, (
            f"Expected uniform stabilizer weight {EXPECTED_STABILIZER_WEIGHT}, "
            f"got {results['code_parameters']['stabilizer_weight']}"
        )


class TestLogicalErrorRates:
    """Verify simulation results are physically consistent."""

    def test_rates_are_valid_probabilities(self, results, spec):
        ler = results["logical_error_rates"]
        for p in spec["error_rates"]:
            rate = ler[str(p)]
            assert isinstance(rate, (int, float)), (
                f"Logical error rate at p={p} should be numeric, got {type(rate)}"
            )
            assert 0.0 <= rate <= 1.0, (
                f"Logical error rate at p={p} is {rate}, not in [0, 1]"
            )

    def test_low_noise_rate(self, results):
        """At p=0.01, the [[72,12,6]] code should correct most errors."""
        rate = results["logical_error_rates"]["0.01"]
        assert rate < 0.05, (
            f"At p=0.01, logical error rate should be <0.05, got {rate}"
        )

    def test_high_noise_rate(self, results):
        """At p=0.10, many errors should be uncorrectable."""
        rate = results["logical_error_rates"]["0.1"]
        assert rate > 0.01, (
            f"At p=0.10, logical error rate should be >0.01, got {rate}"
        )

    def test_monotonicity(self, results, spec):
        """Logical error rate should generally increase with physical error rate."""
        ler = results["logical_error_rates"]
        rates = spec["error_rates"]
        for i in range(len(rates) - 1):
            r_lo = ler[str(rates[i])]
            r_hi = ler[str(rates[i + 1])]
            assert r_lo <= r_hi + MONO_TOLERANCE, (
                f"Logical error rate should be non-decreasing (within tolerance): "
                f"p={rates[i]} -> {r_lo}, p={rates[i+1]} -> {r_hi}"
            )

    def test_rate_spread(self, results):
        """The error rates should span a meaningful range across noise levels."""
        lowest = results["logical_error_rates"]["0.01"]
        highest = results["logical_error_rates"]["0.1"]
        assert highest > lowest, (
            "Logical error rate at p=0.10 should exceed that at p=0.01"
        )

    def test_mid_noise_bounded(self, results):
        """At p=0.05, logical error rate should be between low and high extremes."""
        rate = results["logical_error_rates"]["0.05"]
        assert rate < 0.50, (
            f"At p=0.05, logical error rate should be <0.50, got {rate}"
        )
