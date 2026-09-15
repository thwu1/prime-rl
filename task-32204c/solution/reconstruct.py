#!/usr/bin/env python3
"""
Order book reconstruction from XMBO binary MBO data.

Usage: python3 reconstruct.py [input_file] [output_file]
  input_file  — path to XMBO binary file (default: /app/data/session.xmbo)
  output_file — path for JSON output (default: /app/output/analytics.json)
"""

import struct
import sys
import json
import os

# ── Format constants ──────────────────────────────────────────
HEADER_FMT = '<4sHHHHII12sQQ'
HEADER_SIZE = 48
RECORD_FMT = '<QQqIBBHQ24s'
RECORD_SIZE = 64

ACTION_ADD    = 0x41  # 'A'
ACTION_CANCEL = 0x43  # 'C'
ACTION_MODIFY = 0x4D  # 'M'
ACTION_TRADE  = 0x54  # 'T'
ACTION_FILL   = 0x46  # 'F'

SIDE_BID = 0x42  # 'B'
SIDE_ASK = 0x53  # 'S'

FP_SCALE = 1_000_000_000


def fp_to_price(fp_value):
    """Convert fixed-point int64 to float price."""
    return fp_value / FP_SCALE


# ── Order Book ────────────────────────────────────────────────

class OrderBook:
    """Maintains a set of resting orders keyed by order_id."""

    def __init__(self):
        self.orders = {}  # order_id -> (price_fp, qty, side)

    def add(self, order_id, price_fp, qty, side):
        self.orders[order_id] = (price_fp, qty, side)

    def cancel(self, order_id):
        self.orders.pop(order_id, None)

    def modify(self, order_id, price_fp, qty):
        if order_id in self.orders:
            _, _, side = self.orders[order_id]
            self.orders[order_id] = (price_fp, qty, side)

    def trade(self, order_id, fill_qty):
        if order_id in self.orders:
            price_fp, qty, side = self.orders[order_id]
            remaining = qty - fill_qty
            if remaining > 0:
                self.orders[order_id] = (price_fp, remaining, side)
            else:
                del self.orders[order_id]

    def fill(self, order_id):
        self.orders.pop(order_id, None)

    def best_bid_fp(self):
        bids = [p for _, (p, q, s) in self.orders.items() if s == SIDE_BID]
        return max(bids) if bids else None

    def best_ask_fp(self):
        asks = [p for _, (p, q, s) in self.orders.items() if s == SIDE_ASK]
        return min(asks) if asks else None

    def size_at_best_bid(self):
        bb = self.best_bid_fp()
        if bb is None:
            return 0
        return sum(q for _, (p, q, s) in self.orders.items()
                   if s == SIDE_BID and p == bb)

    def size_at_best_ask(self):
        ba = self.best_ask_fp()
        if ba is None:
            return 0
        return sum(q for _, (p, q, s) in self.orders.items()
                   if s == SIDE_ASK and p == ba)

    def bid_levels(self):
        return len(set(p for _, (p, q, s) in self.orders.items()
                       if s == SIDE_BID))

    def ask_levels(self):
        return len(set(p for _, (p, q, s) in self.orders.items()
                       if s == SIDE_ASK))


# ── Main pipeline ─────────────────────────────────────────────

def parse_and_analyze(input_path, output_path):
    with open(input_path, 'rb') as f:
        # ── Parse header ──
        header_data = f.read(HEADER_SIZE)
        (magic, version, hdr_size, rec_size, _reserved,
         num_records, inst_id, symbol, start_ts, end_ts) = \
            struct.unpack(HEADER_FMT, header_data)

        assert magic == b'XMBO', f"Invalid magic: {magic}"
        assert version == 2, f"Unsupported version: {version}"

        # ── Parse all records ──
        records = []
        for _ in range(num_records):
            rec_data = f.read(rec_size)
            (ts, oid, price_fp, qty, action, side,
             flags, seq, _pad) = struct.unpack(RECORD_FMT, rec_data)
            records.append((ts, oid, price_fp, qty, action, side, flags, seq))

    # ── Sort by sequence number ──
    records.sort(key=lambda r: r[7])

    # ── Process records ──
    book = OrderBook()

    total_trade_value = 0.0
    total_volume = 0
    trade_count = 0
    max_spread = 0.0

    # Iceberg detection: track recent Fill events
    recent_fills = []  # [(timestamp, price_fp, side)]
    iceberg_count = 0

    for ts, oid, price_fp, qty, action, side, flags, seq in records:

        if action == ACTION_ADD:
            # Check for iceberg reload before adding
            for fill_ts, fill_pfp, fill_side in recent_fills:
                if (price_fp == fill_pfp
                        and side == fill_side
                        and ts - fill_ts <= 100_000):
                    iceberg_count += 1
                    break
            book.add(oid, price_fp, qty, side)

        elif action == ACTION_CANCEL:
            book.cancel(oid)

        elif action == ACTION_MODIFY:
            book.modify(oid, price_fp, qty)

        elif action == ACTION_TRADE:
            trade_price = fp_to_price(price_fp)
            total_trade_value += trade_price * qty
            total_volume += qty
            trade_count += 1
            book.trade(oid, qty)

        elif action == ACTION_FILL:
            trade_price = fp_to_price(price_fp)
            total_trade_value += trade_price * qty
            total_volume += qty
            trade_count += 1

            # Record for iceberg detection, prune old entries
            recent_fills = [(t, p, s) for t, p, s in recent_fills
                            if ts - t <= 1_000_000]
            recent_fills.append((ts, price_fp, side))

            book.fill(oid)

        # ── Track spread ──
        bb = book.best_bid_fp()
        ba = book.best_ask_fp()
        if bb is not None and ba is not None:
            spread = fp_to_price(ba) - fp_to_price(bb)
            if spread > max_spread:
                max_spread = spread

    # ── Compute final analytics ──
    vwap = total_trade_value / total_volume if total_volume > 0 else 0.0

    bb_fp = book.best_bid_fp()
    ba_fp = book.best_ask_fp()

    analytics = {
        'session_vwap': round(vwap, 6),
        'total_volume': total_volume,
        'trade_count': trade_count,
        'max_spread': round(max_spread, 6),
        'iceberg_count': iceberg_count,
        'final_best_bid': round(fp_to_price(bb_fp), 6) if bb_fp is not None else None,
        'final_best_ask': round(fp_to_price(ba_fp), 6) if ba_fp is not None else None,
        'final_bid_size': book.size_at_best_bid(),
        'final_ask_size': book.size_at_best_ask(),
        'bid_depth_levels': book.bid_levels(),
        'ask_depth_levels': book.ask_levels(),
        'num_messages': len(records),
    }

    # ── Write output ──
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(analytics, f, indent=2)

    return analytics


if __name__ == '__main__':
    input_file = sys.argv[1] if len(sys.argv) > 1 else '/app/data/session.xmbo'
    output_file = sys.argv[2] if len(sys.argv) > 2 else '/app/output/analytics.json'

    analytics = parse_and_analyze(input_file, output_file)
    print(json.dumps(analytics, indent=2))
