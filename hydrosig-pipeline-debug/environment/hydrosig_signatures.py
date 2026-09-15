"""Hydrological signature computation.

References
----------
Baker, D.B., Richards, R.P., Loftus, T.T. and Kramer, J.W., 2004.
A new flashiness index: Characteristics and applications to midwestern
rivers and streams. JAWRA, 40(2), pp.503-522.

Walsh, R.P.D. and Lawler, D.M., 1981. Rainfall seasonality: description,
spatial patterns and change through time. Weather, 36(7), pp.201-208.

Sankarasubramanian, A., Vogel, R.M. and Limbrunner, J.F., 2001.
Climate elasticity of streamflow in the United States. Water Resources
Research, 37(6), pp.1771-1781.
"""
import numpy as np
import pandas as pd

from .baseflow import baseflow_index


def flood_moments(streamflow_df):
    """Compute flood moments (MAF, CV, CS).

    Parameters
    ----------
    streamflow_df : pandas.DataFrame
        Daily streamflow with DatetimeIndex.

    Returns
    -------
    dict
        Dictionary with keys 'MAF', 'CV', 'CS'.
    """
    annual_max = streamflow_df.resample("YE").max()
    maf = annual_max.mean().iloc[0]

    n = len(streamflow_df)
    values = streamflow_df.iloc[:, 0].values

    s2 = np.sum((values - maf) ** 2) / (n - 1)
    cv = np.sqrt(s2) / maf
    cs = np.sum((values - maf) ** 3) / ((n - 1) * (n - 2) * s2 ** 1.5)

    return {"MAF": float(maf), "CV": float(cv), "CS": float(cs)}


def flow_duration_curve_slope(discharge, bins=(33, 67), log=True):
    """Compute FDC slope between percentile bins.

    Parameters
    ----------
    discharge : array-like
        Discharge values.
    bins : tuple
        Percentile bins.
    log : bool
        Use log-transformed values.

    Returns
    -------
    numpy.ndarray
        Slopes between bins.
    """
    q = np.asarray(discharge, dtype=np.float64)
    if log:
        q = np.log(np.clip(q, 1e-3, None))
    percentiles = np.percentile(q, list(bins))
    slopes = np.diff(percentiles) / (np.diff(bins) / 100.0)
    return slopes


def flashiness_index(discharge):
    """Compute flashiness index (Baker et al., 2004).

    FI = mean(|dQ/Q|)
    """
    q = np.asarray(discharge, dtype=np.float64)
    diffs = np.diff(q) / q[:-1]
    return float(np.nanmean(np.abs(diffs)))


def seasonality_index_walsh(streamflow_series):
    """Compute Walsh & Lawler (1981) seasonality index.

    SI = mean_over_years(1/R * sum(|xi - R/12|))

    Parameters
    ----------
    streamflow_series : pandas.Series
        Daily streamflow with DatetimeIndex.

    Returns
    -------
    float
        Seasonality index.
    """
    annual = streamflow_series.resample("YE").sum()
    monthly = streamflow_series.resample("ME").sum()

    si_values = []
    for year_end in annual.index:
        year_val = annual.loc[year_end]
        if year_val < 1e-6:
            continue
        year_months = monthly[monthly.index.year == year_end.year]
        deviation_sum = (year_months - year_val / 12).sum()
        si_values.append(deviation_sum / year_val)

    return float(np.mean(si_values)) if si_values else 0.0


def streamflow_elasticity(q_series, p_series):
    """Compute streamflow elasticity.

    Following Sankarasubramanian et al. (2001):
    E = median(dQ/dP * P/Q) using annual means.

    Parameters
    ----------
    q_series : pandas.Series
        Daily streamflow.
    p_series : pandas.Series
        Daily precipitation.

    Returns
    -------
    float
        Streamflow elasticity.
    """
    q_annual = q_series.resample("YE").mean()
    p_annual = p_series.resample("YE").mean()

    dq = q_annual.diff()
    dp = p_annual.diff()

    elasticity = np.nanmean(dq / dp * p_annual / q_annual)

    return float(elasticity)


def compute_all_signatures(q_series, p_series, alpha=0.925):
    """Compute all hydrological signatures.

    Parameters
    ----------
    q_series : pandas.Series
        Daily streamflow with DatetimeIndex.
    p_series : pandas.Series
        Daily precipitation with DatetimeIndex.
    alpha : float
        Baseflow filter parameter.

    Returns
    -------
    dict
        All computed signatures.
    """
    q_df = q_series.to_frame("streamflow")

    bfi = baseflow_index(q_series.values, alpha=alpha)
    fm = flood_moments(q_df)
    fdc = flow_duration_curve_slope(q_series.values)
    fi = flashiness_index(q_series.values)
    si = seasonality_index_walsh(q_series)
    se = streamflow_elasticity(q_series, p_series)

    return {
        "baseflow_index": bfi,
        "flood_moments": fm,
        "fdc_slope": fdc.tolist(),
        "flashiness_index": fi,
        "seasonality_index": si,
        "streamflow_elasticity": se,
    }
