#!/usr/bin/env python3
"""Complete VFS analysis pipeline — reference solution.


Builds the full analysis: SQLite database, VFS scoring, Pareto analysis,
gnuplot visualization, workload-weighted VFS, per-category VFS, rank stability,
efficiency analysis, and results.json output.
"""

import json
import math
import os
import sqlite3
import subprocess
import sys

# ============================================================
# VFS constants
# ============================================================
IPCBP0 = 8
CPICBP0 = 0.0315
EPICBP0 = 1000
ALPHA = 1.625
BETA = 4 * ALPHA / (ALPHA - 1) ** 2
GAMMA = 2 / (ALPHA - 1)
CBP_ENERGY_RATIO = 0.05
WPI0 = IPCBP0 * CPICBP0
P2_TO_EXEC_STAGES = 9

DATA_DIR = '/app/data'


def read_all_traces(pred_dir):
    """Read all .out files, return list of field arrays."""
    data = []
    for fn in sorted(os.listdir(pred_dir)):
        if fn.endswith('.out'):
            with open(os.path.join(pred_dir, fn)) as f:
                line = f.readline().strip()
                if line:
                    data.append(line.split(','))
    return data


def get_latencies(data):
    """Compute max ceil P1/P2 latencies across all traces."""
    p1, p2 = 0, 0
    for fields in data:
        p1 = max(p1, math.ceil(float(fields[9])))
        p2 = max(p2, math.ceil(float(fields[10])))
    return p1, p2


def per_trace_metrics(fields, p1, p2):
    """Compute IPC, CPI, EPI for a single trace."""
    instr = float(fields[1])
    npred = float(fields[4])
    extra = float(fields[5])
    div = float(fields[6])
    div_end = float(fields[7])
    misps = float(fields[8])
    epi = float(fields[11])

    if p2 <= p1:
        cycles = npred * max(1, p2)
    else:
        cycles = npred * max(1, p1) + div * p2 - div_end * max(1, p1)
    cycles += extra

    ipc = instr / cycles
    mpi = misps / instr
    cpi = mpi * (P2_TO_EXEC_STAGES + p2 - max(1, min(p1, p2)))
    return ipc, cpi, epi, fields[0]


def harmonic_mean(values):
    """Compute harmonic mean of a list of values."""
    return len(values) / sum(1.0 / v for v in values)


def aggregate(per_trace_list):
    """Aggregate per-trace (ipc, cpi, epi, name) tuples."""
    ipcs = [m[0] for m in per_trace_list]
    cpis = [m[1] for m in per_trace_list]
    epis = [m[2] for m in per_trace_list]
    return harmonic_mean(ipcs), sum(cpis) / len(cpis), sum(epis) / len(epis)


def compute_vfs(ipc, cpi, epi):
    """Compute VFS score."""
    wpi = ipc * cpi
    s = (ipc / IPCBP0) * (1 + WPI0) / (1 + wpi)
    lam = 1 / (1 + WPI0 / 2) - CBP_ENERGY_RATIO
    e_hat = ((epi / EPICBP0) * CBP_ENERGY_RATIO + lam * s ** GAMMA) * (1 + wpi / 2)
    return s * ALPHA * (1 - 2 / (1 + math.sqrt(1 + BETA / (s * e_hat))))


def find_pareto(metrics_dict):
    """Find Pareto-optimal predictors in (IPC up, CPI down, EPI down) space."""
    names = list(metrics_dict.keys())
    pareto, dominated = [], []
    for i in names:
        dom = False
        pi = metrics_dict[i]
        for j in names:
            if i == j:
                continue
            pj = metrics_dict[j]
            if (pj['ipc'] >= pi['ipc'] and pj['cpi'] <= pi['cpi']
                    and pj['epi'] <= pi['epi']
                    and (pj['ipc'] > pi['ipc'] or pj['cpi'] < pi['cpi']
                         or pj['epi'] < pi['epi'])):
                dom = True
                break
        (dominated if dom else pareto).append(i)
    return sorted(pareto), sorted(dominated)


def compute_elasticity(ipc, cpi, epi, delta=0.001):
    """Compute VFS elasticity via central finite differences."""
    vb = compute_vfs(ipc, cpi, epi)
    result = {}
    params = {'ipc': ipc, 'cpi': cpi, 'epi': epi}

    for label in ['ipc', 'cpi', 'epi']:
        args_up = dict(params)
        args_up[label] *= (1 + delta)
        args_dn = dict(params)
        args_dn[label] *= (1 - delta)

        vu = compute_vfs(args_up['ipc'], args_up['cpi'], args_up['epi'])
        vd = compute_vfs(args_dn['ipc'], args_dn['cpi'], args_dn['epi'])

        dvdx = (vu - vd) / (2 * delta * params[label])
        result[label] = dvdx * params[label] / vb

    return result


def main():
    # Load trace metadata
    with open('/app/traces.json') as f:
        trace_meta = json.load(f)

    trace_to_cat = {}
    cat_weights = {}
    for cat, info in trace_meta['categories'].items():
        cat_weights[cat] = info['weight']
        for t in info['traces']:
            trace_to_cat[t] = cat

    # Set up SQLite database
    db_path = '/app/analysis.db'
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)

    conn.execute('''CREATE TABLE raw_traces (
        predictor TEXT,
        trace_name TEXT,
        category TEXT,
        instructions INTEGER,
        branches INTEGER,
        conditional_branches INTEGER,
        npred INTEGER,
        extra_cycles INTEGER,
        divergences INTEGER,
        divergences_at_end INTEGER,
        mispredictions INTEGER,
        p1_latency REAL,
        p2_latency REAL,
        epi INTEGER,
        computed_ipc REAL,
        computed_cpi REAL,
        PRIMARY KEY (predictor, trace_name)
    )''')

    conn.execute('''CREATE TABLE predictor_metrics (
        predictor TEXT PRIMARY KEY,
        p1_ceil INTEGER,
        p2_ceil INTEGER,
        ipc_cbp REAL,
        cpi_cbp REAL,
        epi_cbp REAL,
        vfs_score REAL,
        weighted_ipc REAL,
        weighted_cpi REAL,
        weighted_epi REAL,
        weighted_vfs REAL
    )''')

    # Process each predictor
    all_std = {}
    all_weighted = {}
    vfs_scores = {}
    weighted_vfs_scores = {}
    per_category_vfs = {}

    for pred in sorted(os.listdir(DATA_DIR)):
        pred_path = os.path.join(DATA_DIR, pred)
        if not os.path.isdir(pred_path):
            continue

        data = read_all_traces(pred_path)
        p1, p2 = get_latencies(data)

        per_trace = [per_trace_metrics(f, p1, p2) for f in data]

        # Insert raw data into SQLite
        for fields in data:
            ipc_t, cpi_t, epi_t, tname = per_trace_metrics(fields, p1, p2)
            cat = trace_to_cat.get(tname, 'unknown')
            conn.execute(
                'INSERT INTO raw_traces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (pred, tname, cat,
                 int(fields[1]), int(fields[2]), int(fields[3]),
                 int(fields[4]), int(fields[5]), int(fields[6]),
                 int(fields[7]), int(fields[8]),
                 float(fields[9]), float(fields[10]), int(fields[11]),
                 ipc_t, cpi_t))

        # Standard aggregation
        ipc, cpi, epi = aggregate(per_trace)
        all_std[pred] = {'ipc': ipc, 'cpi': cpi, 'epi': epi}
        vfs = compute_vfs(ipc, cpi, epi)
        vfs_scores[pred] = vfs

        # Workload-weighted aggregation
        cat_data = {}
        for m in per_trace:
            cat = trace_to_cat.get(m[3], 'unknown')
            cat_data.setdefault(cat, []).append(m)

        cat_agg = {}
        for cat, metrics in cat_data.items():
            cat_agg[cat] = aggregate(metrics)

        sum_w_inv_ipc = sum(cat_weights[c] / cat_agg[c][0] for c in cat_agg)
        sum_w_cpi = sum(cat_weights[c] * cat_agg[c][1] for c in cat_agg)
        sum_w_epi = sum(cat_weights[c] * cat_agg[c][2] for c in cat_agg)

        w_ipc = 1.0 / sum_w_inv_ipc
        w_cpi = sum_w_cpi
        w_epi = sum_w_epi
        all_weighted[pred] = {'ipc': w_ipc, 'cpi': w_cpi, 'epi': w_epi}
        w_vfs = compute_vfs(w_ipc, w_cpi, w_epi)
        weighted_vfs_scores[pred] = w_vfs

        # Per-category VFS
        pred_cat_vfs = {}
        for cat, (c_ipc, c_cpi, c_epi) in cat_agg.items():
            pred_cat_vfs[cat] = compute_vfs(c_ipc, c_cpi, c_epi)
        per_category_vfs[pred] = pred_cat_vfs

        # Insert into metrics table
        conn.execute(
            'INSERT INTO predictor_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (pred, p1, p2, ipc, cpi, epi, vfs, w_ipc, w_cpi, w_epi, w_vfs))

    conn.commit()
    conn.close()

    # Rankings
    ranking = sorted(vfs_scores, key=vfs_scores.get, reverse=True)
    best = ranking[0]
    weighted_ranking = sorted(weighted_vfs_scores,
                              key=weighted_vfs_scores.get, reverse=True)

    # Pareto analysis
    pareto, dominated = find_pareto(all_std)

    # Elasticity at best predictor
    bp = all_std[best]
    elasticity = compute_elasticity(bp['ipc'], bp['cpi'], bp['epi'])
    abs_e = {k: abs(v) for k, v in elasticity.items()}
    optimal = max(abs_e, key=abs_e.get)

    # Category specialists
    category_specialists = {}
    for cat in cat_weights:
        best_pred = max(
            (p for p in per_category_vfs if cat in per_category_vfs[p]),
            key=lambda p: per_category_vfs[p][cat]
        )
        category_specialists[cat] = best_pred

    # Rank stability
    rank_stability = {}
    for i, pred in enumerate(ranking):
        std_rank = i + 1
        w_rank = weighted_ranking.index(pred) + 1
        shift = abs(std_rank - w_rank)
        if shift <= 1:
            cls = "stable"
        elif shift <= 3:
            cls = "workload-sensitive"
        else:
            cls = "highly-sensitive"
        rank_stability[pred] = {
            "standard_rank": std_rank,
            "weighted_rank": w_rank,
            "shift": shift,
            "classification": cls
        }

    # Most efficient (highest VFS / EPI ratio)
    most_efficient = max(vfs_scores,
                         key=lambda n: vfs_scores[n] / all_std[n]['epi'])

    # Generate gnuplot visualization
    gp_data = '/app/pareto_data.txt'
    with open(gp_data, 'w') as f:
        for name in sorted(vfs_scores.keys()):
            epi_val = all_std[name]['epi']
            vfs_val = vfs_scores[name]
            is_pareto = 1 if name in pareto else 0
            f.write(f"{epi_val}\t{vfs_val}\t{name}\t{is_pareto}\n")

    gp_script = '/app/pareto.gp'
    with open(gp_script, 'w') as f:
        f.write("set terminal png size 900,600 noenhanced\n")
        f.write("set output '/app/designspace.png'\n")
        f.write("set title 'Branch Predictor Design Space: VFS Score vs Energy'\n")
        f.write("set xlabel 'EPI (fJ/instruction)'\n")
        f.write("set ylabel 'VFS Score'\n")
        f.write("set grid\n")
        f.write("set key outside right top\n")
        f.write("\n")
        f.write("plot '/app/pareto_data.txt' using ($4==1 ? $1 : 1/0):2 "
                "with points pt 7 ps 2 lc rgb '#2166ac' "
                "title 'Pareto-optimal', \\\n")
        f.write("     '/app/pareto_data.txt' using ($4==0 ? $1 : 1/0):2 "
                "with points pt 6 ps 2 lc rgb '#b2182b' "
                "title 'Dominated', \\\n")
        f.write("     '/app/pareto_data.txt' using 1:2:3 "
                "with labels offset 0,1.2 notitle\n")

    subprocess.run(['gnuplot', gp_script], check=True)

    # Write results.json
    results = {
        'vfs_scores': {k: round(v, 6) for k, v in vfs_scores.items()},
        'ranking': ranking,
        'best_predictor': best,
        'best_vfs': round(vfs_scores[best], 6),
        'pareto_optimal': pareto,
        'dominated': dominated,
        'elasticity_at_best': {k: round(v, 6) for k, v in elasticity.items()},
        'optimal_improvement': optimal,
        'weighted_vfs_scores': {k: round(v, 6)
                                for k, v in weighted_vfs_scores.items()},
        'weighted_ranking': weighted_ranking,
        'per_category_vfs': {
            pred: {cat: round(v, 6) for cat, v in cats.items()}
            for pred, cats in per_category_vfs.items()
        },
        'category_specialists': category_specialists,
        'rank_stability': rank_stability,
        'most_efficient': most_efficient,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
