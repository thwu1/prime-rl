A ClickHouse server is installed with a pre-loaded `raw_logs` table in the `default` database containing 1,000,000 application log entries from three services (`webserver`, `auth`, `payment`). Each row has a `Body` (raw log string) and a `ServiceName` column.

Design and create optimized structured table(s) that decompose the raw log bodies into typed columns, achieving a compression ratio of at least **40x**, measured as:

```
ratio = raw_logs_uncompressed_bytes / optimized_tables_compressed_bytes
```

where `raw_logs_uncompressed_bytes` comes from `SELECT sum(data_uncompressed_bytes) FROM system.parts WHERE table='raw_logs' AND active` and `optimized_tables_compressed_bytes` from `SELECT sum(data_compressed_bytes) FROM system.parts WHERE table LIKE 'optimized_%' AND active`.

Requirements:

- Parse raw log bodies into individual typed columns using appropriate ClickHouse data types (e.g., `IPv4`, `DateTime`, `LowCardinality`, `UInt16`, `Decimal`, compression codecs).
- Choose ORDER BY keys that maximize compression based on cardinality and size analysis of the data.
- Preserve all log entries: optimized tables must collectively contain at least 99% of `raw_logs` row count.
- Each optimized table must have a computed `Body` column (`ALIAS`) that reconstructs the original log message from the structured columns.
- Name all optimized tables with prefix `optimized_` (e.g., `optimized_web`, `optimized_auth`, `optimized_payment`).
- Run `OPTIMIZE TABLE <name> FINAL` on each table after loading to merge parts.

Start ClickHouse: `clickhouse-server --daemon`
Query: `clickhouse-client --query "..."`