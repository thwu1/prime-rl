"""Text reversal processor."""


def process(text):
    """Reverse the order of words in the text."""
    words = text.split()
    return " ".join(reversed(words))
