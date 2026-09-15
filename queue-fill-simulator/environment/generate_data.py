#!/usr/bin/env python3
"""
Generates deterministic synthetic L2 market data for the queue position fill simulator task.
Creates /app/data/events.bin, /app/data/layout.txt, /app/data/orders.json,
/app/data/config.json, /app/data/output_schema.json.
"""
import numpy as np
import json
import os

np.random.seed(20240315)

# Event flags (hftbacktest format)
DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_CLEAR_EVENT = 3
DEPTH_SNAPSHOT_EVENT = 4
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28
EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30

tick_size = 0.10
lot_size = 0.001
mid_tick = 500000  # price 50000.0

event_dtype = np.dtype([
    ('ev', '<u8'), ('exch_ts', '<i8'), ('local_ts', '<i8'), ('px', '<f8'),
    ('qty', '<f8'), ('order_id', '<u8'), ('ival', '<i8'), ('fval', '<f8')
], align=True)

events_list = []
ts = 1_000_000_000_000  # 10^12 nanoseconds

# Initialize order book: 25 bid levels, 25 ask levels
bid_book = {}
ask_book = {}
for i in range(25):
    bid_tick = mid_tick - 1 - i
    ask_tick = mid_tick + i
    bid_qty = round(max(30.0, np.random.exponential(50.0)), 3)
    ask_qty = round(max(30.0, np.random.exponential(50.0)), 3)
    bid_book[bid_tick] = bid_qty
    ask_book[ask_tick] = ask_qty

# Emit initial depth clear events
events_list.append((
    DEPTH_CLEAR_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT,
    ts, ts + 50000,
    min(bid_book.keys()) * tick_size, 0.0, 0, 0, 0.0
))
events_list.append((
    DEPTH_CLEAR_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT,
    ts, ts + 50000,
    max(ask_book.keys()) * tick_size, 0.0, 0, 0, 0.0
))
ts += 1

# Emit snapshot events (bids descending, asks ascending)
for pt in sorted(bid_book.keys(), reverse=True):
    events_list.append((
        DEPTH_SNAPSHOT_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT,
        ts, ts + 50000,
        pt * tick_size, bid_book[pt], 0, 0, 0.0
    ))
for pt in sorted(ask_book.keys()):
    events_list.append((
        DEPTH_SNAPSHOT_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT,
        ts, ts + 50000,
        pt * tick_size, ask_book[pt], 0, 0, 0.0
    ))

ts += 1_000_000  # 1ms gap after snapshot

# Generate 3000 incremental events
trade_id = 1
for step in range(3000):
    dt = int(np.random.exponential(400_000))
    ts += max(dt, 1000)
    local_ts = ts + int(np.random.exponential(80_000))

    r = np.random.random()

    if r < 0.25:
        # Bid depth update
        if not bid_book:
            continue
        best_bid = max(bid_book.keys())
        offset = min(np.random.geometric(0.5) - 1, 10)
        target_tick = best_bid - offset

        if target_tick not in bid_book:
            new_qty = round(max(5.0, np.random.exponential(20.0)), 3)
            bid_book[target_tick] = new_qty
        else:
            action = np.random.random()
            if action < 0.35:
                addition = round(max(0.5, np.random.exponential(4.0)), 3)
                bid_book[target_tick] = round(bid_book[target_tick] + addition, 3)
            elif action < 0.75:
                reduction = round(max(0.2, np.random.exponential(3.0)), 3)
                new_val = round(bid_book[target_tick] - reduction, 3)
                if new_val <= 0:
                    new_val = round(max(0.5, np.random.exponential(1.0)), 3)
                bid_book[target_tick] = new_val
            else:
                delta = np.random.normal(0, 2.0)
                bid_book[target_tick] = round(max(0.5, bid_book[target_tick] + delta), 3)

        events_list.append((
            DEPTH_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT,
            ts, local_ts,
            target_tick * tick_size, bid_book[target_tick], 0, 0, 0.0
        ))

    elif r < 0.50:
        # Ask depth update
        if not ask_book:
            continue
        best_ask = min(ask_book.keys())
        offset = min(np.random.geometric(0.5) - 1, 10)
        target_tick = best_ask + offset

        if target_tick not in ask_book:
            new_qty = round(max(5.0, np.random.exponential(20.0)), 3)
            ask_book[target_tick] = new_qty
        else:
            action = np.random.random()
            if action < 0.35:
                addition = round(max(0.5, np.random.exponential(4.0)), 3)
                ask_book[target_tick] = round(ask_book[target_tick] + addition, 3)
            elif action < 0.75:
                reduction = round(max(0.2, np.random.exponential(3.0)), 3)
                new_val = round(ask_book[target_tick] - reduction, 3)
                if new_val <= 0:
                    new_val = round(max(0.5, np.random.exponential(1.0)), 3)
                ask_book[target_tick] = new_val
            else:
                delta = np.random.normal(0, 2.0)
                ask_book[target_tick] = round(max(0.5, ask_book[target_tick] + delta), 3)

        events_list.append((
            DEPTH_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT,
            ts, local_ts,
            target_tick * tick_size, ask_book[target_tick], 0, 0, 0.0
        ))

    else:
        # Trade event
        if not bid_book or not ask_book:
            continue
        best_bid = max(bid_book.keys())
        best_ask = min(ask_book.keys())

        if np.random.random() < 0.5:
            trade_tick = best_ask
            level_qty = ask_book.get(trade_tick, 0.001)
            trade_qty = round(min(level_qty * 0.3,
                                  max(0.001, np.random.exponential(0.08))), 3)

            events_list.append((
                TRADE_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT,
                ts, local_ts,
                trade_tick * tick_size, trade_qty, trade_id, 0, 0.0
            ))
            trade_id += 1

            ask_book[trade_tick] = round(ask_book[trade_tick] - trade_qty, 3)
            if ask_book[trade_tick] <= 0.001:
                ask_book[trade_tick] = round(max(5.0, np.random.exponential(15.0)), 3)
            events_list.append((
                DEPTH_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT,
                ts, local_ts,
                trade_tick * tick_size, ask_book[trade_tick], 0, 0, 0.0
            ))
        else:
            trade_tick = best_bid
            level_qty = bid_book.get(trade_tick, 0.001)
            trade_qty = round(min(level_qty * 0.3,
                                  max(0.001, np.random.exponential(0.08))), 3)

            events_list.append((
                TRADE_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT,
                ts, local_ts,
                trade_tick * tick_size, trade_qty, trade_id, 0, 0.0
            ))
            trade_id += 1

            bid_book[trade_tick] = round(bid_book[trade_tick] - trade_qty, 3)
            if bid_book[trade_tick] <= 0.001:
                bid_book[trade_tick] = round(max(5.0, np.random.exponential(15.0)), 3)
            events_list.append((
                DEPTH_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT,
                ts, local_ts,
                trade_tick * tick_size, bid_book[trade_tick], 0, 0, 0.0
            ))

# Convert to numpy array and save as raw binary
events = np.array(events_list, dtype=event_dtype)

os.makedirs('/app/data', exist_ok=True)
events.tofile('/app/data/events.bin')

# Write binary layout documentation
layout_doc = """Event Record Binary Format
===========================
Little-endian byte order, C-struct alignment.
Each record is 64 bytes, no header, no padding between records.

Offset  Bytes  C Type      Field       Description
------  -----  ----------  ----------  ------------------------------------------
0       8      uint64_t    ev          Event flags bitfield (see types.rs)
8       8      int64_t     exch_ts     Exchange timestamp (nanoseconds)
16      8      int64_t     local_ts    Local timestamp (nanoseconds)
24      8      double      px          Price
32      8      double      qty         Quantity
40      8      uint64_t    order_id    Order identifier (0 for L2 events)
48      8      int64_t     ival        Reserved integer value
56      8      double      fval        Reserved float value

File contains N consecutive records with no separators.
Total file size = N * 64 bytes.
"""
with open('/app/data/layout.txt', 'w') as f:
    f.write(layout_doc)

# Write output schema documentation
output_schema = {
    "results_schema": {
        "orders": [
            {
                "order_id": "int: order ID from orders.json",
                "side": "string: 'buy' or 'sell'",
                "price_tick": "int: price level in ticks",
                "qty": "float: order quantity",
                "models": {
                    "<model_name>": {
                        "filled": "bool: whether the order was filled under this model",
                        "fill_event_idx": "int|null: 0-based index into event stream at fill, null if unfilled",
                        "fill_exch_ts": "int|null: exchange timestamp at fill, null if unfilled",
                        "final_front_q_qty": "float: remaining front-of-queue quantity, 0.0 if filled"
                    }
                }
            }
        ],
        "book_state": {
            "final_best_bid_tick": "int: best bid price level in ticks after processing all events",
            "final_best_ask_tick": "int: best ask price level in ticks after processing all events",
            "final_best_bid_qty": "float: quantity at best bid",
            "final_best_ask_qty": "float: quantity at best ask",
            "total_trade_events": "int: count of trade-type events (base type 2)",
            "total_depth_events": "int: count of depth-update events (base type 1, excluding snapshots and clears)"
        }
    },
    "analysis_schema": {
        "fill_counts": {"<model_name>": "int: number of orders filled by this model"},
        "aggressiveness_ranking": ["models sorted by fill count descending; alphabetical tiebreak"],
        "pairwise_disagreements": {
            "<model_a>__<model_b>": "int: count of orders where models disagree on filled status"
        },
        "model_sensitive_orders": ["int: ascending order IDs where at least two models disagree on fill"],
        "most_conservative_model": "string: model with fewest fills (alphabetical tiebreak)",
        "most_aggressive_model": "string: model with most fills (alphabetical tiebreak)"
    },
    "notes": {
        "model_names": "Use the keys from the 'models' object in config.json",
        "pairwise_key_format": "Alphabetically earlier model name + '__' + later model name, for all C(n,2) unordered pairs",
        "quantities": "Rounded to 6 decimal places",
        "order_ordering": "Same order as orders.json"
    }
}
with open('/app/data/output_schema.json', 'w') as f:
    json.dump(output_schema, f, indent=2)

# Generate test orders with placement timestamps
n_events = len(events)

placement_indices = [
    int(n_events * 0.02),
    int(n_events * 0.02),
    int(n_events * 0.02),
    int(n_events * 0.02),
    int(n_events * 0.15),
    int(n_events * 0.15),
    int(n_events * 0.50),
    int(n_events * 0.50),
]

order_specs = [
    ("buy",  mid_tick - 1,  0.1),
    ("sell", mid_tick,      0.05),
    ("buy",  mid_tick - 15, 0.1),
    ("sell", mid_tick + 15, 0.1),
    ("buy",  mid_tick - 1,  0.5),
    ("sell", mid_tick,      0.3),
    ("buy",  mid_tick - 1,  0.1),
    ("sell", mid_tick,      0.1),
]

orders = []
for i, ((side, pt, qty), pi) in enumerate(zip(order_specs, placement_indices)):
    place_ts = int(events[pi]['exch_ts'])
    orders.append({
        "id": i + 1,
        "side": side,
        "price_tick": int(pt),
        "qty": float(qty),
        "place_at_ts": place_ts
    })

with open('/app/data/orders.json', 'w') as f:
    json.dump(orders, f, indent=2)

config = {
    "tick_size": tick_size,
    "lot_size": lot_size,
    "models": {
        "risk_adverse": {},
        "power_prob_n2": {"n": 2.0},
        "log_prob": {},
        "log_prob2": {},
        "power_prob3_n3": {"n": 3.0}
    }
}
with open('/app/data/config.json', 'w') as f:
    json.dump(config, f, indent=2)

print(f"Generated {len(events)} events ({len(events) * 64} bytes), {trade_id - 1} trades")
if bid_book:
    print(f"Final best bid: {max(bid_book.keys()) * tick_size:.1f}")
if ask_book:
    print(f"Final best ask: {min(ask_book.keys()) * tick_size:.1f}")
