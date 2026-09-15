"""
Transfer functions for the KnownBits abstract domain.

Implement the six TODO functions below.  Each function receives KnownBits
operands and must return a KnownBits result that is:

  * SOUND  — for every concrete input pair (x in a, y in b) the concrete
    operation result must be contained in the abstract output.
  * PRECISE — determine as many bits as possible (do not just return top).

Four reference implementations (AND, OR, XOR, NOT) are provided as examples.
"""

from knownbits import KnownBits


# ============================================================
# PROVIDED EXAMPLES — do not modify
# ============================================================

def transfer_and(a: KnownBits, b: KnownBits) -> KnownBits:
    """Bitwise AND."""
    w = a.width
    return KnownBits(w, a.zero_mask | b.zero_mask, a.one_mask & b.one_mask)


def transfer_or(a: KnownBits, b: KnownBits) -> KnownBits:
    """Bitwise OR."""
    w = a.width
    return KnownBits(w, a.zero_mask & b.zero_mask, a.one_mask | b.one_mask)


def transfer_xor(a: KnownBits, b: KnownBits) -> KnownBits:
    """Bitwise XOR."""
    w = a.width
    mask = (1 << w) - 1
    known = (a.zero_mask | a.one_mask) & (b.zero_mask | b.one_mask)
    ones = (a.one_mask ^ b.one_mask) & known
    zeros = (~(a.one_mask ^ b.one_mask)) & mask & known
    return KnownBits(w, zeros, ones)


def transfer_not(a: KnownBits) -> KnownBits:
    """Bitwise NOT."""
    return KnownBits(a.width, a.one_mask, a.zero_mask)


# ============================================================
# IMPLEMENT THE FOLLOWING SIX TRANSFER FUNCTIONS
# ============================================================

def transfer_add(a: KnownBits, b: KnownBits) -> KnownBits:
    """Unsigned modular addition: (a + b) mod 2^width."""
    return KnownBits.top(a.width)


def transfer_sub(a: KnownBits, b: KnownBits) -> KnownBits:
    """Unsigned modular subtraction: (a - b) mod 2^width."""
    return KnownBits.top(a.width)


def transfer_mul(a: KnownBits, b: KnownBits) -> KnownBits:
    """Unsigned modular multiplication: (a * b) mod 2^width."""
    return KnownBits.top(a.width)


def transfer_shl(a: KnownBits, b: KnownBits) -> KnownBits:
    """Left shift: (a << b) mod 2^width.  Result is 0 when b >= width."""
    return KnownBits.top(a.width)


def transfer_lshr(a: KnownBits, b: KnownBits) -> KnownBits:
    """Logical right shift: a >> b (zero-fill).  Result is 0 when b >= width."""
    return KnownBits.top(a.width)


def transfer_udiv(a: KnownBits, b: KnownBits) -> KnownBits:
    """Unsigned integer division: a // b.  Result is 0 when b is 0."""
    return KnownBits.top(a.width)
