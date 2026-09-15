"""
Tristate Number (tnum) abstract domain for BPF verifier register tracking.

A tnum represents a set of 64-bit unsigned integers:
  - value: bits known to be 1 (known-one bits)
  - mask:  bits with unknown value

Invariant: value & mask == 0

Concretization: gamma(Tnum(v, m)) = { n : n & ~m == v }
"""


BITS = 64
MASK = (1 << BITS) - 1


class Tnum:
    __slots__ = ('value', 'mask')

    def __init__(self, value, mask):
        self.value = value & MASK
        self.mask = mask & MASK
        if self.value & self.mask != 0:
            raise ValueError(
                f"Invalid tnum: value=0x{self.value:x} mask=0x{self.mask:x} "
                f"overlap=0x{self.value & self.mask:x}"
            )

    def __repr__(self):
        return f"Tnum(0x{self.value:x}, 0x{self.mask:x})"

    def __eq__(self, other):
        if other is None:
            return False
        return self.value == other.value and self.mask == other.mask

    def __hash__(self):
        return hash((self.value, self.mask))

    def contains(self, n):
        """Return True if concrete value n is in gamma(self)."""
        return (n & ~self.mask & MASK) == self.value


def tnum_const(n):
    """Tnum representing exactly the value n."""
    return Tnum(n & MASK, 0)


def tnum_unknown():
    """Tnum representing any 64-bit value."""
    return Tnum(0, MASK)


def tnum_and(a, b):
    """Abstract bitwise AND."""
    alpha = a.value | a.mask
    beta = b.value | b.mask
    v = a.value & b.value
    return Tnum(v, alpha & beta & ~v & MASK)


def tnum_or(a, b):
    """Abstract bitwise OR."""
    v = a.value | b.value
    mu = (a.mask | b.mask) & ~v & MASK
    return Tnum(v, mu)


def tnum_xor(a, b):
    """Abstract bitwise XOR."""
    v = a.value ^ b.value
    mu = a.mask | b.mask
    return Tnum(v & ~mu & MASK, mu)


def tnum_add(a, b):
    """Abstract addition."""
    sm = (a.mask + b.mask) & MASK
    sv = (a.value + b.value) & MASK
    sigma = (sm + sv) & MASK
    chi = sigma ^ sm
    mu = chi | a.mask | b.mask
    return Tnum(sv & ~mu & MASK, mu & MASK)


def tnum_sub(a, b):
    """Abstract subtraction."""
    dv = (a.value - b.value) & MASK
    alpha = (dv + a.mask) & MASK
    beta = (dv - b.mask) & MASK
    chi = alpha ^ beta
    mu = chi | a.mask | b.mask
    return Tnum(dv & ~mu & MASK, mu & MASK)


def tnum_lshift(a, shift):
    """Left shift by known constant."""
    if shift >= BITS:
        return tnum_const(0)
    return Tnum((a.value << shift) & MASK, a.mask)


def tnum_rshift(a, shift):
    """Logical right shift by known constant."""
    if shift >= BITS:
        return tnum_const(0)
    return Tnum((a.value >> shift) & MASK, (a.mask >> shift) & MASK)


def tnum_cast(a, size_bytes):
    """Cast to smaller unsigned type (size in bytes)."""
    if size_bytes >= 8:
        return Tnum(a.value, a.mask)
    cmask = (1 << (size_bytes * 8)) - 1
    return Tnum(a.value & cmask, a.mask & cmask)


def tnum_intersect(a, b):
    """
    Meet / intersection of two tnum constraints.
    Returns Tnum c with gamma(c) = gamma(a) & gamma(b),
    or None if the intersection is empty (bottom).
    """
    v = a.value | b.value
    mu = a.mask & b.mask
    return Tnum(v & ~mu & MASK, mu & MASK)


def tnum_mul(a, b):
    """Abstract multiplication. Not yet implemented."""
    return tnum_unknown()


def tnum_range(min_val, max_val):
    """Tightest tnum containing [min_val, max_val]. Not yet implemented."""
    return tnum_unknown()
