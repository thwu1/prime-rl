"""
pbt - A property-based testing library with test-case shrinking.

This library implements property-based testing with automatic test case
minimization (shrinking). Test cases are minimized under the shortlex
order: shorter choice sequences are preferred, and among equal-length
sequences, lexicographically smaller ones are preferred.

Based on minithesis by David R. MacIver (MPL 2.0).
https://github.com/DRMacIver/minithesis

"""

from __future__ import annotations

import hashlib
import os
from array import array
from enum import IntEnum
from random import Random
from typing import (
    cast,
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Mapping,
    NoReturn,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)


T = TypeVar("T", covariant=True)
S = TypeVar("S", covariant=True)
U = TypeVar("U")


class Database(Protocol):
    def __setitem__(self, key: str, value: bytes) -> None:
        ...

    def get(self, key: str) -> Optional[bytes]:
        ...

    def __delitem__(self, key: str) -> None:
        ...


def run_test(
    max_examples: int = 100,
    random: Optional[Random] = None,
    database: Optional[Database] = None,
    quiet: bool = False,
) -> Callable[[Callable[["TestCase"], None]], None]:
    """Decorator to run a test. Usage is:

    .. code-block: python

        @run_test()
        def _(test_case):
            n = test_case.choice(1000)
            ...

    The decorated function takes a ``TestCase`` argument,
    and should raise an exception to indicate a test failure.
    It will either run silently or print drawn values and then
    fail with an exception if the library finds some test case
    that fails.

    Arguments:

    * max_examples: the maximum number of valid test cases to run for.
    * random: An instance of random.Random for deterministic choices.
    * database: A dict-like object for caching results between runs.
    * quiet: Will not print anything on failure if True.
    """

    def accept(test: Callable[["TestCase"], None]) -> None:
        def mark_failures_interesting(test_case: "TestCase") -> None:
            try:
                test(test_case)
            except Exception:
                if test_case.status is not None:
                    raise
                test_case.mark_status(Status.INTERESTING)

        state = TestingState(
            random or Random(), mark_failures_interesting, max_examples
        )

        if database is None:
            db: Database = DirectoryDB(".pbt-cache")
        else:
            db = database

        previous_failure = db.get(test.__name__)

        if previous_failure is not None:
            choices = [
                int.from_bytes(previous_failure[i : i + 8], "big")
                for i in range(0, len(previous_failure), 8)
            ]
            state.test_function(TestCase.for_choices(choices))

        if state.result is None:
            state.run()

        if state.valid_test_cases == 0:
            raise Unsatisfiable()

        if state.result is None:
            try:
                del db[test.__name__]
            except KeyError:
                pass
        else:
            db[test.__name__] = b"".join(i.to_bytes(8, "big") for i in state.result)

        if state.result is not None:
            test(TestCase.for_choices(state.result, print_results=not quiet))

    return accept


class TestCase(object):
    """Represents a single generated test case, which consists
    of an underlying set of choices that produce values."""

    @classmethod
    def for_choices(
        cls,
        choices: Sequence[int],
        print_results: bool = False,
    ) -> "TestCase":
        """Returns a test case that makes this series of choices."""
        return TestCase(
            prefix=choices,
            random=None,
            max_size=len(choices),
            print_results=print_results,
        )

    def __init__(
        self,
        prefix: Sequence[int],
        random: Optional[Random],
        max_size: float = float("inf"),
        print_results: bool = False,
    ):
        self.prefix = prefix
        self.random: Random = cast(Random, random)
        self.max_size = max_size
        self.choices: "array[int]" = array("Q")
        self.status: Optional[Status] = None
        self.print_results = print_results
        self.depth = 0
        self.targeting_score: Optional[int] = None

    def choice(self, n: int) -> int:
        """Returns a number in the range [0, n]"""
        result = self.__make_choice(n, lambda: self.random.randint(0, n))
        if self.__should_print():
            print(f"choice({n}): {result}")
        return result

    def weighted(self, p: float) -> int:
        """Return True with probability ``p``."""
        if p <= 0:
            result = self.forced_choice(0)
        elif p >= 1:
            result = self.forced_choice(1)
        else:
            result = bool(self.__make_choice(1, lambda: int(self.random.random() <= p)))
        if self.__should_print():
            print(f"weighted({p}): {result}")
        return result

    def forced_choice(self, n: int) -> int:
        """Inserts a fake choice into the choice sequence, as if
        some call to choice() had returned ``n``."""
        if n.bit_length() > 64 or n < 0:
            raise ValueError(f"Invalid choice {n}")
        if self.status is not None:
            raise Frozen()
        if len(self.choices) >= self.max_size:
            self.mark_status(Status.OVERRUN)
        self.choices.append(n)
        return n

    def reject(self) -> NoReturn:
        """Mark this test case as invalid."""
        self.mark_status(Status.INVALID)

    def assume(self, precondition: bool) -> None:
        """If this precondition is not met, abort the test and
        mark this test case as invalid."""
        if not precondition:
            self.reject()

    def target(self, score: int) -> None:
        """Set a score to maximize. Multiple calls to this function
        will override previous ones."""
        self.targeting_score = score

    def any(self, possibility: "Possibility[U]") -> U:
        """Return a possible value from ``possibility``."""
        try:
            self.depth += 1
            result = possibility.produce(self)
        finally:
            self.depth -= 1

        if self.__should_print():
            print(f"any({possibility}): {result}")
        return result

    def mark_status(self, status: "Status") -> NoReturn:
        """Set the status and raise StopTest."""
        if self.status is not None:
            raise Frozen()
        self.status = status
        raise StopTest()

    def __should_print(self) -> bool:
        return self.print_results and self.depth == 0

    def __make_choice(self, n: int, rnd_method: Callable[[], int]) -> int:
        """Make a choice in [0, n], by calling rnd_method if
        randomness is needed."""
        if n.bit_length() > 64 or n < 0:
            raise ValueError(f"Invalid choice {n}")
        if self.status is not None:
            raise Frozen()
        if len(self.choices) >= self.max_size:
            self.mark_status(Status.OVERRUN)
        if len(self.choices) < len(self.prefix):
            result = self.prefix[len(self.choices)]
        else:
            result = rnd_method()
        self.choices.append(result)
        if result > n:
            self.mark_status(Status.INVALID)
        return result


class Possibility(Generic[T]):
    """Represents some range of values that might be used in
    a test, that can be requested from a ``TestCase``.

    Pass one of these to TestCase.any to get a concrete value.
    """

    def __init__(self, produce: Callable[["TestCase"], T], name: Optional[str] = None):
        self.produce = produce
        self.name = produce.__name__ if name is None else name

    def __repr__(self) -> str:
        return self.name

    def map(self, f: Callable[[T], S]) -> "Possibility[S]":
        """Returns a ``Possibility`` where values come from
        applying ``f`` to some possible value for ``self``."""
        return Possibility(
            lambda test_case: f(test_case.any(self)),
            name=f"{self.name}.map({f.__name__})",
        )

    def bind(self, f: Callable[[T], "Possibility[S]"]) -> "Possibility[S]":
        """Returns a ``Possibility`` where values come from
        applying ``f`` to some possible value for ``self`` then
        returning a possible value from that."""

        def produce(test_case: "TestCase") -> S:
            return test_case.any(f(test_case.any(self)))

        return Possibility[S](
            produce,
            name=f"{self.name}.bind({f.__name__})",
        )

    def satisfying(self, f: Callable[[T], bool]) -> "Possibility[T]":
        """Returns a ``Possibility`` whose values are any possible
        value of ``self`` for which ``f`` returns True."""

        def produce(test_case: "TestCase") -> T:
            for _ in range(3):
                candidate = test_case.any(self)
                if f(candidate):
                    return candidate
            test_case.reject()

        return Possibility[T](produce, name=f"{self.name}.select({f.__name__})")


def integers(m: int, n: int) -> Possibility[int]:
    """Any integer in the range [m, n] is possible"""
    return Possibility(lambda tc: m + tc.choice(n - m), name=f"integers({m}, {n})")


def lists(
    elements: Possibility[U],
    min_size: int = 0,
    max_size: float = float("inf"),
) -> Possibility[List[U]]:
    """Any lists whose elements are possible values from ``elements``."""

    def produce(test_case: "TestCase") -> List[U]:
        result: List[U] = []
        while True:
            if len(result) < min_size:
                test_case.forced_choice(1)
            elif len(result) + 1 >= max_size:
                test_case.forced_choice(0)
                break
            elif not test_case.weighted(0.9):
                break
            result.append(test_case.any(elements))
        return result

    return Possibility[List[U]](produce, name=f"lists({elements.name})")


def just(value: U) -> Possibility[U]:
    """Only ``value`` is possible."""
    return Possibility[U](lambda tc: value, name=f"just({value})")


def nothing() -> Possibility[NoReturn]:
    """No possible values. Any call to ``any`` will reject."""

    def produce(tc: "TestCase") -> NoReturn:
        tc.reject()

    return Possibility(produce)


def mix_of(*possibilities: Possibility[T]) -> Possibility[T]:
    """Possible values can be any value possible for one of ``possibilities``."""
    if not possibilities:
        return cast(Possibility[T], nothing())
    return Possibility(
        lambda tc: tc.any(possibilities[tc.choice(len(possibilities) - 1)]),
        name="mix_of({', '.join(p.name for p in possibilities)})",
    )


def tuples(*possibilities: Possibility[Any]) -> Possibility[Any]:
    """Any tuple t of length len(possibilities) such that t[i] is possible
    for possibilities[i] is possible."""
    return Possibility(
        lambda tc: tuple(tc.any(p) for p in possibilities),
        name="tuples({', '.join(p.name for p in possibilities)})",
    )


# We cap the maximum amount of entropy a test case can use.
BUFFER_SIZE = 8 * 1024


def sort_key(choices: Sequence[int]) -> Tuple[int, Sequence[int]]:
    """Returns a key that can be used for the shrinking order
    of test cases."""
    return (len(choices), choices)


class CachedTestFunction(object):
    """Returns a cached version of a function that maps
    a choice sequence to the status of calling a test function
    on a test case populated with it. Takes advantage of the
    structure of the test function to predict results even if
    exact sequence of choices has not been seen previously."""

    def __init__(self, test_function: Callable[["TestCase"], None]):
        self.test_function = test_function
        self.tree: Dict[int, Union[Status, Dict[int, Any]]] = {}

    def __call__(self, choices: Sequence[int]) -> Status:
        node: Any = self.tree
        try:
            for c in choices:
                node = node[c]
                if isinstance(node, Status):
                    assert node != Status.OVERRUN
                    return node
            return Status.OVERRUN
        except KeyError:
            pass

        test_case = TestCase.for_choices(choices)
        self.test_function(test_case)
        assert test_case.status is not None

        node = self.tree
        for i, c in enumerate(test_case.choices):
            if i + 1 < len(test_case.choices) or test_case.status == Status.OVERRUN:
                try:
                    node = node[c]
                except KeyError:
                    node = node.setdefault(c, {})
            else:
                node[c] = test_case.status
        return test_case.status


class TestingState(object):
    def __init__(
        self,
        random: Random,
        test_function: Callable[["TestCase"], None],
        max_examples: int,
    ):
        self.random = random
        self.max_examples = max_examples
        self.__test_function = test_function
        self.valid_test_cases = 0
        self.calls = 0
        self.result: Optional["array[int]"] = None
        self.best_scoring: Optional[Tuple[int, Sequence[int]]] = None
        self.test_is_trivial = False

    def test_function(self, test_case: "TestCase") -> None:
        try:
            self.__test_function(test_case)
        except StopTest:
            pass
        if test_case.status is None:
            test_case.status = Status.VALID
        self.calls += 1
        if test_case.status >= Status.INVALID and len(test_case.choices) == 0:
            self.test_is_trivial = True
        if test_case.status >= Status.VALID:
            self.valid_test_cases += 1

            if test_case.targeting_score is not None:
                relevant_info = (test_case.targeting_score, test_case.choices)
                if self.best_scoring is None:
                    self.best_scoring = relevant_info
                else:
                    best, _ = self.best_scoring
                    if test_case.targeting_score > best:
                        self.best_scoring = relevant_info

        if test_case.status == Status.INTERESTING and (
            self.result is None or sort_key(test_case.choices) < sort_key(self.result)
        ):
            self.result = test_case.choices

    def target(self) -> None:
        """If any test cases have had ``target()`` called on them, do a simple
        hill climbing algorithm to attempt to optimise that target score."""
        if self.result is not None or self.best_scoring is None:
            return

        def adjust(i: int, step: int) -> bool:
            assert self.best_scoring is not None
            score, choices = self.best_scoring
            if choices[i] + step < 0 or choices[i].bit_length() >= 64:
                return False
            attempt = array("Q", choices)
            attempt[i] += step
            test_case = TestCase(
                prefix=attempt, random=self.random, max_size=BUFFER_SIZE
            )
            self.test_function(test_case)
            assert test_case.status is not None
            return (
                test_case.status >= Status.VALID
                and test_case.targeting_score is not None
                and test_case.targeting_score > score
            )

        while self.should_keep_generating():
            i = self.random.randrange(0, len(self.best_scoring[1]))
            sign = 0
            for k in [1, -1]:
                if not self.should_keep_generating():
                    return
                if adjust(i, k):
                    sign = k
                    break
            if sign == 0:
                continue

            k = 1
            while self.should_keep_generating() and adjust(i, sign * k):
                k *= 2

            while k > 0:
                while self.should_keep_generating() and adjust(i, sign * k):
                    pass
                k //= 2

    def run(self) -> None:
        self.generate()
        self.target()
        self.shrink()

    def should_keep_generating(self) -> bool:
        return (
            not self.test_is_trivial
            and self.result is None
            and self.valid_test_cases < self.max_examples
            and self.calls < self.max_examples * 10
        )

    def generate(self) -> None:
        """Run random generation until either we have found an interesting
        test case or hit the limit."""
        while self.should_keep_generating() and (
            self.best_scoring is None
            or self.valid_test_cases <= self.max_examples // 2
        ):
            self.test_function(
                TestCase(prefix=(), random=self.random, max_size=BUFFER_SIZE)
            )

    def shrink(self) -> None:
        """If we have found an interesting example, try shrinking it
        so that the choice sequence leading to our best example is
        shortlex smaller than the one we originally found.

        The shrinking process applies a series of reduction passes
        repeatedly until no pass can make further progress (i.e. the
        result is a fixed point of all passes).
        """
        if not self.result:
            return

        cached = CachedTestFunction(self.test_function)

        def consider(choices: "array[int]") -> bool:
            if choices == self.result:
                return True
            return cached(choices) == Status.INTERESTING

        assert consider(self.result)

        prev = None
        while prev != self.result:
            prev = self.result

            # Pass 1: Chunk deletion
            # Try deleting contiguous chunks of the choice sequence.
            # We iterate backwards because later choices tend to depend
            # on earlier ones, so it's easier to make changes near the end.
            k = 8
            while k > 0:
                i = len(self.result) - k - 1
                while i >= 0:
                    if i >= len(self.result):
                        i -= 1
                        continue
                    attempt = self.result[:i] + self.result[i + k :]
                    assert len(attempt) < len(self.result)
                    if not consider(attempt):
                        # When deletion fails, try decrementing the previous
                        # value. This handles length-dependent structures
                        # where deleting an element also requires lowering
                        # the length parameter.
                        if i > 0 and attempt[i - 1] > 0:
                            attempt[i - 1] -= 1
                            if consider(attempt):
                                i += 1
                        i -= 1
                k -= 1

            def replace(values: Mapping[int, int]) -> bool:
                """Attempt to replace some indices in the current
                result with new values."""
                assert self.result is not None
                attempt = array("Q", self.result)
                for i, v in values.items():
                    if i >= len(attempt):
                        return False
                    attempt[i] = v
                return consider(attempt)

            # Pass 2: Block zeroing
            # Try replacing contiguous blocks of k choices with 0,
            # for k from 8 down to 2 (k=1 handled by pass 3).
            # TODO: Implement block zeroing.

            # Pass 3: Individual value lowering via binary search
            # Try replacing each choice with a smaller value by doing
            # a binary search between 0 and the current value.
            i = len(self.result) - 1
            while i >= 0:
                bin_search_down(0, self.result[i], lambda v: replace({i: v}))
                i -= 1

            # Pass 4: Range sorting
            # Try sorting sub-ranges of the choice sequence. Since
            # sorted(x) <= x in shortlex order, this is always a
            # valid reduction.
            # TODO: Implement range sorting.

            # Pass 5: Pair redistribution
            # Try redistributing values between nearby pairs of choices
            # to minimize earlier values. This handles properties that
            # depend on sums of generated values.
            # TODO: Implement pair redistribution.


def bin_search_down(lo: int, hi: int, f: Callable[[int], bool]) -> int:
    """Returns n in [lo, hi] such that f(n) is True,
    where it is assumed and will not be checked that
    f(hi) is True.

    Will return ``lo`` if ``f(lo)`` is True, otherwise
    the only guarantee that is made is that ``f(n - 1)``
    is False and ``f(n)`` is True. In particular this
    does *not* guarantee to find the smallest value,
    only a locally minimal one.
    """
    while lo + 1 < hi:
        mid = lo + (hi - lo) // 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return hi


class DirectoryDB:
    """A basic key/value store using the filesystem."""

    def __init__(self, directory: str):
        self.directory = directory
        try:
            os.mkdir(directory)
        except FileExistsError:
            pass

    def __to_file(self, key: str) -> str:
        return os.path.join(
            self.directory, hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        )

    def __setitem__(self, key: str, value: bytes) -> None:
        with open(self.__to_file(key), "wb") as o:
            o.write(value)

    def get(self, key: str) -> Optional[bytes]:
        f = self.__to_file(key)
        if not os.path.exists(f):
            return None
        with open(f, "rb") as i:
            return i.read()

    def __delitem__(self, key: str) -> None:
        try:
            os.unlink(self.__to_file(key))
        except FileNotFoundError:
            raise KeyError()


class Frozen(Exception):
    """Attempted to make choices on a test case that has been completed."""


class StopTest(Exception):
    """Raised when a test should stop executing early."""


class Unsatisfiable(Exception):
    """Raised when a test has no valid examples."""


class Status(IntEnum):
    # Test case didn't have enough data to complete
    OVERRUN = 0

    # Test case contained something that prevented completion
    INVALID = 1

    # Test case completed just fine but was boring
    VALID = 2

    # Test case completed and was interesting
    INTERESTING = 3
