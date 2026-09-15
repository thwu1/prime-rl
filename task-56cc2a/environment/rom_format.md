# 8086 Microcode ROM Binary Format

## File Structure

The ROM binary consists of a fixed header followed by sequential routine entries.

### Header (6 bytes)

| Offset | Size | Description |
|--------|------|-------------|
| 0 | 4 | Magic bytes: ASCII `UROM` |
| 4 | 1 | Version: `0x01` |
| 5 | 1 | Number of routines (N) |

### Routine Entries

Immediately following the header, N routine entries appear sequentially:

| Field | Size | Description |
|-------|------|-------------|
| Routine ID | 1 byte | Identifies the routine (see table below) |
| Instruction Count | 1 byte | Number of micro-instructions (K) |
| Bitstream | ceil(K × 21 / 8) bytes | Packed micro-instructions |

#### Routine IDs

| ID | Name | Purpose |
|----|------|---------|
| 0 | CORD | Core division loop (restoring division) |
| 1 | PREIDIV | Pre-integer-division — sign handling for IDIV |
| 2 | POSTIDIV | Post-integer-division — overflow check and sign fixup |
| 3 | DIV_WORD | Top-level 16-bit division dispatch |
| 4 | DIV_BYTE | Top-level 8-bit division dispatch |

## Micro-instruction Encoding (21 bits)

Each micro-instruction is exactly 21 bits wide:

```
Bit:  20  19  18  17  16 | 15  14  13  12  11 | 10 |  9   8   7 |  6   5   4   3   2   1   0
      |--- SRC (5) ------| |--- DST (5) ------| | F| |TYPE (3)-| |---- OPERAND (7) ---------|
```

### Field Summary

| Field | Bits | Width | Description |
|-------|------|-------|-------------|
| SRC | [20:16] | 5 | Source register for parallel move |
| DST | [15:11] | 5 | Destination register for parallel move |
| F | [10] | 1 | Flag update bit (controls carry/status flag latching) |
| TYPE | [9:7] | 3 | Instruction type — determines OPERAND semantics |
| OPERAND | [6:0] | 7 | Type-dependent payload |

### Register Codes (5-bit, used in SRC and DST fields)

| Binary | Hex | Name | Description |
|--------|-----|------|-------------|
| 00000 | 0x00 | tmpA | ALU temporary register A |
| 00001 | 0x01 | tmpB | ALU temporary register B (always second ALU input) |
| 00010 | 0x02 | tmpC | ALU temporary register C |
| 00011 | 0x03 | SIGMA | ALU result output (Σ) |
| 00100 | 0x04 | AX | Accumulator register |
| 00101 | 0x05 | DX | Data register |
| 00110 | 0x06 | AH | Accumulator high byte |
| 00111 | 0x07 | AL | Accumulator low byte |
| 01000 | 0x08 | M | Memory operand |
| 11111 | 0x1F | NONE | Null — no register transfer |

### Type Codes (3-bit)

| Code | Name | OPERAND format |
|------|------|----------------|
| 0 | ALU | `[6:4]` = ALU op code, `[3:0]` = source register index |
| 1 | SJMP | `[6:4]` = condition code, `[3:0]` = target line (0–15) |
| 2 | LJMP | `[6:4]` = condition code, `[3:0]` = target routine ID |
| 3 | LCALL | `[6:4]` = condition code, `[3:0]` = target routine ID |
| 4 | SPECIAL | `[6:0]` = special operation code |
| 5 | RETURN | `[6:0]` = combined return flags (see below) |
| 6 | TERMINAL | `[0]`: 0 = NXT (next instruction), 1 = RNI (run next instr) |
| 7 | MOVE | Move only — OPERAND is unused (parallel register transfer) |

### ALU Operations (TYPE=0, in OPERAND[6:4])

| Code | Name | Semantics | Carry behavior |
|------|------|-----------|---------------|
| 0 | SUBT | Σ = reg − tmpB | CF = 1 if reg < tmpB (borrow), else 0 |
| 1 | RCL | Σ = (reg << 1 \| CF_in) & mask | CF = old MSB of reg (**always** updates) |
| 2 | NEG | Σ = (−reg) & mask | CF = 1 if reg ≠ 0 (**always** updates) |
| 3 | COM1 | Σ = (~reg) & mask | CF unchanged |
| 4 | INC | Σ = (reg + 1) & mask | CF unchanged |

The ALU source register (OPERAND[3:0]) uses the lower 4 bits of the register code from the table above. In the division routines this is always one of tmpA(0), tmpB(1), or tmpC(2).

**F bit interaction**: The F bit (bit 10) controls whether the carry flag is updated from the ALU result. RCL and NEG **always** update the carry flag regardless of F. For SUBT, COM1, and INC, carry is only updated when F=1. When F=1 on a MOVE instruction (TYPE=7), the carry flag is latched from the most recent ALU result.

### Condition Codes (TYPE=1,2,3, in OPERAND[6:4])

| Code | Name | Condition |
|------|------|-----------|
| 0 | UNC | Unconditional |
| 1 | CY | Carry flag is set |
| 2 | NCY | Carry flag is clear |
| 3 | NCZ | Loop counter ≠ 0 (also decrements counter) |
| 4 | F1 | F1 internal flag is set |
| 5 | X0 | Bit 0 of X register is set (IDIV vs DIV) |

### Special Operation Codes (TYPE=4, in OPERAND[6:0])

| Code | Name | Effect |
|------|------|--------|
| 1 | MAXC | Set loop counter to 15 (word) or 7 (byte) |
| 2 | RCY | Clear the carry flag to 0 |
| 3 | CF1 | Toggle the F1 internal flag |
| 4 | CCOF | Clear carry and overflow flags |
| 5 | SCOF | Set carry and overflow flags |

### RETURN Flags (TYPE=5, in OPERAND[6:0])

| Bit | Effect when set |
|-----|-----------------|
| 0 | Toggle F1 flag before returning (CF1) |
| 2 | Clear carry and overflow before returning (CCOF) |

Flags can be combined. OPERAND=0 is a plain return. OPERAND=3 would toggle F1; OPERAND=4 would clear carry/overflow.

### Jump/Call Target Routine IDs (OPERAND[3:0] for TYPE=2,3)

| ID | Routine |
|----|---------|
| 0 | INT0 (divide overflow interrupt) |
| 1 | CORD |
| 2 | PREIDIV |
| 3 | POSTIDIV |

## Bitstream Packing

Micro-instructions within each routine are packed into a continuous bitstream, **MSB first**, with no gaps between instructions. Each routine's bitstream is independently packed and padded with zero bits to the next byte boundary.

For a routine with K instructions:
- Total meaningful bits: K × 21
- Total bytes: ceil(K × 21 / 8)
- Padding bits at end: (8 − (K × 21) mod 8) mod 8

### Decoding Algorithm

To extract instruction N from a routine's bitstream:
1. Compute bit offset: `bit_offset = N × 21`
2. For each of the 21 bits (i = 0 to 20):
   - Byte index: `(bit_offset + i) ÷ 8`
   - Bit position within byte: `7 − ((bit_offset + i) mod 8)` (MSB = bit 7)
3. Assemble the 21 bits into an integer (bit 0 of the extraction = bit 20 of the instruction)
4. Parse using the field layout above
