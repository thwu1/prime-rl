
"""Tests for the affine-depth relative pose estimation pipeline."""

import sys
sys.path.insert(0, '/app')

import ctypes
import os
import numpy as np
import pytest

from solver.minimal_solver import compute_coefficients, solve_affine_depth
from solver.pose_recovery import find_rotation, recover_pose
from solver.robust_estimator import ransac_estimate
from solver.types import AffineParams, PoseResult
from data_gen import generate_correspondences, generate_correspondences_with_outliers

c_double_p = ctypes.POINTER(ctypes.c_double)


# ---------------------------------------------------------------------------
# Test compiled C eigenvalue library
# ---------------------------------------------------------------------------

class TestCLibrary:
    def test_library_exists(self):
        """The compiled shared library must exist."""
        assert os.path.exists('/app/csolver/libeigens.so'), \
            "libeigens.so not found at /app/csolver/ — build it first"

    def test_library_loadable(self):
        """The shared library must be loadable and export eig4x4."""
        lib = ctypes.CDLL('/app/csolver/libeigens.so')
        assert hasattr(lib, 'eig4x4'), "eig4x4 symbol not found in library"

    def test_eigenvalues_identity(self):
        """Eigenvalues of the 4x4 identity matrix must all be 1."""
        lib = ctypes.CDLL('/app/csolver/libeigens.so')
        lib.eig4x4.argtypes = [c_double_p, c_double_p, c_double_p, c_double_p]
        lib.eig4x4.restype = ctypes.c_int

        A = np.eye(4, dtype=np.float64).flatten()
        wr = np.zeros(4, dtype=np.float64)
        wi = np.zeros(4, dtype=np.float64)
        vr = np.zeros(16, dtype=np.float64)

        ret = lib.eig4x4(
            A.ctypes.data_as(c_double_p),
            wr.ctypes.data_as(c_double_p),
            wi.ctypes.data_as(c_double_p),
            vr.ctypes.data_as(c_double_p),
        )
        assert ret == 0, f"eig4x4 returned error code {ret}"
        assert np.allclose(sorted(wr), [1.0, 1.0, 1.0, 1.0], atol=1e-10)
        assert np.allclose(wi, 0.0, atol=1e-10)

    def test_eigenvalues_diagonal(self):
        """Eigenvalues of diag(1,2,3,4) must be {1,2,3,4}."""
        lib = ctypes.CDLL('/app/csolver/libeigens.so')
        lib.eig4x4.argtypes = [c_double_p, c_double_p, c_double_p, c_double_p]
        lib.eig4x4.restype = ctypes.c_int

        A = np.diag([1.0, 2.0, 3.0, 4.0]).flatten().astype(np.float64)
        wr = np.zeros(4, dtype=np.float64)
        wi = np.zeros(4, dtype=np.float64)
        vr = np.zeros(16, dtype=np.float64)

        ret = lib.eig4x4(
            A.ctypes.data_as(c_double_p),
            wr.ctypes.data_as(c_double_p),
            wi.ctypes.data_as(c_double_p),
            vr.ctypes.data_as(c_double_p),
        )
        assert ret == 0, f"eig4x4 returned error code {ret}"
        assert np.allclose(sorted(wr), [1.0, 2.0, 3.0, 4.0], atol=1e-10)
        assert np.allclose(wi, 0.0, atol=1e-10)

    def test_eigenvectors_correctness(self):
        """Each eigenvector must satisfy A @ v = lambda * v."""
        lib = ctypes.CDLL('/app/csolver/libeigens.so')
        lib.eig4x4.argtypes = [c_double_p, c_double_p, c_double_p, c_double_p]
        lib.eig4x4.restype = ctypes.c_int

        np.random.seed(12345)
        M = np.random.randn(4, 4)
        M = (M + M.T) / 2  # symmetric → all real eigenvalues
        A_flat = M.flatten().astype(np.float64)
        wr = np.zeros(4, dtype=np.float64)
        wi = np.zeros(4, dtype=np.float64)
        vr = np.zeros(16, dtype=np.float64)

        ret = lib.eig4x4(
            A_flat.ctypes.data_as(c_double_p),
            wr.ctypes.data_as(c_double_p),
            wi.ctypes.data_as(c_double_p),
            vr.ctypes.data_as(c_double_p),
        )
        assert ret == 0

        V = vr.reshape(4, 4)
        for j in range(4):
            if abs(wi[j]) > 1e-8:
                continue
            v = V[:, j]
            if np.linalg.norm(v) < 1e-12:
                continue
            Av = M @ v
            lv = wr[j] * v
            assert np.allclose(Av, lv, atol=1e-8), \
                f"Eigenvector {j} does not satisfy A@v = lambda*v"


# ---------------------------------------------------------------------------
# Test coefficient computation
# ---------------------------------------------------------------------------

class TestCoefficientComputation:
    def test_output_shape(self):
        """Coefficients vector must be length 18 (6 per point pair)."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=42)
        coeffs = compute_coefficients(x1, x2, d1, d2)
        assert isinstance(coeffs, np.ndarray)
        assert coeffs.shape == (18,), f"Expected (18,) but got {coeffs.shape}"

    def test_b1_squared_coefficient(self):
        """c_1 = p_ii + p_jj - 2*p_ij for each pair."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=77)
        coeffs = compute_coefficients(x1, x2, d1, d2)
        for k, (i, j) in enumerate([(0, 1), (0, 2), (1, 2)]):
            expected = (x1[i].dot(x1[i]) + x1[j].dot(x1[j])
                        - 2 * x1[i].dot(x1[j]))
            assert np.isclose(coeffs[k * 6 + 1], expected, atol=1e-10), \
                f"Pair ({i},{j}): b1^2 coeff mismatch"

    def test_alpha_beta_sq_coefficient(self):
        """c_0 = 2*s_ij - s_ii - s_jj for each pair."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=77)
        coeffs = compute_coefficients(x1, x2, d1, d2)
        for k, (i, j) in enumerate([(0, 1), (0, 2), (1, 2)]):
            expected = (2 * x2[i].dot(x2[j]) - x2[i].dot(x2[i])
                        - x2[j].dot(x2[j]))
            assert np.isclose(coeffs[k * 6], expected, atol=1e-10), \
                f"Pair ({i},{j}): alpha*beta^2 coeff mismatch"

    def test_constant_coefficient(self):
        """c_5 = d1i^2*p_ii + d1j^2*p_jj - 2*d1i*d1j*p_ij."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=77)
        coeffs = compute_coefficients(x1, x2, d1, d2)
        for k, (i, j) in enumerate([(0, 1), (0, 2), (1, 2)]):
            expected = (d1[i] ** 2 * x1[i].dot(x1[i])
                        + d1[j] ** 2 * x1[j].dot(x1[j])
                        - 2 * d1[i] * d1[j] * x1[i].dot(x1[j]))
            assert np.isclose(coeffs[k * 6 + 5], expected, atol=1e-10), \
                f"Pair ({i},{j}): constant coeff mismatch"

    def test_alpha_coefficient(self):
        """c_3 = 2*d2i*d2j*s_ij - d2i^2*s_ii - d2j^2*s_jj."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=77)
        coeffs = compute_coefficients(x1, x2, d1, d2)
        for k, (i, j) in enumerate([(0, 1), (0, 2), (1, 2)]):
            expected = (2 * d2[i] * d2[j] * x2[i].dot(x2[j])
                        - d2[i] ** 2 * x2[i].dot(x2[i])
                        - d2[j] ** 2 * x2[j].dot(x2[j]))
            assert np.isclose(coeffs[k * 6 + 3], expected, atol=1e-10), \
                f"Pair ({i},{j}): alpha coeff mismatch"

    def test_alpha_beta_coefficient(self):
        """c_2 = 2*(d2i+d2j)*s_ij - 2*d2i*s_ii - 2*d2j*s_jj."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=77)
        coeffs = compute_coefficients(x1, x2, d1, d2)
        for k, (i, j) in enumerate([(0, 1), (0, 2), (1, 2)]):
            expected = (2 * (d2[i] + d2[j]) * x2[i].dot(x2[j])
                        - 2 * d2[i] * x2[i].dot(x2[i])
                        - 2 * d2[j] * x2[j].dot(x2[j]))
            assert np.isclose(coeffs[k * 6 + 2], expected, atol=1e-10), \
                f"Pair ({i},{j}): alpha*beta coeff mismatch"

    def test_b1_coefficient(self):
        """c_4 = 2*d1i*p_ii + 2*d1j*p_jj - 2*(d1i+d1j)*p_ij."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=77)
        coeffs = compute_coefficients(x1, x2, d1, d2)
        for k, (i, j) in enumerate([(0, 1), (0, 2), (1, 2)]):
            expected = (2 * d1[i] * x1[i].dot(x1[i])
                        + 2 * d1[j] * x1[j].dot(x1[j])
                        - 2 * (d1[i] + d1[j]) * x1[i].dot(x1[j]))
            assert np.isclose(coeffs[k * 6 + 4], expected, atol=1e-10), \
                f"Pair ({i},{j}): b1 coeff mismatch"


# ---------------------------------------------------------------------------
# Test minimal solver
# ---------------------------------------------------------------------------

class TestMinimalSolver:
    @pytest.mark.parametrize("seed", [42, 1, 7, 13, 99, 256, 500])
    def test_recovers_affine_params(self, seed):
        """Solver must recover ground-truth affine params on noise-free data."""
        x1, x2, d1, d2, gt = generate_correspondences(3, seed=seed)
        solutions = solve_affine_depth(x1, x2, d1, d2)

        assert len(solutions) > 0, "Solver returned no solutions"

        best_err = float('inf')
        for sol in solutions:
            err = (abs(sol.a2 - gt['a2_norm'])
                   + abs(sol.b1 - gt['b1_norm'])
                   + abs(sol.b2 - gt['b2_norm']))
            best_err = min(best_err, err)

        assert best_err < 0.01, (
            f"Seed {seed}: no solution close to ground truth "
            f"(best err={best_err:.6f}). "
            f"GT: a2={gt['a2_norm']:.4f}, b1={gt['b1_norm']:.4f}, "
            f"b2={gt['b2_norm']:.4f}"
        )

    def test_solution_count(self):
        """Between 1 and 4 real positive-alpha solutions expected."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=42)
        solutions = solve_affine_depth(x1, x2, d1, d2)
        assert 1 <= len(solutions) <= 8, \
            f"Expected 1-8 solutions, got {len(solutions)}"

    def test_a1_normalized(self):
        """All solutions must have a1 = 1.0."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=42)
        solutions = solve_affine_depth(x1, x2, d1, d2)
        for sol in solutions:
            assert np.isclose(sol.a1, 1.0), f"Expected a1=1.0, got {sol.a1}"

    def test_solutions_satisfy_constraints(self):
        """Each returned solution must satisfy the polynomial equations."""
        x1, x2, d1, d2, _ = generate_correspondences(3, seed=42)
        coeffs = compute_coefficients(x1, x2, d1, d2)
        solutions = solve_affine_depth(x1, x2, d1, d2)

        for sol in solutions:
            alpha = sol.a2 ** 2
            beta = sol.b2 / sol.a2 if sol.a2 > 1e-12 else 0.0
            b1 = sol.b1
            for k in range(3):
                c = coeffs[k * 6:(k + 1) * 6]
                val = (c[0] * alpha * beta ** 2 + c[1] * b1 ** 2
                       + c[2] * alpha * beta + c[3] * alpha
                       + c[4] * b1 + c[5])
                assert abs(val) < 1e-4, (
                    f"Solution does not satisfy equation {k}: residual={val:.6e}"
                )


# ---------------------------------------------------------------------------
# Test pose recovery
# ---------------------------------------------------------------------------

class TestPoseRecovery:
    def test_find_rotation_known(self):
        """find_rotation must exactly recover a known R, t from noiseless data."""
        np.random.seed(42)
        R_gt = np.linalg.qr(np.random.randn(3, 3))[0]
        R_gt = R_gt * np.linalg.det(R_gt)
        t_gt = np.random.randn(3)

        X1 = np.random.randn(10, 3)
        X2 = X1 @ R_gt.T + t_gt

        R_est, t_est = find_rotation(X1, X2)

        assert np.allclose(R_est, R_gt, atol=1e-8), \
            f"Rotation mismatch: max err={np.max(np.abs(R_est - R_gt)):.2e}"
        assert np.allclose(t_est, t_gt, atol=1e-8), \
            f"Translation mismatch: max err={np.max(np.abs(t_est - t_gt)):.2e}"

    def test_rotation_validity(self):
        """Recovered rotation must be orthogonal with det = +1."""
        x1, x2, d1, d2, gt = generate_correspondences(3, seed=42)
        solutions = solve_affine_depth(x1, x2, d1, d2)
        best = min(solutions, key=lambda s: abs(s.a2 - gt['a2_norm']))
        result = recover_pose(x1, x2, d1, d2, best)

        assert np.allclose(result.R @ result.R.T, np.eye(3), atol=1e-6), \
            "R is not orthogonal"
        assert np.isclose(np.linalg.det(result.R), 1.0, atol=1e-6), \
            f"det(R) = {np.linalg.det(result.R):.6f}, expected 1.0"

    @pytest.mark.parametrize("seed", [42, 7, 13, 99])
    def test_rotation_accuracy(self, seed):
        """Recovered rotation must match ground truth closely."""
        x1, x2, d1, d2, gt = generate_correspondences(3, seed=seed)
        solutions = solve_affine_depth(x1, x2, d1, d2)
        best = min(solutions, key=lambda s: abs(s.a2 - gt['a2_norm']))
        result = recover_pose(x1, x2, d1, d2, best)

        R_err = np.linalg.norm(result.R - gt['R'])
        assert R_err < 0.05, \
            f"Seed {seed}: rotation error {R_err:.6f} exceeds threshold"

    @pytest.mark.parametrize("seed", [42, 7, 13, 99])
    def test_translation_direction(self, seed):
        """Recovered translation direction must match ground truth."""
        x1, x2, d1, d2, gt = generate_correspondences(3, seed=seed)
        solutions = solve_affine_depth(x1, x2, d1, d2)
        best = min(solutions, key=lambda s: abs(s.a2 - gt['a2_norm']))
        result = recover_pose(x1, x2, d1, d2, best)

        t_dir_est = result.t / np.linalg.norm(result.t)
        t_dir_gt = gt['t'] / np.linalg.norm(gt['t'])
        # Handle sign ambiguity
        t_err = min(np.linalg.norm(t_dir_est - t_dir_gt),
                    np.linalg.norm(t_dir_est + t_dir_gt))
        assert t_err < 0.05, \
            f"Seed {seed}: translation direction error {t_err:.6f}"

    def test_result_type(self):
        """recover_pose must return a PoseResult."""
        x1, x2, d1, d2, gt = generate_correspondences(3, seed=42)
        solutions = solve_affine_depth(x1, x2, d1, d2)
        result = recover_pose(x1, x2, d1, d2, solutions[0])
        assert isinstance(result, PoseResult)
        assert result.R.shape == (3, 3)
        assert result.t.shape == (3,)
        assert isinstance(result.affine, AffineParams)


# ---------------------------------------------------------------------------
# Test RANSAC
# ---------------------------------------------------------------------------

class TestRANSAC:
    def test_with_outliers(self):
        """RANSAC must handle 30% outlier contamination."""
        x1, x2, d1, d2, gt = generate_correspondences_with_outliers(
            20, 8, seed=42)
        np.random.seed(123)
        result = ransac_estimate(x1, x2, d1, d2,
                                 n_iterations=300,
                                 inlier_threshold=0.5)

        assert isinstance(result, PoseResult)
        R_err = np.linalg.norm(result.R - gt['R'])
        assert R_err < 0.3, \
            f"RANSAC rotation error {R_err:.4f} with outliers"

    def test_clean_data(self):
        """RANSAC on clean data should be highly accurate."""
        x1, x2, d1, d2, gt = generate_correspondences(10, seed=42)
        np.random.seed(456)
        result = ransac_estimate(x1, x2, d1, d2,
                                 n_iterations=100,
                                 inlier_threshold=0.5)

        R_err = np.linalg.norm(result.R - gt['R'])
        assert R_err < 0.1, \
            f"RANSAC rotation error {R_err:.4f} on clean data"

    def test_returns_valid_types(self):
        """RANSAC must return a properly typed PoseResult."""
        x1, x2, d1, d2, _ = generate_correspondences(10, seed=42)
        np.random.seed(789)
        result = ransac_estimate(x1, x2, d1, d2,
                                 n_iterations=50,
                                 inlier_threshold=0.5)

        assert isinstance(result, PoseResult)
        assert result.R.shape == (3, 3)
        assert result.t.shape == (3,)
        assert isinstance(result.affine, AffineParams)
        assert np.isclose(np.linalg.det(result.R), 1.0, atol=1e-4)

    def test_translation_with_outliers(self):
        """RANSAC must recover translation direction despite outliers."""
        x1, x2, d1, d2, gt = generate_correspondences_with_outliers(
            20, 8, seed=42)
        np.random.seed(321)
        result = ransac_estimate(x1, x2, d1, d2,
                                 n_iterations=300,
                                 inlier_threshold=0.5)

        t_dir_est = result.t / np.linalg.norm(result.t)
        t_dir_gt = gt['t'] / np.linalg.norm(gt['t'])
        t_err = min(np.linalg.norm(t_dir_est - t_dir_gt),
                    np.linalg.norm(t_dir_est + t_dir_gt))
        assert t_err < 0.3, \
            f"RANSAC translation direction error {t_err:.4f}"
