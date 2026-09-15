# Earthrise Instruction Set Architecture

## Overview

Earthrise is a 16-bit 2D graphics processor. It steps through a list of instructions,
writing resulting pixels to a framebuffer. All instructions are 16 bits wide.

**Canvas**: 160 x 120 pixels, 8-bit indexed color (0-255). Pixels outside the canvas
are silently clipped (not drawn).

**Framebuffer**: 19200 bytes, one byte per pixel, row-major order (row 0 first),
initialized to zero (color index 0 = background).

## Registers

### Coordinate Registers (signed 12-bit, range -2048 to +2047)

| Index | Name | Description                    |
|-------|------|--------------------------------|
| 0     | x0   | X coordinate of point 0        |
| 1     | y0   | Y coordinate of point 0        |
| 2     | x1   | X coordinate of point 1 / radius for circle |
| 3     | y1   | Y coordinate of point 1        |
| 4     | x2   | X coordinate of point 2        |
| 5     | y2   | Y coordinate of point 2        |
| 6     | x3   | X coordinate of point 3        |
| 7     | y3   | Y coordinate of point 3        |

### Color Registers (unsigned 8-bit, range 0-255)

| Sub-index | Name | Description           |
|-----------|------|-----------------------|
| 0         | lca  | Line color A          |
| 1         | lcb  | Line color B          |
| 2         | fca  | Fill color A          |
| 3         | fcb  | Fill color B          |

All registers are initialized to 0 and persist across instructions.

## Instruction Encoding

### Register Load — Coordinate (bits[15:12] = 0x0 .. 0x7)

```
[RRRR][VVVVVVVVVVVV]
15:12     11:0
```

- `R` = register index (0-7, maps to x0, y0, x1, y1, x2, y2, x3, y3)
- `V` = 12-bit value, sign-extended to the register width

### Register Load — Color (bits[15:12] = 0xC, bits[11:8] = 0x0..0x3)

```
[1100][SSSS][VVVVVVVV]
15:12  11:8    7:0
```

- `S` = color sub-index (0=lca, 1=lcb, 2=fca, 3=fcb)
- `V` = 8-bit color value

### Stop (bits[15:12] = 0xC, bits[11:8] = 0xE)

```
[1100][1110][00000000]  =  0xCE00
```

Halts execution.

### Draw Command (bits[15:12] = 0xD)

```
[1101][SSSS][FFFFFFFF]
15:12  11:8    7:0
```

- `S` = shape code:
  - 0 = pixel
  - 1 = line
  - 2 = triangle
  - 3 = rectangle
  - 4 = circle
- `F` = flags:
  - bit 0: fill mode (0 = outline, 1 = filled). Affects drawing behavior for
    rectangle (shape 3) and triangle (shape 2). For other shapes, only affects
    color selection.
  - bit 1: color B select (0 = color A, 1 = color B)

**Color selection**:
- If fill bit is 0: use `lca` (bit1=0) or `lcb` (bit1=1)
- If fill bit is 1: use `fca` (bit1=0) or `fcb` (bit1=1)

**Shape register usage**:
- **Pixel** (shape 0): draws at (x0, y0)
- **Line** (shape 1): draws from (x0, y0) to (x1, y1)
- **Triangle** (shape 2): uses (x0,y0), (x1,y1), (x2,y2)
  - outline: draws 3 edges as lines
  - filled: rasterizes interior using the hardware triangle fill module
- **Rectangle** (shape 3): uses corners (x0, y0) and (x1, y1)
  - outline: draws 4 edges as lines
  - filled: fills all pixels in the rectangular region
- **Circle** (shape 4): center at (x0, y0), radius = value of x1 register

## Drawing Behavior

The exact pixel-level behavior of each drawing primitive is defined by the
corresponding SystemVerilog hardware module in `/app/hardware/`. The emulator
must replicate these modules precisely.

Available hardware modules:
- `draw_line.sv` — line rasterization
- `draw_circle.sv` — circle rasterization
- `draw_rectangle.sv` — rectangle outline (composed of four line draws)
- `draw_triangle_fill.sv` — filled triangle rasterization via edge function evaluation

**Critical**: these modules use specific algorithmic variants with particular choices
about initialization, traversal order, error term handling, state machine structure,
and non-blocking assignment semantics. Standard textbook implementations of common
drawing algorithms will produce different pixel patterns. Read the modules carefully
and understand their exact behavior — including how SystemVerilog non-blocking
assignments (`<=`) affect state update ordering within each clock cycle.

## Hex File Format

One instruction per line, as a 4-digit uppercase or lowercase hexadecimal value.
Lines beginning with `#` are comments. Blank lines are ignored.

Example:
```
C001    # lca 1
000A    # x0 10
100A    # y0 10
D000    # draw pixel ca
CE00    # stop
```
