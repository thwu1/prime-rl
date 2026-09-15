import numpy as np


def gram_newton_schulz(X, coefficients, restart_iterations=None, epsilon=1e-7):
    """Gram Newton-Schulz iteration for polar decomposition.

    Instead of iterating on the full rectangular matrix X, this variant
    reformulates the recurrence to operate primarily on the smaller symmetric
    Gram matrix R = XX^T. An accumulated transform Q is maintained such that
    the final result is Q @ X_normalized.

    Periodic restarts (recomputing R = (QX)(QX)^T from scratch) prevent
    numerical instability under finite-precision arithmetic.

    Mathematically equivalent to standard Newton-Schulz: for any set of
    coefficients and restart schedule, the output should match
    standard_newton_schulz(X, coefficients) up to floating-point error.

    Args:
        X: Input matrix of shape (M, N) or (batch, M, N).
        coefficients: List of (a, b, c) tuples, one per iteration.
        restart_iterations: List of iteration indices at which to restart.
        epsilon: Small constant for numerical stability in normalization.

    Returns:
        Approximation to the polar factor, same shape as input.
    """
    if restart_iterations is None:
        restart_iterations = []

    original_shape = X.shape
    if X.ndim == 2:
        X = X[np.newaxis, ...]

    X = X.astype(np.float64)

    should_transpose = X.shape[-2] > X.shape[-1]
    if should_transpose:
        X = np.swapaxes(X, -2, -1)

    norms = np.linalg.norm(X, axis=(-2, -1), keepdims=True)
    X = X / (norms + epsilon)

    batch = X.shape[0]
    n = X.shape[-2]

    R = X @ np.swapaxes(X, -2, -1)  # R = XX^T, shape (batch, n, n)
    I = np.tile(np.eye(n), (batch, 1, 1))
    Q = None

    for i, (a, b, c) in enumerate(coefficients):
        # Compute Z = bR + cR^2  (the non-identity part of the polynomial)
        Z = b * R + c * (R @ R)

        # Restart: apply accumulated Q to X and recompute R from scratch
        if i in restart_iterations and i != 0:
            X = Q @ X
            R = X @ np.swapaxes(X, -2, -1)
            Q = None

        # Update Q: Q tracks the accumulated product of polynomials p_i(R)
        if Q is None:
            Q = Z + a * I                 # Q = p(R) = aI + Z
        else:
            Q = a * Q + Q @ Z            # Q = Q_prev @ (aI + Z)

        # Update R for next iteration (skip on last iter and before restarts)
        if i < len(coefficients) - 1 and (i + 1) not in restart_iterations:
            RZ = b * R + R @ Z           # RZ = R(aI + Z)
            R = a * RZ + Z @ RZ          # R_new = (aI + Z) R (aI + Z)

    # Apply accumulated Q to X
    X = Q @ X

    if should_transpose:
        X = np.swapaxes(X, -2, -1)

    if len(original_shape) == 2:
        X = X[0]

    return X
