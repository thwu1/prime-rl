"""Replay engine for rebuilding order book state from event journal."""
from decimal import Decimal

from models import Order, Side
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
            if ev["seq"] >= last_seq:
                self._process_event(book, ev)
        return book

    def _process_event(self, book: OrderBook, ev: dict):
        if ev["type"] == "NEW_ORDER":
            order = Order(
                order_id=ev["order_id"],
                trader_id=ev["trader_id"],
                side=Side(ev["side"]),
                price=Decimal(ev["price"]),
                quantity=ev["quantity"],
                remaining=ev["quantity"],
                timestamp=ev["timestamp"],
            )
            book.process_new_order(order)
        elif ev["type"] == "CANCEL":
            book.cancel_order(ev["target_order_id"])
