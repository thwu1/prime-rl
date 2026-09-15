A C++ analytics tool at `/app/` uses a CMake build system (`/app/CMakeLists.txt`). The current CMakeLists.txt has several configuration errors — the source file path is wrong, the target name doesn't match what downstream tooling expects (`analytics`), and the compile options disable optimization. Fix the CMake configuration so the project builds correctly with optimization enabled.

The program in `/app/src/main.cpp` performs two computations on CSV data at `/app/data/input.csv` (columns: `f0,f1,f2,f3,f4,timestamp,weight,target`):

1. **Leave-One-Out Cross-Validation** for ridge regression with 5 features and regularization lambda=0.01. For each of the N data points, it fits ridge regression on the remaining N-1 points and computes the LOO prediction error, reporting overall LOO RMSE and MAE.

2. **Weighted Pairwise Kernel Sum**: `S = sum_i sum_j exp(-0.5 * min(t_i, t_j)) * w_i * w_j` where timestamps are sorted ascending and weights are positive.

Both implementations use naive O(N^2) algorithms. Optimize the program so it produces numerically correct results (relative error < 1e-4) and completes within 60 seconds for N=100,000 records.

Before and after optimizing, profile the implementation using Valgrind's cachegrind tool on a small dataset (N=1,000). Use `cg_annotate` or parse the cachegrind summary output to extract cache performance metrics. Generate a structured profiling comparison report at `/app/output/profile_report.json` containing metrics for both the naive and optimized versions. The report must be valid JSON with keys `"naive"` and `"optimized"`, each containing integer-valued fields `"I_refs"` (instruction references), `"D_refs"` (data references), `"D1_misses"` (L1 data cache misses), and `"LLd_misses"` (last-level data cache misses), all parsed from cachegrind output.

The final compiled binary must be at `/app/analytics`. It reads from `/app/data/input.csv` and writes JSON to `/app/output/results.json` with fields: `loo_rmse`, `loo_mae`, `kernel_sum`, `elapsed_sec`.