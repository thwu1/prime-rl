#!/usr/bin/env python3
"""Generate synthetic options quote data for benchmark task."""
import struct
import sqlite3
import math
import os
import random

MASTER_SEED = 42

# Market parameters
F = 5250.0
r = 0.043
T_DAYS = 30
T = T_DAYS / 365.0
SENTINEL = (1 << 63) - 1
PRICE_SCALE = 1_000_000_000

STRIKES = [5000, 5050, 5100, 5150, 5200, 5250, 5300, 5350, 5400, 5450, 5500]

# Instruments with sentinel bids on exchange 3
SENTINEL_BID_INSTS = {3, 7, 15, 21}

# Strikes where put prices are artificially shifted (parity violations)
PARITY_VIOLATION_STRIKES = {5100, 5350}
PARITY_SHIFT = 3.5

EXCHANGES = [
    (1, "CBOE", "XCBO"),
    (2, "ISE", "XISX"),
    (3, "PHLX", "XPHL"),
]


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def vol_smile(K):
    """Quadratic volatility smile centered at ATM."""
    m = math.log(K / F)
    return 0.18 + 5.0 * m * m


def black76_price(K, sigma, is_call):
    """Black-76 option price."""
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    disc = math.exp(-r * T)
    if is_call:
        return disc * (F * norm_cdf(d1) - K * norm_cdf(d2))
    else:
        return disc * (K * norm_cdf(-d2) - F * norm_cdf(-d1))


def main():
    os.makedirs("/app/data", exist_ok=True)

    # Generate instrument definitions
    instruments = []
    inst_id = 1
    for K in STRIKES:
        sigma = vol_smile(K)
        for opt_type in ["C", "P"]:
            is_call = opt_type == "C"
            price = black76_price(K, sigma, is_call)
            instruments.append({
                "instrument_id": inst_id,
                "symbol": "ESM4 %s%d" % (opt_type, K),
                "strike": K,
                "expiry_days": T_DAYS,
                "option_type": opt_type,
                "underlying": "ESM4",
                "contract_type": "futures_option",
                "true_price": price,
            })
            inst_id += 1

    # Write SQLite reference database
    db_path = "/app/data/reference.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE instruments (
        instrument_id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        strike REAL NOT NULL,
        expiry_days INTEGER NOT NULL,
        option_type TEXT NOT NULL,
        underlying TEXT NOT NULL,
        contract_type TEXT NOT NULL
    )""")

    cur.execute("""CREATE TABLE exchanges (
        exchange_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        mic TEXT NOT NULL
    )""")

    for inst in instruments:
        cur.execute(
            "INSERT INTO instruments VALUES (?, ?, ?, ?, ?, ?, ?)",
            (inst["instrument_id"], inst["symbol"], inst["strike"],
             inst["expiry_days"], inst["option_type"], inst["underlying"],
             inst["contract_type"])
        )

    for eid, name, mic in EXCHANGES:
        cur.execute("INSERT INTO exchanges VALUES (?, ?, ?)", (eid, name, mic))

    conn.commit()
    conn.close()

    # Generate quote messages
    messages = []
    base_ts = 1712242800_000_000_000  # 2024-04-04T17:00:00Z
    seq = 0

    for inst in instruments:
        for exch_id in [1, 2, 3]:
            rng = random.Random(MASTER_SEED + inst["instrument_id"] * 100 + exch_id)
            noise = rng.uniform(-0.15, 0.15)

            price = inst["true_price"] + noise

            # Parity violation: shift put prices at selected strikes
            if (inst["strike"] in PARITY_VIOLATION_STRIKES
                    and inst["option_type"] == "P"):
                price += PARITY_SHIFT

            spread = max(0.50, price * 0.008)
            bid = max(0.10, price - spread / 2)
            ask = price + spread / 2

            bid_fp = int(round(bid * PRICE_SCALE))
            ask_fp = int(round(ask * PRICE_SCALE))

            # Sentinel bids for specific instruments on exchange 3
            if (inst["instrument_id"] in SENTINEL_BID_INSTS
                    and exch_id == 3):
                bid_fp = SENTINEL

            ts_event = base_ts + seq * 1_000_000

            msg = {
                "instrument_id": inst["instrument_id"],
                "exchange_id": exch_id,
                "channel_id": seq % 2,
                "msg_flags": 0,
                "ts_event": ts_event,
                "bid_px": bid_fp,
                "ask_px": ask_fp,
                "bid_sz": rng.randint(5, 200),
                "ask_sz": rng.randint(5, 200),
                "sequence": seq,
            }
            messages.append(msg)
            seq += 1

            # Duplicate ~30% on the other channel
            if rng.random() < 0.3:
                dup = msg.copy()
                dup["channel_id"] = 1 - msg["channel_id"]
                dup["ts_event"] = msg["ts_event"] + rng.randint(100, 5000)
                dup["msg_flags"] = 1
                messages.append(dup)

    # Heartbeat messages (instrument_id = 0)
    for i in range(10):
        messages.append({
            "instrument_id": 0,
            "exchange_id": 0,
            "channel_id": 0,
            "msg_flags": 0,
            "ts_event": base_ts + (seq + i) * 1_000_000,
            "bid_px": 0,
            "ask_px": 0,
            "bid_sz": 0,
            "ask_sz": 0,
            "sequence": seq + i,
        })

    # Write binary file
    RECORD_FMT = "<IBBHqqqIIII"
    HEADER_FMT = "<4sIII"

    with open("/app/data/quotes.bin", "wb") as f:
        f.write(struct.pack(HEADER_FMT, b"OPTQ", 1, len(messages), 0))
        for msg in messages:
            f.write(struct.pack(
                RECORD_FMT,
                msg["instrument_id"],
                msg["exchange_id"],
                msg["channel_id"],
                msg["msg_flags"],
                msg["ts_event"],
                msg["bid_px"],
                msg["ask_px"],
                msg["bid_sz"],
                msg["ask_sz"],
                msg["sequence"],
                0,
            ))

    # Write TOML config
    with open("/app/data/config.toml", "w") as f:
        f.write(CONFIG_TOML)

    # Write format specification
    with open("/app/data/format_spec.md", "w") as f:
        f.write(FORMAT_SPEC)

    print("Generated %d records for %d instruments" % (len(messages), len(instruments)))


CONFIG_TOML = """\
[market]
futures_price = 5250.0
risk_free_rate = 0.043

[conventions]
time_to_expiry = "calendar_days / 365"
trading_days_per_year = 252
theta_basis = "per_trading_day"
vega_basis = "per_percentage_point"
rho_basis = "per_percentage_point"

[arbitrage]
parity_violation_threshold = 2.0

[output]
database_path = "/app/output/results.db"
"""


FORMAT_SPEC = r"""# Binary Quote Format Specification (OPTQ v1)

## Overview

This file describes the binary format of `quotes.bin`, which contains options
quote messages from multiple exchanges distributed across redundant channels.

## Byte Order

All multi-byte fields are **little-endian**.

## File Header (16 bytes)

| Offset | Size | Type      | Description          |
|--------|------|-----------|----------------------|
| 0      | 4    | char[4]   | Magic: `OPTQ`        |
| 4      | 4    | uint32    | Version (= 1)        |
| 8      | 4    | uint32    | Number of records     |
| 12     | 4    | uint32    | Reserved (= 0)       |

## Record Format (48 bytes each)

| Offset | Size | Type   | Field         | Description |
|--------|------|--------|---------------|-------------|
| 0      | 4    | uint32 | instrument_id | Instrument identifier. **0 = heartbeat** (skip). |
| 4      | 1    | uint8  | exchange_id   | Source exchange identifier (1-18). |
| 5      | 1    | uint8  | channel_id    | Distribution channel (0 or 1). |
| 6      | 2    | uint16 | msg_flags     | Bit flags (see below). |
| 8      | 8    | int64  | ts_event      | Event timestamp in nanoseconds since Unix epoch. |
| 16     | 8    | int64  | bid_px        | Bid price, fixed-point. Divide by 1,000,000,000. |
| 24     | 8    | int64  | ask_px        | Ask price, fixed-point. Divide by 1,000,000,000. |
| 32     | 4    | uint32 | bid_sz        | Bid size in contracts. |
| 36     | 4    | uint32 | ask_sz        | Ask size in contracts. |
| 40     | 4    | uint32 | sequence      | Per-message sequence number. |
| 44     | 4    | uint32 | reserved      | Reserved (= 0). |

## Message Flags (msg_flags)

| Bit | Name       | Meaning |
|-----|------------|---------|
| 0   | F_DUPLICATE | Set when this message may be a duplicate from another channel. |

## Sentinel Values

A price field equal to `0x7FFFFFFFFFFFFFFF` (= 9223372036854775807, i.e. INT64_MAX)
means **no price available** on that side.

- If **both** bid and ask are sentinels, ignore the entire record.
- If only **one** side is a sentinel, the record is a **one-sided quote**.
  The valid side still participates in NBBO computation.

## Deduplication

Quotes are broadcast on two channels for redundancy. Two records are duplicates
if they share the same `(instrument_id, exchange_id, sequence)` tuple. When
duplicates exist, **keep only the record with the earliest `ts_event`**.

## NBBO (National Best Bid and Offer)

After deduplication and filtering, compute the NBBO for each instrument:

- **NBBO bid** = the highest valid (non-sentinel) bid across all exchanges.
- **NBBO ask** = the lowest valid (non-sentinel) ask across all exchanges.
- **NBBO mid** = (NBBO bid + NBBO ask) / 2.

Only exchanges with a valid price on the relevant side contribute.
"""


if __name__ == "__main__":
    main()
