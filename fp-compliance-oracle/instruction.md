`/app/fp_oracle` is an IEEE 754 binary64 compliance oracle built from `/app/` via `make -C /app clean all`. It reads one command per line from stdin and writes results to stdout.

**Commands:**

`DECODE <hex64>` — Output: `<class> <sign> <unbiased_exp> <payload>`. Classes: POS_ZERO, NEG_ZERO, POS_SUBNORMAL, NEG_SUBNORMAL, POS_NORMAL, NEG_NORMAL, POS_INFINITY, NEG_INFINITY, QUIET_NAN, SIGNALING_NAN. Classification, sign, unbiased exponent, and NaN payload must conform to the IEEE 754 binary64 specification.

`NEXTAFTER <hex_x> <hex_y>` — Compute nextafter(x,y) using only integer/bit operations on the raw binary64 representation; do not call the C library `nextafter` or `fpclassify`. Output: `<result_hex> <exception_flags>` where flags is a decimal integer bitfield: 1=invalid, 2=divbyzero, 4=overflow, 8=underflow, 16=inexact. All IEEE 754 edge cases must be handled correctly for both positive and negative values, including proper exception flag reporting.

`TOTALORDER <hex_a> <hex_b>` — IEEE 754-2008 totalOrder predicate using only bit manipulation; do not call the C library `totalorder`. Output: `0` or `1`.

`COUNTEREXAMPLE <id>` — Return a hex64 bit pattern proving the algebraic transformation is not universally valid under IEEE 754. Output: `<hex64>`. IDs: 0: x−x→0, 1: x+0→x, 2: 0·x→0, 3: x/x→1, 4: x−y vs −(y−x) where y=1.0, 5: −x vs 0−x. Each returned value must demonstrably invalidate its transformation when the operation is performed.

`ROUNDING <hex_a> <hex_b> <op>` — Evaluate (a op b) under all four IEEE 754 rounding modes (op: 0=add, 1=sub, 2=mul, 3=div). Output four space-separated hex64 values: `<nearest> <downward> <upward> <towardzero>`.

The implementation has defects. Fix the functions in `/app/fp_oracle.c` to produce fully IEEE 754-compliant output for all commands. `/app/main.c` and `/app/fp_oracle.h` are correct and must not be modified.
