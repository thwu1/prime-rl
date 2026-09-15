#!/usr/bin/env python3
"""
TWAMM Engine — Reference Solution

Reads scenario data from SQLite, uses the compiled C library (libcpamm.so)
for all AMM pool state management, and implements the closed-form TWAMM
virtual-trade mathematics.

"""

import ctypes
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Load C library
# ---------------------------------------------------------------------------
_LIB_SEARCH = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "libcpamm.so"),
    "/app/lib/libcpamm.so",
]
_lib = None
for _p in _LIB_SEARCH:
    if os.path.isfile(_p):
        _lib = ctypes.CDLL(_p)
        break
if _lib is None:
    raise RuntimeError("libcpamm.so not found — compile with 'make -C /app/lib'")

# Function signatures
_lib.cpamm_create.restype = ctypes.c_void_p
_lib.cpamm_create.argtypes = [ctypes.c_double, ctypes.c_double]

_lib.cpamm_free.restype = None
_lib.cpamm_free.argtypes = [ctypes.c_void_p]

_lib.cpamm_get_x.restype = ctypes.c_double
_lib.cpamm_get_x.argtypes = [ctypes.c_void_p]

_lib.cpamm_get_y.restype = ctypes.c_double
_lib.cpamm_get_y.argtypes = [ctypes.c_void_p]

_lib.cpamm_get_k.restype = ctypes.c_double
_lib.cpamm_get_k.argtypes = [ctypes.c_void_p]

_lib.cpamm_set_reserves.restype = ctypes.c_int
_lib.cpamm_set_reserves.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]

_lib.cpamm_spot_price.restype = ctypes.c_double
_lib.cpamm_spot_price.argtypes = [ctypes.c_void_p]


# ---------------------------------------------------------------------------
# TWAMM interval math
# ---------------------------------------------------------------------------
def twamm_interval(pool, x_rate, y_rate, t):
    """
    Compute AMM reserves after t blocks of continuous two-sided virtual
    trading and update the C pool handle accordingly.

    The embedded CPAMM satisfies x*y = K (no fees).

    Derivation:
        dx/dt = x_rate - (y_rate / K) * x^2   (Riccati ODE)
        Equilibrium:  alpha = sqrt(x_rate * K / y_rate)
        Rate param:   theta = sqrt(x_rate * y_rate / K)

        x0 < alpha  =>  x(t) = alpha * tanh(theta*t + atanh(x0/alpha))
        x0 > alpha  =>  x(t) = alpha / tanh(theta*t + atanh(alpha/x0))
        x0 = alpha  =>  x(t) = alpha  (equilibrium)
    """
    x0 = _lib.cpamm_get_x(pool)
    y0 = _lib.cpamm_get_y(pool)
    K = _lib.cpamm_get_k(pool)

    if t <= 0 or (x_rate <= 0 and y_rate <= 0):
        return x0, y0

    # Single-sided cases
    if y_rate <= 0:
        x_final = x0 + x_rate * t
        y_final = K / x_final
    elif x_rate <= 0:
        y_final = y0 + y_rate * t
        x_final = K / y_final
    else:
        # Two-sided case
        alpha = math.sqrt(x_rate * K / y_rate)
        theta = math.sqrt(x_rate * y_rate / K)
        ratio = x0 / alpha

        if abs(ratio - 1.0) < 1e-15:
            x_final = alpha
            y_final = K / alpha
        elif ratio < 1.0:
            u0 = math.atanh(ratio)
            x_final = alpha * math.tanh(theta * t + u0)
            y_final = K / x_final
        else:
            u0 = math.atanh(1.0 / ratio)
            x_final = alpha / math.tanh(theta * t + u0)
            y_final = K / x_final

    rc = _lib.cpamm_set_reserves(pool, ctypes.c_double(x_final),
                                  ctypes.c_double(y_final))
    if rc != 0:
        raise RuntimeError(
            f"cpamm_set_reserves failed (code {rc}): "
            f"new_x={x_final}, new_y={y_final}, k={K}"
        )
    return x_final, y_final


# ---------------------------------------------------------------------------
# Simulation driver
# ---------------------------------------------------------------------------
def simulate(scenario_id, db_path="/app/data/twamm.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Read pool initial reserves
    row = conn.execute(
        "SELECT p.initial_x, p.initial_y "
        "FROM scenarios s JOIN pools p ON s.pool_id = p.pool_id "
        "WHERE s.scenario_id = ?", (scenario_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Scenario '{scenario_id}' not found")
    x_init, y_init = row["initial_x"], row["initial_y"]

    # Read orders
    rows = conn.execute(
        "SELECT order_id, sell_token, total_sell_amount, start_block, end_block "
        "FROM orders WHERE scenario_id = ?", (scenario_id,)
    ).fetchall()
    conn.close()

    orders = [dict(r) for r in rows]

    # Create C pool handle
    pool = _lib.cpamm_create(ctypes.c_double(x_init), ctypes.c_double(y_init))
    if not pool:
        raise RuntimeError("cpamm_create returned NULL")

    try:
        # Separate zero-duration orders
        active_orders = []
        zero_orders = []
        for o in orders:
            if o["end_block"] <= o["start_block"]:
                zero_orders.append(o)
            else:
                active_orders.append(o)

        # Compute per-order sell rates
        rates = {}
        for o in active_orders:
            duration = o["end_block"] - o["start_block"]
            rates[o["order_id"]] = o["total_sell_amount"] / duration

        # Collect all boundary blocks
        boundaries = set()
        for o in active_orders:
            boundaries.add(o["start_block"])
            boundaries.add(o["end_block"])
        boundaries = sorted(boundaries)

        received = defaultdict(float)

        # Process each interval
        for i in range(len(boundaries) - 1):
            t_start = boundaries[i]
            t_end = boundaries[i + 1]
            dt = t_end - t_start
            if dt <= 0:
                continue

            active_x = []  # (order_id, rate) for X-sellers
            active_y = []  # (order_id, rate) for Y-sellers
            for o in active_orders:
                if o["start_block"] <= t_start and o["end_block"] >= t_end:
                    r = rates[o["order_id"]]
                    if o["sell_token"] == "x":
                        active_x.append((o["order_id"], r))
                    else:
                        active_y.append((o["order_id"], r))

            x_rate = sum(r for _, r in active_x)
            y_rate = sum(r for _, r in active_y)

            if x_rate <= 0 and y_rate <= 0:
                continue

            x_before = _lib.cpamm_get_x(pool)
            y_before = _lib.cpamm_get_y(pool)

            x_final, y_final = twamm_interval(pool, x_rate, y_rate, dt)

            total_x_sold = x_rate * dt
            total_y_sold = y_rate * dt
            x_output = x_before + total_x_sold - x_final  # goes to Y-sellers
            y_output = y_before + total_y_sold - y_final  # goes to X-sellers

            if y_rate > 0 and x_output > 0:
                for oid, r in active_y:
                    received[oid] += (r / y_rate) * x_output

            if x_rate > 0 and y_output > 0:
                for oid, r in active_x:
                    received[oid] += (r / x_rate) * y_output

        x_amm = _lib.cpamm_get_x(pool)
        y_amm = _lib.cpamm_get_y(pool)

        order_fills = {}
        for o in active_orders:
            order_fills[o["order_id"]] = {
                "received": received.get(o["order_id"], 0.0)
            }
        for o in zero_orders:
            order_fills[o["order_id"]] = {"received": 0.0}

        return {
            "final_reserves": {"x": x_amm, "y": y_amm},
            "order_fills": order_fills,
        }
    finally:
        _lib.cpamm_free(pool)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 twamm_engine.py <scenario_id>", file=sys.stderr)
        sys.exit(1)
    result = simulate(sys.argv[1])
    print(json.dumps(result))


if __name__ == "__main__":
    main()
