"""Compute the integral:
    I = integral from -inf to inf of exp(-x^2) * (x^4 + 2*x^2 + 3) dx
using Gauss-Hermite quadrature with 100 nodes.
"""
import numpy as np


def compute():
    n = 100
    nodes, weights = np.polynomial.hermite.hermgauss(n)
    # Evaluate the full integrand at quadrature nodes
    integrand_vals = np.exp(-nodes**2) * (nodes**4 + 2.0 * nodes**2 + 3.0)
    return float(np.sum(weights * integrand_vals))


if __name__ == "__main__":
    result = compute()
    print(f"Hermite quadrature estimate: {result:.15e}")
    print(f"RESULT: {result:.15e}")
