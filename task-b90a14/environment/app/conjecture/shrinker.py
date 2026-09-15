"""
Shrinker for choice sequences.

Given a choice sequence that causes a test to be INTERESTING (failing),
the shrinker tries to find the shortlex-minimal sequence that is still
INTERESTING. A sequence `a` is shortlex-smaller than `b` if:
  - len(a) < len(b), OR
  - len(a) == len(b) and a < b lexicographically (via choice_sort_key)
"""

from .data import ChoiceNode, ChoiceType, Status
from .engine import run_test_function


def choice_sort_key(node):
    """
    Sort key for a single choice, used for lexicographic comparison.
    Maps each choice to a comparable tuple:
      - Integers: (0, value)
      - Booleans: (1, int(value))  — False < True
      - Strings:  (2, len(value), tuple(ord(c) for c in value))
    """
    if node.type == ChoiceType.INTEGER:
        return (0, node.value)
    elif node.type == ChoiceType.BOOLEAN:
        return (1, int(node.value))
    elif node.type == ChoiceType.STRING:
        return (2, len(node.value), tuple(ord(c) for c in node.value))


def sequence_sort_key(choices):
    """Sort key for an entire choice sequence (shortlex order)."""
    return (len(choices), tuple(choice_sort_key(c) for c in choices))


class Shrinker:
    """
    Shrinks a choice sequence to its shortlex-minimal INTERESTING form.

    Usage:
        shrinker = Shrinker(test_function, initial_choices, max_calls=10000)
        shrinker.shrink()
        result = shrinker.shrink_target  # the minimal INTERESTING sequence
    """

    def __init__(self, test_function, initial_choices, max_calls=10000):
        """
        Args:
            test_function: A callable that takes a ConjectureData and draws
                choices from it. Should call data.mark_interesting() on failure.
            initial_choices: The initial INTERESTING choice sequence (list of ChoiceNode).
            max_calls: Maximum number of test function evaluations allowed.
        """
        self.test_function = test_function
        self.shrink_target = list(initial_choices)
        self.max_calls = max_calls
        self.call_count = 0
        self._cache = {}

    def cached_test_function(self, choices):
        """
        Run the test function on the given choices, using a cache to avoid
        redundant evaluations. Returns the ConjectureResult.
        Raises RuntimeError if max_calls is exceeded.
        """
        key = tuple((n.type, n.value, n.label) for n in choices)
        if key in self._cache:
            return self._cache[key]
        if self.call_count >= self.max_calls:
            raise RuntimeError("Exceeded max_calls budget")
        self.call_count += 1
        result = run_test_function(self.test_function, choices)
        self._cache[key] = result
        return result

    def consider_new_choices(self, choices):
        """
        Try a new candidate choice sequence. If it is INTERESTING and
        shortlex-smaller than the current shrink_target, adopt it as
        the new target and return True. Otherwise return False.
        """
        if sequence_sort_key(choices) >= sequence_sort_key(self.shrink_target):
            return False
        result = self.cached_test_function(choices)
        if result.status == Status.INTERESTING:
            self.shrink_target = list(result.choices)
            return True
        return False

    def shrink(self):
        """
        Main entry point. Repeatedly applies _reduce() until a fixed point
        is reached (no further reduction is possible).
        """
        prev = None
        while sequence_sort_key(self.shrink_target) != prev:
            prev = sequence_sort_key(self.shrink_target)
            try:
                self._reduce()
            except RuntimeError:
                break  # budget exhausted

    def _reduce(self):
        """Apply reduction transformations to move shrink_target toward
        shortlex minimality while preserving the INTERESTING property.

        Use self.consider_new_choices(candidate) to propose candidate
        sequences — it returns True if the candidate was adopted.

        Each ChoiceNode has .type (ChoiceType enum), .value, .label (str),
        .zero_value() returning the minimal value for that type, and
        .with_value(v) returning a copy with a new value.
        """
        raise NotImplementedError("Reduction logic not yet implemented")
