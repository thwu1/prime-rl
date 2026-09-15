`/app/target.c` contains 6 C functions. `/app/schema.json` defines a set of questions about how GCC compiles each function's x86-64 assembly at specified optimization levels.

Produce three deliverables:

1. `/app/report.json` — answers to every field defined in `/app/schema.json`, derived by compiling `target.c` and examining the generated assembly for each function. Boolean fields require inspecting the assembly at the indicated optimization level. String-valued fields require explaining the underlying language or hardware semantics responsible for the observed compiler behavior.

2. `/app/fixed_accumulate.c` — the `accumulate` function in `target.c` has a performance deficiency visible in its `-O2` assembly that forces the compiler to emit suboptimal code. Identify the root cause and write a corrected implementation that eliminates it. The function must keep the exact signature `void accumulate(int *total, const int *data, int n)` and produce identical results for all inputs.

3. `/app/vectorized_sum.c` — the `sum_floats` function in `target.c` cannot be auto-vectorized by GCC at `-O3 -mavx2` for a reason you must determine. Design and implement a new version of this function that contains packed SIMD float additions in its compiled assembly when built with `-O3 -mavx2` alone (no `-ffast-math`). The function must keep the signature `float sum_floats(const float *arr, int n)` and produce correct results for all valid inputs, including n=0 and lengths that are not multiples of the SIMD register width.