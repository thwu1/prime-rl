#!/usr/bin/env python3
"""Dispatch one plan-bound checkpoint-kernel task through the protected tmux."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import finalize_known_cost_checkpoint_kernel_attempt as finalizer
import materialize_known_cost_checkpoint_kernel_plan as plan_module
import materialize_known_cost_checkpoint_kernel_readiness as readiness_module
import probe_known_cost_checkpoint_kernel as checkpoint_probe

CONTROL_SOCKET = Path("/tmp/codex-rsci-control-20260806.sock")
CONTROL_SESSION = "codex-rsci-control-20260806"
CONTROL_WINDOW = "Launcher"
GPU_QOS = "h100_dev"
CPU_QOS = "cpu_lowest"
ACCOUNT = "ram"
SBATCH_ENVIRONMENT_POLICY = {"remove_all_keys_with_prefix": "SBATCH_"}


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def require_protected_tmux() -> None:
    tmux_value = os.environ.get("TMUX", "")
    pane = os.environ.get("TMUX_PANE", "")
    if tmux_value.split(",", 1)[0] != str(CONTROL_SOCKET) or not pane:
        raise RuntimeError("Submission is allowed only from the protected control tmux")
    completed = subprocess.run(
        ["tmux", "-S", str(CONTROL_SOCKET), "display-message", "-p", "-t", pane, "#S:#W"],
        text=True,
        capture_output=True,
        check=True,
    )
    if completed.stdout.strip() != f"{CONTROL_SESSION}:{CONTROL_WINDOW}":
        raise RuntimeError(f"Submission originated from {completed.stdout.strip()!r}, not the protected Launcher")


def resource_policy_gate() -> dict[str, Any]:
    command = ["squeue", "-h", "-o", "%i|%j|%T|%r|%q"]
    completed = subprocess.run(command, text=True, capture_output=True, check=True, timeout=60)
    rows = []
    blockers = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        pieces = line.split("|", 4)
        if len(pieces) != 5:
            raise ValueError(f"Malformed squeue row: {line!r}")
        row = dict(zip(("job_id", "job_name", "state", "reason", "qos"), pieces, strict=True))
        if row["state"] == "PENDING" and (
            row["job_name"].startswith("rsci-vd-fcsft-") or row["job_name"].startswith("rsci-vd-gstar-")
        ):
            blockers.append(row)
        rows.append(row)
    return {
        "observed_at": utc_now(),
        "command": command,
        "stdout": completed.stdout,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "rows": rows,
        "fixed_clock_or_gstar_pending": len(blockers),
        "blockers": blockers,
        "open": not blockers,
    }


def scheduler_observation(job_id: str) -> dict[str, Any]:
    command = ["scontrol", "show", "job", "-o", job_id]
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"scontrol returned {len(lines)} rows for job {job_id}")
    record = {}
    for field in shlex.split(lines[0]):
        key, separator, value = field.partition("=")
        if not separator or not key or key in record:
            raise ValueError(f"Malformed scontrol field for job {job_id}: {field!r}")
        record[key] = value
    if record.get("JobId") != job_id:
        raise ValueError(f"scontrol returned another job ID for {job_id}")
    return {
        "observed_at": utc_now(),
        "command": command,
        "stdout": completed.stdout,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "record": record,
    }


def _control_source(plan: dict[str, Any]) -> dict[str, Any]:
    return plan_module.require_control_runtime(
        plan,
        role="dispatcher",
        running_file=Path(__file__),
    )


def load_task(plan_path: Path, readiness_path: Path, task_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_identity = plan_module.validate_plan(plan_path)
    readiness_identity = readiness_module.validate_readiness(readiness_path)
    _, plan = plan_module.read_canonical_json(plan_path)
    _, readiness = plan_module.read_canonical_json(readiness_path)
    if readiness.get("plan") != plan_identity or readiness.get("plan_id") != plan.get("plan_id"):
        raise ValueError("Readiness belongs to another checkpoint-kernel plan")
    task = readiness.get("task")
    if not isinstance(task, dict) or task.get("task_id") != task_id:
        raise ValueError("Readiness belongs to another checkpoint-kernel task")
    _control_source(plan)
    return plan, readiness, {"plan": plan_identity, "readiness": readiness_identity}


def render_gpu_script(
    *,
    plan: dict[str, Any],
    readiness: dict[str, Any],
    identities: dict[str, Any],
    task_id: str,
) -> str:
    source = _control_source(plan)
    python_path = Path(str(source["environment"]["python"]))
    runner = Path(str(source["implementations"]["task_runner"]["path"]))
    activation = Path(str(source["implementations"]["activation_helper"]["path"]))
    control_root = Path(str(source["root"]))
    plan_path = Path(str(identities["plan"]["path"]))
    readiness_path = Path(str(identities["readiness"]["path"]))
    attempt_root = Path(str(readiness["paths"]["attempt_root"]))
    log_path = plan_path.parent / "logs" / f"{task_id}_%j.log"
    job_name = f"rsci-kc-kernel-{task_id}"[:128]
    return f"""#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=00:45:00
#SBATCH --output={log_path}
#SBATCH --error={log_path}
set -euo pipefail
source {shlex.quote(str(activation))} {shlex.quote(str(control_root))}
ATTEMPT_DIR={shlex.quote(str(attempt_root))}/${{SLURM_JOB_ID}}
mkdir -p "$ATTEMPT_DIR"
CAPTURE_TMP="$ATTEMPT_DIR/.submitted_batch_script.sbatch.partial"
scontrol write batch_script "$SLURM_JOB_ID" "$CAPTURE_TMP"
test -s "$CAPTURE_TMP"
chmod 0444 "$CAPTURE_TMP"
mv "$CAPTURE_TMP" "$ATTEMPT_DIR/submitted_batch_script.sbatch"
for _ in $(seq 1 300); do
  if [[ -s "$ATTEMPT_DIR/submission_receipt.json" ]]; then
    break
  fi
  sleep 1
done
test -s "$ATTEMPT_DIR/submission_receipt.json"
for _ in $(seq 1 300); do
  if [[ -s "$ATTEMPT_DIR/release_receipt.json" ]]; then
    break
  fi
  sleep 1
done
test -s "$ATTEMPT_DIR/release_receipt.json"
export CUBLAS_WORKSPACE_CONFIG=:4096:8
{shlex.quote(str(python_path))} {shlex.quote(str(runner))} \
  --plan {shlex.quote(str(plan_path))} \
  --readiness {shlex.quote(str(readiness_path))} \
  --submission-receipt "$ATTEMPT_DIR/submission_receipt.json" \
  --release-receipt "$ATTEMPT_DIR/release_receipt.json" \
  --task-id {shlex.quote(task_id)} \
  --attempt-id "$SLURM_JOB_ID" \
  --candidate "$ATTEMPT_DIR/candidate.json" \
  --summary "$ATTEMPT_DIR/runner_summary.json"
"""


def render_finalizer_script(
    *,
    plan: dict[str, Any],
    submission_receipt: Path,
    task_id: str,
) -> str:
    source = _control_source(plan)
    python_path = Path(str(source["environment"]["python"]))
    implementation = Path(str(source["implementations"]["attempt_finalizer"]["path"]))
    activation = Path(str(source["implementations"]["activation_helper"]["path"]))
    control_root = Path(str(source["root"]))
    attempt_root = submission_receipt.parent
    log_path = attempt_root / "finalizer_%j.log"
    return f"""#!/bin/bash
#SBATCH --job-name={f'rsci-kc-final-{task_id}'[:128]}
#SBATCH --nodes=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output={log_path}
#SBATCH --error={log_path}
set -euo pipefail
source {shlex.quote(str(activation))} {shlex.quote(str(control_root))}
CAPTURE_TMP={shlex.quote(str(attempt_root / '.submitted_finalizer_batch_script.sbatch.partial'))}
scontrol write batch_script "$SLURM_JOB_ID" "$CAPTURE_TMP"
test -s "$CAPTURE_TMP"
chmod 0444 "$CAPTURE_TMP"
mv "$CAPTURE_TMP" {shlex.quote(str(attempt_root / 'submitted_finalizer_batch_script.sbatch'))}
{shlex.quote(str(python_path))} {shlex.quote(str(implementation))} finalize \
  --submission-receipt {shlex.quote(str(submission_receipt))}
"""


def _write_script(path: Path, content: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = content.encode()
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"Refusing to replace different batch script: {path}")
        return checkpoint_probe.file_identity(path)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return checkpoint_probe.file_identity(path)


def _atomic_state(path: Path, value: dict[str, Any]) -> None:
    content = canonical_json_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "tasks": {}}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("tasks"), dict):
        raise ValueError("Checkpoint-kernel dispatch state is invalid")
    return value


def _job_ids_by_comment(*, comment: str, job_name: str) -> list[int]:
    completed = subprocess.run(
        ["squeue", "-h", "-o", "%i|%j|%k"],
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
    )
    matches = []
    for line in completed.stdout.splitlines():
        job_id, separator, remainder = line.partition("|")
        observed_name, second_separator, observed_comment = remainder.partition("|")
        if not separator or not second_separator:
            raise ValueError(f"Malformed squeue reconciliation row: {line!r}")
        if observed_name == job_name and observed_comment == comment:
            if not job_id.isdigit():
                raise ValueError(f"Non-scalar reconciled job ID: {job_id!r}")
            matches.append(int(job_id))
    return matches


def _accounting_has_job(job_id: str) -> bool:
    completed = subprocess.run(
        ["sacct", "-X", "-n", "-P", "-j", job_id, "--format=JobIDRaw"],
        text=True,
        capture_output=True,
        check=True,
        timeout=60,
    )
    return [line.strip("|") for line in completed.stdout.splitlines() if line.strip()] == [job_id]


def _sbatch(command: list[str], *, cwd: Path, comment: str, job_name: str) -> int:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SBATCH_")}
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
            env=environment,
            timeout=60,
        )
        raw = completed.stdout.strip().split(";", 1)[0]
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        submission_error = error
    else:
        submission_error = ValueError(f"sbatch returned an invalid job ID: {completed.stdout!r}")
    matches = _job_ids_by_comment(comment=comment, job_name=job_name)
    if len(matches) == 1:
        return matches[0]
    raise RuntimeError(
        f"Ambiguous sbatch outcome for comment {comment}: reconciled job IDs={matches}"
    ) from submission_error


def _prior_attempts(plan_root: Path, task_id: str) -> list[dict[str, Any]]:
    attempts = []
    task_root = plan_root / "attempts" / task_id
    if not task_root.is_dir():
        return attempts
    for path in task_root.glob("*/submission_receipt.json"):
        submission, submission_identity = finalizer.validate_submission(path)
        if submission.get("task_id") != task_id:
            raise ValueError(f"Attempt receipt under {task_id} belongs to another task")
        terminal_path = path.parent / "terminal_receipt.json"
        terminal = None
        terminal_identity = None
        if terminal_path.is_file():
            terminal_identity = finalizer.validate_terminal(terminal_path)
            terminal, _ = finalizer.read_self_hashed(terminal_path, finalizer.TERMINAL_ARTIFACT_TYPE)
        attempts.append(
            {
                "submission": submission,
                "submission_identity": submission_identity,
                "terminal": terminal,
                "terminal_identity": terminal_identity,
            }
        )
    attempts.sort(key=lambda attempt: int(attempt["submission"]["attempt_ordinal"]))
    if [int(attempt["submission"]["attempt_ordinal"]) for attempt in attempts] != list(
        range(1, len(attempts) + 1)
    ):
        raise ValueError(f"Checkpoint-kernel attempt ordinals are not contiguous for {task_id}")
    return attempts


def dispatch(
    *,
    plan_path: Path,
    readiness_path: Path,
    task_id: str,
    submit: bool,
    retry_failed: bool,
    reconcile: bool,
    confirm_study_id: str | None,
) -> dict[str, Any]:
    if reconcile and (not submit or retry_failed):
        raise ValueError("--reconcile requires --submit and cannot be combined with --retry-failed")
    plan, readiness, identities = load_task(plan_path, readiness_path, task_id)
    control_cwd = Path(str(plan["control_source"]["snapshot_path"]))
    plan_root = Path(str(identities["plan"]["path"])).parent
    prior = _prior_attempts(plan_root, task_id)
    state_path = plan_root / "dispatch_state.json"
    preliminary_state_entry = _load_state(state_path)["tasks"].get(task_id)
    if reconcile:
        if not isinstance(preliminary_state_entry, dict):
            raise RuntimeError("--reconcile requires an interrupted mutable dispatch state")
        ordinal = preliminary_state_entry.get("attempt_ordinal")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
            raise ValueError("Interrupted mutable dispatch state has an invalid attempt ordinal")
    else:
        ordinal = len(prior) + 1
    previous_attempts = [
        attempt
        for attempt in prior
        if int(attempt["submission"]["attempt_ordinal"]) == ordinal - 1
    ]
    previous_terminal_identity = previous_attempts[0]["terminal_identity"] if previous_attempts else None
    canonical = Path(str(readiness["paths"]["canonical_output"]))
    if canonical.exists():
        raise FileExistsError(f"Task already has a canonical result: {canonical}")
    if prior:
        latest = prior[-1]
        if latest["terminal"] is None and not reconcile:
            raise RuntimeError("Latest checkpoint-kernel attempt has no terminal receipt")
        if latest["terminal"] is not None and latest["terminal"]["status"] == "succeeded":
            raise RuntimeError("Latest checkpoint-kernel attempt already succeeded")
        if latest["terminal"] is not None and not retry_failed and not reconcile:
            raise RuntimeError("Latest attempt failed; --retry-failed is required for a technical retry")
    task_hash = readiness["task_spec_sha256"]
    script_path = plan_root / "scripts" / task_id / f"attempt_{ordinal:02d}_gpu.sbatch"
    gpu_content = render_gpu_script(
        plan=plan,
        readiness=readiness,
        identities=identities,
        task_id=task_id,
    )
    gpu_identity_preview = {
        "path": str(script_path),
        "size_bytes": len(gpu_content.encode()),
        "sha256": hashlib.sha256(gpu_content.encode()).hexdigest(),
    }
    comment_payload = {
        "plan_id": plan["plan_id"],
        "task_spec_sha256": task_hash,
        "readiness_sha256": identities["readiness"]["sha256"],
        "gpu_script_sha256": gpu_identity_preview["sha256"],
        "attempt_ordinal": ordinal,
    }
    comment = f"rsci-kc-{hashlib.sha256(canonical_json_bytes(comment_payload)).hexdigest()[:32]}"
    finalizer_comment = f"rsci-kc-final-{hashlib.sha256(comment.encode()).hexdigest()[:24]}"
    scheduler_contract = {
        "job_name": f"rsci-kc-kernel-{task_id}"[:128],
        "account": ACCOUNT,
        "qos": GPU_QOS,
        "nodes": 1,
        "gpus": 1,
        "cpus": 16,
        "memory": "128G",
        "time_limit": "00:45:00",
        "comment": comment,
        "held_at_submission": True,
    }
    gpu_command = [
        "sbatch",
        "--parsable",
        "--hold",
        f"--comment={comment}",
        f"--qos={GPU_QOS}",
        f"--account={ACCOUNT}",
        str(script_path),
    ]
    gate = resource_policy_gate()
    if not submit:
        return {
            "submission_performed": False,
            "task_id": task_id,
            "attempt_ordinal": ordinal,
            "previous_terminal_receipt": previous_terminal_identity,
            "resource_gate": gate,
            "gpu_batch_script": gpu_identity_preview,
            "gpu_command": gpu_command,
            "sbatch_environment_policy": SBATCH_ENVIRONMENT_POLICY,
        }
    if confirm_study_id != plan_module.STUDY_ID:
        raise ValueError(f"--confirm-study-id must equal {plan_module.STUDY_ID}")
    require_protected_tmux()
    if not gate["open"]:
        raise RuntimeError(
            f"Resource policy gate is closed by {gate['fixed_clock_or_gstar_pending']} fixed-clock/Gstar jobs"
        )

    lock_path = plan_root / ".dispatch.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prior = _prior_attempts(plan_root, task_id)
        expected_ordinal = (
            len(prior)
            if reconcile and prior and prior[-1]["terminal"] is None
            else len(prior) + 1
        )
        if expected_ordinal != ordinal:
            raise RuntimeError("Checkpoint-kernel attempt inventory changed while waiting for the dispatch lock")
        previous_attempts = [
            attempt
            for attempt in prior
            if int(attempt["submission"]["attempt_ordinal"]) == ordinal - 1
        ]
        previous_terminal_identity = previous_attempts[0]["terminal_identity"] if previous_attempts else None
        if canonical.exists():
            raise FileExistsError(f"Task acquired a canonical result while waiting for the dispatch lock: {canonical}")
        state = _load_state(state_path)
        state_entry = state["tasks"].get(task_id)
        retry_authorized = (
            retry_failed
            and prior
            and prior[-1]["terminal"] is not None
            and prior[-1]["terminal"]["status"] == "failed"
        )
        if state_entry is not None and not retry_authorized and not reconcile:
            raise RuntimeError("Mutable dispatch ledger shows this task is already active or complete")
        if reconcile and state_entry is None:
            raise RuntimeError("--reconcile requires an interrupted mutable dispatch state")
        if reconcile and state_entry is not None and state_entry.get("phase") == "submitted":
            submission_identity = state_entry.get("submission_receipt")
            release_identity = state_entry.get("release_receipt")
            if not isinstance(submission_identity, dict) or not isinstance(release_identity, dict):
                raise ValueError("Submitted mutable state lacks immutable receipt identities")
            if finalizer.validate_submission(Path(str(submission_identity["path"])))[1] != submission_identity:
                raise ValueError("Mutable state submission identity changed")
            if finalizer.validate_release_receipt(Path(str(release_identity["path"])))[1] != release_identity:
                raise ValueError("Mutable state release identity changed")
            return {
                "submission_performed": False,
                "reconciliation_performed": True,
                "task_id": task_id,
                "attempt_ordinal": state_entry["attempt_ordinal"],
                "gpu_job_id": state_entry["gpu_job_id"],
                "finalizer_job_id": state_entry["finalizer_job_id"],
                "submission_receipt": submission_identity,
                "release_receipt": release_identity,
                "resource_gate": gate,
            }
        second_gate = resource_policy_gate()
        if not second_gate["open"] and not reconcile:
            raise RuntimeError("Resource policy gate closed while waiting for the dispatch lock")
        (plan_root / "logs").mkdir(parents=True, exist_ok=True)
        gpu_identity = _write_script(script_path, gpu_content)
        dispatch_intent_path = plan_root / "dispatch_intents" / task_id / f"attempt_{ordinal:02d}.json"
        dispatch_intent: dict[str, Any] = {
            "schema_version": 1,
            "artifact_type": finalizer.DISPATCH_INTENT_ARTIFACT_TYPE,
            "study_id": plan_module.STUDY_ID,
            "plan": identities["plan"],
            "readiness": identities["readiness"],
            "task_id": task_id,
            "task_spec_sha256": task_hash,
            "control_source_sha256": plan["control_source"]["control_source_sha256"],
            "attempt_ordinal": ordinal,
            "previous_terminal_receipt": previous_terminal_identity,
            "gpu_batch_script": gpu_identity,
            "scheduler_contract": scheduler_contract,
            "gpu_sbatch_argv": gpu_command,
            "sbatch_environment_policy": SBATCH_ENVIRONMENT_POLICY,
            "pre_submit_resource_policy_gate": second_gate,
            "submission_channel": {
                "tmux_socket": str(CONTROL_SOCKET),
                "session": CONTROL_SESSION,
                "window": CONTROL_WINDOW,
            },
            "scope": {
                "scheduler_submission_performed": False,
                "gpu_will_be_held_until_receipt": True,
                "scientific_result_identified": False,
            },
        }
        dispatch_intent["payload_without_self_hash_sha256"] = finalizer.canonical_json_sha256(dispatch_intent)
        if dispatch_intent_path.is_file():
            observed_intent, dispatch_intent_identity = finalizer.read_self_hashed(
                dispatch_intent_path,
                finalizer.DISPATCH_INTENT_ARTIFACT_TYPE,
            )
            dispatch_intent["pre_submit_resource_policy_gate"] = observed_intent.get(
                "pre_submit_resource_policy_gate"
            )
            dispatch_intent["payload_without_self_hash_sha256"] = finalizer.canonical_json_sha256(
                {key: value for key, value in dispatch_intent.items() if key != "payload_without_self_hash_sha256"}
            )
            if observed_intent != dispatch_intent:
                raise ValueError("Interrupted dispatch intent differs from deterministic reconstruction")
        else:
            dispatch_intent_identity = checkpoint_probe.write_once(dispatch_intent_path, dispatch_intent)
        if not reconcile:
            state["tasks"][task_id] = {
                "phase": "dispatching",
                "attempt_ordinal": ordinal,
                "gpu_batch_script": gpu_identity,
                "comment": comment,
                "dispatch_intent": dispatch_intent_identity,
            }
            _atomic_state(state_path, state)
        reconciled_gpu_ids = _job_ids_by_comment(
            comment=comment,
            job_name=scheduler_contract["job_name"],
        )
        recorded_gpu_id = str(state_entry.get("gpu_job_id")) if state_entry and state_entry.get("gpu_job_id") else None
        if recorded_gpu_id is not None:
            if len(reconciled_gpu_ids) != 1 or reconciled_gpu_ids[0] != int(recorded_gpu_id):
                raise RuntimeError("Mutable GPU job ID differs from scheduler reconciliation")
            gpu_job_id = int(recorded_gpu_id)
        elif len(reconciled_gpu_ids) == 1:
            gpu_job_id = reconciled_gpu_ids[0]
        elif not reconciled_gpu_ids:
            gpu_job_id = _sbatch(
                gpu_command,
                cwd=control_cwd,
                comment=comment,
                job_name=scheduler_contract["job_name"],
            )
        else:
            raise RuntimeError(f"Multiple GPU jobs match the immutable dispatch intent: {reconciled_gpu_ids}")
        attempt_id = str(gpu_job_id)
        gpu_pre_release = scheduler_observation(attempt_id)
        gpu_record = gpu_pre_release["record"]
        if (
            gpu_record.get("JobName") != scheduler_contract["job_name"]
            or gpu_record.get("Account") != ACCOUNT
            or gpu_record.get("QOS") != GPU_QOS
            or gpu_record.get("Comment") != comment
            or gpu_record.get("NumNodes") != "1"
            or gpu_record.get("NumCPUs") != "16"
            or "gres/gpu=1" not in gpu_record.get("ReqTRES", "").split(",")
        ):
            raise ValueError("GPU scheduler observation differs from the dispatch contract")
        gpu_is_held = gpu_record.get("JobState") == "PENDING" and gpu_record.get("Reason") == "JobHeldUser"
        if not gpu_is_held and not reconcile:
            raise ValueError("New GPU dispatch was not held before immutable receipt creation")
        if not reconcile or not state_entry or state_entry.get("phase") == "dispatching":
            state["tasks"][task_id] = {
                "phase": "gpu_submitted_held" if gpu_is_held else "gpu_reconciled_unheld",
                "attempt_ordinal": ordinal,
                "gpu_job_id": attempt_id,
                "gpu_batch_script": gpu_identity,
                "comment": comment,
                "dispatch_intent": dispatch_intent_identity,
            }
            _atomic_state(state_path, state)
        attempt_root = plan_root / "attempts" / task_id / attempt_id
        attempt_root.mkdir(parents=True, exist_ok=True)
        submission_path = attempt_root / "submission_receipt.json"
        existing_release_path = attempt_root / "release_receipt.json"
        if reconcile and submission_path.is_file() and existing_release_path.is_file():
            existing_submission, submission_identity = finalizer.validate_submission(submission_path)
            _, release_identity = finalizer.validate_release_receipt(existing_release_path)
            state["tasks"][task_id] = {
                "phase": "submitted",
                "attempt_ordinal": ordinal,
                "gpu_job_id": attempt_id,
                "finalizer_job_id": existing_submission["finalizer_job_id"],
                "submission_receipt": submission_identity,
                "release_receipt": release_identity,
                "release": {"reconciled_existing_receipt": True},
            }
            _atomic_state(state_path, state)
            return {
                "submission_performed": False,
                "reconciliation_performed": True,
                "task_id": task_id,
                "attempt_ordinal": ordinal,
                "gpu_job_id": attempt_id,
                "finalizer_job_id": existing_submission["finalizer_job_id"],
                "submission_receipt": submission_identity,
                "release_receipt": release_identity,
                "resource_gate": second_gate,
            }
        finalizer_script_path = plan_root / "scripts" / task_id / f"attempt_{attempt_id}_finalizer.sbatch"
        finalizer_content = render_finalizer_script(
            plan=plan,
            submission_receipt=submission_path,
            task_id=task_id,
        )
        finalizer_identity = _write_script(finalizer_script_path, finalizer_content)
        finalizer_command = [
            "sbatch",
            "--parsable",
            f"--dependency=afterany:{attempt_id}",
            f"--comment={finalizer_comment}",
            f"--qos={CPU_QOS}",
            f"--account={ACCOUNT}",
            str(finalizer_script_path),
        ]
        finalizer_scheduler_contract = {
            "job_name": f"rsci-kc-final-{task_id}"[:128],
            "account": ACCOUNT,
            "qos": CPU_QOS,
            "nodes": 1,
            "gpus": 0,
            "cpus": 4,
            "memory": "32G",
            "time_limit": "01:00:00",
            "dependency": f"afterany:{attempt_id}",
            "comment": finalizer_comment,
        }
        finalizer_intent_path = attempt_root / "finalizer_intent.json"
        finalizer_intent: dict[str, Any] = {
            "schema_version": 1,
            "artifact_type": finalizer.FINALIZER_INTENT_ARTIFACT_TYPE,
            "study_id": plan_module.STUDY_ID,
            "dispatch_intent": dispatch_intent_identity,
            "plan": identities["plan"],
            "readiness": identities["readiness"],
            "task_id": task_id,
            "task_spec_sha256": task_hash,
            "attempt_ordinal": ordinal,
            "attempt_id": attempt_id,
            "gpu_job_id": attempt_id,
            "gpu_pre_release_scheduler": gpu_pre_release,
            "finalizer_batch_script": finalizer_identity,
            "finalizer_scheduler_contract": finalizer_scheduler_contract,
            "finalizer_sbatch_argv": finalizer_command,
            "sbatch_environment_policy": SBATCH_ENVIRONMENT_POLICY,
            "submission_channel": {
                "tmux_socket": str(CONTROL_SOCKET),
                "session": CONTROL_SESSION,
                "window": CONTROL_WINDOW,
            },
            "scope": {
                "finalizer_submission_performed": False,
                "gpu_remains_held": True,
                "scientific_result_identified": False,
            },
        }
        finalizer_intent["payload_without_self_hash_sha256"] = finalizer.canonical_json_sha256(finalizer_intent)
        if finalizer_intent_path.is_file():
            observed_finalizer_intent, finalizer_intent_identity = finalizer.read_self_hashed(
                finalizer_intent_path,
                finalizer.FINALIZER_INTENT_ARTIFACT_TYPE,
            )
            finalizer_intent["gpu_pre_release_scheduler"] = observed_finalizer_intent.get(
                "gpu_pre_release_scheduler"
            )
            gpu_pre_release = finalizer_intent["gpu_pre_release_scheduler"]
            finalizer_intent["payload_without_self_hash_sha256"] = finalizer.canonical_json_sha256(
                {key: value for key, value in finalizer_intent.items() if key != "payload_without_self_hash_sha256"}
            )
            if observed_finalizer_intent != finalizer_intent:
                raise ValueError("Interrupted finalizer intent differs from deterministic reconstruction")
        else:
            finalizer_intent_identity = checkpoint_probe.write_once(finalizer_intent_path, finalizer_intent)
        if not reconcile or not state_entry or state_entry.get("phase") in {"dispatching", "gpu_submitted_held"}:
            state["tasks"][task_id] = {
                "phase": "finalizer_dispatching",
                "attempt_ordinal": ordinal,
                "gpu_job_id": attempt_id,
                "dispatch_intent": dispatch_intent_identity,
                "finalizer_intent": finalizer_intent_identity,
            }
            _atomic_state(state_path, state)
        finalizer_job_name = f"rsci-kc-final-{task_id}"[:128]
        existing_submission = None
        if submission_path.is_file():
            existing_submission, _ = finalizer.validate_submission(submission_path)
        reconciled_finalizer_ids = _job_ids_by_comment(
            comment=finalizer_comment,
            job_name=finalizer_job_name,
        )
        recorded_finalizer_id = (
            str(existing_submission["finalizer_job_id"])
            if existing_submission is not None
            else str(state_entry.get("finalizer_job_id"))
            if state_entry and state_entry.get("finalizer_job_id")
            else None
        )
        if recorded_finalizer_id is not None:
            if reconciled_finalizer_ids and (
                len(reconciled_finalizer_ids) != 1 or reconciled_finalizer_ids[0] != int(recorded_finalizer_id)
            ):
                raise RuntimeError("Mutable finalizer job ID differs from scheduler reconciliation")
            if not reconciled_finalizer_ids and not _accounting_has_job(recorded_finalizer_id):
                raise RuntimeError("Recorded finalizer job is absent from both queue and accounting")
            finalizer_job_id = int(recorded_finalizer_id)
        elif len(reconciled_finalizer_ids) == 1:
            finalizer_job_id = reconciled_finalizer_ids[0]
        elif not reconciled_finalizer_ids:
            finalizer_job_id = _sbatch(
                finalizer_command,
                cwd=control_cwd,
                comment=finalizer_comment,
                job_name=finalizer_job_name,
            )
        else:
            raise RuntimeError(
                f"Multiple finalizer jobs match the immutable finalizer intent: {reconciled_finalizer_ids}"
            )
        if existing_submission is not None:
            finalizer_scheduler_observation = existing_submission["finalizer_scheduler_observation"]
        else:
            finalizer_scheduler_observation = scheduler_observation(str(finalizer_job_id))
            finalizer_record = finalizer_scheduler_observation["record"]
            if (
                finalizer_record.get("JobName") != finalizer_job_name
                or finalizer_record.get("Account") != ACCOUNT
                or finalizer_record.get("QOS") != CPU_QOS
                or finalizer_record.get("Comment") != finalizer_comment
                or not finalizer_record.get("Dependency", "").startswith(f"afterany:{attempt_id}")
            ):
                raise ValueError("Finalizer scheduler observation differs from the dispatch contract")
        state["tasks"][task_id] = {
            "phase": "finalizer_submitted_gpu_held",
            "attempt_ordinal": ordinal,
            "gpu_job_id": attempt_id,
            "finalizer_job_id": str(finalizer_job_id),
            "dispatch_intent": dispatch_intent_identity,
            "finalizer_intent": finalizer_intent_identity,
        }
        _atomic_state(state_path, state)
        if not submission_path.is_file() and not second_gate["open"]:
            raise RuntimeError("Resource policy gate is closed; no submission receipt or release was performed")
        log_path = plan_root / "logs" / f"{task_id}_{attempt_id}.log"
        finalizer_log_path = attempt_root / f"finalizer_{finalizer_job_id}.log"
        submission: dict[str, Any] = {
            "schema_version": 1,
            "artifact_type": finalizer.SUBMISSION_ARTIFACT_TYPE,
            "study_id": plan_module.STUDY_ID,
            "dispatch_intent": dispatch_intent_identity,
            "finalizer_intent": finalizer_intent_identity,
            "plan": identities["plan"],
            "readiness": identities["readiness"],
            "task_id": task_id,
            "task_spec_sha256": task_hash,
            "control_source_sha256": plan["control_source"]["control_source_sha256"],
            "attempt_ordinal": ordinal,
            "previous_terminal_receipt": previous_terminal_identity,
            "attempt_id": attempt_id,
            "gpu_job_id": attempt_id,
            "finalizer_job_id": str(finalizer_job_id),
            "gpu_batch_script": gpu_identity,
            "finalizer_batch_script": finalizer_identity,
            "scheduler_contract": scheduler_contract,
            "finalizer_scheduler_contract": finalizer_scheduler_contract,
            "gpu_pre_release_scheduler": gpu_pre_release,
            "finalizer_scheduler_observation": finalizer_scheduler_observation,
            "gpu_sbatch_argv": gpu_command,
            "finalizer_sbatch_argv": finalizer_command,
            "authorized_release_argv": ["scontrol", "release", attempt_id],
            "release_policy": "release only after immutable submission receipt validates",
            "sbatch_environment_policy": SBATCH_ENVIRONMENT_POLICY,
            "allocation_log_path": str(log_path),
            "finalizer_log_path": str(finalizer_log_path),
            "resource_policy_gate": second_gate,
            "paths": {
                "candidate": str(attempt_root / "candidate.json"),
                "runner_summary": str(attempt_root / "runner_summary.json"),
                "submitted_batch_script": str(attempt_root / "submitted_batch_script.sbatch"),
                "submitted_finalizer_batch_script": str(
                    attempt_root / "submitted_finalizer_batch_script.sbatch"
                ),
                "release_receipt": str(attempt_root / "release_receipt.json"),
                "terminal_receipt": str(attempt_root / "terminal_receipt.json"),
                "canonical_output": str(canonical),
            },
            "submitted_at": utc_now(),
            "submission_channel": {
                "tmux_socket": str(CONTROL_SOCKET),
                "session": CONTROL_SESSION,
                "window": CONTROL_WINDOW,
            },
            "scope": {
                "gpu_submission_performed": True,
                "finalizer_submission_performed": True,
                "gpu_held_while_receipt_was_frozen": True,
                "gpu_released": False,
                "scientific_result_identified": False,
                "canonical_output_published": False,
            },
        }
        submission["payload_without_self_hash_sha256"] = finalizer.canonical_json_sha256(submission)
        if submission_path.is_file():
            submission, submission_identity = finalizer.validate_submission(submission_path)
            if (
                submission["gpu_job_id"] != attempt_id
                or submission["finalizer_job_id"] != str(finalizer_job_id)
                or submission["dispatch_intent"] != dispatch_intent_identity
                or submission["finalizer_intent"] != finalizer_intent_identity
            ):
                raise ValueError("Interrupted immutable submission differs from reconciled jobs")
        else:
            submission_identity = checkpoint_probe.write_once(submission_path, submission)
            finalizer.validate_submission(submission_path)
        release_path = Path(submission["paths"]["release_receipt"])
        if release_path.is_file():
            _, release_identity = finalizer.validate_release_receipt(release_path)
            state["tasks"][task_id] = {
                "phase": "submitted",
                "attempt_ordinal": ordinal,
                "gpu_job_id": attempt_id,
                "finalizer_job_id": str(finalizer_job_id),
                "submission_receipt": submission_identity,
                "release_receipt": release_identity,
                "release": {"reconciled_existing_receipt": True},
            }
            _atomic_state(state_path, state)
            return {
                "submission_performed": False,
                "reconciliation_performed": True,
                "task_id": task_id,
                "attempt_ordinal": ordinal,
                "gpu_job_id": attempt_id,
                "finalizer_job_id": str(finalizer_job_id),
                "submission_receipt": submission_identity,
                "release_receipt": release_identity,
                "resource_gate": second_gate,
            }
        release_command = submission["authorized_release_argv"]
        current_gpu = scheduler_observation(attempt_id)
        already_unheld = current_gpu["record"].get("Reason") != "JobHeldUser"
        if already_unheld and not reconcile:
            raise RuntimeError("GPU job became unheld before the release receipt was materialized")
        if not already_unheld and not second_gate["open"]:
            raise RuntimeError("Resource policy gate is closed; reconciled GPU remains safely held")
        if already_unheld:
            released_stdout = ""
            released_stderr = ""
            release_mode = "protected_reconciliation_of_already_unheld_job"
            gpu_post_release = current_gpu
        else:
            released = subprocess.run(
                release_command,
                text=True,
                capture_output=True,
                check=True,
                timeout=60,
            )
            released_stdout = released.stdout
            released_stderr = released.stderr
            release_mode = "scontrol_release"
            gpu_post_release = scheduler_observation(attempt_id)
        release_record = gpu_post_release["record"]
        if release_record.get("Reason") == "JobHeldUser":
            raise RuntimeError("GPU job remains held after scontrol release")
        release_receipt: dict[str, Any] = {
            "schema_version": 1,
            "artifact_type": finalizer.RELEASE_ARTIFACT_TYPE,
            "study_id": plan_module.STUDY_ID,
            "submission": submission_identity,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "gpu_job_id": attempt_id,
            "release_command": release_command,
            "release_mode": release_mode,
            "released_at": utc_now(),
            "pre_release_scheduler": gpu_pre_release,
            "post_release_scheduler": gpu_post_release,
            "release_stdout": released_stdout,
            "release_stderr": released_stderr,
            "release_stdout_sha256": hashlib.sha256(released_stdout.encode()).hexdigest(),
            "release_stderr_sha256": hashlib.sha256(released_stderr.encode()).hexdigest(),
            "submission_channel": {
                "tmux_socket": str(CONTROL_SOCKET),
                "session": CONTROL_SESSION,
                "window": CONTROL_WINDOW,
            },
            "scope": {
                "held_job_released": True,
                "scientific_result_identified": False,
                "scheduler_mutation": True,
            },
        }
        release_receipt["payload_without_self_hash_sha256"] = finalizer.canonical_json_sha256(release_receipt)
        release_identity = checkpoint_probe.write_once(Path(submission["paths"]["release_receipt"]), release_receipt)
        finalizer.validate_release_receipt(Path(str(release_identity["path"])))
        state["tasks"][task_id] = {
            "phase": "submitted",
            "attempt_ordinal": ordinal,
            "gpu_job_id": attempt_id,
            "finalizer_job_id": str(finalizer_job_id),
            "submission_receipt": submission_identity,
            "release_receipt": release_identity,
            "release": {
                "argv": release_command,
                "released_at": utc_now(),
                "stdout_sha256": hashlib.sha256(released.stdout.encode()).hexdigest(),
                "stderr_sha256": hashlib.sha256(released.stderr.encode()).hexdigest(),
            },
        }
        _atomic_state(state_path, state)
    return {
        "submission_performed": True,
        "task_id": task_id,
        "attempt_ordinal": ordinal,
        "gpu_job_id": attempt_id,
        "finalizer_job_id": str(finalizer_job_id),
        "submission_receipt": submission_identity,
        "release_receipt": release_identity,
        "resource_gate": second_gate,
    }


def status(plan_path: Path) -> dict[str, Any]:
    plan_identity = plan_module.validate_plan(plan_path)
    _, plan = plan_module.read_canonical_json(plan_path)
    plan_root = Path(str(plan_identity["path"])).parent
    rows = []
    for task in plan["tasks"]:
        task_id = task["task_id"]
        readiness_path = plan_root / "readiness" / f"{task_id}.json"
        attempts = _prior_attempts(plan_root, task_id)
        canonical = plan_root / task["result_relative_path"]
        rows.append(
            {
                "task_id": task_id,
                "readiness": readiness_path.is_file(),
                "attempt_count": len(attempts),
                "latest_terminal_status": attempts[-1]["terminal"]["status"] if attempts and attempts[-1]["terminal"] else None,
                "canonical_output": canonical.is_file(),
            }
        )
    return {
        "plan": plan_identity,
        "tasks": rows,
        "resource_gate": resource_policy_gate(),
        "scheduler_mutation": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--plan", type=Path, required=True)
    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--plan", type=Path, required=True)
    dispatch_parser.add_argument("--readiness", type=Path, required=True)
    dispatch_parser.add_argument("--task-id", required=True)
    dispatch_parser.add_argument("--submit", action="store_true")
    dispatch_parser.add_argument("--retry-failed", action="store_true")
    dispatch_parser.add_argument("--reconcile", action="store_true")
    dispatch_parser.add_argument("--confirm-study-id")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "status":
        result = status(args.plan)
    else:
        result = dispatch(
            plan_path=args.plan,
            readiness_path=args.readiness,
            task_id=args.task_id,
            submit=args.submit,
            retry_failed=args.retry_failed,
            reconcile=args.reconcile,
            confirm_study_id=args.confirm_study_id,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
