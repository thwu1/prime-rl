"""IEEE 754-compliant fp8_e4m3 floating-point arithmetic library.

Format: 1 sign bit, 4 exponent bits, 3 mantissa bits.
Bias = 7, precision p = 4.

Uses Python's Fraction type for exact intermediate arithmetic,
ensuring correct rounding in all operations including FMA.
"""

import math
from fractions import Fraction


class FP8:
    """8-bit minifloat: 1 sign, 4 exponent, 3 mantissa bits. Bias=7."""

    EXP_BITS = 4
    MANT_BITS = 3
    BIAS = 7
    EXP_SPECIAL = 15
    EXP_MAX = 14

    def __init__(self, raw):
        self.raw = raw & 0xFF

    @property
    def sign(self):
        return (self.raw >> 7) & 1

    @property
    def exponent(self):
        return (self.raw >> self.MANT_BITS) & ((1 << self.EXP_BITS) - 1)

    @property
    def mantissa(self):
        return self.raw & ((1 << self.MANT_BITS) - 1)

    def __repr__(self):
        return "FP8(0x{:02X})".format(self.raw)

    def __eq__(self, other):
        if isinstance(other, FP8):
            return self.raw == other.raw
        return NotImplemented

    def __hash__(self):
        return hash(self.raw)

    def to_real(self):
        s, e, m = self.sign, self.exponent, self.mantissa
        if e == self.EXP_SPECIAL:
            if m != 0:
                return float('nan')
            return float('-inf') if s else float('inf')
        if e == 0:
            if m == 0:
                return -0.0 if s else 0.0
            # Subnormal: (-1)^s * 2^(1-bias) * (m / 2^MANT_BITS)
            val = float(Fraction(m, 1 << self.MANT_BITS)
                        * Fraction(2) ** (1 - self.BIAS))
            return -val if s else val
        # Normal: (-1)^s * 2^(e-bias) * (1 + m / 2^MANT_BITS)
        val = float(Fraction((1 << self.MANT_BITS) + m, 1 << self.MANT_BITS)
                     * Fraction(2) ** (e - self.BIAS))
        return -val if s else val

    @classmethod
    def from_real(cls, value, rounding='RNE'):
        if math.isnan(value):
            return cls(0x79)
        if math.isinf(value):
            return cls(0xF8 if value < 0 else 0x78)
        if value == 0.0:
            return cls(0x80 if math.copysign(1.0, value) < 0 else 0x00)
        return cls._from_fraction(Fraction(value), rounding)

    @classmethod
    def _from_fraction(cls, value, rounding):
        """Encode an exact rational value to FP8 with specified rounding."""
        if value == 0:
            return cls(0x00)

        sign = 0
        if value < 0:
            sign = 1
            value = -value

        emin = 1 - cls.BIAS          # -6
        emax = cls.EXP_MAX - cls.BIAS  # 7
        min_normal = Fraction(2) ** emin

        if value < min_normal:
            # --- Subnormal region ---
            scale = Fraction(1 << cls.MANT_BITS) / Fraction(2) ** emin
            m_exact = value * scale
            m_int = int(m_exact)          # floor
            remainder = m_exact - m_int

            m_rounded = _round(sign, m_int, remainder, rounding)

            if m_rounded >= (1 << cls.MANT_BITS):
                # Promoted to smallest normal
                return cls((sign << 7) | (1 << cls.MANT_BITS))
            if m_rounded <= 0:
                return cls(sign << 7)      # +-0
            return cls((sign << 7) | m_rounded)

        # --- Normal region ---
        e_unbiased = _floor_log2(value)

        if e_unbiased > emax:
            return _overflow(sign, rounding, cls)

        sig = value / Fraction(2) ** e_unbiased   # in [1, 2)
        m_exact = (sig - 1) * (1 << cls.MANT_BITS)
        m_int = int(m_exact)
        remainder = m_exact - m_int

        m_rounded = _round(sign, m_int, remainder, rounding)

        if m_rounded >= (1 << cls.MANT_BITS):
            e_unbiased += 1
            m_rounded = 0
            if e_unbiased > emax:
                return _overflow(sign, rounding, cls)

        e_biased = e_unbiased + cls.BIAS
        return cls((sign << 7) | (e_biased << cls.MANT_BITS) | m_rounded)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _floor_log2(x):
    """Compute floor(log2(x)) for positive x (Fraction)."""
    if x >= 1:
        n = 0
        while Fraction(2) ** (n + 1) <= x:
            n += 1
        return n
    n = -1
    while Fraction(2) ** n > x:
        n -= 1
    return n


def _round(sign, m_int, remainder, rounding):
    """Round mantissa integer given a fractional remainder in [0, 1)."""
    if remainder == 0:
        return m_int
    half = Fraction(1, 2)
    if rounding == 'RNE':
        if remainder > half:
            return m_int + 1
        if remainder < half:
            return m_int
        # Tie: round to even (LSB = 0)
        return m_int if m_int % 2 == 0 else m_int + 1
    if rounding == 'RNA':
        return m_int + 1 if remainder >= half else m_int
    if rounding == 'RU':
        return m_int + 1 if sign == 0 else m_int
    if rounding == 'RD':
        return m_int + 1 if sign == 1 else m_int
    if rounding == 'RZ':
        return m_int
    raise ValueError("Unknown rounding mode: " + rounding)


def _overflow(sign, rounding, cls):
    """Handle overflow: return infinity or max normal per rounding mode."""
    max_raw = ((sign << 7)
               | (cls.EXP_MAX << cls.MANT_BITS)
               | ((1 << cls.MANT_BITS) - 1))
    inf_raw = (sign << 7) | (cls.EXP_SPECIAL << cls.MANT_BITS)
    if rounding in ('RNE', 'RNA'):
        return cls(inf_raw)
    if rounding == 'RZ':
        return cls(max_raw)
    if rounding == 'RU':
        return cls(inf_raw if sign == 0 else max_raw)
    if rounding == 'RD':
        return cls(inf_raw if sign == 1 else max_raw)
    raise ValueError("Unknown rounding mode: " + rounding)


def _to_fraction(x):
    """Convert a finite FP8 to an exact Fraction."""
    s, e, m = x.sign, x.exponent, x.mantissa
    if e == 0:
        if m == 0:
            return Fraction(0)
        val = (Fraction(m, 1 << FP8.MANT_BITS)
               * Fraction(2) ** (1 - FP8.BIAS))
        return -val if s else val
    val = (Fraction((1 << FP8.MANT_BITS) + m, 1 << FP8.MANT_BITS)
           * Fraction(2) ** (e - FP8.BIAS))
    return -val if s else val


# ------------------------------------------------------------------
# Public arithmetic API
# ------------------------------------------------------------------

def fp8_classify(x):
    """Classify an FP8 value."""
    e, m = x.exponent, x.mantissa
    if e == FP8.EXP_SPECIAL:
        return 'nan' if m != 0 else 'infinity'
    if e == 0:
        return 'zero' if m == 0 else 'subnormal'
    return 'normal'


def fp8_compare(a, b):
    """Compare two FP8 values.  Returns -1, 0, 1, or None (unordered)."""
    if fp8_classify(a) == 'nan' or fp8_classify(b) == 'nan':
        return None

    ac, bc = fp8_classify(a), fp8_classify(b)

    # Infinity handling
    if ac == 'infinity' and bc == 'infinity':
        if a.sign == b.sign:
            return 0
        return -1 if a.sign else 1
    if ac == 'infinity':
        return -1 if a.sign else 1
    if bc == 'infinity':
        return 1 if b.sign else -1

    # Both finite (zero, subnormal, normal)
    av, bv = _to_fraction(a), _to_fraction(b)
    if av < bv:
        return -1
    if av > bv:
        return 1
    return 0


def _zero_sign(rounding, neg_a, neg_b):
    """Determine the sign of an exact-zero sum of two addends.

    IEEE 754 section 6.3:
      - If both addends have the same sign, the zero keeps that sign.
      - If opposite signs produce exact zero, the sign is +0 in all
        rounding modes except RD, where it is -0.
    """
    if rounding == 'RD':
        return FP8(0x80)
    if neg_a and neg_b:
        return FP8(0x80)
    return FP8(0x00)


def fp8_add(a, b, rounding='RNE'):
    """IEEE 754 compliant addition."""
    ac, bc = fp8_classify(a), fp8_classify(b)

    # NaN propagation
    if ac == 'nan' or bc == 'nan':
        return FP8(0x79)

    # Infinity arithmetic
    if ac == 'infinity' and bc == 'infinity':
        if a.sign != b.sign:
            return FP8(0x79)          # Inf + (-Inf) = NaN
        return FP8(a.raw)
    if ac == 'infinity':
        return FP8(a.raw)
    if bc == 'infinity':
        return FP8(b.raw)

    # Both finite
    av, bv = _to_fraction(a), _to_fraction(b)
    result = av + bv

    if result == 0:
        return _zero_sign(rounding, bool(a.sign), bool(b.sign))

    return FP8._from_fraction(result, rounding)


def fp8_mul(a, b, rounding='RNE'):
    """IEEE 754 compliant multiplication."""
    ac, bc = fp8_classify(a), fp8_classify(b)
    result_sign = a.sign ^ b.sign

    # NaN propagation
    if ac == 'nan' or bc == 'nan':
        return FP8(0x79)

    # 0 * Inf = NaN
    if (ac == 'infinity' and bc == 'zero') or \
       (ac == 'zero' and bc == 'infinity'):
        return FP8(0x79)

    # Inf * finite-nonzero = Inf (with XOR sign)
    if ac == 'infinity' or bc == 'infinity':
        return FP8((result_sign << 7)
                    | (FP8.EXP_SPECIAL << FP8.MANT_BITS))

    # Zero (sign = XOR of operand signs)
    if ac == 'zero' or bc == 'zero':
        return FP8(result_sign << 7)

    # Both finite non-zero
    av, bv = _to_fraction(a), _to_fraction(b)
    result = av * bv
    return FP8._from_fraction(result, rounding)


def fp8_fma(a, b, c, rounding='RNE'):
    """Fused multiply-add: a*b + c with a single rounding step."""
    ac, bc, cc = fp8_classify(a), fp8_classify(b), fp8_classify(c)

    # NaN propagation
    if ac == 'nan' or bc == 'nan' or cc == 'nan':
        return FP8(0x79)

    # 0 * Inf or Inf * 0 -> NaN (regardless of c)
    if (ac == 'infinity' and bc == 'zero') or \
       (ac == 'zero' and bc == 'infinity'):
        return FP8(0x79)

    product_sign = a.sign ^ b.sign

    # Product is +-Inf
    if ac == 'infinity' or bc == 'infinity':
        if cc == 'infinity' and product_sign != c.sign:
            return FP8(0x79)          # Inf + (-Inf)
        return FP8((product_sign << 7)
                    | (FP8.EXP_SPECIAL << FP8.MANT_BITS))

    # Product finite, c is +-Inf
    if cc == 'infinity':
        return FP8(c.raw)

    # All operands finite
    av, bv, cv = _to_fraction(a), _to_fraction(b), _to_fraction(c)
    result = av * bv + cv             # exact with Fraction

    if result == 0:
        return _zero_sign(rounding,
                          bool(product_sign),
                          bool(c.sign))

    return FP8._from_fraction(result, rounding)
