
"""Mechanism (structural equation) factories for SCMs."""

import numpy as np


def linear_mechanism(weights, noise_mode="additive"):
    """Create a linear structural equation.

    Y = sum(w_i * PA_i) + U  (additive noise)
    Y = sum(w_i * PA_i) * (1 + U)  (multiplicative noise)

    Args:
        weights: dict mapping parent name -> coefficient.
        noise_mode: "additive" or "multiplicative".

    Returns:
        Callable(parent_values: dict, noise: ndarray) -> ndarray.
    """
    def mechanism(parent_values, noise):
        result = np.zeros_like(noise)
        for parent_name, weight in weights.items():
            result = result + weight * parent_values[parent_name]
        if noise_mode == "additive":
            result = result + noise
        elif noise_mode == "multiplicative":
            result = result * (1.0 + noise)
        return result
    return mechanism


def polynomial_mechanism(terms, noise_mode="additive"):
    """Create a polynomial structural equation.

    Y = sum_j(coeff_j * prod_i(PA_i ^ power_ij)) + U

    Args:
        terms: list of (coefficient, {parent_name: power}) tuples.
            Example: [(2.0, {"X": 1, "Z": 1}), (1.0, {"X": 2})]
            represents 2*X*Z + X^2.
        noise_mode: "additive" or "multiplicative".

    Returns:
        Callable(parent_values: dict, noise: ndarray) -> ndarray.
    """
    def mechanism(parent_values, noise):
        result = np.zeros_like(noise)
        for coeff, powers in terms:
            term = np.full_like(noise, coeff)
            for parent_name, power in powers.items():
                term = term * (parent_values[parent_name] ** power)
            result = result + term
        if noise_mode == "additive":
            result = result + noise
        elif noise_mode == "multiplicative":
            result = result * (1.0 + noise)
        return result
    return mechanism


def identity_mechanism():
    """Create an identity mechanism: Y = U (root node, no parents).

    Returns:
        Callable(parent_values: dict, noise: ndarray) -> ndarray.
    """
    def mechanism(parent_values, noise):
        return noise.copy()
    return mechanism
