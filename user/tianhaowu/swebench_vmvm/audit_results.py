#!/usr/bin/env python3

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

DIRTY_STOP_CONDITIONS = {"error"}


def parsed_reward(row: dict[str, object]) -> tuple[float, bool]:
    rewards = row.get("rewards")
    if not isinstance(rewards, dict) or "solved" not in rewards:
        return 0.0, False
    try:
        reward = float(rewards["solved"])
    except (TypeError, ValueError):
        return 0.0, False
    return reward, reward in (0.0, 1.0)


def is_dirty_row(row: dict[str, object]) -> bool:
    _, reward_is_valid = parsed_reward(row)
    stop = row.get("stop_condition")
    return (
        bool(row.get("errors"))
        or stop in DIRTY_STOP_CONDITIONS
        or not stop
        or not reward_is_valid
        or row.get("is_completed") is not True
    )


def has_mode_changes(row: dict[str, object]) -> bool:
    info = row.get("info")
    candidate = info.get("swebench_candidate_patch") if isinstance(info, dict) else None
    patch = candidate.get("patch") if isinstance(candidate, dict) else None
    return isinstance(patch, str) and re.search(r"^(?:old|new) mode ", patch, flags=re.MULTILINE) is not None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a Verifiers v1 results.jsonl file.")
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected-tasks", type=int, required=True)
    parser.add_argument("--rollouts-per-task", type=int, default=1)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit nonzero unless the result has the exact expected shape and no dirty rows.",
    )
    parser.add_argument(
        "--require-swebench-vmvm-provenance",
        action="store_true",
        help=("Require candidate-patch, fresh-verifier, and parsed SWE-bench report metadata on every row."),
    )
    parser.add_argument(
        "--reject-mode-changes",
        action="store_true",
        help="Reject candidate patches containing old/new mode entries.",
    )
    return parser.parse_args()


def swebench_vmvm_provenance_issues(
    row: dict[str, object],
    reward: float,
) -> list[str]:
    info = row.get("info")
    if not isinstance(info, dict):
        return ["info is not an object"]

    issues = []
    candidate = info.get("swebench_candidate_patch")
    if not isinstance(candidate, dict):
        issues.append("missing candidate patch metadata")
    else:
        patch = candidate.get("patch")
        if not isinstance(patch, str):
            issues.append("candidate patch is not a string")
        else:
            patch_bytes = patch.encode()
            if candidate.get("bytes") != len(patch_bytes):
                issues.append("candidate patch byte count does not match")
            digest = hashlib.sha256(patch_bytes).hexdigest()
            if candidate.get("sha256") != digest:
                issues.append("candidate patch SHA-256 does not match")

    verifier_runtime = info.get("swebench_verifier_runtime")
    if not isinstance(verifier_runtime, (str, dict)) or not verifier_runtime:
        issues.append("missing fresh verifier runtime descriptor")

    verifier_attempts = info.get("swebench_verifier_attempts", 1)
    verifier_failures = info.get("swebench_verifier_failures", [])
    if type(verifier_attempts) is not int or verifier_attempts < 1:
        issues.append("fresh verifier attempt count is invalid")
    if not isinstance(verifier_failures, list) or not all(isinstance(item, str) for item in verifier_failures):
        issues.append("fresh verifier failure history is invalid")
    elif type(verifier_attempts) is int and verifier_attempts != len(verifier_failures) + 1:
        issues.append("fresh verifier attempt count disagrees with failure history")

    verifier = info.get("swebench_verifier")
    if not isinstance(verifier, dict):
        issues.append("missing parsed verifier report")
        return issues
    if not isinstance(verifier.get("exit_code"), int):
        issues.append("verifier exit code is missing or invalid")
    if verifier.get("patch_successfully_applied") is not True:
        issues.append("candidate patch was not successfully applied")
    resolved = verifier.get("resolved")
    if not isinstance(resolved, bool):
        issues.append("verifier resolved field is missing or invalid")
    elif resolved != bool(reward):
        issues.append("verifier resolved field disagrees with reward")
    if not isinstance(verifier.get("tests_status"), dict):
        issues.append("verifier test status is missing or invalid")
    return issues


def main() -> None:
    args = parse_args()
    counts: collections.Counter[int] = collections.Counter()
    names_by_idx: dict[int, str] = {}
    indices_by_name: dict[str, int] = {}
    solved_by_idx: collections.Counter[int] = collections.Counter()
    stops: collections.Counter[str] = collections.Counter()
    dirty_tasks: list[dict[str, object]] = []
    invalid_rewards: list[dict[str, object]] = []
    incomplete_tasks: list[dict[str, object]] = []
    provenance_issues: list[dict[str, object]] = []
    verifier_runtime_tasks: dict[str, dict[str, object]] = {}
    duplicate_verifier_runtimes: list[dict[str, object]] = []
    trace_ids: dict[str, dict[str, object]] = {}
    invalid_trace_ids: list[dict[str, object]] = []
    duplicate_trace_ids: list[dict[str, object]] = []
    mode_change_tasks: list[dict[str, object]] = []
    verifier_attempt_counts: collections.Counter[int] = collections.Counter()
    rows = 0
    solved = 0.0

    with args.results.open() as results:
        for line in results:
            if not line.strip():
                continue
            row = json.loads(line)
            task = row["task"]
            idx = int(task["idx"])
            name = str(task["name"])
            previous_name = names_by_idx.setdefault(idx, name)
            if previous_name != name:
                raise ValueError(f"task index {idx} maps to both {previous_name!r} and {name!r}")
            previous_idx = indices_by_name.setdefault(name, idx)
            if previous_idx != idx:
                raise ValueError(f"task name {name!r} maps to both index {previous_idx} and {idx}")

            trace_id = row.get("id")
            current_trace = {"idx": idx, "name": name}
            if not isinstance(trace_id, str) or not trace_id.strip():
                invalid_trace_ids.append(current_trace)
            else:
                previous_trace = trace_ids.get(trace_id)
                if previous_trace is None:
                    trace_ids[trace_id] = current_trace
                else:
                    duplicate_trace_ids.append(
                        {
                            "id": trace_id,
                            "first_task": previous_trace,
                            "reused_by": current_trace,
                        }
                    )

            rewards = row.get("rewards") or {}
            reward, reward_is_valid = parsed_reward(row)
            stop = str(row.get("stop_condition") or "missing")
            is_completed = row.get("is_completed") is True
            is_dirty = is_dirty_row(row)
            counts[idx] += 1
            solved_by_idx[idx] += int(reward > 0)
            stops[stop] += 1
            rows += 1
            solved += reward
            if not reward_is_valid:
                invalid_rewards.append({"idx": idx, "name": name, "reward": rewards.get("solved")})
            if not is_completed:
                incomplete_tasks.append({"idx": idx, "name": name})
            if args.require_swebench_vmvm_provenance:
                issues = swebench_vmvm_provenance_issues(row, reward)
                if issues:
                    provenance_issues.append({"idx": idx, "name": name, "issues": issues})
                info = row.get("info")
                if isinstance(info, dict):
                    attempts = info.get("swebench_verifier_attempts", 1)
                    if type(attempts) is int and attempts >= 1:
                        verifier_attempt_counts[attempts] += 1
                    descriptor = info.get("swebench_verifier_runtime")
                    if isinstance(descriptor, (str, dict)) and descriptor:
                        descriptor_key = json.dumps(descriptor, sort_keys=True)
                        current_task = {"idx": idx, "name": name}
                        previous_task = verifier_runtime_tasks.setdefault(descriptor_key, current_task)
                        if previous_task != current_task:
                            duplicate_verifier_runtimes.append(
                                {
                                    "descriptor": descriptor,
                                    "first_task": previous_task,
                                    "reused_by": current_task,
                                }
                            )
            if args.reject_mode_changes:
                if has_mode_changes(row):
                    mode_change_tasks.append({"idx": idx, "name": name})
            if is_dirty:
                dirty_tasks.append(
                    {
                        "idx": idx,
                        "name": name,
                        "stop_condition": stop,
                        "errors": [error.get("type") for error in row.get("errors", [])],
                    }
                )

    expected_indices = set(range(args.expected_tasks))
    actual_indices = set(counts)
    missing_indices = sorted(expected_indices - actual_indices)
    unexpected_indices = sorted(actual_indices - expected_indices)
    underfull = {str(idx): count for idx, count in sorted(counts.items()) if count < args.rollouts_per_task}
    overfull = {str(idx): count for idx, count in sorted(counts.items()) if count > args.rollouts_per_task}
    complete_indices = {idx for idx, count in counts.items() if count == args.rollouts_per_task}
    passed_complete_tasks = sum(solved_by_idx[idx] > 0 for idx in complete_indices)
    expected_rows = args.expected_tasks * args.rollouts_per_task

    report = {
        "results": str(args.results.resolve()),
        "rows": rows,
        "expected_rows": expected_rows,
        "tasks_seen": len(actual_indices),
        "expected_tasks": args.expected_tasks,
        "rollouts_per_task": args.rollouts_per_task,
        "solved_rollouts": solved,
        "observed_resolved_rate": solved / rows if rows else 0.0,
        "resolved_rate": solved / expected_rows if expected_rows else 0.0,
        "complete_tasks": len(complete_indices),
        "tasks_with_any_solve": passed_complete_tasks,
        "empirical_pass_at_k_complete_tasks": (
            passed_complete_tasks / len(complete_indices) if complete_indices else 0.0
        ),
        "empirical_pass_at_k": (passed_complete_tasks / args.expected_tasks if args.expected_tasks else 0.0),
        "dirty_rows": len(dirty_tasks),
        "dirty_tasks": dirty_tasks,
        "invalid_rewards": invalid_rewards,
        "incomplete_tasks": incomplete_tasks,
        "provenance_issues": provenance_issues,
        "duplicate_verifier_runtimes": duplicate_verifier_runtimes,
        "verifier_attempt_counts": dict(sorted(verifier_attempt_counts.items())),
        "invalid_trace_ids": invalid_trace_ids,
        "duplicate_trace_ids": duplicate_trace_ids,
        "mode_change_rows": len(mode_change_tasks),
        "mode_change_tasks": mode_change_tasks,
        "stop_conditions": dict(sorted(stops.items())),
        "missing_indices": missing_indices,
        "unexpected_indices": unexpected_indices,
        "underfull": underfull,
        "overfull": overfull,
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.strict:
        problems = []
        if rows != expected_rows:
            problems.append(f"expected {expected_rows} rows, found {rows}")
        if missing_indices:
            problems.append(f"missing {len(missing_indices)} task indices")
        if unexpected_indices:
            problems.append(f"found {len(unexpected_indices)} unexpected task indices")
        if underfull:
            problems.append(f"found {len(underfull)} underfull tasks")
        if overfull:
            problems.append(f"found {len(overfull)} overfull tasks")
        if dirty_tasks:
            problems.append(f"found {len(dirty_tasks)} dirty rows")
        if invalid_trace_ids:
            problems.append(f"found {len(invalid_trace_ids)} invalid trace IDs")
        if duplicate_trace_ids:
            problems.append(f"found {len(duplicate_trace_ids)} duplicate trace IDs")
        if provenance_issues:
            problems.append(f"found {len(provenance_issues)} rows with invalid VMVM provenance")
        if duplicate_verifier_runtimes:
            problems.append(f"found {len(duplicate_verifier_runtimes)} reused verifier runtimes")
        if mode_change_tasks:
            problems.append(f"found {len(mode_change_tasks)} candidate patches with mode changes")
        if problems:
            raise SystemExit("; ".join(problems))


if __name__ == "__main__":
    main()
