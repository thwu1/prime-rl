#!/usr/bin/env python3
"""VFS scoring pipeline for branch predictor analysis.

This pipeline reads simulation output data, aggregates per-trace metrics,
computes VFS scores, and performs analysis including Pareto frontier
identification and elasticity computation.

Usage: python3 pipeline.py /app/data
"""

import csv
import json
import math
import os
import sys


# ============================================================
# Reference core parameters
# ============================================================
IPCcbp0 = 8
CPIcbp0 = 0.0315
EPIcbp0 = 1000

# Technology parameters
ALPHA = 1.625
BETA = 4 * ALPHA / (ALPHA + 1) ** 2
GAMMA = 2 * (ALPHA - 1)

# Energy parameters
cbp_energy_ratio = 0.05
EPI0 = EPIcbp0 / cbp_energy_ratio

WPI0 = IPCcbp0 * CPIcbp0

# Pipeline stages from P2 prediction to execution
P2_TO_EXEC_STAGES = 9


# ============================================================
# Metrics aggregation
# ============================================================
def aggregate_predictor_metrics(pred_dir):
    """Read all .out files in pred_dir and compute aggregate IPC, CPI, EPI.

    Returns dict with keys: ipc_cbp, cpi_cbp, epi_cbp
    """
    # First pass: find max latencies
    p1_latency = 0
    p2_latency = 0
    trace_data = []

    for filename in sorted(os.listdir(pred_dir)):
        if not filename.endswith('.out'):
            continue
        filepath = os.path.join(pred_dir, filename)
        with open(filepath, 'r') as f:
            line = f.readline().strip()
            if not line:
                continue
            fields = line.split(',')
            p1_lat = math.ceil(float(fields[9]))
            p2_lat = math.ceil(float(fields[10]))
            p1_latency = max(p1_latency, p1_lat)
            p2_latency = max(p2_latency, p2_lat)
            trace_data.append(fields)

    # Second pass: compute per-trace metrics
    count = 0
    sum_ipc = 0.0
    sum_cpi = 0.0
    sum_epi = 0.0

    for fields in trace_data:
        instructions = float(fields[1])
        npred = float(fields[4])
        extra_cycles = float(fields[5])
        divergences = float(fields[6])
        div_at_end = float(fields[7])
        mispredictions = float(fields[8])
        epi = float(fields[11])

        # Cycle computation
        if p2_latency <= p1_latency:
            cycles = npred * max(1, p2_latency)
        else:
            cycles = (npred * max(1, p1_latency)
                      + divergences * p2_latency
                      - div_at_end * max(1, p1_latency))
        cycles += extra_cycles

        ipc = instructions / cycles
        mpi = mispredictions / instructions
        cpi = mpi * (P2_TO_EXEC_STAGES + p2_latency
                     - max(1, min(p1_latency, p2_latency)))

        count += 1
        sum_ipc += ipc         # NOTE: summing IPC directly
        sum_cpi += cpi
        sum_epi += epi

    avg_ipc = sum_ipc / count  # arithmetic mean of IPC
    avg_cpi = sum_cpi / count
    avg_epi = sum_epi / count

    return {'ipc_cbp': avg_ipc, 'cpi_cbp': avg_cpi, 'epi_cbp': avg_epi}


# ============================================================
# VFS computation
# ============================================================
def compute_vfs(ipc, cpi, epi):
    """Compute VFS score for given predictor metrics."""
    wpi = ipc * cpi
    speedup = (ipc / IPCcbp0) * (1 + WPI0) / (1 + wpi)

    LAMBDA = 1 / (1 + WPI0 / 2) - cbp_energy_ratio

    normalized_epi = ((epi / EPIcbp0) * cbp_energy_ratio
                      + LAMBDA * speedup ** GAMMA)

    vfs = speedup * ALPHA * (
        1 - 2 / (1 + math.sqrt(1 + BETA / (speedup * normalized_epi)))
    )
    return vfs


# ============================================================
# Pareto frontier
# ============================================================
def find_pareto_optimal(metrics):
    """Find Pareto-optimal predictors in (IPC up, CPI down, EPI down) space.

    Args:
        metrics: dict mapping predictor name -> {ipc_cbp, cpi_cbp, epi_cbp}

    Returns:
        (pareto_list, dominated_list) both sorted alphabetically
    """
    names = list(metrics.keys())
    pareto = []
    dominated = []

    for name_i in names:
        is_dominated = False
        pi = metrics[name_i]
        for name_j in names:
            if name_i == name_j:
                continue
            pj = metrics[name_j]
            # j dominates i if j >= i in all dimensions with at least one strict
            if (pj['ipc_cbp'] >= pi['ipc_cbp']
                    and pj['cpi_cbp'] <= pi['cpi_cbp']
                    and pj['epi_cbp'] <= pi['epi_cbp']
                    and (pj['ipc_cbp'] > pi['ipc_cbp']
                         or pj['cpi_cbp'] < pi['cpi_cbp']
                         or pj['epi_cbp'] < pi['epi_cbp'])):
                is_dominated = True
                break
        if is_dominated:
            dominated.append(name_i)
        else:
            pareto.append(name_i)

    return sorted(pareto), sorted(dominated)


# ============================================================
# Elasticity
# ============================================================
def compute_elasticity(ipc, cpi, epi, delta=0.001):
    """Compute VFS elasticity w.r.t. IPC, CPI, EPI.

    Elasticity e_x = (dVFS/dx) * (x/VFS)
    Computed via central finite differences with relative perturbation delta.
    """
    vfs_base = compute_vfs(ipc, cpi, epi)

    # IPC elasticity
    vfs_up = compute_vfs(ipc * (1 + delta), cpi, epi)
    vfs_dn = compute_vfs(ipc * (1 - delta), cpi, epi)
    dvfs_dipc = (vfs_up - vfs_dn) / (2 * delta * ipc)
    e_ipc = dvfs_dipc * ipc / vfs_base

    # CPI elasticity
    vfs_up = compute_vfs(ipc, cpi * (1 + delta), epi)
    vfs_dn = compute_vfs(ipc, cpi * (1 - delta), epi)
    dvfs_dcpi = (vfs_up - vfs_dn) / (2 * delta * cpi)
    e_cpi = dvfs_dcpi * cpi / vfs_base

    # EPI elasticity
    vfs_up = compute_vfs(ipc, cpi, epi * (1 + delta))
    vfs_dn = compute_vfs(ipc, cpi, epi * (1 - delta))
    dvfs_depi = (vfs_up - vfs_dn) / (2 * delta * epi)
    e_epi = dvfs_depi * epi / vfs_base

    return {'ipc': e_ipc, 'cpi': e_cpi, 'epi': e_epi}


# ============================================================
# Main
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 pipeline.py <data_dir>")
        sys.exit(1)

    data_dir = sys.argv[1]

    # Aggregate metrics for each predictor
    all_metrics = {}
    for pred_name in sorted(os.listdir(data_dir)):
        pred_path = os.path.join(data_dir, pred_name)
        if not os.path.isdir(pred_path):
            continue
        all_metrics[pred_name] = aggregate_predictor_metrics(pred_path)

    # Compute VFS scores
    vfs_scores = {}
    for name, m in all_metrics.items():
        vfs_scores[name] = compute_vfs(m['ipc_cbp'], m['cpi_cbp'], m['epi_cbp'])

    # Rank predictors
    ranking = sorted(vfs_scores.keys(), key=lambda x: vfs_scores[x], reverse=True)
    best = ranking[0]

    # Pareto analysis
    pareto, dominated = find_pareto_optimal(all_metrics)

    # Elasticity at best predictor
    bp = all_metrics[best]
    elasticity = compute_elasticity(bp['ipc_cbp'], bp['cpi_cbp'], bp['epi_cbp'])

    # Optimal improvement direction
    abs_elast = {k: abs(v) for k, v in elasticity.items()}
    optimal = max(abs_elast, key=abs_elast.get)

    results = {
        'vfs_scores': {k: round(v, 6) for k, v in vfs_scores.items()},
        'ranking': ranking,
        'best_predictor': best,
        'best_vfs': round(vfs_scores[best], 6),
        'pareto_optimal': pareto,
        'dominated': dominated,
        'elasticity_at_best': {k: round(v, 6) for k, v in elasticity.items()},
        'optimal_improvement': optimal,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
