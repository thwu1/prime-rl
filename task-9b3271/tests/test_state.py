"""
Tests for monocular depth-corrected relative pose estimation solver.

"""

import os
import sys
import numpy as np
import pytest

sys.path.insert(0, '/app')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_rotation(rng):
    Q, R = np.linalg.qr(rng.standard_normal((3, 3)))
    signs = np.sign(np.diag(R))
    Q = Q @ np.diag(signs)
    if np.linalg.det(Q) < 0:
        Q[:, 0] = -Q[:, 0]
    return Q


def _bounded_rotation(rng, max_angle=0.8):
    """Generate a rotation with bounded angle to keep points visible."""
    axis = rng.standard_normal(3)
    axis = axis / np.linalg.norm(axis)
    angle = rng.uniform(0.05, max_angle)
    K = np.array([[0, -axis[2], axis[1]],
                  [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def _make_3pt_problem(seed):
    """Generate a 3-point problem with known ground truth."""
    rng = np.random.RandomState(seed)

    R = _random_rotation(rng)
    t = rng.standard_normal(3)

    b1_gt = rng.standard_normal() * 0.5
    a2_gt = rng.uniform(0.5, 2.0)
    b2_gt = rng.standard_normal() * 0.5

    while True:
        x1 = np.column_stack([rng.standard_normal((3, 2)), np.ones(3)])
        d1_true = 1.0 + 5.0 * rng.random(3)
        X1 = x1 * d1_true[:, None]
        X2 = X1 @ R.T + t
        d2_true = X2[:, 2]
        if np.all(d2_true > 0):
            break

    x2 = X2 / d2_true[:, None]
    d1_obs = d1_true - b1_gt          # a1 = 1
    d2_obs = (d2_true - b2_gt) / a2_gt

    return x1, x2, d1_obs, d2_obs, b1_gt, a2_gt, b2_gt, R, t


def _make_full_scenario(seed, num_inliers=25, num_outliers=8):
    """Generate a full scenario with inliers and outliers."""
    rng = np.random.RandomState(seed)

    R = _bounded_rotation(rng, max_angle=0.8)
    t = rng.standard_normal(3) * 0.5
    t = t / np.linalg.norm(t)

    b1 = rng.standard_normal() * 0.3
    a2 = rng.uniform(0.5, 2.0)
    b2 = rng.standard_normal() * 0.3

    x1_lst, x2_lst, d1_lst, d2_lst = [], [], [], []
    attempts = 0
    while len(x1_lst) < num_inliers and attempts < num_inliers * 20:
        attempts += 1
        X = rng.standard_normal(3) * 1.5 + np.array([0., 0., 6.])
        if X[2] < 0.5:
            continue
        d1_true = X[2]
        x1_h = X / d1_true
        X2 = R @ X + t
        if X2[2] < 0.5:
            continue
        d2_true = X2[2]
        x2_h = X2 / d2_true
        x1_lst.append(x1_h)
        x2_lst.append(x2_h)
        d1_lst.append((d1_true - b1) / 1.0)
        d2_lst.append((d2_true - b2) / a2)

    actual = len(x1_lst)
    assert actual >= 3, f"Could not generate enough inliers (got {actual})"

    for _ in range(num_outliers):
        x1_lst.append(np.array([rng.standard_normal(), rng.standard_normal(), 1.0]))
        x2_lst.append(np.array([rng.standard_normal(), rng.standard_normal(), 1.0]))
        d1_lst.append(float(rng.uniform(0.5, 10.0)))
        d2_lst.append(float(rng.uniform(0.5, 10.0)))

    x1s = np.array(x1_lst)
    x2s = np.array(x2_lst)
    d1s = np.array(d1_lst)
    d2s = np.array(d2_lst)
    return x1s, x2s, d1s, d2s, R, t, actual


# ---------------------------------------------------------------------------
# Tests: C library integration
# ---------------------------------------------------------------------------

class TestCLibraryIntegration:

    def test_shared_library_exists(self):
        assert os.path.exists('/app/libcoeffgen.so'), \
            "libcoeffgen.so must be compiled at /app/libcoeffgen.so"

    def test_shared_library_loadable(self):
        import ctypes
        lib = ctypes.CDLL('/app/libcoeffgen.so')
        assert hasattr(lib, 'compute_coefficients'), \
            "libcoeffgen.so must export compute_coefficients"

    def test_solver_uses_native_library(self):
        """Verify solver.py interfaces with the compiled C library."""
        with open('/app/solver.py') as f:
            code = f.read()
        assert 'ctypes' in code or 'cffi' in code, \
            "solver.py must use ctypes or cffi to call the C coefficient library"
        assert 'libcoeffgen' in code, \
            "solver.py must reference the libcoeffgen shared library"

    def test_coefficient_output_shape(self):
        """Verify the C library produces 18 coefficients."""
        import ctypes
        lib = ctypes.CDLL('/app/libcoeffgen.so')
        lib.compute_coefficients.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        lib.compute_coefficients.restype = None

        x1 = np.array([[0.1, 0.2, 1.0],
                        [0.3, -0.1, 1.0],
                        [-0.2, 0.4, 1.0]], dtype=np.float64)
        x2 = np.array([[0.15, 0.25, 1.0],
                        [0.35, -0.05, 1.0],
                        [-0.15, 0.45, 1.0]], dtype=np.float64)
        d1 = np.array([3.0, 4.0, 5.0], dtype=np.float64)
        d2 = np.array([2.5, 3.5, 4.5], dtype=np.float64)
        coeffs = np.zeros(18, dtype=np.float64)

        lib.compute_coefficients(
            x1.ctypes.data, x2.ctypes.data,
            d1.ctypes.data, d2.ctypes.data,
            coeffs.ctypes.data,
        )
        assert not np.all(coeffs == 0), "Coefficients should be non-zero"
        assert not np.any(np.isnan(coeffs)), "Coefficients must not be NaN"


# ---------------------------------------------------------------------------
# Tests: scale-shift solver
# ---------------------------------------------------------------------------

class TestScaleShiftSolver:

    def test_returns_list_of_tuples(self):
        from solver import solve_scale_shift
        x1, x2, d1, d2, *_ = _make_3pt_problem(seed=1001)
        solutions = solve_scale_shift(x1, x2, d1, d2)
        assert isinstance(solutions, list)
        assert len(solutions) > 0, "Must return at least one solution"
        for s in solutions:
            assert isinstance(s, tuple) and len(s) == 4

    @pytest.mark.parametrize("seed", [1001, 1002, 1003, 1004, 1005])
    def test_recovers_ground_truth(self, seed):
        from solver import solve_scale_shift
        x1, x2, d1, d2, b1_gt, a2_gt, b2_gt, R, t = _make_3pt_problem(seed)
        solutions = solve_scale_shift(x1, x2, d1, d2)

        best = float('inf')
        for a1, b1, a2, b2 in solutions:
            if np.any(np.isnan([a1, b1, a2, b2])):
                continue
            if abs(a1) < 1e-10:
                continue
            err = abs(b1 / a1 - b1_gt) + abs(a2 / a1 - a2_gt) + abs(b2 / a1 - b2_gt)
            best = min(best, err)

        assert best < 1e-4, (
            f"No solution near GT (best err {best:.2e}) for seed {seed}")

    @pytest.mark.parametrize("seed", [2001, 2002, 2003])
    def test_solutions_satisfy_distance_constraint(self, seed):
        from solver import solve_scale_shift
        x1, x2, d1, d2, *_ = _make_3pt_problem(seed)
        solutions = solve_scale_shift(x1, x2, d1, d2)

        for a1, b1, a2, b2 in solutions:
            if np.any(np.isnan([a1, b1, a2, b2])):
                continue
            D1 = a1 * d1 + b1
            D2 = a2 * d2 + b2
            X1 = x1 * D1[:, None]
            X2 = x2 * D2[:, None]
            for i in range(3):
                for j in range(i + 1, 3):
                    sq1 = np.sum((X1[i] - X1[j]) ** 2)
                    sq2 = np.sum((X2[i] - X2[j]) ** 2)
                    assert abs(sq1 - sq2) < 1e-5, (
                        f"Distance constraint violated: {sq1} vs {sq2}")


# ---------------------------------------------------------------------------
# Tests: rotation estimator
# ---------------------------------------------------------------------------

class TestRotationEstimator:

    def test_proper_rotation(self):
        from solver import estimate_rotation
        rng = np.random.RandomState(42)
        src = rng.standard_normal((3, 15))
        tgt = rng.standard_normal((3, 15))
        R = estimate_rotation(src, tgt)
        assert R.shape == (3, 3)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-6), "R not orthogonal"
        assert abs(np.linalg.det(R) - 1.0) < 1e-6, "det(R) != 1"

    def test_recovers_known_rotation(self):
        from solver import estimate_rotation
        rng = np.random.RandomState(77)
        R_true = _random_rotation(rng)
        src = rng.standard_normal((3, 30))
        tgt = R_true @ src
        R_est = estimate_rotation(src, tgt)
        assert np.linalg.norm(R_est - R_true, 'fro') < 1e-6


# ---------------------------------------------------------------------------
# Tests: translation recovery
# ---------------------------------------------------------------------------

class TestTranslationRecovery:

    def test_recovers_translation(self):
        from solver import recover_translation
        rng = np.random.RandomState(88)
        R = _random_rotation(rng)
        t_true = rng.standard_normal(3)
        t_true = t_true / np.linalg.norm(t_true)
        X1 = rng.standard_normal((25, 3)) + np.array([0, 0, 5])
        X2 = (R @ X1.T).T + t_true
        t_est = recover_translation(X1, X2, R)
        t_est = t_est / np.linalg.norm(t_est)
        err = min(np.linalg.norm(t_est - t_true),
                  np.linalg.norm(t_est + t_true))
        assert err < 1e-6, f"Translation error {err}"


# ---------------------------------------------------------------------------
# Tests: full pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def test_clean_data(self):
        from solver import robust_pose_estimate
        x1s, x2s, d1s, d2s, R_gt, t_gt, n_in = _make_full_scenario(
            seed=4001, num_inliers=30, num_outliers=0)

        R_est, t_est, params, mask = robust_pose_estimate(
            x1s, x2s, d1s, d2s, threshold=0.05, max_iterations=500)

        R_err = np.linalg.norm(R_est - R_gt, 'fro')
        assert R_err < 0.1, f"R error {R_err:.4f}"

        tu = t_est / np.linalg.norm(t_est)
        tg = t_gt / np.linalg.norm(t_gt)
        t_err = min(np.linalg.norm(tu - tg), np.linalg.norm(tu + tg))
        assert t_err < 0.1, f"t error {t_err:.4f}"

    def test_with_outliers(self):
        from solver import robust_pose_estimate
        x1s, x2s, d1s, d2s, R_gt, t_gt, n_in = _make_full_scenario(
            seed=4005, num_inliers=30, num_outliers=10)

        R_est, t_est, params, mask = robust_pose_estimate(
            x1s, x2s, d1s, d2s, threshold=0.05, max_iterations=1000)

        R_err = np.linalg.norm(R_est - R_gt, 'fro')
        assert R_err < 0.15, f"R error {R_err:.4f}"

        tu = t_est / np.linalg.norm(t_est)
        tg = t_gt / np.linalg.norm(t_gt)
        t_err = min(np.linalg.norm(tu - tg), np.linalg.norm(tu + tg))
        assert t_err < 0.15, f"t error {t_err:.4f}"

    def test_inlier_count_reasonable(self):
        from solver import robust_pose_estimate
        x1s, x2s, d1s, d2s, R_gt, t_gt, n_in = _make_full_scenario(
            seed=4010, num_inliers=25, num_outliers=8)

        R_est, t_est, params, mask = robust_pose_estimate(
            x1s, x2s, d1s, d2s, threshold=0.05, max_iterations=500)

        assert int(np.sum(mask)) >= n_in * 0.7, (
            f"Found only {int(np.sum(mask))} inliers, expected >= {int(n_in * 0.7)}")
