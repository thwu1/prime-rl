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
            # At initialization or restart: recompute R eigenvalues from X eigenvalues
            r = x_eigenvalues**2 + perturbation
            if iter_idx != 0:
                x_eigenvalues *= q
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
