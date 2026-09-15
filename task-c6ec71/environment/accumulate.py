"""Staged accumulation for the bracket analysis pipeline."""

import copy
import math
from ops import SegmentState, neutral, compose


def staged_accumulate(elements):
    """
    Compute inclusive prefix accumulation over a sequence of segment states.

    Returns a list where position i holds the composition of elements[0..i].
    Uses a tree-based approach for potential parallelism.
    """
    n = len(elements)
    if n == 0:
        return []
    if n == 1:
        return [copy.deepcopy(elements[0])]

    original = [copy.deepcopy(e) for e in elements]

    # Pad to next power of two
    m = 1
    while m < n:
        m <<= 1

    work = []
    for i in range(m):
        work.append(copy.deepcopy(elements[i]) if i < n else neutral())

    # Reduction phase (bottom-up)
    for d in range(int(math.log2(m))):
        stride = 1 << (d + 1)
        half = 1 << d
        for k in range(0, m, stride):
            li = k + half - 1
            ri = k + stride - 1
            work[ri] = compose(work[li], work[ri])

    # Distribution phase (top-down)
    work[m - 1] = neutral()
    for d in range(int(math.log2(m)) - 1, -1, -1):
        stride = 1 << (d + 1)
        half = 1 << d
        for k in range(0, m, stride):
            li = k + half - 1
            ri = k + stride - 1
            saved = copy.deepcopy(work[li])
            work[li] = copy.deepcopy(work[ri])
            work[ri] = compose(saved, work[ri])

    # Convert to inclusive
    result = []
    for i in range(n):
        result.append(compose(work[i], original[i]))

    return result
