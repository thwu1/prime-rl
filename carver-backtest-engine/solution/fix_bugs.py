#!/usr/bin/env python3
"""Fix all defects in the trading system and implement missing components.

Writes complete correct versions of each buggy module to eliminate
string-replacement fragility. Also fixes the YAML config structure
and implements the missing FDM computation from scratch.
"""

import yaml

# =============================================================================
# Fix 1: volatility.py — fast_vol gets (1-proportion), slow_vol gets proportion
# Bug was: weights were swapped (fast_vol * proportion_of_slow_vol)
# =============================================================================
with open('/app/trading_system/volatility.py', 'w') as f:
    f.write('''\
"""Volatility estimation module."""
import numpy as np


def compute_mixed_vol(price_changes, days, slow_vol_years,
                      proportion_of_slow_vol, vol_abs_min):
    fast_vol = price_changes.ewm(span=days, min_periods=days).std()
    slow_days = int(slow_vol_years * 252)
    slow_vol = price_changes.rolling(slow_days, min_periods=days).std()
    vol = fast_vol * (1.0 - proportion_of_slow_vol) + slow_vol * proportion_of_slow_vol
    vol = vol.clip(lower=vol_abs_min)
    return vol
''')
print("Fixed: volatility proportion weights")

# =============================================================================
# Fix 2: signals.py — two bugs in carry_forecast:
#   (a) sign was inverted: (price - carry_price) should be (carry_price - price)
#   (b) vol normalization: divided by annualized vol (vol * sqrt(252)) instead
#       of daily vol. Carry spread is a daily-return-equivalent so normalize
#       by daily vol only.
# =============================================================================
with open('/app/trading_system/signals.py', 'w') as f:
    f.write('''\
"""Trading signal generation."""


def ewmac_forecast(price, vol, Lfast, Lslow):
    fast_ema = price.ewm(span=Lfast, min_periods=Lfast).mean()
    slow_ema = price.ewm(span=Lslow, min_periods=Lslow).mean()
    return (fast_ema - slow_ema) / vol


def carry_forecast(carry_data, vol, smooth_days):
    raw = (carry_data['carry_price'] - carry_data['price']) / vol
    return raw.ewm(span=smooth_days, min_periods=smooth_days).mean()
''')
print("Fixed: carry signal sign and vol normalization")

# =============================================================================
# Fix 3: data_loader.py — FX pair name construction
# Bug: pair was f"{base_currency}_{instrument_currency}" giving "USD_EUR"
# but the database stores "EUR_USD". Fix: swap the order.
# =============================================================================
with open('/app/trading_system/data_loader.py', 'w') as f:
    f.write('''\
"""Data loading from SQLite database."""
import pandas as pd
import sqlite3

DB_PATH = '/app/market.db'


def _conn():
    return sqlite3.connect(DB_PATH)


def load_prices(instrument):
    conn = _conn()
    df = pd.read_sql_query(
        "SELECT date, price FROM prices WHERE instrument = ? ORDER BY date",
        conn, params=(instrument,), parse_dates=['date'])
    conn.close()
    return df.set_index('date')['price']


def load_carry_data(instrument):
    conn = _conn()
    df = pd.read_sql_query(
        "SELECT date, price, carry_price FROM carry_prices "
        "WHERE instrument = ? ORDER BY date",
        conn, params=(instrument,), parse_dates=['date'])
    conn.close()
    return df.set_index('date')


def load_fx_rate(instrument_currency, base_currency, index):
    if instrument_currency == base_currency:
        return pd.Series(1.0, index=index, name='fx')
    pair = f"{instrument_currency}_{base_currency}"
    conn = _conn()
    df = pd.read_sql_query(
        "SELECT date, rate FROM fx_rates WHERE pair = ? ORDER BY date",
        conn, params=(pair,), parse_dates=['date'])
    conn.close()
    if df.empty:
        return pd.Series(1.0, index=index, name='fx')
    return df.set_index('date')['rate'].reindex(index).ffill()


def load_instrument_config():
    conn = _conn()
    df = pd.read_sql_query("SELECT * FROM instruments", conn)
    conn.close()
    return df
''')
print("Fixed: FX pair name construction")

# =============================================================================
# Fix 4: Config — forecast_weights nested under forecast_combination
# but run_backtest.py reads config.get('forecast_weights') at top level.
# Extract and promote to top level.
# =============================================================================
with open('/app/system_config.yaml', 'r') as f:
    config = yaml.safe_load(f)
if 'forecast_weights' not in config and 'forecast_combination' in config:
    config['forecast_weights'] = config['forecast_combination']['forecast_weights']
    del config['forecast_combination']
    with open('/app/system_config.yaml', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    print("Fixed: forecast_weights config key nesting")

# =============================================================================
# Fix 5: forecast.py — implement FDM from correlation matrix
# The stub returned a constant 1.0. Correct formula:
#   FDM = min(1 / sqrt(w' H w), 2.5)
# where H is the CORRELATION matrix of scaled forecasts and w are
# the normalized forecast weights. Uses correlation (not covariance)
# because forecasts are already scaled to have similar expected
# absolute values via forecast_scalar.
# =============================================================================
with open('/app/trading_system/forecast.py', 'w') as f:
    f.write('''\
"""Forecast scaling, combination, and diversification multiplier."""
import pandas as pd
import numpy as np


def scale_and_cap_forecasts(raw_forecasts, rules_config, cap):
    scaled = {}
    for rule, raw in raw_forecasts.items():
        scalar = rules_config[rule]['forecast_scalar']
        scaled[rule] = (raw * scalar).clip(-cap, cap)
    return scaled


def compute_fdm(scaled_df, weights):
    """Compute FDM using correlation-based diversification benefit.

    FDM = min(1 / sqrt(w' H w), 2.5)
    where H is the correlation matrix of scaled forecasts
    and w are the normalized forecast weights.
    """
    clean = scaled_df.dropna()
    if len(clean) < 20:
        return 1.0
    H = clean.corr().values
    cols = list(clean.columns)
    w = np.array([weights.get(c, 0.0) for c in cols])
    total = w.sum()
    if total == 0:
        return 1.0
    w = w / total
    wHw = float(w @ H @ w)
    if wHw <= 0:
        return 2.5
    fdm = 1.0 / np.sqrt(wHw)
    return min(fdm, 2.5)


def combine_forecasts(scaled_forecasts, weights, fdm, cap, index):
    total_w = sum(weights.values())
    combined = pd.Series(0.0, index=index)
    for rule, w in weights.items():
        if rule in scaled_forecasts:
            combined = combined.add(
                scaled_forecasts[rule] * (w / total_w), fill_value=0.0)
    combined = (combined * fdm).clip(-cap, cap)
    return combined
''')
print("Implemented: FDM correlation-based estimation")

# =============================================================================
# Fix 6: positions.py — vol annualization
# Bug: annual_vol = vol * 252 (wrong: multiplies by business days count)
# Fix: annual_vol = vol * sqrt(252) (correct: standard vol scaling)
# =============================================================================
with open('/app/trading_system/positions.py', 'w') as f:
    f.write('''\
"""Position sizing module."""
import numpy as np


def compute_positions(combined_forecast, vol, pointsize, fx,
                      capital, vol_target_pct, avg_abs_forecast,
                      instrument_weight, idm):
    annual_vol = vol * np.sqrt(252)
    instrument_value_vol = annual_vol * pointsize * fx
    vol_scalar = (capital * vol_target_pct / 100.0) / \\
                 (instrument_value_vol * avg_abs_forecast)
    subsystem_pos = combined_forecast * vol_scalar
    portfolio_pos = subsystem_pos * instrument_weight * idm
    return subsystem_pos, portfolio_pos
''')
print("Fixed: vol annualization factor")

print("\nAll fixes applied. Re-running backtest...")
