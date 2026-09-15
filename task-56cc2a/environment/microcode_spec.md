# Intel 8086 Division Microcode Specification

## Overview

The Intel 8086 processor (1978) implements integer division via microcode — a layer
of internal micro-instructions that control the ALU and registers. This document
specifies the microcode routines, register model, and ALU semantics needed to build
a faithful simulator of the 8086's DIV and IDIV instructions.

## Register Model

The ALU has three **invisible temporary registers**: `tmpA`, `tmpB`, `tmpC` (16-bit
for word mode, 8-bit for byte mode).

Other relevant state:
- **Carry flag (CF)**: set/cleared by ALU operations; used for conditional jumps
  and as a 17th bit during rotations.
- **F1 flag**: internal flag toggled by `CF1`; tracks the sign for signed
  division. Cleared at instruction start.
- **Loop counter**: 4-bit counter; initialized by `MAXC` to 15 (word) or 7 (byte).
  Decremented and tested by `NCZ`.

## ALU Operations

ALU operations use a **two-phase** protocol:

1. **Setup phase**: a micro-instruction specifies the ALU operation and operand
   (e.g., `SUBT tmpA` means "prepare to compute tmpA − tmpB").
2. **Read phase**: a later micro-instruction reads the result via the `Σ` (Sigma)
   pseudo-register and moves it to a destination.

A new setup **replaces** any pending operation. The result in `Σ` persists until
a new result is read.

### Operations used by division

| Operation | Semantics | Carry out |
|-----------|-----------|-----------|
| `SUBT reg` | Σ = reg − tmpB | CF = 1 if reg < tmpB (borrow), else 0 |
| `RCL reg` | Rotate reg left through carry. Σ = (reg << 1 \| CF_in) & mask. | CF = old MSB of reg |
| `NEG reg` | Σ = (−reg) & mask (two's complement) | CF = 1 if reg ≠ 0, else 0 |
| `COM1 reg` | Σ = (~reg) & mask (one's complement) | CF unchanged |
| `INC reg` | Σ = (reg + 1) & mask | CF unchanged |

**Important**: `RCL` always updates the carry flag (it is inherent to the rotation).
Other operations update the carry flag **only when the micro-instruction has the `F`
bit** (shown as `F` in the listings), EXCEPT for `NEG` which always sets carry
based on whether the operand is non-zero.

### Special micro-operations

| Operation | Effect |
|-----------|--------|
| `MAXC` | Set loop counter to 15 (word) or 7 (byte) |
| `NCZ` | If counter ≠ 0: jump to target, decrement counter. If counter = 0: fall through. |
| `RCY` | Clear carry flag to 0 |
| `CF1` | Toggle the F1 flag |
| `CCOF` | Clear carry and overflow flags |
| `SCOF` | Set carry and overflow flags |
| `CALL target` | Push return address, jump to target subroutine |
| `RTN` | Return from subroutine |
| `JMPS cond target` | Conditional short jump |
| `JMP cond target` | Conditional jump |

### Conditions

| Condition | Meaning |
|-----------|---------|
| `CY` | Carry flag is set |
| `NCY` | Carry flag is clear |
| `NCZ` | Loop counter is not zero (also decrements) |
| `F1` | F1 flag is set |
| `X0` | Bit 0 of X register is set (distinguishes DIV from IDIV) |

## Division Instructions

The 8086 has four division instructions:

| Instruction | Operand size | Dividend | Divisor | Quotient | Remainder |
|------------|-------------|----------|---------|----------|-----------|
| DIV r/m16 | word | DX:AX (32-bit) | r/m16 | AX | DX |
| DIV r/m8 | byte | AX (16-bit) | r/m8 | AL | AH |
| IDIV r/m16 | word (signed) | DX:AX (32-bit signed) | r/m16 (signed) | AX | DX |
| IDIV r/m8 | byte (signed) | AX (16-bit signed) | r/m8 (signed) | AL | AH |

For IDIV: remainder sign = dividend sign. Truncating division (toward zero).

## Top-Level Microcode: DIV/IDIV Word

```
   move          action         comment
1. DX → tmpA                    load upper dividend
2. AX → tmpC     RCL tmpA       load lower dividend; set up RCL of tmpA
3. M → tmpB      CALL X0 PREIDIV  load divisor; call PREIDIV if IDIV
4.               CALL CORD      call core division routine
5.               COM1 tmpC      set up complement of quotient
6. DX → tmpB     CALL X0 POSTIDIV  reload original DX; call POSTIDIV if IDIV
7. Σ → AX        NXT            store quotient
8. tmpA → DX     RNI            store remainder
```

## Top-Level Microcode: DIV/IDIV Byte

```
   move          action         comment
1. AH → tmpA                    load upper dividend (AH)
2. AL → tmpC     RCL tmpA       load lower dividend (AL); set up RCL
3. M → tmpB      CALL X0 PREIDIV  load divisor; call PREIDIV if IDIV
4.               CALL CORD      call core division
5.               COM1 tmpC      set up complement
6. AH → tmpB     CALL X0 POSTIDIV  reload original AH; call POSTIDIV if IDIV
7. Σ → AL        NXT            store quotient
8. tmpA → AH     RNI            store remainder
```

## CORD — Core Division Routine

The CORD subroutine implements the restoring division algorithm. At entry:
tmpA = upper dividend, tmpC = lower dividend, tmpB = divisor.

```
Line  move          action         comment
 0.                 SUBT tmpA      set up: tmpA − tmpB
 1.   Σ → no dest   MAXC F         read/discard result; init counter; update flags
 2.                 JMP NCY INT0   if no carry (tmpA ≥ tmpB): overflow interrupt

                                   ── main loop (label 3) ──
 3.                 RCL tmpC       rotate tmpC left through carry
 4.   Σ → tmpC      RCL tmpA       store rotated tmpC; rotate tmpA left
 5.   Σ → tmpA      SUBT tmpA      store rotated tmpA; set up tmpA − tmpB
 6.                 JMPS CY 13     if carry set (old MSB of tmpA was 1): jump to 13
 7.   Σ → no dest   F              read subtraction result (discard); update flags
 8.                 JMPS NCY 14    if no carry (tmpA ≥ tmpB): jump to 14 (subtract)
 9.                 JMPS NCZ 3     if counter not zero: loop; else fall through

                                   ── done (label 10) ──
10.                 RCL tmpC       rotate last quotient bit into tmpC
11.   Σ → tmpC      RCL tmpC       store result; set up second rotation
12.   Σ → no dest   RTN            discard (carry = MSB of tmpC); return

                                   ── subtract paths ──
13.                 RCY            clear carry (quotient bit = 0 complemented)
14.   Σ → tmpA      JMPS NCZ 3    store subtraction result; loop if counter ≠ 0
15.                 JMPS 10        unconditional jump to done
```

### Key points about CORD

- **Carry threading**: the carry flag serves triple duty:
  1. Carries the "extra bit" during RCL of tmpA (17th bit for comparison)
  2. Holds the comparison result (borrow from SUBT)
  3. Transports the quotient bit into tmpC via the next iteration's RCL

- **Complemented quotient**: when a subtraction occurs, carry = 0; when no subtraction,
  carry = 1. These bits fill tmpC, producing the **one's complement** of the actual
  quotient. The top-level code applies `COM1` to fix this.

- **Initial carry**: after the overflow check (line 1-2), carry = 1 (because
  tmpA < tmpB implies borrow). This carry enters the first `RCL tmpC`.

- **Done section**: two `RCL tmpC` operations. The first shifts the last quotient bit
  in. The second is discarded but places the MSB of the complemented quotient
  into the carry flag, used by POSTIDIV for overflow detection.

- **Loop count**: 16 iterations for word, 8 for byte (counter starts at 15 or 7,
  decrements to 0, then falls through on the iteration where counter reaches 0).

## PREIDIV — Pre-Integer-Division

Called before CORD for signed (IDIV) instructions. Converts dividend and divisor
to positive values, tracking sign in F1.

At entry, the top-level code has already set up `RCL tmpA`.

```
Line  move          action         comment
 0.   Σ → no dest                  read RCL result (discard); carry = MSB(tmpA)
 1.                 JMPS NCY 7    if tmpA non-negative (carry=0): skip to 7

                                   ── NEGATE: negate tmpA:tmpC ──
 2.                 NEG tmpC       negate lower word
 3.   Σ → tmpC      COM1 tmpA F    store negated tmpC; set up COM1 of tmpA
                                   (F updates flags from NEG: carry = tmpC_orig ≠ 0)
 4.                 JMPS CY 6     if carry set (tmpC was non-zero): jump to 6
 5.                 NEG tmpA       tmpC was zero: need NEG instead of COM1 for tmpA
 6.   Σ → tmpA      CF1            store result; toggle F1

                                   ── handle divisor (label 7) ──
 7.                 RCL tmpB       rotate tmpB to test sign
 8.   Σ → no dest   NEG tmpB       read/discard RCL; set up NEG of tmpB
 9.                 JMPS NCY 11   if tmpB non-negative: skip to 11
10.   Σ → tmpB      CF1 RTN        store negated tmpB; toggle F1; return
11.                 RTN            return (tmpB positive, no change)
```

### Multi-word negation logic

Negating the 32-bit (or 16-bit) dividend stored in tmpA:tmpC:
- `NEG tmpC`: two's complement of lower word. Carry = 1 if tmpC ≠ 0.
- If carry = 1 (lower word non-zero): `COM1 tmpA` (one's complement of upper word).
- If carry = 0 (lower word was zero): `NEG tmpA` (two's complement of upper word).

This correctly implements: −(tmpA:tmpC) = (~tmpA : (−tmpC)) when tmpC ≠ 0,
or (−tmpA : 0) when tmpC = 0.

## POSTIDIV — Post-Integer-Division

Called after CORD for signed division. Checks for signed overflow, adjusts signs
of quotient and remainder.

At entry: carry = MSB of complemented quotient (from CORD's final RCL).
tmpA = unsigned remainder. tmpC = complemented quotient. tmpB = original
dividend high word/byte (reloaded by top-level code). F1 = result sign.

```
Line  move          action         comment
 0.                 JMP NCY INT0   if carry=0: quotient MSB set → overflow
 1.                 RCL tmpB       rotate tmpB to test original dividend sign
 2.   Σ → no dest   NEG tmpA       read/discard; carry = MSB(orig dividend hi)
                                   set up NEG of remainder
 3.                 JMPS NCY 5    if original dividend positive: skip negate
 4.   Σ → tmpA                     negate remainder (dividend was negative)
 5.                 INC tmpC       set up increment of complemented quotient
 6.                 JMPS F1 8     if F1 set (result negative): skip COM1
 7.                 COM1 tmpC      result positive: complement to get actual quotient
 8.                 CCOF RTN       clear carry/overflow; return
```

### POSTIDIV details

**Overflow check**: if the MSB of the complemented quotient is 0, the actual
quotient's MSB is 1 — meaning the unsigned quotient ≥ 2^(n−1). This is too
large for a signed result. This causes the 8086 to reject quotient = −2^(n−1)
(e.g., −32768 for word, −128 for byte) even though it fits in the signed range.

**Remainder sign**: the original dividend's high byte (DX or AH) is rotated to
check its sign. If negative, the remainder is negated (remainder sign = dividend sign).

**Quotient sign**: controlled by F1.
- F1 = 1: result should be negative. `INC tmpC` converts ~q to ~q+1 = −q
  (two's complement).
- F1 = 0: result should be positive. `COM1 tmpC` converts ~q to q.

The ALU result from POSTIDIV is stored by the top-level code's `Σ → AX` (or `Σ → AL`).

## Reference Test Vectors

| Mode | DX/AH | AX/AL | Divisor | Signed | Quotient | Remainder |
|------|-------|-------|---------|--------|----------|-----------|
| word | 0x0000 | 0x000A | 0x0003 | no | 3 | 1 |
| word | 0x0F00 | 0xFF00 | 0x0FFC | no | 0xF04C | 0x0030 |
| byte | — | 0x2345 | 0x34 | no | 0xAD | 0x21 |
| word | 0xFFFF | 0xFFE5 | 0x0007 | yes | 0xFFFD (−3) | 0xFFFA (−6) |
| word | 0xFFFF | 0x8000 | 0x0001 | yes | OVERFLOW | — |
| byte | — | 0xFF80 | 0x01 | yes | OVERFLOW | — |
