#!/usr/bin/env python3
"""Fail-closed checkpoint for a 66-task CPU-only Terminal-Bench 4 eval."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from audit_traces import DEFAULT_MAX_SEQUENCE_TOKENS, TraceJSONLError, _audit_trace, _iter_traces, _task_slug

EXPECTED_TASK_COUNT = 66
EXPECTED_UNSUPPORTED_TASKS = frozenset(
    {
        "fp8-rmsnorm-gemm",
        "jax-speedrun-gpu",
        "math-eval-grader",
    }
)


class TB4AuditError(ValueError):
    """The expected TB4 input set could not be established safely."""


def _read_task_file(path: Path) -> list[str]:
    slugs = [
        line.strip().split("\t", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(slugs) != len(set(slugs)):
        raise TB4AuditError(f"{path}: duplicate task slugs")
    return slugs


def _expected_slugs(dataset_dir: Path, task_file: Path | None = None) -> set[str]:
    if not dataset_dir.is_dir():
        raise TB4AuditError(f"{dataset_dir}: dataset directory does not exist")
    dataset_slugs = {
        path.name
        for path in dataset_dir.iterdir()
        if path.is_dir() and (path / "task.toml").is_file() and (path / "instruction.md").is_file()
    }
    if task_file is None:
        expected = dataset_slugs
    else:
        requested = set(_read_task_file(task_file))
        if missing := sorted(requested - dataset_slugs):
            raise TB4AuditError(f"{task_file}: tasks missing from dataset: {missing[:20]!r} count={len(missing)}")
        expected = requested
    if len(expected) != EXPECTED_TASK_COUNT:
        raise TB4AuditError(f"expected exactly {EXPECTED_TASK_COUNT} TB4 tasks, found {len(expected)}")
    if missing := sorted(EXPECTED_UNSUPPORTED_TASKS - expected):
        raise TB4AuditError(f"expected GPU-unsupported tasks are absent: {missing!r}")
    return expected


def _unsupported_trace_problems(trace: dict, slug: str) -> list[str]:
    problems: list[str] = []
    task = trace.get("task")
    expected_name = f"terminal-bench/{slug}"
    if not isinstance(task, dict) or task.get("name") != expected_name:
        problems.append("unsupported_task_name_invalid")
    resources = task.get("resources") if isinstance(task, dict) else None
    if not isinstance(resources, dict) or resources.get("gpu") != "1":
        problems.append("unsupported_task_gpu_resource_missing")
    if trace.get("is_completed") is not True:
        problems.append("unsupported_trace_not_completed")
    if trace.get("stop_condition") != "error":
        problems.append("unsupported_trace_stop_condition_invalid")
    if trace.get("nodes") != []:
        problems.append("unsupported_trace_nodes_not_empty")
    if trace.get("rewards") != {}:
        problems.append("unsupported_trace_rewards_not_empty")
    if trace.get("metrics") != {}:
        problems.append("unsupported_trace_metrics_not_empty")

    errors = trace.get("errors")
    expected_message = (
        f"taskset setup: UnsupportedTaskError: {expected_name}: "
        "requests GPU resources, but the current VMVM tenant is CPU-only"
    )
    if not isinstance(errors, list) or len(errors) != 1 or not isinstance(errors[0], dict):
        problems.append("unsupported_trace_error_shape_invalid")
        return problems
    error = errors[0]
    if set(error) != {"type", "message", "traceback"}:
        problems.append("unsupported_trace_error_shape_invalid")
    if error.get("type") != "TasksetError":
        problems.append("unsupported_trace_error_type_invalid")
    if error.get("message") != expected_message:
        problems.append("unsupported_trace_error_message_invalid")
    traceback = error.get("traceback")
    if not isinstance(traceback, str) or expected_message not in traceback:
        problems.append("unsupported_trace_traceback_invalid")
    return problems


def _score_problem(trace: dict) -> tuple[float | None, str | None]:
    rewards = trace.get("rewards")
    if not isinstance(rewards, dict) or set(rewards) != {"solved"}:
        return None, "rewards_solved_missing_or_extra"
    score = rewards["solved"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or score not in {0, 1}
    ):
        return None, "rewards_solved_not_binary"
    return float(score), None


def audit_results(
    results: Path,
    *,
    dataset_dir: Path,
    task_file: Path | None = None,
    min_supported_pass_rate: float | None = None,
    max_supported_pass_rate: float | None = None,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
) -> tuple[dict, bool]:
    expected = _expected_slugs(dataset_dir, task_file)
    supported = expected - EXPECTED_UNSUPPORTED_TASKS
    rows = list(_iter_traces(results))
    per_task = Counter(_task_slug(row) for row in rows)
    trace_ids = [row.get("id") for row in rows]
    global_problems: list[str] = []
    failure_examples: list[dict] = []

    if len(rows) != EXPECTED_TASK_COUNT:
        global_problems.append(f"trace_count={len(rows)} expected={EXPECTED_TASK_COUNT}")
    invalid_ids = sum(not isinstance(trace_id, str) or not trace_id for trace_id in trace_ids)
    if invalid_ids:
        global_problems.append(f"invalid_trace_ids={invalid_ids}")
    valid_ids = [trace_id for trace_id in trace_ids if isinstance(trace_id, str) and trace_id]
    if len(valid_ids) != len(set(valid_ids)):
        global_problems.append("duplicate_trace_ids")
    if missing := sorted(expected - set(per_task)):
        global_problems.append(f"missing_tasks={missing[:20]!r} count={len(missing)}")
    if extra := sorted(set(per_task) - expected):
        global_problems.append(f"unexpected_tasks={extra[:20]!r} count={len(extra)}")
    if wrong := {slug: per_task.get(slug, 0) for slug in expected if per_task.get(slug, 0) != 1}:
        global_problems.append(f"wrong_rollout_multiplicity={dict(sorted(wrong.items()))!r}")

    supported_scores: list[float] = []
    unsupported_seen: set[str] = set()
    supported_failures = 0
    unsupported_failures = 0
    for row in rows:
        slug = _task_slug(row)
        problems: list[str]
        if slug in EXPECTED_UNSUPPORTED_TASKS:
            unsupported_seen.add(slug)
            problems = _unsupported_trace_problems(row, slug)
            if problems:
                unsupported_failures += 1
        else:
            problems = _audit_trace(
                row,
                require_reasoning=True,
                max_sequence_tokens=max_sequence_tokens,
                require_token_data=False,
                require_logprobs=False,
                require_model_io=True,
            )
            if row.get("is_completed") is not True:
                problems.append("supported_trace_not_completed")
            stop_condition = row.get("stop_condition")
            if not isinstance(stop_condition, str) or not stop_condition.strip() or stop_condition == "error":
                problems.append("supported_trace_stop_condition_invalid")
            score, score_problem = _score_problem(row)
            if score_problem is not None:
                problems.append(score_problem)
            elif slug in supported:
                supported_scores.append(score)
            if problems:
                supported_failures += 1
        if problems and len(failure_examples) < 50:
            failure_examples.append({"id": row.get("id"), "task": slug, "problems": problems})

    supported_passes = int(sum(supported_scores))
    supported_pass_rate = supported_passes / len(supported) if supported else 0.0
    all_task_pass_rate = supported_passes / EXPECTED_TASK_COUNT
    if len(supported_scores) != len(supported):
        global_problems.append(f"scored_supported_tasks={len(supported_scores)} expected={len(supported)}")
    if unsupported_seen != EXPECTED_UNSUPPORTED_TASKS:
        missing = sorted(EXPECTED_UNSUPPORTED_TASKS - unsupported_seen)
        global_problems.append(f"missing_expected_unsupported_tasks={missing!r}")
    if min_supported_pass_rate is not None and supported_pass_rate < min_supported_pass_rate:
        global_problems.append(
            f"supported_pass_rate={supported_pass_rate:.12g} below_min={min_supported_pass_rate:.12g}"
        )
    if max_supported_pass_rate is not None and supported_pass_rate > max_supported_pass_rate:
        global_problems.append(
            f"supported_pass_rate={supported_pass_rate:.12g} above_max={max_supported_pass_rate:.12g}"
        )

    summary = {
        "schema_version": 1,
        "ok": not (global_problems or failure_examples),
        "expected_tasks": EXPECTED_TASK_COUNT,
        "observed_traces": len(rows),
        "supported_tasks": len(supported),
        "expected_unsupported_tasks": sorted(EXPECTED_UNSUPPORTED_TASKS),
        "observed_unsupported_tasks": sorted(unsupported_seen),
        "trace_failures": supported_failures + unsupported_failures,
        "supported_trace_failures": supported_failures,
        "unsupported_trace_failures": unsupported_failures,
        "supported_passes": supported_passes,
        "supported_pass_rate": supported_pass_rate,
        "all_task_pass_rate": all_task_pass_rate,
        "score_bounds": {
            "min_supported_pass_rate": min_supported_pass_rate,
            "max_supported_pass_rate": max_supported_pass_rate,
        },
        "global_problems": global_problems,
        "failure_examples": failure_examples,
    }
    return summary, not summary["ok"]


def _rate(value: str) -> float:
    rate = float(value)
    if not math.isfinite(rate) or not 0 <= rate <= 1:
        raise argparse.ArgumentTypeError("must be a finite number between 0 and 1")
    return rate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument(
        "--dataset-dir",
        required=True,
        type=Path,
        help="pinned TB4 tasks directory used to establish the expected slug set",
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        help="optional exact 66-slug subset within --dataset-dir",
    )
    parser.add_argument(
        "--min-supported-pass-rate",
        type=_rate,
        help="optional inclusive lower bound for rewards.solved across the 63 CPU-supported tasks",
    )
    parser.add_argument(
        "--max-supported-pass-rate",
        type=_rate,
        help="optional inclusive upper bound for rewards.solved across the 63 CPU-supported tasks",
    )
    parser.add_argument(
        "--max-sequence-tokens",
        type=int,
        default=DEFAULT_MAX_SEQUENCE_TOKENS,
    )
    args = parser.parse_args()
    if args.max_sequence_tokens < 1:
        parser.error("--max-sequence-tokens must be positive")
    if (
        args.min_supported_pass_rate is not None
        and args.max_supported_pass_rate is not None
        and args.min_supported_pass_rate > args.max_supported_pass_rate
    ):
        parser.error("--min-supported-pass-rate cannot exceed --max-supported-pass-rate")
    try:
        summary, failed = audit_results(
            args.results,
            dataset_dir=args.dataset_dir,
            task_file=args.task_file,
            min_supported_pass_rate=args.min_supported_pass_rate,
            max_supported_pass_rate=args.max_supported_pass_rate,
            max_sequence_tokens=args.max_sequence_tokens,
        )
    except (OSError, TraceJSONLError, TB4AuditError) as error:
        parser.error(str(error))
    print(json.dumps(summary, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
