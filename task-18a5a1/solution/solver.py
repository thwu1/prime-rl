#!/usr/bin/env python3
"""Forensic column-store recovery: diagnose, repair, and query.

Strategy:
1. Parse crash_report.txt for partial/unreliable diagnostic hints.
2. Parse schema.sql for expected column counts and value ranges.
3. Use r0 as a known-good binary format reference.
4. Diagnose each corruption by analyzing actual binary data against expectations.
5. Repair binary files in-place — verify crash report claims against data.
6. Handle r3 entirely from data analysis (crash report has no metadata).
7. Load repaired data into DuckDB and execute analytical queries.
"""

import struct
import os
import re
import sys

DATA_DIR = '/app/data'


# ---------------------------------------------------------------------------
# Binary file helpers
# ---------------------------------------------------------------------------

def read_header(path):
    """Read the 16-byte header: (tuple_count, column_count)."""
    with open(path, 'rb') as f:
        return struct.unpack('<QQ', f.read(16))


def read_columns(path):
    """Read all columns using the file header."""
    with open(path, 'rb') as f:
        nt, nc = struct.unpack('<QQ', f.read(16))
        cols = []
        for _ in range(nc):
            cols.append(list(struct.unpack(f'<{nt}Q', f.read(8 * nt))))
    return nt, nc, cols


def write_binary(path, nt, nc, cols):
    """Write a binary column-store relation file."""
    with open(path, 'wb') as f:
        f.write(struct.pack('<QQ', nt, nc))
        for col in cols:
            for v in col:
                f.write(struct.pack('<Q', v))


# ---------------------------------------------------------------------------
# Step 1: Parse supporting files for diagnostic clues
# ---------------------------------------------------------------------------

# Parse schema.sql — extract column counts and CHECK constraint ranges
schema_info = {}
schema_path = '/app/schema.sql'
if os.path.exists(schema_path):
    with open(schema_path) as f:
        content = f.read()
    for match in re.finditer(
        r'CREATE TABLE (\w+)\s*\((.*?)\);', content, re.DOTALL
    ):
        tname = match.group(1)
        body = match.group(2)
        col_names = re.findall(r'(c\d+)\s+BIGINT', body)
        checks = re.findall(
            r'(c\d+)\s+BIGINT\s+CHECK\s*\(\1\s+BETWEEN\s+(\d+)\s+AND\s+(\d+)\)',
            body
        )
        schema_info[tname] = {
            'num_cols': len(col_names),
            'ranges': {col: (int(lo), int(hi)) for col, lo, hi in checks}
        }

print(f"Schema info: { {k: v['num_cols'] for k, v in schema_info.items()} }")

# Parse crash report for hints (but don't trust blindly)
crash_hints = {}
crash_path = '/app/crash_report.txt'
if os.path.exists(crash_path):
    with open(crash_path) as f:
        crash_content = f.read()
    print("Crash report loaded — treating as advisory only")


# ---------------------------------------------------------------------------
# Step 2: Diagnose and repair each relation
# ---------------------------------------------------------------------------

# --- r1: column count mismatch (file has more data than header says) ---
path_r1 = os.path.join(DATA_DIR, 'r1')
nt1, nc1 = read_header(path_r1)
fsize1 = os.path.getsize(path_r1)
data_bytes1 = fsize1 - 16
schema_nc1 = schema_info.get('r1', {}).get('num_cols', nc1)

# Check if actual file data fits a different column count
true_nc1 = data_bytes1 // (nt1 * 8)
if true_nc1 != nc1 and true_nc1 * nt1 * 8 == data_bytes1:
    print(f"r1: header says {nc1} cols but file data fits {true_nc1} cols. "
          f"Schema expects {schema_nc1}. Fixing header.")
    with open(path_r1, 'r+b') as f:
        f.seek(8)
        f.write(struct.pack('<Q', true_nc1))

# --- r2: byte-order corruption — verify against data, not crash report ---
path_r2 = os.path.join(DATA_DIR, 'r2')
nt2, nc2 = read_header(path_r2)
r2_ranges = schema_info.get('r2', {}).get('ranges', {})

# Read the entire file for byte-level access
with open(path_r2, 'rb') as f:
    raw_r2 = bytearray(f.read())

# Parse all columns as little-endian first
r2_cols = []
for c in range(nc2):
    offset = 16 + c * nt2 * 8
    chunk = bytes(raw_r2[offset:offset + nt2 * 8])
    r2_cols.append(list(struct.unpack(f'<{nt2}Q', chunk)))

# Check each constrained column — find values violating range constraints
# Don't trust crash report direction — check actual data
r2_modified = False
for c in range(nc2):
    col_name = f'c{c}'
    if col_name in r2_ranges:
        _, exp_max = r2_ranges[col_name]
        bad_indices = [i for i, v in enumerate(r2_cols[c]) if v > exp_max]
        if bad_indices:
            print(f"r2.{col_name}: {len(bad_indices)} values exceed max {exp_max}. "
                  f"Attempting byte-swap repair.")
            col_offset = 16 + c * nt2 * 8
            for i in bad_indices:
                # The value was stored in wrong byte order — swap it
                val_bytes = raw_r2[col_offset + i * 8: col_offset + (i + 1) * 8]
                correct_val = struct.unpack('>Q', bytes(val_bytes))[0]
                if correct_val <= exp_max:
                    r2_cols[c][i] = correct_val
                else:
                    print(f"  WARNING: byte-swapped value {correct_val} still "
                          f"exceeds {exp_max} for row {i}")
            r2_modified = True

if r2_modified:
    write_binary(path_r2, nt2, nc2, r2_cols)

# --- r3: NO crash metadata — must diagnose entirely from data ---
path_r3 = os.path.join(DATA_DIR, 'r3')
nt3, nc3, r3_cols = read_columns(path_r3)
r3_ranges = schema_info.get('r3', {}).get('ranges', {})

print(f"r3: analyzing {nc3} columns of {nt3} tuples (no crash metadata)")

# Step A: Detect column permutation via range constraint violations
# For each constrained column, check if its data is in the right position
misplaced = {}
for c in range(nc3):
    col_name = f'c{c}'
    if col_name in r3_ranges:
        _, exp_max = r3_ranges[col_name]
        actual_max = max(r3_cols[c])
        if actual_max > exp_max:
            # This position has data from another column — find which one
            for c2 in range(nc3):
                if c2 != c and c2 not in misplaced.values():
                    c2_name = f'c{c2}'
                    if c2_name in r3_ranges:
                        _, c2_max = r3_ranges[c2_name]
                        if actual_max <= c2_max:
                            misplaced[c] = c2
                            print(f"  Column at position {c}: max={actual_max}, "
                                  f"expected <= {exp_max} for c{c}. "
                                  f"Matches c{c2} range (<= {c2_max}).")
                            break
                    else:
                        # No constraint for c2 — check if current data fits c2
                        # and c2's data fits position c
                        if max(r3_cols[c2]) <= exp_max:
                            misplaced[c] = c2
                            print(f"  Column at position {c}: max={actual_max}. "
                                  f"Position {c2} has max={max(r3_cols[c2])} "
                                  f"which fits c{c}'s constraint (<= {exp_max}).")
                            break

# Apply column swaps
r3_modified = False
processed = set()
for a, b in sorted(misplaced.items()):
    if a not in processed and b not in processed:
        print(f"  Swapping columns at positions {a} and {b}")
        r3_cols[a], r3_cols[b] = r3_cols[b], r3_cols[a]
        processed.update([a, b])
        r3_modified = True

# Step B: Detect delta-encoded columns
# Delta encoding signature: many values near 0 or near 2^64 (negative deltas as uint64)
# Normal data would be in a bounded range; delta-encoded data has bimodal distribution
UINT64_MID = 2 ** 63

for c in range(nc3):
    col = r3_cols[c]
    col_max = max(col)

    # Check if this column has the delta encoding signature:
    # - Many values > 2^63 (negative deltas stored as unsigned)
    # - Remaining values are small (positive deltas)
    large_count = sum(1 for v in col if v > UINT64_MID)
    if large_count > len(col) * 0.1 and col_max > UINT64_MID:
        # Looks like delta encoding — try decoding
        decoded = [col[0]]
        for i in range(1, len(col)):
            decoded.append((decoded[-1] + col[i]) & 0xFFFFFFFFFFFFFFFF)

        # Verify: decoded values should be in a reasonable range
        dec_max = max(decoded)
        dec_min = min(decoded)
        if dec_max < 100000 and dec_min >= 0:
            print(f"  Column {c}: detected delta encoding "
                  f"({large_count}/{len(col)} values > 2^63). "
                  f"Decoded range: [{dec_min}, {dec_max}]")
            r3_cols[c] = decoded
            r3_modified = True
        else:
            print(f"  Column {c}: delta decode produced out-of-range values "
                  f"[{dec_min}, {dec_max}] — skipping")

if r3_modified:
    write_binary(path_r3, nt3, nc3, r3_cols)

# --- r4: tuple count mismatch (file has more rows than header says) ---
path_r4 = os.path.join(DATA_DIR, 'r4')
nt4, nc4 = read_header(path_r4)
fsize4 = os.path.getsize(path_r4)
data_bytes4 = fsize4 - 16
true_nt4 = data_bytes4 // (nc4 * 8)
if true_nt4 != nt4 and true_nt4 * nc4 * 8 == data_bytes4:
    print(f"r4: header says {nt4} tuples but file fits {true_nt4}. Fixing.")
    with open(path_r4, 'r+b') as f:
        f.write(struct.pack('<Q', true_nt4))

print("All repairs complete.")


# ---------------------------------------------------------------------------
# Step 3: Load repaired data into DuckDB and execute queries
# ---------------------------------------------------------------------------

import duckdb

conn = duckdb.connect()

for name in ['r0', 'r1', 'r2', 'r3', 'r4']:
    path = os.path.join(DATA_DIR, name)
    nt, nc, cols = read_columns(path)
    col_defs = ", ".join(f"c{i} UBIGINT" for i in range(nc))
    conn.execute(f"CREATE TABLE {name} ({col_defs})")
    if nt > 0:
        batch_size = 100
        for start in range(0, nt, batch_size):
            end = min(start + batch_size, nt)
            rows = []
            for row_idx in range(start, end):
                vals = ", ".join(str(cols[c][row_idx]) for c in range(nc))
                rows.append(f"({vals})")
            conn.execute(f"INSERT INTO {name} VALUES {', '.join(rows)}")

# Read queries from queries.sql
queries = []
with open('/app/queries.sql') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('--'):
            queries.append(line.rstrip(';'))

# Execute and format results
results = []
for q in queries:
    row = conn.execute(q).fetchone()
    if row is None or all(v is None for v in row):
        results.append("NULL")
    else:
        results.append(
            " ".join("NULL" if v is None else str(v) for v in row)
        )

conn.close()

# Write output
with open('/app/output.txt', 'w') as f:
    for r in results:
        f.write(r + '\n')

print(f"Wrote {len(results)} query results to /app/output.txt")
