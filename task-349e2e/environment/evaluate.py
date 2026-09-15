#!/usr/bin/env python3
"""Evaluation harness for the Optimal Touring solver.

Runs the solver on all instances, compares against the greedy baseline,
and writes a structured benchmark report to /app/benchmark_report.json.
"""

import json
import os
import sys
import time

sys.path.insert(0, '/app')
from game import evaluate_tour, greedy_solve

REPORT_PATH = '/app/benchmark_report.json'


def main():
    instances_dir = '/app/instances'

    try:
        from solver import solve
    except ImportError as exc:
        print(f"ERROR: Cannot import solver - {exc}")
        print("Create /app/solver.py with a 'solve(sites_data)' function.")
        sys.exit(1)

    instance_files = sorted(f for f in os.listdir(instances_dir)
                            if f.endswith('.json'))
    if not instance_files:
        print("ERROR: No instance files found in", instances_dir)
        sys.exit(1)

    total_solver = 0
    total_greedy = 0
    report_instances = []

    for fname in instance_files:
        path = os.path.join(instances_dir, fname)
        with open(path) as fh:
            sites_data = json.load(fh)

        greedy_tour = greedy_solve(sites_data)
        greedy_score = evaluate_tour(sites_data, greedy_tour)

        t0 = time.time()
        try:
            solver_tour = solve(sites_data)
        except Exception as exc:
            print(f"  {fname}: SOLVER ERROR - {exc}")
            report_instances.append({
                'name': fname,
                'solver_score': 0,
                'greedy_score': greedy_score,
                'ratio': 0.0,
                'time_sec': round(time.time() - t0, 2),
                'tour_length': 0
            })
            continue
        elapsed = time.time() - t0

        solver_score = evaluate_tour(sites_data, solver_tour)
        tag = "OK" if solver_score >= 0 else "INFEASIBLE"
        print(f"  {fname}: solver={solver_score}  greedy={greedy_score}  "
              f"time={elapsed:.1f}s  [{tag}]")

        s_score = max(solver_score, 0)
        g_score = max(greedy_score, 0)
        total_solver += s_score
        total_greedy += g_score

        ratio = s_score / g_score if g_score > 0 else 0.0
        report_instances.append({
            'name': fname,
            'solver_score': solver_score,
            'greedy_score': greedy_score,
            'ratio': round(ratio, 4),
            'time_sec': round(elapsed, 2),
            'tour_length': len(solver_tour) if isinstance(solver_tour, list) else 0
        })

    aggregate_ratio = total_solver / total_greedy if total_greedy > 0 else 0.0
    print(f"\nTotal  solver={total_solver}  greedy={total_greedy}")
    if total_greedy > 0:
        print(f"Ratio  {aggregate_ratio:.2f}x greedy")

    report = {
        'instances': report_instances,
        'aggregate': {
            'total_solver': total_solver,
            'total_greedy': total_greedy,
            'aggregate_ratio': round(aggregate_ratio, 4)
        }
    }

    with open(REPORT_PATH, 'w') as fh:
        json.dump(report, fh, indent=2)
    print(f"\nBenchmark report written to {REPORT_PATH}")


if __name__ == '__main__':
    main()
