#!/usr/bin/env python3
"""Entry point for the systematic trading backtest."""
import os
import json
import pandas as pd
from trading_system.config import load_config
from trading_system.data_loader import (
    load_prices, load_carry_data, load_fx_rate, load_instrument_config)
from trading_system.volatility import compute_mixed_vol
from trading_system.signals import ewmac_forecast, carry_forecast
from trading_system.forecast import (
    scale_and_cap_forecasts, compute_fdm, combine_forecasts)
from trading_system.positions import compute_positions


def main():
    config = load_config()
    vc = config['volatility']
    rules_config = config['trading_rules']

    forecast_weights = config.get('forecast_weights', None)
    if forecast_weights is None:
        # Fallback to equal weights if key not found
        forecast_weights = {r: 1.0 / len(rules_config) for r in rules_config}

    cap = config['forecast_cap']
    capital = config['capital']
    vol_target = config['vol_target_pct']
    avg_abs_fc = config['average_absolute_forecast']
    idm = config['instrument_div_multiplier']
    base_ccy = config['base_currency']
    instr_weights = config['instrument_weights']

    instr_meta = load_instrument_config()
    os.makedirs('/app/output', exist_ok=True)

    all_positions = {}
    diagnostics = {}

    for instr in instr_weights:
        price = load_prices(instr)
        cdata = load_carry_data(instr)
        row = instr_meta[instr_meta['code'] == instr].iloc[0]
        pointsize = float(row['pointsize'])
        currency = row['currency']
        fx = load_fx_rate(currency, base_ccy, price.index)

        # Align indices
        common = price.index.intersection(cdata.index).intersection(fx.index)
        price = price.loc[common]
        cdata = cdata.loc[common]
        fx = fx.loc[common]

        # Volatility
        changes = price.diff()
        vol = compute_mixed_vol(
            changes, vc['days'], vc['slow_vol_years'],
            vc['proportion_of_slow_vol'], vc['vol_abs_min'])

        # Raw forecasts
        raw_forecasts = {}
        for rule, params in rules_config.items():
            if rule.startswith('ewmac'):
                raw_forecasts[rule] = ewmac_forecast(
                    price, vol, params['Lfast'], params['Lslow'])
            elif rule == 'carry':
                raw_forecasts[rule] = carry_forecast(
                    cdata, vol, params['smooth_days'])

        # Scale and cap
        scaled = scale_and_cap_forecasts(raw_forecasts, rules_config, cap)

        # FDM and combination
        scaled_df = pd.DataFrame(scaled)
        fdm = compute_fdm(scaled_df, forecast_weights)
        combined = combine_forecasts(
            scaled, forecast_weights, fdm, cap, price.index)

        # Position sizing
        subsystem_pos, portfolio_pos = compute_positions(
            combined, vol, pointsize, fx, capital, vol_target,
            avg_abs_fc, instr_weights[instr], idm)

        all_positions[instr] = portfolio_pos

        # Save intermediates
        pd.DataFrame({'vol': vol}).to_csv(
            f'/app/output/{instr}_vol.csv', index_label='DATETIME')
        pd.DataFrame(raw_forecasts).to_csv(
            f'/app/output/{instr}_raw_forecasts.csv', index_label='DATETIME')
        pd.DataFrame(scaled).to_csv(
            f'/app/output/{instr}_scaled_forecasts.csv', index_label='DATETIME')
        pd.DataFrame({'combined': combined}).to_csv(
            f'/app/output/{instr}_combined_forecast.csv', index_label='DATETIME')

        diagnostics[instr] = {
            'fdm': float(fdm),
            'last_vol': float(vol.dropna().iloc[-1]),
            'last_combined_forecast': float(combined.dropna().iloc[-1]),
            'last_subsystem_position': float(subsystem_pos.dropna().iloc[-1]),
            'last_portfolio_position': float(portfolio_pos.dropna().iloc[-1]),
            'instrument_weight': float(instr_weights[instr]),
            'idm': float(idm),
        }

    pd.DataFrame(all_positions).to_csv(
        '/app/output/positions.csv', index_label='DATETIME')
    with open('/app/output/diagnostics.json', 'w') as f:
        json.dump(diagnostics, f, indent=2)

    print("Backtest complete.")
    for instr, d in diagnostics.items():
        print(f"  {instr}: FDM={d['fdm']:.3f}  "
              f"last_pos={d['last_portfolio_position']:.2f}")


if __name__ == '__main__':
    main()
