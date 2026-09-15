#!/usr/bin/env python3
"""Generate corrupted column-store database for forensic recovery task.

Creates five binary relation files with distinct corruptions,
plus a crash report, schema, and analytical queries.
"""
import struct
import random
import os

random.seed(42)

DATA_DIR = '/app/data'
os.makedirs(DATA_DIR, exist_ok=True)


def gen_col(n, lo, hi):
    """Generate a column of n random integers in [lo, hi]."""
    return [random.randint(lo, hi) for _ in range(n)]


def delta_encode(col):
    """Delta encode: first value unchanged, rest are signed diffs stored as uint64."""
    encoded = [col[0]]
    for i in range(1, len(col)):
        diff = col[i] - col[i - 1]
        encoded.append(diff & 0xFFFFFFFFFFFFFFFF)
    return encoded


# ---------------------------------------------------------------------------
# Generate correct relation data (order of random calls MUST match test)
# ---------------------------------------------------------------------------

# r0: 400 tuples, 3 columns — written CORRECTLY as format reference
r0 = [gen_col(400, 0, 9999), gen_col(400, 0, 99), gen_col(400, 0, 9999)]

# r1: 250 tuples, 4 columns — header will lie about column count
r1 = [gen_col(250, 0, 4999), gen_col(250, 0, 49), gen_col(250, 0, 99),
      gen_col(250, 0, 9999)]

# r2: 300 tuples, 3 columns — c2 partially stored big-endian
r2 = [gen_col(300, 0, 5999), gen_col(300, 0, 49), gen_col(300, 0, 4999)]

# r3: 500 tuples, 5 columns — c1/c3 swapped AND c4 delta-encoded
r3 = [gen_col(500, 0, 99), gen_col(500, 0, 9), gen_col(500, 0, 49),
      gen_col(500, 0, 199), gen_col(500, 0, 9999)]

# r4: 180 tuples, 2 columns — header under-reports tuple count
r4 = [gen_col(180, 0, 99), gen_col(180, 0, 49)]


# ---------------------------------------------------------------------------
# Write binary relation files WITH corruptions
# ---------------------------------------------------------------------------

def write_correct(path, nt, cols):
    """Write a correct binary column-store file."""
    with open(path, 'wb') as f:
        f.write(struct.pack('<QQ', nt, len(cols)))
        for col in cols:
            for v in col:
                f.write(struct.pack('<Q', v))


# r0: CORRECT — serves as reference for the binary format
write_correct(os.path.join(DATA_DIR, 'r0'), 400, r0)

# r1: header says 3 columns but 4 columns of data are present
with open(os.path.join(DATA_DIR, 'r1'), 'wb') as f:
    f.write(struct.pack('<QQ', 250, 3))       # corrupt: 3 instead of 4
    for col in r1:
        for v in col:
            f.write(struct.pack('<Q', v))

# r2: c2 partially converted to big-endian (first 200 of 300 rows)
CONVERT_BOUNDARY = 200
with open(os.path.join(DATA_DIR, 'r2'), 'wb') as f:
    f.write(struct.pack('<QQ', 300, 3))
    for c_idx, col in enumerate(r2):
        for row_idx, v in enumerate(col):
            if c_idx == 2 and row_idx < CONVERT_BOUNDARY:
                f.write(struct.pack('>Q', v))  # big-endian
            else:
                f.write(struct.pack('<Q', v))  # little-endian

# r3: columns c1 and c3 physically swapped + c4 delta-encoded
#     physical order: [c0, c3, c2, c1, c4_delta]
r3_c4_delta = delta_encode(r3[4])
with open(os.path.join(DATA_DIR, 'r3'), 'wb') as f:
    f.write(struct.pack('<QQ', 500, 5))
    write_order = [0, 3, 2, 1, 4]
    for c_idx in write_order:
        col_data = r3_c4_delta if c_idx == 4 else r3[c_idx]
        for v in col_data:
            f.write(struct.pack('<Q', v))

# r4: header says 170 tuples but 180 rows of data exist
with open(os.path.join(DATA_DIR, 'r4'), 'wb') as f:
    f.write(struct.pack('<QQ', 170, 2))        # corrupt: 170 instead of 180
    for col in r4:
        for v in col:
            f.write(struct.pack('<Q', v))


# ---------------------------------------------------------------------------
# Write crash report (replaces explicit migration log)
# ---------------------------------------------------------------------------

CRASH_REPORT = """\
=== Schema Migrator v2.3.1 — Crash Report ===
PID: 28401 | Signal: SIGSEGV | Time: 2024-11-15T03:14:25.091Z
Binary: /opt/migrator/bin/schema_migrator (build 4a7e2f1)

--- Stack Trace ---
  #0  0x7f3e2a1b4320  column_writer::flush_page()+0x120
  #1  0x7f3e2a1b3890  transform_engine::apply_batch()+0x90
  #2  0x7f3e2a1b2100  main()+0x48

--- Binary Format ---
  Layout: column-major, unsigned 64-bit integers, little-endian
  Header: [uint64 tuple_count] [uint64 column_count]
  Data: columns stored sequentially after header

--- Transform Queue ---
  T-001  r0  noop                                     [COMPLETE]
  T-002  r1  schema_extend(target_ncols=4)             [INTERRUPTED]
  T-003  r2  endian_normalize(col=c2, be->le)          [INTERRUPTED @row 200]
  T-004  r3  layout_optimize                           [ABORTED: EFAULT]
  T-005  r4  tuple_extend(target=180)                  [INTERRUPTED]

--- Partial State (captured post-crash — may be inconsistent) ---
  r0:  status=verified_intact
  r1:  column data written for 4 cols; header update pending (hdr_sync=false)
  r2:  endian_normalize processed 200 of 300 rows on col c2
  r3:  <<< EFAULT: transform metadata page unmapped >>>
       <<< state unrecoverable — no diagnostic data available >>>
  r4:  180 tuples of data present; header update pending (hdr_sync=false)

--- ADVISORY ---
  Transform states captured during crash may not reflect actual on-disk state.
  The endian_normalize direction flag has been unreliable in prior builds.
  Verify ALL repairs against schema constraints (/app/schema.sql).
  Use r0 as a known-good binary format reference.
"""

with open('/app/crash_report.txt', 'w') as f:
    f.write(CRASH_REPORT)


# ---------------------------------------------------------------------------
# Write target schema (post-migration)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """\
-- Target schema (post-migration)
-- Binary format: column-major, uint64 little-endian
-- Header: uint64 tuple_count, uint64 column_count

CREATE TABLE r0 (
    c0 BIGINT,
    c1 BIGINT CHECK (c1 BETWEEN 0 AND 99),
    c2 BIGINT
);

CREATE TABLE r1 (
    c0 BIGINT,
    c1 BIGINT CHECK (c1 BETWEEN 0 AND 49),
    c2 BIGINT CHECK (c2 BETWEEN 0 AND 99),
    c3 BIGINT
);

CREATE TABLE r2 (
    c0 BIGINT,
    c1 BIGINT CHECK (c1 BETWEEN 0 AND 49),
    c2 BIGINT CHECK (c2 BETWEEN 0 AND 4999)
);

CREATE TABLE r3 (
    c0 BIGINT CHECK (c0 BETWEEN 0 AND 99),
    c1 BIGINT CHECK (c1 BETWEEN 0 AND 9),
    c2 BIGINT,
    c3 BIGINT CHECK (c3 BETWEEN 0 AND 199),
    c4 BIGINT
);

CREATE TABLE r4 (
    c0 BIGINT CHECK (c0 BETWEEN 0 AND 99),
    c1 BIGINT CHECK (c1 BETWEEN 0 AND 49)
);
"""

with open('/app/schema.sql', 'w') as f:
    f.write(SCHEMA_SQL)


# ---------------------------------------------------------------------------
# Write analytical queries
# ---------------------------------------------------------------------------

QUERIES_SQL = """\
-- Analytical queries to execute after repair
SELECT SUM(c0), SUM(c2) FROM r0 WHERE c1 < 50;
SELECT SUM(r0.c0), SUM(r1.c3) FROM r0 JOIN r1 ON r0.c1 = r1.c2;
SELECT SUM(c0), SUM(c2) FROM r2 WHERE c1 < 25;
SELECT SUM(c1), SUM(c3) FROM r3 WHERE c0 < 50;
SELECT COUNT(*), SUM(c1) FROM r4;
SELECT SUM(r0.c2), SUM(r2.c2) FROM r0 JOIN r2 ON r0.c1 = r2.c1;
SELECT SUM(r3.c4), SUM(r4.c1) FROM r3 JOIN r4 ON r3.c0 = r4.c0;
SELECT SUM(r0.c0), SUM(r1.c3), SUM(r3.c4) FROM r0 JOIN r1 ON r0.c1 = r1.c2 JOIN r3 ON r1.c1 = r3.c2;
SELECT SUM(r0.c0) FROM r0 WHERE c2 > 999999;
SELECT SUM(c4), COUNT(*) FROM r3 WHERE c1 < 5 AND c3 > 100;
"""

with open('/app/queries.sql', 'w') as f:
    f.write(QUERIES_SQL)

print("Generated corrupted database with 5 relations and 10 queries")
