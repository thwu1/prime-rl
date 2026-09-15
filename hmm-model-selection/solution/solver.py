#!/usr/bin/env python3

"""
Reference solution: diagnoses the buggy HMM model (independent Normal priors
causing label switching / divergences), fixes it with incremental ordered
parameterization, loads all training data, runs MCMC for K=2 and K=3,
performs model selection, and decodes hidden states via Viterbi.
"""

import json
import numpy as np

import jax
import jax.numpy as jnp
from jax import lax, random
from jax.scipy.special import logsumexp

import numpyro
import numpyro.distributions as dist
from numpyro.infer import MCMC, NUTS


# ---------------------------------------------------------------------------
# Forward algorithm
# ---------------------------------------------------------------------------

def normal_log_prob(x, mu, sigma):
    return -0.5 * jnp.log(2.0 * jnp.pi) - jnp.log(sigma) - 0.5 * jnp.square((x - mu) / sigma)


def forward_log_likelihood(observations, mu, sigma, transition_log_prob, init_log_prob):
    emission_lp_0 = normal_log_prob(observations[0], mu, sigma)
    log_alpha_init = init_log_prob + emission_lp_0

    def scan_fn(log_alpha, obs_t):
        log_alpha_pred = log_alpha[:, None] + transition_log_prob
        log_alpha_new = logsumexp(log_alpha_pred, axis=0)
        emission_lp = normal_log_prob(obs_t, mu, sigma)
        return log_alpha_new + emission_lp, None

    final_log_alpha, _ = lax.scan(scan_fn, log_alpha_init, observations[1:])
    return logsumexp(final_log_alpha)


# ---------------------------------------------------------------------------
# Fixed NumPyro model (incremental ordered parameterization)
# ---------------------------------------------------------------------------

def make_hmm_model(K):
    def model(all_train_obs):
        transition_prob = numpyro.sample(
            "transition_prob",
            dist.Dirichlet(jnp.ones(K)).expand([K]),
        )

        # Fixed: incremental parameterization enforces ordering
        mu_first = numpyro.sample("mu_first", dist.Normal(0.0, 5.0))
        if K > 1:
            mu_deltas = numpyro.sample("mu_deltas", dist.HalfNormal(3.0).expand([K - 1]))
            mu = numpyro.deterministic(
                "mu",
                jnp.concatenate([
                    jnp.array([mu_first]),
                    mu_first + jnp.cumsum(mu_deltas),
                ]),
            )
        else:
            mu = numpyro.deterministic("mu", jnp.array([mu_first]))

        sigma = numpyro.sample("sigma", dist.HalfNormal(2.0).expand([K]))

        transition_lp = jnp.log(transition_prob)
        init_lp = jnp.log(jnp.ones(K) / K)

        def single_seq_ll(obs):
            return forward_log_likelihood(obs, mu, sigma, transition_lp, init_lp)

        total_ll = jnp.sum(jax.vmap(single_seq_ll)(all_train_obs))
        numpyro.factor("obs", total_ll)

    return model


# ---------------------------------------------------------------------------
# Viterbi decoding
# ---------------------------------------------------------------------------

def viterbi_decode(observations, mu, sigma, transition_log_prob, init_log_prob):
    T = observations.shape[0]

    emission_lp_0 = normal_log_prob(observations[0], mu, sigma)
    log_delta_init = init_log_prob + emission_lp_0

    def scan_fn(log_delta, obs_t):
        scores = log_delta[:, None] + transition_log_prob
        log_delta_new = jnp.max(scores, axis=0)
        back_pointer = jnp.argmax(scores, axis=0)
        emission_lp = normal_log_prob(obs_t, mu, sigma)
        return log_delta_new + emission_lp, back_pointer

    final_log_delta, back_pointers = lax.scan(
        scan_fn, log_delta_init, observations[1:]
    )

    bp_np = np.array(back_pointers)
    states = np.zeros(T, dtype=int)
    states[-1] = int(jnp.argmax(final_log_delta))
    for t in range(T - 2, -1, -1):
        states[t] = bp_np[t, states[t + 1]]
    return states.tolist()


# ---------------------------------------------------------------------------
# MCMC helpers
# ---------------------------------------------------------------------------

def run_mcmc(model, train_obs, rng_key, num_warmup=300, num_samples=500):
    kernel = NUTS(model)
    mcmc = MCMC(
        kernel,
        num_warmup=num_warmup,
        num_samples=num_samples,
        num_chains=1,
        progress_bar=True,
    )
    mcmc.run(rng_key, train_obs)
    mcmc.print_summary()
    return mcmc


def extract_diagnostics(mcmc):
    diverging = mcmc.get_extra_fields()["diverging"]
    num_div = int(jnp.sum(diverging))

    from numpyro.diagnostics import summary as numpyro_summary

    chain_samples = mcmc.get_samples(group_by_chain=True)
    summ = numpyro_summary(chain_samples)
    max_rhat = 1.0
    for param_name in summ:
        rhat_vals = summ[param_name].get("r_hat")
        if rhat_vals is not None:
            rh = float(np.nanmax(rhat_vals))
            if np.isfinite(rh):
                max_rhat = max(max_rhat, rh)
    return num_div, max_rhat


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    numpyro.set_host_device_count(1)

    # Load ALL training data from both experiment batches
    train_1 = np.load("/app/data/experiment_1/obs.npy")
    train_2 = np.load("/app/data/experiment_2/obs.npy")
    train_obs = jnp.array(np.concatenate([train_1, train_2], axis=0))

    # Load held-out evaluation data
    test_obs = jnp.array(np.load("/app/data/holdout/obs.npy"))

    results = {}
    best_K = None
    best_loglik = -np.inf
    best_info = {}

    for K in [2, 3]:
        print(f"\n{'=' * 60}")
        print(f"  Fitting HMM with K = {K} states")
        print(f"{'=' * 60}")

        model = make_hmm_model(K)
        rng_key = random.key(K * 7 + 13)
        mcmc = run_mcmc(model, train_obs, rng_key, num_warmup=300, num_samples=500)
        samples = mcmc.get_samples()

        mu_mean = np.array(jnp.mean(samples["mu"], axis=0))
        sigma_mean = np.array(jnp.mean(samples["sigma"], axis=0))
        trans_mean = np.array(jnp.mean(samples["transition_prob"], axis=0))

        trans_lp = jnp.log(jnp.array(trans_mean))
        init_lp = jnp.log(jnp.ones(K) / K)
        test_loglik = 0.0
        for i in range(test_obs.shape[0]):
            ll = forward_log_likelihood(
                test_obs[i],
                jnp.array(mu_mean),
                jnp.array(sigma_mean),
                trans_lp,
                init_lp,
            )
            test_loglik += float(ll)

        results[f"test_loglik_K{K}"] = test_loglik
        print(f"  K={K}: test total log-likelihood = {test_loglik:.2f}")

        num_div, max_rhat = extract_diagnostics(mcmc)

        if test_loglik > best_loglik:
            best_loglik = test_loglik
            best_K = K
            best_info = {
                "mu_mean": mu_mean.tolist(),
                "sigma_mean": sigma_mean.tolist(),
                "trans_mean": trans_mean.tolist(),
                "num_divergences": num_div,
                "max_rhat": max_rhat,
            }

    results["selected_K"] = best_K
    results["emission_means"] = best_info["mu_mean"]
    results["emission_stds"] = best_info["sigma_mean"]
    results["transition_matrix"] = best_info["trans_mean"]
    results["num_divergences"] = best_info["num_divergences"]
    results["max_rhat"] = best_info["max_rhat"]

    mu_jnp = jnp.array(best_info["mu_mean"])
    sigma_jnp = jnp.array(best_info["sigma_mean"])
    trans_lp = jnp.log(jnp.array(best_info["trans_mean"]))
    init_lp = jnp.log(jnp.ones(best_K) / best_K)

    for i in range(test_obs.shape[0]):
        states = viterbi_decode(test_obs[i], mu_jnp, sigma_jnp, trans_lp, init_lp)
        results[f"decoded_states_seq{i}"] = states

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nSelected model: K = {best_K}")
    print(f"Results saved to /app/results.json")


if __name__ == "__main__":
    main()
