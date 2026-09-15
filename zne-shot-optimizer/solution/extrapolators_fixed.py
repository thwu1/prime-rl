"""
Extrapolation methods for quantum error mitigation — FIXED.

Fixes applied:
1. Lagrange coefficient formula: corrected numerator/denominator order
2. Exponential extrapolation: subtracts asymptote before log-space fitting
"""


import math


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
    Richardson extrapolation: R = sum_j gamma_j * f(lambda_j).
    """
    coeffs = compute_lagrange_coefficients(scale_factors)
    return sum(c * m for c, m in zip(coeffs, measurements))


def exponential_extrapolate(scale_factors, measurements, asymptote=0.0):
    """
    Exponential extrapolation via weighted least squares in log-space.

    Fits f(lambda) = a + b * exp(-c * lambda) and returns f(0) = a + b.
    Subtracts asymptote before log-space fitting.
    """
    g_values = [m - asymptote for m in measurements]

    valid = [(sf, g) for sf, g in zip(scale_factors, g_values)
             if abs(g) > 1e-15]
    if len(valid) < 2:
        return richardson_extrapolate(scale_factors, measurements)

    sign = 1.0 if valid[0][1] > 0 else -1.0
    consistent = [(sf, abs(g)) for sf, g in valid if g * sign > 1e-15]

    if len(consistent) < 2:
        return richardson_extrapolate(scale_factors, measurements)

    x_vals = [p[0] for p in consistent]
    abs_vals = [p[1] for p in consistent]
    log_vals = [math.log(v) for v in abs_vals]
    weights = list(abs_vals)

    sw = sum(weights)
    swx = sum(w * x for w, x in zip(weights, x_vals))
    swy = sum(w * y for w, y in zip(weights, log_vals))
    swxx = sum(w * x * x for w, x in zip(weights, x_vals))
    swxy = sum(w * x * y for w, x, y in zip(weights, x_vals, log_vals))

    det = sw * swxx - swx * swx
    if abs(det) < 1e-30:
        return richardson_extrapolate(scale_factors, measurements)

    log_b = (swxx * swy - swx * swxy) / det
    b = sign * math.exp(log_b)

    return asymptote + b


def linear_extrapolate(scale_factors, measurements):
    """
    Linear least-squares extrapolation to x=0.
    """
    n = len(scale_factors)
    sx = sum(scale_factors)
    sy = sum(measurements)
    sxx = sum(x ** 2 for x in scale_factors)
    sxy = sum(x * y for x, y in zip(scale_factors, measurements))
    det = n * sxx - sx ** 2
    if abs(det) < 1e-30:
        return sy / n
    return (sxx * sy - sx * sxy) / det
