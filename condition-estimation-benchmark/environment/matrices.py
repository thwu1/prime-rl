"""Matrix generators for condition estimation benchmark."""
import numpy as np
from math import comb


def moler(n):
    """Moler matrix: M = U^T U where U is unit upper triangular."""
    U = np.eye(n) + np.triu(np.ones((n, n)), 1)
    return U.T @ U


def pascal_matrix(n):
    """Symmetric Pascal matrix: P[i,j] = C(i+j, i)."""
    P = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            P[i, j] = comb(i + j, i)
    return P


def frank(n):
    """Frank matrix (upper Hessenberg)."""
    F = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if j >= i:
                F[i, j] = n - max(i, j)
    return F


def cauchy_matrix(n):
    """Cauchy matrix with nodes."""
    C = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            C[i, j] = 1.0 / (i + j + 2)
    return C


def parter(n):
    """Parter (Toeplitz-like) matrix."""
    P = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            P[i, j] = 1.0 / (i - j + 0.5)
    return P
