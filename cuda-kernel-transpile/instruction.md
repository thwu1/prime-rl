Implement CPU-equivalent computations for the CUDA kernels in `/app/kernels/`, producing binary output files that match the kernels' numerical behavior.

Read each CUDA source file to understand the computation it performs. Load binary input data from `/app/data/` and write results to `/app/output/` as specified in `/app/spec.json`. All data uses little-endian float32.

The kernels use GPU-specific optimizations (shared memory tiling, register-based z-slice sweeping, float2 vectorization, hardware intrinsics like `__fdividef` and `rsqrtf`) that obscure the underlying mathematical operations. Your implementations must match the mathematical operation performed by each kernel, not reproduce the GPU execution strategy.

Two kernels are provided:

- `/app/kernels/fdtd_3d.cu` — 3D finite-difference stencil on a padded volumetric grid. Uses `__constant__` memory for stencil coefficients and a complex z-slice sweeping pattern with `infront`/`behind` register arrays. The output volume has the same dimensions as the padded input; only the inner region (excluding the halo of width RADIUS on each side) is computed. The halo region of the output must remain zero.

- `/app/kernels/black_scholes.cu` — European option pricing with a polynomial approximation for the cumulative normal distribution (not a standard library CDF). Uses `__fdividef(1.0f, rsqrtf(T))` to compute `sqrt(T)`. The polynomial CND function uses the Abramowitz & Stegun formula 26.2.17 with specific coefficients — you must replicate this exact approximation, not substitute a different CDF implementation.