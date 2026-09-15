"""Verification tests for the choice-sequence shrinker.

Each test constructs an initial interesting choice sequence, runs the
shrinker, and asserts properties of the minimal result.
"""


import sys

sys.path.insert(0, "/app")

import pytest

from choiceseq import Choice, ChoiceConstraints, ChoiceKind, choice_to_index, sort_key
from runner import ConjectureData, Status
from shrinker import Shrinker

IC = ChoiceConstraints  # shorthand


# ------------------------------------------------------------------ #
#  1. Single integer – boundary minimisation via binary search        #
# ------------------------------------------------------------------ #
def test_minimize_single_integer():
    """x >= 42 is interesting.  Should shrink from 789 to exactly 42."""

    def test_fn(data: ConjectureData):
        x = data.draw_integer(min_value=0, max_value=1000)
        assert x < 42

    choices = [Choice(ChoiceKind.INTEGER, 789, IC(min_value=0, max_value=1000))]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 1
    assert result[0].value == 42


# ------------------------------------------------------------------ #
#  2. Two integers – independent minimisation                         #
# ------------------------------------------------------------------ #
def test_minimize_sum_pair():
    """a + b > 10 is interesting.  Minimal pair is (0, 11)."""

    def test_fn(data: ConjectureData):
        a = data.draw_integer(min_value=0, max_value=100)
        b = data.draw_integer(min_value=0, max_value=100)
        assert a + b <= 10

    choices = [
        Choice(ChoiceKind.INTEGER, 73, IC(min_value=0, max_value=100)),
        Choice(ChoiceKind.INTEGER, 45, IC(min_value=0, max_value=100)),
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 2
    assert result[0].value + result[1].value >= 11
    # Shortlex-minimal: first element as small as possible → 0
    assert result[0].value == 0
    assert result[1].value == 11


# ------------------------------------------------------------------ #
#  3. Booleans – zero pass sets as many to False as possible          #
# ------------------------------------------------------------------ #
def test_minimize_booleans():
    """sum >= 2 is interesting.  Minimal triple is (False, True, True)."""

    def test_fn(data: ConjectureData):
        a = data.draw_boolean()
        b = data.draw_boolean()
        c = data.draw_boolean()
        assert sum([a, b, c]) < 2

    choices = [
        Choice(ChoiceKind.BOOLEAN, True, IC()),
        Choice(ChoiceKind.BOOLEAN, True, IC()),
        Choice(ChoiceKind.BOOLEAN, True, IC()),
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 3
    assert sum(c.value for c in result) == 2
    assert result[0].value is False
    assert result[1].value is True
    assert result[2].value is True


# ------------------------------------------------------------------ #
#  4. String – shorten then simplify characters                       #
# ------------------------------------------------------------------ #
def test_minimize_string():
    """'a' in s is interesting.  Minimal string is 'a'."""

    def test_fn(data: ConjectureData):
        s = data.draw_string(max_length=100)
        assert "a" not in s

    choices = [
        Choice(ChoiceKind.STRING, "hello world abc", IC(max_length=100))
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 1
    assert "a" in result[0].value
    assert len(result[0].value) == 1
    assert result[0].value == "a"


# ------------------------------------------------------------------ #
#  5. Float – should shrink to the smallest integer boundary          #
# ------------------------------------------------------------------ #
def test_minimize_float_to_integer():
    """x >= 1.0 is interesting.  Should shrink to 1 (or 1.0)."""

    def test_fn(data: ConjectureData):
        x = data.draw_float(min_value=0.0, max_value=1000.0)
        assert x < 1.0

    choices = [
        Choice(ChoiceKind.FLOAT, 847.239, IC(min_value=0.0, max_value=1000.0))
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 1
    assert result[0].value == 1.0  # works for both int(1) and float(1.0)


# ------------------------------------------------------------------ #
#  6. Redistribution – concentrate value in one integer               #
# ------------------------------------------------------------------ #
def test_redistribute_concentrates():
    """a + b >= 20 starting from (15, 15) → (0, 20)."""

    def test_fn(data: ConjectureData):
        a = data.draw_integer(min_value=0, max_value=100)
        b = data.draw_integer(min_value=0, max_value=100)
        assert a + b < 20

    choices = [
        Choice(ChoiceKind.INTEGER, 15, IC(min_value=0, max_value=100)),
        Choice(ChoiceKind.INTEGER, 15, IC(min_value=0, max_value=100)),
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 2
    assert result[0].value + result[1].value >= 20
    assert result[0].value == 0
    assert result[1].value == 20


# ------------------------------------------------------------------ #
#  7. Convergence – three integers, all value to the last             #
# ------------------------------------------------------------------ #
def test_shrink_convergence():
    """a + b + c >= 30 starting from (50, 40, 30) → (0, 0, 30)."""

    def test_fn(data: ConjectureData):
        a = data.draw_integer(min_value=0, max_value=200)
        b = data.draw_integer(min_value=0, max_value=200)
        c = data.draw_integer(min_value=0, max_value=200)
        assert a + b + c < 30

    choices = [
        Choice(ChoiceKind.INTEGER, 50, IC(min_value=0, max_value=200)),
        Choice(ChoiceKind.INTEGER, 40, IC(min_value=0, max_value=200)),
        Choice(ChoiceKind.INTEGER, 30, IC(min_value=0, max_value=200)),
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 3
    total = sum(c.value for c in result)
    assert total >= 30
    assert result[0].value == 0
    assert result[1].value == 0
    assert result[2].value == 30


# ------------------------------------------------------------------ #
#  8. Efficiency – binary search must not be linear                   #
# ------------------------------------------------------------------ #
def test_efficiency_binary_search():
    """Shrinking 9999 → 500 should need far fewer than 9999 calls."""

    def test_fn(data: ConjectureData):
        x = data.draw_integer(min_value=0, max_value=10000)
        assert x < 500

    choices = [
        Choice(ChoiceKind.INTEGER, 9999, IC(min_value=0, max_value=10000))
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert result[0].value == 500
    assert shrinker.calls < 100  # binary search ≈ 15 calls


# ------------------------------------------------------------------ #
#  9. sort_key ordering sanity                                        #
# ------------------------------------------------------------------ #
def test_sort_key_ordering():
    """Verify basic sort_key properties."""
    c = IC(min_value=0, max_value=100)

    seq1 = [Choice(ChoiceKind.INTEGER, 0, c)]
    seq2 = [Choice(ChoiceKind.INTEGER, 0, c), Choice(ChoiceKind.INTEGER, 0, c)]
    assert sort_key(seq1) < sort_key(seq2), "shorter should be smaller"

    seq3 = [Choice(ChoiceKind.INTEGER, 1, c)]
    seq4 = [Choice(ChoiceKind.INTEGER, 2, c)]
    assert sort_key(seq3) < sort_key(seq4), "1 < 2"

    seqA = [Choice(ChoiceKind.INTEGER, 5, c), Choice(ChoiceKind.INTEGER, 10, c)]
    seqB = [Choice(ChoiceKind.INTEGER, 10, c), Choice(ChoiceKind.INTEGER, 5, c)]
    assert sort_key(seqA) < sort_key(seqB), "(5,10) < (10,5)"


# ------------------------------------------------------------------ #
#  10. consider must use drawn choices (trimming unused trailing)      #
# ------------------------------------------------------------------ #
def test_consider_uses_drawn():
    """When the test draws fewer choices, the result should be shorter."""

    def test_fn(data: ConjectureData):
        x = data.draw_integer(min_value=0, max_value=100)
        if x > 5:
            y = data.draw_integer(min_value=0, max_value=100)
            assert x + y < 50
        else:
            assert False  # always interesting for x <= 5

    choices = [
        Choice(ChoiceKind.INTEGER, 10, IC(min_value=0, max_value=100)),
        Choice(ChoiceKind.INTEGER, 50, IC(min_value=0, max_value=100)),
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    # x=0 takes the else branch → draws only 1 choice → result length 1
    assert len(result) == 1
    assert result[0].value == 0


# ------------------------------------------------------------------ #
#  11. Bytes – prefix shortening and byte zeroing                     #
# ------------------------------------------------------------------ #
def test_minimize_bytes():
    r"""Bytes containing b'\x00' is interesting.  Minimal is b'\x00'."""

    def test_fn(data: ConjectureData):
        b = data.draw_bytes(max_length=100)
        assert b"\x00" not in b

    choices = [
        Choice(ChoiceKind.BYTES, b"\x00\xff\xfe\xfd", IC(max_length=100))
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 1
    assert b"\x00" in result[0].value
    assert result[0].value == b"\x00"


# ------------------------------------------------------------------ #
#  12. Mixed types – joint integer + string minimisation              #
# ------------------------------------------------------------------ #
def test_mixed_types_minimal():
    """n >= 5 and 'x' in s is interesting.  Minimal is (5, 'x')."""

    def test_fn(data: ConjectureData):
        n = data.draw_integer(min_value=0, max_value=100)
        s = data.draw_string(max_length=50)
        assert not (n >= 5 and "x" in s)

    choices = [
        Choice(ChoiceKind.INTEGER, 77, IC(min_value=0, max_value=100)),
        Choice(ChoiceKind.STRING, "xhello", IC(max_length=50)),
    ]
    shrinker = Shrinker(test_fn, choices)
    result = shrinker.shrink()

    assert len(result) == 2
    assert result[0].value == 5
    assert result[1].value == "x"
