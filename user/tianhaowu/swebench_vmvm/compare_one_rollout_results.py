#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two one-rollout benchmark result files on common tasks.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--expected-common-tasks", type=int)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def load_results(path: Path) -> dict[int, tuple[str, int]]:
    results = {}
    with path.open() as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            task = row["task"]
            idx = int(task["idx"])
            name = str(task["name"])
            rewards = row.get("rewards") or {}
            reward = rewards.get("solved")
            if reward not in (0, 0.0, 1, 1.0):
                raise ValueError(f"{path}: task {idx} has invalid reward {reward!r}")
            if row.get("is_completed") is not True or row.get("errors"):
                raise ValueError(f"{path}: task {idx} is not a clean completed row")
            if idx in results:
                raise ValueError(f"{path}: duplicate task index {idx}")
            results[idx] = (name, int(reward))
    return results


def exact_mcnemar_p_value(wins: int, losses: int) -> float:
    discordant = wins + losses
    if discordant == 0:
        return 1.0
    tail = sum(math.comb(discordant, value) for value in range(min(wins, losses) + 1))
    return min(1.0, 2 * tail / 2**discordant)


def main() -> None:
    args = parse_args()
    baseline = load_results(args.baseline)
    candidate = load_results(args.candidate)
    common = sorted(set(baseline) & set(candidate))

    mismatched_names = []
    wins = 0
    losses = 0
    baseline_solved = 0
    candidate_solved = 0
    for idx in common:
        baseline_name, baseline_reward = baseline[idx]
        candidate_name, candidate_reward = candidate[idx]
        if baseline_name != candidate_name:
            mismatched_names.append(
                {
                    "idx": idx,
                    "baseline": baseline_name,
                    "candidate": candidate_name,
                }
            )
        baseline_solved += baseline_reward
        candidate_solved += candidate_reward
        wins += candidate_reward > baseline_reward
        losses += candidate_reward < baseline_reward

    common_count = len(common)
    report = {
        "baseline": str(args.baseline.resolve()),
        "candidate": str(args.candidate.resolve()),
        "baseline_rows": len(baseline),
        "candidate_rows": len(candidate),
        "common_tasks": common_count,
        "baseline_only_indices": sorted(set(baseline) - set(candidate)),
        "candidate_only_indices": sorted(set(candidate) - set(baseline)),
        "mismatched_names": mismatched_names,
        "baseline_solved_on_common": baseline_solved,
        "candidate_solved_on_common": candidate_solved,
        "baseline_rate_on_common": baseline_solved / common_count if common else 0.0,
        "candidate_rate_on_common": candidate_solved / common_count if common else 0.0,
        "candidate_delta": ((candidate_solved - baseline_solved) / common_count if common else 0.0),
        "candidate_wins": wins,
        "candidate_losses": losses,
        "ties": common_count - wins - losses,
        "exact_mcnemar_p_value": exact_mcnemar_p_value(wins, losses),
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.strict:
        problems = []
        if not common:
            problems.append("the result files have no common tasks")
        if args.expected_common_tasks is not None and common_count != args.expected_common_tasks:
            problems.append(f"expected {args.expected_common_tasks} common tasks, found {common_count}")
        if mismatched_names:
            problems.append(f"found {len(mismatched_names)} mismatched task names")
        if problems:
            raise SystemExit("; ".join(problems))


if __name__ == "__main__":
    main()
