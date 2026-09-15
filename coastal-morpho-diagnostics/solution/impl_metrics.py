"""
Morphological skill metrics: BSS, RMSE, volume change, mass balance.
"""

import numpy as np


def brier_skill_score(predicted, observed, baseline):
    """Compute Brier Skill Score.

    BSS = 1 - MSE(predicted, observed) / MSE(baseline, observed)

    Returns
    -------
    float
        BSS value. 1.0 = perfect, 0.0 = no better than baseline, <0 = worse.
    """
    predicted = np.asarray(predicted, dtype=float)
    observed = np.asarray(observed, dtype=float)
    baseline = np.asarray(baseline, dtype=float)

    mse_model = float(np.mean((predicted - observed) ** 2))
    mse_baseline = float(np.mean((baseline - observed) ** 2))

    if mse_baseline == 0.0:
        return 1.0 if mse_model == 0.0 else float("-inf")

    return 1.0 - mse_model / mse_baseline


def rmse(predicted, observed):
    """Root-mean-square error."""
    predicted = np.asarray(predicted, dtype=float)
    observed = np.asarray(observed, dtype=float)
    return float(np.sqrt(np.mean((predicted - observed) ** 2)))


def volume_change(z_initial, z_final, dx, dy=1.0):
    """Net volume change between two elevation fields.

    For a 1-D profile with dy=1 the result is in m^3/m (volume per unit
    alongshore length).  For a 2-D field it is m^3.
    """
    z_initial = np.asarray(z_initial, dtype=float)
    z_final = np.asarray(z_final, dtype=float)
    return float(np.sum(z_final - z_initial) * dx * dy)


def mass_balance_check(z_initial, z_final, dx, dy=1.0, threshold=5.0):
    """Check whether the net volume change is within an acceptable threshold.

    Returns
    -------
    tuple[bool, float]
        (passed, error) where *passed* is True if |error| <= threshold.
    """
    error = volume_change(z_initial, z_final, dx, dy)
    passed = abs(error) <= threshold
    return (passed, error)
