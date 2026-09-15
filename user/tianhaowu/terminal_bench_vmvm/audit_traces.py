#!/usr/bin/env python3
"""Fail closed when rollout traces are unsuitable as token-level training data."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def _task_slug(trace: dict) -> str:
    task = trace.get("task") or {}
    return task.get("slug") or str(task.get("name", "")).rsplit("/", 1)[-1]


def _audit_trace(trace: dict, require_reasoning: bool) -> list[str]:
    problems: list[str] = []
    if trace.get("errors"):
        problems.append("trace_has_errors")
    nodes = trace.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return [*problems, "no_message_nodes"]

    sampled = [node for node in nodes if node.get("sampled")]
    if not sampled:
        problems.append("no_sampled_assistant_nodes")
    reasoning_seen = False
    sampled_tokens = 0
    for index, node in enumerate(nodes):
        token_ids = node.get("token_ids")
        mask = node.get("mask")
        logprobs = node.get("logprobs")
        if not isinstance(token_ids, list) or not isinstance(mask, list) or not isinstance(logprobs, list):
            problems.append(f"node_{index}_missing_token_arrays")
            continue
        if len(token_ids) != len(mask):
            problems.append(f"node_{index}_token_mask_mismatch")
        expected_logprobs = sum(value is True for value in mask)
        if len(logprobs) != expected_logprobs:
            problems.append(f"node_{index}_logprob_mismatch")
        if node.get("sampled"):
            sampled_tokens += expected_logprobs
            message = node.get("message") or {}
            if isinstance(message.get("reasoning_content"), str) and message["reasoning_content"].strip():
                reasoning_seen = True
    if sampled_tokens == 0:
        problems.append("no_sampled_tokens")
    if require_reasoning and not reasoning_seen:
        problems.append("reasoning_content_not_retained")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected-task-file", type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--rollouts-per-task", type=int, default=1)
    parser.add_argument("--require-reasoning", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    traces = [json.loads(line) for line in args.results.read_text().splitlines() if line.strip()]
    expected_slugs = None
    if args.expected_task_file:
        expected_slugs = {
            line.strip().split("\t", 1)[0]
            for line in args.expected_task_file.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    expected_count = args.expected_count
    if expected_count is None and expected_slugs is not None:
        expected_count = len(expected_slugs) * args.rollouts_per_task

    ids = [trace.get("id") for trace in traces]
    slugs = [_task_slug(trace) for trace in traces]
    per_task = Counter(slugs)
    failures = []
    for trace in traces:
        problems = _audit_trace(trace, args.require_reasoning)
        if problems:
            failures.append({"id": trace.get("id"), "task": _task_slug(trace), "problems": problems})

    global_problems = []
    if expected_count is not None and len(traces) != expected_count:
        global_problems.append(f"trace_count={len(traces)} expected={expected_count}")
    if len(set(ids)) != len(ids):
        global_problems.append("duplicate_trace_ids")
    if expected_slugs is not None:
        observed = set(slugs)
        if missing := sorted(expected_slugs - observed):
            global_problems.append(f"missing_tasks={missing[:20]!r} count={len(missing)}")
        if extra := sorted(observed - expected_slugs):
            global_problems.append(f"unexpected_tasks={extra[:20]!r} count={len(extra)}")
        wrong_multiplicity = {
            slug: per_task.get(slug, 0) for slug in expected_slugs if per_task.get(slug, 0) != args.rollouts_per_task
        }
        if wrong_multiplicity:
            global_problems.append(
                f"wrong_rollout_multiplicity={dict(list(sorted(wrong_multiplicity.items()))[:20])!r}"
            )

    summary = {
        "traces": len(traces),
        "tasks": len(per_task),
        "sampled_tokens": sum(
            sum(sum(value is True for value in node.get("mask", [])) for node in trace.get("nodes", []))
            for trace in traces
        ),
        "trace_failures": len(failures),
        "global_problems": global_problems,
        "failure_examples": failures[:50],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if failures or global_problems:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
