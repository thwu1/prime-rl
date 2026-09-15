-- Analytical views for the partition reconciliation system.
-- Creates deduplication and history views with normalized timestamps.
--

-- View 1: One row per (asset_key, partition_key) with the latest normalized timestamp.
-- Timestamps > 1e12 are in milliseconds and get divided by 1000.
CREATE VIEW IF NOT EXISTS v_latest_materializations AS
SELECT asset_key, partition_key, run_id, normalized_ts
FROM (
    SELECT
        asset_key,
        partition_key,
        run_id,
        CASE WHEN timestamp > 1e12 THEN timestamp / 1000.0 ELSE timestamp END AS normalized_ts,
        ROW_NUMBER() OVER (
            PARTITION BY asset_key, partition_key
            ORDER BY CASE WHEN timestamp > 1e12 THEN timestamp / 1000.0 ELSE timestamp END DESC
        ) AS rn
    FROM materializations
)
WHERE rn = 1;

-- View 2: Full history with recency ranking and record counts per partition.
CREATE VIEW IF NOT EXISTS v_materialization_history AS
SELECT
    asset_key,
    partition_key,
    run_id,
    CASE WHEN timestamp > 1e12 THEN timestamp / 1000.0 ELSE timestamp END AS normalized_ts,
    ROW_NUMBER() OVER (
        PARTITION BY asset_key, partition_key
        ORDER BY CASE WHEN timestamp > 1e12 THEN timestamp / 1000.0 ELSE timestamp END DESC
    ) AS recency_rank,
    COUNT(*) OVER (PARTITION BY asset_key, partition_key) AS total_records
FROM materializations;
