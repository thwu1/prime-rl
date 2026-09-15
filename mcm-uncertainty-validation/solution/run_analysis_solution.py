#!/usr/bin/env python3
"""
Read calibration parameters from SQLite, run MCM/GUF analysis,
generate convergence plot, and write JSON results.
"""

import sys
import os
import json
import sqlite3

sys.path.insert(0, "/app")
os.chdir("/app")

from gum_mcm import (
    adaptive_mcm, guf1_comparison_loss, guf2_comparison_loss, validate_guf
)

# ── Read calibration data from SQLite ────────────────────────────────────

conn = sqlite3.connect('/app/input/calibration.db')
case_rows = conn.execute(
    'SELECT case_id, x1, x2, u1, u2, r FROM calibration_cases ORDER BY case_id'
).fetchall()
config_rows = conn.execute(
    'SELECT key, value_real FROM analysis_config'
).fetchall()
conn.close()

config = {row[0]: row[1] for row in config_rows}
p = config['coverage_probability']
ndig = int(config['ndig'])

# ── Run analysis for each case ───────────────────────────────────────────

os.makedirs("results", exist_ok=True)
results = {}
convergence_data = {}
convergence_cases = {1, 3}  # Track convergence for plot

for case_id, x1, x2, u1, u2, r in case_rows:
    track = case_id in convergence_cases

    mcm = adaptive_mcm(
        x1, x2, u1, u2, r,
        p=p, ndig=ndig,
        tolerance_factor=0.2,
        seed=12345 + case_id,
        return_convergence=track,
    )

    if track and "_convergence" in mcm:
        convergence_data[case_id] = mcm.pop("_convergence")

    guf1 = guf1_comparison_loss(x1, x2, u1, u2, r, p=p)
    guf2 = guf2_comparison_loss(x1, x2, u1, u2, r, p=p)
    val = validate_guf(guf1, mcm, ndig=ndig)

    results[f"case_{case_id}"] = {
        "mcm": mcm,
        "guf1": guf1,
        "guf2": guf2,
        "validation": val,
    }

# ── Write JSON results ──────────────────────────────────────────────────

with open("results/comparison_loss.json", "w") as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results/comparison_loss.json")

# ── Generate convergence diagnostic plot ─────────────────────────────────

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('MCM Convergence Diagnostics', fontsize=14)

for col, case_id in enumerate([1, 3]):
    conv = convergence_data[case_id]
    M_vals = conv['M']
    y_vals = conv['y']
    u_vals = conv['u_y']

    axes[0][col].plot(M_vals, y_vals, 'b-', linewidth=1)
    axes[0][col].set_title(f'Case {case_id}: Running Estimate')
    axes[0][col].set_xlabel('Total Monte Carlo trials')
    axes[0][col].set_ylabel('Estimate y')
    axes[0][col].grid(True, alpha=0.3)

    axes[1][col].plot(M_vals, u_vals, 'r-', linewidth=1)
    axes[1][col].set_title(f'Case {case_id}: Running Standard Uncertainty')
    axes[1][col].set_xlabel('Total Monte Carlo trials')
    axes[1][col].set_ylabel('u(y)')
    axes[1][col].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('results/convergence.svg', format='svg')
plt.close()

print("Convergence plot written to /app/results/convergence.svg")
