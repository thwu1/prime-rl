"""
Layout constraint solver.

Implement the split() and compose() functions below.

"""
from typing import List, Dict
from .types import (
    Rect, Constraint, Direction, Flex,
    Length, Percentage, Ratio, Fill, Min, Max,
    Leaf, Container, LayoutNode,
)


def split(
    area: Rect,
    constraints: List[Constraint],
    direction: Direction = Direction.HORIZONTAL,
    spacing: int = 0,
    flex: Flex = Flex.START,
) -> List[Rect]:
    """
    Split a rectangular area into sub-regions based on layout constraints.

    Args:
        area: The rectangular area to partition.
        constraints: Ordered list of constraints defining each sub-region's size.
        direction: HORIZONTAL splits along x-axis; VERTICAL splits along y-axis.
        spacing: Gap in cells between adjacent sub-regions.
        flex: Distribution strategy for leftover space (when sum of sizes < usable).

    Returns:
        List of Rect, one per constraint, laid out sequentially in the given direction.
    """
    raise NotImplementedError("Implement this function")


def compose(area: Rect, node: LayoutNode) -> Dict[str, Rect]:
    """
    Resolve a hierarchical layout tree to a flat mapping of leaf names to Rects.

    Recursively applies split() to each Container node, propagating the allocated
    rectangle down to children. Leaf nodes map their name to their allocated Rect.

    When a child node has sizing="auto", the parent computes the child's intrinsic
    size and uses it to influence constraint resolution.

    Args:
        area: The root rectangular area for the entire layout.
        node: A LayoutNode (Leaf or Container) defining the layout tree.

    Returns:
        Dict mapping each leaf name to its computed Rect.
    """
    raise NotImplementedError("Implement this function")
