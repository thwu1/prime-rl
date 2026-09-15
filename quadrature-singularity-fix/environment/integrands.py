"""
Test integrands for quadrature method evaluation.

Each integrand is defined over a specified finite domain and exercises
different aspects of numerical integration: smooth functions, endpoint
singularities (logarithmic and algebraic), and double-endpoint singularities.

No analytical reference values are provided. The evaluator must determine
accuracy through convergence analysis across methods of increasing order.
"""

import math


INTEGRANDS = {
    "smooth_rational": {
        "description": "4/(1+x^2) on [0, 1]",
        "a": 0.0,
        "b": 1.0,
    },
    "log_power": {
        "description": "(-log(x))^4 on (0, 1]",
        "a": 0.0,
        "b": 1.0,
    },
    "sqrt_inverse": {
        "description": "1/sqrt(x) on (0, 1]",
        "a": 0.0,
        "b": 1.0,
    },
    "beta_singular": {
        "description": "1/sqrt(x*(1-x)) on (0, 1)",
        "a": 0.0,
        "b": 1.0,
    },
    "log_product": {
        "description": "log(x)*log(1-x) on (0, 1)",
        "a": 0.0,
        "b": 1.0,
    },
    "log_sin": {
        "description": "log(sin(x)) on (0, pi/2)",
        "a": 0.0,
        "b": math.pi / 2.0,
    },
}


def smooth_rational(x):
    """4/(1+x^2) — smooth, no singularities."""
    return 4.0 / (1.0 + x * x)


def log_power(x):
    """(-log(x))^4 — logarithmic singularity at x=0."""
    if x <= 0.0:
        return 0.0
    return (-math.log(x)) ** 4


def sqrt_inverse(x):
    """1/sqrt(x) — algebraic (x^{-1/2}) singularity at x=0."""
    if x <= 0.0:
        return 0.0
    return 1.0 / math.sqrt(x)


def beta_singular(x):
    """1/sqrt(x*(1-x)) — algebraic singularity at both x=0 and x=1."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    return 1.0 / math.sqrt(x * (1.0 - x))


def log_product(x):
    """log(x)*log(1-x) — logarithmic singularity at both endpoints."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    return math.log(x) * math.log(1.0 - x)


def log_sin(x):
    """log(sin(x)) — logarithmic singularity at x=0."""
    if x <= 0.0:
        return 0.0
    s = math.sin(x)
    if s <= 0.0:
        return 0.0
    return math.log(s)


FUNCTIONS = {
    "smooth_rational": smooth_rational,
    "log_power": log_power,
    "sqrt_inverse": sqrt_inverse,
    "beta_singular": beta_singular,
    "log_product": log_product,
    "log_sin": log_sin,
}
