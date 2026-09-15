#!/usr/bin/env python3
"""Corrected market microstructure analysis engine."""

import csv
import json
from collections import defaultdict


def compute_mid(book):
    """Compute mid price from current book state."""
    bids = [o['price'] for o in book.values() if o['side'] == 'BUY']
    asks = [o['price'] for o in book.values() if o['side'] == 'SELL']
    best_bid = max(bids) if bids else None
    best_ask = min(asks) if asks else None
    if best_bid is not None and best_ask is not None:
        return (best_bid + best_ask) / 2.0
    elif best_bid is not None:
        return float(best_bid)
    elif best_ask is not None:
        return float(best_ask)
    return None


def build_snapshot(book, ts):
    """Build order book snapshot at given timestamp."""
    bid_levels = defaultdict(int)
    ask_levels = defaultdict(int)
    for o in book.values():
        if o['side'] == 'BUY':
            bid_levels[o['price']] += o['qty']
        else:
            ask_levels[o['price']] += o['qty']

    sorted_bids = sorted(bid_levels.items(), key=lambda x: -x[0])[:5]
    sorted_asks = sorted(ask_levels.items(), key=lambda x: x[0])[:5]

    best_bid = sorted_bids[0][0] if sorted_bids else None
    best_ask = sorted_asks[0][0] if sorted_asks else None
    mid = spread = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2.0
        spread = round(best_ask - best_bid, 2)

    return {
        'timestamp_ns': ts,
        'best_bid': best_bid,
        'best_ask': best_ask,
        'mid_price': mid,
        'spread': spread,
        'bid_levels': [[p, q] for p, q in sorted_bids],
        'ask_levels': [[p, q] for p, q in sorted_asks],
    }


def main():
    with open('/data/config.json') as f:
        config = json.load(f)

    snapshot_ts_set = set(config['snapshot_timestamps_ns'])
    vpin_bucket_vol = config['vpin_bucket_volume']
    vbar_threshold = config['volume_bar_threshold']
    rs_lag = config['realized_spread_trade_lag']

    events = []
    with open('/data/events.csv') as f:
        for row in csv.DictReader(f):
            events.append(row)

    book = {}
    snapshots = []
    trade_records = []

    for ev in events:
        ts = int(ev['timestamp_ns'])
        etype = ev['event_type']

        if etype == 'ADD_ORDER':
            oid = int(ev['order_id'])
            book[oid] = {
                'side': ev['side'],
                'price': float(ev['price']),
                'qty': int(ev['quantity']),
            }
        elif etype == 'CANCEL_ORDER':
            oid = int(ev['order_id'])
            book.pop(oid, None)
        elif etype == 'MODIFY_ORDER':
            oid = int(ev['order_id'])
            if oid in book:
                book[oid]['qty'] = int(ev['quantity'])
        elif etype == 'TRADE':
            mid = compute_mid(book)
            if mid is None:
                mid = float(ev['price'])
            trade_records.append({
                'ts': ts,
                'side': ev['side'],
                'price': float(ev['price']),
                'qty': int(ev['quantity']),
                'mid': mid,
            })

        # Capture snapshot AFTER processing the event at this timestamp
        if ts in snapshot_ts_set:
            snapshots.append(build_snapshot(book, ts))

    snapshots.sort(key=lambda s: s['timestamp_ns'])

    # === Compute microstructure metrics ===

    total_vol = sum(t['qty'] for t in trade_records)
    buy_vol = sum(t['qty'] for t in trade_records if t['side'] == 'BUY')
    sell_vol = total_vol - buy_vol
    vwap = (sum(t['price'] * t['qty'] for t in trade_records) / total_vol
            if total_vol else 0.0)

    # Volume-weighted effective spread
    es_pairs = []
    for t in trade_records:
        if t['mid'] > 0:
            es = 2.0 * abs(t['price'] - t['mid']) / t['mid'] * 10000
            es_pairs.append((es, t['qty']))
    es_vol = sum(q for _, q in es_pairs)
    w_es = sum(s * q for s, q in es_pairs) / es_vol if es_vol else 0.0

    # Volume-weighted realized spread (directional)
    rs_pairs = []
    for i in range(len(trade_records) - rs_lag):
        t = trade_records[i]
        t_future = trade_records[i + rs_lag]
        if t['mid'] > 0:
            d = 1 if t['side'] == 'BUY' else -1
            rs = 2.0 * d * (t['price'] - t_future['mid']) / t['mid'] * 10000
            rs_pairs.append((rs, t['qty']))
    rs_vol = sum(q for _, q in rs_pairs)
    w_rs = sum(s * q for s, q in rs_pairs) / rs_vol if rs_vol else 0.0

    pi_bps = w_es - w_rs

    metrics = {
        'total_trades': len(trade_records),
        'total_volume': total_vol,
        'buy_initiated_volume': buy_vol,
        'sell_initiated_volume': sell_vol,
        'vwap': round(vwap, 6),
        'effective_spread_bps': round(w_es, 6),
        'realized_spread_bps': round(w_rs, 6),
        'price_impact_bps': round(pi_bps, 6),
    }

    # === Volume bars (with trade splitting at boundaries) ===

    volume_bars = []
    cur_bar = None
    bar_pq = 0.0

    for t in trade_records:
        remaining = t['qty']
        while remaining > 0:
            if cur_bar is None:
                cur_bar = {
                    'open': t['price'],
                    'high': t['price'],
                    'low': t['price'],
                    'close': t['price'],
                    'volume': 0,
                    'start_ns': t['ts'],
                    'end_ns': t['ts'],
                }
                bar_pq = 0.0

            space = vbar_threshold - cur_bar['volume']
            fill = min(remaining, space)

            cur_bar['high'] = max(cur_bar['high'], t['price'])
            cur_bar['low'] = min(cur_bar['low'], t['price'])
            cur_bar['close'] = t['price']
            cur_bar['end_ns'] = t['ts']
            cur_bar['volume'] += fill
            bar_pq += t['price'] * fill
            remaining -= fill

            if cur_bar['volume'] >= vbar_threshold:
                cur_bar['vwap'] = round(bar_pq / cur_bar['volume'], 6)
                volume_bars.append(cur_bar)
                cur_bar = None

    if cur_bar and cur_bar['volume'] > 0:
        cur_bar['vwap'] = round(bar_pq / cur_bar['volume'], 6)
        volume_bars.append(cur_bar)

    # === VPIN (with trade splitting at bucket boundaries) ===

    vpin_values = []
    bucket_buy = 0
    bucket_sell = 0
    bucket_vol = 0

    for t in trade_records:
        remaining = t['qty']
        while remaining > 0:
            space = vpin_bucket_vol - bucket_vol
            fill = min(remaining, space)
            if t['side'] == 'BUY':
                bucket_buy += fill
            else:
                bucket_sell += fill
            bucket_vol += fill
            remaining -= fill

            if bucket_vol >= vpin_bucket_vol:
                vpin_values.append(
                    round(abs(bucket_buy - bucket_sell) / bucket_vol, 6)
                )
                bucket_buy = bucket_sell = bucket_vol = 0

    # === Kyle's lambda (Cov / Var of signed volume) ===

    kyle_lambda = 0.0
    if len(trade_records) > 10:
        dms = []
        svs = []
        for i in range(1, len(trade_records)):
            dm = trade_records[i]['mid'] - trade_records[i - 1]['mid']
            d = 1 if trade_records[i]['side'] == 'BUY' else -1
            sv = d * trade_records[i]['qty']
            dms.append(dm)
            svs.append(sv)

        n = len(dms)
        mean_dm = sum(dms) / n
        mean_sv = sum(svs) / n
        cov = sum((dms[j] - mean_dm) * (svs[j] - mean_sv) for j in range(n)) / n
        var_sv = sum((svs[j] - mean_sv) ** 2 for j in range(n)) / n
        kyle_lambda = cov / var_sv if var_sv > 0 else 0.0

    # === Write results ===

    results = {
        'snapshots': snapshots,
        'metrics': metrics,
        'vpin_values': vpin_values,
        'volume_bars': volume_bars,
        'kyle_lambda': round(kyle_lambda, 10),
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print('Analysis complete: {} trades, {} volume bars, {} VPIN values'.format(
        len(trade_records), len(volume_bars), len(vpin_values)))


if __name__ == '__main__':
    main()
