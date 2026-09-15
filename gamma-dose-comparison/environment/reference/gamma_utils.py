
"""Utility helpers extracted from a dose-comparison pipeline.

These are support routines only -- the main comparison loop that ties
them together is not included here.
"""

import numpy as np


def create_eval_interpolator(axes, dose_grid):
    """Build a regular-grid interpolator over an evaluation dose volume.

    Out-of-bounds queries return infinity so that they never appear as
    the best match during a search.
    """
    from scipy.interpolate import RegularGridInterpolator

    return RegularGridInterpolator(
        axes, dose_grid, bounds_error=False, fill_value=np.inf
    )


def dose_normalisation_value(dose_ref, user_norm):
    """Resolve the global normalisation value."""
    if user_norm is not None:
        return float(user_norm)
    return float(np.max(dose_ref))


def apply_cutoff_mask(result, dose_ref, cutoff_percent, global_norm):
    """Set gamma to NaN where reference dose is below the cutoff."""
    threshold = cutoff_percent / 100.0 * global_norm
    result[dose_ref < threshold] = np.nan
    return result


def search_step_size(distance_threshold, interp_fraction):
    """Distance increment for the expanding search."""
    return distance_threshold / interp_fraction


def metric_at_shell(interp_doses, ref_dose_val, search_dist,
                    percent_tol, dist_tol, norm_value):
    """Combined dose-distance metric across a set of sample points.

    *interp_doses* has shape (n_shell_points, n_active_refs).
    Returns the minimum metric value over the shell dimension for each
    active reference point.
    """
    dose_deltas = np.abs(interp_doses - ref_dose_val) / norm_value
    best_delta = np.min(dose_deltas, axis=0)
    return np.sqrt(
        (best_delta / (percent_tol / 100)) ** 2
        + (search_dist / dist_tol) ** 2
    )


def still_improving(current_best, distance, dist_tol):
    """Check whether further searching can improve each point's metric.

    Returns a boolean mask -- True means keep searching.
    """
    return current_best > (distance / dist_tol)
