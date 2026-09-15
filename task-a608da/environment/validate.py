"""Validation utility for the shrinker implementation.

Usage: python3 /app/validate.py

Runs simple test cases through the Shrinker and verifies basic invariants
that any correct shrinking implementation must satisfy.  Use this during
development to check your implementation before running the full test suite.
"""


import sys
import traceback

sys.path.insert(0, "/app")

from choiceseq import Choice, ChoiceConstraints as IC, ChoiceKind, sort_key
from runner import ConjectureData, Status, run_test
from shrinker import Shrinker


def validate(name, test_fn, initial, check):
    """Run the shrinker and validate the result against invariants."""
    try:
        s = Shrinker(test_fn, initial)
        result = s.shrink()

        # Invariant 1: result must still be interesting
        status, _ = run_test(test_fn, result)
        if status != Status.INTERESTING:
            print(f"FAIL {name}: result is not interesting (status={status.value})")
            vals = [(c.kind.value, c.value) for c in result]
            print(f"      result: {vals}")
            return False

        # Invariant 2: result must be <= initial in shortlex order
        if sort_key(result) > sort_key(initial):
            print(f"FAIL {name}: result is larger than initial")
            return False

        # Invariant 3: custom predicate
        if not check(result, s.calls):
            return False

        print(f"PASS {name} ({s.calls} calls, {len(result)} choices)")
        return True
    except Exception as e:
        print(f"ERROR {name}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return False


total = passed = 0


def run(name, test_fn, initial, check=lambda r, c: True):
    global total, passed
    total += 1
    if validate(name, test_fn, initial, check):
        passed += 1


# ---- Test cases ---- #

def _t_int(data):
    x = data.draw_integer(min_value=0, max_value=100)
    assert x < 10

run("int_boundary",
    _t_int,
    [Choice(ChoiceKind.INTEGER, 73, IC(min_value=0, max_value=100))],
    lambda r, c: r[0].value == 10)


def _t_pair(data):
    a = data.draw_integer(min_value=0, max_value=50)
    b = data.draw_integer(min_value=0, max_value=50)
    assert a + b <= 5

run("pair_sum",
    _t_pair,
    [Choice(ChoiceKind.INTEGER, 30, IC(min_value=0, max_value=50)),
     Choice(ChoiceKind.INTEGER, 25, IC(min_value=0, max_value=50))],
    lambda r, c: r[0].value == 0 and r[1].value == 6)


def _t_bool(data):
    a = data.draw_boolean()
    b = data.draw_boolean()
    assert not (a or b)

run("bool_any_true",
    _t_bool,
    [Choice(ChoiceKind.BOOLEAN, True, IC()),
     Choice(ChoiceKind.BOOLEAN, True, IC())],
    lambda r, c: r[0].value is False and r[1].value is True)


def _t_str(data):
    s = data.draw_string(max_length=50)
    assert len(s) == 0

run("string_nonempty",
    _t_str,
    [Choice(ChoiceKind.STRING, "hello", IC(max_length=50))],
    lambda r, c: len(r) == 1 and len(r[0].value) == 1)


def _t_efficiency(data):
    x = data.draw_integer(min_value=0, max_value=10000)
    assert x < 500

run("efficiency_check",
    _t_efficiency,
    [Choice(ChoiceKind.INTEGER, 9999, IC(min_value=0, max_value=10000))],
    lambda r, c: r[0].value == 500 and c < 100)


# ---- Summary ---- #
print(f"\n{'=' * 40}")
print(f"Result: {passed}/{total} passed")
if passed < total:
    print("Some checks failed — review output above.")
sys.exit(0 if passed == total else 1)
