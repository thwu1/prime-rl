#!/usr/bin/env python3
"""Fail closed when rollout traces are unsuitable as token-level training data."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

DEFAULT_MAX_SEQUENCE_TOKENS = 262_144


class TraceJSONLError(ValueError):
    """A results JSONL record could not be decoded as a trace object."""


def _task_slug(trace: dict) -> str:
    task = trace.get("task") or {}
    if not isinstance(task, dict):
        return ""
    return task.get("slug") or str(task.get("name", "")).rsplit("/", 1)[-1]


def _max_branch_tokens(nodes: list) -> tuple[int, list[int], bool]:
    """Return the longest root-to-node token path and graph integrity failures."""
    token_counts = [
        len(node.get("token_ids", []))
        if isinstance(node, dict) and isinstance(node.get("token_ids"), list)
        else 0
        for node in nodes
    ]
    path_lengths: list[int | None] = [None] * len(nodes)
    resolved = [False] * len(nodes)
    invalid_parents: set[int] = set()
    parent_cycle = False

    for start in range(len(nodes)):
        if resolved[start]:
            continue
        trail: list[int] = []
        trail_members: set[int] = set()
        current = start
        prefix_length: int | None
        while True:
            if resolved[current]:
                prefix_length = path_lengths[current]
                break
            if current in trail_members:
                parent_cycle = True
                prefix_length = None
                break
            trail.append(current)
            trail_members.add(current)

            node = nodes[current]
            parent = node.get("parent") if isinstance(node, dict) else None
            if parent is None:
                prefix_length = 0
                break
            if (
                isinstance(parent, bool)
                or not isinstance(parent, int)
                or not 0 <= parent < len(nodes)
            ):
                invalid_parents.add(current)
                prefix_length = None
                break
            current = parent

        for index in reversed(trail):
            if prefix_length is not None:
                prefix_length += token_counts[index]
            path_lengths[index] = prefix_length
            resolved[index] = True

    return max((length or 0 for length in path_lengths), default=0), sorted(invalid_parents), parent_cycle


def _audit_trace(
    trace: dict,
    require_reasoning: bool,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
) -> list[str]:
    problems: list[str] = []
    if trace.get("errors"):
        problems.append("trace_has_errors")
    nodes = trace.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return [*problems, "no_message_nodes"]

    sampled_node_count = 0
    sampled_tokens = 0
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            problems.append(f"node_{index}_not_an_object")
            continue

        is_sampled = node.get("sampled") is True
        if is_sampled:
            sampled_node_count += 1
        token_ids = node.get("token_ids")
        mask = node.get("mask")
        logprobs = node.get("logprobs")
        if not isinstance(token_ids, list) or not isinstance(mask, list) or not isinstance(logprobs, list):
            problems.append(f"node_{index}_missing_token_arrays")
            if is_sampled:
                if not token_ids:
                    problems.append(f"node_{index}_sampled_token_ids_empty")
                if not mask:
                    problems.append(f"node_{index}_sampled_mask_empty")
                if not logprobs:
                    problems.append(f"node_{index}_sampled_logprobs_empty")
                if require_reasoning:
                    message = node.get("message")
                    reasoning = message.get("reasoning_content") if isinstance(message, dict) else None
                    if not isinstance(reasoning, str) or not reasoning.strip():
                        problems.append(f"node_{index}_reasoning_content_not_retained")
            continue
        if any(isinstance(value, bool) or not isinstance(value, int) for value in token_ids):
            problems.append(f"node_{index}_token_ids_not_ints")
        if any(not isinstance(value, bool) for value in mask):
            problems.append(f"node_{index}_mask_not_bools")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            for value in logprobs
        ):
            problems.append(f"node_{index}_logprobs_not_finite_numbers")
        if len(token_ids) != len(mask):
            problems.append(f"node_{index}_token_mask_mismatch")
        expected_logprobs = sum(value is True for value in mask)
        if len(logprobs) != expected_logprobs:
            problems.append(f"node_{index}_logprob_mismatch")
        if is_sampled:
            if not token_ids:
                problems.append(f"node_{index}_sampled_token_ids_empty")
            if not mask:
                problems.append(f"node_{index}_sampled_mask_empty")
            if not logprobs:
                problems.append(f"node_{index}_sampled_logprobs_empty")
            sampled_tokens += expected_logprobs
            if require_reasoning:
                message = node.get("message")
                reasoning = message.get("reasoning_content") if isinstance(message, dict) else None
                if not isinstance(reasoning, str) or not reasoning.strip():
                    problems.append(f"node_{index}_reasoning_content_not_retained")
    if sampled_node_count == 0:
        problems.append("no_sampled_assistant_nodes")
    if sampled_tokens == 0:
        problems.append("no_sampled_tokens")

    max_branch_tokens, invalid_parents, parent_cycle = _max_branch_tokens(nodes)
    problems.extend(f"node_{index}_invalid_parent" for index in invalid_parents)
    if parent_cycle:
        problems.append("parent_cycle")
    if max_branch_tokens > max_sequence_tokens:
        problems.append(
            f"max_sequence_tokens={max_branch_tokens} limit={max_sequence_tokens}"
        )
    return problems


def _iter_traces(results: Path) -> Iterator[dict]:
    """Yield non-empty JSONL records without retaining the input file."""
    with results.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    trace = json.loads(line)
                except json.JSONDecodeError as error:
                    raise TraceJSONLError(
                        f"{results}: invalid JSON on line {line_number}: {error.msg}"
                    ) from None
                if not isinstance(trace, dict):
                    raise TraceJSONLError(
                        f"{results}: invalid trace on line {line_number}: expected a JSON object"
                    )
                yield trace


def _read_expected_slugs(task_file: Path) -> set[str]:
    with task_file.open(encoding="utf-8") as handle:
        return {
            line.strip().split("\t", 1)[0]
            for line in handle
            if line.strip() and not line.lstrip().startswith("#")
        }


def _summarize_traces(
    traces: Iterable[dict],
    *,
    expected_slugs: set[str] | None,
    expected_count: int | None,
    rollouts_per_task: int,
    require_reasoning: bool,
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS,
) -> tuple[dict, bool]:
    trace_count = 0
    sampled_tokens = 0
    trace_failure_count = 0
    failure_examples: list[dict] = []
    seen_ids: set[object] = set()
    duplicate_trace_ids = False
    per_task: Counter[str] = Counter()

    for trace in traces:
        trace_count += 1
        trace_id = trace.get("id")
        if trace_id in seen_ids:
            duplicate_trace_ids = True
        else:
            seen_ids.add(trace_id)

        slug = _task_slug(trace)
        per_task[slug] += 1
        problems = _audit_trace(trace, require_reasoning, max_sequence_tokens)
        if problems:
            trace_failure_count += 1
            if len(failure_examples) < 50:
                failure_examples.append({"id": trace_id, "task": slug, "problems": problems})

        nodes = trace.get("nodes")
        if isinstance(nodes, list):
            sampled_tokens += sum(
                sum(value is True for value in mask)
                for node in nodes
                if isinstance(node, dict) and isinstance((mask := node.get("mask")), list)
            )

    global_problems = []
    if expected_count is not None and trace_count != expected_count:
        global_problems.append(f"trace_count={trace_count} expected={expected_count}")
    if duplicate_trace_ids:
        global_problems.append("duplicate_trace_ids")
    if expected_slugs is not None:
        observed = set(per_task)
        if missing := sorted(expected_slugs - observed):
            global_problems.append(f"missing_tasks={missing[:20]!r} count={len(missing)}")
        if extra := sorted(observed - expected_slugs):
            global_problems.append(f"unexpected_tasks={extra[:20]!r} count={len(extra)}")
        wrong_multiplicity = {
            slug: per_task.get(slug, 0)
            for slug in expected_slugs
            if per_task.get(slug, 0) != rollouts_per_task
        }
        if wrong_multiplicity:
            global_problems.append(
                f"wrong_rollout_multiplicity={dict(list(sorted(wrong_multiplicity.items()))[:20])!r}"
            )

    summary = {
        "traces": trace_count,
        "tasks": len(per_task),
        "sampled_tokens": sampled_tokens,
        "trace_failures": trace_failure_count,
        "global_problems": global_problems,
        "failure_examples": failure_examples,
    }
    return summary, bool(trace_failure_count or global_problems)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected-task-file", type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--rollouts-per-task", type=int, default=1)
    parser.add_argument("--require-reasoning", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--max-sequence-tokens",
        type=int,
        default=DEFAULT_MAX_SEQUENCE_TOKENS,
        help="fail traces with any reconstructed branch longer than this (default: %(default)s)",
    )
    args = parser.parse_args()

    if args.max_sequence_tokens < 1:
        parser.error("--max-sequence-tokens must be positive")

    expected_slugs = None
    if args.expected_task_file:
        expected_slugs = _read_expected_slugs(args.expected_task_file)
    expected_count = args.expected_count
    if expected_count is None and expected_slugs is not None:
        expected_count = len(expected_slugs) * args.rollouts_per_task

    try:
        summary, failed = _summarize_traces(
            _iter_traces(args.results),
            expected_slugs=expected_slugs,
            expected_count=expected_count,
            rollouts_per_task=args.rollouts_per_task,
            require_reasoning=args.require_reasoning,
            max_sequence_tokens=args.max_sequence_tokens,
        )
    except TraceJSONLError as error:
        parser.error(str(error))
    print(json.dumps(summary, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
