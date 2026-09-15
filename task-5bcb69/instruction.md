`/app/cbrtf.c` contains a skeleton for `cr_cbrtf(float x)` — a cube root function for IEEE 754 binary32 (single-precision float). The skeleton handles special cases (±0, ±Inf, NaN) but the core algorithm is unimplemented.

Implement the core algorithm so that `cr_cbrtf(x)` returns the correctly-rounded (round-to-nearest-even) cube root for **every** representable binary32 value, including subnormals. Your result must match `mpfr_cbrt` with `MPFR_RNDN` at the bit level for all inputs.

A spot-check tool tests a sample of normal-range inputs against MPFR:

    cd /app && make clean && make spot_check && ./spot_check

The spot-check covers special values and an exhaustive sweep of the binade [1.0, 2.0), but omits subnormal inputs. Your implementation must handle subnormals correctly — write your own MPFR-based test programs to verify those ranges.

Available: `gcc`, `make`, `gdb`, `binutils`, `libmpfr-dev`, `libgmp-dev`.