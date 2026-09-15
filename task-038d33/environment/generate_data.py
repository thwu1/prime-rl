#!/usr/bin/env python3

"""Generate IoT sensor dataset with specific data patterns for Parquet encoding optimization."""

import duckdb

con = duckdb.connect('/app/data/sensors.duckdb')
con.execute("PRAGMA threads=1")
con.execute("SELECT setseed(0.42)")

con.execute("""
CREATE TABLE readings AS
WITH base AS (
    SELECT
        i AS record_id,
        TIMESTAMP '2024-01-01 00:00:00' + INTERVAL (i) SECOND AS event_timestamp,
        'device_' || LPAD(CAST((i % 200) + 1 AS VARCHAR), 3, '0') AS device_id,
        CASE (i % 8)
            WHEN 0 THEN 'temperature'
            WHEN 1 THEN 'humidity'
            WHEN 2 THEN 'pressure'
            WHEN 3 THEN 'vibration'
            WHEN 4 THEN 'voltage'
            WHEN 5 THEN 'current'
            WHEN 6 THEN 'flow'
            WHEN 7 THEN 'level'
        END AS sensor_type,
        20.0 + CAST(i AS DOUBLE) * 0.00001 + random() * 0.001 AS reading,
        CASE
            WHEN random() < 0.9 THEN 95 + CAST(random() * 5 AS INTEGER)
            ELSE CAST(random() * 94 AS INTEGER)
        END AS quality,
        random() > 0.02 AS is_valid,
        40.0 + random() AS latitude,
        -74.5 + random() AS longitude
    FROM range(1000000) t(i)
)
SELECT
    record_id,
    event_timestamp,
    device_id,
    sensor_type,
    reading,
    quality,
    is_valid,
    latitude,
    longitude,
    '{"sensor":"' || sensor_type || '","device":"' || device_id
        || '","value":' || CAST(ROUND(reading, 6) AS VARCHAR)
        || ',"batch":' || CAST(record_id // 1000 AS VARCHAR) || '}' AS metadata_json
FROM base
""")

row_count = con.execute("SELECT count(*) FROM readings").fetchone()[0]
print(f"Generated {row_count:,} rows in sensors.duckdb")

con.execute("""
COPY readings TO '/app/data/baseline.parquet' (FORMAT PARQUET, COMPRESSION uncompressed)
""")

import os
baseline_size = os.path.getsize('/app/data/baseline.parquet')
print(f"Baseline written: {baseline_size:,} bytes ({baseline_size / 1024 / 1024:.1f} MB)")

con.close()
