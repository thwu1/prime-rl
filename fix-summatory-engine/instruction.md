The CMake project at `/app/` implements sub-linear (O(N^{2/3})) algorithms for number-theoretic summatory functions using a divisor-vector indexing scheme over floor(N/k) values: prime counting pi(N), Mertens function M(N), Euler totient sum, squarefree count Q(N), and Liouville summatory L(N).

The source `/app/engine.cpp` has algorithmic bugs in multiple functions and `liouville_sum` is unimplemented (stub returning -999). The existing `CMakeLists.txt` only builds a standalone executable.

Your goal is to deliver a working shared library with Python bindings and a performance evaluation:

- `/app/build/libntsum.so` — a shared library exporting C-callable functions `ntsum_prime_count`, `ntsum_mertens`, `ntsum_totient_sum`, `ntsum_squarefree_count`, `ntsum_liouville_sum` (each `long long` to `long long`). Guard the exports in `engine.cpp` with a `BUILD_SHARED_LIB` preprocessor define and add a corresponding shared library target to `CMakeLists.txt`.

- `/app/ntsum_bindings.py` — a Python `ctypes` wrapper that loads the shared library from `/app/build/libntsum.so` and exposes all five functions as module-level callables with proper `argtypes`/`restype` declarations.

- `/app/evaluation.json` — performance comparison of the library built at `-O0`, `-O2`, and `-O3` optimization levels. For each level, time `ntsum_prime_count(10000000)` and `ntsum_mertens(10000000)` via the shared library. Required JSON keys: `"O0"`, `"O2"`, `"O3"` (each mapping to `{"prime_count_ms": <float>, "mertens_ms": <float>}`), `"recommended"` (the optimization level with lowest total time), and `"speedup_vs_O0"` (ratio of O0 total time to recommended total time).

Reference correct values — N=10: pi=4, M=-1, phi_sum=32, Q=7, L=0. N=10000: pi=1229, M=-23, phi_sum=30397486, Q=6083, L=-94. N=1000000: pi=78498, M=212, phi_sum=303963552392, Q=607926, L=-530.