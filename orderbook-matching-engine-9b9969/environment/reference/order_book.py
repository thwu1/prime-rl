# Exchange order book — price-time priority matching engine
#
# This module implements the core matching logic for a single-instrument
# limit order book. Orders are matched using strict price-time priority:
# the best-priced resting order is matched first, and among orders at the
# same price, the earliest-inserted order has priority (FIFO).
#
# Ask prices are stored as negated values in a sorted list so that the
# best (lowest) ask is always at the end of the list, mirroring the bid
# side where the best (highest) bid is at the end.

from bisect import bisect, insort_left
import collections

from .types import Lifespan, Side


class IOrderListener:
    """Interface for receiving order lifecycle events via callbacks."""

    def on_order_amended(self, now, order, volume_removed):
        """Called when the order volume is decreased via amend."""
        pass

    def on_order_cancelled(self, now, order, volume_removed):
        """Called when the order is cancelled and removed from the book."""
        pass

    def on_order_placed(self, now, order):
        """Called when a good-for-day order is placed in the book."""
        pass

    def on_order_filled(self, now, order, price, volume, fee):
        """Called when the order is partially or completely filled."""
        pass


class Order:
    """A limit order with price, volume, and lifecycle tracking."""
    __slots__ = ("client_order_id", "lifespan", "listener", "price",
                 "remaining_volume", "side", "total_fees", "volume")

    def __init__(self, client_order_id, lifespan, side, price, volume,
                 listener=None):
        self.client_order_id = client_order_id
        self.lifespan = lifespan
        self.side = side
        self.price = price
        self.remaining_volume = volume
        self.total_fees = 0
        self.volume = volume
        self.listener = listener


class OrderBook:
    """Price-time priority order book with maker/taker fee computation."""

    def __init__(self, maker_fee, taker_fee):
        self._maker_fee = maker_fee
        self._taker_fee = taker_fee
        self._ask_prices = []       # stored as -price, sorted ascending
        self._bid_prices = []       # sorted ascending; best bid is [-1]
        self._levels = {}           # price -> deque[Order]
        self._total_volumes = {}    # price -> total remaining volume

    def amend(self, now, order, new_volume):
        """Decrease an order's total volume.

        The volume removed is clamped so that remaining_volume cannot go
        below zero. If new_volume is less than the already-filled volume,
        all remaining volume is removed.
        """
        if order.remaining_volume > 0:
            fill_volume = order.volume - order.remaining_volume
            diff = order.volume - (fill_volume
                                   if new_volume < fill_volume
                                   else new_volume)
            self._remove_volume(order.price, diff, order.side)
            order.volume -= diff
            order.remaining_volume -= diff
            if order.listener:
                order.listener.on_order_amended(now, order, diff)

    def cancel(self, now, order):
        """Cancel an order, removing all remaining volume from the book."""
        if order.remaining_volume > 0:
            self._remove_volume(order.price, order.remaining_volume,
                                order.side)
            remaining = order.remaining_volume
            order.remaining_volume = 0
            if order.listener:
                order.listener.on_order_cancelled(now, order, remaining)

    def insert(self, now, order):
        """Insert a new order, matching against the opposite side first."""
        if (order.side == Side.SELL and self._bid_prices
                and order.price <= self._bid_prices[-1]):
            self._trade_ask(now, order)
        elif (order.side == Side.BUY and self._ask_prices
              and order.price >= -self._ask_prices[-1]):
            self._trade_bid(now, order)

        if order.remaining_volume > 0:
            if order.lifespan == Lifespan.FILL_AND_KILL:
                remaining = order.remaining_volume
                order.remaining_volume = 0
                if order.listener:
                    order.listener.on_order_cancelled(now, order, remaining)
            else:
                self._place(now, order)

    def _place(self, now, order):
        price = order.price
        if price not in self._levels:
            self._levels[price] = collections.deque()
            self._total_volumes[price] = 0
            if order.side == Side.SELL:
                insort_left(self._ask_prices, -price)
            else:
                insort_left(self._bid_prices, price)
        self._levels[price].append(order)
        self._total_volumes[price] += order.remaining_volume
        if order.listener:
            order.listener.on_order_placed(now, order)

    def _remove_volume(self, price, volume, side):
        if self._total_volumes[price] == volume:
            del self._levels[price]
            del self._total_volumes[price]
            if side == Side.SELL:
                self._ask_prices.pop(
                    bisect(self._ask_prices, -price) - 1)
            elif side == Side.BUY:
                self._bid_prices.pop(
                    bisect(self._bid_prices, price) - 1)
        else:
            self._total_volumes[price] -= volume

    def _trade_ask(self, now, order):
        """Match incoming sell against resting bids (highest first)."""
        best_bid = self._bid_prices[-1]
        while order.remaining_volume > 0 and best_bid >= order.price:
            self._trade_level(now, order, best_bid)
            if self._total_volumes.get(best_bid, 0) == 0:
                self._levels.pop(best_bid, None)
                self._total_volumes.pop(best_bid, None)
                self._bid_prices.pop()
                if not self._bid_prices:
                    break
                best_bid = self._bid_prices[-1]

    def _trade_bid(self, now, order):
        """Match incoming buy against resting asks (lowest first)."""
        best_ask = -self._ask_prices[-1]
        while order.remaining_volume > 0 and best_ask <= order.price:
            self._trade_level(now, order, best_ask)
            if self._total_volumes.get(best_ask, 0) == 0:
                self._levels.pop(best_ask, None)
                self._total_volumes.pop(best_ask, None)
                self._ask_prices.pop()
                if not self._ask_prices:
                    break
                best_ask = -self._ask_prices[-1]

    def _trade_level(self, now, order, best_price):
        """Match the incoming order against resting orders at best_price.

        For each individual fill, fees are computed for both the passive
        (maker) and aggressive (taker) sides and their respective
        callbacks are invoked.
        """
        order_queue = self._levels[best_price]
        total_volume = self._total_volumes[best_price]

        while order.remaining_volume > 0 and total_volume > 0:
            while order_queue[0].remaining_volume == 0:
                order_queue.popleft()
            passive = order_queue[0]
            volume = min(order.remaining_volume, passive.remaining_volume)

            maker_fee = round(best_price * volume * self._maker_fee)
            taker_fee = round(best_price * volume * self._taker_fee)

            total_volume -= volume
            passive.remaining_volume -= volume
            passive.total_fees += maker_fee
            if passive.listener:
                passive.listener.on_order_filled(
                    now, passive, best_price, volume, maker_fee)

            order.remaining_volume -= volume
            order.total_fees += taker_fee
            if order.listener:
                order.listener.on_order_filled(
                    now, order, best_price, volume, taker_fee)

        self._total_volumes[best_price] = total_volume
