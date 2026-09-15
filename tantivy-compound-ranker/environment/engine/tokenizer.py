"""Tokenizer module for text processing."""

import re


def tokenize(text):
    """Tokenize input text into a list of normalized terms."""
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    # Remove duplicates to normalize token stream
    return list(set(tokens))
