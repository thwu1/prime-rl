
"""Minimal 3-point solver for affine-depth scale-shift recovery.

See /app/FORMULATION.md for the mathematical derivation.
"""

import numpy as np
import ctypes
import os
from typing import List
from .types import AffineParams

# Path to the compiled eigenvalue library (must be built first).
_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '..', 'csolver', 'libeigens.so')


def compute_coefficients(x1: np.ndarray, x2: np.ndarray,
                         d1: np.ndarray, d2: np.ndarray) -> np.ndarray:
    """Compute polynomial coefficients from 3 point correspondences.

    Derives 18 coefficients (6 per point pair) from the interpoint distance
    constraint equations defined in FORMULATION.md.

    Args:
        x1: (3, 3) bearing vectors in view 1 (each row is [x, y, 1])
        x2: (3, 3) bearing vectors in view 2
        d1: (3,) predicted depths in view 1
        d2: (3,) predicted depths in view 2

    Returns:
        (18,) coefficient vector. For pair k in {0,1,2} corresponding to
        point pairs (0,1), (0,2), (1,2):
            coeffs[6k+0] = c_0  (alpha*beta^2 term)
            coeffs[6k+1] = c_1  (b1^2 term)
            coeffs[6k+2] = c_2  (alpha*beta term)
            coeffs[6k+3] = c_3  (alpha term)
            coeffs[6k+4] = c_4  (b1 term)
            coeffs[6k+5] = c_5  (constant term)
    """
    raise NotImplementedError(
        "Implement coefficient computation. See /app/FORMULATION.md."
    )


def solve_affine_depth(x1: np.ndarray, x2: np.ndarray,
                       d1: np.ndarray, d2: np.ndarray) -> List[AffineParams]:
    """Solve for affine depth correction parameters from 3 correspondences.

    Solves the polynomial system defined in FORMULATION.md. Requires the
    compiled native library at _LIB_PATH for eigenvalue computation.

    Args:
        x1: (3, 3) bearing vectors in view 1
        x2: (3, 3) bearing vectors in view 2
        d1: (3,) predicted depths in view 1
        d2: (3,) predicted depths in view 2

    Returns:
        List of AffineParams solutions filtered to physically valid results
        (real solutions with alpha > 0).
    """
    raise NotImplementedError(
        "Implement the polynomial system solver using the native library."
    )
