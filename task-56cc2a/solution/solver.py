"""
Intel 8086 Division Microcode Simulator — Complete Implementation

Faithfully implements the CORD, PREIDIV, and POSTIDIV microcode routines
as documented in the 8086 microcode reverse engineering by Ken Shirriff.

"""


class DivisionOverflow(Exception):
    """Raised when the 8086 would generate a type 0 'divide error' interrupt."""
    pass


def execute_div(
    dividend_hi: int,
    dividend_lo: int,
    divisor: int,
    signed: bool = False,
    byte_mode: bool = False,
) -> tuple[int, int]:
    """Simulate the Intel 8086's DIV or IDIV instruction at the microcode level."""

    bits = 8 if byte_mode else 16
    mask = (1 << bits) - 1

    # ── Top-level register loading ──
    # Word: tmpA = DX, tmpC = AX, tmpB = divisor
    # Byte: tmpA = AH, tmpC = AL, tmpB = divisor
    if byte_mode:
        tmpA = (dividend_lo >> 8) & 0xFF
        tmpC = dividend_lo & 0xFF
        tmpB = divisor & 0xFF
    else:
        tmpA = dividend_hi & 0xFFFF
        tmpC = dividend_lo & 0xFFFF
        tmpB = divisor & 0xFFFF

    # Save original upper dividend for POSTIDIV remainder sign check
    original_dividend_hi = tmpA

    f1 = 0  # F1 flag: cleared at instruction start

    # ── PREIDIV (only for IDIV) ──
    # Converts dividend (tmpA:tmpC) and divisor (tmpB) to positive values,
    # tracking the result sign in F1.
    if signed:
        # Test sign of tmpA (upper dividend) via MSB
        if (tmpA >> (bits - 1)) & 1:
            # Dividend is negative: NEGATE tmpA:tmpC
            #
            # NEG tmpC: two's complement of lower word
            old_tmpC = tmpC
            tmpC = (-tmpC) & mask
            # NEG carry: set if operand was non-zero
            neg_carry = 1 if old_tmpC != 0 else 0

            if neg_carry:
                # COM1 tmpA: one's complement of upper word
                tmpA = (~tmpA) & mask
            else:
                # NEG tmpA: two's complement (lower word was zero, carry propagates)
                tmpA = (-tmpA) & mask

            # CF1: toggle F1
            f1 ^= 1

        # Test sign of tmpB (divisor) via MSB
        if (tmpB >> (bits - 1)) & 1:
            # Divisor is negative: NEG tmpB
            tmpB = (-tmpB) & mask
            # CF1: toggle F1
            f1 ^= 1

    # ── CORD: Core Division Routine ──
    # Restoring division algorithm.
    #
    # Initial overflow check: SUBT tmpA (compute tmpA - tmpB)
    # If tmpA >= tmpB (no borrow, carry=0): quotient won't fit → overflow
    # Also handles divide-by-zero (tmpB=0 means tmpA >= tmpB always)
    if tmpB == 0 or tmpA >= tmpB:
        raise DivisionOverflow()

    # After the comparison: tmpA < tmpB → borrow → carry = 1
    carry = 1

    # Main loop: 'bits' iterations (MAXC sets counter to bits-1,
    # loop executes counter+1 times: iterations for counter values
    # bits-1, bits-2, ..., 1, 0)
    for _ in range(bits):
        # RCL tmpC: rotate tmpC left through carry
        # Shifts the previous quotient bit (in carry) into tmpC LSB
        new_carry = (tmpC >> (bits - 1)) & 1
        tmpC = ((tmpC << 1) | carry) & mask
        carry = new_carry

        # RCL tmpA: rotate tmpA left through carry
        # The carry from tmpC's MSB enters tmpA's LSB (32-bit shift effect)
        # The carry out is tmpA's old MSB (the "extra bit" for 17-bit comparison)
        new_carry = (tmpA >> (bits - 1)) & 1
        tmpA = ((tmpA << 1) | carry) & mask
        carry = new_carry

        # SUBT tmpA: set up tmpA - tmpB
        # Decision based on carry (old MSB of tmpA = the extra bit)
        if carry:
            # Path A (line 6 → 13 → 14):
            # Extra bit set → effective value > any n-bit tmpB → subtract
            tmpA = (tmpA - tmpB) & mask
            # RCY: reset carry to 0 (complemented quotient bit = 0 → actual = 1)
            carry = 0
        else:
            # Path B: compare tmpA with tmpB
            # SUBT result determines if tmpA >= tmpB
            if tmpA >= tmpB:
                # Path B1 (line 8 → 14): subtract
                tmpA = tmpA - tmpB
                # carry = 0 (no borrow from SUBT → NCY → complemented bit = 0)
                carry = 0
            else:
                # Path B2 (line 9): don't subtract
                # carry = 1 (borrow from SUBT → CY → complemented bit = 1)
                carry = 1

    # ── Done section (label 10) ──
    # First RCL tmpC: shift last quotient bit (carry) into tmpC
    new_carry = (tmpC >> (bits - 1)) & 1
    tmpC = ((tmpC << 1) | carry) & mask

    # Second RCL tmpC: result discarded, but carry = MSB of tmpC
    # (the MSB of the complemented quotient, used by POSTIDIV)
    cord_carry = (tmpC >> (bits - 1)) & 1

    # At this point:
    # tmpC = complemented quotient (one's complement of actual quotient)
    # tmpA = unsigned remainder
    # cord_carry = MSB of complemented quotient

    if signed:
        # ── POSTIDIV ──

        # Overflow check: JMP NCY INT0
        # If cord_carry = 0 (NCY = true): the complemented quotient's MSB is 0,
        # meaning actual quotient's MSB is 1 → magnitude ≥ 2^(n-1) → overflow
        if cord_carry == 0:
            raise DivisionOverflow()

        # Fix remainder sign: check original dividend's sign
        # RCL tmpB (which was loaded with original DX/AH by top-level code)
        # The MSB of original_dividend_hi tells us the dividend's sign
        if (original_dividend_hi >> (bits - 1)) & 1:
            # Original dividend was negative → negate remainder
            tmpA = (-tmpA) & mask

        # Fix quotient sign based on F1
        if f1:
            # F1 set → result should be negative
            # INC tmpC: ~quotient + 1 = -(actual quotient) in two's complement
            quotient = (tmpC + 1) & mask
        else:
            # F1 clear → result should be positive
            # COM1 tmpC: ~(~quotient) = actual quotient
            quotient = (~tmpC) & mask
    else:
        # ── Unsigned: COM1 tmpC ──
        quotient = (~tmpC) & mask

    remainder = tmpA
    return (quotient, remainder)
