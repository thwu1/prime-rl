"""Type definitions for the fuzzcorp coverage-guided fuzzing framework."""

from typing import FrozenSet, NamedTuple, Optional


class Location(NamedTuple):
    """A source code location: (filename, line_number, column_offset)."""
    filename: str
    line: int
    column: Optional[int]


class Branch(NamedTuple):
    """A branch transition: start_location -> end_location."""
    start: Location
    end: Location


# A fingerprint is a frozenset of branches representing a unique coverage profile.
Fingerprint = FrozenSet[Branch]
