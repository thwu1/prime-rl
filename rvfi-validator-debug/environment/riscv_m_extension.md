# RISC-V M-Extension (RV32M) Specification

The M standard extension adds integer multiply and divide instructions.

All M-extension instructions use the **R-type format** with `opcode=0110011` and `funct7=0000001`.

```
 31      25 24    20 19    15 14  12 11     7 6      0
| 0000001  | rs2    | rs1    | f3  | rd     | 0110011|
  funct7                       funct3          OP
```

## Multiply Instructions

| funct3 | Instruction | Semantics |
|--------|-------------|-----------|
| 000 | MUL | `rd = (rs1 * rs2)[31:0]` — lower 32 bits of product |
| 001 | MULH | `rd = (signed(rs1) * signed(rs2))[63:32]` — upper 32 of signed×signed |
| 010 | MULHSU | `rd = (signed(rs1) * unsigned(rs2))[63:32]` — upper 32 of signed×unsigned |
| 011 | MULHU | `rd = (unsigned(rs1) * unsigned(rs2))[63:32]` — upper 32 of unsigned×unsigned |

### Key properties

- **MUL** gives the same result regardless of signed/unsigned treatment (lower bits are identical).
- **MULH** + **MUL** together yield the full 64-bit signed product.
- **MULHU** + **MUL** together yield the full 64-bit unsigned product.
- **MULHSU** is the most subtle variant: `rs1` is sign-extended to 64 bits while `rs2` is zero-extended. This is required for efficient multi-word signed multiplication where one factor is unsigned.

## Division Instructions

| funct3 | Instruction | Semantics |
|--------|-------------|-----------|
| 100 | DIV | `rd = signed(rs1) / signed(rs2)` — signed division, truncated toward zero |
| 101 | DIVU | `rd = unsigned(rs1) / unsigned(rs2)` — unsigned division |
| 110 | REM | `rd = signed(rs1) % signed(rs2)` — signed remainder (sign of dividend) |
| 111 | REMU | `rd = unsigned(rs1) % unsigned(rs2)` — unsigned remainder |

### Special cases (no traps)

Division by zero and signed overflow are **defined behavior** — they do **not** cause traps.

| Condition | DIV result | DIVU result | REM result | REMU result |
|-----------|-----------|-------------|-----------|-------------|
| Divisor is 0 | `0xFFFFFFFF` (−1) | `0xFFFFFFFF` (2³²−1) | `rs1` (dividend) | `rs1` (dividend) |
| Overflow: `rs1 = −2³¹`, `rs2 = −1` | `0x80000000` (−2³¹) | N/A | `0` | N/A |

### Division rounding

Signed division truncates **toward zero** (not toward negative infinity). The remainder satisfies: `dividend = quotient × divisor + remainder`.

Examples:
- `−13 / 5 = −2` (not −3), `−13 % 5 = −3` (not 2)
- `13 / −5 = −2`, `13 % −5 = 3`

## RVFI Trace Requirements

M-extension instructions follow the standard R-type RVFI protocol:
- `rd_addr` and `rd_wdata` reflect the computed result
- `rs1_addr`/`rs1_rdata` and `rs2_addr`/`rs2_rdata` reflect source operands
- `pc_wdata = pc_rdata + 4` (always sequential)
- No memory access (`mem_rmask = 0`, `mem_wmask = 0`)
- `rd_wdata` must be `0` when `rd_addr` is `x0`
