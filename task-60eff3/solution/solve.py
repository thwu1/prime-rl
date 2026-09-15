#!/usr/bin/env python3

"""Fix all bugs and extend the matching engine with advanced order types
and market data feed."""


def write_engine():
    """Write corrected engine.py with all order types and bug fixes."""
    code = '''\
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
        # FOK: pre-check liquidity
        if order.order_type == OrderType.FOK:
            if not self._check_fok_liquidity(order):
                return []

        all_trades = []
        while True:
            if order.side == Side.BUY:
                trades = self._match_buy(order)
            else:
                trades = self._match_sell(order)
            all_trades.extend(trades)

            # Aggressive iceberg: replenish display and continue matching
            if (order.remaining == 0
                    and order.order_type == OrderType.ICEBERG
                    and order.hidden_qty > 0):
                replenish = min(order.display_qty, order.hidden_qty)
                order.remaining = replenish
                order.hidden_qty -= replenish
                continue
            break

        # IOC: never rests in book
        if order.order_type == OrderType.IOC:
            return all_trades

        # Rest remainder in book
        if order.remaining > 0:
            self._add_to_book(order)

        return all_trades

    def _check_fok_liquidity(self, order: Order) -> bool:
        """Check if FOK order can be fully filled."""
        available = 0
        if order.side == Side.BUY:
            for price in sorted(self.asks.keys()):
                if price > order.price:
                    break
                for resting in self.asks[price]:
                    if resting.trader_id != order.trader_id:
                        available += resting.remaining + resting.hidden_qty
                    if available >= order.quantity:
                        return True
        else:
            for price in sorted(self.bids.keys(), reverse=True):
                if price < order.price:
                    break
                for resting in self.bids[price]:
                    if resting.trader_id != order.trader_id:
                        available += resting.remaining + resting.hidden_qty
                    if available >= order.quantity:
                        return True
        return available >= order.quantity

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
                fill_qty = min(buy_order.remaining, resting.remaining)
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
                    if (resting.order_type == OrderType.ICEBERG
                            and resting.hidden_qty > 0):
                        replenish = min(resting.display_qty, resting.hidden_qty)
                        resting.remaining = replenish
                        resting.hidden_qty -= replenish
                        level.pop(i)
                        level.append(resting)
                    else:
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
                fill_qty = min(sell_order.remaining, resting.remaining)
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
                    if (resting.order_type == OrderType.ICEBERG
                            and resting.hidden_qty > 0):
                        replenish = min(resting.display_qty, resting.hidden_qty)
                        resting.remaining = replenish
                        resting.hidden_qty -= replenish
                        level.pop(i)
                        level.append(resting)
                    else:
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
        return hashlib.sha256("\\n".join(parts).encode()).hexdigest()

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
'''
    with open("/app/engine.py", "w") as f:
        f.write(code)


def write_snapshot():
    """Write corrected snapshot.py with decimal precision and iceberg fields."""
    code = '''\
"""Snapshot save/restore for order book state."""
import json
from decimal import Decimal
from typing import Tuple

from models import Order, Side, OrderType
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
            "price": str(order.price),
            "quantity": order.quantity,
            "remaining": order.remaining,
            "timestamp": order.timestamp,
            "order_type": order.order_type.value,
            "display_qty": order.display_qty,
            "hidden_qty": order.hidden_qty,
        }

    def _deserialize_order(self, data: dict) -> Order:
        return Order(
            order_id=data["order_id"],
            trader_id=data["trader_id"],
            side=Side(data["side"]),
            price=Decimal(str(data["price"])),
            quantity=data["quantity"],
            remaining=data["remaining"],
            timestamp=data["timestamp"],
            order_type=OrderType(data.get("order_type", "LIMIT")),
            display_qty=data.get("display_qty", 0),
            hidden_qty=data.get("hidden_qty", 0),
        )
'''
    with open("/app/snapshot.py", "w") as f:
        f.write(code)


def write_replay():
    """Write corrected replay.py with boundary fix and order type handling."""
    code = '''\
"""Replay engine for rebuilding order book state from event journal."""
from decimal import Decimal

from models import Order, Side, OrderType
from engine import OrderBook
from journal import EventJournal
from snapshot import SnapshotManager


class ReplayEngine:
    def __init__(self):
        self.snapshot_mgr = SnapshotManager()

    def full_replay(self, journal_path: str) -> OrderBook:
        events = EventJournal.read_events(journal_path)
        book = OrderBook()
        for ev in events:
            self._process_event(book, ev)
        return book

    def snapshot_replay(self, journal_path: str, snapshot_path: str) -> OrderBook:
        book, last_seq = self.snapshot_mgr.load_snapshot(snapshot_path)
        events = EventJournal.read_events(journal_path)
        for ev in events:
            if ev["seq"] > last_seq:
                self._process_event(book, ev)
        return book

    def _process_event(self, book: OrderBook, ev: dict):
        if ev["type"] == "NEW_ORDER":
            otype = OrderType(ev.get("order_type", "LIMIT"))
            display = ev.get("display_qty", 0)
            qty = ev["quantity"]
            if otype == OrderType.ICEBERG:
                remaining = display
                hidden = qty - display
            else:
                remaining = qty
                hidden = 0
            order = Order(
                order_id=ev["order_id"],
                trader_id=ev["trader_id"],
                side=Side(ev["side"]),
                price=Decimal(ev["price"]),
                quantity=qty,
                remaining=remaining,
                timestamp=ev["timestamp"],
                order_type=otype,
                display_qty=display,
                hidden_qty=hidden,
            )
            book.process_new_order(order)
        elif ev["type"] == "CANCEL":
            book.cancel_order(ev["target_order_id"])
'''
    with open("/app/replay.py", "w") as f:
        f.write(code)


def write_market_data():
    """Write market_data.py implementation."""
    code = '''\
"""Market data feed generator."""


class MarketDataFeed:
    """Generates trade ticks and BBO updates from order book events."""

    def __init__(self):
        self.entries = []

    def record_event(self, book, trades, aggressor_side, timestamp):
        """Record market data after processing a new order event."""
        for trade in trades:
            self.entries.append({
                "type": "TRADE",
                "trade_id": trade.trade_id,
                "price": str(trade.price),
                "quantity": trade.quantity,
                "aggressor_side": aggressor_side.value,
                "timestamp": trade.timestamp,
            })
        best_bid_price, best_bid_qty = book.get_best_bid()
        best_ask_price, best_ask_qty = book.get_best_ask()
        self.entries.append({
            "type": "BBO",
            "best_bid_price": str(best_bid_price) if best_bid_price is not None else None,
            "best_bid_qty": best_bid_qty,
            "best_ask_price": str(best_ask_price) if best_ask_price is not None else None,
            "best_ask_qty": best_ask_qty,
            "timestamp": timestamp,
        })

    def record_cancel(self, book, timestamp):
        """Record market data after processing a cancel event."""
        best_bid_price, best_bid_qty = book.get_best_bid()
        best_ask_price, best_ask_qty = book.get_best_ask()
        self.entries.append({
            "type": "BBO",
            "best_bid_price": str(best_bid_price) if best_bid_price is not None else None,
            "best_bid_qty": best_bid_qty,
            "best_ask_price": str(best_ask_price) if best_ask_price is not None else None,
            "best_ask_qty": best_ask_qty,
            "timestamp": timestamp,
        })
'''
    with open("/app/market_data.py", "w") as f:
        f.write(code)


if __name__ == "__main__":
    write_engine()
    write_snapshot()
    write_replay()
    write_market_data()
    print("All fixes and extensions applied.")
