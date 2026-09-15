"""
Tests for Newton-Schulz iteration coefficient optimization.

"""

import json
import math
import os

import numpy as np
import pytest


# ---- Independent reimplementation of core functions ----

EVAL_GRID = np.linspace(0.01, 1.0, 50000)


def _iterate_quintic(x, a, b, c, N):
    x = x.copy()
    for _ in range(N):
        x = a * x + b * x**3 + c * x**5
    return x


def _iterate_septic(x, a, b, c, d, N):
    x = x.copy()
    for _ in range(N):
        x = a * x + b * x**3 + c * x**5 + d * x**7
    return x


def _max_deviation(values):
    if np.any(np.isnan(values)) or np.any(np.isinf(values)):
        return float("inf")
    return float(np.max(np.abs(values - 1.0)))


def _generate_test_matrix(seed=42):
    rng = np.random.RandomState(seed)
    U, _ = np.linalg.qr(rng.randn(64, 64))
    V, _ = np.linalg.qr(rng.randn(48, 48))
    sigma = np.exp(np.linspace(-3, 0, 48))
    S = np.zeros((64, 48))
    S[:48, :48] = np.diag(sigma)
    return U @ S @ V.T


def _ns_orthogonalize_matrix(G, a, b, c, n_iters=5):
    X = G.astype(np.float64).copy()
    transposed = False
    if X.shape[0] > X.shape[1]:
        X = X.T
        transposed = True
    X = X / (np.linalg.norm(X, "fro") + 1e-7)
    for _ in range(n_iters):
        A = X @ X.T
        B = b * A + c * A @ A
        X = a * X + B @ X
    if transposed:
        X = X.T
    return X


def _find_positive_fixed_points(a, b, c):
    """Find all positive real x where phi(x) = x analytically.

    phi(x) = a*x + b*x^3 + c*x^5 = x
    => x * ((a-1) + b*x^2 + c*x^4) = 0
    => x=0 or c*u^2 + b*u + (a-1) = 0 where u = x^2
    """
    fps = [0.0]
    if abs(c) < 1e-15:
        # Degenerate: b*u + (a-1) = 0
        if abs(b) > 1e-15:
            u = -(a - 1) / b
            if u > 0:
                fps.append(math.sqrt(u))
    else:
        disc = b * b - 4 * c * (a - 1)
        if disc >= 0:
            sqrt_disc = math.sqrt(disc)
            u1 = (-b + sqrt_disc) / (2 * c)
            u2 = (-b - sqrt_disc) / (2 * c)
            for u in [u1, u2]:
                if u > 1e-12:
                    fps.append(math.sqrt(u))
    return sorted(fps)


def _phi_prime(x, a, b, c):
    """Derivative of phi at x."""
    return a + 3 * b * x**2 + 5 * c * x**4


# ---- Load results ----


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.exists(path), f"results.json not found at {path}"
    with open(path, "r") as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json must contain a JSON object"
    return data


# ---- Format tests ----


class TestFormat:
    def test_quintic_keys(self, results):
        assert "quintic" in results
        q = results["quintic"]
        for key in ["a", "b", "c", "convergence_profile"]:
            assert key in q, f"Missing key '{key}' in quintic"

    def test_septic_keys(self, results):
        assert "septic" in results
        s = results["septic"]
        for key in ["a", "b", "c", "d"]:
            assert key in s, f"Missing key '{key}' in septic"

    def test_fixed_points_key(self, results):
        assert "fixed_points" in results
        fps = results["fixed_points"]
        assert isinstance(fps, list), "fixed_points must be a list"
        assert len(fps) >= 1, "Must have at least one fixed point (x=0)"
        for fp in fps:
            assert "x" in fp and "phi_prime" in fp

    def test_matrix_analysis_keys(self, results):
        assert "matrix_analysis" in results
        ma = results["matrix_analysis"]
        for key in ["frobenius_error", "max_sv_deviation"]:
            assert key in ma, f"Missing key '{key}' in matrix_analysis"

    def test_convergence_profile_length(self, results):
        cp = results["quintic"]["convergence_profile"]
        assert isinstance(cp, list)
        assert len(cp) == 20, f"convergence_profile must have 20 entries, got {len(cp)}"


# ---- Quintic coefficient tests ----


class TestQuinticCoefficients:
    def test_convergence_constraint(self, results):
        """Quintic coefficients must satisfy max deviation <= 0.30 at N=5."""
        q = results["quintic"]
        a, b, c = q["a"], q["b"], q["c"]
        vals = _iterate_quintic(EVAL_GRID.copy(), a, b, c, 5)
        dev = _max_deviation(vals)
        assert dev <= 0.305, f"Max deviation {dev:.6f} exceeds 0.305 at N=5"

    def test_near_optimality(self, results):
        """The coefficient 'a' must be near-optimal (>= 3.0)."""
        a = results["quintic"]["a"]
        assert a >= 3.0, f"a={a:.4f} is below threshold 3.0"

    def test_convergence_profile_consistency(self, results):
        """The reported convergence profile must match independent computation."""
        q = results["quintic"]
        a, b, c = q["a"], q["b"], q["c"]
        cp = q["convergence_profile"]
        for k in range(20):
            N = k + 1
            vals = _iterate_quintic(EVAL_GRID.copy(), a, b, c, N)
            computed = _max_deviation(vals)
            reported = cp[k]
            # Allow small numerical tolerance
            assert abs(computed - reported) < 0.02, (
                f"N={N}: computed dev={computed:.6f} vs reported={reported:.6f}"
            )

    def test_convergence_profile_n5_matches_constraint(self, results):
        """convergence_profile[4] (N=5) should match the convergence constraint."""
        q = results["quintic"]
        assert q["convergence_profile"][4] <= 0.305


# ---- Septic coefficient tests ----


class TestSepticCoefficients:
    def test_convergence_constraint(self, results):
        """Septic coefficients must satisfy max deviation <= 0.30 at N=5."""
        s = results["septic"]
        a, b, c, d = s["a"], s["b"], s["c"], s["d"]
        vals = _iterate_septic(EVAL_GRID.copy(), a, b, c, d, 5)
        dev = _max_deviation(vals)
        assert dev <= 0.305, f"Max deviation {dev:.6f} exceeds 0.305 at N=5"

    def test_near_optimality(self, results):
        """Septic 'a' must be >= 3.0."""
        a = results["septic"]["a"]
        assert a >= 3.0, f"a={a:.4f} is below threshold 3.0"

    def test_septic_at_least_as_good_as_quintic(self, results):
        """Septic has more DOF, so optimal a should be >= quintic a."""
        qa = results["quintic"]["a"]
        sa = results["septic"]["a"]
        assert sa >= qa - 0.15, (
            f"Septic a={sa:.4f} should be >= quintic a={qa:.4f} - 0.15"
        )


# ---- Fixed-point analysis tests ----


class TestFixedPoints:
    def test_includes_zero(self, results):
        """x=0 must be included as a fixed point."""
        fps = results["fixed_points"]
        zero_fps = [fp for fp in fps if abs(fp["x"]) < 1e-8]
        assert len(zero_fps) >= 1, "x=0 must be listed as a fixed point"

    def test_fixed_point_accuracy(self, results):
        """Each reported fixed point must satisfy |phi(x*) - x*| < 1e-4."""
        q = results["quintic"]
        a, b, c = q["a"], q["b"], q["c"]
        for fp in results["fixed_points"]:
            x = fp["x"]
            phi_x = a * x + b * x**3 + c * x**5
            assert abs(phi_x - x) < 1e-4, (
                f"x*={x:.6f}: phi(x*)={phi_x:.6f}, |phi(x*)-x*|={abs(phi_x-x):.2e}"
            )

    def test_phi_prime_accuracy(self, results):
        """Reported phi'(x*) must match independent computation."""
        q = results["quintic"]
        a, b, c = q["a"], q["b"], q["c"]
        for fp in results["fixed_points"]:
            x = fp["x"]
            expected = _phi_prime(x, a, b, c)
            reported = fp["phi_prime"]
            assert abs(expected - reported) < 0.01, (
                f"x*={x:.4f}: phi'(x*)={expected:.4f} vs reported={reported:.4f}"
            )

    def test_completeness(self, results):
        """All positive fixed points must be found."""
        q = results["quintic"]
        a, b, c = q["a"], q["b"], q["c"]
        expected_fps = _find_positive_fixed_points(a, b, c)
        reported_xs = sorted([fp["x"] for fp in results["fixed_points"]])

        for xstar in expected_fps:
            found = any(abs(rx - xstar) < 0.01 for rx in reported_xs)
            assert found, (
                f"Fixed point x*={xstar:.4f} not found in reported: {reported_xs}"
            )

    def test_no_extra_fixed_points(self, results):
        """Reported fixed points should be genuine (no spurious entries)."""
        q = results["quintic"]
        a, b, c = q["a"], q["b"], q["c"]
        expected_fps = _find_positive_fixed_points(a, b, c)
        for fp in results["fixed_points"]:
            x = fp["x"]
            if x < 0:
                pytest.fail(f"Negative fixed point reported: x={x}")
            found = any(abs(x - xstar) < 0.05 for xstar in expected_fps)
            assert found, f"Spurious fixed point x={x:.4f} not near any expected value"


# ---- Matrix analysis tests ----


class TestMatrixAnalysis:
    def test_frobenius_error_consistency(self, results):
        """Frobenius error must match independent computation."""
        q = results["quintic"]
        a, b, c = q["a"], q["b"], q["c"]
        G = _generate_test_matrix(42)
        X = _ns_orthogonalize_matrix(G, a, b, c, 5)
        XtX = X.T @ X
        computed = float(np.linalg.norm(XtX - np.eye(48), "fro"))
        reported = results["matrix_analysis"]["frobenius_error"]
        rel_err = abs(computed - reported) / (computed + 1e-10)
        assert rel_err < 0.05, (
            f"Frobenius error: computed={computed:.6f} vs reported={reported:.6f}"
        )

    def test_max_sv_deviation_consistency(self, results):
        """Max singular value deviation must match independent computation."""
        q = results["quintic"]
        a, b, c = q["a"], q["b"], q["c"]
        G = _generate_test_matrix(42)
        X = _ns_orthogonalize_matrix(G, a, b, c, 5)
        sv = np.linalg.svd(X, compute_uv=False)
        computed = float(np.max(np.abs(sv - 1.0)))
        reported = results["matrix_analysis"]["max_sv_deviation"]
        rel_err = abs(computed - reported) / (computed + 1e-10)
        assert rel_err < 0.05, (
            f"Max SV dev: computed={computed:.6f} vs reported={reported:.6f}"
        )

    def test_reasonable_orthogonality(self, results):
        """Orthogonalization quality should be reasonable."""
        ma = results["matrix_analysis"]
        assert ma["frobenius_error"] < 5.0, (
            f"Frobenius error {ma['frobenius_error']:.4f} is unreasonably large"
        )
        assert ma["max_sv_deviation"] < 0.5, (
            f"Max SV deviation {ma['max_sv_deviation']:.4f} is unreasonably large"
        )
