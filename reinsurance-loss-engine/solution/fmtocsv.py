#!/usr/bin/env python3
"""Convert binary loss stream to CSV format."""
import sys
import struct


def main():
    data = sys.stdin.buffer.read()
    if len(data) < 4:
        return
    offset = 4  # skip stream header

    sys.stdout.write('event_id,output_id,sidx,loss\n')

    while offset + 8 <= len(data):
        event_id = struct.unpack_from('<i', data, offset)[0]
        offset += 4
        item_id = struct.unpack_from('<i', data, offset)[0]
        offset += 4
        while offset + 4 <= len(data):
            sidx = struct.unpack_from('<i', data, offset)[0]
            offset += 4
            if sidx == 0:
                break
            if offset + 8 > len(data):
                break
            loss = struct.unpack_from('<d', data, offset)[0]
            offset += 8
            sys.stdout.write(f'{event_id},{item_id},{sidx},{loss:.4f}\n')

    sys.stdout.flush()


if __name__ == '__main__':
    main()
