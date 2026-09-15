Five computational kernels in `/app/src/` have been parallelized with OpenMP but produce incorrect or non-deterministic results when executed with multiple threads.

Fix all five programs so that they:
- Compile with `gcc -fopenmp -O2 -lm`
- Produce correct, deterministic output regardless of thread count
- Retain meaningful OpenMP parallelism (removing all parallel directives is not acceptable)

The programs are:
- `/app/src/histogram.c`
- `/app/src/jacobi.c`
- `/app/src/nbody.c`
- `/app/src/convolve.c`
- `/app/src/prefix_scan.c`

A `/app/Makefile` builds all programs. Both `gcc` and `clang` (with `libomp-dev`) are available.