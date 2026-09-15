"""Data models for the event-sourced order matching engine."""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    IOC = "IOC"
    FOK = "FOK"
    ICEBERG = "ICEBERG"


@dataclass
class Order:
    order_id: int
    trader_id: str
    side: Side
    price: Decimal
    quantity: int
    remaining: int
    timestamp: int
    order_type: OrderType = OrderType.LIMIT
    display_qty: int = 0
    hidden_qty: int = 0


@dataclass
class Trade:
    trade_id: int
    buy_order_id: int
    sell_order_id: int
    price: Decimal
    quantity: int
    timestamp: int
