"""
Bézier curve arc length computation engine — solution implementation.
"""

import math
import ctypes
import os

from bezier import Point, QuadBez, CubicBez
from coefficients import GAUSS_LEGENDRE

# Load the C shared library
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libquadrature.so')
_lib = ctypes.CDLL(_lib_path)

# Set up function signatures
_lib.cubic_arclen_gl.restype = ctypes.c_double
_lib.cubic_arclen_gl.argtypes = [
    ctypes.POINTER(ctypes.c_double),  # px[4]
    ctypes.POINTER(ctypes.c_double),  # py[4]
    ctypes.POINTER(ctypes.c_double),  # nodes[]
    ctypes.POINTER(ctypes.c_double),  # weights[]
    ctypes.c_int,                     # n
]

_lib.cubic_arclen_gl_interval.restype = ctypes.c_double
_lib.cubic_arclen_gl_interval.argtypes = [
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.c_int,
    ctypes.c_double,
    ctypes.c_double,
]


def _make_c_array(values):
    n = len(values)
    arr = (ctypes.c_double * n)(*values)
    return arr


def quad_arclen_analytical(q):
    """
    Compute arc length of a quadratic Bézier using the closed-form formula.
    Falls back to GL quadrature for near-linear curves.
    """
    a = q.p0 - 2.0 * q.p1 + q.p2  # second derivative / 2
    b = q.p1 - q.p0                # first derivative at t=0 / 2

    A = a.norm_sq()
    B = 2.0 * a.dot(b)
    C = b.norm_sq()

    if C < 1e-30:
        return 0.0

    # Near-linear: fall back to GL quadrature
    if A < 1e-12 * C:
        return _quad_arclen_gl(q, 24)

    disc = 4.0 * A * C - B * B
    if disc <= 0:
        return _quad_arclen_gl(q, 24)

    sqA = math.sqrt(A)
    sqrt_disc = math.sqrt(disc)

    # Evaluate the antiderivative at t=1 and t=0
    # F(t) = [(2At + B) * sqrt(At^2 + Bt + C)] / (4A)
    #       + [disc / (8 * A^(3/2))] * arsinh((2At + B) / sqrt(disc))

    def antideriv(t):
        val_under = A * t * t + B * t + C
        if val_under < 0:
            val_under = 0.0
        sqrt_val = math.sqrt(val_under)
        linear = (2.0 * A * t + B)
        term1 = linear * sqrt_val / (4.0 * A)
        arg = linear / sqrt_disc
        term2 = (disc / (8.0 * A * sqA)) * math.asinh(arg)
        return term1 + term2

    result = 2.0 * (antideriv(1.0) - antideriv(0.0))
    return result


def _quad_arclen_gl(q, order=24):
    """GL quadrature fallback for quadratic Bézier arc length."""
    gl = GAUSS_LEGENDRE[order]
    total = 0.0
    for node, weight in zip(gl["nodes"], gl["weights"]):
        d = q.deriv_at(node)
        total += weight * d.norm()
    return total


def cubic_arclen_gl(c, order=16):
    """
    Compute arc length of a cubic Bézier using GL quadrature via C library.
    """
    gl = GAUSS_LEGENDRE[order]
    px = _make_c_array(c.control_points_x())
    py = _make_c_array(c.control_points_y())
    nodes = _make_c_array(gl["nodes"])
    weights = _make_c_array(gl["weights"])
    return _lib.cubic_arclen_gl(px, py, nodes, weights, order)


def estimate_cubic_error(c):
    """
    Conservative error bound for GL-16 quadrature on a cubic Bézier.

    Uses the Gravesen-inspired approach: the error relates to the
    difference between the control polygon perimeter and the chord
    length, scaled by a factor based on the second derivative integral.
    """
    lp = c.polygon_len
    lc = c.chord_len

    diff = lp - lc
    if diff < 1e-30:
        return 0.0

    # Second derivative terms
    d2_0 = c.p2 - 2.0 * c.p1 + c.p0
    d2_1 = c.p3 - 2.0 * c.p2 + c.p1
    delta = d2_1 - d2_0

    # Integral of squared second derivative norm over [0,1]
    int_d2_sq = delta.norm_sq() / 3.0 + delta.dot(d2_0) + d2_0.norm_sq()

    # The error bound combines the polygon/chord difference with the
    # second derivative integral. The constant factor is chosen to be
    # conservative (overestimate) for GL-16 quadrature.
    # For GL-n, the error scales as O(h^(2n)) where h relates to
    # the curve's non-linearity. We use a practical heuristic:
    err = 0.05 * diff * diff + 1e-6 * int_d2_sq * diff
    if err < 1e-20:
        err = diff * diff

    return err


def arclen_adaptive(curve, tolerance=1e-8, max_depth=20):
    """
    Adaptive arc length computation using recursive subdivision.
    """
    if isinstance(curve, QuadBez):
        return quad_arclen_analytical(curve)

    return _adaptive_cubic(curve, tolerance, max_depth)


def _adaptive_cubic(c, tolerance, depth):
    """Recursive adaptive GL quadrature for cubic Bézier arc length."""
    est_err = estimate_cubic_error(c)

    if est_err < tolerance or depth <= 0:
        return cubic_arclen_gl(c, order=16)

    left, right = c.subdivide(0.5)
    return (_adaptive_cubic(left, tolerance / 2.0, depth - 1) +
            _adaptive_cubic(right, tolerance / 2.0, depth - 1))


def arclen(curve, tolerance=1e-8):
    """
    Main entry point: compute arc length of any Bézier curve.
    """
    if isinstance(curve, QuadBez):
        return quad_arclen_analytical(curve)
    elif isinstance(curve, CubicBez):
        return arclen_adaptive(curve, tolerance=tolerance)
    else:
        raise TypeError(f"Unsupported curve type: {type(curve)}")
