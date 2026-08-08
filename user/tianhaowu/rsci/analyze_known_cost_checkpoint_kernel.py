#!/usr/bin/env python3
"""Seal and analyze the complete known-cost checkpoint-kernel task set."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import finalize_known_cost_checkpoint_kernel_attempt as finalizer
import materialize_known_cost_checkpoint_kernel_plan as plan_module
import numpy as np
import probe_known_cost_checkpoint_kernel as checkpoint_probe

TERMINAL_PROVENANCE_TYPE = "rsci_known_cost_checkpoint_kernel_terminal_provenance"
PRIMARY_ANALYSIS_TYPE = "rsci_known_cost_checkpoint_kernel_primary_analysis"
REPEAT_DECISION_TYPE = "rsci_known_cost_checkpoint_kernel_repeat_decision"
FINALIZER_SCRIPT_CAPTURE_TYPE = "rsci_known_cost_checkpoint_kernel_finalizer_script_capture"
SELECTED_TAGS = [0, 1]
ADJACENT_PAIRS = ((375, 750), (750, 1500))


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


def load_plan(plan_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = plan_module.validate_plan(plan_path)
    _, plan = plan_module.read_canonical_json(plan_path)
    plan_module.require_control_runtime(
        plan,
        role="result_analyzer",
        running_file=Path(__file__),
    )
    if len(plan.get("tasks", [])) != 13:
        raise ValueError("Checkpoint-kernel analyzer requires the exact 13-task primary plan")
    return plan, identity


def _read_self_hashed(path: Path, artifact_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError(f"Artifact is writable: {resolved}")
    raw, value = plan_module.read_canonical_json(resolved)
    if value.get("schema_version") != 1 or value.get("artifact_type") != artifact_type:
        raise ValueError(f"Artifact type or schema differs: {resolved}")
    payload = dict(value)
    self_hash = payload.pop("payload_without_self_hash_sha256", None)
    if self_hash != canonical_json_sha256(payload):
        raise ValueError(f"Artifact self hash differs: {resolved}")
    identity = checkpoint_probe.file_identity(resolved)
    if hashlib.sha256(raw).hexdigest() != identity["sha256"]:
        raise RuntimeError("Canonical artifact byte hash changed while reading")
    return value, identity


def _write_once(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json_bytes(value)
    lock_path = path.parent / ".analysis.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            if path.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace different artifact: {path}")
            return checkpoint_probe.file_identity(path)
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o444)
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return checkpoint_probe.file_identity(path)


def validate_finalizer_script_capture(
    path: Path,
    submission: dict[str, Any],
    submission_identity: dict[str, Any],
) -> dict[str, Any]:
    value, identity = _read_self_hashed(path, FINALIZER_SCRIPT_CAPTURE_TYPE)
    if value.get("study_id") != plan_module.STUDY_ID or value.get("submission") != submission_identity:
        raise ValueError("Finalizer script capture belongs to another submission")
    attempt_root = Path(str(submission["paths"]["terminal_receipt"])).parent
    if path.expanduser().resolve() != attempt_root / "finalizer_script_capture_receipt.json":
        raise ValueError("Finalizer script capture receipt is outside its attempt directory")
    captured = value.get("captured_batch_script")
    if not isinstance(captured, dict) or checkpoint_probe.file_identity(Path(str(captured.get("path")))) != captured:
        raise ValueError("Finalizer scheduler script capture identity changed")
    captured_path = Path(str(captured["path"]))
    if captured_path != attempt_root / "scheduler_finalizer_batch_script.sbatch":
        raise ValueError("Finalizer scheduler script capture path differs")
    if captured_path.is_symlink() or not stat.S_ISREG(captured_path.lstat().st_mode):
        raise ValueError("Finalizer scheduler script capture is not a regular file")
    if stat.S_IMODE(captured_path.stat().st_mode) & 0o222:
        raise ValueError("Finalizer scheduler script capture is writable")
    if captured["sha256"] != submission["finalizer_batch_script"]["sha256"]:
        raise ValueError("Finalizer scheduler script capture differs from dispatched bytes")
    if value.get("job_id") != submission["finalizer_job_id"]:
        raise ValueError("Finalizer scheduler script capture has another job ID")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or command[:4] != ["scontrol", "write", "batch_script", submission["finalizer_job_id"]]
        or len(command) != 5
    ):
        raise ValueError("Finalizer scheduler script-capture command differs")
    for key in ("stdout", "stderr"):
        output = value.get(key)
        if not isinstance(output, str) or value.get(f"{key}_sha256") != hashlib.sha256(output.encode()).hexdigest():
            raise ValueError(f"Finalizer scheduler script-capture {key} hash differs")
    return identity


def capture_finalizer_script(
    submission: dict[str, Any],
    submission_identity: dict[str, Any],
) -> dict[str, Any]:
    attempt_root = Path(str(submission["paths"]["terminal_receipt"])).parent
    receipt_path = attempt_root / "finalizer_script_capture_receipt.json"
    if receipt_path.is_file():
        return validate_finalizer_script_capture(receipt_path, submission, submission_identity)
    capture_path = attempt_root / "scheduler_finalizer_batch_script.sbatch"
    temporary_dir = Path(tempfile.mkdtemp(dir=attempt_root, prefix=".finalizer-script-capture."))
    temporary_capture = temporary_dir / "batch_script.sbatch"
    command = [
        "scontrol",
        "write",
        "batch_script",
        submission["finalizer_job_id"],
        str(temporary_capture),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=True,
            timeout=60,
        )
        temporary_identity = checkpoint_probe.file_identity(temporary_capture)
        if temporary_identity["sha256"] != submission["finalizer_batch_script"]["sha256"]:
            raise ValueError("Scheduler returned different finalizer batch-script bytes")
        temporary_capture.chmod(0o444)
        if capture_path.exists():
            if checkpoint_probe.file_identity(capture_path)["sha256"] != temporary_identity["sha256"]:
                raise FileExistsError("Existing finalizer scheduler capture differs")
        else:
            os.link(temporary_capture, capture_path)
        captured = checkpoint_probe.file_identity(capture_path)
    finally:
        temporary_capture.unlink(missing_ok=True)
        temporary_dir.rmdir()
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": FINALIZER_SCRIPT_CAPTURE_TYPE,
        "study_id": plan_module.STUDY_ID,
        "submission": submission_identity,
        "job_id": submission["finalizer_job_id"],
        "command": command,
        "stdout": completed.stdout,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "stderr": completed.stderr,
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
        "captured_batch_script": captured,
        "scheduler_mutation": False,
    }
    value["payload_without_self_hash_sha256"] = canonical_json_sha256(value)
    _write_once(receipt_path, value)
    return validate_finalizer_script_capture(receipt_path, submission, submission_identity)


def task_attempt_inventory(
    plan_root: Path,
    task: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    task_id = task["task_id"]
    attempts = []
    task_root = plan_root / "attempts" / task_id
    if not task_root.is_dir():
        raise FileNotFoundError(f"Task {task_id} has no attempt directory")
    for attempt_root in task_root.iterdir():
        if not attempt_root.is_dir() or not attempt_root.name.isdigit():
            raise ValueError(f"Unknown attempt entry under {task_id}: {attempt_root}")
        submission_path = attempt_root / "submission_receipt.json"
        terminal_path = attempt_root / "terminal_receipt.json"
        if not submission_path.is_file() or not terminal_path.is_file():
            raise ValueError(f"Task {task_id} has an unterminated attempt: {attempt_root.name}")
        submission, submission_identity = finalizer.validate_submission(submission_path)
        terminal_identity = finalizer.validate_terminal(terminal_path)
        terminal, _ = finalizer.read_self_hashed(terminal_path, finalizer.TERMINAL_ARTIFACT_TYPE)
        if submission["task_spec_sha256"] != canonical_json_sha256(task):
            raise ValueError(f"Attempt {attempt_root.name} has another task specification")
        attempts.append(
            {
                "ordinal": submission["attempt_ordinal"],
                "submission_value": submission,
                "submission": submission_identity,
                "terminal_value": terminal,
                "terminal": terminal_identity,
            }
        )
    attempts.sort(key=lambda item: item["ordinal"])
    if [item["ordinal"] for item in attempts] != list(range(1, len(attempts) + 1)):
        raise ValueError(f"Task {task_id} attempt ordinals are not contiguous")
    successful_indices = [index for index, item in enumerate(attempts) if item["terminal_value"]["status"] == "succeeded"]
    if successful_indices and successful_indices[0] != len(attempts) - 1:
        raise ValueError(f"Task {task_id} has an attempt after scientific success")
    succeeded = [item for item in attempts if item["terminal_value"]["status"] == "succeeded"]
    if len(succeeded) != 1:
        raise ValueError(f"Task {task_id} has {len(succeeded)} successful terminal attempts, expected one")
    success = succeeded[0]
    failed = [
        {"submission": item["submission"], "terminal": item["terminal"]}
        for item in attempts
        if item["terminal_value"]["status"] == "failed"
    ]
    return success["terminal_value"], success["terminal"], failed


def _validate_finalizer_allocation(
    *,
    plan: dict[str, Any],
    submission: dict[str, Any],
    terminal: dict[str, Any],
    allocation: dict[str, Any],
) -> dict[str, Any]:
    record = allocation["record"]
    scheduler = submission["finalizer_scheduler_contract"]
    for field, expected in (
        ("JobIDRaw", submission["finalizer_job_id"]),
        ("JobName", scheduler["job_name"]),
        ("Account", scheduler["account"]),
        ("QOS", scheduler["qos"]),
        ("Comment", scheduler["comment"]),
        ("State", "COMPLETED"),
        ("ExitCode", "0:0"),
        ("ReqCPUS", str(scheduler["cpus"])),
        ("ReqMem", scheduler["memory"]),
        ("NNodes", str(scheduler["nodes"])),
        ("TimelimitRaw", "3600"),
        ("WorkDir", plan["control_source"]["snapshot_path"]),
    ):
        if record[field] != expected:
            raise ValueError(f"Finalizer allocation {field} differs: {record[field]!r} != {expected!r}")
    allocated_tres = finalizer.parse_tres(record["AllocTRES"])
    if allocated_tres.get("node") != "1" or any(key.startswith("gres/gpu") for key in allocated_tres):
        raise ValueError("Finalizer allocation is not exactly one CPU-only node")
    attempt_root = Path(str(submission["paths"]["terminal_receipt"])).parent
    accounting_log = str(attempt_root / "finalizer_%j.log")
    if record["StdOut"] != accounting_log or record["StdErr"] != accounting_log:
        raise ValueError("Finalizer accounting log path differs")
    finalizer_submit = finalizer.parse_time(record["Submit"])
    gpu_end = finalizer.parse_time(terminal["terminal_allocation"]["record"]["End"])
    finalizer_start = finalizer.parse_time(record["Start"])
    finalizer_end = finalizer.parse_time(record["End"])
    if not finalizer_submit <= finalizer_start <= finalizer_end:
        raise ValueError("Finalizer scheduler timestamps are not ordered")
    if finalizer_start < gpu_end:
        raise ValueError("Finalizer started before the GPU allocation ended")
    if int(record["ElapsedRaw"]) > 3600:
        raise ValueError("Finalizer elapsed time exceeds its allocation contract")
    log_path = Path(str(submission["finalizer_log_path"]))
    if not log_path.is_file():
        raise FileNotFoundError(log_path)
    return {
        "allocation": allocation,
        "allocation_log": checkpoint_probe.file_identity(log_path),
        "gpu_end_before_finalizer_start": True,
        "gpu_end_to_finalizer_start_seconds": (finalizer_start - gpu_end).total_seconds(),
    }


def build_terminal_provenance(plan_path: Path) -> dict[str, Any]:
    plan, plan_identity = load_plan(plan_path)
    plan_root = Path(str(plan_identity["path"])).parent
    attempt_task_dirs = {path.name for path in (plan_root / "attempts").iterdir()} if (plan_root / "attempts").is_dir() else set()
    expected_task_dirs = {task["task_id"] for task in plan["tasks"]}
    if attempt_task_dirs != expected_task_dirs:
        raise ValueError("Attempt task-directory inventory differs from the 13-task plan")
    expected_results = {str((plan_root / task["result_relative_path"]).absolute()) for task in plan["tasks"]}
    observed_paths = list((plan_root / "results").glob("**/kernel.json"))
    if any(path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) for path in observed_paths):
        raise ValueError("Canonical result inventory contains a symlink or non-regular file")
    observed_results = {str(path.absolute()) for path in observed_paths}
    if observed_results != expected_results:
        raise ValueError("Canonical result inventory differs from the exact 13 planned paths")
    records = []
    for task in plan["tasks"]:
        terminal, terminal_identity, failed_attempts = task_attempt_inventory(plan_root, task)
        submission_path = Path(str(terminal["submission"]["path"]))
        submission, submission_identity = finalizer.validate_submission(submission_path)
        allocation = finalizer.terminal_allocation(submission["finalizer_job_id"])
        finalizer_script_capture = capture_finalizer_script(submission, submission_identity)
        finalizer_evidence = _validate_finalizer_allocation(
            plan=plan,
            submission=submission,
            terminal=terminal,
            allocation=allocation,
        )
        records.append(
            {
                "task_id": task["task_id"],
                "task_spec_sha256": canonical_json_sha256(task),
                "submission": submission_identity,
                "terminal": terminal_identity,
                "readiness": submission["readiness"],
                "failed_technical_attempts": failed_attempts,
                "finalizer": finalizer_evidence,
                "finalizer_scheduler_script_capture": finalizer_script_capture,
                "canonical_output": checkpoint_probe.validate(Path(str(submission["paths"]["canonical_output"]))),
            }
        )
    failed_attempt_count = sum(len(record["failed_technical_attempts"]) for record in records)
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": TERMINAL_PROVENANCE_TYPE,
        "study_id": plan_module.STUDY_ID,
        "plan": plan_identity,
        "plan_id": plan["plan_id"],
        "control_source_sha256": plan["control_source"]["control_source_sha256"],
        "tasks": records,
        "implementation": plan["control_source"]["implementations"]["result_analyzer"],
        "scope": {
            "each_primary_task_has_exactly_one_terminal_gpu_success": True,
            "successful_primary_cpu_finalizers_completed_with_exit_zero": 13,
            "technical_attempt_count": 13 + failed_attempt_count,
            "failed_technical_attempt_count": failed_attempt_count,
            "successful_finalizer_scheduler_scripts_recaptured": 13,
            "all_13_canonical_outputs_bound": True,
            "scientific_threshold_evaluated": False,
            "scheduler_mutation": False,
        },
    }
    artifact["payload_without_self_hash_sha256"] = canonical_json_sha256(artifact)
    return artifact


def write_terminal_provenance(plan_path: Path) -> dict[str, Any]:
    plan, identity = load_plan(plan_path)
    path = Path(str(identity["path"])).parent / "terminal_provenance.json"
    value = build_terminal_provenance(plan_path)
    written = _write_once(path, value)
    validate_terminal_provenance(path)
    return written


def _replay_allocation(allocation: dict[str, Any], job_id: str) -> dict[str, str]:
    expected_command = [
        "sacct",
        "-X",
        "-n",
        "-P",
        "-j",
        job_id,
        f"--format={','.join(finalizer.SACCT_FIELDS)}",
    ]
    stdout = allocation.get("stdout")
    if (
        allocation.get("command") != expected_command
        or not isinstance(stdout, str)
        or allocation.get("stdout_sha256") != hashlib.sha256(stdout.encode()).hexdigest()
    ):
        raise ValueError("Finalizer allocation capture is malformed")
    rows = [line.split("|") for line in stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != len(finalizer.SACCT_FIELDS):
        raise ValueError("Finalizer allocation capture is ambiguous")
    record = dict(zip(finalizer.SACCT_FIELDS, rows[0], strict=True))
    record["State"] = finalizer.terminal_state(record["State"])
    if allocation.get("record") != record:
        raise ValueError("Finalizer allocation stdout and record differ")
    return record


def validate_terminal_provenance(path: Path) -> dict[str, Any]:
    artifact, identity = _read_self_hashed(path, TERMINAL_PROVENANCE_TYPE)
    if artifact.get("study_id") != plan_module.STUDY_ID:
        raise ValueError("Terminal provenance belongs to another study")
    expected_top_level = {
        "schema_version",
        "artifact_type",
        "study_id",
        "plan",
        "plan_id",
        "control_source_sha256",
        "tasks",
        "implementation",
        "scope",
        "payload_without_self_hash_sha256",
    }
    if set(artifact) != expected_top_level:
        raise ValueError("Terminal provenance top-level schema differs")
    plan_path = Path(str(artifact["plan"]["path"]))
    plan, plan_identity = load_plan(plan_path)
    if artifact["plan"] != plan_identity or artifact["plan_id"] != plan["plan_id"]:
        raise ValueError("Terminal provenance belongs to another plan")
    plan_root = Path(str(plan_identity["path"])).parent
    if path.expanduser().resolve() != plan_root / "terminal_provenance.json":
        raise ValueError("Terminal provenance is outside its plan root")
    if len(artifact.get("tasks", [])) != 13:
        raise ValueError("Terminal provenance does not cover all 13 tasks")
    by_task = {record.get("task_id"): record for record in artifact["tasks"]}
    if set(by_task) != {task["task_id"] for task in plan["tasks"]}:
        raise ValueError("Terminal provenance task inventory differs from the plan")
    if artifact.get("control_source_sha256") != plan["control_source"]["control_source_sha256"]:
        raise ValueError("Terminal provenance control source differs from the plan")
    if artifact.get("implementation") != plan["control_source"]["implementations"]["result_analyzer"]:
        raise ValueError("Terminal provenance used another analyzer")
    failed_attempt_count = sum(len(record.get("failed_technical_attempts", [])) for record in artifact["tasks"])
    expected_scope = {
        "each_primary_task_has_exactly_one_terminal_gpu_success": True,
        "successful_primary_cpu_finalizers_completed_with_exit_zero": 13,
        "technical_attempt_count": 13 + failed_attempt_count,
        "failed_technical_attempt_count": failed_attempt_count,
        "successful_finalizer_scheduler_scripts_recaptured": 13,
        "all_13_canonical_outputs_bound": True,
        "scientific_threshold_evaluated": False,
        "scheduler_mutation": False,
    }
    if artifact.get("scope") != expected_scope:
        raise ValueError("Terminal provenance scope differs")
    gpu_job_ids = set()
    finalizer_job_ids = set()
    for task in plan["tasks"]:
        record = by_task[task["task_id"]]
        expected_record_fields = {
            "task_id",
            "task_spec_sha256",
            "submission",
            "terminal",
            "readiness",
            "failed_technical_attempts",
            "finalizer",
            "finalizer_scheduler_script_capture",
            "canonical_output",
        }
        if set(record) != expected_record_fields:
            raise ValueError(f"Terminal provenance record schema differs for {task['task_id']}")
        if record.get("task_spec_sha256") != canonical_json_sha256(task):
            raise ValueError(f"Terminal provenance task hash differs for {task['task_id']}")
        current_terminal, current_terminal_identity, current_failures = task_attempt_inventory(plan_root, task)
        if current_terminal_identity != record["terminal"] or current_failures != record["failed_technical_attempts"]:
            raise ValueError(f"Attempt inventory changed for {task['task_id']}")
        terminal_path = Path(str(record["terminal"]["path"]))
        if finalizer.validate_terminal(terminal_path) != record["terminal"]:
            raise ValueError(f"Terminal identity changed for {task['task_id']}")
        terminal, _ = finalizer.read_self_hashed(terminal_path, finalizer.TERMINAL_ARTIFACT_TYPE)
        if current_terminal != terminal:
            raise ValueError(f"Successful terminal value changed for {task['task_id']}")
        submission_path = Path(str(record["submission"]["path"]))
        submission, submission_identity = finalizer.validate_submission(submission_path)
        if submission_identity != record["submission"]:
            raise ValueError(f"Submission identity changed for {task['task_id']}")
        script_capture_path = Path(str(record["finalizer_scheduler_script_capture"]["path"]))
        if (
            validate_finalizer_script_capture(script_capture_path, submission, submission_identity)
            != record["finalizer_scheduler_script_capture"]
        ):
            raise ValueError(f"Finalizer scheduler script capture changed for {task['task_id']}")
        if terminal.get("submission") != record["submission"]:
            raise ValueError(f"Terminal and submission are mispaired for {task['task_id']}")
        if (
            submission.get("task_id") != task["task_id"]
            or submission.get("task_spec_sha256") != canonical_json_sha256(task)
            or submission.get("readiness") != record["readiness"]
            or terminal.get("task_id") != task["task_id"]
            or terminal.get("task_spec_sha256") != canonical_json_sha256(task)
        ):
            raise ValueError(f"Terminal chain belongs to another task for {task['task_id']}")
        if submission["gpu_job_id"] in gpu_job_ids or submission["finalizer_job_id"] in finalizer_job_ids:
            raise ValueError("Terminal provenance reuses a scheduler job ID")
        gpu_job_ids.add(submission["gpu_job_id"])
        finalizer_job_ids.add(submission["finalizer_job_id"])
        if record.get("readiness") != submission["readiness"]:
            raise ValueError(f"Readiness identity changed for {task['task_id']}")
        failed_attempts = record.get("failed_technical_attempts")
        if not isinstance(failed_attempts, list):
            raise ValueError(f"Failed-attempt inventory is absent for {task['task_id']}")
        for failed in failed_attempts:
            failed_terminal_path = Path(str(failed["terminal"]["path"]))
            if finalizer.validate_terminal(failed_terminal_path) != failed["terminal"]:
                raise ValueError(f"Failed terminal identity changed for {task['task_id']}")
            failed_terminal, _ = finalizer.read_self_hashed(
                failed_terminal_path,
                finalizer.TERMINAL_ARTIFACT_TYPE,
            )
            if failed_terminal["status"] != "failed" or failed_terminal["submission"] != failed["submission"]:
                raise ValueError(f"Failed-attempt chain differs for {task['task_id']}")
        finalizer_evidence = record["finalizer"]
        replayed = _replay_allocation(finalizer_evidence["allocation"], submission["finalizer_job_id"])
        if replayed["State"] != "COMPLETED" or finalizer.parse_exit_code(replayed["ExitCode"]) != (0, 0):
            raise ValueError(f"Finalizer did not succeed for {task['task_id']}")
        expected_finalizer_evidence = _validate_finalizer_allocation(
            plan=plan,
            submission=submission,
            terminal=terminal,
            allocation=finalizer_evidence["allocation"],
        )
        if expected_finalizer_evidence != finalizer_evidence:
            raise ValueError(f"Finalizer evidence differs for {task['task_id']}")
        if checkpoint_probe.file_identity(Path(finalizer_evidence["allocation_log"]["path"])) != finalizer_evidence[
            "allocation_log"
        ]:
            raise ValueError(f"Finalizer log identity changed for {task['task_id']}")
        canonical = checkpoint_probe.validate(Path(str(submission["paths"]["canonical_output"])))
        candidate = terminal["publication"]["candidate"]
        if (
            canonical != record["canonical_output"]
            or not isinstance(candidate, dict)
            or (candidate["size_bytes"], candidate["sha256"]) != (canonical["size_bytes"], canonical["sha256"])
        ):
            raise ValueError(f"Canonical output identity changed for {task['task_id']}")
    if gpu_job_ids & finalizer_job_ids:
        raise ValueError("Terminal provenance aliases a GPU and finalizer scheduler job")
    return identity


def metric_record(path: Path, expected_identity: dict[str, Any]) -> dict[str, Any]:
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Kernel result is not a regular non-symlink file: {path}")
    validated_identity = checkpoint_probe.validate(path)
    if validated_identity != expected_identity:
        raise ValueError(f"Kernel result identity differs from terminal provenance: {path}")
    before = checkpoint_probe.file_identity(path)
    _, analysis = checkpoint_probe.read_canonical_json(path)
    after = checkpoint_probe.file_identity(path)
    if before != expected_identity or after != expected_identity:
        raise ValueError(f"Kernel result changed while reading: {path}")
    analytic = np.asarray(analysis["analytic_cross_gradient_kernel"], dtype=np.float64)
    responses = analysis["responses"]
    if analytic.shape != (6, 6) or len(responses) != 6:
        raise ValueError(f"Kernel result does not contain six tags: {path}")
    norms = np.asarray([response["gradient_norm"] for response in responses], dtype=np.float64)
    if norms.shape != (6,) or not np.all(np.isfinite(norms)) or np.any(norms <= 0.0):
        raise ValueError(f"Kernel result has invalid gradient norms: {path}")
    gram = analytic * np.square(norms)[None, :]
    if not np.all(np.isfinite(gram)):
        raise ValueError(f"Kernel result has a non-finite Gram matrix: {path}")
    symmetry_error = float(np.max(np.abs(gram - gram.T)))
    if symmetry_error > checkpoint_probe.SYMMETRY_ATOL:
        raise ValueError(f"Kernel result has an asymmetric Gram matrix: {path}")
    gram = (gram + gram.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(gram)
    if eigenvalues[-1] <= 0.0 or eigenvalues[0] < -checkpoint_probe.SYMMETRY_ATOL * max(eigenvalues[-1], 1.0):
        raise ValueError(f"Kernel result has an invalid Gram spectrum: {path}")
    eigenvalues = np.maximum(eigenvalues, 0.0)
    top = eigenvectors[:, -1]
    if float(np.sum(top)) < 0.0:
        top = -top
    delta = np.asarray([2.0, 2.0, -1.0, -1.0, -1.0, -1.0])
    contrast = np.asarray([0.5, 0.5, -0.25, -0.25, -0.25, -0.25])
    uniform = np.ones(6)
    numerator = float(contrast @ gram @ delta)
    denominator = float(uniform @ gram @ uniform / 6.0)
    if denominator <= 0.0:
        raise ValueError(f"Kernel result has a non-positive common denominator: {path}")
    geometry = analysis["geometry"]
    blocks = [block for block in geometry["blocks"] if block["selected_tags"] == SELECTED_TAGS]
    finite = [item for item in analysis["combined_finite_responses"] if item["selected_tags"] == SELECTED_TAGS]
    if len(blocks) != 1 or len(finite) != 1:
        raise ValueError(f"Kernel result lacks the unique selected-tag block: {path}")
    block = blocks[0]
    response = finite[0]
    if not (
        response.get("parameters_restored_bit_exactly") is True
        and response.get("baseline_objectives_recovered") is True
    ):
        raise ValueError(f"Kernel result does not prove combined-step restoration: {path}")
    objective_deltas = np.asarray(response["objective_deltas"], dtype=np.float64)
    step_size = float(analysis["runtime"]["step_size"])
    if objective_deltas.shape != (6,) or step_size <= 0.0:
        raise ValueError(f"Kernel result has an invalid combined finite response: {path}")
    finite_slope = float(contrast @ objective_deltas / step_size)
    stored_checks = {
        "R": float(block["localization_response_ratio"]),
        "N": float(block["selected_minus_unselected_response_per_unit_p"]),
        "D": float(geometry["uniform_common_response_denominator"]),
        "finite": float(response["step_size_normalized_localization_slope"]),
        "epsilon": float(geometry["lambda_second_to_lambda_top"]),
        "energy": float(geometry["rank_one_frobenius_energy"]),
    }
    values = {
        "R": numerator / denominator,
        "N": numerator,
        "D": denominator,
        "finite_localization_slope": finite_slope,
        "lambda_second_to_lambda_top": float(eigenvalues[-2] / eigenvalues[-1]),
        "rank_one_frobenius_energy": float(eigenvalues[-1] ** 2 / np.dot(eigenvalues, eigenvalues)),
        "top_eigenvector": top.tolist(),
        "top_eigenvalue": float(eigenvalues[-1]),
        "top_eigengap": float(eigenvalues[-1] - eigenvalues[-2]),
        "top_eigenvalue_simple": bool(
            eigenvalues[-1] - eigenvalues[-2] > checkpoint_probe.SYMMETRY_ATOL * max(eigenvalues[-1], 1.0)
        ),
        "gram_symmetry_max_abs_error": symmetry_error,
    }
    scalar_values = [value for value in values.values() if isinstance(value, float)]
    if not all(math.isfinite(value) for value in scalar_values):
        raise ValueError(f"Kernel result contains a non-finite scalar: {path}")
    if not all(math.isfinite(value) for value in values["top_eigenvector"]):
        raise ValueError(f"Kernel result contains a non-finite eigenvector: {path}")
    recomputed_checks = {
        "R": values["R"],
        "N": values["N"],
        "D": values["D"],
        "finite": values["finite_localization_slope"],
        "epsilon": values["lambda_second_to_lambda_top"],
        "energy": values["rank_one_frobenius_energy"],
    }
    for name, stored in stored_checks.items():
        if not math.isclose(recomputed_checks[name], stored, abs_tol=1e-10, rel_tol=1e-10):
            raise ValueError(f"Recomputed kernel statistic {name} differs from the stored geometry: {path}")
    if not np.allclose(top, np.asarray(geometry["top_eigenvector_positive_sum"]), atol=1e-10, rtol=1e-10):
        raise ValueError(f"Recomputed top eigenvector differs from stored geometry: {path}")
    stored_eigenvalues = [float(value) for value in geometry["eigenvalues_ascending"]]
    stored_top = [float(value) for value in geometry["top_eigenvector_positive_sum"]]
    values.update(
        {
            "R": stored_checks["R"],
            "N": stored_checks["N"],
            "D": stored_checks["D"],
            "finite_localization_slope": stored_checks["finite"],
            "lambda_second_to_lambda_top": stored_checks["epsilon"],
            "rank_one_frobenius_energy": stored_checks["energy"],
            "top_eigenvector": stored_top,
            "top_eigenvalue": stored_eigenvalues[-1],
            "top_eigengap": stored_eigenvalues[-1] - stored_eigenvalues[-2],
            "top_eigenvalue_simple": bool(
                stored_eigenvalues[-1] - stored_eigenvalues[-2]
                > checkpoint_probe.SYMMETRY_ATOL * max(stored_eigenvalues[-1], 1.0)
            ),
            "gram_symmetry_max_abs_error": float(geometry["gram_symmetry_max_abs_error"]),
        }
    )
    return values


def clock_thresholds(reference: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    if reference["R"] == 0.0 or reference["N"] == 0.0 or reference["D"] <= 0.0:
        raise ValueError("Matched BF16 reference is zero or non-positive and cannot define the threshold")
    sign = 1 if values["N"] > 0.0 else -1 if values["N"] < 0.0 else 0
    finite_sign = (
        1
        if values["finite_localization_slope"] > 0.0
        else -1
        if values["finite_localization_slope"] < 0.0
        else 0
    )
    thresholds = {
        "abs_R_over_abs_R0": abs(values["R"]) / abs(reference["R"]),
        "abs_N_over_abs_N0": abs(values["N"]) / abs(reference["N"]),
        "D_over_D0": values["D"] / reference["D"],
        "R_margin_over_threshold": abs(values["R"]) / (10.0 * abs(reference["R"])),
        "N_margin_over_threshold": abs(values["N"]) / (10.0 * abs(reference["N"])),
        "D_margin_over_floor": values["D"] / (0.5 * reference["D"]),
        "R_tenfold": abs(values["R"]) >= 10.0 * abs(reference["R"]),
        "N_tenfold": abs(values["N"]) >= 10.0 * abs(reference["N"]),
        "D_retained": values["D"] >= 0.5 * reference["D"],
        "N_sign": sign,
        "finite_slope_sign": finite_sign,
        "finite_slope_matches_N": sign != 0 and finite_sign == sign,
    }
    thresholds["single_clock_pass"] = (
        thresholds["R_tenfold"]
        and thresholds["N_tenfold"]
        and thresholds["D_retained"]
        and thresholds["finite_slope_matches_N"]
    )
    return thresholds


def pair_qualifies(reference: dict[str, Any], pair: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [clock_thresholds(reference, values) for values in pair]
    same_nonzero_sign = rows[0]["N_sign"] != 0 and rows[0]["N_sign"] == rows[1]["N_sign"]
    qualifies = same_nonzero_sign and all(
        row["single_clock_pass"]
        for row in rows
    )
    return {"qualifies": qualifies, "same_nonzero_N_sign": same_nonzero_sign, "clocks": rows}


def repeat_pre_execution_observation(
    plan_root: Path,
    observed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    paths = [
        plan_root / "conditional_repeats",
        plan_root / "repeat_plan.json",
        plan_root / "repeat_authority.json",
        plan_root / "repeat_terminal_provenance.json",
        plan_root / "repeat_confirmation.json",
    ]
    expected = {"paths": [str(path) for path in paths], "all_repeat_namespaces_absent": True}
    if observed is not None:
        if observed != expected:
            raise ValueError("Repeat pre-execution observation differs from the fixed namespace")
        return expected
    existing = [str(path) for path in paths if path.exists()]
    if existing:
        raise FileExistsError(f"Conditional-repeat artifact predates the primary decision: {existing[0]}")
    return expected


def build_primary_analysis(
    plan_path: Path,
    provenance_path: Path,
    *,
    pre_repeat_observation: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan, plan_identity = load_plan(plan_path)
    provenance_identity = validate_terminal_provenance(provenance_path)
    provenance, _ = _read_self_hashed(provenance_path, TERMINAL_PROVENANCE_TYPE)
    if provenance["plan"] != plan_identity:
        raise ValueError("Terminal provenance belongs to another checkpoint-kernel plan")
    plan_root = Path(str(plan_identity["path"])).parent
    pre_repeat = repeat_pre_execution_observation(plan_root, pre_repeat_observation)
    input_before = {
        "terminal_provenance": provenance_identity,
        "task_evidence_sha256": canonical_json_sha256(provenance["tasks"]),
    }
    by_task = {task["task_id"]: task for task in plan["tasks"]}
    evidence_by_task = {record["task_id"]: record for record in provenance["tasks"]}
    reference_task = by_task["reference-step-0000"]
    reference = metric_record(
        plan_root / reference_task["result_relative_path"],
        evidence_by_task["reference-step-0000"]["canonical_output"],
    )
    reference_vector = reference["top_eigenvector"]
    arms: dict[str, Any] = {}
    repeat_tasks = []
    for condition in plan_module.EXPECTED_ARMS.values():
        clocks = {}
        for step in plan_module.CHECKPOINT_STEPS:
            task = by_task[f"{condition}-step-{step:04d}"]
            values = metric_record(
                plan_root / task["result_relative_path"],
                evidence_by_task[task["task_id"]]["canonical_output"],
            )
            dot = sum(left * right for left, right in zip(reference_vector, values["top_eigenvector"], strict=True))
            angle_interpretable = reference["top_eigenvalue_simple"] and values["top_eigenvalue_simple"]
            angle = math.acos(min(1.0, max(0.0, abs(dot)))) if angle_interpretable else None
            values["top_mode_angle_radians"] = angle
            values["top_mode_angle_degrees"] = math.degrees(angle) if angle is not None else None
            values["top_mode_angle_interpretable"] = angle_interpretable
            values["thresholds"] = clock_thresholds(reference, values)
            clocks[step] = values
        pair_results = []
        selected_pair = None
        for earlier, later in ADJACENT_PAIRS:
            result = pair_qualifies(reference, [clocks[earlier], clocks[later]])
            pair_results.append({"steps": [earlier, later], **result})
            if selected_pair is None and result["qualifies"]:
                selected_pair = [earlier, later]
        if selected_pair is not None:
            trigger = selected_pair[1]
            for step in selected_pair:
                repeat_tasks.append(
                    {
                        "condition": condition,
                        "checkpoint_step": step,
                        "trigger_step": trigger,
                        "result_relative_path": (
                            f"conditional_repeats/{condition}/trigger_{trigger}/step_{step}/kernel.json"
                        ),
                    }
                )
        arms[condition] = {
            "clocks": {str(step): clocks[step] for step in plan_module.CHECKPOINT_STEPS},
            "adjacent_pair_tests_in_fixed_order": pair_results,
            "first_qualifying_pair": selected_pair,
            "primary_status": (
                "primary_pair_qualifies_pending_fresh_repeats"
                if selected_pair is not None
                else "no_primary_tenfold_pair"
            ),
            "fresh_scientific_repeats_required": selected_pair is not None,
        }
    provenance_identity_after = validate_terminal_provenance(provenance_path)
    provenance_after, _ = _read_self_hashed(provenance_path, TERMINAL_PROVENANCE_TYPE)
    input_after = {
        "terminal_provenance": provenance_identity_after,
        "task_evidence_sha256": canonical_json_sha256(provenance_after["tasks"]),
    }
    if input_after != input_before:
        raise ValueError("Checkpoint-kernel scientific inputs changed during analysis")
    qualifying_conditions = [
        condition for condition, values in arms.items() if values["first_qualifying_pair"] is not None
    ]
    analysis: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": PRIMARY_ANALYSIS_TYPE,
        "study_id": plan_module.STUDY_ID,
        "plan": plan_identity,
        "terminal_provenance": provenance_identity,
        "reference": reference,
        "arms": arms,
        "summary": {
            "qualifying_arm_count": len(qualifying_conditions),
            "qualifying_conditions": qualifying_conditions,
            "repeat_task_count": len(repeat_tasks),
        },
        "preregistered_rule": plan["analysis_rule"],
        "implementation": plan["control_source"]["implementations"]["result_analyzer"],
        "claim_scope": {
            "all_13_primary_results_analyzed": True,
            "canonical_files_alone_accepted": False,
            "fixed_pair_localization_threshold_evaluated": True,
            "conditional_repeats_completed": False,
            "reproducible_tenfold_amplification_identified": False,
            "practical_effect_calibrated": False,
            "causal_training_effect_identified": False,
            "phase_transition_identified": False,
            "hysteresis_identified": False,
            "smoke_promotion_changed": False,
        },
        "input_toctou": {"before": input_before, "after": input_after, "identical": True},
        "repeat_pre_execution": pre_repeat,
    }
    analysis["payload_without_self_hash_sha256"] = canonical_json_sha256(analysis)
    decision: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": REPEAT_DECISION_TYPE,
        "study_id": plan_module.STUDY_ID,
        "plan": plan_identity,
        "terminal_provenance": provenance_identity,
        "selected_pairs": {
            condition: arms[condition]["first_qualifying_pair"] for condition in plan_module.EXPECTED_ARMS.values()
        },
        "repeat_tasks": repeat_tasks,
        "repeat_task_count": len(repeat_tasks),
        "max_repeat_task_count": 8,
        "selection_rule": "first qualifying adjacent pair in [375,750], [750,1500] order per arm",
        "can_change_smoke_promotion": False,
        "implementation": plan["control_source"]["implementations"]["result_analyzer"],
    }
    decision["payload_without_self_hash_sha256"] = canonical_json_sha256(decision)
    return analysis, decision


def write_primary_analysis(plan_path: Path, provenance_path: Path) -> dict[str, Any]:
    _, plan_identity = load_plan(plan_path)
    plan_root = Path(str(plan_identity["path"])).parent
    analysis, decision = build_primary_analysis(plan_path, provenance_path)
    analysis_path = plan_root / "analysis" / "primary_summary.json"
    analysis_identity = _write_once(analysis_path, analysis)
    validate_primary_analysis(analysis_path)
    decision["primary_analysis"] = analysis_identity
    decision["payload_without_self_hash_sha256"] = canonical_json_sha256(
        {key: value for key, value in decision.items() if key != "payload_without_self_hash_sha256"}
    )
    decision_identity = _write_once(plan_root / "repeat_decision.json", decision)
    validate_repeat_decision(plan_root / "repeat_decision.json")
    return {"primary_analysis": analysis_identity, "repeat_decision": decision_identity}


def validate_primary_analysis(path: Path) -> dict[str, Any]:
    observed, identity = _read_self_hashed(path, PRIMARY_ANALYSIS_TYPE)
    plan_path = Path(str(observed["plan"]["path"]))
    provenance_path = Path(str(observed["terminal_provenance"]["path"]))
    expected, _ = build_primary_analysis(
        plan_path,
        provenance_path,
        pre_repeat_observation=observed["repeat_pre_execution"],
    )
    if canonical_json_bytes(observed) != canonical_json_bytes(expected):
        raise ValueError("Primary checkpoint-kernel analysis differs from deterministic replay")
    expected_path = plan_path.parent / "analysis" / "primary_summary.json"
    if path.expanduser().resolve() != expected_path:
        raise ValueError(f"Primary checkpoint-kernel analysis must be {expected_path}")
    return identity


def validate_repeat_decision(path: Path) -> dict[str, Any]:
    observed, identity = _read_self_hashed(path, REPEAT_DECISION_TYPE)
    plan_path = Path(str(observed["plan"]["path"]))
    provenance_path = Path(str(observed["terminal_provenance"]["path"]))
    primary_path = Path(str(observed["primary_analysis"]["path"]))
    primary_identity = validate_primary_analysis(primary_path)
    primary, _ = _read_self_hashed(primary_path, PRIMARY_ANALYSIS_TYPE)
    _, expected = build_primary_analysis(
        plan_path,
        provenance_path,
        pre_repeat_observation=primary["repeat_pre_execution"],
    )
    expected["primary_analysis"] = primary_identity
    expected["payload_without_self_hash_sha256"] = canonical_json_sha256(
        {key: value for key, value in expected.items() if key != "payload_without_self_hash_sha256"}
    )
    if canonical_json_bytes(observed) != canonical_json_bytes(expected):
        raise ValueError("Checkpoint-kernel repeat decision differs from deterministic replay")
    if path.expanduser().resolve() != plan_path.parent / "repeat_decision.json":
        raise ValueError("Checkpoint-kernel repeat decision is outside its plan root")
    return identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal = subparsers.add_parser("materialize-terminals")
    seal.add_argument("--plan", type=Path, required=True)
    validate = subparsers.add_parser("validate-terminals")
    validate.add_argument("--terminal-provenance", type=Path, required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--plan", type=Path, required=True)
    analyze.add_argument("--terminal-provenance", type=Path, required=True)
    validate_analysis = subparsers.add_parser("validate-analysis")
    validate_analysis.add_argument("--analysis", type=Path, required=True)
    validate_repeat = subparsers.add_parser("validate-repeat-decision")
    validate_repeat.add_argument("--repeat-decision", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize-terminals":
        result = {"terminal_provenance": write_terminal_provenance(args.plan), "scheduler_mutation": False}
    elif args.command == "validate-terminals":
        result = {
            "terminal_provenance": validate_terminal_provenance(args.terminal_provenance),
            "scheduler_mutation": False,
        }
    elif args.command == "analyze":
        result = {
            **write_primary_analysis(args.plan, args.terminal_provenance),
            "scheduler_mutation": False,
        }
    elif args.command == "validate-analysis":
        result = {"primary_analysis": validate_primary_analysis(args.analysis), "scheduler_mutation": False}
    else:
        result = {
            "repeat_decision": validate_repeat_decision(args.repeat_decision),
            "scheduler_mutation": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
