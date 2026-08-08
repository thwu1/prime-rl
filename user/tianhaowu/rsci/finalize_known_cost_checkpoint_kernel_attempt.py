#!/usr/bin/env python3
"""Finalize one checkpoint-kernel GPU attempt and publish only proven success."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import stat
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import materialize_known_cost_checkpoint_kernel_plan as plan_module
import materialize_known_cost_checkpoint_kernel_readiness as readiness_module
import probe_known_cost_checkpoint_kernel as checkpoint_probe

SCHEMA_VERSION = 1
SUBMISSION_ARTIFACT_TYPE = "rsci_known_cost_checkpoint_kernel_submission_receipt"
DISPATCH_INTENT_ARTIFACT_TYPE = "rsci_known_cost_checkpoint_kernel_dispatch_intent"
FINALIZER_INTENT_ARTIFACT_TYPE = "rsci_known_cost_checkpoint_kernel_finalizer_intent"
RELEASE_ARTIFACT_TYPE = "rsci_known_cost_checkpoint_kernel_release_receipt"
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
    "ReqTRES",
    "ReqCPUS",
    "ReqMem",
    "NNodes",
    "TimelimitRaw",
    "Comment",
    "StdOut",
    "StdErr",
    "WorkDir",
    "SubmitLine",
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
    identity = checkpoint_probe.file_identity(resolved)
    if hashlib.sha256(raw).hexdigest() != identity["sha256"]:
        raise RuntimeError("Canonical artifact byte hash changed while reading")
    return value, identity


def terminal_state(value: str) -> str:
    normalized = value.split("+", 1)[0].strip().split(maxsplit=1)[0].upper()
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


def wait_terminal_allocation(job_id: str, *, attempts: int = 60, interval_seconds: float = 5.0) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return terminal_allocation(job_id)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(interval_seconds)
    raise RuntimeError(f"Terminal accounting did not stabilize for job {job_id}") from last_error


def parse_exit_code(value: str) -> tuple[int, int]:
    pieces = value.split(":")
    if len(pieces) != 2 or any(not piece.isdigit() for piece in pieces):
        raise ValueError(f"Invalid SLURM ExitCode: {value!r}")
    return int(pieces[0]), int(pieces[1])


def parse_tres(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in value.split(","):
        key, separator, item = field.partition("=")
        if not separator or not key or not item or key in result:
            raise ValueError(f"Invalid TRES record: {value!r}")
        result[key] = item
    return result


def replay_scheduler_observation(value: object, job_id: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("Scheduler observation is not an object")
    command = ["scontrol", "show", "job", "-o", job_id]
    stdout = value.get("stdout")
    if (
        value.get("command") != command
        or not isinstance(stdout, str)
        or value.get("stdout_sha256") != hashlib.sha256(stdout.encode()).hexdigest()
    ):
        raise ValueError("Scheduler observation command or stdout hash differs")
    parse_time(str(value.get("observed_at")))
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("Scheduler observation has an ambiguous row count")
    record = {}
    for field in shlex.split(lines[0]):
        key, separator, item = field.partition("=")
        if not separator or not key or key in record:
            raise ValueError(f"Malformed scheduler observation field: {field!r}")
        record[key] = item
    if record != value.get("record") or record.get("JobId") != job_id:
        raise ValueError("Scheduler observation parsed record differs")
    return record


def parse_time(value: str) -> datetime:
    if value in ("", "Unknown", "None"):
        raise ValueError(f"Invalid scheduler timestamp: {value!r}")
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def validate_submission(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    submission, identity = read_self_hashed(path, SUBMISSION_ARTIFACT_TYPE)
    if submission.get("study_id") != plan_module.STUDY_ID:
        raise ValueError("Submission receipt belongs to another study")
    plan_path = Path(str(submission.get("plan", {}).get("path"))).expanduser().resolve()
    readiness_path = Path(str(submission.get("readiness", {}).get("path"))).expanduser().resolve()
    if plan_module.validate_plan(plan_path) != submission.get("plan"):
        raise ValueError("Submission receipt plan identity changed")
    if readiness_module.validate_readiness(readiness_path) != submission.get("readiness"):
        raise ValueError("Submission receipt readiness identity changed")
    _, plan = plan_module.read_canonical_json(plan_path)
    control_source = plan_module.require_control_runtime(
        plan,
        role="attempt_finalizer",
        running_file=Path(__file__),
    )
    _, readiness = plan_module.read_canonical_json(readiness_path)
    task_id = str(submission.get("task_id"))
    if readiness.get("task", {}).get("task_id") != task_id:
        raise ValueError("Submission receipt task differs from readiness")
    attempt_id = str(submission.get("attempt_id"))
    if attempt_id != str(submission.get("gpu_job_id")) or not attempt_id.isdigit() or int(attempt_id) < 1:
        raise ValueError("Submission receipt attempt ID differs from its GPU job ID")
    finalizer_job_id = str(submission.get("finalizer_job_id"))
    if not finalizer_job_id.isdigit() or int(finalizer_job_id) < 1 or finalizer_job_id == attempt_id:
        raise ValueError("Submission receipt has an invalid finalizer job ID")
    ordinal = submission.get("attempt_ordinal")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        raise ValueError("Submission receipt has an invalid attempt ordinal")
    previous_terminal = submission.get("previous_terminal_receipt")
    if ordinal == 1:
        if previous_terminal is not None:
            raise ValueError("First submission attempt unexpectedly binds a previous terminal")
    else:
        if not isinstance(previous_terminal, dict):
            raise ValueError("Technical retry does not bind the previous failed terminal")
        previous_path = Path(str(previous_terminal.get("path"))).expanduser().resolve()
        if validate_terminal(previous_path) != previous_terminal:
            raise ValueError("Technical retry previous-terminal identity changed")
        previous_value, _ = read_self_hashed(previous_path, TERMINAL_ARTIFACT_TYPE)
        previous_submission, _ = read_self_hashed(
            Path(str(previous_value["submission"]["path"])),
            SUBMISSION_ARTIFACT_TYPE,
        )
        if (
            previous_value.get("status") != "failed"
            or previous_value.get("task_id") != task_id
            or previous_submission.get("attempt_ordinal") != ordinal - 1
        ):
            raise ValueError("Technical retry does not immediately follow a failed attempt")
    if submission.get("task_spec_sha256") != readiness.get("task_spec_sha256"):
        raise ValueError("Submission receipt task hash differs from readiness")
    if submission.get("control_source_sha256") != control_source.get("control_source_sha256"):
        raise ValueError("Submission receipt control source differs from the plan")
    plan_root = plan_path.parent
    attempt_root = plan_root / "attempts" / task_id / attempt_id
    if path.expanduser().resolve() != attempt_root / "submission_receipt.json":
        raise ValueError("Submission receipt is not at its attempt-local path")
    expected_paths = {
        "candidate": str(attempt_root / "candidate.json"),
        "runner_summary": str(attempt_root / "runner_summary.json"),
        "submitted_batch_script": str(attempt_root / "submitted_batch_script.sbatch"),
        "submitted_finalizer_batch_script": str(attempt_root / "submitted_finalizer_batch_script.sbatch"),
        "release_receipt": str(attempt_root / "release_receipt.json"),
        "terminal_receipt": str(attempt_root / "terminal_receipt.json"),
        "canonical_output": readiness["paths"]["canonical_output"],
    }
    paths = submission.get("paths")
    if paths != expected_paths:
        raise ValueError("Submission receipt paths differ from the plan namespace")
    script = submission.get("gpu_batch_script")
    if not isinstance(script, dict) or checkpoint_probe.file_identity(Path(str(script.get("path")))) != script:
        raise ValueError("Submission GPU batch-script identity changed")
    expected_gpu_script = plan_root / "scripts" / task_id / f"attempt_{ordinal:02d}_gpu.sbatch"
    if Path(str(script["path"])).resolve() != expected_gpu_script:
        raise ValueError("Submission GPU batch script is outside its plan namespace")
    finalizer_script = submission.get("finalizer_batch_script")
    if (
        not isinstance(finalizer_script, dict)
        or checkpoint_probe.file_identity(Path(str(finalizer_script.get("path")))) != finalizer_script
    ):
        raise ValueError("Submission finalizer batch-script identity changed")
    expected_finalizer_script = plan_root / "scripts" / task_id / f"attempt_{attempt_id}_finalizer.sbatch"
    if Path(str(finalizer_script["path"])).resolve() != expected_finalizer_script:
        raise ValueError("Submission finalizer batch script is outside its plan namespace")
    for script_path in (expected_gpu_script, expected_finalizer_script):
        if stat.S_IMODE(script_path.stat().st_mode) & 0o222:
            raise ValueError(f"Submission batch script is writable: {script_path}")
    scheduler = submission.get("scheduler_contract")
    comment_payload = {
        "plan_id": plan["plan_id"],
        "task_spec_sha256": readiness["task_spec_sha256"],
        "readiness_sha256": submission["readiness"]["sha256"],
        "gpu_script_sha256": script["sha256"],
        "attempt_ordinal": ordinal,
    }
    expected_comment = f"rsci-kc-{hashlib.sha256(canonical_json_bytes(comment_payload)).hexdigest()[:32]}"
    expected_scheduler = {
        "job_name": f"rsci-kc-kernel-{task_id}"[:128],
        "account": "ram",
        "qos": "h100_dev",
        "nodes": 1,
        "gpus": 1,
        "cpus": 16,
        "memory": "128G",
        "time_limit": "00:45:00",
        "comment": expected_comment,
        "held_at_submission": True,
    }
    if scheduler != expected_scheduler:
        raise ValueError("Submission scheduler contract differs")
    expected_finalizer_scheduler = {
        "job_name": f"rsci-kc-final-{task_id}"[:128],
        "account": "ram",
        "qos": "cpu_lowest",
        "nodes": 1,
        "gpus": 0,
        "cpus": 4,
        "memory": "32G",
        "time_limit": "01:00:00",
        "dependency": f"afterany:{attempt_id}",
        "comment": f"rsci-kc-final-{hashlib.sha256(expected_comment.encode()).hexdigest()[:24]}",
    }
    if submission.get("finalizer_scheduler_contract") != expected_finalizer_scheduler:
        raise ValueError("Submission finalizer scheduler contract differs")
    expected_gpu_argv = [
        "sbatch",
        "--parsable",
        "--hold",
        f"--comment={expected_comment}",
        "--qos=h100_dev",
        "--account=ram",
        str(expected_gpu_script),
    ]
    expected_finalizer_argv = [
        "sbatch",
        "--parsable",
        f"--dependency=afterany:{attempt_id}",
        f"--comment={expected_finalizer_scheduler['comment']}",
        "--qos=cpu_lowest",
        "--account=ram",
        str(expected_finalizer_script),
    ]
    if submission.get("gpu_sbatch_argv") != expected_gpu_argv:
        raise ValueError("Submission GPU sbatch argv differs")
    if submission.get("finalizer_sbatch_argv") != expected_finalizer_argv:
        raise ValueError("Submission finalizer sbatch argv differs")
    expected_environment_policy = {"remove_all_keys_with_prefix": "SBATCH_"}
    if submission.get("sbatch_environment_policy") != expected_environment_policy:
        raise ValueError("Submission sbatch environment policy differs")
    gpu_observation = submission.get("gpu_pre_release_scheduler")
    gpu_record = replay_scheduler_observation(gpu_observation, attempt_id)
    if (
        gpu_record.get("JobName") != expected_scheduler["job_name"]
        or gpu_record.get("Account") != expected_scheduler["account"]
        or gpu_record.get("QOS") != expected_scheduler["qos"]
        or gpu_record.get("Comment") != expected_scheduler["comment"]
        or gpu_record.get("JobState") != "PENDING"
        or gpu_record.get("Reason") != "JobHeldUser"
        or gpu_record.get("NumNodes") != "1"
        or gpu_record.get("NumCPUs") != "16"
        or "gres/gpu=1" not in gpu_record.get("ReqTRES", "").split(",")
    ):
        raise ValueError("Submission does not contain the exact held GPU scheduler observation")
    finalizer_observation = submission.get("finalizer_scheduler_observation")
    finalizer_record = replay_scheduler_observation(finalizer_observation, finalizer_job_id)
    if (
        finalizer_record.get("JobName") != expected_finalizer_scheduler["job_name"]
        or finalizer_record.get("Account") != expected_finalizer_scheduler["account"]
        or finalizer_record.get("QOS") != expected_finalizer_scheduler["qos"]
        or finalizer_record.get("Comment") != expected_finalizer_scheduler["comment"]
        or not finalizer_record.get("Dependency", "").startswith(f"afterany:{attempt_id}")
    ):
        raise ValueError("Submission does not contain the exact finalizer scheduler observation")
    if submission.get("allocation_log_path") != str(plan_root / "logs" / f"{task_id}_{attempt_id}.log"):
        raise ValueError("Submission GPU allocation log path differs")
    if submission.get("finalizer_log_path") != str(attempt_root / f"finalizer_{finalizer_job_id}.log"):
        raise ValueError("Submission finalizer log path differs")
    if submission.get("submission_channel") != {
        "tmux_socket": "/tmp/codex-rsci-control-20260806.sock",
        "session": "codex-rsci-control-20260806",
        "window": "Launcher",
    }:
        raise ValueError("Submission receipt does not bind the protected control tmux")
    scope = submission.get("scope")
    expected_scope = {
        "gpu_submission_performed": True,
        "finalizer_submission_performed": True,
        "gpu_held_while_receipt_was_frozen": True,
        "gpu_released": False,
        "scientific_result_identified": False,
        "canonical_output_published": False,
    }
    if scope != expected_scope:
        raise ValueError("Submission receipt scope differs")
    gate = submission.get("resource_policy_gate")
    if (
        not isinstance(gate, dict)
        or gate.get("open") is not True
        or gate.get("fixed_clock_or_gstar_pending") != 0
        or gate.get("blockers") != []
    ):
        raise ValueError("Submission receipt does not prove an open resource-policy gate")
    gate_stdout = gate.get("stdout")
    if (
        gate.get("command") != ["squeue", "-h", "-o", "%i|%j|%T|%r|%q"]
        or not isinstance(gate_stdout, str)
        or gate.get("stdout_sha256") != hashlib.sha256(gate_stdout.encode()).hexdigest()
    ):
        raise ValueError("Submission resource-policy observation is malformed")
    replayed_rows = []
    for line in gate_stdout.splitlines():
        if not line.strip():
            continue
        pieces = line.split("|", 4)
        if len(pieces) != 5:
            raise ValueError("Submission resource-policy observation has a malformed row")
        replayed_rows.append(dict(zip(("job_id", "job_name", "state", "reason", "qos"), pieces, strict=True)))
    if replayed_rows != gate.get("rows"):
        raise ValueError("Submission resource-policy rows differ from stdout")
    replayed_blockers = [
        row
        for row in replayed_rows
        if row["state"] == "PENDING"
        and (row["job_name"].startswith("rsci-vd-fcsft-") or row["job_name"].startswith("rsci-vd-gstar-"))
    ]
    if (
        gate.get("blockers") != replayed_blockers
        or gate.get("fixed_clock_or_gstar_pending") != len(replayed_blockers)
        or gate.get("open") is not (not replayed_blockers)
    ):
        raise ValueError("Submission resource-policy decision differs from replayed rows")
    parse_time(str(gate.get("observed_at")))
    dispatch_intent_record = submission.get("dispatch_intent")
    if not isinstance(dispatch_intent_record, dict):
        raise ValueError("Submission receipt has no immutable dispatch intent")
    dispatch_intent_path = Path(str(dispatch_intent_record.get("path"))).expanduser().resolve()
    expected_intent_path = plan_root / "dispatch_intents" / task_id / f"attempt_{ordinal:02d}.json"
    if dispatch_intent_path != expected_intent_path:
        raise ValueError("Submission dispatch intent is outside its plan namespace")
    dispatch_intent, dispatch_intent_identity = read_self_hashed(
        dispatch_intent_path,
        DISPATCH_INTENT_ARTIFACT_TYPE,
    )
    if dispatch_intent_identity != dispatch_intent_record:
        raise ValueError("Submission dispatch-intent identity changed")
    expected_intent = {
        "schema_version": 1,
        "artifact_type": DISPATCH_INTENT_ARTIFACT_TYPE,
        "study_id": plan_module.STUDY_ID,
        "plan": submission["plan"],
        "readiness": submission["readiness"],
        "task_id": task_id,
        "task_spec_sha256": submission["task_spec_sha256"],
        "control_source_sha256": submission["control_source_sha256"],
        "attempt_ordinal": ordinal,
        "previous_terminal_receipt": previous_terminal,
        "gpu_batch_script": script,
        "scheduler_contract": scheduler,
        "gpu_sbatch_argv": expected_gpu_argv,
        "sbatch_environment_policy": expected_environment_policy,
        "resource_policy_gate": gate,
        "submission_channel": submission["submission_channel"],
        "scope": {
            "scheduler_submission_performed": False,
            "gpu_will_be_held_until_receipt": True,
            "scientific_result_identified": False,
        },
    }
    expected_intent["payload_without_self_hash_sha256"] = canonical_json_sha256(expected_intent)
    if dispatch_intent != expected_intent:
        raise ValueError("Submission receipt differs from its immutable dispatch intent")
    finalizer_intent_record = submission.get("finalizer_intent")
    if not isinstance(finalizer_intent_record, dict):
        raise ValueError("Submission receipt has no immutable finalizer intent")
    finalizer_intent_path = Path(str(finalizer_intent_record.get("path"))).expanduser().resolve()
    expected_finalizer_intent_path = attempt_root / "finalizer_intent.json"
    if finalizer_intent_path != expected_finalizer_intent_path:
        raise ValueError("Submission finalizer intent is outside its attempt namespace")
    finalizer_intent, finalizer_intent_identity = read_self_hashed(
        finalizer_intent_path,
        FINALIZER_INTENT_ARTIFACT_TYPE,
    )
    if finalizer_intent_identity != finalizer_intent_record:
        raise ValueError("Submission finalizer-intent identity changed")
    expected_finalizer_intent = {
        "schema_version": 1,
        "artifact_type": FINALIZER_INTENT_ARTIFACT_TYPE,
        "study_id": plan_module.STUDY_ID,
        "dispatch_intent": dispatch_intent_record,
        "plan": submission["plan"],
        "readiness": submission["readiness"],
        "task_id": task_id,
        "task_spec_sha256": submission["task_spec_sha256"],
        "attempt_ordinal": ordinal,
        "attempt_id": attempt_id,
        "gpu_job_id": attempt_id,
        "gpu_pre_release_scheduler": gpu_observation,
        "finalizer_batch_script": finalizer_script,
        "finalizer_scheduler_contract": expected_finalizer_scheduler,
        "finalizer_sbatch_argv": expected_finalizer_argv,
        "sbatch_environment_policy": expected_environment_policy,
        "submission_channel": submission["submission_channel"],
        "scope": {
            "finalizer_submission_performed": False,
            "gpu_remains_held": True,
            "scientific_result_identified": False,
        },
    }
    expected_finalizer_intent["payload_without_self_hash_sha256"] = canonical_json_sha256(
        expected_finalizer_intent
    )
    if finalizer_intent != expected_finalizer_intent:
        raise ValueError("Submission receipt differs from its immutable finalizer intent")
    expected_release_argv = ["scontrol", "release", attempt_id]
    if submission.get("authorized_release_argv") != expected_release_argv:
        raise ValueError("Submission receipt does not authorize the exact release command")
    if submission.get("release_policy") != "release only after immutable submission receipt validates":
        raise ValueError("Submission release policy differs")
    parse_time(str(submission.get("submitted_at")))
    return submission, identity


def validate_release_receipt(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    release, identity = read_self_hashed(path, RELEASE_ARTIFACT_TYPE)
    if release.get("study_id") != plan_module.STUDY_ID:
        raise ValueError("Release receipt belongs to another study")
    submission_path = Path(str(release.get("submission", {}).get("path"))).expanduser().resolve()
    submission, submission_identity = validate_submission(submission_path)
    if release.get("submission") != submission_identity:
        raise ValueError("Release receipt submission identity changed")
    expected_path = Path(str(submission["paths"]["release_receipt"]))
    if path.expanduser().resolve() != expected_path:
        raise ValueError("Release receipt is outside its attempt directory")
    for key in ("task_id", "attempt_id", "gpu_job_id"):
        if release.get(key) != submission.get(key):
            raise ValueError(f"Release receipt {key} differs from submission")
    job_id = submission["gpu_job_id"]
    if release.get("release_command") != submission.get("authorized_release_argv"):
        raise ValueError("Release receipt command differs")
    if release.get("pre_release_scheduler") != submission.get("gpu_pre_release_scheduler"):
        raise ValueError("Release receipt pre-release observation differs from submission")
    replay_scheduler_observation(release["pre_release_scheduler"], job_id)
    post_record = replay_scheduler_observation(release.get("post_release_scheduler"), job_id)
    if post_record.get("Reason") == "JobHeldUser":
        raise ValueError("Release receipt still observes a user-held GPU job")
    if release.get("submission_channel") != submission.get("submission_channel"):
        raise ValueError("Release receipt did not use the protected submission channel")
    if release.get("scope") != {
        "held_job_released": True,
        "scientific_result_identified": False,
        "scheduler_mutation": True,
    }:
        raise ValueError("Release receipt scope differs")
    submitted_at = parse_time(str(submission["submitted_at"]))
    released_at = parse_time(str(release.get("released_at")))
    if released_at < submitted_at:
        raise ValueError("Release receipt predates submission")
    empty_hash = hashlib.sha256(b"").hexdigest()
    if release.get("release_stdout_sha256") != empty_hash or release.get("release_stderr_sha256") != empty_hash:
        raise ValueError("scontrol release emitted unexpected output")
    return release, identity


def _artifact_mtime(path: Path) -> dict[str, Any]:
    stat_result = path.stat()
    return {
        "mtime_ns": stat_result.st_mtime_ns,
        "mtime_utc": datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat(),
        "ctime_ns": stat_result.st_ctime_ns,
        "ctime_utc": datetime.fromtimestamp(stat_result.st_ctime, tz=UTC).isoformat(),
    }


def build_terminal_receipt(submission_path: Path) -> dict[str, Any]:
    submission, submission_identity = validate_submission(submission_path)
    _, release_identity = validate_release_receipt(Path(str(submission["paths"]["release_receipt"])))
    plan_path = Path(str(submission["plan"]["path"]))
    _, plan = plan_module.read_canonical_json(plan_path)
    control_source = plan["control_source"]
    finalizer_environment = {
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "job_name": os.environ.get("SLURM_JOB_NAME"),
        "account": os.environ.get("SLURM_JOB_ACCOUNT"),
        "qos": os.environ.get("SLURM_JOB_QOS"),
        "node_list": os.environ.get("SLURM_JOB_NODELIST"),
        "submit_dir": os.environ.get("SLURM_SUBMIT_DIR"),
    }
    finalizer_scheduler = submission["finalizer_scheduler_contract"]
    expected_finalizer_environment = {
        "job_id": submission["finalizer_job_id"],
        "job_name": finalizer_scheduler["job_name"],
        "account": finalizer_scheduler["account"],
        "qos": finalizer_scheduler["qos"],
        "submit_dir": str(Path(str(control_source["snapshot_path"]))),
    }
    for key, expected in expected_finalizer_environment.items():
        if finalizer_environment[key] != expected:
            raise ValueError(f"Live finalizer {key} differs from its submission contract")
    if not finalizer_environment["node_list"]:
        raise ValueError("Live finalizer has no node allocation")
    allocation = wait_terminal_allocation(str(submission["gpu_job_id"]))
    record = allocation["record"]
    scheduler = submission["scheduler_contract"]
    for field, expected in (
        ("JobName", scheduler["job_name"]),
        ("Account", scheduler["account"]),
        ("QOS", scheduler["qos"]),
    ):
        if record[field] != expected:
            raise ValueError(f"Terminal allocation {field} differs: {record[field]!r} != {expected!r}")
    if record["Comment"] != scheduler["comment"]:
        raise ValueError("Terminal allocation comment differs from the content-addressed submission")
    requested_tres = parse_tres(record["ReqTRES"])
    if requested_tres.get("gres/gpu") != "1" or requested_tres.get("node") != "1":
        raise ValueError("Terminal accounting does not prove a one-GPU, one-node request")
    if record["ReqCPUS"] != str(scheduler["cpus"]) or record["ReqMem"] != scheduler["memory"]:
        raise ValueError("Terminal allocation CPU or memory request differs")
    if record["TimelimitRaw"] != "2700":
        raise ValueError("Terminal allocation time limit differs")
    if record["WorkDir"] != str(Path(str(control_source["snapshot_path"]))):
        raise ValueError("Terminal allocation working directory differs from the control snapshot")
    accounting_log_path = str(
        plan_path.parent / "logs" / f"{submission['task_id']}_%j.log"
    )
    if record["StdOut"] != accounting_log_path or record["StdErr"] != accounting_log_path:
        raise ValueError("Terminal allocation log paths differ from the submission")
    exit_code = parse_exit_code(record["ExitCode"])
    succeeded = record["State"] == "COMPLETED" and exit_code == (0, 0)
    if succeeded:
        allocated_tres = parse_tres(record["AllocTRES"])
        if allocated_tres.get("gres/gpu") != "1" or allocated_tres.get("node") != "1":
            raise ValueError("Successful allocation does not prove one GPU and one node")
        if record["NNodes"] != str(scheduler["nodes"]):
            raise ValueError("Successful allocation node count differs")

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
    finalizer_script_capture = checkpoint_probe.file_identity(paths["submitted_finalizer_batch_script"])
    if finalizer_script_capture["sha256"] != submission["finalizer_batch_script"]["sha256"]:
        raise ValueError("In-allocation finalizer-script capture differs from the dispatched script")
    log_path = Path(str(submission["allocation_log_path"]))
    allocation_log = checkpoint_probe.file_identity(log_path) if log_path.is_file() else None
    if succeeded and allocation_log is None:
        raise ValueError("Successful GPU allocation has no allocation log")
    evidence: dict[str, Any] = {
        "submitted_batch_script": script_capture,
        "submitted_finalizer_batch_script": finalizer_script_capture,
        "allocation_log": allocation_log,
        "finalizer_environment": finalizer_environment,
        "release_receipt": release_identity,
    }

    candidate = None
    runner_summary = None
    if succeeded:
        candidate = checkpoint_probe.validate(paths["candidate"])
        runner_summary, runner_summary_identity = read_self_hashed(
            paths["runner_summary"],
            "rsci_known_cost_checkpoint_kernel_runner_summary",
        )
        evidence["runner_summary"] = runner_summary_identity
    else:
        evidence["failed_candidate_file"] = (
            checkpoint_probe.file_identity(paths["candidate"]) if paths["candidate"].is_file() else None
        )
        evidence["failed_runner_summary_file"] = (
            checkpoint_probe.file_identity(paths["runner_summary"])
            if paths["runner_summary"].is_file()
            else None
        )
    if succeeded:
        if runner_summary.get("candidate") != candidate or runner_summary.get("already_complete") is not False:
            raise ValueError("Runner summary does not prove a fresh candidate")
        expected_runner_fields = {
            "schema_version": 1,
            "artifact_type": "rsci_known_cost_checkpoint_kernel_runner_summary",
            "candidate": candidate,
            "candidate_sha256": candidate["sha256"],
            "plan_id": plan["plan_id"],
            "task_id": submission["task_id"],
            "attempt_id": submission["attempt_id"],
            "already_complete": False,
            "canonical_output_published": False,
            "scheduler_mutation": False,
        }
        if {key: runner_summary.get(key) for key in expected_runner_fields} != expected_runner_fields:
            raise ValueError("Runner summary fields differ from the successful attempt")
        if set(runner_summary) != {*expected_runner_fields, "payload_without_self_hash_sha256"}:
            raise ValueError("Runner summary has unexpected fields")
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
            or binding.get("submission_receipt") != submission_identity
            or binding.get("release_receipt") != release_identity
            or binding.get("plan_id") != plan["plan_id"]
            or binding.get("task_spec_sha256") != submission["task_spec_sha256"]
            or binding.get("control_source_sha256") != submission["control_source_sha256"]
            or binding.get("candidate_path") != submission["paths"]["candidate"]
            or binding.get("runner_summary_path") != submission["paths"]["runner_summary"]
            or binding.get("canonical_output_path") != submission["paths"]["canonical_output"]
            or binding.get("runner_implementation") != control_source["implementations"]["task_runner"]
            or binding.get("checkpoint_probe_implementation")
            != control_source["implementations"]["checkpoint_probe"]
        ):
            raise ValueError("Candidate execution binding differs from submission")
        slurm_environment = binding.get("slurm_environment")
        if not isinstance(slurm_environment, dict) or (
            slurm_environment.get("job_id") != submission["gpu_job_id"]
            or slurm_environment.get("job_name") != scheduler["job_name"]
            or slurm_environment.get("account") != scheduler["account"]
            or slurm_environment.get("qos") != scheduler["qos"]
            or slurm_environment.get("node_list") != record["NodeList"]
            or slurm_environment.get("submit_dir") != record["WorkDir"]
            or not slurm_environment.get("cuda_visible_devices")
        ):
            raise ValueError("Candidate SLURM environment differs from terminal accounting")
        expected_argv = [
            str(Path(str(control_source["environment"]["python"])).resolve()),
            str(Path(str(control_source["implementations"]["task_runner"]["path"]))),
            "--plan",
            str(plan_path),
            "--readiness",
            str(Path(str(submission["readiness"]["path"]))),
            "--submission-receipt",
            str(submission_path.resolve()),
            "--release-receipt",
            submission["paths"]["release_receipt"],
            "--task-id",
            submission["task_id"],
            "--attempt-id",
            submission["attempt_id"],
            "--candidate",
            submission["paths"]["candidate"],
            "--summary",
            submission["paths"]["runner_summary"],
        ]
        if binding.get("argv") != expected_argv:
            raise ValueError("Candidate runner argv differs from the dispatched task")
        start = parse_time(record["Start"])
        end = parse_time(record["End"])
        submit = parse_time(record["Submit"])
        receipt_time = parse_time(str(submission["submitted_at"]))
        clock_tolerance = timedelta(seconds=5)
        if not (
            submit - clock_tolerance <= receipt_time
            and receipt_time <= start + clock_tolerance
            and start <= end
        ):
            raise ValueError("Submission receipt and allocation timestamps are not ordered")
        candidate_mtime = datetime.fromtimestamp(paths["candidate"].stat().st_mtime, tz=UTC)
        candidate_ctime = datetime.fromtimestamp(paths["candidate"].stat().st_ctime, tz=UTC)
        summary_mtime = datetime.fromtimestamp(paths["runner_summary"].stat().st_mtime, tz=UTC)
        summary_ctime = datetime.fromtimestamp(paths["runner_summary"].stat().st_ctime, tz=UTC)
        if not start - clock_tolerance <= candidate_mtime <= summary_mtime <= end + clock_tolerance:
            raise ValueError("Candidate modification time is outside the GPU allocation")
        if not start - clock_tolerance <= candidate_ctime <= summary_ctime <= end + clock_tolerance:
            raise ValueError("Candidate change time is outside the GPU allocation")
        evidence["candidate"] = candidate
        evidence["candidate_time"] = _artifact_mtime(paths["candidate"])
        evidence["runner_summary_time"] = _artifact_mtime(paths["runner_summary"])
        evidence["filesystem_scheduler_clock_tolerance_seconds"] = 5

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
        "implementation": control_source["implementations"]["attempt_finalizer"],
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
        if terminal_path.exists():
            if terminal_path.read_bytes() != content:
                raise FileExistsError("Terminal receipt differs from the existing attempt receipt")
        else:
            _write_read_only(terminal_path, content)
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
    if terminal.get("study_id") != plan_module.STUDY_ID:
        raise ValueError("Terminal receipt belongs to another study")
    submission_path = Path(str(terminal["submission"]["path"]))
    submission, submission_identity = validate_submission(submission_path)
    if terminal["submission"] != submission_identity:
        raise ValueError("Terminal receipt submission identity changed")
    if terminal["paths"] != submission["paths"] or terminal["attempt_id"] != submission["attempt_id"]:
        raise ValueError("Terminal receipt path or attempt differs from submission")
    for key in ("plan", "readiness", "task_id", "task_spec_sha256", "gpu_job_id", "scheduler_contract"):
        if terminal.get(key) != submission.get(key):
            raise ValueError(f"Terminal receipt {key} differs from submission")
    paths = {key: Path(value) for key, value in terminal["paths"].items()}
    if path.expanduser().resolve() != paths["terminal_receipt"]:
        raise ValueError("Terminal receipt is not at its attempt-local path")
    allocation = terminal.get("terminal_allocation")
    if not isinstance(allocation, dict):
        raise ValueError("Terminal receipt has no allocation evidence")
    expected_allocation_command = [
        "sacct",
        "-X",
        "-n",
        "-P",
        "-j",
        submission["gpu_job_id"],
        f"--format={','.join(SACCT_FIELDS)}",
    ]
    stdout = allocation.get("stdout")
    record = allocation.get("record")
    if (
        allocation.get("command") != expected_allocation_command
        or not isinstance(stdout, str)
        or allocation.get("stdout_sha256") != hashlib.sha256(stdout.encode()).hexdigest()
        or not isinstance(record, dict)
        or set(record) != set(SACCT_FIELDS)
    ):
        raise ValueError("Terminal allocation evidence is malformed")
    rows = [line.split("|") for line in stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != len(SACCT_FIELDS):
        raise ValueError("Terminal allocation stdout is ambiguous")
    replayed_record = dict(zip(SACCT_FIELDS, rows[0], strict=True))
    replayed_record["State"] = terminal_state(replayed_record["State"])
    if replayed_record != record or record["JobIDRaw"] != submission["gpu_job_id"]:
        raise ValueError("Terminal allocation stdout and record differ")
    succeeded = record["State"] == "COMPLETED" and parse_exit_code(record["ExitCode"]) == (0, 0)
    expected_status = "succeeded" if succeeded else "failed"
    if terminal.get("status") != expected_status:
        raise ValueError("Terminal status differs from scheduler evidence")
    evidence = terminal.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("Terminal receipt has no evidence object")
    for key, submission_key in (
        ("submitted_batch_script", "gpu_batch_script"),
        ("submitted_finalizer_batch_script", "finalizer_batch_script"),
    ):
        recorded = evidence.get(key)
        if recorded is not None and checkpoint_probe.file_identity(Path(str(recorded.get("path")))) != recorded:
            raise ValueError(f"Terminal {key} identity changed")
        if key == "submitted_finalizer_batch_script" and recorded is None:
            raise ValueError("Terminal receipt lacks its finalizer script capture")
        if recorded is not None and recorded["sha256"] != submission[submission_key]["sha256"]:
            raise ValueError(f"Terminal {key} differs from the dispatched script")
    allocation_log = evidence.get("allocation_log")
    if allocation_log is not None and checkpoint_probe.file_identity(Path(str(allocation_log.get("path")))) != allocation_log:
        raise ValueError("Terminal allocation log identity changed")
    if succeeded and allocation_log is None:
        raise ValueError("Successful terminal receipt has no allocation log")
    _, release_identity = validate_release_receipt(Path(str(submission["paths"]["release_receipt"])))
    if evidence.get("release_receipt") != release_identity:
        raise ValueError("Terminal release-receipt identity changed")
    _, plan = plan_module.read_canonical_json(Path(str(submission["plan"]["path"])))
    if terminal.get("implementation") != plan["control_source"]["implementations"]["attempt_finalizer"]:
        raise ValueError("Terminal receipt used another finalizer implementation")
    expected_publication = {
        "eligible": succeeded,
        "canonical_output": submission["paths"]["canonical_output"],
        "candidate": evidence.get("candidate") if succeeded else None,
        "method": "hard_link_after_terminal_validation" if succeeded else None,
    }
    if terminal.get("publication") != expected_publication:
        raise ValueError("Terminal publication declaration differs from scheduler status")
    expected_scope = {
        "proves_terminal_allocation": True,
        "proves_submitted_script_capture": evidence.get("submitted_batch_script") is not None,
        "proves_candidate_created_during_successful_allocation": succeeded,
        "proves_scientific_repeat": False,
        "proves_causal_training_effect": False,
    }
    if terminal.get("scope") != expected_scope:
        raise ValueError("Terminal receipt scope differs")
    if terminal["status"] == "succeeded":
        for label in ("candidate", "canonical_output"):
            artifact_path = paths[label]
            if artifact_path.is_symlink() or not stat.S_ISREG(artifact_path.lstat().st_mode):
                raise ValueError(f"Successful {label} is not a regular non-symlink file")
        candidate = checkpoint_probe.validate(paths["candidate"])
        canonical = checkpoint_probe.validate(paths["canonical_output"])
        candidate_stat = paths["candidate"].stat()
        canonical_stat = paths["canonical_output"].stat()
        if (
            candidate["sha256"] != canonical["sha256"]
            or candidate_stat.st_dev != canonical_stat.st_dev
            or candidate_stat.st_ino != canonical_stat.st_ino
        ):
            raise ValueError("Canonical result is not the hard-linked attempt candidate")
        if terminal["publication"]["candidate"] != candidate:
            raise ValueError("Terminal publication candidate identity changed")
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
