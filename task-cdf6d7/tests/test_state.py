
"""Verification tests for the groundwater impulse-response model calibration task."""

import json
import os

import numpy as np
import pandas as pd
import pytest


RESULTS_PATH = "/app/results.json"
HEAD_PATH = "/app/head.csv"


@pytest.fixture
def results():
    """Load the results JSON file."""
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH, "r") as f:
        data = json.load(f)
    return data


@pytest.fixture
def head_data():
    """Load the head observations."""
    df = pd.read_csv(HEAD_PATH, parse_dates=["date"], index_col="date")
    return df["head"]


class TestResultsSchema:
    """Verify the results file has all required fields."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json does not exist"

    def test_top_level_keys(self, results):
        required = [
            "exponential_model",
            "gamma_model",
            "best_model",
            "cross_validation",
            "diagnostics",
        ]
        for key in required:
            assert key in results, f"Missing top-level key: {key}"

    def test_exponential_model_keys(self, results):
        required = ["evp", "rmse", "aic", "n_parameters", "response_time_95pct"]
        for key in required:
            assert key in results["exponential_model"], (
                f"Missing key in exponential_model: {key}"
            )

    def test_gamma_model_keys(self, results):
        required = ["evp", "rmse", "aic", "n_parameters"]
        for key in required:
            assert key in results["gamma_model"], (
                f"Missing key in gamma_model: {key}"
            )

    def test_cross_validation_keys(self, results):
        required = ["calibration_evp", "validation_rmse", "validation_nse"]
        for key in required:
            assert key in results["cross_validation"], (
                f"Missing key in cross_validation: {key}"
            )

    def test_diagnostics_keys(self, results):
        required = [
            "durbin_watson",
            "acf_lag1",
            "mean_residual",
            "std_residual",
            "n_observations",
        ]
        for key in required:
            assert key in results["diagnostics"], (
                f"Missing key in diagnostics: {key}"
            )


class TestModelFitQuality:
    """Verify that the models achieve reasonable goodness-of-fit."""

    def test_exponential_evp(self, results):
        """Exponential model should explain substantial variance."""
        evp = results["exponential_model"]["evp"]
        assert isinstance(evp, (int, float)), "EVP must be numeric"
        assert evp > 70.0, f"Exponential model EVP ({evp:.1f}%) is too low"
        assert evp <= 100.0, f"Exponential model EVP ({evp:.1f}%) exceeds 100%"

    def test_gamma_evp(self, results):
        """Gamma model should explain substantial variance."""
        evp = results["gamma_model"]["evp"]
        assert isinstance(evp, (int, float)), "EVP must be numeric"
        assert evp > 70.0, f"Gamma model EVP ({evp:.1f}%) is too low"
        assert evp <= 100.0, f"Gamma model EVP ({evp:.1f}%) exceeds 100%"

    def test_exponential_rmse(self, results):
        """RMSE should be small relative to head variation."""
        rmse = results["exponential_model"]["rmse"]
        assert isinstance(rmse, (int, float)), "RMSE must be numeric"
        assert rmse > 0, "RMSE must be positive"
        assert rmse < 2.0, f"Exponential model RMSE ({rmse:.3f}m) is too high"

    def test_gamma_rmse(self, results):
        """RMSE should be small relative to head variation."""
        rmse = results["gamma_model"]["rmse"]
        assert isinstance(rmse, (int, float)), "RMSE must be numeric"
        assert rmse > 0, "RMSE must be positive"
        assert rmse < 2.0, f"Gamma model RMSE ({rmse:.3f}m) is too high"


class TestModelComparison:
    """Verify that model comparison is performed correctly."""

    def test_best_model_value(self, results):
        """best_model must be 'exponential' or 'gamma'."""
        assert results["best_model"] in ("exponential", "gamma"), (
            f"best_model must be 'exponential' or 'gamma', got '{results['best_model']}'"
        )

    def test_aic_consistency(self, results):
        """The selected best model should have lower or equal AIC."""
        aic_exp = results["exponential_model"]["aic"]
        aic_gam = results["gamma_model"]["aic"]
        best = results["best_model"]
        if best == "exponential":
            assert aic_exp <= aic_gam, (
                f"Selected exponential but its AIC ({aic_exp:.1f}) > gamma AIC ({aic_gam:.1f})"
            )
        else:
            assert aic_gam <= aic_exp, (
                f"Selected gamma but its AIC ({aic_gam:.1f}) > exponential AIC ({aic_exp:.1f})"
            )

    def test_best_model_is_gamma(self, results):
        """Gamma response with n near 1 still outperforms pure exponential by AIC."""
        assert results["best_model"] == "gamma", (
            "The gamma model achieves a lower AIC than the exponential model "
            f"for this dataset, but got '{results['best_model']}'"
        )

    def test_parameter_counts(self, results):
        """Exponential has fewer parameters than Gamma."""
        n_exp = results["exponential_model"]["n_parameters"]
        n_gam = results["gamma_model"]["n_parameters"]
        assert isinstance(n_exp, int), "n_parameters must be an integer"
        assert isinstance(n_gam, int), "n_parameters must be an integer"
        assert n_exp >= 4, f"Too few parameters for exponential model: {n_exp}"
        assert n_gam >= 5, f"Too few parameters for gamma model: {n_gam}"
        assert n_gam > n_exp, (
            f"Gamma ({n_gam} params) should have more params than Exponential ({n_exp})"
        )


class TestResponseFunction:
    """Verify response function properties."""

    def test_response_time_range(self, results):
        """Response time at 95% should be physically reasonable."""
        rt = results["exponential_model"]["response_time_95pct"]
        assert isinstance(rt, (int, float)), "response_time_95pct must be numeric"
        assert rt > 50, f"Response time ({rt:.0f} days) is unrealistically short"
        assert rt < 1500, f"Response time ({rt:.0f} days) is unrealistically long"

    def test_response_time_approximate_value(self, results):
        """Response time should be in expected range for this aquifer system."""
        rt = results["exponential_model"]["response_time_95pct"]
        assert 100 < rt < 800, (
            f"Response time ({rt:.0f} days) outside expected range [100, 800]"
        )


class TestCrossValidation:
    """Verify temporal cross-validation results."""

    def test_calibration_evp(self, results):
        """Calibration EVP should be reasonable."""
        evp = results["cross_validation"]["calibration_evp"]
        assert isinstance(evp, (int, float)), "calibration_evp must be numeric"
        assert evp > 60.0, f"Calibration EVP ({evp:.1f}%) is too low"

    def test_validation_rmse(self, results):
        """Validation RMSE should be reasonable."""
        rmse = results["cross_validation"]["validation_rmse"]
        assert isinstance(rmse, (int, float)), "validation_rmse must be numeric"
        assert rmse > 0, "Validation RMSE must be positive"
        assert rmse < 3.0, f"Validation RMSE ({rmse:.3f}m) is too high"

    def test_validation_nse(self, results):
        """Validation NSE should indicate decent predictive skill."""
        nse = results["cross_validation"]["validation_nse"]
        assert isinstance(nse, (int, float)), "validation_nse must be numeric"
        assert nse > 0.3, f"Validation NSE ({nse:.3f}) indicates poor prediction"
        assert nse <= 1.0, f"Validation NSE ({nse:.3f}) exceeds theoretical max"

    def test_validation_degrades_gracefully(self, results):
        """Validation performance should not vastly exceed calibration."""
        cal_evp = results["cross_validation"]["calibration_evp"]
        val_nse = results["cross_validation"]["validation_nse"]
        assert val_nse * 100 < cal_evp + 15, (
            "Validation NSE suspiciously exceeds calibration EVP"
        )


class TestDiagnostics:
    """Verify diagnostic statistics."""

    def test_durbin_watson_range(self, results):
        """Durbin-Watson should be between 0 and 4."""
        dw = results["diagnostics"]["durbin_watson"]
        assert isinstance(dw, (int, float)), "durbin_watson must be numeric"
        assert 0 < dw < 4, f"Durbin-Watson ({dw:.3f}) outside valid range [0, 4]"

    def test_durbin_watson_reasonable(self, results):
        """DW should indicate non-negative residual autocorrelation."""
        dw = results["diagnostics"]["durbin_watson"]
        assert 0.001 < dw < 2.5, (
            f"Durbin-Watson ({dw:.4f}) outside expected range for transfer function model"
        )

    def test_acf_lag1_range(self, results):
        """ACF at lag 1 should be between -1 and 1."""
        acf = results["diagnostics"]["acf_lag1"]
        assert isinstance(acf, (int, float)), "acf_lag1 must be numeric"
        assert -1.0 <= acf <= 1.0, f"ACF lag 1 ({acf:.3f}) outside valid range"

    def test_mean_residual_near_zero(self, results):
        """Mean residual should be near zero for a well-fitted model."""
        mean_res = results["diagnostics"]["mean_residual"]
        assert isinstance(mean_res, (int, float)), "mean_residual must be numeric"
        assert abs(mean_res) < 1.0, (
            f"Mean residual ({mean_res:.4f}m) is too far from zero"
        )

    def test_std_residual_reasonable(self, results):
        """Residual std should be small relative to signal."""
        std_res = results["diagnostics"]["std_residual"]
        assert isinstance(std_res, (int, float)), "std_residual must be numeric"
        assert std_res > 0, "std_residual must be positive"
        assert std_res < 2.0, f"Residual std ({std_res:.3f}m) is too large"

    def test_n_observations(self, results, head_data):
        """Number of observations should match the input data."""
        n_obs = results["diagnostics"]["n_observations"]
        n_actual = len(head_data)
        assert isinstance(n_obs, int), "n_observations must be an integer"
        assert abs(n_obs - n_actual) < n_actual * 0.1, (
            f"n_observations ({n_obs}) doesn't match input data ({n_actual})"
        )


class TestPhysicalConsistency:
    """Verify that results are physically consistent."""

    def test_both_models_fit_similarly(self, results):
        """Gamma should fit at least as well as Exponential (more parameters)."""
        evp_exp = results["exponential_model"]["evp"]
        evp_gam = results["gamma_model"]["evp"]
        assert evp_gam >= evp_exp - 5.0, (
            f"Gamma EVP ({evp_gam:.1f}%) much worse than Exponential ({evp_exp:.1f}%) "
            "despite having more parameters"
        )

    def test_aic_values_finite(self, results):
        """AIC values should be finite numbers."""
        aic_exp = results["exponential_model"]["aic"]
        aic_gam = results["gamma_model"]["aic"]
        assert np.isfinite(aic_exp), "Exponential AIC is not finite"
        assert np.isfinite(aic_gam), "Gamma AIC is not finite"
