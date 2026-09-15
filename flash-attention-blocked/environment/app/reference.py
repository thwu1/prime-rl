
"""Naive O(N^2) memory attention implementations -- correctness reference."""

import numpy as np


def reference_forward(Q, K, V):
    """Standard scaled dot-product attention forward pass.

    Returns
    -------
    O : ndarray, shape (N, d)
    L : ndarray, shape (N,) -- per-row logsumexp of the scaled score matrix
    """
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)
    S = Q @ K.T * scale
    m = np.max(S, axis=1, keepdims=True)
    P = np.exp(S - m)
    l = np.sum(P, axis=1, keepdims=True)
    P = P / l
    O = P @ V
    L = m.ravel() + np.log(l.ravel())
    return O, L


def reference_backward(Q, K, V, O, dO, L):
    """Standard attention backward pass."""
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)
    S = Q @ K.T * scale
    P = np.exp(S - L[:, None])
    D = np.sum(dO * O, axis=1)
    dP = dO @ V.T
    dS = P * (dP - D[:, None])
    dQ = dS @ K * scale
    dK = dS.T @ Q * scale
    dV = P.T @ dO
    return dQ, dK, dV


def reference_causal_forward(Q, K, V):
    """Causal attention forward pass. Position i attends only to j <= i.

    Returns
    -------
    O : ndarray, shape (N, d)
    L : ndarray, shape (N,) -- per-row logsumexp of masked scaled scores
    """
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)
    S = Q @ K.T * scale
    mask = np.triu(np.ones((N, N), dtype=bool), k=1)
    S = np.where(mask, -np.inf, S)
    m = np.max(S, axis=1, keepdims=True)
    P = np.exp(S - m)
    l = np.sum(P, axis=1, keepdims=True)
    P = P / l
    O = P @ V
    L = m.ravel() + np.log(l.ravel())
    return O, L


def reference_causal_backward(Q, K, V, O, dO, L):
    """Causal attention backward pass."""
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)
    S = Q @ K.T * scale
    mask = np.triu(np.ones((N, N), dtype=bool), k=1)
    S = np.where(mask, -np.inf, S)
    P = np.exp(S - L[:, None])
    D = np.sum(dO * O, axis=1)
    dP = dO @ V.T
    dS = P * (dP - D[:, None])
    dQ = dS @ K * scale
    dK = dS.T @ Q * scale
    dV = P.T @ dO
    return dQ, dK, dV
