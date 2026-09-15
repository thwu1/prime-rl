#!/usr/bin/env python3
"""
Queue-position-aware order fill simulator for HFT backtesting.
Implements ProbQueueModel with multiple probability functions.
"""
import math
import json
import numpy as np

# Event type constants
DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_CLEAR_EVENT = 3
DEPTH_SNAPSHOT_EVENT = 4
EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28


def event_type(ev_flags):
    return int(ev_flags) & 0xFF


def is_buy(ev_flags):
    return bool(int(ev_flags) & BUY_EVENT)


def is_sell(ev_flags):
    return bool(int(ev_flags) & SELL_EVENT)


class PowerProbQueueFunc:
    def __init__(self, n):
        self.n = float(n)

    def prob(self, front, back):
        fb = back ** self.n
        ff = front ** self.n
        denom = fb + ff
        if denom == 0:
            return 0.0
        return fb / denom


class LogProbQueueFunc:
    def prob(self, front, back):
        fb = math.log(1.0 + back)
        ff = math.log(1.0 + front)
        denom = fb + ff
        if denom == 0:
            return 0.0
        return fb / denom


class LogProbQueueFunc2:
    def prob(self, front, back):
        ft = math.log(1.0 + back + front)
        if ft == 0:
            return 0.0
        return math.log(1.0 + back) / ft


class PowerProbQueueFunc2:
    def __init__(self, n):
        self.n = float(n)

    def prob(self, front, back):
        total = back + front
        if total == 0:
            return 0.0
        return (back ** self.n) / (total ** self.n)


class PowerProbQueueFunc3:
    def __init__(self, n):
        self.n = float(n)

    def prob(self, front, back):
        total = front + back
        if total == 0:
            return 0.0
        return 1.0 - (front / total) ** self.n


class QueuePos:
    def __init__(self):
        self.front_q_qty = 0.0
        self.cum_trade_qty = 0.0


class OrderBook:
    def __init__(self, tick_size, lot_size):
        self._tick_size = tick_size
        self._lot_size = lot_size
        self._bids = {}
        self._asks = {}

    @property
    def tick_size(self):
        return self._tick_size

    @property
    def lot_size(self):
        return self._lot_size

    def price_to_tick(self, price):
        return round(price / self._tick_size)

    def tick_to_price(self, tick):
        return round(tick * self._tick_size, 10)

    @property
    def best_bid_tick(self):
        if not self._bids:
            return None
        return max(self._bids.keys())

    @property
    def best_ask_tick(self):
        if not self._asks:
            return None
        return min(self._asks.keys())

    @property
    def best_bid(self):
        t = self.best_bid_tick
        return self.tick_to_price(t) if t is not None else None

    @property
    def best_ask(self):
        t = self.best_ask_tick
        return self.tick_to_price(t) if t is not None else None

    def bid_qty_at_tick(self, tick):
        return self._bids.get(tick, 0.0)

    def ask_qty_at_tick(self, tick):
        return self._asks.get(tick, 0.0)

    def update_bid(self, price_tick, qty):
        prev = self._bids.get(price_tick, 0.0)
        if qty <= 0:
            self._bids.pop(price_tick, None)
        else:
            self._bids[price_tick] = qty
        return prev

    def update_ask(self, price_tick, qty):
        prev = self._asks.get(price_tick, 0.0)
        if qty <= 0:
            self._asks.pop(price_tick, None)
        else:
            self._asks[price_tick] = qty
        return prev


class ProbQueueModel:
    def __init__(self, prob_func):
        self.prob_func = prob_func

    def new_order(self, side, price_tick, book):
        qpos = QueuePos()
        if side == 'buy':
            qpos.front_q_qty = book.bid_qty_at_tick(price_tick)
        else:
            qpos.front_q_qty = book.ask_qty_at_tick(price_tick)
        return qpos

    def trade(self, qpos, qty):
        qpos.front_q_qty -= qty
        qpos.cum_trade_qty += qty

    def depth(self, qpos, prev_qty, new_qty):
        chg = prev_qty - new_qty
        chg -= qpos.cum_trade_qty
        qpos.cum_trade_qty = 0.0

        if chg < 0:
            qpos.front_q_qty = min(qpos.front_q_qty, new_qty)
            return

        front = qpos.front_q_qty
        back = prev_qty - front

        if front < 0 or back < 0:
            qpos.front_q_qty = min(qpos.front_q_qty, new_qty)
            return

        prob = self.prob_func.prob(front, back)
        if math.isinf(prob):
            prob = 1.0

        est_front = front - (1.0 - prob) * chg + min(0.0, back - prob * chg)
        qpos.front_q_qty = min(est_front, new_qty)

    def is_filled(self, qpos, lot_size):
        exec_lots = round(-qpos.front_q_qty / lot_size)
        if exec_lots > 0:
            qpos.front_q_qty = 0.0
            return exec_lots * lot_size
        return 0.0


class SimOrder:
    def __init__(self, order_id, side, price, qty, submit_event_idx, tick_size):
        self.order_id = order_id
        self.side = side
        self.price = price
        self.price_tick = round(price / tick_size)
        self.qty = qty
        self.submit_event_idx = submit_event_idx
        self.qpos = None
        self.active = False
        self.filled = False
        self.fill_event_idx = -1


def run_simulation(data, orders_spec, config, prob_func):
    tick_size = config['tick_size']
    lot_size = config['lot_size']
    maker_fee = config['maker_fee']

    book = OrderBook(tick_size, lot_size)
    model = ProbQueueModel(prob_func)

    sim_orders = []
    for o in orders_spec:
        sim_orders.append(SimOrder(
            o['order_id'], o['side'], o['price'],
            o['qty'], o['submit_event_idx'], tick_size
        ))

    book_snapshots = {}

    for idx in range(len(data)):
        ev = data[idx]
        ev_flags = int(ev['ev'])
        etype = event_type(ev_flags)
        price = float(ev['px'])
        qty = float(ev['qty'])
        price_tick = book.price_to_tick(price)

        # Activate orders at their submit time
        for order in sim_orders:
            if not order.active and not order.filled and order.submit_event_idx == idx:
                order.active = True
                order.qpos = model.new_order(order.side, order.price_tick, book)

        if etype in (DEPTH_EVENT, DEPTH_SNAPSHOT_EVENT):
            if is_buy(ev_flags):
                prev_qty = book.update_bid(price_tick, qty)
                if etype == DEPTH_EVENT:
                    for order in sim_orders:
                        if (order.active and not order.filled and
                                order.side == 'buy' and order.price_tick == price_tick):
                            model.depth(order.qpos, prev_qty, qty)
            elif is_sell(ev_flags):
                prev_qty = book.update_ask(price_tick, qty)
                if etype == DEPTH_EVENT:
                    for order in sim_orders:
                        if (order.active and not order.filled and
                                order.side == 'sell' and order.price_tick == price_tick):
                            model.depth(order.qpos, prev_qty, qty)

        elif etype == TRADE_EVENT:
            if is_sell(ev_flags):
                # Sell trade: aggressive seller hitting bids -> can fill buy orders
                for order in sim_orders:
                    if order.active and not order.filled and order.side == 'buy':
                        if order.price_tick > price_tick:
                            order.filled = True
                            order.fill_event_idx = idx
                        elif order.price_tick == price_tick:
                            model.trade(order.qpos, qty)
                            fill_qty = model.is_filled(order.qpos, lot_size)
                            if fill_qty > 0:
                                order.filled = True
                                order.fill_event_idx = idx

            elif is_buy(ev_flags):
                # Buy trade: aggressive buyer lifting asks -> can fill sell orders
                for order in sim_orders:
                    if order.active and not order.filled and order.side == 'sell':
                        if order.price_tick < price_tick:
                            order.filled = True
                            order.fill_event_idx = idx
                        elif order.price_tick == price_tick:
                            model.trade(order.qpos, qty)
                            fill_qty = model.is_filled(order.qpos, lot_size)
                            if fill_qty > 0:
                                order.filled = True
                                order.fill_event_idx = idx

        # Check marketable fills after book update
        for order in sim_orders:
            if order.active and not order.filled:
                if (order.side == 'buy' and book.best_ask_tick is not None
                        and order.price_tick >= book.best_ask_tick):
                    order.filled = True
                    order.fill_event_idx = idx
                elif (order.side == 'sell' and book.best_bid_tick is not None
                      and order.price_tick <= book.best_bid_tick):
                    order.filled = True
                    order.fill_event_idx = idx

        # Record snapshots at checkpoints
        if idx in (500, 1000, 1500):
            bb = book.best_bid
            ba = book.best_ask
            book_snapshots[f'event_{idx}'] = {
                'best_bid': bb if bb is not None else 0,
                'best_ask': ba if ba is not None else 0
            }

    # Compute P&L
    filled_ids = []
    position = 0.0
    cash = 0.0
    fees = 0.0

    for order in sim_orders:
        if order.filled:
            filled_ids.append(order.order_id)
            fee = abs(order.price * order.qty * maker_fee)
            fees += fee
            if order.side == 'buy':
                position += order.qty
                cash -= order.price * order.qty
            else:
                position -= order.qty
                cash += order.price * order.qty
            cash -= fee

    mid = 0.0
    if book.best_bid is not None and book.best_ask is not None:
        mid = (book.best_bid + book.best_ask) / 2

    pnl = cash + position * mid

    return {
        'filled_order_ids': sorted(filled_ids),
        'total_fills': len(filled_ids),
        'pnl': round(pnl, 6),
        'total_fees': round(fees, 6),
        'final_position': round(position, 6)
    }, book_snapshots
