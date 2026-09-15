"""Non-linear value function transforms.

Element-wise non-linear transformations for value estimates.
Each forward transform has a corresponding inverse.
"""

import chex
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
    z = jnp.sqrt(1 + 4 * eps * (eps + 1 + x)) / 2 / eps - 1 / 2 / eps
    return jnp.sign(x) * (jnp.square(z) - 1)


def hyperbolic_sin(x: Array) -> Array:
    """Hyperbolic sine."""
    chex.assert_type(x, float)
    return jnp.sinh(x)


def hyperbolic_arcsin(x: Array) -> Array:
    """Hyperbolic arcsine."""
    chex.assert_type(x, float)
    return jnp.arcsinh(x)
