A distributed latency monitoring pipeline at `/app/pipeline/` processes per-host CSV measurements from `/app/data/`. It produces streaming quantile estimates, memory-bounded sketch variants, and anomaly detection results.

Configuration: `/app/config.yaml`. Output JSON schema: `/app/schema/output_schema.json`. Reference exact quantiles for select validation windows: `/app/expected/reference_quantiles.json`.

## Pipeline Debugging

The pipeline (`python3 /app/pipeline/run_pipeline.py`) produces incorrect results. Observed symptoms:

- Quantile estimates are grossly inaccurate compared to exact values computed on the raw CSV data
- The anomaly detector produces an excessive number of alerts
- Memory-bounded sketch variants show unexpected accuracy loss

Diagnose and fix all defects in the pipeline modules under `/app/pipeline/`. After fixing, re-run the pipeline to produce correct output at `/app/output/report.json`.

## SLO Compliance Analysis

Using the corrected pipeline output, evaluate each time window's p99 latency against the SLO target defined in `config.yaml`. The output schema at `/app/schema/output_schema.json` defines the required per-window fields, scoring formulas, and compliance semantics.

## Configuration Benchmark

Evaluate accuracy-memory tradeoffs across the parameter matrix defined in `config.yaml` (`benchmark.alpha_values` × `benchmark.max_buckets_values`). For each configuration, measure quantile estimation accuracy against exact quantiles computed from the raw CSV data.

Store all benchmark results in a SQLite database at `/app/output/benchmark.db` in a table named `benchmark` with columns: `alpha REAL, max_buckets INTEGER, max_relative_error REAL, mean_relative_error REAL, memory_buckets INTEGER, p99_max_relative_error REAL` and primary key `(alpha, max_buckets)`.

After populating the benchmark table, use the `sqlite3` command-line tool to create a SQL view named `pareto_frontier` in the database. This view must compute the non-dominated configurations using the Pareto analysis dimensions specified in the output schema.

## Benchmark Report

Generate `/app/output/benchmark_report.txt` by querying the benchmark database using the `sqlite3` command-line tool with column-aligned, human-readable output. The report must contain:

- A line: `=== Benchmark Summary ===`
- The full benchmark table sorted by `alpha, max_buckets`
- A line: `=== Pareto Frontier ===`
- The Pareto-optimal configurations from the `pareto_frontier` view

## Output

Write the final evaluation report to `/app/output/evaluation.json` conforming to the JSON schema at `/app/schema/output_schema.json`.