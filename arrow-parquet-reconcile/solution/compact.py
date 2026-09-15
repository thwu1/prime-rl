#!/usr/bin/env python3
"""Compact heterogeneous Parquet staging data into a deduplicated, partitioned dataset."""

import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc
import pyarrow.dataset as ds
import json
import os
import glob
from datetime import datetime, timezone

STAGING = '/app/staging'
OUTPUT_DIR = '/app/output/compacted'
QUARANTINE_PATH = '/app/output/quarantine.parquet'
MANIFEST_PATH = '/app/output/manifest.json'

# Target schema derived from data_contract.md
TARGET_SCHEMA = pa.schema([
    ('event_id', pa.int64()),
    ('timestamp', pa.timestamp('us', tz='UTC')),
    ('amount', pa.float64()),
    ('user_id', pa.int64()),
    ('category', pa.string()),
    ('status', pa.string()),
    ('region', pa.string()),
    ('channel', pa.string()),
    ('risk_score', pa.float64()),
])


def unify_table_to_target(table):
    """Convert a table with any source schema to the target schema.

    Handles: int32->int64, float32->float64, decimal128->float64,
    dictionary->plain string, timestamp precision/timezone normalization,
    and missing columns filled with typed nulls.
    """
    n = len(table)
    result = {}

    for field in TARGET_SCHEMA:
        col_name = field.name
        target_type = field.type

        if col_name not in table.column_names:
            # Column absent in this schema epoch -> fill with typed nulls
            result[col_name] = pa.nulls(n, type=target_type)
            continue

        col = table.column(col_name)

        if col_name == 'timestamp':
            # Handle timezone: assume UTC for naive timestamps
            if not hasattr(col.type, 'tz') or col.type.tz is None:
                col = pc.assume_timezone(col, timezone='UTC')
            # Normalize precision to microseconds
            if col.type != pa.timestamp('us', tz='UTC'):
                col = pc.cast(col, pa.timestamp('us', tz='UTC'))

        elif col_name == 'amount':
            # decimal128 or float32 -> float64
            if col.type != pa.float64():
                col = pc.cast(col, pa.float64())

        elif col_name in ('event_id', 'user_id'):
            # int32 -> int64
            if col.type != pa.int64():
                col = pc.cast(col, pa.int64())

        elif col_name == 'category':
            # dictionary<string> -> plain string
            if pa.types.is_dictionary(col.type):
                col = pc.cast(col, pa.string())

        result[col_name] = col

    return pa.table(result, schema=TARGET_SCHEMA)


# ---- Step 1: Read all staging files and unify schemas ----
files = sorted(glob.glob(os.path.join(STAGING, '*.parquet')))
total_input_rows = 0
file_tables = []

for fpath in files:
    table = pq.read_table(fpath)
    total_input_rows += len(table)
    print(f"Read {os.path.basename(fpath)}: {len(table)} rows, "
          f"schema: {[f'{f.name}:{f.type}' for f in table.schema]}")

    unified = unify_table_to_target(table)

    # Tag rows with source filename for dedup ordering
    fname_col = pa.array([os.path.basename(fpath)] * len(unified), type=pa.string())
    unified = unified.append_column('_source_file', fname_col)
    file_tables.append(unified)

print(f"\nTotal input rows: {total_input_rows}")

# ---- Step 2: Concatenate all unified tables ----
combined = pa.concat_tables(file_tables)

# ---- Step 3: Separate null event_id rows (cannot participate in dedup) ----
null_id_mask = pc.is_null(combined.column('event_id'))
null_id_rows = combined.filter(null_id_mask)
valid_rows = combined.filter(pc.invert(null_id_mask))
print(f"Null event_id rows quarantined: {len(null_id_rows)}")

# ---- Step 4: Deduplicate by event_id, keeping lexicographically latest filename ----
# Sort by event_id ASC, then _source_file DESC so latest file comes first
indices = pc.sort_indices(valid_rows, sort_keys=[
    ('event_id', 'ascending'),
    ('_source_file', 'descending'),
])
sorted_table = valid_rows.take(indices)

# Keep first occurrence of each event_id (which has the latest filename)
event_ids = sorted_table.column('event_id')
prev_id = None
keep_indices = []
for i in range(len(sorted_table)):
    eid = event_ids[i].as_py()
    if eid != prev_id:
        keep_indices.append(i)
        prev_id = eid

deduped = sorted_table.take(keep_indices)
duplicates_removed = len(valid_rows) - len(deduped)
print(f"Duplicates removed: {duplicates_removed}")

# Drop the source file tracking column
deduped = deduped.drop('_source_file')
null_id_rows = null_id_rows.drop('_source_file')

# ---- Step 5: Apply quarantine rules ----
quarantine_parts = []
quarantine_reasons = []

# 5a: Null event_id rows (already separated)
for _ in range(len(null_id_rows)):
    quarantine_reasons.append('null_event_id')
quarantine_parts.append(null_id_rows)

# 5b: Negative amounts
neg_mask = pc.less(deduped.column('amount'), 0)
neg_rows = deduped.filter(neg_mask)
for _ in range(len(neg_rows)):
    quarantine_reasons.append('negative_amount')
quarantine_parts.append(neg_rows)
deduped = deduped.filter(pc.invert(neg_mask))
print(f"Negative amount rows quarantined: {len(neg_rows)}")

# 5c: Future timestamps (after 2024-12-31T23:59:59 UTC)
cutoff = pa.scalar(
    datetime(2025, 1, 1, tzinfo=timezone.utc),
    type=pa.timestamp('us', tz='UTC'))
future_mask = pc.greater_equal(deduped.column('timestamp'), cutoff)
future_rows = deduped.filter(future_mask)
for _ in range(len(future_rows)):
    quarantine_reasons.append('future_timestamp')
quarantine_parts.append(future_rows)
deduped = deduped.filter(pc.invert(future_mask))
print(f"Future timestamp rows quarantined: {len(future_rows)}")

# Write quarantine file
quarantine_table = pa.concat_tables(quarantine_parts)
quarantine_table = quarantine_table.append_column(
    'quarantine_reason', pa.array(quarantine_reasons, type=pa.string()))
os.makedirs(os.path.dirname(QUARANTINE_PATH), exist_ok=True)
pq.write_table(quarantine_table, QUARANTINE_PATH, compression='zstd')
print(f"Wrote {len(quarantine_table)} quarantined rows to {QUARANTINE_PATH}")

# ---- Step 6: Derive year_month partition key and write partitioned output ----
year_month_col = pc.strftime(deduped.column('timestamp'), '%Y-%m')
deduped = deduped.append_column('year_month', year_month_col)

total_output_rows = len(deduped)
unique_ym = sorted(set(year_month_col.to_pylist()))
partition_stats = []

os.makedirs(OUTPUT_DIR, exist_ok=True)

for ym in unique_ym:
    mask = pc.equal(deduped.column('year_month'), ym)
    partition_data = deduped.filter(mask)
    # Remove partition column from data (encoded in directory name)
    partition_data = partition_data.drop('year_month')
    # Sort by timestamp within partition
    partition_data = partition_data.sort_by('timestamp')

    part_dir = os.path.join(OUTPUT_DIR, f'year_month={ym}')
    os.makedirs(part_dir, exist_ok=True)
    pq.write_table(
        partition_data,
        os.path.join(part_dir, 'data.parquet'),
        compression='zstd')

    partition_stats.append({
        'year_month': ym,
        'row_count': len(partition_data),
    })
    print(f"Partition {ym}: {len(partition_data)} rows")

# ---- Step 7: Write manifest ----
manifest = {
    'total_input_rows': total_input_rows,
    'total_output_rows': total_output_rows,
    'total_quarantined': len(quarantine_table),
    'duplicates_removed': duplicates_removed,
    'files_processed': len(files),
    'partitions': partition_stats,
}
with open(MANIFEST_PATH, 'w') as f:
    json.dump(manifest, f, indent=2)
print(f"\nWrote manifest to {MANIFEST_PATH}")
print(f"Summary: {total_input_rows} input -> {total_output_rows} output, "
      f"{len(quarantine_table)} quarantined, {duplicates_removed} duplicates removed")
