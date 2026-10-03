#!/usr/bin/env python3
"""Emit an aggregate-only, explicitly non-certifying Qwen diagnostic summary."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path

from audit_traces import (
    QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
    _iter_traces,
    _read_expected_slugs,
    _summarize_traces,
)


class DiagnosticError(ValueError):
    """A diagnostic artifact failed aggregate validation."""


def _publish_exclusive(path: Path, value: object) -> None:
    payload = (json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def summarize(results: Path, expected_task_file: Path, cleanup_audit: Path, output: Path) -> dict[str, object]:
    expected = _read_expected_slugs(expected_task_file)
    if len(expected) != 1:
        raise DiagnosticError("diagnostic_task_count_invalid")
    traces = list(_iter_traces(results))
    summary, failed = _summarize_traces(
        traces,
        expected_slugs=expected,
        expected_count=1,
        rollouts_per_task=1,
        require_reasoning=True,
        require_token_data=False,
        require_logprobs=False,
        require_model_io=True,
        aggregate_only=True,
        model_io_contract=QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
        require_request_graph_match=True,
        max_sequence_tokens=262_144,
    )
    try:
        cleanup = json.loads(cleanup_audit.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise DiagnosticError("diagnostic_cleanup_invalid") from error
    if (
        not isinstance(cleanup, dict)
        or cleanup.get("kind") != "sandoq-pool-cleanup"
        or cleanup.get("state") != "passed"
        or cleanup.get("failures") != 0
    ):
        raise DiagnosticError("diagnostic_cleanup_invalid")
    if len(traces) != 1:
        raise DiagnosticError("diagnostic_trace_count_invalid")
    rewards = traces[0].get("rewards")
    if not isinstance(rewards, dict) or not rewards:
        reward: float | None = None
    else:
        values = list(rewards.values())
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        ):
            raise DiagnosticError("diagnostic_reward_invalid")
        reward = float(sum(values))
    result = {
        "schema_version": 1,
        "kind": "qwen-sandoq-noncertifying-diagnostic",
        "certifying": False,
        "state": "failed" if failed else "passed",
        "traces": summary["traces"],
        "model_io_turns": summary.get("model_io_turns", 0),
        "trace_failures": summary["trace_failures"],
        "problem_counts": summary.get("problem_counts", {}),
        "reward": reward,
        "cleanup_verified": True,
    }
    _publish_exclusive(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--expected-task-file", type=Path, required=True)
    parser.add_argument("--cleanup-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = summarize(args.results, args.expected_task_file, args.cleanup_audit, args.output)
    except Exception:  # noqa: BLE001 - never disclose private diagnostic content
        print("Qwen Sandoq diagnostic validation failed", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, allow_nan=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["state"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
