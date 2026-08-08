#!/usr/bin/env python3
"""Finalize one checkpoint-kernel GPU attempt and publish only proven success."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import materialize_known_cost_checkpoint_kernel_plan as plan_module
import materialize_known_cost_checkpoint_kernel_readiness as readiness_module
import probe_known_cost_checkpoint_kernel as checkpoint_probe

SCHEMA_VERSION = 1
SUBMISSION_ARTIFACT_TYPE = "rsci_known_cost_checkpoint_kernel_submission_receipt"
TERMINAL_ARTIFACT_TYPE = "rsci_known_cost_checkpoint_kernel_terminal_receipt"
TERMINAL_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
}
SACCT_FIELDS = (
    "JobIDRaw",
    "JobName",
    "Account",
    "QOS",
    "State",
    "ExitCode",
    "ElapsedRaw",
    "Start",
    "End",
    "NodeList",
    "AllocTRES",
    "Submit",
)


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


def read_self_hashed(path: Path, artifact_type: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError(f"Artifact is writable: {resolved}")
    raw, value = plan_module.read_canonical_json(resolved)
    if value.get("schema_version") != SCHEMA_VERSION or value.get("artifact_type") != artifact_type:
        raise ValueError(f"Artifact type or schema differs: {resolved}")
    payload = dict(value)
    self_hash = payload.pop("payload_without_self_hash_sha256", None)
    if self_hash != canonical_json_sha256(payload):
        raise ValueError(f"Artifact self hash differs: {resolved}")
    return value, {**checkpoint_probe.file_identity(resolved), "canonical_bytes_sha256": hashlib.sha256(raw).hexdigest()}


def terminal_state(value: str) -> str:
    normalized = value.split("+", 1)[0].strip().upper()
    if normalized not in TERMINAL_STATES:
        raise ValueError(f"SLURM state is not terminal: {value!r}")
    return normalized


def terminal_allocation(job_id: str) -> dict[str, Any]:
    command = [
        "sacct",
        "-X",
        "-n",
        "-P",
        "-j",
        job_id,
        f"--format={','.join(SACCT_FIELDS)}",
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=True, timeout=60)
    rows = [line.split("|") for line in completed.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != len(SACCT_FIELDS):
        raise ValueError(f"sacct returned {len(rows)} ambiguous rows for job {job_id}")
    record = dict(zip(SACCT_FIELDS, rows[0], strict=True))
    if record["JobIDRaw"] != job_id:
        raise ValueError("sacct returned another job ID")
    record["State"] = terminal_state(record["State"])
    return {
        "command": command,
        "stdout": completed.stdout,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "record": record,
    }


def parse_exit_code(value: str) -> tuple[int, int]:
    pieces = value.split(":")
    if len(pieces) != 2 or any(not piece.isdigit() for piece in pieces):
        raise ValueError(f"Invalid SLURM ExitCode: {value!r}")
    return int(pieces[0]), int(pieces[1])


def parse_time(value: str) -> datetime:
    if value in ("", "Unknown", "None"):
        raise ValueError(f"Invalid scheduler timestamp: {value!r}")
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def validate_submission(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    submission, identity = read_self_hashed(path, SUBMISSION_ARTIFACT_TYPE)
    plan_path = Path(str(submission.get("plan", {}).get("path"))).expanduser().resolve()
    readiness_path = Path(str(submission.get("readiness", {}).get("path"))).expanduser().resolve()
    if plan_module.validate_plan(plan_path) != submission.get("plan"):
        raise ValueError("Submission receipt plan identity changed")
    if readiness_module.validate_readiness(readiness_path) != submission.get("readiness"):
        raise ValueError("Submission receipt readiness identity changed")
    _, readiness = plan_module.read_canonical_json(readiness_path)
    task_id = str(submission.get("task_id"))
    if readiness.get("task", {}).get("task_id") != task_id:
        raise ValueError("Submission receipt task differs from readiness")
    attempt_id = str(submission.get("attempt_id"))
    if attempt_id != str(submission.get("gpu_job_id")) or not attempt_id.isdigit() or int(attempt_id) < 1:
        raise ValueError("Submission receipt attempt ID differs from its GPU job ID")
    plan_root = plan_path.parent
    attempt_root = plan_root / "attempts" / task_id / attempt_id
    expected_paths = {
        "candidate": str(attempt_root / "candidate.json"),
        "runner_summary": str(attempt_root / "runner_summary.json"),
        "submitted_batch_script": str(attempt_root / "submitted_batch_script.sbatch"),
        "terminal_receipt": str(attempt_root / "terminal_receipt.json"),
        "canonical_output": readiness["paths"]["canonical_output"],
    }
    paths = submission.get("paths")
    if paths != expected_paths:
        raise ValueError("Submission receipt paths differ from the plan namespace")
    script = submission.get("gpu_batch_script")
    if not isinstance(script, dict) or checkpoint_probe.file_identity(Path(str(script.get("path")))) != script:
        raise ValueError("Submission GPU batch-script identity changed")
    scheduler = submission.get("scheduler_contract")
    expected_scheduler = {
        "job_name": f"rsci-kc-kernel-{task_id}"[:128],
        "account": "ram",
        "qos": "h100_dev",
        "nodes": 1,
        "gpus": 1,
        "cpus": 16,
        "memory": "128G",
        "time_limit": "00:45:00",
        "comment": f"rsci-kc-kernel-{submission['task_spec_sha256'][:24]}",
    }
    if scheduler != expected_scheduler:
        raise ValueError("Submission scheduler contract differs")
    return submission, identity


def _artifact_mtime(path: Path) -> dict[str, Any]:
    stat_result = path.stat()
    return {
        "mtime_ns": stat_result.st_mtime_ns,
        "mtime_utc": datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat(),
    }


def build_terminal_receipt(submission_path: Path) -> dict[str, Any]:
    submission, submission_identity = validate_submission(submission_path)
    allocation = terminal_allocation(str(submission["gpu_job_id"]))
    record = allocation["record"]
    scheduler = submission["scheduler_contract"]
    for field, expected in (
        ("JobName", scheduler["job_name"]),
        ("Account", scheduler["account"]),
        ("QOS", scheduler["qos"]),
    ):
        if record[field] != expected:
            raise ValueError(f"Terminal allocation {field} differs: {record[field]!r} != {expected!r}")
    if "gres/gpu=1" not in record["AllocTRES"] or "node=1" not in record["AllocTRES"]:
        raise ValueError("Terminal allocation does not prove one GPU and one node")
    exit_code = parse_exit_code(record["ExitCode"])
    succeeded = record["State"] == "COMPLETED" and exit_code == (0, 0)

    paths = {key: Path(value) for key, value in submission["paths"].items()}
    script_capture = (
        checkpoint_probe.file_identity(paths["submitted_batch_script"])
        if paths["submitted_batch_script"].is_file()
        else None
    )
    if succeeded and (
        script_capture is None
        or script_capture["size_bytes"] < 1
        or script_capture["sha256"] != submission["gpu_batch_script"]["sha256"]
    ):
        raise ValueError("Successful allocation lacks the exact in-allocation submitted-script capture")
    if script_capture is not None and script_capture["sha256"] != submission["gpu_batch_script"]["sha256"]:
        raise ValueError("In-allocation submitted-script capture differs from the dispatched script")
    log_path = Path(str(submission["allocation_log_path"]))
    allocation_log = checkpoint_probe.file_identity(log_path)
    evidence: dict[str, Any] = {
        "submitted_batch_script": script_capture,
        "allocation_log": allocation_log,
    }

    candidate = None
    runner_summary = None
    if paths["candidate"].exists():
        candidate = checkpoint_probe.validate(paths["candidate"])
    if paths["runner_summary"].exists():
        runner_summary, runner_summary_identity = read_self_hashed(
            paths["runner_summary"],
            "rsci_known_cost_checkpoint_kernel_runner_summary",
        )
        evidence["runner_summary"] = runner_summary_identity
    if succeeded:
        if candidate is None or runner_summary is None:
            raise ValueError("Successful allocation lacks candidate or runner summary")
        if runner_summary.get("candidate") != candidate or runner_summary.get("already_complete") is not False:
            raise ValueError("Runner summary does not prove a fresh candidate")
        binding = runner_summary.get("execution_binding")
        if binding is not None:
            raise ValueError("Runner summary unexpectedly duplicates candidate execution binding")
        _, candidate_payload = checkpoint_probe.read_canonical_json(paths["candidate"])
        binding = candidate_payload.get("execution_binding")
        if not isinstance(binding, dict):
            raise ValueError("Candidate lacks a plan execution binding")
        if (
            binding.get("attempt_id") != submission["attempt_id"]
            or binding.get("task_id") != submission["task_id"]
            or binding.get("plan") != submission["plan"]
            or binding.get("readiness") != submission["readiness"]
        ):
            raise ValueError("Candidate execution binding differs from submission")
        start = parse_time(record["Start"])
        end = parse_time(record["End"])
        candidate_mtime = datetime.fromtimestamp(paths["candidate"].stat().st_mtime, tz=UTC)
        if not start <= candidate_mtime <= end:
            raise ValueError("Candidate modification time is outside the GPU allocation")
        evidence["candidate"] = candidate
        evidence["candidate_time"] = _artifact_mtime(paths["candidate"])

    readiness_module.validate_readiness(Path(str(submission["readiness"]["path"])))
    terminal: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": TERMINAL_ARTIFACT_TYPE,
        "study_id": plan_module.STUDY_ID,
        "status": "succeeded" if succeeded else "failed",
        "submission": submission_identity,
        "plan": submission["plan"],
        "readiness": submission["readiness"],
        "task_id": submission["task_id"],
        "task_spec_sha256": submission["task_spec_sha256"],
        "attempt_id": submission["attempt_id"],
        "gpu_job_id": submission["gpu_job_id"],
        "terminal_allocation": allocation,
        "scheduler_contract": scheduler,
        "evidence": evidence,
        "paths": submission["paths"],
        "publication": {
            "eligible": succeeded,
            "canonical_output": submission["paths"]["canonical_output"],
            "candidate": candidate,
            "method": "hard_link_after_terminal_validation" if succeeded else None,
        },
        "implementation": checkpoint_probe.source_identity(Path(__file__)),
        "scope": {
            "proves_terminal_allocation": True,
            "proves_submitted_script_capture": script_capture is not None,
            "proves_candidate_created_during_successful_allocation": succeeded,
            "proves_scientific_repeat": False,
            "proves_causal_training_effect": False,
        },
    }
    terminal["payload_without_self_hash_sha256"] = canonical_json_sha256(terminal)
    return terminal


def _write_read_only(path: Path, content: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def publish_terminal(terminal: dict[str, Any]) -> dict[str, Any]:
    paths = {key: Path(value) for key, value in terminal["paths"].items()}
    terminal_path = paths["terminal_receipt"]
    content = canonical_json_bytes(terminal)
    plan_root = Path(str(terminal["plan"]["path"])).parent
    lock_path = plan_root / ".terminalize.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if terminal["status"] == "succeeded":
            canonical = paths["canonical_output"]
            candidate = paths["candidate"]
            canonical.parent.mkdir(parents=True, exist_ok=True)
            if canonical.exists():
                if checkpoint_probe.file_identity(canonical)["sha256"] != checkpoint_probe.file_identity(candidate)[
                    "sha256"
                ]:
                    raise FileExistsError("Canonical result belongs to another attempt")
            else:
                os.link(candidate, canonical)
        if terminal_path.exists():
            if terminal_path.read_bytes() != content:
                raise FileExistsError("Terminal receipt differs from the existing attempt receipt")
        else:
            _write_read_only(terminal_path, content)
    return {
        "terminal_receipt": checkpoint_probe.file_identity(terminal_path),
        "canonical_output": (
            checkpoint_probe.file_identity(paths["canonical_output"])
            if terminal["status"] == "succeeded"
            else None
        ),
    }


def validate_terminal(path: Path) -> dict[str, Any]:
    terminal, identity = read_self_hashed(path, TERMINAL_ARTIFACT_TYPE)
    submission_path = Path(str(terminal["submission"]["path"]))
    submission, submission_identity = validate_submission(submission_path)
    if terminal["submission"] != submission_identity:
        raise ValueError("Terminal receipt submission identity changed")
    if terminal["paths"] != submission["paths"] or terminal["attempt_id"] != submission["attempt_id"]:
        raise ValueError("Terminal receipt path or attempt differs from submission")
    paths = {key: Path(value) for key, value in terminal["paths"].items()}
    if path.expanduser().resolve() != paths["terminal_receipt"]:
        raise ValueError("Terminal receipt is not at its attempt-local path")
    if terminal["status"] == "succeeded":
        candidate = checkpoint_probe.validate(paths["candidate"])
        canonical = checkpoint_probe.validate(paths["canonical_output"])
        if candidate["sha256"] != canonical["sha256"] or paths["candidate"].stat().st_ino != paths[
            "canonical_output"
        ].stat().st_ino:
            raise ValueError("Canonical result is not the hard-linked attempt candidate")
        if terminal["publication"]["candidate"] != candidate:
            raise ValueError("Terminal publication candidate identity changed")
    elif paths["canonical_output"].exists():
        raise ValueError("Failed attempt has a canonical output")
    return identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--submission-receipt", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--terminal-receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "finalize":
        terminal = build_terminal_receipt(args.submission_receipt)
        published = publish_terminal(terminal)
        validated = validate_terminal(Path(str(published["terminal_receipt"]["path"])))
        summary = {
            "command": "finalize",
            "status": terminal["status"],
            "terminal_receipt": validated,
            "canonical_output": published["canonical_output"],
            "scheduler_mutation": False,
        }
    else:
        validated = validate_terminal(args.terminal_receipt)
        terminal, _ = read_self_hashed(args.terminal_receipt, TERMINAL_ARTIFACT_TYPE)
        summary = {
            "command": "validate",
            "status": terminal["status"],
            "terminal_receipt": validated,
            "scheduler_mutation": False,
        }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
