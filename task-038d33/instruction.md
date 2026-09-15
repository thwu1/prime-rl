An IoT monitoring pipeline writes sensor telemetry to `/app/data/baseline.parquet` (1M rows, source DuckDB database at `/app/data/sensors.duckdb`, table `readings`). Two production SLA violations have been filed:

1. The file consumes far more storage than expected for this data volume and column profile.
2. Dashboard queries filtering on `event_timestamp` ranges show no evidence of row group pruning — all rows are scanned regardless of predicate selectivity.

DuckDB CLI is at `/usr/local/bin/duckdb`. Python 3 and pip are available.

Investigate the baseline file's internal structure to identify root causes for both issues, then produce the deliverables below.

## `/app/output/optimized.parquet`

An optimized re-encoding of the same dataset satisfying all of the following:

- Identical data to the baseline (same rows, same values, all 10 columns preserved)
- File size at most 20% of the baseline
- Exactly 4 row groups of 250,000 rows each
- Consecutive row groups have strictly non-overlapping `event_timestamp` ranges (max of group *i* < min of group *i*+1), and likewise for `record_id`
- Every row group carries valid min/max statistics for both `record_id` and `event_timestamp`
- Each column's Parquet encoding is individually selected to match its data distribution — not a single default applied uniformly
- A schema metadata key `optimization_config` containing a JSON object that maps every column name to the encoding applied to it (non-empty string values)

## `/app/output/analysis.json`

A JSON diagnostic report containing:

- `baseline_size_bytes` (int), `optimized_size_bytes` (int), `compression_ratio` (float: optimized / baseline), `num_row_groups` (int), `compression_codec` (string)
- `row_group_boundaries`: array of 4 objects, each with `row_group_index`, `num_rows`, `min_record_id`, `max_record_id`, `min_timestamp`, `max_timestamp`
- `columns`: object keyed by all 10 column names, each with `physical_type` (string), `encoding` (string), `cardinality` (int — computed from actual data), `rationale` (string, at least 10 characters explaining why this encoding fits the column's data characteristics)