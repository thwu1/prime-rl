#!/usr/bin/env python3
"""Summarize redacted Sandoq image-build receipts without task identifiers."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

SAFE_LABEL = re.compile(r"[A-Za-z0-9_.+-]+")


def _label(value: object) -> str:
    if value is None:
        return "unavailable"
    if not isinstance(value, str) or SAFE_LABEL.fullmatch(value) is None:
        return "invalid"
    return value


def summarize(status_root: Path) -> dict[str, object]:
    states: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    cleanup: Counter[str] = Counter()
    receipts = 0
    unreadable = 0
    for path in status_root.glob("*.json"):
        receipts += 1
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            unreadable += 1
            continue
        if not isinstance(value, dict):
            unreadable += 1
            continue
        state = _label(value.get("state"))
        states[state] += 1
        if state != "failed":
            continue
        stages[_label(value.get("failure_stage"))] += 1
        classes[_label(value.get("diagnostic_class"))] += 1
        cleanup[str(value.get("cleanup_verified") is True).lower()] += 1
    return {
        "schema_version": 1,
        "receipts": receipts,
        "unreadable_receipts": unreadable,
        "states": dict(sorted(states.items())),
        "failure_stages": dict(sorted(stages.items())),
        "diagnostic_classes": dict(sorted(classes.items())),
        "failure_cleanup_verified": dict(sorted(cleanup.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.status_root.is_dir():
        parser.error("status root must be a directory")
    print(json.dumps(summarize(args.status_root), sort_keys=True))


if __name__ == "__main__":
    main()
