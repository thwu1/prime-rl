#!/usr/bin/env python3
"""Generate deterministic synthetic L2 market data for the fill simulation task."""
import numpy as np
import json

event_dtype = np.dtype([
    ('ev', 'u8'),
    ('exch_ts', 'i8'),
    ('local_ts', 'i8'),
    ('px', 'f8'),
    ('qty', 'f8'),
    ('order_id', 'u8'),
    ('ival', 'i8'),
    ('fval', 'f8')
])

# Event type flags
DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_SNAPSHOT_EVENT = 4
EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28

tick_size = 1.0
lot_size = 1.0
latency_ns = 5_000_000  # 5ms

T0 = 1_000_000_000_000  # base timestamp in nanoseconds
S = 1_000_000_000       # 1 second in nanoseconds


def mk(ts_offset, flags, px, qty):
    t = T0 + ts_offset
    return (flags, t, t + latency_ns, float(px), float(qty), 0, 0, 0.0)


events = []

# ---- Initial snapshot at T0 ----
SB = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
SS = DEPTH_SNAPSHOT_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT

for px, qty in [(99, 20), (98, 50), (97, 60), (96, 40), (95, 30)]:
    events.append(mk(0, SB, px, qty))
for px, qty in [(101, 25), (102, 45), (103, 50), (104, 35), (105, 20)]:
    events.append(mk(0, SS, px, qty))

# ---- Phase 1: Activity at bid level 99 ----
TS = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT   # sell aggressor
DB = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT    # bid-side depth

events.append(mk(1 * S, TS, 99, 5))     # sell trade at 99 qty=5
events.append(mk(2 * S, DB, 99, 40))    # bid 99 depth -> 40 (new orders arrive)
events.append(mk(3 * S, TS, 99, 2))     # sell trade at 99 qty=2
events.append(mk(4 * S, DB, 99, 20))    # bid 99 depth -> 20 (cancellations)
events.append(mk(5 * S, TS, 99, 12))    # sell trade at 99 qty=12
events.append(mk(6 * S, TS, 99, 3))     # sell trade at 99 qty=3
events.append(mk(7 * S, TS, 99, 5))     # sell trade at 99 qty=5
events.append(mk(8 * S, DB, 99, 0))     # bid 99 cleared

# ---- Phase 2: Activity at ask level 101 ----
TB = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT    # buy aggressor
DS = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT   # ask-side depth

events.append(mk(9 * S, TB, 101, 8))    # buy trade at 101 qty=8
events.append(mk(10 * S, DS, 101, 35))  # ask 101 depth -> 35 (new orders)
events.append(mk(11 * S, TB, 101, 3))   # buy trade at 101 qty=3
events.append(mk(12 * S, DS, 101, 15))  # ask 101 depth -> 15 (cancellations)
events.append(mk(13 * S, TB, 101, 10))  # buy trade at 101 qty=10
events.append(mk(14 * S, TB, 101, 8))   # buy trade at 101 qty=8
events.append(mk(15 * S, DS, 101, 0))   # ask 101 cleared

# ---- Phase 3: Activity at bid level 98 ----
events.append(mk(16 * S, TS, 98, 20))   # sell trade at 98 qty=20
events.append(mk(17 * S, DB, 98, 15))   # bid 98 depth -> 15
events.append(mk(18 * S, TS, 98, 18))   # sell trade at 98 qty=18
events.append(mk(19 * S, DB, 98, 0))    # bid 98 cleared

# ---- Phase 4: Market drops ----
events.append(mk(20 * S, DS, 100, 30))  # new ask at 100
events.append(mk(21 * S, DS, 98, 20))   # ask drops to 98

data = np.array(events, dtype=event_dtype)
np.savez_compressed('/app/market_data.npz', data=data)

# ---- Orders ----
orders = {
    "tick_size": tick_size,
    "lot_size": lot_size,
    "maker_fee_rate": -0.0001,
    "taker_fee_rate": 0.0005,
    "orders": [
        {"id": 1, "side": "buy",  "price": 99.0,  "qty": 3.0,
         "submit_time_ns": T0 + S // 2},
        {"id": 2, "side": "sell", "price": 101.0, "qty": 5.0,
         "submit_time_ns": T0 + S // 2},
        {"id": 3, "side": "buy",  "price": 98.0,  "qty": 10.0,
         "submit_time_ns": T0 + S // 2},
        {"id": 4, "side": "buy",  "price": 97.0,  "qty": 1.0,
         "submit_time_ns": T0 + 10 * S},
        {"id": 5, "side": "sell", "price": 101.0, "qty": 3.0,
         "submit_time_ns": T0 + S // 2},
    ]
}

with open('/app/orders.json', 'w') as f:
    json.dump(orders, f, indent=2)

print("Generated market_data.npz and orders.json in /app/")
