"""Eigendecomposition of the perturbation effect covariance."""
import numpy as np
from db import get_models, get_perturbation_names


def run(prior_results, config, taxonomy):
    """Eigendecomposition of E^T @ E where E is the effect matrix.

    E has shape (num_models x num_non_default_perturbations), with rows
    ordered by sorted model name. Reports top-k eigenvalues in descending
    order and their corresponding unit-norm eigenvectors.
    """
    effect_data = prior_results["effects"]
    models = sorted(effect_data.keys())
    p_names = get_perturbation_names()
    non_default = sorted(
        [n for pid, n in p_names.items() if pid != 0],
        key=lambda n: [pid for pid, nm in p_names.items() if nm == n][0]
    )

    k = config.get("decomposition_rank", 2)

    # Build effect matrix E: (num_models x num_perturbations)
    E = np.zeros((len(models), len(non_default)))
    for m_idx, model in enumerate(models):
        for p_idx, p_name in enumerate(non_default):
            E[m_idx, p_idx] = effect_data[model][p_name]

    # Compute covariance-like matrix and decompose
    M = E @ E.T

    eigenvalues, eigenvectors = np.linalg.eigh(M)

    # Sort descending
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    top_eigenvalues = eigenvalues[:k].tolist()
    top_eigenvectors = [eigenvectors[:, i].tolist() for i in range(k)]

    return {
        "eigenvalues": top_eigenvalues,
        "eigenvectors": top_eigenvectors
    }
