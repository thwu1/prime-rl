# Dagster Storage Architecture

## Schema Overview

### runs
| Column | Type | Description |
|--------|------|-------------|
| run_id | TEXT (UNIQUE) | Identifier for a pipeline run |
| pipeline_name | TEXT | Pipeline that produced this run |
| status | TEXT | One of: NOT_STARTED, STARTED, SUCCESS, FAILURE |
| create_timestamp | REAL | Unix timestamp when run was created |
| update_timestamp | REAL | Unix timestamp of last status change |
| start_time | REAL | Unix timestamp when execution began |
| end_time | REAL | Unix timestamp when execution completed |
| tags_json | TEXT | JSON object of run tags |

### event_logs
| Column | Type | Description |
|--------|------|-------------|
| run_id | TEXT | References runs.run_id |
| event_type | TEXT | Engine event type |
| dagster_event_type | TEXT | Dagster-specific event type |
| step_key | TEXT | Step that produced the event |
| asset_key | TEXT | Asset affected (if applicable) |
| partition_key | TEXT | Partition key (if applicable) |
| timestamp | REAL | Unix timestamp |
| event_body_json | TEXT | JSON event payload |

### asset_keys
| Column | Type | Description |
|--------|------|-------------|
| asset_key | TEXT (UNIQUE) | Asset identifier |
| last_materialization_timestamp | REAL | Timestamp of most recent ASSET_MATERIALIZATION event |
| last_run_id | TEXT | run_id of the run that produced the most recent materialization |
| tags_json | TEXT | JSON metadata |

### job_ticks
| Column | Type | Description |
|--------|------|-------------|
| job_origin_id | TEXT | Sensor/schedule origin identifier |
| job_name | TEXT | Human-readable job name |
| status | TEXT | One of: STARTED, SUCCESS, FAILURE, SKIPPED |
| tick_type | TEXT | SENSOR or SCHEDULE |
| timestamp | REAL | Unix timestamp when tick was created |
| tick_body_json | TEXT | JSON tick payload |
| end_timestamp | REAL | Unix timestamp when tick completed |

## Data Integrity Invariants

1. **Referential integrity**: Every `event_logs.run_id` MUST correspond to an existing `runs.run_id` entry.
2. **Run lifecycle**: No run should remain in `STARTED` status for more than 24 hours without an update (measured against the most recent `update_timestamp` in the system). Such runs must be resolved to `FAILURE`.
3. **Event uniqueness**: Each `(asset_key, partition_key, run_id)` combination must have at most one `ASSET_MATERIALIZATION` event.
4. **Metadata consistency**: `asset_keys.last_materialization_timestamp` and `asset_keys.last_run_id` must accurately reflect the actual latest `ASSET_MATERIALIZATION` event for that asset in `event_logs`.
5. **Tick lifecycle**: No job tick should remain in `STARTED` status for more than 2 hours (measured against the latest event timestamp in the system). Such ticks must be resolved to `FAILURE`.

## Performance Requirements

All queries defined in `/app/queries.py` represent the daemon's hot paths. Each must be served by an appropriate index -- `EXPLAIN QUERY PLAN` must show `SEARCH` or `USING INDEX` for every query (no `SCAN TABLE`). Index design must account for:
- Column ordering matching each query's filter, sort, and aggregation patterns
- Composite indexes for multi-column predicates
- Different queries may reference overlapping columns but require different column orderings

## Retention Policy

Events and ticks older than 30 days (computed relative to the most recent event timestamp in `event_logs`) must be pruned, subject to these preservation rules:

1. **Latest materializations**: The most recent `ASSET_MATERIALIZATION` event per `(asset_key, partition_key)` must be preserved regardless of age.
2. **Non-terminal runs**: All events belonging to runs with status `STARTED` or `NOT_STARTED` must be preserved.
3. **Backfill runs**: All events belonging to runs tagged with `dagster/backfill` in `tags_json` must be preserved regardless of age.
4. **Tick retention**: When pruning old ticks, preserve the 3 most recent ticks per `job_origin_id` regardless of age.

## Reconciliation Module

`/app/pipeline/reconciliation.py` implements asset dependency resolution:

- **topological_sort(asset_deps)**: Kahn's algorithm over the dependency graph. Must include ALL nodes -- both those appearing as dictionary keys and those appearing only as dependency values in the lists.
- **get_weekly_partition_for_daily(daily_key)**: Maps a daily partition key (YYYY-MM-DD) to its containing Monday-aligned weekly partition. Monday maps to itself; Sunday maps to the preceding Monday.
- **find_stale_assets(asset_deps, materialization_times)**: An asset is stale if ANY upstream dependency has a newer materialization timestamp, not only when ALL do. Assets with no materialization timestamp but with dependencies are also stale.
- **compute_reconciliation_plan(asset_deps, materialization_times)**: Returns assets needing rematerialization in topological order. Must propagate staleness transitively -- if asset B depends on stale asset A, then B is also considered stale regardless of B's own timestamp comparisons.
- **validate_partition_completeness(weekly_key, materialized_daily_partitions)**: Checks that all 7 daily partitions (Monday through Sunday) within a weekly partition window have been materialized.
