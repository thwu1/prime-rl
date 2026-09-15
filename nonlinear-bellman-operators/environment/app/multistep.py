"""Multistep return calculations for reinforcement learning.

Functions for computing bootstrapped estimates of returns from trajectories.
Trajectories are not assumed to align with episode boundaries; bootstrapping
estimates returns beyond the end of a trajectory.
"""

import chex
import jax
import jax.numpy as jnp
import base as base_lib

Array = chex.Array
Scalar = chex.Scalar
Numeric = chex.Numeric


def lambda_returns(
    r_t: Array,
    discount_t: Array,
    v_t: Array,
    lambda_: Numeric = 1.,
    stop_target_gradients: bool = False,
) -> Array:
    """Multistep truncated lambda returns.

    Args:
        r_t: rewards at time t, shape [T].
        discount_t: discounts at time t, shape [T].
        v_t: values at time t, shape [T].
        lambda_: mixing parameter.
        stop_target_gradients: whether to stop gradient through targets.

    Returns:
        Lambda returns, shape [T].
    """
    chex.assert_rank([r_t, discount_t, v_t, lambda_], [1, 1, 1, {0, 1}])
    chex.assert_type([r_t, discount_t, v_t, lambda_], float)
    chex.assert_equal_shape([r_t, discount_t, v_t])
    raise NotImplementedError


def n_step_bootstrapped_returns(
    r_t: Array,
    discount_t: Array,
    v_t: Array,
    n: int,
    lambda_t: Numeric = 1.,
    stop_target_gradients: bool = False,
) -> Array:
    """Computes strided n-step bootstrapped return targets over a sequence."""
    chex.assert_rank([r_t, discount_t, v_t, lambda_t], [1, 1, 1, {0, 1}])
    chex.assert_type([r_t, discount_t, v_t, lambda_t], float)
    chex.assert_equal_shape([r_t, discount_t, v_t])
    seq_len = r_t.shape[0]

    lambda_t = jnp.ones_like(discount_t) * lambda_t

    pad_size = min(n - 1, seq_len)
    targets = jnp.concatenate([v_t[n - 1:], jnp.array([v_t[-1]] * pad_size)])

    r_t = jnp.concatenate([r_t, jnp.zeros(n - 1)])
    discount_t = jnp.concatenate([discount_t, jnp.ones(n - 1)])
    lambda_t = jnp.concatenate([lambda_t, jnp.ones(n - 1)])
    v_t = jnp.concatenate([v_t, jnp.array([v_t[-1]] * (n - 1))])

    for i in reversed(range(n)):
        r_ = r_t[i:i + seq_len]
        discount_ = discount_t[i:i + seq_len]
        lambda_ = lambda_t[i:i + seq_len]
        v_ = v_t[i:i + seq_len]
        targets = r_ + discount_ * ((1. - lambda_) * v_ + lambda_ * targets)

    return jax.lax.select(stop_target_gradients,
                          jax.lax.stop_gradient(targets), targets)


def general_off_policy_returns_from_action_values(
    q_t: Array,
    a_t: Array,
    r_t: Array,
    discount_t: Array,
    c_t: Array,
    pi_t: Array,
    stop_target_gradients: bool = False,
) -> Array:
    """Calculates targets for off-policy correction algorithms."""
    chex.assert_rank([q_t, a_t, r_t, discount_t, c_t, pi_t],
                     [2, 1, 1, 1, 1, 2])
    chex.assert_type([q_t, a_t, r_t, discount_t, c_t, pi_t],
                     [float, int, float, float, float, float])
    chex.assert_equal_shape(
        [q_t[..., 0], a_t, r_t, discount_t, c_t, pi_t[..., 0]])

    exp_q_t = (pi_t * q_t).sum(axis=-1)
    q_a_t = base_lib.batched_index(q_t, a_t)[:-1]
    c_t = c_t[:-1]

    return general_off_policy_returns_from_q_and_v(
        q_a_t, exp_q_t, r_t, discount_t, c_t, stop_target_gradients)


def general_off_policy_returns_from_q_and_v(
    q_t: Array,
    v_t: Array,
    r_t: Array,
    discount_t: Array,
    c_t: Array,
    stop_target_gradients: bool = False,
) -> Array:
    """Calculates targets for off-policy evaluation algorithms."""
    chex.assert_rank([q_t, v_t, r_t, discount_t, c_t], 1)
    chex.assert_type([q_t, v_t, r_t, discount_t, c_t], float)
    chex.assert_equal_shape([q_t, v_t[:-1], r_t[:-1], discount_t[:-1], c_t])

    g = r_t[-1] + discount_t[-1] * v_t[-1]

    def _body(acc, xs):
        reward, discount, c, v, q = xs
        acc = reward + discount * (v - c * q + c * acc)
        return acc, acc

    _, returns = jax.lax.scan(
        _body, g, (r_t[:-1], discount_t[:-1], c_t, v_t[:-1], q_t), reverse=True)
    returns = jnp.concatenate([returns, g[jnp.newaxis]], axis=0)

    return jax.lax.select(stop_target_gradients,
                          jax.lax.stop_gradient(returns), returns)
