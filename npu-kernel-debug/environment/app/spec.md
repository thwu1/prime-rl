# MiniNPU ISA Specification v1.0

## Overview

MiniNPU is a minimal neural processing unit designed for ML inference workloads.
It features a vector processing unit with 16-wide SIMD lanes and a scalar unit
for control flow and auxiliary computations.

## Architecture

### Memory

- **Scratchpad Memory**: 4096 words of 32-bit IEEE 754 floating-point values
- **Addressing**: Word-addressed (address 0 = first word, address 1 = second word, etc.)
- **Access**: All loads and stores operate on the scratchpad

### Registers

#### Vector Registers

- 16 vector registers: `v0` through `v15`
- Each register holds VLEN = 16 elements of float32
- All elements initialized to 0.0 at reset

#### Scalar Registers

- 16 scalar registers: `s0` through `s15`
- Each holds a single float32 value
- **`s0` is hardwired to 0.0**: reads always return 0.0; writes are ignored
- `s1` through `s15` initialized to 0.0 at reset

## Instruction Set

### Notation

- `vd`, `vs`, `vs1`, `vs2` : vector register operands
- `sd`, `ss`, `ss1`, `ss2` : scalar register operands
- `addr` : immediate word address (unsigned integer)
- `#imm` : immediate floating-point constant
- `label` : branch target (defined as `.label_name:` on a separate line)

### Memory Instructions

| Instruction | Syntax | Operation |
|---|---|---|
| VLD | `VLD vd, addr` | Load 16 consecutive words from memory[addr .. addr+15] into vd |
| VST | `VST vs, addr` | Store 16 words from vs into memory[addr .. addr+15] |
| SLD | `SLD sd, addr` | Load memory[addr] into sd |
| SST | `SST ss, addr` | Store ss into memory[addr] |

### Vector Arithmetic

| Instruction | Syntax | Operation |
|---|---|---|
| VADD | `VADD vd, vs1, vs2` | vd[i] = vs1[i] + vs2[i] for i in 0..15 |
| VSUB | `VSUB vd, vs1, vs2` | vd[i] = vs1[i] - vs2[i] for i in 0..15 |
| VMUL | `VMUL vd, vs1, vs2` | vd[i] = vs1[i] * vs2[i] for i in 0..15 |
| VDIV | `VDIV vd, vs1, vs2` | vd[i] = vs1[i] / vs2[i] for i in 0..15 |
| VMAX | `VMAX vd, vs1, vs2` | vd[i] = max(vs1[i], vs2[i]) for i in 0..15 |
| VMAC | `VMAC vd, vs1, vs2` | vd[i] = vd[i] + vs1[i] * vs2[i] for i in 0..15 |
| VSQRT | `VSQRT vd, vs` | vd[i] = sqrt(vs[i]) for i in 0..15 |
| VEXP | `VEXP vd, vs` | vd[i] = exp(vs[i]) for i in 0..15 |
| VRECIP | `VRECIP vd, vs` | vd[i] = 1.0 / vs[i] for i in 0..15 |
| VNEG | `VNEG vd, vs` | vd[i] = -vs[i] for i in 0..15 |

### Vector-Scalar Instructions

| Instruction | Syntax | Operation |
|---|---|---|
| VBCAST | `VBCAST vd, ss` | vd[i] = ss for all i in 0..15 |
| VREDSUM | `VREDSUM sd, vs` | sd = sum of vs[i] for i in 0..15 |
| VREDMAX | `VREDMAX sd, vs` | sd = max of vs[i] for i in 0..15 |

### Scalar Arithmetic

| Instruction | Syntax | Operation |
|---|---|---|
| SMOV | `SMOV sd, #imm` | sd = imm (float literal) |
| SADD | `SADD sd, ss1, ss2` | sd = ss1 + ss2 |
| SSUB | `SSUB sd, ss1, ss2` | sd = ss1 - ss2 |
| SMUL | `SMUL sd, ss1, ss2` | sd = ss1 * ss2 |
| SDIV | `SDIV sd, ss1, ss2` | sd = ss1 / ss2 |
| SSQRT | `SSQRT sd, ss` | sd = sqrt(ss) |
| SMAX | `SMAX sd, ss1, ss2` | sd = max(ss1, ss2) |

### Control Flow

| Instruction | Syntax | Operation |
|---|---|---|
| BNZ | `BNZ ss, label` | If ss != 0.0, jump to label; else next instruction |
| DEC | `DEC sd, ss` | sd = ss - 1.0 |
| HALT | `HALT` | Stop execution |

### Labels

Labels are defined on their own line with a leading dot and trailing colon:

```
.loop_start:
    VLD v0, 0
    DEC s1, s1
    BNZ s1, loop_start
```

Note: BNZ references labels **without** the leading dot.

### Comments

Lines beginning with `#` are comments and ignored by the assembler.

## Programming Notes

1. **VMAC accumulates** into the destination register. Initialize the destination
   to zero (e.g., via `VBCAST vd, s0`) before starting a reduction loop.

2. For **numerically stable softmax**, subtract the maximum value before
   computing exponentials to avoid overflow.

3. Memory addresses are word-aligned. VLD/VST access 16 consecutive words
   starting at the given address. Ensure addresses do not exceed scratchpad
   bounds (0-4095).

4. The **DEC/BNZ** pair provides simple counted loops:
   ```
   SMOV s1, #4.0
   .loop:
       # loop body here
       DEC s1, s1
       BNZ s1, loop
   ```
   This executes the body 4 times (s1 counts down: 4, 3, 2, 1; loop exits
   when DEC produces 0).
