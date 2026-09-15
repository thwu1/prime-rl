"""

Polynomial basis functions for DGSEM on Legendre-Gauss-Lobatto (LGL) nodes.
"""

import numpy as np


def legendre_poly(n, x):
    """Evaluate Legendre polynomial P_n(x) and its derivative P_n'(x)."""
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
    """Compute N+1 Legendre-Gauss-Lobatto nodes and weights on [-1, 1].

    LGL nodes are roots of (1-x^2)*P_N'(x) = 0: the endpoints -1, 1 plus
    the N-1 interior roots of P_N'(x). Uses Newton's method starting from
    Chebyshev-Gauss-Lobatto initial guesses. Weights: w_j = 2/(N(N+1)[P_N(x_j)]^2).
    """
    if N == 0:
        return np.array([0.0]), np.array([2.0])
    if N == 1:
        return np.array([-1.0, 1.0]), np.array([1.0, 1.0])

    nodes = np.zeros(N + 1)
    nodes[0] = -1.0
    nodes[N] = 1.0

    # Initial guess: Chebyshev-Gauss-Lobatto nodes
    for j in range(1, N):
        nodes[j] = -np.cos(np.pi * j / N)

    # Newton iteration to find roots of P_N'(x)
    for j in range(1, N):
        x = nodes[j]
        for _ in range(100):
            L, dL = legendre_poly(N, x)
            if abs(1 - x * x) < 1e-16:
                break
            # P_N''(x) = (2*x*P_N'(x) - N*(N+1)*P_N(x)) / (1 - x^2)
            d2L = (2.0 * x * dL - N * (N + 1) * L) / (1.0 - x * x)
            dx = -dL / d2L
            x = x + dx
            if abs(dx) < 1e-15:
                break
        nodes[j] = x

    nodes.sort()

    # Weights
    weights = np.zeros(N + 1)
    for j in range(N + 1):
        L, _ = legendre_poly(N, nodes[j])
        weights[j] = 2.0 / (N * (N + 1) * L * L)

    return nodes, weights


def barycentric_weights(nodes):
    """Compute barycentric interpolation weights: w_j = 1/prod_{k!=j}(x_j - x_k)."""
    n = len(nodes)
    w = np.ones(n)
    for j in range(n):
        for k in range(n):
            if k != j:
                w[j] /= (nodes[j] - nodes[k])
    return w


def derivative_matrix(nodes):
    """Build polynomial derivative matrix D on given nodes using barycentric formula.

    D_{ij} = (w_j / w_i) / (x_i - x_j)  for i != j
    D_{ii} = -sum_{j != i} D_{ij}
    """
    n = len(nodes)
    w = barycentric_weights(nodes)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i != j:
                D[i, j] = (w[j] / w[i]) / (nodes[i] - nodes[j])
        D[i, i] = -np.sum(D[i, :])
    return D
