"""Corpus management for coverage-guided fuzzing.

"""

from collections import Counter, defaultdict

from .types import Branch, Fingerprint


class Corpus:
    """Manage a corpus of inputs with coverage fingerprints.

    Maintains minimal covering examples with reference-counted
    fingerprint-to-input mapping and AFL-fast behavior count reset.
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

    def _add_fingerprint(self, input_bytes: bytes, fingerprint: Fingerprint) -> None:
        """Add a fingerprint-input mapping and reset behavior counts."""
        self.fingerprints[fingerprint] = input_bytes
        self.inputs.add(input_bytes)
        self._ref_counts[input_bytes] += 1
        # AFL-fast trick: reset all behavior counts to 1 when corpus changes.
        # The union ensures we don't lose track of any known behaviors.
        all_behaviors = fingerprint | set(self.behavior_counts)
        self.behavior_counts = Counter(all_behaviors)

    def _evict(self, input_bytes: bytes) -> None:
        """Evict an input whose reference count has reached zero."""
        assert self._ref_counts[input_bytes] == 0
        del self._ref_counts[input_bytes]
        self.inputs.discard(input_bytes)

    def consider(self, input_bytes: bytes, fingerprint: Fingerprint) -> bool:
        """Consider adding input_bytes with the given coverage fingerprint.

        Returns True if the corpus changed, False otherwise.
        """
        # Empty fingerprint is not interesting
        if not fingerprint:
            return False

        # Always update behavior counts
        self.behavior_counts.update(fingerprint)

        changed = False

        if fingerprint not in self.fingerprints:
            # New fingerprint: add it
            self._add_fingerprint(input_bytes, fingerprint)
            changed = True
        elif self.sort_key(input_bytes) < self.sort_key(self.fingerprints[fingerprint]):
            # Shorter input for existing fingerprint: replace
            old_input = self.fingerprints[fingerprint]
            self._ref_counts[old_input] -= 1
            self._add_fingerprint(input_bytes, fingerprint)
            if self._ref_counts[old_input] == 0:
                self._evict(old_input)
            changed = True

        return changed

    def check_invariants(self) -> None:
        """Verify all corpus invariants. Raises AssertionError on violation."""
        # 1. set(behavior_counts) == union of all fingerprints' branches
        all_behaviors = set()
        for fp in self.fingerprints:
            all_behaviors |= fp
        assert all_behaviors == set(self.behavior_counts), (
            f"behaviors mismatch: "
            f"extra in counts: {set(self.behavior_counts) - all_behaviors}, "
            f"missing from counts: {all_behaviors - set(self.behavior_counts)}"
        )

        # 2. len(inputs) <= len(fingerprints)
        assert len(self.inputs) <= len(self.fingerprints), (
            f"more inputs ({len(self.inputs)}) than fingerprints "
            f"({len(self.fingerprints)})"
        )

        # 3. Every fingerprint value is in self.inputs
        for fp, inp in self.fingerprints.items():
            assert inp in self.inputs, (
                f"fingerprint maps to input not in self.inputs"
            )

        # 4. Reference counts match actual fingerprint->input mapping counts
        expected_refs: dict[bytes, int] = {}
        for inp in self.fingerprints.values():
            expected_refs[inp] = expected_refs.get(inp, 0) + 1

        for inp in self.inputs:
            assert inp in self._ref_counts, f"input not in ref counts"
            assert self._ref_counts[inp] == expected_refs.get(inp, 0), (
                f"ref count mismatch: got {self._ref_counts[inp]}, "
                f"expected {expected_refs.get(inp, 0)}"
            )

        # 5. All ref counts are positive
        for inp, count in self._ref_counts.items():
            assert count > 0, f"non-positive ref count: {count}"

        # 6. self.inputs is subset of fingerprint values
        fp_values = set(self.fingerprints.values())
        assert self.inputs.issubset(fp_values), (
            f"inputs not subset of fingerprint values: "
            f"{self.inputs - fp_values}"
        )
