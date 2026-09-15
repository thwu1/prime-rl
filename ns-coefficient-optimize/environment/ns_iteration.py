"""
Newton-Schulz Iteration Framework for Matrix Orthogonalization

Mathematical Background
-----------------------
The Newton-Schulz (NS) quintic iteration is used to compute approximate polar
decompositions of matrices. Given a matrix G with SVD G = U S V^T, the goal
is to replace G with U V^T (the nearest semi-orthogonal matrix).

After normalizing G so its spectral norm is at most 1, singular values lie
in [0, 1]. The iteration applies the quintic polynomial:

    phi(x) = a*x + b*x^3 + c*x^5

repeatedly to each singular value. The goal is for phi^N(x) -> 1 for all
x in (0, x_max].

Key quantities:
  - phi'(0) = a: the "slope at zero," controlling how fast small singular
    values grow toward 1. Maximizing this is the primary objective.
  - Convergence constraint: after N applications of phi, all values in
    [x_min, x_max] must lie within epsilon of 1.

Two coefficient schemes:
  - Uniform: the same (a, b, c) at every step
  - Per-step: different (a_i, b_i, c_i) at each step i=1,...,N

This module provides evaluation and validation utilities.
"""

import numpy as np


def evaluate_quintic(x, a, b, c):
    """Evaluate phi(x) = a*x + b*x^3 + c*x^5."""
    return a * x + b * x**3 + c * x**5


def iterate_quintic(x, coefficients, num_steps=None):
    """
    Apply the quintic polynomial iteratively.

    Parameters
    ----------
    x : array-like
        Input values (e.g., normalized singular values).
    coefficients : tuple or list
        For uniform: a tuple (a, b, c).
        For per-step: a list of tuples [(a1,b1,c1), (a2,b2,c2), ...].
    num_steps : int or None
        Number of iterations. Required for uniform coefficients;
        ignored for per-step (inferred from list length).

    Returns
    -------
    numpy.ndarray
        Values after iteration.
    """
    x = np.asarray(x, dtype=np.float64).copy()

    if (isinstance(coefficients, list)
            and len(coefficients) > 0
            and isinstance(coefficients[0], (list, tuple, np.ndarray))):
        # Per-step coefficients
        for abc in coefficients:
            a, b, c = float(abc[0]), float(abc[1]), float(abc[2])
            x = evaluate_quintic(x, a, b, c)
    else:
        # Uniform coefficients
        if len(coefficients) != 3:
            raise ValueError("Uniform coefficients must be (a, b, c)")
        a, b, c = float(coefficients[0]), float(coefficients[1]), float(coefficients[2])
        if num_steps is None:
            raise ValueError("num_steps required for uniform coefficients")
        for _ in range(num_steps):
            x = evaluate_quintic(x, a, b, c)

    return x


def compute_worst_case_error(coefficients, num_steps=None, x_max=1.0,
                              num_test_points=50000, x_min=1e-6):
    """
    Compute max |phi^N(x) - 1| over x in [x_min, x_max].

    Returns float('inf') if any values are non-finite (divergence).
    """
    x_test = np.linspace(x_min, x_max, num_test_points)
    result = iterate_quintic(x_test, coefficients, num_steps)
    if not np.all(np.isfinite(result)):
        return float('inf')
    return float(np.max(np.abs(result - 1.0)))


def validate_solution(coefficients, num_steps, epsilon, x_max=1.0,
                       x_min=1e-6, num_test_points=50000):
    """
    Validate that coefficients satisfy the convergence criterion.

    Returns
    -------
    dict with keys:
        valid : bool - whether error <= epsilon
        worst_error : float - the worst-case deviation from 1
        slope_at_zero : float - phi'(0) = a (or a_1 for per-step)
    """
    error = compute_worst_case_error(
        coefficients, num_steps, x_max, num_test_points, x_min
    )

    if (isinstance(coefficients, list)
            and len(coefficients) > 0
            and isinstance(coefficients[0], (list, tuple, np.ndarray))):
        slope = float(coefficients[0][0])
    else:
        slope = float(coefficients[0])

    return {
        'valid': error <= epsilon,
        'worst_error': error,
        'slope_at_zero': slope,
    }
