"""
Tests for the EOF analysis pipeline.
Verifies that pipeline output matches reference and satisfies mathematical properties.

"""
import os
import shutil
import subprocess

import numpy as np
import pytest

RESULTS_DIR = "/app/results"
REFERENCE_DIR = "/app/reference"

FILES = [
    "total_variance",
    "unrotated_expvar_ratio",
    "unrotated_components",
    "unrotated_scores",
    "rotated_components",
    "rotated_scores",
    "rotated_expvar_ratio",
    "rotation_matrix",
    "phi_matrix",
    "varimax_criterion_before",
    "varimax_criterion_after",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Re-run the pipeline from scratch to generate fresh results."""
    if os.path.exists(RESULTS_DIR):
        shutil.rmtree(RESULTS_DIR)
    result = subprocess.run(
        ["python3", "/app/run_analysis.py"],
        capture_output=True,
        text=True,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Pipeline failed (exit {result.returncode}):\n{result.stderr}"
    )


@pytest.fixture(scope="session")
def results(run_pipeline):
    r = {}
    for name in FILES:
        path = os.path.join(RESULTS_DIR, f"{name}.npy")
        assert os.path.isfile(path), f"Missing result: {path}"
        r[name] = np.load(path)
    return r


@pytest.fixture(scope="session")
def reference():
    r = {}
    for name in FILES:
        path = os.path.join(REFERENCE_DIR, f"{name}.npy")
        assert os.path.isfile(path), f"Missing reference: {path}"
        r[name] = np.load(path)
    return r


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mode_error(a, b):
    """Min of positive/negative comparison for sign-ambiguous vectors."""
    return min(np.max(np.abs(a - b)), np.max(np.abs(a + b)))


# ---------------------------------------------------------------------------
# 1. Reference comparison tests
# ---------------------------------------------------------------------------


class TestMatchReference:
    """Pipeline outputs must match pre-computed reference values."""

    def test_total_variance(self, results, reference):
        np.testing.assert_allclose(
            results["total_variance"],
            reference["total_variance"],
            rtol=1e-6,
            err_msg="total_variance does not match reference",
        )

    def test_unrotated_expvar_ratio(self, results, reference):
        np.testing.assert_allclose(
            results["unrotated_expvar_ratio"],
            reference["unrotated_expvar_ratio"],
            rtol=1e-4,
            err_msg="unrotated_expvar_ratio does not match reference",
        )

    def test_unrotated_components(self, results, reference):
        res = results["unrotated_components"]
        ref = reference["unrotated_components"]
        for i in range(res.shape[0]):
            err = _mode_error(res[i], ref[i])
            assert err < 1e-4, (
                f"unrotated_components mode {i}: max error = {err:.2e}"
            )

    def test_unrotated_scores(self, results, reference):
        res = results["unrotated_scores"]
        ref = reference["unrotated_scores"]
        for i in range(res.shape[1]):
            err = _mode_error(res[:, i], ref[:, i])
            scale = max(np.max(np.abs(ref[:, i])), 1e-10)
            assert err / scale < 1e-4, (
                f"unrotated_scores mode {i}: relative error = {err / scale:.2e}"
            )

    def test_rotated_components(self, results, reference):
        res = results["rotated_components"]
        ref = reference["rotated_components"]
        for i in range(res.shape[0]):
            err = _mode_error(res[i], ref[i])
            assert err < 1e-3, (
                f"rotated_components mode {i}: max error = {err:.2e}"
            )

    def test_rotated_scores(self, results, reference):
        res = results["rotated_scores"]
        ref = reference["rotated_scores"]
        for i in range(res.shape[1]):
            err = _mode_error(res[:, i], ref[:, i])
            scale = max(np.max(np.abs(ref[:, i])), 1e-10)
            assert err / scale < 1e-3, (
                f"rotated_scores mode {i}: relative error = {err / scale:.2e}"
            )

    def test_rotated_expvar_ratio(self, results, reference):
        np.testing.assert_allclose(
            results["rotated_expvar_ratio"],
            reference["rotated_expvar_ratio"],
            rtol=1e-4,
            err_msg="rotated_expvar_ratio does not match reference",
        )

    def test_rotation_matrix(self, results, reference):
        res = results["rotation_matrix"]
        ref = reference["rotation_matrix"]
        for i in range(res.shape[1]):
            err = _mode_error(res[:, i], ref[:, i])
            assert err < 1e-3, (
                f"rotation_matrix column {i}: max error = {err:.2e}"
            )

    def test_phi_matrix(self, results, reference):
        np.testing.assert_allclose(
            np.abs(results["phi_matrix"]),
            np.abs(reference["phi_matrix"]),
            atol=1e-3,
            err_msg="phi_matrix does not match reference",
        )

    def test_varimax_criterion_before(self, results, reference):
        np.testing.assert_allclose(
            results["varimax_criterion_before"],
            reference["varimax_criterion_before"],
            rtol=1e-4,
            err_msg="varimax_criterion_before does not match reference",
        )

    def test_varimax_criterion_after(self, results, reference):
        np.testing.assert_allclose(
            results["varimax_criterion_after"],
            reference["varimax_criterion_after"],
            rtol=1e-4,
            err_msg="varimax_criterion_after does not match reference",
        )


# ---------------------------------------------------------------------------
# 2. Mathematical property tests
# ---------------------------------------------------------------------------


class TestMathematicalProperties:
    """Verify mathematical invariants of the outputs."""

    def test_components_orthonormal(self, results):
        V = results["unrotated_components"]
        gram = V @ V.T
        np.testing.assert_allclose(
            gram, np.eye(V.shape[0]), atol=1e-8,
            err_msg="Unrotated components must be orthonormal",
        )

    def test_variance_positive_decreasing(self, results):
        ev = results["unrotated_expvar_ratio"]
        assert np.all(ev > 0), "Variance ratios must be positive"
        assert np.all(np.diff(ev) <= 1e-12), "Must be non-increasing"

    def test_variance_sum_leq_one(self, results):
        s = np.sum(results["unrotated_expvar_ratio"])
        assert s <= 1.0 + 1e-10, f"Sum of variance ratios = {s} > 1"

    def test_rotated_variance_positive(self, results):
        assert np.all(results["rotated_expvar_ratio"] > 0)

    def test_varimax_improved(self, results):
        before = float(results["varimax_criterion_before"])
        after = float(results["varimax_criterion_after"])
        assert after > before, (
            f"Varimax criterion must improve: {before} -> {after}"
        )

    def test_phi_symmetric_unit_diagonal(self, results):
        phi = results["phi_matrix"]
        np.testing.assert_allclose(
            np.diag(phi), 1.0, atol=1e-8,
            err_msg="Phi diagonal must be 1.0",
        )
        np.testing.assert_allclose(
            phi, phi.T, atol=1e-8,
            err_msg="Phi must be symmetric",
        )

    def test_phi_bounded(self, results):
        assert np.all(np.abs(results["phi_matrix"]) <= 1.0 + 1e-8), \
            "Phi elements must be in [-1, 1]"

    def test_rotation_matrix_invertible(self, results):
        R = results["rotation_matrix"]
        det = np.linalg.det(R)
        assert abs(det) > 1e-6, f"R must be invertible (det={det})"

    def test_oblique_rotation(self, results):
        """Promax with power > 1 must produce non-orthogonal R."""
        R = results["rotation_matrix"]
        RtR = R.T @ R
        offdiag = RtR - np.diag(np.diag(RtR))
        assert np.max(np.abs(offdiag)) > 0.01, \
            "Rotation matrix must be oblique (non-orthogonal)"

    def test_scores_finite(self, results):
        assert np.all(np.isfinite(results["unrotated_scores"])), \
            "Unrotated scores contain non-finite values"
        assert np.all(np.isfinite(results["rotated_scores"])), \
            "Rotated scores contain non-finite values"

    def test_rotated_scores_nontrivial(self, results):
        """Rotated scores should have meaningful variance."""
        for i in range(results["rotated_scores"].shape[1]):
            v = np.var(results["rotated_scores"][:, i])
            assert v > 0.01, f"Rotated mode {i} scores have near-zero variance"
