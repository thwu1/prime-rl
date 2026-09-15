"""Character manipulation utilities."""


def shift_char(c, n):
    """Shift a character by n positions in the alphabet."""
    if c.isalpha():
        base = ord('A') if c.isupper() else ord('a')
        return chr((ord(c) - base + n) % 26 + base)
    return c
