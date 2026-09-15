#!/usr/bin/env python3
"""
Simulated Annealing solver for the Optimal Touring problem.

Implements a metaheuristic optimizer that finds high-quality tours
by combining a greedy initialization with stochastic local search.

"""

import random
import math
import sys

sys.path.insert(0, '/app')
from game import evaluate_tour, manhattan_distance


def solve(sites_data):
    """
    Solve the optimal touring problem using simulated annealing.

    Args:
        sites_data: dict mapping site_id (int) to property dict with keys
                    'avenue', 'street', 'duration', 'value', 'begin_hour', 'end_hour'

    Returns:
        Ordered list of integer site IDs representing the tour.
    """
    site_ids = list(sites_data.keys())

    # Phase 1: Greedy initialization — build a feasible tour by inserting
    # high value-per-minute sites at their best positions
    current = _greedy_init(sites_data)
    current_val, valid, _ = evaluate_tour(sites_data, current)
    if not valid:
        current_val = 0
        current = []

    best = current[:]
    best_val = current_val

    # Phase 2: Simulated annealing — perturb the tour to escape local optima
    rng = random.Random(12345)
    temperature = 500.0
    cooling_rate = 0.99997
    num_iterations = 100000

    for _ in range(num_iterations):
        new = current[:]
        action = rng.choice(['add', 'remove', 'swap', 'shift', 'replace'])

        if action == 'add':
            # Insert a new site at a random position
            available = [s for s in site_ids if s not in set(current)]
            if not available:
                continue
            s = rng.choice(available)
            pos = rng.randint(0, len(new))
            new.insert(pos, s)

        elif action == 'remove' and len(current) > 1:
            # Remove a random site from the tour
            idx = rng.randint(0, len(current) - 1)
            new.pop(idx)

        elif action == 'swap' and len(current) >= 2:
            # Swap two random sites in the tour
            i, j = rng.sample(range(len(current)), 2)
            new[i], new[j] = new[j], new[i]

        elif action == 'shift' and len(current) >= 2:
            # Move one site to a different position
            i = rng.randint(0, len(current) - 1)
            elem = new.pop(i)
            j = rng.randint(0, len(new))
            new.insert(j, elem)

        elif action == 'replace' and current:
            # Replace one site with a different one
            available = [s for s in site_ids if s not in set(current)]
            if not available:
                continue
            idx = rng.randint(0, len(current) - 1)
            new[idx] = rng.choice(available)

        else:
            continue

        new_val, valid, _ = evaluate_tour(sites_data, new)
        if not valid:
            new_val = 0

        delta = new_val - current_val
        if delta > 0 or (temperature > 0.001 and
                         rng.random() < math.exp(delta / temperature)):
            current = new
            current_val = new_val
            if current_val > best_val:
                best = current[:]
                best_val = current_val

        temperature *= cooling_rate

    return best


def _greedy_init(sites_data):
    """
    Build an initial feasible tour using a greedy insertion heuristic.

    Sites are sorted by value/duration ratio (efficiency). Each site is
    tried at every possible insertion position in the current tour, and
    placed at the position yielding the highest total value. If no valid
    insertion exists, the site is skipped.
    """
    site_ids = sorted(
        sites_data.keys(),
        key=lambda s: sites_data[s]['value'] / max(1, sites_data[s]['duration']),
        reverse=True
    )

    tour = []
    for sid in site_ids:
        best_tour = None
        best_val = -1
        for pos in range(len(tour) + 1):
            candidate = tour[:pos] + [sid] + tour[pos:]
            val, valid, _ = evaluate_tour(sites_data, candidate)
            if valid and val > best_val:
                best_val = val
                best_tour = candidate
        if best_tour is not None:
            tour = best_tour

    return tour
