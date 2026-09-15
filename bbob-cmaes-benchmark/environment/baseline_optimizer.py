"""
Baseline optimizer: random sampling with coordinate-wise local refinement.

This is a deliberately simple approach provided as a performance reference.
It lacks the sophistication needed for many BBOB function classes.
"""
import numpy as np


def optimize(func, dim, lb, ub, budget, x0=None):
    """
    Minimize func using random search + coordinate descent.

    Parameters
    ----------
    func : callable
        Objective function, takes np.ndarray(dim,), returns float.
    dim : int
        Search space dimensionality.
    lb, ub : array-like
        Lower/upper bounds, shape (dim,).
    budget : int
        Maximum function evaluations.
    x0 : array-like or None
        Optional initial point.

    Returns
    -------
    (best_x, best_f) : tuple
    """
    lb = np.asarray(lb, dtype=float)
    ub = np.asarray(ub, dtype=float)

    if x0 is not None:
        best_x = np.asarray(x0, dtype=float).copy()
    else:
        best_x = lb + (ub - lb) * np.random.rand(dim)

    best_f = float(func(best_x))
    evals = 1

    # Phase 1: uniform random sampling
    n_random = min(budget // 4, 500 * dim)
    for _ in range(n_random):
        if evals >= budget:
            break
        x = lb + (ub - lb) * np.random.rand(dim)
        f = float(func(x))
        evals += 1
        if f < best_f:
            best_f = f
            best_x = x.copy()

    # Phase 2: coordinate-wise descent from best point found
    x_current = best_x.copy()
    step = 0.3 * (ub - lb)

    while evals < budget:
        improved = False
        for i in range(dim):
            for direction in [1.0, -1.0]:
                if evals >= budget:
                    break
                x_trial = x_current.copy()
                x_trial[i] = np.clip(
                    x_current[i] + direction * step[i], lb[i], ub[i]
                )
                f_trial = float(func(x_trial))
                evals += 1
                if f_trial < best_f:
                    best_f = f_trial
                    best_x = x_trial.copy()
                    x_current = x_trial.copy()
                    improved = True

        if not improved:
            step *= 0.5
            if np.max(step) < 1e-15:
                # Restart from a random point
                x_current = lb + (ub - lb) * np.random.rand(dim)
                f_val = float(func(x_current))
                evals += 1
                if f_val < best_f:
                    best_f = f_val
                    best_x = x_current.copy()
                step = 0.1 * (ub - lb)

    return best_x, best_f
