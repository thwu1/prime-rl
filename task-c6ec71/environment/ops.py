"""Core operations for the bracket analysis pipeline."""

from dataclasses import dataclass, field


@dataclass
class SegmentState:
    """
    Represents the cumulative effect of processing a contiguous segment
    of bracket tokens.

    n_pops: number of elements consumed from the preceding context
    pushes: list of indices (positions of unmatched open brackets)
    """
    n_pops: int = 0
    pushes: list = field(default_factory=list)

    def __repr__(self):
        return f"SS(pops={self.n_pops}, pushes={self.pushes})"


def neutral():
    """Return the neutral element for composition."""
    return SegmentState(0, [])


def compose(left, right):
    """
    Compose two segment states in sequence.

    The right segment's pops consume pushes from the left segment's
    push list (from the end, i.e. most recent first). If the right
    segment requires more pops than the left has pushes, the excess
    propagates.
    """
    if right.n_pops >= len(left.pushes):
        excess = right.n_pops - len(left.pushes)
        return SegmentState(excess, list(right.pushes))
    else:
        surviving = list(left.pushes[:len(left.pushes) - right.n_pops])
        return SegmentState(left.n_pops, surviving + list(right.pushes))


def char_to_segment(index, ch):
    """Convert a single bracket character at the given index to a segment state."""
    if ch == '[':
        return SegmentState(0, [index])
    elif ch == ']':
        return SegmentState(1, [])
    else:
        return neutral()
