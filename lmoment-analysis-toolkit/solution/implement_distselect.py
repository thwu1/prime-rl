#!/usr/bin/env python3

"""
Implement the distribution selection module (distselect.py).

This replaces the stub functions with working implementations based on
Hosking & Wallis (1997) L-moment ratio diagram theory.

Functions implemented:
- _gev_tau4: numerical inversion tau3 -> kappa -> tau4
- _glo_tau4: closed-form (1 + 5*tau3^2) / 6
- _gpa_tau4: closed-form tau3*(1 + 5*tau3) / (5 + tau3)
- select_distribution: L-moment ratio diagram comparison
- bootstrap_return_level: percentile bootstrap for return levels
"""

DISTSELECT_CODE = '''"""
Distribution selection via L-moment ratio diagram analysis and
bootstrap confidence intervals for return levels.

Implements Hosking & Wallis (1997) L-moment ratio diagram theory for
comparing candidate extreme value distribution families.
"""
import numpy as np
from math import log
from scipy.optimize import brentq
from analysis.lmoments import sample_lmoments
from analysis.fit import fit_gev, return_level_gev


def _gev_tau3_func(kh):
    """Theoretical GEV L-skewness as a function of Hosking kappa."""
    if abs(kh) < 1e-10:
        return 2 * log(3) / log(2) - 3  # Gumbel limit
    return 2 * (1 - 3 ** (-kh)) / (1 - 2 ** (-kh)) - 3


def _gev_tau4(tau3):
    """Theoretical GEV L-kurtosis as a function of L-skewness tau3.

    Inverts tau3(kappa) via Brent root-finding, then computes tau4(kappa)
    using the GEV L-kurtosis formula from Hosking & Wallis (1997).
    """
    try:
        kh = brentq(lambda k: _gev_tau3_func(k) - tau3,
                    -0.99, 10.0, xtol=1e-12)
    except ValueError:
        return None

    if abs(kh) < 1e-10:
        # Gumbel limit: tau4 = 16 - 10*ln(3)/ln(2)
        return 16 - 10 * log(3) / log(2)

    d = 1 - 2 ** (-kh)
    return (5 * (1 - 4 ** (-kh)) - 10 * (1 - 3 ** (-kh)) + 6 * d) / d


def _glo_tau4(tau3):
    """Theoretical GLO L-kurtosis: tau4 = (1 + 5*tau3^2) / 6."""
    return (1 + 5 * tau3 ** 2) / 6


def _gpa_tau4(tau3):
    """Theoretical GPA L-kurtosis: tau4 = tau3*(1 + 5*tau3) / (5 + tau3)."""
    return tau3 * (1 + 5 * tau3) / (5 + tau3)


_TAU4_FUNCS = {
    "gev": _gev_tau4,
    "glo": _glo_tau4,
    "gpa": _gpa_tau4,
}


def select_distribution(data, candidates=None):
    """Select best-fitting distribution using L-moment ratio diagram.

    Computes sample L-skewness (tau3 = l3/l2) and L-kurtosis (tau4 = l4/l2),
    then compares against theoretical tau4(tau3) curves for each candidate.
    The best distribution minimizes |tau4_sample - tau4_theoretical|.
    """
    if candidates is None:
        candidates = ["gev", "glo", "gpa"]

    data = np.asarray(data, dtype=float)
    lm = sample_lmoments(data, nmom=4)
    tau3 = float(lm[2] / lm[1])
    tau4 = float(lm[3] / lm[1])

    distances = {}
    for name in candidates:
        func = _TAU4_FUNCS.get(name)
        if func is None:
            continue
        t4_theo = func(tau3)
        if t4_theo is None:
            distances[name] = float("inf")
        else:
            distances[name] = float(abs(tau4 - t4_theo))

    selected = min(distances, key=distances.get)

    return {
        "selected": selected,
        "tau3": tau3,
        "tau4": tau4,
        "distances": distances,
    }


def bootstrap_return_level(data, T=100, n_boot=500, ci_level=0.95, seed=42):
    """Bootstrap confidence interval for T-year return level.

    Resamples with replacement, refits GEV to each resample,
    computes T-year return level, returns percentile-based CIs.
    """
    data = np.asarray(data, dtype=float)
    n = len(data)

    # Point estimate from original data
    loc, scale, shape = fit_gev(data)
    point_est = return_level_gev(loc, scale, shape, T)

    # Bootstrap resampling
    rng = np.random.default_rng(seed)
    boot_rls = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        sample = data[idx]
        try:
            loc_b, scale_b, shape_b = fit_gev(sample)
            if scale_b > 0:
                rl_b = return_level_gev(loc_b, scale_b, shape_b, T)
                if np.isfinite(rl_b):
                    boot_rls.append(rl_b)
        except Exception:
            continue

    boot_rls = np.array(boot_rls)
    alpha = 1 - ci_level
    ci_lower = float(np.percentile(boot_rls, 100 * alpha / 2))
    ci_upper = float(np.percentile(boot_rls, 100 * (1 - alpha / 2)))

    return {
        "point_estimate": float(point_est),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "n_boot": len(boot_rls),
    }
'''


if __name__ == "__main__":
    with open("/app/analysis/distselect.py", "w") as f:
        f.write(DISTSELECT_CODE)
    print("Distribution selection module implemented.")
