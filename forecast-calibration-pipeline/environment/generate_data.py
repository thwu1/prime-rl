#!/usr/bin/env python3
"""Generate synthetic futures price data and config for the forecast calibration task."""

import random
import math
import os
from datetime import datetime, timedelta

random.seed(42)

os.makedirs('/data', exist_ok=True)

# Write config.yaml
config_content = """\
instruments:
  - INSTR_A
  - INSTR_B
  - INSTR_C
  - INSTR_D

volatility_calculation:
  days: 35
  min_periods: 10
  proportion_of_slow_vol: 0.3
  vol_abs_min: 0.0000000001

trading_rules:
  ewmac8_32:
    Lfast: 8
    Lslow: 32
  ewmac16_64:
    Lfast: 16
    Lslow: 64
  ewmac32_128:
    Lfast: 32
    Lslow: 128

forecast_cap: 20.0
average_absolute_forecast: 10.0

forecast_weights:
  ewmac8_32: 0.333
  ewmac16_64: 0.334
  ewmac32_128: 0.333

percentage_vol_target: 16.0
notional_trading_capital: 1000000
"""

with open('/data/config.yaml', 'w') as f:
    f.write(config_content)

# Generate price data
start = datetime(2015, 1, 2)
n_days = 2000
dates = []
current = start
while len(dates) < n_days:
    if current.weekday() < 5:
        dates.append(current.strftime('%Y-%m-%d'))
    current += timedelta(days=1)

instruments = [
    ('INSTR_A', 100.0, 0.15, 0.03),
    ('INSTR_B', 50.0, 0.25, -0.01),
    ('INSTR_C', 200.0, 0.10, 0.05),
    ('INSTR_D', 75.0, 0.20, 0.02),
]

for name, start_price, annual_vol, drift in instruments:
    daily_vol = annual_vol / math.sqrt(252)
    daily_drift = drift / 252
    price = start_price
    with open(f'/data/{name}.csv', 'w') as f:
        f.write('date,price\n')
        for d in dates:
            f.write(f'{d},{price:.6f}\n')
            log_return = random.gauss(daily_drift, daily_vol)
            price *= math.exp(log_return)
