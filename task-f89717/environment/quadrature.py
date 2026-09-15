"""
Adaptive Gauss-Kronrod Quadrature Library

Implements the G7-K15 adaptive quadrature algorithm for numerical integration.
Features:
  - Gauss(7)-Kronrod(15) point rule for local estimation and error control
  - Globally adaptive interval subdivision with priority-queue scheduling
  - Wynn epsilon algorithm for sequence acceleration on partial sums
  - Semi-infinite interval support via variable transformation

Reference: Piessens, de Doncker-Kapenga, Uberhuber, Kahaner,
  "QUADPACK: A Subroutine Package for Automatic Integration",
  Springer-Verlag, 1983.
"""

import heapq
import math


# =====================================================================
# Gauss-Kronrod 15-point rule: abscissae and weights
# Reference interval: [-1, 1]
# Only positive abscissae stored; symmetry handles negatives.
# =====================================================================

# Kronrod abscissae (positive), ordered descending
_XGK = [
    0.9914553711208126,   # 0  (K-only)
    0.9491079123427585,   # 1  (G+K)
    0.8648644233597691,   # 2  (K-only)
    0.7415311855993945,   # 3  (G+K)
    0.5860872354676911,   # 4  (K-only)
    0.4058451513773972,   # 5  (G+K)
    0.2077849550078985,   # 6  (K-only)
    0.0000000000000000,   # 7  (G+K, center)
]

# Kronrod weights for the 15-point rule
_WGK = [
    0.02293532201052922,  # 0
    0.06309209262997855,  # 1
    0.16900472663926790,  # 2
    0.14065325971552592,  # 3
    0.10479001032225019,  # 4
    0.19035057806478540,  # 5
    0.20443294007529889,  # 6
    0.20948214108472783,  # 7
]

# Gauss weights for the embedded 7-point rule
# Correspond to _XGK at indices 1, 3, 5, 7
_WG = [
    0.12948496616887000,  # for _XGK[1]
    0.27970539148927000,  # for _XGK[3]
    0.38183005050512000,  # for _XGK[5]
    0.41795918367347000,  # for _XGK[7]
]


def _gk15(f, a, b):
    """
    Estimate integral of f over [a, b] using the G7-K15 rule.

    Returns
    -------
    result_k : Kronrod (15-pt) estimate
    result_g : Gauss (7-pt) estimate
    abserr   : |result_k - result_g|
    resabs   : approx of integral of |f|
    """
    center = 0.5 * (a + b)
    half_len = 0.5 * (b - a)

    f_center = f(center)

    result_k = _WGK[7] * f_center
    result_g = _WG[3] * f_center
    resabs = abs(result_k)

    gauss_map = {1: 0, 3: 1, 5: 2}

    for i in range(7):
        abscissa = half_len * _XGK[i]
        fv1 = f(center - abscissa)
        fv2 = f(center + abscissa)
        fsum = fv1 + fv2

        result_k += _WGK[i] * fsum
        resabs += _WGK[i] * (abs(fv1) + abs(fv2))

        if i in gauss_map:
            result_g += _WG[gauss_map[i]] * fsum

    result_k *= half_len
    result_g *= half_len
    resabs *= abs(half_len)

    abserr = abs(result_k - result_g)

    return result_k, result_g, abserr, resabs


def _wynn_epsilon(sums):
    """
    Wynn epsilon algorithm for convergence acceleration.

    Given a sequence of partial sums, returns an accelerated estimate
    of the limit using the epsilon-table recurrence:

        e_{k}^{(n)} = e_{k-2}^{(n+1)} + 1 / (e_{k-1}^{(n+1)} - e_{k-1}^{(n)})

    Parameters
    ----------
    sums : list of float
        Monotone or alternating sequence of partial sums.

    Returns
    -------
    float : best available estimate of the series limit.
    """
    n = len(sums)
    if n == 0:
        return 0.0
    if n <= 2:
        return sums[-1]

    # e[row][col]: col 0 = auxiliary zeros, col 1 = partial sums
    ncols = n + 1
    e = [[0.0] * ncols for _ in range(n)]

    for i in range(n):
        e[i][1] = sums[i]

    # Apply the recurrence across the table
    for k in range(2, ncols):
        for i in range(n - k + 1):
            delta = e[i + 1][k - 1] - e[i][k - 1]
            if abs(delta) < 1.0e-300:
                e[i][k] = 1.0e300
            else:
                e[i][k] = e[i][k - 2] + 1.0 / delta

    # In this shifted scheme, odd columns (3, 5, 7, ...) correspond
    # to even-subscript epsilon values which are the convergent estimates.
    best = sums[-1]
    for col in range(3, ncols, 2):
        val = e[0][col]
        if abs(val) < 1.0e299:
            best = val

    return best


def _adaptive_quad(f, a, b, epsabs, epsrel, limit):
    """
    Globally adaptive quadrature on [a, b].

    Uses a priority queue keyed by estimated local error to decide
    which subinterval to bisect next.  Stops when the accumulated
    error satisfies the tolerance or the subdivision limit is reached.

    Returns (result, abserr, neval, info) where info=0 means converged.
    """
    # Initial evaluation on whole interval
    res_k, res_g, err, resabs = _gk15(f, a, b)

    total_integral = res_k
    total_error = err
    neval = 15

    # Priority queue: (error_key, tiebreaker, left, right, local_result)
    # heapq is a min-heap; we store error directly for priority ordering.
    counter = 0
    heap = [(err, counter, a, b, res_k)]
    counter += 1

    running_sums = [total_integral]
    subdivisions = 0

    while subdivisions < limit:
        tol = max(epsabs, epsrel * abs(total_integral))
        if total_error <= tol:
            break

        if not heap:
            break

        # Pop the interval to refine next
        old_err, _, ia, ib, old_res = heapq.heappop(heap)

        mid = 0.5 * (ia + ib)

        # Evaluate on both halves
        r1, g1, e1, ra1 = _gk15(f, ia, mid)
        r2, g2, e2, ra2 = _gk15(f, mid, ib)
        neval += 30

        # Update totals: replace old contribution with new
        new_res = r1 + r2
        new_err = e1 + e2

        total_integral += (new_res - old_res)
        total_error += (new_err - old_err)
        total_error = max(total_error, 5e-16 * abs(total_integral))

        # Push refined subintervals back into the queue
        heapq.heappush(heap, (e1, counter, ia, mid, r1))
        counter += 1
        heapq.heappush(heap, (e2, counter, mid, ib, r2))
        counter += 1

        running_sums.append(total_integral)
        subdivisions += 1

    # Convergence acceleration on the sequence of running totals
    if len(running_sums) >= 4:
        accelerated = _wynn_epsilon(running_sums)
        if math.isfinite(accelerated):
            accel_diff = abs(accelerated - total_integral)
            if accel_diff < total_error:
                total_integral = accelerated

    info = 0 if total_error <= max(epsabs, epsrel * abs(total_integral)) else 1
    return total_integral, total_error, neval, info


def _make_semi_infinite_transform(f, a):
    """
    Map f on [a, inf) to g on [0, 1) via x = a + t/(1-t).

    The Jacobian of this substitution is dx/dt = 1 / (1 - t)^2.
    """
    def g(t):
        if t >= 1.0 - 1e-15:
            return 0.0
        omt = 1.0 - t
        x = a + t / omt
        # Jacobian of the transformation
        jac = 1.0 / omt
        return f(x) * jac

    return g


def _semi_inf(f, a, epsabs, epsrel, limit):
    """Integrate f on [a, inf) via transformation to [0, 1]."""
    g = _make_semi_infinite_transform(f, a)
    return _adaptive_quad(g, 0.0, 1.0, epsabs, epsrel, limit)


def integrate(f, a, b, epsabs=1.49e-8, epsrel=1.49e-8, limit=500):
    """
    Compute a definite integral using adaptive Gauss-Kronrod quadrature.

    Supports finite intervals [a, b] and semi-infinite intervals
    [a, inf), (-inf, b], or (-inf, inf).

    Parameters
    ----------
    f : callable
        Integrand f(x) -> float.
    a : float
        Lower limit (may be -math.inf).
    b : float
        Upper limit (may be math.inf).
    epsabs : float
        Absolute error tolerance.
    epsrel : float
        Relative error tolerance.
    limit : int
        Maximum number of adaptive subdivisions.

    Returns
    -------
    result : float
        Estimated integral value.
    abserr : float
        Estimated absolute error.
    neval : int
        Total integrand evaluations.
    converged : bool
        True if tolerance was met.
    """
    if a == b:
        return 0.0, 0.0, 0, True

    if b < a:
        r, e, n, c = integrate(f, b, a, epsabs, epsrel, limit)
        return -r, e, n, c

    # Handle infinite bounds
    if math.isinf(b) and b > 0:
        if math.isinf(a) and a < 0:
            # (-inf, inf): split at origin
            r1, e1, n1, i1 = _semi_inf(
                lambda x: f(-x), 0.0, epsabs / 2, epsrel, limit // 2
            )
            r2, e2, n2, i2 = _semi_inf(f, 0.0, epsabs / 2, epsrel, limit // 2)
            return r1 + r2, e1 + e2, n1 + n2, (i1 == 0 and i2 == 0)
        # [a, inf)
        r, e, n, i = _semi_inf(f, a, epsabs, epsrel, limit)
        return r, e, n, (i == 0)

    if math.isinf(a) and a < 0:
        # (-inf, b]
        r, e, n, i = _semi_inf(lambda x: f(-x), -b, epsabs, epsrel, limit)
        return r, e, n, (i == 0)

    # Finite interval [a, b]
    r, e, n, i = _adaptive_quad(f, a, b, epsabs, epsrel, limit)
    return r, e, n, (i == 0)
