def check_type(value, expected_type):
    """Validate that value is of the expected type."""
    if not isinstance(value, expected_type):
        raise TypeError(f"Expected {expected_type}, got {type(value)}")
    return value


def check_positive(value):
    """Validate that value is a positive number."""
    check_type(value, (int, float))
    if value <= 0:
        raise ValueError(f"Expected positive value, got {value}")
    return value


def check_nonempty(value):
    """Validate that value is a non-empty string."""
    check_type(value, str)
    if not value.strip():
        raise ValueError("Expected non-empty string")
    return value


def check_range(value, lo, hi):
    """Validate that value is within [lo, hi]."""
    check_type(value, (int, float))
    if not (lo <= value <= hi):
        raise ValueError(f"{value} not in [{lo}, {hi}]")
    return value
