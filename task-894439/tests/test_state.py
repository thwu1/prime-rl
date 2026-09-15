
"""
Tests for rough Heston calibration via leverage swaps.

Verifies the full pipeline: Fukasawa robust variance/gamma swap estimation,
normalized leverage computation, Mittag-Leffler formula evaluation, and
rough Heston parameter calibration from SPX implied vol data.
"""

import json
import os

import numpy as np
import pytest


@pytest.fixture
def swap_data():
    path = "/app/output/swap_curves.json"
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def calib_data():
    path = "/app/output/calibration.json"
    assert os.path.exists(path), f"Missing output file: {path}"
    with open(path) as f:
        return json.load(f)


class TestOutputStructure:
    """Verify output files exist and have correct structure."""

    def test_swap_curves_file_exists(self):
        assert os.path.exists("/app/output/swap_curves.json")

    def test_calibration_file_exists(self):
        assert os.path.exists("/app/output/calibration.json")

    def test_swap_curves_keys(self, swap_data):
        required = {"expiries", "var_swaps", "gamma_swaps", "norm_leverage"}
        assert required.issubset(set(swap_data.keys()))

    def test_calibration_keys(self, calib_data):
        required = {"H", "nu", "rho", "lbd", "rmse", "model_norm_leverage"}
        assert required.issubset(set(calib_data.keys()))

    def test_swap_curves_lengths(self, swap_data):
        n = len(swap_data["expiries"])
        assert n == 48, f"Expected 48 expiries, got {n}"
        assert len(swap_data["var_swaps"]) == n
        assert len(swap_data["gamma_swaps"]) == n
        assert len(swap_data["norm_leverage"]) == n

    def test_model_leverage_length(self, calib_data, swap_data):
        n = len(swap_data["expiries"])
        assert len(calib_data["model_norm_leverage"]) == n


class TestVarianceSwaps:
    """Verify variance swap computation via Fukasawa robust methodology."""

    # Reference values at selected expiries (index, expected_value, rel_tol)
    REFERENCE_VS = [
        (5, 0.02593, 0.015),    # T ~ 0.025y (9 days)
        (12, 0.02708, 0.015),   # T ~ 0.055y (20 days)
        (26, 0.03899, 0.015),   # T ~ 0.197y (72 days)
        (33, 0.04939, 0.015),   # T ~ 0.504y (184 days)
        (41, 0.05449, 0.015),   # T ~ 1.002y (366 days)
        (46, 0.05712, 0.02),    # T ~ 3.838y (3.8 years)
    ]

    @pytest.mark.parametrize("idx,expected,rtol", REFERENCE_VS)
    def test_variance_swap_value(self, swap_data, idx, expected, rtol):
        vs = swap_data["var_swaps"][idx]
        assert abs(vs - expected) / expected < rtol, (
            f"VarSwap at idx={idx}: got {vs:.6f}, expected ~{expected:.5f} "
            f"(rel err = {abs(vs - expected)/expected:.4f}, tol = {rtol})"
        )

    def test_variance_swaps_positive(self, swap_data):
        vs = np.array(swap_data["var_swaps"])
        assert np.all(vs > 0), "All variance swaps must be positive"

    def test_variance_swaps_range(self, swap_data):
        vs = np.array(swap_data["var_swaps"])
        assert np.all(vs > 0.005), "Variance swaps unreasonably small"
        assert np.all(vs < 0.2), "Variance swaps unreasonably large"


class TestGammaSwaps:
    """Verify gamma swap computation via Fukasawa robust methodology."""

    REFERENCE_GS = [
        (5, 0.02549, 0.015),    # T ~ 0.025y
        (12, 0.02646, 0.015),   # T ~ 0.055y
        (26, 0.03581, 0.015),   # T ~ 0.197y
        (33, 0.04112, 0.015),   # T ~ 0.504y
        (41, 0.04239, 0.015),   # T ~ 1.002y
        (46, 0.04218, 0.02),    # T ~ 3.838y
    ]

    @pytest.mark.parametrize("idx,expected,rtol", REFERENCE_GS)
    def test_gamma_swap_value(self, swap_data, idx, expected, rtol):
        gs = swap_data["gamma_swaps"][idx]
        assert abs(gs - expected) / expected < rtol, (
            f"GammaSwap at idx={idx}: got {gs:.6f}, expected ~{expected:.5f} "
            f"(rel err = {abs(gs - expected)/expected:.4f}, tol = {rtol})"
        )

    def test_gamma_swaps_positive(self, swap_data):
        gs = np.array(swap_data["gamma_swaps"])
        assert np.all(gs > 0), "All gamma swaps must be positive"

    def test_gamma_less_than_variance(self, swap_data):
        """Gamma swap should be less than variance swap (negative leverage effect)."""
        vs = np.array(swap_data["var_swaps"])
        gs = np.array(swap_data["gamma_swaps"])
        # At least 90% of expiries should show gamma < variance
        frac = np.mean(gs < vs)
        assert frac >= 0.90, (
            f"Expected gamma < variance for at least 90% of expiries, got {frac:.2%}"
        )


class TestNormalizedLeverage:
    """Verify normalized leverage contract computation."""

    def test_leverage_negative(self, swap_data):
        """Leverage effect: normalized leverage should be negative for equity indices."""
        nl = np.array(swap_data["norm_leverage"])
        # At least 95% should be negative
        frac_neg = np.mean(nl < 0)
        assert frac_neg >= 0.95, (
            f"Expected at least 95% negative normalized leverage, got {frac_neg:.2%}"
        )

    def test_leverage_magnitude_increases(self, swap_data):
        """Absolute normalized leverage should generally increase with maturity."""
        nl = np.array(swap_data["norm_leverage"])
        expiries = np.array(swap_data["expiries"])
        # Compare short-term average (first 10) vs long-term average (last 10)
        short_avg = np.mean(np.abs(nl[:10]))
        long_avg = np.mean(np.abs(nl[-10:]))
        assert long_avg > short_avg * 3, (
            f"Long-term |leverage| ({long_avg:.4f}) should be much larger than "
            f"short-term ({short_avg:.4f})"
        )

    REFERENCE_NL = [
        (5, -0.01677, 0.10),    # T ~ 0.025y
        (12, -0.02286, 0.10),   # T ~ 0.055y
        (26, -0.08170, 0.08),   # T ~ 0.197y
        (33, -0.16734, 0.06),   # T ~ 0.504y
        (41, -0.22150, 0.06),   # T ~ 1.002y
    ]

    @pytest.mark.parametrize("idx,expected,rtol", REFERENCE_NL)
    def test_normalized_leverage_value(self, swap_data, idx, expected, rtol):
        nl = swap_data["norm_leverage"][idx]
        assert abs(nl - expected) / abs(expected) < rtol, (
            f"NormLeverage at idx={idx}: got {nl:.6f}, expected ~{expected:.5f}"
        )


class TestCalibration:
    """Verify rough Heston parameter calibration."""

    def test_H_positive(self, calib_data):
        assert calib_data["H"] > 0, "Hurst parameter must be positive"

    def test_H_bounded(self, calib_data):
        assert calib_data["H"] <= 1.0, "Hurst parameter must be <= 1"

    def test_nu_positive(self, calib_data):
        assert calib_data["nu"] > 0, "Vol-of-vol must be positive"

    def test_rho_negative(self, calib_data):
        assert calib_data["rho"] < 0, "Correlation must be negative (leverage effect)"

    def test_rho_bounded(self, calib_data):
        assert calib_data["rho"] > -1.0, "Correlation must be > -1"

    def test_lambda_nonnegative(self, calib_data):
        assert calib_data["lbd"] >= 0, "Mean reversion must be non-negative"

    def test_rmse_below_threshold(self, calib_data):
        """The calibration fit quality should be reasonable."""
        assert calib_data["rmse"] < 0.02, (
            f"RMSE = {calib_data['rmse']:.6f} exceeds threshold of 0.02"
        )

    def test_model_leverage_negative(self, calib_data):
        """Model normalized leverage should be negative everywhere."""
        ml = np.array(calib_data["model_norm_leverage"])
        assert np.all(ml < 0), "Model normalized leverage must be negative"

    def test_model_fit_correlation(self, swap_data, calib_data):
        """Model leverage should be highly correlated with empirical leverage."""
        emp = np.array(swap_data["norm_leverage"])
        model = np.array(calib_data["model_norm_leverage"])
        corr = np.corrcoef(emp, model)[0, 1]
        assert corr > 0.98, (
            f"Correlation between model and empirical leverage = {corr:.4f}, "
            f"expected > 0.98"
        )

    def test_lambda_prime_positive(self, calib_data):
        """lambda' = lambda - rho*nu must be positive for model admissibility."""
        lbdp = calib_data["lbd"] - calib_data["rho"] * calib_data["nu"]
        assert lbdp > 0, (
            f"lambda' = {lbdp:.6f} must be positive "
            f"(lambda={calib_data['lbd']:.4f}, rho*nu={calib_data['rho']*calib_data['nu']:.4f})"
        )


class TestMittagLefflerFormula:
    """Verify the rough Heston normalized leverage formula implementation."""

    def test_model_monotonic_in_maturity(self, calib_data):
        """Model |normalized leverage| should be monotonically increasing with T."""
        ml = np.abs(np.array(calib_data["model_norm_leverage"]))
        # Allow up to 2 violations due to numerical noise
        violations = np.sum(np.diff(ml) < -1e-6)
        assert violations <= 2, (
            f"Model |leverage| should be monotonic, found {violations} violations"
        )

    def test_short_term_leverage_small(self, calib_data):
        """At very short maturities, |leverage| should be small."""
        ml = np.array(calib_data["model_norm_leverage"])
        assert abs(ml[0]) < 0.10, (
            f"|Model leverage| at shortest maturity = {abs(ml[0]):.4f}, expected < 0.10"
        )

    def test_long_term_leverage_bounded(self, calib_data):
        """Model leverage should stay bounded (rough Heston has finite long-term limit)."""
        ml = np.array(calib_data["model_norm_leverage"])
        H = calib_data["H"]
        rho = calib_data["rho"]
        nu = calib_data["nu"]
        lbd = calib_data["lbd"]
        lbdp = lbd - rho * nu
        # Theoretical long-term limit: rho*nu/lbdp
        limit = rho * nu / lbdp
        # Last model value should be within 50% of the theoretical limit
        assert abs(ml[-1]) < abs(limit) * 1.5, (
            f"|Model leverage| at longest T = {abs(ml[-1]):.4f}, "
            f"theoretical limit = {abs(limit):.4f}"
        )
