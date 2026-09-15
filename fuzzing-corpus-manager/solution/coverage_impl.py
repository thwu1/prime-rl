"""Coverage collection using Python 3.12's sys.monitoring API.

"""

import os
import sys
from pathlib import Path

from .types import Branch, Location


class CoverageCollector:
    """Collect branch-level coverage as a context manager using sys.monitoring."""

    tool_id: int = 4
    tool_name: str = "fuzzcorp"

    def __init__(self, exclude_prefixes: list[str] | None = None):
        self.branches: set[Branch] = set()
        self._exclude_prefixes = exclude_prefixes or []
        self._stdlib_path = str(Path(os.__file__).parent)

    def _should_trace(self, filename: str) -> bool:
        """Return True if this file should be traced for coverage."""
        # Filter standard library
        if filename.startswith(self._stdlib_path):
            return False
        # Filter generated/frozen code like "<frozen posixpath>"
        if filename.startswith("<") and filename.endswith(">"):
            return False
        # Filter user-specified prefixes
        for prefix in self._exclude_prefixes:
            if filename.startswith(prefix):
                return False
        return True

    def trace_branch(self, code, source_offset: int, dest_offset: int):
        """sys.monitoring callback for BRANCH events."""
        if not self._should_trace(code.co_filename):
            # Do NOT return sys.monitoring.DISABLE here — it permanently
            # disables tracking for this code location and persists across
            # context manager reuse.
            return

        positions = list(code.co_positions())
        s_start_line, _s_end_line, s_start_col, _s_end_col = positions[
            source_offset // 2
        ]
        d_start_line, _d_end_line, d_start_col, _d_end_col = positions[
            dest_offset // 2
        ]

        # Skip if any needed position info is None
        if (
            s_start_line is None
            or d_start_line is None
            or s_start_col is None
            or d_start_col is None
        ):
            return

        source = Location(code.co_filename, s_start_line, s_start_col)
        dest = Location(code.co_filename, d_start_line, d_start_col)
        self.branches.add(Branch(source, dest))

    def __enter__(self) -> "CoverageCollector":
        self.branches = set()
        sys.monitoring.use_tool_id(self.tool_id, self.tool_name)
        sys.monitoring.set_events(self.tool_id, sys.monitoring.events.BRANCH)
        sys.monitoring.register_callback(
            self.tool_id, sys.monitoring.events.BRANCH, self.trace_branch
        )
        return self

    def __exit__(self, *args) -> None:
        sys.monitoring.set_events(self.tool_id, 0)
        sys.monitoring.register_callback(
            self.tool_id, sys.monitoring.events.BRANCH, None
        )
        sys.monitoring.free_tool_id(self.tool_id)
