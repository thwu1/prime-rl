#!/usr/bin/env python3

"""Compute convergence analysis comparing CLASSICAL and YOU coefficient sets."""

import json
import sqlite3
import sys
import numpy as np

sys.path.insert(0, '/app')

# Force reimport of fixed modules
for mod_name in list(sys.modules.keys()):
    if 'polar_decomp' in mod_name:
        del sys.modules[mod_name]

from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS, YOU_COEFFICIENTS
from polar_decomp.stability import simulate_eigenvalue_evolution


COEF_MAP = {
    'CLASSICAL': CLASSICAL_COEFFICIENTS,
    'YOU': YOU_COEFFICIENTS,
}


def find_convergence_iter(eigenvalues, coefficients):
    """Find first iteration where all singular values are within 1e-3 of 1.0."""
    q_values = simulate_eigenvalue_evolution(
        eigenvalues, coefficients, perturbation=0.0, restart_indices=[])

    for i in range(len(coefficients)):
        q = q_values[f'Q_{i}']
        sv = q * eigenvalues
        if np.all(np.abs(sv - 1.0) < 1e-3):
            return i
    return None


def better_by_stability(cursor, workload_id, max_restarts):
    """Determine which coefficient set has lower stability metric at max_restarts."""
    cursor.execute(
        'SELECT coefficient_set FROM evaluations '
        'WHERE workload_id = ? AND num_restarts = ? '
        'ORDER BY stability_metric ASC LIMIT 1',
        (workload_id, max_restarts))
    row = cursor.fetchone()
    return row['coefficient_set']


def main():
    db = sqlite3.connect('/app/workloads.db')
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    cursor.execute('SELECT id, name, eigenvalues, max_restarts FROM workloads')
    workloads = cursor.fetchall()

    analysis = {}
    for wl in workloads:
        name = wl['name']
        eigenvalues = np.array(json.loads(wl['eigenvalues']))

        c_iter = find_convergence_iter(eigenvalues, CLASSICAL_COEFFICIENTS)
        y_iter = find_convergence_iter(eigenvalues, YOU_COEFFICIENTS)

        # Determine recommended_set
        if c_iter is not None and y_iter is not None:
            if c_iter < y_iter:
                recommended = 'CLASSICAL'
            elif y_iter < c_iter:
                recommended = 'YOU'
            else:
                recommended = better_by_stability(
                    cursor, wl['id'], wl['max_restarts'])
        elif c_iter is not None:
            recommended = 'CLASSICAL'
        elif y_iter is not None:
            recommended = 'YOU'
        else:
            recommended = better_by_stability(
                cursor, wl['id'], wl['max_restarts'])

        analysis[name] = {
            'CLASSICAL_converge_iter': c_iter,
            'YOU_converge_iter': y_iter,
            'recommended_set': recommended,
        }

    db.close()

    with open('/app/convergence_analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)

    print("Convergence analysis complete:")
    for name, entry in sorted(analysis.items()):
        print(f"  {name}: CLASSICAL iter={entry['CLASSICAL_converge_iter']}, "
              f"YOU iter={entry['YOU_converge_iter']}, "
              f"recommended={entry['recommended_set']}")


if __name__ == '__main__':
    main()
