
"""
Newton-Schulz polar decomposition solver — corrected version.

Fixes applied:
1. gram_newton_schulz: transpose check corrected from n<m to n>m
2. gram_newton_schulz: R update corrected to two-step p(R) R p(R) form
3. gram_newton_schulz: restart now applies Q to X before reforming R
4. stability_metric: denominator changed from mean to min
5. find_optimal_restarts: fully implemented via exhaustive search
6. analyze_convergence: fixed orthogonality check for transposed matrices
"""

import numpy as np
import json
from itertools import combinations


def load_coefficients(path="/app/coefficients.json"):
    """Load Newton-Schulz polynomial coefficients from JSON file."""
    with open(path) as f:
        data = json.load(f)
    return data


def standard_newton_schulz(X, coefficients, epsilon=1e-7):
    """Standard Newton-Schulz iteration for polar decomposition.

    Computes the polar factor U such that X ≈ UH where U has orthonormal
    rows (for n <= m) or orthonormal columns (for n > m).

    For each iteration with coefficients (a, b, c):
        A = X @ X^T
        B = b*A + c*A^2
        X = a*X + B @ X

    Args:
        X: Input matrix of shape (M, N) or batch (B, M, N)
        coefficients: List of [a, b, c] coefficient triples
        epsilon: Normalization epsilon

    Returns:
        Polar factor with same shape as X
    """
    original_shape = X.shape
    if X.ndim == 2:
        X = X[np.newaxis, ...].copy()
    else:
        X = X.copy()

    should_transpose = X.shape[-2] > X.shape[-1]
    if should_transpose:
        X = np.swapaxes(X, -2, -1).copy()

    norms = np.linalg.norm(X, axis=(-2, -1), keepdims=True)
    X = X / (norms + epsilon)

    for a, b, c in coefficients:
        A = X @ np.swapaxes(X, -2, -1)
        B = b * A + c * (A @ A)
        X = a * X + B @ X

    if should_transpose:
        X = np.swapaxes(X, -2, -1)

    return X.reshape(original_shape)


def gram_newton_schulz(X, coefficients, epsilon=1e-7, reset_iterations=None):
    """Gram Newton-Schulz iteration for polar decomposition.

    Operates on the symmetric Gram matrix R = XX^T instead of X directly,
    tracking an accumulator Q. Final result is Q @ X.

    Args:
        X: Input matrix of shape (M, N) or batch (B, M, N)
        coefficients: List of [a, b, c] coefficient triples
        epsilon: Normalization epsilon
        reset_iterations: List of iteration indices at which to restart

    Returns:
        Polar factor with same shape as X
    """
    if reset_iterations is None:
        reset_iterations = []

    original_shape = X.shape
    if X.ndim == 2:
        X = X[np.newaxis, ...].copy()
    else:
        X = X.copy()

    # FIX 1: Transpose when n > m (tall matrix), not n < m
    should_transpose = X.shape[-2] > X.shape[-1]
    if should_transpose:
        X = np.swapaxes(X, -2, -1).copy()

    norms = np.linalg.norm(X, axis=(-2, -1), keepdims=True)
    X = X / (norms + epsilon)

    batch_size = X.shape[0]
    n = X.shape[-2]

    R = X @ np.swapaxes(X, -2, -1)
    I = np.tile(np.eye(n), (batch_size, 1, 1))
    Q = None

    for i, (a, b, c) in enumerate(coefficients):
        if i in reset_iterations and i != 0:
            # FIX 3: Apply Q to X before reforming R
            X = Q @ X
            R = X @ np.swapaxes(X, -2, -1)
            Q = None

        Z = b * R + c * (R @ R)

        if i == 0 or i in reset_iterations:
            Q = Z + a * I
        else:
            Q = Q @ Z + a * Q

        if i < len(coefficients) - 1 and (i + 1) not in reset_iterations:
            # FIX 2: Correct R update: R_new = p(R) @ R @ p(R)
            # where p(R) = Z + aI, computed as two-step:
            # RZ = R@Z + a*R = R(Z+aI)
            # R = Z@RZ + a*RZ = (Z+aI)@RZ = (Z+aI) R (Z+aI)
            RZ = R @ Z + a * R
            R = Z @ RZ + a * RZ

    X = Q @ X

    if should_transpose:
        X = np.swapaxes(X, -2, -1)

    return X.reshape(original_shape)


def simulate_eigenvalue_evolution(eigenvalues, coefficients, perturbation,
                                   reset_indices=None):
    """Simulate how eigenvalues of intermediate matrices evolve through iterations.

    Models the scalar eigenvalue dynamics of the Newton-Schulz iteration:
    - r represents eigenvalues of the Gram matrix R
    - q accumulates the product of polynomial evaluations
    - perturbation models floating-point errors in forming XX^T

    Args:
        eigenvalues: 1D array of initial singular values (after normalization)
        coefficients: List of [a, b, c] coefficient triples
        perturbation: Negative perturbation to Gram eigenvalues (models fp16 error)
        reset_indices: Iteration indices at which to restart

    Returns:
        Dict mapping 'Q_i' to arrays of accumulated Q eigenvalues at iteration i
    """
    if reset_indices is None:
        reset_indices = []

    eigenvalues = eigenvalues.copy().astype(np.float64)
    q_values = {}

    for iter_idx, (a, b, c) in enumerate(coefficients):
        if iter_idx == 0 or iter_idx in reset_indices:
            if iter_idx != 0:
                eigenvalues *= q
            r = eigenvalues**2 + perturbation
            q = np.ones(len(eigenvalues))

        z = a + r * (b + r * c)
        q *= z
        r *= z**2
        q_values[f'Q_{iter_idx}'] = q.copy()

    return q_values


def stability_metric(q_values):
    """Compute stability metric: worst-case condition number of Q across iterations.

    For each iteration, computes the ratio of the largest to smallest absolute
    Q eigenvalue. Returns the maximum such ratio across all iterations.

    Args:
        q_values: Dict from simulate_eigenvalue_evolution

    Returns:
        Maximum condition number of Q across all iterations
    """
    def condition(vals):
        abs_vals = np.abs(vals)
        # FIX 4: Use min, not mean
        return abs_vals.max() / abs_vals.min()
    return max(condition(vals) for vals in q_values.values())


def find_optimal_restarts(eigenvalues, coefficients, perturbation, num_restarts=1):
    """Find restart positions that minimize the stability metric.

    Exhaustively searches over all combinations of restart positions
    to find the set that minimizes the stability metric.

    Args:
        eigenvalues: 1D array of initial singular values
        coefficients: List of [a, b, c] coefficient triples
        perturbation: Negative perturbation value
        num_restarts: Number of restart positions to find

    Returns:
        Tuple of (best_restart_positions: list, best_metric: float)
    """
    # FIX 5: Full implementation
    possible_positions = list(range(1, len(coefficients)))

    if num_restarts == 0:
        q_results = simulate_eigenvalue_evolution(
            eigenvalues, coefficients, perturbation, reset_indices=[]
        )
        return [], stability_metric(q_results)

    best_restarts = None
    best_metric = float('inf')

    for restart_combo in combinations(possible_positions, num_restarts):
        test_restarts = list(restart_combo)
        q_results = simulate_eigenvalue_evolution(
            eigenvalues, coefficients, perturbation, reset_indices=test_restarts
        )
        metric = stability_metric(q_results)

        if metric < best_metric:
            best_metric = metric
            best_restarts = test_restarts

    return best_restarts, best_metric


def compute_polar_error(result):
    """Compute orthogonality error of a polar factor.

    For n <= m: computes ||U U^T - I||_F
    For n > m: computes ||U^T U - I||_F

    Args:
        result: Computed polar factor

    Returns:
        Frobenius norm of the orthogonality residual
    """
    if result.ndim == 2:
        result = result[np.newaxis, ...]

    if result.shape[-2] <= result.shape[-1]:
        product = result @ np.swapaxes(result, -2, -1)
        n = result.shape[-2]
    else:
        product = np.swapaxes(result, -2, -1) @ result
        n = result.shape[-1]

    I = np.eye(n)
    errors = np.linalg.norm(product - I, axis=(-2, -1))
    return float(errors.squeeze()) if errors.size == 1 else errors.squeeze()


def analyze_convergence(X, coefficients, epsilon=1e-7):
    """Compute per-iteration orthogonality error for standard Newton-Schulz.

    Args:
        X: Input matrix
        coefficients: List of [a, b, c] coefficient triples
        epsilon: Normalization epsilon

    Returns:
        List of orthogonality errors, one per iteration
    """
    original_shape = X.shape
    if X.ndim == 2:
        X = X[np.newaxis, ...].copy()
    else:
        X = X.copy()

    should_transpose = X.shape[-2] > X.shape[-1]
    if should_transpose:
        X = np.swapaxes(X, -2, -1).copy()

    norms = np.linalg.norm(X, axis=(-2, -1), keepdims=True)
    X = X / (norms + epsilon)

    errors = []
    for a, b, c in coefficients:
        A = X @ np.swapaxes(X, -2, -1)
        B = b * A + c * (A @ A)
        X = a * X + B @ X

        # FIX 6: After possible transpose, X is always n×m with n ≤ m.
        # Check orthogonality via X @ X^T = I_n (not X^T @ X)
        product = X @ np.swapaxes(X, -2, -1)
        n = X.shape[-2]

        err = float(np.linalg.norm(product - np.eye(n), axis=(-2, -1)).mean())
        errors.append(err)

    return errors
