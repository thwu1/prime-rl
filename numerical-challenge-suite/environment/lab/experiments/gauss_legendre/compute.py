"""Compute the definite integral:
    I = integral from -1 to 1 of exp(x) / (1 + 25*x^2) dx
using Gauss-Legendre quadrature with 200 nodes.
"""
import numpy as np


def compute():
    n = 200
    nodes, weights = np.polynomial.legendre.leggauss(n)
    vals = np.exp(nodes) / (1.0 + 25.0 * nodes**2)
    return float(np.sum(weights * vals))


if __name__ == "__main__":
    result = compute()
    print(f"Gauss-Legendre integral estimate: {result:.15e}")
    print(f"RESULT: {result:.15e}")
