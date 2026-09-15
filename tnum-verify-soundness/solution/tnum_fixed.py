"""
Tristate Number (tnum) abstract domain for BPF verifier register tracking.
Fixed version: all bugs corrected, missing operations implemented.

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
    """Abstract addition. FIX: chi uses sv, not sm."""
    sm = (a.mask + b.mask) & MASK
    sv = (a.value + b.value) & MASK
    sigma = (sm + sv) & MASK
    chi = sigma ^ sv
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
    """Left shift by known constant. FIX: shift mask along with value."""
    if shift >= BITS:
        return tnum_const(0)
    return Tnum((a.value << shift) & MASK, (a.mask << shift) & MASK)


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
    FIX: detect conflicts where known bits disagree.
    """
    v = a.value | b.value
    mu = a.mask & b.mask
    conflict = (a.value ^ b.value) & ~a.mask & ~b.mask
    if conflict:
        return None
    return Tnum(v & ~mu & MASK, mu & MASK)


def tnum_mul(a, b):
    """Abstract multiplication using schoolbook method in the abstract domain."""
    acc = Tnum(0, 0)
    cur_a_val = a.value
    cur_a_mask = a.mask
    cur_b_val = b.value
    cur_b_mask = b.mask
    while cur_a_val or cur_a_mask:
        if cur_a_val & 1:
            acc = tnum_add(acc, Tnum(cur_b_val & MASK, cur_b_mask & MASK))
        elif cur_a_mask & 1:
            acc = tnum_add(acc, Tnum(0, (cur_b_mask | cur_b_val) & MASK))
        cur_a_val = (cur_a_val >> 1) & MASK
        cur_a_mask = (cur_a_mask >> 1) & MASK
        cur_b_val = (cur_b_val << 1) & MASK
        cur_b_mask = (cur_b_mask << 1) & MASK
    return acc


def tnum_range(min_val, max_val):
    """Tightest tnum containing all values in [min_val, max_val]."""
    if min_val > max_val:
        return None
    chi = min_val ^ max_val
    if chi == 0:
        return tnum_const(min_val)
    bits = chi.bit_length()
    mask = (1 << bits) - 1
    value = min_val & ~mask & MASK
    return Tnum(value, mask & MASK)
