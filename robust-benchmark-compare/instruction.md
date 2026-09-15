A Zig performance benchmarking tool (source at `/app/poop-src/main.zig`) uses Linux `perf_event_open` to collect hardware counter samples and computes basic statistics for command comparison. Study its data structures, outlier handling, confidence interval approach, and the embedded reference tables to understand the benchmark data format and the tool's existing analytical limitations.

Build `/app/benchmark_compare.py` — a Python engine that extends this tool's statistical approach into a rigorous multi-metric comparison system. The engine must:

- Read two JSON benchmark files (data at `/data/`, format matches the Zig tool's sample structure)
- Identify and exclude anomalous samples before statistical testing
- Determine whether each metric differs significantly between runs, properly accounting for potentially unequal variances and sample sizes, with exact p-values computed from the continuous theoretical distribution (not table lookup)
- Quantify practical significance using a non-parametric dominance measure bounded to [-1, 1]
- Compute resampling-based confidence intervals for the location difference that remain valid without distributional assumptions
- Control the family-wise error rate when testing multiple metrics simultaneously
- Persist all raw data and computed statistics in a SQLite database at `/app/benchmark.db` conforming to `/app/db_schema.sql`
- Write the final report as JSON conforming to `/app/schema.json`

Constraints:
- Only Python standard library modules for statistical computation (`math`, `random`, `json`, `sqlite3`, `sys`, `os`). No numpy, scipy, or other external packages.
- Expose a `compare_benchmarks(baseline_path, candidate_path, output_path)` function
- All statistical computations implemented from scratch

Run: `python3 /app/benchmark_compare.py /data/run_a.json /data/run_b.json /app/report.json`

Test data: `/data/run_a.json`, `/data/run_b.json`, `/data/edge_small.json`, `/data/edge_zero_var.json`