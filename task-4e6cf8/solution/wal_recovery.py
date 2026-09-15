#!/usr/bin/env python3
"""SQLite WAL forensics and recovery tool.

Parses the raw binary WAL format, validates frame checksums using SQLite's
incremental checksum algorithm, detects corruption, and recovers the database
to the last fully committed valid transaction.
"""

import struct
import sys
import json
import shutil
import os


def wal_checksum(data, s0=0, s1=0, little_endian=True):
    """Compute SQLite WAL checksum.

    The WAL uses an incremental checksum of two 32-bit unsigned integers.
    Data is processed in 8-byte chunks as pairs of 32-bit words.

    The byte order of the words is determined by the WAL magic number:
      0x377f0682 -> little-endian words
      0x377f0683 -> big-endian words

    Algorithm per pair of words (w0, w1):
      s0 += w0 + s1
      s1 += w1 + s0
    All arithmetic wraps at 32 bits.

    The stored checksum values in the WAL are always big-endian.
    """
    fmt = '<I' if little_endian else '>I'
    mask = 0xFFFFFFFF
    for i in range(0, len(data), 8):
        w0 = struct.unpack(fmt, data[i:i + 4])[0]
        w1 = struct.unpack(fmt, data[i + 4:i + 8])[0]
        s0 = (s0 + w0 + s1) & mask
        s1 = (s1 + w1 + s0) & mask
    return s0, s1


def parse_and_recover(db_path):
    wal_path = db_path + '-wal'
    data_dir = os.path.dirname(db_path)

    with open(wal_path, 'rb') as f:
        wal = f.read()

    if len(wal) < 32:
        raise ValueError("WAL file too small for header")

    # ---- WAL Header (32 bytes) ----
    magic = struct.unpack('>I', wal[0:4])[0]
    little_endian = (magic == 0x377f0682)

    version = struct.unpack('>I', wal[4:8])[0]
    page_size = struct.unpack('>I', wal[8:12])[0]
    checkpoint_seq = struct.unpack('>I', wal[12:16])[0]
    salt1 = struct.unpack('>I', wal[16:20])[0]
    salt2 = struct.unpack('>I', wal[20:24])[0]
    hdr_cksum1 = struct.unpack('>I', wal[24:28])[0]
    hdr_cksum2 = struct.unpack('>I', wal[28:32])[0]

    # Verify header checksum (covers first 24 bytes)
    h_s0, h_s1 = wal_checksum(wal[0:24], little_endian=little_endian)
    if h_s0 != hdr_cksum1 or h_s1 != hdr_cksum2:
        raise ValueError("WAL header checksum mismatch")

    header_info = {
        'magic': magic,
        'page_size': page_size,
        'checkpoint_seq': checkpoint_seq,
        'salt1': salt1,
        'salt2': salt2,
        'version': version,
    }

    # ---- Frame processing ----
    frame_hdr_size = 24
    frame_size = frame_hdr_size + page_size
    total_frames = (len(wal) - 32) // frame_size

    frames = []
    running_s0, running_s1 = h_s0, h_s1
    first_invalid = None
    valid_count = 0
    tx_count = 0

    committed_pages = {}   # pgno -> page_data from committed txns
    current_tx_pages = {}  # pgno -> page_data in current uncommitted txn
    last_commit_db_size = None

    for i in range(total_frames):
        offset = 32 + i * frame_size

        pgno = struct.unpack('>I', wal[offset:offset + 4])[0]
        db_size = struct.unpack('>I', wal[offset + 4:offset + 8])[0]
        f_salt1 = struct.unpack('>I', wal[offset + 8:offset + 12])[0]
        f_salt2 = struct.unpack('>I', wal[offset + 12:offset + 16])[0]
        f_cksum1 = struct.unpack('>I', wal[offset + 16:offset + 20])[0]
        f_cksum2 = struct.unpack('>I', wal[offset + 20:offset + 24])[0]

        page_data = wal[offset + frame_hdr_size:offset + frame_size]

        salt_ok = (f_salt1 == salt1 and f_salt2 == salt2)

        # Checksum covers frame header first 8 bytes + page data
        cksum_input = wal[offset:offset + 8] + page_data
        computed_s0, computed_s1 = wal_checksum(
            cksum_input, running_s0, running_s1, little_endian
        )

        checksum_valid = (computed_s0 == f_cksum1 and computed_s1 == f_cksum2)
        is_commit = (db_size > 0)
        is_valid = salt_ok and checksum_valid

        frames.append({
            'index': i,
            'page_number': pgno,
            'is_commit': is_commit,
            'checksum_valid': is_valid,
        })

        if is_valid:
            valid_count += 1
            running_s0, running_s1 = computed_s0, computed_s1
            current_tx_pages[pgno] = page_data
            if is_commit:
                tx_count += 1
                committed_pages.update(current_tx_pages)
                current_tx_pages = {}
                last_commit_db_size = db_size
        else:
            first_invalid = i
            current_tx_pages = {}
            break

    # ---- Report ----
    report = {
        'header': header_info,
        'total_frames': total_frames,
        'valid_frames': valid_count,
        'corrupted_frames': 1 if first_invalid is not None else 0,
        'valid_transactions': tx_count,
        'first_invalid_frame': first_invalid,
        'frames': frames,
    }

    report_path = os.path.join(data_dir, 'wal_report.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    # ---- Recover database ----
    output_path = os.path.join(data_dir, 'recovered.db')
    shutil.copy2(db_path, output_path)

    with open(output_path, 'r+b') as f:
        for pgno, pdata in committed_pages.items():
            f.seek((pgno - 1) * page_size)
            f.write(pdata)

        if last_commit_db_size:
            f.truncate(last_commit_db_size * page_size)

        # Switch journal mode from WAL to rollback journal
        f.seek(18)
        f.write(b'\x01\x01')

    print(f"Report: {report_path}")
    print(f"Recovered DB: {output_path}")
    print(f"Valid transactions: {tx_count}")
    print(f"First invalid frame: {first_invalid}")

    return report


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <database_path>", file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(db_path + '-wal'):
        print(f"WAL not found: {db_path}-wal", file=sys.stderr)
        sys.exit(1)

    parse_and_recover(db_path)


if __name__ == '__main__':
    main()
