#!/usr/bin/env python3
"""Market microstructure analysis engine.

Processes L3 order book events and produces market quality analytics.
"""

import csv
import json
from collections import defaultdict


def compute_mid(book):
    """Compute mid price from current order book state."""
    bids = [o['price'] for o in book.values() if o['side'] == 'BUY']
    asks = [o['price'] for o in book.values() if o['side'] == 'SELL']
    bb = max(bids) if bids else None
    ba = min(asks) if asks else None
    if bb is not None and ba is not None:
        return (bb + ba) / 2.0
    if bb is not None:
        return float(bb)
    if ba is not None:
        return float(ba)
    return None


def build_snapshot(book, ts):
    """Build order book snapshot at a given timestamp."""
    bl = defaultdict(int)
    al = defaultdict(int)
    for o in book.values():
        if o['side'] == 'BUY':
            bl[o['price']] += o['qty']
        else:
            al[o['price']] += o['qty']

    sb = sorted(bl.items(), key=lambda x: -x[0])[:5]
    sa = sorted(al.items(), key=lambda x: x[0])[:5]
    bb = sb[0][0] if sb else None
    ba = sa[0][0] if sa else None
    mid = spread = None
    if bb is not None and ba is not None:
        mid = (bb + ba) / 2.0
        spread = round(ba - bb, 2)

    return {
        'timestamp_ns': ts,
        'best_bid': bb,
        'best_ask': ba,
        'mid_price': mid,
        'spread': spread,
        'bid_levels': [[p, q] for p, q in sb],
        'ask_levels': [[p, q] for p, q in sa],
    }


def main():
    with open('/data/config.json') as f:
        config = json.load(f)

    snap_ts = set(config['snapshot_timestamps_ns'])
    vpin_bv = config['vpin_bucket_volume']
    vbar_th = config['volume_bar_threshold']
    rs_lag = config['realized_spread_trade_lag']

    events = []
    with open('/data/events.csv') as f:
        for row in csv.DictReader(f):
            events.append(row)

    book = {}
    snapshots = []
    trades = []

    for ev in events:
        ts = int(ev['timestamp_ns'])
        et = ev['event_type']

        if ts in snap_ts:
            snapshots.append(build_snapshot(book, ts))

        if et == 'ADD_ORDER':
            book[int(ev['order_id'])] = {
                'side': ev['side'],
                'price': float(ev['price']),
                'qty': int(ev['quantity']),
            }
        elif et == 'CANCEL_ORDER':
            book.pop(int(ev['order_id']), None)
        elif et == 'MODIFY_ORDER':
            oid = int(ev['order_id'])
            if oid in book:
                book[oid]['qty'] = int(ev['quantity'])
        elif et == 'TRADE':
            mid = compute_mid(book)
            if mid is None:
                mid = float(ev['price'])
            trades.append({
                'ts': ts, 'side': ev['side'],
                'price': float(ev['price']),
                'qty': int(ev['quantity']),
                'mid': mid,
            })

    snapshots.sort(key=lambda s: s['timestamp_ns'])

    # Aggregate trade metrics
    total_vol = sum(t['qty'] for t in trades)
    buy_vol = sum(t['qty'] for t in trades if t['side'] == 'BUY')
    sell_vol = total_vol - buy_vol
    vwap = sum(t['price'] * t['qty'] for t in trades) / total_vol if total_vol else 0.0

    # Effective spread (volume-weighted, in bps)
    es_data = []
    for t in trades:
        if t['mid'] > 0:
            es_data.append(
                (2.0 * abs(t['price'] - t['mid']) / t['mid'] * 10000, t['qty']))
    es_vol = sum(q for _, q in es_data)
    eff_spread = sum(s * q for s, q in es_data) / es_vol if es_vol else 0.0

    # Realized spread (volume-weighted, in bps)
    rs_data = []
    for i in range(len(trades) - rs_lag):
        t = trades[i]
        t_lag = trades[i + rs_lag]
        if t['mid'] > 0:
            rs = 2.0 * abs(t['price'] - t_lag['mid']) / t['mid'] * 10000
            rs_data.append((rs, t['qty']))
    rs_vol = sum(q for _, q in rs_data)
    real_spread = sum(s * q for s, q in rs_data) / rs_vol if rs_vol else 0.0

    # Volume bars
    vbars = []
    cur = None
    pq_sum = 0.0
    for t in trades:
        if cur is None:
            cur = {
                'open': t['price'], 'high': t['price'],
                'low': t['price'], 'close': t['price'],
                'volume': 0, 'start_ns': t['ts'], 'end_ns': t['ts'],
            }
            pq_sum = 0.0
        cur['high'] = max(cur['high'], t['price'])
        cur['low'] = min(cur['low'], t['price'])
        cur['close'] = t['price']
        cur['end_ns'] = t['ts']
        cur['volume'] += t['qty']
        pq_sum += t['price'] * t['qty']
        if cur['volume'] >= vbar_th:
            cur['vwap'] = pq_sum / cur['volume']
            vbars.append(cur)
            cur = None
    if cur and cur['volume'] > 0:
        cur['vwap'] = pq_sum / cur['volume']
        vbars.append(cur)

    # VPIN
    vpin_vals = []
    bkt_buy = bkt_sell = bkt_vol = 0
    for t in trades:
        if t['side'] == 'BUY':
            bkt_buy += t['qty']
        else:
            bkt_sell += t['qty']
        bkt_vol += t['qty']
        if bkt_vol >= vpin_bv:
            vpin_vals.append(abs(bkt_buy - bkt_sell) / bkt_vol)
            bkt_buy = bkt_sell = bkt_vol = 0

    # Kyle's lambda (price impact coefficient)
    kyle_l = 0.0
    if len(trades) > 10:
        delta_mid = [trades[i]['mid'] - trades[i - 1]['mid']
                     for i in range(1, len(trades))]
        signed_vol = [(1 if trades[i]['side'] == 'BUY' else -1) * trades[i]['qty']
                      for i in range(1, len(trades))]
        n = len(delta_mid)
        mu_dm = sum(delta_mid) / n
        mu_sv = sum(signed_vol) / n
        cov = sum((delta_mid[j] - mu_dm) * (signed_vol[j] - mu_sv)
                  for j in range(n)) / n
        var_dm = sum((delta_mid[j] - mu_dm) ** 2 for j in range(n)) / n
        kyle_l = cov / var_dm if var_dm > 0 else 0.0

    output = {
        'snapshots': snapshots,
        'metrics': {
            'total_trades': len(trades),
            'total_volume': total_vol,
            'buy_initiated_volume': buy_vol,
            'sell_initiated_volume': sell_vol,
            'vwap': vwap,
            'effective_spread_bps': eff_spread,
            'realized_spread_bps': real_spread,
            'price_impact_bps': eff_spread - real_spread,
        },
        'vpin_values': vpin_vals,
        'volume_bars': vbars,
        'kyle_lambda': kyle_l,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('Processed {} events, {} trades'.format(len(events), len(trades)))


if __name__ == '__main__':
    main()
