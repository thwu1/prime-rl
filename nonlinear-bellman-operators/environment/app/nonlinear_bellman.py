"""Transformed (nonlinear Bellman) value function targets.

Computes TD errors for value functions that are solutions to nonlinear
Bellman equations via element-wise nonlinear transforms.
"""

import collections

import chex
import jax.numpy as jnp
import base as base_lib
import multistep
import transforms
import vtrace

Array = chex.Array

TxPair = collections.namedtuple('TxPair', ['apply', 'apply_inv'])

IDENTITY_PAIR = TxPair(transforms.identity, transforms.identity)
SIGNED_LOGP1_PAIR = TxPair(transforms.signed_logp1, transforms.signed_expm1)
SIGNED_HYPERBOLIC_PAIR = TxPair(
    transforms.signed_hyperbolic, transforms.signed_parabolic)
HYPERBOLIC_SIN_PAIR = TxPair(
    transforms.hyperbolic_arcsin, transforms.hyperbolic_sin)


def compose_tx(*tx_list):
    """Compose a sequence of TxPairs into a single TxPair.

    Args:
        *tx_list: sequence of TxPair objects.

    Returns:
        A composed TxPair.
    """
    raise NotImplementedError


def transformed_q_lambda(
    q_tm1: Array,
    a_tm1: Array,
    r_t: Array,
    discount_t: Array,
    q_t: Array,
    lambda_: Array,
    stop_target_gradients: bool = True,
    tx_pair: TxPair = IDENTITY_PAIR,
) -> Array:
    """Q(lambda) TD error in transformed value space.

    Args:
        q_tm1: Q-values at t-1, shape [T, A].
        a_tm1: action indices at t-1, shape [T].
        r_t: rewards, shape [T].
        discount_t: discounts, shape [T].
        q_t: Q-values at t, shape [T, A].
        lambda_: mixing parameter.
        stop_target_gradients: block gradient through targets.
        tx_pair: transform pair.

    Returns:
        TD errors, shape [T].
    """
    chex.assert_rank([q_tm1, a_tm1, r_t, discount_t, q_t, lambda_],
                     [2, 1, 1, 1, 2, {0, 1}])
    chex.assert_type([q_tm1, a_tm1, r_t, discount_t, q_t, lambda_],
                     [float, int, float, float, float, float])
    raise NotImplementedError


def transformed_retrace(
    q_tm1: Array,
    q_t: Array,
    a_tm1: Array,
    a_t: Array,
    r_t: Array,
    discount_t: Array,
    pi_t: Array,
    mu_t: Array,
    lambda_: float,
    eps: float = 1e-8,
    stop_target_gradients: bool = True,
    tx_pair: TxPair = IDENTITY_PAIR,
) -> Array:
    """Retrace TD error in transformed value space.

    Args:
        q_tm1: Q-values at t-1, shape [T, A].
        q_t: target network Q-values at t, shape [T, A].
        a_tm1: actions at t-1, shape [T].
        a_t: actions at t, shape [T].
        r_t: rewards, shape [T].
        discount_t: discounts, shape [T].
        pi_t: target policy probs, shape [T, A].
        mu_t: behavior policy probs, shape [T].
        lambda_: mixing parameter.
        eps: numerical stability constant.
        stop_target_gradients: block gradient through targets.
        tx_pair: transform pair.

    Returns:
        TD errors, shape [T].
    """
    chex.assert_rank([q_tm1, q_t, a_tm1, a_t, r_t, discount_t, pi_t, mu_t],
                     [2, 2, 1, 1, 1, 1, 2, 1])
    chex.assert_type([q_tm1, q_t, a_tm1, a_t, r_t, discount_t, pi_t, mu_t],
                     [float, float, int, int, float, float, float, float])
    raise NotImplementedError


def transformed_n_step_q_learning(
    q_tm1: Array,
    a_tm1: Array,
    target_q_t: Array,
    a_t: Array,
    r_t: Array,
    discount_t: Array,
    n: int,
    stop_target_gradients: bool = True,
    tx_pair: TxPair = IDENTITY_PAIR,
) -> Array:
    """N-step Q-learning TD error in transformed value space.

    Args:
        q_tm1: Q-values at [0..T-1], shape [T, A].
        a_tm1: actions at [0..T-1], shape [T].
        target_q_t: target Q-values at [1..T], shape [T, A].
        a_t: bootstrap action indices, shape [T].
        r_t: rewards, shape [T].
        discount_t: discounts, shape [T].
        n: bootstrap horizon.
        stop_target_gradients: block gradient through targets.
        tx_pair: transform pair.

    Returns:
        TD errors, shape [T].
    """
    chex.assert_rank([q_tm1, target_q_t, a_tm1, a_t, r_t, discount_t],
                     [2, 2, 1, 1, 1, 1])
    chex.assert_type([q_tm1, target_q_t, a_tm1, a_t, r_t, discount_t],
                     [float, float, int, int, float, float])
    raise NotImplementedError


def transformed_vtrace(
    v_tm1: Array,
    v_t: Array,
    r_t: Array,
    discount_t: Array,
    rho_tm1: Array,
    lambda_: float = 1.0,
    clip_rho_threshold: float = 1.0,
    stop_target_gradients: bool = True,
    tx_pair: TxPair = IDENTITY_PAIR,
) -> Array:
    """V-trace TD error in transformed value space.

    Args:
        v_tm1: state values at t-1, shape [T].
        v_t: state values at t, shape [T].
        r_t: rewards, shape [T].
        discount_t: discounts, shape [T].
        rho_tm1: importance sampling ratios, shape [T].
        lambda_: mixing parameter.
        clip_rho_threshold: clip threshold.
        stop_target_gradients: block gradient through targets.
        tx_pair: transform pair.

    Returns:
        TD errors, shape [T].
    """
    chex.assert_rank([v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_],
                     [1, 1, 1, 1, 1, {0, 1}])
    chex.assert_type([v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_], float)
    raise NotImplementedError
