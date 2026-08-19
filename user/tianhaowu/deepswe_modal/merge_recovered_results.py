import argparse
import hashlib
import json
from pathlib import Path

METRIC_NAMES = (
    "f2p",
    "f2p_passed",
    "f2p_total",
    "p2p",
    "p2p_passed",
    "p2p_total",
    "partial",
    "reward",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--replace-task", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with path.open() as file:
        return json.load(file)


def task_name_from_config(config_path: Path) -> str:
    config = load_json(config_path)
    return Path(config["task"]["path"]).name


def index_trials(job_dir: Path) -> dict[str, dict]:
    trials = {}
    for trial_dir in sorted(path for path in job_dir.iterdir() if path.is_dir()):
        config_path = trial_dir / "config.json"
        if not config_path.is_file():
            continue
        task_name = task_name_from_config(config_path)
        if task_name in trials:
            raise ValueError(f"duplicate task {task_name!r} in {job_dir}")
        result_path = trial_dir / "result.json"
        trials[task_name] = {
            "trial_dir": trial_dir,
            "result_path": result_path if result_path.is_file() else None,
        }
    return trials


def require_scored_result(task_name: str, trial: dict, source: str) -> dict:
    result_path = trial["result_path"]
    if result_path is None:
        raise ValueError(f"{source} task {task_name!r} has no result.json")
    result = load_json(result_path)
    if result.get("exception_info") is not None:
        exception_type = result["exception_info"].get("exception_type", "unknown")
        raise ValueError(f"{source} task {task_name!r} failed with {exception_type}")
    verifier_result = result.get("verifier_result")
    if not isinstance(verifier_result, dict) or not isinstance(
        verifier_result.get("rewards"), dict
    ):
        raise ValueError(f"{source} task {task_name!r} has no verifier rewards")
    missing_metrics = [
        metric for metric in METRIC_NAMES if not isinstance(verifier_result["rewards"].get(metric), int | float)
    ]
    if missing_metrics:
        raise ValueError(f"{source} task {task_name!r} is missing metrics {missing_metrics}")
    return result


def aggregate_metrics(results: dict[str, dict]) -> dict[str, float]:
    count = len(results)
    return {
        metric: sum(result["verifier_result"]["rewards"][metric] for result in results.values())
        / count
        for metric in METRIC_NAMES
    }


def aggregate_sha256(job_dir: Path) -> str | None:
    path = job_dir / "result.json"
    return file_sha256(path) if path.is_file() else None


def main() -> None:
    args = parse_args()
    replace_tasks = args.replace_task
    if len(replace_tasks) != len(set(replace_tasks)):
        raise ValueError("--replace-task values must be unique")

    expected_tasks = {path.name for path in args.tasks.iterdir() if path.is_dir()}
    if not expected_tasks:
        raise ValueError(f"no task directories found under {args.tasks}")
    unknown_replacements = sorted(set(replace_tasks) - expected_tasks)
    if unknown_replacements:
        raise ValueError(f"replacement tasks are not in the benchmark: {unknown_replacements}")

    base_trials = index_trials(args.base)
    recovery_trials = index_trials(args.recovery)
    if set(recovery_trials) != set(replace_tasks):
        raise ValueError(
            "recovery tasks do not exactly match --replace-task: "
            f"recovery={sorted(recovery_trials)}, requested={sorted(replace_tasks)}"
        )

    final_results = {}
    task_provenance = {}
    for task_name in sorted(expected_tasks):
        source = "recovery" if task_name in recovery_trials else "base"
        trials = recovery_trials if source == "recovery" else base_trials
        if task_name not in trials:
            raise ValueError(f"{source} has no trial directory for task {task_name!r}")
        result = require_scored_result(task_name, trials[task_name], source)
        result_path = trials[task_name]["result_path"]
        final_results[task_name] = result
        task_provenance[task_name] = {
            "source": source,
            "trial_name": result["trial_name"],
            "task_checksum": result["task_checksum"],
            "result_path": str(result_path.resolve()),
            "result_sha256": file_sha256(result_path),
        }

    if set(final_results) != expected_tasks:
        raise ValueError("final task set does not exactly match the benchmark")

    for task_name in replace_tasks:
        base_trial = base_trials.get(task_name)
        base_result = None
        if base_trial is not None and base_trial["result_path"] is not None:
            base_result = load_json(base_trial["result_path"])
        replacement_checksum = final_results[task_name]["task_checksum"]
        if base_result is not None and base_result.get("task_checksum") != replacement_checksum:
            raise ValueError(f"task checksum changed for recovered task {task_name!r}")

    output = {
        "n_tasks": len(final_results),
        "metrics": aggregate_metrics(final_results),
        "provenance": {
            "base_job_dir": str(args.base.resolve()),
            "base_aggregate_sha256": aggregate_sha256(args.base),
            "recovery_job_dir": str(args.recovery.resolve()),
            "recovery_aggregate_sha256": aggregate_sha256(args.recovery),
            "tasks_dir": str(args.tasks.resolve()),
            "replaced_tasks": sorted(replace_tasks),
            "source_counts": {
                "base": len(final_results) - len(replace_tasks),
                "recovery": len(replace_tasks),
            },
        },
        "tasks": task_provenance,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), **output["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
