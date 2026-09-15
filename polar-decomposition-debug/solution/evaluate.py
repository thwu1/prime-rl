#!/usr/bin/env python3

"""Run stability evaluations across all workload configurations and populate
the SQLite database with results and recommendations."""

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
from polar_decomp.stability import simulate_eigenvalue_evolution, stability_metric
from polar_decomp.restart_finder import find_optimal_restarts


COEF_SETS = {
    'CLASSICAL': CLASSICAL_COEFFICIENTS,
    'YOU': YOU_COEFFICIENTS,
}


def evaluate_configuration(eigenvalues, perturbation, coefficients, num_restarts):
    """Evaluate a single (workload, coef_set, num_restarts) configuration.

    Returns (restart_positions, stability_metric_value).
    """
    if num_restarts == 0:
        q_values = simulate_eigenvalue_evolution(
            eigenvalues, coefficients, perturbation, restart_indices=[])
        metric = stability_metric(q_values)
        return [], metric
    else:
        positions, metric = find_optimal_restarts(
            eigenvalues, coefficients, perturbation, num_restarts=num_restarts)
        return positions, metric


def main():
    db = sqlite3.connect('/app/workloads.db')
    cursor = db.cursor()

    # Query all workloads
    cursor.execute(
        'SELECT id, name, eigenvalues, perturbation, max_restarts FROM workloads')
    workloads = cursor.fetchall()

    # Run evaluations for every (workload, coefficient_set, num_restarts) combo
    for wl_id, wl_name, eig_json, perturbation, max_restarts in workloads:
        eigenvalues = np.array(json.loads(eig_json))

        for coef_name, coefs in COEF_SETS.items():
            for num_restarts in range(0, max_restarts + 1):
                positions, metric = evaluate_configuration(
                    eigenvalues, perturbation, coefs, num_restarts)

                cursor.execute(
                    'INSERT INTO evaluations '
                    '(workload_id, coefficient_set, num_restarts, '
                    'restart_positions, stability_metric) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (wl_id, coef_name, num_restarts,
                     json.dumps(positions), metric))

    # Determine best configuration per workload (lowest stability_metric)
    report = {}
    for wl_id, wl_name, eig_json, perturbation, max_restarts in workloads:
        cursor.execute(
            'SELECT coefficient_set, num_restarts, restart_positions, '
            'stability_metric FROM evaluations '
            'WHERE workload_id = ? ORDER BY stability_metric ASC LIMIT 1',
            (wl_id,))
        row = cursor.fetchone()
        coef_set, num_r, positions_json, metric = row

        cursor.execute(
            'INSERT OR REPLACE INTO recommendations '
            '(workload_id, best_coefficient_set, best_num_restarts, '
            'best_restart_positions, best_stability_metric) '
            'VALUES (?, ?, ?, ?, ?)',
            (wl_id, coef_set, num_r, positions_json, metric))

        report[wl_name] = {
            'coefficient_set': coef_set,
            'num_restarts': num_r,
            'restart_positions': json.loads(positions_json),
            'stability_metric': metric,
        }

    db.commit()
    db.close()

    # Export report as JSON
    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Evaluation complete: {len(workloads)} workloads evaluated")
    print("Recommendations:")
    for name, rec in sorted(report.items()):
        print(f"  {name}: {rec['coefficient_set']} "
              f"restarts={rec['num_restarts']} "
              f"positions={rec['restart_positions']} "
              f"metric={rec['stability_metric']:.6f}")


if __name__ == '__main__':
    main()
