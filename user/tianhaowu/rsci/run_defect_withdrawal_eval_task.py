#!/usr/bin/env python3
"""Run one sealed verifier-defect withdrawal evaluation task."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any
from urllib.request import ProxyHandler, build_opener

import materialize_defect_withdrawal_eval as eval_plan

LOCAL_HTTP = build_opener(ProxyHandler({}))


class TerminationRequested(RuntimeError):
    def __init__(self, signal_number: int) -> None:
        super().__init__(f"received signal {signal.Signals(signal_number).name}")
        self.signal_number = signal_number


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("task_id")
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--dispatch-intent", type=Path, required=True)
    return parser.parse_args()


def load_plan(path: Path) -> tuple[bytes, dict[str, Any]]:
    eval_plan.validate_plan(path)
    raw, plan = eval_plan._read_json(path)
    return raw, plan


def task_from_plan(plan: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [task for task in plan["tasks"] if task["task_id"] == task_id]
    if len(matches) != 1:
        raise ValueError(f"Task lookup is not unique: {task_id}")
    task = matches[0]
    eval_plan._validate_task_contract(plan, task)
    return task


def attempt_predecessor(task: dict[str, Any], attempt: int) -> tuple[Path, str | None]:
    if attempt < 1:
        raise ValueError("Attempt must be positive")
    receipt_dir = Path(task["receipt_dir"])
    paths = []
    if receipt_dir.exists():
        if not receipt_dir.is_dir() or receipt_dir.is_symlink():
            raise ValueError(f"Receipt root is not a plain directory: {receipt_dir}")
        for path in receipt_dir.iterdir():
            match = eval_plan.RECEIPT_NAME_RE.fullmatch(path.name)
            if match is None:
                raise ValueError(f"Unexpected receipt artifact: {path}")
            paths.append((int(match.group(1)), path))
    paths.sort()
    if [number for number, _ in paths] != list(range(1, len(paths) + 1)):
        raise ValueError(f"Receipt attempts are not contiguous: {task['task_id']}")
    if attempt != len(paths) + 1:
        raise ValueError(f"Attempt {attempt} is not the next attempt {len(paths) + 1}")
    predecessor_sha256 = None
    if paths:
        raw, predecessor = eval_plan._read_json(paths[-1][1])
        if predecessor.get("status") == "succeeded":
            raise ValueError(f"Task already succeeded: {task['task_id']}")
        predecessor_sha256 = eval_plan.bytes_sha256(raw)
    return receipt_dir / f"attempt_{attempt:04d}.json", predecessor_sha256


def scheduler_identity(
    plan: dict[str, Any],
    task: dict[str, Any],
    attempt: int,
    dispatch_intent: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    job_id = os.environ.get("SLURM_JOB_ID")
    if not isinstance(job_id, str) or not job_id.isdigit():
        raise ValueError("SLURM_JOB_ID must identify the evaluation allocation")
    import dispatch_defect_withdrawal as dispatch

    runtime = dispatch.validate_runtime_eval_dispatch(
        dispatch_intent,
        plan=plan,
        task=task,
        attempt=attempt,
        job_id=job_id,
    )
    observed_job_name = os.environ.get("SLURM_JOB_NAME")
    if observed_job_name != runtime["scheduler"]["job_name"]:
        raise ValueError("Scheduler job name differs from the protected dispatch")
    array_task = os.environ.get("SLURM_ARRAY_TASK_ID")
    if array_task is not None and not array_task.isdigit():
        raise ValueError("SLURM_ARRAY_TASK_ID is invalid")
    scheduler = {
        **runtime["scheduler"],
        "array_task_id": int(array_task) if array_task is not None else None,
    }
    if scheduler["account"] != os.environ.get("SLURM_JOB_ACCOUNT") or scheduler["qos"] != os.environ.get(
        "SLURM_JOB_QOS"
    ):
        raise ValueError("Scheduler environment differs from the protected dispatch")
    return scheduler, runtime["dispatch_intent"]


def _terminate_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=30)


def _tail(path: Path, lines: int = 100) -> str:
    if not path.is_file():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _health_ready(url: str) -> bool:
    try:
        with LOCAL_HTTP.open(url, timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def start_inference(task: dict[str, Any], runtime_dir: Path) -> subprocess.Popen[bytes]:
    health_url = f"http://127.0.0.1:{task['transport_port']}/health"
    if _health_ready(health_url):
        raise RuntimeError(f"Inference port is already served: {health_url}")
    server_log = runtime_dir / "server.log"
    environment = dict(os.environ)
    cache_root = Path(environment.get("SLURM_TMPDIR", "/tmp")) / (f"rsci-vdw-eval-{environment['SLURM_JOB_ID']}")
    cache_root.mkdir(parents=True, exist_ok=True)
    environment["VLLM_CACHE_ROOT"] = str(cache_root)
    environment["HF_HUB_OFFLINE"] = "1"
    environment["UV_NO_SYNC"] = "1"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment.pop(name, None)
    log_handle = server_log.open("ab")
    try:
        process = subprocess.Popen(
            ["uv", "run", "--no-sync", "inference", "@", task["inference_config"]["path"]],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    try:
        for _ in range(180):
            if _health_ready(health_url):
                return process
            if process.poll() is not None:
                raise RuntimeError(
                    f"Inference exited with code {process.returncode} before health: {_tail(server_log)}"
                )
            time.sleep(5)
        raise TimeoutError(f"Inference did not become healthy within 15 minutes: {_tail(server_log)}")
    except BaseException:
        _terminate_process(process)
        raise


def run_evaluator(task: dict[str, Any], runtime_dir: Path) -> None:
    evaluator_log = runtime_dir / "evaluator.log"
    environment = dict(os.environ)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "OPENAI_API_KEY": "unused",
            "UV_NO_SYNC": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment.pop(name, None)
    with evaluator_log.open("ab") as handle:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--no-sync",
                task["evaluator_path"],
                task["eval_config"]["path"],
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=environment,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"Evaluator exited with code {completed.returncode}: {_tail(evaluator_log)}")


def build_terminal_receipt(
    *,
    plan: dict[str, Any],
    plan_sha256: str,
    task: dict[str, Any],
    attempt: int,
    predecessor_receipt_sha256: str | None,
    dispatch_intent: dict[str, Any],
    scheduler: dict[str, Any],
    started_at: str,
    finished_at: str,
    status: str,
    exit_code: int,
    failure: str | None = None,
) -> dict[str, Any]:
    if status not in eval_plan.TERMINAL_RECEIPT_STATUSES:
        raise ValueError(f"Unsupported terminal status: {status}")
    receipt = {
        "schema_version": eval_plan.SCHEMA_VERSION,
        "artifact_type": eval_plan.RECEIPT_ARTIFACT_TYPE,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan_sha256,
        "task_id": task["task_id"],
        "attempt": attempt,
        "predecessor_receipt_sha256": predecessor_receipt_sha256,
        "config_bundle_sha256": task["config_bundle_sha256"],
        "checkpoint_inventory_sha256": task["checkpoint_inventory_sha256"],
        "result_root": task["result_root"],
        "dispatch_intent": dispatch_intent,
        "runner": eval_plan.file_identity(Path(__file__)),
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "scheduler": scheduler,
        "exit_code": exit_code,
    }
    if status == "succeeded":
        if exit_code != 0 or failure is not None:
            raise ValueError("Succeeded receipt requires exit_code=0 and no failure")
        receipt["artifacts"] = {
            name: eval_plan.file_identity(Path(task["result_root"]) / name) for name in eval_plan.SUCCESS_ARTIFACT_NAMES
        }
    else:
        if exit_code == 0 or not isinstance(failure, str) or not failure:
            raise ValueError("Unsuccessful receipt requires nonzero exit and a failure")
        receipt["failure"] = failure
    return receipt


def _termination_status(error: BaseException) -> str:
    if isinstance(error, TerminationRequested):
        if error.signal_number == signal.SIGUSR1:
            return "preempted"
        return "cancelled"
    return "failed"


def execute(plan_path: Path, task_id: str, attempt: int, dispatch_intent_path: Path) -> None:
    plan_raw, plan = load_plan(plan_path)
    task = task_from_plan(plan, task_id)
    receipt_path, predecessor_sha256 = attempt_predecessor(task, attempt)
    scheduler, dispatch_intent = scheduler_identity(
        plan,
        task,
        attempt,
        dispatch_intent_path,
    )
    runtime_dir = Path(task["result_root"]) / "runtime" / f"attempt_{attempt:04d}"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    inference: subprocess.Popen[bytes] | None = None
    receipt: dict[str, Any]
    failure_error: BaseException | None = None
    try:
        inference = start_inference(task, runtime_dir)
        run_evaluator(task, runtime_dir)
        eval_plan.validate_completed_task(plan, task)
        receipt = build_terminal_receipt(
            plan=plan,
            plan_sha256=eval_plan.bytes_sha256(plan_raw),
            task=task,
            attempt=attempt,
            predecessor_receipt_sha256=predecessor_sha256,
            dispatch_intent=dispatch_intent,
            scheduler=scheduler,
            started_at=started_at,
            finished_at=utc_now(),
            status="succeeded",
            exit_code=0,
        )
    except BaseException as error:
        failure_error = error
        receipt = build_terminal_receipt(
            plan=plan,
            plan_sha256=eval_plan.bytes_sha256(plan_raw),
            task=task,
            attempt=attempt,
            predecessor_receipt_sha256=predecessor_sha256,
            dispatch_intent=dispatch_intent,
            scheduler=scheduler,
            started_at=started_at,
            finished_at=utc_now(),
            status=_termination_status(error),
            exit_code=1,
            failure=f"{type(error).__name__}: {error}",
        )
    finally:
        _terminate_process(inference)
    eval_plan._write_once(receipt_path, eval_plan.canonical_json_bytes(receipt))
    eval_plan.validate_receipt_chain(plan, eval_plan.bytes_sha256(plan_raw))
    if failure_error is not None:
        raise failure_error


def main() -> None:
    args = parse_args()

    def handle_signal(signal_number: int, _frame: FrameType | None) -> None:
        raise TerminationRequested(signal_number)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, handle_signal)
    execute(args.plan, args.task_id, args.attempt, args.dispatch_intent)
    print(json.dumps({"task_id": args.task_id, "attempt": args.attempt, "status": "succeeded"}))


if __name__ == "__main__":
    main()
