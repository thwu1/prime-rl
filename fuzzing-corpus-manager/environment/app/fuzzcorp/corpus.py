"""Corpus management for coverage-guided fuzzing."""

from collections import Counter, defaultdict

from .types import Branch, Fingerprint


class Corpus:
    """Manages test inputs and their coverage fingerprints.

    Attributes:
        inputs: set[bytes] — all current input byte strings in the corpus.
        fingerprints: dict[Fingerprint, bytes] — maps each unique coverage
            fingerprint to its current representative input.
        behavior_counts: Counter — per-Branch observation count.
        _ref_counts: dict[bytes, int] — how many fingerprints currently
            reference each input.
    """

    def __init__(self):
        self.inputs: set[bytes] = set()
        self.fingerprints: dict[Fingerprint, bytes] = {}
        self.behavior_counts: Counter = Counter()
        self._ref_counts: dict[bytes, int] = defaultdict(int)

    @staticmethod
    def sort_key(input_bytes: bytes) -> tuple[int, bytes]:
        """Shortlex ordering key: (length, bytes value)."""
        return (len(input_bytes), input_bytes)

    def consider(self, input_bytes: bytes, fingerprint: Fingerprint) -> bool:
        """Consider adding input_bytes with the given coverage fingerprint.

        Returns True if the corpus changed, False otherwise.
        Empty fingerprints are rejected.
        """
        raise NotImplementedError

    def check_invariants(self) -> None:
        """Verify all corpus invariants. Raises AssertionError on violation."""
        raise NotImplementedError
