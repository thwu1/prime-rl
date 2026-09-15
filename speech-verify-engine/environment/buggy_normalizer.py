"""Text normalization for speech comparison."""
import re

_ONES = [
    '', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
    'seventeen', 'eighteen', 'nineteen',
]
_TENS = [
    '', '', 'twenty', 'thirty', 'forty', 'fifty',
    'sixty', 'seventy', 'eighty', 'ninety',
]


def _int_to_words(n):
    """Convert integer 0-9999 to English words."""
    if n < 0:
        return 'zero'
    parts = []
    if n >= 1000:
        parts.append(_ONES[n // 1000])
        parts.append('thousand')
        n %= 1000
    if n >= 100:
        parts.append(_ONES[n // 100])
        parts.append('hundred')
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10])
        if n % 10:
            parts.append(_ONES[n % 10])
    elif n > 0:
        parts.append(_ONES[n])
    return ' '.join(parts)


def normalize(text):
    """Normalize text for speech comparison.

    Expands pure-digit integer tokens 0-9999 to English words,
    case-folds, strips non-alphanumeric characters, collapses whitespace.
    """
    def _expand(match):
        n = int(match.group())
        if 0 <= n <= 9999:
            return _int_to_words(n)
        return match.group()

    text = re.sub(r'\d+', _expand, text)
    text = text.lower()
    text = re.sub(r'[^a-z0-9 ]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
