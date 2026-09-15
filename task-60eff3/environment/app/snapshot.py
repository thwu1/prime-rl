"""Snapshot save/restore for order book state."""
import json
from decimal import Decimal
from typing import Tuple

from models import Order, Side
from engine import OrderBook


class SnapshotManager:
    def save_snapshot(self, book: OrderBook, last_seq: int, path: str):
        data = {
            "last_seq": last_seq,
            "trade_counter": book._trade_counter,
            "bids": {},
            "asks": {},
        }

        for price, orders in book.bids.items():
            key = str(price)
            data["bids"][key] = [self._serialize_order(o) for o in orders]

        for price, orders in book.asks.items():
            key = str(price)
            data["asks"][key] = [self._serialize_order(o) for o in orders]

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_snapshot(self, path: str) -> Tuple[OrderBook, int]:
        with open(path, "r") as f:
            data = json.load(f)

        book = OrderBook()
        book.set_trade_counter(data["trade_counter"])

        for price_str, orders in data["bids"].items():
            price = Decimal(price_str)
            book.bids[price] = []
            for o_data in orders:
                order = self._deserialize_order(o_data)
                book.bids[price].append(order)
                book.orders[order.order_id] = order

        for price_str, orders in data["asks"].items():
            price = Decimal(price_str)
            book.asks[price] = []
            for o_data in orders:
                order = self._deserialize_order(o_data)
                book.asks[price].append(order)
                book.orders[order.order_id] = order

        return book, data["last_seq"]

    def _serialize_order(self, order: Order) -> dict:
        return {
            "order_id": order.order_id,
            "trader_id": order.trader_id,
            "side": order.side.value,
            "price": float(order.price),
            "quantity": order.quantity,
            "remaining": order.remaining,
            "timestamp": order.timestamp,
        }

    def _deserialize_order(self, data: dict) -> Order:
        return Order(
            order_id=data["order_id"],
            trader_id=data["trader_id"],
            side=Side(data["side"]),
            price=Decimal(data["price"]),
            quantity=data["quantity"],
            remaining=data["remaining"],
            timestamp=data["timestamp"],
        )
