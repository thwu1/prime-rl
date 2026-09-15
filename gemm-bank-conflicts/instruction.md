Analyze shared memory bank conflicts in tiled GEMM kernel configurations and determine optimal shared memory layout padding to minimize them.

## Environment

- `/app/kernels.db` — SQLite database with tables `hardware` (NVIDIA shared memory architecture parameters: `warp_size`, `num_banks`, `bank_width_bytes`) and `kernels` (GEMM tiling configurations: `name`, `block_tile_m`, `block_tile_n`, `block_tile_k`, `thread_tile_m`, `thread_tile_n`, `element_bytes`).
- `/app/src/bank_model.c` and `/app/src/Makefile` — C source implementing the shared memory bank-address mapping functions `compute_bank` and `row_major_addr`. Run `make` in `/app/src/` to compile the shared library `/app/src/libbank.so`.

## Kernel Access Pattern

The GEMM kernel uses 2D block tiling with 2D thread tiling. The 1D thread block contains `(BM * BN) / (TM * TN)` threads. Thread `tid` owns a `TM x TN` sub-tile of the output at row base `(tid / (BN / TN)) * TM`, column base `(tid % (BN / TN)) * TN`.

In the compute inner loop over `k_i` in `[0, BK)`, each thread reads:
- From A tile: element at `[row_base + r][k_i]` for each `r` in `[0, TM)`
- From B tile: element at `[k_i][col_base + c]` for each `c` in `[0, TN)`

Tiles are row-major in shared memory. With row padding `s`, A tile has row stride `BK + s` and B tile has row stride `BN + s`. Threads in a warp execute in lockstep — shared memory loads are issued by all threads in the warp simultaneously. Consult NVIDIA's CUDA documentation for shared memory banking semantics, bank conflict definitions, and broadcast rules.

## Task

For each kernel in the database, count total bank conflicts across all warp-level access events in the full compute phase (both tiles), first with no padding (`s = 0`), then with the smallest `s` in `[0, 32]` that minimizes conflicts for each tile independently.

Write your analysis as a Python script at `/app/bank_conflicts.py`. This script must use the compiled C shared library `/app/src/libbank.so` (via ctypes or equivalent) for bank-address computations, and must exit with code 0 on success.

## Output

Your script must produce two output files:

**`/app/results.json`** — JSON with the following schema:
```json
{
  "scenarios": [
    {
      "name": "<kernel_name>",
      "num_threads": <int>,
      "num_warps": <int>,
      "a_tile": {
        "dimensions": [<BM>, <BK>],
        "conflicts_no_padding": <int>,
        "optimal_skew": <int>,
        "conflicts_with_padding": <int>
      },
      "b_tile": {
        "dimensions": [<BK>, <BN>],
        "conflicts_no_padding": <int>,
        "optimal_skew": <int>,
        "conflicts_with_padding": <int>
      },
      "total_conflicts_no_padding": <int>,
      "total_conflicts_with_padding": <int>
    }
  ]
}
```

All values are integers. `dimensions` arrays contain two integers. `total_conflicts_no_padding` must equal `a_tile.conflicts_no_padding + b_tile.conflicts_no_padding`, and likewise for the padded totals. There must be one entry per kernel in the database (three total: `small_tiles`, `medium_tiles`, `large_tiles`).

**`/app/analysis.db`** — SQLite database with table `conflict_analysis` having columns: `kernel_name TEXT PRIMARY KEY`, `num_threads INTEGER`, `num_warps INTEGER`, `a_conflicts_no_padding INTEGER`, `a_optimal_skew INTEGER`, `a_conflicts_with_padding INTEGER`, `b_conflicts_no_padding INTEGER`, `b_optimal_skew INTEGER`, `b_conflicts_with_padding INTEGER`, `total_conflicts_no_padding INTEGER`, `total_conflicts_with_padding INTEGER`. One row per kernel. Values must be consistent with `/app/results.json`.