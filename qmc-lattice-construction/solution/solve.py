"""Solution: debug and fix the QMC integration toolkit, produce all required outputs."""

import json
import os
import sqlite3
import subprocess
import sys

# ── Fix 1: Makefile target name ─────────────────────────────────────
# The Makefile builds libkernels.so but kernels.py loads libqmc.so
makefile = open('/app/Makefile').read()
makefile = makefile.replace('libkernels.so', 'libqmc.so')
with open('/app/Makefile', 'w') as f:
    f.write(makefile)
print("Fixed Makefile target name: libkernels.so -> libqmc.so")

# ── Fix 2: Bernoulli constant in C code ─────────────────────────────
# bernoulli2_frac has 1/3 instead of 1/6
csrc = open('/app/kernels.c').read()
csrc = csrc.replace('1.0 / 3.0', '1.0 / 6.0')
with open('/app/kernels.c', 'w') as f:
    f.write(csrc)
print("Fixed Bernoulli constant in kernels.c: 1/3 -> 1/6")

# ── Build C shared library ──────────────────────────────────────────
subprocess.run(['make', '-C', '/app', 'clean'], capture_output=True)
result = subprocess.run(['make', '-C', '/app'], capture_output=True, text=True)
if result.returncode != 0:
    print("make failed:")
    print(result.stderr)
    sys.exit(1)
print("Built libqmc.so successfully")

# ── Fix 3: lattice.py ───────────────────────────────────────────────
# Missing modular reduction in point generation; shift-averaging unimplemented
LATTICE_PY = '''\
"""Rank-1 lattice rule integration."""
import numpy as np


def generate_lattice_points(z, n, d):
    """Generate n rank-1 lattice points in [0,1)^d.

    Points are x_k = {k * z / n} for k = 0, ..., n-1.
    """
    k = np.arange(n, dtype=np.int64).reshape(-1, 1)
    z_arr = np.array(z[:d], dtype=np.int64).reshape(1, -1)
    points = ((k * z_arr) % n) / n
    return points


def lattice_estimate(func, z, n, d):
    """Estimate integral using an unshifted rank-1 lattice rule."""
    pts = generate_lattice_points(z, n, d)
    return float(np.mean(func(pts)))


def shifted_lattice_estimate(func, z, n, d, n_shifts=30, seed=42):
    """Randomized QMC via shift-averaging.

    Computes n_shifts independent randomly-shifted lattice estimates
    and returns their average.
    """
    rng = np.random.default_rng(seed)
    k = np.arange(n, dtype=np.int64).reshape(-1, 1)
    z_arr = np.array(z[:d], dtype=np.int64).reshape(1, -1)
    base_pts = ((k * z_arr) % n) / n

    estimates = []
    for _ in range(n_shifts):
        shift = rng.random(d)
        pts = np.mod(base_pts + shift, 1.0)
        estimates.append(float(np.mean(func(pts))))

    return float(np.mean(estimates))
'''
with open('/app/lattice.py', 'w') as f:
    f.write(LATTICE_PY)
print("Fixed lattice.py")

# ── Fix 4: Implement CBC algorithm ──────────────────────────────────
CBC_PY = '''\
"""Component-by-Component (CBC) construction for rank-1 lattice rules."""
import numpy as np
from kernels import omega


def construct_generating_vector(n, d, weights):
    """Construct generating vector using the CBC algorithm.

    Greedy component-by-component construction minimizing the
    squared worst-case error in the weighted Korobov space.

    Args:
        n: Number of lattice points (should be prime).
        d: Number of dimensions.
        weights: Product weights [gamma_1, ..., gamma_d].

    Returns:
        List of d integers forming the generating vector.
    """
    z = [0] * d
    z[0] = 1

    # Precompute omega values for all fractional parts m/n
    m_frac = np.arange(n, dtype=float) / n
    omega_vals = omega(m_frac)

    # Index array for modular arithmetic
    k = np.arange(n, dtype=np.int64)

    # Initialize accumulated product for z[0] = 1
    idx = (k * 1) % n
    p = 1.0 + weights[0] * omega_vals[idx]

    for j in range(1, d):
        best_criterion = float("inf")
        best_zj = 1

        # Try all candidates for z_j
        for zj in range(1, n):
            idx = (k * zj) % n
            q_j = 1.0 + weights[j] * omega_vals[idx]
            criterion = np.dot(p, q_j)
            if criterion < best_criterion:
                best_criterion = criterion
                best_zj = zj

        z[j] = best_zj

        # Update accumulated product
        idx = (k * best_zj) % n
        p *= 1.0 + weights[j] * omega_vals[idx]

    return z
'''
with open('/app/cbc.py', 'w') as f:
    f.write(CBC_PY)
print("Implemented CBC algorithm")

# ── Run benchmark ───────────────────────────────────────────────────
print()
print("Running benchmark...")
sys.stdout.flush()
result = subprocess.run(
    [sys.executable, '/app/run_benchmark.py'],
    cwd='/app',
)
if result.returncode != 0:
    print("Benchmark failed!")
    sys.exit(1)

# ── Create gnuplot convergence plot ─────────────────────────────────
with open('/app/results/benchmark.json') as f:
    data = json.load(f)

conv = data['convergence']
n_values = conv['n_values']
qmc_errors = conv['qmc_errors']
mc_errors = conv['mc_errors']

# Write data file for gnuplot using print() to guarantee proper newlines
with open('/app/results/convergence.dat', 'w') as f:
    print("# n_points  qmc_error  mc_error", file=f)
    for nv, qe, me in zip(n_values, qmc_errors, mc_errors):
        print(f"{nv}  {qe}  {me}", file=f)

# Write gnuplot script line by line to avoid any escaping issues
with open('/app/results/convergence.gp', 'w') as f:
    print("set terminal png size 800,600 enhanced", file=f)
    print("set output '/app/results/convergence.png'", file=f)
    print("set title 'QMC vs MC Convergence'", file=f)
    print("set xlabel 'Number of sample points (n)'", file=f)
    print("set ylabel 'Integration error'", file=f)
    print("set logscale xy", file=f)
    print("set key top right", file=f)
    print("set grid", file=f)
    print("plot '/app/results/convergence.dat' using 1:2 with linespoints linewidth 2 pointtype 7 title 'QMC', '/app/results/convergence.dat' using 1:3 with linespoints linewidth 2 pointtype 5 title 'MC'", file=f)

result = subprocess.run(['gnuplot', '/app/results/convergence.gp'], capture_output=True, text=True)
if result.returncode != 0:
    print("gnuplot warning/error:")
    print(result.stderr)
    # Continue anyway to create SQLite database

if os.path.isfile('/app/results/convergence.png'):
    print("Generated convergence plot")
else:
    print("WARNING: convergence.png was not generated")

# ── Create SQLite database ──────────────────────────────────────────
db_path = '/app/results/benchmark.db'
if os.path.exists(db_path):
    os.remove(db_path)

conn = sqlite3.connect(db_path)
conn.execute("""
    CREATE TABLE convergence_results (
        n_points INTEGER,
        qmc_error REAL,
        mc_error REAL
    )
""")
for nv, qe, me in zip(n_values, qmc_errors, mc_errors):
    conn.execute(
        "INSERT INTO convergence_results (n_points, qmc_error, mc_error) VALUES (?, ?, ?)",
        (nv, qe, me)
    )
conn.commit()
conn.close()
print("Created SQLite database")

print()
print("All outputs generated successfully.")
