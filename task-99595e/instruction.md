A bfloat16 floating-point arithmetic library is provided at `/app/bf16_arith.py`. A pristine copy is also available at `/opt/task/bf16_arith.py`. The library implements addition, subtraction, multiplication, and comparison operations using pure integer arithmetic, with support for all 5 IEEE 754 rounding modes (`RN_EVEN`, `RN_AWAY`, `RD`, `RU`, `RZ`) and special values (NaN, infinity, denormals, signed zeros).

The implementation contains several bugs related to IEEE 754 edge cases. Fix all bugs in `/app/bf16_arith.py` so that the test suite passes.

Key areas where IEEE 754 compliance is tested:

- **Sign-of-zero rules**: The sign of a zero result depends on the rounding mode. In particular, `x - x` produces `+0` in all rounding modes except Round-Downward (RD), where it produces `-0`.
- **Rounding mode overflow boundaries**: Not all rounding modes can produce both `+inf` and `-inf` from overflow. Round-toward-Zero can never produce infinity from overflow; it clamps to the maximum finite value.
- **Invalid operations**: Certain operand combinations (e.g., `0 * inf`, `inf + (-inf)`) are IEEE 754 invalid operations that must return quiet NaN.
- **Gradual underflow**: When subtraction of close values near the minimum normal number produces a result smaller than the minimum normal, the result must be a denormal (subnormal) number, not zero.
- **Unordered comparisons**: Any comparison involving NaN (except `!=`) must return False.
- **Round-to-nearest-even tie-breaking**: When the result is exactly midway between two representable values, it must round to the value with an even least-significant bit in the significand.

The bfloat16 format: 1 sign bit, 8 exponent bits (bias=127), 7 significand bits, precision p=8.