"""Compute the spectral radius (largest eigenvalue) of the 400 x 400
symmetric matrix B defined by:
    B_{ij} = 1 / (1 + |i - j|)   for |i - j| <= 20
    B_{ij} = 0                    otherwise
    (0-based indexing, i,j = 0, ..., 399)

Uses power iteration with Rayleigh quotient estimation.
"""
import numpy as np


def compute():
    N = 400
    bandwidth = 20

    # Build the symmetric banded matrix
    B = np.zeros((N, N))
    for i in range(N):
        for d in range(-bandwidth, bandwidth + 1):
            j = i + d
            if 0 <= j < N:
                B[i, j] = 1.0 / (1.0 + abs(d))

    # Power iteration with Rayleigh quotient
    rng = np.random.RandomState(42)
    x = rng.randn(N)
    x /= np.linalg.norm(x)

    n_iter = 50
    lam = 0.0
    for _ in range(n_iter):
        y = B @ x
        lam = float(np.dot(x, y))
        x = y / np.linalg.norm(y)

    return lam


if __name__ == "__main__":
    result = compute()
    print(f"Spectral radius estimate (50 iterations): {result:.15e}")
    print(f"RESULT: {result:.15e}")
