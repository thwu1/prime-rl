# Event Data Contract v3.0

## Target Schema

All output records must conform to this schema:

| Column      | Type                  | Nullable | Notes                                |
|-------------|-----------------------|----------|--------------------------------------|
| event_id    | int64                 | no       | Unique event identifier              |
| timestamp   | timestamp[us, tz=UTC] | no       | Event time in microsecond-precision UTC |
| amount      | float64               | no       | Transaction amount in dollars        |
| user_id     | int64                 | yes      | User identifier                      |
| category    | string                | yes      | Event category                       |
| status      | string                | no       | One of: completed, pending, failed   |
| region      | string                | yes      | Geographic region                    |
| channel     | string                | yes      | Origination channel                  |
| risk_score  | float64               | yes      | Risk assessment score [0.0, 1.0]     |

## Deduplication

When the same `event_id` appears in multiple staging files, retain the record from the file whose name is lexicographically greatest. This reflects the retry semantics of the ingestion pipeline — later versions supersede earlier ones.

## Data Quality Rules

Quarantine (exclude from main output) any record where:
- `event_id` is null
- `amount` is negative
- `timestamp` is after 2024-12-31T23:59:59 UTC

Quarantined records must be written to a separate file with an additional `quarantine_reason` string column explaining why the record was excluded.

## Output Format

- Compression: ZSTD
- Partitioning: Hive-style by `year_month` column derived from `timestamp` (format: `YYYY-MM`)
- The `year_month` partition column must NOT appear as a data column within partition files
- Row groups should be sorted by `timestamp` ascending within each partition

## Compaction Manifest

The manifest JSON file must include:
- `total_input_rows`: total rows across all staging files before any processing
- `total_output_rows`: rows in the final compacted dataset
- `total_quarantined`: rows written to the quarantine file
- `duplicates_removed`: number of duplicate rows removed during deduplication
- `files_processed`: number of staging files read
- `partitions`: list of objects, each with `year_month` and `row_count`
