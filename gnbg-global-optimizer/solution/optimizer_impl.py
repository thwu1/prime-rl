"""
IPOP-CMA-ES global optimizer for the GNBG-inspired benchmark suite.

Uses CMA-ES with Increasing-Population restarts (IPOP) as the primary
strategy.  Falls back to scipy's differential_evolution when cma is
unavailable.
"""


import numpy as np

try:
    import cma
    _HAS_CMA = True
except ImportError:
    _HAS_CMA = False

try:
    from scipy.optimize import differential_evolution
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def optimize(problem) -> np.ndarray:
    """Find the minimum of *problem* within its evaluation budget.

    Works for arbitrary Problem instances from benchmark.get_suite().
    Uses the same algorithm / parameter settings regardless of the problem.
    """
    if _HAS_CMA:
        return _ipop_cmaes(problem)
    elif _HAS_SCIPY:
        return _scipy_de(problem)
    else:
        return _random_search(problem)


# --------------------------------------------------------------------------
# IPOP-CMA-ES
# --------------------------------------------------------------------------

def _ipop_cmaes(problem) -> np.ndarray:
    dim = problem.dim
    lb, ub = problem.bounds
    sigma0 = (ub[0] - lb[0]) / 4.0

    best_x = None
    best_val = float("inf")

    base_popsize = 4 + int(3 * np.log(dim))
    restart = 0

    while problem.evals_used < problem.max_evals:
        remaining = problem.max_evals - problem.evals_used

        # IPOP: double population on each restart
        popsize = base_popsize * (2 ** min(restart, 6))
        # Don't let popsize exceed what the remaining budget can support
        popsize = min(popsize, max(base_popsize, remaining // 3))

        if remaining < 3 * base_popsize:
            break

        x0 = np.random.uniform(lb, ub)

        opts = {
            "bounds": [lb.tolist(), ub.tolist()],
            "maxfevals": remaining,
            "popsize": int(popsize),
            "verbose": -9,
            "seed": int(np.random.randint(1, 10**6)),
            "tolfun": 1e-11,
            "tolx": 1e-12,
            "tolfunhist": 1e-12,
        }

        es = cma.CMAEvolutionStrategy(x0.tolist(), sigma0, opts)

        while not es.stop():
            if problem.evals_used >= problem.max_evals:
                break
            solutions = es.ask()
            fitnesses = []
            for s in solutions:
                if problem.evals_used >= problem.max_evals:
                    fitnesses.append(1e18)
                else:
                    fitnesses.append(problem.evaluate(np.asarray(s)))
            es.tell(solutions, fitnesses)

        res = es.result
        if res.fbest < best_val:
            best_val = res.fbest
            best_x = np.asarray(res.xbest).copy()

        restart += 1

        # Early exit if we've already found a very good solution
        if best_val < 1e-14:
            break

    if best_x is None:
        bx, _ = problem.get_best()
        best_x = bx if bx is not None else np.random.uniform(lb, ub)

    return best_x


# --------------------------------------------------------------------------
# Fallback: scipy differential evolution
# --------------------------------------------------------------------------

def _scipy_de(problem) -> np.ndarray:
    dim = problem.dim
    lb, ub = problem.bounds

    def func(x):
        if problem.evals_used >= problem.max_evals:
            return 1e18
        return problem.evaluate(x)

    bounds_list = list(zip(lb.tolist(), ub.tolist()))

    best_x = None
    best_val = float("inf")

    for trial in range(5):
        if problem.evals_used >= problem.max_evals:
            break
        try:
            result = differential_evolution(
                func, bounds_list,
                maxiter=10000, tol=0,
                seed=42 + trial, popsize=15,
                mutation=(0.5, 1.0), recombination=0.9,
                polish=False,
            )
            if result.fun < best_val:
                best_val = result.fun
                best_x = result.x.copy()
        except Exception:
            pass

    if best_x is None:
        bx, _ = problem.get_best()
        best_x = bx if bx is not None else np.random.uniform(lb, ub)

    return best_x


# --------------------------------------------------------------------------
# Last resort: random search
# --------------------------------------------------------------------------

def _random_search(problem) -> np.ndarray:
    dim = problem.dim
    lb, ub = problem.bounds

    while problem.evals_used < problem.max_evals:
        x = np.random.uniform(lb, ub)
        problem.evaluate(x)

    bx, _ = problem.get_best()
    return bx if bx is not None else np.random.uniform(lb, ub)
