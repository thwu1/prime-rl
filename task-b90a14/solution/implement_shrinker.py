"""
Solution: implements the full shrinker reduction logic in shrinker.py.

Discovers and implements the necessary reduction strategies by studying
the hypothesis library's Conjecture engine internals.
"""

SHRINKER_CODE = r'''"""
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
      - Booleans: (1, int(value))  -- False < True
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
    """Shrinks a choice sequence to its shortlex-minimal INTERESTING form."""

    def __init__(self, test_function, initial_choices, max_calls=10000):
        self.test_function = test_function
        self.shrink_target = list(initial_choices)
        self.max_calls = max_calls
        self.call_count = 0
        self._cache = {}

    def cached_test_function(self, choices):
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
        if sequence_sort_key(choices) >= sequence_sort_key(self.shrink_target):
            return False
        result = self.cached_test_function(choices)
        if result.status == Status.INTERESTING:
            self.shrink_target = list(result.choices)
            return True
        return False

    def shrink(self):
        prev = None
        while sequence_sort_key(self.shrink_target) != prev:
            prev = sequence_sort_key(self.shrink_target)
            try:
                self._reduce()
            except RuntimeError:
                break

    def _reduce(self):
        """Apply all reduction transformations."""
        self._delete_elements()
        self._replace_with_zero()
        self._minimize_values()
        self._reorder_adjacent()
        self._delete_labeled_intervals()

    def _delete_elements(self):
        """Try removing each element. On success, don't advance (next
        element slid into current position). On failure, advance."""
        i = 0
        while i < len(self.shrink_target):
            candidate = self.shrink_target[:i] + self.shrink_target[i + 1:]
            if not self.consider_new_choices(candidate):
                i += 1

    def _replace_with_zero(self):
        """Try replacing each choice with its type's zero value."""
        for i in range(len(self.shrink_target)):
            if i >= len(self.shrink_target):
                break
            node = self.shrink_target[i]
            zero = node.zero_value()
            if node.value == zero:
                continue
            candidate = list(self.shrink_target)
            candidate[i] = node.with_value(zero)
            self.consider_new_choices(candidate)

    def _minimize_values(self):
        """Minimize each choice's value individually."""
        i = 0
        while i < len(self.shrink_target):
            node = self.shrink_target[i]
            if node.type == ChoiceType.INTEGER:
                self._minimize_integer(i)
            elif node.type == ChoiceType.STRING:
                self._minimize_string(i)
            elif node.type == ChoiceType.BOOLEAN:
                if node.value is True:
                    candidate = list(self.shrink_target)
                    candidate[i] = node.with_value(False)
                    self.consider_new_choices(candidate)
            i += 1

    def _minimize_integer(self, idx):
        node = self.shrink_target[idx]
        current = node.value
        if current <= 0:
            return

        # Try 0 first
        candidate = list(self.shrink_target)
        candidate[idx] = node.with_value(0)
        if self.consider_new_choices(candidate):
            return

        # Binary search in [0, current)
        lo = 0
        hi = current
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            candidate = list(self.shrink_target)
            candidate[idx] = self.shrink_target[idx].with_value(mid)
            if self.consider_new_choices(candidate):
                hi = mid
            else:
                lo = mid + 1

        # Try lo
        if lo < self.shrink_target[idx].value:
            candidate = list(self.shrink_target)
            candidate[idx] = self.shrink_target[idx].with_value(lo)
            self.consider_new_choices(candidate)

    def _minimize_string(self, idx):
        node = self.shrink_target[idx]
        current = node.value
        if not current:
            return

        # Try truncating to shorter lengths
        for length in range(len(current)):
            candidate = list(self.shrink_target)
            candidate[idx] = node.with_value(current[:length])
            if self.consider_new_choices(candidate):
                node = self.shrink_target[idx]
                current = node.value
                break

        # Re-read after potential change
        if idx < len(self.shrink_target):
            node = self.shrink_target[idx]
            current = node.value

        # Try lowering each character
        for ci in range(len(current)):
            char_ord = ord(current[ci])
            if char_ord <= 0:
                continue

            lo_ord = 0
            hi_ord = char_ord

            # Try lowest first
            new_str = current[:ci] + chr(lo_ord) + current[ci + 1:]
            candidate = list(self.shrink_target)
            candidate[idx] = self.shrink_target[idx].with_value(new_str)
            if self.consider_new_choices(candidate):
                if idx < len(self.shrink_target):
                    node = self.shrink_target[idx]
                    current = node.value
                continue

            # Binary search on character ordinal
            while lo_ord + 1 < hi_ord:
                mid_ord = (lo_ord + hi_ord) // 2
                if idx >= len(self.shrink_target):
                    break
                cur = self.shrink_target[idx].value
                new_str = cur[:ci] + chr(mid_ord) + cur[ci + 1:]
                candidate = list(self.shrink_target)
                candidate[idx] = self.shrink_target[idx].with_value(new_str)
                if self.consider_new_choices(candidate):
                    hi_ord = mid_ord
                    if idx < len(self.shrink_target):
                        node = self.shrink_target[idx]
                        current = node.value
                else:
                    lo_ord = mid_ord + 1

    def _reorder_adjacent(self):
        """Swap adjacent same-typed choices when it produces a
        shortlex-smaller sequence."""
        i = 0
        while i + 1 < len(self.shrink_target):
            a = self.shrink_target[i]
            b = self.shrink_target[i + 1]
            if a.type == b.type and choice_sort_key(a) > choice_sort_key(b):
                candidate = list(self.shrink_target)
                candidate[i] = b
                candidate[i + 1] = a
                self.consider_new_choices(candidate)
            i += 1

    def _delete_labeled_intervals(self):
        """Find contiguous runs sharing a label and try deleting each run."""
        i = 0
        while i < len(self.shrink_target):
            label = self.shrink_target[i].label
            j = i + 1
            while j < len(self.shrink_target) and self.shrink_target[j].label == label:
                j += 1
            if j - i > 1:
                candidate = self.shrink_target[:i] + self.shrink_target[j:]
                if self.consider_new_choices(candidate):
                    continue  # don't advance, next interval slid here
            i = j
'''

with open("/app/conjecture/shrinker.py", "w") as f:
    f.write(SHRINKER_CODE)

print("Shrinker implementation written successfully.")
