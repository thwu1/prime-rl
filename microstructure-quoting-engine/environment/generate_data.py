#!/usr/bin/env python3
"""Generate deterministic synthetic market data with embedded regime structure."""

import csv
import math
import os

SEED = 42
N = 5000
OMEGA = 0.000002
ALPHA = 0.08
BETA = 0.90


def lcg(state):
    return (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF


def uniform(state):
    state = lcg(state)
    return state, (state >> 11) / (1 << 53)


def box_muller(state):
    state, u1 = uniform(state)
    state, u2 = uniform(state)
    u1 = max(u1, 1e-15)
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    return state, z


def main():
    os.makedirs('/app/data', exist_ok=True)
    rng = SEED
    price = 100.0
    sigma2 = OMEGA / (1 - ALPHA - BETA)  # 0.0001

    with open('/app/data/events.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['timestamp', 'bid_price', 'bid_size', 'ask_price', 'ask_size',
                     'trade_price', 'trade_volume', 'trade_side', 'log_return'])

        for t in range(N):
            # Regime configuration
            if 1500 <= t < 2500:
                vol_mult = 4.0
                drift = 0.0
            elif 2500 <= t < 3000:
                vol_mult = 7.0
                drift = -0.003
            else:
                vol_mult = 1.0
                drift = 0.0

            rng, z = box_muller(rng)
            z = max(-3.5, min(3.5, z))

            # Base GARCH return (for GARCH state updates)
            base_sigma = math.sqrt(sigma2)
            base_ret = base_sigma * z

            # Actual return with regime scaling
            eff_sigma = base_sigma * math.sqrt(vol_mult)
            ret = drift + eff_sigma * z
            ret = max(-0.08, min(0.08, ret))

            # Update GARCH with base return only (keeps state well-behaved)
            sigma2 = OMEGA + ALPHA * base_ret ** 2 + BETA * sigma2
            sigma2 = max(sigma2, 1e-12)
            sigma2 = min(sigma2, 0.001)

            new_price = price * math.exp(ret)
            half_spread = max(0.003, eff_sigma * 3) * new_price
            bid_p = round(new_price - half_spread, 4)
            ask_p = round(new_price + half_spread, 4)

            rng, u = uniform(rng)
            bid_sz = int(100 + u * 900)
            rng, u = uniform(rng)
            ask_sz = int(100 + u * 900)

            rng, u = uniform(rng)
            trade_p = round(bid_p + u * (ask_p - bid_p), 4)
            rng, u = uniform(rng)
            trade_vol = int(10 + u * 490)

            mid = (bid_p + ask_p) / 2
            trade_side = 1 if trade_p > mid else (-1 if trade_p < mid else 0)

            w.writerow([t, bid_p, bid_sz, ask_p, ask_sz, trade_p,
                         trade_vol, trade_side, round(ret, 10)])
            price = new_price


if __name__ == '__main__':
    main()
