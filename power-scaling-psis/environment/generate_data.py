#!/usr/bin/env python3
"""Generate synthetic MCMC posterior samples for the power-scaling sensitivity task.

Model: Hierarchical Normal
  y_ij ~ Normal(mu_j, sigma),  i=1..n_j, j=1..J
  mu_j ~ Normal(mu_0, tau)                           [prior component: group_means]
  mu_0 ~ Normal(0, 2)                                [prior component: grand_mean]
  sigma ~ LogNormal(0, 0.5)                           [prior component: noise_sd]
  tau   ~ LogNormal(0, 0.5)                           [prior component: group_sd]

True parameters: mu_0=5, sigma=1.5, tau=2.0
The N(0,2) prior on mu_0 creates deliberate prior-data conflict (true=5 vs prior center=0).
"""

import numpy as np
import json
import os
import sys


def log_prior_grand_mean(mu_0, prior_mean=0.0, prior_sd=2.0):
    return -0.5 * ((mu_0 - prior_mean) / prior_sd) ** 2


def log_prior_noise_sd(sigma, loc=0.0, scale=0.5):
    ls = np.log(np.maximum(sigma, 1e-300))
    return -0.5 * ((ls - loc) / scale) ** 2 - ls


def log_prior_group_sd(tau, loc=0.0, scale=0.5):
    lt = np.log(np.maximum(tau, 1e-300))
    return -0.5 * ((lt - loc) / scale) ** 2 - lt


def log_prior_group_means(mu_j, mu_0, tau):
    tau_safe = max(tau, 1e-10)
    return float(np.sum(-0.5 * ((mu_j - mu_0) / tau_safe) ** 2 - np.log(tau_safe)))


def log_likelihood(y, group_ids, mu_j, sigma, N):
    sigma_safe = max(sigma, 1e-10)
    residuals = y - mu_j[group_ids]
    return -0.5 * np.sum((residuals / sigma_safe) ** 2) - N * np.log(sigma_safe)


def main():
    np.random.seed(54321)

    J = 8
    n_per_group = 30
    N = J * n_per_group

    true_mu_0 = 5.0
    true_sigma = 1.5
    true_tau = 2.0
    true_mu = np.random.normal(true_mu_0, true_tau, J)

    group_ids = np.repeat(np.arange(J), n_per_group)
    y = np.random.normal(true_mu[group_ids], true_sigma)

    y_bar = np.array([y[group_ids == j].mean() for j in range(J)])
    n_j = np.array([np.sum(group_ids == j) for j in range(J)])

    prior_mu0_mean, prior_mu0_sd = 0.0, 2.0

    n_chains = 4
    n_iter = 2500
    n_warmup = 500
    n_keep = n_iter - n_warmup

    all_chains_samples = []
    all_chains_lp = []
    all_chains_ll = []

    for chain in range(n_chains):
        np.random.seed(100 + chain * 777)

        mu_0 = np.random.normal(0, 2)
        sigma = np.exp(np.random.normal(0, 0.5))
        tau = np.exp(np.random.normal(0, 0.5))
        mu_j = np.random.normal(mu_0, max(tau, 0.1), J)

        chain_mu0, chain_sigma, chain_tau, chain_mu = [], [], [], []
        chain_lp_gm, chain_lp_ns, chain_lp_gs, chain_lp_grm = [], [], [], []
        chain_ll = []

        for it in range(n_iter):
            # Gibbs update for mu_j (conjugate normal-normal)
            prec_prior = 1.0 / max(tau, 1e-10) ** 2
            prec_lik = n_j / max(sigma, 1e-10) ** 2
            post_prec = prec_prior + prec_lik
            post_mean = (prec_prior * mu_0 + prec_lik * y_bar) / post_prec
            mu_j = np.random.normal(post_mean, 1.0 / np.sqrt(post_prec))

            # Gibbs update for mu_0 (conjugate)
            prec_p = 1.0 / prior_mu0_sd ** 2
            prec_l = J / max(tau, 1e-10) ** 2
            post_prec_mu0 = prec_p + prec_l
            post_mean_mu0 = (prec_p * prior_mu0_mean + prec_l * np.mean(mu_j)) / post_prec_mu0
            mu_0 = np.random.normal(post_mean_mu0, 1.0 / np.sqrt(post_prec_mu0))

            # MH update for sigma (log scale)
            log_s = np.log(max(sigma, 1e-300))
            log_s_prop = log_s + np.random.normal(0, 0.08)
            s_prop = np.exp(log_s_prop)
            ll_curr = log_likelihood(y, group_ids, mu_j, sigma, N)
            ll_prop = log_likelihood(y, group_ids, mu_j, s_prop, N)
            lp_curr = log_prior_noise_sd(sigma)
            lp_prop = log_prior_noise_sd(s_prop)
            if np.log(np.random.uniform()) < (ll_prop + lp_prop) - (ll_curr + lp_curr):
                sigma = s_prop

            # MH update for tau (log scale)
            log_t = np.log(max(tau, 1e-300))
            log_t_prop = log_t + np.random.normal(0, 0.2)
            t_prop = np.exp(log_t_prop)
            lp_curr_t = log_prior_group_sd(tau) + log_prior_group_means(mu_j, mu_0, tau)
            lp_prop_t = log_prior_group_sd(t_prop) + log_prior_group_means(mu_j, mu_0, t_prop)
            if np.log(np.random.uniform()) < lp_prop_t - lp_curr_t:
                tau = t_prop

            if it >= n_warmup:
                chain_mu0.append(mu_0)
                chain_sigma.append(sigma)
                chain_tau.append(tau)
                chain_mu.append(mu_j.copy())
                chain_lp_gm.append(log_prior_grand_mean(mu_0))
                chain_lp_ns.append(log_prior_noise_sd(sigma))
                chain_lp_gs.append(log_prior_group_sd(tau))
                chain_lp_grm.append(log_prior_group_means(mu_j, mu_0, tau))
                chain_ll.append(log_likelihood(y, group_ids, mu_j, sigma, N))

        samples = {
            'mu_0': np.array(chain_mu0),
            'sigma': np.array(chain_sigma),
            'tau': np.array(chain_tau),
        }
        for j in range(J):
            samples[f'mu_{j + 1}'] = np.array([m[j] for m in chain_mu])

        lp = {
            'grand_mean': np.array(chain_lp_gm),
            'noise_sd': np.array(chain_lp_ns),
            'group_sd': np.array(chain_lp_gs),
            'group_means': np.array(chain_lp_grm),
        }

        all_chains_samples.append(samples)
        all_chains_lp.append(lp)
        all_chains_ll.append(np.array(chain_ll))

    # Combine chains
    combined_samples = {}
    for key in all_chains_samples[0]:
        combined_samples[key] = np.concatenate([c[key] for c in all_chains_samples])

    combined_lp = {}
    for key in all_chains_lp[0]:
        combined_lp[key] = np.concatenate([c[key] for c in all_chains_lp])

    combined_ll = np.concatenate(all_chains_ll)

    # Save
    data_dir = '/app/data'
    os.makedirs(data_dir, exist_ok=True)
    np.savez(os.path.join(data_dir, 'samples.npz'), **combined_samples)
    np.savez(os.path.join(data_dir, 'log_prior_components.npz'), **combined_lp)
    np.save(os.path.join(data_dir, 'log_likelihood.npy'), combined_ll)
    np.save(os.path.join(data_dir, 'y.npy'), y)
    np.save(os.path.join(data_dir, 'group_ids.npy'), group_ids)

    model_spec = {
        'parameters': list(combined_samples.keys()),
        'scalar_parameters': ['mu_0', 'sigma', 'tau'],
        'prior_components': list(combined_lp.keys()),
        'prior_descriptions': {
            'grand_mean': 'Normal(0, 2) prior on mu_0 (population mean)',
            'noise_sd': 'LogNormal(0, 0.5) prior on sigma (observation noise)',
            'group_sd': 'LogNormal(0, 0.5) prior on tau (group-level spread)',
            'group_means': 'Normal(mu_0, tau) hierarchical prior on group means mu_j',
        },
        'n_chains': n_chains,
        'n_samples_per_chain': n_keep,
        'n_samples_total': n_chains * n_keep,
        'J': J,
        'N': N,
        'alpha_grid': [0.5, 0.75, 0.9, 0.99, 1.01, 1.1, 1.25, 1.5],
    }

    with open(os.path.join(data_dir, 'model_spec.json'), 'w') as f:
        json.dump(model_spec, f, indent=2)

    # Verify all files were created
    expected = ['samples.npz', 'log_prior_components.npz', 'log_likelihood.npy',
                'y.npy', 'group_ids.npy', 'model_spec.json']
    for fname in expected:
        fpath = os.path.join(data_dir, fname)
        if not os.path.exists(fpath):
            print(f"ERROR: {fpath} was not created!", file=sys.stderr)
            sys.exit(1)
        sz = os.path.getsize(fpath)
        print(f"  {fname}: {sz} bytes")

    print(f"Data generation complete. Total samples: {n_chains * n_keep}")


if __name__ == '__main__':
    main()
