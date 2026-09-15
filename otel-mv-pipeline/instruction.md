ClickHouse is installed on this system. Raw OpenTelemetry-style telemetry data containing distributed tracing spans from a microservices application is available at `/app/data/telemetry.csv`. The expected row count is in `/app/data/row_count.txt`.

Build a ClickHouse-based observability data pipeline:

- Create database `observability` with table `spans` using a MergeTree-family engine. The sorting key must be optimized for service-level time-range queries and should include `service_name`. Use `LowCardinality` for low-cardinality string columns. Choose appropriate column types (e.g., `DateTime64(6)` for microsecond timestamps, `UInt64` for durations, `UInt16` for status codes).

- Ingest all rows from the CSV into the table. The total row count must match `/app/data/row_count.txt`.

- Create at least 2 materialized views in the `observability` database for real-time aggregation: one for error-rate tracking per service and one for latency percentile tracking. The views must be populated with data from the existing spans (not empty).

- Produce these result files in `/app/results/`:

  - `top_error_services.csv`: Top 3 services by error rate (errors defined as `status_code >= 400`). Columns: `service_name,total_requests,error_count,error_rate`. Rate as decimal rounded to 4 places. Ordered by `error_rate` descending.

  - `p99_by_service.csv`: P99 duration per service in microseconds (integer). Columns: `service_name,p99_duration_us`. Ordered alphabetically by `service_name`.

  - `deep_traces.csv`: All `trace_id` values with more than 5 spans. Columns: `trace_id,span_count`. Ordered by `span_count` descending, then `trace_id` ascending.

  - `error_correlation.csv`: For each service, the single operation with the highest error count. Columns: `service_name,operation_name,error_count`. Ordered alphabetically by `service_name`.

All result CSVs must include a header row.