#!/usr/bin/env python3
"""
PCAP / MoldUDP64 / ITCH 5.0 Feed Reconstruction Engine.

Parses PCAP capture files, extracts UDP payloads on port 26400,
decodes MoldUDP64 framing, processes ITCH 5.0 messages, reconstructs
per-symbol limit order books, computes VWAP/volume, answers BBO queries,
and reports feed diagnostics (session tracking, gap detection, heartbeats).
"""

import sys
import struct
import json
import os
from collections import defaultdict

# PCAP constants
PCAP_MAGIC_LE = 0xa1b2c3d4
PCAP_GLOBAL_HEADER_SIZE = 24
PCAP_RECORD_HEADER_SIZE = 16
ETHERTYPE_IPV4 = 0x0800
IP_PROTO_UDP = 17
MOLD_DST_PORT = 26400

# MoldUDP64 constants
MOLD_HEADER_SIZE = 20
HEARTBEAT_COUNT = 0
END_OF_SESSION_COUNT = 0xFFFF


class Order:
    __slots__ = ['ref', 'side', 'shares', 'symbol', 'price', 'mpid']

    def __init__(self, ref, side, shares, symbol, price, mpid=''):
        self.ref = ref
        self.side = side
        self.shares = shares
        self.symbol = symbol
        self.price = price
        self.mpid = mpid


class FeedEngine:
    def __init__(self):
        self.orders = {}
        self.executions = []
        self.broken = set()
        self.session_ids = set()
        self.total_messages = 0
        self.gaps = []
        self.heartbeat_count = 0
        self.session_next_seq = {}

    # ---- PCAP parsing ----

    def _extract_udp_payloads(self, filepath):
        """Extract UDP payloads on port 26400 from a PCAP file."""
        with open(filepath, 'rb') as f:
            raw = f.read()

        if len(raw) < PCAP_GLOBAL_HEADER_SIZE:
            return []

        magic = struct.unpack_from('<I', raw, 0)[0]
        if magic != PCAP_MAGIC_LE:
            return []

        pos = PCAP_GLOBAL_HEADER_SIZE
        payloads = []

        while pos + PCAP_RECORD_HEADER_SIZE <= len(raw):
            ts_sec, ts_usec, incl_len, orig_len = struct.unpack_from(
                '<IIII', raw, pos)
            pos += PCAP_RECORD_HEADER_SIZE

            if pos + incl_len > len(raw):
                break

            pkt_data = raw[pos:pos + incl_len]
            pos += incl_len

            # Ethernet header: 14 bytes minimum
            if len(pkt_data) < 14:
                continue
            ethertype = struct.unpack_from('>H', pkt_data, 12)[0]
            if ethertype != ETHERTYPE_IPV4:
                continue

            # IPv4 header: minimum 20 bytes
            ip_start = 14
            if len(pkt_data) < ip_start + 20:
                continue
            ip_ihl = (pkt_data[ip_start] & 0x0F) * 4
            ip_protocol = pkt_data[ip_start + 9]
            if ip_protocol != IP_PROTO_UDP:
                continue

            # UDP header: 8 bytes
            udp_start = ip_start + ip_ihl
            if len(pkt_data) < udp_start + 8:
                continue
            dst_port = struct.unpack_from('>H', pkt_data, udp_start + 2)[0]
            if dst_port != MOLD_DST_PORT:
                continue

            udp_len = struct.unpack_from('>H', pkt_data, udp_start + 4)[0]
            payload_start = udp_start + 8
            payload = pkt_data[payload_start:payload_start + udp_len - 8]
            payloads.append(payload)

        return payloads

    # ---- MoldUDP64 parsing ----

    def parse_captures(self, captures_dir):
        all_messages = []

        for filename in sorted(os.listdir(captures_dir)):
            if not filename.endswith('.pcap'):
                continue
            filepath = os.path.join(captures_dir, filename)
            payloads = self._extract_udp_payloads(filepath)
            for payload in payloads:
                self._parse_moldudp64_packet(payload, all_messages)

        all_messages.sort(key=lambda x: x[0])
        return all_messages

    def _parse_moldudp64_packet(self, raw, all_messages):
        """Parse a single MoldUDP64 downstream packet."""
        if len(raw) < MOLD_HEADER_SIZE:
            return

        session_id = raw[0:10].decode('ascii').rstrip()
        seq_num = struct.unpack_from('>Q', raw, 10)[0]
        msg_count = struct.unpack_from('>H', raw, 18)[0]

        self.session_ids.add(session_id)

        # Gap detection
        if session_id in self.session_next_seq:
            expected = self.session_next_seq[session_id]
            if seq_num > expected:
                self.gaps.append({
                    'session': session_id,
                    'expected_seq': expected,
                    'actual_seq': seq_num,
                })

        if msg_count == HEARTBEAT_COUNT:
            self.heartbeat_count += 1
            self.session_next_seq[session_id] = seq_num
            return
        elif msg_count == END_OF_SESSION_COUNT:
            return

        # Normal data packet: parse message blocks
        pos = MOLD_HEADER_SIZE
        for _ in range(msg_count):
            if pos + 2 > len(raw):
                break
            msg_len = struct.unpack_from('>H', raw, pos)[0]
            pos += 2
            if pos + msg_len > len(raw):
                break
            msg_data = raw[pos:pos + msg_len]
            pos += msg_len

            ts = int.from_bytes(msg_data[5:11], 'big') if len(msg_data) >= 11 else 0
            all_messages.append((ts, msg_data))
            self.total_messages += 1

        self.session_next_seq[session_id] = seq_num + msg_count

    # ---- ITCH message processing ----

    def process_itch_message(self, msg):
        mt = chr(msg[0])

        if mt == 'A':
            ref = struct.unpack_from('>Q', msg, 11)[0]
            self.orders[ref] = Order(
                ref=ref,
                side=chr(msg[19]),
                shares=struct.unpack_from('>I', msg, 20)[0],
                symbol=msg[24:32].decode('ascii').rstrip(),
                price=struct.unpack_from('>I', msg, 32)[0] / 10000.0,
            )
        elif mt == 'F':
            ref = struct.unpack_from('>Q', msg, 11)[0]
            self.orders[ref] = Order(
                ref=ref,
                side=chr(msg[19]),
                shares=struct.unpack_from('>I', msg, 20)[0],
                symbol=msg[24:32].decode('ascii').rstrip(),
                price=struct.unpack_from('>I', msg, 32)[0] / 10000.0,
                mpid=msg[36:40].decode('ascii').rstrip(),
            )
        elif mt == 'E':
            ref = struct.unpack_from('>Q', msg, 11)[0]
            if ref not in self.orders:
                return
            order = self.orders[ref]
            shares = struct.unpack_from('>I', msg, 19)[0]
            match = struct.unpack_from('>Q', msg, 23)[0]
            self.executions.append((order.symbol, shares, order.price, match, True))
            order.shares -= shares
            if order.shares <= 0:
                del self.orders[ref]
        elif mt == 'C':
            ref = struct.unpack_from('>Q', msg, 11)[0]
            if ref not in self.orders:
                return
            order = self.orders[ref]
            shares = struct.unpack_from('>I', msg, 19)[0]
            match = struct.unpack_from('>Q', msg, 23)[0]
            printable = chr(msg[31]) == 'Y'
            price = struct.unpack_from('>I', msg, 32)[0] / 10000.0
            self.executions.append((order.symbol, shares, price, match, printable))
            order.shares -= shares
            if order.shares <= 0:
                del self.orders[ref]
        elif mt == 'X':
            ref = struct.unpack_from('>Q', msg, 11)[0]
            if ref not in self.orders:
                return
            self.orders[ref].shares -= struct.unpack_from('>I', msg, 19)[0]
            if self.orders[ref].shares <= 0:
                del self.orders[ref]
        elif mt == 'D':
            self.orders.pop(struct.unpack_from('>Q', msg, 11)[0], None)
        elif mt == 'U':
            orig_ref = struct.unpack_from('>Q', msg, 11)[0]
            new_ref = struct.unpack_from('>Q', msg, 19)[0]
            if orig_ref not in self.orders:
                return
            old = self.orders.pop(orig_ref)
            self.orders[new_ref] = Order(
                new_ref, old.side,
                struct.unpack_from('>I', msg, 27)[0],
                old.symbol,
                struct.unpack_from('>I', msg, 31)[0] / 10000.0,
                old.mpid,
            )
        elif mt == 'P':
            shares = struct.unpack_from('>I', msg, 20)[0]
            symbol = msg[24:32].decode('ascii').rstrip()
            price = struct.unpack_from('>I', msg, 32)[0] / 10000.0
            match = struct.unpack_from('>Q', msg, 36)[0]
            self.executions.append((symbol, shares, price, match, True))
        elif mt == 'Q':
            shares = struct.unpack_from('>Q', msg, 11)[0]
            symbol = msg[19:27].decode('ascii').rstrip()
            price = struct.unpack_from('>I', msg, 27)[0] / 10000.0
            match = struct.unpack_from('>Q', msg, 31)[0]
            self.executions.append((symbol, int(shares), price, match, True))
        elif mt == 'B':
            self.broken.add(struct.unpack_from('>Q', msg, 11)[0])
        # All other message types (S, R, H, Y, L, V, W, K, J, h, I, N, O)
        # are parsed for transport framing but do not affect the order book.

    # ---- BBO computation ----

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

    # ---- VWAP / Volume ----

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

    # ---- Main entry point ----

    def run(self, captures_dir, queries_path):
        with open(queries_path) as f:
            queries = json.load(f)

        bbo_queries = queries.get('bbo_queries', [])
        all_messages = self.parse_captures(captures_dir)

        # Sort BBO queries by timestamp, preserving original index
        indexed_queries = sorted(
            enumerate(bbo_queries), key=lambda x: x[1]['timestamp_ns']
        )
        bbo_results = [None] * len(bbo_queries)
        qi = 0

        for ts, msg_data in all_messages:
            while qi < len(indexed_queries):
                orig_i, q = indexed_queries[qi]
                if ts > q['timestamp_ns']:
                    sym = q['symbol']
                    bp, bs, ap, as_ = self.get_bbo(sym)
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
            self.process_itch_message(msg_data)

        # Answer remaining queries after all messages
        while qi < len(indexed_queries):
            orig_i, q = indexed_queries[qi]
            sym = q['symbol']
            bp, bs, ap, as_ = self.get_bbo(sym)
            bbo_results[orig_i] = {
                'symbol': sym,
                'timestamp_ns': q['timestamp_ns'],
                'bid_price': bp,
                'bid_size': bs,
                'ask_price': ap,
                'ask_size': as_,
            }
            qi += 1

        vwap, volume = self.compute_vwap_volume()

        sorted_gaps = sorted(
            self.gaps, key=lambda g: (g['session'], g['expected_seq'])
        )

        result = {
            'vwap': vwap,
            'volume': volume,
            'bbo': bbo_results,
            'diagnostics': {
                'sessions': sorted(self.session_ids),
                'total_messages': self.total_messages,
                'gaps': sorted_gaps,
                'heartbeat_count': self.heartbeat_count,
            },
        }
        print(json.dumps(result))


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: feed_engine <captures_dir> <queries_file>",
            file=sys.stderr,
        )
        sys.exit(1)
    engine = FeedEngine()
    engine.run(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    main()
