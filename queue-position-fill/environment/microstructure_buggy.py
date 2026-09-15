"""
Market microstructure fill simulation engine.
Port of hftbacktest's L2 queue position models.
"""

import math
import numpy as np

DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_SNAPSHOT_EVENT = 4
EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28


def _round_half_away(x):
    """Round to nearest integer, ties away from zero (matches Rust f64::round)."""
    if x >= 0:
        return int(math.floor(x + 0.5))
    else:
        return int(math.ceil(x - 0.5))


class OrderBook:
    def __init__(self, tick_size, lot_size):
        self.tick_size = tick_size
        self.lot_size = lot_size
        self._bids = {}
        self._asks = {}

    def process_event(self, event):
        """Process one event. Returns (prev_qty, new_qty) for depth/snapshot
        events on the affected side, or (0, 0) for trade events."""
        ev = int(event['ev'])
        px = float(event['px'])
        qty = float(event['qty'])

        is_depth = (ev & DEPTH_EVENT) != 0
        is_snapshot = (ev & DEPTH_SNAPSHOT_EVENT) != 0
        is_trade = (ev & TRADE_EVENT) != 0
        is_buy = (ev & BUY_EVENT) != 0
        is_sell = (ev & SELL_EVENT) != 0

        if is_trade:
            return (0.0, 0.0)

        if is_depth or is_snapshot:
            if is_buy:
                prev = self._bids.get(px, 0.0)
                self._bids[px] = qty
                return (prev, qty)
            elif is_sell:
                prev = self._asks.get(px, 0.0)
                self._asks[px] = qty
                return (prev, qty)

        return (0.0, 0.0)

    @property
    def best_bid(self):
        if not self._bids:
            return float('-inf')
        return max(self._bids.keys())

    @property
    def best_ask(self):
        if not self._asks:
            return float('inf')
        return min(self._asks.keys())

    @property
    def best_bid_qty(self):
        bb = self.best_bid
        return self._bids.get(bb, 0.0)

    @property
    def best_ask_qty(self):
        ba = self.best_ask
        return self._asks.get(ba, 0.0)

    def bid_qty_at(self, price):
        return self._bids.get(price, 0.0)

    def ask_qty_at(self, price):
        return self._asks.get(price, 0.0)


class RiskAdverseQueueModel:
    def __init__(self, lot_size):
        self.lot_size = lot_size

    def new_order(self, depth_qty):
        return {"front_q_qty": depth_qty}

    def trade(self, state, qty):
        state["front_q_qty"] -= qty

    def depth(self, state, prev_qty, new_qty):
        state["front_q_qty"] = min(state["front_q_qty"], new_qty)

    def is_filled(self, state):
        fq = state["front_q_qty"]
        exec_lots = _round_half_away(-fq / self.lot_size)
        if exec_lots > 0:
            state["front_q_qty"] = 0.0
            return exec_lots * self.lot_size
        return 0.0


class ProbQueueModel:
    def __init__(self, lot_size, prob_func):
        self.lot_size = lot_size
        self.prob_func = prob_func

    def new_order(self, depth_qty):
        return {"front_q_qty": depth_qty, "cum_trade_qty": 0.0}

    def trade(self, state, qty):
        state["front_q_qty"] -= qty
        state["cum_trade_qty"] += qty

    def depth(self, state, prev_qty, new_qty):
        chg = prev_qty - new_qty - state["cum_trade_qty"]

        if chg < 0.0:
            state["front_q_qty"] = min(state["front_q_qty"], new_qty)
            return

        state["cum_trade_qty"] = 0.0

        front = state["front_q_qty"]
        back = prev_qty - front

        prob = self.prob_func(front, back)
        if math.isinf(prob):
            prob = 1.0

        est_front = front - (1.0 - prob) * chg + min(back - prob * chg, 0.0)
        state["front_q_qty"] = min(est_front, new_qty)

    def is_filled(self, state):
        fq = state["front_q_qty"]
        exec_lots = _round_half_away(-fq / self.lot_size)
        if exec_lots > 0:
            state["front_q_qty"] = 0.0
            return exec_lots * self.lot_size
        return 0.0


def power_prob_func(n):
    """Power probability: f(x) = x**n, prob = f(back)/(f(back)+f(front))."""
    def prob(front, back):
        fb = back ** n
        ff = front ** n
        denom = fb + ff
        if denom == 0:
            return 0.0
        return fb / denom
    return prob


def log_prob_func():
    """Log probability: f(x) = ln(1+x), prob = f(back)/(f(back)+f(front))."""
    def prob(front, back):
        fb = math.log(1.0 + back)
        ff = math.log(1.0 + front)
        denom = fb + ff
        if denom == 0:
            return 0.0
        return fb / denom
    return prob
