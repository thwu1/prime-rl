#!/usr/bin/env python3
"""
TWAMM (Time-Weighted Average Market Maker) Simulator.

Implements closed-form virtual-trade math for infinitesimal order execution
against an embedded constant-product AMM (x*y=k, no fees).

"""

import json
import math
import sys
from collections import defaultdict


def twamm_interval(x0: float, y0: float, x_rate: float, y_rate: float, t: float):
    """
    Compute AMM reserves after t blocks of continuous two-sided virtual trading.

    The embedded CPAMM satisfies x*y = K (no fees).
    x_rate: aggregate rate of X being sold to the AMM (tokens/block)
    y_rate: aggregate rate of Y being sold to the AMM (tokens/block)

    Returns (x_final, y_final) - the AMM reserves after t blocks.

    Derivation:
        Infinitesimal trades preserve x*y=K. The net flow into the AMM gives:
            dx/dt = x_rate - (x/y)*y_rate = x_rate - (x^2/K)*y_rate

        This is a Riccati ODE: dx/dt = A - B*x^2
        where A = x_rate, B = y_rate/K.

        Equilibrium: x* = sqrt(A/B) = sqrt(x_rate * K / y_rate) =: alpha

        Solution:
        - If x0 < alpha: x(t) = alpha * tanh(theta*t + atanh(x0/alpha))
        - If x0 > alpha: x(t) = alpha / tanh(theta*t + atanh(alpha/x0))
        - If x0 = alpha: x(t) = alpha

        where theta = sqrt(A*B) = sqrt(x_rate * y_rate / K)
    """
    K = x0 * y0

    if t <= 0 or (x_rate <= 0 and y_rate <= 0):
        return x0, y0

    # Single-sided cases
    if y_rate <= 0:
        # Only X selling: x increases linearly
        x_final = x0 + x_rate * t
        y_final = K / x_final
        return x_final, y_final

    if x_rate <= 0:
        # Only Y selling: y increases linearly
        y_final = y0 + y_rate * t
        x_final = K / y_final
        return x_final, y_final

    # Two-sided case
    alpha = math.sqrt(x_rate * K / y_rate)
    theta = math.sqrt(x_rate * y_rate / K)

    ratio = x0 / alpha

    if abs(ratio - 1.0) < 1e-15:
        # At equilibrium
        return alpha, K / alpha

    if ratio < 1.0:
        # tanh branch
        u0 = math.atanh(ratio)
        x_final = alpha * math.tanh(theta * t + u0)
    else:
        # coth branch: x(t) = alpha / tanh(theta*t + atanh(alpha/x0))
        u0 = math.atanh(1.0 / ratio)
        x_final = alpha / math.tanh(theta * t + u0)

    y_final = K / x_final
    return x_final, y_final


def simulate(scenario: dict) -> dict:
    """Run the full TWAMM simulation."""
    x_amm = scenario["initial_reserves"]["x"]
    y_amm = scenario["initial_reserves"]["y"]
    orders = scenario["orders"]

    # Filter out zero-duration orders
    active_orders = []
    zero_orders = []
    for o in orders:
        if o["end_block"] <= o["start_block"]:
            zero_orders.append(o)
        else:
            active_orders.append(o)

    # Pre-compute sell rates
    rates = {}
    for o in active_orders:
        duration = o["end_block"] - o["start_block"]
        rates[o["id"]] = o["total_sell_amount"] / duration

    # Collect all boundary blocks
    boundaries = set()
    for o in active_orders:
        boundaries.add(o["start_block"])
        boundaries.add(o["end_block"])
    boundaries = sorted(boundaries)

    # Track received tokens for each order
    received = defaultdict(float)

    # Process each interval between boundaries
    for i in range(len(boundaries) - 1):
        t_start = boundaries[i]
        t_end = boundaries[i + 1]
        dt = t_end - t_start

        if dt <= 0:
            continue

        # Find active orders in this interval
        active_x = []  # orders selling X
        active_y = []  # orders selling Y
        for o in active_orders:
            if o["start_block"] <= t_start and o["end_block"] >= t_end:
                r = rates[o["id"]]
                if o["sell_token"] == "x":
                    active_x.append((o["id"], r))
                else:
                    active_y.append((o["id"], r))

        x_rate = sum(r for _, r in active_x)
        y_rate = sum(r for _, r in active_y)

        if x_rate <= 0 and y_rate <= 0:
            continue

        # Compute TWAMM math for this interval
        x_before = x_amm
        y_before = y_amm
        x_amm, y_amm = twamm_interval(x_before, y_before, x_rate, y_rate, dt)

        # Compute total outputs
        # X flowing to Y-sellers: x_before + x_sold - x_amm
        total_x_sold = x_rate * dt
        total_y_sold = y_rate * dt
        x_output = x_before + total_x_sold - x_amm  # goes to Y sellers
        y_output = y_before + total_y_sold - y_amm  # goes to X sellers

        # Distribute proportionally within pools
        if y_rate > 0 and x_output > 0:
            for oid, r in active_y:
                share = r / y_rate
                received[oid] += share * x_output

        if x_rate > 0 and y_output > 0:
            for oid, r in active_x:
                share = r / x_rate
                received[oid] += share * y_output

    # Build result
    order_fills = {}
    for o in active_orders:
        order_fills[o["id"]] = {"received": received.get(o["id"], 0.0)}
    for o in zero_orders:
        order_fills[o["id"]] = {"received": 0.0}

    return {
        "final_reserves": {"x": x_amm, "y": y_amm},
        "order_fills": order_fills,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 twamm.py <scenario.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        scenario = json.load(f)

    result = simulate(scenario)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
