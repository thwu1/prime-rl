A benchmark framework for square dense matrix multiplication (C := C + A * B) is provided at `/app/`. It contains:

- `benchmark.cpp` — harness that measures MFLOPS/s across 26 matrix sizes (31–769) and verifies numerical correctness against a BLAS reference implementation (componentwise error bounded by 3·ε·n·|A|·|B|).
- `dgemm-naive.c` — baseline triple-loop implementation.
- `dgemm-blocked.c` — skeleton blocked implementation (your optimization target).
- `dgemm-blas.c` — OpenBLAS reference (for correctness verification only).
- `CMakeLists.txt` — build system producing `benchmark-naive`, `benchmark-blocked`, and `benchmark-blas`.

Optimize `/app/dgemm-blocked.c` so that `benchmark-blocked` achieves **at least 4x average speedup over the naive implementation** (`benchmark-naive`) across all 26 test matrix sizes, while passing the correctness verification. Your implementation must not call any BLAS, LAPACK, or external linear algebra library routines — it must be self-contained C code. You must not modify any file other than `dgemm-blocked.c`.

Build from `/app/build/` with `cmake -DCMAKE_BUILD_TYPE=Release .. && make`. Matrices are column-major. The function signature is:

```c
void square_dgemm(int lda, double* A, double* B, double* C);
```