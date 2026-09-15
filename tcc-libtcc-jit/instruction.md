The file `/app/series_jit.c` is a C program that dynamically compiles and evaluates mathematical series using TCC's libtcc library. It was written against TCC 0.9.27 (stable release) and has multiple issues that prevent it from building and running correctly with the TCC source tree at `/app/tcc-src/` (current development branch, where the libtcc API has changed).

The series definitions are in `/app/input.json`, where each entry contains `name` (string), `term_body` (body of a C function `double term_k(int k)`), and `num_terms` (integer count of terms to sum).

Build TCC from the provided source tree, diagnose all issues in the evaluator, and fix them so that the program satisfies the following requirements:

- **Executable**: Produce a working binary at `/app/series_jit` with execute permission.
- **Dynamic input**: The program must parse and read series definitions from `/app/input.json` at runtime. If the file is modified (e.g., a new series entry is appended) and the program is re-run, the output must reflect the updated contents.
- **JIT compilation**: Use libtcc's `tcc_compile_string` and `tcc_get_symbol` API to dynamically compile each series' C function body at runtime. The user-written C source file(s) under `/app/` (outside the TCC source/install trees) must contain calls to both of these functions. Do not statically embed the mathematical logic.
- **Library support**: Some series function bodies call `pow()` from the math library, which must be correctly resolved during JIT compilation and relocation.
- **Output format**: Write results to `/app/output.txt`, one line per series in the format `<name> <value>` where `<value>` uses `%.17g` printf formatting.
- **Numerical correctness**: Each partial sum must converge to its expected mathematical constant within the tolerance implied by the series' convergence rate and term count (e.g., a 10M-term alternating series should be accurate to ~1e-6; a 25-term factorial series should reach machine precision).
- **Determinism**: Re-running the executable must produce byte-identical output each time.