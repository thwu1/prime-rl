"""
Semi-supervised Hidden Markov Model in NumPyro.

This module implements a semi-supervised HMM where:
- Supervised data: observed (word, category) pairs used to learn model parameters
- Unsupervised data: only words are observed; latent categories are marginalized
  via the forward algorithm
- Categories follow a first-order Markov chain with transition matrix
- Words are emitted according to category-specific categorical distributions

The forward algorithm operates in log space for numerical stability, using
logsumexp to avoid underflow when summing over latent states.

Mathematical notation:
- C = number of categories (hidden states)
- W = number of possible words (observations)
- transition_prob[i, j] = P(next_category = j | current_category = i)
- emission_prob[c, w] = P(word = w | category = c)

Forward algorithm step:
  alpha_t(j) = sum_i alpha_{t-1}(i) * transition_prob[i, j] * emission_prob[j, word_t]

In log space with prev_log_prob[i] = log(alpha_{t-1}(i)):
  log_prob_tmp[i, j] = prev_log_prob[i] + log_transition[i, j]
  log_prob[i, j] = log_prob_tmp[i, j] + log_emission[j, word_t]
  new_log_prob[j] = logsumexp_i(log_prob[i, j])

Note: The logsumexp marginalizes over the previous state (axis 0) to yield
the forward probability for each current state j.

References:
    [1] Stan User's Guide: HMMs section
    [2] http://pyro.ai/examples/hmm.html
    [3] https://en.wikipedia.org/wiki/Forward_algorithm
"""


import jax.numpy as jnp
from jax import lax, random
from jax.scipy.special import logsumexp

import numpyro
import numpyro.distributions as dist
from numpyro.infer import MCMC, NUTS


def simulate_data(rng_key, num_categories=3, num_words=10,
                  num_supervised=100, num_unsupervised=20):
    """Generate synthetic HMM data with known ground truth parameters.

    Returns a dict with ground truth parameters and generated data.
    The data consists of two sequences:
    - Supervised: both categories and words are observed
    - Unsupervised: only words are observed (starts from fresh initial state)
    """
    rng_key, rng_transition, rng_emission = random.split(rng_key, 3)

    transition_prior = jnp.ones(num_categories)
    emission_prior = jnp.repeat(0.1, num_words)

    transition_prob = dist.Dirichlet(transition_prior).sample(
        key=rng_transition, sample_shape=(num_categories,)
    )
    emission_prob = dist.Dirichlet(emission_prior).sample(
        key=rng_emission, sample_shape=(num_categories,)
    )

    start_prob = jnp.repeat(1.0 / num_categories, num_categories)
    categories, words = [], []
    for t in range(num_supervised + num_unsupervised):
        rng_key, rng_t, rng_e = random.split(rng_key, 3)
        if t == 0 or t == num_supervised:
            category = dist.Categorical(start_prob).sample(key=rng_t)
        else:
            category = dist.Categorical(transition_prob[category]).sample(key=rng_t)
        word = dist.Categorical(emission_prob[category]).sample(key=rng_e)
        categories.append(category)
        words.append(word)

    categories, words = jnp.stack(categories), jnp.stack(words)
    supervised_categories = categories[:num_supervised]
    supervised_words = words[:num_supervised]
    unsupervised_words = words[num_supervised:]

    return {
        'transition_prior': transition_prior,
        'emission_prior': emission_prior,
        'transition_prob': transition_prob,
        'emission_prob': emission_prob,
        'supervised_categories': supervised_categories,
        'supervised_words': supervised_words,
        'unsupervised_words': unsupervised_words,
    }


def forward_one_step(prev_log_prob, curr_word, transition_log_prob, emission_log_prob):
    """Compute one step of the forward algorithm in log space.

    Args:
        prev_log_prob: shape (C,) - log forward probabilities at previous time step
        curr_word: scalar - index of observed word at current time step
        transition_log_prob: shape (C, C) - log transition matrix where [i,j] = log P(j|i)
        emission_log_prob: shape (C, W) - log emission matrix where [c,w] = log P(w|c)

    Returns:
        shape (C,) - log forward probabilities at current time step
    """
    log_prob_tmp = jnp.expand_dims(prev_log_prob, axis=1) + transition_log_prob
    log_prob = log_prob_tmp + emission_log_prob[:, curr_word]
    return logsumexp(log_prob, axis=1)


def forward_log_prob(init_log_prob, words, transition_log_prob, emission_log_prob):
    """Compute forward log probabilities for a sequence of words.

    Args:
        init_log_prob: shape (C,) - initial log probabilities (conditioned on first word)
        words: shape (T,) - sequence of word indices to process
        transition_log_prob: shape (C, C) - log transition matrix
        emission_log_prob: shape (C, W) - log emission matrix

    Returns:
        shape (C,) - final log forward probabilities after processing all words
    """
    log_prob = init_log_prob
    for word in words:
        log_prob = forward_one_step(log_prob, word, transition_log_prob, emission_log_prob)
    return log_prob


def semi_supervised_hmm(transition_prior, emission_prior,
                        supervised_categories, supervised_words,
                        unsupervised_words):
    """Semi-supervised HMM model for NumPyro.

    The model combines:
    1. Direct observation of category transitions from supervised data
    2. Direct observation of word emissions from supervised data
    3. Marginal likelihood of unsupervised words via the forward algorithm
    """
    num_categories = transition_prior.shape[0]
    num_words = emission_prior.shape[0]

    transition_prob = numpyro.sample(
        "transition_prob",
        dist.Dirichlet(
            jnp.broadcast_to(transition_prior, (num_categories, num_categories))
        ),
    )
    emission_prob = numpyro.sample(
        "emission_prob",
        dist.Dirichlet(
            jnp.broadcast_to(emission_prior, (num_categories, num_words))
        ),
    )

    # Supervised data: observe category transitions
    # P(category[t+1] | category[t]) for t = 0, ..., T-2
    numpyro.sample(
        "supervised_categories",
        dist.Categorical(transition_prob[supervised_categories[1:]]),
        obs=supervised_categories[:-1],
    )
    # Supervised data: observe word emissions
    numpyro.sample(
        "supervised_words",
        dist.Categorical(emission_prob[supervised_categories]),
        obs=supervised_words,
    )

    # Unsupervised data: marginalize latent categories via forward algorithm
    transition_log_prob = jnp.log(transition_prob)
    emission_log_prob = jnp.log(emission_prob)
    init_log_prob = emission_log_prob[:, unsupervised_words[0]]
    log_prob = forward_log_prob(
        init_log_prob, unsupervised_words[1:],
        transition_log_prob, emission_log_prob,
    )
    log_prob = logsumexp(log_prob, axis=0, keepdims=True)
    numpyro.factor("forward_log_prob", -log_prob)


def run_inference(rng_key, data, num_warmup=200, num_samples=200, num_chains=1):
    """Run MCMC inference on the semi-supervised HMM.

    Returns the MCMC object with samples and diagnostics.
    """
    kernel = NUTS(semi_supervised_hmm, target_accept_prob=0.55)
    mcmc = MCMC(
        kernel,
        num_warmup=num_warmup,
        num_samples=num_samples,
        num_chains=num_chains,
        progress_bar=False,
    )
    mcmc.run(
        rng_key,
        data['transition_prior'],
        data['emission_prior'],
        data['supervised_categories'],
        data['supervised_words'],
        data['unsupervised_words'],
    )
    return mcmc
