The `/app/` directory contains a parallel statistics computation engine simulating GPU-style warp-level reductions and shared memory access patterns. It processes four datasets in `/app/data/`.

Running `python3 /app/parallel_reduce.py` currently produces incorrect output. The simulator modules in `/app/simulator/` contain defects affecting statistical correctness and memory analysis.

Your objectives:

1. Diagnose and fix the simulator so `python3 /app/parallel_reduce.py` writes:
   - `/app/output/statistics.json` — per-dataset statistics (mean, variance, skewness, excess kurtosis) matching sequential computation within 1e-9 relative error
   - `/app/output/bank_analysis.json` — shared memory bank conflict analysis for the primary architecture

2. `/app/config.json` lists two target architectures with different shared memory bank counts. Design a single AoS (array-of-structures) struct layout with minimum padding that eliminates all bank conflicts on both architectures simultaneously. Use `/app/layout_tool.py` and the shared memory simulator to evaluate candidates.

3. Write `/app/output/design_report.json` with:
   - `"layouts_evaluated"`: array of at least 6 layout objects, each containing `name`, `padding_bytes`, `total_struct_size`, `conflicts_by_arch` (object mapping each architecture name to its total warp conflict count), `memory_overhead_percent`
   - Must include at least one SoA variant
   - `"cross_arch_optimal"`: the layout achieving zero conflicts on both architectures with minimum overhead, containing `padding_bytes`, `padded_struct_size`, `conflicts_by_arch`, `memory_overhead_percent`, `justification` (explain why the naive single-architecture solution fails and why your choice is optimal for both)
   - `"ranking"`: layout names ordered best-to-worst by total cross-architecture conflicts, then overhead