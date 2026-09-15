"""Tests for the dynamical system model selection task.

Verifies model ranking, parameter estimation, forward predictions, and diagnostics.
"""


import json

import numpy as np
import pytest
from scipy.integrate import solve_ivp

# True generative parameters (known to the test, not the agent)
TRUE_ALPHA = 0.55
TRUE_BETA = 0.028
TRUE_GAMMA = 0.80
TRUE_DELTA = 0.024
Y0 = [30.0, 10.0]
T_START = 0.0
NOISE_STD = 0.5
PREDICTION_TIMES = [26.0, 27.0, 28.0, 29.0, 30.0]


def _true_rhs(t, y):
    return [TRUE_ALPHA * y[0] - TRUE_BETA * y[0] * y[1],
            -TRUE_GAMMA * y[1] + TRUE_DELTA * y[0] * y[1]]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ranking():
    with open("/app/results/ranking.json") as f:
        return json.load(f)


@pytest.fixture
def selected():
    with open("/app/results/selected_model.json") as f:
        return json.load(f)


@pytest.fixture
def prediction():
    with open("/app/results/prediction.json") as f:
        return json.load(f)


@pytest.fixture
def diagnostics():
    with open("/app/results/diagnostics.json") as f:
        return json.load(f)


@pytest.fixture
def true_future():
    """High-accuracy reference trajectory at prediction times."""
    sol = solve_ivp(_true_rhs, [T_START, max(PREDICTION_TIMES) + 0.1], Y0,
                    method="DOP853", t_eval=PREDICTION_TIMES,
                    rtol=1e-12, atol=1e-14)
    assert sol.status == 0
    return sol.y  # shape (2, 5)


# ---------------------------------------------------------------------------
# Model selection tests
# ---------------------------------------------------------------------------

class TestModelSelection:
    """Verify the agent selects the correct model."""

    def test_ranking_has_four_models(self, ranking):
        assert "rankings" in ranking
        assert len(ranking["rankings"]) == 4, (
            f"Expected 4 models in ranking, got {len(ranking['rankings'])}"
        )

    def test_ranking_entries_have_required_fields(self, ranking):
        for entry in ranking["rankings"]:
            assert "model" in entry, "Each ranking entry must have 'model'"
            assert "score" in entry, "Each ranking entry must have 'score'"

    def test_all_four_models_present(self, ranking):
        models = {e["model"] for e in ranking["rankings"]}
        assert models == {"model_a", "model_b", "model_c", "model_d"}, (
            f"Expected all four models, got {models}"
        )

    def test_model_a_ranked_first(self, ranking):
        """Model A (classic Lotka-Volterra) should be the best model."""
        best = ranking["rankings"][0]["model"]
        assert best == "model_a", (
            f"Expected model_a ranked first, got {best}"
        )

    def test_selected_model_name(self, selected):
        assert selected["name"] == "model_a", (
            f"Expected selected model 'model_a', got {selected['name']}"
        )

    def test_selected_has_fitted_parameters(self, selected):
        assert "fitted_parameters" in selected
        assert isinstance(selected["fitted_parameters"], dict)
        assert len(selected["fitted_parameters"]) >= 4


# ---------------------------------------------------------------------------
# Parameter estimation tests
# ---------------------------------------------------------------------------

class TestParameterEstimation:
    """Verify estimated parameters are close to the true values."""

    def test_alpha(self, selected):
        p = selected["fitted_parameters"]
        assert "alpha" in p, "Missing parameter 'alpha'"
        assert abs(p["alpha"] - TRUE_ALPHA) < 0.15, (
            f"alpha={p['alpha']:.4f}, expected ~{TRUE_ALPHA}"
        )

    def test_beta(self, selected):
        p = selected["fitted_parameters"]
        assert "beta" in p, "Missing parameter 'beta'"
        assert abs(p["beta"] - TRUE_BETA) < 0.010, (
            f"beta={p['beta']:.5f}, expected ~{TRUE_BETA}"
        )

    def test_gamma(self, selected):
        p = selected["fitted_parameters"]
        assert "gamma" in p, "Missing parameter 'gamma'"
        assert abs(p["gamma"] - TRUE_GAMMA) < 0.25, (
            f"gamma={p['gamma']:.4f}, expected ~{TRUE_GAMMA}"
        )

    def test_delta(self, selected):
        p = selected["fitted_parameters"]
        assert "delta" in p, "Missing parameter 'delta'"
        assert abs(p["delta"] - TRUE_DELTA) < 0.010, (
            f"delta={p['delta']:.5f}, expected ~{TRUE_DELTA}"
        )

    def test_parameters_positive(self, selected):
        for name, val in selected["fitted_parameters"].items():
            assert val > 0, f"Parameter {name}={val} must be positive"


# ---------------------------------------------------------------------------
# Prediction tests
# ---------------------------------------------------------------------------

class TestPredictions:
    """Verify forward trajectory predictions."""

    def test_prediction_format(self, prediction):
        for key in ["times", "y1_mean", "y2_mean", "y1_std", "y2_std"]:
            assert key in prediction, f"Missing key '{key}' in prediction.json"
        assert len(prediction["times"]) == 5

    def test_prediction_rmse_y1(self, prediction, true_future):
        y1_pred = np.array(prediction["y1_mean"])
        y1_true = true_future[0]
        rmse = np.sqrt(np.mean((y1_pred - y1_true) ** 2))
        assert rmse < 15.0, (
            f"y1 prediction RMSE={rmse:.2f}, expected < 15.0"
        )

    def test_prediction_rmse_y2(self, prediction, true_future):
        y2_pred = np.array(prediction["y2_mean"])
        y2_true = true_future[1]
        rmse = np.sqrt(np.mean((y2_pred - y2_true) ** 2))
        assert rmse < 15.0, (
            f"y2 prediction RMSE={rmse:.2f}, expected < 15.0"
        )

    def test_uncertainty_positive(self, prediction):
        for key in ["y1_std", "y2_std"]:
            for i, s in enumerate(prediction[key]):
                assert s > 0, f"{key}[{i}]={s} must be positive"

    def test_uncertainty_finite(self, prediction):
        for key in ["y1_std", "y2_std"]:
            for i, s in enumerate(prediction[key]):
                assert np.isfinite(s), f"{key}[{i}]={s} must be finite"

    def test_predictions_finite(self, prediction):
        for key in ["y1_mean", "y2_mean"]:
            for i, v in enumerate(prediction[key]):
                assert np.isfinite(v), f"{key}[{i}]={v} must be finite"


# ---------------------------------------------------------------------------
# Diagnostic tests
# ---------------------------------------------------------------------------

class TestDiagnostics:
    """Verify model-fit diagnostics."""

    def test_diagnostics_format(self, diagnostics):
        for key in ["training_rmse_y1", "training_rmse_y2",
                     "normalized_residual_variance_y1",
                     "normalized_residual_variance_y2"]:
            assert key in diagnostics, f"Missing key '{key}'"

    def test_rmse_y1_reasonable(self, diagnostics):
        val = diagnostics["training_rmse_y1"]
        assert 0.1 < val < 3.0, (
            f"training_rmse_y1={val:.4f}, expected in (0.1, 3.0) near noise_std={NOISE_STD}"
        )

    def test_rmse_y2_reasonable(self, diagnostics):
        val = diagnostics["training_rmse_y2"]
        assert 0.1 < val < 3.0, (
            f"training_rmse_y2={val:.4f}, expected in (0.1, 3.0) near noise_std={NOISE_STD}"
        )

    def test_residual_variance_y1(self, diagnostics):
        val = diagnostics["normalized_residual_variance_y1"]
        assert 0.2 < val < 5.0, (
            f"normalized_residual_variance_y1={val:.4f}, expected near 1.0"
        )

    def test_residual_variance_y2(self, diagnostics):
        val = diagnostics["normalized_residual_variance_y2"]
        assert 0.2 < val < 5.0, (
            f"normalized_residual_variance_y2={val:.4f}, expected near 1.0"
        )
