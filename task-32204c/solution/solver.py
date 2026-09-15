#!/usr/bin/env python3
"""
Multi-feed order book reconstruction pipeline.

Extracts market data from pcap via tshark, deduplicates across channels,
reconstructs per-instrument order books, computes analytics, writes to SQLite.
"""

import subprocess
import struct
import sqlite3
import os
import sys

# ── Constants ────────────────────────────────────────────────
RECORD_SIZE = 64
CHANNEL_HDR_SIZE = 8
RECORD_FMT = '<QQqIBBHQI20s'

ACTION_ADD = 0x41
ACTION_CANCEL = 0x43
ACTION_MODIFY = 0x4D
ACTION_TRADE = 0x54
ACTION_FILL = 0x46
SIDE_BID = 0x42
SIDE_ASK = 0x53

PCAP_FILE = '/app/data/market_feed.pcap'
REF_DB = '/app/data/instruments.db'
OUTPUT_DB = '/app/output/analysis.db'


def load_instrument_config(ref_db_path):
    """Load instrument metadata from reference SQLite database."""
    conn = sqlite3.connect(ref_db_path)
    c = conn.cursor()

    instruments = {}
    for row in c.execute('SELECT instrument_id, symbol, tick_size, lot_size, price_scale FROM instruments'):
        instruments[row[0]] = {
            'symbol': row[1],
            'tick_size': row[2],
            'lot_size': row[3],
            'price_scale': row[4],
        }

    channels = {}
    for row in c.execute('SELECT channel_id, port FROM channel_config'):
        channels[row[0]] = {'port': row[1]}

    conn.close()
    return instruments, channels


def extract_udp_from_pcap(pcap_path, ports):
    """Use tshark to extract UDP payloads from pcap file."""
    port_filter = ' || '.join(f'udp.dstport == {p}' for p in ports)
    cmd = [
        'tshark', '-r', pcap_path, '-n',
        '-Y', port_filter,
        '-T', 'fields',
        '-e', 'frame.time_epoch',
        '-e', 'udp.dstport',
        '-e', 'data.data',
        '-E', 'separator=|',
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"tshark stderr: {result.stderr}", file=sys.stderr)
        # Fallback: try udp.payload field name
        cmd_alt = [
            'tshark', '-r', pcap_path, '-n',
            '-Y', port_filter,
            '-T', 'fields',
            '-e', 'frame.time_epoch',
            '-e', 'udp.dstport',
            '-e', 'udp.payload',
            '-E', 'separator=|',
        ]
        result = subprocess.run(cmd_alt, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"tshark failed: {result.stderr}")

    packets = []
    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        parts = line.split('|')
        if len(parts) < 3 or not parts[2].strip():
            continue

        cap_epoch = float(parts[0])
        dst_port = int(parts[1])
        hex_data = parts[2].replace(':', '').strip()
        raw_data = bytes.fromhex(hex_data)

        packets.append({
            'capture_epoch_us': int(cap_epoch * 1_000_000),
            'dst_port': dst_port,
            'raw': raw_data,
        })

    return packets


def parse_channel_payload(raw):
    """Parse channel header + XMBO records from UDP payload."""
    if len(raw) < CHANNEL_HDR_SIZE:
        return None, []

    channel_id, ch_seq_start, msg_count = struct.unpack('<HIH', raw[:CHANNEL_HDR_SIZE])

    records = []
    offset = CHANNEL_HDR_SIZE
    for i in range(msg_count):
        if offset + RECORD_SIZE > len(raw):
            break
        fields = struct.unpack(RECORD_FMT, raw[offset:offset + RECORD_SIZE])
        ts, oid, price_fp, qty, action, side, flags, seq, inst_id, _pad = fields
        records.append({
            'ts': ts, 'oid': oid, 'price_fp': price_fp, 'qty': qty,
            'action': action, 'side': side, 'flags': flags,
            'seq': seq, 'inst_id': inst_id,
        })
        offset += RECORD_SIZE

    return {
        'channel_id': channel_id,
        'ch_seq_start': ch_seq_start,
        'msg_count': msg_count,
    }, records


class OrderBook:
    def __init__(self):
        self.orders = {}  # oid -> (price_fp, qty, side)

    def add(self, oid, price_fp, qty, side):
        self.orders[oid] = (price_fp, qty, side)

    def cancel(self, oid):
        self.orders.pop(oid, None)

    def modify(self, oid, price_fp, qty):
        if oid in self.orders:
            _, _, side = self.orders[oid]
            self.orders[oid] = (price_fp, qty, side)

    def trade(self, oid, fill_qty):
        if oid in self.orders:
            pfp, oq, side = self.orders[oid]
            rem = oq - fill_qty
            if rem > 0:
                self.orders[oid] = (pfp, rem, side)
            else:
                self.orders.pop(oid)

    def fill(self, oid):
        self.orders.pop(oid, None)

    def best_bid_fp(self):
        bids = [p for p, q, s in self.orders.values() if s == SIDE_BID]
        return max(bids) if bids else None

    def best_ask_fp(self):
        asks = [p for p, q, s in self.orders.values() if s == SIDE_ASK]
        return min(asks) if asks else None

    def size_at_price(self, target_fp, target_side):
        return sum(q for p, q, s in self.orders.values()
                   if p == target_fp and s == target_side)

    def depth(self, side):
        return len(set(p for p, q, s in self.orders.values() if s == side))


def run_pipeline():
    # ── Load reference data ──────────────────────────────────
    instruments, channels = load_instrument_config(REF_DB)
    ports = [ch['port'] for ch in channels.values()]

    print(f"Loaded {len(instruments)} instruments, {len(channels)} channels")
    print(f"Filtering pcap for ports: {ports}")

    # ── Extract packets from pcap ────────────────────────────
    packets = extract_udp_from_pcap(PCAP_FILE, ports)
    print(f"Extracted {len(packets)} UDP packets from pcap")

    # ── Parse all packets ────────────────────────────────────
    all_records = {}  # seq -> record dict (deduplicate by record sequence)
    channel_sequences = {}  # channel_id -> list of (ch_seq_start, msg_count)
    latency_data = []  # per-packet latency entries

    port_to_channel = {}
    for ch_id, ch_info in channels.items():
        port_to_channel[ch_info['port']] = ch_id

    for pkt in packets:
        ch_hdr, records = parse_channel_payload(pkt['raw'])
        if ch_hdr is None:
            continue

        ch_id = ch_hdr['channel_id']

        # Track channel sequences for gap detection
        if ch_id not in channel_sequences:
            channel_sequences[ch_id] = []
        channel_sequences[ch_id].append((ch_hdr['ch_seq_start'], ch_hdr['msg_count']))

        # Latency: capture time vs first record's message timestamp
        if records:
            latency_data.append({
                'channel_id': ch_id,
                'capture_epoch_us': pkt['capture_epoch_us'],
                'message_time_ns': records[0]['ts'],
                'packet_msg_count': len(records),
            })

        # Deduplicate by record sequence number
        for rec in records:
            seq = rec['seq']
            if seq not in all_records:
                all_records[seq] = rec

    print(f"Total unique records after dedup: {len(all_records)}")

    # ── Detect channel gaps ──────────────────────────────────
    gaps = []
    for ch_id, seq_list in channel_sequences.items():
        seq_list.sort(key=lambda x: x[0])
        for i in range(1, len(seq_list)):
            expected = seq_list[i - 1][0] + seq_list[i - 1][1]
            actual = seq_list[i][0]
            if actual > expected:
                gap_size = actual - expected
                gaps.append({
                    'channel_id': ch_id,
                    'expected_seq': expected,
                    'actual_seq': actual,
                    'gap_size': gap_size,
                })

    print(f"Detected {len(gaps)} channel gaps")

    # ── Sort records by sequence, group by instrument ────────
    sorted_records = sorted(all_records.values(), key=lambda r: r['seq'])

    inst_records = {}
    for rec in sorted_records:
        iid = rec['inst_id']
        if iid not in inst_records:
            inst_records[iid] = []
        inst_records[iid].append(rec)

    # ── Process per-instrument order books ───────────────────
    all_trades = []
    all_metrics = []

    for inst_id, records in inst_records.items():
        if inst_id not in instruments:
            print(f"Warning: unknown instrument {inst_id}, skipping")
            continue

        inst_info = instruments[inst_id]
        price_scale = inst_info['price_scale']

        book = OrderBook()
        vol_sum = 0
        val_sum = 0.0
        trade_count = 0
        max_spread = 0.0
        iceberg_count = 0
        recent_fills = []  # (ts, price_fp, side)

        for rec in records:
            ts = rec['ts']
            oid = rec['oid']
            pfp = rec['price_fp']
            qty = rec['qty']
            action = rec['action']
            side = rec['side']
            price = pfp / price_scale

            if action == ACTION_ADD:
                # Check for iceberg reload
                for ft, fp, fs in recent_fills:
                    if pfp == fp and side == fs and ts - ft <= 100_000:
                        iceberg_count += 1
                        break
                book.add(oid, pfp, qty, side)

            elif action == ACTION_CANCEL:
                book.cancel(oid)

            elif action == ACTION_MODIFY:
                book.modify(oid, pfp, qty)

            elif action == ACTION_TRADE:
                val_sum += price * qty
                vol_sum += qty
                trade_count += 1
                book.trade(oid, qty)
                all_trades.append({
                    'instrument_id': inst_id,
                    'timestamp_ns': ts,
                    'price': round(price, 6),
                    'quantity': qty,
                    'side': chr(side),
                    'action': 'T',
                    'sequence': rec['seq'],
                })

            elif action == ACTION_FILL:
                val_sum += price * qty
                vol_sum += qty
                trade_count += 1
                recent_fills = [(t, p, s) for t, p, s in recent_fills
                                if ts - t <= 1_000_000]
                recent_fills.append((ts, pfp, side))
                book.fill(oid)
                all_trades.append({
                    'instrument_id': inst_id,
                    'timestamp_ns': ts,
                    'price': round(price, 6),
                    'quantity': qty,
                    'side': chr(side),
                    'action': 'F',
                    'sequence': rec['seq'],
                })

            # Track spread
            bb = book.best_bid_fp()
            ba = book.best_ask_fp()
            if bb is not None and ba is not None:
                spread = (ba - bb) / price_scale
                if spread > max_spread:
                    max_spread = spread

        # Final metrics
        vwap = val_sum / vol_sum if vol_sum > 0 else 0.0
        bb_fp = book.best_bid_fp()
        ba_fp = book.best_ask_fp()

        all_metrics.append({
            'instrument_id': inst_id,
            'symbol': inst_info['symbol'],
            'vwap': round(vwap, 6),
            'total_volume': vol_sum,
            'trade_count': trade_count,
            'max_spread': round(max_spread, 6),
            'iceberg_count': iceberg_count,
            'final_best_bid': round(bb_fp / price_scale, 6) if bb_fp else None,
            'final_best_ask': round(ba_fp / price_scale, 6) if ba_fp else None,
            'final_bid_size': book.size_at_price(bb_fp, SIDE_BID) if bb_fp else 0,
            'final_ask_size': book.size_at_price(ba_fp, SIDE_ASK) if ba_fp else 0,
            'bid_depth': book.depth(SIDE_BID),
            'ask_depth': book.depth(SIDE_ASK),
            'message_count': len(records),
        })

    # ── Write output SQLite database ─────────────────────────
    os.makedirs(os.path.dirname(OUTPUT_DB), exist_ok=True)
    if os.path.exists(OUTPUT_DB):
        os.remove(OUTPUT_DB)

    conn = sqlite3.connect(OUTPUT_DB)
    c = conn.cursor()

    c.execute('''CREATE TABLE metrics (
        instrument_id INTEGER, symbol TEXT, vwap REAL, total_volume INTEGER,
        trade_count INTEGER, max_spread REAL, iceberg_count INTEGER,
        final_best_bid REAL, final_best_ask REAL, final_bid_size INTEGER,
        final_ask_size INTEGER, bid_depth INTEGER, ask_depth INTEGER,
        message_count INTEGER
    )''')

    c.execute('''CREATE TABLE trades (
        instrument_id INTEGER, timestamp_ns INTEGER, price REAL,
        quantity INTEGER, side TEXT, action TEXT, sequence INTEGER
    )''')

    c.execute('''CREATE TABLE gaps (
        channel_id INTEGER, expected_seq INTEGER, actual_seq INTEGER,
        gap_size INTEGER
    )''')

    c.execute('''CREATE TABLE latency (
        channel_id INTEGER, capture_epoch_us INTEGER,
        message_time_ns INTEGER, packet_msg_count INTEGER
    )''')

    for m in all_metrics:
        c.execute('INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (m['instrument_id'], m['symbol'], m['vwap'], m['total_volume'],
                   m['trade_count'], m['max_spread'], m['iceberg_count'],
                   m['final_best_bid'], m['final_best_ask'],
                   m['final_bid_size'], m['final_ask_size'],
                   m['bid_depth'], m['ask_depth'], m['message_count']))

    for t in all_trades:
        c.execute('INSERT INTO trades VALUES (?,?,?,?,?,?,?)',
                  (t['instrument_id'], t['timestamp_ns'], t['price'],
                   t['quantity'], t['side'], t['action'], t['sequence']))

    for g in gaps:
        c.execute('INSERT INTO gaps VALUES (?,?,?,?)',
                  (g['channel_id'], g['expected_seq'], g['actual_seq'], g['gap_size']))

    for l in latency_data:
        c.execute('INSERT INTO latency VALUES (?,?,?,?)',
                  (l['channel_id'], l['capture_epoch_us'],
                   l['message_time_ns'], l['packet_msg_count']))

    conn.commit()
    conn.close()

    print(f"\nWrote output to {OUTPUT_DB}")
    print(f"  Metrics: {len(all_metrics)} instruments")
    print(f"  Trades: {len(all_trades)} records")
    print(f"  Gaps: {len(gaps)} detected")
    print(f"  Latency: {len(latency_data)} entries")


if __name__ == '__main__':
    run_pipeline()
