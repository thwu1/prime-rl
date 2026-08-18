import argparse
import json
import tomllib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("tasks", type=Path)
    parser.add_argument("--expected-count", type=int)
    return parser.parse_args()


def task_names(tasks_dir: Path) -> set[str]:
    names = set()
    for config_path in tasks_dir.glob("*/task.toml"):
        config = tomllib.loads(config_path.read_text())
        names.add(config["task"]["name"])
    return names


def trial_results(result_path: Path, result: dict) -> list[dict]:
    if "trial_results" in result:
        return result["trial_results"]
    return [
        json.loads(path.read_text())
        for path in sorted(result_path.parent.glob("*/result.json"))
    ]


def main() -> None:
    args = parse_args()
    known_tasks = task_names(args.tasks)
    result = json.loads(args.result.read_text())
    trials = trial_results(args.result, result)
    actual = {trial["task_name"] for trial in trials}

    failures = []
    for trial in trials:
        exception = trial.get("exception_info")
        verifier = trial.get("verifier_result") or {}
        rewards = verifier.get("rewards") or {}
        if exception is not None or rewards.get("reward") != 1:
            failures.append(
                {
                    "task_name": trial["task_name"],
                    "reward": rewards.get("reward"),
                    "exception": (
                        exception.get("exception_type") if exception is not None else None
                    ),
                }
            )

    if args.expected_count is not None and args.expected_count <= 0:
        raise ValueError("expected-count must be positive")
    expected_count = args.expected_count or len(known_tasks)
    missing = sorted(known_tasks - actual) if args.expected_count is None else []
    unexpected = sorted(actual - known_tasks)
    duplicates = len(trials) - len(actual)
    print(
        f"oracle trials={len(trials)} expected={expected_count} "
        f"failures={len(failures)} missing={len(missing)} "
        f"unexpected={len(unexpected)} duplicates={duplicates}"
    )
    if failures:
        print(json.dumps(failures, indent=2))
    if missing:
        print(f"missing={missing}")
    if unexpected:
        print(f"unexpected={unexpected}")
    if (
        len(trials) != expected_count
        or failures
        or missing
        or unexpected
        or duplicates
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
