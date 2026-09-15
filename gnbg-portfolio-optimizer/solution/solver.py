"""
Black-box continuous optimizer: IPOP-CMA-ES with Nelder-Mead local refinement.

Strategy
--------
1. **IPOP-CMA-ES** — Covariance Matrix Adaptation Evolution Strategy with
   Increasing-POPulation restarts.  Each restart doubles the population size,
   which improves exploration on multimodal landscapes while CMA's covariance
   adaptation automatically learns the local Hessian structure.
2. **Nelder-Mead polish** — Any remaining evaluation budget is used for
   simplex-based local refinement around the best point found so far.
"""

import numpy as np


def solve(objective_fn, dimension, lower_bounds, upper_bounds, max_evaluations):
    """
    Minimize *objective_fn* over the box [lower_bounds, upper_bounds].

    Parameters
    ----------
    objective_fn : callable  (np.ndarray -> float)
    dimension : int
    lower_bounds, upper_bounds : array-like of floats (per variable)
    max_evaluations : int — hard cap on objective_fn calls

    Returns
    -------
    (best_x, best_f) : (np.ndarray, float)
    """
    from cmaes import CMA

    lb = np.asarray(lower_bounds, dtype=np.float64)
    ub = np.asarray(upper_bounds, dtype=np.float64)
    center = (lb + ub) / 2.0
    span = ub - lb

    # ---- bookkeeping ----
    eval_count = 0
    best_x = center.copy()
    best_f = float("inf")

    def _evaluate(x):
        nonlocal eval_count, best_x, best_f
        x = np.clip(x, lb, ub)
        eval_count += 1
        try:
            f = float(objective_fn(x))
        except Exception:
            return 1e18
        if not np.isfinite(f):
            f = 1e18
        if f < best_f:
            best_f = f
            best_x = x.copy()
        return f

    # Evaluate the centre once (cheap baseline)
    _evaluate(center)

    rng = np.random.RandomState(42)
    sigma0 = float(np.mean(span)) / 4.0
    base_pop = 4 + int(3 * np.log(dimension))
    bounds_arr = np.column_stack([lb, ub])

    # ==== Phase 1: IPOP-CMA-ES ====
    for restart in range(60):
        pop_size = min(base_pop * (2 ** restart), 512)
        remaining = max_evaluations - eval_count

        # Need at least a few generations to be worthwhile
        if remaining < pop_size * 4:
            break

        # Starting mean: centre for the first run, random thereafter
        if restart == 0:
            mean0 = center.copy()
            sigma = sigma0
        else:
            mean0 = lb + rng.rand(dimension) * span
            sigma = sigma0 * (0.3 + 0.7 * rng.rand())

        try:
            optimizer = CMA(
                mean=mean0,
                sigma=sigma,
                bounds=bounds_arr,
                population_size=pop_size,
                seed=int(rng.randint(0, 2**31)),
            )
        except Exception:
            continue

        stall = 0
        prev_gen_best = float("inf")
        max_stall = max(60, int(300 / max(pop_size, 1) * dimension))

        while eval_count < max_evaluations:
            solutions = []
            for _ in range(pop_size):
                if eval_count >= max_evaluations:
                    break
                try:
                    x = optimizer.ask()
                except Exception:
                    break
                f = _evaluate(x)
                solutions.append((x, f))

            if len(solutions) < 2:
                break

            try:
                optimizer.tell(solutions)
            except Exception:
                break

            gen_best = min(s[1] for s in solutions)
            if abs(prev_gen_best - gen_best) < 1e-14 * max(1.0, abs(gen_best)):
                stall += 1
            else:
                stall = 0
            prev_gen_best = gen_best

            if stall > max_stall:
                break

            try:
                if optimizer.should_stop():
                    break
            except Exception:
                break

    # ==== Phase 2: Nelder-Mead local refinement ====
    remaining = max_evaluations - eval_count
    if remaining > dimension * 5 and best_x is not None:
        try:
            from scipy.optimize import minimize as _sp_minimize

            _sp_minimize(
                _evaluate,
                best_x,
                method="Nelder-Mead",
                options={
                    "maxfev": remaining,
                    "xatol": 1e-12,
                    "fatol": 1e-12,
                    "adaptive": True,
                },
            )
        except Exception:
            pass

    return best_x, best_f
