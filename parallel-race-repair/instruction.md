Four sequential C++ programs in `/app/src/` implement computational algorithms. Each has an empty parallel function stub marked `/* ---- IMPLEMENT THIS FUNCTION ---- */`. A reference sequential implementation is included in each file.

`/app/candidates.md` presents three candidate parallelization strategies (A, B, C) for each program. Some candidates are correct; others contain subtle concurrency bugs — data races, out-of-bounds accesses, or incorrect OpenMP semantics — that would cause wrong results or undefined behavior under multi-threaded execution.

Your deliverables:

1. **Evaluate** every candidate strategy for correctness and race-freedom. Write your verdicts to `/app/verdicts.json` in this exact schema:
   ```
   {
     "<program>": {
       "<A|B|C>": {"correct": <bool>, "flaw": "<explanation or 'none'>"}
     }
   }
   ```
   All four programs (`histogram`, `jacobi`, `knn_search`, `lu_factor`) and all three candidates per program must be present. For incorrect candidates, `flaw` must explain the specific bug.

2. **Implement** the empty `*_parallel` function in each source file so that all four programs satisfy:
   - Compile cleanly with `g++ -O2 -fopenmp -std=c++17`
   - Compile cleanly with `clang++ -O1 -fopenmp -fsanitize=thread -std=c++17 -DSMALL_SIZE`
   - Report `RESULT: PASS` when run with `OMP_NUM_THREADS=4`
   - Report no data races under ThreadSanitizer (`TSAN_OPTIONS="exitcode=66 halt_on_error=1 suppressions=/app/tsan.supp"`)

Programs:
- `/app/src/histogram.cpp` — parallel histogram computation
- `/app/src/jacobi.cpp` — parallel 2D Jacobi iterative stencil solver
- `/app/src/knn_search.cpp` — parallel k-nearest neighbors search
- `/app/src/lu_factor.cpp` — parallel LU decomposition with partial pivoting

Build system: `/app/Makefile` — `make all` (normal), `make tsan` (ThreadSanitizer), `make clean`.
TSan suppression file: `/app/tsan.supp` (filters known libomp false positives).