The directory `/app/` contains a skeleton C library for computing three number-theoretic summatory functions. The API is defined in `/app/dirichlet.h` and accessed through `/app/compute.py` via ctypes (loading `/app/libdirichlet.so`, built by running `make` in `/app/`).

Mathematical definitions of the target functions are in `/app/spec.txt`. A reference implementation that works for small inputs is at `/app/naive.py`.

Implement `/app/dirichlet.c` so that the three exported functions — `mertens(n)`, `totient_sum(n)`, `liouville_sum(n)` — produce correct values for any n up to 10^10, with total computation time under 120 seconds on a single core and memory usage under 2 GB. The `totient_sum` result must be reduced modulo 998244353; the other two return exact integers.