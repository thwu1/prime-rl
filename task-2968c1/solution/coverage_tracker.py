"""
Coverage tracker using sys.settrace for line-level instrumentation.
"""
import sys


class CoverageTracker:
    """Track which lines execute during a function call."""

    def __init__(self):
        self._last_coverage = frozenset()

    def track(self, func, *args, **kwargs):
        """Run func(*args, **kwargs) while recording line coverage.

        Returns (result, exception_or_None, frozenset of (filename, lineno)).
        """
        coverage = set()

        def tracer(frame, event, arg):
            if event == 'line':
                coverage.add((frame.f_code.co_filename, frame.f_lineno))
            return tracer

        old = sys.gettrace()
        sys.settrace(tracer)
        try:
            result = func(*args, **kwargs)
            exc = None
        except Exception as e:
            result = None
            exc = e
        finally:
            sys.settrace(old)

        self._last_coverage = frozenset(coverage)
        return result, exc, self._last_coverage

    def track_file(self, func, target_file, *args, **kwargs):
        """Like track() but only records coverage for lines in target_file."""
        coverage = set()

        def tracer(frame, event, arg):
            if event == 'line':
                if frame.f_code.co_filename == target_file:
                    coverage.add((frame.f_code.co_filename, frame.f_lineno))
            return tracer

        old = sys.gettrace()
        sys.settrace(tracer)
        try:
            result = func(*args, **kwargs)
            exc = None
        except Exception as e:
            result = None
            exc = e
        finally:
            sys.settrace(old)

        self._last_coverage = frozenset(coverage)
        return result, exc, self._last_coverage
