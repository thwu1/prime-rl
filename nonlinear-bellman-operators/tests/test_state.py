"""Tests for nonlinear Bellman operator library with V-trace.

Verifies transforms, multistep returns, V-trace corrections, composed
transformed algorithms, and gradient correctness against golden reference
arrays and mathematical invariants.
"""

import sys
sys.path.insert(0, '/app')

import functools
import pytest
import numpy as np
import jax
import jax.numpy as jnp

jax.config.update('jax_numpy_rank_promotion', 'raise')

import transforms
import multistep
import vtrace
import nonlinear_bellman
from nonlinear_bellman import (
    TxPair, IDENTITY_PAIR, SIGNED_LOGP1_PAIR,
    SIGNED_HYPERBOLIC_PAIR, HYPERBOLIC_SIN_PAIR,
    compose_tx,
)


# =====================================================================
# Transform inverse tests
# =====================================================================

class TestTransformInverses:
    """Each transform pair must be an exact inverse."""

    @pytest.fixture
    def test_values(self):
        return np.array(
            [[[1.2, 2.2], [-1.2, 0.2], [2.2, -1.2]],
             [[4.2, 2.2], [1.2, 1.2], [-1.2, -2.2]]],
            dtype=np.float64)

    @pytest.mark.parametrize("tx_pair", [
        IDENTITY_PAIR, SIGNED_LOGP1_PAIR,
        SIGNED_HYPERBOLIC_PAIR, HYPERBOLIC_SIN_PAIR,
    ], ids=["identity", "signed_logp1", "signed_hyperbolic", "hyperbolic_sin"])
    def test_roundtrip_forward_inverse(self, tx_pair, test_values):
        tx, inv_tx = tx_pair
        np.testing.assert_allclose(
            inv_tx(tx(test_values)), test_values, rtol=1e-3)

    @pytest.mark.parametrize("tx_pair", [
        IDENTITY_PAIR, SIGNED_LOGP1_PAIR,
        SIGNED_HYPERBOLIC_PAIR, HYPERBOLIC_SIN_PAIR,
    ], ids=["identity", "signed_logp1", "signed_hyperbolic", "hyperbolic_sin"])
    def test_roundtrip_inverse_forward(self, tx_pair, test_values):
        tx, inv_tx = tx_pair
        np.testing.assert_allclose(
            tx(inv_tx(test_values)), test_values, rtol=1e-3)


# =====================================================================
# compose_tx tests
# =====================================================================

class TestComposeTx:
    """compose_tx must produce valid composed pairs."""

    def test_compose_two_pairs(self):
        composed = compose_tx(SIGNED_LOGP1_PAIR, SIGNED_HYPERBOLIC_PAIR)
        x = np.array([1.0, -2.0, 3.5, 0.0], dtype=np.float64)
        y = composed.apply(x)
        x_reconstructed = composed.apply_inv(y)
        np.testing.assert_allclose(x, x_reconstructed, rtol=1e-3)

    def test_compose_three_pairs(self):
        composed = compose_tx(
            SIGNED_LOGP1_PAIR, IDENTITY_PAIR, HYPERBOLIC_SIN_PAIR)
        x = np.array([0.5, -1.0, 2.0], dtype=np.float64)
        y = composed.apply(x)
        x_reconstructed = composed.apply_inv(y)
        np.testing.assert_allclose(x, x_reconstructed, rtol=1e-3)

    def test_compose_order_matters(self):
        """Forward applies in order: compose(f,g).apply(x) = g(f(x))."""
        x = np.array([1.5], dtype=np.float64)
        composed_fg = compose_tx(SIGNED_LOGP1_PAIR, HYPERBOLIC_SIN_PAIR)
        composed_gf = compose_tx(HYPERBOLIC_SIN_PAIR, SIGNED_LOGP1_PAIR)
        # These should generally differ
        y_fg = composed_fg.apply(x)
        y_gf = composed_gf.apply(x)
        # Both should still be invertible
        np.testing.assert_allclose(
            composed_fg.apply_inv(y_fg), x, rtol=1e-3)
        np.testing.assert_allclose(
            composed_gf.apply_inv(y_gf), x, rtol=1e-3)


# =====================================================================
# Lambda returns tests
# =====================================================================

class TestLambdaReturns:
    """Direct tests of the lambda_returns function."""

    def test_basic_sequence(self):
        r_t = jnp.array([-1.3, -1.3, 2.3], dtype=jnp.float32)
        discount_t = jnp.array([0., 0.89, 0.85], dtype=jnp.float32)
        v_t = jnp.array([2.2, 0.2, 2.2], dtype=jnp.float32)
        lambda_ = 0.75

        result = multistep.lambda_returns(r_t, discount_t, v_t, lambda_)
        expected = np.array([-1.3, 1.528, 4.17], dtype=np.float32)
        np.testing.assert_allclose(result, expected, rtol=1e-3)

    def test_second_sequence(self):
        r_t = jnp.array([1.3, 5.3, -3.3], dtype=jnp.float32)
        discount_t = jnp.array([0.88, 1., 0.83], dtype=jnp.float32)
        v_t = jnp.array([4.2, 1.2, -1.2], dtype=jnp.float32)
        lambda_ = 0.75

        result = multistep.lambda_returns(
            r_t, discount_t, v_t, lambda_, stop_target_gradients=True)
        expected = np.array([3.79348, 2.378, -4.296], dtype=np.float32)
        np.testing.assert_allclose(result, expected, rtol=1e-3)

    def test_lambda_one_reduces_to_discounted_returns(self):
        """With lambda=1, lambda_returns should equal discounted returns."""
        r_t = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        v_t = jnp.array([10.0, 10.0, 10.0], dtype=jnp.float32)

        result = multistep.lambda_returns(r_t, discount_t, v_t, lambda_=1.0)
        # With lambda=1: G_2 = 3.0 + 0.9*10 = 12.0
        # G_1 = 2.0 + 0.9*12.0 = 12.8
        # G_0 = 1.0 + 0.9*12.8 = 12.52
        expected = np.array([12.52, 12.8, 12.0], dtype=np.float32)
        np.testing.assert_allclose(result, expected, rtol=1e-3)


# =====================================================================
# V-trace tests
# =====================================================================

class TestVTrace:
    """Tests for the V-trace error computation."""

    def test_on_policy(self):
        """With rho=1, V-trace computes standard multistep corrections."""
        v_tm1 = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 5.0], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([1.0, 1.0, 1.0], dtype=jnp.float32)

        result = vtrace.vtrace(v_tm1, v_t, r_t, discount_t, rho_tm1,
                               lambda_=1.0, clip_rho_threshold=1.0)
        expected = np.array([3.505, 2.45, 2.5], dtype=np.float32)
        np.testing.assert_allclose(result, expected, rtol=1e-3)

    def test_off_policy_clipping(self):
        """Off-policy with clipped importance weights."""
        v_tm1 = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 5.0], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([2.0, 0.5, 1.5], dtype=jnp.float32)

        result = vtrace.vtrace(v_tm1, v_t, r_t, discount_t, rho_tm1,
                               lambda_=1.0, clip_rho_threshold=1.0)
        expected = np.array([2.4025, 1.225, 2.5], dtype=np.float32)
        np.testing.assert_allclose(result, expected, rtol=1e-3)

    def test_episode_boundary(self):
        """Discount=0 at boundary decouples episodes."""
        v_tm1 = jnp.array([1.0, 2.0, 3.0, 0.5], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 0.5, 1.5], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0, 0.3], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.0, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([1.0, 1.0, 1.0, 1.0], dtype=jnp.float32)

        result = vtrace.vtrace(v_tm1, v_t, r_t, discount_t, rho_tm1,
                               lambda_=1.0, clip_rho_threshold=1.0)
        expected = np.array([-0.95, -2.5, -0.515, 1.15], dtype=np.float32)
        np.testing.assert_allclose(result, expected, rtol=1e-3)

    def test_vtrace_lambda_zero(self):
        """With lambda=0, corrections do not propagate across timesteps."""
        v_tm1 = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 5.0], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([2.0, 0.5, 1.5], dtype=jnp.float32)

        result = vtrace.vtrace(v_tm1, v_t, r_t, discount_t, rho_tm1,
                               lambda_=0.0, clip_rho_threshold=1.0,
                               stop_target_gradients=False)
        # lambda=0 => c=0 => no backward propagation; each error is independent
        clipped = jnp.minimum(1.0, rho_tm1)
        expected = clipped * (r_t + discount_t * v_t - v_tm1)
        np.testing.assert_allclose(result, expected, rtol=1e-3)

    def test_higher_clip_threshold(self):
        """With clip_rho_threshold>1, larger importance weights are preserved."""
        v_tm1 = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 5.0], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([2.0, 0.5, 1.5], dtype=jnp.float32)

        result = vtrace.vtrace(v_tm1, v_t, r_t, discount_t, rho_tm1,
                               lambda_=1.0, clip_rho_threshold=5.0)
        # clipped_rho = min(5, [2,0.5,1.5]) = [2,0.5,1.5]
        # c = min(1, rho)*1 = [1,0.5,1]
        # td = [2*1.3, 0.5*0.2, 1.5*2.5] = [2.6, 0.1, 3.75]
        # scan: t=2: 3.75, t=1: 0.1+0.9*0.5*3.75=1.7875, t=0: 2.6+0.9*1*1.7875=4.20875
        expected = np.array([4.20875, 1.7875, 3.75], dtype=np.float32)
        np.testing.assert_allclose(result, expected, rtol=1e-3)


# =====================================================================
# V-trace TD error and advantage tests
# =====================================================================

class TestVTraceTdErrorAndAdvantage:
    """Tests for vtrace_td_error_and_advantage."""

    def test_golden_values(self):
        """Golden values for errors, q_estimate, and pg_advantage."""
        v_tm1 = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 5.0], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([2.0, 0.5, 1.5], dtype=jnp.float32)

        output = vtrace.vtrace_td_error_and_advantage(
            v_tm1, v_t, r_t, discount_t, rho_tm1,
            lambda_=0.7, clip_rho_threshold=1.0, clip_pg_rho_threshold=5.0)

        expected_errors = np.array([1.859125, 0.8875, 2.5], dtype=np.float32)
        expected_q = np.array([2.859125, 3.775, 5.5], dtype=np.float32)
        expected_pg = np.array([3.71825, 0.8875, 3.75], dtype=np.float32)

        np.testing.assert_allclose(output.errors, expected_errors, rtol=1e-3)
        np.testing.assert_allclose(output.q_estimate, expected_q, rtol=1e-3)
        np.testing.assert_allclose(output.pg_advantage, expected_pg, rtol=1e-3)

    def test_q_estimate_consistency(self):
        """v_s = v + clipped_rho * (q - v) must hold."""
        v_tm1 = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 5.0], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([2.0, 0.5, 1.5], dtype=jnp.float32)

        output = vtrace.vtrace_td_error_and_advantage(
            v_tm1, v_t, r_t, discount_t, rho_tm1,
            lambda_=0.8, clip_rho_threshold=1.0)

        targets = output.errors + v_tm1
        clipped_rho = jnp.minimum(1.0, rho_tm1)
        vs_from_q = v_tm1 + clipped_rho * (output.q_estimate - v_tm1)
        np.testing.assert_allclose(targets, vs_from_q, rtol=1e-3)


# =====================================================================
# Transformed Q(lambda) golden-value tests
# =====================================================================

class TestTransformedQLambda:
    """Golden-value tests for transformed_q_lambda across 4 transform pairs."""

    @pytest.fixture
    def data(self):
        d = {}
        d['lambda_'] = 0.75
        d['q_tm1'] = np.array(
            [[[1.1, 2.1], [-1.1, 1.1], [3.1, -3.1]],
             [[2.1, 3.1], [-1.1, 0.1], [-2.1, -1.1]]],
            dtype=np.float32)
        d['a_tm1'] = np.array(
            [[0, 1, 0], [1, 0, 0]], dtype=np.int32)
        d['discount_t'] = np.array(
            [[0., 0.89, 0.85], [0.88, 1., 0.83]], dtype=np.float32)
        d['r_t'] = np.array(
            [[-1.3, -1.3, 2.3], [1.3, 5.3, -3.3]], dtype=np.float32)
        d['q_t'] = np.array(
            [[[1.2, 2.2], [-1.2, 0.2], [2.2, -1.2]],
             [[4.2, 2.2], [1.2, 1.2], [-1.2, -2.2]]],
            dtype=np.float32)
        d['expected_td'] = np.array(
            [[[-2.4, 0.4280, 1.07], [0.6935, 3.478, -2.196]],
             [[-1.9329, 0.6643, -0.7854], [-0.20713, 2.1855, 0.27132]],
             [[-1.6179, 0.4633, -0.7576], [-1.1097, 1.6509, 0.3598]],
             [[-2.1785, 0.6562, -0.5938], [-0.0892, 2.6553, -0.1208]]],
            dtype=np.float32)
        return d

    @pytest.mark.parametrize("tx_pair,td_index", [
        (IDENTITY_PAIR, 0),
        (SIGNED_LOGP1_PAIR, 1),
        (SIGNED_HYPERBOLIC_PAIR, 2),
        (HYPERBOLIC_SIN_PAIR, 3),
    ], ids=["identity", "signed_logp1", "signed_hyperbolic", "hyperbolic_sin"])
    def test_golden_values(self, tx_pair, td_index, data):
        fn = jax.vmap(functools.partial(
            nonlinear_bellman.transformed_q_lambda,
            tx_pair=tx_pair, lambda_=data['lambda_']))
        actual_td = fn(
            data['q_tm1'], data['a_tm1'], data['r_t'],
            data['discount_t'], data['q_t'])
        np.testing.assert_allclose(
            data['expected_td'][td_index], actual_td, rtol=1e-3)


# =====================================================================
# Transformed Retrace golden-value tests
# =====================================================================

class TestTransformedRetrace:
    """Golden-value tests for transformed_retrace across 4 transform pairs."""

    @pytest.fixture
    def data(self):
        d = {}
        d['lambda_'] = 0.9
        d['qs'] = np.array(
            [[[1.1, 2.1], [-1.1, 1.1], [3.1, -3.1], [-1.2, 0.0]],
             [[2.1, 3.1], [9.5, 0.1], [-2.1, -1.1], [0.1, 7.4]]],
            dtype=np.float32)
        d['targnet_qs'] = np.array(
            [[[1.2, 2.2], [-1.2, 0.2], [2.2, -1.2], [-2.25, -6.0]],
             [[4.2, 2.2], [1.2, 1.2], [-1.2, -2.2], [1.5, 1.0]]],
            dtype=np.float32)
        d['actions'] = np.array(
            [[0, 1, 0, 0], [1, 0, 0, 1]], dtype=np.int32)
        d['rewards'] = np.array(
            [[-1.3, -1.3, 2.3, 42.0], [1.3, 5.3, -3.3, -5.0]],
            dtype=np.float32)
        d['pcontinues'] = np.array(
            [[0., 0.89, 0.85, 0.99], [0.88, 1., 0.83, 0.95]],
            dtype=np.float32)
        d['target_policy_probs'] = np.array(
            [[[0.5, 0.5], [0.2, 0.8], [0.6, 0.4], [0.9, 0.1]],
             [[0.1, 0.9], [1.0, 0.0], [0.3, 0.7], [0.7, 0.3]]],
            dtype=np.float32)
        d['behavior_policy_probs'] = np.array(
            [[0.5, 0.1, 0.9, 0.3], [0.4, 0.6, 1.0, 0.9]],
            dtype=np.float32)
        d['expected_td'] = np.array(
            [[[-2.4, -2.7905, -3.0313], [0.7889, -6.3645, -0.0795]],
             [[-1.9329, -4.2626, -6.7738], [-2.3989, -9.9802, 1.4852]],
             [[-1.6179, -3.0165, -5.2699], [-2.7742, -9.9544, 2.3167]],
             [[-2.1785, -4.2530, -6.7081], [-1.3654, -8.2213, 0.7641]]],
            dtype=np.float32)
        return d

    @pytest.mark.parametrize("tx_pair,td_index", [
        (IDENTITY_PAIR, 0),
        (SIGNED_LOGP1_PAIR, 1),
        (SIGNED_HYPERBOLIC_PAIR, 2),
        (HYPERBOLIC_SIN_PAIR, 3),
    ], ids=["identity", "signed_logp1", "signed_hyperbolic", "hyperbolic_sin"])
    def test_golden_values(self, tx_pair, td_index, data):
        fn = jax.vmap(functools.partial(
            nonlinear_bellman.transformed_retrace,
            tx_pair=tx_pair, lambda_=data['lambda_']))
        actual_td = fn(
            data['qs'][:, :-1], data['targnet_qs'][:, 1:],
            data['actions'][:, :-1], data['actions'][:, 1:],
            data['rewards'][:, :-1], data['pcontinues'][:, :-1],
            data['target_policy_probs'][:, 1:],
            data['behavior_policy_probs'][:, 1:])
        np.testing.assert_allclose(
            data['expected_td'][td_index], actual_td, rtol=1e-3)


# =====================================================================
# Transformed N-step Q-learning golden-value tests
# =====================================================================

class TestTransformedNStepQLearning:
    """Golden-value tests for transformed_n_step_q_learning across 4 pairs."""

    @pytest.fixture
    def data(self):
        d = {}
        d['n'] = 2
        d['q_tm1'] = np.array(
            [[[1.1, 2.1], [-1.1, 1.1], [3.1, -3.1]],
             [[2.1, 3.1], [-1.1, 0.1], [-2.1, -1.1]]],
            dtype=np.float32)
        d['a_tm1'] = np.array(
            [[0, 1, 0], [1, 0, 0]], dtype=np.int32)
        d['discount_t'] = np.array(
            [[0., 0.89, 0.85], [0.88, 1., 0.83]], dtype=np.float32)
        d['r_t'] = np.array(
            [[-1.3, -1.3, 2.3], [1.3, 5.3, -3.3]], dtype=np.float32)
        d['target_q_t'] = np.array(
            [[[1.2, 2.2], [-1.2, 0.2], [2.2, -1.2]],
             [[4.2, 2.2], [1.2, 1.2], [-1.2, -2.2]]],
            dtype=np.float32)
        d['a_t'] = np.array(
            [[0, 1, 0], [1, 0, 0]], dtype=np.int32)
        d['expected_td'] = np.array([
            [[-2.4, 1.3112999, 1.0700002],
             [3.9199996, 2.104, -2.196]],
            [[-1.9329091, 0.9564189, -0.7853615],
             [-0.9021418, 1.1716722, 0.2713145]],
            [[-1.6178751, 0.85600746, -0.75762916],
             [-0.87689304, 0.6246443, 0.3598088]],
            [[-2.178451, 1.02313, -0.593768],
             [-0.415362, 1.790864, -0.120749]]
        ], dtype=np.float32)
        return d

    @pytest.mark.parametrize("tx_pair,td_index", [
        (IDENTITY_PAIR, 0),
        (SIGNED_LOGP1_PAIR, 1),
        (SIGNED_HYPERBOLIC_PAIR, 2),
        (HYPERBOLIC_SIN_PAIR, 3),
    ], ids=["identity", "signed_logp1", "signed_hyperbolic", "hyperbolic_sin"])
    def test_golden_values(self, tx_pair, td_index, data):
        fn = jax.vmap(functools.partial(
            nonlinear_bellman.transformed_n_step_q_learning,
            tx_pair=tx_pair, n=data['n']))
        actual_td = fn(
            data['q_tm1'], data['a_tm1'], data['target_q_t'],
            data['a_t'], data['r_t'], data['discount_t'])
        np.testing.assert_allclose(
            data['expected_td'][td_index], actual_td, rtol=1e-3)


# =====================================================================
# Transformed V-trace tests
# =====================================================================

class TestTransformedVTrace:
    """Tests for transformed_vtrace across transform pairs."""

    @pytest.fixture
    def data(self):
        d = {}
        d['v_tm1'] = np.array(
            [[1.0, 2.0, 3.0],
             [3.0, 1.0, 0.0]], dtype=np.float32)
        d['v_t'] = np.array(
            [[2.0, 3.0, 5.0],
             [1.0, 0.0, 2.0]], dtype=np.float32)
        d['r_t'] = np.array(
            [[0.5, -0.5, 1.0],
             [1.0, -1.0, 2.0]], dtype=np.float32)
        d['discount_t'] = np.array(
            [[0.9, 0.9, 0.9],
             [0.95, 0.0, 0.9]], dtype=np.float32)
        d['rho_tm1'] = np.array(
            [[2.0, 0.5, 1.5],
             [0.3, 3.0, 0.8]], dtype=np.float32)
        # Identity expected: matches regular vtrace
        d['expected_identity'] = np.array(
            [[2.4025, 1.225, 2.5],
             [-0.885, -2.0, 3.04]], dtype=np.float32)
        return d

    def test_identity_matches_vtrace(self, data):
        """With IDENTITY_PAIR, transformed_vtrace matches regular vtrace."""
        fn = jax.vmap(functools.partial(
            nonlinear_bellman.transformed_vtrace,
            tx_pair=IDENTITY_PAIR, lambda_=1.0))
        actual = fn(data['v_tm1'], data['v_t'], data['r_t'],
                    data['discount_t'], data['rho_tm1'])
        np.testing.assert_allclose(actual, data['expected_identity'], rtol=1e-3)

    @pytest.mark.parametrize("tx_pair", [
        SIGNED_LOGP1_PAIR, SIGNED_HYPERBOLIC_PAIR, HYPERBOLIC_SIN_PAIR,
    ], ids=["signed_logp1", "signed_hyperbolic", "hyperbolic_sin"])
    def test_non_identity_differs(self, tx_pair, data):
        """Non-identity transforms produce different results than identity."""
        fn_id = jax.vmap(functools.partial(
            nonlinear_bellman.transformed_vtrace,
            tx_pair=IDENTITY_PAIR, lambda_=1.0))
        fn_tx = jax.vmap(functools.partial(
            nonlinear_bellman.transformed_vtrace,
            tx_pair=tx_pair, lambda_=1.0))
        td_id = fn_id(data['v_tm1'], data['v_t'], data['r_t'],
                      data['discount_t'], data['rho_tm1'])
        td_tx = fn_tx(data['v_tm1'], data['v_t'], data['r_t'],
                      data['discount_t'], data['rho_tm1'])
        assert not np.allclose(td_id, td_tx, rtol=1e-2)

    @pytest.mark.parametrize("tx_pair", [
        SIGNED_LOGP1_PAIR, SIGNED_HYPERBOLIC_PAIR, HYPERBOLIC_SIN_PAIR,
    ], ids=["signed_logp1", "signed_hyperbolic", "hyperbolic_sin"])
    def test_target_invertibility(self, tx_pair, data):
        """Transformed targets round-trip through inverse transform."""
        fn = jax.vmap(functools.partial(
            nonlinear_bellman.transformed_vtrace,
            tx_pair=tx_pair, lambda_=1.0))
        td = fn(data['v_tm1'], data['v_t'], data['r_t'],
                data['discount_t'], data['rho_tm1'])
        targets = td + data['v_tm1']
        # Round-trip through transform
        np.testing.assert_allclose(
            tx_pair.apply(tx_pair.apply_inv(targets)), targets, rtol=1e-3)


# =====================================================================
# Composed transform integration tests
# =====================================================================

class TestComposedTransformAlgorithms:
    """Tests for composed transforms used in TD-error functions."""

    def test_identity_composition_q_lambda(self):
        """compose_tx(IDENTITY, IDENTITY) matches plain IDENTITY for Q(lambda)."""
        composed = compose_tx(IDENTITY_PAIR, IDENTITY_PAIR)
        q_tm1 = jnp.array([[1.1, 2.1], [-1.1, 1.1]], dtype=jnp.float32)
        a_tm1 = jnp.array([0, 1], dtype=jnp.int32)
        r_t = jnp.array([-1.3, 2.3], dtype=jnp.float32)
        discount_t = jnp.array([0.89, 0.85], dtype=jnp.float32)
        q_t = jnp.array([[1.2, 2.2], [2.2, -1.2]], dtype=jnp.float32)

        td_composed = nonlinear_bellman.transformed_q_lambda(
            q_tm1, a_tm1, r_t, discount_t, q_t,
            lambda_=0.75, tx_pair=composed)
        td_identity = nonlinear_bellman.transformed_q_lambda(
            q_tm1, a_tm1, r_t, discount_t, q_t,
            lambda_=0.75, tx_pair=IDENTITY_PAIR)
        np.testing.assert_allclose(td_composed, td_identity, rtol=1e-3)

    def test_composed_transform_roundtrip_in_vtrace(self):
        """Composed transform applied and inverted produces valid targets."""
        composed = compose_tx(SIGNED_LOGP1_PAIR, HYPERBOLIC_SIN_PAIR)
        v_tm1 = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 5.0], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([1.0, 1.0, 1.0], dtype=jnp.float32)

        td = nonlinear_bellman.transformed_vtrace(
            v_tm1, v_t, r_t, discount_t, rho_tm1,
            lambda_=1.0, tx_pair=composed)
        targets = td + v_tm1
        # Targets must round-trip through the composed transform
        np.testing.assert_allclose(
            composed.apply(composed.apply_inv(targets)), targets, rtol=1e-3)


# =====================================================================
# Gradient correctness tests
# =====================================================================

class TestGradientCorrectness:
    """Verify that stop_target_gradients controls gradient flow."""

    def test_lambda_returns_stop_gradient(self):
        """stop_target_gradients=True blocks gradient through v_t."""
        r_t = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        v_t = jnp.array([1.0, 1.0, 1.0], dtype=jnp.float32)

        def f(v):
            return jnp.sum(multistep.lambda_returns(
                r_t, discount_t, v, 0.75, stop_target_gradients=True))
        grad = jax.grad(f)(v_t)
        np.testing.assert_allclose(grad, np.zeros(3), atol=1e-5)

    def test_lambda_returns_gradient_flows(self):
        """stop_target_gradients=False allows gradient through v_t."""
        r_t = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        v_t = jnp.array([1.0, 1.0, 1.0], dtype=jnp.float32)

        def f(v):
            return jnp.sum(multistep.lambda_returns(
                r_t, discount_t, v, 0.75, stop_target_gradients=False))
        grad = jax.grad(f)(v_t)
        assert not np.allclose(grad, np.zeros(3), atol=1e-5)

    def test_lambda_returns_gradient_values(self):
        """Verify specific gradient magnitudes when gradients flow."""
        r_t = jnp.array([1.0, 2.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9], dtype=jnp.float32)
        v_t = jnp.array([1.0, 1.0], dtype=jnp.float32)

        def f(v):
            return jnp.sum(multistep.lambda_returns(
                r_t, discount_t, v, 0.5, stop_target_gradients=False))
        grad = jax.grad(f)(v_t)
        # Analytically: d(sum)/dv[0] = 0.45, d(sum)/dv[1] = 1.305
        expected_grad = np.array([0.45, 1.305], dtype=np.float32)
        np.testing.assert_allclose(grad, expected_grad, rtol=1e-3)

    def test_vtrace_stop_gradient(self):
        """stop_target_gradients=True blocks gradient through v_t in vtrace."""
        v_tm1 = jnp.array([1.0, 2.0, 3.0], dtype=jnp.float32)
        v_t = jnp.array([2.0, 3.0, 5.0], dtype=jnp.float32)
        r_t = jnp.array([0.5, -0.5, 1.0], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.9], dtype=jnp.float32)
        rho_tm1 = jnp.array([1.0, 1.0, 1.0], dtype=jnp.float32)

        def f(v):
            return jnp.sum(vtrace.vtrace(
                v_tm1, v, r_t, discount_t, rho_tm1,
                stop_target_gradients=True))
        grad = jax.grad(f)(v_t)
        np.testing.assert_allclose(grad, np.zeros(3), atol=1e-5)

    def test_transformed_vtrace_stop_gradient(self):
        """stop_target_gradients blocks gradient in transformed vtrace."""
        v_tm1 = jnp.array([0.5, -0.3, 1.0], dtype=jnp.float32)
        v_t = jnp.array([1.0, 0.5, -0.2], dtype=jnp.float32)
        r_t = jnp.array([0.1, -0.3, 0.2], dtype=jnp.float32)
        discount_t = jnp.array([0.9, 0.9, 0.8], dtype=jnp.float32)
        rho_tm1 = jnp.array([1.5, 0.5, 2.0], dtype=jnp.float32)

        for tx_pair in [IDENTITY_PAIR, SIGNED_LOGP1_PAIR]:
            def f(v, txp=tx_pair):
                return jnp.sum(nonlinear_bellman.transformed_vtrace(
                    v_tm1, v, r_t, discount_t, rho_tm1,
                    stop_target_gradients=True, tx_pair=txp))
            grad = jax.grad(f)(v_t)
            np.testing.assert_allclose(grad, np.zeros(3), atol=1e-5)
