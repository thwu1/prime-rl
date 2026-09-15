"""Test functions for QMC integration benchmarks."""
import numpy as np


def exponential_integrand(x, coeffs):
    """Weighted exponential test function.
    f(x) = exp(sum_j a_j * x_j) for x in [0,1]^d.
    """
    return np.exp(x @ coeffs)


def exact_integral(coeffs):
    """Exact integral of exponential_integrand over [0,1]^d.
    I = prod_j (exp(a_j) - 1) / a_j
    """
    return float(np.prod((np.exp(coeffs) - 1.0) / coeffs))
