#!/usr/bin/env python3
"""Generate deterministic market data for the queue-position fill simulator task.

Design goals:
- Fixed mid-price (no drift) so fills happen ONLY through queue exhaustion
- Buy orders at 99.98, sell orders at 100.02 (exactly 2 ticks from mid)
- Trade offsets 0-2 from mid: SELL trades at 100.00/99.99/99.98, BUY at 100.00/100.01/100.02
- No trade-through possible (no trades below 99.98 or above 100.02)
- Depth events at order levels exercise the probability queue models
- Different queue models should produce different fill timings
"""
import numpy as np
import json
import os

np.random.seed(42)

event_dtype = np.dtype([
    ('ev', 'u8'), ('exch_ts', 'i8'), ('local_ts', 'i8'),
    ('px', 'f8'), ('qty', 'f8'), ('order_id', 'u8'),
    ('ival', 'i8'), ('fval', 'f8')
], align=True)

DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_SNAPSHOT_EVENT = 4
EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28

tick_size = 0.01
lot_size = 0.01
mid_price = 100.00  # Fixed, never changes

events = []
ts = 1_000_000_000_000

# Initial snapshot: 10 bid levels, 10 ask levels
# Ensure meaningful depth at 99.98 (buy order level) and 100.02 (sell order level)
bid_depths = {
    99.99: 45.0, 99.98: 65.0, 99.97: 55.0, 99.96: 40.0, 99.95: 35.0,
    99.94: 30.0, 99.93: 25.0, 99.92: 20.0, 99.91: 15.0, 99.90: 10.0
}
ask_depths = {
    100.01: 50.0, 100.02: 70.0, 100.03: 60.0, 100.04: 45.0, 100.05: 40.0,
    100.06: 35.0, 100.07: 30.0, 100.08: 25.0, 100.09: 20.0, 100.10: 15.0
}

for price, qty in sorted(bid_depths.items(), reverse=True):
    events.append((
        EXCH_EVENT | LOCAL_EVENT | DEPTH_SNAPSHOT_EVENT | BUY_EVENT,
        ts, ts + 100_000, price, qty, 0, 0, 0.0
    ))
    ts += 10_000

for price, qty in sorted(ask_depths.items()):
    events.append((
        EXCH_EVENT | LOCAL_EVENT | DEPTH_SNAPSHOT_EVENT | SELL_EVENT,
        ts, ts + 100_000, price, qty, 0, 0, 0.0
    ))
    ts += 10_000

# Track book state for consistency
book_bids = dict(bid_depths)
book_asks = dict(ask_depths)

# Generate 2000 events focused on exercising queue models
for i in range(2000):
    ts += np.random.randint(1_000_000, 20_000_000)
    latency = np.random.randint(500_000, 3_000_000)
    r = np.random.random()

    if r < 0.30:
        # Trade event (30% of events)
        if np.random.random() < 0.5:
            # SELL trade (aggressive seller hitting bids)
            # Weighted towards 99.98 to exercise buy order queue
            w = np.random.random()
            if w < 0.30:
                trade_price = 99.98  # At buy order level
            elif w < 0.65:
                trade_price = 99.99
            else:
                trade_price = 100.00
            trade_qty = round(np.random.uniform(0.5, 5.0), 2)
            events.append((
                EXCH_EVENT | LOCAL_EVENT | TRADE_EVENT | SELL_EVENT,
                ts, ts + latency, trade_price, trade_qty, 0, 0, 0.0
            ))
        else:
            # BUY trade (aggressive buyer lifting asks)
            w = np.random.random()
            if w < 0.30:
                trade_price = 100.02  # At sell order level
            elif w < 0.65:
                trade_price = 100.01
            else:
                trade_price = 100.00
            trade_qty = round(np.random.uniform(0.5, 5.0), 2)
            events.append((
                EXCH_EVENT | LOCAL_EVENT | TRADE_EVENT | BUY_EVENT,
                ts, ts + latency, trade_price, trade_qty, 0, 0, 0.0
            ))
    else:
        # Depth update (70% of events)
        if np.random.random() < 0.5:
            # Bid depth update
            # Focus on 99.98 (buy order level) with higher probability
            w = np.random.random()
            if w < 0.35:
                price = 99.98
            elif w < 0.55:
                price = 99.99
            elif w < 0.70:
                price = 99.97
            else:
                price = round(99.90 + np.random.randint(0, 7) * tick_size, 2)

            # Generate new qty: mix of increases, decreases, and replacements
            old_qty = book_bids.get(price, 0.0)
            change_type = np.random.random()
            if change_type < 0.3:
                # Increase
                qty = round(old_qty + np.random.uniform(5.0, 30.0), 2)
            elif change_type < 0.7:
                # Decrease
                qty = round(max(0.0, old_qty - np.random.uniform(2.0, 15.0)), 2)
            elif change_type < 0.85:
                # Replace with new value
                qty = round(np.random.uniform(10.0, 80.0), 2)
            else:
                # Clear level
                qty = 0.0

            # Ensure no crossing
            if qty > 0 and price >= min(book_asks.keys()):
                continue
            if qty <= 0:
                book_bids.pop(price, None)
            else:
                book_bids[price] = qty
            events.append((
                EXCH_EVENT | LOCAL_EVENT | DEPTH_EVENT | BUY_EVENT,
                ts, ts + latency, price, qty, 0, 0, 0.0
            ))
        else:
            # Ask depth update
            w = np.random.random()
            if w < 0.35:
                price = 100.02
            elif w < 0.55:
                price = 100.01
            elif w < 0.70:
                price = 100.03
            else:
                price = round(100.04 + np.random.randint(0, 7) * tick_size, 2)

            old_qty = book_asks.get(price, 0.0)
            change_type = np.random.random()
            if change_type < 0.3:
                qty = round(old_qty + np.random.uniform(5.0, 30.0), 2)
            elif change_type < 0.7:
                qty = round(max(0.0, old_qty - np.random.uniform(2.0, 15.0)), 2)
            elif change_type < 0.85:
                qty = round(np.random.uniform(10.0, 80.0), 2)
            else:
                qty = 0.0

            if qty > 0 and price <= max(book_bids.keys()):
                continue
            if qty <= 0:
                book_asks.pop(price, None)
            else:
                book_asks[price] = qty
            events.append((
                EXCH_EVENT | LOCAL_EVENT | DEPTH_EVENT | SELL_EVENT,
                ts, ts + latency, price, qty, 0, 0, 0.0
            ))

data = np.array(events, dtype=event_dtype)
os.makedirs('/app', exist_ok=True)
np.savez_compressed('/app/market_data.npz', data=data)

# Generate orders: buy at 99.98, sell at 100.02
np.random.seed(123)
orders = []
for i in range(15):
    submit_idx = min(25 + i * 80, len(data) - 10)
    qty = round(np.random.uniform(1.0, 6.0), 2)
    orders.append({
        'order_id': i,
        'side': 'buy',
        'price': 99.98,
        'qty': qty,
        'submit_event_idx': submit_idx
    })
for i in range(15):
    submit_idx = min(25 + i * 80, len(data) - 10)
    qty = round(np.random.uniform(1.0, 6.0), 2)
    orders.append({
        'order_id': 15 + i,
        'side': 'sell',
        'price': 100.02,
        'qty': qty,
        'submit_event_idx': submit_idx
    })

with open('/app/orders.json', 'w') as f:
    json.dump(orders, f, indent=2)

config = {
    'tick_size': tick_size,
    'lot_size': lot_size,
    'maker_fee': 0.0002,
    'taker_fee': 0.0007
}
with open('/app/config.json', 'w') as f:
    json.dump(config, f, indent=2)

print(f"Generated {len(data)} events, {len(orders)} orders")
bb = max(book_bids.keys()) if book_bids else 0
ba = min(book_asks.keys()) if book_asks else 999
print(f"Final best_bid: {bb}, best_ask: {ba}")
