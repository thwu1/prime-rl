"""
Transfer functions for the KnownBits abstract domain — full solution.

Algorithms:
  add / sub — carry-propagation analysis (LLVM computeForAddCarry)
  mul       — trailing-zero accumulation + range-based leading zeros
  shl/lshr  — join over all concrete shift amounts
  udiv      — range-based leading-zero analysis
"""

from knownbits import KnownBits


# ============================================================
# PROVIDED EXAMPLES — unchanged
# ============================================================

def transfer_and(a: KnownBits, b: KnownBits) -> KnownBits:
    w = a.width
    return KnownBits(w, a.zero_mask | b.zero_mask, a.one_mask & b.one_mask)


def transfer_or(a: KnownBits, b: KnownBits) -> KnownBits:
    w = a.width
    return KnownBits(w, a.zero_mask & b.zero_mask, a.one_mask | b.one_mask)


def transfer_xor(a: KnownBits, b: KnownBits) -> KnownBits:
    w = a.width
    mask = (1 << w) - 1
    known = (a.zero_mask | a.one_mask) & (b.zero_mask | b.one_mask)
    ones = (a.one_mask ^ b.one_mask) & known
    zeros = (~(a.one_mask ^ b.one_mask)) & mask & known
    return KnownBits(w, zeros, ones)


def transfer_not(a: KnownBits) -> KnownBits:
    return KnownBits(a.width, a.one_mask, a.zero_mask)


# ============================================================
# INTERNAL: addition with carry
# ============================================================

def _add_carry(a, b, carry_zero, carry_one):
    """Carry-propagation analysis for a + b + carry.

    *carry_zero*: True  → carry-in is known 0
    *carry_one* : True  → carry-in is known 1

    Uses max/min sum to determine where carries are unambiguous,
    then marks result bits known only where both operands and the
    carry into that position are all known.
    """
    w = a.width
    mask = (1 << w) - 1

    a_max = a.get_max_unsigned()
    a_min = a.get_min_unsigned()
    b_max = b.get_max_unsigned()
    b_min = b.get_min_unsigned()

    # Max sum (determines known-0 result bits)
    sum_hi = (a_max + b_max + (0 if carry_zero else 1)) & mask
    # Min sum (determines known-1 result bits)
    sum_lo = (a_min + b_min + (1 if carry_one else 0)) & mask

    # Extract per-bit carry information from the extreme sums.
    # carry[i] = sum[i] XOR a_bit[i] XOR b_bit[i]
    # ~a XOR ~b = a XOR b, so we can use zero_mask directly.
    carry_kz = (~(sum_hi ^ a.zero_mask ^ b.zero_mask)) & mask
    carry_ko = (sum_lo ^ a.one_mask ^ b.one_mask) & mask

    a_known = (a.zero_mask | a.one_mask) & mask
    b_known = (b.zero_mask | b.one_mask) & mask
    carry_known = (carry_kz | carry_ko) & mask

    known = a_known & b_known & carry_known

    result_zero = (~sum_hi & known) & mask
    result_one = (sum_lo & known) & mask

    return KnownBits(w, result_zero, result_one)


# ============================================================
# IMPLEMENTATIONS
# ============================================================

def transfer_add(a: KnownBits, b: KnownBits) -> KnownBits:
    """Unsigned modular addition via carry-propagation analysis."""
    return _add_carry(a, b, carry_zero=True, carry_one=False)


def transfer_sub(a: KnownBits, b: KnownBits) -> KnownBits:
    """a - b  =  a + NOT(b) + 1."""
    b_not = KnownBits(b.width, b.one_mask, b.zero_mask)
    return _add_carry(a, b_not, carry_zero=False, carry_one=True)


def transfer_mul(a: KnownBits, b: KnownBits) -> KnownBits:
    """Trailing-zero accumulation + range-based leading-zero analysis."""
    w = a.width
    mask = (1 << w) - 1

    # Both fully known → exact answer
    a_full = ((a.zero_mask | a.one_mask) & mask) == mask
    b_full = ((b.zero_mask | b.one_mask) & mask) == mask
    if a_full and b_full:
        return KnownBits.from_constant(w, (a.one_mask * b.one_mask) & mask)

    # Either operand provably zero
    if a.get_max_unsigned() == 0 or b.get_max_unsigned() == 0:
        return KnownBits.from_constant(w, 0)

    # Count trailing known-zero bits
    a_tz = 0
    for i in range(w):
        if (a.zero_mask >> i) & 1:
            a_tz += 1
        else:
            break

    b_tz = 0
    for i in range(w):
        if (b.zero_mask >> i) & 1:
            b_tz += 1
        else:
            break

    total_tz = min(a_tz + b_tz, w)
    result_zero = ((1 << total_tz) - 1) & mask
    result_one = 0

    # Leading zeros when no overflow
    a_max = a.get_max_unsigned()
    b_max = b.get_max_unsigned()
    max_prod = a_max * b_max
    if 0 < max_prod <= mask:
        lz = w - max_prod.bit_length()
        for i in range(w - 1, w - 1 - lz, -1):
            if i >= 0:
                result_zero |= 1 << i

    return KnownBits(w, result_zero & mask, result_one)


def _shl_const(a, shift, w):
    mask = (1 << w) - 1
    if shift >= w:
        return KnownBits.from_constant(w, 0)
    low = (1 << shift) - 1
    return KnownBits(w,
                     ((a.zero_mask << shift) | low) & mask,
                     (a.one_mask << shift) & mask)


def transfer_shl(a: KnownBits, b: KnownBits) -> KnownBits:
    """Join over all concrete shift amounts."""
    w = a.width
    result = None
    for s in b.iterate_concrete_values():
        r = _shl_const(a, s, w)
        result = r if result is None else result.join(r)
    return result if result is not None else KnownBits.top(w)


def _lshr_const(a, shift, w):
    mask = (1 << w) - 1
    if shift >= w:
        return KnownBits.from_constant(w, 0)
    high = mask & ~((1 << (w - shift)) - 1)
    return KnownBits(w,
                     ((a.zero_mask >> shift) | high) & mask,
                     (a.one_mask >> shift) & mask)


def transfer_lshr(a: KnownBits, b: KnownBits) -> KnownBits:
    """Join over all concrete shift amounts."""
    w = a.width
    result = None
    for s in b.iterate_concrete_values():
        r = _lshr_const(a, s, w)
        result = r if result is None else result.join(r)
    return result if result is not None else KnownBits.top(w)


def transfer_udiv(a: KnownBits, b: KnownBits) -> KnownBits:
    """Range-based leading-zero analysis for unsigned division."""
    w = a.width
    mask = (1 << w) - 1

    if b.get_max_unsigned() == 0:
        return KnownBits.from_constant(w, 0)
    if a.get_max_unsigned() == 0:
        return KnownBits.from_constant(w, 0)

    # Both constants
    a_full = ((a.zero_mask | a.one_mask) & mask) == mask
    b_full = ((b.zero_mask | b.one_mask) & mask) == mask
    if a_full and b_full:
        d = b.one_mask
        return KnownBits.from_constant(w, a.one_mask // d if d else 0)

    b_min = max(b.get_min_unsigned(), 1)

    # Divisor always larger than dividend → 0
    if b_min > a.get_max_unsigned():
        return KnownBits.from_constant(w, 0)

    max_result = a.get_max_unsigned() // b_min
    if max_result > mask:
        max_result = mask
    if max_result == 0:
        return KnownBits.from_constant(w, 0)

    # Leading zeros
    result_zero = 0
    lz = w - max_result.bit_length()
    for i in range(w - 1, w - 1 - lz, -1):
        if i >= 0:
            result_zero |= 1 << i

    return KnownBits(w, result_zero & mask, 0)
