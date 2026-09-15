`/app/libfpmath.so` is a compiled C shared library implementing six single-precision floating-point math functions. The function prototypes are in `/app/fpmath.h` and the audit parameters are in `/app/audit_config.json`. The C source code is not available — only the compiled binary.

Some of these implementations contain numerical bugs that violate IEEE 754 correctness expectations (catastrophic cancellation, intermediate overflow, special-value mishandling). Others are numerically sound. Your job is to determine which functions are numerically sound and which are not, prove it with quantitative evidence, and provide corrected implementations.

Produce:

1. `/app/audit_report.json` — For each function, classify it as `"stable"` (≤ 4 ULP error across its domain) or `"unstable"`. For unstable functions, report the `bug_type`, the `max_ulp_error` observed, and a `worst_case_input` that triggers it. Use arbitrary-precision arithmetic (≥ 50 decimal digits) as ground truth — float64 alone is insufficient for rigorous ULP analysis at the float32 boundary. The report schema is specified in `/app/audit_config.json`.

2. `/app/libfpmath_fixed.so` — A corrected shared library exporting the same symbols with identical C signatures, where every function achieves ≤ 4 ULP error and correctly handles IEEE 754 special values (±0, ±Inf, NaN, subnormals).