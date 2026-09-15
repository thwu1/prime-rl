"""Tests for thermal model correction task.

Verifies that the corrected model accurately predicts pot temperature
on both training and extrapolation ranges, satisfies energy conservation,
and recovers an interpretable coupling equation.
"""

import pytest
import numpy as np
from scipy.integrate import solve_ivp
import csv
import os

# ===== Ground truth system (hidden from agent) =====
C1_TRUE = 1.0
C2_TRUE = 15.0
G_COND_TRUE = 1.0
G_AIR = 0.1
T_ENV = 293.15
T0 = 273.15


def input_f(t):
    return (1 + np.sin(0.005 * t**2)) / 2


def true_system(t, y):
    T1, T2 = y
    dT1 = (input_f(t) - G_COND_TRUE * (T1 - T2)) / C1_TRUE
    dT2 = (G_COND_TRUE * (T1 - T2) - G_AIR * (T2 - T_ENV)) / C2_TRUE
    return [dT1, dT2]


def generate_ground_truth():
    """Generate dense ground truth solution over [0, 200]."""
    t_dense = np.linspace(0, 200, 2000)
    sol = solve_ivp(true_system, [0, 200], [T0, T0], t_eval=t_dense,
                    method='RK45', rtol=1e-12, atol=1e-12)
    return sol.t, sol.y[1]


def load_predictions(filepath):
    """Load predictions CSV with columns t and T_pot_pred."""
    t_vals, T_vals = [], []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            t_vals.append(float(row['t']))
            T_vals.append(float(row['T_pot_pred']))
    return np.array(t_vals), np.array(T_vals)


# ===== File existence tests =====

class TestResultFilesExist:
    """All required output files must be present."""

    def test_results_directory(self):
        assert os.path.isdir('/app/results'), \
            "Directory /app/results/ must exist"

    def test_predictions_train_exists(self):
        assert os.path.isfile('/app/results/predictions_train.csv'), \
            "predictions_train.csv must exist in /app/results/"

    def test_predictions_test_exists(self):
        assert os.path.isfile('/app/results/predictions_test.csv'), \
            "predictions_test.csv must exist in /app/results/"

    def test_training_loss_exists(self):
        assert os.path.isfile('/app/results/training_loss.txt'), \
            "training_loss.txt must exist in /app/results/"

    def test_conservation_check_exists(self):
        assert os.path.isfile('/app/results/conservation_check.txt'), \
            "conservation_check.txt must exist in /app/results/"

    def test_recovered_equation_exists(self):
        assert os.path.isfile('/app/results/recovered_equation.txt'), \
            "recovered_equation.txt must exist in /app/results/"


# ===== Prediction accuracy tests =====

class TestPredictionAccuracy:
    """Predictions must match ground truth within tolerance."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.t_true, self.T_true = generate_ground_truth()

    def test_training_predictions_format(self):
        """Training predictions must cover [0, 100] with enough points."""
        t_pred, T_pred = load_predictions('/app/results/predictions_train.csv')
        assert len(t_pred) >= 50, \
            f"Too few training predictions ({len(t_pred)}), need >= 50"
        assert t_pred[0] <= 1.0, \
            f"Training predictions must start near t=0, got t={t_pred[0]}"
        assert t_pred[-1] >= 99.0, \
            f"Training predictions must extend to t~100, got t={t_pred[-1]}"
        assert np.all(np.isfinite(T_pred)), \
            "Training predictions contain NaN or Inf"

    def test_training_mse(self):
        """Training MSE must be below 0.01 K^2."""
        t_pred, T_pred = load_predictions('/app/results/predictions_train.csv')
        T_ref = np.interp(t_pred, self.t_true, self.T_true)
        mse = np.mean((T_pred - T_ref)**2)
        assert mse < 0.01, \
            f"Training MSE = {mse:.6f} exceeds threshold 0.01 K^2"

    def test_extrapolation_predictions_format(self):
        """Test predictions must cover [100, 200] with enough points."""
        t_pred, T_pred = load_predictions('/app/results/predictions_test.csv')
        assert len(t_pred) >= 50, \
            f"Too few test predictions ({len(t_pred)}), need >= 50"
        assert t_pred[0] <= 101.0, \
            f"Test predictions must start near t=100, got t={t_pred[0]}"
        assert t_pred[-1] >= 199.0, \
            f"Test predictions must extend to t~200, got t={t_pred[-1]}"
        assert np.all(np.isfinite(T_pred)), \
            "Test predictions contain NaN or Inf"

    def test_extrapolation_mse(self):
        """Extrapolation MSE must be below 0.5 K^2."""
        t_pred, T_pred = load_predictions('/app/results/predictions_test.csv')
        T_ref = np.interp(t_pred, self.t_true, self.T_true)
        mse = np.mean((T_pred - T_ref)**2)
        assert mse < 0.5, \
            f"Extrapolation MSE = {mse:.6f} exceeds threshold 0.5 K^2"


# ===== Training metrics tests =====

class TestTrainingMetrics:
    """Training loss, conservation, and equation recovery checks."""

    def test_training_loss_value(self):
        """Reported training loss must be < 0.01."""
        content = open('/app/results/training_loss.txt').read().strip()
        loss = float(content)
        assert loss < 0.01, \
            f"Training loss {loss:.6e} exceeds threshold 0.01"

    def test_conservation_error(self):
        """Energy conservation error must be < 1.0."""
        content = open('/app/results/conservation_check.txt').read().strip()
        err = float(content)
        assert err < 1.0, \
            f"Conservation error {err:.4f} exceeds threshold 1.0"

    def test_recovered_equation_content(self):
        """Recovered equation must contain meaningful numerical content."""
        content = open('/app/results/recovered_equation.txt').read().strip()
        assert len(content) > 10, \
            "Recovered equation is too short to be meaningful"
        has_number = any(c.isdigit() for c in content)
        assert has_number, \
            "Recovered equation must contain numerical coefficients"

    def test_recovered_equation_identifies_coupling(self):
        """Recovered equation should reference temperature difference."""
        content = open('/app/results/recovered_equation.txt').read().lower()
        coupling_indicators = [
            '-', 'diff', 'conduct', 'coupl', 'delta', 'subtract',
            'x1', 'x2', 'x_norm', 't2', 'fourier', 'linear'
        ]
        found = any(ind in content for ind in coupling_indicators)
        assert found, \
            "Recovered equation should reference a temperature difference or coupling"
