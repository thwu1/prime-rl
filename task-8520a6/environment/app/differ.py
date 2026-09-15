
"""Text difference computation."""

from __future__ import annotations
from typing import List


def myers_diff(text_a: str, text_b: str) -> List[str]:
    """Compute a line-based diff between two text versions.

    Returns a list of strings prefixed with:
        ' ' - line present in both (context)
        '-' - line removed from text_a
        '+' - line added from text_b

    The edit script should use the minimum number of insertions
    and deletions to transform text_a into text_b.
    """
    lines_a = text_a.splitlines() if text_a else []
    lines_b = text_b.splitlines() if text_b else []

    if not lines_a and not lines_b:
        return []
    if not lines_a:
        return ["+" + ln for ln in lines_b]
    if not lines_b:
        return ["-" + ln for ln in lines_a]

    # Positional comparison — compare lines at the same index
    result: List[str] = []
    max_len = max(len(lines_a), len(lines_b))

    for idx in range(max_len):
        if idx < len(lines_a) and idx < len(lines_b):
            if lines_a[idx] == lines_b[idx]:
                result.append(" " + lines_a[idx])
            else:
                result.append("-" + lines_a[idx])
                result.append("+" + lines_b[idx])
        elif idx < len(lines_a):
            result.append("-" + lines_a[idx])
        else:
            result.append("+" + lines_b[idx])

    return result
