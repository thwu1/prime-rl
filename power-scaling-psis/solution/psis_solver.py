#!/usr/bin/env python3
"""Power-scaling prior sensitivity analysis with Pareto Smoothed Importance Sampling.


Implements the methodology from:
  - Kallioinen et al. (2023), Statistics and Computing 34(57)
  - Vehtari et al. (2024), JMLR 25(72)
"""

import json
import os
import sys

import numpy as np
from scipy.stats import genpareto


def psis_smooth(log_ratios):
    """Apply Pareto Smoothed Importance Sampling to log importance ratios.

    Returns (smoothed_log_weights, pareto_k_hat).
    """
    S = len(log_ratios)
    lw = log_ratios.copy()

    # Degenerate case: all weights equal
    if np.ptp(lw) < 1e-12:
        return lw, 0.0

    # Stabilize by centering
    max_lw = np.max(lw)
    lw_c = lw - max_lw

    # Number of tail samples
    M = min(int(0.2 * S), int(3.0 * np.sqrt(S)))
    if M < 5:
        return lw, 0.0

    # Sort and identify tail
    order = np.argsort(lw_c)
    sorted_vals = lw_c[order]

    # Threshold: the smallest value in the tail
    threshold_log = sorted_vals[S - M]
    exp_threshold = np.exp(threshold_log)

    # Tail values in exp space
    tail_logs = sorted_vals[S - M:]
    tail_exps = np.exp(tail_logs)

    # Exceedances above threshold
    exceedances = tail_exps - exp_threshold
    pos_mask = exceedances > 1e-300
    n_pos = int(np.sum(pos_mask))

    if n_pos < 5:
        return lw, 0.0

    # Fit Generalized Pareto Distribution to positive exceedances
    pos_exc = exceedances[pos_mask]
    try:
        c, _, scale = genpareto.fit(pos_exc, floc=0)
        if scale <= 0 or not np.isfinite(c) or not np.isfinite(scale):
            return lw, 0.0
    except Exception:
        return lw, 0.0

    k_hat = float(c)

    # Compute expected order statistics from fitted GPD
    probs = (np.arange(1, M + 1) - 0.5) / M
    try:
        gpd_quantiles = genpareto.ppf(probs, c, loc=0, scale=scale)
        if not np.all(np.isfinite(gpd_quantiles)):
            return lw, k_hat
    except Exception:
        return lw, k_hat

    # Smoothed tail in exp space
    smoothed_exp = exp_threshold + gpd_quantiles
    # Truncate at the observed maximum
    smoothed_exp = np.clip(smoothed_exp, 1e-300, tail_exps[-1])

    # Replace tail values in result
    result = lw_c.copy()
    tail_indices = order[S - M:]
    for i in range(M):
        result[tail_indices[i]] = np.log(smoothed_exp[i])

    return result + max_lw, k_hat


def compute_ess(log_weights):
    """Effective sample size from normalized importance weights."""
    w = np.exp(log_weights - np.max(log_weights))
    w /= w.sum()
    return float(1.0 / np.sum(w ** 2))


def compute_weighted_moments(samples, log_weights):
    """Weighted mean and variance from log importance weights."""
    w = np.exp(log_weights - np.max(log_weights))
    w /= w.sum()
    mean = float(np.dot(w, samples))
    var = float(np.dot(w, (samples - mean) ** 2))
    return mean, var


def main():
    # Verify data exists
    data_dir = "/app/data"
    for fname in ["samples.npz", "log_prior_components.npz", "model_spec.json"]:
        fpath = os.path.join(data_dir, fname)
        if not os.path.exists(fpath):
            print(f"ERROR: Required file {fpath} not found", file=sys.stderr)
            sys.exit(1)

    # Load data
    samples = dict(np.load(os.path.join(data_dir, "samples.npz")))
    log_priors = dict(np.load(os.path.join(data_dir, "log_prior_components.npz")))
    with open(os.path.join(data_dir, "model_spec.json")) as f:
        spec = json.load(f)

    alphas = spec["alpha_grid"]
    comps = spec["prior_components"]
    params = spec["parameters"]

    pk_out = {}
    ess_out = {}
    wm_out = {}
    sens_out = {}

    # PSIS analysis for each (prior component, alpha)
    for comp in comps:
        lp = log_priors[comp]
        for alpha in alphas:
            log_w = (alpha - 1.0) * lp
            smoothed_lw, k = psis_smooth(log_w)

            akey = f"{comp}_alpha_{alpha}"
            pk_out[akey] = k
            ess_out[akey] = compute_ess(smoothed_lw)

            for param in params:
                m, v = compute_weighted_moments(samples[param], smoothed_lw)
                wm_out[f"{param}_alpha_{alpha}_prior_{comp}"] = {
                    "mean": m,
                    "var": v,
                }

    # Derivative-based sensitivity: Cov(param, log_prior) / SD(param)
    for param in params:
        s = samples[param]
        sd = float(np.std(s, ddof=1))
        sens_out[param] = {}
        for comp in comps:
            lp = log_priors[comp]
            cov = float(np.cov(s, lp)[0, 1])
            sens_out[param][comp] = cov / sd if sd > 0 else 0.0

    # Write results
    os.makedirs("/app/results", exist_ok=True)
    for name, obj in [
        ("pareto_k", pk_out),
        ("ess", ess_out),
        ("weighted_moments", wm_out),
        ("sensitivity", sens_out),
    ]:
        with open(f"/app/results/{name}.json", "w") as f:
            json.dump(obj, f, indent=2)

    # Summary
    print("Results written to /app/results/")
    print("\n=== Pareto k-hat ===")
    for comp in comps:
        vals = [pk_out[f"{comp}_alpha_{a}"] for a in alphas]
        print(f"  {comp}: {['%.3f' % v for v in vals]}")
    print("\n=== Sensitivity (scalar params) ===")
    for param in spec["scalar_parameters"]:
        print(f"  {param}: {sens_out[param]}")


if __name__ == "__main__":
    main()
