#!/bin/bash

set -e

# ------------------------------------------------------------------
# Robust ClickHouse startup — kill any zombie, start fresh as root
# ------------------------------------------------------------------
start_clickhouse() {
    if clickhouse-client --query "SELECT 1" >/dev/null 2>&1; then
        return 0
    fi

    # Kill any lingering ClickHouse process so ports are freed
    pkill -9 -f clickhouse-server 2>/dev/null || true
    sleep 2

    # Ensure directories exist with root ownership
    mkdir -p /var/lib/clickhouse /var/log/clickhouse-server /var/run/clickhouse-server
    chown -R root:root /var/lib/clickhouse /var/log/clickhouse-server /var/run/clickhouse-server

    # Remove stale PID files
    rm -f /var/run/clickhouse-server/clickhouse-server.pid 2>/dev/null
    rm -f /run/clickhouse-server/clickhouse-server.pid 2>/dev/null

    # Start server as root
    clickhouse-server --config-file=/etc/clickhouse-server/config.xml --daemon 2>/dev/null || true

    # Wait for server (up to 120 seconds)
    for i in $(seq 1 120); do
        clickhouse-client --query "SELECT 1" >/dev/null 2>&1 && return 0
        sleep 1
    done

    echo "ERROR: ClickHouse server failed to start"
    cat /var/log/clickhouse-server/clickhouse-server.err.log 2>/dev/null | tail -30 || true
    exit 1
}

start_clickhouse

# Create database
clickhouse-client --query "CREATE DATABASE IF NOT EXISTS observability"

# Create spans table with optimized schema
clickhouse-client --multiquery --query "
CREATE TABLE IF NOT EXISTS observability.spans (
    timestamp DateTime64(6),
    trace_id String,
    span_id String,
    parent_span_id String,
    service_name LowCardinality(String),
    operation_name LowCardinality(String),
    duration_us UInt64,
    status_code UInt16,
    http_method LowCardinality(String),
    http_url String,
    log_level LowCardinality(String)
) ENGINE = MergeTree()
ORDER BY (service_name, timestamp, trace_id)
PARTITION BY toDate(timestamp)
"

# Ingest data from CSV
clickhouse-client --query "INSERT INTO observability.spans FORMAT CSVWithNames" < /app/data/telemetry.csv

# Create materialized view for error rate tracking (SummingMergeTree)
clickhouse-client --query "
CREATE MATERIALIZED VIEW IF NOT EXISTS observability.mv_error_rates
ENGINE = SummingMergeTree()
ORDER BY (service_name, window_start)
POPULATE
AS SELECT
    service_name,
    toStartOfFiveMinutes(timestamp) AS window_start,
    count() AS total_requests,
    countIf(status_code >= 400) AS error_count
FROM observability.spans
GROUP BY service_name, window_start
"

# Create materialized view for latency percentile tracking (AggregatingMergeTree)
clickhouse-client --query "
CREATE MATERIALIZED VIEW IF NOT EXISTS observability.mv_latency_percentiles
ENGINE = AggregatingMergeTree()
ORDER BY (service_name, operation_name, window_start)
POPULATE
AS SELECT
    service_name,
    operation_name,
    toStartOfMinute(timestamp) AS window_start,
    quantileState(0.99)(duration_us) AS p99_state,
    countState() AS request_count
FROM observability.spans
GROUP BY service_name, operation_name, window_start
"

# Generate result files
mkdir -p /app/results

# 1. Top error services by error rate
clickhouse-client --format CSVWithNames --query "
SELECT
    service_name,
    count() AS total_requests,
    countIf(status_code >= 400) AS error_count,
    round(countIf(status_code >= 400) / count(), 4) AS error_rate
FROM observability.spans
GROUP BY service_name
ORDER BY error_rate DESC
LIMIT 3
" > /app/results/top_error_services.csv

# 2. P99 latency per service
clickhouse-client --format CSVWithNames --query "
SELECT
    service_name,
    toUInt64(quantile(0.99)(duration_us)) AS p99_duration_us
FROM observability.spans
GROUP BY service_name
ORDER BY service_name ASC
" > /app/results/p99_by_service.csv

# 3. Deep traces (more than 5 spans)
clickhouse-client --format CSVWithNames --query "
SELECT
    trace_id,
    count() AS span_count
FROM observability.spans
GROUP BY trace_id
HAVING span_count > 5
ORDER BY span_count DESC, trace_id ASC
" > /app/results/deep_traces.csv

# 4. Error correlation: top error operation per service
# Note: subquery column renamed to err_cnt to avoid ClickHouse name
# resolution conflict with the outer max(...) AS error_count alias.
clickhouse-client --format CSVWithNames --query "
SELECT
    service_name,
    argMax(operation_name, err_cnt) AS operation_name,
    max(err_cnt) AS error_count
FROM (
    SELECT
        service_name,
        operation_name,
        countIf(status_code >= 400) AS err_cnt
    FROM observability.spans
    GROUP BY service_name, operation_name
)
WHERE err_cnt > 0
GROUP BY service_name
ORDER BY service_name ASC
" > /app/results/error_correlation.csv

echo "Solution complete."
