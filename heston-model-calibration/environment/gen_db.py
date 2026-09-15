#!/usr/bin/env python3
"""Generate the options.db SQLite database for the Heston calibration task.

Uses pure Python (no numpy) to implement the Heston characteristic function
and COS Fourier cosine expansion method for European option pricing.
"""

import sqlite3
import cmath
import math
import random

# True Heston parameters (for clean feeds: reuters_eikon, bloomberg_bpipe)
KAPPA_TRUE = 1.5
GAMMA_TRUE = 0.4
VBAR_TRUE = 0.04
V0_TRUE = 0.04
RHO_TRUE = -0.7

# Anomalous Heston parameters (for darkpool_composite)
KAPPA_ANOM = 0.5
GAMMA_ANOM = 0.8
VBAR_ANOM = 0.09
V0_ANOM = 0.06
RHO_ANOM = -0.3

S0 = 100.0
R = 0.05

MATURITIES = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0]
STRIKES = [70.0, 75.0, 80.0, 85.0, 90.0, 95.0, 100.0,
           105.0, 110.0, 115.0, 120.0, 125.0, 130.0]


def heston_cf(u_list, r, tau, kappa, gamma, vbar, v0, rho):
    """Heston characteristic function of log(S_T / S_0) — pure Python."""
    results = []
    j = complex(0, 1)
    for u_val in u_list:
        u = complex(u_val, 0) if isinstance(u_val, (int, float)) else u_val
        a1 = kappa - gamma * rho * j * u
        D = cmath.sqrt(a1 ** 2 + gamma ** 2 * (u ** 2 + j * u))
        g = (a1 - D) / (a1 + D)
        exp_neg = cmath.exp(-D * tau)
        C = (a1 - D) / (gamma ** 2) * (1.0 - exp_neg) / (1.0 - g * exp_neg)
        A = (r * j * u * tau
             + kappa * vbar / (gamma ** 2)
             * ((a1 - D) * tau
                - 2.0 * cmath.log((1.0 - g * exp_neg) / (1.0 - g))))
        results.append(cmath.exp(A + C * v0))
    return results


def cos_call_prices(S0, r, tau, strikes, kappa, gamma, vbar, v0, rho,
                    N=500, L=8):
    """COS method for European call prices via put-call parity — pure Python."""
    a = -L * math.sqrt(tau)
    b = L * math.sqrt(tau)
    ba = b - a

    # Precompute all u_k values and their characteristic function values
    u_vals = [k * math.pi / ba for k in range(N)]
    cf_vals = heston_cf(u_vals, r, tau, kappa, gamma, vbar, v0, rho)

    # Precompute H_k coefficients (put payoff expansion)
    c_int = a
    d_int = 0.0
    H_arr = []
    for k_idx in range(N):
        kpi_ba = k_idx * math.pi / ba
        denom = 1.0 + kpi_ba ** 2

        cos_d = math.cos(kpi_ba * (d_int - a))
        cos_c = math.cos(kpi_ba * (c_int - a))
        sin_d = math.sin(kpi_ba * (d_int - a))
        sin_c = math.sin(kpi_ba * (c_int - a))
        exp_d = math.exp(d_int)
        exp_c = math.exp(c_int)

        chi_k = (cos_d * exp_d - cos_c * exp_c
                 + kpi_ba * (sin_d * exp_d - sin_c * exp_c)) / denom

        if k_idx == 0:
            psi_k = d_int - c_int
        else:
            psi_k = (sin_d - sin_c) * ba / (k_idx * math.pi)

        H_arr.append(2.0 / ba * (-chi_k + psi_k))

    # Price each strike
    disc = math.exp(-r * tau)
    prices = []
    for K in strikes:
        x0 = math.log(S0 / K)
        put_val = 0.0
        for k_idx in range(N):
            mat = cmath.exp(complex(0, 1) * (x0 - a) * u_vals[k_idx])
            term = cf_vals[k_idx] * H_arr[k_idx]
            if k_idx == 0:
                term *= 0.5
            put_val += (mat * term).real

        put_price = disc * K * put_val
        call_price = put_price + S0 - K * disc
        prices.append(max(call_price, 0.0))

    return prices


def main():
    conn = sqlite3.connect("/app/options.db")
    cur = conn.cursor()

    # Create schema
    cur.execute("""CREATE TABLE market_config (
        param_name TEXT PRIMARY KEY,
        param_value REAL NOT NULL
    )""")

    cur.execute("""CREATE TABLE feeds (
        feed_id INTEGER PRIMARY KEY,
        feed_name TEXT UNIQUE NOT NULL
    )""")

    cur.execute("""CREATE TABLE instruments (
        instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
        expiry REAL NOT NULL,
        strike REAL NOT NULL
    )""")

    cur.execute("""CREATE TABLE price_observations (
        obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
        feed_id INTEGER NOT NULL,
        instrument_id INTEGER NOT NULL,
        px REAL NOT NULL,
        FOREIGN KEY (feed_id) REFERENCES feeds(feed_id),
        FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
    )""")

    cur.execute("""CREATE TABLE quality_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        feed_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        severity TEXT NOT NULL,
        FOREIGN KEY (feed_id) REFERENCES feeds(feed_id)
    )""")

    # Market configuration
    cur.execute("INSERT INTO market_config VALUES (?, ?)", ("spot_price", S0))
    cur.execute("INSERT INTO market_config VALUES (?, ?)", ("risk_free_rate", R))

    # Feed definitions
    cur.execute("INSERT INTO feeds VALUES (?, ?)", (1, "reuters_eikon"))
    cur.execute("INSERT INTO feeds VALUES (?, ?)", (2, "bloomberg_bpipe"))
    cur.execute("INSERT INTO feeds VALUES (?, ?)", (3, "darkpool_composite"))

    # Instruments (maturity x strike grid)
    inst_map = {}
    iid = 0
    for T in MATURITIES:
        for K in STRIKES:
            iid += 1
            cur.execute("INSERT INTO instruments VALUES (?, ?, ?)", (iid, T, K))
            inst_map[(T, K)] = iid

    # Generate option prices from true Heston parameters
    true_prices = {}
    for T in MATURITIES:
        true_prices[T] = cos_call_prices(
            S0, R, T, STRIKES,
            KAPPA_TRUE, GAMMA_TRUE, VBAR_TRUE, V0_TRUE, RHO_TRUE,
            N=500, L=8
        )

    # Generate anomalous prices from different Heston parameters
    anom_prices = {}
    for T in MATURITIES:
        anom_prices[T] = cos_call_prices(
            S0, R, T, STRIKES,
            KAPPA_ANOM, GAMMA_ANOM, VBAR_ANOM, V0_ANOM, RHO_ANOM,
            N=500, L=8
        )

    # Insert price observations
    # reuters_eikon: exact true prices (clean)
    # bloomberg_bpipe: true prices with tiny noise (clean)
    # darkpool_composite: anomalous prices (different model)
    random.seed(42)
    for T in MATURITIES:
        for j, K in enumerate(STRIKES):
            inst = inst_map[(T, K)]
            base = true_prices[T][j]

            # reuters_eikon — exact
            cur.execute(
                "INSERT INTO price_observations (feed_id, instrument_id, px) "
                "VALUES (?, ?, ?)",
                (1, inst, round(base, 6))
            )

            # bloomberg_bpipe — tiny multiplicative noise (0.05% std dev)
            noise = random.gauss(0, 0.0005) * base
            px_bb = max(base + noise, 0.0)
            cur.execute(
                "INSERT INTO price_observations (feed_id, instrument_id, px) "
                "VALUES (?, ?, ?)",
                (2, inst, round(px_bb, 6))
            )

            # darkpool_composite — anomalous model
            cur.execute(
                "INSERT INTO price_observations (feed_id, instrument_id, px) "
                "VALUES (?, ?, ?)",
                (3, inst, round(anom_prices[T][j], 6))
            )

    # Quality log entries (hints, not answers)
    cur.execute(
        "INSERT INTO quality_log (feed_id, message, severity) VALUES (?, ?, ?)",
        (1, "Daily reconciliation passed", "info")
    )
    cur.execute(
        "INSERT INTO quality_log (feed_id, message, severity) VALUES (?, ?, ?)",
        (2, "Daily reconciliation passed", "info")
    )
    cur.execute(
        "INSERT INTO quality_log (feed_id, message, severity) VALUES (?, ?, ?)",
        (3, "Settlement latency exceeds threshold on 12 instruments", "warning")
    )
    cur.execute(
        "INSERT INTO quality_log (feed_id, message, severity) VALUES (?, ?, ?)",
        (3, "Price source flagged as model-derived for OTM contracts", "warning")
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
