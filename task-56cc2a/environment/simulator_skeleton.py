"""
Intel 8086 Division Microcode Simulator — Skeleton

Implement the execute_div() function to simulate the 8086's DIV/IDIV instructions
at the microcode level, following the specifications in /app/rom_format.md, /app/division_context.md, and /app/microcode_spec.md.

The implementation must faithfully follow the 8086 microcode algorithm, including:
- The restoring division algorithm (CORD routine) with carry flag threading
- The complemented quotient representation
- Multi-word two's complement negation (PREIDIV)
- Signed overflow detection via POSTIDIV (rejects quotient = -2^(n-1))
- Byte vs word mode differences (8 vs 16 iterations, register widths)
"""



class DivisionOverflow(Exception):
    """Raised when the 8086 would generate a type 0 'divide error' interrupt.

    This occurs on:
    - Division by zero
    - Unsigned quotient too large (>= 2^16 for word, >= 2^8 for byte)
    - Signed quotient out of range: the 8086 rejects quotients with magnitude
      >= 2^(n-1), which means -32768 (word) and -128 (byte) cause overflow
      even though they fit in the signed representation.
    """
    pass


def execute_div(
    dividend_hi: int,
    dividend_lo: int,
    divisor: int,
    signed: bool = False,
    byte_mode: bool = False,
) -> tuple[int, int]:
    """Simulate the Intel 8086's DIV or IDIV instruction.

    Parameters
    ----------
    dividend_hi : int
        For word mode: DX register (0x0000–0xFFFF).
        For byte mode: ignored (pass 0).
    dividend_lo : int
        For word mode: AX register (0x0000–0xFFFF).
        For byte mode: AX register (0x0000–0xFFFF).
    divisor : int
        For word mode: 16-bit source operand (0x0000–0xFFFF).
        For byte mode: 8-bit source operand (0x00–0xFF).
    signed : bool
        False for DIV (unsigned), True for IDIV (signed).
    byte_mode : bool
        False for word (16-bit) operation, True for byte (8-bit) operation.

    Returns
    -------
    (quotient, remainder) : tuple[int, int]
        Both values as unsigned integers in the range appropriate for the mode.
        For word mode: 0x0000–0xFFFF each.
        For byte mode: 0x00–0xFF each.
        For signed mode: the signed result encoded as unsigned (two's complement).

    Raises
    ------
    DivisionOverflow
        When the 8086 would generate a type 0 interrupt.
    """
    raise NotImplementedError("Implement the 8086 microcode division simulator")
