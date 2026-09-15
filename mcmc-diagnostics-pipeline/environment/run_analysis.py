#!/usr/bin/env python3
"""MCMC Diagnostics Analysis Pipeline.

Loads pre-computed chain data from two hierarchical Bayesian models,
computes convergence diagnostics, and generates a comprehensive report.

Usage:
    python3 /app/run_analysis.py

Output:
    /app/output/diagnostics.json
"""
import json
import os
import sys

import numpy as np

from diagnostics import (
    compute_bulk_ess,
    compute_mcse_mean,
    compute_rhat,
    compute_tail_ess,
    compute_waic,
    generate_report,
)


def load_chains(model_dir):
    """Load chain data for a model.

    Parameters
    ----------
    model_dir : str - path to directory containing chain_*.npy files

    Returns
    -------
    np.ndarray, shape (n_chains, n_draws, n_params)
    """
    chains = []
    i = 0
    while os.path.exists(os.path.join(model_dir, f"chain_{i}.npy")):
        chains.append(np.load(os.path.join(model_dir, f"chain_{i}.npy")))
        i += 1
    if not chains:
        raise FileNotFoundError(f"No chain files found in {model_dir}")
    return np.stack(chains)


def analyze_model(model_dir, param_names):
    """Run full convergence diagnostics on a model.

    Parameters
    ----------
    model_dir : str - path to model data directory
    param_names : list of str - parameter names

    Returns
    -------
    dict with diagnostic results
    """
    chains_all = load_chains(model_dir)  # (n_chains, n_draws, n_params)
    n_chains, n_draws, n_params = chains_all.shape

    if n_params != len(param_names):
        raise ValueError(
            f"Chain has {n_params} params but {len(param_names)} names provided"
        )

    rhat = {}
    bulk_ess = {}
    tail_ess = {}
    mcse = {}

    for p in range(n_params):
        name = param_names[p]
        param_chains = chains_all[:, :, p]  # (n_chains, n_draws)

        rhat[name] = float(compute_rhat(param_chains))
        bulk_ess[name] = float(compute_bulk_ess(param_chains))
        tail_ess[name] = float(compute_tail_ess(param_chains))
        mcse[name] = float(compute_mcse_mean(param_chains))

        print(
            f"  {name}: R-hat={rhat[name]:.4f}, "
            f"bulk_ESS={bulk_ess[name]:.0f}, "
            f"tail_ESS={tail_ess[name]:.0f}, "
            f"MCSE={mcse[name]:.4f}"
        )

    # Load log-likelihoods and compute WAIC
    log_lik_path = os.path.join(model_dir, "log_lik.npy")
    log_lik = np.load(log_lik_path)
    waic_result = compute_waic(log_lik)

    print(f"  WAIC={waic_result['waic']:.2f}, p_waic={waic_result['p_waic']:.2f}")

    # Generate convergence report
    report = generate_report(rhat, bulk_ess, tail_ess, param_names)

    return {
        "rhat": rhat,
        "bulk_ess": bulk_ess,
        "tail_ess": tail_ess,
        "mcse_mean": mcse,
        "waic": {k: float(v) for k, v in waic_result.items()},
        "convergence": report,
    }


def main():
    data_dir = "/app/data"
    output_dir = "/app/output"

    # Load parameter names
    with open(os.path.join(data_dir, "param_names.json")) as f:
        param_names = json.load(f)

    results = {}

    # Analyze both models
    for model_name in ["model_a", "model_b"]:
        print(f"\n{'='*60}")
        print(f"Analyzing {model_name}...")
        print(f"{'='*60}")
        model_dir = os.path.join(data_dir, model_name)
        results[model_name] = analyze_model(model_dir, param_names[model_name])

    # Model comparison via WAIC
    waic_a = results["model_a"]["waic"]["waic"]
    waic_b = results["model_b"]["waic"]["waic"]

    results["model_comparison"] = {
        "preferred_model": "model_a" if waic_a < waic_b else "model_b",
        "delta_waic": float(abs(waic_a - waic_b)),
        "waic_model_a": float(waic_a),
        "waic_model_b": float(waic_b),
    }

    print(f"\n{'='*60}")
    print("Model Comparison")
    print(f"{'='*60}")
    print(f"  WAIC Model A: {waic_a:.2f}")
    print(f"  WAIC Model B: {waic_b:.2f}")
    print(f"  Preferred: {results['model_comparison']['preferred_model']}")

    # Write output
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "diagnostics.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to {output_path}")


if __name__ == "__main__":
    main()
