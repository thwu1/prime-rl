"""Reference implementation: DBN MBO order book reconstruction engine."""

import struct
import json
import os
from collections import defaultdict

RECORD_SIZE = 56
RECORD_FMT = '<BBHIQQqIBBBBQiI'
UNDEF_PRICE = 0x7FFFFFFFFFFFFFFF
PRICE_SCALE = 1_000_000_000


def parse_records(filepath):
    """Parse binary MBO records from a DBN feed file."""
    records = []
    with open(filepath, 'rb') as f:
        while True:
            data = f.read(RECORD_SIZE)
            if len(data) < RECORD_SIZE:
                break
            fields = struct.unpack(RECORD_FMT, data)
            records.append({
                'instrument_id': fields[3],
                'ts_event': fields[4],
                'order_id': fields[5],
                'price': fields[6],
                'size': fields[7],
                'action': chr(fields[10]),
                'side': chr(fields[11]),
            })
    return records


class OrderBook:
    """L3 order book maintaining individual orders keyed by order_id."""

    def __init__(self):
        self.orders = {}
        self._priority = 0

    def add(self, oid, px, sz, side):
        self._priority += 1
        self.orders[oid] = {
            'price': px, 'size': sz, 'side': side, 'pri': self._priority
        }

    def cancel(self, oid):
        self.orders.pop(oid, None)

    def modify(self, oid, px, sz, side):
        if oid in self.orders:
            old = self.orders[oid]
            if old['price'] != px:
                # Price changed: lose priority (remove and re-add)
                self._priority += 1
                self.orders[oid] = {
                    'price': px, 'size': sz, 'side': side, 'pri': self._priority
                }
            else:
                # Price unchanged: keep priority, update size/side
                old['size'] = sz
                old['side'] = side
        else:
            # Order not found: treat as Add
            self.add(oid, px, sz, side)

    def fill(self, oid, fill_sz):
        if oid in self.orders:
            self.orders[oid]['size'] -= fill_sz
            if self.orders[oid]['size'] <= 0:
                del self.orders[oid]

    def clear(self):
        self.orders.clear()

    def has_orders(self):
        return len(self.orders) > 0

    def get_levels(self, side, max_levels=5):
        """Aggregate orders by price level, return sorted list."""
        agg = defaultdict(lambda: [0, 0])  # [total_size, count]
        for o in self.orders.values():
            if o['side'] == side:
                agg[o['price']][0] += o['size']
                agg[o['price']][1] += 1

        reverse = (side == 'B')  # Bids descending, asks ascending
        sorted_px = sorted(agg.keys(), reverse=reverse)
        result = []
        for px in sorted_px[:max_levels]:
            result.append({
                'price': px / PRICE_SCALE,
                'size': agg[px][0],
                'count': agg[px][1],
            })
        return result


def snapshot_books(books):
    """Create a snapshot of all non-empty order books."""
    instruments = {}
    for inst_id in sorted(books.keys()):
        book = books[inst_id]
        if book.has_orders():
            instruments[str(inst_id)] = {
                'bids': book.get_levels('B'),
                'asks': book.get_levels('A'),
            }
    return instruments


def main():
    records = parse_records('/app/data/feed.bin')
    with open('/app/data/checkpoints.json') as f:
        checkpoints = json.load(f)

    # Build a merged timeline: records processed before checkpoints at same ts
    events = []
    for i, rec in enumerate(records):
        events.append((0, rec['ts_event'], i))   # 0 = record (sorts first)
    for j, cp_ts in enumerate(checkpoints):
        events.append((1, cp_ts, j))              # 1 = checkpoint (sorts second)

    events.sort(key=lambda e: (e[1], e[0], e[2]))

    books = defaultdict(OrderBook)
    ohlcv = {}
    snapshots_by_idx = {}

    for etype, ts, idx in events:
        if etype == 0:
            # Process record
            rec = records[idx]
            inst = rec['instrument_id']
            book = books[inst]
            action = rec['action']

            if action == 'A':
                book.add(rec['order_id'], rec['price'], rec['size'], rec['side'])
            elif action == 'C':
                book.cancel(rec['order_id'])
            elif action == 'M':
                book.modify(rec['order_id'], rec['price'], rec['size'], rec['side'])
            elif action == 'T':
                if rec['price'] != UNDEF_PRICE:
                    ts_start = (rec['ts_event'] // 1_000_000_000) * 1_000_000_000
                    key = (inst, ts_start)
                    px = rec['price'] / PRICE_SCALE
                    if key not in ohlcv:
                        ohlcv[key] = {
                            'open': px, 'high': px, 'low': px, 'close': px,
                            'volume': rec['size']
                        }
                    else:
                        bar = ohlcv[key]
                        bar['high'] = max(bar['high'], px)
                        bar['low'] = min(bar['low'], px)
                        bar['close'] = px
                        bar['volume'] += rec['size']
            elif action == 'F':
                book.fill(rec['order_id'], rec['size'])
            elif action == 'R':
                book.clear()
        else:
            # Checkpoint: snapshot the books
            snap = {
                'ts': ts,
                'instruments': snapshot_books(books),
            }
            snapshots_by_idx[idx] = snap

    # Order snapshots by original checkpoint order
    final_snapshots = [snapshots_by_idx[i] for i in range(len(checkpoints))]

    # Build sorted OHLCV list
    ohlcv_list = []
    for (inst, ts_start) in sorted(ohlcv.keys()):
        bar = ohlcv[(inst, ts_start)]
        ohlcv_list.append({
            'instrument_id': inst,
            'ts_start': ts_start,
            'open': bar['open'],
            'high': bar['high'],
            'low': bar['low'],
            'close': bar['close'],
            'volume': bar['volume'],
        })

    # Write outputs
    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/snapshots.json', 'w') as f:
        json.dump(final_snapshots, f)
    with open('/app/output/ohlcv.json', 'w') as f:
        json.dump(ohlcv_list, f)


if __name__ == '__main__':
    main()
