#!/usr/bin/env python3
"""
Carver-style systematic trading backtest engine.
Implements: mixed vol, EWMAC, carry, forecast combination with FDM,
vol-targeted position sizing, portfolio construction with IDM.
"""

import pandas as pd
import numpy as np
import yaml
import json
import os


def load_config(path='/app/config.yaml'):
    with open(path) as f:
        return yaml.safe_load(f)


def load_prices(instrument):
    df = pd.read_csv(f'/app/data/prices/{instrument}.csv', parse_dates=['DATETIME'])
    df = df.set_index('DATETIME')
    return df['PRICE'].resample('B').last().ffill()


def load_carry(instrument):
    df = pd.read_csv(f'/app/data/carry/{instrument}.csv', parse_dates=['DATETIME'])
    df = df.set_index('DATETIME')
    return df.resample('B').last().ffill()


def load_fx(currency, base, reference_index):
    if currency == base:
        return pd.Series(1.0, index=reference_index, name='FXRATE')
    path = f'/app/data/fx/{currency}{base}fx.csv'
    df = pd.read_csv(path, parse_dates=['DATETIME'])
    df = df.set_index('DATETIME')
    return df['FXRATE'].resample('B').last().ffill()


def compute_mixed_vol(price_changes, days, slow_vol_years,
                      proportion_of_slow_vol, vol_abs_min):
    fast_vol = price_changes.ewm(span=days, min_periods=days).std()
    slow_days = int(slow_vol_years * 252)
    slow_vol = price_changes.rolling(slow_days, min_periods=days).std()
    vol = fast_vol * (1.0 - proportion_of_slow_vol) + slow_vol * proportion_of_slow_vol
    vol = vol.clip(lower=vol_abs_min)
    return vol


def ewmac_forecast(price, vol, Lfast, Lslow):
    fast_ema = price.ewm(span=Lfast, min_periods=Lfast).mean()
    slow_ema = price.ewm(span=Lslow, min_periods=Lslow).mean()
    return (fast_ema - slow_ema) / vol


def carry_forecast(carry_data, vol, smooth_days):
    raw = (carry_data['CARRY'] - carry_data['PRICE']) / vol
    return raw.ewm(span=smooth_days, min_periods=smooth_days).mean()


def compute_fdm(scaled_df, weights):
    corr = scaled_df.dropna().corr()
    w = np.array([weights.get(c, 0.0) for c in corr.columns])
    total = w.sum()
    if total == 0:
        return 1.0
    w = w / total
    wHw = float(w @ corr.values @ w)
    if wHw <= 0:
        return 2.5
    fdm = 1.0 / np.sqrt(wHw)
    return min(fdm, 2.5)


def main():
    config = load_config()
    vc = config['volatility_calculation']
    instruments = list(config['instrument_weights'].keys())
    rules_config = config['trading_rules']
    forecast_weights = config['forecast_weights']
    cap = config['forecast_cap']
    capital = config['notional_trading_capital']
    vol_target = config['percentage_vol_target']
    avg_abs_fc = config['average_absolute_forecast']
    idm = config['instrument_div_multiplier']
    base_ccy = config['base_currency']

    instr_meta = pd.read_csv('/app/data/instrument_config.csv')
    os.makedirs('/app/output', exist_ok=True)

    all_positions = {}
    diagnostics = {}

    for instr in instruments:
        price = load_prices(instr)
        cdata = load_carry(instr)
        row = instr_meta[instr_meta['Instrument'] == instr].iloc[0]
        pointsize = float(row['Pointsize'])
        currency = row['Currency']
        fx = load_fx(currency, base_ccy, price.index)

        # Align indices
        idx = price.index.intersection(cdata.index).intersection(fx.index)
        price, cdata, fx = price.loc[idx], cdata.loc[idx], fx.loc[idx]

        # 1) Mixed volatility
        changes = price.diff()
        vol = compute_mixed_vol(
            changes, vc['days'], vc['slow_vol_years'],
            vc['proportion_of_slow_vol'], vc['vol_abs_min'])

        # 2) Raw forecasts
        raw_forecasts = {}
        for rule, params in rules_config.items():
            if rule.startswith('ewmac'):
                raw_forecasts[rule] = ewmac_forecast(
                    price, vol, params['Lfast'], params['Lslow'])
            elif rule == 'carry':
                raw_forecasts[rule] = carry_forecast(
                    cdata, vol, params['smooth_days'])

        # 3) Scale and cap
        scaled_forecasts = {}
        for rule, raw in raw_forecasts.items():
            scalar = rules_config[rule]['forecast_scalar']
            scaled_forecasts[rule] = (raw * scalar).clip(-cap, cap)

        # 4) FDM
        scaled_df = pd.DataFrame(scaled_forecasts).dropna()
        fdm = compute_fdm(scaled_df, forecast_weights)

        # 5) Combine forecasts
        total_w = sum(forecast_weights.values())
        combined = pd.Series(0.0, index=price.index)
        for rule, w in forecast_weights.items():
            if rule in scaled_forecasts:
                combined = combined.add(
                    scaled_forecasts[rule] * (w / total_w), fill_value=0.0)
        combined = (combined * fdm).clip(-cap, cap)

        # 6) Position sizing
        annual_vol = vol * np.sqrt(252)
        instrument_value_vol = annual_vol * pointsize * fx
        vol_scalar = (capital * vol_target / 100.0) / \
                     (instrument_value_vol * avg_abs_fc)
        subsystem_pos = combined * vol_scalar

        # 7) Portfolio position
        instr_weight = config['instrument_weights'][instr]
        portfolio_pos = subsystem_pos * instr_weight * idm
        all_positions[instr] = portfolio_pos

        # Save intermediates
        pd.DataFrame({'vol': vol}).to_csv(
            f'/app/output/{instr}_vol.csv', index_label='DATETIME')
        pd.DataFrame(raw_forecasts).to_csv(
            f'/app/output/{instr}_raw_forecasts.csv', index_label='DATETIME')
        pd.DataFrame(scaled_forecasts).to_csv(
            f'/app/output/{instr}_scaled_forecasts.csv', index_label='DATETIME')
        pd.DataFrame({'combined': combined}).to_csv(
            f'/app/output/{instr}_combined_forecast.csv', index_label='DATETIME')

        diagnostics[instr] = {
            'fdm': float(fdm),
            'last_vol': float(vol.dropna().iloc[-1]),
            'last_combined_forecast': float(combined.dropna().iloc[-1]),
            'last_subsystem_position': float(subsystem_pos.dropna().iloc[-1]),
            'last_portfolio_position': float(portfolio_pos.dropna().iloc[-1]),
            'instrument_weight': float(instr_weight),
            'idm': float(idm),
        }

    # Save portfolio positions
    pd.DataFrame(all_positions).to_csv(
        '/app/output/positions.csv', index_label='DATETIME')

    with open('/app/output/diagnostics.json', 'w') as f:
        json.dump(diagnostics, f, indent=2)

    print("Backtest complete. Results in /app/output/")
    for instr, d in diagnostics.items():
        print(f"  {instr}: FDM={d['fdm']:.3f}  "
              f"last_pos={d['last_portfolio_position']:.2f}")


if __name__ == '__main__':
    main()
