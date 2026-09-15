def check_type(value, expected_type):
    if not isinstance(value, expected_type):
        raise TypeError(f"Expected {expected_type}, got {type(value)}")
    return value


def check_positive(value):
    check_type(value, (int, float))
    if value <= 0:
        raise ValueError(f"Expected positive value, got {value}")
    return value


def check_nonempty(text):
    check_type(text, str)
    if not text.strip():
        raise ValueError("Expected non-empty string")
    return text


def check_range(value, lo, hi):
    check_type(value, (int, float))
    if not (lo <= value <= hi):
        raise ValueError(f"{value} not in range [{lo}, {hi}]")
    return value


def validate_schema(data, schema):
    check_type(data, dict)
    for key, expected in schema.items():
        if key not in data:
            raise KeyError(f"Missing key: {key}")
        check_type(data[key], expected)
