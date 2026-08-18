import argparse
import json
import os
import subprocess
from pathlib import Path

from pier_runner import run_pier_job
from provider_env import PROJECT_DIR, provider_environment_context
from submit_eval import PROVIDERS, build_environment

TASKS = Path("/checkpoint/ram/tianhaowu/deepswe_eval/deep-swe/tasks")
JOBS = Path("/checkpoint/ram/tianhaowu/deepswe_eval/jobs")
CONFIGS = Path("/checkpoint/ram/tianhaowu/deepswe_eval/configs")
VALIDATOR = PROJECT_DIR / "user/tianhaowu/deepswe_modal/validate_oracle.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--n-concurrent", type=int, default=16)
    parser.add_argument("--n-tasks", type=int)
    parser.add_argument("--sample-seed", type=int, default=0)
    parser.add_argument("--task-name", action="append", default=[])
    parser.add_argument("--name", default="deepswe-v1.1-oracle")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.n_concurrent <= 0:
        raise ValueError("n_concurrent must be positive")
    if args.n_tasks is not None and args.n_tasks <= 0:
        raise ValueError("n_tasks must be positive")
    if args.task_name and args.n_tasks is None:
        args.n_tasks = len(args.task_name)
    slurm_job_id = os.environ.get("SLURM_JOB_ID", "local")
    job_name = f"{args.name}-{args.provider}-{slurm_job_id}"
    dataset = {"path": str(TASKS)}
    if args.task_name:
        dataset["task_names"] = args.task_name
    if args.n_tasks is not None:
        dataset.update(n_tasks=args.n_tasks, sample_seed=args.sample_seed)
    config = {
        "job_name": job_name,
        "jobs_dir": str(JOBS),
        "n_attempts": 1,
        "n_concurrent_trials": args.n_concurrent,
        "quiet": True,
        "retry": {"max_retries": 1},
        "environment": build_environment(
            args.provider,
            {},
            modal_app_name="__pier_deepswe_oracle__",
        ),
        "agents": [{"name": "oracle"}],
        "datasets": [dataset],
    }
    CONFIGS.mkdir(parents=True, exist_ok=True)
    config_path = CONFIGS / f"{job_name}.json"
    config_path.write_text(json.dumps(config, indent=2))
    with provider_environment_context(args.provider) as env:
        result_path = run_pier_job(config_path, job_name, env=env)
    validator_command = [
            "uv",
            "run",
            "--no-sync",
            "python",
            str(VALIDATOR),
            str(result_path),
            str(TASKS),
        ]
    if args.n_tasks is not None:
        validator_command.extend(["--expected-count", str(args.n_tasks)])
    subprocess.run(
        validator_command,
        cwd=PROJECT_DIR,
        check=True,
    )


if __name__ == "__main__":
    main()
