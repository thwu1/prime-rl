"""
Core data types for the Conjecture engine.

A test case is represented as a sequence of typed choices (the "choice sequence").
Each choice is a ChoiceNode with a type, value, and label indicating which part
of the test produced it.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Union


class ChoiceType(Enum):
    INTEGER = auto()
    BOOLEAN = auto()
    STRING = auto()


@dataclass(frozen=True)
class ChoiceNode:
    """A single typed choice in the choice sequence."""
    type: ChoiceType
    value: Union[int, bool, str]
    label: str = ""

    def zero_value(self):
        """Return the zero/minimal value for this choice's type."""
        if self.type == ChoiceType.INTEGER:
            return 0
        elif self.type == ChoiceType.BOOLEAN:
            return False
        elif self.type == ChoiceType.STRING:
            return ""

    def with_value(self, new_value):
        """Return a copy with a different value."""
        return ChoiceNode(type=self.type, value=new_value, label=self.label)


class Status(Enum):
    """Outcome of running a test function on a choice sequence."""
    VALID = auto()       # Test passed (not interesting)
    INTERESTING = auto() # Test failed (this is what we want to shrink)
    INVALID = auto()     # Choice sequence was rejected / too short
    OVERRUN = auto()     # Ran out of choices


@dataclass
class ConjectureResult:
    """The result of running a test function against a choice sequence."""
    status: Status
    choices: tuple  # tuple of ChoiceNode
    interesting_origin: Any = None  # identifies which failure mode

    @property
    def choice_sequence(self):
        return self.choices


@dataclass
class ChoiceConstraints:
    """Constraints on a choice draw, used during generation."""
    choice_type: ChoiceType
    label: str = ""
    min_value: Any = None
    max_value: Any = None


class ConjectureData:
    """
    Represents a test case being executed. The test function draws choices
    from this object. During generation, choices come from a provider.
    During replay, choices come from a fixed sequence.
    """

    def __init__(self, choices=None, max_choices=1000):
        self._choices = list(choices) if choices else []
        self._replay_index = 0
        self._is_replay = choices is not None
        self._drawn = []
        self.status = Status.VALID
        self.max_choices = max_choices
        self.interesting_origin = None

    def draw_integer(self, min_value=0, max_value=2**63, label=""):
        """Draw an integer choice."""
        return self._draw(ChoiceType.INTEGER, label, min_value, max_value)

    def draw_boolean(self, label=""):
        """Draw a boolean choice."""
        return self._draw(ChoiceType.BOOLEAN, label)

    def draw_string(self, min_size=0, max_size=64, label=""):
        """Draw a string choice."""
        return self._draw(ChoiceType.STRING, label, min_size, max_size)

    def _draw(self, choice_type, label, min_val=None, max_val=None):
        if self.status != Status.VALID:
            raise StopTest(self.status)

        if self._is_replay:
            if self._replay_index >= len(self._choices):
                self.status = Status.OVERRUN
                raise StopTest(Status.OVERRUN)
            node = self._choices[self._replay_index]
            self._replay_index += 1
            # Type mismatch during replay means INVALID
            if node.type != choice_type:
                self.status = Status.INVALID
                raise StopTest(Status.INVALID)
            self._drawn.append(node)
            return node.value
        else:
            raise RuntimeError("Non-replay drawing not supported in this context")

    def mark_interesting(self, origin=None):
        """Mark this test case as interesting (failing)."""
        self.status = Status.INTERESTING
        self.interesting_origin = origin
        raise StopTest(Status.INTERESTING)

    def freeze(self):
        """Finalize this test case."""
        return ConjectureResult(
            status=self.status,
            choices=tuple(self._drawn),
            interesting_origin=self.interesting_origin,
        )


class StopTest(Exception):
    """Raised to abort test execution early."""
    def __init__(self, status):
        self.status = status
        super().__init__(str(status))
