Five C source files in `/app/src/` contain OpenMP-parallelized computational kernels. Each has data-race bugs that cause incorrect or non-deterministic results under concurrent execution:

- `/app/src/histogram.c` — parallel histogram binning
- `/app/src/jacobi2d.c` — 2D Jacobi stencil iteration
- `/app/src/nbody.c` — N-body gravitational simulation
- `/app/src/lu_factor.c` — in-place LU matrix factorization
- `/app/src/wavefront.c` — 2D dynamic-programming wavefront

Fix every data race across all five files. Each corrected kernel must:

1. Compile with `gcc -O2 -fopenmp`
2. Produce output matching a correct sequential reference implementation
3. Produce identical output across repeated concurrent runs with `OMP_NUM_THREADS=4`
4. Retain meaningful OpenMP parallelism (`#pragma omp` directives and `#include <omp.h>` must remain)

A `Makefile` is provided in `/app/`. `make` builds normal binaries into `/app/build/`; `make tsan` builds ThreadSanitizer-instrumented binaries for debugging.