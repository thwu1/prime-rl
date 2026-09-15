# RISC-V RV32I & RVFI Reference

## RVFI (RISC-V Formal Interface) Signal Semantics

The RVFI is a trace interface for formally verifying RISC-V processors.
Each retired instruction produces an RVFI record with these signals:

| Signal | Width | Description |
|--------|-------|-------------|
| `insn` | 32 | The instruction word |
| `rs1_addr` | 5 | Decoded rs1 register address (0 if unused) |
| `rs1_rdata` | 32 | Value of x[rs1] before execution. **Must be 0 when rs1_addr is 0** |
| `rs2_addr` | 5 | Decoded rs2 register address (0 if unused) |
| `rs2_rdata` | 32 | Value of x[rs2] before execution. **Must be 0 when rs2_addr is 0** |
| `rd_addr` | 5 | Decoded rd register address. **Must be 0 for instructions that don't write rd** |
| `rd_wdata` | 32 | Value written to x[rd]. **Must be 0 when rd_addr is 0** |
| `pc_rdata` | 32 | PC of this instruction (before execution) |
| `pc_wdata` | 32 | PC of the next instruction (after execution) |
| `mem_addr` | 32 | Memory access address (when rmask or wmask is nonzero) |
| `mem_rmask` | 4 | Byte mask for memory reads |
| `mem_wmask` | 4 | Byte mask for memory writes |
| `mem_rdata` | 32 | Data read from memory |
| `mem_wdata` | 32 | Data written to memory |
| `trap` | 1 | Set for illegal instructions, misaligned jumps/memory, or other faults |
| `intr` | 1 | Set for the **first instruction of a trap/interrupt handler** — i.e., an instruction whose `pc_rdata` does not match the previous instruction's `pc_wdata` due to an external interrupt or trap redirection |
| `halt` | 1 | Set on the last instruction before halting |

### Key RVFI Rules

1. **x0 is hardwired to zero**: `rd_wdata` must be 0 when `rd_addr` is 0.
2. **Register consistency**: If an instruction reads register `x[N]` and the shadow register file has a valid entry for `x[N]`, the `rs_rdata` must match the last written value.
3. **PC continuity**: `pc_rdata` of instruction N+1 should equal `pc_wdata` of instruction N, **unless** instruction N+1 has `intr=1` (indicating a trap/interrupt handler entry).
4. **Trap disables PC tracking**: After a trapping instruction (`trap=1`), PC shadow tracking is temporarily invalid since the trap vector address depends on CSR state.

---

## RV32I Instruction Formats

### R-type (register-register ALU)
```
 31      25 24    20 19    15 14  12 11     7 6      0
| funct7   | rs2    | rs1    | f3  | rd     | opcode |
```
Opcode: `0110011`. Instructions: ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND.

### I-type (immediate ALU, loads, JALR)
```
 31              20 19    15 14  12 11     7 6      0
| imm[11:0]       | rs1    | f3  | rd     | opcode |
```
Immediate is **sign-extended from 12 bits**. Opcode: `0010011` (ALU-imm), `0000011` (loads), `1100111` (JALR).

For shift-immediate instructions (SLLI/SRLI/SRAI), `imm[11:5]` encodes funct7 and `imm[4:0]` is the shift amount.

### S-type (stores)
```
 31      25 24    20 19    15 14  12 11     7 6      0
| imm[11:5]| rs2    | rs1    | f3  | imm[4:0]| opcode |
```
Immediate is `{insn[31:25], insn[11:7]}`, **sign-extended from 12 bits**. Opcode: `0100011`.

### B-type (branches)
```
 31    30    25 24    20 19    15 14  12 11    8  7   6      0
|im12|imm[10:5]| rs2    | rs1    | f3  |im[4:1]|im11| opcode |
```
Immediate is `{insn[31], insn[7], insn[30:25], insn[11:8], 1'b0}`, **sign-extended from 13 bits** (note: 13 bits, not 12). Opcode: `1100011`.

### U-type (LUI, AUIPC)
```
 31                              12 11     7 6      0
| imm[31:12]                      | rd     | opcode |
```
Immediate is the upper 20 bits, with lower 12 bits zero. LUI opcode: `0110111`, AUIPC opcode: `0010111`.

### J-type (JAL)
```
 31   30        21  20  19        12 11     7 6      0
|im20| imm[10:1] |im11| imm[19:12] | rd     | opcode |
```
Immediate is `{insn[31], insn[19:12], insn[20], insn[30:21], 1'b0}`, **sign-extended from 21 bits**. Opcode: `1101111`.

---

## Key Instruction Semantics

### ALU Operations
- **ADD**: `rd = rs1 + rs2`
- **SUB**: `rd = rs1 - rs2` (funct7=`0100000`)
- **SLL**: `rd = rs1 << (rs2[4:0])`
- **SLT**: `rd = (signed(rs1) < signed(rs2)) ? 1 : 0`
- **SLTU**: `rd = (unsigned(rs1) < unsigned(rs2)) ? 1 : 0`
- **SRL**: `rd = rs1 >> (rs2[4:0])` (logical, zero-fill)
- **SRA**: `rd = signed(rs1) >>> (rs2[4:0])` (**arithmetic, sign-extending fill**)
- Same operations exist as I-type (ADDI, SLTI, SLTIU, XORI, ORI, ANDI, SLLI, SRLI, SRAI)

### Upper Immediates
- **LUI**: `rd = imm` (upper 20 bits placed directly)
- **AUIPC**: `rd = pc + imm` (add upper immediate to PC)

### Branches
All branch targets: `pc + imm` when taken, `pc + 4` when not taken.
- **BEQ**: taken if `rs1 == rs2`
- **BNE**: taken if `rs1 != rs2`
- **BLT**: taken if `signed(rs1) < signed(rs2)`
- **BGE**: taken if `signed(rs1) >= signed(rs2)`
- **BLTU**: taken if `unsigned(rs1) < unsigned(rs2)`
- **BGEU**: taken if `unsigned(rs1) >= unsigned(rs2)`

### Jumps
- **JAL**: `rd = pc + 4; pc = pc + imm`. Target must be aligned.
- **JALR**: `rd = pc + 4; pc = (rs1 + imm) & ~1`. Note the **LSB is cleared** to enforce alignment.

### Loads
Address: `rs1 + imm`. Result is placed in `rd`.
- **LW**: load 32-bit word. `mem_rmask = 0xF`. Traps on misaligned address.
- **LH**: load 16-bit halfword, **sign-extended to 32 bits**. `mem_rmask = 0x3`. Traps on misaligned.
- **LHU**: load 16-bit halfword, **zero-extended**. `mem_rmask = 0x3`. Traps on misaligned.
- **LB**: load 8-bit byte, **sign-extended to 32 bits**. `mem_rmask = 0x1`.
- **LBU**: load 8-bit byte, **zero-extended**. `mem_rmask = 0x1`.

### Stores
Address: `rs1 + imm`. Data from `rs2`.
- **SW**: store 32-bit word. `mem_wmask = 0xF`. Traps on misaligned address.
- **SH**: store 16-bit halfword. `mem_wmask = 0x3`. Traps on misaligned.
- **SB**: store 8-bit byte. `mem_wmask = 0x1`.

### Funct3 Encoding Reference

| funct3 | R-type  | I-type  | Load | Store | Branch |
|--------|---------|---------|------|-------|--------|
| 000    | ADD/SUB | ADDI    | LB   | SB    | BEQ    |
| 001    | SLL     | SLLI    | LH   | SH    | BNE    |
| 010    | SLT     | SLTI    | LW   | SW    |        |
| 011    | SLTU    | SLTIU   |      |       |        |
| 100    | XOR     | XORI    | LBU  |       | BLT    |
| 101    | SRL/SRA | SRLI/SRAI| LHU |       | BGE    |
| 110    | OR      | ORI     |      |       | BLTU   |
| 111    | AND     | ANDI    |      |       | BGEU   |
