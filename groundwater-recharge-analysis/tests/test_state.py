"""Tests for groundwater system characterization results.

Validates structure, physical plausibility, and statistical correctness
of the groundwater analysis results.
"""

import json
import os
from datetime import datetime

import pytest

RESULTS_PATH = "/app/results.json"


@pytest.fixture
def results():
    """Load and return the results JSON."""
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    """Verify the results file has all required fields."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_top_level_keys(self, results):
        required = [
            "et_stats",
            "models",
            "best_model",
            "best_model_evp",
            "response_time_95",
            "step_response_gain",
            "durbin_watson",
            "n_observations",
            "calibration_period",
            "validation",
            "residual_diagnostics",
        ]
        for key in required:
            assert key in results, f"Missing top-level key: {key}"

    def test_et_stats_structure(self, results):
        et = results["et_stats"]
        assert "method" in et
        assert "mean_mm_day" in et
        assert "annual_total_mm" in et

    def test_models_structure(self, results):
        models = results["models"]
        assert len(models) == 3, f"Expected 3 models, got {len(models)}"
        for name in ["Exponential", "Gamma", "FourParam"]:
            assert name in models, f"Missing model: {name}"
            m = models[name]
            for key in ["evp", "rmse", "aic", "n_parameters"]:
                assert key in m, f"Model {name} missing key: {key}"

    def test_calibration_period_structure(self, results):
        cp = results["calibration_period"]
        assert "start" in cp
        assert "end" in cp

    def test_validation_structure(self, results):
        val = results["validation"]
        assert "evp" in val
        assert "rmse" in val
        assert "period" in val
        assert "start" in val["period"]
        assert "end" in val["period"]

    def test_residual_diagnostics_structure(self, results):
        rd = results["residual_diagnostics"]
        assert "lag1_autocorrelation" in rd
        assert "seasonal_amplitude_m" in rd


class TestETStatistics:
    """Verify evapotranspiration computation is physically plausible."""

    def test_et_method_specified(self, results):
        method = results["et_stats"]["method"]
        assert isinstance(method, str) and len(method) > 0, (
            "ET method must be a non-empty string"
        )

    def test_et_mean_plausible(self, results):
        mean_et = results["et_stats"]["mean_mm_day"]
        assert 0.5 < mean_et < 5.0, (
            f"Mean ET {mean_et} mm/day outside plausible range for temperate climate"
        )

    def test_et_annual_total_plausible(self, results):
        annual = results["et_stats"]["annual_total_mm"]
        assert 200 < annual < 1500, (
            f"Annual ET {annual} mm outside plausible range for temperate climate"
        )

    def test_et_mean_annual_consistent(self, results):
        mean_et = results["et_stats"]["mean_mm_day"]
        annual = results["et_stats"]["annual_total_mm"]
        expected_annual = mean_et * 365.25
        assert abs(annual - expected_annual) / expected_annual < 0.15, (
            f"Annual total {annual} inconsistent with mean {mean_et} mm/day"
        )


class TestModelComparison:
    """Verify model comparison results are reasonable."""

    def test_all_models_have_positive_evp(self, results):
        for name, m in results["models"].items():
            assert m["evp"] > 20.0, (
                f"Model {name} EVP={m['evp']}% is too low for this dataset"
            )

    def test_all_models_have_positive_rmse(self, results):
        for name, m in results["models"].items():
            assert 0 < m["rmse"] < 5.0, (
                f"Model {name} RMSE={m['rmse']} outside expected range"
            )

    def test_best_model_evp_reasonable(self, results):
        assert results["best_model_evp"] > 40.0, (
            f"Best model EVP={results['best_model_evp']}% too low"
        )

    def test_best_model_is_in_models(self, results):
        assert results["best_model"] in results["models"]

    def test_best_model_evp_matches(self, results):
        best = results["best_model"]
        assert abs(results["best_model_evp"] - results["models"][best]["evp"]) < 0.1

    def test_aic_ranking_consistent(self, results):
        """Best model must have the lowest (or tied) AIC."""
        best = results["best_model"]
        best_aic = results["models"][best]["aic"]
        for name, m in results["models"].items():
            assert m["aic"] >= best_aic - 0.5, (
                f"Model {name} AIC={m['aic']} < best model {best} AIC={best_aic}"
            )

    def test_n_parameters_ordering(self, results):
        """Exponential < Gamma < FourParam in parameter count."""
        models = results["models"]
        assert models["Exponential"]["n_parameters"] < models["FourParam"]["n_parameters"], (
            "Exponential should have fewer parameters than FourParam"
        )


class TestResponseFunction:
    """Verify response function characteristics."""

    def test_response_time_95_range(self, results):
        t95 = results["response_time_95"]
        assert 30 < t95 < 3000, (
            f"95% response time {t95} days outside physically reasonable range"
        )

    def test_step_response_gain_positive(self, results):
        gain = results["step_response_gain"]
        assert gain > 0, f"Step response gain must be positive, got {gain}"
        assert gain < 1000, f"Step response gain {gain} unreasonably large"


class TestDiagnostics:
    """Verify diagnostic statistics."""

    def test_durbin_watson_range(self, results):
        dw = results["durbin_watson"]
        assert 0 < dw < 4, f"Durbin-Watson {dw} outside valid range [0, 4]"

    def test_n_observations_reasonable(self, results):
        n = results["n_observations"]
        assert n > 1000, f"Expected >1000 observations, got {n}"
        assert n < 10000, f"Too many observations ({n}), data is ~5844 days"


class TestResidualDiagnostics:
    """Verify residual diagnostics for model adequacy assessment."""

    def test_lag1_autocorrelation_valid(self, results):
        r1 = results["residual_diagnostics"]["lag1_autocorrelation"]
        assert -1.0 <= r1 <= 1.0, (
            f"Lag-1 autocorrelation {r1} outside valid range [-1, 1]"
        )

    def test_lag1_autocorrelation_is_float(self, results):
        r1 = results["residual_diagnostics"]["lag1_autocorrelation"]
        assert isinstance(r1, (int, float)), (
            f"Lag-1 autocorrelation must be numeric, got {type(r1)}"
        )

    def test_seasonal_amplitude_non_negative(self, results):
        amp = results["residual_diagnostics"]["seasonal_amplitude_m"]
        assert amp >= 0, f"Seasonal amplitude must be non-negative, got {amp}"

    def test_seasonal_amplitude_bounded(self, results):
        amp = results["residual_diagnostics"]["seasonal_amplitude_m"]
        assert amp < 2.0, (
            f"Seasonal amplitude {amp} m unreasonably large for well-fitted model"
        )


class TestSplitSampleValidation:
    """Verify split-sample validation was performed correctly."""

    def test_validation_evp_reasonable(self, results):
        val_evp = results["validation"]["evp"]
        assert val_evp > 10.0, (
            f"Validation EVP={val_evp}% too low, model may not generalize"
        )

    def test_validation_rmse_positive(self, results):
        val_rmse = results["validation"]["rmse"]
        assert 0 < val_rmse < 5.0, (
            f"Validation RMSE={val_rmse} outside expected range"
        )

    def test_periods_non_overlapping(self, results):
        cal_end = datetime.strptime(results["calibration_period"]["end"], "%Y-%m-%d")
        val_start = datetime.strptime(
            results["validation"]["period"]["start"], "%Y-%m-%d"
        )
        assert val_start >= cal_end, (
            f"Validation start {val_start} must be >= calibration end {cal_end}"
        )

    def test_calibration_period_length(self, results):
        cal_start = datetime.strptime(
            results["calibration_period"]["start"], "%Y-%m-%d"
        )
        cal_end = datetime.strptime(results["calibration_period"]["end"], "%Y-%m-%d")
        cal_days = (cal_end - cal_start).days
        assert cal_days >= 5 * 365, (
            f"Calibration period {cal_days} days is less than 5 years"
        )

    def test_validation_period_length(self, results):
        val_start = datetime.strptime(
            results["validation"]["period"]["start"], "%Y-%m-%d"
        )
        val_end = datetime.strptime(
            results["validation"]["period"]["end"], "%Y-%m-%d"
        )
        val_days = (val_end - val_start).days
        assert val_days >= 2 * 365, (
            f"Validation period {val_days} days is less than 2 years"
        )

    def test_validation_evp_less_than_calibration(self, results):
        """Validation EVP should generally be <= calibration EVP."""
        cal_evp = results["best_model_evp"]
        val_evp = results["validation"]["evp"]
        assert val_evp <= cal_evp + 5.0, (
            f"Validation EVP ({val_evp}%) significantly exceeds calibration "
            f"EVP ({cal_evp}%), which is suspicious"
        )
