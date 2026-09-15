"""
Verification tests for the Conjecture shrinker implementation.
Tests verify that _reduce() is implemented and produces correct
minimal choice sequences for various test function scenarios.
"""

import pytest
import sys

sys.path.insert(0, '/app')

from conjecture.data import ChoiceNode, ChoiceType, Status
from conjecture.engine import run_test_function
from conjecture.shrinker import Shrinker, sequence_sort_key


# ---- Helpers ----

def make_int(value, label=""):
    return ChoiceNode(type=ChoiceType.INTEGER, value=value, label=label)


def make_bool(value, label=""):
    return ChoiceNode(type=ChoiceType.BOOLEAN, value=value, label=label)


def make_str(value, label=""):
    return ChoiceNode(type=ChoiceType.STRING, value=value, label=label)


# ---- Basic: _reduce is implemented ----

class TestImplemented:

    def test_reduce_is_implemented(self):
        """_reduce() must not raise NotImplementedError."""
        def test_fn(data):
            data.draw_integer(label="x")
            data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_int(5)])
        try:
            shrinker._reduce()
        except NotImplementedError:
            pytest.fail("_reduce() still raises NotImplementedError")


# ---- Integer minimization ----

class TestIntegerMinimization:

    def test_to_exact_threshold(self):
        """INT(100) must shrink to INT(10) for threshold >= 10."""
        def test_fn(data):
            x = data.draw_integer(label="x")
            if x >= 10:
                data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_int(100)])
        shrinker.shrink()
        assert len(shrinker.shrink_target) == 1
        assert shrinker.shrink_target[0].value == 10

    def test_to_zero_unconditional(self):
        """INT(500) must shrink to INT(0) when any value is INTERESTING."""
        def test_fn(data):
            data.draw_integer(label="x")
            data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_int(500)])
        shrinker.shrink()
        assert shrinker.shrink_target[0].value == 0

    def test_already_minimal(self):
        """INT(0) must stay at INT(0) when already minimal."""
        def test_fn(data):
            data.draw_integer(label="x")
            data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_int(0)])
        shrinker.shrink()
        assert shrinker.shrink_target[0].value == 0

    def test_precise_binary_search(self):
        """INT(10000) must shrink to INT(42) for threshold >= 42."""
        def test_fn(data):
            x = data.draw_integer(label="x")
            if x >= 42:
                data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_int(10000)])
        shrinker.shrink()
        assert shrinker.shrink_target[0].value == 42


# ---- Deletion ----

class TestDeletion:

    def test_delete_unnecessary_suffix(self):
        """Extra elements after the interesting draw must be removed."""
        def test_fn(data):
            x = data.draw_integer(label="x")
            if x >= 5:
                data.mark_interesting()

        initial = [make_int(50), make_int(99), make_int(42)]
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        assert len(shrinker.shrink_target) == 1
        assert shrinker.shrink_target[0].value == 5

    def test_delete_prefix_in_scan(self):
        """Scan-until-match: prefix elements must be deleted, value minimized."""
        def test_fn(data):
            while True:
                v = data.draw_integer(label="v")
                if v >= 50:
                    data.mark_interesting()

        initial = [make_int(10), make_int(20), make_int(60)]
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        assert len(shrinker.shrink_target) == 1
        assert shrinker.shrink_target[0].value == 50

    def test_variable_length(self):
        """Variable-length sequence must be shortened and values minimized."""
        def test_fn(data):
            n = data.draw_integer(label="n")
            for _ in range(min(n, 10)):
                v = data.draw_integer(label="v")
                if v >= 50:
                    data.mark_interesting()

        initial = [make_int(3, "n"), make_int(10, "v"),
                   make_int(70, "v"), make_int(20, "v")]
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        assert len(shrinker.shrink_target) == 2
        assert shrinker.shrink_target[0].value == 1
        assert shrinker.shrink_target[1].value == 50


# ---- Boolean minimization ----

class TestBooleans:

    def test_true_to_false(self):
        """BOOL(True) must shrink to BOOL(False) when both are INTERESTING."""
        def test_fn(data):
            data.draw_boolean(label="b")
            data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_bool(True)])
        shrinker.shrink()
        assert shrinker.shrink_target[0].value is False

    def test_stays_true_when_required(self):
        """BOOL(True) must stay True when only True is INTERESTING."""
        def test_fn(data):
            b = data.draw_boolean(label="b")
            if b:
                data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_bool(True)])
        shrinker.shrink()
        assert shrinker.shrink_target[0].value is True


# ---- String minimization ----

class TestStrings:

    def test_to_empty_unconditional(self):
        """String must shrink to empty when any string is INTERESTING."""
        def test_fn(data):
            data.draw_string(label="s")
            data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_str("test string")])
        shrinker.shrink()
        assert shrinker.shrink_target[0].value == ""

    def test_shorten_to_min_length(self):
        """String must shrink to minimum length with minimized characters."""
        def test_fn(data):
            s = data.draw_string(label="s")
            if len(s) >= 3:
                data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_str("hello world")])
        shrinker.shrink()
        result = shrinker.shrink_target[0].value
        assert len(result) == 3
        assert all(ord(c) == 0 for c in result)

    def test_content_preserved(self):
        """When content matters, string must preserve required content."""
        def test_fn(data):
            s = data.draw_string(label="s")
            if 'a' in s:
                data.mark_interesting()

        shrinker = Shrinker(test_fn, [make_str("abcdef")])
        shrinker.shrink()
        assert shrinker.shrink_target[0].value == "a"


# ---- General properties ----

class TestProperties:

    def test_result_is_interesting(self):
        """Shrink result must always be INTERESTING."""
        def test_fn(data):
            x = data.draw_integer(label="x")
            y = data.draw_integer(label="y")
            if x * y >= 100:
                data.mark_interesting()

        initial = [make_int(20), make_int(30)]
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        result = run_test_function(test_fn, shrinker.shrink_target)
        assert result.status == Status.INTERESTING

    def test_shortlex_improved(self):
        """Result must be shortlex <= the initial sequence."""
        def test_fn(data):
            x = data.draw_integer(label="x")
            if x >= 5:
                data.mark_interesting()

        initial = [make_int(100)]
        initial_key = sequence_sort_key(initial)
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        result_key = sequence_sort_key(shrinker.shrink_target)
        assert result_key <= initial_key

    def test_budget_respected(self):
        """Shrinker must not exceed max_calls."""
        def test_fn(data):
            x = data.draw_integer(label="x")
            if x >= 1:
                data.mark_interesting()

        budget = 50
        shrinker = Shrinker(test_fn, [make_int(1000)], max_calls=budget)
        shrinker.shrink()
        assert shrinker.call_count <= budget
        result = run_test_function(test_fn, shrinker.shrink_target)
        assert result.status == Status.INTERESTING

    def test_idempotent(self):
        """Re-shrinking an already-shrunk sequence must be a no-op."""
        def test_fn(data):
            a = data.draw_integer(label="a")
            b = data.draw_integer(label="b")
            if a + b >= 15:
                data.mark_interesting()

        initial = [make_int(100), make_int(200)]
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        first_key = sequence_sort_key(shrinker.shrink_target)
        shrinker.shrink()
        assert sequence_sort_key(shrinker.shrink_target) == first_key


# ---- Complex scenarios ----

class TestComplex:

    def test_mixed_types(self):
        """Shrinking must work across mixed choice types."""
        def test_fn(data):
            flag = data.draw_boolean(label="f")
            name = data.draw_string(label="n")
            val = data.draw_integer(label="v")
            if flag and len(name) >= 2 and val >= 3:
                data.mark_interesting()

        initial = [make_bool(True), make_str("testing"), make_int(99)]
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        result = shrinker.shrink_target
        assert len(result) == 3
        assert result[0].value is True
        assert len(result[1].value) == 2
        assert result[2].value == 3
        res = run_test_function(test_fn, result)
        assert res.status == Status.INTERESTING

    def test_conditional_draws(self):
        """Shrinking must handle conditional draw structures."""
        def test_fn(data):
            mode = data.draw_integer(label="mode")
            if mode >= 1:
                x = data.draw_integer(label="x")
                if x >= 100:
                    data.mark_interesting()

        initial = [make_int(5), make_int(500)]
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        result = shrinker.shrink_target
        assert len(result) == 2
        assert result[0].value == 1
        assert result[1].value == 100

    def test_sum_constraint(self):
        """Sum constraint: a+b must equal exactly the threshold after shrinking."""
        def test_fn(data):
            a = data.draw_integer(label="a")
            b = data.draw_integer(label="b")
            if a + b >= 10:
                data.mark_interesting()

        initial = [make_int(50), make_int(80)]
        shrinker = Shrinker(test_fn, initial)
        shrinker.shrink()
        result = shrinker.shrink_target
        a_val = result[0].value
        b_val = result[1].value
        assert a_val + b_val == 10
        res = run_test_function(test_fn, result)
        assert res.status == Status.INTERESTING

    def test_nested_conditional(self):
        """Nested structure with deletion and value minimization combined."""
        def test_fn(data):
            depth = data.draw_integer(label="depth")
            if depth < 1:
                return
            for _ in range(depth):
                flag = data.draw_boolean(label="check")
                if flag:
                    val = data.draw_integer(label="payload")
                    if val >= 100:
                        data.mark_interesting()

        initial = [
            make_int(3, "depth"),
            make_bool(False, "check"),
            make_bool(True, "check"),
            make_int(200, "payload"),
            make_bool(False, "check"),
        ]
        shrinker = Shrinker(test_fn, initial, max_calls=5000)
        shrinker.shrink()
        result = shrinker.shrink_target
        assert len(result) == 3
        assert result[0].value == 1
        assert result[1].value is True
        assert result[2].value == 100

    def test_large_sequence_reduction(self):
        """Large sequence with many deletable prefix elements."""
        def test_fn(data):
            while True:
                v = data.draw_integer(label="v")
                if v >= 75:
                    data.mark_interesting()

        # Values: 0, 5, 10, ..., 95. First v >= 75 is at index 15 (v=75).
        initial = [make_int(i * 5) for i in range(20)]
        res = run_test_function(test_fn, initial)
        assert res.status == Status.INTERESTING, "Precondition: initial must be INTERESTING"

        shrinker = Shrinker(test_fn, initial, max_calls=5000)
        shrinker.shrink()
        result = shrinker.shrink_target
        assert len(result) == 1
        assert result[0].value == 75
