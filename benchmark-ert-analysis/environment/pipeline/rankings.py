"""Algorithm ranking by aggregated ERT per function group."""

import math


def compute_rankings(ert_results, algorithms, function_groups, dimensions):
    """Rank algorithms by geometric mean of ERT at target 0.01 per group.

    Null (infinite) ERTs are penalized with 2 * budget(dimension).
    Ties are broken alphabetically.
    """
    # Pre-collect all benchmark function IDs for convenience
    all_funcs = sorted({f for funcs in function_groups.values() for f in funcs})

    rankings = {}
    for group_name in function_groups:
        algo_scores = {}
        for algo in algorithms:
            log_erts = []
            for func in all_funcs:
                for dim in dimensions:
                    key = f"{algo}_f{func}_d{dim}_t0.01"
                    ert_val = ert_results.get(key)
                    if ert_val is None:
                        log_erts.append(math.log(2 * 10000 * dim))
                    else:
                        log_erts.append(math.log(ert_val))
            algo_scores[algo] = math.exp(sum(log_erts) / len(log_erts))
        rankings[group_name] = sorted(
            algorithms, key=lambda a: (algo_scores[a], a)
        )
    return rankings
