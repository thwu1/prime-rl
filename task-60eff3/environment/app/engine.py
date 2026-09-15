"""Order matching engine with price-time priority."""
import hashlib
from decimal import Decimal
from typing import Dict, List

from models import Order, Trade, Side, OrderType


class OrderBook:
    def __init__(self):
        self.bids: Dict[Decimal, List[Order]] = {}
        self.asks: Dict[Decimal, List[Order]] = {}
        self.orders: Dict[int, Order] = {}
        self._trade_counter = 0
        self.trades: List[Trade] = []

    def next_trade_id(self) -> int:
        self._trade_counter += 1
        return self._trade_counter

    def set_trade_counter(self, val: int):
        self._trade_counter = val

    def process_new_order(self, order: Order) -> List[Trade]:
        if order.side == Side.BUY:
            trades = self._match_buy(order)
        else:
            trades = self._match_sell(order)

        if order.remaining > 0:
            self._add_to_book(order)

        return trades

    def _match_buy(self, buy_order: Order) -> List[Trade]:
        trades = []
        ask_prices = sorted(self.asks.keys())

        for price in ask_prices:
            if price > buy_order.price or buy_order.remaining <= 0:
                break

            level = self.asks[price]
            i = 0
            while i < len(level) and buy_order.remaining > 0:
                resting = level[i]

                if resting.trader_id == buy_order.trader_id:
                    level.pop(i)
                    self.orders.pop(resting.order_id, None)
                    continue

                fill_qty = min(buy_order.quantity, resting.remaining)

                trade = Trade(
                    trade_id=self.next_trade_id(),
                    buy_order_id=buy_order.order_id,
                    sell_order_id=resting.order_id,
                    price=price,
                    quantity=fill_qty,
                    timestamp=buy_order.timestamp,
                )
                trades.append(trade)
                self.trades.append(trade)

                buy_order.remaining -= fill_qty
                resting.remaining -= fill_qty

                if resting.remaining <= 0:
                    level.pop(i)
                    self.orders.pop(resting.order_id, None)
                else:
                    i += 1

            if not level:
                del self.asks[price]

        return trades

    def _match_sell(self, sell_order: Order) -> List[Trade]:
        trades = []
        bid_prices = sorted(self.bids.keys(), reverse=True)

        for price in bid_prices:
            if price < sell_order.price or sell_order.remaining <= 0:
                break

            level = self.bids[price]
            i = 0
            while i < len(level) and sell_order.remaining > 0:
                resting = level[i]

                if resting.trader_id == sell_order.trader_id:
                    level.pop(i)
                    self.orders.pop(resting.order_id, None)
                    continue

                fill_qty = min(sell_order.quantity, resting.remaining)

                trade = Trade(
                    trade_id=self.next_trade_id(),
                    buy_order_id=resting.order_id,
                    sell_order_id=sell_order.order_id,
                    price=price,
                    quantity=fill_qty,
                    timestamp=sell_order.timestamp,
                )
                trades.append(trade)
                self.trades.append(trade)

                sell_order.remaining -= fill_qty
                resting.remaining -= fill_qty

                if resting.remaining <= 0:
                    level.pop(i)
                    self.orders.pop(resting.order_id, None)
                else:
                    i += 1

            if not level:
                del self.bids[price]

        return trades

    def _add_to_book(self, order: Order):
        book = self.bids if order.side == Side.BUY else self.asks
        if order.price not in book:
            book[order.price] = []
        book[order.price].append(order)
        self.orders[order.order_id] = order

    def cancel_order(self, order_id: int) -> bool:
        if order_id not in self.orders:
            return False
        order = self.orders[order_id]
        book = self.bids if order.side == Side.BUY else self.asks
        if order.price in book:
            book[order.price] = [
                o for o in book[order.price] if o.order_id != order_id
            ]
            if not book[order.price]:
                del book[order.price]
        del self.orders[order_id]
        return True

    def get_state_hash(self) -> str:
        parts = []
        for price in sorted(self.bids.keys(), reverse=True):
            for o in self.bids[price]:
                parts.append(
                    f"B|{o.order_id}|{o.trader_id}|{o.price}|{o.remaining}|{o.hidden_qty}"
                )
        for price in sorted(self.asks.keys()):
            for o in self.asks[price]:
                parts.append(
                    f"A|{o.order_id}|{o.trader_id}|{o.price}|{o.remaining}|{o.hidden_qty}"
                )
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def get_best_bid(self):
        if not self.bids:
            return None, 0
        price = max(self.bids.keys())
        qty = sum(o.remaining for o in self.bids[price])
        return price, qty

    def get_best_ask(self):
        if not self.asks:
            return None, 0
        price = min(self.asks.keys())
        qty = sum(o.remaining for o in self.asks[price])
        return price, qty

    def get_summary(self) -> dict:
        return {
            "bid_levels": len(self.bids),
            "ask_levels": len(self.asks),
            "total_orders": len(self.orders),
            "total_trades": len(self.trades),
            "best_bid": str(max(self.bids.keys())) if self.bids else None,
            "best_ask": str(min(self.asks.keys())) if self.asks else None,
        }
