"""V-trace off-policy correction algorithm."""

import collections

import chex
import jax
import jax.numpy as jnp

Array = chex.Array
Numeric = chex.Numeric
VTraceOutput = collections.namedtuple(
    'VTraceOutput', ['errors', 'pg_advantage', 'q_estimate'])


def vtrace(
    v_tm1: Array,
    v_t: Array,
    r_t: Array,
    discount_t: Array,
    rho_tm1: Array,
    lambda_: Numeric = 1.0,
    clip_rho_threshold: float = 1.0,
    stop_target_gradients: bool = True,
) -> Array:
    """V-trace errors from importance weights.

    Args:
        v_tm1: values at time t-1, shape [T].
        v_t: values at time t, shape [T].
        r_t: rewards at time t, shape [T].
        discount_t: discounts at time t, shape [T].
        rho_tm1: importance sampling ratios, shape [T].
        lambda_: mixing parameter.
        clip_rho_threshold: clip threshold for importance weights.
        stop_target_gradients: whether to stop gradient through targets.

    Returns:
        V-trace errors, shape [T].
    """
    chex.assert_rank(
        [v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_],
        [1, 1, 1, 1, 1, {0, 1}])
    chex.assert_type(
        [v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_], float)
    chex.assert_equal_shape([v_tm1, v_t, r_t, discount_t, rho_tm1])
    raise NotImplementedError


def vtrace_td_error_and_advantage(
    v_tm1: Array,
    v_t: Array,
    r_t: Array,
    discount_t: Array,
    rho_tm1: Array,
    lambda_: Numeric = 1.0,
    clip_rho_threshold: float = 1.0,
    clip_pg_rho_threshold: float = 1.0,
    stop_target_gradients: bool = True,
) -> VTraceOutput:
    """V-trace errors, Q-estimates, and policy gradient advantages.

    Args:
        v_tm1: values at time t-1, shape [T].
        v_t: values at time t, shape [T].
        r_t: rewards at time t, shape [T].
        discount_t: discounts at time t, shape [T].
        rho_tm1: importance sampling ratios, shape [T].
        lambda_: mixing parameter.
        clip_rho_threshold: clip threshold for value errors.
        clip_pg_rho_threshold: clip threshold for PG advantages.
        stop_target_gradients: whether to stop gradient through targets.

    Returns:
        VTraceOutput with errors, pg_advantage, q_estimate.
    """
    chex.assert_rank(
        [v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_],
        [1, 1, 1, 1, 1, {0, 1}])
    chex.assert_type(
        [v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_], float)
    chex.assert_equal_shape([v_tm1, v_t, r_t, discount_t, rho_tm1])
    raise NotImplementedError
