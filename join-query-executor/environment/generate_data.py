#!/usr/bin/env python3
"""Generate binary relation files, CSV backups, SQLite catalog, and query workload.

Corruption map (NOT visible to the agent):
  r0 — clean everywhere (baseline)
  r1 — csv: last 10 rows duplicated (310 total vs 300 true)
  r2 — bin: columns written in reverse order
  r3 — sqlite: truncated to first 370 of 400 rows
  r4 — bin: row-major layout; csv: columns 0 and 1 swapped (NO two agree)
  r5 — bin: columns 0 and 2 swapped
"""
import struct
import random
import os
import csv
import sqlite3

SEED = 42
random.seed(SEED)

# Output to /opt/taskdata so data survives if /app is mounted over
DATA_DIR = '/opt/taskdata/data'
os.makedirs(DATA_DIR, exist_ok=True)

# (num_rows, num_cols, value_lo, value_hi)
SPECS = [
    (200, 4, 1, 50),
    (300, 3, 1, 50),
    (150, 4, 1, 40),
    (400, 3, 1, 50),
    (250, 4, 1, 50),
    (180, 3, 1, 50),
]

# Generate ground-truth data
relations = []
for nrows, ncols, lo, hi in SPECS:
    cols = [[random.randint(lo, hi) for _ in range(nrows)] for _ in range(ncols)]
    relations.append((nrows, ncols, cols))

# ---- Write binary files (some corrupted) ----
for idx, (nrows, ncols, cols) in enumerate(relations):
    path = os.path.join(DATA_DIR, f'r{idx}.bin')
    with open(path, 'wb') as f:
        f.write(struct.pack('<Q', nrows))
        f.write(struct.pack('<Q', ncols))
        if idx == 2:
            # Reversed column order: c3 c2 c1 c0
            for c in range(ncols - 1, -1, -1):
                f.write(struct.pack(f'<{nrows}Q', *cols[c]))
        elif idx == 4:
            # Row-major layout instead of column-major
            for r in range(nrows):
                for c in range(ncols):
                    f.write(struct.pack('<Q', cols[c][r]))
        elif idx == 5:
            # Columns 0 and 2 swapped: writes c2 c1 c0
            col_order = [2, 1, 0]
            for c in col_order:
                f.write(struct.pack(f'<{nrows}Q', *cols[c]))
        else:
            for c in range(ncols):
                f.write(struct.pack(f'<{nrows}Q', *cols[c]))

# ---- Write CSV files (some corrupted) ----
for idx, (nrows, ncols, cols) in enumerate(relations):
    path = os.path.join(DATA_DIR, f'r{idx}.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow([f'c{c}' for c in range(ncols)])
        if idx == 1:
            # Duplicate last 10 rows (310 total)
            for r in range(nrows):
                w.writerow([cols[c][r] for c in range(ncols)])
            for r in range(nrows - 10, nrows):
                w.writerow([cols[c][r] for c in range(ncols)])
        elif idx == 4:
            # Columns 0 and 1 swapped
            for r in range(nrows):
                row = [cols[c][r] for c in range(ncols)]
                row[0], row[1] = row[1], row[0]
                w.writerow(row)
        else:
            for r in range(nrows):
                w.writerow([cols[c][r] for c in range(ncols)])

# ---- Write SQLite catalog ----
db_path = '/opt/taskdata/catalog.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
for idx, (nrows, ncols, cols) in enumerate(relations):
    col_defs = ', '.join(f'c{c} INTEGER' for c in range(ncols))
    cur.execute(f'CREATE TABLE r{idx} ({col_defs})')
    placeholders = ', '.join('?' * ncols)
    insert_count = 370 if idx == 3 else nrows
    for r in range(insert_count):
        row = [cols[c][r] for c in range(ncols)]
        cur.execute(f'INSERT INTO r{idx} VALUES ({placeholders})', row)
conn.commit()
conn.close()

# ---- Write query workload (25 queries) ----
QUERIES = [
    "0 1|0.0=1.0|0.2 1.2",
    "0 3|0.1=1.1|0.2 1.2",
    "1 3|0.0=1.0&1.2<30|0.2 1.2",
    "0 2|0.0=1.0|0.2 1.2",
    "0 4|0.0=1.0|0.2 1.2",
    "2 5|0.1=1.1|0.0 1.2",
    "3 5|0.0=1.0|0.2 1.2",
    "1 5|0.0=1.0|0.1 1.1",
    "0 1|0.0=1.0&0.2<25|0.3 1.2",
    "0 3|0.1=1.1&0.3<20|0.2 1.2",
    "0 1|0.0=1.0&0.2>30|0.3 1.1",
    "1 5|0.0=1.0&0.1<20|0.2 1.1",
    "0 0|0.0=1.0&1.2>30|0.3 1.3",
    "0 0|0.0=1.0&0.2>20|0.3 1.3",
    "0 0|0.0=1.0|0.2 1.3",
    "1 1|0.0=1.1&0.1>25|0.2 1.2",
    "3 3|0.0=1.0&0.1>25|0.1 1.1",
    "0 1|0.0=1.0&0.2>999|0.3 1.2",
    "0 3|0.1=1.1&0.3>999|0.2 1.2",
    "0 1 3|0.0=1.0&1.0=2.0|0.3 2.2",
    "0 1 2|0.0=1.0&1.0=2.0|0.3 2.3",
    "0 1 3|0.0=1.0&1.0=2.0&0.2<30|0.3 1.2 2.2",
    "0 3 4|0.0=1.0&1.0=2.0|0.3 2.3",
    "0 0 2|0.0=1.0&1.0=2.0&0.2>20|0.3 2.2",
    "0 3|0.0=1.0&0.2=25|0.1 1.2",
]

with open('/opt/taskdata/workload.txt', 'w') as f:
    for q in QUERIES:
        f.write(q + '\n')

print(f"Generated {len(relations)} relations, {len(QUERIES)} queries at /opt/taskdata/")
