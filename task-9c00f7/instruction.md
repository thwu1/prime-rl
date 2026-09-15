The project at `/app/` contains a C framework for single-precision general matrix multiplication (SGEMM). It includes a naive triple-loop reference implementation (`/app/src/naive.c`), a stub for the optimized implementation (`/app/src/optimized.c`), a correctness test harness (`/app/test_runner.c`), header (`/app/include/matmul.h`), and a CMake build configuration.

Implement the `matmul` function in `/app/src/optimized.c` so that it computes `C = A * B` where A is M-by-K, B is K-by-N, C is M-by-N, all stored in column-major order with leading dimension equal to the row count (element at row i, column j of matrix X with M rows is at `X[j * M + i]`).

```c
void matmul(float* A, float* B, float* C, int M, int N, int K);
```

Requirements:

- Must produce results matching `matmul_naive` within floating-point tolerance for **all** matrix dimensions — including sizes that are not multiples of any particular power of two, and degenerate cases like 1-by-1
- Must be a genuine SIMD-optimized implementation, not a wrapper around the naive function (examine the build flags in `CMakeLists.txt` for what the target platform supports)
- Must handle the full range of test cases in the test harness, including large matrices (1000x1000)

Build: `cd /app && cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j`

Test: `/app/build/test_runner`