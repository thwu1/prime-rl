#!/usr/bin/env python3
"""
Sim-to-real transfer diagnostic pipeline.

Loads multi-source evaluation data (CSVs + SQLite), performs statistical
analyses, and writes results to /app/results.json.
"""

import csv
import json
import sqlite3

import numpy as np
from scipy import stats


def load_data():
    """Load data from CSV files and SQLite database."""
    conn = sqlite3.connect("/app/data/experiment.db")
    c = conn.cursor()

    c.execute("SELECT source, n_episodes FROM trial_counts")
    trial_counts = dict(c.fetchall())

    c.execute("SELECT param_name, param_value FROM analysis_params")
    analysis_params = {name: value for name, value in c.fetchall()}

    c.execute("SELECT variant_name FROM variant_info ORDER BY variant_id")
    variants = [row[0] for row in c.fetchall()]

    conn.close()

    sim_results = {}
    policies_ordered = []
    tasks_ordered = []

    for variant in variants:
        with open(f"/app/data/sim/{variant}.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pol = row["policy"]
                tsk = row["task"]
                rate = float(row["success_rate"])
                sim_results.setdefault(pol, {}).setdefault(tsk, {})[variant] = rate
                if pol not in policies_ordered:
                    policies_ordered.append(pol)
                if tsk not in tasks_ordered:
                    tasks_ordered.append(tsk)

    real_results = {}
    with open("/app/data/real_results.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            real_results.setdefault(row["policy"], {})[row["task"]] = float(
                row["success_rate"]
            )

    return (
        sim_results,
        real_results,
        policies_ordered,
        tasks_ordered,
        variants,
        trial_counts,
        analysis_params,
    )


def build_matrices(sim_results, real_results, policies, tasks, variants):
    """Build numpy arrays from structured data."""
    n_pol = len(policies)
    n_tsk = len(tasks)
    n_var = len(variants)

    sim_matrix = np.zeros((n_pol, n_tsk, n_var))
    real_matrix = np.zeros((n_pol, n_tsk))

    for pi, policy in enumerate(policies):
        for ti, task in enumerate(tasks):
            for vi, variant in enumerate(variants):
                sim_matrix[pi, ti, vi] = sim_results[policy][task][variant]
            real_matrix[pi, ti] = real_results[policy][task]

    return sim_matrix, real_matrix


def compute_mmrv(sim_matrix):
    """MMRV: max over variants per task, then mean over tasks per policy."""
    return sim_matrix.max(axis=2).mean(axis=1)


def compute_task_correlations(sim_matrix, real_matrix, tasks):
    """Per-task Pearson r between max-variant sim and real scores."""
    max_sim = sim_matrix.max(axis=2)
    task_corrs = {}
    for ti, task in enumerate(tasks):
        r, _ = stats.pearsonr(max_sim[:, ti], real_matrix[:, ti])
        task_corrs[task] = float(r)
    return task_corrs


def fisher_z_mean(task_corrs):
    """Aggregate correlations via Fisher z-transform."""
    z_vals = [np.arctanh(r) for r in task_corrs.values()]
    mean_z = np.mean(z_vals)
    return float(np.tanh(mean_z))


def anova_decomposition(sim_matrix, real_matrix):
    """Main-effects variance decomposition of sim-real discrepancy."""
    n_pol, n_tsk, n_var = sim_matrix.shape
    discrepancy = sim_matrix - real_matrix[:, :, np.newaxis]

    grand_mean = discrepancy.mean()
    ss_total = np.sum((discrepancy - grand_mean) ** 2)

    policy_means = discrepancy.mean(axis=(1, 2))
    ss_policy = n_tsk * n_var * np.sum((policy_means - grand_mean) ** 2)

    task_means = discrepancy.mean(axis=(0, 2))
    ss_task = n_pol * n_var * np.sum((task_means - grand_mean) ** 2)

    variant_means = discrepancy.mean(axis=(0, 1))
    ss_variant = n_pol * n_tsk * np.sum((variant_means - grand_mean) ** 2)

    ss_residual = ss_total - ss_policy - ss_task - ss_variant

    eta_sq = {
        "policy": float(ss_policy / ss_total),
        "task": float(ss_task / ss_total),
        "variant": float(ss_variant / ss_total),
    }

    df_pol = n_pol - 1
    df_tsk = n_tsk - 1
    df_var = n_var - 1
    df_resid = n_pol * n_tsk * n_var - 1 - df_pol - df_tsk - df_var
    ms_resid = ss_residual / df_resid

    f_stats = {
        "policy": float((ss_policy / df_pol) / ms_resid),
        "task": float((ss_task / df_tsk) / ms_resid),
        "variant": float((ss_variant / df_var) / ms_resid),
    }

    return eta_sq, f_stats


def deming_regression(sim_matrix, real_matrix, variants, lam):
    """Per-variant Deming regression with known error ratio."""
    calibration = {}
    for vi, variant in enumerate(variants):
        x = sim_matrix[:, :, vi].flatten()
        y = real_matrix.flatten()

        x_bar = x.mean()
        y_bar = y.mean()

        s_xx = np.sum((x - x_bar) ** 2)
        s_yy = np.sum((y - y_bar) ** 2)
        s_xy = np.sum((x - x_bar) * (y - y_bar))

        beta = (
            s_yy
            - lam * s_xx
            + np.sqrt((s_yy - lam * s_xx) ** 2 + 4 * lam * s_xy**2)
        ) / (2 * s_xy)
        alpha = y_bar - beta * x_bar

        calibration[variant] = {"slope": float(beta), "intercept": float(alpha)}

    return calibration


def influence_diagnostics(mmrv_scores, real_means, policies):
    """Regression diagnostics for OLS model."""
    n = len(policies)
    p = 2

    X = np.column_stack([np.ones(n), mmrv_scores])
    y = real_means

    H = X @ np.linalg.inv(X.T @ X) @ X.T
    h = np.diag(H)

    beta = np.linalg.inv(X.T @ X) @ X.T @ y
    y_hat = X @ beta
    e = y - y_hat
    MSE = np.sum(e**2) / (n - p)

    cooks_d = (e**2 * h) / (p * MSE * (1 - h) ** 2)

    s_sq_i = ((n - p) * MSE - e**2 / (1 - h)) / (n - p - 1)
    t_star = e / (np.sqrt(np.maximum(s_sq_i, 1e-15)) * np.sqrt(1 - h))
    dffits = t_star * np.sqrt(h / (1 - h))

    diag = {}
    for i, pol in enumerate(policies):
        diag[pol] = {
            "leverage": float(h[i]),
            "cooks_d": float(cooks_d[i]),
            "dffits": float(dffits[i]),
        }

    return diag, y_hat


def permutation_test(mmrv_scores, real_means, n_perm, seed):
    """One-sided permutation test for correlation."""
    rng = np.random.RandomState(seed)
    observed_r, _ = stats.pearsonr(mmrv_scores, real_means)

    count_ge = 0
    for _ in range(n_perm):
        perm_real = rng.permutation(real_means)
        r_perm, _ = stats.pearsonr(mmrv_scores, perm_real)
        if r_perm >= observed_r:
            count_ge += 1

    p_value = (count_ge + 1) / (n_perm + 1)
    return float(p_value)


def jackknife_plus_conformal(mmrv_scores, real_means, policies, alpha):
    """Distribution-free prediction intervals via leave-one-out."""
    n = len(policies)
    X = np.column_stack([np.ones(n), mmrv_scores])
    y = real_means

    beta_full = np.linalg.inv(X.T @ X) @ X.T @ y
    y_hat_full = X @ beta_full

    loo_residuals = np.zeros(n)
    loo_betas = []
    for j in range(n):
        mask = np.ones(n, dtype=bool)
        mask[j] = False
        X_j = X[mask]
        y_j = y[mask]
        beta_j = np.linalg.inv(X_j.T @ X_j) @ X_j.T @ y_j
        loo_betas.append(beta_j)
        loo_residuals[j] = y[j] - X[j] @ beta_j

    intervals = {}
    for i in range(n):
        adj_low = []
        adj_high = []
        for j in range(n):
            pred_j_at_i = X[i] @ loo_betas[j]
            R_j = abs(loo_residuals[j])
            adj_low.append(pred_j_at_i - R_j)
            adj_high.append(pred_j_at_i + R_j)

        q_low = float(np.quantile(adj_low, alpha / 2))
        q_high = float(np.quantile(adj_high, 1 - alpha / 2))

        intervals[policies[i]] = {
            "predicted": float(y_hat_full[i]),
            "lower": q_low,
            "upper": q_high,
        }

    return intervals


def main():
    (
        sim_results,
        real_results,
        policies,
        tasks,
        variants,
        trial_counts,
        analysis_params,
    ) = load_data()

    sim_matrix, real_matrix = build_matrices(
        sim_results, real_results, policies, tasks, variants
    )

    # Derive error variance ratio from trial counts
    lam = trial_counts["simulation"] / trial_counts["real_world"]

    mmrv_scores = compute_mmrv(sim_matrix)
    real_means = real_matrix.mean(axis=1)

    task_corrs = compute_task_correlations(sim_matrix, real_matrix, tasks)
    fisher_r = fisher_z_mean(task_corrs)

    agg_r, _ = stats.pearsonr(mmrv_scores, real_means)

    eta_sq, f_stats = anova_decomposition(sim_matrix, real_matrix)

    deming_cal = deming_regression(sim_matrix, real_matrix, variants, lam=lam)

    infl_diag, _ = influence_diagnostics(mmrv_scores, real_means, policies)

    perm_p = permutation_test(
        mmrv_scores,
        real_means,
        n_perm=int(analysis_params["n_permutations"]),
        seed=int(analysis_params["permutation_seed"]),
    )

    conf_intervals = jackknife_plus_conformal(
        mmrv_scores,
        real_means,
        policies,
        alpha=1.0 - analysis_params["confidence_level"],
    )

    results = {
        "mmrv_scores": {p: float(mmrv_scores[i]) for i, p in enumerate(policies)},
        "real_mean_scores": {p: float(real_means[i]) for i, p in enumerate(policies)},
        "task_correlations": task_corrs,
        "fisher_z_mean_r": fisher_r,
        "anova_eta_squared": eta_sq,
        "anova_f_stats": f_stats,
        "deming_calibration": deming_cal,
        "influence_diagnostics": infl_diag,
        "permutation_p_value": perm_p,
        "conformal_intervals": conf_intervals,
        "aggregate_pearson_r": float(agg_r),
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
