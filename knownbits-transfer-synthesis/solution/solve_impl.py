"""
Reference implementation of KnownBits transfer functions.
Based on techniques used in LLVM's ValueTracking (KnownBits::computeFor*).
"""

import sys
sys.path.insert(0, '/app')

from knownbits import KnownBits, top, constant, meet, get_min_unsigned, get_max_unsigned


def transfer_and(a, b):
    w = a.width
    # Bit i is known-zero if EITHER input has bit i known-zero
    # Bit i is known-one if BOTH inputs have bit i known-one
    new_zero = a.zero_mask | b.zero_mask
    new_one = a.one_mask & b.one_mask
    return KnownBits(w, new_zero, new_one)


def transfer_or(a, b):
    w = a.width
    # Bit i is known-one if EITHER input has bit i known-one
    # Bit i is known-zero if BOTH inputs have bit i known-zero
    new_one = a.one_mask | b.one_mask
    new_zero = a.zero_mask & b.zero_mask
    return KnownBits(w, new_zero, new_one)


def transfer_xor(a, b):
    w = a.width
    full = (1 << w) - 1
    # Bit i is known if both inputs have bit i known
    a_known = a.zero_mask | a.one_mask
    b_known = b.zero_mask | b.one_mask
    both_known = a_known & b_known

    # For known bits, XOR them
    xor_ones = (a.one_mask ^ b.one_mask) & both_known
    xor_zeros = (~(a.one_mask ^ b.one_mask)) & full & both_known

    return KnownBits(w, xor_zeros, xor_ones)


def transfer_shl(a, b):
    w = a.width
    full = (1 << w) - 1

    # If shift amount is fully known
    if b.num_unknown == 0:
        amt = b.one_mask
        if amt >= w:
            return constant(w, 0)
        new_zero = ((a.zero_mask << amt) | ((1 << amt) - 1)) & full
        new_one = (a.one_mask << amt) & full
        return KnownBits(w, new_zero, new_one)

    # Unknown shift: meet over all possible shift amounts
    min_shift = get_min_unsigned(b)
    max_shift = get_max_unsigned(b)

    # Start with bottom (all known) and widen
    result_zero = full
    result_one = full

    for s in range(min_shift, min(max_shift + 1, w + 1)):
        if not b.contains(s):
            continue
        if s >= w:
            # result is 0
            result_zero &= full
            result_one &= 0
        else:
            shifted_zero = ((a.zero_mask << s) | ((1 << s) - 1)) & full
            shifted_one = (a.one_mask << s) & full
            # Join: a bit is known only if known in ALL possibilities
            result_zero &= shifted_zero
            result_one &= shifted_one

    # Also consider shift amounts >= w that map to 0
    for s in range(max(min_shift, w), max_shift + 1):
        if b.contains(s):
            result_zero &= full
            result_one &= 0
            break

    if result_zero & result_one:
        return top(w)
    return KnownBits(w, result_zero, result_one)


def transfer_lshr(a, b):
    w = a.width
    full = (1 << w) - 1

    if b.num_unknown == 0:
        amt = b.one_mask
        if amt >= w:
            return constant(w, 0)
        new_zero = (a.zero_mask >> amt) | (full & ~((1 << (w - amt)) - 1))
        new_one = a.one_mask >> amt
        return KnownBits(w, new_zero, new_one)

    min_shift = get_min_unsigned(b)
    max_shift = get_max_unsigned(b)

    result_zero = full
    result_one = full

    for s in range(min_shift, min(max_shift + 1, w + 1)):
        if not b.contains(s):
            continue
        if s >= w:
            result_zero &= full
            result_one &= 0
        else:
            shifted_zero = (a.zero_mask >> s) | (full & ~((1 << (w - s)) - 1))
            shifted_one = a.one_mask >> s
            result_zero &= shifted_zero
            result_one &= shifted_one

    for s in range(max(min_shift, w), max_shift + 1):
        if b.contains(s):
            result_zero &= full
            result_one &= 0
            break

    if result_zero & result_one:
        return top(w)
    return KnownBits(w, result_zero, result_one)


def transfer_ashr(a, b):
    w = a.width
    full = (1 << w) - 1
    sign_bit = 1 << (w - 1)

    if b.num_unknown == 0:
        amt = b.one_mask
        if amt >= w:
            amt = w - 1  # clamp
        base_zero = a.zero_mask >> amt
        base_one = a.one_mask >> amt
        # Sign extension: if sign bit is known
        sign_fill_mask = full & ~((1 << (w - amt)) - 1)
        if a.zero_mask & sign_bit:
            # sign is known-zero, fill top with zeros
            base_zero |= sign_fill_mask
        elif a.one_mask & sign_bit:
            # sign is known-one, fill top with ones
            base_one |= sign_fill_mask
        # else sign unknown, top bits unknown (neither set)
        return KnownBits(w, base_zero & ~base_one, base_one & ~base_zero)

    min_shift = get_min_unsigned(b)
    max_shift = get_max_unsigned(b)

    result_zero = full
    result_one = full

    for s in range(min_shift, min(max_shift + 1, w)):
        if not b.contains(s):
            continue
        amt = s if s < w else w - 1
        base_zero = a.zero_mask >> amt
        base_one = a.one_mask >> amt
        sign_fill_mask = full & ~((1 << (w - amt)) - 1) if amt > 0 else 0
        if a.zero_mask & sign_bit:
            base_zero |= sign_fill_mask
        elif a.one_mask & sign_bit:
            base_one |= sign_fill_mask
        else:
            pass  # sign unknown — no fill
        cand_zero = base_zero & ~base_one
        cand_one = base_one & ~base_zero
        result_zero &= cand_zero
        result_one &= cand_one

    for s in range(max(min_shift, w), max_shift + 1):
        if b.contains(s):
            amt = w - 1
            base_zero = a.zero_mask >> amt
            base_one = a.one_mask >> amt
            sign_fill_mask = full & ~((1 << (w - amt)) - 1)
            if a.zero_mask & sign_bit:
                base_zero |= sign_fill_mask
            elif a.one_mask & sign_bit:
                base_one |= sign_fill_mask
            cand_zero = base_zero & ~base_one
            cand_one = base_one & ~base_zero
            result_zero &= cand_zero
            result_one &= cand_one
            break

    if result_zero & result_one:
        return top(w)
    return KnownBits(w, result_zero, result_one)


def transfer_add(a, b):
    """LLVM-style carry-chain analysis for addition."""
    w = a.width
    full = (1 << w) - 1

    # Compute possible sum when both are at their extremes
    # PossibleSumZero: result when we get the max possible sum (to find which bits COULD be 0)
    # We use: for each result bit, it's known if the carry into that bit is known
    # and the input bits are known.

    # LLVM approach:
    # possible_sum_one = min(a) + min(b) — minimum sum tells us which bits MUST be 1
    # possible_sum_zero = max(a) + max(b) — maximum sum tells us which bits MUST be 0

    max_a = get_max_unsigned(a)
    max_b = get_max_unsigned(b)
    min_a = get_min_unsigned(a)
    min_b = get_min_unsigned(b)

    possible_sum_zero = (max_a + max_b) & full
    possible_sum_one = (min_a + min_b) & full

    # Carry analysis: XOR of operand known bits with sums reveals carry information
    a_known = a.zero_mask | a.one_mask
    b_known = b.zero_mask | b.one_mask

    carry_known_zero = (~(possible_sum_zero ^ a.zero_mask ^ b.zero_mask)) & full
    carry_known_one = (possible_sum_one ^ a.one_mask ^ b.one_mask) & full

    carry_known = carry_known_zero | carry_known_one
    known = a_known & b_known & carry_known

    new_zero = (~possible_sum_zero) & full & known
    new_one = possible_sum_one & known

    if new_zero & new_one:
        new_zero = new_zero & ~new_one  # resolve conflicts conservatively
    return KnownBits(w, new_zero, new_one)


def transfer_not(a):
    w = a.width
    return KnownBits(w, a.one_mask, a.zero_mask)


def transfer_neg(a):
    """neg(a) = ~a + 1, compose NOT and ADD transfer functions."""
    w = a.width
    not_a = transfer_not(a)
    one = constant(w, 1)
    return transfer_add(not_a, one)


def transfer_sub(a, b):
    """sub(a,b) = a + ~b + 1 = a + neg(b)"""
    w = a.width
    neg_b = transfer_neg(b)
    return transfer_add(a, neg_b)


def transfer_mul(a, b):
    """Multiplication: track trailing known-zero bits."""
    w = a.width
    full = (1 << w) - 1

    # Count trailing known-zero bits in each operand
    trailing_zeros_a = 0
    for i in range(w):
        if (a.zero_mask >> i) & 1:
            trailing_zeros_a += 1
        else:
            break

    trailing_zeros_b = 0
    for i in range(w):
        if (b.zero_mask >> i) & 1:
            trailing_zeros_b += 1
        else:
            break

    total_trailing_zeros = min(trailing_zeros_a + trailing_zeros_b, w)

    # Known-zero from trailing zeros
    if total_trailing_zeros >= w:
        return constant(w, 0)

    new_zero = (1 << total_trailing_zeros) - 1

    # If both are constants, we know the exact result
    if a.num_unknown == 0 and b.num_unknown == 0:
        result = (a.one_mask * b.one_mask) & full
        return constant(w, result)

    # Use range analysis for additional leading-zero information
    max_a = get_max_unsigned(a)
    max_b = get_max_unsigned(b)
    max_prod = max_a * max_b

    # Find leading zeros from max product
    if max_prod == 0:
        return constant(w, 0)

    if max_prod < (1 << w):
        # Product fits in width bits, check for leading zeros
        for i in range(w - 1, -1, -1):
            if max_prod < (1 << i):
                new_zero |= (1 << i)
            else:
                break

    new_one = 0  # Hard to determine known-one bits for mul in general

    return KnownBits(w, new_zero & full, new_one & full)


def write_solution():
    """Write the solution transfers.py to /app/transfers.py."""
"""
Transfer Functions for the KnownBits Abstract Domain — SOLUTION
"""

from knownbits import KnownBits, top, constant, meet
from knownbits import get_min_unsigned, get_max_unsigned


def transfer_and(a, b):
    w = a.width
    new_zero = a.zero_mask | b.zero_mask
    new_one = a.one_mask & b.one_mask
    return KnownBits(w, new_zero, new_one)


def transfer_or(a, b):
    w = a.width
    new_one = a.one_mask | b.one_mask
    new_zero = a.zero_mask & b.zero_mask
    return KnownBits(w, new_zero, new_one)


def transfer_xor(a, b):
    w = a.width
    full = (1 << w) - 1
    a_known = a.zero_mask | a.one_mask
    b_known = b.zero_mask | b.one_mask
    both_known = a_known & b_known
    xor_ones = (a.one_mask ^ b.one_mask) & both_known
    xor_zeros = (~(a.one_mask ^ b.one_mask)) & full & both_known
    return KnownBits(w, xor_zeros, xor_ones)


def transfer_shl(a, b):
    w = a.width
    full = (1 << w) - 1
    if b.num_unknown == 0:
        amt = b.one_mask
        if amt >= w:
            return constant(w, 0)
        new_zero = ((a.zero_mask << amt) | ((1 << amt) - 1)) & full
        new_one = (a.one_mask << amt) & full
        return KnownBits(w, new_zero, new_one)
    min_shift = get_min_unsigned(b)
    max_shift = get_max_unsigned(b)
    result_zero = full
    result_one = full
    for s in range(min_shift, min(max_shift + 1, w + 1)):
        if not b.contains(s):
            continue
        if s >= w:
            result_zero &= full
            result_one &= 0
        else:
            shifted_zero = ((a.zero_mask << s) | ((1 << s) - 1)) & full
            shifted_one = (a.one_mask << s) & full
            result_zero &= shifted_zero
            result_one &= shifted_one
    for s in range(max(min_shift, w), max_shift + 1):
        if b.contains(s):
            result_zero &= full
            result_one &= 0
            break
    if result_zero & result_one:
        return top(w)
    return KnownBits(w, result_zero, result_one)


def transfer_lshr(a, b):
    w = a.width
    full = (1 << w) - 1
    if b.num_unknown == 0:
        amt = b.one_mask
        if amt >= w:
            return constant(w, 0)
        new_zero = (a.zero_mask >> amt) | (full & ~((1 << (w - amt)) - 1))
        new_one = a.one_mask >> amt
        return KnownBits(w, new_zero, new_one)
    min_shift = get_min_unsigned(b)
    max_shift = get_max_unsigned(b)
    result_zero = full
    result_one = full
    for s in range(min_shift, min(max_shift + 1, w + 1)):
        if not b.contains(s):
            continue
        if s >= w:
            result_zero &= full
            result_one &= 0
        else:
            shifted_zero = (a.zero_mask >> s) | (full & ~((1 << (w - s)) - 1))
            shifted_one = a.one_mask >> s
            result_zero &= shifted_zero
            result_one &= shifted_one
    for s in range(max(min_shift, w), max_shift + 1):
        if b.contains(s):
            result_zero &= full
            result_one &= 0
            break
    if result_zero & result_one:
        return top(w)
    return KnownBits(w, result_zero, result_one)


def transfer_ashr(a, b):
    w = a.width
    full = (1 << w) - 1
    sign_bit = 1 << (w - 1)
    if b.num_unknown == 0:
        amt = b.one_mask
        if amt >= w:
            amt = w - 1
        base_zero = a.zero_mask >> amt
        base_one = a.one_mask >> amt
        sign_fill_mask = full & ~((1 << (w - amt)) - 1) if amt > 0 else 0
        if a.zero_mask & sign_bit:
            base_zero |= sign_fill_mask
        elif a.one_mask & sign_bit:
            base_one |= sign_fill_mask
        return KnownBits(w, base_zero & ~base_one, base_one & ~base_zero)
    min_shift = get_min_unsigned(b)
    max_shift = get_max_unsigned(b)
    result_zero = full
    result_one = full
    for s in range(min_shift, min(max_shift + 1, w)):
        if not b.contains(s):
            continue
        amt = s if s < w else w - 1
        base_zero = a.zero_mask >> amt
        base_one = a.one_mask >> amt
        sign_fill_mask = full & ~((1 << (w - amt)) - 1) if amt > 0 else 0
        if a.zero_mask & sign_bit:
            base_zero |= sign_fill_mask
        elif a.one_mask & sign_bit:
            base_one |= sign_fill_mask
        cand_zero = base_zero & ~base_one
        cand_one = base_one & ~base_zero
        result_zero &= cand_zero
        result_one &= cand_one
    for s in range(max(min_shift, w), max_shift + 1):
        if b.contains(s):
            amt = w - 1
            base_zero = a.zero_mask >> amt
            base_one = a.one_mask >> amt
            sign_fill_mask = full & ~((1 << (w - amt)) - 1)
            if a.zero_mask & sign_bit:
                base_zero |= sign_fill_mask
            elif a.one_mask & sign_bit:
                base_one |= sign_fill_mask
            cand_zero = base_zero & ~base_one
            cand_one = base_one & ~base_zero
            result_zero &= cand_zero
            result_one &= cand_one
            break
    if result_zero & result_one:
        return top(w)
    return KnownBits(w, result_zero, result_one)


def transfer_add(a, b):
    w = a.width
    full = (1 << w) - 1
    max_a = get_max_unsigned(a)
    max_b = get_max_unsigned(b)
    min_a = get_min_unsigned(a)
    min_b = get_min_unsigned(b)
    possible_sum_zero = (max_a + max_b) & full
    possible_sum_one = (min_a + min_b) & full
    a_known = a.zero_mask | a.one_mask
    b_known = b.zero_mask | b.one_mask
    carry_known_zero = (~(possible_sum_zero ^ a.zero_mask ^ b.zero_mask)) & full
    carry_known_one = (possible_sum_one ^ a.one_mask ^ b.one_mask) & full
    carry_known = carry_known_zero | carry_known_one
    known = a_known & b_known & carry_known
    new_zero = (~possible_sum_zero) & full & known
    new_one = possible_sum_one & known
    if new_zero & new_one:
        new_zero = new_zero & ~new_one
    return KnownBits(w, new_zero, new_one)


def transfer_not(a):
    w = a.width
    return KnownBits(w, a.one_mask, a.zero_mask)


def transfer_neg(a):
    w = a.width
    not_a = transfer_not(a)
    one = constant(w, 1)
    return transfer_add(not_a, one)


def transfer_sub(a, b):
    neg_b = transfer_neg(b)
    return transfer_add(a, neg_b)


def transfer_mul(a, b):
    w = a.width
    full = (1 << w) - 1
    trailing_zeros_a = 0
    for i in range(w):
        if (a.zero_mask >> i) & 1:
            trailing_zeros_a += 1
        else:
            break
    trailing_zeros_b = 0
    for i in range(w):
        if (b.zero_mask >> i) & 1:
            trailing_zeros_b += 1
        else:
            break
    total_trailing_zeros = min(trailing_zeros_a + trailing_zeros_b, w)
    if total_trailing_zeros >= w:
        return constant(w, 0)
    new_zero = (1 << total_trailing_zeros) - 1
    if a.num_unknown == 0 and b.num_unknown == 0:
        result = (a.one_mask * b.one_mask) & full
        return constant(w, result)
    max_a = get_max_unsigned(a)
    max_b = get_max_unsigned(b)
    max_prod = max_a * max_b
    if max_prod == 0:
        return constant(w, 0)
    if max_prod < (1 << w):
        for i in range(w - 1, -1, -1):
            if max_prod < (1 << i):
                new_zero |= (1 << i)
            else:
                break
    new_one = 0
    return KnownBits(w, new_zero & full, new_one & full)


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
'''
    with open('/app/transfers.py', 'w') as f:
        f.write(solution)


if __name__ == '__main__':
    write_solution()
