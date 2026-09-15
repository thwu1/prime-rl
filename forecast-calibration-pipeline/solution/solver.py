#!/usr/bin/env python3
"""
Solve the Carver-style forecast calibration pipeline task.
"""

import json
import math
import os

import numpy as np
import pandas as pd
import yaml


def main():
    with open('/data/config.yaml') as f:
        config = yaml.safe_load(f)

    instruments = config['instruments']
    vc = config['volatility_calculation']
    rules = config['trading_rules']
    forecast_cap = config['forecast_cap']
    avg_abs_fc = config['average_absolute_forecast']
    fw = config['forecast_weights']
    capital = config['notional_trading_capital']
    vol_target = config['percentage_vol_target']

    # Load prices
    prices = {}
    for inst in instruments:
        df = pd.read_csv(f'/data/{inst}.csv', parse_dates=['date'], index_col='date')
        prices[inst] = df['price']

    # 1. Blended volatility
    vols = {}
    for inst in instruments:
        ret = prices[inst].diff()
        fast = ret.ewm(span=vc['days'], min_periods=vc['min_periods']).std()
        slow = ret.expanding(min_periods=vc['min_periods']).std()
        blended = vc['proportion_of_slow_vol'] * slow + (1.0 - vc['proportion_of_slow_vol']) * fast
        vols[inst] = blended.clip(lower=vc['vol_abs_min'])

    # 2. EWMAC raw forecasts
    rule_names = list(rules.keys())
    raw_fc = {}
    for rn in rule_names:
        raw_fc[rn] = {}
        for inst in instruments:
            f_ema = prices[inst].ewm(span=rules[rn]['Lfast']).mean()
            s_ema = prices[inst].ewm(span=rules[rn]['Lslow']).mean()
            raw_fc[rn][inst] = (f_ema - s_ema) / vols[inst]

    # 3. Pooled forecast scalars
    scalars = {}
    for rn in rule_names:
        pooled = pd.concat([raw_fc[rn][inst] for inst in instruments]).dropna()
        scalars[rn] = avg_abs_fc / pooled.abs().mean()

    # 4. Scale and cap
    sc_fc = {}
    for rn in rule_names:
        sc_fc[rn] = {}
        for inst in instruments:
            s = raw_fc[rn][inst] * scalars[rn]
            sc_fc[rn][inst] = s.clip(lower=-forecast_cap, upper=forecast_cap)

    # 5. FDM from averaged correlation matrices
    corr_mats = []
    for inst in instruments:
        fc_df = pd.DataFrame({rn: sc_fc[rn][inst] for rn in rule_names}).dropna()
        if len(fc_df) > 20:
            corr_mats.append(fc_df.corr().values)
    avg_corr = np.mean(corr_mats, axis=0)
    w = np.array([fw[rn] for rn in rule_names])
    fdm = 1.0 / math.sqrt(float(w @ avg_corr @ w))
    fdm = min(fdm, 2.5)

    # 6. Combined forecasts
    combined = {}
    for inst in instruments:
        c = sum(fw[rn] * sc_fc[rn][inst] for rn in rule_names) * fdm
        combined[inst] = c.clip(lower=-forecast_cap, upper=forecast_cap)

    # 7. Subsystem positions
    positions = {}
    for inst in instruments:
        pos = (combined[inst] / avg_abs_fc) * (capital * vol_target / 100.0) / (
            vols[inst] * math.sqrt(252)
        )
        positions[inst] = pos

    # Write output
    results = {
        'forecast_scalars': {rn: float(scalars[rn]) for rn in rule_names},
        'forecast_diversification_multiplier': float(fdm),
        'combined_forecasts_last': {
            inst: float(combined[inst].dropna().iloc[-1]) for inst in instruments
        },
        'subsystem_positions_last': {
            inst: float(positions[inst].dropna().iloc[-1]) for inst in instruments
        },
        'vol_on_last_date': {
            inst: float(vols[inst].dropna().iloc[-1]) for inst in instruments
        },
    }

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/output/results.json")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
