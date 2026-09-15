"""
SIMDB Recovery Module

Provides automated crash recovery from WAL files.  Reconstructs
the database by loading the pre-WAL base state from a SQLite backup
and replaying committed transactions.

Note: This module was designed for the initial single-WAL recovery
path and may not handle all edge cases in newer deployments.
"""

import struct
import zlib
import sqlite3

PAGE_SIZE = 4096
HEADER_SIZE = 32

FT_BEGIN = 0x01
FT_PAGE_WRITE = 0x02
FT_COMMIT = 0x03
FT_ABORT = 0x04


def load_base_state(backup_path):
    """Load base database state from SQLite backup.

    Reads the ``kv_snapshot`` and ``db_config`` tables to reconstruct
    the binary pages as they were before WAL transactions began.
    """
    conn = sqlite3.connect(backup_path)
    cur = conn.cursor()

    cur.execute("SELECT val FROM db_config WHERE param = 'page_count'")
    page_count = int(cur.fetchone()[0])

    cur.execute("SELECT val FROM db_config WHERE param = 'page_size'")
    page_size = int(cur.fetchone()[0])

    pages = [bytearray(page_size) for _ in range(page_count)]

    cur.execute(
        "SELECT page_num, key, value FROM kv_snapshot ORDER BY page_num")
    page_entries = {}
    for pn, k, v in cur.fetchall():
        page_entries.setdefault(pn, []).append((k, v))

    for pn, entries in page_entries.items():
        page_data = _encode_page(entries, page_size)
        pages[pn] = bytearray(page_data)

    conn.close()
    return pages


def _encode_page(entries, page_size=PAGE_SIZE):
    """Encode key-value entries to binary page format."""
    buf = struct.pack('>H', len(entries))
    for k, v in entries:
        kb = k.encode('utf-8')
        vb = v.encode('utf-8')
        buf += struct.pack('>HH', len(kb), len(vb)) + kb + vb
    return buf + b'\x00' * (page_size - len(buf))


def classify_wal_transactions(wal_path):
    """Parse WAL and classify each transaction.

    Returns dict mapping txn_id -> {
        'status': 'committed' | 'aborted' | 'in_progress',
        'writes': [(page_num, page_data), ...]
    }

    Recovery order: transactions are replayed in transaction ID
    order (ascending) to ensure deterministic recovery.
    """
    with open(wal_path, 'rb') as f:
        data = f.read()

    transactions = {}
    offset = 32  # skip WAL header

    while offset + 4 <= len(data):
        frame_len = struct.unpack_from('>I', data, offset)[0]
        if offset + 4 + frame_len > len(data):
            break  # truncated

        payload = data[offset + 4:offset + 4 + frame_len]
        body = payload[:-4]

        ft, txn_id = struct.unpack_from('>BI', body, 0)

        if txn_id not in transactions:
            transactions[txn_id] = {
                'status': 'in_progress', 'writes': []}

        if ft == FT_BEGIN:
            pass  # marks transaction start
        elif ft == FT_COMMIT:
            transactions[txn_id]['status'] = 'committed'
        elif ft == FT_ABORT:
            transactions[txn_id]['status'] = 'aborted'
        elif ft == FT_PAGE_WRITE and len(body) > 9:
            pg_num = struct.unpack_from('>I', body, 5)[0]
            pg_data = body[9:9 + PAGE_SIZE]
            transactions[txn_id]['writes'].append(
                (pg_num, bytes(pg_data)))

        offset += 4 + frame_len

    return transactions


def recover(backup_path, wal_path, output_path):
    """Perform crash recovery.

    Algorithm:
        1. Load base state from SQLite backup
        2. Parse and classify WAL transactions
        3. Replay committed writes in transaction ID order
        4. Write recovered database with updated checksum
    """
    pages = load_base_state(backup_path)
    txns = classify_wal_transactions(wal_path)

    # Apply committed transactions in txn_id order
    for txn_id in sorted(txns.keys()):
        info = txns[txn_id]
        if info['status'] == 'committed':
            for page_num, page_data in info['writes']:
                if page_num < len(pages):
                    pages[page_num] = bytearray(page_data)

    # Write recovered database
    all_pages = b''.join(bytes(p) for p in pages)
    checksum = zlib.crc32(all_pages) & 0xFFFFFFFF
    header = struct.pack(
        '>6sHIII', b'SIMDB\x00', 1, PAGE_SIZE,
        len(pages), checksum)
    header += b'\x00' * (HEADER_SIZE - len(header))

    with open(output_path, 'wb') as f:
        f.write(header)
        f.write(all_pages)

    committed_count = sum(
        1 for t in txns.values() if t['status'] == 'committed')
    return len(pages), committed_count
