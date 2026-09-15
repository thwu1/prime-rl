__all__ = ['scale', 'normalize_value', 'safe_divide']

from codebase.core import check_type, check_positive


def scale(value, factor):
    check_type(value, (int, float))
    check_type(factor, (int, float))
    return value * factor


def normalize_value(value, lo, hi):
    check_type(value, (int, float))
    if hi == lo:
        raise ValueError("Cannot normalize: lo equals hi")
    return (value - lo) / (hi - lo)


def safe_divide(numerator, denominator):
    check_type(numerator, (int, float))
    check_positive(denominator)
    return numerator / denominator


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))
