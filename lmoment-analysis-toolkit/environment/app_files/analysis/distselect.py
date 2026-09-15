"""
Distribution selection via L-moment ratio diagram analysis and
bootstrap confidence intervals for return levels.

The L-moment ratio diagram plots sample (tau3, tau4) against
theoretical tau4(tau3) curves for candidate distributions.
The best-fitting distribution minimizes |tau4_sample - tau4_theoretical(tau3_sample)|.

Candidate distributions:
- GEV (Generalized Extreme Value)
- GLO (Generalized Logistic)
- GPA (Generalized Pareto)

References:
    Hosking, J.R.M. (1990). L-moments: analysis and estimation of
    distributions using linear combinations of order statistics.
    JRSS-B, 52(1), 105-124.

    Hosking, J.R.M. and Wallis, J.R. (1997). Regional Frequency
    Analysis: An Approach Based on L-Moments. Cambridge University Press.
"""
import numpy as np
from analysis.lmoments import sample_lmoments
from analysis.fit import fit_gev, return_level_gev


def _gev_tau4(tau3):
    """Theoretical GEV L-kurtosis as a function of L-skewness tau3.

    Requires numerical inversion of the GEV tau3(kappa) relation to
    obtain the Hosking shape parameter kappa, then computing tau4
    from the L-kurtosis formula for the GEV distribution.

    Parameters
    ----------
    tau3 : float
        Sample or theoretical L-skewness.

    Returns
    -------
    float or None
        Theoretical L-kurtosis, or None if inversion fails.
    """
    raise NotImplementedError("GEV tau4 computation not yet implemented")


def _glo_tau4(tau3):
    """Theoretical GLO (Generalized Logistic) L-kurtosis as a
    function of L-skewness tau3.

    Parameters
    ----------
    tau3 : float

    Returns
    -------
    float
    """
    raise NotImplementedError("GLO tau4 computation not yet implemented")


def _gpa_tau4(tau3):
    """Theoretical GPA (Generalized Pareto) L-kurtosis as a
    function of L-skewness tau3.

    Parameters
    ----------
    tau3 : float

    Returns
    -------
    float
    """
    raise NotImplementedError("GPA tau4 computation not yet implemented")


_TAU4_FUNCS = {
    "gev": _gev_tau4,
    "glo": _glo_tau4,
    "gpa": _gpa_tau4,
}


def select_distribution(data, candidates=None):
    """Select the best-fitting distribution using L-moment ratio diagram.

    Computes sample L-skewness (tau3 = l3/l2) and L-kurtosis (tau4 = l4/l2),
    then compares against theoretical tau4(tau3) curves for each candidate
    distribution. The best distribution minimizes the absolute difference
    |tau4_sample - tau4_theoretical(tau3_sample)|.

    Parameters
    ----------
    data : array_like
        Sample observations.
    candidates : list of str or None
        Distribution names to consider. Default: ["gev", "glo", "gpa"].

    Returns
    -------
    dict with keys:
        "selected" : str — name of the best-fitting distribution
        "tau3" : float — sample L-skewness
        "tau4" : float — sample L-kurtosis
        "distances" : dict — {dist_name: absolute tau4 distance}
    """
    raise NotImplementedError("Distribution selection not yet implemented")


def bootstrap_return_level(data, T=100, n_boot=500, ci_level=0.95, seed=42):
    """Bootstrap confidence interval for T-year return level.

    Resamples data with replacement, fits GEV to each resample,
    computes the T-year return level, and returns percentile-based
    confidence intervals.

    Parameters
    ----------
    data : array_like
        Sample observations.
    T : float
        Return period in years.
    n_boot : int
        Number of bootstrap resamples.
    ci_level : float
        Confidence level (0.95 = 95% CI).
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict with keys:
        "point_estimate" : float — return level from original data
        "ci_lower" : float — lower confidence bound
        "ci_upper" : float — upper confidence bound
        "n_boot" : int — number of successful bootstrap resamples
    """
    raise NotImplementedError("Bootstrap return level not yet implemented")
