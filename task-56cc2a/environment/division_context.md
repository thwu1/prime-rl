# Intel 8086 Division Algorithm — Context Notes

## Overview

The Intel 8086 processor (1978) implements integer division via microcode — a layer of internal micro-instructions controlling the ALU and registers. Division uses three subroutines (CORD, PREIDIV, POSTIDIV) coordinated by two top-level dispatch routines (DIV_WORD, DIV_BYTE).

The microcode ROM at `/app/microcode_rom.bin` contains these five routines in packed binary form. The encoding format is documented in `/app/rom_format.md`. You must decode the ROM to obtain the exact instruction sequences.

## Register Model

The ALU has three invisible temporary registers: **tmpA**, **tmpB**, **tmpC** (16-bit for word mode, 8-bit for byte mode).

Other state:
- **Carry flag (CF)**: set/cleared by ALU operations; serves triple duty in division as overflow indicator, comparison result, and quotient bit carrier
- **F1 flag**: internal flag toggled by CF1; tracks result sign for signed division. Cleared at instruction start.
- **Loop counter**: 4-bit counter; initialized by MAXC to 15 (word) or 7 (byte). Decremented and tested by NCZ.
- **X register bit 0**: set for IDIV, clear for DIV. Used by conditional calls to select signed vs unsigned paths.

## ALU Semantics

ALU operations use a two-phase protocol:
1. **Setup**: a micro-instruction specifies the ALU operation and source register, configuring the ALU
2. **Read**: a subsequent instruction reads the result via Σ (Sigma) and moves it to a destination

A new setup replaces any pending operation. The Σ result persists until consumed.

### Carry Flag Behavior

This is critical to understand:
- **SUBT**: CF = 1 if source < tmpB (borrow occurred). Only updates CF when the F bit is set.
- **RCL**: CF = old MSB of source. **Always** updates CF regardless of F bit.
- **NEG**: CF = 1 if source ≠ 0. **Always** updates CF regardless of F bit.
- **COM1, INC**: do not modify CF.
- **F bit on MOVE**: latches the carry from the most recent ALU result into the flags register.

## Division Instructions

| Instruction | Dividend | Divisor | Quotient → | Remainder → |
|------------|----------|---------|------------|-------------|
| DIV r/m16 | DX:AX (32-bit unsigned) | r/m16 | AX | DX |
| DIV r/m8 | AX (16-bit unsigned) | r/m8 | AL | AH |
| IDIV r/m16 | DX:AX (32-bit signed) | r/m16 (signed) | AX | DX |
| IDIV r/m8 | AX (16-bit signed) | r/m8 (signed) | AL | AH |

For IDIV: remainder sign matches dividend sign. Division truncates toward zero.

## Algorithm Overview

### Top-Level Flow

1. Load dividend into tmpA (upper) and tmpC (lower)
2. Load divisor into tmpB
3. Set up RCL of tmpA (used by PREIDIV to test sign)
4. If IDIV: call PREIDIV to convert to unsigned
5. Call CORD for the actual division
6. Set up COM1 of tmpC (complement the quotient)
7. If IDIV: reload original upper dividend into tmpB, call POSTIDIV for sign/overflow fixup
8. Store results: quotient from Σ, remainder from tmpA

### CORD — Core Division

Implements restoring division:
- **Overflow check**: subtracts tmpB from tmpA. If no borrow (tmpA ≥ tmpB), the quotient cannot fit → overflow interrupt.
- **Main loop** (16 iterations for word, 8 for byte): uses RCL to shift tmpC and tmpA left through carry, creating a 33-bit (or 17-bit) working value. After shifting, subtracts tmpB and decides whether to keep or restore. The carry flag simultaneously carries the shift overflow, the comparison result, and the quotient bit.
- **Quotient accumulation**: quotient bits enter tmpC in **complemented** form (carry=0 means subtraction occurred → actual quotient bit is 1). The top-level code applies COM1 to invert.
- **Exit**: two final RCL operations on tmpC. The first shifts in the last quotient bit. The second places the complemented quotient's MSB into the carry flag for POSTIDIV's overflow detection.

### PREIDIV — Pre-Integer Division

Called only for IDIV. Converts signed operands to positive:
- Tests MSB of tmpA (upper dividend) via carry from RCL
- If negative: performs multi-word negation of tmpA:tmpC
  - NEG tmpC (carry = 1 if tmpC ≠ 0)
  - If carry: COM1 tmpA (one's complement — the +1 from NEG carries over)
  - If no carry: NEG tmpA (lower word was zero, need full two's complement)
  - Toggle F1
- Tests MSB of tmpB (divisor) via RCL
- If negative: NEG tmpB, toggle F1
- F1 ends up set when result should be negative (operand signs differ)

### POSTIDIV — Post-Integer Division

Called only for IDIV. Three tasks:
1. **Overflow**: checks carry from CORD's final RCL. If carry=0, the complemented quotient's MSB was 0, meaning actual quotient's MSB is 1 → magnitude ≥ 2^(n−1) → overflow. This makes the 8086 reject quotient = −2^(n−1) (−32768 word, −128 byte) even though it fits in the signed range.
2. **Remainder sign**: tests original dividend's sign (from tmpB, reloaded by top-level). If negative, negate the remainder.
3. **Quotient sign**: if F1 set (negative result), INC tmpC converts ~q to ~q+1 = −q. If F1 clear (positive result), COM1 tmpC converts ~q to q.

## Reference Test Vectors

| Mode | DX/AH | AX/AL | Divisor | Signed | Quotient | Remainder |
|------|-------|-------|---------|--------|----------|-----------|
| word | 0x0000 | 0x000A | 0x0003 | no | 3 | 1 |
| word | 0x0F00 | 0xFF00 | 0x0FFC | no | 0xF04C | 0x0030 |
| byte | — | 0x2345 | 0x34 | no | 0xAD | 0x21 |
| word | 0xFFFF | 0xFFE5 | 0x0007 | yes | 0xFFFD (−3) | 0xFFFA (−6) |
| word | 0x0000 | 0x001B | 0xFFF9 | yes | 0xFFFD (−3) | 6 |
| word | 0xFFFF | 0x8000 | 0x0001 | yes | OVERFLOW | — |
| byte | — | 0xFF80 | 0x01 | yes | OVERFLOW | — |
