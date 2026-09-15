"""ROT13 cipher processor."""
from backends.helpers.char_utils import shift_char


def process(text):
    """Apply ROT13 cipher to the text."""
    return "".join(shift_char(c, 13) for c in text)
