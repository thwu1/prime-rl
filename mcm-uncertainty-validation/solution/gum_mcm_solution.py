#!/usr/bin/env python3
"""
JCGM 101:2008 Adaptive Monte Carlo Method implementation
for the comparison loss measurement uncertainty propagation.
"""

import numpy as np
import math


# ── Distribution sampling ────────────────────────────────────────────────


def sample_bivariate_gaussian(x1, x2, u1, u2, r, M, rng):
    """
    Sample M draws from bivariate Gaussian via Cholesky decomposition.
    """
    z = rng.standard_normal((2, M))
    sqrt_1mr2 = math.sqrt(max(1.0 - r * r, 0.0))
    xi1 = x1 + u1 * z[0]
    xi2 = x2 + r * u2 * z[0] + u2 * sqrt_1mr2 * z[1]
    return xi1, xi2


# ── Model ────────────────────────────────────────────────────────────────


def comparison_loss_model(xi1, xi2):
    """Comparison loss model: delta_Y = X1^2 + X2^2."""
    return xi1 * xi1 + xi2 * xi2


# ── Coverage intervals ───────────────────────────────────────────────────


def coverage_symmetric(sorted_vals, p):
    """Probabilistically symmetric coverage interval."""
    M = len(sorted_vals)
    lo_idx = max(0, int(math.ceil((1.0 - p) / 2.0 * M)) - 1)
    hi_idx = min(M - 1, int(math.ceil((1.0 + p) / 2.0 * M)) - 1)
    return float(sorted_vals[lo_idx]), float(sorted_vals[hi_idx])


def coverage_shortest(sorted_vals, p):
    """Shortest coverage interval containing at least p fraction of values."""
    M = len(sorted_vals)
    q = int(math.ceil(p * M))
    if q >= M:
        return float(sorted_vals[0]), float(sorted_vals[-1])

    widths = sorted_vals[q - 1:] - sorted_vals[: M - q + 1]
    best_i = int(np.argmin(widths))
    return float(sorted_vals[best_i]), float(sorted_vals[best_i + q - 1])


# ── Numerical tolerance ─────────────────────────────────────────────────


def numerical_tolerance(u_y, ndig):
    """Compute numerical tolerance delta per JCGM 101:2008 section 7.9.2."""
    if u_y <= 0:
        return 0.0
    log_val = math.log10(u_y)
    ell = math.floor(log_val) - ndig + 1
    return 0.5 * (10.0 ** ell)


# ── Adaptive MCM ────────────────────────────────────────────────────────


def adaptive_mcm(x1, x2, u1, u2, r, p=0.95, ndig=1,
                 tolerance_factor=1.0, seed=None, max_batches=500,
                 return_convergence=False):
    """
    Adaptive Monte Carlo procedure per JCGM 101:2008 section 7.9.4.
    """
    rng = np.random.default_rng(seed)

    J = math.ceil(100.0 / (1.0 - p))
    M = max(J, 10000)

    all_values = []
    batch_y = []
    batch_u = []
    batch_lo = []
    batch_hi = []

    convergence_M = []
    convergence_y = []
    convergence_u = []

    h = 0
    while True:
        xi1, xi2 = sample_bivariate_gaussian(x1, x2, u1, u2, r, M, rng)
        dy = comparison_loss_model(xi1, xi2)
        all_values.append(dy)

        sorted_batch = np.sort(dy)
        y_h = float(np.mean(dy))
        u_y_h = float(np.std(dy, ddof=0))
        lo_h, hi_h = coverage_shortest(sorted_batch, p)

        batch_y.append(y_h)
        batch_u.append(u_y_h)
        batch_lo.append(lo_h)
        batch_hi.append(hi_h)
        h += 1

        # Compute cumulative statistics
        all_arr = np.concatenate(all_values)
        u_y_all = float(np.std(all_arr, ddof=0))

        if return_convergence:
            convergence_M.append(len(all_arr))
            convergence_y.append(float(np.mean(all_arr)))
            convergence_u.append(u_y_all)

        if h < 2:
            continue

        delta = numerical_tolerance(u_y_all, ndig) * tolerance_factor

        if delta <= 0:
            if h >= max_batches:
                break
            continue

        n = h
        s_y = float(np.std(batch_y, ddof=1)) / math.sqrt(n)
        s_u = float(np.std(batch_u, ddof=1)) / math.sqrt(n)
        s_lo = float(np.std(batch_lo, ddof=1)) / math.sqrt(n)
        s_hi = float(np.std(batch_hi, ddof=1)) / math.sqrt(n)

        if all(2.0 * s < delta for s in [s_y, s_u, s_lo, s_hi]):
            break

        if h >= max_batches:
            break

    all_arr = np.concatenate(all_values)
    all_sorted = np.sort(all_arr)

    y = float(np.mean(all_arr))
    u_y = float(np.std(all_arr, ddof=0))
    shortest = coverage_shortest(all_sorted, p)
    symmetric = coverage_symmetric(all_sorted, p)

    result = {
        "y": y,
        "u_y": u_y,
        "shortest_95": list(shortest),
        "symmetric_95": list(symmetric),
        "M_trials": int(len(all_arr)),
    }

    if return_convergence:
        result["_convergence"] = {
            "M": convergence_M,
            "y": convergence_y,
            "u_y": convergence_u,
        }

    return result


# ── GUM uncertainty framework ───────────────────────────────────────────


def guf1_comparison_loss(x1, x2, u1, u2, r, p=0.95):
    """GUF with first-order terms for delta_Y = X1^2 + X2^2."""
    y = x1 * x1 + x2 * x2

    c1 = 2.0 * x1
    c2 = 2.0 * x2

    u_y_sq = (c1 * c1 * u1 * u1
              + c2 * c2 * u2 * u2
              + 2.0 * c1 * c2 * r * u1 * u2)
    u_y = math.sqrt(max(u_y_sq, 0.0))

    k = 1.959964
    coverage = [y - k * u_y, y + k * u_y]

    return {"y": y, "u_y": u_y, "coverage_95": coverage}


def guf2_comparison_loss(x1, x2, u1, u2, r, p=0.95):
    """GUF with second-order terms for delta_Y = X1^2 + X2^2."""
    cov_12 = r * u1 * u2

    # Corrected estimate
    y = x1 * x1 + x2 * x2 + u1 * u1 + u2 * u2

    # First-order variance
    c1 = 2.0 * x1
    c2 = 2.0 * x2
    u_y_sq_1 = (c1 * c1 * u1 * u1
                + c2 * c2 * u2 * u2
                + 2.0 * c1 * c2 * cov_12)

    # Second-order variance addition
    u_y_sq_2 = 0.5 * (4.0 * u1 ** 4
                       + 4.0 * cov_12 ** 2
                       + 4.0 * cov_12 ** 2
                       + 4.0 * u2 ** 4)

    u_y = math.sqrt(max(u_y_sq_1 + u_y_sq_2, 0.0))

    k = 1.959964
    coverage = [y - k * u_y, y + k * u_y]

    return {"y": y, "u_y": u_y, "coverage_95": coverage}


# ── Validation ───────────────────────────────────────────────────────────


def validate_guf(guf_result, mcm_result, ndig=1):
    """Validation procedure per JCGM 101:2008 section 8.1."""
    u_y_mcm = mcm_result["u_y"]
    delta = numerical_tolerance(u_y_mcm, ndig)

    guf_lo, guf_hi = guf_result["coverage_95"]
    mcm_lo, mcm_hi = mcm_result["shortest_95"]

    d_low = abs(guf_lo - mcm_lo)
    d_high = abs(guf_hi - mcm_hi)

    validated = bool(d_low <= delta and d_high <= delta)

    return {
        "ndig": ndig,
        "delta": delta,
        "d_low": d_low,
        "d_high": d_high,
        "validated": validated,
    }
