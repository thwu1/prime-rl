"""Scheduling for coverage-guided fuzzing."""

import math

from .corpus import Corpus
from .types import Fingerprint


class TargetState:
    """Mutable state for a single fuzz target."""

    def __init__(self, name: str):
        self.name = name
        self.ninputs: int = 0
        self.elapsed_time: float = 0.0
        self.since_new_behavior: int = 0


def softmax(values: list[float]) -> list[float]:
    """Compute softmax probabilities from a list of scores.

    Must handle extreme values without overflow or underflow.
    Empty input returns empty list.
    """
    raise NotImplementedError


class FuzzScheduler:
    """Scheduler for multi-target fuzzing based on behavior discovery rates."""

    def __init__(self):
        self.targets: dict[str, TargetState] = {}

    def register_target(self, name: str) -> None:
        """Register a new fuzz target."""
        raise NotImplementedError

    def record_execution(self, name: str, elapsed_time: float, found_new: bool) -> None:
        """Record a single execution of a fuzz target."""
        raise NotImplementedError

    def behaviors_per_input(self, name: str) -> float:
        """Estimate behaviors discovered per input for the named target."""
        raise NotImplementedError

    def behaviors_per_second(self, name: str) -> float:
        """Estimate behaviors discovered per second for the named target."""
        raise NotImplementedError

    def get_probabilities(self) -> dict[str, float]:
        """Get probability distribution over targets for time allocation."""
        raise NotImplementedError

    @staticmethod
    def power_schedule(corpus: Corpus) -> dict[Fingerprint, float]:
        """Compute normalized weights for corpus entries based on branch rarity."""
        raise NotImplementedError
