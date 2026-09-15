"""TCP sequence number arithmetic with wrapping at 2^32.

Implements RFC 793 / RFC 1323 sequence number comparison logic,
handling the circular nature of the 32-bit sequence number space.
"""

SEQUENCE_SPACE = 1 << 32  # 2^32
HALF_SPACE = 1 << 31      # 2^31


def wrap32(n):
    """Constrain a number to the 32-bit unsigned range [0, 2^32)."""
    return n & 0xFFFFFFFF


def wrapping_add(a, b):
    """Add two values with wrapping at 2^32."""
    return (a + b) & 0xFFFFFFFF


def wrapping_sub(a, b):
    """Subtract with wrapping at 2^32."""
    return (a - b) & 0xFFFFFFFF


def wrapping_lt(lhs, rhs):
    """Check if lhs < rhs in wrapping sequence space.

    Per RFC 1323: a sequence number is considered 'less than' another
    if the unsigned distance (lhs - rhs) mod 2^32 is greater than 2^31,
    meaning lhs is in the 'lower half' of the circular space relative
    to rhs.
    """
    return wrapping_sub(lhs, rhs) > HALF_SPACE


def is_between_wrapped(start, x, end):
    """Check if x is strictly between start and end in wrapping space.

    Returns True iff start < x < end (all comparisons wrapping).
    This is an open interval -- neither endpoint is included.
    """
    return wrapping_lt(start, x) and wrapping_lt(x, end)
