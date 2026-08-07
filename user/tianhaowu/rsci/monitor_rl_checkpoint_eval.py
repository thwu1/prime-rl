#!/usr/bin/env python
"""Persist progress and scheduler state for one frozen-evaluation array."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from checkpoint_eval_artifacts import EXPECTED_STEPS, ValidationCache, inspect_metrics, job_ledger_path, load_job_ledger

TERMINAL_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "TIMEOUT",
}
ACTIVE_ACCOUNTING_STATES = {
    "COMPLETING",
    "CONFIGURING",
    "PENDING",
    "REQUEUED",
    "REQUEUE_FED",
    "REQUEUE_HOLD",
    "RESIZING",
    "RUNNING",
    "SIGNALING",
    "STAGE_OUT",
    "STOPPED",
    "SUSPENDED",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("array_job_id")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--scheduler-discovery-grace-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.interval_seconds < 1:
        raise ValueError("--interval-seconds must be positive")
    if args.scheduler_discovery_grace_seconds < 0:
        raise ValueError("--scheduler-discovery-grace-seconds must be non-negative")
    if re.fullmatch(r"[1-9][0-9]*", args.array_job_id) is None:
        raise ValueError("array_job_id must be a positive integer")
    return args


def normalize_state(raw_state: str) -> str:
    fields = raw_state.split()
    if not fields:
        raise ValueError("Slurm returned an empty job state")
    return fields[0].rstrip("+")


def expand_task_spec(spec: str) -> list[int]:
    task_spec = spec.split("%", maxsplit=1)[0]
    tasks: set[int] = set()
    for segment in task_spec.split(","):
        match = re.fullmatch(r"([0-9]+)(?:-([0-9]+)(?::([1-9][0-9]*))?)?", segment)
        if match is None:
            raise ValueError(f"Unsupported Slurm array task specification: {spec}")
        start = int(match.group(1))
        stop = int(match.group(2) or start)
        stride = int(match.group(3) or 1)
        if stop < start:
            raise ValueError(f"Descending Slurm array task range: {segment}")
        tasks.update(range(start, stop + 1, stride))
    if len(tasks) > 100_000:
        raise ValueError(f"Refusing to expand more than 100,000 Slurm array tasks: {spec}")
    return sorted(tasks)


def _run_scheduler(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)


def query_squeue(array_job_id: str) -> dict[str, Any]:
    result = _run_scheduler(
        [
            "squeue",
            "--noheader",
            "--array",
            "--jobs",
            array_job_id,
            "--format=%F|%K|%T|%M|%R",
        ]
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        if "Invalid job id specified" in message:
            return {"visibility": "purged", "parent": None, "tasks": {}}
        raise RuntimeError(f"squeue failed for array {array_job_id}: {message}")

    parent = None
    tasks: dict[str, dict[str, str]] = {}
    for line_number, line in enumerate(result.stdout.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("|", maxsplit=4)
        if len(fields) != 5:
            raise ValueError(f"Malformed squeue row {line_number}: {line!r}")
        parent_id, task_id, raw_state, elapsed, reason = fields
        if parent_id != array_job_id:
            raise ValueError(f"Unexpected array job ID in squeue row: {line!r}")
        record = {
            "state": normalize_state(raw_state),
            "source": "squeue",
            "elapsed": elapsed,
            "reason": reason,
        }
        if task_id == "N/A":
            parent = record
        elif task_id.isdecimal():
            tasks[str(int(task_id))] = record
        else:
            raise ValueError(f"Unexpected array task ID in squeue row: {line!r}")
    visibility = "live" if parent is not None or tasks else "absent"
    return {"visibility": visibility, "parent": parent, "tasks": tasks}


def query_sacct(array_job_id: str) -> dict[str, Any]:
    result = _run_scheduler(
        [
            "sacct",
            "-X",
            "--array",
            "--noheader",
            "--parsable2",
            "--jobs",
            array_job_id,
            "--format=JobID,State,ExitCode,Elapsed,Reason",
        ]
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"sacct failed for array {array_job_id}: {message}")

    parent = None
    tasks: dict[str, dict[str, str]] = {}
    task_pattern = re.compile(rf"^{re.escape(array_job_id)}_([0-9]+)$")
    range_pattern = re.compile(rf"^{re.escape(array_job_id)}_\[([^]]+)\]$")
    found = False
    for line_number, line in enumerate(result.stdout.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("|")
        if len(fields) < 5:
            raise ValueError(f"Malformed sacct row {line_number}: {line!r}")
        job_ref, raw_state, exit_code, elapsed, reason = fields[:5]
        record = {
            "state": normalize_state(raw_state),
            "source": "sacct",
            "exit_code": exit_code,
            "elapsed": elapsed,
            "reason": reason,
        }
        if job_ref == array_job_id:
            parent = record
            found = True
            continue
        if match := task_pattern.fullmatch(job_ref):
            tasks[str(int(match.group(1)))] = record
            found = True
            continue
        if match := range_pattern.fullmatch(job_ref):
            for task_id in expand_task_spec(match.group(1)):
                tasks.setdefault(str(task_id), record)
            found = True
    return {"visibility": "recorded" if found else "absent", "parent": parent, "tasks": tasks}


def scheduler_snapshot(array_job_id: str) -> dict[str, Any]:
    live = query_squeue(array_job_id)
    accounting = query_sacct(array_job_id)
    tasks = {task_id: dict(record) for task_id, record in accounting["tasks"].items()}
    for task_id, live_record in live["tasks"].items():
        record = dict(live_record)
        if task_id in tasks:
            record["accounting_state"] = tasks[task_id]["state"]
            record["exit_code"] = tasks[task_id]["exit_code"]
        tasks[task_id] = record
    tasks = dict(sorted(tasks.items(), key=lambda item: int(item[0])))
    parent = live["parent"] or accounting["parent"]
    states = Counter(record["state"] for record in tasks.values())
    producer_active = live["visibility"] == "live" or any(
        record["state"] in ACTIVE_ACCOUNTING_STATES for record in accounting["tasks"].values()
    )
    if accounting["parent"] is not None:
        producer_active |= accounting["parent"]["state"] in ACTIVE_ACCOUNTING_STATES
    scheduler_seen = live["visibility"] == "live" or accounting["visibility"] == "recorded"
    return {
        "squeue_visibility": live["visibility"],
        "sacct_visibility": accounting["visibility"],
        "scheduler_seen": scheduler_seen,
        "producer_active": producer_active,
        "parent": parent,
        "known_task_count": len(tasks),
        "state_counts": dict(sorted(states.items())),
        "tasks": tasks,
    }


def reconcile_scheduler(
    current: dict[str, Any],
    expected_task_ids: set[str],
    known_tasks: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], set[str], dict[str, dict[str, Any]]]:
    expected_task_ids = expected_task_ids | set(current["tasks"])
    known_tasks = {task_id: dict(record) for task_id, record in known_tasks.items()}
    known_tasks.update({task_id: dict(record) for task_id, record in current["tasks"].items()})
    known_tasks = dict(sorted(known_tasks.items(), key=lambda item: int(item[0])))
    all_producers_terminal = bool(expected_task_ids) and all(
        task_id in known_tasks and known_tasks[task_id]["state"] in TERMINAL_STATES for task_id in expected_task_ids
    )
    dependency_failed_tasks = sorted(
        (
            task_id
            for task_id in expected_task_ids
            if task_id in known_tasks and "DependencyNeverSatisfied" in str(known_tasks[task_id].get("reason", ""))
        ),
        key=int,
    )
    all_producers_stopped = bool(expected_task_ids) and all(
        task_id in known_tasks
        and (
            known_tasks[task_id]["state"] in TERMINAL_STATES
            or "DependencyNeverSatisfied" in str(known_tasks[task_id].get("reason", ""))
        )
        for task_id in expected_task_ids
    )
    states = Counter(record["state"] for record in known_tasks.values())
    current["expected_task_ids"] = sorted(expected_task_ids, key=int)
    current["known_task_count"] = len(known_tasks)
    current["state_counts"] = dict(sorted(states.items()))
    current["all_producers_terminal"] = all_producers_terminal
    current["all_producers_stopped"] = all_producers_stopped
    current["dependency_failed_task_ids"] = dependency_failed_tasks
    current["tasks"] = known_tasks
    return current, expected_task_ids, known_tasks


def classify_batch(
    completed_count: int,
    *,
    producer_active: bool,
    all_producers_stopped: bool,
    scheduler_seen: bool,
    discovery_grace_expired: bool,
) -> str:
    if completed_count == len(EXPECTED_STEPS):
        return "complete"
    if all_producers_stopped:
        return "stopped-incomplete"
    if producer_active:
        return "running"
    if not scheduler_seen and not discovery_grace_expired:
        return "waiting-for-scheduler"
    return "scheduler-unresolved"


def _iso_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def progress_payload(completion_times: list[float], now: float) -> dict[str, Any]:
    count = len(completion_times)
    remaining = len(EXPECTED_STEPS) - count
    window = sorted(completion_times)[-5:]
    throughput_per_hour = None
    eta_seconds = None
    eta_at = None
    if len(window) >= 2 and window[-1] > window[0]:
        throughput_per_hour = 3600.0 * (len(window) - 1) / (window[-1] - window[0])
    if remaining == 0:
        eta_seconds = 0
        eta_at = _iso_timestamp(now)
    elif throughput_per_hour is not None and throughput_per_hour > 0:
        eta_seconds = round(3600.0 * remaining / throughput_per_hour)
        eta_at = _iso_timestamp((datetime.fromtimestamp(now, UTC) + timedelta(seconds=eta_seconds)).timestamp())
    return {
        "completed_count": count,
        "expected_count": len(EXPECTED_STEPS),
        "percent_complete": round(100.0 * count / len(EXPECTED_STEPS), 6),
        "throughput_per_hour": None if throughput_per_hour is None else round(throughput_per_hour, 6),
        "throughput_window_completions": len(window),
        "eta_seconds": eta_seconds,
        "eta_at": eta_at,
    }


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    partial.replace(path)


def previous_monitor_state(
    status_path: Path,
    run_dir: Path,
    array_job_id: str,
) -> tuple[float, bool, set[str], dict[str, dict[str, Any]]] | None:
    if not status_path.is_file():
        return None
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Existing monitor status is not a JSON object: {status_path}")
    if payload.get("run_dir") != str(run_dir) or payload.get("array_job_id") != array_job_id:
        return None
    monitor = payload.get("monitor")
    scheduler = payload.get("scheduler")
    if not isinstance(monitor, dict) or not isinstance(scheduler, dict):
        raise ValueError(f"Existing monitor status lacks monitor or scheduler state: {status_path}")
    started_at_unix = monitor.get("started_at_unix")
    ever_seen = scheduler.get("ever_seen")
    expected_task_ids = scheduler.get("expected_task_ids")
    tasks = scheduler.get("tasks")
    if (
        isinstance(started_at_unix, bool)
        or not isinstance(started_at_unix, (int, float))
        or not isinstance(ever_seen, bool)
        or not isinstance(expected_task_ids, list)
        or not all(isinstance(task_id, str) and task_id.isdecimal() for task_id in expected_task_ids)
        or not isinstance(tasks, dict)
        or not all(
            isinstance(task_id, str)
            and task_id.isdecimal()
            and isinstance(record, dict)
            and isinstance(record.get("state"), str)
            for task_id, record in tasks.items()
        )
    ):
        raise ValueError(f"Existing monitor status has invalid persistent state: {status_path}")
    return (
        float(started_at_unix),
        ever_seen,
        set(expected_task_ids),
        {task_id: dict(record) for task_id, record in tasks.items()},
    )


def monitor(run_dir: Path, array_job_id: str, interval_seconds: int, discovery_grace_seconds: int) -> int:
    run_dir = run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")
    if not (run_dir / "configs" / "trainer.toml").is_file():
        raise FileNotFoundError(f"Resolved trainer config does not exist under run directory: {run_dir}")
    ledger = load_job_ledger(run_dir, array_job_id)
    if ledger is None:
        raise FileNotFoundError(
            f"Frozen evaluation job ledger does not exist: {job_ledger_path(run_dir, array_job_id)}"
        )
    task_to_step = {str(task_id): int(step) for task_id, step in ledger["task_to_step"].items()}
    ledger_task_ids = set(task_to_step)
    status_path = run_dir / "evals" / "op11-45" / "array" / "status.json"
    previous = previous_monitor_state(status_path, run_dir, array_job_id)
    if previous is None:
        started_at_unix = time.time()
        ever_seen = False
        expected_task_ids = set(ledger_task_ids)
        known_tasks: dict[str, dict[str, Any]] = {}
    else:
        started_at_unix, ever_seen, expected_task_ids, known_tasks = previous
        if expected_task_ids != ledger_task_ids:
            raise ValueError("Persisted monitor task IDs do not match the frozen evaluation job ledger")
        if not set(known_tasks).issubset(ledger_task_ids):
            raise ValueError("Persisted monitor tasks are absent from the frozen evaluation job ledger")
    validation_cache: ValidationCache = {}

    while True:
        now = time.time()
        completed, missing, invalid, completion_times = inspect_metrics(run_dir, validation_cache)
        scheduler = scheduler_snapshot(array_job_id)
        unexpected_tasks = set(scheduler["tasks"]) - ledger_task_ids
        if unexpected_tasks:
            raise ValueError(
                f"Scheduler returned tasks absent from the job ledger: {sorted(unexpected_tasks, key=int)}"
            )
        ever_seen |= scheduler["scheduler_seen"]
        scheduler, expected_task_ids, known_tasks = reconcile_scheduler(
            scheduler,
            expected_task_ids,
            known_tasks,
        )
        for task_id, record in scheduler["tasks"].items():
            record["step"] = task_to_step[task_id]
        scheduler["job_ledger_path"] = str(job_ledger_path(run_dir, array_job_id))
        scheduler["ever_seen"] = ever_seen
        discovery_grace_expired = now - started_at_unix >= discovery_grace_seconds
        state = classify_batch(
            len(completed),
            producer_active=scheduler["producer_active"],
            all_producers_stopped=scheduler["all_producers_stopped"],
            scheduler_seen=ever_seen,
            discovery_grace_expired=discovery_grace_expired,
        )
        stop_reason = None
        if state == "stopped-incomplete":
            stop_reason = (
                "dependency-never-satisfied" if scheduler["dependency_failed_task_ids"] else "all-producers-terminal"
            )
        payload = {
            "schema_version": 1,
            "updated_at": _iso_timestamp(now),
            "run_dir": str(run_dir),
            "array_job_id": array_job_id,
            "state": state,
            "stop_reason": stop_reason,
            "expected_steps": list(EXPECTED_STEPS),
            "completed_steps": completed,
            "missing_steps": missing,
            "invalid_metrics": invalid,
            "progress": progress_payload(completion_times, now),
            "scheduler": scheduler,
            "monitor": {
                "started_at": _iso_timestamp(started_at_unix),
                "started_at_unix": started_at_unix,
                "interval_seconds": interval_seconds,
                "scheduler_discovery_grace_seconds": discovery_grace_seconds,
            },
        }
        write_status(status_path, payload)
        print(
            f"{payload['updated_at']} state={state} valid_metrics={len(completed)}/{len(EXPECTED_STEPS)} "
            f"scheduler_states={scheduler['state_counts']}",
            flush=True,
        )
        if state == "complete":
            return 0
        if state == "stopped-incomplete":
            print(f"Frozen evaluation producers terminated before completion; see {status_path}", flush=True)
            return 1
        time.sleep(interval_seconds)


def main() -> None:
    args = parse_args()
    raise SystemExit(
        monitor(
            args.run_dir,
            args.array_job_id,
            args.interval_seconds,
            args.scheduler_discovery_grace_seconds,
        )
    )


if __name__ == "__main__":
    main()
