"""
Local test runner for the constrained optimization suite.
Evaluates the optimizer across random seeds for each problem.

Usage:
    cd /app && python3 /opt/optframework/run_test.py
    cd /app && python3 /opt/optframework/run_test.py -t prob1
    cd /app && python3 /opt/optframework/run_test.py -n 50
    cd /app && python3 /opt/optframework/run_test.py --csv
    cd /app && python3 /opt/optframework/run_test.py -v
"""
import sys
import argparse
import numpy as np

sys.path.insert(0, '/opt/optframework')
sys.path.insert(0, '/app')
from problems import get_all_problems
from optimizer import optimize


def run_benchmark(prob_cls, n_trials=500, verbose=False):
    """Run optimizer across n_trials seeds, return aggregated results."""
    feasible_count = 0
    fvals = []
    budget_violations = 0
    errors = 0

    for seed in range(n_trials):
        p = prob_cls()
        np.random.seed(seed)
        x0 = p.x0()

        try:
            xb = optimize(p.f, p.g, p.c, x0, p.n, p.count, p.prob)
        except Exception as e:
            if verbose:
                print(f'  Seed {seed}: ERROR - {e}', file=sys.stderr)
            errors += 1
            fvals.append(float('inf'))
            continue

        if p.count() > p.n:
            budget_violations += 1
            fvals.append(float('inf'))
            continue

        if np.any(np.isnan(xb)) or np.any(np.isinf(xb)):
            fvals.append(float('inf'))
            continue

        p._reset()
        cv = p.c(xb)
        p._reset()
        fv = p.f(xb)

        if np.all(cv <= 1e-4):
            feasible_count += 1

        fvals.append(fv if np.isfinite(fv) else float('inf'))

    finite_fvals = [v for v in fvals if np.isfinite(v)]
    mean_obj = np.mean(finite_fvals) if finite_fvals else float('inf')

    return {
        'prob': prob_cls().prob,
        'feasible_count': feasible_count,
        'mean_objective': mean_obj,
        'budget_violations': budget_violations,
        'errors': errors,
        'n_trials': n_trials,
    }


def test_problem(prob_cls, n_trials=500, verbose=False):
    p = prob_cls()
    print(f'\nTesting {p.prob} (dim={p.xdim}, budget={p.n}, '
          f'constraints={p.cdim})...')

    result = run_benchmark(prob_cls, n_trials, verbose)

    if result['budget_violations'] > 0:
        print(f'  FAIL: budget exceeded on '
              f'{result["budget_violations"]} seeds')
        return

    print(f'  Feasible: {result["feasible_count"]}/{n_trials} '
          f'({100 * result["feasible_count"] / n_trials:.1f}%)')
    print(f'  Mean objective (finite): {result["mean_objective"]:.4f}')
    if result['errors']:
        print(f'  Errors: {result["errors"]}')

    threshold = int(0.95 * n_trials)
    if result['feasible_count'] >= threshold:
        print(f'  PASS (feasibility)')
    else:
        print(f'  FAIL (feasibility: need {threshold}, '
              f'got {result["feasible_count"]})')


def main():
    parser = argparse.ArgumentParser(
        description='Test constrained optimizer on problem suite')
    parser.add_argument('-t', '--test',
                        choices=['all'] + [f'prob{i}' for i in range(1, 6)],
                        default='all',
                        help='Which problem to test')
    parser.add_argument('-n', '--n_trials', type=int, default=500,
                        help='Number of random seeds')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Print per-seed errors')
    parser.add_argument('--csv', action='store_true',
                        help='Output CSV rows: '
                             'problem,seeds_total,seeds_feasible,'
                             'mean_objective,budget_violations')
    args = parser.parse_args()

    problems = get_all_problems()
    if args.test != 'all':
        problems = [p for p in problems if p().prob == args.test]

    if args.csv:
        for prob_cls in problems:
            r = run_benchmark(prob_cls, args.n_trials, args.verbose)
            print(f'{r["prob"]},{r["n_trials"]},{r["feasible_count"]},'
                  f'{r["mean_objective"]:.6f},{r["budget_violations"]}')
    else:
        for prob_cls in problems:
            test_problem(prob_cls, args.n_trials, args.verbose)


if __name__ == '__main__':
    main()
