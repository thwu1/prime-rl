
"""Tests for the PBT library's shrinking engine.

These tests verify both correctness (the library runs without errors)
and shrink quality (the library produces minimal failing test cases).
"""

from random import Random

import pytest

from pbt import (
    CachedTestFunction,
    Frozen,
    Possibility,
    Status,
    TestCase,
    TestingState,
    Unsatisfiable,
    integers,
    just,
    lists,
    mix_of,
    nothing,
    run_test,
    tuples,
)


# ── Shrink quality tests ────────────────────────────────────────────


@pytest.mark.parametrize("seed", range(5))
def test_finds_small_list(capsys, seed):
    """Lists with sum > 1000 should shrink to [1001]."""
    with pytest.raises(AssertionError):

        @run_test(database={}, random=Random(seed))
        def _(test_case):
            ls = test_case.any(lists(integers(0, 10000)))
            assert sum(ls) <= 1000

    captured = capsys.readouterr()
    assert captured.out.strip() == "any(lists(integers(0, 10000))): [1001]"


@pytest.mark.parametrize("seed", range(5))
def test_finds_small_list_even_with_bad_lists(capsys, seed):
    """Even lists generated with a length parameter (monadic bind)
    should shrink to [1001]. This requires sorting to move the large
    element to the end so chunk deletion can work with the length
    parameter."""
    with pytest.raises(AssertionError):

        @Possibility
        def bad_list(test_case):
            n = test_case.choice(10)
            return [test_case.choice(10000) for _ in range(n)]

        @run_test(database={}, random=Random(seed))
        def _(test_case):
            ls = test_case.any(bad_list)
            assert sum(ls) <= 1000

    captured = capsys.readouterr()
    assert captured.out.strip() == "any(bad_list): [1001]"


def test_reduces_additive_pairs(capsys):
    """When two choices must sum to > 1000, the shrinker should
    redistribute value so the first choice is minimal (1) and the
    second is maximal (1000)."""
    with pytest.raises(AssertionError):

        @run_test(database={}, max_examples=10000, random=Random(0))
        def _(test_case):
            m = test_case.choice(1000)
            n = test_case.choice(1000)
            assert m + n <= 1000

    captured = capsys.readouterr()
    assert [c.strip() for c in captured.out.splitlines()] == [
        "choice(1000): 1",
        "choice(1000): 1000",
    ]


def test_irrelevant_choice_zeroed(capsys):
    """Choices that don't affect the failing property should be
    minimized to 0."""
    with pytest.raises(AssertionError):

        @run_test(database={}, max_examples=1000, random=Random(0))
        def _(test_case):
            test_case.choice(1000)  # irrelevant to the property
            n = test_case.choice(1000)
            assert n < 100

    captured = capsys.readouterr()
    assert [c.strip() for c in captured.out.splitlines()] == [
        "choice(1000): 0",
        "choice(1000): 100",
    ]


def test_redistributes_three_choices(capsys):
    """When three choices must sum above a threshold, the shrinker
    should minimize earlier choices by shifting value to later ones.
    This requires both correct binary search boundaries and value
    redistribution between pairs."""
    with pytest.raises(AssertionError):

        @run_test(database={}, max_examples=10000, random=Random(0))
        def _(tc):
            a = tc.choice(100)
            b = tc.choice(100)
            c = tc.choice(100)
            assert a + b + c <= 10

    captured = capsys.readouterr()
    assert [c.strip() for c in captured.out.splitlines()] == [
        "choice(100): 0",
        "choice(100): 0",
        "choice(100): 11",
    ]


def test_target_and_reduce(capsys):
    """Targeting should find a high value, then shrinking should
    reduce it to the minimal failing value."""
    with pytest.raises(AssertionError):

        @run_test(database={}, random=Random(0))
        def _(tc):
            m = tc.choice(100000)
            tc.target(m)
            assert m <= 99900

    captured = capsys.readouterr()
    assert captured.out.strip() == "choice(100000): 99901"


def test_can_target_score_upwards(capsys):
    """Targeting combined with shrinking should find the maximum
    possible score when it triggers a failure."""
    with pytest.raises(AssertionError):

        @run_test(database={}, max_examples=1000, random=Random(0))
        def _(test_case):
            n = test_case.choice(1000)
            m = test_case.choice(1000)
            score = n + m
            test_case.target(score)
            assert score < 2000

    captured = capsys.readouterr()
    assert [c.strip() for c in captured.out.splitlines()] == [
        "choice(1000): 1000",
        "choice(1000): 1000",
    ]


# ── Correctness tests ───────────────────────────────────────────────


def test_test_cases_satisfy_preconditions():
    """Preconditions (assume) should filter invalid test cases."""

    @run_test(database={})
    def _(test_case):
        n = test_case.choice(10)
        test_case.assume(n != 0)
        assert n != 0


def test_error_on_too_strict_precondition():
    """A test that always rejects should raise Unsatisfiable."""
    with pytest.raises(Unsatisfiable):

        @run_test(database={})
        def _(test_case):
            test_case.choice(10)
            test_case.reject()


def test_function_cache():
    """The CachedTestFunction should avoid redundant calls."""

    def tf(tc):
        if tc.choice(1000) >= 200:
            tc.mark_status(Status.INTERESTING)
        if tc.choice(1) == 0:
            tc.reject()

    state = TestingState(Random(0), tf, 100)
    cache = CachedTestFunction(state.test_function)

    assert cache([1, 1]) == Status.VALID
    assert cache([1]) == Status.OVERRUN
    assert cache([1000]) == Status.INTERESTING
    assert cache([1000]) == Status.INTERESTING
    assert cache([1000, 1]) == Status.INTERESTING

    assert state.calls == 2


def test_errors_when_using_frozen():
    """Operations on a frozen TestCase should raise Frozen."""
    tc = TestCase.for_choices([0])
    tc.status = Status.VALID

    with pytest.raises(Frozen):
        tc.mark_status(Status.INTERESTING)

    with pytest.raises(Frozen):
        tc.choice(10)

    with pytest.raises(Frozen):
        tc.forced_choice(10)


def test_mapped_possibility():
    """Mapped possibilities should produce transformed values."""

    @run_test(database={})
    def _(tc):
        n = tc.any(integers(0, 5).map(lambda n: n * 2))
        assert n % 2 == 0


def test_size_bounds_on_list():
    """Lists with size bounds should respect them."""

    @run_test(database={})
    def _(tc):
        ls = tc.any(lists(integers(0, 10), min_size=1, max_size=3))
        assert 1 <= len(ls) <= 3
