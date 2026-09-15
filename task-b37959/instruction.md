Given matrix chain specifications in `/app/problem/chains.json`, determine the minimum-FLOP evaluation cost for each chain and produce the corresponding BLAS kernel execution plan. Consult `/app/problem/blas_reference.txt` for available BLAS kernels, cost model, and structural property semantics.

Write to:
- `/app/results.json` — JSON mapping chain name to minimum FLOP cost (integer)
- `/app/kernel_plan.json` — JSON mapping chain name to ordered list of BLAS routine names (`"dgemm"`, `"dsymm"`, `"dtrmm"`, `"ddiagmm"`)

Additionally, write `/app/blas_eval.c` implementing the CBLAS test chains specified in `/app/problem/blas_test_spec.json`. Compile with: `gcc -o /app/blas_eval /app/blas_eval.c -lopenblas -lm`. Output one line per chain as `chain_name=%.10f` (Frobenius norm), ending with `BLAS_EVAL_COMPLETE`. Note: `cblas_dtrmm` overwrites its B argument in-place. Use `CblasRowMajor`, `CblasUpper` for symmetric storage, `CblasLower`/`CblasNonUnit` for lower-triangular.