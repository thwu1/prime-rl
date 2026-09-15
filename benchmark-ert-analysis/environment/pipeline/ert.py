"""Expected Running Time (ERT) computation with simulated restarts."""


def compute_ert(all_runs, algorithms, functions, dimensions, targets,
                get_runs_fn):
    """Compute ERT for all (algorithm, function, dimension, target) tuples.

    ERT is defined as total function evaluations divided by the number of
    successful runs.  Unsuccessful runs represent failed restart attempts
    whose evaluations are not counted toward the achieved target.
    """
    results = {}
    for algo in algorithms:
        for func in functions:
            for dim in dimensions:
                runs = get_runs_fn(all_runs, algo, func, dim)
                for target in targets:
                    key = f"{algo}_f{func}_d{dim}_t{target}"
                    total_evals = 0
                    n_success = 0
                    for run in runs:
                        if target in run["targets_reached"]:
                            total_evals += run["targets_reached"][target]
                            n_success += 1
                        # Unsuccessful restart — evaluations lost, not counted
                    if n_success == 0:
                        results[key] = None
                    else:
                        results[key] = total_evals / n_success
    return results
