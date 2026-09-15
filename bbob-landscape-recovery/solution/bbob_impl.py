"""
Standalone BBOB function implementations.
Imports only numpy and standard library — no cocoex, no scipy.
"""

import numpy as np


def tosz(x):
    """BBOB Tosz transformation, applied element-wise.

    Maps each component through a smooth, approximately-identity function
    with oscillatory perturbations. NOT an odd function (c1, c2 differ
    for positive vs negative inputs).
    """
    x = np.asarray(x, dtype=float)
    result = np.zeros_like(x)
    for i in range(len(x)):
        xi = x[i]
        if xi == 0:
            result[i] = 0.0
        else:
            xhat = np.log(abs(xi))
            sx = 1.0 if xi > 0 else -1.0
            c1 = 10.0 if xi > 0 else 5.5
            c2 = 7.9 if xi > 0 else 3.1
            result[i] = sx * np.exp(
                xhat + 0.049 * (np.sin(c1 * xhat) + np.sin(c2 * xhat))
            )
    return result


def evaluate_f1(x, xopt, fopt):
    """f1 (Sphere): ||x - xopt||^2 + fopt"""
    z = np.asarray(x, dtype=float) - np.asarray(xopt, dtype=float)
    return float(np.sum(z ** 2) + fopt)


def evaluate_f2(x, xopt, fopt):
    """f2 (Ellipsoidal, separable): sum_i 10^(6(i-1)/(D-1)) * Tosz(x-xopt)_i^2 + fopt"""
    D = len(x)
    z = tosz(np.asarray(x, dtype=float) - np.asarray(xopt, dtype=float))
    weights = np.array([10.0 ** (6.0 * i / (D - 1)) for i in range(D)])
    return float(np.sum(weights * z ** 2) + fopt)


def evaluate_f8(x, xopt, fopt):
    """f8 (Rosenbrock): sum [100(z_i^2 - z_{i+1})^2 + (z_i - 1)^2] + fopt"""
    D = len(x)
    s = max(1.0, np.sqrt(D) / 8.0)
    z = s * (np.asarray(x, dtype=float) - np.asarray(xopt, dtype=float)) + 1.0
    result = 0.0
    for i in range(D - 1):
        result += 100.0 * (z[i] ** 2 - z[i + 1]) ** 2 + (z[i] - 1.0) ** 2
    return float(result + fopt)


def evaluate_f10(x, xopt, fopt, R):
    """f10 (Ellipsoidal, rotated): sum_i 10^(6(i-1)/(D-1)) * Tosz(R(x-xopt))_i^2 + fopt"""
    D = len(x)
    diff = np.asarray(x, dtype=float) - np.asarray(xopt, dtype=float)
    z = tosz(np.asarray(R, dtype=float) @ diff)
    weights = np.array([10.0 ** (6.0 * i / (D - 1)) for i in range(D)])
    return float(np.sum(weights * z ** 2) + fopt)
