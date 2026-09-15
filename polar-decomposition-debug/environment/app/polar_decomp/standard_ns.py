import numpy as np


def standard_newton_schulz(X, coefficients, epsilon=1e-7):
    """Reference implementation of standard Newton-Schulz iteration for polar decomposition.

    Computes an approximation to the polar factor U of X (where X = UP for
    positive semi-definite P) by iterating:
        X <- (a*I + b*XX^T + c*(XX^T)^2) X
    for each (a, b, c) coefficient triple.

    Args:
        X: Input matrix of shape (M, N) or (batch, M, N).
        coefficients: List of (a, b, c) tuples, one per iteration.
        epsilon: Small constant for numerical stability in normalization.

    Returns:
        Approximation to the polar factor, same shape as input.
    """
    original_shape = X.shape
    if X.ndim == 2:
        X = X[np.newaxis, ...]

    X = X.astype(np.float64)

    # Ensure n <= m by transposing if necessary
    should_transpose = X.shape[-2] > X.shape[-1]
    if should_transpose:
        X = np.swapaxes(X, -2, -1)

    # Normalize by Frobenius norm so singular values are in (0, 1]
    norms = np.linalg.norm(X, axis=(-2, -1), keepdims=True)
    X = X / (norms + epsilon)

    for a, b, c in coefficients:
        A = X @ np.swapaxes(X, -2, -1)      # A = XX^T
        B = b * A + c * (A @ A)              # B = bA + cA^2
        X = a * X + B @ X                    # X = (aI + bA + cA^2)X

    if should_transpose:
        X = np.swapaxes(X, -2, -1)

    if len(original_shape) == 2:
        X = X[0]

    return X
