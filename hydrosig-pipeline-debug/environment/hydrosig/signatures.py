"""Hydrological signature computations.

Implements standard hydrological signatures including flood moments,
flow duration curve slope, seasonality index, and streamflow elasticity.
"""
import numpy as np
import pandas as pd


def flood_moments(q_df):
    """Compute flood moments: MAF, CV, CS (Fisher-Pearson skewness).

    MAF = mean of annual maxima
    CV  = coefficient of variation
    CS  = coefficient of skewness (Fisher-Pearson adjusted)
    """
    annual_max = q_df.resample('YE').max()
    maf = float(annual_max.mean().iloc[0])

    n = len(q_df)
    values = q_df.iloc[:, 0].values
    s2 = np.sum((values - maf) ** 2) / (n - 1)
    cv = float(np.sqrt(s2) / maf)
    cs = float(np.sum((values - maf) ** 3) / ((n - 1) * (n - 2) * s2 ** 1.5))

    return {'MAF': maf, 'CV': cv, 'CS': cs}


def fdc_slope(discharge, bins=(33, 67)):
    """Compute flow duration curve slope between percentile bins.

    Uses log-transformed discharge (clipped at 1e-3).
    """
    q = np.asarray(discharge, dtype=np.float64)
    q_log = np.log(np.clip(q, 1e-3, None))
    percentiles = np.percentile(q_log, list(bins))
    return float(np.diff(percentiles)[0] / (np.diff(bins)[0] / 100.0))


def seasonality_index(q_series):
    """Compute Walsh & Lawler (1981) seasonality index.

    SI = mean over years of: (1/R) * sum(|x_i - R/12|)
    where R is annual total, x_i monthly totals.
    """
    annual = q_series.resample('YE').sum()
    monthly = q_series.resample('ME').sum()

    si_values = []
    for year_end in annual.index:
        r = annual.loc[year_end]
        if r < 1e-6:
            continue
        year_months = monthly[monthly.index.year == year_end.year]
        deviation_sum = (year_months - r / 12).sum()
        si_values.append(float(deviation_sum / r))

    return float(np.mean(si_values)) if si_values else 0.0


def streamflow_elasticity(q_series, p_series):
    """Compute streamflow elasticity (Sankarasubramanian et al., 2001).

    E = median(dQ/dP * P/Q) using annual means.
    """
    q_annual = q_series.resample('YE').mean()
    p_annual = p_series.resample('YE').mean()
    dq = q_annual.diff()
    dp = p_annual.diff()
    ratios = dq / dp * p_annual / q_annual
    return float(np.nanmean(ratios))
