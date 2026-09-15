def round_val(x, decimals=2):
    """Round a float to the given number of decimal places."""
    return round(float(x), decimals)


def pad_string(s, width, fill_char=' '):
    """Pad a string to the specified width."""
    return str(s).ljust(width, fill_char)
