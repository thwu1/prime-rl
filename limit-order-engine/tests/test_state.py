"""
Tests for limit order book matching engine (shared library + CLI binary).

"""

import struct
import subprocess
import tempfile
import os
import io
import time
import random
import ctypes
from contextlib import contextmanager
import pytest

SIDE_BUY = 0
SIDE_SELL = 1
ENGINE = "/app/engine"
LIBENGINE = "/app/libengine.so"


# ── Binary message builders ──────────────────────────────────────────

def msg_add(oid, side, qty, price, tid):
    return struct.pack("<BQBIIQ", ord("A"), oid, side, qty, price, tid)

def msg_cancel(oid):
    return struct.pack("<BQ", ord("X"), oid)

def msg_reduce(oid, rq):
    return struct.pack("<BQI", ord("D"), oid, rq)

def msg_replace(old_id, new_id, nq, np):
    return struct.pack("<BQQII", ord("U"), old_id, new_id, nq, np)

def msg_query(qid, qtype, param):
    return struct.pack("<BQBQ", ord("Q"), qid, qtype, param)


# ── Engine runner ────────────────────────────────────────────────────

def run_engine(messages, timeout=30):
    """Write binary feed, run engine, return output lines."""
    feed = b"".join(messages)
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as inf:
        inf.write(feed)
        in_path = inf.name
    out_path = in_path + ".out"
    try:
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = "/app:" + env.get("LD_LIBRARY_PATH", "")
        result = subprocess.run(
            [ENGINE, in_path, out_path],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        assert result.returncode == 0, f"Engine exited {result.returncode}: {result.stderr}"
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            with open(out_path) as f:
                return [l.strip() for l in f if l.strip()]
        return []
    finally:
        if os.path.exists(in_path):
            os.unlink(in_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


# ── Shared library wrapper ──────────────────────────────────────────

class LOBLib:
    """ctypes wrapper around libengine.so for direct API testing."""

    def __init__(self):
        self.lib = ctypes.CDLL(LIBENGINE)

        self.lib.lob_book_create.restype = ctypes.c_void_p
        self.lib.lob_book_create.argtypes = []

        self.lib.lob_book_destroy.restype = None
        self.lib.lob_book_destroy.argtypes = [ctypes.c_void_p]

        self.lib.lob_process_feed.restype = ctypes.c_int
        self.lib.lob_process_feed.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t, ctypes.c_char_p,
        ]

        self.lib.lob_add_order.restype = None
        self.lib.lob_add_order.argtypes = [
            ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint8,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64,
        ]

        self.lib.lob_cancel_order.restype = None
        self.lib.lob_cancel_order.argtypes = [ctypes.c_void_p, ctypes.c_uint64]

        self.lib.lob_reduce_order.restype = None
        self.lib.lob_reduce_order.argtypes = [
            ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint32,
        ]

        self.lib.lob_replace_order.restype = None
        self.lib.lob_replace_order.argtypes = [
            ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64,
            ctypes.c_uint32, ctypes.c_uint32,
        ]

        self.lib.lob_best_bid.restype = ctypes.c_uint32
        self.lib.lob_best_bid.argtypes = [ctypes.c_void_p]

        self.lib.lob_best_offer.restype = ctypes.c_uint32
        self.lib.lob_best_offer.argtypes = [ctypes.c_void_p]

        self.lib.lob_volume_at_price.restype = ctypes.c_uint32
        self.lib.lob_volume_at_price.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

        self.lib.lob_book_depth.restype = None
        self.lib.lob_book_depth.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]

        self.lib.lob_order_info.restype = ctypes.c_int
        self.lib.lob_order_info.argtypes = [
            ctypes.c_void_p, ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]

        self.lib.lob_get_output.restype = ctypes.c_char_p
        self.lib.lob_get_output.argtypes = [ctypes.c_void_p]

        self.lib.lob_clear_output.restype = None
        self.lib.lob_clear_output.argtypes = [ctypes.c_void_p]

    def create_book(self):
        h = self.lib.lob_book_create()
        assert h is not None and h != 0, "lob_book_create returned NULL"
        return h

    def destroy_book(self, book):
        self.lib.lob_book_destroy(book)

    @contextmanager
    def new_book(self):
        book = self.create_book()
        try:
            yield book
        finally:
            self.destroy_book(book)

    def add_order(self, book, oid, side, qty, price, tid):
        self.lib.lob_add_order(book, oid, side, qty, price, tid)

    def cancel_order(self, book, oid):
        self.lib.lob_cancel_order(book, oid)

    def reduce_order(self, book, oid, rq):
        self.lib.lob_reduce_order(book, oid, rq)

    def replace_order(self, book, old_id, new_id, nq, np):
        self.lib.lob_replace_order(book, old_id, new_id, nq, np)

    def best_bid(self, book):
        return self.lib.lob_best_bid(book)

    def best_offer(self, book):
        return self.lib.lob_best_offer(book)

    def volume_at_price(self, book, price):
        return self.lib.lob_volume_at_price(book, price)

    def book_depth(self, book):
        bl = ctypes.c_int(0)
        sl = ctypes.c_int(0)
        self.lib.lob_book_depth(book, ctypes.byref(bl), ctypes.byref(sl))
        return bl.value, sl.value

    def order_info(self, book, oid):
        side = ctypes.c_uint8(0)
        price = ctypes.c_uint32(0)
        qty = ctypes.c_uint32(0)
        found = self.lib.lob_order_info(
            book, oid, ctypes.byref(side), ctypes.byref(price), ctypes.byref(qty),
        )
        if found:
            return side.value, price.value, qty.value
        return None

    def get_output(self, book):
        raw = self.lib.lob_get_output(book)
        if raw is None:
            return []
        text = raw.decode("utf-8").strip()
        if not text:
            return []
        return [l for l in text.split("\n") if l.strip()]

    def clear_output(self, book):
        self.lib.lob_clear_output(book)

    def process_feed(self, book, data, output_path):
        buf = (ctypes.c_uint8 * len(data))(*data)
        return self.lib.lob_process_feed(book, buf, len(data), output_path.encode())


# ── Reference implementation ─────────────────────────────────────────

class RefBook:
    """Pure-Python reference matching engine for verification."""

    def __init__(self):
        self.orders = {}
        self.buy_levels = {}
        self.sell_levels = {}
        self.output = []

    def _match_buy(self, buy_id, price, qty, tid):
        for sp in sorted(self.sell_levels.keys()):
            if price < sp or qty <= 0:
                break
            level = self.sell_levels[sp]
            i = 0
            while i < len(level) and qty > 0:
                so = level[i]
                sord = self.orders[so]
                if sord["tid"] == tid:
                    i += 1
                    continue
                eq = min(qty, sord["qty"])
                self.output.append(f"E {buy_id} {so} {sp} {eq}")
                qty -= eq
                sord["qty"] -= eq
                if sord["qty"] == 0:
                    level.pop(i)
                    del self.orders[so]
                else:
                    i += 1
            if not level:
                del self.sell_levels[sp]
        return qty

    def _match_sell(self, sell_id, price, qty, tid):
        for bp in sorted(self.buy_levels.keys(), reverse=True):
            if price > bp or qty <= 0:
                break
            level = self.buy_levels[bp]
            i = 0
            while i < len(level) and qty > 0:
                bo = level[i]
                bord = self.orders[bo]
                if bord["tid"] == tid:
                    i += 1
                    continue
                eq = min(qty, bord["qty"])
                self.output.append(f"E {bo} {sell_id} {bp} {eq}")
                qty -= eq
                bord["qty"] -= eq
                if bord["qty"] == 0:
                    level.pop(i)
                    del self.orders[bo]
                else:
                    i += 1
            if not level:
                del self.buy_levels[bp]
        return qty

    def add(self, oid, side, qty, price, tid):
        rem = qty
        if side == SIDE_BUY:
            rem = self._match_buy(oid, price, rem, tid)
        else:
            rem = self._match_sell(oid, price, rem, tid)
        if rem > 0:
            self.orders[oid] = {"side": side, "qty": rem, "price": price, "tid": tid}
            levels = self.buy_levels if side == SIDE_BUY else self.sell_levels
            levels.setdefault(price, []).append(oid)

    def cancel(self, oid):
        if oid not in self.orders:
            return
        o = self.orders[oid]
        levels = self.buy_levels if o["side"] == SIDE_BUY else self.sell_levels
        levels[o["price"]].remove(oid)
        if not levels[o["price"]]:
            del levels[o["price"]]
        del self.orders[oid]

    def reduce(self, oid, rq):
        if oid not in self.orders:
            return
        o = self.orders[oid]
        if rq >= o["qty"]:
            self.cancel(oid)
        else:
            o["qty"] -= rq

    def replace(self, old_id, new_id, nq, np):
        if old_id not in self.orders:
            return
        o = self.orders[old_id]
        side, tid = o["side"], o["tid"]
        self.cancel(old_id)
        self.add(new_id, side, nq, np, tid)

    def query(self, qid, qtype, param):
        if qtype == 0:
            r = str(max(self.buy_levels.keys())) if self.buy_levels else "0"
        elif qtype == 1:
            r = str(min(self.sell_levels.keys())) if self.sell_levels else "0"
        elif qtype == 2:
            p = int(param)
            vol = 0
            if p in self.buy_levels:
                vol += sum(self.orders[oid]["qty"] for oid in self.buy_levels[p])
            if p in self.sell_levels:
                vol += sum(self.orders[oid]["qty"] for oid in self.sell_levels[p])
            r = str(vol)
        elif qtype == 3:
            r = f"{len(self.buy_levels)} {len(self.sell_levels)}"
        elif qtype == 4:
            if param in self.orders:
                o = self.orders[param]
                r = f"{o['side']} {o['price']} {o['qty']}"
            else:
                r = "NONE"
        else:
            r = "UNKNOWN"
        self.output.append(f"Q {qid} {r}")


# ═════════════════════════════════════════════════════════════════════
# CLI BINARY TESTS
# ═════════════════════════════════════════════════════════════════════


class TestBasicMatching:
    """Fundamental crossing / no-crossing scenarios."""

    def test_buy_then_sell(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_SELL, 100, 10050, 1002),
        ])
        assert lines == ["E 1 2 10050 100"]

    def test_sell_then_buy(self):
        lines = run_engine([
            msg_add(1, SIDE_SELL, 100, 10050, 1001),
            msg_add(2, SIDE_BUY, 100, 10050, 1002),
        ])
        assert lines == ["E 2 1 10050 100"]

    def test_no_crossing(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 9900, 1001),
            msg_add(2, SIDE_SELL, 100, 10050, 1002),
        ])
        assert lines == []

    def test_exec_at_resting_price(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_SELL, 100, 9500, 1002),
        ])
        assert lines == ["E 1 2 10050 100"]

    def test_aggressive_sell_exec_at_resting(self):
        lines = run_engine([
            msg_add(1, SIDE_SELL, 100, 9500, 1001),
            msg_add(2, SIDE_BUY, 100, 10500, 1002),
        ])
        assert lines == ["E 2 1 9500 100"]

    def test_partial_fill(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_SELL, 30, 10050, 1002),
        ])
        assert lines == ["E 1 2 10050 30"]

    def test_overfill_queues_remainder(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 50, 10050, 1001),
            msg_add(2, SIDE_SELL, 80, 10050, 1002),
            msg_add(3, SIDE_BUY, 30, 10050, 1003),
        ])
        assert lines == ["E 1 2 10050 50", "E 3 2 10050 30"]


class TestPriority:
    """Price-time priority ordering."""

    def test_price_priority(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 50, 10000, 1001),
            msg_add(2, SIDE_BUY, 50, 10050, 1002),
            msg_add(3, SIDE_SELL, 50, 10000, 1003),
        ])
        assert lines == ["E 2 3 10050 50"]

    def test_time_priority(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 50, 10050, 1001),
            msg_add(2, SIDE_BUY, 50, 10050, 1002),
            msg_add(3, SIDE_SELL, 50, 10050, 1003),
        ])
        assert lines == ["E 1 3 10050 50"]

    def test_multi_level_sweep(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 50, 10000, 1001),
            msg_add(2, SIDE_BUY, 50, 10050, 1002),
            msg_add(3, SIDE_BUY, 50, 10100, 1003),
            msg_add(4, SIDE_SELL, 120, 9900, 1004),
        ])
        assert lines == [
            "E 3 4 10100 50",
            "E 2 4 10050 50",
            "E 1 4 10000 20",
        ]

    def test_sell_side_multi_level_sweep(self):
        lines = run_engine([
            msg_add(1, SIDE_SELL, 30, 10100, 1001),
            msg_add(2, SIDE_SELL, 40, 10200, 1002),
            msg_add(3, SIDE_SELL, 50, 10300, 1003),
            msg_add(4, SIDE_BUY, 100, 10250, 1004),
        ])
        assert lines == [
            "E 4 1 10100 30",
            "E 4 2 10200 40",
        ]


class TestCancel:
    """Cancel operations."""

    def test_cancel_prevents_match(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_cancel(1),
            msg_add(2, SIDE_SELL, 100, 10050, 1002),
        ])
        assert lines == []

    def test_cancel_nonexistent(self):
        lines = run_engine([
            msg_cancel(999),
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
        ])
        assert lines == []

    def test_cancel_middle_preserves_queue(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 50, 10050, 1001),
            msg_add(2, SIDE_BUY, 50, 10050, 1002),
            msg_add(3, SIDE_BUY, 50, 10050, 1003),
            msg_cancel(2),
            msg_add(4, SIDE_SELL, 80, 10050, 1004),
        ])
        assert lines == ["E 1 4 10050 50", "E 3 4 10050 30"]


class TestReduce:
    """Reduce (partial cancel) operations."""

    def test_reduce_quantity(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_reduce(1, 60),
            msg_add(2, SIDE_SELL, 100, 10050, 1002),
        ])
        assert lines == ["E 1 2 10050 40"]

    def test_reduce_to_zero_removes(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_reduce(1, 100),
            msg_add(2, SIDE_SELL, 100, 10050, 1002),
        ])
        assert lines == []

    def test_reduce_over_removes(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_reduce(1, 200),
            msg_add(2, SIDE_SELL, 100, 10050, 1002),
        ])
        assert lines == []

    def test_reduce_nonexistent(self):
        lines = run_engine([
            msg_reduce(999, 50),
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
        ])
        assert lines == []


class TestReplace:
    """Replace operations."""

    def test_replace_changes_price(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_replace(1, 2, 50, 10100),
            msg_query(100, 4, 2),
        ])
        assert "Q 100 0 10100 50" in lines

    def test_replace_triggers_match(self):
        lines = run_engine([
            msg_add(1, SIDE_SELL, 100, 10050, 1001),
            msg_add(2, SIDE_BUY, 50, 9900, 1002),
            msg_replace(2, 3, 100, 10050),
        ])
        exec_lines = [l for l in lines if l.startswith("E")]
        assert exec_lines == ["E 3 1 10050 100"]

    def test_replace_nonexistent_ignored(self):
        lines = run_engine([
            msg_replace(999, 1000, 100, 10050),
            msg_query(100, 4, 1000),
        ])
        assert "Q 100 NONE" in lines

    def test_replace_loses_time_priority(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 50, 10050, 1001),
            msg_add(2, SIDE_BUY, 50, 10050, 1002),
            msg_replace(1, 3, 50, 10050),
            msg_add(4, SIDE_SELL, 50, 10050, 1003),
        ])
        assert lines == ["E 2 4 10050 50"]


class TestSelfTradePrevention:
    """Self-trade prevention (STP) scenarios."""

    def test_stp_same_price(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_SELL, 100, 10050, 1001),
        ])
        exec_lines = [l for l in lines if l.startswith("E")]
        assert exec_lines == []

    def test_stp_skip_to_next_order(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 50, 10050, 1001),
            msg_add(2, SIDE_BUY, 50, 10050, 1002),
            msg_add(3, SIDE_SELL, 50, 10050, 1001),
        ])
        exec_lines = [l for l in lines if l.startswith("E")]
        assert exec_lines == ["E 2 3 10050 50"]

    def test_stp_skip_to_next_level(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 50, 10050, 1001),
            msg_add(2, SIDE_BUY, 50, 10000, 1002),
            msg_add(3, SIDE_SELL, 80, 9900, 1001),
        ])
        exec_lines = [l for l in lines if l.startswith("E")]
        assert exec_lines == ["E 2 3 10000 50"]

    def test_stp_creates_locked_book(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_SELL, 100, 10000, 1001),
            msg_query(100, 0, 0),
            msg_query(101, 1, 0),
            msg_query(102, 3, 0),
        ])
        exec_lines = [l for l in lines if l.startswith("E")]
        assert exec_lines == []
        assert "Q 100 10050" in lines
        assert "Q 101 10000" in lines
        assert "Q 102 1 1" in lines

    def test_stp_partial_match_across_traders(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 30, 10050, 1001),
            msg_add(2, SIDE_BUY, 70, 10050, 1002),
            msg_add(3, SIDE_BUY, 40, 10050, 1001),
            msg_add(4, SIDE_SELL, 150, 10050, 1001),
        ])
        exec_lines = [l for l in lines if l.startswith("E")]
        assert exec_lines == ["E 2 4 10050 70"]


class TestQueries:
    """Book state query operations."""

    def test_empty_book_queries(self):
        lines = run_engine([
            msg_query(1, 0, 0),
            msg_query(2, 1, 0),
            msg_query(3, 3, 0),
        ])
        assert "Q 1 0" in lines
        assert "Q 2 0" in lines
        assert "Q 3 0 0" in lines

    def test_best_bid_offer(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_BUY, 200, 10000, 1002),
            msg_add(3, SIDE_SELL, 50, 10100, 1003),
            msg_add(4, SIDE_SELL, 75, 10200, 1004),
            msg_query(100, 0, 0),
            msg_query(101, 1, 0),
        ])
        assert "Q 100 10050" in lines
        assert "Q 101 10100" in lines

    def test_vol_at_price(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_BUY, 200, 10050, 1002),
            msg_add(3, SIDE_SELL, 50, 10100, 1003),
            msg_query(100, 2, 10050),
            msg_query(101, 2, 10100),
            msg_query(102, 2, 9999),
        ])
        assert "Q 100 300" in lines
        assert "Q 101 50" in lines
        assert "Q 102 0" in lines

    def test_book_depth(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_BUY, 200, 10000, 1002),
            msg_add(3, SIDE_SELL, 50, 10100, 1003),
            msg_add(4, SIDE_SELL, 75, 10200, 1004),
            msg_add(5, SIDE_SELL, 25, 10300, 1005),
            msg_query(100, 3, 0),
        ])
        assert "Q 100 2 3" in lines

    def test_order_info(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_SELL, 50, 10100, 1002),
            msg_query(100, 4, 1),
            msg_query(101, 4, 2),
            msg_query(102, 4, 999),
        ])
        assert "Q 100 0 10050 100" in lines
        assert "Q 101 1 10100 50" in lines
        assert "Q 102 NONE" in lines

    def test_queries_after_partial_fill(self):
        lines = run_engine([
            msg_add(1, SIDE_BUY, 100, 10050, 1001),
            msg_add(2, SIDE_SELL, 30, 10050, 1002),
            msg_query(100, 4, 1),
            msg_query(101, 2, 10050),
        ])
        assert "Q 100 0 10050 70" in lines
        assert "Q 101 70" in lines


class TestComplexScenario:
    """Mixed operations verified against reference implementation."""

    def test_randomized_5000_messages(self):
        random.seed(12345)
        ref = RefBook()
        msgs = []
        oid = 1
        active = set()

        for _ in range(5000):
            r = random.random()
            if r < 0.45 or len(active) < 5:
                side = random.randint(0, 1)
                qty = random.randint(1, 500)
                price = random.randint(9000, 11000)
                tid = random.randint(1, 20)
                msgs.append(msg_add(oid, side, qty, price, tid))
                ref.add(oid, side, qty, price, tid)
                if oid in ref.orders:
                    active.add(oid)
                oid += 1
            elif r < 0.60 and active:
                coid = random.choice(sorted(active))
                msgs.append(msg_cancel(coid))
                ref.cancel(coid)
                active.discard(coid)
            elif r < 0.72 and active:
                roid = random.choice(sorted(active))
                rq = random.randint(1, 200)
                msgs.append(msg_reduce(roid, rq))
                ref.reduce(roid, rq)
                if roid not in ref.orders:
                    active.discard(roid)
            elif r < 0.85 and active:
                old = random.choice(sorted(active))
                nq = random.randint(1, 500)
                np = random.randint(9000, 11000)
                msgs.append(msg_replace(old, oid, nq, np))
                ref.replace(old, oid, nq, np)
                active.discard(old)
                if oid in ref.orders:
                    active.add(oid)
                oid += 1
            else:
                qtype = random.randint(0, 4)
                if qtype == 2:
                    param = random.randint(9000, 11000)
                elif qtype == 4:
                    param = random.randint(1, max(1, oid - 1))
                else:
                    param = 0
                msgs.append(msg_query(oid, qtype, param))
                ref.query(oid, qtype, param)
                oid += 1

        lines = run_engine(msgs)
        assert lines == ref.output, (
            f"Mismatch: got {len(lines)} lines, expected {len(ref.output)}. "
            f"First diff at line "
            f"{next((i for i,(a,b) in enumerate(zip(lines, ref.output)) if a!=b), 'length')}"
        )


class TestPerformance:
    """Engine must handle 500K messages within 30 seconds."""

    def test_500k_messages(self):
        random.seed(42)
        buf = io.BytesIO()
        oid = 1

        for _ in range(500000):
            r = random.random()
            if r < 0.50:
                buf.write(struct.pack(
                    "<BQBIIQ", ord("A"), oid,
                    random.randint(0, 1),
                    random.randint(1, 1000),
                    random.randint(9000, 11000),
                    random.randint(1, 50),
                ))
                oid += 1
            elif r < 0.70:
                buf.write(struct.pack(
                    "<BQ", ord("X"), random.randint(1, max(1, oid - 1))))
            elif r < 0.85:
                buf.write(struct.pack(
                    "<BQI", ord("D"),
                    random.randint(1, max(1, oid - 1)),
                    random.randint(1, 200),
                ))
            else:
                buf.write(struct.pack(
                    "<BQQII", ord("U"),
                    random.randint(1, max(1, oid - 1)),
                    oid,
                    random.randint(1, 1000),
                    random.randint(9000, 11000),
                ))
                oid += 1

        feed = buf.getvalue()
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(feed)
            in_path = f.name
        out_path = in_path + ".out"

        try:
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = "/app:" + env.get("LD_LIBRARY_PATH", "")
            start = time.time()
            result = subprocess.run(
                [ENGINE, in_path, out_path],
                capture_output=True, text=True, timeout=30, env=env,
            )
            elapsed = time.time() - start
            assert result.returncode == 0, f"Engine failed: {result.stderr}"
            assert elapsed < 30, f"Took {elapsed:.1f}s (limit 30s)"
            assert os.path.exists(out_path), "No output file"
            with open(out_path) as f:
                exec_count = sum(1 for l in f if l.startswith("E "))
            assert exec_count > 0, "Expected some executions"
        finally:
            if os.path.exists(in_path):
                os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)


# ═════════════════════════════════════════════════════════════════════
# SHARED LIBRARY TESTS
# ═════════════════════════════════════════════════════════════════════


class TestSharedLibrary:
    """Tests exercising libengine.so directly via ctypes FFI."""

    def setup_method(self):
        self.lib = LOBLib()

    def test_load_and_create_destroy(self):
        """Library loads and book lifecycle works."""
        with self.lib.new_book():
            pass  # just create and destroy

    def test_basic_matching_via_api(self):
        """Add orders through library API and verify execution output."""
        with self.lib.new_book() as book:
            self.lib.add_order(book, 1, SIDE_BUY, 100, 10050, 1001)
            self.lib.add_order(book, 2, SIDE_SELL, 100, 10050, 1002)
            output = self.lib.get_output(book)
            assert output == ["E 1 2 10050 100"]

    def test_stp_via_api(self):
        """Self-trade prevention works through library API."""
        with self.lib.new_book() as book:
            self.lib.add_order(book, 1, SIDE_BUY, 50, 10050, 1001)
            self.lib.add_order(book, 2, SIDE_BUY, 50, 10050, 1002)
            self.lib.add_order(book, 3, SIDE_SELL, 50, 10050, 1001)
            output = self.lib.get_output(book)
            assert output == ["E 2 3 10050 50"]

    def test_all_queries_via_api(self):
        """All query functions return correct values through library API."""
        with self.lib.new_book() as book:
            self.lib.add_order(book, 1, SIDE_BUY, 100, 10050, 1001)
            self.lib.add_order(book, 2, SIDE_BUY, 200, 10000, 1002)
            self.lib.add_order(book, 3, SIDE_SELL, 50, 10100, 1003)
            self.lib.add_order(book, 4, SIDE_SELL, 75, 10200, 1004)

            assert self.lib.best_bid(book) == 10050
            assert self.lib.best_offer(book) == 10100
            assert self.lib.volume_at_price(book, 10050) == 100
            assert self.lib.volume_at_price(book, 10000) == 200
            assert self.lib.volume_at_price(book, 10100) == 50
            assert self.lib.volume_at_price(book, 9999) == 0

            bl, sl = self.lib.book_depth(book)
            assert bl == 2
            assert sl == 2

            info = self.lib.order_info(book, 1)
            assert info == (SIDE_BUY, 10050, 100)
            info = self.lib.order_info(book, 3)
            assert info == (SIDE_SELL, 10100, 50)
            assert self.lib.order_info(book, 999) is None

    def test_reduce_replace_via_api(self):
        """Reduce and replace operations work through library API."""
        with self.lib.new_book() as book:
            self.lib.add_order(book, 1, SIDE_BUY, 100, 10050, 1001)
            self.lib.reduce_order(book, 1, 60)
            info = self.lib.order_info(book, 1)
            assert info == (SIDE_BUY, 10050, 40)

            self.lib.replace_order(book, 1, 2, 200, 10100)
            assert self.lib.order_info(book, 1) is None
            info = self.lib.order_info(book, 2)
            assert info == (SIDE_BUY, 10100, 200)

    def test_output_buffer_lifecycle(self):
        """Output accumulates and can be cleared."""
        with self.lib.new_book() as book:
            self.lib.add_order(book, 1, SIDE_BUY, 50, 10050, 1001)
            self.lib.add_order(book, 2, SIDE_SELL, 50, 10050, 1002)
            output = self.lib.get_output(book)
            assert output == ["E 1 2 10050 50"]

            self.lib.clear_output(book)
            assert self.lib.get_output(book) == []

            self.lib.add_order(book, 3, SIDE_BUY, 100, 10100, 1003)
            self.lib.add_order(book, 4, SIDE_SELL, 30, 10100, 1004)
            output = self.lib.get_output(book)
            assert output == ["E 3 4 10100 30"]

    def test_multiple_books_isolation(self):
        """Multiple book instances must be fully independent."""
        book1 = self.lib.create_book()
        book2 = self.lib.create_book()
        try:
            # Add different orders to each book
            self.lib.add_order(book1, 1, SIDE_BUY, 100, 10050, 1001)
            self.lib.add_order(book2, 1, SIDE_SELL, 200, 9900, 2001)

            # Verify book1 state
            assert self.lib.best_bid(book1) == 10050
            assert self.lib.best_offer(book1) == 0

            # Verify book2 state is independent
            assert self.lib.best_bid(book2) == 0
            assert self.lib.best_offer(book2) == 9900

            # Match in book1 only
            self.lib.add_order(book1, 2, SIDE_SELL, 50, 10050, 1002)
            out1 = self.lib.get_output(book1)
            assert out1 == ["E 1 2 10050 50"]

            # book2 must be completely unaffected
            out2 = self.lib.get_output(book2)
            assert out2 == []
            assert self.lib.best_offer(book2) == 9900
            assert self.lib.volume_at_price(book2, 9900) == 200

            # Cancel in book2, verify book1 unaffected
            self.lib.cancel_order(book2, 1)
            assert self.lib.best_offer(book2) == 0
            assert self.lib.best_bid(book1) == 10050  # partial fill left 50
        finally:
            self.lib.destroy_book(book1)
            self.lib.destroy_book(book2)

    def test_process_feed_via_library(self):
        """lob_process_feed processes binary data and writes output file."""
        with self.lib.new_book() as book:
            feed = b""
            feed += msg_add(1, SIDE_BUY, 100, 10050, 1001)
            feed += msg_add(2, SIDE_SELL, 60, 10050, 1002)
            feed += msg_query(100, 4, 1)

            with tempfile.NamedTemporaryFile(suffix=".out", delete=False) as f:
                out_path = f.name
            try:
                rc = self.lib.process_feed(book, feed, out_path)
                assert rc == 0, "lob_process_feed returned nonzero"
                with open(out_path) as f:
                    lines = [l.strip() for l in f if l.strip()]
                assert lines == ["E 1 2 10050 60", "Q 100 0 10050 40"]
            finally:
                if os.path.exists(out_path):
                    os.unlink(out_path)

    def test_symbol_visibility(self):
        """Only lob_* function symbols should be exported."""
        result = subprocess.run(
            ["nm", "-D", "--defined-only", LIBENGINE],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"nm failed: {result.stderr}"

        func_syms = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "T":
                func_syms.append(parts[2])

        # No non-lob function symbols exported
        non_lob = [s for s in func_syms if not s.startswith("lob_")]
        assert non_lob == [], f"Non-lob function symbols exported: {non_lob}"

        # All required API functions present
        required = {
            "lob_book_create", "lob_book_destroy", "lob_process_feed",
            "lob_add_order", "lob_cancel_order", "lob_reduce_order",
            "lob_replace_order", "lob_best_bid", "lob_best_offer",
            "lob_volume_at_price", "lob_book_depth", "lob_order_info",
            "lob_get_output", "lob_clear_output",
        }
        missing = required - set(func_syms)
        assert missing == set(), f"Missing required symbols: {missing}"
