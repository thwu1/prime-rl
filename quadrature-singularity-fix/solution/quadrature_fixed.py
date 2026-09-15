"""
Adaptive Gauss-Kronrod Quadrature Library — FIXED VERSION
==========================================================

Fixes applied:
1. _apply_gk21: Gauss-10 node selection corrected from even to odd
   Kronrod indices (i % 2 == 1, not i % 2 == 0).
2. _adaptive: Error estimation changed from abs(res_k)-abs(res_g)
   to abs(res_k - res_g).
3. integrate: Domain transformations implemented for semi-infinite
   [a, inf), left-infinite (-inf, b], and doubly-infinite (-inf, inf).
"""

import math


# ================================================================
# Gauss-Kronrod 15-point rule with embedded 7-point Gauss rule
# ================================================================

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

        if i % 2 == 0:
            res_g += fsum * _G7_W[gi]
            gi += 1

    return res_k * half_len, res_g * half_len, res_abs * half_len


def _apply_gk21(f, a, b):
    center = 0.5 * (a + b)
    half_len = 0.5 * (b - a)

    f0 = f(center)
    res_k = f0 * _GK21_KRONROD_W[0]
    res_abs = abs(f0) * _GK21_KRONROD_W[0]
    res_g = 0.0

    gi = 0
    for i in range(1, 11):
        xi = _GK21_NODES[i]
        fp = f(center + half_len * xi)
        fm = f(center - half_len * xi)
        fsum = fp + fm

        res_k += fsum * _GK21_KRONROD_W[i]
        res_abs += (abs(fp) + abs(fm)) * _GK21_KRONROD_W[i]

        # FIX: Gauss-10 nodes are at ODD Kronrod indices (1,3,5,7,9)
        # because gauss_order=10 is even.
        if i % 2 == 1:
            res_g += fsum * _G10_W[gi]
            gi += 1

    return res_k * half_len, res_g * half_len, res_abs * half_len


# ================================================================
# Adaptive integration engine
# ================================================================

def _adaptive(f, a, b, tol, max_depth, depth=0):
    res_k, res_g, res_abs = _apply_gk21(f, a, b)
    # FIX: use abs(res_k - res_g), not abs(res_k) - abs(res_g)
    err = abs(res_k - res_g)
    err = max(err, abs(res_k) * 2.3e-16)

    if err <= tol or depth >= max_depth:
        return res_k, err

    mid = 0.5 * (a + b)
    r1, e1 = _adaptive(f, a, mid, tol, max_depth, depth + 1)
    r2, e2 = _adaptive(f, mid, b, tol, max_depth, depth + 1)
    return r1 + r2, e1 + e2


# ================================================================
# Domain transformation helpers
# ================================================================

def _integrate_right_infinite(f, a, tol, max_depth):
    """Integrate f over [a, inf).

    Splits at a finite point to handle potential endpoint
    singularities at x = a, then uses a variable substitution
    for the tail [c, inf) -> [-1, 1].
    """
    c = a + max(1.0, abs(a)) if a != 0 else 1.0
    half_tol = tol / 2.0

    # Finite part [a, c]: may have endpoint singularity at x = a
    r1, e1 = _adaptive(f, a, c, half_tol, max_depth)

    # Tail [c, inf) via substitution z = 1/(t+1), x = 2z + c - 1
    def g(t):
        s = t + 1.0
        if s < 1e-15:
            return 0.0
        z = 1.0 / s
        x = 2.0 * z + c - 1.0
        try:
            val = f(x)
        except (ValueError, OverflowError, ZeroDivisionError):
            return 0.0
        result = val * z * z
        if not math.isfinite(result):
            return 0.0
        return result

    r2, e2 = _adaptive(g, -1.0, 1.0, half_tol, max_depth)
    return r1 + 2.0 * r2, e1 + 2.0 * e2


def _integrate_left_infinite(f, b, tol, max_depth):
    """Integrate f over (-inf, b].

    Uses reflection: int_{-inf}^{b} f(x)dx = int_{-b}^{inf} f(-u+2b-... )
    Implemented via splitting analogous to the right-infinite case.
    """
    c = b - max(1.0, abs(b)) if b != 0 else -1.0
    half_tol = tol / 2.0

    # Finite part [c, b]
    r1, e1 = _adaptive(f, c, b, half_tol, max_depth)

    # Tail (-inf, c] via substitution: z = 1/(t+1), x = c - (2z - 1) = c + 1 - 2z
    def g(t):
        s = t + 1.0
        if s < 1e-15:
            return 0.0
        z = 1.0 / s
        x = c + 1.0 - 2.0 * z
        try:
            val = f(x)
        except (ValueError, OverflowError, ZeroDivisionError):
            return 0.0
        result = val * z * z
        if not math.isfinite(result):
            return 0.0
        return result

    r2, e2 = _adaptive(g, -1.0, 1.0, half_tol, max_depth)
    return r1 + 2.0 * r2, e1 + 2.0 * e2


def _integrate_doubly_infinite(f, tol, max_depth):
    """Integrate f over (-inf, inf).

    Uses substitution x = t / (1 - t^2), dx = (1 + t^2) / (1 - t^2)^2 dt,
    mapping (-inf, inf) to (-1, 1).
    """
    def g(t):
        t2 = t * t
        denom = 1.0 - t2
        if denom <= 0.0:
            return 0.0
        inv = 1.0 / denom
        x = t * inv
        w = (1.0 + t2) * inv * inv
        try:
            val = f(x)
        except (ValueError, OverflowError, ZeroDivisionError):
            return 0.0
        result = val * w
        if not math.isfinite(result):
            return 0.0
        return result

    return _adaptive(g, -1.0, 1.0, tol, max_depth)


# ================================================================
# Public interface
# ================================================================

def integrate(f, a, b, tol=1e-12, max_depth=50):
    if math.isnan(a) or math.isnan(b):
        raise ValueError("Integration bounds must not be NaN.")

    # ---- doubly-infinite (-inf, inf) ----
    if a == -math.inf and b == math.inf:
        return _integrate_doubly_infinite(f, tol, max_depth)

    # ---- left-infinite (-inf, b] ----
    if a == -math.inf:
        return _integrate_left_infinite(f, b, tol, max_depth)

    # ---- right-infinite [a, inf) ----
    if b == math.inf:
        return _integrate_right_infinite(f, a, tol, max_depth)

    # ---- finite [a, b] ----
    if b < a:
        r, e = _adaptive(f, b, a, tol, max_depth)
        return -r, e
    if a == b:
        return 0.0, 0.0

    return _adaptive(f, a, b, tol, max_depth)
