Implement a correctly-rounded `exp2m1f` function (`2^x - 1` for IEEE 754 binary32 float) at `/app/exp2m1f.c`.

The function `float cr_exp2m1f(float x)` must return the correctly-rounded (round-to-nearest-even) result of `2^x - 1` for every possible 32-bit float input. The header `/app/exp2m1f.h` and `/app/Makefile` are already in place.

**Constraints:**
- The Makefile does not link against libm (`-lm`). Your implementation must not call any standard math library functions (`exp`, `exp2`, `expm1`, `log`, `sqrt`, `pow`, `ldexp`, etc.). You may use basic arithmetic operators, integer/bit manipulation, and GCC/Clang compiler builtins (`__builtin_fma`, `__builtin_fmaf`, `__builtin_expect`).
- Must handle all IEEE 754 special cases: `cr_exp2m1f(+0) = +0`, `cr_exp2m1f(-0) = -0`, `cr_exp2m1f(+Inf) = +Inf`, `cr_exp2m1f(-Inf) = -1`, `cr_exp2m1f(NaN) = NaN`.
- Must handle overflow correctly (for large positive `x`, result is `+Inf`).
- Must avoid catastrophic cancellation for inputs near zero (where `2^x ≈ 1`).

Tests compile `/app/exp2m1f.c` as a shared library (without libm) and verify outputs against a high-precision (200-bit) MPFR/mpmath reference across special values, near-zero inputs, overflow/underflow boundaries, table-boundary values, and a pseudo-random sample of ~1000 inputs spanning the full float32 range.