"""
Numerical functions with custom VJP rules for JAX.

Each function implements a common numerical operation with a @custom_vjp
decorator for custom backward-pass differentiation.

"""

import jax
import jax.numpy as jnp
from jax import custom_vjp


# ============================================================
# Function 1: log1pexp (softplus)
# Computes log(1 + exp(x))
# ============================================================

@custom_vjp
def log1pexp(x):
    return jnp.log(1.0 + jnp.exp(x))

def log1pexp_fwd(x):
    ans = log1pexp(x)
    return ans, (x,)

def log1pexp_bwd(res, g):
    x, = res
    return (g * jnp.exp(x),)

log1pexp.defvjp(log1pexp_fwd, log1pexp_bwd)


# ============================================================
# Function 2: logsumexp (two-argument)
# Computes log(exp(a) + exp(b))
# ============================================================

@custom_vjp
def logsumexp(a, b):
    return jnp.log(jnp.exp(a) + jnp.exp(b))

def logsumexp_fwd(a, b):
    ans = logsumexp(a, b)
    return ans, (a, b)

def logsumexp_bwd(res, g):
    a, b = res
    ea = jnp.exp(a)
    eb = jnp.exp(b)
    total = ea + eb
    return (g * ea / total, g * eb / total)

logsumexp.defvjp(logsumexp_fwd, logsumexp_bwd)


# ============================================================
# Function 3: sigmoid
# Computes 1 / (1 + exp(-x))
# ============================================================

@custom_vjp
def sigmoid(x):
    return 1.0 / (1.0 + jnp.exp(-x))

def sigmoid_fwd(x):
    ans = sigmoid(x)
    return ans, (ans,)

def sigmoid_bwd(res, g):
    y, = res
    return (g * (1.0 - y) * (1.0 - y),)

sigmoid.defvjp(sigmoid_fwd, sigmoid_bwd)


# ============================================================
# Function 4: safe_sqrt
# Computes sqrt(max(x, 0)) with safe gradient near zero
# ============================================================

@custom_vjp
def safe_sqrt(x):
    return jnp.sqrt(jnp.maximum(x, 0.0))

def safe_sqrt_fwd(x):
    ans = safe_sqrt(x)
    return ans, (x,)

def safe_sqrt_bwd(res, g):
    x, = res
    eps = 1e-12
    safe_x = jnp.maximum(x, 0.0) - eps
    return (g * 0.5 / jnp.sqrt(jnp.abs(safe_x)),)

safe_sqrt.defvjp(safe_sqrt_fwd, safe_sqrt_bwd)


# ============================================================
# Function 5: huber_loss
# Computes Huber loss: 0.5*x^2 for |x|<=delta,
# delta*(|x| - 0.5*delta) otherwise
# ============================================================

@custom_vjp
def huber_loss(x, delta):
    abs_x = jnp.abs(x)
    return jnp.where(abs_x <= delta, 0.5 * x ** 2,
                     delta * (abs_x - 0.5 * delta))

def huber_loss_fwd(x, delta):
    ans = huber_loss(x, delta)
    return ans, (x, delta)

def huber_loss_bwd(res, g):
    x, delta = res
    abs_x = jnp.abs(x)
    dx = jnp.where(abs_x <= delta, g * x, g * x)
    return (dx, jnp.zeros_like(delta))

huber_loss.defvjp(huber_loss_fwd, huber_loss_bwd)


# ============================================================
# Function 6: log_cosh
# Computes log(cosh(x))
# NOTE: No custom_vjp — relies on JAX default autodiff
# ============================================================

def log_cosh(x):
    return jnp.log(jnp.cosh(x))
