"""Coverage collection using sys.settrace."""

import sys
from types import FrameType
from typing import Set, Tuple, Optional, Any


class CoverageCollector:
    """Collect line-level coverage using sys.settrace."""

    def __init__(self, target_func_name: Optional[str] = None):
        self._coverage: Set[Tuple[str, int]] = set()
        self._target = target_func_name
        self._prev_trace = None

    def __enter__(self):
        self._prev_trace = sys.gettrace()
        sys.settrace(self._traceit)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        sys.settrace(self._prev_trace)
        return False

    def _traceit(self, frame: FrameType, event: str, arg: Any):
        if event == 'call':
            name = frame.f_code.co_name
            if self._target is None or name == self._target:
                return self._traceit
            return None
        if event == 'line':
            name = frame.f_code.co_name
            if self._target is None or name == self._target:
                self._coverage.add((name, frame.f_lineno))
        return self._traceit

    def coverage(self) -> Set[Tuple[str, int]]:
        """Return the set of (function_name, line_number) pairs covered."""
        return set(self._coverage)
