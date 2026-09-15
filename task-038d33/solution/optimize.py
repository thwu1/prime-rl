#!/usr/bin/env python3
"""

Parquet storage layout engineer: sorts data, writes with per-column v2 encodings,
ZSTD compression, controlled row groups, file-level metadata, and analysis report.
"""

import json
import os

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

BASELINE = '/app/data/baseline.parquet'
OPTIMIZED = '/app/output/optimized.parquet'
ANALYSIS = '/app/output/analysis.json'

os.makedirs('/app/output', exist_ok=True)

# ── 1. Read baseline and sort by event_timestamp ──────────────────────────
table = pq.read_table(BASELINE)
table = table.sort_by('event_timestamp')
print(f"Read {table.num_rows:,} rows, sorted by event_timestamp")

# ── 2. Define per-column encoding map ─────────────────────────────────────
encoding_map = {
    'record_id': 'DELTA_BINARY_PACKED',
    'event_timestamp': 'DELTA_BINARY_PACKED',
    'reading': 'BYTE_STREAM_SPLIT',
    'latitude': 'BYTE_STREAM_SPLIT',
    'longitude': 'BYTE_STREAM_SPLIT',
    'device_id': 'RLE_DICTIONARY',
    'sensor_type': 'RLE_DICTIONARY',
    'quality': 'RLE_DICTIONARY',
    'is_valid': 'PLAIN',
    'metadata_json': 'PLAIN',
}

# ── 3. Embed optimization_config in Parquet schema metadata ───────────────
config_json = json.dumps(encoding_map)
existing_meta = table.schema.metadata or {}
merged_meta = {**existing_meta, b'optimization_config': config_json.encode('utf-8')}
table = table.replace_schema_metadata(merged_meta)

# ── 4. Write optimized file with per-column encoding control ──────────────
# column_encoding: explicit non-dictionary encodings
column_encoding = {
    'record_id': 'DELTA_BINARY_PACKED',
    'event_timestamp': 'DELTA_BINARY_PACKED',
    'reading': 'BYTE_STREAM_SPLIT',
    'latitude': 'BYTE_STREAM_SPLIT',
    'longitude': 'BYTE_STREAM_SPLIT',
}

# use_dictionary: list of columns that should use dictionary/RLE_DICTIONARY
use_dictionary = ['device_id', 'sensor_type', 'quality']

writer = pq.ParquetWriter(
    OPTIMIZED,
    table.schema,
    compression='zstd',
    use_dictionary=use_dictionary,
    column_encoding=column_encoding,
    write_statistics=True,
    data_page_version='2.0',
)

chunk_size = 250_000
for i in range(4):
    chunk = table.slice(i * chunk_size, chunk_size)
    writer.write_table(chunk)
    print(f"  Wrote row group {i}: rows {i * chunk_size:,}–{(i + 1) * chunk_size - 1:,}")

writer.close()

# ── 5. Generate analysis report ───────────────────────────────────────────
baseline_size = os.path.getsize(BASELINE)
optimized_size = os.path.getsize(OPTIMIZED)

pf = pq.ParquetFile(OPTIMIZED)
meta = pf.metadata

# Row group boundaries from actual Parquet metadata
row_group_boundaries = []
for i in range(meta.num_row_groups):
    rg = meta.row_group(i)
    rid_stats = ts_stats = None
    for j in range(rg.num_columns):
        col = rg.column(j)
        if col.path_in_schema == 'record_id':
            rid_stats = col.statistics
        elif col.path_in_schema == 'event_timestamp':
            ts_stats = col.statistics

    row_group_boundaries.append({
        'row_group_index': i,
        'num_rows': rg.num_rows,
        'min_record_id': int(rid_stats.min) if rid_stats else None,
        'max_record_id': int(rid_stats.max) if rid_stats else None,
        'min_timestamp': str(ts_stats.min) if ts_stats else None,
        'max_timestamp': str(ts_stats.max) if ts_stats else None,
    })

# Per-column analysis using DuckDB for cardinality queries
con = duckdb.connect()

rationale_map = {
    'record_id': 'Sequential integers with constant delta of 1 compress optimally with DELTA_BINARY_PACKED encoding',
    'event_timestamp': 'Monotonically increasing timestamps stored as int64 have constant deltas, ideal for DELTA_BINARY_PACKED',
    'device_id': 'Low cardinality (200 values) string column efficiently stored with RLE_DICTIONARY encoding',
    'sensor_type': 'Very low cardinality (8 values) yields excellent compression with RLE_DICTIONARY encoding',
    'reading': 'Slowly drifting doubles with small noise — BYTE_STREAM_SPLIT separates exponent/mantissa bytes for better ZSTD compression',
    'latitude': 'Doubles in narrow range [40,41] share high-order bytes — BYTE_STREAM_SPLIT exploits this byte-level structure',
    'longitude': 'Doubles in narrow range [-74.5,-73.5] share high-order bytes — BYTE_STREAM_SPLIT groups similar bytes together',
    'quality': 'Concentrated in 95-99 with few outliers — dictionary captures the small value set efficiently',
    'is_valid': 'Boolean column with 98% true values — plain encoding with bit-packing is compact, ZSTD handles the skew',
    'metadata_json': 'High cardinality structured strings — plain encoding lets ZSTD exploit the repetitive JSON key structure',
}

columns_info = {}
for j in range(meta.row_group(0).num_columns):
    col = meta.row_group(0).column(j)
    col_name = col.path_in_schema

    card = con.execute(
        f'SELECT count(DISTINCT "{col_name}") FROM read_parquet(?)',
        [BASELINE]
    ).fetchone()[0]

    columns_info[col_name] = {
        'physical_type': str(col.physical_type),
        'encoding': encoding_map[col_name],
        'cardinality': card,
        'rationale': rationale_map[col_name],
    }

analysis = {
    'baseline_size_bytes': baseline_size,
    'optimized_size_bytes': optimized_size,
    'compression_ratio': round(optimized_size / baseline_size, 6),
    'num_row_groups': meta.num_row_groups,
    'compression_codec': 'ZSTD',
    'row_group_boundaries': row_group_boundaries,
    'columns': columns_info,
}

with open(ANALYSIS, 'w') as f:
    json.dump(analysis, f, indent=2, default=str)

print(f"\nBaseline:  {baseline_size:>12,} bytes")
print(f"Optimized: {optimized_size:>12,} bytes")
print(f"Ratio:     {optimized_size / baseline_size:>12.4f} "
      f"({optimized_size / baseline_size * 100:.1f}%)")
print(f"Analysis written to {ANALYSIS}")

con.close()
