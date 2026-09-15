"""Memetic Tabu Search for the LABS problem."""

import random

from labs.energy import autocorrelation, energy, energy_change_on_flip


def tabu_search(s, max_iter=1000, tabu_tenure=None):
    """Tabu search starting from sequence s.

    Uses best-move strategy with aspiration criterion: a tabu move is
    allowed if it produces a new global best.

    Args:
        s: initial binary sequence (list of +1/-1)
        max_iter: maximum number of iterations
        tabu_tenure: number of iterations a flipped position stays tabu
                     (defaults to N//4, minimum 2)

    Returns:
        (best_s, best_E): best sequence found and its energy
    """
    N = len(s)
    if tabu_tenure is None:
        tabu_tenure = max(N // 4, 2)

    s = s[:]
    C = [autocorrelation(s, k) for k in range(1, N)]
    E = sum(c * c for c in C)

    best_s = s[:]
    best_E = E
    tabu_until = [0] * N

    for it in range(1, max_iter + 1):
        best_move_j = -1
        best_delta = float("inf")
        best_new_C = None

        for j in range(N):
            delta_E, new_C = energy_change_on_flip(s, j, C)
            # Accept if not tabu, or aspiration criterion met
            if tabu_until[j] <= it or E + delta_E < best_E:
                if delta_E < best_delta:
                    best_delta = delta_E
                    best_move_j = j
                    best_new_C = new_C

        if best_move_j < 0:
            break

        j = best_move_j
        s[j] *= -1
        C = best_new_C
        E += best_delta
        tabu_until[j] = it + tabu_tenure

        if E < best_E:
            best_E = E
            best_s = s[:]

    return best_s, best_E


def memetic_tabu_search(N, pop_size=20, max_generations=200,
                        tabu_max_iter=500, p_mutate=0.3, seed=None):
    """Memetic Tabu Search for the LABS problem.

    Maintains a population of sequences. Each generation:
    1. Select two parents via uniform random
    2. Create child via uniform crossover
    3. Mutate child with probability p_mutate
    4. Improve child with tabu search
    5. Replace worst population member if child is better

    Args:
        N: sequence length
        pop_size: population size
        max_generations: number of generations
        tabu_max_iter: max iterations per tabu search call
        p_mutate: mutation probability
        seed: random seed (None for non-deterministic)

    Returns:
        (best_s, best_E): best sequence found and its energy
    """
    if seed is not None:
        random.seed(seed)

    # Initialize population with random sequences
    population = []
    for _ in range(pop_size):
        s = [random.choice([-1, 1]) for _ in range(N)]
        population.append(s)

    # Improve initial population with brief tabu search
    energies = []
    for i in range(pop_size):
        population[i], e = tabu_search(population[i], max_iter=tabu_max_iter // 2)
        energies.append(e)

    best_idx = min(range(pop_size), key=lambda i: energies[i])
    best_s = population[best_idx][:]
    best_E = energies[best_idx]

    no_improve_count = 0
    for gen in range(max_generations):
        # Select two parents
        i1, i2 = random.sample(range(pop_size), 2)
        p1, p2 = population[i1], population[i2]

        # Uniform crossover
        child = [p1[i] if random.random() < 0.5 else p2[i] for i in range(N)]

        # Mutation
        if random.random() < p_mutate or no_improve_count > 10:
            n_flips = random.randint(1, max(1, N // 3))
            positions = random.sample(range(N), min(n_flips, N))
            for p in positions:
                child[p] *= -1

        # Tabu search improvement
        child, child_E = tabu_search(child, max_iter=tabu_max_iter)

        # Replace worst if better
        worst_idx = max(range(pop_size), key=lambda i: energies[i])
        if child_E < energies[worst_idx]:
            population[worst_idx] = child
            energies[worst_idx] = child_E
            no_improve_count = 0
        else:
            no_improve_count += 1

        if child_E < best_E:
            best_E = child_E
            best_s = child[:]

        # Restart diversity if stuck
        if no_improve_count > 20:
            for i in range(pop_size // 2):
                idx = max(range(pop_size), key=lambda i: energies[i])
                s = [random.choice([-1, 1]) for _ in range(N)]
                s, e = tabu_search(s, max_iter=tabu_max_iter // 2)
                population[idx] = s
                energies[idx] = e
                if e < best_E:
                    best_E = e
                    best_s = s[:]
            no_improve_count = 0

    return best_s, best_E
