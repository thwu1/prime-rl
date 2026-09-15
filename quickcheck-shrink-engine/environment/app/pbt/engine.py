"""
Property-based test runner with shrinking support.
Port of the Rust quickcheck crate's test execution logic.
"""

from pbt.gen import Gen


class TestResult:
    """Result of a single property test."""

    def __init__(self, status, args=None, error=None):
        self.status = status
        self.args = args
        self.error = error

    @staticmethod
    def passed():
        return TestResult("pass")

    @staticmethod
    def failed():
        return TestResult("fail")

    @staticmethod
    def discard():
        return TestResult("discard")

    @staticmethod
    def from_bool(b):
        return TestResult("pass" if b else "fail")

    def is_failure(self):
        return self.status == "fail"

    def is_discard(self):
        return self.status == "discard"


def _is_failure(result):
    """Check if a predicate result indicates failure."""
    if isinstance(result, TestResult):
        return result.is_failure()
    return not result


def _is_discard(result):
    """Check if a predicate result indicates discard."""
    if isinstance(result, TestResult):
        return result.is_discard()
    return False


def find_minimal_counterexample(predicate, failing_input, shrinker):
    """Find a minimal counterexample by shrinking."""
    current = failing_input
    while True:
        found_smaller = False
        for candidate in shrinker(current):
            result = predicate(candidate)
            if _is_failure(result):
                current = candidate
                found_smaller = True
        if not found_smaller:
            return current


def quickcheck(
    predicate, generator, shrinker, num_tests=100, max_tests=10000, seed=None
):
    """Run a property-based test."""
    gen = Gen(seed=seed)

    n_passed = 0
    for _ in range(max_tests):
        if n_passed >= num_tests:
            break
        inp = generator(gen)
        result = predicate(inp)
        if _is_discard(result):
            continue
        elif _is_failure(result):
            minimal = find_minimal_counterexample(predicate, inp, shrinker)
            return {
                "status": "failed",
                "num_passed": n_passed,
                "counterexample": minimal,
                "original": inp,
            }
        else:
            n_passed += 1

    if n_passed >= num_tests:
        return {"status": "passed", "num_passed": n_passed}
    else:
        return {"status": "gave_up", "num_passed": n_passed}
