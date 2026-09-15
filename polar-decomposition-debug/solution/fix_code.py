#!/usr/bin/env python3

"""Fix bugs in the polar decomposition library.

Three categories of bugs plus one missing implementation:

Bug 1 (gram_ns.py): The restart block executes AFTER Z computation. It must
execute BEFORE so that Z is computed from the freshly restarted Gram matrix R,
not the stale pre-restart R. Compare with the standard NS: each iteration
recomputes A = XX^T from the current X. The Gram variant must similarly use
the current R after a restart.

Bug 2 (gram_ns.py): The RZ computation uses coefficient 'b' instead of 'a'.
The recurrence for updating R is R_new = p(R) R p(R) where p(R) = aI + Z.
Expanding: R_new = (aI + Z) R (aI + Z). The intermediate term RZ should be
R(aI + Z) = aR + RZ, using coefficient 'a' (identity coefficient), not 'b'
(the linear coefficient of R in Z).

Bug 3 (stability.py): At restart, r is recomputed from x_eigenvalues BEFORE
x_eigenvalues are updated by the accumulated q. The correct order is: first
absorb the accumulated q into x_eigenvalues (x_eigenvalues *= q), then
recompute r from the updated eigenvalues (r = x_eigenvalues**2 + perturbation).

Bug 4 (restart_finder.py): find_optimal_restarts raises NotImplementedError.
Must be implemented via exhaustive search over all combinations of restart
positions, evaluating each via simulate_eigenvalue_evolution + stability_metric.
"""

import os


def write_corrected_gram_ns():
    """Write corrected gram_ns.py with bugs 1 and 2 fixed."""
    content = '''\
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
        # Restart: apply accumulated Q to X and recompute R from scratch
        if i in restart_iterations and i != 0:
            X = Q @ X
            R = X @ np.swapaxes(X, -2, -1)
            Q = None

        # Compute Z = bR + cR^2  (the non-identity part of the polynomial)
        Z = b * R + c * (R @ R)

        # Update Q: Q tracks the accumulated product of polynomials p_i(R)
        if Q is None:
            Q = Z + a * I                 # Q = p(R) = aI + Z
        else:
            Q = a * Q + Q @ Z            # Q = Q_prev @ (aI + Z)

        # Update R for next iteration (skip on last iter and before restarts)
        if i < len(coefficients) - 1 and (i + 1) not in restart_iterations:
            RZ = a * R + R @ Z           # RZ = R(aI + Z)
            R = a * RZ + Z @ RZ          # R_new = (aI + Z) R (aI + Z)

    # Apply accumulated Q to X
    X = Q @ X

    if should_transpose:
        X = np.swapaxes(X, -2, -1)

    if len(original_shape) == 2:
        X = X[0]

    return X
'''
    with open('/app/polar_decomp/gram_ns.py', 'w') as f:
        f.write(content)
    print("Fixed gram_ns.py (restart ordering + RZ coefficient)")


def write_corrected_stability():
    """Write corrected stability.py with bug 3 fixed."""
    content = '''\
import numpy as np


def simulate_eigenvalue_evolution(x_eigenvalues, coefficients, perturbation, restart_indices=None):
    """Simulate eigenvalue evolution through Gram Newton-Schulz iterations.

    Models how the eigenvalues of the accumulated polynomial Q and the
    intermediate Gram matrix R evolve, including the effect of perturbations
    (simulating spurious negative eigenvalues from floating-point error) and
    restarts.

    The simulation tracks scalar eigenvalues rather than full matrices,
    enabling fast analysis of convergence and stability properties.

    Args:
        x_eigenvalues: Array of singular values of X (after normalization).
        coefficients: List of (a, b, c) tuples, one per iteration.
        perturbation: Scalar added to eigenvalues of R at initialization and
            restarts. Should be negative to simulate floating-point error
            introducing spurious negative eigenvalues in the Gram matrix.
        restart_indices: List of iteration indices at which to restart.

    Returns:
        Dictionary mapping 'Q_{i}' to the accumulated Q eigenvalue array
        at each iteration i.
    """
    if restart_indices is None:
        restart_indices = []

    x_eigenvalues = x_eigenvalues.copy().astype(np.float64)
    q_values = {}

    for iter_idx, (a, b, c) in enumerate(coefficients):
        if (iter_idx == 0) or (iter_idx in restart_indices):
            # At initialization or restart: update eigenvalues then recompute r
            if iter_idx != 0:
                x_eigenvalues *= q
            r = x_eigenvalues**2 + perturbation
            q = np.ones(len(x_eigenvalues))

        # Polynomial evaluation: z = p(r) = a + br + cr^2 (Horner form)
        z = a + r * (b + r * c)
        q *= z
        r *= z**2
        q_values[f'Q_{iter_idx}'] = q.copy()

    return q_values


def stability_metric(q_values):
    """Compute the worst-case condition number of Q across all iterations.

    A large condition number indicates that Q amplifies differences between
    eigenvalues, which can cause numerical instability in the Gram formulation.

    Args:
        q_values: Dictionary from simulate_eigenvalue_evolution.

    Returns:
        Maximum ratio of max(|Q|)/min(|Q|) across all iterations.
    """
    def condition(vals):
        abs_vals = np.abs(vals)
        return abs_vals.max() / abs_vals.min()
    return max(condition(vals) for vals in q_values.values())
'''
    with open('/app/polar_decomp/stability.py', 'w') as f:
        f.write(content)
    print("Fixed stability.py (eigenvalue update ordering at restart)")


def write_restart_finder():
    """Write the missing find_optimal_restarts implementation."""
    content = '''\
import numpy as np
from itertools import combinations
from .stability import simulate_eigenvalue_evolution, stability_metric


def find_optimal_restarts(x_eigenvalues, coefficients, perturbation, num_restarts=1):
    """Find restart positions that minimize the stability metric.

    Searches all possible combinations of restart positions (iterations 1
    through len(coefficients)-1) and returns the combination that produces
    the lowest stability metric (worst-case condition number of Q).

    Args:
        x_eigenvalues: Array of singular values of X (after normalization).
        coefficients: List of (a, b, c) tuples, one per iteration.
        perturbation: Scalar perturbation for Gram matrix eigenvalues.
        num_restarts: Number of restart positions to find.

    Returns:
        Tuple of (best_restart_positions, best_metric_value) where
        best_restart_positions is a sorted list of iteration indices.
    """
    possible_positions = list(range(1, len(coefficients)))

    if num_restarts > len(possible_positions):
        raise ValueError(
            f"Cannot have {num_restarts} restarts with only "
            f"{len(coefficients)} iterations"
        )

    best_positions = None
    best_metric = float('inf')

    for combo in combinations(possible_positions, num_restarts):
        restart_indices = list(combo)
        q_values = simulate_eigenvalue_evolution(
            x_eigenvalues, coefficients, perturbation,
            restart_indices=restart_indices
        )
        metric = stability_metric(q_values)

        if metric < best_metric:
            best_metric = metric
            best_positions = sorted(restart_indices)

    return best_positions, best_metric
'''
    with open('/app/polar_decomp/restart_finder.py', 'w') as f:
        f.write(content)
    print("Implemented restart_finder.py (exhaustive search)")


def verify_fixes():
    """Quick smoke test that the fixed modules import and basic math works."""
    import sys
    sys.path.insert(0, '/app')

    # Force reimport of fixed modules
    for mod_name in list(sys.modules.keys()):
        if 'polar_decomp' in mod_name:
            del sys.modules[mod_name]

    from polar_decomp.standard_ns import standard_newton_schulz
    from polar_decomp.gram_ns import gram_newton_schulz
    from polar_decomp.coefficients import CLASSICAL_COEFFICIENTS
    from polar_decomp.stability import simulate_eigenvalue_evolution
    from polar_decomp.restart_finder import find_optimal_restarts

    import numpy as np
    rng = np.random.RandomState(42)
    X = rng.randn(8, 16)

    result_std = standard_newton_schulz(X, CLASSICAL_COEFFICIENTS)
    result_gram = gram_newton_schulz(X, CLASSICAL_COEFFICIENTS)

    max_diff = np.max(np.abs(result_std - result_gram))
    print(f"Verification: max diff between standard and gram NS = {max_diff:.2e}")
    assert max_diff < 1e-6, f"Fix verification failed: max_diff={max_diff}"
    print("All fixes verified successfully.")


if __name__ == '__main__':
    write_corrected_gram_ns()
    write_corrected_stability()
    write_restart_finder()
    verify_fixes()
