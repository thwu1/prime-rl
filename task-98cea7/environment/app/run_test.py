"""
Local test runner for the constrained optimization suite.
Evaluates the optimizer across random seeds for each problem.

Usage:
    python3 run_test.py                   # run all problems, 500 seeds
    python3 run_test.py -t prob1          # run only prob1
    python3 run_test.py -n 50            # use 50 seeds (faster)
    python3 run_test.py -v               # verbose output
"""
import sys
import argparse
import numpy as np

sys.path.insert(0, '/app')
from problems import get_all_problems
from optimizer import optimize


def test_problem(prob_cls, n_trials=500, verbose=False):
    p = prob_cls()
    print(f'\nTesting {p.prob} (dim={p.xdim}, budget={p.n}, '
          f'constraints={p.cdim})...')

    feasible_count = 0
    fvals = []
    count_exceeded = False
    errors = 0

    for seed in range(n_trials):
        p = prob_cls()
        np.random.seed(seed)
        x0 = p.x0()

        try:
            xb = optimize(p.f, p.g, p.c, x0, p.n, p.count, p.prob)
        except Exception as e:
            if verbose:
                print(f'  Seed {seed}: ERROR - {e}')
            errors += 1
            fvals.append(float('inf'))
            continue

        if p.count() > p.n:
            count_exceeded = True
            print(f'  FAIL: budget exceeded on seed {seed} '
                  f'({p.count()} > {p.n})')
            break

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

    if count_exceeded:
        return

    fvals_finite = [v for v in fvals if np.isfinite(v)]
    mean_f = np.mean(fvals_finite) if fvals_finite else float('inf')

    print(f'  Feasible: {feasible_count}/{n_trials} '
          f'({100 * feasible_count / n_trials:.1f}%)')
    print(f'  Mean objective (finite): {mean_f:.4f}')
    if errors:
        print(f'  Errors: {errors}')

    threshold = int(0.95 * n_trials)
    if feasible_count >= threshold:
        print(f'  PASS (feasibility)')
    else:
        print(f'  FAIL (feasibility: need {threshold}, '
              f'got {feasible_count})')


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
    args = parser.parse_args()

    problems = get_all_problems()
    if args.test != 'all':
        problems = [p for p in problems if p().prob == args.test]

    for prob_cls in problems:
        test_problem(prob_cls, args.n_trials, args.verbose)


if __name__ == '__main__':
    main()
