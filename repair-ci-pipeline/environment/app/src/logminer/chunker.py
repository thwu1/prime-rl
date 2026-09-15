"""Text chunking utilities for processing long CI logs."""
from typing import List, Tuple


def split_with_overlap(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> List[Tuple[int, int, str]]:
    """Split text into overlapping chunks by line count.

    Args:
        text: Input text to split.
        chunk_size: Maximum lines per chunk.
        overlap: Number of overlapping lines between consecutive chunks.

    Returns:
        List of (start_line, end_line, chunk_text) tuples.
        Line numbers are 1-based.

    Raises:
        No exceptions; returns empty list for empty input.
    """
    if not text or not text.strip():
        return []

    lines = text.split('\n')
    total = len(lines)

    if total <= chunk_size:
        return [(1, total, text)]

    chunks: List[Tuple[int, int, str]] = []
    step = chunk_size - overlap

    pos = 0
    while pos < total:
        end = min(pos + chunk_size, total)
        chunk_lines = lines[pos:end]
        chunks.append((pos + 1, end, '\n'.join(chunk_lines)))

        if end >= total:
            break
        pos += step

    return chunks
