#!/usr/bin/env python3

import argparse
import collections
import json
import tomllib
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit SWE-rebench Harbor task conversion and verifier metadata.")
    parser.add_argument("results", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--expected-rollouts", type=int)
    parser.add_argument("--require-verifier-metadata", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def base_image(task_dir: Path) -> str:
    dockerfile = task_dir / "environment" / "Dockerfile"
    return next(
        line.split(None, 1)[1].strip()
        for line in dockerfile.read_text().splitlines()
        if line.strip().upper().startswith("FROM ")
    )


def source_tasks(config: dict[str, Any]) -> list[dict[str, object]]:
    taskset = config["taskset"]
    dataset_dir = Path(taskset["dataset_dir"])
    selected = taskset.get("tasks")
    task_dirs = [
        path.parent
        for path in sorted(dataset_dir.rglob("task.toml"))
        if (path.parent / "instruction.md").is_file() and (selected is None or path.parent.name in selected)
    ]
    tasks = []
    for idx, task_dir in enumerate(task_dirs):
        task_config = tomllib.loads((task_dir / "task.toml").read_text())
        instance = json.loads((task_dir / "tests" / "config.json").read_text())
        tasks.append(
            {
                "idx": idx,
                "name": task_config["task"]["name"],
                "prompt": (task_dir / "instruction.md").read_text().strip(),
                "image": base_image(task_dir),
                "workdir": f"/{instance['repo'].split('/', 1)[1]}",
            }
        )
    return tasks


def main() -> None:
    args = parse_args()
    config_path = args.config or args.results.parent / "config.toml"
    config = tomllib.loads(config_path.read_text())
    expected = source_tasks(config)
    expected_rollouts = args.expected_rollouts or config["num_rollouts"]
    issues: list[dict[str, object]] = []
    counts: collections.Counter[int] = collections.Counter()
    stops: collections.Counter[str] = collections.Counter()
    trace_ids: set[str] = set()
    rows = 0
    solved = 0
    verifier_metadata_rows = 0
    missing_verifier_metadata = 0

    if config["taskset"].get("id") != "swe-rebench-harbor":
        issues.append({"issue": "config does not use the swe-rebench-harbor taskset"})
    if config.get("num_tasks") != len(expected):
        issues.append(
            {
                "issue": "configured task count differs from Harbor source",
                "configured": config.get("num_tasks"),
                "source": len(expected),
            }
        )

    with args.results.open() as results:
        for line_number, line in enumerate(results, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            task = row.get("task") or {}
            task_idx = task.get("idx")
            task_ref = {"row": line_number, "idx": task_idx, "name": task.get("name")}
            if not isinstance(task_idx, int) or isinstance(task_idx, bool) or not 0 <= task_idx < len(expected):
                issues.append({**task_ref, "issue": "task index is outside the Harbor source"})
                continue
            counts[task_idx] += 1
            expected_task = expected[task_idx]
            for field in ("name", "prompt", "image", "workdir"):
                if task.get(field) != expected_task[field]:
                    issues.append({**task_ref, "issue": f"task {field} differs from the Harbor source"})

            trace_id = row.get("id")
            if not isinstance(trace_id, str) or not trace_id:
                issues.append({**task_ref, "issue": "missing trace ID"})
            elif trace_id in trace_ids:
                issues.append({**task_ref, "issue": "duplicate trace ID"})
            else:
                trace_ids.add(trace_id)
            if row.get("errors"):
                issues.append({**task_ref, "issue": "row contains serialized errors"})
            if row.get("is_completed") is not True:
                issues.append({**task_ref, "issue": "row is not complete"})
            stops[str(row.get("stop_condition") or "missing")] += 1

            reward = (row.get("rewards") or {}).get("solved")
            if reward not in (0, 0.0, 1, 1.0):
                issues.append({**task_ref, "issue": f"invalid solved reward {reward!r}"})
                continue
            solved += int(float(reward) > 0)
            verifier = (row.get("info") or {}).get("swe_rebench_verifier")
            if not isinstance(verifier, dict):
                missing_verifier_metadata += 1
                if args.require_verifier_metadata:
                    issues.append({**task_ref, "issue": "missing SWE-rebench verifier metadata"})
                continue
            verifier_metadata_rows += 1
            if not isinstance(verifier.get("exit_code"), int):
                issues.append({**task_ref, "issue": "invalid verifier exit code"})
            if verifier.get("reward") != float(reward):
                issues.append({**task_ref, "issue": "verifier metadata disagrees with persisted reward"})

    for task in expected:
        count = counts[task["idx"]]
        if count != expected_rollouts:
            issues.append(
                {
                    "idx": task["idx"],
                    "name": task["name"],
                    "issue": f"expected {expected_rollouts} rollouts, found {count}",
                }
            )

    expected_rows = len(expected) * expected_rollouts
    report = {
        "results": str(args.results.resolve()),
        "config": str(config_path.resolve()),
        "source_tasks": len(expected),
        "expected_rollouts": expected_rollouts,
        "expected_rows": expected_rows,
        "rows": rows,
        "solved_rollouts": solved,
        "resolved_rate": solved / expected_rows if expected_rows else 0.0,
        "verifier_metadata_rows": verifier_metadata_rows,
        "missing_verifier_metadata": missing_verifier_metadata,
        "stop_conditions": dict(sorted(stops.items())),
        "issues": issues,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
