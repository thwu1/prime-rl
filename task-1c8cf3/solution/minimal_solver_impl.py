
"""Minimal 3-point solver for affine-depth scale-shift recovery.

Uses the compiled C/LAPACK eigenvalue library for the core polynomial solver.
"""

import numpy as np
import ctypes
import os
from typing import List
from .types import AffineParams

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '..', 'csolver', 'libeigens.so')
_c_double_p = ctypes.POINTER(ctypes.c_double)
_lib = None


def _get_lib():
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL(_LIB_PATH)
        _lib.eig4x4.argtypes = [_c_double_p, _c_double_p,
                                 _c_double_p, _c_double_p]
        _lib.eig4x4.restype = ctypes.c_int
    return _lib


def _eig4x4_c(A):
    """Eigenvalue decomposition of 4x4 real matrix via C/LAPACK library."""
    lib = _get_lib()
    a_buf = np.ascontiguousarray(A.flatten(), dtype=np.float64)
    wr = np.zeros(4, dtype=np.float64)
    wi = np.zeros(4, dtype=np.float64)
    vr = np.zeros(16, dtype=np.float64)
    ret = lib.eig4x4(
        a_buf.ctypes.data_as(_c_double_p),
        wr.ctypes.data_as(_c_double_p),
        wi.ctypes.data_as(_c_double_p),
        vr.ctypes.data_as(_c_double_p),
    )
    if ret != 0:
        raise RuntimeError(f"eig4x4 LAPACK error info={ret}")
    V = vr.reshape(4, 4)
    return wr, wi, V


def compute_coefficients(x1: np.ndarray, x2: np.ndarray,
                         d1: np.ndarray, d2: np.ndarray) -> np.ndarray:
    """Compute 18 polynomial coefficients from 3 point correspondences."""
    coeffs = np.zeros(18)

    pairs = [(0, 1), (0, 2), (1, 2)]
    for k, (i, j) in enumerate(pairs):
        base = k * 6

        s_ii = x2[i].dot(x2[i])
        s_jj = x2[j].dot(x2[j])
        s_ij = x2[i].dot(x2[j])
        p_ii = x1[i].dot(x1[i])
        p_jj = x1[j].dot(x1[j])
        p_ij = x1[i].dot(x1[j])

        coeffs[base + 0] = 2 * s_ij - s_ii - s_jj
        coeffs[base + 1] = p_ii + p_jj - 2 * p_ij
        coeffs[base + 2] = (2 * (d2[i] + d2[j]) * s_ij
                            - 2 * d2[i] * s_ii - 2 * d2[j] * s_jj)
        coeffs[base + 3] = (2 * d2[i] * d2[j] * s_ij
                            - d2[i] ** 2 * s_ii - d2[j] ** 2 * s_jj)
        coeffs[base + 4] = (2 * d1[i] * p_ii + 2 * d1[j] * p_jj
                            - 2 * (d1[i] + d1[j]) * p_ij)
        coeffs[base + 5] = (d1[i] ** 2 * p_ii + d1[j] ** 2 * p_jj
                            - 2 * d1[i] * d1[j] * p_ij)

    return coeffs


def solve_affine_depth(x1: np.ndarray, x2: np.ndarray,
                       d1: np.ndarray, d2: np.ndarray) -> List[AffineParams]:
    """Solve for affine depth parameters via action matrix eigenvalue method."""
    coeffs = compute_coefficients(x1, x2, d1, d2)

    # Index arrays encoding the expanded polynomial system structure after
    # multiplying the 3 equations by the monomial set {1, b1, beta, b1*beta}.
    # fmt: off
    coeff_ind0 = [
        0, 6, 12, 1, 7, 13, 2, 8, 0, 6, 12, 14, 6, 0, 12,
        1, 7, 13, 3, 9, 2, 8, 14, 15, 4, 10, 7, 1, 16, 13,
        8, 2, 6, 12, 0, 14, 9, 3, 8, 14, 2, 15, 3, 9, 15,
        4, 10, 16, 7, 13, 1, 5, 11, 10, 4, 17, 16
    ]
    coeff_ind1 = [
        11, 17, 5, 9, 15, 3, 5, 11, 17, 10, 16, 4, 11, 5, 17
    ]
    ind0 = [
        0, 1, 9, 12, 13, 21, 24, 25, 26, 28, 29, 33, 39, 42, 47,
        50, 52, 53, 60, 61, 62, 64, 65, 69, 72, 73, 75, 78, 81, 83,
        87, 90, 91, 92, 94, 95, 99, 102, 103, 104, 106, 107, 110, 112,
        113, 122, 124, 125, 127, 128, 130, 132, 133, 135, 138, 141, 143
    ]
    ind1 = [
        7, 8, 10, 19, 20, 22, 26, 28, 29, 31, 32, 34, 39, 42, 47
    ]
    # fmt: on

    C0 = np.zeros((12, 12))
    C1 = np.zeros((12, 4))
    C0[np.unravel_index(ind0, (12, 12), "F")] = coeffs[coeff_ind0]
    C1[np.unravel_index(ind1, (12, 4), "F")] = coeffs[coeff_ind1]

    try:
        C2 = np.linalg.solve(C0, C1)
    except np.linalg.LinAlgError:
        return []

    # 4x4 action matrix for multiplication by b1
    # Basis = [1, alpha, b1, beta]
    AM = np.array([
        [0.0, 0.0, 1.0, 0.0],
        -C2[9, :],
        -C2[10, :],
        -C2[11, :]
    ])

    # Eigenvalue decomposition via C/LAPACK library
    wr, wi, V = _eig4x4_c(AM)

    real_mask = np.abs(wi) < 1e-8

    solutions = []
    for idx in range(4):
        if not real_mask[idx]:
            continue
        if abs(V[0, idx]) < 1e-12:
            continue
        alpha = float(V[1, idx] / V[0, idx])
        b1_val = float(wr[idx])
        beta = float(V[3, idx] / V[0, idx])

        if alpha < -1e-10:
            continue
        alpha = max(alpha, 0.0)

        a2 = np.sqrt(alpha)
        b2 = beta * a2

        solutions.append(AffineParams(a1=1.0, b1=b1_val, a2=a2, b2=b2))

    return solutions
