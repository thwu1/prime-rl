"""
Zero-Noise Extrapolation (ZNE) Optimizer — Full Solution

Implements Richardson extrapolation with optimal shot allocation,
exponential extrapolation via WLS in log-space, and scale factor
optimization for quantum error mitigation.
"""


import math
from itertools import combinations


def compute_lagrange_coefficients(scale_factors):
    """
    Compute Lagrange interpolation coefficients for extrapolation to x=0.

    gamma_j = L_j(0) = prod_{k != j} (0 - lambda_k) / (lambda_j - lambda_k)
    """
    n = len(scale_factors)
    coefficients = []
    for j in range(n):
        coeff = 1.0
        for k in range(n):
            if k != j:
                coeff *= (0.0 - scale_factors[k]) / (scale_factors[j] - scale_factors[k])
        coefficients.append(coeff)
    return coefficients


def richardson_extrapolate(scale_factors, measurements):
    """
    Perform Richardson extrapolation: R = sum_j gamma_j * f(lambda_j).
    """
    coeffs = compute_lagrange_coefficients(scale_factors)
    return sum(c * m for c, m in zip(coeffs, measurements))


def optimal_shot_allocation(scale_factors, total_budget):
    """
    Variance-minimizing integer shot allocation using largest-remainder method.

    N_j = M * |gamma_j| / Gamma, rounded to integers summing to M.
    """
    coeffs = compute_lagrange_coefficients(scale_factors)
    abs_coeffs = [abs(c) for c in coeffs]
    gamma_sum = sum(abs_coeffs)

    # Compute ideal (continuous) allocations
    ideal = [total_budget * ac / gamma_sum for ac in abs_coeffs]

    # Floor each allocation
    floors = [int(math.floor(x)) for x in ideal]

    # Compute fractional remainders with index
    remainders = [(ideal[i] - floors[i], i) for i in range(len(ideal))]
    # Sort by remainder descending, break ties by larger |gamma| first
    remainders.sort(key=lambda x: (-x[0], -abs_coeffs[x[1]]))

    # Distribute the deficit
    deficit = total_budget - sum(floors)
    for i in range(deficit):
        floors[remainders[i][1]] += 1

    return floors


def richardson_variance_uniform(scale_factors, total_budget):
    """
    Variance with uniform allocation: Var = (n / M) * sum gamma_j^2.
    """
    coeffs = compute_lagrange_coefficients(scale_factors)
    n = len(scale_factors)
    return (n / total_budget) * sum(c ** 2 for c in coeffs)


def richardson_variance_optimal(scale_factors, total_budget):
    """
    Variance with optimal allocation: Var = Gamma^2 / M.
    """
    coeffs = compute_lagrange_coefficients(scale_factors)
    gamma = sum(abs(c) for c in coeffs)
    return gamma ** 2 / total_budget


def exponential_extrapolate(scale_factors, measurements, asymptote=0.0):
    """
    Exponential extrapolation via WLS in log-space.

    Fits f(lambda) = a + b * exp(-c * lambda) by:
    1. Subtracting asymptote: g = f - a
    2. Tracking sign of g values
    3. Fitting log|g| = log|b| - c*lambda with WLS (weights = |g|)
    4. Recovering f(0) = a + b
    """
    g_values = [m - asymptote for m in measurements]

    # Filter valid points (nonzero g)
    valid_indices = [i for i, g in enumerate(g_values) if abs(g) > 1e-15]
    if len(valid_indices) < 2:
        # Fallback to Richardson
        return richardson_extrapolate(scale_factors, measurements)

    # Determine consistent sign
    sign = 1.0 if g_values[valid_indices[0]] > 0 else -1.0

    # Keep only points with consistent sign
    consistent = [
        (scale_factors[i], abs(g_values[i]))
        for i in valid_indices
        if g_values[i] * sign > 1e-15
    ]

    if len(consistent) < 2:
        return richardson_extrapolate(scale_factors, measurements)

    x_vals = [p[0] for p in consistent]
    abs_g = [p[1] for p in consistent]
    y_vals = [math.log(ag) for ag in abs_g]
    weights = list(abs_g)  # w_j = |g(lambda_j)|

    # Weighted least squares: y = beta_0 + beta_1 * x
    # where y = log|g|, beta_0 = log|b|, beta_1 = -c
    sw = sum(weights)
    swx = sum(w * x for w, x in zip(weights, x_vals))
    swy = sum(w * y for w, y in zip(weights, y_vals))
    swxx = sum(w * x * x for w, x in zip(weights, x_vals))
    swxy = sum(w * x * y for w, x, y in zip(weights, x_vals, y_vals))

    det = sw * swxx - swx * swx
    if abs(det) < 1e-30:
        return richardson_extrapolate(scale_factors, measurements)

    log_b = (swxx * swy - swx * swxy) / det
    # neg_c = (sw * swxy - swx * swy) / det  # not needed for f(0)

    # b = sign * exp(log|b|)
    b = sign * math.exp(log_b)

    # f(0) = asymptote + b
    return asymptote + b


def find_optimal_scale_factors(candidates, subset_size):
    """
    Exhaustive search over C(n,k) subsets to minimize Gamma = sum |gamma_j|.
    """
    best_gamma = float("inf")
    best_factors = None

    for combo in combinations(candidates, subset_size):
        factors = list(combo)
        coeffs = compute_lagrange_coefficients(factors)
        gamma = sum(abs(c) for c in coeffs)
        if gamma < best_gamma - 1e-15:
            best_gamma = gamma
            best_factors = sorted(factors)

    return best_factors, best_gamma
