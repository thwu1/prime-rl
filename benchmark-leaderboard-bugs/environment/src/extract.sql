-- Stage 1: DuckDB data extraction
-- Reads Parquet run results and SQLite metadata
-- Creates temp tables for pipeline.py to query

ATTACH '{db_path}' AS meta (TYPE SQLITE);

CREATE TEMP TABLE model_info AS SELECT name, release_date FROM meta.models;

CREATE TEMP TABLE task_info AS SELECT id, created_at, repo FROM meta.tasks;

CREATE TEMP TABLE pipeline_meta AS
    SELECT (SELECT COUNT(*) FROM task_info) AS num_tasks,
           5 AS num_runs_per_model;

CREATE TEMP TABLE long_results AS
    WITH parquet_data AS (
        SELECT
            regexp_extract(filename, '([^/]+)\.parquet$', 1) AS model_name,
            instance_id, r1, r2, r3, r4, r5
        FROM read_parquet('{runs_dir}/*.parquet', filename=true)
    )
    SELECT model_name, instance_id, run_name,
           COALESCE(resolved, false) AS resolved
    FROM parquet_data
    UNPIVOT (resolved FOR run_name IN (r1, r2, r3, r4, r5));

CREATE TEMP TABLE run_rates AS
    SELECT
        model_name,
        run_name,
        CAST(COUNT(CASE WHEN resolved THEN 1 END) AS DOUBLE)
            / (SELECT num_tasks FROM pipeline_meta) AS rate
    FROM long_results
    GROUP BY model_name, run_name;

CREATE TEMP TABLE model_metrics AS
    SELECT
        model_name,
        AVG(rate) AS resolved_rate,
        SQRT(VAR_POP(rate) / COUNT(rate)) AS sem
    FROM run_rates
    GROUP BY model_name;

CREATE TEMP TABLE task_solve_counts AS
    SELECT
        instance_id,
        model_name,
        COUNT(CASE WHEN resolved THEN 1 END) AS successes,
        COUNT(*) AS attempts
    FROM long_results
    GROUP BY instance_id, model_name
