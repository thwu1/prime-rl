#!/usr/bin/env python3
"""
Reference solution for the queue position fill simulator.
Reads binary event data and Rust source to understand and implement the queue models.
"""

import numpy as np
import json
import math
import os

# Event dtype matching the binary layout in layout.txt
EVENT_DTYPE = np.dtype([
    ('ev', '<u8'), ('exch_ts', '<i8'), ('local_ts', '<i8'), ('px', '<f8'),
    ('qty', '<f8'), ('order_id', '<u8'), ('ival', '<i8'), ('fval', '<f8')
], align=True)

# Event flags (from types.rs)
DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_CLEAR_EVENT = 3
DEPTH_SNAPSHOT_EVENT = 4
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28


def event_base_type(ev):
    return int(ev) & 0xF


def event_has_flag(ev, flag):
    return (int(ev) & flag) != 0


# === Probability Functions (ported from queue.rs) ===

def power_prob_func(n):
    def prob(front, back):
        fb = back ** n
        ff = front ** n
        d = fb + ff
        return fb / d if d != 0 else 0.0
    return prob


def log_prob_func():
    def prob(front, back):
        fb = math.log(1.0 + back)
        ff = math.log(1.0 + front)
        d = fb + ff
        return fb / d if d != 0 else 0.0
    return prob


def log_prob2_func():
    def prob(front, back):
        fb = math.log(1.0 + back)
        ft = math.log(1.0 + back + front)
        return fb / ft if ft != 0 else 0.0
    return prob


def power_prob3_func(n):
    def prob(front, back):
        d = front + back
        if d == 0:
            return 0.0
        return 1.0 - (front / d) ** n
    return prob


# === Queue State ===

class QueueState:
    __slots__ = ['front_q_qty', 'cum_trade_qty', 'lot_size',
                 'filled', 'fill_event_idx', 'fill_exch_ts']

    def __init__(self, front_q_qty, lot_size):
        self.front_q_qty = front_q_qty
        self.cum_trade_qty = 0.0
        self.lot_size = lot_size
        self.filled = False
        self.fill_event_idx = None
        self.fill_exch_ts = None

    def check_fill(self, event_idx, exch_ts):
        if self.filled:
            return
        exec_lots = int(round(-self.front_q_qty / self.lot_size))
        if exec_lots > 0:
            self.filled = True
            self.fill_event_idx = event_idx
            self.fill_exch_ts = int(exch_ts)
            self.front_q_qty = 0.0

    def force_fill(self, event_idx, exch_ts):
        if self.filled:
            return
        self.filled = True
        self.fill_event_idx = event_idx
        self.fill_exch_ts = int(exch_ts)
        self.front_q_qty = 0.0


# === Queue Models (ported from queue.rs) ===

class RiskAdverseModel:
    name = "risk_adverse"

    def trade(self, state, qty):
        if state.filled:
            return
        state.front_q_qty -= qty

    def depth(self, state, prev_qty, new_qty):
        if state.filled:
            return
        state.front_q_qty = min(state.front_q_qty, new_qty)


class ProbQueueModel:
    def __init__(self, name, prob_func):
        self.name = name
        self.prob_func = prob_func

    def trade(self, state, qty):
        if state.filled:
            return
        state.front_q_qty -= qty
        state.cum_trade_qty += qty

    def depth(self, state, prev_qty, new_qty):
        if state.filled:
            return
        chg = prev_qty - new_qty
        chg -= state.cum_trade_qty
        state.cum_trade_qty = 0.0

        if chg < 0.0:
            state.front_q_qty = min(state.front_q_qty, new_qty)
            return

        front = state.front_q_qty
        back = prev_qty - front

        prob = self.prob_func(front, back)
        if math.isinf(prob):
            prob = 1.0

        est_front = front - (1.0 - prob) * chg + min(back - prob * chg, 0.0)
        state.front_q_qty = min(est_front, new_qty)


def compute_analysis(results):
    model_names = list(results["orders"][0]["models"].keys())

    fill_counts = {}
    for m in model_names:
        fill_counts[m] = sum(1 for o in results["orders"] if o["models"][m]["filled"])

    ranking = sorted(model_names, key=lambda m: (-fill_counts[m], m))

    sorted_models = sorted(model_names)
    pairwise = {}
    for i in range(len(sorted_models)):
        for j in range(i + 1, len(sorted_models)):
            a, b = sorted_models[i], sorted_models[j]
            key = f"{a}__{b}"
            count = sum(
                1 for o in results["orders"]
                if o["models"][a]["filled"] != o["models"][b]["filled"]
            )
            pairwise[key] = count

    sensitive = sorted([
        o["order_id"] for o in results["orders"]
        if len(set(o["models"][m]["filled"] for m in model_names)) > 1
    ])

    most_conservative = sorted(model_names, key=lambda m: (fill_counts[m], m))[0]
    most_aggressive = sorted(model_names, key=lambda m: (-fill_counts[m], m))[0]

    return {
        "fill_counts": fill_counts,
        "aggressiveness_ranking": ranking,
        "pairwise_disagreements": pairwise,
        "model_sensitive_orders": sensitive,
        "most_conservative_model": most_conservative,
        "most_aggressive_model": most_aggressive,
    }


def run_simulation():
    # Read binary event data
    events = np.fromfile('/app/data/events.bin', dtype=EVENT_DTYPE)

    with open('/app/data/orders.json') as f:
        orders = json.load(f)
    with open('/app/data/config.json') as f:
        config = json.load(f)

    tick_size = config['tick_size']
    lot_size = config['lot_size']

    models = [
        RiskAdverseModel(),
        ProbQueueModel("power_prob_n2", power_prob_func(2.0)),
        ProbQueueModel("log_prob", log_prob_func()),
        ProbQueueModel("log_prob2", log_prob2_func()),
        ProbQueueModel("power_prob3_n3", power_prob3_func(3.0)),
    ]

    bid_book = {}
    ask_book = {}

    order_states = {}
    order_specs = {o['id']: o for o in orders}
    placed_orders = set()

    total_trade_events = 0
    total_depth_events = 0

    for ei in range(len(events)):
        ev = int(events[ei]['ev'])
        exch_ts = int(events[ei]['exch_ts'])
        px = float(events[ei]['px'])
        qty = float(events[ei]['qty'])

        bt = event_base_type(ev)
        is_buy = event_has_flag(ev, BUY_EVENT)
        is_sell = event_has_flag(ev, SELL_EVENT)
        pt = int(round(px / tick_size))

        for order in orders:
            oid = order['id']
            if oid not in placed_orders and exch_ts >= order['place_at_ts']:
                placed_orders.add(oid)
                if order['side'] == 'buy':
                    bq = bid_book.get(order['price_tick'], 0.0)
                else:
                    bq = ask_book.get(order['price_tick'], 0.0)
                order_states[oid] = {}
                for m in models:
                    order_states[oid][m.name] = QueueState(bq, lot_size)

        if bt == DEPTH_CLEAR_EVENT:
            if is_buy:
                bid_book.clear()
            elif is_sell:
                ask_book.clear()

        elif bt == DEPTH_SNAPSHOT_EVENT:
            if is_buy:
                bid_book[pt] = qty
            elif is_sell:
                ask_book[pt] = qty

        elif bt == DEPTH_EVENT:
            total_depth_events += 1

            if is_buy:
                prev = bid_book.get(pt, 0.0)
                if qty <= 0:
                    bid_book.pop(pt, None)
                else:
                    bid_book[pt] = qty

                for oid in order_states:
                    spec = order_specs[oid]
                    if spec['side'] == 'buy' and spec['price_tick'] == pt:
                        for m in models:
                            s = order_states[oid][m.name]
                            m.depth(s, prev, qty)
                            s.check_fill(ei, exch_ts)

            elif is_sell:
                prev = ask_book.get(pt, 0.0)
                if qty <= 0:
                    ask_book.pop(pt, None)
                else:
                    ask_book[pt] = qty

                for oid in order_states:
                    spec = order_specs[oid]
                    if spec['side'] == 'sell' and spec['price_tick'] == pt:
                        for m in models:
                            s = order_states[oid][m.name]
                            m.depth(s, prev, qty)
                            s.check_fill(ei, exch_ts)

        elif bt == TRADE_EVENT:
            total_trade_events += 1

            if is_sell:
                for oid in order_states:
                    spec = order_specs[oid]
                    if spec['side'] == 'buy':
                        if spec['price_tick'] > pt:
                            for m in models:
                                order_states[oid][m.name].force_fill(ei, exch_ts)
                        elif spec['price_tick'] == pt:
                            for m in models:
                                s = order_states[oid][m.name]
                                m.trade(s, qty)
                                s.check_fill(ei, exch_ts)

            elif is_buy:
                for oid in order_states:
                    spec = order_specs[oid]
                    if spec['side'] == 'sell':
                        if spec['price_tick'] < pt:
                            for m in models:
                                order_states[oid][m.name].force_fill(ei, exch_ts)
                        elif spec['price_tick'] == pt:
                            for m in models:
                                s = order_states[oid][m.name]
                                m.trade(s, qty)
                                s.check_fill(ei, exch_ts)

    bbt = max(bid_book.keys()) if bid_book else None
    bat = min(ask_book.keys()) if ask_book else None

    results = {
        "orders": [],
        "book_state": {
            "final_best_bid_tick": bbt,
            "final_best_ask_tick": bat,
            "final_best_bid_qty": round(bid_book.get(bbt, 0.0), 6) if bbt is not None else 0.0,
            "final_best_ask_qty": round(ask_book.get(bat, 0.0), 6) if bat is not None else 0.0,
            "total_trade_events": total_trade_events,
            "total_depth_events": total_depth_events,
        }
    }

    for order in orders:
        oid = order['id']
        if oid not in order_states:
            continue
        or_ = {
            "order_id": oid,
            "side": order['side'],
            "price_tick": order['price_tick'],
            "qty": order['qty'],
            "models": {}
        }
        for m in models:
            s = order_states[oid][m.name]
            or_["models"][m.name] = {
                "filled": s.filled,
                "fill_event_idx": s.fill_event_idx,
                "fill_exch_ts": s.fill_exch_ts,
                "final_front_q_qty": round(s.front_q_qty, 6)
            }
        results["orders"].append(or_)

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    analysis = compute_analysis(results)
    with open('/app/analysis.json', 'w') as f:
        json.dump(analysis, f, indent=2)

    return results


if __name__ == '__main__':
    r = run_simulation()
    print(json.dumps(r, indent=2))
