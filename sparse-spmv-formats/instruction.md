`/app/spmv_bench.py` implements sparse matrix-vector multiplication (SpMV) across three GPU storage formats — CSR, JDS (Jagged Diagonal Storage), and ELLPACK — along with GPU memory traffic estimation and warp-level workload simulation. The module contains multiple bugs that produce incorrect results for format conversions, SpMV computation, performance modeling, and file I/O.

Sparse matrix data is available in `/app/data/` (text-based CSR format; see `/app/data/FORMAT.txt` for the schema) and `/app/matrices/` (Matrix Market coordinate format).

Diagnose and fix all bugs in the module. One function is entirely unimplemented and must be written from scratch. Do not change any existing function signatures.