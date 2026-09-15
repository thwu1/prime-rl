"""
Diagnostic verification checks for coastal morphological simulations.
"""

import numpy as np


def slope_check(z, dx, locations, expected_slopes, tolerance):
    """Verify finite-difference slopes at specified index positions.

    Parameters
    ----------
    z : array_like
        1-D elevation array.
    dx : float
        Grid spacing in metres.
    locations : list[int]
        Index positions into the slopes array (supports negative indices).
    expected_slopes : list[float]
        Expected slope value at each location.
    tolerance : float
        Relative tolerance fraction (e.g. 0.1 = 10 %).

    Returns
    -------
    dict
        ``{"passed": bool, "details": [{"location", "expected", "actual", "passed"}, ...]}``
    """
    z = np.asarray(z, dtype=float)
    slopes = np.diff(z) / dx
    n = len(slopes)

    details = []
    all_passed = True

    for loc, expected in zip(locations, expected_slopes):
        idx = loc if loc >= 0 else n + loc
        if 0 <= idx < n:
            actual = float(slopes[idx])
            if expected != 0:
                ok = abs(actual - expected) <= abs(expected) * tolerance
            else:
                ok = abs(actual) <= tolerance
            details.append({
                "location": loc,
                "expected": expected,
                "actual": actual,
                "passed": bool(ok),
            })
            if not ok:
                all_passed = False
        else:
            details.append({
                "location": loc,
                "expected": expected,
                "actual": None,
                "passed": False,
                "error": "index out of range",
            })
            all_passed = False

    return {"passed": all_passed, "details": details}


def bed_level_change_check(z_initial, z_final):
    """Check whether any bed-level change occurred.

    Returns
    -------
    dict
        ``{"passed": bool, "mean_abs_change": float}``
        ``passed`` is True when the mean absolute change is > 0.
    """
    z_initial = np.asarray(z_initial, dtype=float)
    z_final = np.asarray(z_final, dtype=float)
    mean_abs = float(np.mean(np.abs(z_final - z_initial)))
    return {"passed": mean_abs > 0, "mean_abs_change": mean_abs}


def run_diagnostics(config):
    """Run a full diagnostic verification suite.

    Parameters
    ----------
    config : dict
        Must contain keys ``z_pre``, ``z_sim``, ``z_obs``, ``dx``, ``dy``,
        ``mass_balance_threshold``.
        Optional: ``slope_locations``, ``expected_slopes``, ``slope_tolerance``.

    Returns
    -------
    dict
        Per-check results plus ``"overall"`` (``"PASS"`` or ``"FAIL"``).
    """
    from coastal_diag.metrics import brier_skill_score, rmse, mass_balance_check, volume_change

    z_pre = np.asarray(config["z_pre"], dtype=float)
    z_sim = np.asarray(config["z_sim"], dtype=float)
    z_obs = np.asarray(config["z_obs"], dtype=float)
    dx = config["dx"]
    dy = config.get("dy", 1.0)

    results = {}

    # Skill metrics
    results["brier_skill_score"] = float(brier_skill_score(z_sim, z_obs, z_pre))
    results["rmse"] = float(rmse(z_sim, z_obs))
    results["volume_change"] = float(volume_change(z_pre, z_sim, dx, dy))

    # Mass balance
    threshold = config.get("mass_balance_threshold", 5.0)
    passed, error = mass_balance_check(z_pre, z_sim, dx, dy, threshold)
    results["mass_balance"] = {"passed": passed, "error": error}

    # Bed level change
    results["bed_level_change"] = bed_level_change_check(z_pre, z_sim)

    # Slope check (optional)
    if "slope_locations" in config and "expected_slopes" in config:
        results["slope_check"] = slope_check(
            z_sim, dx,
            config["slope_locations"],
            config["expected_slopes"],
            config.get("slope_tolerance", 0.1),
        )

    # Overall verdict
    all_passed = True
    for key, val in results.items():
        if isinstance(val, dict) and "passed" in val:
            if not val["passed"]:
                all_passed = False
    results["overall"] = "PASS" if all_passed else "FAIL"

    return results
