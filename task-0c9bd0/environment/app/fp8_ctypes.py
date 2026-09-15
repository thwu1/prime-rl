"""Python ctypes wrapper for libfp8.so shared library.

Load the FP8 shared library and expose its functions with proper
ctypes type annotations for use by test harnesses.

Required module-level callables (matching fp8_api.h):
  fp8_to_float(raw: uint8) -> double
  fp8_from_float(value: double, rounding: int) -> uint8
  fp8_add(a: uint8, b: uint8, rounding: int) -> uint8
  fp8_mul(a: uint8, b: uint8, rounding: int) -> uint8
  fp8_fma(a: uint8, b: uint8, c: uint8, rounding: int) -> uint8
  fp8_classify(raw: uint8) -> int
  fp8_compare(a: uint8, b: uint8) -> int

Rounding mode constants: RNE=0, RNA=1, RU=2, RD=3, RZ=4
Classification constants: CLASS_NORMAL=0, CLASS_SUBNORMAL=1,
  CLASS_ZERO=2, CLASS_INFINITY=3, CLASS_NAN=4
Compare: CMP_UNORDERED=2
"""

# TODO: Load /app/libfp8.so via ctypes.CDLL, set argtypes and restype
# for each function, and expose them as module-level names.

raise NotImplementedError("Load libfp8.so and expose the API")
