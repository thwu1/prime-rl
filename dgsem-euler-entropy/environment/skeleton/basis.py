"""
Polynomial basis functions for DGSEM on Legendre-Gauss-Lobatto (LGL) nodes.

Provides:
- LGL node and weight computation
- Polynomial derivative matrix on LGL nodes
- Barycentric interpolation weights
"""

import numpy as np


def legendre_poly(n, x):
    """Evaluate Legendre polynomial P_n(x) and its derivative P_n'(x).

    Parameters
    ----------
    n : int
        Degree of the Legendre polynomial.
    x : float
        Evaluation point in [-1, 1].

    Returns
    -------
    L_n : float
        Value of P_n(x).
    dL_n : float
        Value of P_n'(x).
    """
    if n == 0:
        return 1.0, 0.0
    elif n == 1:
        return x, 1.0

    L_prev, L_curr = 1.0, x
    dL_prev, dL_curr = 0.0, 1.0
    for k in range(2, n + 1):
        L_next = ((2 * k - 1) * x * L_curr - (k - 1) * L_prev) / k
        dL_next = dL_prev + (2 * k - 1) * L_curr
        L_prev, L_curr = L_curr, L_next
        dL_prev, dL_curr = dL_curr, dL_next
    return L_curr, dL_curr


def lgl_nodes_weights(N):
    """Compute the N+1 Legendre-Gauss-Lobatto nodes and weights on [-1, 1].

    Parameters
    ----------
    N : int
        Polynomial degree. Returns N+1 nodes.

    Returns
    -------
    nodes : np.ndarray, shape (N+1,)
        LGL quadrature nodes sorted in ascending order.
    weights : np.ndarray, shape (N+1,)
        Corresponding quadrature weights.

    TODO: Implement this function. The LGL nodes are the roots of
    (1 - x^2) * P_N'(x) = 0, i.e., x = -1, x = 1, and the N-1 roots
    of P_N'(x). Use Newton's method starting from the Chebyshev-Gauss-Lobatto
    nodes as initial guesses. Weights are w_j = 2 / (N*(N+1)*[P_N(x_j)]^2).
    """
    raise NotImplementedError("LGL nodes and weights computation not implemented")


def derivative_matrix(nodes):
    """Build the polynomial derivative matrix D on the given nodes.

    Parameters
    ----------
    nodes : np.ndarray, shape (N+1,)
        Interpolation nodes (e.g., LGL nodes).

    Returns
    -------
    D : np.ndarray, shape (N+1, N+1)
        Derivative matrix such that (Df)_i = f'(x_i) for polynomial f
        defined by its nodal values.

    TODO: Implement using the explicit formula:
        D_{ij} = (w_j^bary / w_i^bary) / (x_i - x_j)  for i != j
        D_{ii} = -sum_{j != i} D_{ij}
    where w_j^bary are the barycentric weights.
    """
    raise NotImplementedError("Derivative matrix construction not implemented")


def barycentric_weights(nodes):
    """Compute barycentric interpolation weights for given nodes.

    Parameters
    ----------
    nodes : np.ndarray, shape (N+1,)

    Returns
    -------
    w : np.ndarray, shape (N+1,)
        Barycentric weights.

    TODO: Implement. w_j = 1 / prod_{k != j}(x_j - x_k).
    """
    raise NotImplementedError("Barycentric weights computation not implemented")
