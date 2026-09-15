#!/usr/bin/env python3
"""
Solution: writes a complete bfloat16 implementation to /app/bf16.py.

Uses Python's fractions.Fraction for exact rational intermediate arithmetic,
then rounds to bfloat16 using the specified IEEE 754 rounding mode.
"""


IMPLEMENTATION = r'''"""
BFloat16 floating-point arithmetic library.

All functions operate on 16-bit integers representing bfloat16 values.
Rounding modes: "RNE", "RNA", "RZ", "RU", "RD"
"""

from fractions import Fraction
import math

# Format constants
BF16_SIGN_BITS = 1
BF16_EXP_BITS = 8
BF16_MAN_BITS = 7
BF16_BIAS = 127
BF16_EXP_MAX = 255
BF16_MAN_MAX = 127

# Special values
BF16_POS_ZERO = 0x0000
BF16_NEG_ZERO = 0x8000
BF16_POS_INF = 0x7F80
BF16_NEG_INF = 0xFF80
BF16_QNAN = 0x7FC0
BF16_MAX_NORMAL = 0x7F7F
BF16_MIN_NORMAL = 0x0080

ROUNDING_MODES = ("RNE", "RNA", "RZ", "RU", "RD")


def bf16_unpack(raw):
    raw = raw & 0xFFFF
    sign = (raw >> 15) & 1
    exp = (raw >> 7) & 0xFF
    man = raw & 0x7F
    return (sign, exp, man)


def bf16_pack(sign, exp, man):
    return ((sign & 1) << 15) | ((exp & 0xFF) << 7) | (man & 0x7F)


def bf16_classify(raw):
    _, exp, man = bf16_unpack(raw)
    if exp == 0xFF:
        return "nan" if man != 0 else "infinity"
    if exp == 0:
        return "zero" if man == 0 else "subnormal"
    return "normal"


def bf16_to_float(raw):
    sign, exp, man = bf16_unpack(raw)
    if exp == 0xFF:
        if man != 0:
            return float('nan')
        return float('-inf') if sign else float('inf')
    if exp == 0:
        val = man * (2.0 ** -133)
    else:
        val = (128 + man) * (2.0 ** (exp - 134))
    return -val if sign else val


def _bf16_to_fraction(raw):
    """Convert bf16 raw to (Fraction_value, classification, sign)."""
    sign, exp, man = bf16_unpack(raw)
    if exp == 0xFF:
        if man != 0:
            return (None, 'nan', sign)
        return (None, 'inf', sign)
    if exp == 0:
        if man == 0:
            return (Fraction(0), 'zero', sign)
        val = Fraction(man, 2 ** 133)
        return (-val if sign else val, 'subnormal', sign)
    sig = 128 + man
    e = exp - 134
    if e >= 0:
        val = Fraction(sig * (1 << e))
    else:
        val = Fraction(sig, 1 << (-e))
    return (-val if sign else val, 'normal', sign)


def _fraction_to_bf16(val, rm="RNE"):
    """Round an exact Fraction to the nearest bfloat16 value."""
    if val == 0:
        return BF16_POS_ZERO

    sign = 0
    if val < 0:
        sign = 1
        val = -val

    two = Fraction(2)

    # Find exponent: val in [2^exp_u, 2^(exp_u+1))
    fval = float(val)
    if fval == 0.0 or math.isinf(fval):
        if fval == 0.0:
            exp_u = -200
        else:
            exp_u = val.numerator.bit_length() - val.denominator.bit_length()
    else:
        exp_u = math.floor(math.log2(fval))

    # Refine (at most a few iterations)
    for _ in range(5):
        if val >= two ** (exp_u + 1):
            exp_u += 1
        elif exp_u > -200 and val < two ** exp_u:
            exp_u -= 1
        else:
            break

    exp_biased = exp_u + 127

    # Overflow check
    if exp_biased >= 255:
        if rm == "RZ" or (rm == "RU" and sign == 1) or (rm == "RD" and sign == 0):
            return bf16_pack(sign, 254, 0x7F)
        return bf16_pack(sign, 0xFF, 0)

    if exp_biased >= 1:
        # Normal range: significand = val / 2^exp_u, in [1, 2)
        sig = val / (two ** exp_u)
        man_exact = (sig - 1) * 128  # in [0, 128)
        man_int = int(man_exact)
        remainder = man_exact - man_int
    else:
        # Subnormal range: value = mantissa * 2^(-133)
        man_exact = val * (two ** 133)
        man_int = int(man_exact)
        remainder = man_exact - man_int
        exp_biased = 0

    # Rounding decision
    half = Fraction(1, 2)
    lsb = man_int & 1
    inexact = remainder > 0

    round_up = False
    if rm == "RNE":
        if remainder > half:
            round_up = True
        elif remainder == half:
            round_up = (lsb == 1)
    elif rm == "RNA":
        round_up = (remainder >= half)
    elif rm == "RZ":
        round_up = False
    elif rm == "RU":
        round_up = (sign == 0 and inexact)
    elif rm == "RD":
        round_up = (sign == 1 and inexact)

    if round_up:
        man_int += 1

    # Handle mantissa overflow
    if exp_biased > 0:
        if man_int >= 128:
            man_int = 0
            exp_biased += 1
            if exp_biased >= 255:
                if rm == "RZ" or (rm == "RU" and sign == 1) or (rm == "RD" and sign == 0):
                    return bf16_pack(sign, 254, 0x7F)
                return bf16_pack(sign, 0xFF, 0)
    else:
        # Subnormal: mantissa overflow promotes to normal
        if man_int >= 128:
            man_int = 0
            exp_biased = 1

    return bf16_pack(sign, exp_biased, man_int & 0x7F)


def bf16_from_float(value, rm="RNE"):
    if math.isnan(value):
        return BF16_QNAN
    if math.isinf(value):
        return BF16_NEG_INF if value < 0 else BF16_POS_INF
    if value == 0.0:
        return BF16_NEG_ZERO if math.copysign(1.0, value) < 0 else BF16_POS_ZERO

    num, den = value.as_integer_ratio()
    exact = Fraction(num, den)
    return _fraction_to_bf16(exact, rm)


def bf16_add(a, b, rm="RNE"):
    a_val, a_cls, a_sign = _bf16_to_fraction(a)
    b_val, b_cls, b_sign = _bf16_to_fraction(b)

    if a_cls == 'nan' or b_cls == 'nan':
        return BF16_QNAN

    if a_cls == 'inf' and b_cls == 'inf':
        if a_sign == b_sign:
            return a & 0xFFFF
        return BF16_QNAN
    if a_cls == 'inf':
        return a & 0xFFFF
    if b_cls == 'inf':
        return b & 0xFFFF

    if a_cls == 'zero' and b_cls == 'zero':
        if a_sign == b_sign:
            return a & 0xFFFF
        return BF16_NEG_ZERO if rm == "RD" else BF16_POS_ZERO
    if a_cls == 'zero':
        return b & 0xFFFF
    if b_cls == 'zero':
        return a & 0xFFFF

    result = a_val + b_val

    if result == 0:
        return BF16_NEG_ZERO if rm == "RD" else BF16_POS_ZERO

    return _fraction_to_bf16(result, rm)


def bf16_mul(a, b, rm="RNE"):
    a_val, a_cls, a_sign = _bf16_to_fraction(a)
    b_val, b_cls, b_sign = _bf16_to_fraction(b)

    result_sign = a_sign ^ b_sign

    if a_cls == 'nan' or b_cls == 'nan':
        return BF16_QNAN

    if (a_cls == 'inf' and b_cls == 'zero') or (b_cls == 'inf' and a_cls == 'zero'):
        return BF16_QNAN

    if a_cls == 'inf' or b_cls == 'inf':
        return bf16_pack(result_sign, 0xFF, 0)

    if a_cls == 'zero' or b_cls == 'zero':
        return bf16_pack(result_sign, 0, 0)

    result = a_val * b_val
    return _fraction_to_bf16(result, rm)
'''

with open('/app/bf16.py', 'w') as f:
    f.write(IMPLEMENTATION)

print("bf16.py written to /app/bf16.py")
