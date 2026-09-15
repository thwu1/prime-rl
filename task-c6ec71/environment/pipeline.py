"""Main entry point for the bracket analysis pipeline."""

from ops import char_to_segment
from accumulate import staged_accumulate
from extract import extract_structure


def analyze(tokens):
    """
    Analyze a string of bracket characters and return structural metadata.

    Args:
        tokens: string containing '[' and ']' characters

    Returns:
        dict with keys 'matches', 'parents', 'depths', each a list of ints
    """
    n = len(tokens)
    if n == 0:
        return {"matches": [], "parents": [], "depths": []}

    # Stage 1: Convert each character to its segment representation
    segments = [char_to_segment(i, tokens[i]) for i in range(n)]

    # Stage 2: Accumulate segment states across the sequence
    accumulated = staged_accumulate(segments)

    # Stage 3: Extract structural information from accumulated states
    return extract_structure(tokens, accumulated)
