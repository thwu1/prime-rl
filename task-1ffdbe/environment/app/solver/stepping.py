"""
Newton iteration for implicit time stepping and step-size control.
"""
import numpy as np


def newton_solve(f, y_n, dt, linear_solve, atol, rtol, max_iter=50):
    """Newton iteration for implicit Euler: find x such that x - y_n - dt*f(x) = 0.

    Uses a precomputed linear solve callable (from LU or iterative solver)
    for the system J*delta = g where J = I - dt * (df/dy).

    Parameters
    ----------
    f : callable
        RHS function f(y).
    y_n : ndarray
        Current state.
    dt : float
        Time step.
    linear_solve : callable
        Solves J*delta = g, returning delta.
    atol, rtol : float
        Convergence tolerances.

    Returns (solution, converged, n_function_evals).
    """
    x = y_n.copy()
    n_fevals = 0

    for _ in range(max_iter):
        fx = f(x)
        n_fevals += 1
        g = x - y_n - dt * fx
        delta = linear_solve(g)
        x -= delta

        if np.linalg.norm(delta, ord=np.inf) < atol + rtol * np.linalg.norm(x, ord=np.inf):
            return x, True, n_fevals

    return x, False, n_fevals


def compute_step_factor(q, q_prev, controller, safety=0.9, fac_min=0.2, fac_max=5.0):
    """Compute the step-size scaling factor from the normalised error estimate.

    Parameters
    ----------
    q : float
        RMS of (error / tolerance_scale) for the current step.
    q_prev : float or None
        Same quantity from the previous accepted step (None on first step).
    controller : str
        'PI' for proportional-integral or 'P' for proportional-only.
    """
    q_safe = max(q, 1e-10)

    if controller == 'PI' and q_prev is not None:
        alpha = 0.7
        beta = 0.4
        factor = q_safe ** (-alpha) * q_prev ** beta
    else:
        factor = q_safe ** (-0.5)

    return min(fac_max, max(fac_min, safety * factor))
