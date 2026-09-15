"""Test runner that executes test functions against choice sequences.

The runner feeds choices from a sequence to the test function via
ConjectureData.draw_*() methods.  It classifies each run as:

  VALID        - test passed (no assertion failure)
  INTERESTING  - test found a bug (AssertionError)
  INVALID      - test precondition violated (Unsatisfied)
  OVERRUN      - choice sequence exhausted or type mismatch
"""


from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

from choiceseq import Choice, ChoiceConstraints, ChoiceKind


class Status(Enum):
    VALID = "valid"
    INTERESTING = "interesting"
    INVALID = "invalid"
    OVERRUN = "overrun"


class Unsatisfied(Exception):
    """Raised when a test precondition is not met."""


class Overrun(Exception):
    """Raised when the choice sequence is exhausted or types mismatch."""


@dataclass
class ConjectureData:
    """Tracks choices drawn during a single test execution."""

    _choices: list
    _index: int = field(default=0, init=False)
    _drawn: list = field(default_factory=list, init=False)

    def draw_integer(
        self, min_value: int = 0, max_value: int = 2**63 - 1
    ) -> int:
        constraints = ChoiceConstraints(min_value=min_value, max_value=max_value)
        return self._draw(ChoiceKind.INTEGER, constraints)

    def draw_float(
        self, min_value: float = -1e308, max_value: float = 1e308
    ) -> float:
        constraints = ChoiceConstraints(min_value=min_value, max_value=max_value)
        return self._draw(ChoiceKind.FLOAT, constraints)

    def draw_boolean(self) -> bool:
        return self._draw(ChoiceKind.BOOLEAN, ChoiceConstraints())

    def draw_string(self, max_length: int = 1024) -> str:
        constraints = ChoiceConstraints(max_length=max_length)
        return self._draw(ChoiceKind.STRING, constraints)

    def draw_bytes(self, max_length: int = 1024) -> bytes:
        constraints = ChoiceConstraints(max_length=max_length)
        return self._draw(ChoiceKind.BYTES, constraints)

    def assume(self, condition: bool) -> None:
        """Mark a precondition.  Raises Unsatisfied if *condition* is false."""
        if not condition:
            raise Unsatisfied("Precondition not satisfied")

    # ------------------------------------------------------------------ #

    def _draw(self, kind: ChoiceKind, constraints: ChoiceConstraints) -> Any:
        if self._index >= len(self._choices):
            raise Overrun("Choice sequence exhausted")

        choice = self._choices[self._index]

        if choice.kind != kind:
            raise Overrun(
                f"Type mismatch at index {self._index}: "
                f"expected {kind}, got {choice.kind}"
            )

        if not constraints.validate(kind, choice.value):
            raise Overrun(
                f"Value {choice.value!r} violates requested constraints "
                f"at index {self._index}"
            )

        self._index += 1
        drawn_choice = Choice(kind, choice.value, constraints)
        self._drawn.append(drawn_choice)
        return choice.value

    @property
    def choices(self) -> list:
        """Choices actually consumed so far (with the test's constraints)."""
        return list(self._drawn)


def run_test(
    test_fn: Callable, choices: Sequence[Choice]
) -> tuple:
    """Run *test_fn* with the given choice sequence.

    Returns ``(status, drawn_choices)`` where *drawn_choices* are only
    the choices the test actually consumed.
    """
    data = ConjectureData(list(choices))
    try:
        test_fn(data)
        return (Status.VALID, data.choices)
    except AssertionError:
        return (Status.INTERESTING, data.choices)
    except Unsatisfied:
        return (Status.INVALID, data.choices)
    except Overrun:
        return (Status.OVERRUN, data.choices)
