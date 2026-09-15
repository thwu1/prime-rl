"""Post-processing module: score rotation, sign convention, and reordering."""
import numpy as np


def compute_rotated_scores(scores, singular_values, R_combined, rot_exp_var,
                           n_rotate, n_time):
    """
    Compute rotated scores from unrotated scores and rotation matrix.

    Parameters
    ----------
    scores : ndarray, shape (n_time, n_modes)
    singular_values : ndarray, shape (n_modes,)
    R_combined : ndarray, shape (n_rotate, n_rotate)
    rot_exp_var : ndarray, shape (n_rotate,)
    n_rotate : int
    n_time : int

    Returns
    -------
    rot_scores : ndarray, shape (n_time, n_rotate)
    """
    # Normalize to get U (left singular vectors)
    U_truncated = scores[:, :n_rotate] / singular_values[None, :n_rotate]

    # Rotate scores
    rot_scores_normalized = U_truncated @ R_combined.T

    # Scale by pseudo-norms
    pseudo_norms = np.sqrt(rot_exp_var * (n_time - 1))
    rot_scores = rot_scores_normalized * pseudo_norms[None, :]
    return rot_scores


def apply_sign_convention(components, n_rotate):
    """
    Apply deterministic sign convention: the element with the
    largest absolute value in each component is positive.

    Returns
    -------
    components : ndarray (modified in-place)
    sign_mult : ndarray, shape (n_rotate,)
    """
    sign_mult = np.ones(n_rotate)
    for i in range(n_rotate):
        max_idx = np.argmax(np.abs(components[i]))
        if components[i, max_idx] < 0:
            sign_mult[i] = -1.0
            components[i] *= -1
    return components, sign_mult


def reorder_by_variance(rot_loadings, rot_exp_var, R_combined, phi):
    """
    Sort rotated modes by descending explained variance.

    Returns
    -------
    rot_loadings, rot_exp_var, R_combined, phi, order
    """
    order = np.argsort(rot_exp_var)[::-1]
    rot_loadings = rot_loadings[:, order]
    rot_exp_var = rot_exp_var[order]
    R_combined = R_combined[:, order]
    phi = phi[np.ix_(order, order)]
    return rot_loadings, rot_exp_var, R_combined, phi, order
