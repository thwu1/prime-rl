#!/usr/bin/env python3
"""DBN Feed Reconciler — reference solution."""

import json
import os
import struct
from collections import defaultdict

RECORD_FMT = '<BBHIQQqIBBccQiI'
RECORD_SIZE = struct.calcsize(RECORD_FMT)  # 56
PRICE_SCALE = 1_000_000_000
UNDEF_PRICE = 0x7FFFFFFFFFFFFFFF


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------
def parse_header(data):
    """Parse the variable-length DBN file header.
    Returns (header_dict, offset_after_header).
    """
    assert data[:3] == b'DBN', f"Bad magic: {data[:3]!r}"
    version = data[3]
    name_len = struct.unpack_from('<H', data, 4)[0]
    dataset = data[6:6 + name_len].decode('utf-8')
    off = 6 + name_len
    record_count = struct.unpack_from('<I', data, off)[0]
    start_ts = struct.unpack_from('<Q', data, off + 4)[0]
    end_ts = struct.unpack_from('<Q', data, off + 12)[0]
    compression = data[off + 20]
    schema = data[off + 21]
    return {
        'version': version,
        'dataset': dataset,
        'record_count': record_count,
        'start_ts': start_ts,
        'end_ts': end_ts,
        'compression': compression,
        'schema': schema,
    }, off + 24


def parse_records(raw_data, venue):
    """Unpack MBO records from raw (decompressed) bytes."""
    records = []
    offset = 0
    while offset + RECORD_SIZE <= len(raw_data):
        fields = struct.unpack_from(RECORD_FMT, raw_data, offset)
        (length, rtype, pub_id, inst_id, ts_event,
         order_id, price, size, flags, channel_id,
         action_b, side_b, ts_recv, ts_in_delta, sequence) = fields
        records.append({
            'venue': venue,
            'publisher_id': pub_id,
            'instrument_id': inst_id,
            'ts_event': ts_event,
            'order_id': order_id,
            'price': price,
            'size': size,
            'action': action_b.decode('ascii'),
            'side': side_b.decode('ascii'),
            'sequence': sequence,
        })
        offset += RECORD_SIZE
    return records


def read_feed(filepath):
    """Read a .bin feed file, handling header and optional zstd decompression."""
    with open(filepath, 'rb') as f:
        data = f.read()
    header, hdr_end = parse_header(data)
    payload = data[hdr_end:]
    if header['compression'] == 1:
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        payload = dctx.decompress(payload)
    return header, parse_records(payload, header['dataset'])


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------
class OrderBook:
    def __init__(self):
        self.orders = {}  # order_id -> {price, size, side}

    def add(self, order_id, price, size, side):
        self.orders[order_id] = {'price': price, 'size': size, 'side': side}

    def cancel(self, order_id):
        return self.orders.pop(order_id, None) is not None

    def modify(self, order_id, price, size, side):
        if order_id in self.orders:
            self.orders[order_id] = {'price': price, 'size': size, 'side': side}
        else:
            self.add(order_id, price, size, side)

    def fill(self, order_id, fill_size):
        if order_id in self.orders:
            self.orders[order_id]['size'] -= fill_size
            if self.orders[order_id]['size'] <= 0:
                del self.orders[order_id]
            return True
        return False

    def clear(self):
        self.orders.clear()

    def get_levels(self, side, max_levels=5):
        level_map = defaultdict(lambda: {'size': 0, 'count': 0})
        for o in self.orders.values():
            if o['side'] == side:
                level_map[o['price']]['size'] += o['size']
                level_map[o['price']]['count'] += 1
        levels = [(px, d['size'], d['count']) for px, d in level_map.items()]
        if side == 'B':
            levels.sort(key=lambda x: -x[0])
        else:
            levels.sort(key=lambda x: x[0])
        return [{'price': px / PRICE_SCALE, 'size': sz, 'count': ct}
                for px, sz, ct in levels[:max_levels]]

    def best_bid(self):
        bids = [o['price'] for o in self.orders.values() if o['side'] == 'B']
        return max(bids) if bids else None

    def best_ask(self):
        asks = [o['price'] for o in self.orders.values() if o['side'] == 'A']
        return min(asks) if asks else None

    def is_empty(self):
        return len(self.orders) == 0


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------
def take_snapshot(books, timestamp, canonical_symbols):
    snap = {'timestamp': timestamp, 'books': {}}
    for sym in sorted(canonical_symbols):
        book = books.get(sym)
        if book is None or book.is_empty():
            continue
        bids = book.get_levels('B')
        asks = book.get_levels('A')
        if bids or asks:
            snap['books'][sym] = {'bids': bids, 'asks': asks}
    return snap


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Load config
    with open('/app/symbology.json') as f:
        symbology = json.load(f)
    with open('/app/checkpoints.json') as f:
        checkpoints = json.load(f)

    # Build lookup: (venue, inst_id) -> canonical symbol
    id_to_sym = {}
    all_symbols = []
    for m in symbology['mappings']:
        canonical = m['canonical']
        all_symbols.append(canonical)
        for venue, inst_id in m['venues'].items():
            id_to_sym[(venue, inst_id)] = canonical

    # Read all feeds
    all_records = []
    feed_dir = '/app/feeds'
    for fname in sorted(os.listdir(feed_dir)):
        if fname.endswith('.bin'):
            _hdr, records = read_feed(os.path.join(feed_dir, fname))
            all_records.extend(records)

    # Sort by ts_event (stable sort preserves file order for ties)
    all_records.sort(key=lambda r: r['ts_event'])

    # State
    books = {}           # canonical -> OrderBook
    anomalies = []
    known_orders = set() # all order_ids ever added/modified (for phantom detection)
    venue_seqs = {}      # venue -> last sequence number
    crossed = set()      # symbols already reported as crossed

    # Collect trades for duplicate detection
    trade_key_to_venues = defaultdict(set)  # (canonical, ts, price, size) -> {venue...}

    checkpoint_idx = 0
    results = []

    for rec in all_records:
        ts = rec['ts_event']
        venue = rec['venue']
        inst_id = rec['instrument_id']
        canonical = id_to_sym.get((venue, inst_id))
        if canonical is None:
            continue

        # Emit snapshots for any checkpoints before this event
        while checkpoint_idx < len(checkpoints) and checkpoints[checkpoint_idx] < ts:
            results.append(take_snapshot(books, checkpoints[checkpoint_idx], all_symbols))
            checkpoint_idx += 1

        # Sequence gap detection (per-venue)
        seq = rec['sequence']
        if venue in venue_seqs:
            expected = venue_seqs[venue] + 1
            if seq > expected:
                anomalies.append({
                    'type': 'sequence_gap',
                    'timestamp': ts,
                    'venue': venue,
                    'expected_seq': expected,
                    'actual_seq': seq,
                })
        venue_seqs[venue] = seq

        if canonical not in books:
            books[canonical] = OrderBook()
        book = books[canonical]
        action = rec['action']

        if action == 'A':
            book.add(rec['order_id'], rec['price'], rec['size'], rec['side'])
            known_orders.add(rec['order_id'])

        elif action == 'C':
            if rec['order_id'] not in known_orders:
                anomalies.append({
                    'type': 'phantom_order',
                    'timestamp': ts,
                    'venue': venue,
                    'order_id': rec['order_id'],
                })
            book.cancel(rec['order_id'])

        elif action == 'M':
            book.modify(rec['order_id'], rec['price'], rec['size'], rec['side'])
            known_orders.add(rec['order_id'])

        elif action == 'T':
            trade_key_to_venues[(canonical, ts, rec['price'], rec['size'])].add(venue)

        elif action == 'F':
            if rec['order_id'] not in known_orders:
                anomalies.append({
                    'type': 'phantom_order',
                    'timestamp': ts,
                    'venue': venue,
                    'order_id': rec['order_id'],
                })
            book.fill(rec['order_id'], rec['size'])

        elif action == 'R':
            book.clear()

        # Crossed book check (only Add/Modify can create a cross)
        if action in ('A', 'M') and canonical not in crossed:
            bb = book.best_bid()
            ba = book.best_ask()
            if bb is not None and ba is not None and bb >= ba:
                anomalies.append({
                    'type': 'crossed_book',
                    'timestamp': ts,
                    'symbol': canonical,
                    'best_bid': bb / PRICE_SCALE,
                    'best_ask': ba / PRICE_SCALE,
                })
                crossed.add(canonical)

    # Remaining checkpoints
    while checkpoint_idx < len(checkpoints):
        results.append(take_snapshot(books, checkpoints[checkpoint_idx], all_symbols))
        checkpoint_idx += 1

    # Duplicate trade anomalies
    for (canonical, ts, price, size), venues in trade_key_to_venues.items():
        if len(venues) > 1:
            anomalies.append({
                'type': 'duplicate_trade',
                'timestamp': ts,
                'symbol': canonical,
                'price': price / PRICE_SCALE,
                'size': size,
            })

    # Sort anomalies by timestamp
    anomalies.sort(key=lambda a: a['timestamp'])

    # Write output
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/snapshots.json', 'w') as f:
        json.dump(results, f, indent=2)
    with open('/app/output/anomalies.json', 'w') as f:
        json.dump(anomalies, f, indent=2)


if __name__ == '__main__':
    main()
