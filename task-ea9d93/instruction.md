Raw ERT microbenchmark data is in `/app/data/`. Each `flops_NNN.dat` file contains measurements at NNN FLOPs per element. Per-line format: `working_set_bytes trials microseconds total_bytes total_flops` (comment lines start with `#`).

Pre-recorded STREAM benchmark output is at `/app/stream_output.txt`. Hardware specifications are in `/app/system_spec.json`. Application kernel profiles are in `/app/kernels.json`.

Build a cross-validated hierarchical roofline model that integrates three information sources: ERT empirical measurements, STREAM bandwidth figures, and theoretical peak calculations from the hardware specification. The analysis must detect the four-level memory hierarchy (L1/L2/L3/DRAM) from ERT data, reconcile STREAM and ERT DRAM bandwidth measurements by correctly accounting for the write-allocate effects and byte-counting convention differences inherent to each benchmark's methodology, and validate all empirical results against theoretical hardware limits.

For kernel classification: when `write_allocate` is true, effective bytes per element = `bytes_read_per_element + 2 * bytes_written_per_element`; otherwise `bytes_read_per_element + bytes_written_per_element`. Use write-allocate-corrected arithmetic intensity for roofline classification and achievable GFLOP/s prediction.

Write results to `/app/results/roofline_analysis.json`:

```json
{
  "empirical": {
    "bandwidths_gbs": {"L1": ..., "L2": ..., "L3": ..., "DRAM": ...},
    "cache_boundaries_bytes": {"L1": ..., "L2": ..., "L3": ...},
    "peak_gflops": ...
  },
  "theoretical": {
    "peak_gflops": ...,
    "dram_bandwidth_gbs": ...
  },
  "stream": {
    "copy_gbs": ..., "scale_gbs": ..., "add_gbs": ..., "triad_gbs": ...
  },
  "validation": {
    "peak_efficiency": ...,
    "dram_efficiency": ...,
    "stream_triad_corrected_gbs": ...,
    "stream_ert_ratio": ...
  },
  "ridge_points": {"L1": ..., "L2": ..., "L3": ..., "DRAM": ...},
  "kernel_analysis": [
    {
      "name": "...",
      "arithmetic_intensity": ...,
      "arithmetic_intensity_with_wa": ...,
      "memory_level": "L1|L2|L3|DRAM",
      "classification": "memory-bound|compute-bound",
      "achievable_gflops": ...
    }
  ]
}
```

`arithmetic_intensity` is the uncorrected AI. `arithmetic_intensity_with_wa` is the write-allocate-corrected AI (null when `write_allocate` is false).

Generate a log-log roofline chart at `/app/results/roofline.svg` using gnuplot. The chart must display sloped bandwidth ceilings for each memory level (L1, L2, L3, DRAM), the empirical peak compute ceiling, the theoretical peak as a dashed line, and all kernel operating points with name labels.