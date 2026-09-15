import duckdb
import os

os.makedirs('/app/output', exist_ok=True)

con = duckdb.connect('/app/warehouse.duckdb')

# Table 1: sequential_data - 2M rows
# Sequential IDs and timestamps with cycling categories and smooth value function.
# SHUFFLED so that a default export has no useful zone maps on ts.
con.execute("""
CREATE TABLE sequential_data AS
SELECT id, ts, category, value FROM (
    SELECT
        i::BIGINT AS id,
        TIMESTAMP '2024-01-01' + (i * INTERVAL '1' SECOND) AS ts,
        'cat_' || LPAD((i % 10 + 1)::VARCHAR, 3, '0') AS category,
        (i * 0.001 + sin(i * 0.01) * 0.1)::DOUBLE AS value,
        hash(i * 7 + 13) AS _shuffle
    FROM range(0, 2000000) t(i)
) sub
ORDER BY _shuffle
""")
print("Created sequential_data: 2,000,000 rows (shuffled)")

# Table 2: wide_integers - 2M rows
# All columns stored as BIGINT but actual value ranges are much smaller.
# Values are pseudo-randomly distributed (hash-based), not sorted by any key.
con.execute("""
CREATE TABLE wide_integers AS
SELECT
    i::BIGINT AS record_id,
    (hash(i + 1000000) % 500)::BIGINT AS group_code,
    (hash(i + 2000000) % 20)::BIGINT AS sub_code,
    (hash(i + 3000000) % 2)::BIGINT AS flag_a,
    (hash(i + 4000000) % 2)::BIGINT AS flag_b,
    (hash(i + 5000000) % 256)::BIGINT AS counter,
    (hash(i + 6000000) % 10001)::BIGINT AS score
FROM range(0, 2000000) t(i)
""")
print("Created wide_integers: 2,000,000 rows")

# Table 3: text_logs - 500K rows
# Text-heavy data with low-cardinality categorical columns (severity, service).
# Message column has template patterns; request_id is high-entropy (md5 hash).
con.execute("""
CREATE TABLE text_logs AS
SELECT
    i::BIGINT AS log_id,
    CASE
        WHEN hash(i + 100) % 100 < 60 THEN 'INFO'
        WHEN hash(i + 100) % 100 < 80 THEN 'DEBUG'
        WHEN hash(i + 100) % 100 < 90 THEN 'WARNING'
        WHEN hash(i + 100) % 100 < 98 THEN 'ERROR'
        ELSE 'CRITICAL'
    END AS severity,
    CASE hash(i + 200) % 8
        WHEN 0 THEN 'auth-service'
        WHEN 1 THEN 'api-gateway'
        WHEN 2 THEN 'user-service'
        WHEN 3 THEN 'payment-processor'
        WHEN 4 THEN 'notification-service'
        WHEN 5 THEN 'data-pipeline'
        WHEN 6 THEN 'cache-manager'
        ELSE 'search-indexer'
    END AS service,
    'Request ' || (hash(i + 300) % 10000)::VARCHAR || ' processed in ' ||
    (hash(i + 400) % 5000)::VARCHAR || 'ms by handler ' ||
    CASE hash(i + 500) % 5
        WHEN 0 THEN 'AuthHandler'
        WHEN 1 THEN 'DataHandler'
        WHEN 2 THEN 'QueryHandler'
        WHEN 3 THEN 'StreamHandler'
        ELSE 'CacheHandler'
    END AS message,
    md5(i::VARCHAR) AS request_id
FROM range(0, 500000) t(i)
""")
print("Created text_logs: 500,000 rows")

# Table 4: sensor_metrics - 2M rows
# Float time-series from 100 sensors, with smooth temporal patterns.
# SHUFFLED so that a default export has no useful zone maps on measured_at.
con.execute("""
CREATE TABLE sensor_metrics AS
SELECT sensor_id, measured_at, temperature, humidity, pressure, battery_pct FROM (
    SELECT
        ((hash(i + 700) % 100) + 1)::INTEGER AS sensor_id,
        TIMESTAMP '2024-06-01' + (i * INTERVAL '1' SECOND) AS measured_at,
        (20.0 + ((hash(i + 700) % 100) + 1) * 0.05 + sin(i * 0.001) * 2.0)::DOUBLE AS temperature,
        (50.0 + cos(i * 0.0005) * 10.0 + (hash(i + 800) % 100) * 0.01)::DOUBLE AS humidity,
        (1013.25 + sin(i * 0.0001) * 5.0 + (hash(i + 900) % 50) * 0.01)::DOUBLE AS pressure,
        (100.0 - (i / 2000000.0) * 5.0)::DOUBLE AS battery_pct,
        hash(i * 3 + 17) AS _shuffle
    FROM range(0, 2000000) t(i)
) sub
ORDER BY _shuffle
""")
print("Created sensor_metrics: 2,000,000 rows (shuffled)")

con.close()
print("Database created successfully at /app/warehouse.duckdb")
