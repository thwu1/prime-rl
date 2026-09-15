Implement an IEEE 754-compliant FP8 E4M3 floating-point arithmetic system with three interoperating components:

1. **C shared library** (`/app/libfp8.so`): Implement all functions declared in `/app/fp8_api.h`. Build using the Makefile at `/app/Makefile` (`make -C /app`). The library must compile as a position-independent shared object and link with `-lm`.

2. **Python ctypes wrapper** (`/app/fp8_ctypes.py`): Load `/app/libfp8.so` via ctypes and expose all API functions as module-level callables with correct argument and return type annotations.

3. **Verilog FP8 adder** (`/app/fp8_adder.v`): Implement a combinational `fp8_adder` module matching the port interface in the provided stub. Must handle all IEEE 754 special cases (NaN, infinity, signed zeros, subnormals) and all 5 rounding modes. Verified via Icarus Verilog (`iverilog` + `vvp`) simulation against `/tests/fp8_adder_tb.v`.

The FP8 E4M3 format specification is at `/app/spec.md`. Stubs with required signatures are at `/app/fp8.c`, `/app/fp8_ctypes.py`, and `/app/fp8_adder.v`. The C library must handle encoding/decoding, addition, multiplication, fused multiply-add (single-rounding semantics), classification, and comparison. Tests verify all three components end-to-end.