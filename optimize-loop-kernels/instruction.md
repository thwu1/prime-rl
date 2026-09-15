A C++ program at `/app/` implements four computational kernels in `kernels.cpp`. Each kernel suffers from a distinct compiler optimization barrier that prevents efficient code generation. A support function used by one kernel is defined in `transform.cpp`. The program builds with `make` and runs correctness checks via `./benchmark`.

Use compiler optimization reports (GCC: `-fopt-info-vec-all`; Clang: `-Rpass-missed=loop-vectorize`) and `llvm-mca` to diagnose each kernel's optimization barrier. Apply source-level fixes to remove each barrier while preserving numerical correctness.

Produce the following artifacts:

- Modified source file(s) under `/app/` with optimization barriers resolved
- `/app/analysis.json` — a JSON object keyed by function name (`scale_array`, `column_sums`, `dot_product`, `apply_transform`), each containing:
  - `"bottleneck"`: one of `"pointer_aliasing"`, `"non_unit_stride"`, `"dependency_chain"`, `"function_call"`, `"register_spilling"`, `"branch_misprediction"`
  - `"explanation"`: description of the issue and the fix applied
- `/app/llvm_mca_analysis.txt` — saved output from `llvm-mca` analysis of at least one kernel's generated assembly

The modified program must compile via `make` and all four kernels must report PASS when `./benchmark` is run.