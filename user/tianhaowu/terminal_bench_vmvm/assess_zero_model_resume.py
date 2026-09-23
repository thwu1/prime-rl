#!/usr/bin/env python3
"""Decide whether an eval may safely resume missing or zero-model rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class ResumeAssessmentError(RuntimeError):
    """A stable, aggregate-only resume assessment failure."""


def _plain_nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def assess(results: Path, expected_count: int) -> dict[str, int | str]:
    if not results.is_absolute() or not results.is_file() or expected_count < 1:
        raise ResumeAssessmentError("resume_input_invalid")
    seen: set[int] = set()
    errors = 0
    with results.open("rb") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                row: Any = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ResumeAssessmentError("resume_results_invalid") from error
            task = row.get("task") if isinstance(row, dict) else None
            task_index = task.get("idx") if isinstance(task, dict) else None
            if not _plain_nonnegative_integer(task_index) or task_index in seen:
                raise ResumeAssessmentError("resume_results_invalid")
            seen.add(task_index)
            row_errors = row.get("errors")
            if not isinstance(row_errors, list):
                raise ResumeAssessmentError("resume_results_invalid")
            if row_errors:
                errors += 1
                if (
                    row.get("nodes") != []
                    or row.get("rewards") != {}
                    or row.get("metrics") != {}
                    or row.get("info") != {}
                ):
                    raise ResumeAssessmentError("model_bearing_error_not_retryable")
            elif not isinstance(row.get("nodes"), list) or not row["nodes"]:
                raise ResumeAssessmentError("completed_trace_invalid")
    if len(seen) > expected_count:
        raise ResumeAssessmentError("resume_results_invalid")
    missing = expected_count - len(seen)
    state = "complete" if errors == 0 and missing == 0 else "resume_required"
    return {
        "state": state,
        "observed_rows": len(seen),
        "zero_model_error_rows": errors,
        "missing_rows": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--format", choices=("json", "tsv"), default="json")
    args = parser.parse_args(argv)
    try:
        result = assess(args.results, args.expected_count)
    except ResumeAssessmentError as error:
        print(json.dumps({"code": str(error), "state": "blocked"}, sort_keys=True), file=sys.stderr)
        return 2
    if args.format == "tsv":
        print(
            result["state"],
            result["observed_rows"],
            result["zero_model_error_rows"],
            result["missing_rows"],
            sep="\t",
        )
    else:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
