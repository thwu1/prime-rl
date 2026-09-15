#!/usr/bin/env python3
"""
Fill simulation runner.

Process L2 market data through three queue position models and
write results to /app/results.json.

See /app/reference/spec.md for output format and event processing rules.
"""

import json
import numpy as np


def main():
    data = np.load('/app/market_data.npz')['data']
    with open('/app/orders.json') as f:
        orders_cfg = json.load(f)

    # Implement: run simulation with risk_adverse, prob_power_2, prob_log
    # Write results to /app/results.json


if __name__ == "__main__":
    main()
