
import json
import math
import os
import subprocess
import sys

import pytest

# Ground truth parameters (embedded, not from external file)
GT_E_A1 = 150000.0  # J/mol
GT_A1 = 5e12  # 1/s
GT_W1 = 0.55
GT_E_A2 = 185000.0  # J/mol
GT_A2 = 5e14  # 1/s
GT_W2 = 0.45

# Ground truth predictions at beta=7.5 K/min (pre-computed via ODE integration)
GT_PREDICTIONS = {
    "480.0": 0.012667186872149353,
    "520.0": 0.21710319296317357,
    "540.0": 0.49476107643679484,
    "560.0": 0.6653591306696689,
    "580.0": 0.8720074808522112,
    "620.0": 0.9999999817455002,
    "700.0": 1.0,
}

RESULTS_PATH = "/app/results.json"
ANALYZE_SCRIPT = "/app/analyze.py"


@pytest.fixture(scope="session")
def run_analysis():
    """Run the analysis script and return the results."""
    assert os.path.isfile(ANALYZE_SCRIPT), (
        f"Analysis script not found at {ANALYZE_SCRIPT}"
    )
    result = subprocess.run(
        [sys.executable, ANALYZE_SCRIPT],
        capture_output=True,
        text=True,
        timeout=300,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"analyze.py failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout[-2000:]}\n"
        f"stderr: {result.stderr[-2000:]}"
    )
    assert os.path.isfile(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}"
    )


@pytest.fixture(scope="session")
def results(run_analysis):
    """Load results.json after running analysis."""
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestResultsSchema:
    """Verify the output has the correct structure."""

    def test_has_reaction_1(self, results):
        assert "reaction_1" in results

    def test_has_reaction_2(self, results):
        assert "reaction_2" in results

    def test_has_predictions(self, results):
        assert "predictions_beta_7_5" in results

    def test_reaction_1_keys(self, results):
        r1 = results["reaction_1"]
        for key in [
            "activation_energy_J_mol",
            "pre_exponential_factor_per_s",
            "weight_fraction",
        ]:
            assert key in r1, f"Missing key {key} in reaction_1"
            assert isinstance(r1[key], (int, float)), f"{key} must be numeric"

    def test_reaction_2_keys(self, results):
        r2 = results["reaction_2"]
        for key in [
            "activation_energy_J_mol",
            "pre_exponential_factor_per_s",
            "weight_fraction",
        ]:
            assert key in r2, f"Missing key {key} in reaction_2"
            assert isinstance(r2[key], (int, float)), f"{key} must be numeric"

    def test_prediction_keys(self, results):
        preds = results["predictions_beta_7_5"]
        for temp in ["480.0", "520.0", "540.0", "560.0", "580.0", "620.0", "700.0"]:
            assert temp in preds, f"Missing prediction for T={temp}"


class TestActivationEnergies:
    """Verify recovered activation energies are within tolerance."""

    def test_ea1_relative_error(self, results):
        ea1 = results["reaction_1"]["activation_energy_J_mol"]
        rel_err = abs(ea1 - GT_E_A1) / GT_E_A1
        assert rel_err < 0.08, (
            f"E_a1 relative error {rel_err:.4f} exceeds 8%. "
            f"Got {ea1:.0f}, expected {GT_E_A1:.0f}"
        )

    def test_ea2_relative_error(self, results):
        ea2 = results["reaction_2"]["activation_energy_J_mol"]
        rel_err = abs(ea2 - GT_E_A2) / GT_E_A2
        assert rel_err < 0.08, (
            f"E_a2 relative error {rel_err:.4f} exceeds 8%. "
            f"Got {ea2:.0f}, expected {GT_E_A2:.0f}"
        )

    def test_ea1_positive(self, results):
        ea1 = results["reaction_1"]["activation_energy_J_mol"]
        assert ea1 > 0, "Activation energy must be positive"

    def test_ea2_positive(self, results):
        ea2 = results["reaction_2"]["activation_energy_J_mol"]
        assert ea2 > 0, "Activation energy must be positive"

    def test_ea1_less_than_ea2(self, results):
        ea1 = results["reaction_1"]["activation_energy_J_mol"]
        ea2 = results["reaction_2"]["activation_energy_J_mol"]
        assert ea1 < ea2, (
            f"Reaction 1 must have lower E_a. Got E_a1={ea1:.0f}, E_a2={ea2:.0f}"
        )


class TestPreExponentialFactors:
    """Verify recovered pre-exponential factors within 1.5 orders of magnitude."""

    def test_a1_log_error(self, results):
        a1 = results["reaction_1"]["pre_exponential_factor_per_s"]
        assert a1 > 0, "Pre-exponential factor must be positive"
        log_err = abs(math.log10(a1) - math.log10(GT_A1))
        assert log_err < 1.5, (
            f"log10(A1) error {log_err:.2f} exceeds 1.5. "
            f"Got {a1:.2e}, expected {GT_A1:.2e}"
        )

    def test_a2_log_error(self, results):
        a2 = results["reaction_2"]["pre_exponential_factor_per_s"]
        assert a2 > 0, "Pre-exponential factor must be positive"
        log_err = abs(math.log10(a2) - math.log10(GT_A2))
        assert log_err < 1.5, (
            f"log10(A2) error {log_err:.2f} exceeds 1.5. "
            f"Got {a2:.2e}, expected {GT_A2:.2e}"
        )


class TestWeightFractions:
    """Verify recovered weight fractions."""

    def test_w1_absolute_error(self, results):
        w1 = results["reaction_1"]["weight_fraction"]
        err = abs(w1 - GT_W1)
        assert err < 0.06, (
            f"w1 absolute error {err:.4f} exceeds 0.06. Got {w1:.4f}, expected {GT_W1}"
        )

    def test_w2_absolute_error(self, results):
        w2 = results["reaction_2"]["weight_fraction"]
        err = abs(w2 - GT_W2)
        assert err < 0.06, (
            f"w2 absolute error {err:.4f} exceeds 0.06. Got {w2:.4f}, expected {GT_W2}"
        )

    def test_weights_sum_to_one(self, results):
        w1 = results["reaction_1"]["weight_fraction"]
        w2 = results["reaction_2"]["weight_fraction"]
        assert abs(w1 + w2 - 1.0) < 0.01, (
            f"Weight fractions must sum to 1.0, got {w1 + w2:.4f}"
        )

    def test_weights_positive(self, results):
        w1 = results["reaction_1"]["weight_fraction"]
        w2 = results["reaction_2"]["weight_fraction"]
        assert w1 > 0 and w2 > 0, "Weight fractions must be positive"


class TestPredictions:
    """Verify predictions at beta=7.5 K/min."""

    @pytest.mark.parametrize("temp", ["480.0", "520.0", "540.0", "560.0", "580.0", "620.0", "700.0"])
    def test_prediction_accuracy(self, results, temp):
        pred = results["predictions_beta_7_5"][temp]
        gt = GT_PREDICTIONS[temp]
        err = abs(pred - gt)
        assert err < 0.04, (
            f"Prediction at T={temp} K: error {err:.4f} exceeds 0.04. "
            f"Got {pred:.6f}, expected {gt:.6f}"
        )

    def test_predictions_monotonically_increasing(self, results):
        preds = results["predictions_beta_7_5"]
        temps = sorted(preds.keys(), key=float)
        vals = [preds[t] for t in temps]
        for i in range(1, len(vals)):
            assert vals[i] >= vals[i - 1] - 0.001, (
                f"Predictions should be monotonically increasing. "
                f"T={temps[i-1]}: {vals[i-1]:.4f} > T={temps[i]}: {vals[i]:.4f}"
            )

    def test_predictions_bounded(self, results):
        preds = results["predictions_beta_7_5"]
        for temp, val in preds.items():
            assert 0.0 <= val <= 1.0, (
                f"Prediction at T={temp} must be in [0, 1], got {val:.6f}"
            )
