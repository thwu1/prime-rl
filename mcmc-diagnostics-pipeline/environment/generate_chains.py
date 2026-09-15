#!/usr/bin/env python3
"""Generate synthetic MCMC chain data for convergence diagnostics analysis.

Creates chain data mimicking two hierarchical Bayesian models:
- Model A: Centered parameterization (with convergence pathologies)
- Model B: Non-centered parameterization (well-converged)

The data is structured to test MCMC diagnostic implementations:
- Model A's log_tau parameter has chains stuck at different levels (funnel geometry)
- Model A has one observation with extreme log-likelihoods (tests numerical stability)
- Model B has well-mixing chains for all parameters
"""
import json
import os

import numpy as np


def ar1(n, rho, sigma, mu, rng):
    """Generate a stationary AR(1) process.

    Parameters
    ----------
    n : int - number of draws
    rho : float - autocorrelation coefficient
    sigma : float - marginal standard deviation
    mu : float - stationary mean
    rng : np.random.RandomState
    """
    x = np.empty(n)
    innov_sd = sigma * np.sqrt(max(1.0 - rho ** 2, 1e-10))
    x[0] = rng.normal(mu, sigma)
    for t in range(1, n):
        x[t] = mu + rho * (x[t - 1] - mu) + rng.normal(0, innov_sd)
    return x


N_DRAWS = 2000
N_CHAINS = 4
SEED = 12345

# ========== Model A: Centered parameterization ==========
os.makedirs("/app/data/model_a", exist_ok=True)

param_names_a = ["mu", "log_tau"] + [f"theta_{i}" for i in range(8)]

for c in range(N_CHAINS):
    rng = np.random.RandomState(SEED + c)
    chain = np.empty((N_DRAWS, 10))

    # mu: good mixing across all chains (same stationary mean)
    chain[:, 0] = ar1(N_DRAWS, 0.4, 1.5, 4.0, rng)

    # log_tau: POOR convergence — chains 0,1 stuck at high mean, chains 2,3 at low mean
    # This mimics the funnel geometry in centered hierarchical models
    if c < 2:
        chain[:, 1] = ar1(N_DRAWS, 0.95, 0.8, 1.8, rng)
    else:
        chain[:, 1] = ar1(N_DRAWS, 0.95, 0.8, -0.5, rng)

    # theta_0..7: moderate mixing (same means across chains)
    for p in range(8):
        chain[:, 2 + p] = ar1(N_DRAWS, 0.5, 3.0, 5.0 + 0.1 * p, rng)

    np.save(f"/app/data/model_a/chain_{c}.npy", chain)

# Log-likelihoods for Model A: shape (n_chains, n_draws, n_obs)
log_lik_a = np.empty((N_CHAINS, N_DRAWS, 8))
for c in range(N_CHAINS):
    rng = np.random.RandomState(SEED + 100 + c)
    log_lik_a[c] = rng.normal(-3.0, 1.5, size=(N_DRAWS, 8))

# Observation 7: extreme negative log-likelihoods (triggers numerical instability)
for c in range(N_CHAINS):
    rng = np.random.RandomState(SEED + 200 + c)
    log_lik_a[c, :, 7] = rng.normal(-750.0, 2.0, size=N_DRAWS)

np.save("/app/data/model_a/log_lik.npy", log_lik_a)

# ========== Model B: Non-centered parameterization ==========
os.makedirs("/app/data/model_b", exist_ok=True)

param_names_b = ["mu", "log_tau"] + [f"theta_tilde_{i}" for i in range(8)]

for c in range(N_CHAINS):
    rng = np.random.RandomState(SEED + 300 + c)
    chain = np.empty((N_DRAWS, 10))

    # All parameters: good mixing (low autocorrelation, same means)
    chain[:, 0] = ar1(N_DRAWS, 0.3, 1.5, 4.0, rng)  # mu
    chain[:, 1] = ar1(N_DRAWS, 0.3, 0.8, 0.7, rng)  # log_tau
    for p in range(8):
        chain[:, 2 + p] = ar1(N_DRAWS, 0.3, 1.0, 0.0, rng)  # theta_tilde

    np.save(f"/app/data/model_b/chain_{c}.npy", chain)

# Log-likelihoods for Model B: better fit, no extreme values
log_lik_b = np.empty((N_CHAINS, N_DRAWS, 8))
for c in range(N_CHAINS):
    rng = np.random.RandomState(SEED + 400 + c)
    log_lik_b[c] = rng.normal(-1.8, 0.5, size=(N_DRAWS, 8))

np.save("/app/data/model_b/log_lik.npy", log_lik_b)

# ========== Parameter names ==========
with open("/app/data/param_names.json", "w") as f:
    json.dump({"model_a": param_names_a, "model_b": param_names_b}, f, indent=2)

print("Chain data generated successfully.")
print(f"  Model A: {N_CHAINS} chains x {N_DRAWS} draws x {len(param_names_a)} params")
print(f"  Model B: {N_CHAINS} chains x {N_DRAWS} draws x {len(param_names_b)} params")
print(f"  Log-likelihoods: {N_CHAINS} chains x {N_DRAWS} draws x 8 observations")
