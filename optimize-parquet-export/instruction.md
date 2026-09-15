A DuckDB database at `/app/warehouse.duckdb` contains four analytical tables with distinct data distributions. Export each table to a Parquet file in `/app/output/` that satisfies file size, row group structure, and zone map filtering constraints simultaneously:

| Table | Output File | Max Size | Row Groups | Zone Map Constraint |
|-------|------------|----------|------------|---------------------|
| `sequential_data` | `/app/output/sequential_data.parquet` | 15 MB | 20 – 40 | A 2-day window on `ts` overlaps ≤ 5 row groups |
| `wide_integers` | `/app/output/wide_integers.parquet` | 45 MB | — | `score BETWEEN 5000 AND 6000` overlaps ≤ 25% of total row groups |
| `text_logs` | `/app/output/text_logs.parquet` | 30 MB | — | `severity = 'CRITICAL'` overlaps ≤ 2 row groups |
| `sensor_metrics` | `/app/output/sensor_metrics.parquet` | 50 MB | 25 – 70 | A 3-day window on `measured_at` overlaps ≤ 10 row groups |

**Row group constraints** specify the required count of Parquet row groups in the exported file.

**Zone map constraints** require that the per-row-group column-chunk statistics (min/max) make the given filter selective: only the listed number of row groups may have a statistics range overlapping the filter predicate. This verifies that the physical data layout enables efficient predicate pushdown for analytical scans.

Every exported file must preserve the exact rows, columns, and values of its source table. A default `COPY table TO file (FORMAT PARQUET)` will violate multiple constraints. The data characteristics of each table require distinct layout strategies.

DuckDB CLI is available at `/usr/local/bin/duckdb` and the Python bindings are installed (`import duckdb`).