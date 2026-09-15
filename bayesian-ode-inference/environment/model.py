"""
Bayesian parameter inference for a Lotka-Volterra predator-prey system using NumPyro.

ODE system (prey u, predator v):
    du/dt = (alpha - beta * v) * u     [prey growth minus predation]
    dv/dt = (-gamma + delta * u) * v   [predator growth from predation minus death]

Parameters:
    alpha: prey intrinsic growth rate
    beta:  predation effect on prey
    gamma: predator death rate
    delta: predation benefit to predator

Observations follow a log-normal distribution around the true ODE trajectory.

Usage: python3 /app/model.py
"""

import json
import os
import csv

import jax
import jax.numpy as jnp
import numpy as np
import numpyro
import numpyro.distributions as dist
from numpyro.infer import MCMC, NUTS, Predictive
from jax.experimental.ode import odeint


def dz_dt(z, t, theta):
    """Lotka-Volterra ODE right-hand side.

    Args:
        z: state vector [u, v] — prey and predator populations
        t: time (unused in this autonomous system)
        theta: parameter vector [alpha, beta, gamma, delta]

    Returns:
        Time derivatives [du/dt, dv/dt]
    """
    u = z[0]
    v = z[1]
    alpha = theta[0]
    beta = theta[1]
    gamma = theta[2]
    delta = theta[3]
    du_dt = (alpha + beta * v) * u
    dv_dt = (-gamma + delta * u) * v
    return jnp.stack([du_dt, dv_dt])


def model(ts, y=None):
    """NumPyro probabilistic model for Lotka-Volterra inference.

    Args:
        ts: array of observation time points
        y: observed populations, shape (T, 2). None for prior predictive.
    """
    # Priors on ODE parameters
    alpha = numpyro.sample("alpha", dist.Normal(1.0, 0.5))
    beta = numpyro.sample("beta", dist.Normal(0.1, 0.05))
    gamma = numpyro.sample("gamma", dist.Normal(1.5, 0.5))
    delta = numpyro.sample("delta", dist.Normal(0.05, 0.03))

    # Initial population sizes
    z_init = numpyro.sample(
        "z_init",
        dist.Normal(jnp.array([25.0, 8.0]), jnp.array([10.0, 5.0])),
    )

    # Observation noise scale (log-space)
    sigma = numpyro.sample(
        "sigma",
        dist.LogNormal(jnp.array([-1.0, -1.0]), jnp.array([1.0, 1.0])),
    )

    # Pack ODE parameters
    theta = jnp.stack([alpha, beta, gamma, delta])

    # Integrate ODE forward in time
    z = odeint(dz_dt, z_init, ts, theta, rtol=1e-2, atol=1e-2, mxstep=100)

    # Log-normal observation likelihood
    numpyro.sample("obs", dist.LogNormal(jnp.log(z), sigma), obs=y)


def run_inference(ts, y, rng_key, num_warmup=500, num_samples=500):
    """Run NUTS MCMC inference.

    Args:
        ts: time points array
        y: observed data, shape (T, 2)
        rng_key: JAX PRNG key
        num_warmup: warmup / adaptation steps
        num_samples: posterior samples to collect

    Returns:
        Fitted MCMC object
    """
    kernel = NUTS(model)
    mcmc = MCMC(
        kernel,
        num_warmup=num_warmup,
        num_samples=num_samples,
        num_chains=1,
        progress_bar=True,
    )
    mcmc.run(rng_key, ts=ts, y=y)
    mcmc.print_summary()
    return mcmc


def compute_predictions(mcmc, ts, rng_key):
    """Compute posterior predictive distributions.

    Should return a dict with keys:
        time, mean_u, lower_u, upper_u, mean_v, lower_v, upper_v
    where lower/upper are the 5th/95th percentiles (90% CI).

    Args:
        mcmc: fitted MCMC object with posterior samples
        ts: time points for prediction
        rng_key: JAX PRNG key for sampling

    Returns:
        dict or None
    """
    # TODO: implement posterior predictive computation
    pass


def compute_diagnostics(mcmc):
    """Extract MCMC convergence diagnostics.

    Should return a dict mapping parameter names to dicts with r_hat and n_eff.

    Args:
        mcmc: fitted MCMC object

    Returns:
        dict or None
    """
    # TODO: implement diagnostics extraction
    pass


def save_results(mcmc, predictions, diagnostics, output_dir="/app/results"):
    """Save all inference results to files."""
    os.makedirs(output_dir, exist_ok=True)

    samples = mcmc.get_samples()

    # ---- Parameter summary ----
    param_summary = {}
    for name in ["alpha", "beta", "gamma", "delta", "sigma"]:
        if name not in samples:
            continue
        vals = np.array(samples[name])
        if vals.ndim == 1:
            param_summary[name] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals)),
                "median": float(np.median(vals)),
                "q5": float(np.percentile(vals, 5)),
                "q95": float(np.percentile(vals, 95)),
            }
        else:
            for i in range(vals.shape[1]):
                param_summary[f"{name}_{i}"] = {
                    "mean": float(np.mean(vals[:, i])),
                    "std": float(np.std(vals[:, i])),
                    "median": float(np.median(vals[:, i])),
                    "q5": float(np.percentile(vals[:, i], 5)),
                    "q95": float(np.percentile(vals[:, i], 95)),
                }

    if "z_init" in samples:
        zi = np.array(samples["z_init"])
        param_summary["u0"] = {
            "mean": float(np.mean(zi[:, 0])),
            "std": float(np.std(zi[:, 0])),
            "median": float(np.median(zi[:, 0])),
            "q5": float(np.percentile(zi[:, 0], 5)),
            "q95": float(np.percentile(zi[:, 0], 95)),
        }
        param_summary["v0"] = {
            "mean": float(np.mean(zi[:, 1])),
            "std": float(np.std(zi[:, 1])),
            "median": float(np.median(zi[:, 1])),
            "q5": float(np.percentile(zi[:, 1], 5)),
            "q95": float(np.percentile(zi[:, 1], 95)),
        }

    with open(os.path.join(output_dir, "parameters.json"), "w") as f:
        json.dump(param_summary, f, indent=2)

    # ---- Predictions ----
    if predictions is not None:
        with open(
            os.path.join(output_dir, "predictions.csv"), "w", newline=""
        ) as f:
            writer = csv.writer(f)
            writer.writerow(
                ["time", "u_mean", "u_lower", "u_upper",
                 "v_mean", "v_lower", "v_upper"]
            )
            for i in range(len(predictions["time"])):
                writer.writerow([
                    f"{predictions['time'][i]:.1f}",
                    f"{predictions['mean_u'][i]:.4f}",
                    f"{predictions['lower_u'][i]:.4f}",
                    f"{predictions['upper_u'][i]:.4f}",
                    f"{predictions['mean_v'][i]:.4f}",
                    f"{predictions['lower_v'][i]:.4f}",
                    f"{predictions['upper_v'][i]:.4f}",
                ])

    # ---- Diagnostics ----
    if diagnostics is not None:
        with open(os.path.join(output_dir, "diagnostics.json"), "w") as f:
            json.dump(diagnostics, f, indent=2)

    print(f"Results saved to {output_dir}/")


if __name__ == "__main__":
    numpyro.set_host_device_count(1)

    # Load observed data
    data = np.genfromtxt("/app/data.csv", delimiter=",", names=True)
    ts = jnp.array(data["time"])
    y = jnp.column_stack([jnp.array(data["u"]), jnp.array(data["v"])])

    print(f"Loaded {len(ts)} time points")
    print(f"Prey range:     [{float(y[:, 0].min()):.2f}, {float(y[:, 0].max()):.2f}]")
    print(f"Predator range: [{float(y[:, 1].min()):.2f}, {float(y[:, 1].max()):.2f}]")

    rng_key = jax.random.PRNGKey(42)
    rng_key, pred_key = jax.random.split(rng_key)

    mcmc = run_inference(ts, y, rng_key)
    predictions = compute_predictions(mcmc, ts, pred_key)
    diagnostics = compute_diagnostics(mcmc)
    save_results(mcmc, predictions, diagnostics)

    print("Inference complete. Results saved to /app/results/")
