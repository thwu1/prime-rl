"""Zero-noise extrapolation methods for quantum error mitigation.

"""
import numpy as np
from scipy.optimize import curve_fit


def richardson_extrapolate(scale_factors, values):
    """Compute the zero-noise limit using Richardson extrapolation.

    Uses the Lagrange interpolation formula evaluated at x=0:
        result = sum_i w_i * values[i]
    where w_i = prod_{j!=i} (0 - sf_j) / (sf_i - sf_j)

    Args:
        scale_factors: list of noise scale factors.
        values: list of measured expectation values at each scale factor.

    Returns:
        float: extrapolated zero-noise value.
    """
    sf = list(scale_factors)
    vals = list(values)
    n = len(sf)

    result = 0.0
    for i in range(n):
        weight = 1.0
        for j in range(n):
            if j != i:
                weight *= (0.0 - sf[j]) / (sf[i] - sf[j])
        result += weight * vals[i]

    return float(result)


def poly_extrapolate(scale_factors, values, order):
    """Fit a polynomial of given order and extrapolate to zero.

    Args:
        scale_factors: list of noise scale factors.
        values: list of measured expectation values.
        order: polynomial degree.

    Returns:
        float: polynomial value at x=0.
    """
    coeffs = np.polyfit(scale_factors, values, order)
    return float(np.polyval(coeffs, 0.0))


def exponential_extrapolate(scale_factors, values, asymptote=None):
    """Fit y = a + b * exp(c * x) and extrapolate to x=0.

    For depolarizing noise, the expectation value decays exponentially
    toward the maximally mixed state value, making this the physically
    motivated model.

    Args:
        scale_factors: list of noise scale factors.
        values: list of measured expectation values.
        asymptote: if provided, fix a to this value and fit only b, c.

    Returns:
        float: a + b (value at x=0).
    """
    sf = np.array(scale_factors, dtype=float)
    vals = np.array(values, dtype=float)

    if asymptote is not None:
        a_fixed = float(asymptote)

        def model_fixed(x, b, c):
            return a_fixed + b * np.exp(c * x)

        # Initialize via log-linear fit on shifted data
        shifted = vals - a_fixed
        if np.all(shifted > 1e-15):
            log_shifted = np.log(shifted)
            slope, intercept = np.polyfit(sf, log_shifted, 1)
            b0 = np.exp(intercept)
            c0 = slope
        else:
            b0 = max(shifted[0], 0.01)
            c0 = -0.1

        try:
            popt, _ = curve_fit(
                model_fixed, sf, vals, p0=[b0, c0], maxfev=10000
            )
            return float(a_fixed + popt[0])
        except RuntimeError:
            return float(vals[0])

    else:
        # Estimate initial asymptote from data
        a0 = min(vals) - 0.1 * abs(max(vals) - min(vals))
        shifted = vals - a0
        if np.all(shifted > 1e-15):
            log_shifted = np.log(shifted)
            slope, intercept = np.polyfit(sf, log_shifted, 1)
            b0 = np.exp(intercept)
            c0 = slope
        else:
            b0 = max(vals[0] - a0, 0.01)
            c0 = -0.1

        def model_full(x, a, b, c):
            return a + b * np.exp(c * x)

        try:
            popt, _ = curve_fit(
                model_full, sf, vals, p0=[a0, b0, c0], maxfev=10000
            )
            return float(popt[0] + popt[1])  # a + b * exp(0) = a + b
        except RuntimeError:
            # Fallback: use Richardson if exponential fit fails
            return richardson_extrapolate(
                list(scale_factors), list(values)
            )
