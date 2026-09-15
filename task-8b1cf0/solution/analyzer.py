#!/usr/bin/env python3
"""
Monetary Policy Regime Analysis Pipeline.
Processes FRED economic time series and outputs structured analysis JSON.
"""

import json
import os
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import spsolve


DATA_DIR = '/fred_data'
OUTPUT_PATH = '/app/output/analysis.json'


def load_data():
    gdp = pd.read_csv(os.path.join(DATA_DIR, 'GDP.csv'),
                       parse_dates=['observation_date'])
    cpi = pd.read_csv(os.path.join(DATA_DIR, 'CPIAUCSL.csv'),
                       parse_dates=['observation_date'])
    unrate = pd.read_csv(os.path.join(DATA_DIR, 'UNRATE.csv'),
                          parse_dates=['observation_date'])
    fedfunds = pd.read_csv(os.path.join(DATA_DIR, 'FEDFUNDS.csv'),
                            parse_dates=['observation_date'])
    t10y2y = pd.read_csv(os.path.join(DATA_DIR, 'T10Y2Y.csv'),
                          parse_dates=['observation_date'])

    # T10Y2Y has missing values (non-numeric strings for weekends/holidays)
    t10y2y['T10Y2Y'] = pd.to_numeric(t10y2y['T10Y2Y'], errors='coerce')
    t10y2y = t10y2y.dropna(subset=['T10Y2Y'])

    return gdp, cpi, unrate, fedfunds, t10y2y


def hp_filter(y, lamb=1600):
    """
    Hodrick-Prescott filter via sparse matrix algebra.
    Minimizes sum((y-tau)^2) + lambda * sum((tau_{t+1} - 2*tau_t + tau_{t-1})^2)
    Equivalent to solving: (I + lambda * D'D) * tau = y
    """
    T = len(y)
    D = sparse.diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(T - 2, T))
    I = sparse.eye(T)
    A = I + lamb * D.T.dot(D)
    trend = spsolve(A.tocsc(), y)
    cycle = y - trend
    return trend, cycle


def compute_sahm_rule(unrate_df):
    df = unrate_df.set_index('observation_date').sort_index()

    # 3-month simple moving average of unemployment rate
    df['ma3'] = df['UNRATE'].rolling(3).mean()
    # Trailing 12-month minimum of the 3-month SMA
    df['min12'] = df['ma3'].rolling(12).min()
    # Sahm indicator
    df['sahm'] = df['ma3'] - df['min12']

    # Find trigger dates: first month crossing 0.50 from below
    trigger_dates = []
    was_below = True
    indicator = {}

    for date, row in df.iterrows():
        if pd.notna(row['sahm']):
            indicator[date.strftime('%Y-%m-%d')] = round(float(row['sahm']), 4)
            if row['sahm'] >= 0.50:
                if was_below:
                    trigger_dates.append(date.strftime('%Y-%m-%d'))
                    was_below = False
            else:
                was_below = True

    return {'trigger_dates': trigger_dates, 'indicator': indicator}


def compute_output_gap(gdp_df, cpi_df):
    cpi = cpi_df.set_index('observation_date')['CPIAUCSL'].sort_index()
    gdp = gdp_df.set_index('observation_date')['GDP'].sort_index()

    # Quarterly average CPI (QS = quarter-start frequency)
    cpi_quarterly = cpi.resample('QS').mean()

    # Align and deflate
    common_dates = gdp.index.intersection(cpi_quarterly.index)
    gdp_aligned = gdp.loc[common_dates]
    cpi_aligned = cpi_quarterly.loc[common_dates]
    real_gdp = gdp_aligned / (cpi_aligned / 100.0)

    # HP filter on log(real GDP)
    log_rgdp = np.log(real_gdp.values)
    log_trend, log_cycle = hp_filter(log_rgdp, lamb=1600)

    # Output gap: percentage deviation of actual from trend
    output_gap = (np.exp(log_rgdp) / np.exp(log_trend) - 1.0) * 100.0

    values = {}
    for i, date in enumerate(common_dates):
        quarter = (date.month - 1) // 3 + 1
        key = f"{date.year}-Q{quarter}"
        values[key] = round(float(output_gap[i]), 4)

    return {'lambda': 1600, 'values': values}, common_dates, output_gap


def compute_inflation(cpi_df):
    """Year-over-year CPI inflation rate (%)."""
    cpi = cpi_df.set_index('observation_date')['CPIAUCSL'].sort_index()
    inflation = (cpi / cpi.shift(12) - 1.0) * 100.0
    return inflation.dropna()


def compute_taylor_rule(cpi_df, output_gap_values, output_gap_dates,
                        r_star=2.0, pi_star=2.0):
    inflation = compute_inflation(cpi_df)

    # Interpolate quarterly output gap to monthly via linear interpolation
    gap_series = pd.Series(output_gap_values, index=output_gap_dates)
    monthly_dates = pd.date_range(start=gap_series.index[0],
                                   end=gap_series.index[-1], freq='MS')
    gap_monthly = gap_series.reindex(monthly_dates).interpolate(method='linear')

    # Taylor (1993) formula: i = r* + pi + 0.5*(pi - pi*) + 0.5*gap
    common_dates = inflation.index.intersection(gap_monthly.index)
    prescribed_rates = {}
    for date in common_dates:
        pi = float(inflation.loc[date])
        gap = float(gap_monthly.loc[date])
        rate = r_star + pi + 0.5 * (pi - pi_star) + 0.5 * gap
        prescribed_rates[date.strftime('%Y-%m-%d')] = round(rate, 4)

    return {
        'r_star': r_star,
        'pi_star': pi_star,
        'prescribed_rates': prescribed_rates
    }


def detect_yield_curve_inversions(t10y2y_df, min_days=5):
    df = t10y2y_df.set_index('observation_date').sort_index()
    spread = df['T10Y2Y']

    # Identify negative spread days and group contiguous periods
    negative = spread < 0
    groups = (negative != negative.shift()).cumsum()

    episodes = []
    for group_id in groups[negative].unique():
        group = spread[groups == group_id]
        if len(group) >= min_days:
            episodes.append({
                'start': group.index[0].strftime('%Y-%m-%d'),
                'end': group.index[-1].strftime('%Y-%m-%d'),
                'duration_days': int(len(group)),
                'min_spread': round(float(group.min()), 4)
            })

    return episodes


def compute_real_fed_funds(fedfunds_df, cpi_df):
    fedfunds = fedfunds_df.set_index('observation_date')['FEDFUNDS'].sort_index()
    inflation = compute_inflation(cpi_df)

    common_dates = fedfunds.index.intersection(inflation.index)
    real_rate = {}
    for date in common_dates:
        rate = float(fedfunds.loc[date]) - float(inflation.loc[date])
        real_rate[date.strftime('%Y-%m-%d')] = round(rate, 4)

    return real_rate


def compute_monetary_stance(fedfunds_df, taylor_rates):
    """Compare actual fed funds to Taylor-prescribed rate by quarter."""
    ff = fedfunds_df.set_index('observation_date')['FEDFUNDS'].sort_index()
    ff.index = pd.to_datetime(ff.index)

    # Convert Taylor rates to series
    taylor_series = pd.Series(
        {pd.Timestamp(k): v for k, v in taylor_rates.items()}
    ).sort_index()

    # Align to common monthly dates
    common = ff.index.intersection(taylor_series.index)
    ff_aligned = ff.loc[common]
    taylor_aligned = taylor_series.loc[common]

    # Quarterly averages
    ff_quarterly = ff_aligned.resample('QS').mean()
    taylor_quarterly = taylor_aligned.resample('QS').mean()

    common_quarters = ff_quarterly.index.intersection(taylor_quarterly.index)

    quarterly_deviation = {}
    stance = {}

    for date in common_quarters:
        if pd.isna(ff_quarterly.loc[date]) or pd.isna(taylor_quarterly.loc[date]):
            continue
        quarter = (date.month - 1) // 3 + 1
        key = f"{date.year}-Q{quarter}"
        dev = round(float(ff_quarterly.loc[date] - taylor_quarterly.loc[date]), 4)
        quarterly_deviation[key] = dev

        if dev < -2.0:
            stance[key] = "accommodative"
        elif dev > 2.0:
            stance[key] = "restrictive"
        else:
            stance[key] = "neutral"

    return {'quarterly_deviation': quarterly_deviation, 'stance': stance}


def main():
    gdp, cpi, unrate, fedfunds, t10y2y = load_data()

    sahm = compute_sahm_rule(unrate)
    output_gap_result, gap_dates, gap_values = compute_output_gap(gdp, cpi)
    taylor = compute_taylor_rule(cpi, gap_values, gap_dates)
    inversions = detect_yield_curve_inversions(t10y2y)
    real_rate = compute_real_fed_funds(fedfunds, cpi)
    stance = compute_monetary_stance(fedfunds, taylor['prescribed_rates'])

    analysis = {
        'sahm_rule': sahm,
        'output_gap': output_gap_result,
        'taylor_rule': taylor,
        'yield_curve_inversions': inversions,
        'real_fed_funds_rate': real_rate,
        'monetary_stance': stance
    }

    os.makedirs('/app/output', exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(analysis, f, indent=2)

    print(f"Analysis written to {OUTPUT_PATH}")
    print(f"Sahm triggers: {len(sahm['trigger_dates'])}")
    print(f"Output gap quarters: {len(output_gap_result['values'])}")
    print(f"Taylor rule months: {len(taylor['prescribed_rates'])}")
    print(f"Yield curve inversions: {len(inversions)}")
    print(f"Real rate months: {len(real_rate)}")
    print(f"Monetary stance quarters: {len(stance['quarterly_deviation'])}")


if __name__ == '__main__':
    main()
