# Hardware Arithmetic Verification & Fixed-Point Mandelbrot

## Overview

Three SystemVerilog arithmetic modules from the Project F hardware library are
provided in `/app/verilog/`. The source code of each module defines its exact
computational behavior, including initialization, iteration, edge cases, and
output extraction. No separate algorithm documentation is provided — the
Verilog is the specification.

The environment includes Icarus Verilog (`iverilog`, `vvp`) for SystemVerilog
compilation and simulation.

## Module Summary

### `divu_int.sv` — Unsigned Integer Division with Remainder

- **Parameters**: `WIDTH` (operand bit width, default 5)
- **Inputs**: `clk`, `rst`, `start`, `a[WIDTH-1:0]` (dividend), `b[WIDTH-1:0]` (divisor)
- **Outputs**: `busy`, `done` (1-cycle pulse), `valid`, `dbz`, `val[WIDTH-1:0]` (quotient), `rem[WIDTH-1:0]` (remainder)
- **Functional**: Computes unsigned integer division. Sets `dbz=1` on divide-by-zero.

### `sqrt_int.sv` — Integer Square Root

- **Parameters**: `WIDTH` (radicand bit width, must be even, default 8)
- **Inputs**: `clk`, `start`, `rad[WIDTH-1:0]` (radicand)
- **Outputs**: `busy`, `valid`, `root[WIDTH-1:0]`, `rem[WIDTH-1:0]`
- **Functional**: Computes `root = floor(sqrt(rad))` and `rem = rad - root*root`.

### `divu.sv` — Unsigned Fixed-Point Division

- **Parameters**: `WIDTH` (total bit width, default 8), `FBITS` (fractional bits, default 4)
- **Inputs**: `clk`, `rst`, `start`, `a[WIDTH-1:0]`, `b[WIDTH-1:0]`
- **Outputs**: `busy`, `done` (1-cycle pulse), `valid`, `dbz`, `ovf`, `val[WIDTH-1:0]` (quotient)
- **Functional**: Computes unsigned fixed-point quotient in Q(WIDTH-FBITS).FBITS format. Sets `dbz=1` on divide-by-zero, `ovf=1` on overflow.

## Test Vectors

### Integer Division (`divu_int`, WIDTH=32)

Compute for these (dividend, divisor) pairs:
1. (100, 7)
2. (255, 16)
3. (1, 1)
4. (0, 42)
5. (12345678, 9999)
6. (999999999, 7)
7. (4294967295, 65536)
8. (100, 0)

### Integer Square Root (`sqrt_int`, WIDTH=32)

Compute for these radicands:
1. 0
2. 1
3. 25
4. 144
5. 200
6. 1000000
7. 50000000
8. 4294967295

### Fixed-Point Division (`divu`, WIDTH=25, FBITS=21)

Compute for these real-valued pairs, converting to unsigned fixed-point as
`fp = int(real_value * 2**21)`:
1. (7.0, 2.0)
2. (10.0, 4.0)
3. (15.0, 2.0)
4. (1.0, 3.0)
5. (1.0, 7.0)

### Mandelbrot Grid (Q4.21 signed fixed-point, max_iter=255)

Compute Mandelbrot set escape iterations using Q4.21 signed fixed-point arithmetic:
- 25-bit two's complement representation
- 4 integer bits (including sign), 21 fractional bits

The Mandelbrot set is defined by the complex iteration z_{n+1} = z_n^2 + c
starting from z_0 = 0, where z and c are complex numbers. A point c escapes
at iteration n when the 25-bit signed interpretation of |z_n|^2
(i.e., Re(z_n)^2 + Im(z_n)^2) exceeds the Q4.21 representation of 4.0.
Return max_iter (255) if no escape occurs.

All fixed-point operations (multiply, add, subtract) must use standard
25-bit two's complement arithmetic with truncation toward negative infinity.

Grid coordinates (outer loop over cx, inner loop over cy):
- Real axis (cx): -2.0, -1.75, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5
- Imaginary axis (cy): -1.25, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.25

Convert to Q4.21: `fp = int(real_value * 2**21)`. For negative values, use
standard Python signed integer; mask to 25 bits (`& 0x1FFFFFF`) for internal
computation only.

## Required Output

Generate `/app/results.json` with this exact structure:

```json
{
  "divu_int": {
    "width": 32,
    "results": [
      {"a": <int>, "b": <int>, "quotient": <int>, "remainder": <int>, "dbz": <bool>}
    ]
  },
  "sqrt_int": {
    "width": 32,
    "results": [
      {"radicand": <int>, "root": <int>, "remainder": <int>}
    ]
  },
  "divu_fp": {
    "width": 25,
    "fbits": 21,
    "results": [
      {"a": <int>, "b": <int>, "quotient": <int>, "dbz": <bool>, "ovf": <bool>}
    ]
  },
  "mandelbrot": {
    "width": 25,
    "fbits": 21,
    "max_iter": 255,
    "grid": [
      {"cx": <int>, "cy": <int>, "iterations": <int>}
    ]
  }
}
```

All integer values are raw bit patterns. For `divu_fp`, `a` and `b` are the
unsigned fixed-point representations. For the Mandelbrot grid, `cx` and `cy`
are the signed Python integers (before masking) from `int(real * 2**21)`.
