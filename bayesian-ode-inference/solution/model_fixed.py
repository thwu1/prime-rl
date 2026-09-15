"""
Corrected Bayesian parameter inference for a Lotka-Volterra predator-prey system.

Fixes applied relative to the buggy /app/model.py:
  1. ODE sign error: alpha + beta*v  ->  alpha - beta*v
  2. Priors on ODE parameters: Normal (allows negative) -> TruncatedNormal(low=0)
  3. Prior on initial conditions: Normal -> LogNormal (ensures positivity)
  4. ODE solver tolerances: rtol/atol=1e-2, mxstep=100 -> rtol=1e-6, atol=1e-5, mxstep=1000
  5. NUTS kernel: added dense_mass=True and target_accept_prob=0.9
  6. Increased MCMC warmup/samples for reliable convergence
  7. Implemented compute_predictions via NumPyro Predictive
  8. Implemented compute_diagnostics via numpyro.diagnostics
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
from numpyro.diagnostics import split_gelman_rubin, effective_sample_size
from jax.experimental.ode import odeint


def dz_dt(z, t, theta):
    """Lotka-Volterra ODE right-hand side."""
    u = z[0]
    v = z[1]
    alpha = theta[0]
    beta = theta[1]
    gamma = theta[2]
    delta = theta[3]
    # FIX 1: corrected sign  (was alpha + beta * v)
    du_dt = (alpha - beta * v) * u
    dv_dt = (-gamma + delta * u) * v
    return jnp.stack([du_dt, dv_dt])


def model(ts, y=None):
    """NumPyro probabilistic model for Lotka-Volterra inference."""
    # FIX 2: TruncatedNormal ensures positivity of ODE parameters
    alpha = numpyro.sample(
        "alpha", dist.TruncatedNormal(low=0.0, loc=1.0, scale=0.5)
    )
    beta = numpyro.sample(
        "beta", dist.TruncatedNormal(low=0.0, loc=0.1, scale=0.05)
    )
    gamma = numpyro.sample(
        "gamma", dist.TruncatedNormal(low=0.0, loc=1.5, scale=0.5)
    )
    delta = numpyro.sample(
        "delta", dist.TruncatedNormal(low=0.0, loc=0.05, scale=0.03)
    )

    # FIX 3: LogNormal ensures positive initial populations
    z_init = numpyro.sample(
        "z_init",
        dist.LogNormal(
            jnp.log(jnp.array([25.0, 8.0])),
            jnp.array([0.3, 0.3]),
        ),
    )

    # Observation noise scale (log-space)
    sigma = numpyro.sample(
        "sigma",
        dist.LogNormal(jnp.array([-1.0, -1.0]), jnp.array([1.0, 1.0])),
    )

    theta = jnp.stack([alpha, beta, gamma, delta])

    # FIX 4: tighter ODE solver tolerances
    z = odeint(dz_dt, z_init, ts, theta, rtol=1e-6, atol=1e-5, mxstep=1000)

    numpyro.sample("obs", dist.LogNormal(jnp.log(z), sigma), obs=y)


def run_inference(ts, y, rng_key, num_warmup=500, num_samples=1000):
    """Run NUTS MCMC inference."""
    # FIX 5: dense_mass + target_accept_prob for correlated parameters
    kernel = NUTS(model, dense_mass=True, target_accept_prob=0.9)
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
    """FIX 7: Compute posterior predictive distributions."""
    posterior_samples = mcmc.get_samples()
    predictive = Predictive(model, posterior_samples=posterior_samples)
    pred = predictive(rng_key, ts=ts)
    obs = np.array(pred["obs"])  # (num_samples, T, 2)

    return {
        "time": list(np.array(ts)),
        "mean_u": list(np.mean(obs[:, :, 0], axis=0)),
        "lower_u": list(np.percentile(obs[:, :, 0], 5, axis=0)),
        "upper_u": list(np.percentile(obs[:, :, 0], 95, axis=0)),
        "mean_v": list(np.mean(obs[:, :, 1], axis=0)),
        "lower_v": list(np.percentile(obs[:, :, 1], 5, axis=0)),
        "upper_v": list(np.percentile(obs[:, :, 1], 95, axis=0)),
    }


def compute_diagnostics(mcmc):
    """FIX 8: Extract MCMC convergence diagnostics for ODE parameters."""
    samples = mcmc.get_samples(group_by_chain=True)
    result = {}
    for name in ["alpha", "beta", "gamma", "delta"]:
        if name not in samples:
            continue
        vals_np = np.array(samples[name])
        if vals_np.ndim == 2:  # (chains, samples)
            result[name] = {
                "r_hat": float(split_gelman_rubin(vals_np)),
                "n_eff": float(effective_sample_size(vals_np)),
            }
    return result


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
