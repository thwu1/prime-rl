#!/usr/bin/env python3
"""Write correct implementations of the nonlinear Bellman library modules."""

import textwrap

# Fix: signed_parabolic must use jnp.abs(x) in the z formula
TRANSFORMS_SRC = textwrap.dedent('''\
    """Non-linear value transforms for reinforcement learning."""

    import chex
    import jax
    import jax.numpy as jnp

    Array = chex.Array
    Numeric = chex.Numeric


    def identity(x: Array) -> Array:
        """Identity transform."""
        chex.assert_type(x, float)
        return x


    def signed_logp1(x: Array) -> Array:
        """Signed log(1+|x|)."""
        chex.assert_type(x, float)
        return jnp.sign(x) * jnp.log1p(jnp.abs(x))


    def signed_expm1(x: Array) -> Array:
        """Inverse of signed_logp1."""
        chex.assert_type(x, float)
        return jnp.sign(x) * jnp.expm1(jnp.abs(x))


    def signed_hyperbolic(x: Array, eps: float = 1e-3) -> Array:
        """Signed hyperbolic squashing transform."""
        chex.assert_type(x, float)
        return jnp.sign(x) * (jnp.sqrt(jnp.abs(x) + 1) - 1) + eps * x


    def signed_parabolic(x: Array, eps: float = 1e-3) -> Array:
        """Inverse of signed_hyperbolic."""
        chex.assert_type(x, float)
        z = jnp.sqrt(1 + 4 * eps * (eps + 1 + jnp.abs(x))) / 2 / eps - 1 / 2 / eps
        return jnp.sign(x) * (jnp.square(z) - 1)


    def hyperbolic_sin(x: Array) -> Array:
        """Hyperbolic sine."""
        chex.assert_type(x, float)
        return jnp.sinh(x)


    def hyperbolic_arcsin(x: Array) -> Array:
        """Hyperbolic arcsine."""
        chex.assert_type(x, float)
        return jnp.arcsinh(x)
''')

MULTISTEP_SRC = textwrap.dedent('''\
    """Multistep return calculations for reinforcement learning."""

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
        """Multistep truncated lambda returns."""
        chex.assert_rank([r_t, discount_t, v_t, lambda_], [1, 1, 1, {0, 1}])
        chex.assert_type([r_t, discount_t, v_t, lambda_], float)
        chex.assert_equal_shape([r_t, discount_t, v_t])

        lambda_ = jnp.ones_like(discount_t) * lambda_

        def _body(acc, xs):
            returns, discounts, values, lam = xs
            acc = returns + discounts * ((1 - lam) * values + lam * acc)
            return acc, acc

        _, returns = jax.lax.scan(
            _body, v_t[-1], (r_t, discount_t, v_t, lambda_), reverse=True)

        return jax.lax.select(stop_target_gradients,
                              jax.lax.stop_gradient(returns), returns)


    def n_step_bootstrapped_returns(
        r_t: Array,
        discount_t: Array,
        v_t: Array,
        n: int,
        lambda_t: Numeric = 1.,
        stop_target_gradients: bool = False,
    ) -> Array:
        """Strided n-step bootstrapped return targets."""
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
        """Off-policy return targets from action values."""
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
        """Core off-policy return computation."""
        chex.assert_rank([q_t, v_t, r_t, discount_t, c_t], 1)
        chex.assert_type([q_t, v_t, r_t, discount_t, c_t], float)
        chex.assert_equal_shape([q_t, v_t[:-1], r_t[:-1], discount_t[:-1], c_t])

        g = r_t[-1] + discount_t[-1] * v_t[-1]

        def _body(acc, xs):
            reward, discount, c, v, q = xs
            acc = reward + discount * (v - c * q + c * acc)
            return acc, acc

        _, returns = jax.lax.scan(
            _body, g, (r_t[:-1], discount_t[:-1], c_t, v_t[:-1], q_t),
            reverse=True)
        returns = jnp.concatenate([returns, g[jnp.newaxis]], axis=0)

        return jax.lax.select(stop_target_gradients,
                              jax.lax.stop_gradient(returns), returns)
''')

VTRACE_SRC = textwrap.dedent('''\
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
        """Calculates V-trace errors from importance weights."""
        chex.assert_rank(
            [v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_],
            [1, 1, 1, 1, 1, {0, 1}])
        chex.assert_type(
            [v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_], float)
        chex.assert_equal_shape([v_tm1, v_t, r_t, discount_t, rho_tm1])

        c_tm1 = jnp.minimum(1.0, rho_tm1) * lambda_
        clipped_rhos_tm1 = jnp.minimum(clip_rho_threshold, rho_tm1)

        td_errors = clipped_rhos_tm1 * (r_t + discount_t * v_t - v_tm1)

        def _body(acc, xs):
            td_error, discount, c = xs
            acc = td_error + discount * c * acc
            return acc, acc

        _, errors = jax.lax.scan(
            _body, 0.0, (td_errors, discount_t, c_tm1), reverse=True)

        return jax.lax.select(
            stop_target_gradients,
            jax.lax.stop_gradient(errors + v_tm1) - v_tm1,
            errors)


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
        """Calculates V-trace errors, PG advantage, and Q-estimates."""
        chex.assert_rank(
            [v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_],
            [1, 1, 1, 1, 1, {0, 1}])
        chex.assert_type(
            [v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_], float)
        chex.assert_equal_shape([v_tm1, v_t, r_t, discount_t, rho_tm1])

        lambda_ = jnp.ones_like(discount_t) * lambda_

        errors = vtrace(
            v_tm1, v_t, r_t, discount_t, rho_tm1,
            lambda_, clip_rho_threshold, stop_target_gradients)

        targets_tm1 = errors + v_tm1
        q_bootstrap = jnp.concatenate([
            lambda_[:-1] * targets_tm1[1:] + (1 - lambda_[:-1]) * v_tm1[1:],
            v_t[-1:],
        ], axis=0)
        q_estimate = r_t + discount_t * q_bootstrap
        clipped_pg_rho_tm1 = jnp.minimum(clip_pg_rho_threshold, rho_tm1)
        pg_advantages = clipped_pg_rho_tm1 * (q_estimate - v_tm1)
        return VTraceOutput(
            errors=errors, pg_advantage=pg_advantages, q_estimate=q_estimate)
''')

NONLINEAR_BELLMAN_SRC = textwrap.dedent('''\
    """Transformed (nonlinear Bellman) value function targets."""

    import collections
    import functools

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
        """Compose a sequence of TxPairs."""
        def apply_fn(x):
            for tx in tx_list:
                x = tx.apply(x)
            return x

        def apply_inv_fn(x):
            for tx in tx_list[::-1]:
                x = tx.apply_inv(x)
            return x

        return TxPair(apply_fn, apply_inv_fn)


    def transform_values(build_targets, *value_argnums):
        """Decorator to convert targets to use transformed value function."""
        @functools.wraps(build_targets)
        def wrapped_build_targets(tx_pair, *args, **kwargs):
            tx_args = list(args)
            for index in value_argnums:
                tx_args[index] = tx_pair.apply_inv(tx_args[index])
            targets = build_targets(*tx_args, **kwargs)
            return tx_pair.apply(targets)
        return wrapped_build_targets


    transformed_lambda_returns = transform_values(multistep.lambda_returns, 2)
    transformed_general_off_policy_returns_from_action_values = transform_values(
        multistep.general_off_policy_returns_from_action_values, 0)
    transformed_n_step_returns = transform_values(
        multistep.n_step_bootstrapped_returns, 2)


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
        """Transformed Q(lambda) TD error."""
        chex.assert_rank([q_tm1, a_tm1, r_t, discount_t, q_t, lambda_],
                         [2, 1, 1, 1, 2, {0, 1}])
        chex.assert_type([q_tm1, a_tm1, r_t, discount_t, q_t, lambda_],
                         [float, int, float, float, float, float])

        qa_tm1 = base_lib.batched_index(q_tm1, a_tm1)
        v_t = jnp.max(q_t, axis=-1)
        target_tm1 = transformed_lambda_returns(
            tx_pair, r_t, discount_t, v_t, lambda_, stop_target_gradients)
        return target_tm1 - qa_tm1


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
        """Transformed Retrace TD error."""
        chex.assert_rank([q_tm1, q_t, a_tm1, a_t, r_t, discount_t, pi_t, mu_t],
                         [2, 2, 1, 1, 1, 1, 2, 1])
        chex.assert_type([q_tm1, q_t, a_tm1, a_t, r_t, discount_t, pi_t, mu_t],
                         [float, float, int, int, float, float, float, float])

        pi_a_t = base_lib.batched_index(pi_t, a_t)
        c_t = jnp.minimum(1.0, pi_a_t / (mu_t + eps)) * lambda_
        target_tm1 = transformed_general_off_policy_returns_from_action_values(
            tx_pair, q_t, a_t, r_t, discount_t, c_t, pi_t, stop_target_gradients)
        q_a_tm1 = base_lib.batched_index(q_tm1, a_tm1)
        return target_tm1 - q_a_tm1


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
        """Transformed n-step Q-learning TD error."""
        chex.assert_rank([q_tm1, target_q_t, a_tm1, a_t, r_t, discount_t],
                         [2, 2, 1, 1, 1, 1])
        chex.assert_type([q_tm1, target_q_t, a_tm1, a_t, r_t, discount_t],
                         [float, float, int, int, float, float])

        v_t = base_lib.batched_index(target_q_t, a_t)
        target_tm1 = transformed_n_step_returns(
            tx_pair, r_t, discount_t, v_t, n,
            stop_target_gradients=stop_target_gradients)
        q_a_tm1 = base_lib.batched_index(q_tm1, a_tm1)
        return target_tm1 - q_a_tm1


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
        """Transformed V-trace TD error."""
        chex.assert_rank([v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_],
                         [1, 1, 1, 1, 1, {0, 1}])
        chex.assert_type([v_tm1, v_t, r_t, discount_t, rho_tm1, lambda_], float)

        v_tm1_inv = tx_pair.apply_inv(v_tm1)
        v_t_inv = tx_pair.apply_inv(v_t)
        errors = vtrace.vtrace(
            v_tm1_inv, v_t_inv, r_t, discount_t, rho_tm1,
            lambda_, clip_rho_threshold, stop_target_gradients)
        targets = errors + v_tm1_inv
        return tx_pair.apply(targets) - v_tm1
''')


def main():
    with open('/app/transforms.py', 'w') as f:
        f.write(TRANSFORMS_SRC)
    print("Wrote /app/transforms.py (fixed signed_parabolic)")

    with open('/app/multistep.py', 'w') as f:
        f.write(MULTISTEP_SRC)
    print("Wrote /app/multistep.py")

    with open('/app/vtrace.py', 'w') as f:
        f.write(VTRACE_SRC)
    print("Wrote /app/vtrace.py")

    with open('/app/nonlinear_bellman.py', 'w') as f:
        f.write(NONLINEAR_BELLMAN_SRC)
    print("Wrote /app/nonlinear_bellman.py")

    print("Solution implementation complete.")


if __name__ == '__main__':
    main()
