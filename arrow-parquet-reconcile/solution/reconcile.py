#!/usr/bin/env python3
"""Reconcile heterogeneous Parquet warehouse into unified format."""

import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.compute as pc
import json
import os
import glob

CONFIG_PATH = '/app/config.json'
WAREHOUSE_PATH = '/app/warehouse'

with open(CONFIG_PATH) as f:
    config = json.load(f)

TARGET_COLUMNS = list(config['target_schema'].keys())
RENAMES = config['column_renames']


def get_target_arrow_type(col_name):
    """Parse the target schema spec into a pyarrow type."""
    spec = config['target_schema'][col_name]
    t = spec['type']
    if t == 'int64':
        return pa.int64()
    elif t == 'float64':
        return pa.float64()
    elif t == 'string':
        return pa.string()
    elif t == 'bool':
        return pa.bool_()
    elif t == 'timestamp[us, tz=UTC]':
        return pa.timestamp('us', tz='UTC')
    else:
        raise ValueError(f"Unknown target type: {t}")


TARGET_TYPES = {col: get_target_arrow_type(col) for col in TARGET_COLUMNS}


def process_file(filepath):
    """Read a Parquet file and reconcile it to the target schema."""
    table = pq.read_table(filepath)
    n_rows = len(table)
    filename = os.path.basename(filepath)

    # Step 1: Extract columns into a mutable dict
    cols = {name: table.column(name) for name in table.column_names}

    # Step 2: Apply column renames
    renamed = {}
    for old_name, col_data in cols.items():
        new_name = RENAMES.get(old_name, old_name)
        renamed[new_name] = col_data
    cols = renamed

    # Step 3: Transform amount_cents -> amount (divide by 100)
    if 'amount_cents' in cols:
        cents = cols.pop('amount_cents')
        cents_float = pc.cast(cents, pa.float64())
        cols['amount'] = pc.divide(cents_float, pa.scalar(100.0, type=pa.float64()))

    # Step 4: Convert is_fraud from various source types to bool
    if 'is_fraud' in cols:
        fraud_col = cols['is_fraud']
        col_type = fraud_col.type

        if pa.types.is_string(col_type) or pa.types.is_large_string(col_type):
            # String "Y"/"N" -> True/False
            cols['is_fraud'] = pc.equal(fraud_col, 'Y')
        elif pa.types.is_integer(col_type):
            # int8 0/nonzero -> False/True
            cols['is_fraud'] = pc.not_equal(fraud_col, pa.scalar(0, type=col_type))
        # bool type needs no conversion

    # Step 5: Build output columns in target schema order
    result_arrays = []
    for col_name in TARGET_COLUMNS:
        target_type = TARGET_TYPES[col_name]

        if col_name not in cols:
            # Column absent from this file -> fill with typed nulls
            result_arrays.append(pa.nulls(n_rows, type=target_type))
            continue

        c = cols[col_name]

        # Type-specific coercions
        if col_name == 'txn_id':
            if pa.types.is_string(c.type) or pa.types.is_large_string(c.type):
                c = pc.cast(c, pa.int64())
            elif c.type != pa.int64():
                c = pc.cast(c, pa.int64())

        elif col_name == 'ts':
            # Normalize timestamps to microsecond UTC
            if c.type.tz is None:
                # Timezone-naive: assume UTC
                c = pc.assume_timezone(c, timezone='UTC')
            if c.type != pa.timestamp('us', tz='UTC'):
                c = pc.cast(c, pa.timestamp('us', tz='UTC'))

        elif col_name == 'amount':
            if pa.types.is_decimal(c.type):
                c = pc.cast(c, pa.float64())
            elif c.type != pa.float64():
                c = pc.cast(c, pa.float64())

        elif col_name == 'merchant':
            # dictionary_decode is not available on ChunkedArray; use pc.cast
            if pa.types.is_dictionary(c.type):
                c = pc.cast(c, pa.string())
            if pa.types.is_large_string(c.type):
                c = pc.cast(c, pa.string())

        elif col_name == 'category':
            # dictionary_decode is not available on ChunkedArray; use pc.cast
            if pa.types.is_dictionary(c.type):
                c = pc.cast(c, pa.string())
            if pa.types.is_large_string(c.type):
                c = pc.cast(c, pa.string())

        elif col_name == 'risk_score':
            if c.type != pa.float64():
                c = pc.cast(c, pa.float64())

        # is_fraud already converted above; region is already string

        result_arrays.append(c)

    return pa.table(result_arrays, names=TARGET_COLUMNS)


# Discover and process all Parquet files
parquet_files = sorted(glob.glob(os.path.join(WAREHOUSE_PATH, '*.parquet')))
if not parquet_files:
    raise RuntimeError(f"No Parquet files found in {WAREHOUSE_PATH}")

tables = []
file_info = []

for fpath in parquet_files:
    print(f"Processing {os.path.basename(fpath)}...")
    orig_schema = pq.read_schema(fpath)
    t = process_file(fpath)
    tables.append(t)
    file_info.append({
        'file': os.path.basename(fpath),
        'rows': len(t),
        'original_columns': orig_schema.names,
    })
    print(f"  -> {len(t)} rows, columns: {orig_schema.names}")

# Concatenate all reconciled tables
unified = pa.concat_tables(tables)
print(f"\nUnified table: {len(unified)} rows, schema:\n{unified.schema}")

# Write output
output_dir = os.path.dirname(config['output']['path'])
os.makedirs(output_dir, exist_ok=True)

output_path = config['output']['path']
pq.write_table(
    unified,
    output_path,
    version=config['output']['format_version'],
    compression=config['output']['compression'],
    use_dictionary=config['output']['dictionary_columns'],
)
print(f"\nWrote reconciled Parquet to {output_path}")

# Generate report
null_counts = {}
for col_name in TARGET_COLUMNS:
    null_counts[col_name] = unified.column(col_name).null_count

report = {
    'total_rows': len(unified),
    'files_processed': len(parquet_files),
    'files': file_info,
    'null_counts': null_counts,
    'output_schema': str(unified.schema),
}

report_path = config['output']['report_path']
with open(report_path, 'w') as rf:
    json.dump(report, rf, indent=2)
print(f"Wrote report to {report_path}")
