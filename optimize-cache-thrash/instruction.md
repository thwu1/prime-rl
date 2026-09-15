A sensor data analytics pipeline in `/app/` processes a 16384x512 telemetry matrix through four computational kernels: `analyze_sensors`, `normalize_data`, `smooth_data`, and `compute_distances`. The code is functionally correct but severely underperforms. Not all kernels suffer from the same bottleneck type.

Your task has two deliverables:

**Performance diagnosis report** — Profile the unoptimized binary at `/app/.original/pipeline` using `valgrind --tool=cachegrind` and interpret the results with `cg_annotate`. Write `/app/analysis.json` containing:

```json
{
  "cache_config": {
    "l1d_size_bytes": <int>,
    "l1d_line_bytes": <int>,
    "l1d_associativity": <int>
  },
  "kernel_profiles": {
    "<kernel_name>": {
      "d1_read_miss_rate_pct": <float>,
      "classification": "<cache_bound|compute_bound>"
    }
  },
  "most_cache_impactful": "<kernel_name>"
}
```

All four kernels must appear in `kernel_profiles`. Each kernel's `classification` must correctly identify whether its primary bottleneck is data cache misses or redundant computation. `most_cache_impactful` is the kernel with the highest total D1 read misses. The L1 data cache configuration must reflect the actual environment.

**Optimized implementation** — Restructure `/app/pipeline.c` so the pipeline runs at least 3x faster overall while producing numerically identical output. Apply the appropriate optimization strategy to each kernel based on your diagnosis — cache optimizations alone will not suffice.

Build: `make -C /app`
Run: `/app/pipeline <seed> <output_file>` (timing on stderr as `TIME=...`)
Baseline: `/app/.original/pipeline`