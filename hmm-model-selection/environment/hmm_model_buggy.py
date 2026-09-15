"""HMM model definition for NumPyro inference."""
import jax
import jax.numpy as jnp
from jax import lax
from jax.scipy.special import logsumexp

import numpyro
import numpyro.distributions as dist


def _normal_log_prob(x, mu, sigma):
    """Log-probability of Normal(mu, sigma) at x."""
    return -0.5 * jnp.log(2.0 * jnp.pi) - jnp.log(sigma) - 0.5 * ((x - mu) / sigma) ** 2


def forward_log_likelihood(observations, mu, sigma, transition_log_prob, init_log_prob):
    """Marginal log-likelihood of an observation sequence via the forward algorithm.

    Args:
        observations: (T,) array
        mu: (K,) emission means
        sigma: (K,) emission stds
        transition_log_prob: (K, K) log transition matrix
        init_log_prob: (K,) log initial distribution

    Returns:
        Scalar marginal log-likelihood.
    """
    emission_lp_0 = _normal_log_prob(observations[0], mu, sigma)
    log_alpha_init = init_log_prob + emission_lp_0

    def scan_fn(log_alpha, obs_t):
        log_alpha_pred = log_alpha[:, None] + transition_log_prob
        log_alpha_new = logsumexp(log_alpha_pred, axis=0)
        emission_lp = _normal_log_prob(obs_t, mu, sigma)
        return log_alpha_new + emission_lp, None

    final_log_alpha, _ = lax.scan(scan_fn, log_alpha_init, observations[1:])
    return logsumexp(final_log_alpha)


def hmm_model(obs_sequences, K):
    """Bayesian Gaussian-emission HMM.

    Args:
        obs_sequences: (N, T) array of observation sequences
        K: number of hidden states
    """
    # Transition probabilities — Dirichlet prior on each row
    transition_prob = numpyro.sample(
        "transition_prob",
        dist.Dirichlet(jnp.ones(K)).expand([K]),
    )

    # Emission means — independent Normal priors per state
    mu = numpyro.sample("mu", dist.Normal(0.0, 5.0).expand([K]))

    # Emission standard deviations
    sigma = numpyro.sample("sigma", dist.HalfNormal(2.0).expand([K]))

    # Log-space transition and initial distributions
    transition_lp = jnp.log(transition_prob)
    init_lp = jnp.log(jnp.ones(K) / K)

    # Total log-likelihood across all sequences
    total_ll = jnp.sum(
        jax.vmap(
            lambda obs: forward_log_likelihood(obs, mu, sigma, transition_lp, init_lp)
        )(obs_sequences)
    )
    numpyro.factor("obs", total_ll)
