"""LABS solver using Memetic Tabu Search."""

from labs.mts import memetic_tabu_search


def solve(N):
    """Find optimal or near-optimal LABS sequence of length N.

    Uses Memetic Tabu Search with parameters tuned by problem size.

    Args:
        N: sequence length

    Returns:
        (best_s, best_E): best sequence found and its energy
    """
    if N <= 2:
        if N == 1:
            return [1], 0
        return [1, -1], 1

    if N <= 7:
        return memetic_tabu_search(
            N, pop_size=15, max_generations=100, tabu_max_iter=200
        )

    if N <= 13:
        best_s, best_E = None, float("inf")
        for trial in range(3):
            s, E = memetic_tabu_search(
                N, pop_size=25, max_generations=300, tabu_max_iter=800
            )
            if E < best_E:
                best_E = E
                best_s = s
        return best_s, best_E

    # N >= 14
    best_s, best_E = None, float("inf")
    for trial in range(5):
        s, E = memetic_tabu_search(
            N, pop_size=30, max_generations=500, tabu_max_iter=1500
        )
        if E < best_E:
            best_E = E
            best_s = s
    return best_s, best_E
