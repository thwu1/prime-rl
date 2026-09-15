"""
Ochiai-metric statistical fault localization.
"""
import math


class OchiaiLocalizer:
    """Rank code locations by suspiciousness using the Ochiai metric."""

    def __init__(self):
        self.runs = []  # list of (coverage_frozenset, outcome_str)

    def add_run(self, coverage, outcome):
        """Record a test run. outcome is 'pass' or 'fail'."""
        self.runs.append((frozenset(coverage), outcome))

    def all_events(self):
        """Return the set of all observed events (code locations)."""
        events = set()
        for cov, _ in self.runs:
            events.update(cov)
        return events

    def suspiciousness(self, event):
        """Compute the Ochiai suspiciousness score for an event.

        Ochiai(e) = failed(e) / sqrt((failed(e) + not_in_failed(e)) *
                                      (failed(e) + passed(e)))
        """
        failed_with = 0
        failed_without = 0
        passed_with = 0

        for cov, outcome in self.runs:
            if outcome == 'fail':
                if event in cov:
                    failed_with += 1
                else:
                    failed_without += 1
            elif outcome == 'pass':
                if event in cov:
                    passed_with += 1

        numerator = failed_with
        denominator = math.sqrt(
            (failed_with + failed_without) * (failed_with + passed_with)
        )
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def rank(self):
        """Return all events sorted by descending suspiciousness.

        Returns list of (event, score) tuples.
        """
        events = self.all_events()
        ranked = [(event, self.suspiciousness(event)) for event in events]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked
