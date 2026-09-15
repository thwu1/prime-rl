"""Stack Monoid Parallel Bracket Analyzer — Reference Solution."""

import copy
import math
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class StackMonoidElement:
    """Stack monoid element: n_pops pops followed by pushes."""
    n_pops: int = 0
    pushes: list = field(default_factory=list)

    def __eq__(self, other):
        if not isinstance(other, StackMonoidElement):
            return False
        return self.n_pops == other.n_pops and self.pushes == other.pushes

    def __repr__(self):
        return f"SME(pops={self.n_pops}, pushes={self.pushes})"


def identity() -> StackMonoidElement:
    """Monoid identity: zero pops, no pushes."""
    return StackMonoidElement(0, [])


def combine(a: StackMonoidElement, b: StackMonoidElement) -> StackMonoidElement:
    """
    Compose two stack-operation sequences.

    Pops from *b* consume pushes from *a* (from the top, i.e. the end of
    the list).  If *b* has more pops than *a* has pushes, the excess pops
    add to *a*'s existing pops.  The resulting pushes are surviving pushes
    from *a* followed by all pushes from *b*.
    """
    if b.n_pops >= len(a.pushes):
        # All of a's pushes are consumed; excess pops pass through
        return StackMonoidElement(
            a.n_pops + b.n_pops - len(a.pushes),
            list(b.pushes),
        )
    else:
        # Only the topmost b.n_pops pushes from a are consumed
        surviving = list(a.pushes[: len(a.pushes) - b.n_pops])
        return StackMonoidElement(a.n_pops, surviving + list(b.pushes))


def map_token(index: int, token: str) -> StackMonoidElement:
    """Lift a single bracket token into the monoid."""
    if token == '[':
        return StackMonoidElement(0, [index])
    elif token == ']':
        return StackMonoidElement(1, [])
    else:
        return identity()


def parallel_inclusive_scan(
    elements: List[StackMonoidElement],
) -> List[StackMonoidElement]:
    """
    Work-efficient inclusive prefix scan (Blelloch algorithm).

    Given elements [e0, e1, ..., e_{n-1}], returns
    [e0, e0*e1, e0*e1*e2, ...] where * is `combine`.

    CRITICAL: the stack monoid is **non-commutative**.  In the down-sweep
    the new right child must be  combine(prefix, left_total), NOT
    combine(left_total, prefix).
    """
    n = len(elements)
    if n == 0:
        return []
    if n == 1:
        return [copy.deepcopy(elements[0])]

    # ---- save originals (needed to convert exclusive -> inclusive) ----
    original = [copy.deepcopy(e) for e in elements]

    # ---- pad to next power of two ----
    m = 1
    while m < n:
        m <<= 1

    work: List[StackMonoidElement] = []
    for i in range(m):
        work.append(copy.deepcopy(elements[i]) if i < n else identity())

    # ---- up-sweep (reduce) ----
    for d in range(int(math.log2(m))):
        stride = 1 << (d + 1)
        half = 1 << d
        for k in range(0, m, stride):
            li = k + half - 1
            ri = k + stride - 1
            work[ri] = combine(work[li], work[ri])

    # ---- down-sweep (exclusive scan) ----
    work[m - 1] = identity()
    for d in range(int(math.log2(m)) - 1, -1, -1):
        stride = 1 << (d + 1)
        half = 1 << d
        for k in range(0, m, stride):
            li = k + half - 1
            ri = k + stride - 1
            tmp = copy.deepcopy(work[li])
            work[li] = copy.deepcopy(work[ri])
            # CORRECT ORDER for non-commutative monoid:
            #   new_right = combine(prefix, left_subtree_total)
            work[ri] = combine(work[ri], tmp)

    # ---- convert exclusive scan to inclusive ----
    result: List[StackMonoidElement] = []
    for i in range(n):
        result.append(combine(work[i], original[i]))

    return result


def analyze(tokens: str) -> Dict[str, List[int]]:
    """
    Analyse a bracket string using the stack monoid prefix scan.

    Returns {"matches": [...], "parents": [...], "depths": [...]}.
    """
    n = len(tokens)
    if n == 0:
        return {"matches": [], "parents": [], "depths": []}

    # 1. Map tokens to monoid elements
    elements = [map_token(i, tokens[i]) for i in range(n)]

    # 2. Inclusive prefix scan
    scan = parallel_inclusive_scan(elements)

    # 3. Extract tree structure from scan results
    matches = [-1] * n
    parents = [-1] * n
    depths = [0] * n

    for i in range(n):
        if tokens[i] == '[':
            # depth = number of enclosing open brackets
            depths[i] = len(scan[i].pushes) - 1

            # parent = top of stack *before* this token was pushed
            if i == 0:
                parents[i] = (
                    scan[i].pushes[-2] if len(scan[i].pushes) >= 2 else -1
                )
            else:
                prev = scan[i - 1].pushes
                parents[i] = prev[-1] if prev else -1

        elif tokens[i] == ']':
            # depth = stack size *after* popping
            depths[i] = len(scan[i].pushes)

            # match = top of stack before popping (the open bracket being closed)
            if i > 0 and scan[i - 1].pushes:
                match_idx = scan[i - 1].pushes[-1]
                matches[i] = match_idx
                matches[match_idx] = i
            elif i == 0:
                matches[i] = -1
            else:
                matches[i] = -1

    # Set parents for close brackets (same parent as their matching open)
    for i in range(n):
        if tokens[i] == ']':
            if matches[i] != -1:
                parents[i] = parents[matches[i]]
            else:
                parents[i] = -1

    return {"matches": matches, "parents": parents, "depths": depths}
