#!/usr/bin/env python3
"""Convert CSV loss stream to binary format."""
import sys
import csv
import struct
from collections import OrderedDict


def main():
    reader = csv.DictReader(sys.stdin)
    buf = sys.stdout.buffer
    buf.write(struct.pack('<i', 1))

    blocks = OrderedDict()
    for row in reader:
        event_id = int(row['event_id'])
        if 'item_id' in row:
            item_id = int(row['item_id'])
        else:
            item_id = int(row['output_id'])
        sidx = int(row['sidx'])
        loss = float(row['loss'])
        key = (event_id, item_id)
        if key not in blocks:
            blocks[key] = []
        blocks[key].append((sidx, loss))

    for (event_id, item_id), samples in blocks.items():
        buf.write(struct.pack('<ii', event_id, item_id))
        for sidx, loss in samples:
            buf.write(struct.pack('<id', sidx, loss))
        buf.write(struct.pack('<i', 0))

    buf.flush()


if __name__ == '__main__':
    main()
