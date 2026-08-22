#!/usr/bin/env python3

import argparse
import asyncio
import copy
import hashlib
import inspect
import json
import os
import shutil
import tarfile
import tempfile
import time
import tomllib
from pathlib import Path

from swebench_verified_vmvm.taskset import (
    SWEBenchVerifiedVMVMConfig,
    SWEBenchVerifiedVMVMTaskset,
)
from verifiers.v1.runtimes import VMVMConfig, VMVMRuntime, make_runtime
from verifiers.v1.trace import Trace

TIMEOUT_ERROR_TYPE = "TasksetError"
TIMEOUT_ERROR_MESSAGE = "scoring timed out"
REQUIRED_RUN_FILES = (
    "config.toml",
    "implementation.sha256",
    "implementation.tar.gz",
    "implementation_revisions.txt",
    "models.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Re-run only the fresh SWE-bench Verified verifier for an exact timed-out "
            "result row, preserving its model trajectory and candidate patch."
        )
    )
    parser.add_argument("base_dir", type=Path)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_sha256(row: dict[str, object]) -> str:
    payload = json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def read_target_row(results: Path, trace_id: str) -> dict[str, object]:
    matches = []
    with results.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("id") == trace_id:
                matches.append(row)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one row for trace {trace_id}, found {len(matches)}")
    return matches[0]


def candidate_patch(row: dict[str, object]) -> str:
    info = row.get("info")
    candidate = info.get("swebench_candidate_patch") if isinstance(info, dict) else None
    if not isinstance(candidate, dict):
        raise ValueError("timed-out row has no candidate-patch metadata")
    patch = candidate.get("patch")
    if not isinstance(patch, str):
        raise ValueError("timed-out row has a non-string candidate patch")
    encoded = patch.encode()
    if candidate.get("bytes") != len(encoded):
        raise ValueError("candidate-patch byte count does not match")
    if candidate.get("sha256") != hashlib.sha256(encoded).hexdigest():
        raise ValueError("candidate-patch SHA-256 does not match")
    return patch


def validate_timeout_row(row: dict[str, object]) -> None:
    if row.get("is_completed") is not True:
        raise ValueError("timed-out row is not complete")
    errors = row.get("errors")
    if not isinstance(errors, list) or len(errors) != 1:
        raise ValueError("timed-out row must contain exactly one error")
    error = errors[0]
    if not isinstance(error, dict) or error.get("type") != TIMEOUT_ERROR_TYPE:
        raise ValueError(f"row error is not {TIMEOUT_ERROR_TYPE}")
    if error.get("message") != TIMEOUT_ERROR_MESSAGE:
        raise ValueError(f"row error is not {TIMEOUT_ERROR_MESSAGE!r}")
    traceback = error.get("traceback")
    required_frames = ("_run_fresh_verifier", "_run_verifier", "asyncio.exceptions.CancelledError")
    if not isinstance(traceback, str) or not all(frame in traceback for frame in required_frames):
        raise ValueError("timeout did not originate in the fresh VMVM verifier command")
    rewards = row.get("rewards")
    if not isinstance(rewards, dict) or rewards:
        raise ValueError("timed-out row already has rewards")
    candidate_patch(row)


def task_name(row: dict[str, object]) -> str:
    task = row.get("task")
    name = task.get("name") if isinstance(task, dict) else None
    if not isinstance(name, str) or not name:
        raise ValueError("timed-out row has no task name")
    return name


def build_taskset(config: dict[str, object], name: str) -> SWEBenchVerifiedVMVMTaskset:
    taskset_config = copy.deepcopy(config.get("taskset"))
    if not isinstance(taskset_config, dict) or taskset_config.get("id") != "swebench-verified-vmvm":
        raise ValueError("config does not use swebench-verified-vmvm")
    taskset_config["tasks"] = [name]
    taskset_config.pop("id", None)
    return SWEBenchVerifiedVMVMTaskset(SWEBenchVerifiedVMVMConfig(**taskset_config))


def build_runtime(config: dict[str, object], trace_id: str) -> VMVMRuntime:
    harness = config.get("harness")
    runtime_config = harness.get("runtime") if isinstance(harness, dict) else None
    if not isinstance(runtime_config, dict) or runtime_config.get("type") != "vmvm":
        raise ValueError("config does not use a VMVM harness runtime")
    runtime = make_runtime(VMVMConfig(**runtime_config), name=f"{trace_id}-verifier-recovery-template")
    if not isinstance(runtime, VMVMRuntime):
        raise TypeError("configured runtime is not VMVM")
    return runtime


async def recover_row(
    row: dict[str, object],
    config: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    validate_timeout_row(row)
    name = task_name(row)
    taskset = build_taskset(config, name)
    tasks = taskset.load_tasks()
    if len(tasks) != 1 or tasks[0].name != name:
        raise ValueError(f"could not load exact SWE-bench task {name}")
    task = tasks[0]
    timeout_seconds = task.timeout.scoring
    if timeout_seconds is None or timeout_seconds <= 0:
        raise ValueError(f"task {name} has no positive verifier timeout")

    info = row.get("info")
    if not isinstance(info, dict):
        raise ValueError("timed-out row has no info metadata")
    trace = Trace(id=str(row["id"]), task=task, info=copy.deepcopy(info))
    runtime = build_runtime(config, trace.id)
    patch = candidate_patch(row)
    started_at = time.time()
    score, report, exit_code, output_tail = await taskset._run_fresh_verifier(task, trace, runtime, patch)
    completed_at = time.time()

    verifier = {
        "exit_code": exit_code,
        "patch_successfully_applied": report["patch_successfully_applied"],
        "resolved": report["resolved"],
        "tests_status": report["tests_status"],
    }
    if report.get("timed_out") is True:
        verifier["timed_out"] = True
        verifier["timeout_sec"] = report["timeout_sec"]
    if not score:
        verifier["output_tail"] = output_tail

    recovered = copy.deepcopy(row)
    recovered["info"] = copy.deepcopy(trace.info)
    recovered["info"]["swebench_verifier"] = verifier
    recovered["info"]["swebench_verifier_recovery"] = {
        "classification": "same_trajectory_fresh_verifier",
        "source_error_type": TIMEOUT_ERROR_TYPE,
        "source_error_message": TIMEOUT_ERROR_MESSAGE,
        "source_row_sha256": row_sha256(row),
        "candidate_patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "started_at": started_at,
        "completed_at": completed_at,
    }
    recovered["rewards"] = {"solved": score}
    recovered["errors"] = []
    timing = recovered.get("timing")
    if not isinstance(timing, dict):
        timing = {}
        recovered["timing"] = timing
    timing["scoring"] = {"start": started_at, "end": completed_at}
    return recovered, recovered["info"]["swebench_verifier_recovery"]


def copy_run_files(base_dir: Path, output_dir: Path) -> None:
    for name in REQUIRED_RUN_FILES:
        source = base_dir / name
        if not source.is_file():
            raise ValueError(f"base run is missing required file: {source}")
        if name != "config.toml":
            shutil.copy2(source, output_dir / name)


def write_recovery_sources(output_dir: Path) -> tuple[dict[str, str], str]:
    sources = {
        "recover_swebench_verified_verifier.py": Path(__file__).resolve(),
        "swebench_verified_vmvm/taskset.py": Path(inspect.getfile(SWEBenchVerifiedVMVMTaskset)).resolve(),
    }
    hashes = {name: file_sha256(path) for name, path in sources.items()}
    archive_path = output_dir / "verifier_recovery_sources.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sources.items():
            archive.add(path, arcname=name)
    with (output_dir / "verifier_recovery_sources.sha256").open("x") as handle:
        for name, digest in sorted(hashes.items()):
            handle.write(f"{digest}  {name}\n")
        handle.flush()
        os.fsync(handle.fileno())
    return hashes, file_sha256(archive_path)


def main() -> None:
    args = parse_args()
    base_dir = args.base_dir.resolve()
    output_dir = args.output_dir.resolve()
    results = base_dir / "results.jsonl"
    config_path = base_dir / "config.toml"
    if output_dir.exists():
        raise SystemExit(f"refusing to overwrite existing output directory: {output_dir}")
    if not results.is_file() or not config_path.is_file():
        raise SystemExit(f"base run is incomplete: {base_dir}")

    source_row = read_target_row(results, args.trace_id)
    config = tomllib.loads(config_path.read_text())
    recovered_row, recovery = asyncio.run(recover_row(source_row, config))

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        copy_run_files(base_dir, temporary_dir)
        recovery_source_hashes, recovery_archive_sha256 = write_recovery_sources(temporary_dir)
        recovery["source_files"] = recovery_source_hashes
        recovery["source_archive_sha256"] = recovery_archive_sha256
        taskset_config = copy.deepcopy(config)
        taskset_config["taskset"]["tasks"] = [task_name(source_row)]
        taskset_config["num_tasks"] = 1
        taskset_config["num_rollouts"] = 1
        taskset_config["max_concurrent"] = 1
        taskset_config["multiplex"] = 1
        taskset_config["output_dir"] = str(output_dir)
        with (temporary_dir / "config.toml").open("w") as handle:
            import tomli_w

            tomli_w.dump(taskset_config, handle)
            handle.flush()
            os.fsync(handle.fileno())
        with (temporary_dir / "results.jsonl").open("x") as handle:
            handle.write(json.dumps(recovered_row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        manifest = {
            "base_directory": str(base_dir),
            "source_trace_id": args.trace_id,
            "source_row_sha256": row_sha256(source_row),
            "output_directory": str(output_dir),
            "output_results_sha256": file_sha256(temporary_dir / "results.jsonl"),
            "task_name": task_name(source_row),
            "reward": recovered_row["rewards"]["solved"],
            "recovery": recovery,
        }
        with (temporary_dir / "swebench_verifier_recovery.json").open("x") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        (temporary_dir / ".writer.lock").touch()
        temporary_dir.replace(output_dir)
    except BaseException:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise

    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
