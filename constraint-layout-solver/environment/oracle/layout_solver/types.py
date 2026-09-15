"""
Constraint-based layout types for terminal UI.

"""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Union


class Direction(Enum):
    HORIZONTAL = auto()
    VERTICAL = auto()


class Flex(Enum):
    START = auto()
    CENTER = auto()
    END = auto()
    SPACE_BETWEEN = auto()


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle defined by position and size."""
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Length:
    """Fixed size in terminal cells."""
    value: int


@dataclass(frozen=True)
class Percentage:
    """Percentage of usable space (integer 0-100)."""
    value: int


@dataclass(frozen=True)
class Ratio:
    """Fraction of usable space: numerator / denominator."""
    numerator: int
    denominator: int


@dataclass(frozen=True)
class Fill:
    """Proportional share of remaining space after fixed allocations."""
    weight: int = 1


@dataclass(frozen=True)
class Min:
    """Wraps another constraint; resolved size must be >= value."""
    value: int
    inner: 'Constraint'


@dataclass(frozen=True)
class Max:
    """Wraps another constraint; resolved size must be <= value."""
    value: int
    inner: 'Constraint'


Constraint = Union[Length, Percentage, Ratio, Fill, Min, Max]


@dataclass(frozen=True)
class Leaf:
    """A terminal leaf node in a layout tree."""
    name: str
    intrinsic_width: int = 0
    intrinsic_height: int = 0
    sizing: str = "fixed"


@dataclass(frozen=True)
class Container:
    """A container node that splits its allocated area among its children."""
    direction: Direction
    constraints: tuple
    children: tuple
    spacing: int = 0
    flex: Flex = Flex.START
    sizing: str = "fixed"


LayoutNode = Union[Leaf, Container]
