
"""Tests for the exchange matching engine and trade surveillance pipeline.

Verifies:
- Limit order matching correctness (partial fills, no overfill)
- IOC order behavior (partial fill, immediate cancel of remainder)
- FOK order behavior (liquidity pre-check including iceberg hidden qty)
- Iceberg order mechanics (display/hidden, replenishment, time priority loss)
- Snapshot fidelity (Decimal precision, iceberg field preservation)
- Replay determinism (boundary correctness, mixed-type scenario)
- Market data feed (trade ticks, BBO updates)
- Surveillance database (schema, row counts)
- Surveillance outputs (wash pairs, cancel ratios, VWAP)
"""
import os
import sqlite3 as sqlite3_mod
import sys
import tempfile

import pytest

sys.path.insert(0, "/app")

from decimal import Decimal

from engine import OrderBook
from journal import EventJournal
from models import Order, Side, OrderType
from replay import ReplayEngine
from snapshot import SnapshotManager
from market_data import MarketDataFeed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_order(oid, trader, side, price, qty, ts=0,
               order_type=OrderType.LIMIT, display_qty=0):
    if order_type == OrderType.ICEBERG:
        remaining = display_qty
        hidden = qty - display_qty
    else:
        remaining = qty
        hidden = 0
    return Order(oid, trader, side, Decimal(price), qty, remaining, ts,
                 order_type, display_qty, hidden)


MIXED_SCENARIO = [
    {"type": "NEW_ORDER", "order_id": 1, "trader_id": "ALICE", "side": "SELL",
     "price": "100.10", "quantity": 10, "timestamp": 1000,
     "order_type": "LIMIT", "display_qty": 0},
    {"type": "NEW_ORDER", "order_id": 2, "trader_id": "BOB", "side": "SELL",
     "price": "100.20", "quantity": 15, "timestamp": 2000,
     "order_type": "LIMIT", "display_qty": 0},
    {"type": "NEW_ORDER", "order_id": 3, "trader_id": "CHARLIE", "side": "BUY",
     "price": "99.90", "quantity": 20, "timestamp": 3000,
     "order_type": "LIMIT", "display_qty": 0},
    {"type": "NEW_ORDER", "order_id": 4, "trader_id": "DAVE", "side": "SELL",
     "price": "100.10", "quantity": 30, "timestamp": 4000,
     "order_type": "ICEBERG", "display_qty": 10},
    {"type": "NEW_ORDER", "order_id": 5, "trader_id": "EVE", "side": "BUY",
     "price": "100.10", "quantity": 15, "timestamp": 5000,
     "order_type": "IOC", "display_qty": 0},
    # --- snapshot taken here (after seq 5) ---
    {"type": "NEW_ORDER", "order_id": 6, "trader_id": "FRANK", "side": "BUY",
     "price": "99.90", "quantity": 100, "timestamp": 6000,
     "order_type": "FOK", "display_qty": 0},
    {"type": "CANCEL", "target_order_id": 3, "timestamp": 7000},
    {"type": "NEW_ORDER", "order_id": 8, "trader_id": "GEORGE", "side": "BUY",
     "price": "100.20", "quantity": 25, "timestamp": 8000,
     "order_type": "LIMIT", "display_qty": 0},
]

MIXED_SNAP_SEQ = 5


def run_live_mixed(journal_path, snapshot_path):
    """Process the mixed scenario live, writing journal and snapshot."""
    book = OrderBook()
    journal = EventJournal()
    snap = SnapshotManager()

    with open(journal_path, "w") as f:
        for ev in MIXED_SCENARIO:
            if ev["type"] == "NEW_ORDER":
                otype = OrderType(ev.get("order_type", "LIMIT"))
                dqty = ev.get("display_qty", 0)
                qty = ev["quantity"]
                if otype == OrderType.ICEBERG:
                    rem = dqty
                    hid = qty - dqty
                else:
                    rem = qty
                    hid = 0
                journal.write_new_order(
                    f, ev["order_id"], ev["trader_id"],
                    ev["side"], ev["price"], qty,
                    ev["timestamp"], ev.get("order_type", "LIMIT"),
                    dqty,
                )
                order = Order(
                    ev["order_id"], ev["trader_id"],
                    Side(ev["side"]), Decimal(ev["price"]),
                    qty, rem, ev["timestamp"],
                    otype, dqty, hid,
                )
                book.process_new_order(order)
            elif ev["type"] == "CANCEL":
                journal.write_cancel(f, ev["target_order_id"], ev["timestamp"])
                book.cancel_order(ev["target_order_id"])

            if journal.seq == MIXED_SNAP_SEQ:
                snap.save_snapshot(book, MIXED_SNAP_SEQ, snapshot_path)

    return book


# ---------------------------------------------------------------------------
# Tests: Limit Order Correctness
# ---------------------------------------------------------------------------

class TestLimitOrders:

    def test_partial_fill_uses_remaining(self):
        """Fill qty must use order.remaining, not order.quantity."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.SELL, "100.10", 5, 1000))
        book.process_new_order(make_order(2, "B", Side.SELL, "100.10", 20, 2000))
        trades = book.process_new_order(
            make_order(3, "C", Side.BUY, "100.10", 8, 3000)
        )
        assert len(trades) == 2, f"Expected 2 trades, got {len(trades)}"
        assert trades[0].quantity == 5
        assert trades[1].quantity == 3
        assert book.orders[2].remaining == 17
        assert 3 not in book.orders

    def test_no_overfill(self):
        """Total filled must never exceed order quantity."""
        book = OrderBook()
        for i in range(1, 4):
            book.process_new_order(
                make_order(i, f"S{i}", Side.SELL, "100.00", 10, i * 1000)
            )
        buy = make_order(10, "BUYER", Side.BUY, "100.00", 15, 50000)
        trades = book.process_new_order(buy)
        total = sum(t.quantity for t in trades)
        assert total == 15, f"Total fill should be 15, got {total}"
        assert buy.remaining == 0


# ---------------------------------------------------------------------------
# Tests: IOC Orders
# ---------------------------------------------------------------------------

class TestIOCOrders:

    def test_ioc_partial_fill_not_resting(self):
        """IOC remainder must be cancelled, never resting in book."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.SELL, "100.10", 10, 1000))
        ioc = make_order(2, "B", Side.BUY, "100.10", 15, 2000, OrderType.IOC)
        trades = book.process_new_order(ioc)
        assert len(trades) == 1
        assert trades[0].quantity == 10
        assert 2 not in book.orders, "IOC remainder must not rest in book"
        assert len(book.bids) == 0

    def test_ioc_no_match_not_resting(self):
        """IOC with no match must not rest in book."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.SELL, "100.20", 10, 1000))
        ioc = make_order(2, "B", Side.BUY, "100.10", 15, 2000, OrderType.IOC)
        trades = book.process_new_order(ioc)
        assert len(trades) == 0
        assert 2 not in book.orders
        assert len(book.bids) == 0


# ---------------------------------------------------------------------------
# Tests: FOK Orders
# ---------------------------------------------------------------------------

class TestFOKOrders:

    def test_fok_reject_insufficient_liquidity(self):
        """FOK must be rejected when available liquidity < order qty."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.SELL, "100.10", 10, 1000))
        fok = make_order(2, "B", Side.BUY, "100.10", 15, 2000, OrderType.FOK)
        trades = book.process_new_order(fok)
        assert len(trades) == 0, "FOK should be rejected"
        assert book.orders[1].remaining == 10, "Sell order must be unchanged"
        assert 2 not in book.orders

    def test_fok_accept_sufficient_liquidity(self):
        """FOK must execute when sufficient liquidity exists."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.SELL, "100.10", 10, 1000))
        book.process_new_order(make_order(2, "B", Side.SELL, "100.10", 10, 2000))
        fok = make_order(3, "C", Side.BUY, "100.10", 15, 3000, OrderType.FOK)
        trades = book.process_new_order(fok)
        assert len(trades) == 2
        assert trades[0].quantity == 10
        assert trades[1].quantity == 5
        assert 1 not in book.orders
        assert book.orders[2].remaining == 5

    def test_fok_considers_iceberg_hidden(self):
        """FOK liquidity check must include iceberg hidden qty."""
        book = OrderBook()
        book.process_new_order(make_order(
            1, "A", Side.SELL, "100.10", 20, 1000,
            OrderType.ICEBERG, display_qty=5
        ))
        fok = make_order(2, "B", Side.BUY, "100.10", 12, 2000, OrderType.FOK)
        trades = book.process_new_order(fok)
        assert len(trades) == 3, f"Expected 3 trades, got {len(trades)}"
        assert sum(t.quantity for t in trades) == 12
        assert 2 not in book.orders
        assert book.orders[1].remaining == 3
        assert book.orders[1].hidden_qty == 5


# ---------------------------------------------------------------------------
# Tests: Iceberg Orders
# ---------------------------------------------------------------------------

class TestIcebergOrders:

    def test_iceberg_resting_replenishment(self):
        """Resting iceberg must replenish display from hidden when consumed."""
        book = OrderBook()
        book.process_new_order(make_order(
            1, "A", Side.SELL, "100.00", 25, 1000,
            OrderType.ICEBERG, display_qty=10
        ))
        trades = book.process_new_order(
            make_order(2, "B", Side.BUY, "100.00", 22, 2000)
        )
        assert len(trades) == 3
        assert trades[0].quantity == 10
        assert trades[1].quantity == 10
        assert trades[2].quantity == 2
        assert book.orders[1].remaining == 3
        assert book.orders[1].hidden_qty == 0

    def test_iceberg_time_priority_loss(self):
        """Replenished iceberg must lose time priority (move to back)."""
        book = OrderBook()
        book.process_new_order(make_order(
            1, "A", Side.SELL, "100.00", 15, 1000,
            OrderType.ICEBERG, display_qty=5
        ))
        book.process_new_order(
            make_order(2, "B", Side.SELL, "100.00", 8, 2000)
        )
        trades = book.process_new_order(
            make_order(3, "C", Side.BUY, "100.00", 9, 3000)
        )
        assert len(trades) == 2
        assert trades[0].quantity == 5, "First fill from iceberg (front of queue)"
        assert trades[0].sell_order_id == 1
        assert trades[1].quantity == 4, "Second fill from limit (iceberg went to back)"
        assert trades[1].sell_order_id == 2
        assert book.orders[2].remaining == 4
        assert book.orders[1].remaining == 5
        assert book.orders[1].hidden_qty == 5

    def test_aggressive_iceberg_multi_fill(self):
        """Aggressive iceberg must replenish and continue matching."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.SELL, "100.00", 3, 1000))
        book.process_new_order(make_order(2, "B", Side.SELL, "100.00", 6, 2000))
        ice = make_order(3, "C", Side.BUY, "100.00", 20, 3000,
                         OrderType.ICEBERG, display_qty=5)
        trades = book.process_new_order(ice)
        assert len(trades) == 3
        assert trades[0].quantity == 3
        assert trades[1].quantity == 2
        assert trades[2].quantity == 4
        assert 1 not in book.orders
        assert 2 not in book.orders
        assert 3 in book.orders
        assert book.orders[3].remaining == 1
        assert book.orders[3].hidden_qty == 10

    def test_aggressive_iceberg_full_fill(self):
        """Aggressive iceberg fills completely across multiple replenishments."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.SELL, "100.00", 20, 1000))
        ice = make_order(2, "B", Side.BUY, "100.00", 15, 2000,
                         OrderType.ICEBERG, display_qty=5)
        trades = book.process_new_order(ice)
        assert len(trades) == 3
        assert all(t.quantity == 5 for t in trades)
        assert book.orders[1].remaining == 5
        assert 2 not in book.orders


# ---------------------------------------------------------------------------
# Tests: Snapshot Fidelity
# ---------------------------------------------------------------------------

class TestSnapshotFidelity:

    def test_decimal_precision(self):
        """Decimal prices must survive snapshot round-trip exactly."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.SELL, "100.10", 10, 1000))
        book.process_new_order(make_order(2, "B", Side.BUY, "99.95", 15, 2000))
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "snap.json")
            snap = SnapshotManager()
            snap.save_snapshot(book, 2, path)
            restored, last_seq = snap.load_snapshot(path)
        assert last_seq == 2
        assert Decimal("100.10") in restored.asks, (
            "Ask price 100.10 missing after restore"
        )
        assert Decimal("99.95") in restored.bids, (
            "Bid price 99.95 missing after restore"
        )
        assert restored.orders[1].price == Decimal("100.10")
        assert restored.orders[2].price == Decimal("99.95")

    def test_iceberg_fields_preserved(self):
        """Snapshot must preserve iceberg order_type, display_qty, hidden_qty."""
        book = OrderBook()
        book.process_new_order(make_order(
            1, "A", Side.SELL, "100.10", 20, 1000,
            OrderType.ICEBERG, display_qty=5
        ))
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "snap.json")
            snap = SnapshotManager()
            snap.save_snapshot(book, 1, path)
            restored, _ = snap.load_snapshot(path)
        o = restored.orders[1]
        assert o.order_type == OrderType.ICEBERG
        assert o.display_qty == 5
        assert o.hidden_qty == 15
        assert o.remaining == 5

    def test_cancel_after_restore(self):
        """Cancel must work correctly after snapshot restore."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.BUY, "99.95", 10, 1000))
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "snap.json")
            snap = SnapshotManager()
            snap.save_snapshot(book, 1, path)
            restored, _ = snap.load_snapshot(path)
        assert restored.cancel_order(1) is True
        assert 1 not in restored.orders
        assert len(restored.bids) == 0


# ---------------------------------------------------------------------------
# Tests: Replay Determinism
# ---------------------------------------------------------------------------

class TestReplayDeterminism:

    def test_boundary_no_duplicate(self):
        """Snapshot boundary event must not be replayed."""
        book = OrderBook()
        book.process_new_order(make_order(1, "A", Side.BUY, "100.00", 10, 1000))
        book.process_new_order(make_order(2, "B", Side.SELL, "200.00", 15, 2000))
        with tempfile.TemporaryDirectory() as td:
            snap_path = os.path.join(td, "snap.json")
            journal_path = os.path.join(td, "journal.jsonl")
            snap = SnapshotManager()
            snap.save_snapshot(book, 2, snap_path)
            journal = EventJournal()
            with open(journal_path, "w") as f:
                journal.write_new_order(f, 1, "A", "BUY", "100.00", 10, 1000)
                journal.write_new_order(f, 2, "B", "SELL", "200.00", 15, 2000)
                journal.write_new_order(f, 3, "C", "BUY", "90.00", 5, 3000)
            engine = ReplayEngine()
            replayed = engine.snapshot_replay(journal_path, snap_path)
        assert len(replayed.orders) == 3
        total_in_levels = sum(
            len(orders) for orders in replayed.bids.values()
        ) + sum(len(orders) for orders in replayed.asks.values())
        assert total_in_levels == 3, (
            f"Expected 3 orders in levels, got {total_in_levels} "
            "(boundary event may have been replayed)"
        )

    def test_mixed_scenario_matches_live(self):
        """Snapshot+replay with mixed order types must match live state."""
        with tempfile.TemporaryDirectory() as td:
            jp = os.path.join(td, "journal.jsonl")
            sp = os.path.join(td, "snap.json")

            live_book = run_live_mixed(jp, sp)
            live_hash = live_book.get_state_hash()

            engine = ReplayEngine()
            replay_book = engine.snapshot_replay(jp, sp)
            replay_hash = replay_book.get_state_hash()

        assert live_hash == replay_hash, (
            f"State divergence: live={live_book.get_summary()}, "
            f"replay={replay_book.get_summary()}"
        )


# ---------------------------------------------------------------------------
# Tests: Market Data Feed
# ---------------------------------------------------------------------------

class TestMarketData:

    def test_trade_ticks(self):
        """Trade ticks must appear for each fill with correct fields."""
        book = OrderBook()
        feed = MarketDataFeed()

        sell = make_order(1, "A", Side.SELL, "100.10", 10, 1000)
        trades = book.process_new_order(sell)
        feed.record_event(book, trades, sell.side, sell.timestamp)

        buy = make_order(2, "B", Side.BUY, "100.10", 5, 2000)
        trades = book.process_new_order(buy)
        feed.record_event(book, trades, buy.side, buy.timestamp)

        trade_entries = [e for e in feed.entries if e["type"] == "TRADE"]
        assert len(trade_entries) == 1
        assert trade_entries[0]["quantity"] == 5
        assert trade_entries[0]["price"] == "100.10"
        assert trade_entries[0]["aggressor_side"] == "BUY"

    def test_bbo_updates(self):
        """BBO updates must reflect correct book state after each event."""
        book = OrderBook()
        feed = MarketDataFeed()

        sell = make_order(1, "A", Side.SELL, "100.10", 10, 1000)
        trades = book.process_new_order(sell)
        feed.record_event(book, trades, sell.side, sell.timestamp)

        buy = make_order(2, "B", Side.BUY, "99.90", 5, 2000)
        trades = book.process_new_order(buy)
        feed.record_event(book, trades, buy.side, buy.timestamp)

        bbo = [e for e in feed.entries if e["type"] == "BBO"]
        assert len(bbo) == 2
        assert bbo[0]["best_ask_price"] == "100.10"
        assert bbo[0]["best_ask_qty"] == 10
        assert bbo[0]["best_bid_price"] is None
        assert bbo[1]["best_bid_price"] == "99.90"
        assert bbo[1]["best_bid_qty"] == 5
        assert bbo[1]["best_ask_price"] == "100.10"

    def test_bbo_iceberg_visible_only(self):
        """BBO qty must show only visible (remaining), not hidden."""
        book = OrderBook()
        feed = MarketDataFeed()

        ice = make_order(1, "A", Side.SELL, "100.10", 20, 1000,
                         OrderType.ICEBERG, display_qty=5)
        trades = book.process_new_order(ice)
        feed.record_event(book, trades, ice.side, ice.timestamp)

        bbo = [e for e in feed.entries if e["type"] == "BBO"]
        assert bbo[0]["best_ask_qty"] == 5, (
            "BBO must show visible qty only, not hidden"
        )

    def test_cancel_emits_bbo(self):
        """Cancel event must emit a BBO update."""
        book = OrderBook()
        feed = MarketDataFeed()

        sell = make_order(1, "A", Side.SELL, "100.10", 10, 1000)
        trades = book.process_new_order(sell)
        feed.record_event(book, trades, sell.side, sell.timestamp)

        book.cancel_order(1)
        feed.record_cancel(book, 2000)

        bbo = [e for e in feed.entries if e["type"] == "BBO"]
        assert len(bbo) == 2
        assert bbo[1]["best_ask_price"] is None
        assert bbo[1]["best_ask_qty"] == 0


# ---------------------------------------------------------------------------
# Tests: Surveillance Database
# ---------------------------------------------------------------------------

class TestSurveillanceDatabase:

    def test_database_exists(self):
        """SQLite surveillance database must exist."""
        assert os.path.exists("/app/surveillance/exchange.db"), (
            "Surveillance database not found at /app/surveillance/exchange.db"
        )

    def test_tables_exist(self):
        """Database must contain orders, trades, and cancellations tables."""
        conn = sqlite3_mod.connect("/app/surveillance/exchange.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "orders" in tables, "Missing 'orders' table"
        assert "trades" in tables, "Missing 'trades' table"
        assert "cancellations" in tables, "Missing 'cancellations' table"

    def test_orders_row_count(self):
        """Orders table must have exactly 35 rows from production log."""
        conn = sqlite3_mod.connect("/app/surveillance/exchange.db")
        count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        conn.close()
        assert count == 35, f"Expected 35 orders, got {count}"

    def test_trades_row_count(self):
        """Trades table must have exactly 21 rows from production log."""
        conn = sqlite3_mod.connect("/app/surveillance/exchange.db")
        count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        conn.close()
        assert count == 21, f"Expected 21 trades, got {count}"

    def test_cancellations_row_count(self):
        """Cancellations table must have exactly 6 rows from production log."""
        conn = sqlite3_mod.connect("/app/surveillance/exchange.db")
        count = conn.execute("SELECT COUNT(*) FROM cancellations").fetchone()[0]
        conn.close()
        assert count == 6, f"Expected 6 cancellations, got {count}"


# ---------------------------------------------------------------------------
# Tests: Surveillance Outputs
# ---------------------------------------------------------------------------

class TestSurveillanceOutputs:

    def test_wash_pairs_exists(self):
        """Wash pairs CSV must exist."""
        assert os.path.exists("/app/surveillance/wash_pairs.csv"), (
            "Wash pairs output not found"
        )

    def test_wash_pairs_content(self):
        """Wash pairs must detect FRANK-MALLORY with 6 mutual trades."""
        with open("/app/surveillance/wash_pairs.csv") as f:
            content = f.read().strip()
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        assert len(lines) == 2, (
            f"Expected header + 1 data row, got {len(lines)} lines"
        )
        data_line = lines[1]
        assert "FRANK" in data_line, "FRANK must appear in wash pair"
        assert "MALLORY" in data_line, "MALLORY must appear in wash pair"
        parts = data_line.split(",")
        assert int(parts[-1]) == 6, (
            f"Expected trade_count=6 for FRANK-MALLORY, got {parts[-1]}"
        )

    def test_cancel_ratios_exists(self):
        """Cancel ratios CSV must exist."""
        assert os.path.exists("/app/surveillance/cancel_ratios.csv"), (
            "Cancel ratios output not found"
        )

    def test_cancel_ratios_eve_highest(self):
        """EVE must have highest cancel ratio (6/7 = 0.8571)."""
        with open("/app/surveillance/cancel_ratios.csv") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) >= 2, "Cancel ratios file too short"
        eve_line = lines[1]
        parts = eve_line.split(",")
        assert parts[0] == "EVE", (
            f"First data row should be EVE (highest ratio), got {parts[0]}"
        )
        assert int(parts[1]) == 7, f"EVE should have 7 orders, got {parts[1]}"
        assert int(parts[2]) == 6, f"EVE should have 6 cancels, got {parts[2]}"
        ratio = float(parts[3])
        assert abs(ratio - 0.8571) < 0.001, (
            f"EVE cancel ratio should be ~0.8571, got {ratio}"
        )

    def test_cancel_ratios_all_traders(self):
        """Cancel ratios must include all 9 traders."""
        with open("/app/surveillance/cancel_ratios.csv") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) == 10, (
            f"Expected header + 9 trader rows, got {len(lines)} lines"
        )
        traders = {l.split(",")[0] for l in lines[1:]}
        expected = {"ALICE", "BOB", "CHARLIE", "DAVE", "EVE",
                    "FRANK", "GEORGE", "HENRY", "MALLORY"}
        assert traders == expected, (
            f"Missing traders: {expected - traders}"
        )

    def test_vwap_exists(self):
        """VWAP output file must exist."""
        assert os.path.exists("/app/surveillance/vwap.txt"), (
            "VWAP output not found"
        )

    def test_vwap_value(self):
        """VWAP must be approximately 100.0356."""
        with open("/app/surveillance/vwap.txt") as f:
            value = float(f.read().strip())
        assert abs(value - 100.0356) < 0.01, (
            f"VWAP should be ~100.0356, got {value}"
        )
