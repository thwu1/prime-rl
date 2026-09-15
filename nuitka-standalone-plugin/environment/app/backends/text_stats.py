"""Text statistics processor."""
import collections


def process(text):
    """Compute text statistics."""
    words = text.lower().split()
    word_count = len(words)
    char_count = len(text)
    freq = collections.Counter(c for c in text.lower() if c.isalpha())
    top = freq.most_common(1)[0]
    return f"words={word_count} chars={char_count} top_char='{top[0]}':{top[1]}"
