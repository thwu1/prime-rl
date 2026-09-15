"""
Tests for Newton-Schulz Quintic Iteration Coefficient Optimization.

"""

import json
import os

import numpy as np
import pytest


# ============================================================
# Load problem spec parameters
# ============================================================

MUON_COEFFS = (3.4445, -4.7750, 2.0315)
MUON_N_ITERS = 5
MATRIX_SEED = 42
MATRIX_SHAPES = [(8, 6), (16, 16), (32, 16), (64, 64), (128, 64)]

P2_GRID = np.linspace(0.01, 1.0, 500)
P2_N_ITERS = 15
P2_TOLERANCE = 0.01
P2_DIVERGENCE_BOUND = 10.0

P3_GRID = np.linspace(0.01, 0.98, 500)
P3_N_COMPOSITIONS = 5
P3_LOWER_BOUND = 0.65
P3_UPPER_BOUND = 1.35
P3_DIVERGENCE_BOUND = 10.0

RESULTS_FILE = "/app/results.json"


# ============================================================
# Helper functions
# ============================================================

def apply_ns_polynomial(x, a, b, c):
    """Apply quintic polynomial phi(x) = a*x + b*x^3 + c*x^5."""
    return a * x + b * x**3 + c * x**5


def iterate_ns_polynomial(x, a, b, c, n_iters):
    """Apply quintic polynomial n_iters times, returning all intermediate values."""
    trajectory = [x.copy()]
    for _ in range(n_iters):
        x = apply_ns_polynomial(x, a, b, c)
        trajectory.append(x.copy())
    return trajectory


def ns_iteration_matrix(G, a, b, c, n_iters):
    """Apply Newton-Schulz iteration to a matrix.

    X <- a*X + (b*XX^T + c*(XX^T)^2) X
    equivalent to applying phi to each singular value.
    """
    X = G.copy()
    X = X / (np.linalg.norm(X, "fro") + 1e-7)
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True
    for _ in range(n_iters):
        A = X @ X.T
        B = b * A + c * A @ A
        X = a * X + B @ X
    if transposed:
        X = X.T
    return X


def true_polar_factor(G):
    """Compute the true polar factor U @ V.T via SVD."""
    U, S, Vt = np.linalg.svd(G, full_matrices=False)
    return U @ Vt


# ============================================================
# Load results
# ============================================================

@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_FILE), f"Results file not found: {RESULTS_FILE}"
    with open(RESULTS_FILE, "r") as f:
        data = json.load(f)
    assert "part1" in data, "Missing 'part1' in results"
    assert "part2" in data, "Missing 'part2' in results"
    assert "part3" in data, "Missing 'part3' in results"
    return data


# ============================================================
# Part 1: Implementation & Verification
# ============================================================

class TestPart1:
    """Test NS iteration implementation and matrix orthogonalization."""

    def test_part1_has_errors(self, results):
        """Part 1 should report errors for each matrix shape."""
        p1 = results["part1"]
        assert "errors" in p1, "Missing 'errors' key in part1"
        errors = p1["errors"]
        assert len(errors) == len(MATRIX_SHAPES), (
            f"Expected {len(MATRIX_SHAPES)} errors, got {len(errors)}"
        )

    def test_part1_errors_are_finite(self, results):
        """All errors should be finite positive numbers."""
        errors = results["part1"]["errors"]
        for i, err in enumerate(errors):
            assert isinstance(err, (int, float)), f"Error {i} is not a number"
            assert np.isfinite(err), f"Error {i} is not finite: {err}"
            assert err >= 0, f"Error {i} is negative: {err}"

    def test_part1_errors_below_threshold(self, results):
        """All errors should be below a generous threshold.

        Note: 5 NS iterations is only an approximate orthogonalization.
        Larger matrices have more singular values, each contributing
        some non-zero error to the Frobenius norm. Errors scale roughly
        with sqrt(min(m,n)).
        """
        errors = results["part1"]["errors"]
        for i, err in enumerate(errors):
            m, n = MATRIX_SHAPES[i]
            # Allow error proportional to sqrt of number of singular values
            threshold = 0.3 * np.sqrt(min(m, n))
            assert err < threshold, (
                f"Error for matrix shape {MATRIX_SHAPES[i]} is too large: "
                f"{err:.6f} >= {threshold:.4f}"
            )

    def test_part1_smallest_matrix_accurate(self, results):
        """The smallest matrix should have a reasonably small error."""
        errors = results["part1"]["errors"]
        assert errors[0] < 0.5, (
            f"Error for smallest matrix {MATRIX_SHAPES[0]} is too large: {errors[0]:.6f}"
        )

    def test_part1_independently_verified(self, results):
        """Independently compute errors and verify they match reported values."""
        reported_errors = results["part1"]["errors"]
        rng = np.random.default_rng(MATRIX_SEED)
        a, b, c = MUON_COEFFS

        for i, shape in enumerate(MATRIX_SHAPES):
            G = rng.standard_normal(shape)
            X = ns_iteration_matrix(G, a, b, c, MUON_N_ITERS)
            P = true_polar_factor(G)
            true_error = np.linalg.norm(X - P, "fro")
            # Allow some tolerance for numerical differences
            assert abs(true_error - reported_errors[i]) < 0.05, (
                f"Shape {shape}: reported error {reported_errors[i]:.6f} "
                f"differs from independently computed {true_error:.6f}"
            )


# ============================================================
# Part 2: Fixed-Coefficient Optimization
# ============================================================

class TestPart2:
    """Test fixed-coefficient optimization with a+b+c=1 constraint."""

    def test_part2_has_required_keys(self, results):
        p2 = results["part2"]
        assert "coefficients" in p2
        assert "max_error" in p2
        assert "a_value" in p2

    def test_part2_coefficients_format(self, results):
        coeffs = results["part2"]["coefficients"]
        assert len(coeffs) == 3, f"Expected 3 coefficients, got {len(coeffs)}"
        for i, v in enumerate(coeffs):
            assert isinstance(v, (int, float)), f"Coefficient {i} is not a number"
            assert np.isfinite(v), f"Coefficient {i} is not finite"

    def test_part2_fixed_point_constraint(self, results):
        """a + b + c should equal 1 (fixed point at x=1)."""
        a, b, c = results["part2"]["coefficients"]
        s = a + b + c
        assert abs(s - 1.0) < 1e-4, (
            f"a + b + c = {s:.6f}, expected 1.0 (within 1e-4)"
        )

    def test_part2_convergence_constraint(self, results):
        """Verify the convergence constraint on the grid."""
        a, b, c = results["part2"]["coefficients"]
        x = P2_GRID.copy()

        for k in range(P2_N_ITERS):
            x = apply_ns_polynomial(x, a, b, c)
            # Check divergence at every step
            assert np.all(np.abs(x) < P2_DIVERGENCE_BOUND), (
                f"Divergence detected at iteration {k+1}: max |x| = {np.max(np.abs(x)):.4f}"
            )

        max_error = np.max(np.abs(x - 1.0))
        assert max_error < P2_TOLERANCE, (
            f"Max |phi^{P2_N_ITERS}(x) - 1| = {max_error:.6f}, "
            f"exceeds tolerance {P2_TOLERANCE}"
        )

    def test_part2_a_value_consistency(self, results):
        """Reported a_value should match the first coefficient."""
        a = results["part2"]["coefficients"][0]
        a_reported = results["part2"]["a_value"]
        assert abs(a - a_reported) < 1e-6, (
            f"a_value {a_reported} doesn't match coefficient a={a}"
        )

    def test_part2_a_above_minimum(self, results):
        """The optimized 'a' should be at least 2.5 (well above trivial baseline)."""
        a = results["part2"]["coefficients"][0]
        assert a >= 2.5, (
            f"Optimized a = {a:.4f} is below minimum threshold 2.5. "
            f"The baseline (2, -1.5, 0.5) achieves a=2.0; optimization should do better."
        )

    def test_part2_max_error_consistent(self, results):
        """Reported max_error should be close to independently computed."""
        a, b, c = results["part2"]["coefficients"]
        x = P2_GRID.copy()
        for _ in range(P2_N_ITERS):
            x = apply_ns_polynomial(x, a, b, c)
        true_max_error = np.max(np.abs(x - 1.0))
        reported = results["part2"]["max_error"]
        assert abs(true_max_error - reported) < 0.005, (
            f"Reported max_error {reported:.6f} differs from computed {true_max_error:.6f}"
        )


# ============================================================
# Part 3: Per-Iteration Coefficient Optimization
# ============================================================

class TestPart3:
    """Test per-iteration coefficient optimization."""

    def test_part3_has_required_keys(self, results):
        p3 = results["part3"]
        assert "coefficients" in p3
        assert "product_of_slopes" in p3
        assert "max_error" in p3

    def test_part3_coefficients_format(self, results):
        coeffs = results["part3"]["coefficients"]
        assert len(coeffs) == P3_N_COMPOSITIONS, (
            f"Expected {P3_N_COMPOSITIONS} coefficient triples, got {len(coeffs)}"
        )
        for i, triple in enumerate(coeffs):
            assert len(triple) == 3, f"Triple {i} has {len(triple)} elements, expected 3"
            for j, v in enumerate(triple):
                assert isinstance(v, (int, float)), f"coefficients[{i}][{j}] is not a number"
                assert np.isfinite(v), f"coefficients[{i}][{j}] is not finite"

    def test_part3_composition_constraint(self, results):
        """Verify the composed map sends the grid into [0.65, 1.35]."""
        coeffs = results["part3"]["coefficients"]
        x = P3_GRID.copy()

        for i, (a, b, c) in enumerate(coeffs):
            x = apply_ns_polynomial(x, a, b, c)
            # Check divergence
            assert np.all(np.abs(x) < P3_DIVERGENCE_BOUND), (
                f"Divergence at step {i+1}: max |x| = {np.max(np.abs(x)):.4f}"
            )

        assert np.all(x >= P3_LOWER_BOUND), (
            f"Composed map min = {np.min(x):.6f}, below {P3_LOWER_BOUND}"
        )
        assert np.all(x <= P3_UPPER_BOUND), (
            f"Composed map max = {np.max(x):.6f}, above {P3_UPPER_BOUND}"
        )

    def test_part3_product_consistency(self, results):
        """Reported product should match product of first elements."""
        coeffs = results["part3"]["coefficients"]
        true_product = 1.0
        for triple in coeffs:
            true_product *= triple[0]
        reported = results["part3"]["product_of_slopes"]
        assert abs(true_product - reported) / max(abs(true_product), 1e-10) < 0.01, (
            f"Reported product {reported:.4f} differs from computed {true_product:.4f}"
        )

    def test_part3_product_above_threshold(self, results):
        """Per-iteration should outperform uniform: product > a_fixed^5."""
        a_fixed = results["part2"]["coefficients"][0]
        product = results["part3"]["product_of_slopes"]
        uniform_product = a_fixed ** P3_N_COMPOSITIONS
        assert product > uniform_product, (
            f"Per-iteration product {product:.2f} should exceed "
            f"uniform a^5 = {a_fixed:.4f}^5 = {uniform_product:.2f}"
        )

    def test_part3_all_slopes_positive(self, results):
        """All a_i values should be positive (meaningful convergence)."""
        coeffs = results["part3"]["coefficients"]
        for i, (a, b, c) in enumerate(coeffs):
            assert a > 0, f"Slope a_{i} = {a} is not positive"

    def test_part3_max_error_consistent(self, results):
        """Reported max_error should be close to independently computed."""
        coeffs = results["part3"]["coefficients"]
        x = P3_GRID.copy()
        for a, b, c in coeffs:
            x = apply_ns_polynomial(x, a, b, c)
        true_max_dev = np.max(np.abs(x - 1.0))
        reported = results["part3"]["max_error"]
        assert abs(true_max_dev - reported) < 0.01, (
            f"Reported max_error {reported:.6f} differs from computed {true_max_dev:.6f}"
        )
