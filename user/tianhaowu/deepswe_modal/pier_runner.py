import argparse
import json
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path

PROJECT_DIR = Path("/storage/home/tianhaowu/prime-rl")
JOBS_DIR = Path("/checkpoint/ram/tianhaowu/deepswe_eval/jobs")


def pier_command(config: Path, job_name: str) -> list[str]:
    return [
        "uv",
        "tool",
        "run",
        "--offline",
        "--isolated",
        "--from",
        "datacurve-pier==0.3.1",
        "--with-editable",
        str(PROJECT_DIR / "deps/verifiers"),
        "--exclude-newer-package",
        "datacurve-pier=2026-08-19",
        "pier",
        "run",
        "--config",
        str(config),
        "--job-name",
        job_name,
        "--yes",
    ]


def pier_resume_command(job_dir: Path) -> list[str]:
    return [
        "uv",
        "tool",
        "run",
        "--offline",
        "--isolated",
        "--from",
        "datacurve-pier==0.3.1",
        "--with-editable",
        str(PROJECT_DIR / "deps/verifiers"),
        "--exclude-newer-package",
        "datacurve-pier=2026-08-19",
        "pier",
        "job",
        "resume",
        "--job-path",
        str(job_dir),
    ]


def read_result(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def terminate_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def validate_clean_completion(result: dict) -> None:
    stats = result["stats"]
    total = result["n_total_trials"]
    completed = stats["n_completed_trials"]
    errored = stats["n_errored_trials"]
    running = stats["n_running_trials"]
    pending = stats["n_pending_trials"]
    cancelled = stats.get("n_cancelled_trials", 0)
    if result.get("finished_at") is None:
        raise RuntimeError("Pier result is not marked finished")
    if completed != total or running or pending or cancelled:
        raise RuntimeError(
            "Pier job did not reach a complete terminal state: "
            f"total={total} completed={completed} errored={errored} "
            f"running={running} pending={pending} cancelled={cancelled}"
        )


def run_pier_job(
    config: Path,
    job_name: str,
    *,
    env: dict[str, str] | None = None,
) -> Path:
    job_dir = JOBS_DIR / job_name
    result_path = job_dir / "result.json"
    existing_result = read_result(result_path)
    if existing_result is not None and existing_result.get("finished_at") is not None:
        validate_clean_completion(existing_result)
        print(f"Pier already completed: {result_path}", flush=True)
        return result_path

    command = pier_resume_command(job_dir) if existing_result is not None else pier_command(config, job_name)
    print(f"Running: {shlex.join(command)}", flush=True)
    process = subprocess.Popen(
        command,
        cwd=PROJECT_DIR,
        env=env,
        start_new_session=True,
    )

    def handle_sigterm(_signum, _frame) -> None:
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, handle_sigterm)
    result = None
    try:
        while True:
            result = read_result(result_path)
            if result is not None and result.get("finished_at") is not None:
                break
            return_code = process.poll()
            if return_code is not None:
                raise subprocess.CalledProcessError(return_code, command)
            time.sleep(5)

        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("Pier result is complete; terminating its lingering process", flush=True)
            terminate_process_group(process)
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        terminate_process_group(process)

    validate_clean_completion(result)
    print(
        f"Pier completed: {result_path} (errored={result['stats']['n_errored_trials']})",
        flush=True,
    )
    return result_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("job_name")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_pier_job(args.config.resolve(), args.job_name, env=os.environ.copy())


if __name__ == "__main__":
    main()
