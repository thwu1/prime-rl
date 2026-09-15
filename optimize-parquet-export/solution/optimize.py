
"""
Parquet Storage Layout Optimization Solution

Key design decisions per table:

1. sequential_data — Sort by (ts, category) with ROW_GROUP_SIZE 70000.
   - ts-primary sort creates contiguous time ranges per row group, enabling
     zone map filtering on ts (each row group covers ~19 hours).
   - This CONTRADICTS sorting by category (which would create better RLE on
     category but destroy time-range zone maps).
   - With v2 DELTA_BINARY_PACKED, the sequential id and ts columns compress
     to near-zero regardless of sort order.
   - ROW_GROUP_SIZE 70000 yields ~28 row groups (within the 20-40 requirement).

2. wide_integers — Sort by (score, group_code, sub_code, record_id).
   - score-first sort creates contiguous score ranges per row group, enabling
     zone map filtering on score (each row group covers ~625 values out of
     0-10000, so a 1000-value range query overlaps ~2-3 row groups).
   - This CONTRADICTS sorting by group_code (compression-optimal for creating
     value runs) but the 45 MB target is generous enough to accommodate.
   - v2 DELTA_BINARY_PACKED handles all integer columns efficiently regardless.

3. text_logs — Sort by (severity, service, log_id).
   - severity-first sort concentrates the rare CRITICAL severity (~2%, ~10K rows)
     into the first row group, enabling zone map selectivity.
   - This also creates good RLE runs on severity and dictionary efficiency on
     service within severity groups.

4. sensor_metrics — Sort by (measured_at, sensor_id) with ROW_GROUP_SIZE 50000.
   - measured_at-first sort creates contiguous time ranges per row group,
     enabling zone map filtering on measured_at.
   - This CONTRADICTS sorting by sensor_id (which groups each sensor's smooth
     float readings together for better BYTE_STREAM_SPLIT compression).
   - ROW_GROUP_SIZE 50000 yields 40 row groups (within 25-70), each covering
     ~14 hours, so a 3-day filter overlaps ~6 row groups.
"""

import duckdb
import os

os.makedirs("/app/output", exist_ok=True)

con = duckdb.connect("/app/warehouse.duckdb", read_only=True)

# sequential_data: Sort by ts for zone map filtering.
# ROW_GROUP_SIZE 70000 -> ~28 row groups, each covering ~19 hours.
# A 2-day filter overlaps ~3 row groups.
print("Exporting sequential_data...")
con.execute("""
    COPY (
        SELECT * FROM sequential_data
        ORDER BY ts, category
    ) TO '/app/output/sequential_data.parquet'
    (FORMAT PARQUET, COMPRESSION zstd, PARQUET_VERSION v2, ROW_GROUP_SIZE 70000)
""")

# wide_integers: Sort by score first for zone map filtering on score ranges.
# Secondary sort by group_code, sub_code for residual compression benefit.
print("Exporting wide_integers...")
con.execute("""
    COPY (
        SELECT * FROM wide_integers
        ORDER BY score, group_code, sub_code, record_id
    ) TO '/app/output/wide_integers.parquet'
    (FORMAT PARQUET, COMPRESSION zstd, PARQUET_VERSION v2)
""")

# text_logs: Sort by severity first to concentrate rare CRITICAL rows.
# Secondary sort by service for dictionary/RLE efficiency.
print("Exporting text_logs...")
con.execute("""
    COPY (
        SELECT * FROM text_logs
        ORDER BY severity, service, log_id
    ) TO '/app/output/text_logs.parquet'
    (FORMAT PARQUET, COMPRESSION zstd, PARQUET_VERSION v2)
""")

# sensor_metrics: Sort by measured_at for time-range zone maps.
# Secondary sort by sensor_id for local float smoothness within time slices.
# ROW_GROUP_SIZE 50000 -> 40 row groups, each covering ~14 hours.
print("Exporting sensor_metrics...")
con.execute("""
    COPY (
        SELECT * FROM sensor_metrics
        ORDER BY measured_at, sensor_id
    ) TO '/app/output/sensor_metrics.parquet'
    (FORMAT PARQUET, COMPRESSION zstd, PARQUET_VERSION v2, ROW_GROUP_SIZE 50000)
""")

con.close()

# Report file sizes
print("\nExport complete. File sizes:")
for name in ["sequential_data", "wide_integers", "text_logs", "sensor_metrics"]:
    path = f"/app/output/{name}.parquet"
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"  {name}.parquet: {size_mb:.2f} MB")

# Report row group counts
print("\nRow group counts:")
con2 = duckdb.connect("/app/warehouse.duckdb", read_only=True)
for name in ["sequential_data", "wide_integers", "text_logs", "sensor_metrics"]:
    rg_count = con2.execute(f"""
        SELECT COUNT(DISTINCT row_group_id)
        FROM parquet_metadata('/app/output/{name}.parquet')
    """).fetchone()[0]
    print(f"  {name}.parquet: {rg_count} row groups")
con2.close()
