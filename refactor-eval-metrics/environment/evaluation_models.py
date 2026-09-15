"""Reference implementation of refactoring evaluation metrics.

This module defines the metric computation model used by the CodeTaste
benchmark for evaluating code refactoring quality. Study this code to
understand the precise formulas for IFR, test validity, and alignment.

Note: This is reference code — your pipeline implementation does not
need to use these exact classes or Pydantic. Implement the same logic
using whatever approach you prefer.
"""

from typing import Optional


class TestMetrics:
    """Test execution metrics for a single benchmark instance.

    Attributes:
        passed: Number of tests that passed
        failed: Number of tests that failed
        skipped: Number of tests that were skipped
        total: Total number of tests
        error: Error message if test execution itself failed, None otherwise
    """

    def __init__(self, passed: int, failed: int, total: int,
                 skipped: int = 0, error: Optional[str] = None):
        self.passed = passed
        self.failed = failed
        self.skipped = skipped
        self.total = total
        self.error = error

    @property
    def pass_rate(self) -> float:
        """Fraction of tests that passed."""
        return self.passed / self.total if self.total > 0 else 0.0

    @property
    def is_valid(self) -> bool:
        """Test suite validity check.

        Valid when: no execution error, at least 10 tests total,
        and at least 30% pass rate."""
        return (self.error is None
                and self.total >= 10
                and (self.passed / self.total) >= 0.3)


class RuleMetrics:
    """Rule evaluation metrics from SARIF static analysis output.

    Positive rules define desired patterns (should appear after refactoring).
    Negative rules define undesired patterns (should be absent after refactoring).

    A "matched" rule means the pattern was found in the refactored code.
    For positive rules, matching is good. For negative rules, matching is bad.

    Attributes:
        positive_rules_matched: Number of desired-pattern rules that matched
        negative_rules_matched: Number of undesired-pattern rules that matched
        total_positive_rules: Total number of desired-pattern rules defined
        total_negative_rules: Total number of undesired-pattern rules defined
    """

    def __init__(self, positive_rules_matched: int, negative_rules_matched: int,
                 total_positive_rules: int, total_negative_rules: int):
        self.positive_rules_matched = positive_rules_matched
        self.negative_rules_matched = negative_rules_matched
        self.total_positive_rules = total_positive_rules
        self.total_negative_rules = total_negative_rules

    @property
    def ifr(self) -> Optional[float]:
        """Combined Instruction Following Rate.

        IFR = (positive_matched + negative_avoided) / total_rules

        where negative_avoided = total_negative - negative_matched
        """
        total = self.total_positive_rules + self.total_negative_rules
        if total == 0:
            return None
        followed = self.positive_rules_matched + (
            self.total_negative_rules - self.negative_rules_matched
        )
        return followed / total

    @property
    def positive_ifr(self) -> Optional[float]:
        """Positive instruction following rate.

        Fraction of desired patterns that were successfully introduced.
        """
        if self.total_positive_rules == 0:
            return None
        return self.positive_rules_matched / self.total_positive_rules

    @property
    def negative_ifr(self) -> Optional[float]:
        """Negative instruction following rate.

        Fraction of undesired patterns that were successfully removed.
        """
        if self.total_negative_rules == 0:
            return None
        avoided = self.total_negative_rules - self.negative_rules_matched
        return avoided / self.total_negative_rules


# Alignment Score
# ===============
# alignment = pass_score * ifr
#
# where:
#   pass_score = 1.0 if TestMetrics.is_valid else 0.0
#
# Alignment is 0.0 when tests are invalid (pass_score=0),
# regardless of how high the IFR might be.
# Alignment is null when ifr is null (no rules defined at all).
