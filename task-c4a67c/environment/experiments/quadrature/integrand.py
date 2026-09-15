"""Experiment: Quadrature

Evaluate the definite integral of f(x) over the domain specified in config.json.
Parameters alpha and beta control the oscillation and are session-specific
(see /app/calibration.json).
"""
from math import cos, cosh


# Session-specific parameters from /app/calibration.json
ALPHA = 1.7320508075688772
BETA = 0.6180339887498949


def f(x):
    """The integrand to be numerically integrated."""
    return cos(ALPHA * x ** 2 + BETA * x) / cosh(x)
