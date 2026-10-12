from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

SCORED_STATUSES = {"completed", "model_error", "model_timeout"}
RETRYABLE_ATTEMPT_STATUSES = {"retryable_error", "vmvm_lost"}


def iter_results(paths: list[Path]) -> Iterator[tuple[Path, int, dict[str, Any]]]:
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"Expected an object at {path}:{line_number}")
                yield path, line_number, row


def _expected_keys(task_catalog: Path | None, num_trials: int) -> set[tuple[str, int]] | None:
    if task_catalog is None:
        return None
    catalog = json.loads(task_catalog.read_text())
    if not isinstance(catalog, list):
        raise ValueError(f"Expected a task list in {task_catalog}")
    task_ids = [str(task["task_id"]) for task in catalog]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError(f"Duplicate task IDs in {task_catalog}")
    return {(task_id, trial) for trial in range(num_trials) for task_id in task_ids}


def _audit_attempts(
    path: Path,
    result_statuses: dict[tuple[str, int], str],
) -> dict[str, Any]:
    chains: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    malformed_rows: list[str] = []
    for _, line_number, row in iter_results([path]):
        try:
            key = (str(row["task_id"]), int(row.get("trial", 0)))
            record = {
                "line": line_number,
                "attempt": int(row["attempt"]),
                "status": str(row["status"]),
            }
        except (KeyError, TypeError, ValueError) as error:
            malformed_rows.append(f"{path}:{line_number}: {error}")
            continue
        chains[key].append(record)

    missing_keys = sorted(set(result_statuses) - set(chains))
    unexpected_keys = sorted(set(chains) - set(result_statuses))
    invalid_sequences: list[dict[str, Any]] = []
    invalid_transitions: list[dict[str, Any]] = []
    for key, records in sorted(chains.items()):
        attempts = [record["attempt"] for record in records]
        expected_attempts = list(range(1, len(records) + 1))
        if attempts != expected_attempts:
            invalid_sequences.append(
                {
                    "key": key,
                    "attempts": attempts,
                    "expected": expected_attempts,
                }
            )

        for record in records[:-1]:
            if record["status"] not in RETRYABLE_ATTEMPT_STATUSES:
                invalid_transitions.append(
                    {
                        "key": key,
                        "line": record["line"],
                        "attempt": record["attempt"],
                        "status": record["status"],
                        "expected": sorted(RETRYABLE_ATTEMPT_STATUSES),
                    }
                )

        expected_terminal = result_statuses.get(key)
        if expected_terminal is not None and records[-1]["status"] != expected_terminal:
            invalid_transitions.append(
                {
                    "key": key,
                    "line": records[-1]["line"],
                    "attempt": records[-1]["attempt"],
                    "status": records[-1]["status"],
                    "expected": expected_terminal,
                }
            )

    return {
        "path": str(path.resolve()),
        "rows": sum(len(records) for records in chains.values()),
        "keys": len(chains),
        "missing_keys": missing_keys,
        "unexpected_keys": unexpected_keys,
        "malformed_rows": malformed_rows,
        "invalid_sequences": invalid_sequences,
        "invalid_transitions": invalid_transitions,
        "exact": not any(
            [
                missing_keys,
                unexpected_keys,
                malformed_rows,
                invalid_sequences,
                invalid_transitions,
            ]
        ),
    }


def audit(
    paths: list[Path],
    expected_total: int,
    expected_passes: int | None,
    num_trials: int,
    task_catalog: Path | None,
    expected_any_passes: int | None,
    expected_all_passes: int | None,
    allow_mixed_fingerprints: bool,
    attempts_path: Path | None,
) -> dict[str, Any]:
    if num_trials < 1:
        raise ValueError("num_trials must be positive")
    if expected_total % num_trials:
        raise ValueError("expected_total must be divisible by num_trials")
    expected_tasks = expected_total // num_trials
    key_counts: Counter[tuple[str, int]] = Counter()
    status_counts: Counter[str] = Counter()
    reward_counts: Counter[str] = Counter()
    fingerprints: set[str] = set()
    missing_fingerprint_keys: list[tuple[str, int]] = []
    result_statuses: dict[tuple[str, int], str] = {}
    pass_sets = [set[str]() for _ in range(num_trials)]
    trial_counts = [0] * num_trials
    trial_passes = [0] * num_trials
    missing_historical_tools: dict[str, list[str]] = {}
    termination_counts: Counter[str] = Counter()
    rows = 0
    passes = 0
    fails = 0
    turns = 0
    tool_calls = 0
    context_resets = 0

    for path, line_number, row in iter_results(paths):
        rows += 1
        task_id = str(row["task_id"])
        trial = int(row.get("trial", 0))
        if trial not in range(num_trials):
            raise ValueError(f"Trial {trial} at {path}:{line_number} is outside [0, {num_trials})")
        key_counts[(task_id, trial)] += 1
        trial_counts[trial] += 1

        status = str(row.get("status"))
        result_statuses[(task_id, trial)] = status
        status_counts[status] += 1
        reward = row.get("reward")
        reward_counts[repr(reward)] += 1
        if reward == 1:
            passes += 1
            trial_passes[trial] += 1
            pass_sets[trial].add(task_id)
        elif reward == 0:
            fails += 1

        if fingerprint := row.get("config_fingerprint"):
            fingerprints.add(str(fingerprint))
        else:
            missing_fingerprint_keys.append((task_id, trial))
        termination_counts[str(row.get("termination_reason"))] += 1
        trajectory = row.get("trajectory") or []
        turns += len(trajectory)
        tool_calls += sum(len(turn.get("tool_results") or []) for turn in trajectory if isinstance(turn, dict))
        context_resets += len(row.get("context", {}).get("resets") or [])
        missing = row.get("service", {}).get("task_drift", {}).get("missing_historical_tools")
        if missing:
            missing_historical_tools[f"{trial}:{task_id}"] = missing

    observed_keys = set(key_counts)
    expected_keys = _expected_keys(task_catalog, num_trials)
    duplicates = sorted(key for key, count in key_counts.items() if count > 1)
    missing_keys = sorted(expected_keys - observed_keys) if expected_keys is not None else []
    unexpected_keys = sorted(observed_keys - expected_keys) if expected_keys is not None else []
    invalid_statuses = sorted(status for status in status_counts if status not in SCORED_STATUSES)
    invalid_rewards = sorted(reward for reward in reward_counts if reward not in {"0", "1"})
    mixed_fingerprints = len(fingerprints) > 1
    any_passes = len(set.union(*pass_sets)) if pass_sets else 0
    all_passes = len(set.intersection(*pass_sets)) if pass_sets else 0
    pass_rates = [100 * count / expected_tasks for count in trial_passes]

    report: dict[str, Any] = {
        "paths": [str(path.resolve()) for path in paths],
        "rows": rows,
        "unique_trials": len(observed_keys),
        "passes": passes,
        "fails": fails,
        "coverage_percent": 100 * rows / expected_total if expected_total else 0.0,
        "observed_pass_at_1": passes / rows if rows else 0.0,
        "observed_pass_at_1_percent": 100 * passes / rows if rows else 0.0,
        "pass_at_1": passes / expected_total if expected_total else 0.0,
        "pass_at_1_percent": 100 * passes / expected_total if expected_total else 0.0,
        "trial_counts": trial_counts,
        "trial_passes": trial_passes,
        "expected_total": expected_total,
        "expected_passes": expected_passes,
        "duplicates": duplicates,
        "missing_keys": missing_keys,
        "unexpected_keys": unexpected_keys,
        "status_counts": dict(sorted(status_counts.items())),
        "termination_counts": dict(sorted(termination_counts.items())),
        "reward_counts": dict(sorted(reward_counts.items())),
        "average_turns": turns / rows if rows else 0.0,
        "average_tool_calls": tool_calls / rows if rows else 0.0,
        "context_resets": context_resets,
        "invalid_statuses": invalid_statuses,
        "invalid_rewards": invalid_rewards,
        "config_fingerprints": sorted(fingerprints),
        "missing_fingerprint_keys": missing_fingerprint_keys,
        "mixed_fingerprints": mixed_fingerprints,
        "missing_historical_tools": missing_historical_tools,
    }
    if num_trials > 1:
        pass_at_k = 100 * any_passes / expected_tasks
        pass_pow_k = 100 * all_passes / expected_tasks
        report["any_passes"] = any_passes
        report["all_passes"] = all_passes
        report["metrics"] = {
            "pass_at_1_percent": 100 * passes / expected_total,
            "pass_at_1_std_percent": statistics.pstdev(pass_rates),
            f"pass_at_{num_trials}_percent": pass_at_k,
            f"pass_pow_{num_trials}_percent": pass_pow_k,
        }

    expected_metrics_match = (
        (expected_passes is None or passes == expected_passes)
        and (expected_any_passes is None or any_passes == expected_any_passes)
        and (expected_all_passes is None or all_passes == expected_all_passes)
    )
    attempt_audit = _audit_attempts(attempts_path, result_statuses) if attempts_path is not None else None
    report["attempt_audit"] = attempt_audit
    report["exact"] = (
        rows == expected_total
        and len(observed_keys) == expected_total
        and expected_metrics_match
        and not duplicates
        and not missing_keys
        and not unexpected_keys
        and not invalid_statuses
        and not invalid_rewards
        and not missing_fingerprint_keys
        and not missing_historical_tools
        and (allow_mixed_fingerprints or len(fingerprints) == 1)
        and (attempt_audit is None or attempt_audit["exact"])
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path, nargs="+")
    parser.add_argument("--expected-total", type=int, default=108)
    parser.add_argument("--expected-passes", type=int)
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--task-catalog", type=Path)
    parser.add_argument("--expected-any-passes", type=int)
    parser.add_argument("--expected-all-passes", type=int)
    parser.add_argument("--attempts", type=Path)
    parser.add_argument("--allow-mixed-fingerprints", action="store_true")
    args = parser.parse_args()
    report = audit(
        args.results,
        args.expected_total,
        args.expected_passes,
        args.num_trials,
        args.task_catalog,
        args.expected_any_passes,
        args.expected_all_passes,
        args.allow_mixed_fingerprints,
        args.attempts,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["exact"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
