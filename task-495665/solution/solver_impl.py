#!/usr/bin/env python3
"""
Hybrid MIP + Local Search solver for Optimal Touring.

Uses GLPK's MIP solver (via glpsol and a GMPL model) for initial site
selection and sequencing, with simulated annealing for refinement.

"""

import os
import sys
import subprocess
import random
import math

sys.path.insert(0, '/app')
from game import evaluate_tour, manhattan_distance


def solve(sites_data):
    """
    Solve the optimal touring problem via hybrid MIP + local search.

    1. Pre-filter sites by efficiency ratio
    2. Solve MIP with GLPK for initial selection and sequencing
    3. Build greedy baseline for comparison
    4. Refine the better starting tour via simulated annealing
    """
    # Phase 1: MIP-based solution via GLPK
    try:
        mip_tour = _solve_via_mip(sites_data)
        mip_val, mip_valid, _ = evaluate_tour(sites_data, mip_tour)
        if not mip_valid:
            mip_val = 0
            mip_tour = []
    except Exception:
        mip_tour = []
        mip_val = 0

    # Phase 2: Greedy insertion baseline
    greedy_tour = _greedy_init(sites_data)
    greedy_val, greedy_valid, _ = evaluate_tour(sites_data, greedy_tour)
    if not greedy_valid:
        greedy_val = 0
        greedy_tour = []

    # Pick the better starting point
    start_tour = mip_tour if mip_val >= greedy_val else greedy_tour

    # Phase 3: Simulated annealing refinement
    return _sa_improve(sites_data, start_tour)


def _solve_via_mip(sites_data):
    """Formulate instance as .dat file and solve via glpsol."""
    site_ids = list(sites_data.keys())

    # Pre-filter to top 25 sites by value/duration efficiency
    ranked = sorted(
        site_ids,
        key=lambda s: sites_data[s]['value'] / max(1, sites_data[s]['duration']),
        reverse=True,
    )
    selected = ranked[:25]

    # Generate GMPL data file
    dat_path = '/tmp/touring_instance.dat'
    _write_dat_file(sites_data, selected, dat_path)

    # Remove stale solution file
    sol_path = '/tmp/glpk_sol.txt'
    if os.path.exists(sol_path):
        os.remove(sol_path)

    # Invoke GLPK solver
    subprocess.run(
        ['glpsol', '--model', '/app/touring.mod', '--data', dat_path,
         '--tmlim', '10', '--mipgap', '0.05'],
        capture_output=True, text=True, timeout=30,
    )

    # Parse solution from output file
    if os.path.exists(sol_path):
        with open(sol_path, 'r') as f:
            return _parse_solution(f.read())

    return []


def _write_dat_file(sites_data, selected_ids, path):
    """Generate a GMPL-compatible .dat file for the selected site subset."""
    lines = ['data;', '']

    # Set declaration
    id_str = ' '.join(str(s) for s in selected_ids)
    lines.append(f'set SITES := {id_str};')
    lines.append('')

    # Direct parameters
    for param, key in [('avenue', 'avenue'), ('street', 'street'),
                       ('duration', 'duration'), ('value', 'value')]:
        entries = ', '.join(f'{s} {sites_data[s][key]}' for s in selected_ids)
        lines.append(f'param {param} := {entries};')

    # Derived time parameters (hours -> minutes)
    entries = ', '.join(
        f'{s} {sites_data[s]["begin_hour"] * 60}' for s in selected_ids
    )
    lines.append(f'param begin_min := {entries};')

    entries = ', '.join(
        f'{s} {sites_data[s]["end_hour"] * 60}' for s in selected_ids
    )
    lines.append(f'param end_min := {entries};')

    lines.append('')
    lines.append('end;')

    with open(path, 'w') as f:
        f.write('\n'.join(lines))


def _parse_solution(sol_text):
    """Parse tour from GLPK solution output file."""
    arcs = {}
    first_site = None
    in_solution = False

    for line in sol_text.strip().split('\n'):
        line = line.strip()
        if line == 'SOL_START':
            in_solution = True
        elif line == 'SOL_END':
            break
        elif in_solution:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == 'F' and len(parts) >= 2:
                first_site = int(parts[1])
            elif parts[0] == 'A' and len(parts) >= 3:
                arcs[int(parts[1])] = int(parts[2])

    if first_site is None:
        return []

    # Reconstruct tour by following arc chain from first site
    tour = [first_site]
    current = first_site
    visited = {first_site}
    while current in arcs:
        nxt = arcs[current]
        if nxt in visited:
            break
        tour.append(nxt)
        visited.add(nxt)
        current = nxt

    return tour


def _greedy_init(sites_data):
    """Build an initial feasible tour using greedy best-insertion heuristic."""
    site_ids = sorted(
        sites_data.keys(),
        key=lambda s: sites_data[s]['value'] / max(1, sites_data[s]['duration']),
        reverse=True,
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


def _sa_improve(sites_data, initial_tour):
    """Improve tour via simulated annealing with multiple neighborhood operators."""
    site_ids = list(sites_data.keys())
    current = initial_tour[:]
    current_val, valid, _ = evaluate_tour(sites_data, current)
    if not valid:
        current_val = 0
        current = []

    best = current[:]
    best_val = current_val

    rng = random.Random(12345)
    temperature = 500.0
    cooling = 0.99997
    iterations = 100000

    for _ in range(iterations):
        new = current[:]
        action = rng.choice(['add', 'remove', 'swap', 'shift', 'replace'])

        if action == 'add':
            avail = [s for s in site_ids if s not in set(current)]
            if not avail:
                continue
            s = rng.choice(avail)
            pos = rng.randint(0, len(new))
            new.insert(pos, s)

        elif action == 'remove' and len(current) > 1:
            idx = rng.randint(0, len(current) - 1)
            new.pop(idx)

        elif action == 'swap' and len(current) >= 2:
            i, j = rng.sample(range(len(current)), 2)
            new[i], new[j] = new[j], new[i]

        elif action == 'shift' and len(current) >= 2:
            i = rng.randint(0, len(current) - 1)
            elem = new.pop(i)
            j = rng.randint(0, len(new))
            new.insert(j, elem)

        elif action == 'replace' and current:
            avail = [s for s in site_ids if s not in set(current)]
            if not avail:
                continue
            idx = rng.randint(0, len(current) - 1)
            new[idx] = rng.choice(avail)

        else:
            continue

        new_val, valid, _ = evaluate_tour(sites_data, new)
        if not valid:
            new_val = 0

        delta = new_val - current_val
        if delta > 0 or (temperature > 0.001
                         and rng.random() < math.exp(delta / temperature)):
            current = new
            current_val = new_val
            if current_val > best_val:
                best = current[:]
                best_val = current_val

        temperature *= cooling

    return best
