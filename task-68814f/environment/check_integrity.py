#!/usr/bin/env python3
"""SIMDB integrity checker — validates structural correctness of a database file."""

import os
import struct
import sys
import zlib


def check_database(path: str) -> list:
    """Return a list of integrity-check errors (empty means OK)."""
    errors = []

    if not os.path.isfile(path):
        return [f'File not found: {path}']

    with open(path, 'rb') as fh:
        data = fh.read()

    if len(data) < 32:
        return ['File smaller than minimum header size (32 bytes)']

    # ── Header fields ──────────────────────────────────────────────
    magic = data[0:6]
    if magic != b'SIMDB\x00':
        errors.append(f'Invalid magic bytes: {magic!r} (expected SIMDB\\x00)')

    version = struct.unpack_from('>H', data, 6)[0]
    if version != 1:
        errors.append(f'Unsupported format version: {version}')

    page_size = struct.unpack_from('>I', data, 8)[0]
    page_count = struct.unpack_from('>I', data, 12)[0]
    stored_crc = struct.unpack_from('>I', data, 16)[0]

    expected_len = 32 + page_count * page_size
    if len(data) != expected_len:
        errors.append(
            f'File size mismatch: actual {len(data)}, '
            f'expected {expected_len} (header 32 + {page_count} x {page_size})')

    # ── CRC-32 ─────────────────────────────────────────────────────
    page_bytes = data[32:]
    computed_crc = zlib.crc32(page_bytes) & 0xFFFFFFFF
    if stored_crc != computed_crc:
        errors.append(
            f'Header CRC-32 mismatch: stored 0x{stored_crc:08X}, '
            f'computed 0x{computed_crc:08X}')

    # ── Per-page structural checks ────────────────────────────────
    for i in range(min(page_count, (len(data) - 32) // page_size)):
        base = 32 + i * page_size
        pdata = data[base:base + page_size]
        try:
            n_entries = struct.unpack_from('>H', pdata, 0)[0]
            pos = 2
            for j in range(n_entries):
                if pos + 4 > page_size:
                    errors.append(
                        f'Page {i}, entry {j}: header exceeds page boundary')
                    break
                klen = struct.unpack_from('>H', pdata, pos)[0]
                vlen = struct.unpack_from('>H', pdata, pos + 2)[0]
                pos += 4 + klen + vlen
                if pos > page_size:
                    errors.append(
                        f'Page {i}, entry {j}: data overflows page '
                        f'(needs {pos} bytes, page is {page_size})')
                    break
        except struct.error as exc:
            errors.append(f'Page {i}: struct parse error: {exc}')

    return errors


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/app/data.db'
    errors = check_database(path)
    if errors:
        print(f'INTEGRITY CHECK FAILED for {path}')
        for e in errors:
            print(f'  - {e}')
        sys.exit(1)
    else:
        print(f'INTEGRITY CHECK PASSED for {path}')
        sys.exit(0)


if __name__ == '__main__':
    main()
