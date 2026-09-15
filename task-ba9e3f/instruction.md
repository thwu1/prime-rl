`/app/correlate.cpp` contains a naive implementation of pairwise Pearson correlation matrix computation. Given an n x d input matrix (n row vectors of dimension d, row-major layout), it produces the n x n symmetric correlation matrix where entry (i,j) is the Pearson correlation coefficient between row i and row j.

The current implementation is correct but extremely slow for large inputs due to redundant per-pair mean/variance recomputation and poor utilization of modern CPU microarchitecture (no SIMD exploitation, poor cache locality, unnecessary double-precision arithmetic in the inner loop).

**Your task:** Modify only `/app/correlate.cpp` to achieve at least **10x speedup** over the naive baseline for n=1500, d=500, while maintaining correctness (output must match the naive reference within absolute tolerance 1e-3 for all entries).

- The function signature in `/app/correlate.h` must not change.
- Do not modify `/app/benchmark.cpp` or `/app/correlate.h`.
- A read-only copy of the naive implementation is at `/app/correlate_naive.cpp` for reference.
- **Build:** `cd /app && make`
- **Benchmark:** `/app/benchmark <n> <d> [output_file]` — prints `TIME:<seconds>` to stdout and optionally writes the raw float32 output matrix to a binary file.