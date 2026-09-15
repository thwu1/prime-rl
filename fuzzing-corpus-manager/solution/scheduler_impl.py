"""Bayesian scheduling for coverage-guided fuzzing.

"""

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
    """Numerically stable softmax."""
    if not values:
        return []
    # Subtract max for numerical stability
    max_val = max(values)
    exps = [math.exp(v - max_val) for v in values]
    total = sum(exps)
    return [e / total for e in exps]


class FuzzScheduler:
    """Bayesian scheduler for multi-target fuzzing."""

    def __init__(self):
        self.targets: dict[str, TargetState] = {}

    def register_target(self, name: str) -> None:
        """Register a new fuzz target with initial state."""
        self.targets[name] = TargetState(name)

    def record_execution(self, name: str, elapsed_time: float, found_new: bool) -> None:
        """Record a single execution of a fuzz target."""
        state = self.targets[name]
        state.ninputs += 1
        state.elapsed_time += elapsed_time
        if found_new:
            state.since_new_behavior = 0
        else:
            state.since_new_behavior += 1

    def behaviors_per_input(self, name: str) -> float:
        """Estimate behaviors discovered per input for the named target."""
        since = self.targets[name].since_new_behavior
        return (1.0 / since) if since > 0 else 1.0

    def behaviors_per_second(self, name: str) -> float:
        """Estimate behaviors discovered per second for the named target."""
        state = self.targets[name]
        if state.elapsed_time == 0:
            return 1.0
        inputs_per_second = state.ninputs / state.elapsed_time
        return self.behaviors_per_input(name) * inputs_per_second

    def get_probabilities(self) -> dict[str, float]:
        """Get probability distribution over targets using softmax."""
        if not self.targets:
            return {}
        names = list(self.targets.keys())
        scores = [self.behaviors_per_second(name) for name in names]
        probs = softmax(scores)
        return dict(zip(names, probs))

    @staticmethod
    def power_schedule(corpus: Corpus) -> dict[Fingerprint, float]:
        """AFL-fast inspired power schedule over corpus fingerprints.

        Weight each fingerprint by 1/min(behavior_count) of its branches.
        """
        if not corpus.fingerprints:
            return {}

        weights: dict[Fingerprint, float] = {}
        for fingerprint in corpus.fingerprints:
            if not fingerprint:
                weights[fingerprint] = 1.0
            else:
                weights[fingerprint] = 1.0 / min(
                    corpus.behavior_counts[b] for b in fingerprint
                )

        total = sum(weights.values())
        return {k: v / total for k, v in weights.items()}
