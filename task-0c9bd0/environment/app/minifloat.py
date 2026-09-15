# Implement IEEE 754-compliant fp8_e4m3 floating-point arithmetic.
# See /app/spec.md for format details and requirements.


class FP8:
    """8-bit minifloat: 1 sign, 4 exponent, 3 mantissa bits. Bias=7."""

    EXP_BITS = 4
    MANT_BITS = 3
    BIAS = 7
    EXP_SPECIAL = 15
    EXP_MAX = 14

    def __init__(self, raw: int):
        raise NotImplementedError

    def to_real(self) -> float:
        raise NotImplementedError

    @classmethod
    def from_real(cls, value: float, rounding: str = 'RNE') -> 'FP8':
        raise NotImplementedError


def fp8_add(a: FP8, b: FP8, rounding: str = 'RNE') -> FP8:
    raise NotImplementedError


def fp8_mul(a: FP8, b: FP8, rounding: str = 'RNE') -> FP8:
    raise NotImplementedError


def fp8_fma(a: FP8, b: FP8, c: FP8, rounding: str = 'RNE') -> FP8:
    raise NotImplementedError


def fp8_classify(a: FP8) -> str:
    raise NotImplementedError


def fp8_compare(a: FP8, b: FP8):
    raise NotImplementedError
