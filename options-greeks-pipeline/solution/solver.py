#!/usr/bin/env python3
"""Solution: Futures options analytics pipeline."""

import struct
import sqlite3
import tomllib
import math
import os
from collections import defaultdict

SENTINEL = (1 << 63) - 1
PRICE_SCALE = 1_000_000_000
DATA_DIR = "/app/data"


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black76_price(F, K, T, sigma, r, is_call):
    """Black-76 option pricing model for futures options."""
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    disc = math.exp(-r * T)
    if is_call:
        return disc * (F * norm_cdf(d1) - K * norm_cdf(d2))
    else:
        return disc * (K * norm_cdf(-d2) - F * norm_cdf(-d1))


def implied_vol(F, K, T, r, is_call, market_price, tol=1e-10, max_iter=100):
    """Compute implied volatility using bisection on Black-76."""
    lo, hi = 0.001, 5.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        price = black76_price(F, K, T, mid, r, is_call)
        if price < market_price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2.0


def compute_greeks(F, K, T, sigma, r, is_call, trading_days):
    """Compute all five Black-76 Greeks with convention scaling."""
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    disc = math.exp(-r * T)
    npd1 = norm_pdf(d1)

    # Delta
    if is_call:
        delta = disc * norm_cdf(d1)
    else:
        delta = -disc * norm_cdf(-d1)

    # Gamma (same for calls and puts)
    gamma = disc * npd1 / (F * sigma * sqrt_T)

    # Theta per trading day
    common_term = -F * disc * sigma * npd1 / (2.0 * sqrt_T)
    if is_call:
        theta_annual = common_term + r * disc * (F * norm_cdf(d1) - K * norm_cdf(d2))
    else:
        theta_annual = common_term + r * disc * (K * norm_cdf(-d2) - F * norm_cdf(-d1))
    theta = theta_annual / trading_days

    # Vega per 1 percentage point
    vega = F * disc * npd1 * sqrt_T / 100.0

    # Rho per 1 percentage point: rho = -T * V / 100
    if is_call:
        price = disc * (F * norm_cdf(d1) - K * norm_cdf(d2))
    else:
        price = disc * (K * norm_cdf(-d2) - F * norm_cdf(-d1))
    rho = -T * price / 100.0

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}


def main():
    # Load TOML config
    with open(os.path.join(DATA_DIR, "config.toml"), "rb") as f:
        config = tomllib.load(f)

    F = config["market"]["futures_price"]
    r = config["market"]["risk_free_rate"]
    trading_days = config["conventions"]["trading_days_per_year"]
    threshold = config["arbitrage"]["parity_violation_threshold"]
    output_db_path = config["output"]["database_path"]

    # Load definitions from SQLite reference database
    ref_conn = sqlite3.connect(os.path.join(DATA_DIR, "reference.db"))
    ref_conn.row_factory = sqlite3.Row
    defs = {}
    for row in ref_conn.execute("SELECT * FROM instruments"):
        defs[row["instrument_id"]] = dict(row)
    ref_conn.close()

    # Parse binary quotes
    records = []
    bin_path = os.path.join(DATA_DIR, "quotes.bin")
    header_fmt = "<4sIII"
    record_fmt = "<IBBHqqqIIII"

    with open(bin_path, "rb") as f:
        header = struct.unpack(header_fmt, f.read(struct.calcsize(header_fmt)))
        magic, version, num_records, _ = header
        assert magic == b"OPTQ", "Invalid magic bytes"

        rec_size = struct.calcsize(record_fmt)
        for _ in range(num_records):
            fields = struct.unpack(record_fmt, f.read(rec_size))
            records.append({
                "instrument_id": fields[0],
                "exchange_id": fields[1],
                "channel_id": fields[2],
                "msg_flags": fields[3],
                "ts_event": fields[4],
                "bid_px": fields[5],
                "ask_px": fields[6],
                "bid_sz": fields[7],
                "ask_sz": fields[8],
                "sequence": fields[9],
            })

    # Filter heartbeats (instrument_id == 0)
    records = [rec for rec in records if rec["instrument_id"] != 0]

    # Filter records where both bid and ask are sentinels
    records = [rec for rec in records
               if not (rec["bid_px"] == SENTINEL and rec["ask_px"] == SENTINEL)]

    # Deduplicate by (instrument_id, exchange_id, sequence), keep earliest ts_event
    dedup = {}
    for rec in records:
        key = (rec["instrument_id"], rec["exchange_id"], rec["sequence"])
        if key not in dedup or rec["ts_event"] < dedup[key]["ts_event"]:
            dedup[key] = rec
    records = list(dedup.values())

    # Group by instrument
    inst_quotes = defaultdict(list)
    for rec in records:
        inst_quotes[rec["instrument_id"]].append(rec)

    # Create output directory and database
    os.makedirs(os.path.dirname(output_db_path), exist_ok=True)
    if os.path.exists(output_db_path):
        os.remove(output_db_path)
    out_conn = sqlite3.connect(output_db_path)
    out_cur = out_conn.cursor()

    # Create output tables
    out_cur.execute("""CREATE TABLE nbbo (
        instrument_id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        nbbo_bid REAL NOT NULL,
        nbbo_ask REAL NOT NULL,
        nbbo_mid REAL NOT NULL
    )""")

    out_cur.execute("""CREATE TABLE implied_volatility (
        instrument_id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        strike REAL NOT NULL,
        option_type TEXT NOT NULL,
        implied_vol REAL NOT NULL
    )""")

    out_cur.execute("""CREATE TABLE greeks (
        instrument_id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        delta REAL NOT NULL,
        gamma REAL NOT NULL,
        theta REAL NOT NULL,
        vega REAL NOT NULL,
        rho REAL NOT NULL
    )""")

    out_cur.execute("""CREATE TABLE parity_violations (
        strike REAL NOT NULL,
        call_mid REAL NOT NULL,
        put_mid REAL NOT NULL,
        theoretical_diff REAL NOT NULL,
        actual_diff REAL NOT NULL,
        violation_amount REAL NOT NULL
    )""")

    # Compute NBBO
    nbbo_results = {}
    for inst_id in sorted(defs.keys()):
        quotes = inst_quotes.get(inst_id, [])
        valid_bids = [q["bid_px"] / PRICE_SCALE for q in quotes
                      if q["bid_px"] != SENTINEL]
        valid_asks = [q["ask_px"] / PRICE_SCALE for q in quotes
                      if q["ask_px"] != SENTINEL]
        if valid_bids and valid_asks:
            best_bid = max(valid_bids)
            best_ask = min(valid_asks)
            mid = (best_bid + best_ask) / 2.0
            nbbo_results[inst_id] = {
                "nbbo_bid": best_bid,
                "nbbo_ask": best_ask,
                "nbbo_mid": mid,
            }
            out_cur.execute(
                "INSERT INTO nbbo VALUES (?, ?, ?, ?, ?)",
                (inst_id, defs[inst_id]["symbol"], best_bid, best_ask, mid)
            )

    # Compute implied volatility
    iv_results = {}
    for inst_id in sorted(defs.keys()):
        if inst_id not in nbbo_results:
            continue
        defn = defs[inst_id]
        T = defn["expiry_days"] / 365.0
        K = defn["strike"]
        is_call = defn["option_type"] == "C"
        mid = nbbo_results[inst_id]["nbbo_mid"]

        iv = implied_vol(F, K, T, r, is_call, mid)
        iv_results[inst_id] = iv
        out_cur.execute(
            "INSERT INTO implied_volatility VALUES (?, ?, ?, ?, ?)",
            (inst_id, defn["symbol"], K, defn["option_type"], iv)
        )

    # Compute Greeks
    for inst_id in sorted(defs.keys()):
        if inst_id not in iv_results:
            continue
        defn = defs[inst_id]
        T = defn["expiry_days"] / 365.0
        K = defn["strike"]
        is_call = defn["option_type"] == "C"
        sigma = iv_results[inst_id]

        g = compute_greeks(F, K, T, sigma, r, is_call, trading_days)
        out_cur.execute(
            "INSERT INTO greeks VALUES (?, ?, ?, ?, ?, ?, ?)",
            (inst_id, defn["symbol"], g["delta"], g["gamma"],
             g["theta"], g["vega"], g["rho"])
        )

    # Put-call parity violations
    by_strike = defaultdict(dict)
    for inst_id, defn in defs.items():
        if inst_id in nbbo_results:
            by_strike[defn["strike"]][defn["option_type"]] = inst_id

    for strike in sorted(by_strike.keys()):
        types = by_strike[strike]
        if "C" in types and "P" in types:
            T = defs[types["C"]]["expiry_days"] / 365.0
            call_mid = nbbo_results[types["C"]]["nbbo_mid"]
            put_mid = nbbo_results[types["P"]]["nbbo_mid"]
            theoretical = math.exp(-r * T) * (F - strike)
            actual = call_mid - put_mid
            violation = abs(actual - theoretical)
            if violation > threshold:
                out_cur.execute(
                    "INSERT INTO parity_violations VALUES (?, ?, ?, ?, ?, ?)",
                    (strike, call_mid, put_mid, theoretical, actual, violation)
                )

    out_conn.commit()
    out_conn.close()
    print("Pipeline complete. Results written to %s" % output_db_path)


if __name__ == "__main__":
    main()
