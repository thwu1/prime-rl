#!/usr/bin/env python3
"""Generate synthetic market data for the market-making pipeline task.

Produces:
  /app/data/returns.csv   - 500 daily log returns from a GARCH(1,1) process
  /app/data/orderbook.csv - 3000 L1 order book ticks with regime shifts and VPIN episodes
"""

import csv
import math
import os
import random


def generate():
    os.makedirs('/app/data', exist_ok=True)

    # === Daily returns from GARCH(1,1) with known parameters ===
    random.seed(42)
    omega, alpha, beta = 2e-6, 0.08, 0.90
    sigma2 = omega / (1.0 - alpha - beta)  # long-run variance = 1e-4

    with open('/app/data/returns.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['day', 'log_return'])
        for day in range(500):
            z = random.gauss(0, 1)
            r = z * math.sqrt(sigma2)
            w.writerow([day, f'{r:.10f}'])
            sigma2 = omega + alpha * r * r + beta * sigma2
            sigma2 = max(sigma2, 1e-10)

    # === L1 order book ticks with regime shifts and VPIN episodes ===
    random.seed(1337)
    price = 100.0

    with open('/app/data/orderbook.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['tick', 'bid_price', 'bid_size', 'ask_price', 'ask_size',
                     'trade_price', 'trade_volume', 'trade_side'])
        for i in range(3000):
            u1, u2, u3 = random.random(), random.random(), random.random()

            # Regime shifts embedded in the data:
            #   ticks 0-999:    normal volatility
            #   ticks 1000-1499: crisis (3x vol)
            #   ticks 1500-2499: normal
            #   ticks 2500-2999: low vol (0.3x vol)
            if 1000 <= i < 1500:
                vol_mult = 3.0
            elif 2500 <= i:
                vol_mult = 0.3
            else:
                vol_mult = 1.0

            # VPIN episodes:
            #   ticks 500-699:   strong buy pressure
            #   ticks 1800-1999: strong sell pressure
            if 500 <= i < 700:
                bias = 0.7
            elif 1800 <= i < 2000:
                bias = -0.7
            else:
                bias = 0.0

            price_change = ((u1 - 0.5) + bias * 0.3) * 0.1 * vol_mult
            price += price_change
            spread = 0.05 + u2 * 0.1 * vol_mult
            bid = price - spread / 2.0
            ask = price + spread / 2.0
            bid_size = 100.0 + u2 * 900.0 + (500.0 if bias > 0.3 else 0.0)
            ask_size = 100.0 + u3 * 900.0 + (500.0 if bias < -0.3 else 0.0)

            trade_price = ask if u1 > 0.5 - bias * 0.3 else bid
            trade_side = 1 if trade_price >= (bid + ask) / 2.0 else -1
            trade_volume = 10.0 + u3 * 90.0

            w.writerow([i, f'{bid:.4f}', f'{bid_size:.2f}',
                        f'{ask:.4f}', f'{ask_size:.2f}',
                        f'{trade_price:.4f}', f'{trade_volume:.2f}', trade_side])


if __name__ == '__main__':
    generate()
    print('Generated /app/data/returns.csv and /app/data/orderbook.csv')
