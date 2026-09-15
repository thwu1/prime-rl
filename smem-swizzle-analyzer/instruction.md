A shared memory layout optimizer for CUDA GEMM kernels is at `/app/`. It consists of:

- A C library (`src/smem_bank.{c,h}`) for bank conflict simulation, built via CMake into a shared library loaded at runtime through Python ctypes bindings
- Python ctypes bindings (`smem_optimizer/banking.py`) that load `libsmembank.so` and expose `count_bank_conflicts` / `compute_bank_id`
- Python analysis modules (`smem_optimizer/swizzle.py`, `padding.py`, `evaluator.py`) for XOR swizzle and padding strategies — most are stubs or have bugs
- A `Makefile` orchestrating the CMake build and Python optimizer run
- Kernel tiling configurations in `/app/kernel_configs.yaml`

The project has bugs across multiple layers (CMake build configuration, C implementation, Python modules) and missing implementations throughout. Fix all issues and complete the implementation so that `make -C /app all` successfully builds the C shared library, runs the optimizer against all 8 kernel configurations, and produces:

- `/app/optimal_layouts.json` — A JSON array with one object per configuration containing: `name`, `baseline_conflicts`, `swizzle_conflicts`, `swizzle_sizeof_tc`, `padding_conflicts`, `padding_amount`, `padding_overhead_bytes`, `optimal_strategy` (`"swizzle"`, `"padding"`, or `"none"`), and `optimal_conflicts`.

- `/app/analysis_report.csv` — A CSV file with headers `name`, `baseline_conflicts`, `swizzle_sizeof_tc`, `swizzle_conflicts`, `padding_amount`, `padding_conflicts`, `padding_overhead_bytes`, `optimal_strategy`, `optimal_conflicts` and one data row per configuration.

The configurations span multiple data types (float16, float32, float64), tile shapes, access patterns (column vs. row), and vectorization widths. The optimizer must account for how these parameters interact with the 32-bank / 4-byte-width shared memory architecture when evaluating each strategy.