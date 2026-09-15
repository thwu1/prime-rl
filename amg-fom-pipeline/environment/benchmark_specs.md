# CORAL-2 Procurement Benchmark Specifications

## AMG — Algebraic Multigrid Solver

AMG is a parallel algebraic multigrid solver for linear systems arising from
problems on unstructured grids. The benchmark uses a 3D Laplace problem on a
regular grid. AMG is memory-access bound, generates many small messages, and
stresses memory and network latency.

**Figure of Merit** — computational throughput of the solve phase:

    FOM = nnz × iterations / solve_time

where `nnz` is the number of non-zero matrix entries, `iterations` is the
solver iteration count, and `solve_time` is wall-clock seconds for the solve
phase. Higher is better.

For the standard CORAL-2 configuration (100×100×100 grid), the 7-point stencil
discretization of the 3D Laplace operator produces approximately 7 × nx × ny × nz
non-zero entries in the finest-level system matrix. The standard expected `nnz` is
7,000,000 (see `standard_configs.toml`). Deviations in measured `nnz` from values
predicted by the grid configuration warrant investigation.

Because AMG's performance is dominated by sparse matrix-vector products, its
throughput correlates with sustained memory bandwidth. Systems with high memory
bandwidth (as measured by STREAM Triad) should exhibit proportionally higher
AMG FOMs, all else being equal.


## Kripke — Deterministic Transport Sweep

Kripke is a deterministic Sn transport code using structured sweep algorithms
built on RAJA. It exercises memory bandwidth and network latency through
wavefront parallelism.

**Figure of Merit** — transport sweep throughput:

    FOM = zones × directions × groups × iterations / sweep_time

where `zones` is the total spatial zone count, `directions` is the number of
discrete ordinate directions, `groups` is the energy group count, `iterations`
is the source iteration count, and `sweep_time` is the total sweep wall-clock
time in seconds. Higher is better.


## STREAM — Memory Bandwidth

STREAM measures sustained memory bandwidth using simple vector kernel
operations (Copy, Scale, Add, Triad).

**Figure of Merit** — the Triad kernel bandwidth:

    FOM = triad_bandwidth   (MB/s)

Higher is better. The ratio of measured Triad bandwidth to theoretical peak
memory bandwidth characterizes system memory efficiency. This ratio is a
key validation metric: it cannot exceed 1.0 (a physical impossibility), and
well-configured systems typically achieve 75-90%.


## PENNANT — Unstructured Mesh Hydrodynamics

PENNANT is a mini-app for hydrodynamics on general unstructured meshes in 2D
(arbitrary polygons). It makes heavy use of indirect addressing and irregular
memory access patterns.

**Figure of Merit** — simulation throughput:

    FOM = zones × cycles / elapsed_time

where `zones` is the mesh zone count, `cycles` is the number of completed time
steps, and `elapsed_time` is the total wall-clock time in seconds. Higher is
better.
