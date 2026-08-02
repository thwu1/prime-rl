#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import wandb
from wandb.proto import wandb_internal_pb2
from wandb.sdk.internal import datastore, sender
from wandb.sync.sync import SyncManager

REMOTE_TERMINAL_STATES = frozenset({"crashed", "failed", "finished", "killed"})


class NoopDirWatcher:
    def __init__(self, *args, **kwargs):
        pass

    def finish(self):
        pass

    def update_policy(self, *args, **kwargs):
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload completed RSCI offline W&B metric streams")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--entity", default="ram")
    parser.add_argument("--project", default="rsci")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--watch-job", action="append", default=[])
    parser.add_argument("--run-id-override", action="append", default=[])
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def parse_overrides(values: list[str]) -> dict[str, str]:
    overrides = {}
    for value in values:
        local_id, separator, remote_id = value.partition("=")
        if not separator or not local_id or not remote_id:
            raise ValueError(f"Expected LOCAL_ID=REMOTE_ID, got {value!r}")
        overrides[local_id] = remote_id
    return overrides


def run_file(run_dir: Path) -> Path:
    files = list(run_dir.glob("*.wandb"))
    if len(files) != 1:
        raise ValueError(f"Expected one .wandb file in {run_dir}, found {len(files)}")
    return files[0]


def record_metadata(path: Path) -> tuple[Counter[str], int | None] | None:
    store = datastore.DataStore()
    store.open_for_scan(str(path))
    counts: Counter[str] = Counter()
    exit_code = None
    try:
        while data := store.scan_data():
            record = wandb_internal_pb2.Record()
            record.ParseFromString(data)
            record_type = record.WhichOneof("record_type")
            counts[record_type] += 1
            if record_type == "exit":
                exit_code = record.exit.exit_code
    except AssertionError:
        return None
    return counts, exit_code


def discover_completed(root: Path) -> Iterator[tuple[Path, Path, Counter[str], int]]:
    for run_dir in sorted(root.glob("**/wandb/offline-run-*")):
        path = run_file(run_dir)
        if Path(f"{path}.synced").exists():
            continue
        metadata = record_metadata(path)
        if metadata is None:
            continue
        counts, exit_code = metadata
        if counts["exit"] == 1 and exit_code is not None:
            yield run_dir, path, counts, exit_code


def job_active(job_id: str) -> bool:
    result = subprocess.run(
        ["squeue", "--noheader", "--jobs", job_id, "--format=%T"],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def remote_run(api: wandb.Api, entity: str, project: str, run_id: str):
    try:
        return api.run(f"{entity}/{project}/{run_id}")
    except wandb.errors.CommError:
        return None


def verify_remote_run(
    entity: str,
    project: str,
    remote_id: str,
    expected_history_rows: int,
    local_exit_code: int,
    timeout_seconds: int = 120,
):
    expected_states = {"finished"} if local_exit_code == 0 else REMOTE_TERMINAL_STATES
    deadline = time.monotonic() + timeout_seconds
    while True:
        uploaded = wandb.Api(timeout=60).run(f"{entity}/{project}/{remote_id}")
        if uploaded.state in expected_states:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Remote run {remote_id} is {uploaded.state}, expected one of {sorted(expected_states)}")
        time.sleep(5)

    remote_history_rows = sum(1 for _ in uploaded.scan_history(page_size=1000))
    if remote_history_rows != expected_history_rows:
        raise RuntimeError(
            f"Remote run {remote_id} has {remote_history_rows} history rows, expected {expected_history_rows}"
        )
    return uploaded


def sync_run(
    api: wandb.Api,
    run_dir: Path,
    path: Path,
    counts: Counter[str],
    entity: str,
    project: str,
    remote_id: str,
    local_exit_code: int,
) -> dict:
    existing = remote_run(api, entity, project, remote_id)
    if existing is None:
        manager = SyncManager(
            project=project,
            entity=entity,
            run_id=remote_id,
            app_url=api.client.app_url,
            mark_synced=False,
            append=False,
            skip_console=True,
        )
        manager.add(run_dir)
        manager.start()
        while not manager.is_done():
            manager.poll()
        manager._thread.join()

    uploaded = verify_remote_run(entity, project, remote_id, counts["history"], local_exit_code)
    Path(f"{path}.synced").touch()
    return {
        "history_rows": counts["history"],
        "local_exit_code": local_exit_code,
        "local_run_dir": str(run_dir),
        "remote_id": remote_id,
        "state": uploaded.state,
        "synced_at": now(),
        "url": uploaded.url,
    }


def main() -> None:
    args = parse_args()
    overrides = parse_overrides(args.run_id_override)
    sender.DirWatcher = NoopDirWatcher
    sender.SendManager._save_file = lambda self, fname, policy="end": None

    api = wandb.Api(timeout=60)
    status = {
        "created_at": now(),
        "entity": args.entity,
        "failures": {},
        "project": args.project,
        "root": str(args.root),
        "runs": {},
        "watch_jobs": args.watch_job,
    }
    if args.status.exists():
        status = json.loads(args.status.read_text())

    while True:
        for run_dir, path, counts, exit_code in discover_completed(args.root):
            local_id = run_dir.name.rsplit("-", 1)[-1]
            remote_id = overrides.get(local_id, local_id)
            try:
                status["runs"][local_id] = sync_run(
                    api,
                    run_dir,
                    path,
                    counts,
                    args.entity,
                    args.project,
                    remote_id,
                    exit_code,
                )
                status["failures"].pop(local_id, None)
            except Exception as error:
                status["failures"][local_id] = {"error": str(error), "failed_at": now()}
            status["completed_runs"] = len(status["runs"])
            status["failed_runs"] = len(status["failures"])
            status["updated_at"] = now()
            atomic_write_json(args.status, status)

        active_jobs = [job_id for job_id in args.watch_job if job_active(job_id)]
        status["active_watch_jobs"] = active_jobs
        status["completed_runs"] = len(status["runs"])
        status["failed_runs"] = len(status["failures"])
        status["updated_at"] = now()
        atomic_write_json(args.status, status)

        if args.once or not active_jobs:
            break
        time.sleep(args.poll_seconds)

    if status["failures"]:
        raise RuntimeError(f"Failed to sync {len(status['failures'])} W&B runs; see {args.status}")


if __name__ == "__main__":
    main()
