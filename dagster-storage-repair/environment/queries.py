"""
Canonical query patterns used by the orchestration daemon.
These queries must use index scans (not full table scans) for acceptable performance.
The agent must add indexes to dagster_storage.db so that all seven queries
use indexed lookups as shown by EXPLAIN QUERY PLAN.

"""

# Query 1: Fetch all events for a specific run, ordered by time
EVENTS_BY_RUN = "SELECT * FROM event_logs WHERE run_id = ? ORDER BY timestamp"

# Query 2: Get the latest materialization event for a specific asset
LATEST_MATERIALIZATION = (
    "SELECT * FROM event_logs "
    "WHERE asset_key = ? AND dagster_event_type = 'ASSET_MATERIALIZATION' "
    "ORDER BY timestamp DESC LIMIT 1"
)

# Query 3: Get recent ticks for a specific job origin
TICKS_BY_ORIGIN = (
    "SELECT * FROM job_ticks "
    "WHERE job_origin_id = ? AND timestamp > ? "
    "ORDER BY timestamp DESC"
)

# Query 4: Get events of a specific type within a time range
EVENTS_BY_TYPE_TIMERANGE = (
    "SELECT * FROM event_logs "
    "WHERE dagster_event_type = ? AND timestamp BETWEEN ? AND ?"
)

# Query 5: Get events for a specific asset and partition
EVENTS_BY_ASSET_PARTITION = (
    "SELECT * FROM event_logs "
    "WHERE asset_key = ? AND partition_key = ? "
    "ORDER BY timestamp DESC"
)

# Query 6: Get latest materialization timestamp per asset (reconciliation cache)
MAT_TIMESTAMPS_BY_ASSET = (
    "SELECT asset_key, MAX(timestamp) FROM event_logs "
    "WHERE dagster_event_type = 'ASSET_MATERIALIZATION' "
    "GROUP BY asset_key"
)

# Query 7: Count events by type within a time window (monitoring dashboard)
EVENT_COUNTS_BY_TIMERANGE = (
    "SELECT dagster_event_type, COUNT(*) FROM event_logs "
    "WHERE timestamp BETWEEN ? AND ? "
    "GROUP BY dagster_event_type"
)
