"""Choice sequence shrinker for the property-based testing engine."""


from typing import Any, Callable, Sequence

from choiceseq import Choice, sort_key
from runner import Status, run_test


class Shrinker:
    """Shrinks a choice sequence to find a minimal interesting example.

    Attributes:
        test_fn:   The test function (accepts a ConjectureData).
        current:   The current best interesting choice sequence.
        calls:     Number of test-function invocations so far.
        max_calls: Hard cap on invocations.
    """

    def __init__(
        self,
        test_fn: Callable,
        initial: Sequence[Choice],
        max_calls: int = 10_000,
    ):
        self.test_fn = test_fn
        self.current = list(initial)
        self.max_calls = max_calls
        self.calls = 0

        status, _ = self._run(self.current)
        if status != Status.INTERESTING:
            raise ValueError("Initial choice sequence is not interesting")

    def _run(self, choices: Sequence[Choice]) -> tuple:
        """Run the test function and bump the call counter."""
        self.calls += 1
        if self.calls > self.max_calls:
            return (Status.VALID, [])
        return run_test(self.test_fn, choices)

    def consider(self, choices: Sequence[Choice]) -> bool:
        """Try a candidate sequence. If it is interesting and strictly
        improves on the current best, adopt it and return True."""
        status, drawn = self._run(choices)
        if status == Status.INTERESTING:
            if sort_key(drawn) < sort_key(self.current):
                self.current = list(drawn)
                return True
        return False

    def shrink(self) -> list:
        """Run the shrinking process and return the result."""
        return self.current
