# VecTor-16 ISA Reference

## Architecture Overview

VecTor-16 is a custom vector processing unit designed for ML inference workloads.

**Registers:**
- **v0–v7**: 8 vector registers, each holding 16 float64 elements
- **s0–s15**: 16 scalar registers, each holding one float64 value
- **a0–a7**: 8 address registers, each holding one integer address

**Memory:**
- Flat address space, each address holds one float64 value
- Total memory: 65536 entries
- Initialized to 0.0

## Assembly Syntax

- One instruction per line
- Comments start with `#` (rest of line is ignored)
- Operands separated by commas and/or whitespace
- Opcodes are case-insensitive
- Register names are case-insensitive (e.g., `V0`, `v0`, `S3`, `s3`)

## Instruction Set

### Vector Arithmetic

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| VADD | `VADD vd, vs1, vs2` | vd[i] = vs1[i] + vs2[i] | 1 |
| VSUB | `VSUB vd, vs1, vs2` | vd[i] = vs1[i] - vs2[i] | 1 |
| VMUL | `VMUL vd, vs1, vs2` | vd[i] = vs1[i] * vs2[i] | 1 |
| VDIV | `VDIV vd, vs1, vs2` | vd[i] = vs1[i] / vs2[i] | 4 |
| VEXP | `VEXP vd, vs1` | vd[i] = exp(vs1[i]) | 8 |
| VSQRT | `VSQRT vd, vs1` | vd[i] = sqrt(max(0, vs1[i])) | 8 |
| VABS | `VABS vd, vs1` | vd[i] = \|vs1[i]\| | 1 |
| VNEG | `VNEG vd, vs1` | vd[i] = -vs1[i] | 1 |
| VMAX | `VMAX vd, vs1, vs2` | vd[i] = max(vs1[i], vs2[i]) | 1 |
| VMIN | `VMIN vd, vs1, vs2` | vd[i] = min(vs1[i], vs2[i]) | 1 |

**VEXP saturation:** exp(x) returns 0.0 for x < -88 and +inf for x > 88.

### Vector-Scalar

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| VADDS | `VADDS vd, vs1, ss` | vd[i] = vs1[i] + ss | 1 |
| VSUBS | `VSUBS vd, vs1, ss` | vd[i] = vs1[i] - ss | 1 |
| VMULS | `VMULS vd, vs1, ss` | vd[i] = vs1[i] * ss | 1 |
| VDIVS | `VDIVS vd, vs1, ss` | vd[i] = vs1[i] / ss | 4 |

### Reductions

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| VREDSUM | `VREDSUM sd, vs1` | sd = sum of all vs1[i] | 4 |
| VREDMAX | `VREDMAX sd, vs1` | sd = max of all vs1[i] | 4 |
| VREDMIN | `VREDMIN sd, vs1` | sd = min of all vs1[i] | 4 |

### Vector Memory

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| VLOAD | `VLOAD vd, abase, offset` | Load 16 floats from mem[abase + offset] | 2 |
| VSTORE | `VSTORE vs, abase, offset` | Store 16 floats to mem[abase + offset] | 2 |

**Alignment:** The effective address `(abase + offset)` **must** be a multiple of 16. Unaligned accesses cause an `AlignmentError` and abort execution.

### Scalar Memory

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| SLOAD | `SLOAD sd, abase, offset` | sd = mem[abase + offset] | 1 |
| SSTORE | `SSTORE ss, abase, offset` | mem[abase + offset] = ss | 1 |

No alignment requirement for scalar memory access.

### Scalar Arithmetic

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| SADD | `SADD sd, ss1, ss2` | sd = ss1 + ss2 | 1 |
| SSUB | `SSUB sd, ss1, ss2` | sd = ss1 - ss2 | 1 |
| SMUL | `SMUL sd, ss1, ss2` | sd = ss1 * ss2 | 1 |
| SDIV | `SDIV sd, ss1, ss2` | sd = ss1 / ss2 | 2 |
| SEXP | `SEXP sd, ss1` | sd = exp(ss1) | 4 |
| SSQRT | `SSQRT sd, ss1` | sd = sqrt(max(0, ss1)) | 4 |
| SMAX | `SMAX sd, ss1, ss2` | sd = max(ss1, ss2) | 1 |
| SMIN | `SMIN sd, ss1, ss2` | sd = min(ss1, ss2) | 1 |
| SSET | `SSET sd, imm` | sd = float immediate value | 1 |
| SCOPY | `SCOPY sd, ss1` | sd = ss1 | 1 |

**SEXP saturation:** Same behavior as VEXP (0.0 for x < -88, +inf for x > 88).

### Address Registers

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| ASET | `ASET ad, imm` | ad = integer immediate | 1 |
| AADD | `AADD ad, as1, imm` | ad = as1 + integer immediate | 1 |
| ACOPY | `ACOPY ad, as1` | ad = as1 | 1 |

Address registers hold integer values used as memory base addresses. The `offset` in load/store instructions is also an integer immediate.

### Vector Utility

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| VCOPY | `VCOPY vd, vs1` | Copy all 16 elements from vs1 to vd | 1 |
| VFILL | `VFILL vd, ss` | Fill all 16 elements of vd with scalar ss | 1 |

### Control Flow

| Instruction | Syntax | Operation | Cycles |
|---|---|---|---|
| LABEL | `LABEL name` | Define a named jump target | 0 |
| JMP | `JMP label` | Unconditional jump to label | 1 |
| JLT | `JLT ss1, ss2, label` | Jump if ss1 < ss2 | 1 |
| JLE | `JLE ss1, ss2, label` | Jump if ss1 <= ss2 | 1 |
| JGT | `JGT ss1, ss2, label` | Jump if ss1 > ss2 | 1 |
| JGE | `JGE ss1, ss2, label` | Jump if ss1 >= ss2 | 1 |
| JEQ | `JEQ ss1, ss2, label` | Jump if \|ss1 - ss2\| < 1e-10 | 1 |
| JNE | `JNE ss1, ss2, label` | Jump if \|ss1 - ss2\| >= 1e-10 | 1 |
| NOP | `NOP` | No operation | 1 |
| HALT | `HALT` | Terminate execution | 0 |

## Execution Model

- Execution begins at the first instruction (index 0)
- Instructions execute sequentially unless a jump changes the program counter
- No pipeline hazards or data dependencies between instructions
- Execution terminates when HALT is reached or the program counter exceeds the instruction count
- Maximum cycle budget: 500,000 cycles (simulator aborts if exceeded)

## Common Patterns

### Tiled vector processing
For vectors longer than 16 elements, process in tiles of 16 using VLOAD/VSTORE with offset arithmetic:
```
ASET a0, 0          # base address
VLOAD v0, a0, 0     # first 16 elements
VLOAD v1, a0, 16    # next 16 elements
```

### Loop with scalar counter
```
SSET s0, 0.0        # counter = 0
SSET s1, 10.0       # limit = 10

LABEL my_loop
# ... loop body ...
SSET s2, 1.0
SADD s0, s0, s2     # counter++
JLT s0, s1, my_loop # loop while counter < limit
```

### Dot product of two 16-element vectors
```
VLOAD v0, a0, 0     # load first vector
VLOAD v1, a1, 0     # load second vector
VMUL v2, v0, v1     # element-wise multiply
VREDSUM s0, v2      # sum all products
```

## Running the Simulator

```bash
python3 /app/simulator/sim.py program.asm
python3 /app/simulator/sim.py program.asm --trace
```
