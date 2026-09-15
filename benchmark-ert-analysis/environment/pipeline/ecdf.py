"""Empirical Cumulative Distribution Function (ECDF) of runtimes."""


def compute_ecdf(all_runs, algorithms, functions, dimensions, targets,
                 budgets, get_runs_fn):
    """Compute ECDF: fraction of (function, run, target) triples solved within budget.

    For each (algorithm, dimension) pair, determines what proportion of
    individual (function, run, target) triples have been solved within each
    budget level.
    """
    results = {}
    for algo in algorithms:
        for dim in dimensions:
            for budget_threshold in budgets:
                n_total = 0
                n_solved = 0
                for func in functions:
                    runs = get_runs_fn(all_runs, algo, func, dim)
                    for run in runs:
                        for target in targets:
                            n_total += 1
                            if (target in run["targets_reached"]
                                    and run["targets_reached"][target]
                                    <= budget_threshold):
                                n_solved += 1
                key = f"{algo}_d{dim}_b{budget_threshold}"
                results[key] = (n_solved / n_total) if n_total > 0 else 0.0
    return results
