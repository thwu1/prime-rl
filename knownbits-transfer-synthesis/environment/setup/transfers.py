"""
Transfer Functions for the KnownBits Abstract Domain

Implement each transfer function below. Each function receives KnownBits
input(s) and must return a KnownBits result that is SOUND: the returned
KnownBits must contain every possible concrete result.

Precision matters: returning top() (all unknown) is always sound but scores
zero precision. Your goal is to propagate as much known-bit information as
possible while remaining sound.

Available from knownbits module:
  - KnownBits(width, zero_mask, one_mask)
  - top(width), constant(width, value), meet(a, b)
  - get_min_unsigned(kb), get_max_unsigned(kb)
  - get_min_signed(kb), get_max_signed(kb)

RULES:
  - Do NOT call concrete operation functions or enumerate concrete values
    inside transfer functions. Transfer functions must work in O(1) or O(width)
    time using only bitwise reasoning on the masks.
  - You may use helper functions but they must operate on masks, not enumerate.
  - The transfer functions must be correct for ALL bit widths (4 through 16).
"""

from knownbits import KnownBits, top, constant, meet
from knownbits import get_min_unsigned, get_max_unsigned


# ============================================================
# BITWISE OPERATIONS — Implement these
# ============================================================

def transfer_and(a, b):
    """Known-bits transfer for: result = a & b"""
    # TODO: implement
    return top(a.width)


def transfer_or(a, b):
    """Known-bits transfer for: result = a | b"""
    # TODO: implement
    return top(a.width)


def transfer_xor(a, b):
    """Known-bits transfer for: result = a ^ b"""
    # TODO: implement
    return top(a.width)


# ============================================================
# SHIFT OPERATIONS — Implement these
# ============================================================

def transfer_shl(a, b):
    """Known-bits transfer for: result = a << b (logical shift left).
    If shift amount >= width, result is 0.
    When shift amount is unknown, must be sound for ALL possible shift amounts.
    """
    # TODO: implement
    return top(a.width)


def transfer_lshr(a, b):
    """Known-bits transfer for: result = a >> b (logical shift right, zero-fill).
    If shift amount >= width, result is 0.
    """
    # TODO: implement
    return top(a.width)


def transfer_ashr(a, b):
    """Known-bits transfer for: result = a >> b (arithmetic shift right, sign-fill).
    If shift amount >= width, result is all-sign-bit.
    """
    # TODO: implement
    return top(a.width)


# ============================================================
# ARITHMETIC OPERATIONS — Implement these
# ============================================================

def transfer_add(a, b):
    """Known-bits transfer for: result = a + b (unsigned, mod 2^width).

    This is the hardest standard transfer function. Consider how carries
    propagate through known and unknown bits. LLVM's implementation uses
    the insight that you can compute possible-sum-zero and possible-sum-one
    by adding the max/min values and analyzing the carry chain.
    """
    # TODO: implement
    return top(a.width)


def transfer_sub(a, b):
    """Known-bits transfer for: result = a - b (unsigned, mod 2^width).

    Hint: subtraction can be expressed in terms of addition and bitwise NOT.
    """
    # TODO: implement
    return top(a.width)


def transfer_mul(a, b):
    """Known-bits transfer for: result = a * b (unsigned, mod 2^width).

    At minimum, track trailing known-zero bits (from shift-and-add model
    of multiplication). For higher precision, consider the range of possible
    results and how leading bits become known.
    """
    # TODO: implement
    return top(a.width)


# ============================================================
# UNARY OPERATIONS — Implement these
# ============================================================

def transfer_neg(a):
    """Known-bits transfer for: result = -a (two's complement negation, mod 2^width).

    Hint: -a == ~a + 1
    """
    # TODO: implement
    return top(a.width)


def transfer_not(a):
    """Known-bits transfer for: result = ~a (bitwise complement)."""
    # TODO: implement
    return top(a.width)


# ============================================================
# Do not modify below this line
# ============================================================

TRANSFER_FUNCTIONS = {
    'and': ('binary', transfer_and),
    'or': ('binary', transfer_or),
    'xor': ('binary', transfer_xor),
    'shl': ('binary', transfer_shl),
    'lshr': ('binary', transfer_lshr),
    'ashr': ('binary', transfer_ashr),
    'add': ('binary', transfer_add),
    'sub': ('binary', transfer_sub),
    'mul': ('binary', transfer_mul),
    'neg': ('unary', transfer_neg),
    'not': ('unary', transfer_not),
}
