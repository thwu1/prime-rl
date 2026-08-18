import argparse
import json
import tomllib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("tasks", type=Path)
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
    expected = task_names(args.tasks)
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

    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    print(
        f"oracle trials={len(trials)} expected={len(expected)} "
        f"failures={len(failures)} missing={len(missing)} unexpected={len(unexpected)}"
    )
    if failures:
        print(json.dumps(failures, indent=2))
    if missing:
        print(f"missing={missing}")
    if unexpected:
        print(f"unexpected={unexpected}")
    if len(trials) != len(expected) or failures or missing or unexpected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
