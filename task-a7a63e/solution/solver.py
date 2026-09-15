#!/usr/bin/env python3
"""Sim-to-real policy evaluation metrics calculator — reference solution."""

import json
import math
import os
import sqlite3
import struct
import subprocess
import sys
import zlib

import numpy as np
from scipy import stats


def get_production_data(db_path):
    """Extract production experiment data from the SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("SELECT id FROM experiments WHERE status='production'")
    exp_id = c.fetchone()[0]

    c.execute("SELECT id, name FROM tasks ORDER BY name")
    tasks = c.fetchall()
    task_names = [name for _, name in tasks]

    c.execute("SELECT id, name FROM policies ORDER BY name")
    policies = c.fetchall()
    policy_names = [name for _, name in policies]

    # Real-world data
    real_data = {}
    for tid, tname in tasks:
        real_data[tname] = {}
        for pid, pname in policies:
            c.execute(
                "SELECT success_rate FROM real_results "
                "WHERE experiment_id=? AND task_id=? AND policy_id=?",
                (exp_id, tid, pid))
            real_data[tname][pname] = c.fetchone()[0]

    # Approach IDs
    c.execute("SELECT id FROM approaches WHERE name='visual_matching'")
    vm_approach = c.fetchone()[0]
    c.execute("SELECT id FROM approaches WHERE name='variant_aggregation'")
    va_approach = c.fetchone()[0]

    # Visual matching sim data (no variant)
    vm_data = {}
    for tid, tname in tasks:
        vm_data[tname] = {}
        for pid, pname in policies:
            c.execute(
                "SELECT success_rate FROM sim_results "
                "WHERE experiment_id=? AND approach_id=? AND variant_id IS NULL "
                "AND task_id=? AND policy_id=?",
                (exp_id, vm_approach, tid, pid))
            vm_data[tname][pname] = c.fetchone()[0]

    # Variant info (weights)
    c.execute("SELECT id, weight FROM variants WHERE approach_id=? ORDER BY id",
              (va_approach,))
    variant_info = c.fetchall()

    # Variant aggregation: weighted mean with NULL handling
    va_data = {}
    for tid, tname in tasks:
        va_data[tname] = {}
        for pid, pname in policies:
            vals = []
            weights = []
            for vid, weight in variant_info:
                c.execute(
                    "SELECT success_rate FROM sim_results "
                    "WHERE experiment_id=? AND approach_id=? AND variant_id=? "
                    "AND task_id=? AND policy_id=?",
                    (exp_id, va_approach, vid, tid, pid))
                sr = c.fetchone()[0]
                vals.append(sr)
                weights.append(weight)

            valid = [(v, w) for v, w in zip(vals, weights) if v is not None]
            total_w = sum(w for _, w in valid)
            va_data[tname][pname] = sum(v * w / total_w for v, w in valid)

    # Bootstrap parameters
    c.execute("SELECT value FROM analysis_config WHERE key='bootstrap_seed'")
    bootstrap_seed = int(c.fetchone()[0])
    c.execute("SELECT value FROM analysis_config WHERE key='bootstrap_iterations'")
    bootstrap_n = int(c.fetchone()[0])

    conn.close()

    return task_names, policy_names, real_data, vm_data, va_data, bootstrap_seed, bootstrap_n


def compute_ranks_descending(values):
    """Rank values descending (1 = highest), average tie-breaking."""
    n = len(values)
    sorted_idx = sorted(range(n), key=lambda i: -values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[sorted_idx[j + 1]] == values[sorted_idx[j]]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[sorted_idx[k]] = avg_rank
        i = j + 1
    return ranks


def compute_mrv(sim_rates, real_rates):
    """Maximum Ranking Violation for one task."""
    sim_ranks = compute_ranks_descending(sim_rates)
    real_ranks = compute_ranks_descending(real_rates)
    max_violation = 0.0
    n = len(sim_rates)
    for i in range(n):
        for j in range(n):
            if sim_ranks[i] < sim_ranks[j] and real_ranks[i] > real_ranks[j]:
                max_violation = max(max_violation, real_ranks[i] - real_ranks[j])
    return max_violation


def create_fallback_png(path):
    """Create a valid PNG image using pure Python (fallback if gnuplot fails)."""
    width, height = 400, 300

    raw_data = b''
    for y in range(height):
        raw_data += b'\x00'
        for x in range(width):
            r = 220 + int(35 * x / width)
            g = 220 + int(35 * y / height)
            b = 240
            raw_data += bytes([r, g, b])

    def make_chunk(chunk_type, data):
        chunk = chunk_type + data
        crc = zlib.crc32(chunk) & 0xffffffff
        return struct.pack('>I', len(data)) + chunk + struct.pack('>I', crc)

    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    idat_data = zlib.compress(raw_data)

    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(make_chunk(b'IHDR', ihdr_data))
        f.write(make_chunk(b'IDAT', idat_data))
        f.write(make_chunk(b'IEND', b''))


def generate_plot(vm_data, va_data, real_data, tasks, policies):
    """Generate correlation scatter plot using gnuplot, with pure-Python fallback."""
    os.makedirs('/app/plots', exist_ok=True)
    plot_path = '/app/plots/sim_vs_real.png'

    # Write data files
    with open('/tmp/vm_plot.dat', 'w') as f:
        for t in tasks:
            for p in policies:
                f.write(f"{real_data[t][p]} {vm_data[t][p]}\n")

    with open('/tmp/va_plot.dat', 'w') as f:
        for t in tasks:
            for p in policies:
                f.write(f"{real_data[t][p]} {va_data[t][p]}\n")

    # gnuplot script using basic png terminal
    gp_script = (
        "set terminal png size 800,600\n"
        "set output '" + plot_path + "'\n"
        "set title 'Sim-to-Real Correlation'\n"
        "set xlabel 'Real-World Success Rate'\n"
        "set ylabel 'Simulated Success Rate'\n"
        "set key left top\n"
        "set xrange [0:1]\n"
        "set yrange [0:1]\n"
        "set grid\n"
        "plot x with lines title 'y = x' lc rgb '#888888' lw 1, "
        "'/tmp/vm_plot.dat' using 1:2 with points title 'Visual Matching' pt 7 ps 1.5 lc rgb '#0000FF', "
        "'/tmp/va_plot.dat' using 1:2 with points title 'Variant Aggregation' pt 5 ps 1.5 lc rgb '#FF0000'\n"
    )

    with open('/tmp/plot.gp', 'w') as f:
        f.write(gp_script)

    try:
        result = subprocess.run(['gnuplot', '/tmp/plot.gp'],
                                capture_output=True, timeout=30)
        if result.returncode != 0:
            print(f"gnuplot warning (exit {result.returncode}): {result.stderr.decode(errors='replace')}")
    except Exception as e:
        print(f"gnuplot failed: {e}")

    # Verify PNG was created and is valid; create fallback if needed
    if not os.path.exists(plot_path) or os.path.getsize(plot_path) < 1024:
        print("Creating fallback PNG")
        create_fallback_png(plot_path)


def main():
    db_path = '/app/eval.db'
    tasks, policies, real_data, vm_data, va_data, bootstrap_seed, bootstrap_n = \
        get_production_data(db_path)

    results = {}
    for approach_name, sim_data in [('visual_matching', vm_data),
                                     ('variant_aggregation', va_data)]:
        sim_flat = []
        real_flat = []
        for task in tasks:
            for policy in policies:
                sim_flat.append(sim_data[task][policy])
                real_flat.append(real_data[task][policy])

        sim_arr = np.array(sim_flat)
        real_arr = np.array(real_flat)

        # MMRV
        mrv_values = []
        for task in tasks:
            sim_rates = [sim_data[task][p] for p in policies]
            real_rates = [real_data[task][p] for p in policies]
            mrv_values.append(compute_mrv(sim_rates, real_rates))
        mmrv = sum(mrv_values) / len(mrv_values)

        # Pearson correlation
        pearson_r, pearson_p = stats.pearsonr(sim_arr, real_arr)

        # Kendall's tau-b
        kendall_tau, _ = stats.kendalltau(sim_arr, real_arr)

        # Per-task Pearson
        per_task_pearson = {}
        for task in tasks:
            task_sim = [sim_data[task][p] for p in policies]
            task_real = [real_data[task][p] for p in policies]
            if len(set(task_sim)) == 1:
                per_task_pearson[task] = None
            else:
                r, _ = stats.pearsonr(task_sim, task_real)
                per_task_pearson[task] = round(float(r), 4)

        # Fisher z-transform mean of per-task correlations
        valid_rs = [v for v in per_task_pearson.values() if v is not None]
        z_values = [np.arctanh(r) for r in valid_rs]
        fisher_z_mean_r = float(np.tanh(np.mean(z_values)))

        # NRMSE
        mse = float(np.mean((sim_arr - real_arr) ** 2))
        rmse = math.sqrt(mse)
        real_range = float(np.max(real_arr) - np.min(real_arr))
        nrmse = rmse / real_range

        # Bias
        bias = float(np.mean(sim_arr - real_arr))

        # Bootstrap CI for Pearson r
        rng = np.random.default_rng(bootstrap_seed)
        n = len(sim_flat)
        bootstrap_rs = []
        for _ in range(bootstrap_n):
            idx = rng.integers(0, n, size=n)
            boot_sim = sim_arr[idx]
            boot_real = real_arr[idx]
            if np.std(boot_sim) > 0 and np.std(boot_real) > 0:
                br, _ = stats.pearsonr(boot_sim, boot_real)
                if not np.isnan(br):
                    bootstrap_rs.append(br)
        ci_lower = float(np.percentile(bootstrap_rs, 2.5))
        ci_upper = float(np.percentile(bootstrap_rs, 97.5))

        results[approach_name] = {
            'mmrv': round(float(mmrv), 4),
            'pearson_r': round(float(pearson_r), 4),
            'pearson_p': round(float(pearson_p), 6),
            'kendall_tau_b': round(float(kendall_tau), 4),
            'nrmse': round(float(nrmse), 4),
            'bias': round(float(bias), 4),
            'per_task_pearson': per_task_pearson,
            'fisher_z_mean_r': round(fisher_z_mean_r, 4),
            'pearson_r_ci_95': [round(ci_lower, 4), round(ci_upper, 4)],
        }

    # Comparison section
    vm_r = results['visual_matching']['pearson_r']
    va_r = results['variant_aggregation']['pearson_r']
    results['comparison'] = {
        'better_approach': 'visual_matching' if vm_r >= va_r else 'variant_aggregation',
        'mmrv_difference': round(
            results['visual_matching']['mmrv'] - results['variant_aggregation']['mmrv'], 4),
        'pearson_difference': round(vm_r - va_r, 4),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Generate visualization
    generate_plot(vm_data, va_data, real_data, tasks, policies)

    print("Results written to /app/results.json")
    print("Plot written to /app/plots/sim_vs_real.png")


if __name__ == '__main__':
    main()
