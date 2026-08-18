"""Keep commit-pinned RSCI jobs from importing the mutable source checkout."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


snapshot_value = os.environ.get("RSCI_SOURCE_SNAPSHOT")
live_repo_value = os.environ.get("RSCI_LIVE_REPO_ROOT")
if snapshot_value and live_repo_value:
    snapshot = Path(snapshot_value).resolve()
    live_repo = Path(live_repo_value).resolve()
    guarded_path = []
    for entry in sys.path:
        if not entry:
            guarded_path.append(entry)
            continue
        resolved = Path(entry).resolve()
        if _is_within(resolved, live_repo) and not _is_within(resolved, snapshot):
            continue
        guarded_path.append(entry)
    sys.path[:] = guarded_path
