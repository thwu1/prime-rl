#!/bin/bash

# Deploy the WAL forensics tool
cp /solution/wal_forensics_impl.py /app/wal_forensics.py

# Verify by parsing and reconstructing
python3 -c "
import sys, sqlite3
sys.path.insert(0, '/app')
from wal_forensics import (parse_wal_header, parse_frames,
                           identify_transactions, validate_checksums,
                           reconstruct_at_transaction)

h = parse_wal_header('/app/forensic.db-wal')
print(f'WAL magic: 0x{h[\"magic\"]:08x}, page_size: {h[\"page_size\"]}')
print(f'Header checksum valid: {h[\"header_checksum_valid\"]}')

frames = parse_frames('/app/forensic.db-wal')
print(f'Frames parsed: {len(frames)}')

txns = identify_transactions('/app/forensic.db-wal')
print(f'Transactions: {len(txns)}')

v = validate_checksums('/app/forensic.db-wal')
print(f'All checksums valid: {v[\"header_valid\"] and all(f[\"valid\"] for f in v[\"frames\"])}')

for i, txn in enumerate(txns):
    out = f'/tmp/solve_verify_txn{i}.db'
    reconstruct_at_transaction('/app/forensic.db', '/app/forensic.db-wal', i, out)
    conn = sqlite3.connect(out)
    count = conn.execute('SELECT COUNT(*) FROM sensors').fetchone()[0]
    conn.close()
    print(f'  txn {i}: {count} rows, pages modified: {txn[\"pages_modified\"]}')
"
