# GPU Architecture Notes

## SM Resource Model

GPUs execute through Streaming Multiprocessors (SMs). Work is scheduled in warps
(fixed-size groups of threads). Cooperative Thread Arrays (CTAs, also called thread
blocks) are the unit of resource allocation. Multiple CTAs can execute concurrently
on a single SM, bounded by finite resources.

Four independent resources constrain CTA residency on each SM:

- **Warp slots**: Each CTA occupies warp slots equal to its warp count.
- **Register file**: Each CTA's register footprint depends on per-thread register
  allocation multiplied by its thread count. The hardware allocator rounds
  per-thread register counts upward to the allocation granularity boundary.
- **Shared memory**: Each CTA's shared memory allocation is carved from the SM's
  shared memory pool.
- **Block slots**: A hard ceiling on concurrent CTAs per SM.

The binding constraint — whichever resource yields the fewest concurrent CTAs —
determines actual CTA residency. When multiple resources impose the same CTA
limit, the bottleneck is reported by hardware diagnostic priority: shared memory,
registers, warps, block slots.

A configuration is infeasible if its per-thread register demand exceeds the
per-thread maximum, or its shared memory exceeds the per-block limit, or it
cannot fit at least one CTA on the SM.

## Occupancy

Occupancy is defined as the ratio of active warps on an SM to the SM's maximum
warp capacity. It quantifies how well execution resources are utilized for
latency hiding.

## Tiled Matmul Kernel Resources

Study `/app/triton_matmul.py` for details on how tiled matmul maps configuration
parameters to hardware resources:

- **Thread structure**: A CTA uses `num_warps` warps. Each warp has `warp_size`
  threads.
- **Accumulator pressure**: The kernel maintains a tile-sized output accumulator
  in higher precision (fp32). This accumulator, of dimensions BLOCK_M x BLOCK_N,
  is distributed evenly across all threads in the CTA. Each thread's share of
  the accumulator contributes to its register footprint, in addition to overhead
  registers for addressing, loop control, and masking.
- **Shared memory**: Software pipelining uses `num_stages` pipeline stages. Each
  stage holds input tile buffers (both A-tile and B-tile) in the input precision.
- **Tile scheduling**: The `GROUP_SIZE_M` parameter reorders CTA-to-tile mapping
  to improve L2 cache utilization.

Hardware specifications and kernel resource profiles (including register overhead
estimates) are available in the SQLite database at `/app/gpu_specs.db`.

## Cache-Aware Memory Traffic

Tile grouping via `GROUP_SIZE_M` affects effective DRAM traffic. Rather than
processing tiles in strict row-major order, consecutive row-tile indices are
grouped together. CTAs within a group process adjacent row tiles while sharing
column-tile iterations, so B-matrix column data loaded by one CTA remains in
L2 cache for subsequent CTAs in the same group. This reduces effective DRAM
traffic for the B-tile proportionally to the effective group size, which is
bounded by the actual number of row tiles in the matrix dimension.
