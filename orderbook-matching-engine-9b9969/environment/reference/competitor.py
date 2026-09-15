# Competitor (trader) — order validation and position enforcement
#
# Each Competitor instance manages a single trader's active orders,
# validates new order submissions against exchange limits, and tracks
# position for breach detection. The validation checks in submit_insert
# are applied in a fixed order; the first failing check determines the
# rejection reason.

import bisect

from .account import Account
from .order_book import IOrderListener, Order, OrderBook
from .types import Lifespan, Side


class Competitor(IOrderListener):
    """A trader with order validation, tracking, and position limits."""

    def __init__(self, name, book, account, position_limit,
                 order_count_limit, active_volume_limit):
        self.name = name
        self.book = book
        self.account = account
        self.buy_prices = []        # sorted ascending
        self.sell_prices = []       # stored as -price, sorted ascending
        self.orders = {}            # client_order_id -> Order
        self.active_volume = 0
        self.position_limit = position_limit
        self.order_count_limit = order_count_limit
        self.active_volume_limit = active_volume_limit

    # ---- IOrderListener callbacks ----

    def on_order_amended(self, now, order, volume_removed):
        self.active_volume -= volume_removed
        if order.remaining_volume == 0:
            del self.orders[order.client_order_id]
            if order.side == Side.BUY:
                self.buy_prices.pop(
                    bisect.bisect(self.buy_prices, order.price) - 1)
            else:
                self.sell_prices.pop(
                    bisect.bisect(self.sell_prices, -order.price) - 1)

    def on_order_cancelled(self, now, order, volume_removed):
        self.active_volume -= volume_removed
        del self.orders[order.client_order_id]
        if order.side == Side.BUY:
            self.buy_prices.pop(
                bisect.bisect(self.buy_prices, order.price) - 1)
        else:
            self.sell_prices.pop(
                bisect.bisect(self.sell_prices, -order.price) - 1)

    def on_order_placed(self, now, order):
        pass

    def on_order_filled(self, now, order, price, volume, fee):
        self.active_volume -= volume
        if order.remaining_volume == 0:
            del self.orders[order.client_order_id]
            if order.side == Side.BUY:
                self.buy_prices.pop(
                    bisect.bisect(self.buy_prices, order.price) - 1)
            else:
                self.sell_prices.pop(
                    bisect.bisect(self.sell_prices, -order.price) - 1)
        self.account.transact(order.side, price, volume, fee)

    # ---- Order submission ----

    def submit_insert(self, now, client_order_id, side, price, volume,
                      lifespan):
        """Validate and submit an insert order.

        Returns a rejection reason string, or None on success.
        """
        if len(self.orders) >= self.order_count_limit:
            return "active-order-count"

        if self.active_volume + volume > self.active_volume_limit:
            return "active-volume"

        if ((side == Side.BUY and self.sell_prices
             and price >= -self.sell_prices[-1])
                or (side == Side.SELL and self.buy_prices
                    and price <= self.buy_prices[-1])):
            return "self-cross"

        order = Order(client_order_id, Lifespan(lifespan), Side(side),
                      price, volume, self)
        self.orders[client_order_id] = order
        if side == Side.BUY:
            bisect.insort(self.buy_prices, price)
        else:
            bisect.insort(self.sell_prices, -price)
        self.active_volume += volume
        self.book.insert(now, order)
        return None

    def submit_amend(self, now, client_order_id, new_volume):
        """Amend an order to a smaller volume. Ignored if order unknown
        or new_volume would increase the order's total volume."""
        if client_order_id in self.orders:
            order = self.orders[client_order_id]
            if new_volume < order.volume:
                self.book.amend(now, order, new_volume)

    def submit_cancel(self, now, client_order_id):
        """Cancel an active order. Ignored if order unknown."""
        if client_order_id in self.orders:
            self.book.cancel(now, self.orders[client_order_id])

    def check_position_breach(self):
        """Return True if this trader's absolute position exceeds the limit."""
        return abs(self.account.position) > self.position_limit

    def cancel_all_orders(self, now):
        """Cancel every remaining active order for this trader."""
        for oid in sorted(self.orders):
            order = self.orders[oid]
            if order.remaining_volume > 0:
                self.book.cancel(now, order)
