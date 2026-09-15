"""
Tests for Newton-Schulz coefficient optimization results.

Verifies that /app/results.json contains correct, convergent coefficients
for each optimization target specified in /opt/ns_task/targets.json.
"""

import json
import sys
sys.path.insert(0, '/opt/ns_task')
import numpy as np
import pytest

from ns_iteration import compute_worst_case_error


@pytest.fixture(scope="module")
def results():
    with open('/app/results.json', 'r') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def targets():
    with open('/opt/ns_task/targets.json', 'r') as f:
        return json.load(f)


def _iterate_uniform(x, a, b, c, n):
    """Apply phi(x) = ax + bx^3 + cx^5 for n iterations."""
    for _ in range(n):
        x = a * x + b * x**3 + c * x**5
    return x


def _iterate_perstep(x, coeffs_list):
    """Apply per-step quintic polynomials sequentially."""
    for a, b, c in coeffs_list:
        x = a * x + b * x**3 + c * x**5
    return x


# =========================================================================
# uniform_steady tests (epsilon = 0.35, 10 iterations)
# =========================================================================

class TestUniformSteady:

    def test_entry_exists(self, results):
        assert "uniform_steady" in results
        entry = results["uniform_steady"]
        for key in ("coefficients", "worst_case_error", "slope_at_zero"):
            assert key in entry, f"Missing key '{key}' in uniform_steady"

    def test_coefficients_format(self, results):
        coeffs = results["uniform_steady"]["coefficients"]
        assert isinstance(coeffs, list) and len(coeffs) == 3
        assert all(isinstance(c, (int, float)) for c in coeffs)

    def test_convergence(self, results, targets):
        entry = results["uniform_steady"]
        target = targets["uniform_steady"]
        a, b, c = entry["coefficients"]
        x = np.linspace(target["x_min"], target["x_max"], 100000)
        x = _iterate_uniform(x, a, b, c, target["eval_iterations"])
        assert np.all(np.isfinite(x)), "Iteration diverged to inf/NaN"
        max_err = float(np.max(np.abs(x - 1.0)))
        assert max_err <= target["epsilon"] + 0.005, (
            f"Worst-case error {max_err:.6f} exceeds epsilon={target['epsilon']}"
        )

    def test_slope_quality(self, results):
        slope = results["uniform_steady"]["slope_at_zero"]
        assert slope >= 2.50, (
            f"Slope {slope:.4f} too low; need >= 2.50"
        )

    def test_slope_matches_coefficient(self, results):
        entry = results["uniform_steady"]
        a = entry["coefficients"][0]
        assert abs(entry["slope_at_zero"] - a) < 0.01

    def test_reported_error_consistency(self, results, targets):
        entry = results["uniform_steady"]
        target = targets["uniform_steady"]
        a, b, c = entry["coefficients"]
        computed = compute_worst_case_error(
            (a, b, c),
            num_steps=target["eval_iterations"],
            x_max=target["x_max"],
            x_min=target["x_min"],
            num_test_points=100000,
        )
        assert abs(computed - entry["worst_case_error"]) < 0.02, (
            f"Reported error {entry['worst_case_error']:.6f} vs computed {computed:.6f}"
        )

    def test_polynomial_sign_structure(self, results):
        a, b, c = results["uniform_steady"]["coefficients"]
        assert a > 0, "a must be positive (drives growth near zero)"
        assert b < 0, "b should be negative (damping term)"
        assert c > 0, "c should be positive (stabilising quintic)"


# =========================================================================
# perstep_finite tests (epsilon = 0.35, 5 steps)
# =========================================================================

class TestPerstepFinite:

    def test_entry_exists(self, results):
        assert "perstep_finite" in results
        entry = results["perstep_finite"]
        for key in ("coefficients", "worst_case_error", "slope_at_zero"):
            assert key in entry

    def test_coefficients_format(self, results):
        coeffs = results["perstep_finite"]["coefficients"]
        assert isinstance(coeffs, list) and len(coeffs) == 5
        for i, step_coeffs in enumerate(coeffs):
            assert isinstance(step_coeffs, list) and len(step_coeffs) == 3, (
                f"Step {i} coefficients must be [a, b, c]"
            )
            assert all(isinstance(v, (int, float)) for v in step_coeffs)

    def test_convergence(self, results, targets):
        entry = results["perstep_finite"]
        target = targets["perstep_finite"]
        coeffs = [tuple(c) for c in entry["coefficients"]]
        x = np.linspace(target["x_min"], target["x_max"], 100000)
        x = _iterate_perstep(x, coeffs)
        assert np.all(np.isfinite(x)), "Iteration diverged to inf/NaN"
        max_err = float(np.max(np.abs(x - 1.0)))
        assert max_err <= target["epsilon"] + 0.005, (
            f"Worst-case error {max_err:.6f} exceeds epsilon={target['epsilon']}"
        )

    def test_slope_quality(self, results):
        slope = results["perstep_finite"]["slope_at_zero"]
        assert slope >= 2.50, (
            f"First-step slope {slope:.4f} too low; need >= 2.50"
        )

    def test_slope_matches_first_coefficient(self, results):
        entry = results["perstep_finite"]
        a1 = entry["coefficients"][0][0]
        assert abs(entry["slope_at_zero"] - a1) < 0.01

    def test_reported_error_consistency(self, results, targets):
        entry = results["perstep_finite"]
        target = targets["perstep_finite"]
        coeffs = [tuple(c) for c in entry["coefficients"]]
        computed = compute_worst_case_error(
            coeffs,
            x_max=target["x_max"],
            x_min=target["x_min"],
            num_test_points=100000,
        )
        assert abs(computed - entry["worst_case_error"]) < 0.02


# =========================================================================
# uniform_tight tests (epsilon = 0.05, 10 iterations)
# =========================================================================

class TestUniformTight:

    def test_entry_exists(self, results):
        assert "uniform_tight" in results

    def test_convergence(self, results, targets):
        entry = results["uniform_tight"]
        target = targets["uniform_tight"]
        a, b, c = entry["coefficients"]
        x = np.linspace(target["x_min"], target["x_max"], 100000)
        x = _iterate_uniform(x, a, b, c, target["eval_iterations"])
        assert np.all(np.isfinite(x)), "Iteration diverged"
        max_err = float(np.max(np.abs(x - 1.0)))
        assert max_err <= target["epsilon"] + 0.005, (
            f"Worst-case error {max_err:.6f} exceeds epsilon={target['epsilon']}"
        )

    def test_slope_quality(self, results):
        slope = results["uniform_tight"]["slope_at_zero"]
        assert slope >= 2.00, f"Slope {slope:.4f} too low; need >= 2.00"

    def test_polynomial_sign_structure(self, results):
        a, b, c = results["uniform_tight"]["coefficients"]
        assert a > 0
        assert b < 0
        assert c > 0

    def test_reported_error_consistency(self, results, targets):
        entry = results["uniform_tight"]
        target = targets["uniform_tight"]
        a, b, c = entry["coefficients"]
        computed = compute_worst_case_error(
            (a, b, c),
            num_steps=target["eval_iterations"],
            x_max=target["x_max"],
            x_min=target["x_min"],
            num_test_points=100000,
        )
        assert abs(computed - entry["worst_case_error"]) < 0.02


# =========================================================================
# Cross-target validation
# =========================================================================

class TestCrossTarget:

    def test_all_targets_present(self, results):
        required = {"uniform_steady", "perstep_finite", "uniform_tight"}
        assert required <= set(results.keys())

    def test_tight_has_lower_error(self, results):
        steady_err = results["uniform_steady"]["worst_case_error"]
        tight_err = results["uniform_tight"]["worst_case_error"]
        assert tight_err < steady_err, (
            f"Tight error ({tight_err:.6f}) should be less than "
            f"steady error ({steady_err:.6f})"
        )

    def test_both_uniform_slopes_above_baseline(self, results):
        """Both uniform solutions must beat the baseline a=2.0."""
        assert results["uniform_steady"]["slope_at_zero"] > 2.0
        assert results["uniform_tight"]["slope_at_zero"] > 2.0
