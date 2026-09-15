## Input Data

- `/app/data/ert_raw/` — ERT micro-kernel measurements at multiple FLOP intensities (`flop_001.dat` through `flop_128.dat`). Each file has whitespace-delimited rows: `elements trials time_us total_bytes total_flops`.
- `/app/data/stream_results.txt` — STREAM benchmark output with raw bandwidth measurements (MB/s).
- `/app/data/kernels.json` — Six application kernel profiles with FLOP counts, byte counts, working-set sizes, and measured GFLOP/s.
- `/app/data/ert_bw_profile.c` — C source for a bandwidth-profile extraction tool (requires `libm`).
- `/app/data/output_format.json` — Required JSON output schema with field descriptions and computational notes.
- `/app/data/chart_requirements.txt` — SVG chart rendering specification.

## Required Outputs

Produce a hierarchical roofline characterization of the target architecture from the empirical data above. Deliver three artifacts:

### 1. `/app/results/bw_profile.dat`

Bandwidth profile produced by the compiled C tool from `/app/data/ert_bw_profile.c`. Must contain at least 10 data rows, each with at least 3 columns: working-set size in bytes (integer), followed by floating-point values.

### 2. `/app/results/roofline_analysis.json`

Must conform to the schema in `/app/data/output_format.json`. Required top-level fields:

- **`peak_gflops`** (float): Peak compute performance derived from the ERT measurements.
- **`cache_hierarchy`** (list of 4 objects): Detected memory hierarchy levels — exactly L1, L2, L3, DRAM — ordered from highest to lowest bandwidth. Each entry must contain:
  - `level` (string): one of "L1", "L2", "L3", "DRAM"
  - `bandwidth_gbps` (float): empirically determined bandwidth in GB/s; values must be monotonically decreasing across the four levels
  - `ridge_point` (float): arithmetic intensity where the memory ceiling meets the compute ceiling for this level (see `output_format.json` notes for the formula)
  - `size_bytes` (int): detected capacity — required for L1, L2, L3; must be **omitted** for DRAM
- **`stream_corrected`** (object): STREAM bandwidth results with write-allocate correction factors applied. Fields: `copy_gbps`, `scale_gbps`, `add_gbps`, `triad_gbps`, `average_gbps`. The `average_gbps` must equal the arithmetic mean of the four corrected values.
- **`kernel_analysis`** (list of 6 objects): One entry per application kernel from `kernels.json`. Each entry must contain:
  - `name` (string): kernel name matching `kernels.json`
  - `arithmetic_intensity` (float): FLOP/Byte ratio
  - `cache_level` (string): which memory hierarchy level the kernel operates in, based on its working-set size relative to detected cache capacities
  - `bound` (string): `"memory"` or `"compute"` classification
  - `attainable_gflops` (float): theoretical attainable performance (see `output_format.json` notes)
  - `efficiency` (float): ratio of measured to attainable performance (see `output_format.json` notes)

### 3. `/app/results/roofline_chart.svg`

Log-log roofline visualization. Must be generated using gnuplot. Requirements:

- Title must contain "Hierarchical Roofline"
- Must show bandwidth ceilings labeled with cache level names: L1, L2, L3, DRAM
- Must show a peak compute ceiling labeled with "Peak"
- Must include labeled data points for all six application kernels, each identifiable by its name