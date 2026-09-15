"""Coverage collection for the fuzzcorp framework."""

import os
import sys
from pathlib import Path

from .types import Branch, Location


class CoverageCollector:
    """Context manager that collects branch-level coverage from running Python code.

    Attributes:
        branches: set[Branch] — branches observed during the most recent
            context-manager session.

    Constructor accepts an optional ``exclude_prefixes`` list of path prefixes
    whose code should not be instrumented.
    """

    tool_id: int = 4
    tool_name: str = "fuzzcorp"

    def __init__(self, exclude_prefixes: list[str] | None = None):
        self.branches: set[Branch] = set()
        self._exclude_prefixes = exclude_prefixes or []

    def _should_trace(self, filename: str) -> bool:
        """Return True if this file should be traced for coverage."""
        raise NotImplementedError

    def trace_branch(self, code, source_offset: int, dest_offset: int):
        """Monitoring callback for branch events."""
        raise NotImplementedError

    def __enter__(self) -> "CoverageCollector":
        raise NotImplementedError

    def __exit__(self, *args) -> None:
        raise NotImplementedError
