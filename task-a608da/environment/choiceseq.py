"""Choice sequence representation for a Conjecture-style property-based testing engine.

A choice sequence is a list of typed choices that fully determines a test case.
Each choice has a kind (integer, float, boolean, string, bytes) and optional
constraints (min/max for numerics, max_length for string/bytes).

The test function draws choices from the sequence via ConjectureData.draw_*()
methods. Manipulating the sequence produces different test inputs.
"""


import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence


class ChoiceKind(Enum):
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    STRING = "string"
    BYTES = "bytes"


@dataclass(frozen=True)
class ChoiceConstraints:
    """Constraints on a choice value."""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    max_length: Optional[int] = None

    def validate(self, kind: ChoiceKind, value: Any) -> bool:
        """Check whether value is valid for the given kind under these constraints."""
        if kind == ChoiceKind.INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                return False
            if self.min_value is not None and value < self.min_value:
                return False
            if self.max_value is not None and value > self.max_value:
                return False
        elif kind == ChoiceKind.FLOAT:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
            if math.isnan(value):
                return True
            if self.min_value is not None and value < self.min_value:
                return False
            if self.max_value is not None and value > self.max_value:
                return False
        elif kind == ChoiceKind.BOOLEAN:
            if not isinstance(value, bool):
                return False
        elif kind == ChoiceKind.STRING:
            if not isinstance(value, str):
                return False
            if self.max_length is not None and len(value) > self.max_length:
                return False
        elif kind == ChoiceKind.BYTES:
            if not isinstance(value, bytes):
                return False
            if self.max_length is not None and len(value) > self.max_length:
                return False
        return True


@dataclass(frozen=True)
class Choice:
    """A single typed choice in a choice sequence."""
    kind: ChoiceKind
    value: Any
    constraints: ChoiceConstraints = field(default_factory=ChoiceConstraints)

    def __post_init__(self):
        if not self.constraints.validate(self.kind, self.value):
            raise ValueError(
                f"Value {self.value!r} violates constraints "
                f"for {self.kind}: {self.constraints}"
            )

    def __eq__(self, other):
        if not isinstance(other, Choice):
            return NotImplemented
        return self.kind == other.kind and self.value == other.value

    def __hash__(self):
        return hash((self.kind, self.value))


def choice_to_index(choice: Choice) -> tuple:
    """Convert a choice to a sortable index for shortlex ordering.

    Ordering within each type:
    - BOOLEAN: False < True
    - INTEGER: 0, 1, -1, 2, -2, ... (by abs value, positive first)
    - FLOAT: 0.0 first, then by abs value (integer floats before
             fractional), positive before negative
    - STRING: shorter first, then lexicographic
    - BYTES: shorter first, then by byte values

    Cross-type ordering: BOOLEAN < INTEGER < FLOAT < STRING < BYTES
    """
    kind = choice.kind
    value = choice.value

    if kind == ChoiceKind.BOOLEAN:
        return (0, int(value))
    elif kind == ChoiceKind.INTEGER:
        if value == 0:
            return (1, 0, 0)
        return (1, abs(value), 0 if value > 0 else 1)
    elif kind == ChoiceKind.FLOAT:
        if math.isnan(value):
            return (2, float("inf"), 0, 0)
        if value == 0.0:
            return (2, 0, 0, 0)
        av = abs(value)
        is_int = (av == int(av)) if not math.isinf(av) else False
        return (2, av, 0 if is_int else 1, 0 if value > 0 else 1)
    elif kind == ChoiceKind.STRING:
        return (3, len(value), value)
    elif kind == ChoiceKind.BYTES:
        return (4, len(value), tuple(value))
    raise ValueError(f"Unknown kind: {kind}")


def sort_key(choices: Sequence[Choice]) -> tuple:
    """Shortlex sort key for a choice sequence.

    Shorter sequences are always smaller. Among same-length sequences,
    compare element-wise using choice_to_index.
    """
    return (len(choices), tuple(choice_to_index(c) for c in choices))
