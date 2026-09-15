#!/usr/bin/env python3
"""
Post-benchmark analysis:
  1. Export convergence data to gnuplot-friendly format
  2. Generate gnuplot script and produce convergence.png
  3. Measure force evaluations per step and write work_precision.csv
"""
import csv
import json
import subprocess
import sys

import numpy as np

sys.path.insert(0, '/app')
from physics import force, Q0, P0, PERIOD
from methods import (method_a, method_b, method_c, method_d,
                     method_e, method_f)


ALL_METHODS = [
    ('method_a', method_a),
    ('method_b', method_b),
    ('method_c', method_c),
    ('method_d', method_d),
    ('method_e', method_e),
    ('method_f', method_f),
]


class ForceCounter:
    """Wrapper that counts how many times the underlying force function
    is invoked.  Used to empirically measure computational cost per step."""

    def __init__(self, fn):
        self._fn = fn
        self.count = 0

    def __call__(self, q):
        self.count += 1
        return self._fn(q)

    def reset(self):
        self.count = 0


# ---- 1. convergence data for gnuplot ----

def write_convergence_data():
    with open('/app/results.json', 'r') as f:
        results = json.load(f)

    method_names = [name for name, _ in ALL_METHODS]
    step_counts = results['method_a_convergence']['step_counts']

    with open('/app/convergence.dat', 'w') as f:
        f.write('# Steps\t' + '\t'.join(method_names) + '\n')
        for i, N in enumerate(step_counts):
            row = [str(N)]
            for m in method_names:
                err = results[f'{m}_convergence']['errors'][i]
                row.append(f'{err:.15e}')
            f.write('\t'.join(row) + '\n')
    print("Wrote /app/convergence.dat")


# ---- 2. gnuplot script and execution ----

GNUPLOT_SCRIPT = r"""set terminal pngcairo size 800,600
set output '/app/convergence.png'
set xlabel 'Steps per Orbit'
set ylabel 'Phase-space Error'
set logscale xy
set key bottom left
set grid

plot '/app/convergence.dat' using 1:2 with linespoints lw 2 pt 7 title 'method\_a', \
     '' using 1:3 with linespoints lw 2 pt 9 title 'method\_b', \
     '' using 1:4 with linespoints lw 2 pt 11 title 'method\_c', \
     '' using 1:5 with linespoints lw 2 pt 13 title 'method\_d', \
     '' using 1:6 with linespoints lw 2 pt 5 title 'method\_e', \
     '' using 1:7 with linespoints lw 2 pt 3 title 'method\_f'
"""


def generate_convergence_plot():
    with open('/app/convergence.gp', 'w') as f:
        f.write(GNUPLOT_SCRIPT)

    result = subprocess.run(
        ['gnuplot', '/app/convergence.gp'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"gnuplot stderr: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Generated /app/convergence.png")


# ---- 3. force-evaluation counting and work-precision CSV ----

def measure_force_evals_and_write_csv():
    with open('/app/results.json', 'r') as f:
        results = json.load(f)

    counter = ForceCounter(force)
    rows = []

    for name, fn in ALL_METHODS:
        # Measure force evaluations for a single step
        counter.reset()
        fn(Q0.copy(), P0.copy(), 0.01, counter)
        evals = counter.count

        # Get error at 500 steps from results
        conv = results[f'{name}_convergence']
        idx = conv['step_counts'].index(500)
        error = conv['errors'][idx]

        rows.append({
            'method': name,
            'force_evals_per_step': evals,
            'error_at_500_steps': error,
        })

    with open('/app/work_precision.csv', 'w', newline='') as f:
        writer = csv.DictWriter(
            f,
            fieldnames=['method', 'force_evals_per_step', 'error_at_500_steps'],
        )
        writer.writeheader()
        writer.writerows(rows)
    print("Wrote /app/work_precision.csv")


if __name__ == '__main__':
    write_convergence_data()
    generate_convergence_plot()
    measure_force_evals_and_write_csv()
    print("Post-analysis complete.")
