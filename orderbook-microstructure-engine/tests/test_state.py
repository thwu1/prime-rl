#!/usr/bin/env python3
"""Independent verification of market microstructure analysis results."""

import csv
import json
import os
from collections import defaultdict

import pytest


def _reference_solution():
    """Independently compute expected results from raw event data."""
    with open('/data/config.json') as f:
        config = json.load(f)

    snap_ts_set = set(config['snapshot_timestamps_ns'])
    vpin_bv = config['vpin_bucket_volume']
    vbar_th = config['volume_bar_threshold']
    rs_lag = config['realized_spread_trade_lag']

    events = []
    with open('/data/events.csv') as f:
        for row in csv.DictReader(f):
            events.append(row)

    book = {}
    snapshots = {}
    trades = []

    for ev in events:
        ts = int(ev['timestamp_ns'])
        et = ev['event_type']

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
            bids = [o['price'] for o in book.values() if o['side'] == 'BUY']
            asks = [o['price'] for o in book.values() if o['side'] == 'SELL']
            bb = max(bids) if bids else None
            ba = min(asks) if asks else None
            if bb is not None and ba is not None:
                mid = (bb + ba) / 2.0
            elif bb is not None:
                mid = float(bb)
            elif ba is not None:
                mid = float(ba)
            else:
                mid = float(ev['price'])
            trades.append({
                'ts': ts,
                'side': ev['side'],
                'price': float(ev['price']),
                'qty': int(ev['quantity']),
                'mid': mid,
            })

        if ts in snap_ts_set:
            bl = defaultdict(int)
            al = defaultdict(int)
            for o in book.values():
                if o['side'] == 'BUY':
                    bl[o['price']] += o['qty']
                else:
                    al[o['price']] += o['qty']
            sb = sorted(bl.items(), key=lambda x: -x[0])[:5]
            sa = sorted(al.items(), key=lambda x: x[0])[:5]
            bb2 = sb[0][0] if sb else None
            ba2 = sa[0][0] if sa else None
            m2 = s2 = None
            if bb2 is not None and ba2 is not None:
                m2 = (bb2 + ba2) / 2.0
                s2 = round(ba2 - bb2, 2)
            snapshots[ts] = {
                'best_bid': bb2,
                'best_ask': ba2,
                'mid_price': m2,
                'spread': s2,
                'bid_levels': [[p, q] for p, q in sb],
                'ask_levels': [[p, q] for p, q in sa],
            }

    # --- Metrics ---
    tv = sum(t['qty'] for t in trades)
    bv = sum(t['qty'] for t in trades if t['side'] == 'BUY')
    sv = tv - bv
    vwap = sum(t['price'] * t['qty'] for t in trades) / tv if tv else 0.0

    es_pairs = []
    for t in trades:
        if t['mid'] > 0:
            es_pairs.append(
                (2.0 * abs(t['price'] - t['mid']) / t['mid'] * 10000, t['qty'])
            )
    esv = sum(q for _, q in es_pairs)
    wes = sum(s * q for s, q in es_pairs) / esv if esv else 0.0

    rs_pairs = []
    for i in range(len(trades) - rs_lag):
        t = trades[i]
        tf = trades[i + rs_lag]
        if t['mid'] > 0:
            d = 1 if t['side'] == 'BUY' else -1
            rs_pairs.append(
                (2.0 * d * (t['price'] - tf['mid']) / t['mid'] * 10000, t['qty'])
            )
    rsv = sum(q for _, q in rs_pairs)
    wrs = sum(s * q for s, q in rs_pairs) / rsv if rsv else 0.0

    # --- Volume bars ---
    vbars = []
    cb = None
    bpq = 0.0
    for t in trades:
        rem = t['qty']
        while rem > 0:
            if cb is None:
                cb = {
                    'open': t['price'],
                    'high': t['price'],
                    'low': t['price'],
                    'close': t['price'],
                    'volume': 0,
                    'start_ns': t['ts'],
                    'end_ns': t['ts'],
                }
                bpq = 0.0
            space = vbar_th - cb['volume']
            fill = min(rem, space)
            cb['high'] = max(cb['high'], t['price'])
            cb['low'] = min(cb['low'], t['price'])
            cb['close'] = t['price']
            cb['end_ns'] = t['ts']
            cb['volume'] += fill
            bpq += t['price'] * fill
            rem -= fill
            if cb['volume'] >= vbar_th:
                cb['vwap'] = bpq / cb['volume']
                vbars.append(cb)
                cb = None
    if cb and cb['volume'] > 0:
        cb['vwap'] = bpq / cb['volume']
        vbars.append(cb)

    # --- VPIN ---
    vpins = []
    vb_buy = vb_sell = vb_vol = 0
    for t in trades:
        rem = t['qty']
        while rem > 0:
            space = vpin_bv - vb_vol
            fill = min(rem, space)
            if t['side'] == 'BUY':
                vb_buy += fill
            else:
                vb_sell += fill
            vb_vol += fill
            rem -= fill
            if vb_vol >= vpin_bv:
                vpins.append(abs(vb_buy - vb_sell) / vb_vol)
                vb_buy = vb_sell = vb_vol = 0

    # --- Kyle's lambda ---
    kl = 0.0
    if len(trades) > 10:
        dms = [trades[i]['mid'] - trades[i - 1]['mid'] for i in range(1, len(trades))]
        svs = [
            (1 if trades[i]['side'] == 'BUY' else -1) * trades[i]['qty']
            for i in range(1, len(trades))
        ]
        n = len(dms)
        md = sum(dms) / n
        ms = sum(svs) / n
        cov = sum((dms[j] - md) * (svs[j] - ms) for j in range(n)) / n
        var = sum((svs[j] - ms) ** 2 for j in range(n)) / n
        kl = cov / var if var > 0 else 0.0

    return {
        'snapshots': snapshots,
        'metrics': {
            'total_trades': len(trades),
            'total_volume': tv,
            'buy_initiated_volume': bv,
            'sell_initiated_volume': sv,
            'vwap': vwap,
            'effective_spread_bps': wes,
            'realized_spread_bps': wrs,
            'price_impact_bps': wes - wrs,
        },
        'vpin_values': vpins,
        'volume_bars': vbars,
        'kyle_lambda': kl,
    }


@pytest.fixture(scope='module')
def expected():
    return _reference_solution()


@pytest.fixture(scope='module')
def results():
    with open('/app/results.json') as f:
        return json.load(f)


# ---- Structural tests ----

def test_results_file_exists():
    assert os.path.isfile('/app/results.json'), '/app/results.json not found'


def test_top_level_keys(results):
    for key in ('snapshots', 'metrics', 'vpin_values', 'volume_bars', 'kyle_lambda'):
        assert key in results, 'Missing top-level key: {}'.format(key)


def test_metrics_keys(results):
    required = [
        'total_trades', 'total_volume', 'buy_initiated_volume',
        'sell_initiated_volume', 'vwap', 'effective_spread_bps',
        'realized_spread_bps', 'price_impact_bps',
    ]
    for key in required:
        assert key in results['metrics'], 'Missing metric: {}'.format(key)


# ---- Snapshot tests ----

def test_snapshot_count(results, expected):
    assert len(results['snapshots']) == len(expected['snapshots']), \
        'Snapshot count mismatch: got {}, expected {}'.format(
            len(results['snapshots']), len(expected['snapshots']))


def test_snapshot_best_bid_ask(results, expected):
    for snap in results['snapshots']:
        ts = snap['timestamp_ns']
        assert ts in expected['snapshots'], \
            'Unexpected snapshot timestamp {}'.format(ts)
        exp = expected['snapshots'][ts]
        assert snap['best_bid'] == pytest.approx(exp['best_bid'], abs=1e-6), \
            'best_bid mismatch at ts={}'.format(ts)
        assert snap['best_ask'] == pytest.approx(exp['best_ask'], abs=1e-6), \
            'best_ask mismatch at ts={}'.format(ts)


def test_snapshot_mid_and_spread(results, expected):
    for snap in results['snapshots']:
        ts = snap['timestamp_ns']
        exp = expected['snapshots'][ts]
        if exp['mid_price'] is not None:
            assert snap['mid_price'] == pytest.approx(exp['mid_price'], abs=1e-6), \
                'mid_price mismatch at ts={}'.format(ts)
        if exp['spread'] is not None:
            assert snap['spread'] == pytest.approx(exp['spread'], abs=1e-4), \
                'spread mismatch at ts={}'.format(ts)


def test_snapshot_bid_levels(results, expected):
    for snap in results['snapshots']:
        ts = snap['timestamp_ns']
        exp = expected['snapshots'][ts]
        assert len(snap['bid_levels']) == len(exp['bid_levels']), \
            'bid level count mismatch at ts={}'.format(ts)
        for i, (ep, eq) in enumerate(exp['bid_levels']):
            assert snap['bid_levels'][i][0] == pytest.approx(ep, abs=1e-6), \
                'bid price mismatch level {} at ts={}'.format(i, ts)
            assert snap['bid_levels'][i][1] == eq, \
                'bid qty mismatch level {} at ts={}'.format(i, ts)


def test_snapshot_ask_levels(results, expected):
    for snap in results['snapshots']:
        ts = snap['timestamp_ns']
        exp = expected['snapshots'][ts]
        assert len(snap['ask_levels']) == len(exp['ask_levels']), \
            'ask level count mismatch at ts={}'.format(ts)
        for i, (ep, eq) in enumerate(exp['ask_levels']):
            assert snap['ask_levels'][i][0] == pytest.approx(ep, abs=1e-6), \
                'ask price mismatch level {} at ts={}'.format(i, ts)
            assert snap['ask_levels'][i][1] == eq, \
                'ask qty mismatch level {} at ts={}'.format(i, ts)


# ---- Exact metrics ----

def test_total_trades(results, expected):
    assert results['metrics']['total_trades'] == expected['metrics']['total_trades']


def test_total_volume(results, expected):
    assert results['metrics']['total_volume'] == expected['metrics']['total_volume']


def test_buy_sell_volumes(results, expected):
    assert results['metrics']['buy_initiated_volume'] == \
        expected['metrics']['buy_initiated_volume']
    assert results['metrics']['sell_initiated_volume'] == \
        expected['metrics']['sell_initiated_volume']


# ---- Approximate metrics ----

def test_vwap(results, expected):
    assert results['metrics']['vwap'] == pytest.approx(
        expected['metrics']['vwap'], rel=1e-4)


def test_effective_spread(results, expected):
    assert results['metrics']['effective_spread_bps'] == pytest.approx(
        expected['metrics']['effective_spread_bps'], rel=1e-3)


def test_realized_spread(results, expected):
    assert results['metrics']['realized_spread_bps'] == pytest.approx(
        expected['metrics']['realized_spread_bps'], abs=0.5)


def test_price_impact(results, expected):
    assert results['metrics']['price_impact_bps'] == pytest.approx(
        expected['metrics']['price_impact_bps'], abs=0.5)


# ---- Volume bars ----

def test_volume_bar_count(results, expected):
    assert len(results['volume_bars']) == len(expected['volume_bars']), \
        'Volume bar count mismatch: got {}, expected {}'.format(
            len(results['volume_bars']), len(expected['volume_bars']))


def test_volume_bar_threshold(results):
    """Every complete bar (all but possibly the last) must have exactly the threshold volume."""
    with open('/data/config.json') as f:
        threshold = json.load(f)['volume_bar_threshold']
    bars = results['volume_bars']
    for i, bar in enumerate(bars[:-1]):
        assert bar['volume'] == threshold, \
            'Bar {} volume {} != threshold {}'.format(i, bar['volume'], threshold)
    if bars:
        assert bars[-1]['volume'] <= threshold


def test_volume_bar_total_volume(results, expected):
    actual_total = sum(b['volume'] for b in results['volume_bars'])
    expected_total = sum(b['volume'] for b in expected['volume_bars'])
    assert actual_total == expected_total, \
        'Total volume across bars: got {}, expected {}'.format(actual_total, expected_total)


def test_volume_bar_ohlcv(results, expected):
    for i in range(min(len(results['volume_bars']), len(expected['volume_bars']))):
        bar = results['volume_bars'][i]
        exp = expected['volume_bars'][i]
        assert bar['open'] == pytest.approx(exp['open'], abs=1e-6), \
            'Bar {} open mismatch'.format(i)
        assert bar['high'] == pytest.approx(exp['high'], abs=1e-6), \
            'Bar {} high mismatch'.format(i)
        assert bar['low'] == pytest.approx(exp['low'], abs=1e-6), \
            'Bar {} low mismatch'.format(i)
        assert bar['close'] == pytest.approx(exp['close'], abs=1e-6), \
            'Bar {} close mismatch'.format(i)
        assert bar['vwap'] == pytest.approx(exp['vwap'], rel=1e-4), \
            'Bar {} vwap mismatch'.format(i)


# ---- VPIN ----

def test_vpin_count(results, expected):
    assert len(results['vpin_values']) == len(expected['vpin_values']), \
        'VPIN count mismatch: got {}, expected {}'.format(
            len(results['vpin_values']), len(expected['vpin_values']))


def test_vpin_range(results):
    for i, v in enumerate(results['vpin_values']):
        assert 0.0 <= v <= 1.0, 'VPIN[{}] = {} out of [0,1] range'.format(i, v)


def test_vpin_values(results, expected):
    for i in range(min(len(results['vpin_values']), len(expected['vpin_values']))):
        assert results['vpin_values'][i] == pytest.approx(
            expected['vpin_values'][i], abs=1e-4), \
            'VPIN bucket {} mismatch'.format(i)


# ---- Kyle's lambda ----

def test_kyle_lambda_sign(results, expected):
    if abs(expected['kyle_lambda']) > 1e-10:
        assert (results['kyle_lambda'] > 0) == (expected['kyle_lambda'] > 0), \
            "Kyle's lambda sign mismatch: got {}, expected {}".format(
                results['kyle_lambda'], expected['kyle_lambda'])


def test_kyle_lambda_value(results, expected):
    if abs(expected['kyle_lambda']) > 1e-10:
        assert results['kyle_lambda'] == pytest.approx(
            expected['kyle_lambda'], rel=0.05), \
            "Kyle's lambda mismatch: got {}, expected {}".format(
                results['kyle_lambda'], expected['kyle_lambda'])
