#!/usr/bin/env python3
"""
Nasdaq ITCH 5.0 Binary Protocol Parser and Order Book Engine.

Parses all 23 ITCH 5.0 message types, maintains per-symbol limit order books,
computes VWAP/volume from printable executions (excluding broken trades),
and answers BBO snapshot queries at specified timestamps.
"""

import sys
import struct
import json
from collections import defaultdict

# Message body sizes by type code byte value
MSG_SIZES = {
    ord('S'): 12, ord('R'): 39, ord('H'): 25, ord('Y'): 20,
    ord('L'): 26, ord('V'): 35, ord('W'): 12, ord('K'): 28,
    ord('J'): 35, ord('h'): 21, ord('A'): 36, ord('F'): 40,
    ord('E'): 31, ord('C'): 36, ord('X'): 23, ord('D'): 19,
    ord('U'): 35, ord('P'): 44, ord('Q'): 40, ord('B'): 19,
    ord('I'): 50, ord('N'): 20, ord('O'): 48,
}


class Order:
    __slots__ = ['ref', 'side', 'shares', 'symbol', 'price', 'mpid']

    def __init__(self, ref, side, shares, symbol, price, mpid=''):
        self.ref = ref
        self.side = side
        self.shares = shares
        self.symbol = symbol
        self.price = price
        self.mpid = mpid


class OrderBook:
    def __init__(self):
        self.orders = {}           # ref_number -> Order
        self.executions = []       # [(symbol, shares, price, match_number, printable)]
        self.broken = set()        # set of broken match numbers

    def add_order(self, ref, side, shares, symbol, price, mpid=''):
        self.orders[ref] = Order(ref, side, shares, symbol, price, mpid)

    def execute_order(self, ref, shares, match_number, price=None, printable=True):
        if ref not in self.orders:
            return
        order = self.orders[ref]
        exec_price = price if price is not None else order.price
        self.executions.append((order.symbol, shares, exec_price, match_number, printable))
        order.shares -= shares
        if order.shares <= 0:
            del self.orders[ref]

    def cancel_order(self, ref, shares):
        if ref not in self.orders:
            return
        self.orders[ref].shares -= shares
        if self.orders[ref].shares <= 0:
            del self.orders[ref]

    def delete_order(self, ref):
        self.orders.pop(ref, None)

    def replace_order(self, orig_ref, new_ref, new_shares, new_price):
        if orig_ref not in self.orders:
            return
        old = self.orders.pop(orig_ref)
        self.orders[new_ref] = Order(
            new_ref, old.side, new_shares, old.symbol, new_price, old.mpid
        )

    def add_trade(self, symbol, shares, price, match_number):
        self.executions.append((symbol, shares, price, match_number, True))

    def add_cross_trade(self, symbol, shares, price, match_number):
        self.executions.append((symbol, shares, price, match_number, True))

    def break_trade(self, match_number):
        self.broken.add(match_number)

    def get_bbo(self, symbol):
        best_bid_price = None
        best_bid_size = 0
        best_ask_price = None
        best_ask_size = 0

        for order in self.orders.values():
            if order.symbol != symbol:
                continue
            if order.side == 'B':
                if best_bid_price is None or order.price > best_bid_price:
                    best_bid_price = order.price
                    best_bid_size = order.shares
                elif order.price == best_bid_price:
                    best_bid_size += order.shares
            else:
                if best_ask_price is None or order.price < best_ask_price:
                    best_ask_price = order.price
                    best_ask_size = order.shares
                elif order.price == best_ask_price:
                    best_ask_size += order.shares

        return best_bid_price, best_bid_size, best_ask_price, best_ask_size

    def compute_vwap_volume(self):
        sym_data = defaultdict(lambda: [0.0, 0])
        for symbol, shares, price, match_num, printable in self.executions:
            if not printable:
                continue
            if match_num in self.broken:
                continue
            sym_data[symbol][0] += shares * price
            sym_data[symbol][1] += shares

        vwap = {}
        volume = {}
        for sym, (notional, vol) in sym_data.items():
            if vol > 0:
                vwap[sym] = notional / vol
                volume[sym] = vol
        return vwap, volume


def parse_ts(data, off):
    return int.from_bytes(data[off:off + 6], 'big')

def parse_p4(data, off):
    return struct.unpack_from('>I', data, off)[0] / 10000.0

def parse_stock(data, off):
    return data[off:off + 8].decode('ascii').rstrip()

def parse_u16(data, off):
    return struct.unpack_from('>H', data, off)[0]

def parse_u32(data, off):
    return struct.unpack_from('>I', data, off)[0]

def parse_u64(data, off):
    return struct.unpack_from('>Q', data, off)[0]


def process_message(book, msg):
    mt = chr(msg[0])

    if mt == 'A':
        book.add_order(
            ref=parse_u64(msg, 11),
            side=chr(msg[19]),
            shares=parse_u32(msg, 20),
            symbol=parse_stock(msg, 24),
            price=parse_p4(msg, 32),
        )
    elif mt == 'F':
        book.add_order(
            ref=parse_u64(msg, 11),
            side=chr(msg[19]),
            shares=parse_u32(msg, 20),
            symbol=parse_stock(msg, 24),
            price=parse_p4(msg, 32),
            mpid=msg[36:40].decode('ascii').rstrip(),
        )
    elif mt == 'E':
        book.execute_order(
            ref=parse_u64(msg, 11),
            shares=parse_u32(msg, 19),
            match_number=parse_u64(msg, 23),
        )
    elif mt == 'C':
        book.execute_order(
            ref=parse_u64(msg, 11),
            shares=parse_u32(msg, 19),
            match_number=parse_u64(msg, 23),
            price=parse_p4(msg, 32),
            printable=(chr(msg[31]) == 'Y'),
        )
    elif mt == 'X':
        book.cancel_order(
            ref=parse_u64(msg, 11),
            shares=parse_u32(msg, 19),
        )
    elif mt == 'D':
        book.delete_order(ref=parse_u64(msg, 11))
    elif mt == 'U':
        book.replace_order(
            orig_ref=parse_u64(msg, 11),
            new_ref=parse_u64(msg, 19),
            new_shares=parse_u32(msg, 27),
            new_price=parse_p4(msg, 31),
        )
    elif mt == 'P':
        book.add_trade(
            symbol=parse_stock(msg, 24),
            shares=parse_u32(msg, 20),
            price=parse_p4(msg, 32),
            match_number=parse_u64(msg, 36),
        )
    elif mt == 'Q':
        book.add_cross_trade(
            symbol=parse_stock(msg, 19),
            shares=int(parse_u64(msg, 11)),
            price=parse_p4(msg, 27),
            match_number=parse_u64(msg, 31),
        )
    elif mt == 'B':
        book.break_trade(match_number=parse_u64(msg, 11))
    # All other message types (S, R, H, Y, L, V, W, K, J, h, I, N, O)
    # are parsed for framing but do not affect the order book.


def main():
    if len(sys.argv) != 3:
        print("Usage: itch_engine <itch_file> <queries_file>", file=sys.stderr)
        sys.exit(1)

    itch_path = sys.argv[1]
    queries_path = sys.argv[2]

    with open(itch_path, 'rb') as f:
        raw = f.read()
    with open(queries_path) as f:
        queries = json.load(f)

    bbo_queries = queries.get('bbo_queries', [])

    # Parse all messages into (timestamp, message_bytes) pairs
    messages = []
    pos = 0
    while pos + 2 <= len(raw):
        msg_len = struct.unpack_from('>H', raw, pos)[0]
        pos += 2
        if pos + msg_len > len(raw):
            break
        msg_data = raw[pos:pos + msg_len]
        pos += msg_len
        # All ITCH 5.0 messages have timestamp at offset 5 (6 bytes)
        ts = parse_ts(msg_data, 5) if len(msg_data) >= 11 else 0
        messages.append((ts, msg_data))

    # Sort BBO queries by timestamp, preserving original index
    indexed_queries = sorted(enumerate(bbo_queries), key=lambda x: x[1]['timestamp_ns'])

    book = OrderBook()
    bbo_results = [None] * len(bbo_queries)
    qi = 0

    for ts, msg_data in messages:
        # Answer pending BBO queries whose timestamp < current message timestamp
        while qi < len(indexed_queries):
            orig_i, q = indexed_queries[qi]
            if ts > q['timestamp_ns']:
                sym = q['symbol']
                bp, bs, ap, as_ = book.get_bbo(sym)
                bbo_results[orig_i] = {
                    'symbol': sym,
                    'timestamp_ns': q['timestamp_ns'],
                    'bid_price': bp,
                    'bid_size': bs,
                    'ask_price': ap,
                    'ask_size': as_,
                }
                qi += 1
            else:
                break

        process_message(book, msg_data)

    # Answer remaining queries (timestamp >= last message)
    while qi < len(indexed_queries):
        orig_i, q = indexed_queries[qi]
        sym = q['symbol']
        bp, bs, ap, as_ = book.get_bbo(sym)
        bbo_results[orig_i] = {
            'symbol': sym,
            'timestamp_ns': q['timestamp_ns'],
            'bid_price': bp,
            'bid_size': bs,
            'ask_price': ap,
            'ask_size': as_,
        }
        qi += 1

    vwap, volume = book.compute_vwap_volume()

    result = {
        'vwap': vwap,
        'volume': volume,
        'bbo': bbo_results,
    }
    print(json.dumps(result))


if __name__ == '__main__':
    main()
