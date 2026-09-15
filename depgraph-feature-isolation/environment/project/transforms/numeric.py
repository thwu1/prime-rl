from project.core.validation import check_type, check_positive


def scale(value, factor):
    """Scale a numeric value by a factor."""
    check_type(value, (int, float))
    check_type(factor, (int, float))
    return value * factor


def normalize_value(value, lo, hi):
    """Normalize a value to the [0, 1] range given bounds."""
    check_type(value, (int, float))
    if hi == lo:
        return 0.0
    return (value - lo) / (hi - lo)


def safe_divide(numerator, denominator):
    """Divide numerator by denominator, ensuring denominator is positive."""
    check_type(numerator, (int, float))
    check_positive(denominator)
    return numerator / denominator
