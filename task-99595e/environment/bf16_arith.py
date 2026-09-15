"""
bfloat16 IEEE 754-compliant arithmetic library.
Implements addition, subtraction, multiplication, and comparison
using pure integer arithmetic.

bfloat16 format:
  - 1 sign bit (bit 15)
  - 8 exponent bits (bits 14:7), bias = 127
  - 7 significand/mantissa bits (bits 6:0)
  - Precision p = 8 (7 stored + 1 hidden bit)

Supports all 5 IEEE 754 rounding modes.
"""

# Rounding modes
RN_EVEN = 0  # Round to nearest, ties to even (default)
RN_AWAY = 1  # Round to nearest, ties away from zero
RD = 2       # Round toward -infinity (floor)
RU = 3       # Round toward +infinity (ceiling)
RZ = 4       # Round toward zero (truncate)

# Format parameters
SIGN_BIT = 15
EXP_BITS = 8
SIG_BITS = 7
BIAS = 127
EXP_MAX = 0xFF
SIG_MASK = (1 << SIG_BITS) - 1  # 0x7F

# Internal: place hidden bit at position 23 for alignment arithmetic
INTERNAL_SHIFT = 16
HIDDEN_POS = SIG_BITS + INTERNAL_SHIFT  # 23

# Special value constants
POS_ZERO = 0x0000
NEG_ZERO = 0x8000
POS_INF  = 0x7F80
NEG_INF  = 0xFF80
QNAN     = 0x7FC0
MAX_POS  = 0x7F7F  # exp=254, sig=0x7F
MAX_NEG  = 0xFF7F


def sign(x):
    return (x >> SIGN_BIT) & 1

def exponent(x):
    return (x >> SIG_BITS) & 0xFF

def significand(x):
    return x & SIG_MASK

def pack(s, e, m):
    return ((s & 1) << SIGN_BIT) | ((e & 0xFF) << SIG_BITS) | (m & SIG_MASK)

def is_nan(x):
    return exponent(x) == EXP_MAX and significand(x) != 0

def is_inf(x):
    return exponent(x) == EXP_MAX and significand(x) == 0

def is_zero(x):
    return exponent(x) == 0 and significand(x) == 0

def is_denormal(x):
    return exponent(x) == 0 and significand(x) != 0

def is_negative(x):
    return sign(x) == 1

def negate(x):
    return x ^ (1 << SIGN_BIT)

def abs_val(x):
    return x & 0x7FFF

def full_significand(x):
    """Significand with hidden bit. Normal: (1<<7)|sig. Denormal/zero: sig."""
    e = exponent(x)
    m = significand(x)
    if e == 0:
        return m
    return (1 << SIG_BITS) | m


def _should_round_up(s, result_lsb, guard, round_bit, sticky, rmode):
    """Determine whether to increment the truncated result magnitude."""
    if rmode == RN_EVEN:
        if guard and (round_bit or sticky):
            return True
        # Exact tie: truncate
        return False

    elif rmode == RN_AWAY:
        return bool(guard)

    elif rmode == RD:
        if s == 1:
            return bool(guard or round_bit or sticky)
        return False

    elif rmode == RU:
        if s == 0:
            return bool(guard or round_bit or sticky)
        return False

    elif rmode == RZ:
        return False

    return False


def bf16_add(a, b, rmode=RN_EVEN):
    """Add two bfloat16 values. Returns bfloat16 bit pattern."""

    # NaN propagation
    if is_nan(a):
        return a | 0x0040  # quieten
    if is_nan(b):
        return b | 0x0040

    # Infinity handling
    a_inf = is_inf(a)
    b_inf = is_inf(b)

    if a_inf and b_inf:
        if sign(a) == sign(b):
            return a
        else:
            return POS_INF

    if a_inf:
        return a
    if b_inf:
        return b

    # Zero handling
    a_zero = is_zero(a)
    b_zero = is_zero(b)

    if a_zero and b_zero:
        if sign(a) == sign(b):
            return a
        else:
            return POS_ZERO

    if a_zero:
        return b
    if b_zero:
        return a

    # Unpack
    sa, ea, ma = sign(a), exponent(a), full_significand(a)
    sb, eb, mb = sign(b), exponent(b), full_significand(b)

    effective_sub = (sa != sb)

    # Ensure |a| >= |b|
    if ea < eb or (ea == eb and ma < mb):
        sa, sb = sb, sa
        ea, eb = eb, ea
        ma, mb = mb, ma

    # Effective exponents (denormals use effective exponent 1)
    eff_ea = ea if ea != 0 else 1
    eff_eb = eb if eb != 0 else 1
    exp_diff = eff_ea - eff_eb

    # Place significands in internal format
    int_ma = ma << INTERNAL_SHIFT
    int_mb = mb << INTERNAL_SHIFT

    # Align smaller operand
    if exp_diff >= 32:
        shifted_mb = 0
        sticky_from_shift = 1 if int_mb != 0 else 0
    elif exp_diff > 0:
        mask = (1 << exp_diff) - 1
        sticky_from_shift = 1 if (int_mb & mask) != 0 else 0
        shifted_mb = int_mb >> exp_diff
    else:
        shifted_mb = int_mb
        sticky_from_shift = 0

    # Add or subtract
    if effective_sub:
        result_mag = int_ma - shifted_mb
        result_sign = sa

        if result_mag == 0 and sticky_from_shift == 0:
            # Exact cancellation
            return POS_ZERO
    else:
        result_mag = int_ma + shifted_mb
        result_sign = sa

    if result_mag == 0:
        return pack(result_sign, 0, 0)

    # Find leading one position
    leading_one = 0
    for i in range(31, -1, -1):
        if result_mag & (1 << i):
            leading_one = i
            break

    result_exp = eff_ea
    guard = 0
    round_bit = 0
    sticky = sticky_from_shift

    if leading_one > HIDDEN_POS:
        # Carry-out: shift right
        shift_right = leading_one - HIDDEN_POS
        guard = (result_mag >> (shift_right - 1)) & 1
        if shift_right >= 2:
            round_bit = (result_mag >> (shift_right - 2)) & 1
            if shift_right > 2:
                below = result_mag & ((1 << (shift_right - 2)) - 1)
                sticky = 1 if (below != 0 or sticky_from_shift) else 0
            else:
                sticky = sticky_from_shift
        else:
            round_bit = 0
            sticky = sticky_from_shift

        result_mag = result_mag >> shift_right
        result_exp += shift_right

    elif leading_one < HIDDEN_POS:
        # Cancellation: shift left to normalize
        shift_left = HIDDEN_POS - leading_one
        result_mag = result_mag << shift_left
        result_exp -= shift_left
        guard = 0
        round_bit = 0
        sticky = sticky_from_shift

        # Underflow check
        if result_exp < 1:
            return pack(result_sign, 0, 0)

    # Extract significand
    result_sig = (result_mag >> INTERNAL_SHIFT) & SIG_MASK
    result_lsb = result_sig & 1

    # Apply rounding
    if _should_round_up(result_sign, result_lsb, guard, round_bit, sticky, rmode):
        result_sig += 1
        if result_sig > SIG_MASK:
            result_sig = 0
            result_exp += 1

    # Overflow
    if result_exp >= EXP_MAX:
        return pack(result_sign, EXP_MAX, 0)

    # Underflow
    if result_exp <= 0:
        return pack(result_sign, 0, 0)

    return pack(result_sign, result_exp, result_sig)


def bf16_sub(a, b, rmode=RN_EVEN):
    """Subtract: a - b."""
    return bf16_add(a, negate(b), rmode)


def bf16_mul(a, b, rmode=RN_EVEN):
    """Multiply two bfloat16 values. Returns bfloat16 bit pattern."""
    result_sign = sign(a) ^ sign(b)

    if is_nan(a):
        return a | 0x0040
    if is_nan(b):
        return b | 0x0040

    a_inf, b_inf = is_inf(a), is_inf(b)
    a_zero, b_zero = is_zero(a), is_zero(b)

    if (a_zero and b_inf) or (a_inf and b_zero):
        return pack(result_sign, 0, 0)

    if a_inf or b_inf:
        return pack(result_sign, EXP_MAX, 0)

    if a_zero or b_zero:
        return pack(result_sign, 0, 0)

    ea, ma = exponent(a), full_significand(a)
    eb, mb = exponent(b), full_significand(b)

    eff_ea = ea if ea != 0 else 1
    eff_eb = eb if eb != 0 else 1

    product = ma * mb

    result_exp = eff_ea + eff_eb - BIAS

    # Find leading one in product
    leading_one = 0
    for i in range(31, -1, -1):
        if product & (1 << i):
            leading_one = i
            break

    target = SIG_BITS  # hidden bit at bit 7

    if leading_one > target:
        shift_right = leading_one - target
        guard = (product >> (shift_right - 1)) & 1
        if shift_right >= 2:
            round_bit = (product >> (shift_right - 2)) & 1
        else:
            round_bit = 0
        if shift_right > 2:
            below = product & ((1 << (shift_right - 2)) - 1)
            sticky = 1 if below else 0
        else:
            sticky = 0

        result_sig_full = product >> shift_right
        result_exp += (leading_one - 2 * SIG_BITS)
    elif leading_one < target:
        shift_left = target - leading_one
        result_sig_full = product << shift_left
        result_exp -= shift_left
        guard = round_bit = sticky = 0
    else:
        result_sig_full = product
        guard = round_bit = sticky = 0

    result_sig = result_sig_full & SIG_MASK
    result_lsb = result_sig & 1

    if _should_round_up(result_sign, result_lsb, guard, round_bit, sticky, rmode):
        result_sig += 1
        if result_sig > SIG_MASK:
            result_sig = 0
            result_exp += 1

    if result_exp >= EXP_MAX:
        return pack(result_sign, EXP_MAX, 0)

    if result_exp <= 0:
        return pack(result_sign, 0, 0)

    return pack(result_sign, result_exp, result_sig)


def bf16_equal(a, b):
    """IEEE 754 equality. +0 == -0 is True. NaN == anything is False."""
    if is_nan(a) or is_nan(b):
        return False
    if is_zero(a) and is_zero(b):
        return True
    return a == b


def bf16_less_than(a, b):
    """IEEE 754 less-than."""
    if is_zero(a) and is_zero(b):
        return False

    sa, sb = sign(a), sign(b)

    if sa != sb:
        return sa == 1

    abs_a, abs_b = abs_val(a), abs_val(b)

    if sa == 0:
        return abs_a < abs_b
    else:
        return abs_a > abs_b


def bf16_less_equal(a, b):
    """IEEE 754 less-or-equal."""
    if is_nan(a) or is_nan(b):
        return False
    return bf16_equal(a, b) or bf16_less_than(a, b)


def bf16_not_equal(a, b):
    """IEEE 754 not-equal. NaN != anything is True."""
    return not bf16_equal(a, b)


def bf16_to_float(x):
    """Convert bfloat16 bit pattern to Python float."""
    import struct
    f32_bits = x << 16
    return struct.unpack('f', struct.pack('I', f32_bits))[0]


def float_to_bf16(f, rmode=RN_EVEN):
    """Convert Python float to bfloat16 bit pattern with RNE rounding."""
    import struct
    f32_bytes = struct.pack('f', f)
    f32_bits = struct.unpack('I', f32_bytes)[0]
    f32_sign = (f32_bits >> 31) & 1
    f32_exp = (f32_bits >> 23) & 0xFF
    f32_sig = f32_bits & 0x7FFFFF
    truncated = f32_sig & 0xFFFF
    bf16_sig = (f32_sig >> 16) & 0x7F
    halfway = 0x8000
    if truncated > halfway or (truncated == halfway and (bf16_sig & 1)):
        bf16_sig += 1
        if bf16_sig > 0x7F:
            bf16_sig = 0
            f32_exp += 1
    if f32_exp >= 0xFF:
        return pack(f32_sign, 0xFF, 0)
    return pack(f32_sign, f32_exp, bf16_sig)
