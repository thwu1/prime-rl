#!/usr/bin/env python3

"""
SIMDB WAL Forensic Recovery

Strategy:
1. data.db is corrupted (CRC mismatch) -- cannot be used as base state.
2. Reconstruct base state from backup.sqlite (pre-WAL snapshot).
   - Use kv_snapshot table for page data, db_config for metadata.
   - Do NOT trust wal_metadata (pre-crash monitoring, partially wrong).
   - Do NOT use engine/recovery.py (buggy: ignores CRC corruption).
3. Parse wal.log: validate per-frame CRC32, classify transactions,
   stop on truncation.
4. Apply only committed (valid BEGIN + valid COMMIT, no corrupted frames)
   transaction writes in WAL file order.
5. Write recovered.db with correct header checksum.
6. Validate with simdb-ctl validate.
"""

import sqlite3
import struct
import zlib

PAGE_SIZE = 4096
HEADER_SIZE = 32
WAL_HEADER_SIZE = 32

# Frame types (from engine/wal.py)
FT_BEGIN = 0x01
FT_PAGE_WRITE = 0x02
FT_COMMIT = 0x03
FT_ABORT = 0x04


def reconstruct_base_from_sqlite(sqlite_path):
    """Read the pre-WAL database state from the SQLite backup.

    Entries must be sorted by key to match the engine's Page.to_bytes()
    format (required by simdb-ctl validate).
    """
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()

    cur.execute("SELECT val FROM db_config WHERE param = 'page_count'")
    page_count = int(cur.fetchone()[0])

    cur.execute(
        "SELECT page_num, key, value FROM kv_snapshot "
        "ORDER BY page_num, key"
    )
    pages_data = {}
    for pn, k, v in cur.fetchall():
        pages_data.setdefault(pn, []).append((k, v))

    conn.close()

    pages = []
    for i in range(page_count):
        entries = pages_data.get(i, [])
        pages.append(encode_page(entries))

    return pages


def encode_page(entries):
    """Serialize key-value entries into a PAGE_SIZE-byte page.

    Entries are sorted by key for deterministic output, matching
    the engine's Page.to_bytes() sort order.
    """
    sorted_entries = sorted(entries, key=lambda x: x[0])
    buf = struct.pack('>H', len(sorted_entries))
    for key, value in sorted_entries:
        kb = key.encode('utf-8')
        vb = value.encode('utf-8')
        buf += struct.pack('>HH', len(kb), len(vb))
        buf += kb + vb
    return buf + b'\x00' * (PAGE_SIZE - len(buf))


def parse_wal(wal_path):
    """Parse WAL and return committed writes in WAL file order.

    Transaction classification:
      - Committed: has valid BEGIN + valid COMMIT, no corrupted frames
      - Aborted: has ABORT frame
      - Corrupted: any frame for this txn failed CRC validation
      - Uncommitted: has BEGIN but no COMMIT/ABORT
      - Phantom: has COMMIT but no BEGIN
      - Truncated: frame_length exceeds remaining file bytes
    """
    with open(wal_path, 'rb') as f:
        data = f.read()

    magic = data[0:8]
    if magic != b'SIMWAL\x00\x00':
        raise ValueError(f"Bad WAL magic: {magic!r}")

    has_begin = set()
    txn_state = {}
    corrupted = set()
    all_writes = []

    offset = WAL_HEADER_SIZE
    while offset < len(data):
        if offset + 4 > len(data):
            break

        frame_len = struct.unpack_from('>I', data, offset)[0]

        if offset + 4 + frame_len > len(data):
            break  # truncated frame -- crash boundary

        frame_bytes = data[offset + 4:offset + 4 + frame_len]
        body = frame_bytes[:-4]
        stored_crc = struct.unpack_from(
            '>I', frame_bytes, len(frame_bytes) - 4)[0]
        computed_crc = zlib.crc32(body) & 0xFFFFFFFF

        ft, txn_id = struct.unpack_from('>BI', body, 0)

        if stored_crc != computed_crc:
            # Frame CRC is invalid -- mark entire transaction as corrupted
            corrupted.add(txn_id)
        else:
            if ft == FT_BEGIN:
                has_begin.add(txn_id)
                txn_state.setdefault(txn_id, 'active')
            elif ft == FT_COMMIT:
                txn_state[txn_id] = 'committed'
            elif ft == FT_ABORT:
                txn_state[txn_id] = 'aborted'
            elif ft == FT_PAGE_WRITE:
                page_num = struct.unpack_from('>I', body, 5)[0]
                page_data = body[9:9 + PAGE_SIZE]
                all_writes.append((txn_id, page_num, bytes(page_data)))

        offset += 4 + frame_len

    # Committed = has BEGIN + has COMMIT + not corrupted
    committed_txns = {
        tid for tid, st in txn_state.items()
        if st == 'committed'
        and tid in has_begin
        and tid not in corrupted
    }

    return [(tid, pn, pd) for tid, pn, pd in all_writes
            if tid in committed_txns]


def main():
    # 1. Reconstruct base state from SQLite backup
    pages = reconstruct_base_from_sqlite('/app/backup.sqlite')

    # 2. Parse WAL and get committed writes
    committed_writes = parse_wal('/app/wal.log')

    # 3. Apply committed writes in WAL file order (last write per page wins)
    for _txn_id, page_num, page_data in committed_writes:
        pages[page_num] = bytearray(page_data)

    # 4. Compute header checksum and write recovered database
    all_page_bytes = b''.join(bytes(p) for p in pages)
    checksum = zlib.crc32(all_page_bytes) & 0xFFFFFFFF

    header = struct.pack('>6sHIII',
                         b'SIMDB\x00', 1, PAGE_SIZE, len(pages), checksum)
    header += b'\x00' * (HEADER_SIZE - len(header))

    with open('/app/recovered.db', 'wb') as f:
        f.write(header)
        f.write(all_page_bytes)

    print(f"Recovery complete: /app/recovered.db")
    print(f"  Pages: {len(pages)}")
    print(f"  Committed writes applied: {len(committed_writes)}")
    print(f"  Checksum: 0x{checksum:08X}")


if __name__ == '__main__':
    main()
