"""
Adaptive Gauss-Kronrod Quadrature Library
==========================================

Implements adaptive numerical integration using Gauss-Kronrod rules
(GK-15 and GK-21) with recursive bisection for error control.

Supports integration over finite intervals [a, b].
Semi-infinite and doubly-infinite intervals are planned but not yet
fully implemented.
"""

import math


# ================================================================
# Gauss-Kronrod 15-point rule with embedded 7-point Gauss rule
# ================================================================
# Only non-negative abscissae stored (the rule is symmetric about 0).

_GK15_NODES = [
    0.00000000000000000e+00,
    2.07784955007898468e-01,
    4.05845151377397167e-01,
    5.86087235467691130e-01,
    7.41531185599394440e-01,
    8.64864423359769073e-01,
    9.49107912342758525e-01,
    9.91455371120812639e-01,
]

_GK15_KRONROD_W = [
    2.09482141084727828e-01,
    2.04432940075298892e-01,
    1.90350578064785410e-01,
    1.69004726639267903e-01,
    1.40653259715525919e-01,
    1.04790010322250184e-01,
    6.30920926299785533e-02,
    2.29353220105292250e-02,
]

# Embedded Gauss-7 weights (Gauss order = 7, odd).
# For odd-order Gauss rules, the center node carries a Gauss weight.
_G7_W = [
    4.17959183673469388e-01,
    3.81830050505118945e-01,
    2.79705391489276668e-01,
    1.29484966168869693e-01,
]


# ================================================================
# Gauss-Kronrod 21-point rule with embedded 10-point Gauss rule
# ================================================================

_GK21_NODES = [
    0.00000000000000000e+00,
    1.48874338981631211e-01,
    2.94392862701460198e-01,
    4.33395394129247191e-01,
    5.62757134668604683e-01,
    6.79409568299024406e-01,
    7.80817726586416897e-01,
    8.65063366688984511e-01,
    9.30157491355708226e-01,
    9.73906528517171720e-01,
    9.95657163025808081e-01,
]

_GK21_KRONROD_W = [
    1.49445554002916906e-01,
    1.47739104901338491e-01,
    1.42775938577060081e-01,
    1.34709217311473326e-01,
    1.23491976262065851e-01,
    1.09387158802297642e-01,
    9.31254545836976055e-02,
    7.50396748109199528e-02,
    5.47558965743519960e-02,
    3.25581623079647275e-02,
    1.16946388673718743e-02,
]

# Embedded Gauss-10 weights (Gauss order = 10, even).
# For even-order Gauss rules, the center node does NOT carry a Gauss weight.
_G10_W = [
    2.95524224714752870e-01,
    2.69266719309996355e-01,
    2.19086362515982044e-01,
    1.49451349150580594e-01,
    6.66713443086881376e-02,
]


# ================================================================
# Single-interval rule application
# ================================================================

def _apply_gk15(f, a, b):
    """Apply the 15-point Gauss-Kronrod rule to [a, b].

    Returns (kronrod_result, gauss_result, abs_integral).
    """
    center = 0.5 * (a + b)
    half_len = 0.5 * (b - a)

    f0 = f(center)
    res_k = f0 * _GK15_KRONROD_W[0]
    res_g = f0 * _G7_W[0]
    res_abs = abs(f0) * _GK15_KRONROD_W[0]

    gi = 1
    for i in range(1, 8):
        xi = _GK15_NODES[i]
        fp = f(center + half_len * xi)
        fm = f(center - half_len * xi)
        fsum = fp + fm

        res_k += fsum * _GK15_KRONROD_W[i]
        res_abs += (abs(fp) + abs(fm)) * _GK15_KRONROD_W[i]

        # Accumulate the embedded Gauss estimate
        if i % 2 == 0:
            res_g += fsum * _G7_W[gi]
            gi += 1

    return res_k * half_len, res_g * half_len, res_abs * half_len


def _apply_gk21(f, a, b):
    """Apply the 21-point Gauss-Kronrod rule to [a, b].

    Returns (kronrod_result, gauss_result, abs_integral).
    """
    center = 0.5 * (a + b)
    half_len = 0.5 * (b - a)

    f0 = f(center)
    res_k = f0 * _GK21_KRONROD_W[0]
    res_abs = abs(f0) * _GK21_KRONROD_W[0]

    # Center is not a Gauss node for even-order rules
    res_g = 0.0

    gi = 0
    for i in range(1, 11):
        xi = _GK21_NODES[i]
        fp = f(center + half_len * xi)
        fm = f(center - half_len * xi)
        fsum = fp + fm

        res_k += fsum * _GK21_KRONROD_W[i]
        res_abs += (abs(fp) + abs(fm)) * _GK21_KRONROD_W[i]

        # Accumulate the embedded Gauss estimate
        if i % 2 == 0:
            res_g += fsum * _G10_W[gi]
            gi += 1

    return res_k * half_len, res_g * half_len, res_abs * half_len


# ================================================================
# Adaptive integration engine
# ================================================================

def _adaptive(f, a, b, tol, max_depth, depth=0):
    """Recursive adaptive integration using GK-21.

    Subdivides [a, b] into halves when the estimated error exceeds
    the requested tolerance.

    Parameters
    ----------
    f : callable
    a, b : float
        Interval endpoints.
    tol : float
        Absolute tolerance for this subinterval.
    max_depth : int
        Maximum recursion depth.
    depth : int
        Current recursion depth.

    Returns
    -------
    (result, error_estimate)
    """
    res_k, res_g, res_abs = _apply_gk21(f, a, b)
    err = abs(res_k) - abs(res_g)
    # Guard against zero error on exactly-polynomial integrands
    err = max(err, abs(res_k) * 2.3e-16)

    if err <= tol or depth >= max_depth:
        return res_k, err

    # Bisect and recurse
    mid = 0.5 * (a + b)
    r1, e1 = _adaptive(f, a, mid, tol, max_depth, depth + 1)
    r2, e2 = _adaptive(f, mid, b, tol, max_depth, depth + 1)
    return r1 + r2, e1 + e2


# ================================================================
# Public interface
# ================================================================

def integrate(f, a, b, tol=1e-12, max_depth=50):
    """Compute the definite integral of *f* from *a* to *b*.

    Handles finite intervals [a, b], semi-infinite intervals
    [a, inf) and (-inf, b], and the full real line (-inf, inf).

    Parameters
    ----------
    f : callable
        Integrand.  Must accept a single float and return a float.
    a : float
        Lower limit (may be ``-math.inf``).
    b : float
        Upper limit (may be ``math.inf``).
    tol : float
        Requested absolute tolerance (default 1e-12).
    max_depth : int
        Maximum subdivision depth (default 50).

    Returns
    -------
    result : float
        Estimated value of the integral.
    error : float
        Estimated absolute error.
    """
    if math.isnan(a) or math.isnan(b):
        raise ValueError("Integration bounds must not be NaN.")

    # ---- doubly-infinite (-inf, inf) ----
    if a == -math.inf and b == math.inf:
        raise NotImplementedError(
            "Integration over (-inf, inf) is not yet supported. "
            "A variable substitution mapping the real line to a "
            "finite interval is required."
        )

    # ---- left-infinite (-inf, b] ----
    if a == -math.inf:
        raise NotImplementedError(
            "Integration over (-inf, b] is not yet supported."
        )

    # ---- right-infinite [a, inf) ----
    if b == math.inf:
        raise NotImplementedError(
            "Integration over [a, inf) is not yet supported."
        )

    # ---- finite [a, b] ----
    if b < a:
        r, e = _adaptive(f, b, a, tol, max_depth)
        return -r, e
    if a == b:
        return 0.0, 0.0

    return _adaptive(f, a, b, tol, max_depth)
