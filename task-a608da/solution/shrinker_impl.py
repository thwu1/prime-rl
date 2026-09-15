"""Complete shrinker implementation.

Implements all shrink passes for the Conjecture-style PBT engine.
"""


import math
from typing import Any, Callable, Sequence

from choiceseq import Choice, ChoiceConstraints, ChoiceKind, choice_to_index, sort_key
from runner import Status, run_test


class Shrinker:
    """Shrinks a choice sequence to find the shortlex-minimal interesting example."""

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
        self.calls += 1
        if self.calls > self.max_calls:
            return (Status.VALID, [])
        return run_test(self.test_fn, choices)

    # -- helpers -------------------------------------------------------- #

    @staticmethod
    def _zero_value(choice: Choice) -> Any:
        kind = choice.kind
        c = choice.constraints
        if kind == ChoiceKind.INTEGER:
            mv = c.min_value if c.min_value is not None else 0
            return max(0, int(mv))
        elif kind == ChoiceKind.FLOAT:
            mv = c.min_value if c.min_value is not None else 0.0
            return float(max(0.0, mv))
        elif kind == ChoiceKind.BOOLEAN:
            return False
        elif kind == ChoiceKind.STRING:
            return ""
        elif kind == ChoiceKind.BYTES:
            return b""
        return None

    def _replace(self, index: int, new_value: Any) -> list:
        """Copy of self.current with one value replaced."""
        choices = list(self.current)
        old = choices[index]
        choices[index] = Choice(old.kind, new_value, old.constraints)
        return choices

    # -- core ---------------------------------------------------------- #

    def consider(self, choices: Sequence[Choice]) -> bool:
        status, drawn = self._run(choices)
        if status == Status.INTERESTING:
            if sort_key(drawn) < sort_key(self.current):
                self.current = list(drawn)
                return True
        return False

    def shrink(self) -> list:
        while self.calls <= self.max_calls:
            prev = list(self.current)
            self.pass_delete_choices()
            self.pass_zero_choices()
            self.pass_minimize_individual()
            self.pass_reorder_choices()
            self.pass_redistribute()
            if self.current == prev:
                break
        return self.current

    # -- passes -------------------------------------------------------- #

    def pass_delete_choices(self) -> bool:
        made_progress = False
        for k in [8, 4, 2, 1]:
            i = 0
            while i + k <= len(self.current):
                if self.calls > self.max_calls:
                    return made_progress
                candidate = self.current[:i] + self.current[i + k :]
                if self.consider(candidate):
                    made_progress = True
                    # weird loop: do NOT advance i
                else:
                    i += 1
        return made_progress

    def pass_zero_choices(self) -> bool:
        made_progress = False
        i = 0
        while i < len(self.current):
            if self.calls > self.max_calls:
                break
            choice = self.current[i]
            zero = self._zero_value(choice)
            if choice.value != zero:
                try:
                    candidate = self._replace(i, zero)
                    if self.consider(candidate):
                        made_progress = True
                        # current may have changed length
                        if i >= len(self.current):
                            break
                        # don't increment – re-examine same position
                        continue
                except ValueError:
                    pass
            i += 1
        return made_progress

    def pass_minimize_individual(self) -> bool:
        made_progress = False
        i = 0
        while i < len(self.current):
            if self.calls > self.max_calls:
                break
            choice = self.current[i]
            kind = choice.kind

            if kind == ChoiceKind.BOOLEAN:
                i += 1
                continue

            if kind == ChoiceKind.INTEGER:
                lo = self._zero_value(choice)
                hi = choice.value
                while lo < hi:
                    if self.calls > self.max_calls:
                        break
                    mid = (lo + hi) // 2
                    try:
                        candidate = self._replace(i, mid)
                        if self.consider(candidate):
                            made_progress = True
                            if i >= len(self.current):
                                break
                            hi = self.current[i].value
                        else:
                            lo = mid + 1
                    except ValueError:
                        lo = mid + 1

            elif kind == ChoiceKind.FLOAT:
                # (a) truncate to integer
                try:
                    trunc_val = math.trunc(choice.value)
                except (ValueError, OverflowError):
                    trunc_val = None
                if trunc_val is not None and trunc_val != choice.value:
                    try:
                        candidate = self._replace(i, trunc_val)
                        if self.consider(candidate):
                            made_progress = True
                            if i >= len(self.current):
                                break
                    except ValueError:
                        pass

                # (b) integer binary search
                if i < len(self.current):
                    cur = self.current[i]
                    try:
                        lo = int(self._zero_value(cur))
                        hi = int(cur.value)
                    except (ValueError, OverflowError):
                        lo = hi = 0
                    while lo < hi:
                        if self.calls > self.max_calls:
                            break
                        mid = (lo + hi) // 2
                        try:
                            candidate = self._replace(i, mid)
                            if self.consider(candidate):
                                made_progress = True
                                if i >= len(self.current):
                                    break
                                try:
                                    hi = int(self.current[i].value)
                                except (ValueError, OverflowError):
                                    break
                            else:
                                lo = mid + 1
                        except ValueError:
                            lo = mid + 1

            elif kind == ChoiceKind.STRING:
                # try shorter prefixes
                s = choice.value
                for new_len in range(len(s) - 1, -1, -1):
                    if self.calls > self.max_calls:
                        break
                    try:
                        candidate = self._replace(i, s[:new_len])
                        if self.consider(candidate):
                            made_progress = True
                            break
                    except ValueError:
                        pass
                # try lowering each character
                if i < len(self.current):
                    s = self.current[i].value
                    for j in range(len(s)):
                        if self.calls > self.max_calls:
                            break
                        ch = s[j]
                        if ch.isalpha() and ch != "a":
                            new_s = s[:j] + "a" + s[j + 1 :]
                        elif ch.isdigit() and ch != "0":
                            new_s = s[:j] + "0" + s[j + 1 :]
                        else:
                            continue
                        try:
                            candidate = self._replace(i, new_s)
                            if self.consider(candidate):
                                made_progress = True
                                if i >= len(self.current):
                                    break
                                s = self.current[i].value
                        except ValueError:
                            pass

            elif kind == ChoiceKind.BYTES:
                # try shorter prefixes
                b = choice.value
                for new_len in range(len(b) - 1, -1, -1):
                    if self.calls > self.max_calls:
                        break
                    try:
                        candidate = self._replace(i, b[:new_len])
                        if self.consider(candidate):
                            made_progress = True
                            break
                    except ValueError:
                        pass
                # try zeroing each byte
                if i < len(self.current):
                    b = self.current[i].value
                    for j in range(len(b)):
                        if self.calls > self.max_calls:
                            break
                        if b[j] != 0:
                            new_b = b[:j] + b"\x00" + b[j + 1 :]
                            try:
                                candidate = self._replace(i, new_b)
                                if self.consider(candidate):
                                    made_progress = True
                                    if i >= len(self.current):
                                        break
                                    b = self.current[i].value
                            except ValueError:
                                pass

            i += 1
        return made_progress

    def pass_reorder_choices(self) -> bool:
        made_progress = False
        i = 0
        while i < len(self.current) - 1:
            if self.calls > self.max_calls:
                break
            a = self.current[i]
            b = self.current[i + 1]
            if a.kind == b.kind and choice_to_index(a) > choice_to_index(b):
                candidate = list(self.current)
                candidate[i] = Choice(b.kind, b.value, a.constraints)
                candidate[i + 1] = Choice(a.kind, a.value, b.constraints)
                if self.consider(candidate):
                    made_progress = True
            i += 1
        return made_progress

    def pass_redistribute(self) -> bool:
        made_progress = False
        i = 0
        while i < len(self.current) - 1:
            if self.calls > self.max_calls:
                break
            a = self.current[i]
            b = self.current[i + 1]
            if a.kind == ChoiceKind.INTEGER and b.kind == ChoiceKind.INTEGER:
                s = a.value + b.value
                for new_a, new_b in [(0, s), (s, 0), (s // 2, s - s // 2)]:
                    ac = a.constraints
                    bc = b.constraints
                    a_min = ac.min_value if ac.min_value is not None else 0
                    a_max = ac.max_value if ac.max_value is not None else 2**63
                    b_min = bc.min_value if bc.min_value is not None else 0
                    b_max = bc.max_value if bc.max_value is not None else 2**63
                    if a_min <= new_a <= a_max and b_min <= new_b <= b_max:
                        try:
                            candidate = list(self.current)
                            candidate[i] = Choice(
                                ChoiceKind.INTEGER, new_a, a.constraints
                            )
                            candidate[i + 1] = Choice(
                                ChoiceKind.INTEGER, new_b, b.constraints
                            )
                            if self.consider(candidate):
                                made_progress = True
                                break
                        except ValueError:
                            pass
            i += 1
        return made_progress
