#!/usr/bin/env python3
"""Generate synthetic L3 order book event data, configuration, and audit database."""

import csv
import json
import math
import os
import random
import sqlite3
from collections import defaultdict


def generate_events():
    random.seed(42)
    TICK = 0.01
    mid = 100.00
    events = []
    book = {}
    next_oid = 1
    next_tid = 1
    t_ns = 1_000_000_000

    for i in range(15000):
        t_ns += random.randint(50_000, 2_000_000)
        if random.random() < 0.1:
            mid += random.choice([-1, 1]) * TICK
            mid = round(mid, 2)

        n = len(book)
        if n < 30:
            probs = [0.60, 0.05, 0.05, 0.30]
        elif n > 100:
            probs = [0.10, 0.45, 0.10, 0.35]
        else:
            probs = [0.30, 0.25, 0.10, 0.35]

        r = random.random()
        if r < probs[0]:
            etype = 'ADD'
        elif r < probs[0] + probs[1]:
            etype = 'CANCEL'
        elif r < probs[0] + probs[1] + probs[2]:
            etype = 'MODIFY'
        else:
            etype = 'TRADE'

        if etype in ('CANCEL', 'MODIFY') and not book:
            etype = 'ADD'

        if etype == 'ADD':
            side = random.choice(['BUY', 'SELL'])
            offset = random.choice([1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20])
            if side == 'BUY':
                price = round(mid - offset * TICK, 2)
            else:
                price = round(mid + offset * TICK, 2)
            qty = random.choice([10, 20, 50, 100, 200, 500])
            oid = next_oid
            next_oid += 1
            book[oid] = {'side': side, 'price': price, 'qty': qty}
            events.append([t_ns, 'ADD_ORDER', str(oid), side,
                           '{:.2f}'.format(price), str(qty), ''])
        elif etype == 'CANCEL':
            oid = random.choice(list(book.keys()))
            events.append([t_ns, 'CANCEL_ORDER', str(oid), '', '', '', ''])
            del book[oid]
        elif etype == 'MODIFY':
            oid = random.choice(list(book.keys()))
            old_qty = book[oid]['qty']
            delta = random.choice([-50, -30, -20, -10, 10, 20, 30, 50])
            new_qty = max(1, old_qty + delta)
            book[oid]['qty'] = new_qty
            events.append([t_ns, 'MODIFY_ORDER', str(oid), '', '',
                           str(new_qty), ''])
        elif etype == 'TRADE':
            phase = i / 15000.0
            buy_prob = 0.5 + 0.15 * math.sin(2 * math.pi * phase * 3)
            agg_side = 'BUY' if random.random() < buy_prob else 'SELL'
            if agg_side == 'BUY':
                price = round(mid + random.choice([0, 0, 1, 1, 2]) * TICK, 2)
            else:
                price = round(mid - random.choice([0, 0, 1, 1, 2]) * TICK, 2)
            qty = random.choice([5, 10, 15, 20, 25, 50, 100])
            tid = 'T{:06d}'.format(next_tid)
            next_tid += 1
            events.append([t_ns, 'TRADE', '', agg_side,
                           '{:.2f}'.format(price), str(qty), tid])

    return events


def compute_checkpoints(events, config):
    """Compute correct reference checkpoints from event data."""
    snap_ts_list = config['snapshot_timestamps_ns']
    vpin_bv = config['vpin_bucket_volume']
    vbar_th = config['volume_bar_threshold']

    book = {}
    trades = []
    first_snap_data = None

    for ev in events:
        ts, et = ev[0], ev[1]

        if et == 'ADD_ORDER':
            book[int(ev[2])] = {'side': ev[3], 'price': float(ev[4]),
                                'qty': int(ev[5])}
        elif et == 'CANCEL_ORDER':
            book.pop(int(ev[2]), None)
        elif et == 'MODIFY_ORDER':
            oid = int(ev[2])
            if oid in book:
                book[oid]['qty'] = int(ev[5])
        elif et == 'TRADE':
            trades.append({'side': ev[3], 'qty': int(ev[5])})

        if ts == snap_ts_list[0] and first_snap_data is None:
            bl = defaultdict(int)
            al = defaultdict(int)
            for o in book.values():
                if o['side'] == 'BUY':
                    bl[o['price']] += o['qty']
                else:
                    al[o['price']] += o['qty']
            sb = sorted(bl.items(), key=lambda x: -x[0])[:5]
            sa = sorted(al.items(), key=lambda x: x[0])[:5]
            if sb and sa:
                first_snap_data = {
                    'best_bid': sb[0][0],
                    'best_ask': sa[0][0],
                    'mid': (sb[0][0] + sa[0][0]) / 2.0,
                    'spread': round(sa[0][0] - sb[0][0], 2),
                }

    tv = sum(t['qty'] for t in trades)
    bv = sum(t['qty'] for t in trades if t['side'] == 'BUY')

    n_complete_bars = 0
    cb_vol = 0
    for t in trades:
        rem = t['qty']
        while rem > 0:
            space = vbar_th - cb_vol
            fill = min(rem, space)
            cb_vol += fill
            rem -= fill
            if cb_vol >= vbar_th:
                n_complete_bars += 1
                cb_vol = 0
    total_bars = n_complete_bars + (1 if cb_vol > 0 else 0)

    n_vpin = 0
    vb_vol = 0
    for t in trades:
        rem = t['qty']
        while rem > 0:
            space = vpin_bv - vb_vol
            fill = min(rem, space)
            vb_vol += fill
            rem -= fill
            if vb_vol >= vpin_bv:
                n_vpin += 1
                vb_vol = 0

    checkpoints = [
        ('total_trades', str(len(trades)),
         'Total number of trade events'),
        ('total_volume', str(tv),
         'Sum of all trade quantities'),
        ('buy_initiated_volume', str(bv),
         'Volume from buyer-initiated trades'),
        ('sell_initiated_volume', str(tv - bv),
         'Volume from seller-initiated trades'),
        ('volume_bar_count', str(total_bars),
         'Expected total volume bars (complete + partial)'),
        ('complete_volume_bars', str(n_complete_bars),
         'Volume bars reaching exactly the configured threshold'),
        ('vpin_bucket_count', str(n_vpin),
         'Number of completed VPIN volume buckets'),
    ]

    if first_snap_data:
        checkpoints.extend([
            ('first_snapshot_best_bid', '{:.2f}'.format(first_snap_data['best_bid']),
             'Best bid at first snapshot timestamp (state after processing the event at that timestamp)'),
            ('first_snapshot_best_ask', '{:.2f}'.format(first_snap_data['best_ask']),
             'Best ask at first snapshot timestamp (state after processing the event at that timestamp)'),
            ('first_snapshot_spread', '{:.4f}'.format(first_snap_data['spread']),
             'Bid-ask spread at first snapshot timestamp'),
        ])

    return checkpoints


def main():
    os.makedirs('/data', exist_ok=True)
    events = generate_events()

    with open('/data/events.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp_ns', 'event_type', 'order_id', 'side',
                         'price', 'quantity', 'trade_id'])
        writer.writerows(events)

    all_ts = [e[0] for e in events]
    n = len(all_ts)
    snap_indices = [int(n * (k + 1) / 11) for k in range(10)]
    snap_ts = [all_ts[idx] for idx in snap_indices]

    config = {
        'snapshot_timestamps_ns': snap_ts,
        'vpin_bucket_volume': 500,
        'volume_bar_threshold': 1000,
        'realized_spread_trade_lag': 20,
    }
    with open('/data/config.json', 'w') as f:
        json.dump(config, f, indent=2)

    checkpoints = compute_checkpoints(events, config)

    conn = sqlite3.connect('/data/audit.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE events (
        seq INTEGER PRIMARY KEY,
        ts_ns INTEGER NOT NULL,
        evt_type TEXT NOT NULL,
        oid TEXT,
        direction TEXT,
        px REAL,
        sz INTEGER,
        tid TEXT
    )''')

    for i, ev in enumerate(events):
        c.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?)',
                  (i, ev[0], ev[1],
                   ev[2] if ev[2] else None,
                   ev[3] if ev[3] else None,
                   float(ev[4]) if ev[4] else None,
                   int(ev[5]) if ev[5] else None,
                   ev[6] if ev[6] else None))

    c.execute('''CREATE TABLE reference_checkpoints (
        metric TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        description TEXT
    )''')
    c.executemany('INSERT INTO reference_checkpoints VALUES (?,?,?)', checkpoints)

    conn.commit()
    conn.close()

    trades = [e for e in events if e[1] == 'TRADE']
    print('Generated {} events ({} trades)'.format(len(events), len(trades)))
    print('Audit database written to /data/audit.db')


if __name__ == '__main__':
    main()
