"""
"""
import json
import sys
import os
import pytest
import numpy as np


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def config():
    with open("/app/config.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ns_module():
    """Import the newton_schulz module from /app/."""
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    if "newton_schulz" in sys.modules:
        del sys.modules["newton_schulz"]
    import newton_schulz
    return newton_schulz


class TestResultsStructure:
    def test_results_json_exists(self, results):
        assert isinstance(results, dict)

    def test_septic_coefficients_present(self, results):
        sc = results["septic_coefficients"]
        for key in ["a", "b", "c", "d"]:
            assert key in sc, f"Missing coefficient '{key}'"
            assert isinstance(sc[key], (int, float)), f"Coefficient '{key}' must be numeric"

    def test_required_fields_present(self, results):
        assert "constraint_satisfied" in results
        assert results["constraint_satisfied"] is True
        assert "max_deviation" in results
        assert isinstance(results["max_deviation"], (int, float))
        assert "slope_at_zero" in results
        assert isinstance(results["slope_at_zero"], (int, float))

    def test_benchmark_structure(self, results):
        bench = results["benchmark"]
        assert "quintic_5step_errors" in bench
        assert "septic_3step_errors" in bench
        assert "matrix_sizes" in bench
        assert len(bench["quintic_5step_errors"]) == len(bench["matrix_sizes"])
        assert len(bench["septic_3step_errors"]) == len(bench["matrix_sizes"])


class TestCoefficientConstraints:
    def test_convergence_constraint_satisfied(self, results, config):
        """Verify the iterated polynomial maps x_range into tolerance_band on a 100k grid."""
        sc = results["septic_coefficients"]
        a, b, c, d = sc["a"], sc["b"], sc["c"], sc["d"]

        constraints = config["septic_constraints"]
        x_min, x_max = constraints["x_range"]
        tol_lo, tol_hi = constraints["tolerance_band"]
        n_iter = constraints["num_steps"]

        x_grid = np.linspace(x_min, x_max, 100000)
        y = x_grid.copy()
        for _ in range(n_iter):
            y = a * y + b * y**3 + c * y**5 + d * y**7

        assert not np.any(np.isnan(y)), "NaN values encountered in iteration"
        assert not np.any(np.isinf(y)), "Inf values encountered in iteration"
        min_val = y.min()
        max_val = y.max()
        assert min_val >= tol_lo - 1e-6, (
            f"Constraint violated: min value {min_val:.6f} < {tol_lo}"
        )
        assert max_val <= tol_hi + 1e-6, (
            f"Constraint violated: max value {max_val:.6f} > {tol_hi}"
        )

    def test_slope_at_zero_sufficient(self, results):
        """The convergence rate coefficient a must be meaningfully large."""
        a = results["septic_coefficients"]["a"]
        assert a >= 4.0, (
            f"Slope at zero a={a:.4f} is too small; expected >= 4.0"
        )

    def test_slope_at_zero_consistent(self, results):
        """slope_at_zero field must match the coefficient a."""
        assert abs(results["slope_at_zero"] - results["septic_coefficients"]["a"]) < 1e-6

    def test_max_deviation_consistent(self, results, config):
        """Recompute max_deviation independently and check it matches reported value."""
        sc = results["septic_coefficients"]
        a, b, c, d = sc["a"], sc["b"], sc["c"], sc["d"]

        constraints = config["septic_constraints"]
        x_min, x_max = constraints["x_range"]
        n_iter = constraints["num_steps"]

        x_grid = np.linspace(x_min, x_max, 100000)
        y = x_grid.copy()
        for _ in range(n_iter):
            y = a * y + b * y**3 + c * y**5 + d * y**7

        actual_max_dev = float(np.max(np.abs(y - 1.0)))
        reported_max_dev = results["max_deviation"]

        tol = max(0.02, 0.05 * actual_max_dev)
        assert abs(actual_max_dev - reported_max_dev) < tol, (
            f"Reported max_deviation {reported_max_dev:.6f} does not match "
            f"independently computed value {actual_max_dev:.6f}"
        )


class TestImplementation:
    def test_newtonschulz7_square_matrix(self, ns_module):
        """Test orthogonalization of a square matrix."""
        np.random.seed(42)
        G = np.random.randn(64, 64)
        X = ns_module.newtonschulz7(G, steps=3)
        assert X.shape == (64, 64), f"Output shape {X.shape} != (64, 64)"
        err = ns_module.orthogonality_error(X)
        assert err < 0.5, f"Orthogonality error {err:.4f} too large for 64x64"

    def test_newtonschulz7_tall_matrix(self, ns_module):
        """Test orthogonalization of a tall (m > n) matrix."""
        np.random.seed(43)
        G = np.random.randn(128, 64)
        X = ns_module.newtonschulz7(G, steps=3)
        assert X.shape == (128, 64), f"Output shape {X.shape} != (128, 64)"
        err = ns_module.orthogonality_error(X)
        assert err < 0.5, f"Orthogonality error {err:.4f} too large for 128x64"

    def test_newtonschulz7_wide_matrix(self, ns_module):
        """Test orthogonalization of a wide (m < n) matrix."""
        np.random.seed(44)
        G = np.random.randn(64, 128)
        X = ns_module.newtonschulz7(G, steps=3)
        assert X.shape == (64, 128), f"Output shape {X.shape} != (64, 128)"
        err = ns_module.orthogonality_error(X)
        assert err < 0.5, f"Orthogonality error {err:.4f} too large for 64x128"

    def test_newtonschulz7_vs_quintic(self, ns_module):
        """Septic 3-step quality should be close to quintic 5-step."""
        np.random.seed(99)
        G = np.random.randn(128, 64)
        err5 = ns_module.orthogonality_error(ns_module.newtonschulz5(G, steps=5))
        err7 = ns_module.orthogonality_error(ns_module.newtonschulz7(G, steps=3))
        assert err7 < err5 + 0.15, (
            f"Septic 3-step error {err7:.4f} too far from "
            f"quintic 5-step error {err5:.4f}; difference "
            f"{err7 - err5:.4f} exceeds 0.15"
        )


class TestBenchmarkData:
    def test_benchmark_errors_valid(self, results):
        bench = results["benchmark"]
        for err in bench["quintic_5step_errors"]:
            assert isinstance(err, (int, float)), f"Non-numeric error: {err}"
            assert 0 <= err < 2.0, f"Quintic error {err} out of expected range [0, 2)"
        for err in bench["septic_3step_errors"]:
            assert isinstance(err, (int, float)), f"Non-numeric error: {err}"
            assert 0 <= err < 2.0, f"Septic error {err} out of expected range [0, 2)"

    def test_matrix_sizes_valid(self, results):
        bench = results["benchmark"]
        for size in bench["matrix_sizes"]:
            assert len(size) == 2, f"Matrix size must be [m, n], got {size}"
            assert all(isinstance(s, int) for s in size), f"Sizes must be integers: {size}"
            assert all(s > 0 for s in size), f"Sizes must be positive: {size}"
