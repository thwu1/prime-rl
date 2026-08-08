#!/usr/bin/env python3
"""Freeze a plan-bound readiness manifest for one checkpoint-kernel task."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import materialize_known_cost_checkpoint_kernel_plan as plan_module
import probe_known_cost_checkpoint_kernel as checkpoint_probe

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_checkpoint_kernel_readiness"


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def directory_inventory(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    files = []
    for item in sorted(resolved.rglob("*")):
        if not item.is_file():
            continue
        relative = item.relative_to(resolved).as_posix()
        identity = checkpoint_probe.file_identity(item)
        files.append(
            {
                "relative_path": relative,
                "size_bytes": identity["size_bytes"],
                "sha256": identity["sha256"],
                "is_symlink": item.is_symlink(),
                "symlink_target": os.readlink(item) if item.is_symlink() else None,
            }
        )
    if not files:
        raise ValueError(f"Directory inventory is empty: {resolved}")
    return {
        "path": str(resolved),
        "file_count": len(files),
        "size_bytes": sum(item["size_bytes"] for item in files),
        "inventory_sha256": canonical_json_sha256(files),
        "files": files,
    }


def load_plan_task(plan_path: Path, task_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_path = plan_path.expanduser().resolve()
    plan_identity = plan_module.validate_plan(plan_path)
    _, plan = plan_module.read_canonical_json(plan_path)
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Checkpoint-kernel plan has no task inventory")
    matches = [task for task in tasks if isinstance(task, dict) and task.get("task_id") == task_id]
    if len(matches) != 1:
        raise ValueError(f"Checkpoint-kernel plan has {len(matches)} tasks named {task_id}")
    task = matches[0]
    if canonical_json_sha256(task) == "0" * 64:
        raise RuntimeError("Unreachable task hash")
    return plan, task, plan_identity


def _postrun_authority(plan: dict[str, Any]) -> dict[str, Any]:
    inputs = plan.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Checkpoint-kernel plan has no input identities")
    recorded = inputs.get("postrun_authority")
    if not isinstance(recorded, dict):
        raise ValueError("Checkpoint-kernel plan has no post-run authority identity")
    path = Path(str(recorded.get("path"))).expanduser().resolve()
    if checkpoint_probe.file_identity(path) != recorded:
        raise ValueError("Plan-bound post-run authority identity changed")
    _, authority = plan_module.read_canonical_json(path)
    return authority


def validate_completion_with_pinned_implementation(
    plan: dict[str, Any],
    task: dict[str, Any],
) -> dict[str, Any]:
    authority = _postrun_authority(plan)
    source = authority.get("postrun_control_source")
    if not isinstance(source, dict):
        raise ValueError("Post-run authority has no control source")
    environment = source.get("environment")
    implementations = source.get("implementations")
    if not isinstance(environment, dict) or not isinstance(implementations, dict):
        raise ValueError("Post-run authority control source is incomplete")
    python_path = Path(str(environment.get("python"))).expanduser().resolve()
    implementation = implementations.get("training_completion_materializer")
    if not isinstance(implementation, dict):
        raise ValueError("Post-run authority does not bind the completion materializer")
    implementation_path = Path(str(implementation.get("path"))).expanduser().resolve()
    if checkpoint_probe.file_identity(implementation_path) != implementation:
        raise ValueError("Authority-pinned completion validator identity changed")
    snapshot_path = Path(str(source.get("snapshot_path"))).expanduser().resolve()
    if not python_path.is_file() or not snapshot_path.is_dir():
        raise FileNotFoundError("Authority-pinned Python or source snapshot is absent")
    receipt_path = Path(str(task.get("completion_receipt_path"))).expanduser().resolve()
    command = [
        str(python_path),
        str(implementation_path),
        "validate",
        "--receipt",
        str(receipt_path),
    ]
    completed = subprocess.run(
        command,
        cwd=snapshot_path,
        text=True,
        capture_output=True,
        check=True,
    )
    summary = json.loads(completed.stdout)
    if not isinstance(summary, dict) or summary.get("command") != "validate":
        raise ValueError("Authority-pinned completion validator returned an invalid summary")
    if summary.get("receipt") != checkpoint_probe.file_identity(receipt_path):
        raise ValueError("Authority-pinned completion validator returned another receipt")
    if summary.get("live_scheduler_rechecked") is not False or summary.get("scheduler_mutation") is not False:
        raise ValueError("Authority-pinned completion validation changed its offline scope")
    return {
        "python": checkpoint_probe.file_identity(python_path),
        "implementation": implementation,
        "snapshot_path": str(snapshot_path),
        "snapshot_tree_sha256": source.get("source_tree_sha256"),
        "runtime_identity_sha256": source.get("runtime_identity_sha256"),
        "argv": command,
        "summary": summary,
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
    }


def current_task_context(plan_path: Path, task_id: str) -> dict[str, Any]:
    plan, task, plan_identity = load_plan_task(plan_path, task_id)
    checkpoint_path = Path(str(task["model_path"])).expanduser().resolve()
    step = int(task["checkpoint_step"])
    receipt_value = task.get("completion_receipt_path")
    receipt_path = Path(str(receipt_value)).expanduser().resolve() if receipt_value is not None else None
    checkpoint_before = directory_inventory(checkpoint_path)
    completion_validation = None
    if step:
        completion_validation = validate_completion_with_pinned_implementation(plan, task)
    probe_context = checkpoint_probe.checkpoint_context(
        Path(str(plan["inputs"]["source_probe"]["directory"])),
        checkpoint_path,
        receipt_path,
        step,
    )
    checkpoint_after = directory_inventory(checkpoint_path)
    if checkpoint_after != checkpoint_before:
        raise ValueError("Checkpoint inventory changed while materializing readiness")
    if step and probe_context["checkpoint"].get("arm_filename") != task.get("arm_filename"):
        raise ValueError("Checkpoint probe context belongs to another planned arm")

    plan_root = Path(str(plan_identity["path"])).parent
    canonical_output = plan_root / str(task["result_relative_path"])
    readiness_path = plan_root / "readiness" / f"{task_id}.json"
    attempt_root = plan_root / "attempts" / task_id
    return {
        "plan": plan_identity,
        "plan_id": plan["plan_id"],
        "task": task,
        "task_spec_sha256": canonical_json_sha256(task),
        "probe_context": probe_context,
        "checkpoint_inventory": checkpoint_after,
        "authority_pinned_completion_validation": completion_validation,
        "paths": {
            "readiness": str(readiness_path),
            "attempt_root": str(attempt_root),
            "canonical_output": str(canonical_output),
        },
        "implementations": {
            "readiness_materializer": checkpoint_probe.source_identity(Path(__file__)),
            "checkpoint_probe": checkpoint_probe.source_identity(Path(checkpoint_probe.__file__)),
        },
    }


def capture_pre_execution(context: dict[str, Any]) -> dict[str, Any]:
    paths = context["paths"]
    readiness = Path(paths["readiness"])
    canonical = Path(paths["canonical_output"])
    attempt_root = Path(paths["attempt_root"])
    if readiness.exists():
        raise FileExistsError(f"Readiness already exists: {readiness}")
    if canonical.exists():
        raise FileExistsError(f"Canonical checkpoint-kernel output already exists: {canonical}")
    candidates = sorted(str(path) for path in attempt_root.glob("*/candidate.json")) if attempt_root.is_dir() else []
    if candidates:
        raise FileExistsError(f"Checkpoint-kernel attempt candidate predates readiness: {candidates[0]}")
    return {
        "readiness_absent": True,
        "canonical_output_absent": True,
        "attempt_candidates_absent": True,
        "readiness_path": str(readiness),
        "canonical_output_path": str(canonical),
        "attempt_root": str(attempt_root),
    }


def build_readiness(
    plan_path: Path,
    task_id: str,
    pre_execution: dict[str, Any],
) -> dict[str, Any]:
    context = current_task_context(plan_path, task_id)
    paths = context["paths"]
    expected_pre_execution = {
        "readiness_absent": True,
        "canonical_output_absent": True,
        "attempt_candidates_absent": True,
        "readiness_path": paths["readiness"],
        "canonical_output_path": paths["canonical_output"],
        "attempt_root": paths["attempt_root"],
    }
    if pre_execution != expected_pre_execution:
        raise ValueError("Readiness pre-execution observation differs from the planned paths")
    readiness: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": plan_module.STUDY_ID,
        **context,
        "pre_execution": pre_execution,
        "scope": {
            "task_input_ready": True,
            "gpu_execution_authorized": False,
            "scheduler_submission_performed": False,
            "canonical_output_published": False,
            "scientific_result_identified": False,
        },
        "checks": {
            "plan_and_task_exactly_bound": True,
            "checkpoint_inventory_stable_during_readiness": True,
            "canonical_and_attempt_outputs_absent": True,
            "role_appropriate_completion_rule_satisfied": (
                context["authority_pinned_completion_validation"] is not None
                if int(context["task"]["checkpoint_step"]) > 0
                else context["authority_pinned_completion_validation"] is None
            ),
            "this_tool_performed_no_submission": True,
        },
    }
    readiness["payload_without_self_hash_sha256"] = canonical_json_sha256(readiness)
    return readiness


def write_readiness(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    expected = Path(str(value["paths"]["readiness"]))
    if resolved != expected:
        raise ValueError(f"Readiness must be written to {expected}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json_bytes(value)
    lock_path = resolved.parent / ".materialize.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if resolved.exists():
            if resolved.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace different readiness: {resolved}")
            return checkpoint_probe.file_identity(resolved)
        descriptor, temporary_name = tempfile.mkstemp(dir=resolved.parent, prefix=f".{resolved.name}.")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o444)
            os.link(temporary, resolved)
        finally:
            temporary.unlink(missing_ok=True)
    return checkpoint_probe.file_identity(resolved)


def validate_readiness(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError("Checkpoint-kernel readiness is writable")
    raw, observed = plan_module.read_canonical_json(resolved)
    if observed.get("schema_version") != SCHEMA_VERSION or observed.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Checkpoint-kernel readiness has the wrong schema or artifact type")
    payload = dict(observed)
    self_hash = payload.pop("payload_without_self_hash_sha256", None)
    if self_hash != canonical_json_sha256(payload):
        raise ValueError("Checkpoint-kernel readiness self hash differs")
    expected = build_readiness(
        Path(str(observed["plan"]["path"])),
        str(observed["task"]["task_id"]),
        observed["pre_execution"],
    )
    if raw != canonical_json_bytes(expected):
        raise ValueError("Checkpoint-kernel readiness differs from deterministic replay")
    if resolved != Path(str(observed["paths"]["readiness"])):
        raise ValueError("Checkpoint-kernel readiness is not at its planned path")
    return checkpoint_probe.file_identity(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--plan", type=Path, required=True)
    materialize.add_argument("--task-id", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--readiness", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        context = current_task_context(args.plan, args.task_id)
        pre_execution = capture_pre_execution(context)
        value = build_readiness(args.plan, args.task_id, pre_execution)
        identity = write_readiness(Path(value["paths"]["readiness"]), value)
        validated = validate_readiness(Path(str(identity["path"])))
        summary = {"command": "materialize", "task_id": args.task_id, "readiness": validated}
    else:
        validated = validate_readiness(args.readiness)
        _, value = plan_module.read_canonical_json(args.readiness)
        summary = {"command": "validate", "task_id": value["task"]["task_id"], "readiness": validated}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
