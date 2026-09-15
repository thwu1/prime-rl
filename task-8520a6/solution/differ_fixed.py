
"""Fixed text difference computation using Myers O(ND) algorithm."""

from __future__ import annotations
from typing import List, Dict


def myers_diff(text_a: str, text_b: str) -> List[str]:
    """Compute a minimal line-based diff.

    Returns a list of strings prefixed with:
        ' ' - line present in both (context)
        '-' - line removed from text_a
        '+' - line added from text_b
    """
    lines_a: List[str] = text_a.splitlines() if text_a else []
    lines_b: List[str] = text_b.splitlines() if text_b else []

    n, m = len(lines_a), len(lines_b)

    if n == 0 and m == 0:
        return []
    if n == 0:
        return ["+" + ln for ln in lines_b]
    if m == 0:
        return ["-" + ln for ln in lines_a]

    max_d = n + m
    v: Dict[int, int] = {1: 0}
    trace: List[Dict[int, int]] = []

    for d in range(max_d + 1):
        trace.append(dict(v))

        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v.get(k - 1, -1) < v.get(k + 1, -1)):
                x = v.get(k + 1, 0)
            else:
                x = v.get(k - 1, 0) + 1

            y = x - k

            while x < n and y < m and lines_a[x] == lines_b[y]:
                x += 1
                y += 1

            v[k] = x

            if x >= n and y >= m:
                trace.append(dict(v))
                return _backtrack(trace, lines_a, lines_b, d)

    return []


def _backtrack(
    trace: List[Dict[int, int]],
    lines_a: List[str],
    lines_b: List[str],
    edit_distance: int,
) -> List[str]:
    x, y = len(lines_a), len(lines_b)
    edits: List[str] = []

    for d in range(edit_distance, 0, -1):
        k = x - y
        v_prev = trace[d]

        if k == -d or (k != d and v_prev.get(k - 1, -1) < v_prev.get(k + 1, -1)):
            prev_k = k + 1
            prev_x = v_prev.get(prev_k, 0)
            prev_y = prev_x - prev_k
            mid_x = prev_x
            mid_y = prev_y + 1
        else:
            prev_k = k - 1
            prev_x = v_prev.get(prev_k, 0)
            prev_y = prev_x - prev_k
            mid_x = prev_x + 1
            mid_y = prev_y

        while x > mid_x:
            x -= 1
            y -= 1
            edits.append(" " + lines_a[x])

        if prev_k == k + 1:
            edits.append("+" + lines_b[mid_y - 1])
        else:
            edits.append("-" + lines_a[mid_x - 1])

        x, y = prev_x, prev_y

    while x > 0:
        x -= 1
        y -= 1
        edits.append(" " + lines_a[x])

    edits.reverse()
    return edits
