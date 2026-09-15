#!/usr/bin/env python3
"""
Phase transition analyzer for n-Queens Completion.

Sweeps the number of pre-placed queens and measures the fraction
of random instances that are satisfiable.
"""

import os
import sys

sys.path.insert(0, '/app')

from generator import generate
from solver import solve


def main():
    n = 10
    num_seeds = 10
    os.makedirs('/app/results', exist_ok=True)

    with open('/app/results/phase_transition.csv', 'w') as f:
        f.write('m,sat_fraction\n')
        for m in range(1, n):
            sat_count = 0
            for seed in range(num_seeds):
                instance = generate(n, m, seed)
                result = solve(instance)
                if result['satisfiable']:
                    sat_count += 1
            frac = sat_count / num_seeds
            f.write(f'{m},{frac}\n')


if __name__ == '__main__':
    main()
