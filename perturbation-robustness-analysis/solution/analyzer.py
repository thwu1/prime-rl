#!/usr/bin/env python3
"""
Reference implementation: Perturbation robustness analysis pipeline.

Reads raw rollout data from SQLite, audits for data quality issues,
and produces a comprehensive statistical report.
"""

import json
import math
import os
import sqlite3

import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# Data loading — with deduplication and calibration filtering
# ---------------------------------------------------------------------------

def load_sim_data(db_path='/app/data/benchmark.db'):
    """Load simulation data with deduplication of duplicate rollout entries."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        SELECT model, perturbation_id, task_id,
               CAST(SUM(success) AS REAL) / COUNT(*) as success_rate
        FROM (
            SELECT DISTINCT model, task_id, perturbation_id, rollout_id, success
            FROM rollouts
        )
        GROUP BY model, perturbation_id, task_id
    ''')
    data = {}
    for model, pert_id, task_id, rate in c.fetchall():
        data.setdefault((model, pert_id), {})[task_id] = rate
    conn.close()
    return data


def load_real_data(db_path='/app/data/benchmark.db'):
    """Load real-world data, excluding calibration trials (trial_id < 0)."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        SELECT model, task_id,
               CAST(SUM(success) AS REAL) / COUNT(*) as success_rate
        FROM real_trials
        WHERE trial_id >= 0
        GROUP BY model, task_id
    ''')
    data = {}
    for model, task_id, rate in c.fetchall():
        data.setdefault(model, {})[task_id] = rate
    conn.close()
    return data


def load_taxonomy(db_path='/app/data/benchmark.db'):
    """Load perturbation taxonomy from database metadata tables."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    categories = {}
    perturbations = {}
    c.execute(
        'SELECT perturbation_id, name, category FROM perturbation_meta')
    for pid, pname, pcat in c.fetchall():
        perturbations[str(pid)] = {'name': pname, 'category': pcat}
        if pcat != 'Baseline':
            categories.setdefault(pcat, []).append(pid)
    conn.close()
    return {'categories': categories, 'perturbations': perturbations}


# ---------------------------------------------------------------------------
# Statistical methods
# ---------------------------------------------------------------------------

def hedges_g_paired(default_rates, pert_rates):
    """Paired Hedges' g with small-sample correction."""
    diffs = np.array(default_rates) - np.array(pert_rates)
    n = len(diffs)
    if n <= 1:
        return 0.0
    sd = np.std(diffs, ddof=1)
    if sd < 1e-15:
        return 0.0
    d_z = np.mean(diffs) / sd
    df = n - 1
    J = 1.0 - 3.0 / (4.0 * df - 1.0)
    return float(J * d_z)


def bca_bootstrap_ci(default_rates, pert_rates,
                     n_bootstrap=10000, alpha=0.05, seed=42):
    """BCa (bias-corrected and accelerated) bootstrap 95% CI."""
    rng = np.random.RandomState(seed)
    d_arr = np.array(default_rates, dtype=np.float64)
    p_arr = np.array(pert_rates, dtype=np.float64)
    n = len(d_arr)

    theta_hat = hedges_g_paired(default_rates, pert_rates)

    # Bootstrap distribution
    theta_boot = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        idx = rng.randint(0, n, size=n)
        theta_boot[i] = hedges_g_paired(d_arr[idx], p_arr[idx])

    # Bias correction z0
    prop = np.mean(theta_boot < theta_hat)
    prop = np.clip(prop, 1e-10, 1.0 - 1e-10)
    z0 = stats.norm.ppf(prop)

    # Acceleration constant a (jackknife)
    theta_jack = np.empty(n)
    for i in range(n):
        d_jack = np.delete(d_arr, i)
        p_jack = np.delete(p_arr, i)
        theta_jack[i] = hedges_g_paired(d_jack, p_jack)

    theta_bar = np.mean(theta_jack)
    diff = theta_bar - theta_jack
    numerator = np.sum(diff ** 3)
    denominator = 6.0 * np.sum(diff ** 2) ** 1.5
    a_acc = numerator / denominator if abs(denominator) > 1e-15 else 0.0

    # Adjusted percentiles
    z_lo = stats.norm.ppf(alpha / 2.0)
    z_hi = stats.norm.ppf(1.0 - alpha / 2.0)

    def adj_percentile(z_val):
        num = z0 + z_val
        den = 1.0 - a_acc * num
        if abs(den) < 1e-15:
            return stats.norm.cdf(z_val)
        return float(stats.norm.cdf(z0 + num / den))

    a1 = np.clip(adj_percentile(z_lo),
                 0.5 / n_bootstrap, 1.0 - 0.5 / n_bootstrap)
    a2 = np.clip(adj_percentile(z_hi),
                 0.5 / n_bootstrap, 1.0 - 0.5 / n_bootstrap)

    ci_lo = float(np.percentile(theta_boot, 100.0 * a1))
    ci_hi = float(np.percentile(theta_boot, 100.0 * a2))

    return ci_lo, ci_hi


def spearman_with_fisher_ci(sim_vals, real_vals, alpha=0.05):
    """Spearman rank correlation with Fisher z-transform 95% CI."""
    rho, p_value = stats.spearmanr(sim_vals, real_vals)
    n = len(sim_vals)

    z = np.arctanh(rho)
    se = 1.0 / math.sqrt(n - 3)
    z_crit = stats.norm.ppf(1.0 - alpha / 2.0)
    ci_lo = float(np.tanh(z - z_crit * se))
    ci_hi = float(np.tanh(z + z_crit * se))

    return {
        'spearman_rho': float(rho),
        'p_value': float(p_value),
        'fisher_z_ci_lower': ci_lo,
        'fisher_z_ci_upper': ci_hi,
        'n_pairs': n,
    }


def compute_cri(sim_data, models, task_ids, pert_ids):
    """Composite Robustness Index per model."""
    cris = {}
    for model in models:
        all_rel_drops = []
        per_pert_means = []

        for pid in pert_ids:
            drops = []
            for tid in task_ids:
                d_rate = sim_data[(model, 0)][tid]
                p_rate = sim_data[(model, pid)][tid]
                rel_drop = ((d_rate - p_rate) / d_rate
                            if d_rate > 0 else 0.0)
                all_rel_drops.append(rel_drop)
                drops.append(rel_drop)
            per_pert_means.append(float(np.mean(drops)))

        mean_drop = float(np.mean(all_rel_drops))

        sorted_desc = sorted(all_rel_drops, reverse=True)
        k = max(1, math.ceil(0.10 * len(sorted_desc)))
        cvar_10 = float(np.mean(sorted_desc[:k]))

        m = float(np.mean(per_pert_means))
        s = float(np.std(per_pert_means, ddof=1))
        sensitivity_cv = s / abs(m) if abs(m) > 1e-10 else 0.0

        cri = (0.5 * (1.0 - mean_drop)
               + 0.3 * (1.0 - cvar_10)
               + 0.2 * (1.0 - sensitivity_cv))
        cris[model] = float(cri)

    return cris


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    sim_data = load_sim_data()
    real_data = load_real_data()
    taxonomy = load_taxonomy()

    models = sorted(set(k[0] for k in sim_data))
    task_ids = sorted(sim_data[next(iter(sim_data))].keys())
    pert_ids = sorted(set(k[1] for k in sim_data if k[1] != 0))

    # --- Effect sizes + BCa CIs ---
    effect_sizes = {}
    for model in models:
        default_rates = [sim_data[(model, 0)][tid] for tid in task_ids]
        for pid in pert_ids:
            pert_rates = [sim_data[(model, pid)][tid] for tid in task_ids]
            g = hedges_g_paired(default_rates, pert_rates)
            ci_lo, ci_hi = bca_bootstrap_ci(default_rates, pert_rates)
            pert_info = taxonomy['perturbations'][str(pid)]
            effect_sizes[f"{model}_pert{pid}"] = {
                'hedges_g': g,
                'ci_lower': ci_lo,
                'ci_upper': ci_hi,
                'perturbation': pert_info['name'],
                'category': pert_info['category'],
            }

    # --- Category aggregates ---
    category_aggregates = {}
    for model in models:
        agg = {}
        for cat_name, cat_pids in taxonomy['categories'].items():
            gs = [effect_sizes[f"{model}_pert{p}"]['hedges_g']
                  for p in cat_pids
                  if f"{model}_pert{p}" in effect_sizes]
            if gs:
                agg[cat_name] = float(np.mean(gs))
        category_aggregates[model] = agg

    # --- Real-to-sim Spearman correlation ---
    sim_vals, real_vals = [], []
    for model in models:
        for tid in task_ids:
            if model in real_data and tid in real_data[model]:
                sim_vals.append(sim_data[(model, 0)][tid])
                real_vals.append(real_data[model][tid])
    correlation = spearman_with_fisher_ci(sim_vals, real_vals)

    # --- Composite Robustness Index ---
    cri = compute_cri(sim_data, models, task_ids, pert_ids)

    # --- Output ---
    report = {
        'effect_sizes': effect_sizes,
        'category_aggregates': category_aggregates,
        'real_to_sim_correlation': correlation,
        'composite_robustness_index': cri,
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Analysis complete. Report written to /app/output/report.json")


if __name__ == '__main__':
    main()
