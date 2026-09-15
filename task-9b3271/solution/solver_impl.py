"""
Complete solver for monocular depth-corrected relative pose estimation.

"""

import ctypes
import numpy as np

# ---------------------------------------------------------------------------
# Load the C coefficient library
# ---------------------------------------------------------------------------
_lib = ctypes.CDLL('/app/libcoeffgen.so')
_lib.compute_coefficients.argtypes = [
    ctypes.c_void_p,   # x1
    ctypes.c_void_p,   # x2
    ctypes.c_void_p,   # d1
    ctypes.c_void_p,   # d2
    ctypes.c_void_p,   # coeffs out
]
_lib.compute_coefficients.restype = None


def _compute_coeffs(x1, x2, d1, d2):
    """Call C library to compute 18 polynomial coefficients."""
    x1_c = np.ascontiguousarray(x1, dtype=np.float64)
    x2_c = np.ascontiguousarray(x2, dtype=np.float64)
    d1_c = np.ascontiguousarray(d1, dtype=np.float64)
    d2_c = np.ascontiguousarray(d2, dtype=np.float64)
    coeffs = np.zeros(18, dtype=np.float64)
    _lib.compute_coefficients(
        x1_c.ctypes.data,
        x2_c.ctypes.data,
        d1_c.ctypes.data,
        d2_c.ctypes.data,
        coeffs.ctypes.data,
    )
    return coeffs


def solve_scale_shift(x1, x2, d1, d2):
    """Minimal 3-point solver for depth scale/shift parameters.

    Uses the C library for coefficient computation, then solves the
    polynomial system via elimination and eigenvalue decomposition.
    """
    coeffs = _compute_coeffs(x1, x2, d1, d2)

    # Build the 12x12 elimination matrix C0 and 12x4 RHS matrix C1.
    # The system is obtained by multiplying the 3 constraint equations
    # by {b1, a2, b2}, giving 12 equations total in degree-3 monomials.
    ci0 = [0, 6, 12, 1, 7, 13, 2, 8, 0, 6, 12, 14,
           6, 0, 12, 1, 7, 13, 3, 9, 2, 8, 14, 15,
           4, 10, 7, 1, 16, 13, 8, 2, 6, 12, 0, 14,
           9, 3, 8, 14, 2, 15, 3, 9, 15, 4, 10, 16,
           7, 13, 1, 5, 11, 10, 4, 17, 16]
    ci1 = [11, 17, 5, 9, 15, 3, 5, 11, 17, 10, 16, 4, 11, 5, 17]
    r0 = [0, 1, 9, 12, 13, 21, 24, 25, 26, 28, 29, 33,
          39, 42, 47, 50, 52, 53, 60, 61, 62, 64, 65, 69,
          72, 73, 75, 78, 81, 83, 87, 90, 91, 92, 94, 95,
          99, 102, 103, 104, 106, 107, 110, 112, 113, 122,
          124, 125, 127, 128, 130, 132, 133, 135, 138, 141, 143]
    r1 = [7, 8, 10, 19, 20, 22, 26, 28, 29, 31, 32, 34, 39, 42, 47]

    C0 = np.zeros((12, 12))
    C1 = np.zeros((12, 4))
    C0[np.unravel_index(r0, (12, 12), 'F')] = coeffs[ci0]
    C1[np.unravel_index(r1, (12, 4), 'F')] = coeffs[ci1]

    try:
        C2 = np.linalg.solve(C0, C1)
    except np.linalg.LinAlgError:
        return []

    AM = np.array([
        [0.0, 0.0, 1.0, 0.0],
        -C2[9, :],
        -C2[10, :],
        -C2[11, :],
    ])

    D, V = np.linalg.eig(AM)

    sols = np.array([V[1, :] / V[0, :], D, V[3, :] / V[0, :]]).T
    real_mask = np.isreal(D)
    sols = sols[real_mask, :]

    solutions = []
    for s in sols:
        s = np.real(s)
        if s[0] < 0:
            continue
        a2 = np.sqrt(s[0])
        b1 = s[1]
        b2 = s[2] * a2
        solutions.append((1.0, float(b1), float(a2), float(b2)))

    return solutions


def estimate_rotation(source_pts, target_pts):
    """Optimal rotation estimation from paired point sets.

    Finds R minimizing || target - R @ source ||_F via SVD.
    """
    M = target_pts @ source_pts.T
    U, S, Vt = np.linalg.svd(M)
    D = np.eye(3)
    D[2, 2] = np.linalg.det(U) * np.linalg.det(Vt)
    return U @ D @ Vt


def recover_translation(X1, X2, R):
    """Recover unit translation from paired 3D points and rotation."""
    t = np.mean(X2, axis=0) - R @ np.mean(X1, axis=0)
    norm = np.linalg.norm(t)
    if norm < 1e-10:
        return np.array([0.0, 0.0, 1.0])
    return t / norm


def _estimate_pose(X1, X2):
    """Estimate R and t from paired 3D point sets (row vectors, N x 3)."""
    m1 = np.mean(X1, axis=0)
    m2 = np.mean(X2, axis=0)
    X1c = (X1 - m1).T
    X2c = (X2 - m2).T
    R = estimate_rotation(X1c, X2c)
    t = m2 - R @ m1
    return R, t


def robust_pose_estimate(x1s, x2s, d1s, d2s, threshold=0.01,
                         max_iterations=1000):
    """Robust pose estimation with outlier rejection using the 3-point solver."""
    N = len(x1s)
    best_num_inliers = 0
    best_result = None
    rng = np.random.RandomState(0)

    for _ in range(max_iterations):
        idx = rng.choice(N, 3, replace=False)

        try:
            solutions = solve_scale_shift(
                x1s[idx], x2s[idx], d1s[idx], d2s[idx])
        except Exception:
            continue

        for a1, b1, a2, b2 in solutions:
            if np.any(np.isnan([a1, b1, a2, b2])):
                continue

            D1 = a1 * d1s + b1
            D2 = a2 * d2s + b2

            D1_s = D1[idx]
            D2_s = D2[idx]
            if np.any(D1_s <= 0) or np.any(D2_s <= 0):
                continue

            X1_all = x1s * D1[:, None]
            X2_all = x2s * D2[:, None]

            try:
                R, t_raw = _estimate_pose(X1_all[idx], X2_all[idx])
            except Exception:
                continue

            X2_pred = (R @ X1_all.T).T + t_raw
            residuals = np.linalg.norm(X2_all - X2_pred, axis=1)

            inlier_mask = residuals < threshold
            num_inliers = int(np.sum(inlier_mask))

            if num_inliers > best_num_inliers:
                best_num_inliers = num_inliers
                X1_in = X1_all[inlier_mask]
                X2_in = X2_all[inlier_mask]
                R_ref, t_ref = _estimate_pose(X1_in, X2_in)
                tn = np.linalg.norm(t_ref)
                t_unit = t_ref / tn if tn > 1e-10 else np.array([0., 0., 1.])
                best_result = (R_ref, t_unit, (a1, b1, a2, b2), inlier_mask)

    if best_result is None:
        raise ValueError("Failed to find a valid solution")

    return best_result
