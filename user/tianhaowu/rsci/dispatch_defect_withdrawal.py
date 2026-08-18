#!/usr/bin/env python3
"""Protected dispatch and terminal provenance for the withdrawal study."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import analyze_defect_withdrawal_eval as withdrawal_analysis
import audit_defect_withdrawal_training as withdrawal_audit
import materialize_defect_withdrawal_eval as eval_plan
import materialize_defect_withdrawal_forks as withdrawal_forks
import source_provenance

SCHEMA_VERSION = 1
STUDY_ID = eval_plan.STUDY_ID
CONTROL_TMUX = {
    "socket": "/tmp/codex-rsci-control-20260806.sock",
    "session": "codex-rsci-control-20260806",
    "window": "Launcher",
}
REQUIRED_ACCOUNT = "ram"
REQUIRED_QOS = "h100_ram_high"
TRAINING_AUTHORITY_NAME = "training_dispatch_authority.json"
TRAINING_AUTHORITY_ARTIFACT = "rsci_defect_withdrawal_training_dispatch_authority"
GLOBAL_INTENT_ARTIFACT = "rsci_defect_withdrawal_global_dispatch_intent"
BATCH_INTENT_ARTIFACT = "rsci_defect_withdrawal_batch_dispatch_intent"
TRAINING_INTENT_ARTIFACT = "rsci_defect_withdrawal_training_dispatch_intent"
TRAINING_SUBMISSION_ARTIFACT = "rsci_defect_withdrawal_training_submission_receipt"
EVAL_INTENT_ARTIFACT = "rsci_defect_withdrawal_eval_dispatch_intent"
EVAL_SUBMISSION_ARTIFACT = withdrawal_analysis.SUBMISSION_RECEIPT_ARTIFACT_TYPE
SCRIPT_REPOSITORY_PATH = Path("user/tianhaowu/rsci/dispatch_defect_withdrawal.py")
STATE_LOCK_NAME = ".dispatch.lock"
HIGH_PRIORITY_JOB_PREFIXES = (
    "rsci-vd-fcsft-",
    "rsci-vd-gstar-",
    "rsci-kc1-",
    "rsci-rl-op10-40-",
)
TRAINING_JOB_PREFIX = "rsci-vd-withdraw-"
EVAL_JOB_PREFIX = "rsci-vdw-eval-"
TRAINING_MAX_LIVE_JOBS = 3
EVAL_MAX_LIVE_JOBS = 5
SQUEUE_FORMAT = "%A|%1000k|%200j|%100a|%100q|%T|%V"
SACCT_QUERY_FORMAT = "JobIDRaw,Comment,JobName,Account,QOS,State,Submit"
TERMINAL_SACCT_FIELDS = (
    "JobIDRaw",
    "Comment",
    "JobName",
    "Account",
    "QOS",
    "State",
    "ExitCode",
    "Submit",
    "Start",
    "End",
    "ElapsedRaw",
    "Restarts",
)
TERMINAL_SACCT_FORMAT = ",".join(TERMINAL_SACCT_FIELDS)
TERMINAL_STATES = frozenset(
    {
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
)
JOB_ID_RE = re.compile(r"[1-9][0-9]*")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be RFC3339 UTC")
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _parse_slurm_time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a Slurm timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a Slurm timestamp") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _self_hashed(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, eval_plan.SELF_HASH_FIELD: eval_plan.canonical_json_sha256(payload)}


def _verify_self_hash(payload: dict[str, Any], label: str) -> None:
    recorded = payload.get(eval_plan.SELF_HASH_FIELD)
    without = {key: value for key, value in payload.items() if key != eval_plan.SELF_HASH_FIELD}
    if recorded != eval_plan.canonical_json_sha256(without):
        raise ValueError(f"{label} self hash differs")


def _clean_scheduler_environment() -> tuple[dict[str, str], list[str]]:
    environment = dict(os.environ)
    removed = sorted(key for key in environment if key.startswith("SBATCH_"))
    for key in removed:
        environment.pop(key)
    return environment, removed


def require_control_tmux() -> dict[str, str]:
    tmux_value = os.environ.get("TMUX")
    pane = os.environ.get("TMUX_PANE")
    if not tmux_value or not pane:
        raise ValueError("Actual dispatch/terminalization must run inside the protected control tmux")
    socket = tmux_value.split(",", maxsplit=1)[0]
    if socket != CONTROL_TMUX["socket"]:
        raise ValueError("Control tmux socket differs")
    try:
        controlling_tty = os.ttyname(0)
    except OSError as error:
        raise ValueError("Protected dispatch requires the control pane's interactive TTY") from error
    completed = subprocess.run(
        [
            "tmux",
            "-S",
            CONTROL_TMUX["socket"],
            "display-message",
            "-p",
            "-t",
            pane,
            "#{session_name}\t#{window_name}\t#{pane_tty}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    observed = completed.stdout.rstrip("\n").split("\t")
    if observed[:2] != [CONTROL_TMUX["session"], CONTROL_TMUX["window"]]:
        raise ValueError(f"Control tmux target differs: {observed!r}")
    if len(observed) != 3 or os.path.realpath(observed[2]) != os.path.realpath(controlling_tty):
        raise ValueError("Current process TTY differs from the protected control pane")
    return {**CONTROL_TMUX, "pane_tty": observed[2]}


def parse_scheduler_rows(output: str, *, source: str) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split("|")]
        if len(fields) < 7 or JOB_ID_RE.fullmatch(fields[0]) is None:
            raise ValueError(f"Malformed {source} scheduler row {line_number}: {line!r}")
        records.append(
            {
                "job_id": fields[0],
                "comment": fields[1],
                "job_name": fields[2],
                "account": fields[3],
                "qos": fields[4],
                "state": fields[5],
                "submit_time": fields[6],
                "source": source,
            }
        )
    return records


def live_scheduler_snapshot() -> dict[str, Any]:
    command = ["squeue", "--noheader", f"--format={SQUEUE_FORMAT}"]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    return {
        "queried_at": utc_now(),
        "command": command,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "records": parse_scheduler_rows(completed.stdout, source="squeue"),
    }


def enforce_resource_gate(
    snapshot: dict[str, Any],
    *,
    phase: str,
    selected_new_count: int,
) -> dict[str, Any]:
    if phase not in {"training", "eval"}:
        raise ValueError(f"Unknown dispatch phase: {phase}")
    higher_priority = [
        record for record in snapshot["records"] if record["job_name"].startswith(HIGH_PRIORITY_JOB_PREFIXES)
    ]
    if higher_priority:
        raise RuntimeError(
            "Withdrawal resource gate is closed by higher-priority jobs: "
            + ", ".join(f"{record['job_id']}:{record['job_name']}" for record in higher_priority)
        )
    prefix = TRAINING_JOB_PREFIX if phase == "training" else EVAL_JOB_PREFIX
    maximum = TRAINING_MAX_LIVE_JOBS if phase == "training" else EVAL_MAX_LIVE_JOBS
    live = [record for record in snapshot["records"] if record["job_name"].startswith(prefix)]
    projected = len(live) + selected_new_count
    if projected > maximum:
        raise RuntimeError(f"Withdrawal {phase} live-job cap exceeded: {len(live)} + {selected_new_count} > {maximum}")
    return {
        "phase": phase,
        "blocked_job_prefixes": list(HIGH_PRIORITY_JOB_PREFIXES),
        "higher_priority_live_count": 0,
        "max_live_jobs": maximum,
        "live_count": len(live),
        "selected_new_count": selected_new_count,
        "projected_live_count": projected,
        "scheduler_snapshot": snapshot,
    }


def _reject_live_job_names(snapshot: dict[str, Any], job_names: set[str]) -> None:
    collisions = [
        record for record in snapshot["records"] if record["job_name"] in job_names
    ]
    if collisions:
        raise RuntimeError(
            "Selected scheduler job name is already live: "
            + ", ".join(f"{record['job_id']}:{record['job_name']}" for record in collisions)
        )


def scheduler_snapshot_for_names(job_names: list[str], *, since: datetime) -> dict[str, Any]:
    name_filter = ",".join(sorted(set(job_names)))
    start = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    squeue_command = ["squeue", "--noheader", "--name", name_filter, f"--format={SQUEUE_FORMAT}"]
    sacct_command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--name",
        name_filter,
        "--starttime",
        start,
        f"--format={SACCT_QUERY_FORMAT}",
    ]
    squeue = subprocess.run(squeue_command, check=True, capture_output=True, text=True, timeout=60)
    sacct = subprocess.run(sacct_command, check=True, capture_output=True, text=True, timeout=60)
    records = parse_scheduler_rows(squeue.stdout, source="squeue")
    records.extend(parse_scheduler_rows(sacct.stdout, source="sacct"))
    return {
        "queried_at": utc_now(),
        "start_time": start,
        "squeue_command": squeue_command,
        "squeue_stdout_sha256": hashlib.sha256(squeue.stdout.encode()).hexdigest(),
        "sacct_command": sacct_command,
        "sacct_stdout_sha256": hashlib.sha256(sacct.stdout.encode()).hexdigest(),
        "records": records,
    }


def _submitted_script_sha256(job_id: str) -> str:
    completed = subprocess.run(
        ["scontrol", "write", "batch_script", job_id, "-"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    if not completed.stdout:
        raise ValueError(f"Scheduler returned an empty submitted script for job {job_id}")
    return hashlib.sha256(completed.stdout).hexdigest()


def verify_scheduler_job(
    job_id: str,
    *,
    comment: str,
    job_name: str,
    sbatch_sha256: str,
) -> dict[str, Any]:
    command = ["scontrol", "show", "job", job_id, "--oneliner"]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    fields = {}
    for name in ("Comment", "JobName", "Account", "QOS"):
        match = re.search(rf"(?:^|\s){name}=(\S+)", completed.stdout)
        if match is None:
            raise ValueError(f"Scheduler job {job_id} has no {name}")
        fields[name] = match.group(1)
    observed_script = _submitted_script_sha256(job_id)
    if (
        fields["Comment"] != comment
        or fields["JobName"] != job_name
        or fields["Account"] != REQUIRED_ACCOUNT
        or fields["QOS"] != REQUIRED_QOS
        or observed_script != sbatch_sha256
    ):
        raise ValueError(f"Scheduler identity differs for job {job_id}")
    return {
        "command": command,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "submitted_batch_script_sha256": observed_script,
        "record": {
            "job_id": job_id,
            "comment": comment,
            "job_name": job_name,
            "account": REQUIRED_ACCOUNT,
            "qos": REQUIRED_QOS,
        },
    }


def _parse_terminal_allocation_stdout(stdout: str, *, job_id: str) -> dict[str, Any]:
    rows = [line.split("|") for line in stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) < len(TERMINAL_SACCT_FIELDS):
        raise ValueError(f"Scheduler returned an ambiguous terminal allocation for job {job_id}")
    raw = {
        field: value.strip()
        for field, value in zip(TERMINAL_SACCT_FIELDS, rows[0][: len(TERMINAL_SACCT_FIELDS)], strict=True)
    }
    return {
        "job_id": raw["JobIDRaw"],
        "comment": raw["Comment"],
        "job_name": raw["JobName"],
        "account": raw["Account"],
        "qos": raw["QOS"],
        "state": raw["State"].split(maxsplit=1)[0].rstrip("+"),
        "exit_code": raw["ExitCode"],
        "submit_time": raw["Submit"],
        "start_time": raw["Start"],
        "end_time": raw["End"],
        "elapsed_seconds": int(raw["ElapsedRaw"]),
        "restart_count": int(raw["Restarts"]),
    }


def terminal_allocation(job_id: str, *, expected: dict[str, Any]) -> dict[str, Any]:
    command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--jobs",
        job_id,
        f"--format={TERMINAL_SACCT_FORMAT}",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    record = _parse_terminal_allocation_stdout(completed.stdout, job_id=job_id)
    for field in ("job_id", "comment", "job_name", "account", "qos"):
        if record[field] != expected[field]:
            raise ValueError(f"Terminal allocation {field} differs for job {job_id}")
    if record["state"] not in TERMINAL_STATES:
        raise ValueError(f"Scheduler job {job_id} is not terminal: {record['state']}")
    script_sha256 = _submitted_script_sha256(job_id)
    if script_sha256 != expected["submitted_batch_script_sha256"]:
        raise ValueError(f"Submitted script changed for terminal job {job_id}")
    return {
        "queried_at": utc_now(),
        "command": command,
        "stdout": completed.stdout,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "record": record,
        "submitted_batch_script_sha256": script_sha256,
    }


def _assert_job_not_live(job_id: str) -> None:
    completed = subprocess.run(
        ["squeue", "--noheader", "--jobs", job_id, f"--format={SQUEUE_FORMAT}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0 and "Invalid job id specified" not in completed.stderr:
        raise RuntimeError(f"squeue failed for job {job_id}: {completed.stderr.strip()}")
    if completed.returncode == 0 and completed.stdout.strip():
        raise RuntimeError(f"Scheduler job {job_id} remains live")


def _validate_snapshot_record(snapshot: dict[str, Any]) -> None:
    if set(snapshot) != {"queried_at", "command", "stdout_sha256", "records"}:
        raise ValueError("Scheduler baseline record has the wrong schema")
    _parse_utc(snapshot.get("queried_at"), "scheduler snapshot queried_at")
    if (
        snapshot.get("command") != ["squeue", "--noheader", f"--format={SQUEUE_FORMAT}"]
        or eval_plan.SHA256_RE.fullmatch(str(snapshot.get("stdout_sha256"))) is None
        or not isinstance(snapshot.get("records"), list)
    ):
        raise ValueError("Scheduler baseline record is invalid")
    expected_record_fields = {
        "job_id",
        "comment",
        "job_name",
        "account",
        "qos",
        "state",
        "submit_time",
        "source",
    }
    for record in snapshot["records"]:
        if (
            not isinstance(record, dict)
            or set(record) != expected_record_fields
            or JOB_ID_RE.fullmatch(str(record.get("job_id"))) is None
            or any(
                not isinstance(record.get(field), str)
                for field in ("comment", "job_name", "account", "qos", "state")
            )
            or record.get("source") != "squeue"
        ):
            raise ValueError("Scheduler snapshot contains a malformed record")
        _parse_slurm_time(record.get("submit_time"), "scheduler record submit_time")


def _training_arm_record(arm: str, *, pristine: bool) -> dict[str, Any]:
    spec = withdrawal_forks.ARMS[arm]
    root = spec.output_root.expanduser().resolve()
    manifest = root / withdrawal_forks.MANIFEST_NAME
    withdrawal_forks.validate_materialized_fork(
        manifest,
        spec=spec,
        repo_root=eval_plan.REPO_ROOT,
        require_resolved_configs=True,
        require_pristine=pristine,
    )
    source_state = source_provenance.verify_snapshot(root, require_launch=True)
    return {
        "arm": arm,
        "run_root": str(root),
        "job_name": spec.job_name,
        "fork_manifest": eval_plan.file_identity(manifest),
        "source_provenance": eval_plan.file_identity(root / source_provenance.MANIFEST_NAME),
        "source_snapshot": {
            key: source_state[key]
            for key in ("snapshot_path", "parent_commit_sha", "source_tree_sha256", "launch_artifacts_sha256")
        },
        "sbatch": eval_plan.file_identity(root / "rl.sbatch"),
    }


def build_training_authority(
    eval_authority_path: Path,
    baseline: dict[str, Any],
    *,
    created_at: str,
) -> dict[str, Any]:
    eval_authority = eval_plan.validate_authority(eval_authority_path)
    _validate_snapshot_record(baseline)
    arms = [_training_arm_record(arm, pristine=True) for arm in ("p05_on", "p05_off", "p00_clean")]
    names = {arm["job_name"] for arm in arms}
    if any(record["job_name"] in names for record in baseline["records"]):
        raise ValueError("Training authority must precede every withdrawal scheduler job")
    dispatcher = eval_plan.file_identity(Path(__file__))
    expected_dispatcher = {
        field: eval_authority["implementations"]["dispatcher"][field] for field in ("path", "size_bytes", "sha256")
    }
    if dispatcher != expected_dispatcher:
        raise ValueError("Dispatcher differs from the evaluation authority")
    root = Path(eval_authority["eval_root"])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": TRAINING_AUTHORITY_ARTIFACT,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "eval_authority": eval_plan.file_identity(eval_authority_path),
        "dispatcher": dispatcher,
        "control_tmux": dict(CONTROL_TMUX),
        "resource_policy": {
            "blocked_job_prefixes": list(HIGH_PRIORITY_JOB_PREFIXES),
            "training_max_live_jobs": TRAINING_MAX_LIVE_JOBS,
            "eval_max_live_jobs": EVAL_MAX_LIVE_JOBS,
            "required_account": REQUIRED_ACCOUNT,
            "required_qos": REQUIRED_QOS,
        },
        "pretraining_scheduler_baseline": baseline,
        "arms": arms,
        "state_root": str((root / "control" / "training").resolve()),
    }
    return _self_hashed(payload)


def materialize_training_authority(eval_authority_path: Path) -> Path:
    eval_authority = eval_plan.validate_authority(eval_authority_path)
    path = Path(eval_authority["eval_root"]) / TRAINING_AUTHORITY_NAME
    if path.exists():
        validate_training_authority(path)
        return path
    baseline = live_scheduler_snapshot()
    authority = build_training_authority(eval_authority_path, baseline, created_at=utc_now())
    eval_plan._write_once(path, eval_plan.canonical_json_bytes(authority))
    validate_training_authority(path)
    return path


def validate_training_authority(path: Path) -> dict[str, Any]:
    _, authority = eval_plan._read_json(path)
    _verify_self_hash(authority, "Training dispatch authority")
    if (
        authority.get("schema_version") != SCHEMA_VERSION
        or authority.get("artifact_type") != TRAINING_AUTHORITY_ARTIFACT
        or authority.get("study_id") != STUDY_ID
        or authority.get("control_tmux") != CONTROL_TMUX
    ):
        raise ValueError("Training dispatch authority identity differs")
    eval_authority_path = Path(authority["eval_authority"]["path"])
    eval_authority = eval_plan.validate_authority(eval_authority_path)
    if eval_plan.file_identity(eval_authority_path) != authority["eval_authority"]:
        raise ValueError("Evaluation authority changed after training authority freeze")
    expected_dispatcher = {
        field: eval_authority["implementations"]["dispatcher"][field] for field in ("path", "size_bytes", "sha256")
    }
    if (
        authority.get("dispatcher") != expected_dispatcher
        or eval_plan.file_identity(Path(__file__)) != expected_dispatcher
    ):
        raise ValueError("Training authority dispatcher changed")
    _parse_utc(authority.get("created_at"), "training authority created_at")
    _validate_snapshot_record(authority.get("pretraining_scheduler_baseline", {}))
    expected_policy = {
        "blocked_job_prefixes": list(HIGH_PRIORITY_JOB_PREFIXES),
        "training_max_live_jobs": TRAINING_MAX_LIVE_JOBS,
        "eval_max_live_jobs": EVAL_MAX_LIVE_JOBS,
        "required_account": REQUIRED_ACCOUNT,
        "required_qos": REQUIRED_QOS,
    }
    if authority.get("resource_policy") != expected_policy:
        raise ValueError("Training authority resource policy differs")
    recorded_arms = authority.get("arms")
    if not isinstance(recorded_arms, list) or {arm.get("arm") for arm in recorded_arms} != {
        "p05_on",
        "p05_off",
        "p00_clean",
    }:
        raise ValueError("Training authority arm inventory differs")
    for recorded in recorded_arms:
        current = _training_arm_record(recorded["arm"], pristine=False)
        if recorded != current:
            raise ValueError(f"Training arm changed after authority freeze: {recorded['arm']}")
    expected_path = Path(eval_authority["eval_root"]) / TRAINING_AUTHORITY_NAME
    if path.expanduser().resolve() != expected_path.resolve():
        raise ValueError(f"Training authority must be at {expected_path}")
    return authority


def _arm_by_name(authority: dict[str, Any], arm: str) -> dict[str, Any]:
    matches = [record for record in authority["arms"] if record["arm"] == arm]
    if len(matches) != 1:
        raise ValueError(f"Training arm lookup differs: {arm}")
    return matches[0]


def _state_paths(state_root: Path, key: str, attempt: int = 1) -> dict[str, Path]:
    root = state_root / key / f"attempt_{attempt:04d}"
    return {
        "root": root,
        "intent": root / "dispatch_intent.json",
        "receipt": root / "submission_receipt.json",
        "allocation": root / "allocation.log",
    }


def _global_intent(state_root: Path, authority_identity: dict[str, Any], phase: str) -> Path:
    path = state_root / "global_dispatch_intent.json"
    payload = _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": GLOBAL_INTENT_ARTIFACT,
            "study_id": STUDY_ID,
            "phase": phase,
            "authority": authority_identity,
            "control_tmux": dict(CONTROL_TMUX),
        }
    )
    eval_plan._write_once(path, eval_plan.canonical_json_bytes(payload))
    return path


def _comment(identity: dict[str, Any]) -> str:
    return eval_plan.canonical_json_sha256(identity)


def _training_comment_identity(
    *,
    authority: dict[str, Any],
    arm: str,
    sbatch: dict[str, Any],
    job_name: str,
    batch_intent: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        "authority": authority,
        "arm": arm,
        "sbatch": sbatch,
        "job_name": job_name,
        "batch_intent": batch_intent,
        "created_at": created_at,
    }


def _eval_comment_identity(
    *,
    plan: dict[str, Any],
    task_id: str,
    attempt: int,
    sbatch: dict[str, Any],
    batch_intent: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    return {
        "plan": plan,
        "task_id": task_id,
        "attempt": attempt,
        "sbatch": sbatch,
        "batch_intent": batch_intent,
        "created_at": created_at,
    }


def _submission_command(sbatch: dict[str, Any], comment: str, args: list[str]) -> list[str]:
    return [
        "sbatch",
        "--parsable",
        f"--comment={comment}",
        f"--qos={REQUIRED_QOS}",
        f"--account={REQUIRED_ACCOUNT}",
        sbatch["path"],
        *args,
    ]


def _write_batch_intent(
    state_root: Path,
    *,
    authority: dict[str, Any],
    global_path: Path,
    phase: str,
    selected: list[str],
    gate: dict[str, Any],
) -> Path:
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": BATCH_INTENT_ARTIFACT,
        "study_id": STUDY_ID,
        "phase": phase,
        "authority": authority,
        "global_intent": eval_plan.file_identity(global_path),
        "selected": selected,
        "resource_gate": gate,
    }
    digest = eval_plan.canonical_json_sha256(core)
    path = state_root / "batches" / f"batch_{digest}.json"
    eval_plan._write_once(path, eval_plan.canonical_json_bytes(_self_hashed(core)))
    return path


def _validate_global_intent(
    path: Path,
    *,
    authority: dict[str, Any],
    phase: str,
    state_root: Path,
) -> dict[str, Any]:
    expected_path = (state_root / "global_dispatch_intent.json").resolve()
    if path.resolve() != expected_path:
        raise ValueError(f"Global dispatch intent must be at {expected_path}")
    _, observed = eval_plan._read_json(path)
    _verify_self_hash(observed, "Global dispatch intent")
    expected = _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": GLOBAL_INTENT_ARTIFACT,
            "study_id": STUDY_ID,
            "phase": phase,
            "authority": authority,
            "control_tmux": dict(CONTROL_TMUX),
        }
    )
    if observed != expected:
        raise ValueError("Global dispatch intent differs from its sealed authority")
    return observed


def _validate_batch_intent(
    path: Path,
    *,
    authority: dict[str, Any],
    global_path: Path,
    phase: str,
    state_root: Path,
    member: str,
    allowed: set[str],
) -> dict[str, Any]:
    _validate_global_intent(
        global_path,
        authority=authority,
        phase=phase,
        state_root=state_root,
    )
    _, observed = eval_plan._read_json(path)
    _verify_self_hash(observed, "Batch dispatch intent")
    expected_fields = {
        "schema_version",
        "artifact_type",
        "study_id",
        "phase",
        "authority",
        "global_intent",
        "selected",
        "resource_gate",
        eval_plan.SELF_HASH_FIELD,
    }
    selected = observed.get("selected")
    if (
        set(observed) != expected_fields
        or observed.get("schema_version") != SCHEMA_VERSION
        or observed.get("artifact_type") != BATCH_INTENT_ARTIFACT
        or observed.get("study_id") != STUDY_ID
        or observed.get("phase") != phase
        or observed.get("authority") != authority
        or observed.get("global_intent") != eval_plan.file_identity(global_path)
        or not isinstance(selected, list)
        or not selected
        or any(not isinstance(item, str) or item not in allowed for item in selected)
        or len(selected) != len(set(selected))
        or member not in selected
    ):
        raise ValueError("Batch dispatch intent differs from its sealed batch")
    recorded_gate = observed.get("resource_gate")
    if not isinstance(recorded_gate, dict) or not isinstance(recorded_gate.get("scheduler_snapshot"), dict):
        raise ValueError("Batch dispatch resource gate is malformed")
    _validate_snapshot_record(recorded_gate["scheduler_snapshot"])
    expected_gate = enforce_resource_gate(
        recorded_gate["scheduler_snapshot"],
        phase=phase,
        selected_new_count=len(selected),
    )
    if recorded_gate != expected_gate:
        raise ValueError("Batch dispatch resource gate differs")
    core = {key: value for key, value in observed.items() if key != eval_plan.SELF_HASH_FIELD}
    expected_path = (state_root / "batches" / f"batch_{eval_plan.canonical_json_sha256(core)}.json").resolve()
    if path.resolve() != expected_path:
        raise ValueError(f"Batch dispatch intent must be at {expected_path}")
    return observed


def _submit(command: list[str]) -> tuple[str, str, list[str]]:
    environment, removed = _clean_scheduler_environment()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    stdout = completed.stdout.strip()
    if completed.returncode != 0:
        raise RuntimeError(
            f"Ambiguous sbatch outcome; reconcile exact comment: returncode={completed.returncode}, "
            f"stdout={stdout!r}, stderr={completed.stderr.strip()!r}"
        )
    job_id = stdout.split(";", maxsplit=1)[0]
    if JOB_ID_RE.fullmatch(job_id) is None:
        raise RuntimeError(f"Ambiguous sbatch stdout; reconcile exact comment: {stdout!r}")
    return job_id, stdout, removed


def _matching_scheduler_record(intent: dict[str, Any]) -> dict[str, Any]:
    intent_created_at = _parse_utc(intent["created_at"], "dispatch intent created_at")
    since = intent_created_at - timedelta(minutes=1)
    snapshot = scheduler_snapshot_for_names([intent["scheduler"]["job_name"]], since=since)
    matches = [
        record
        for record in snapshot["records"]
        if record["comment"] == intent["comment"]
        and record["job_name"] == intent["scheduler"]["job_name"]
        and record["account"] == REQUIRED_ACCOUNT
        and record["qos"] == REQUIRED_QOS
        and _parse_slurm_time(record["submit_time"], "scheduler record submit_time") >= intent_created_at
    ]
    by_job = {record["job_id"]: record for record in matches}
    if len(by_job) != 1:
        raise RuntimeError(f"Expected exactly one scheduler match, found {len(by_job)}")
    return next(iter(by_job.values()))


def _training_intent(
    authority_path: Path,
    authority: dict[str, Any],
    arm: dict[str, Any],
    global_path: Path,
    batch_path: Path,
) -> dict[str, Any]:
    created_at = utc_now()
    authority_identity = eval_plan.file_identity(authority_path)
    batch_identity = eval_plan.file_identity(batch_path)
    comment = _comment(
        _training_comment_identity(
            authority=authority_identity,
            arm=arm["arm"],
            sbatch=arm["sbatch"],
            job_name=arm["job_name"],
            batch_intent=batch_identity,
            created_at=created_at,
        )
    )
    return _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": TRAINING_INTENT_ARTIFACT,
            "study_id": STUDY_ID,
            "phase": "training",
            "created_at": created_at,
            "authority": authority_identity,
            "global_intent": eval_plan.file_identity(global_path),
            "batch_intent": batch_identity,
            "arm": arm["arm"],
            "run_root": arm["run_root"],
            "comment": comment,
            "sbatch": arm["sbatch"],
            "scheduler": {
                "job_name": arm["job_name"],
                "account": REQUIRED_ACCOUNT,
                "qos": REQUIRED_QOS,
            },
            "command": _submission_command(arm["sbatch"], comment, []),
            "remove_all_sbatch_environment_variables": True,
        }
    )


def _bound_identity_path(identity: object, label: str) -> Path:
    if not isinstance(identity, dict) or not isinstance(identity.get("path"), str):
        raise ValueError(f"{label} must be a file identity")
    path = Path(identity["path"])
    if eval_plan.file_identity(path) != identity:
        raise ValueError(f"{label} changed")
    return path


def _validate_training_intent(
    path: Path,
    *,
    authority_path: Path,
    authority: dict[str, Any],
    arm: dict[str, Any],
) -> dict[str, Any]:
    expected_path = _state_paths(Path(authority["state_root"]), arm["arm"])["intent"].resolve()
    if path.resolve() != expected_path:
        raise ValueError(f"Training dispatch intent must be at {expected_path}")
    _, intent = eval_plan._read_json(path)
    _verify_self_hash(intent, "Training dispatch intent")
    expected_fields = {
        "schema_version",
        "artifact_type",
        "study_id",
        "phase",
        "created_at",
        "authority",
        "global_intent",
        "batch_intent",
        "arm",
        "run_root",
        "comment",
        "sbatch",
        "scheduler",
        "command",
        "remove_all_sbatch_environment_variables",
        eval_plan.SELF_HASH_FIELD,
    }
    created_at = intent.get("created_at")
    _parse_utc(created_at, "training dispatch intent created_at")
    authority_identity = eval_plan.file_identity(authority_path)
    global_path = _bound_identity_path(intent.get("global_intent"), "Training global intent")
    batch_path = _bound_identity_path(intent.get("batch_intent"), "Training batch intent")
    _validate_batch_intent(
        batch_path,
        authority=authority_identity,
        global_path=global_path,
        phase="training",
        state_root=Path(authority["state_root"]),
        member=arm["arm"],
        allowed={"p05_on", "p05_off", "p00_clean"},
    )
    expected_comment = _comment(
        _training_comment_identity(
            authority=authority_identity,
            arm=arm["arm"],
            sbatch=arm["sbatch"],
            job_name=arm["job_name"],
            batch_intent=eval_plan.file_identity(batch_path),
            created_at=str(created_at),
        )
    )
    if (
        set(intent) != expected_fields
        or intent.get("schema_version") != SCHEMA_VERSION
        or intent.get("artifact_type") != TRAINING_INTENT_ARTIFACT
        or intent.get("study_id") != STUDY_ID
        or intent.get("phase") != "training"
        or intent.get("authority") != authority_identity
        or intent.get("arm") != arm["arm"]
        or intent.get("run_root") != arm["run_root"]
        or intent.get("comment") != expected_comment
        or intent.get("sbatch") != arm["sbatch"]
        or intent.get("scheduler")
        != {"job_name": arm["job_name"], "account": REQUIRED_ACCOUNT, "qos": REQUIRED_QOS}
        or intent.get("command") != _submission_command(arm["sbatch"], expected_comment, [])
        or intent.get("remove_all_sbatch_environment_variables") is not True
    ):
        raise ValueError("Training dispatch intent differs from the sealed arm")
    return intent


def _validate_submission_mode(
    *,
    source: object,
    stdout: object,
    job_id: str,
    removed_sbatch_variables: object | None = None,
) -> None:
    if source not in {"sbatch_stdout", "scheduler_reconciliation"}:
        raise ValueError(f"Unknown submission source: {source}")
    if JOB_ID_RE.fullmatch(job_id) is None:
        raise ValueError(f"Invalid scheduler job ID: {job_id}")
    if source == "sbatch_stdout":
        if (
            not isinstance(stdout, str)
            or re.fullmatch(rf"{re.escape(job_id)}(?:;[^;\s]+)?", stdout) is None
        ):
            raise ValueError("Direct submission has invalid sbatch stdout")
        if removed_sbatch_variables is not None and (
            not isinstance(removed_sbatch_variables, list)
            or any(not isinstance(item, str) or not item.startswith("SBATCH_") for item in removed_sbatch_variables)
            or removed_sbatch_variables != sorted(set(removed_sbatch_variables))
        ):
            raise ValueError("Direct submission has invalid removed SBATCH variables")
    elif stdout is not None or removed_sbatch_variables not in (None, []):
        raise ValueError("Reconciled submission cannot claim direct sbatch output")


def _training_submission_receipt(
    intent_path: Path,
    intent: dict[str, Any],
    *,
    job_id: str,
    sbatch_stdout: str | None,
    source: str,
    removed_sbatch_variables: list[str],
) -> dict[str, Any]:
    _validate_submission_mode(
        source=source,
        stdout=sbatch_stdout,
        job_id=job_id,
        removed_sbatch_variables=removed_sbatch_variables,
    )
    verification = verify_scheduler_job(
        job_id,
        comment=intent["comment"],
        job_name=intent["scheduler"]["job_name"],
        sbatch_sha256=intent["sbatch"]["sha256"],
    )
    return _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": TRAINING_SUBMISSION_ARTIFACT,
            "study_id": STUDY_ID,
            "arm": intent["arm"],
            "dispatch_intent": eval_plan.file_identity(intent_path),
            "job_id": job_id,
            "comment": intent["comment"],
            "sbatch": intent["sbatch"],
            "submitted_at": utc_now(),
            "source": source,
            "sbatch_stdout": sbatch_stdout,
            "removed_sbatch_environment_variables": removed_sbatch_variables,
            "scheduler_verification": verification,
        }
    )


def _validate_training_submission(
    path: Path,
    *,
    authority_path: Path,
    authority: dict[str, Any],
    arm: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = _state_paths(Path(authority["state_root"]), arm["arm"])
    if path.resolve() != paths["receipt"].resolve():
        raise ValueError(f"Training submission receipt must be at {paths['receipt'].resolve()}")
    intent = _validate_training_intent(
        paths["intent"],
        authority_path=authority_path,
        authority=authority,
        arm=arm,
    )
    _, receipt = eval_plan._read_json(path)
    _verify_self_hash(receipt, "Training submission receipt")
    expected_fields = {
        "schema_version",
        "artifact_type",
        "study_id",
        "arm",
        "dispatch_intent",
        "job_id",
        "comment",
        "sbatch",
        "submitted_at",
        "source",
        "sbatch_stdout",
        "removed_sbatch_environment_variables",
        "scheduler_verification",
        eval_plan.SELF_HASH_FIELD,
    }
    job_id = receipt.get("job_id")
    if not isinstance(job_id, str):
        raise ValueError("Training receipt job ID is invalid")
    _validate_submission_mode(
        source=receipt.get("source"),
        stdout=receipt.get("sbatch_stdout"),
        job_id=job_id,
        removed_sbatch_variables=receipt.get("removed_sbatch_environment_variables"),
    )
    submitted_at = _parse_utc(receipt.get("submitted_at"), "training receipt submitted_at")
    if submitted_at < _parse_utc(intent["created_at"], "training intent created_at"):
        raise ValueError("Training receipt predates its dispatch intent")
    verification = receipt.get("scheduler_verification")
    expected_scheduler_record = {
        "job_id": job_id,
        "comment": intent["comment"],
        "job_name": arm["job_name"],
        "account": REQUIRED_ACCOUNT,
        "qos": REQUIRED_QOS,
    }
    if (
        set(receipt) != expected_fields
        or receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("artifact_type") != TRAINING_SUBMISSION_ARTIFACT
        or receipt.get("study_id") != STUDY_ID
        or receipt.get("arm") != arm["arm"]
        or receipt.get("dispatch_intent") != eval_plan.file_identity(paths["intent"])
        or receipt.get("comment") != intent["comment"]
        or receipt.get("sbatch") != arm["sbatch"]
        or not isinstance(verification, dict)
        or set(verification) != {"command", "stdout_sha256", "submitted_batch_script_sha256", "record"}
        or verification.get("command") != ["scontrol", "show", "job", job_id, "--oneliner"]
        or eval_plan.SHA256_RE.fullmatch(str(verification.get("stdout_sha256"))) is None
        or verification.get("submitted_batch_script_sha256") != arm["sbatch"]["sha256"]
        or verification.get("record") != expected_scheduler_record
    ):
        raise ValueError("Training submission receipt differs from its protected dispatch")
    return intent, receipt


def dispatch_training(
    authority_path: Path,
    arms: list[str],
    *,
    dry_run: bool,
    confirm_study_id: str | None,
) -> dict[str, Any]:
    authority = validate_training_authority(authority_path)
    selected = list(dict.fromkeys(arms))
    if not selected or any(arm not in {"p05_on", "p05_off", "p00_clean"} for arm in selected):
        raise ValueError("Training dispatch requires one to three exact arm names")
    state_root = Path(authority["state_root"])
    state_root.mkdir(parents=True, exist_ok=True)
    with (state_root / STATE_LOCK_NAME).open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        for arm in selected:
            paths = _state_paths(state_root, arm)
            if paths["intent"].exists() or paths["receipt"].exists():
                raise ValueError(f"Training arm already has protected dispatch state: {arm}")
        arm_records = [_arm_by_name(authority, arm) for arm in selected]
        for arm in arm_records:
            if _training_arm_record(arm["arm"], pristine=True) != arm:
                raise ValueError(f"Training arm is no longer pristine: {arm['arm']}")
        if not dry_run:
            if confirm_study_id != STUDY_ID:
                raise ValueError(f"Actual training dispatch requires --confirm-study-id {STUDY_ID}")
            require_control_tmux()
        snapshot = live_scheduler_snapshot()
        _reject_live_job_names(snapshot, {arm["job_name"] for arm in arm_records})
        gate = enforce_resource_gate(snapshot, phase="training", selected_new_count=len(selected))
        preview = []
        authority_identity = eval_plan.file_identity(authority_path)
        if dry_run:
            for arm in arm_records:
                preview.append(
                    {
                        "arm": arm["arm"],
                        "comment": "<bound-to-immutable-batch-at-dispatch>",
                        "command": shlex.join(
                            _submission_command(
                                arm["sbatch"],
                                "<bound-to-immutable-batch-at-dispatch>",
                                [],
                            )
                        ),
                    }
                )
            return {"dry_run": True, "resource_gate": gate, "submissions": preview}
        global_path = _global_intent(state_root, authority_identity, "training")
        batch_path = _write_batch_intent(
            state_root,
            authority=authority_identity,
            global_path=global_path,
            phase="training",
            selected=selected,
            gate=gate,
        )
        intents = []
        for arm in arm_records:
            paths = _state_paths(state_root, arm["arm"])
            intent = _training_intent(authority_path, authority, arm, global_path, batch_path)
            eval_plan._write_once(paths["intent"], eval_plan.canonical_json_bytes(intent))
            _validate_training_intent(
                paths["intent"],
                authority_path=authority_path,
                authority=authority,
                arm=arm,
            )
            intents.append((arm, paths, intent))
        pre_submit = live_scheduler_snapshot()
        _reject_live_job_names(pre_submit, {arm["job_name"] for arm in arm_records})
        enforce_resource_gate(pre_submit, phase="training", selected_new_count=len(selected))
        receipts = []
        for arm, paths, intent in intents:
            job_id, stdout, removed = _submit(intent["command"])
            receipt = _training_submission_receipt(
                paths["intent"],
                intent,
                job_id=job_id,
                sbatch_stdout=stdout,
                source="sbatch_stdout",
                removed_sbatch_variables=removed,
            )
            eval_plan._write_once(paths["receipt"], eval_plan.canonical_json_bytes(receipt))
            _validate_training_submission(
                paths["receipt"],
                authority_path=authority_path,
                authority=authority,
                arm=arm,
            )
            receipts.append(receipt)
        return {"dry_run": False, "receipts": receipts}


def reconcile_training(
    authority_path: Path,
    arms: list[str],
    *,
    confirm_study_id: str,
) -> dict[str, Any]:
    if confirm_study_id != STUDY_ID:
        raise ValueError(f"Training reconciliation requires --confirm-study-id {STUDY_ID}")
    selected = list(dict.fromkeys(arms))
    if not selected or len(selected) != len(arms) or any(
        arm not in {"p05_on", "p05_off", "p00_clean"} for arm in selected
    ):
        raise ValueError("Training reconciliation requires unique exact arm names")
    require_control_tmux()
    authority = validate_training_authority(authority_path)
    state_root = Path(authority["state_root"])
    receipts = []
    with (state_root / STATE_LOCK_NAME).open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        for arm in selected:
            paths = _state_paths(state_root, arm)
            if not paths["intent"].is_file() or paths["receipt"].exists():
                raise ValueError(f"Training arm is not pending reconciliation: {arm}")
            arm_record = _arm_by_name(authority, arm)
            intent = _validate_training_intent(
                paths["intent"],
                authority_path=authority_path,
                authority=authority,
                arm=arm_record,
            )
            record = _matching_scheduler_record(intent)
            receipt = _training_submission_receipt(
                paths["intent"],
                intent,
                job_id=record["job_id"],
                sbatch_stdout=None,
                source="scheduler_reconciliation",
                removed_sbatch_variables=[],
            )
            eval_plan._write_once(paths["receipt"], eval_plan.canonical_json_bytes(receipt))
            _validate_training_submission(
                paths["receipt"],
                authority_path=authority_path,
                authority=authority,
                arm=arm_record,
            )
            receipts.append(receipt)
    return {"receipts": receipts}


def _load_training_submission(
    authority_path: Path,
    authority: dict[str, Any],
    arm: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    arm_record = _arm_by_name(authority, arm)
    paths = _state_paths(Path(authority["state_root"]), arm)
    intent, receipt = _validate_training_submission(
        paths["receipt"],
        authority_path=authority_path,
        authority=authority,
        arm=arm_record,
    )
    return intent, receipt, paths


def terminalize_training(
    authority_path: Path,
    arms: list[str],
    *,
    confirm_study_id: str,
) -> dict[str, Any]:
    if confirm_study_id != STUDY_ID:
        raise ValueError(f"Training terminalization requires --confirm-study-id {STUDY_ID}")
    selected = list(dict.fromkeys(arms))
    if not selected or len(selected) != len(arms) or any(
        arm not in {"p05_on", "p05_off", "p00_clean"} for arm in selected
    ):
        raise ValueError("Training terminalization requires unique exact arm names")
    require_control_tmux()
    authority = validate_training_authority(authority_path)
    outputs = []
    for arm in selected:
        arm_record = _arm_by_name(authority, arm)
        intent, receipt, paths = _load_training_submission(authority_path, authority, arm)
        job_id = str(receipt["job_id"])
        _assert_job_not_live(job_id)
        expected = {
            "job_id": job_id,
            "comment": intent["comment"],
            "job_name": arm_record["job_name"],
            "account": REQUIRED_ACCOUNT,
            "qos": REQUIRED_QOS,
            "submitted_batch_script_sha256": arm_record["sbatch"]["sha256"],
        }
        allocation = terminal_allocation(job_id, expected=expected)
        if allocation["record"]["state"] != "COMPLETED" or allocation["record"]["exit_code"] != "0:0":
            raise ValueError(f"Training allocation did not complete successfully: {arm}/{job_id}")
        if allocation["record"]["restart_count"] != 0:
            raise ValueError(f"Training allocation restarted and invalidated the task cursor: {arm}/{job_id}")
        eval_plan._write_once(paths["allocation"], allocation["stdout"].encode())
        ledger_audit_path = withdrawal_audit.materialize_audit(
            arm,
            Path(arm_record["run_root"]),
        )
        checkpoints = {
            str(step): eval_plan.directory_identity(Path(arm_record["run_root"]) / "weights" / f"step_{step}")
            for step in (eval_plan.SOURCE_STEP, eval_plan.INTERMEDIATE_STEP, eval_plan.FINAL_STEP)
        }
        scheduler = {
            key: allocation["record"][key]
            for key in (
                "job_id",
                "comment",
                "job_name",
                "account",
                "qos",
                "state",
                "exit_code",
                "restart_count",
            )
        }
        scheduler["submitted_batch_script_sha256"] = allocation["submitted_batch_script_sha256"]
        payload = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": eval_plan.TRAINING_TERMINAL_ARTIFACT_TYPE,
            "study_id": STUDY_ID,
            "arm": arm,
            "run_root": arm_record["run_root"],
            "dispatch_authority": eval_plan.file_identity(authority_path),
            "dispatch_intent": eval_plan.file_identity(paths["intent"]),
            "fork_manifest": arm_record["fork_manifest"],
            "source_provenance": arm_record["source_provenance"],
            "rl_sbatch": arm_record["sbatch"],
            "submission_receipt": eval_plan.file_identity(paths["receipt"]),
            "allocation_log": eval_plan.file_identity(paths["allocation"]),
            "training_ledger_audit": eval_plan.file_identity(ledger_audit_path),
            "scheduler": scheduler,
            "checkpoints": checkpoints,
        }
        provenance = _self_hashed(payload)
        output = Path(arm_record["run_root"]) / eval_plan.TRAINING_TERMINAL_NAME
        eval_plan._write_once(output, eval_plan.canonical_json_bytes(provenance))
        eval_plan._validate_training_terminal_provenance(
            arm=arm,
            root=Path(arm_record["run_root"]),
            fork_manifest=arm_record["fork_manifest"],
            source_manifest=arm_record["source_provenance"],
            rl_sbatch=arm_record["sbatch"],
            checkpoints=checkpoints,
        )
        outputs.append(eval_plan.file_identity(output))
    return {"training_terminal_provenance": outputs}


def _eval_state_root(plan: dict[str, Any]) -> Path:
    return Path(plan["plan_root"]) / "dispatch"


def _eval_authority_identity(plan: dict[str, Any]) -> dict[str, Any]:
    return plan["authority"]


def _next_eval_attempt(task: dict[str, Any]) -> int:
    root = Path(task["receipt_dir"])
    receipts = sorted(root.glob("attempt_*.json")) if root.exists() else []
    if receipts:
        _, last = eval_plan._read_json(receipts[-1])
        if last.get("status") == "succeeded":
            raise ValueError(f"Evaluation task already succeeded: {task['task_id']}")
    return len(receipts) + 1


def _eval_task_intent(
    plan_path: Path,
    plan: dict[str, Any],
    task: dict[str, Any],
    attempt: int,
    global_path: Path,
    batch_path: Path,
    intent_path: Path,
) -> dict[str, Any]:
    created_at = utc_now()
    plan_identity = eval_plan.file_identity(plan_path)
    batch_identity = eval_plan.file_identity(batch_path)
    comment = _comment(
        _eval_comment_identity(
            plan=plan_identity,
            task_id=task["task_id"],
            attempt=attempt,
            sbatch=task["sbatch"],
            batch_intent=batch_identity,
            created_at=created_at,
        )
    )
    return _self_hashed(
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": EVAL_INTENT_ARTIFACT,
            "study_id": STUDY_ID,
            "phase": "eval",
            "created_at": created_at,
            "plan": plan_identity,
            "eval_authority": _eval_authority_identity(plan),
            "global_intent": eval_plan.file_identity(global_path),
            "batch_intent": batch_identity,
            "task_id": task["task_id"],
            "attempt": attempt,
            "comment": comment,
            "sbatch": task["sbatch"],
            "scheduler": {
                "job_name": task["job_name"],
                "account": REQUIRED_ACCOUNT,
                "qos": REQUIRED_QOS,
            },
            "command": _submission_command(
                task["sbatch"],
                comment,
                [str(attempt), str(intent_path.resolve())],
            ),
            "remove_all_sbatch_environment_variables": True,
        }
    )


def validate_eval_task_intent(
    path: Path,
    *,
    plan: dict[str, Any],
    task: dict[str, Any],
    attempt: int,
) -> dict[str, Any]:
    expected_path = _state_paths(
        _eval_state_root(plan) / "tasks",
        hashlib.sha256(task["task_id"].encode()).hexdigest(),
        attempt,
    )["intent"].resolve()
    if path.resolve() != expected_path:
        raise ValueError(f"Evaluation dispatch intent must be at {expected_path}")
    _, intent = eval_plan._read_json(path)
    _verify_self_hash(intent, "Evaluation dispatch intent")
    expected_fields = {
        "schema_version",
        "artifact_type",
        "study_id",
        "phase",
        "created_at",
        "plan",
        "eval_authority",
        "global_intent",
        "batch_intent",
        "task_id",
        "attempt",
        "comment",
        "sbatch",
        "scheduler",
        "command",
        "remove_all_sbatch_environment_variables",
        eval_plan.SELF_HASH_FIELD,
    }
    created_at = intent.get("created_at")
    _parse_utc(created_at, "evaluation dispatch intent created_at")
    plan_identity = eval_plan.file_identity(Path(plan["plan_path"]))
    global_path = _bound_identity_path(intent.get("global_intent"), "Evaluation global intent")
    batch_path = _bound_identity_path(intent.get("batch_intent"), "Evaluation batch intent")
    _validate_batch_intent(
        batch_path,
        authority=plan_identity,
        global_path=global_path,
        phase="eval",
        state_root=_eval_state_root(plan),
        member=task["task_id"],
        allowed={record["task_id"] for record in plan["tasks"]},
    )
    expected_comment = _comment(
        _eval_comment_identity(
            plan=plan_identity,
            task_id=task["task_id"],
            attempt=attempt,
            sbatch=task["sbatch"],
            batch_intent=eval_plan.file_identity(batch_path),
            created_at=str(created_at),
        )
    )
    if (
        set(intent) != expected_fields
        or intent.get("schema_version") != SCHEMA_VERSION
        or intent.get("artifact_type") != EVAL_INTENT_ARTIFACT
        or intent.get("study_id") != STUDY_ID
        or intent.get("phase") != "eval"
        or intent.get("plan") != plan_identity
        or intent.get("eval_authority") != plan["authority"]
        or intent.get("task_id") != task["task_id"]
        or intent.get("attempt") != attempt
        or intent.get("comment") != expected_comment
        or intent.get("sbatch") != task["sbatch"]
        or intent.get("scheduler") != {"job_name": task["job_name"], "account": REQUIRED_ACCOUNT, "qos": REQUIRED_QOS}
        or intent.get("command")
        != _submission_command(
            task["sbatch"],
            expected_comment,
            [str(attempt), str(path.resolve())],
        )
        or intent.get("remove_all_sbatch_environment_variables") is not True
    ):
        raise ValueError("Evaluation dispatch intent differs from the sealed task")
    return intent


def _eval_submission_receipt(
    plan_path: Path,
    task: dict[str, Any],
    intent_path: Path,
    intent: dict[str, Any],
    *,
    job_id: str,
    stdout: str | None,
    source: str,
) -> dict[str, Any]:
    _validate_submission_mode(source=source, stdout=stdout, job_id=job_id)
    verify_scheduler_job(
        job_id,
        comment=intent["comment"],
        job_name=task["job_name"],
        sbatch_sha256=task["sbatch"]["sha256"],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": EVAL_SUBMISSION_ARTIFACT,
        "study_id": STUDY_ID,
        "plan": eval_plan.file_identity(plan_path),
        "task_id": task["task_id"],
        "attempt": intent["attempt"],
        "job_id": job_id,
        "comment": intent["comment"],
        "sbatch": task["sbatch"],
        "dispatch_intent": eval_plan.file_identity(intent_path),
        "batch_intent": intent["batch_intent"],
        "global_intent": intent["global_intent"],
        "submitted_at": utc_now(),
        "submission_source": source,
        "sbatch_stdout": stdout,
    }


def _validate_eval_submission(
    path: Path,
    *,
    plan_path: Path,
    plan: dict[str, Any],
    task: dict[str, Any],
    intent_path: Path,
    attempt: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_path = intent_path.with_name("submission_receipt.json").resolve()
    if path.resolve() != expected_path:
        raise ValueError(f"Evaluation submission receipt must be at {expected_path}")
    intent = validate_eval_task_intent(intent_path, plan=plan, task=task, attempt=attempt)
    _, receipt = eval_plan._read_json(path)
    expected_fields = {
        "schema_version",
        "artifact_type",
        "study_id",
        "plan",
        "task_id",
        "attempt",
        "job_id",
        "comment",
        "sbatch",
        "dispatch_intent",
        "batch_intent",
        "global_intent",
        "submitted_at",
        "submission_source",
        "sbatch_stdout",
    }
    job_id = receipt.get("job_id")
    if not isinstance(job_id, str):
        raise ValueError("Evaluation receipt job ID is invalid")
    _validate_submission_mode(
        source=receipt.get("submission_source"),
        stdout=receipt.get("sbatch_stdout"),
        job_id=job_id,
    )
    submitted_at = _parse_utc(receipt.get("submitted_at"), "evaluation receipt submitted_at")
    if submitted_at < _parse_utc(intent["created_at"], "evaluation intent created_at"):
        raise ValueError("Evaluation receipt predates its dispatch intent")
    if (
        set(receipt) != expected_fields
        or receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("artifact_type") != EVAL_SUBMISSION_ARTIFACT
        or receipt.get("study_id") != STUDY_ID
        or receipt.get("plan") != eval_plan.file_identity(plan_path)
        or receipt.get("task_id") != task["task_id"]
        or receipt.get("attempt") != attempt
        or receipt.get("comment") != intent["comment"]
        or receipt.get("sbatch") != task["sbatch"]
        or receipt.get("dispatch_intent") != eval_plan.file_identity(intent_path)
        or receipt.get("batch_intent") != intent["batch_intent"]
        or receipt.get("global_intent") != intent["global_intent"]
    ):
        raise ValueError("Evaluation submission receipt differs from its protected dispatch")
    return intent, receipt


def dispatch_eval(
    plan_path: Path,
    task_ids: list[str],
    *,
    dry_run: bool,
    confirm_study_id: str | None,
) -> dict[str, Any]:
    eval_plan.validate_plan(plan_path)
    _, plan = eval_plan._read_json(plan_path)
    if eval_plan.file_identity(Path(__file__)) != {
        field: plan["implementations"]["dispatcher"][field] for field in ("path", "size_bytes", "sha256")
    }:
        raise ValueError("Evaluation dispatcher differs from the plan authority")
    task_by_id = {task["task_id"]: task for task in plan["tasks"]}
    selected = list(dict.fromkeys(task_ids))
    if (
        not selected
        or len(selected) != len(task_ids)
        or len(selected) > EVAL_MAX_LIVE_JOBS
        or any(task_id not in task_by_id for task_id in selected)
    ):
        raise ValueError("Evaluation dispatch requires one to five exact incomplete task IDs")
    state_root = _eval_state_root(plan)
    state_root.mkdir(parents=True, exist_ok=True)
    with (state_root / STATE_LOCK_NAME).open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        attempts = {task_id: _next_eval_attempt(task_by_id[task_id]) for task_id in selected}
        paths_by_task = {
            task_id: _state_paths(state_root / "tasks", hashlib.sha256(task_id.encode()).hexdigest(), attempts[task_id])
            for task_id in selected
        }
        for task_id, paths in paths_by_task.items():
            if paths["intent"].exists() or paths["receipt"].exists():
                raise ValueError(f"Evaluation attempt already has protected state: {task_id}")
        if not dry_run:
            if confirm_study_id != STUDY_ID:
                raise ValueError(f"Actual evaluation dispatch requires --confirm-study-id {STUDY_ID}")
            require_control_tmux()
        snapshot = live_scheduler_snapshot()
        selected_job_names = {task_by_id[task_id]["job_name"] for task_id in selected}
        _reject_live_job_names(snapshot, selected_job_names)
        gate = enforce_resource_gate(snapshot, phase="eval", selected_new_count=len(selected))
        if dry_run:
            preview = []
            for task_id in selected:
                task = task_by_id[task_id]
                attempt = attempts[task_id]
                comment = "<bound-to-immutable-batch-at-dispatch>"
                preview.append(
                    {
                        "task_id": task_id,
                        "attempt": attempt,
                        "comment": comment,
                        "command": shlex.join(
                            _submission_command(
                                task["sbatch"],
                                comment,
                                [str(attempt), str(paths_by_task[task_id]["intent"].resolve())],
                            )
                        ),
                    }
                )
            return {"dry_run": True, "resource_gate": gate, "submissions": preview}
        global_path = _global_intent(state_root, eval_plan.file_identity(plan_path), "eval")
        batch_path = _write_batch_intent(
            state_root,
            authority=eval_plan.file_identity(plan_path),
            global_path=global_path,
            phase="eval",
            selected=selected,
            gate=gate,
        )
        prepared = []
        for task_id in selected:
            task = task_by_id[task_id]
            paths = paths_by_task[task_id]
            intent = _eval_task_intent(
                plan_path,
                plan,
                task,
                attempts[task_id],
                global_path,
                batch_path,
                paths["intent"],
            )
            eval_plan._write_once(paths["intent"], eval_plan.canonical_json_bytes(intent))
            validate_eval_task_intent(
                paths["intent"],
                plan=plan,
                task=task,
                attempt=attempts[task_id],
            )
            prepared.append((task, paths, intent))
        pre_submit = live_scheduler_snapshot()
        _reject_live_job_names(pre_submit, selected_job_names)
        enforce_resource_gate(pre_submit, phase="eval", selected_new_count=len(selected))
        receipts = []
        for task, paths, intent in prepared:
            job_id, stdout, _ = _submit(intent["command"])
            receipt = _eval_submission_receipt(
                plan_path,
                task,
                paths["intent"],
                intent,
                job_id=job_id,
                stdout=stdout,
                source="sbatch_stdout",
            )
            eval_plan._write_once(paths["receipt"], eval_plan.canonical_json_bytes(receipt))
            _validate_eval_submission(
                paths["receipt"],
                plan_path=plan_path,
                plan=plan,
                task=task,
                intent_path=paths["intent"],
                attempt=intent["attempt"],
            )
            receipts.append(receipt)
        return {"dry_run": False, "receipts": receipts}


def validate_runtime_eval_dispatch(
    intent_path: Path,
    *,
    plan: dict[str, Any],
    task: dict[str, Any],
    attempt: int,
    job_id: str,
) -> dict[str, Any]:
    intent = validate_eval_task_intent(intent_path, plan=plan, task=task, attempt=attempt)
    receipt_path = intent_path.with_name("submission_receipt.json")
    for _ in range(60):
        if receipt_path.is_file():
            break
        time.sleep(5)
    if not receipt_path.is_file():
        raise FileNotFoundError(f"Protected evaluation submission receipt did not appear: {receipt_path}")
    _, receipt = _validate_eval_submission(
        receipt_path,
        plan_path=Path(plan["plan_path"]),
        plan=plan,
        task=task,
        intent_path=intent_path,
        attempt=attempt,
    )
    if receipt["job_id"] != job_id:
        raise ValueError("Runtime scheduler allocation differs from the protected submission receipt")
    return {
        "dispatch_intent": eval_plan.file_identity(intent_path),
        "scheduler": {
            "job_id": job_id,
            "comment": intent["comment"],
            "job_name": task["job_name"],
            "account": REQUIRED_ACCOUNT,
            "qos": REQUIRED_QOS,
            "submitted_batch_script_sha256": task["sbatch"]["sha256"],
        },
    }


def reconcile_eval(
    plan_path: Path,
    task_ids: list[str],
    *,
    confirm_study_id: str,
) -> dict[str, Any]:
    if confirm_study_id != STUDY_ID:
        raise ValueError(f"Evaluation reconciliation requires --confirm-study-id {STUDY_ID}")
    eval_plan.validate_plan(plan_path)
    _, plan = eval_plan._read_json(plan_path)
    task_by_id = {task["task_id"]: task for task in plan["tasks"]}
    selected = list(dict.fromkeys(task_ids))
    if not selected or len(selected) != len(task_ids) or any(
        task_id not in task_by_id for task_id in selected
    ):
        raise ValueError("Evaluation reconciliation requires unique exact task IDs")
    require_control_tmux()
    state_root = _eval_state_root(plan)
    receipts = []
    with (state_root / STATE_LOCK_NAME).open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        for task_id in selected:
            task = task_by_id[task_id]
            attempts = sorted((state_root / "tasks" / hashlib.sha256(task_id.encode()).hexdigest()).glob("attempt_*"))
            if not attempts:
                raise ValueError(f"Evaluation task has no pending dispatch: {task_id}")
            paths = {
                "intent": attempts[-1] / "dispatch_intent.json",
                "receipt": attempts[-1] / "submission_receipt.json",
            }
            if not paths["intent"].is_file() or paths["receipt"].exists():
                raise ValueError(f"Evaluation task is not pending reconciliation: {task_id}")
            try:
                attempt = int(attempts[-1].name.removeprefix("attempt_"))
            except ValueError as error:
                raise ValueError(f"Malformed evaluation attempt directory: {attempts[-1]}") from error
            intent = validate_eval_task_intent(
                paths["intent"],
                plan=plan,
                task=task,
                attempt=attempt,
            )
            record = _matching_scheduler_record(intent)
            receipt = _eval_submission_receipt(
                plan_path,
                task,
                paths["intent"],
                intent,
                job_id=record["job_id"],
                stdout=None,
                source="scheduler_reconciliation",
            )
            eval_plan._write_once(paths["receipt"], eval_plan.canonical_json_bytes(receipt))
            _validate_eval_submission(
                paths["receipt"],
                plan_path=plan_path,
                plan=plan,
                task=task,
                intent_path=paths["intent"],
                attempt=attempt,
            )
            receipts.append(receipt)
    return {"receipts": receipts}


def _eval_submission_records(plan: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    state_root = _eval_state_root(plan) / "tasks"
    records = {}
    for task in plan["tasks"]:
        task_root = state_root / hashlib.sha256(task["task_id"].encode()).hexdigest()
        if not task_root.exists():
            continue
        for attempt_root in sorted(task_root.glob("attempt_*")):
            try:
                attempt = int(attempt_root.name.removeprefix("attempt_"))
            except ValueError as error:
                raise ValueError(f"Malformed evaluation attempt directory: {attempt_root}") from error
            if attempt_root.name != f"attempt_{attempt:04d}" or attempt < 1:
                raise ValueError(f"Malformed evaluation attempt directory: {attempt_root}")
            intent_path = attempt_root / "dispatch_intent.json"
            receipt_path = attempt_root / "submission_receipt.json"
            if not intent_path.is_file() or not receipt_path.is_file():
                raise ValueError(f"Evaluation dispatch state is incomplete: {attempt_root}")
            intent, receipt = _validate_eval_submission(
                receipt_path,
                plan_path=Path(plan["plan_path"]),
                plan=plan,
                task=task,
                intent_path=intent_path,
                attempt=attempt,
            )
            key = (task["task_id"], attempt)
            if key in records:
                raise ValueError(f"Duplicate evaluation protected attempt: {key}")
            records[key] = {
                "task": task,
                "intent_path": intent_path,
                "intent": intent,
                "receipt_path": receipt_path,
                "receipt": receipt,
                "allocation_path": attempt_root / "allocation.log",
            }
    return records


def materialize_eval_terminals(plan_path: Path, *, confirm_study_id: str) -> Path:
    if confirm_study_id != STUDY_ID:
        raise ValueError(f"Terminal materialization requires --confirm-study-id {STUDY_ID}")
    require_control_tmux()
    eval_plan.validate_plan(plan_path, require_complete=True)
    _, plan = eval_plan._read_json(plan_path)
    submissions = _eval_submission_records(plan)
    terminal_receipts = {}
    for task in plan["tasks"]:
        paths = sorted(Path(task["receipt_dir"]).glob("attempt_*.json"))
        if not paths:
            raise ValueError(f"Evaluation task has no terminal receipt: {task['task_id']}")
        _, terminal_receipt = eval_plan._read_json(paths[-1])
        key = (task["task_id"], int(terminal_receipt["attempt"]))
        if terminal_receipt.get("status") != "succeeded" or key not in submissions:
            raise ValueError(f"Evaluation task lacks matching protected success: {task['task_id']}")
        submission = submissions[key]
        protected_receipt = submission["receipt"]
        terminal_scheduler = terminal_receipt.get("scheduler")
        if (
            terminal_receipt.get("dispatch_intent")
            != eval_plan.file_identity(submission["intent_path"])
            or not isinstance(terminal_scheduler, dict)
            or terminal_scheduler.get("job_id") != protected_receipt["job_id"]
            or terminal_scheduler.get("comment") != protected_receipt["comment"]
            or terminal_scheduler.get("job_name") != task["job_name"]
            or terminal_scheduler.get("account") != REQUIRED_ACCOUNT
            or terminal_scheduler.get("qos") != REQUIRED_QOS
            or terminal_scheduler.get("submitted_batch_script_sha256") != task["sbatch"]["sha256"]
        ):
            raise ValueError(f"Evaluation terminal receipt differs from protected dispatch: {task['task_id']}")
        terminal_receipts[key] = (paths[-1], terminal_receipt)
    if not set(terminal_receipts).issubset(submissions):
        raise ValueError("Successful evaluation receipts lack protected submissions")
    records = []
    for key, (terminal_path, terminal_receipt) in sorted(terminal_receipts.items()):
        submission = submissions[key]
        task = submission["task"]
        receipt = submission["receipt"]
        job_id = str(receipt["job_id"])
        _assert_job_not_live(job_id)
        expected = {
            "job_id": job_id,
            "comment": receipt["comment"],
            "job_name": task["job_name"],
            "account": REQUIRED_ACCOUNT,
            "qos": REQUIRED_QOS,
            "submitted_batch_script_sha256": task["sbatch"]["sha256"],
        }
        allocation = terminal_allocation(job_id, expected=expected)
        if allocation["record"]["state"] != "COMPLETED" or allocation["record"]["exit_code"] != "0:0":
            raise ValueError(f"Successful runner receipt lacks COMPLETED/0:0: {key}")
        if allocation["record"]["restart_count"] != 0:
            raise ValueError(f"Evaluation allocation restarted: {key}")
        eval_plan._write_once(submission["allocation_path"], allocation["stdout"].encode())
        if terminal_receipt.get("dispatch_intent") != eval_plan.file_identity(submission["intent_path"]):
            raise ValueError(f"Terminal receipt binds a different dispatch intent: {key}")
        records.append(
            {
                "task_id": task["task_id"],
                "attempt": key[1],
                "job_id": job_id,
                "comment": receipt["comment"],
                "job_name": task["job_name"],
                "account": REQUIRED_ACCOUNT,
                "qos": REQUIRED_QOS,
                "state": allocation["record"]["state"],
                "exit_code": allocation["record"]["exit_code"],
                "restart_count": allocation["record"]["restart_count"],
                "submitted_batch_script_sha256": allocation["submitted_batch_script_sha256"],
                "submission_receipt": eval_plan.file_identity(submission["receipt_path"]),
                "terminal_receipt": eval_plan.file_identity(terminal_path),
                "allocation_log": eval_plan.file_identity(submission["allocation_path"]),
            }
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": withdrawal_analysis.TERMINAL_PROVENANCE_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "plan": eval_plan.file_identity(plan_path),
        "tasks": records,
    }
    provenance = _self_hashed(payload)
    output = Path(plan["plan_root"]) / withdrawal_analysis.TERMINAL_PROVENANCE_NAME
    eval_plan._write_once(output, eval_plan.canonical_json_bytes(provenance))
    withdrawal_analysis._terminal_provenance(plan, plan_path)
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    training_authority = subparsers.add_parser("materialize-training-authority")
    training_authority.add_argument("--eval-authority", type=Path, required=True)
    validate_authority = subparsers.add_parser("validate-training-authority")
    validate_authority.add_argument("--authority", type=Path, required=True)
    dispatch_training_parser = subparsers.add_parser("dispatch-training")
    dispatch_training_parser.add_argument("--authority", type=Path, required=True)
    dispatch_training_parser.add_argument("--arm", action="append", required=True)
    dispatch_training_parser.add_argument("--dry-run", action="store_true")
    dispatch_training_parser.add_argument("--confirm-study-id")
    reconcile_training_parser = subparsers.add_parser("reconcile-training")
    reconcile_training_parser.add_argument("--authority", type=Path, required=True)
    reconcile_training_parser.add_argument("--arm", action="append", required=True)
    reconcile_training_parser.add_argument("--confirm-study-id", required=True)
    terminal_training_parser = subparsers.add_parser("terminalize-training")
    terminal_training_parser.add_argument("--authority", type=Path, required=True)
    terminal_training_parser.add_argument("--arm", action="append", required=True)
    terminal_training_parser.add_argument("--confirm-study-id", required=True)
    dispatch_eval_parser = subparsers.add_parser("dispatch-eval")
    dispatch_eval_parser.add_argument("--plan", type=Path, required=True)
    dispatch_eval_parser.add_argument("--task", action="append", required=True)
    dispatch_eval_parser.add_argument("--dry-run", action="store_true")
    dispatch_eval_parser.add_argument("--confirm-study-id")
    reconcile_eval_parser = subparsers.add_parser("reconcile-eval")
    reconcile_eval_parser.add_argument("--plan", type=Path, required=True)
    reconcile_eval_parser.add_argument("--task", action="append", required=True)
    reconcile_eval_parser.add_argument("--confirm-study-id", required=True)
    terminals = subparsers.add_parser("materialize-eval-terminals")
    terminals.add_argument("--plan", type=Path, required=True)
    terminals.add_argument("--confirm-study-id", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize-training-authority":
        path = materialize_training_authority(args.eval_authority)
        result = {"training_dispatch_authority": str(path)}
    elif args.command == "validate-training-authority":
        authority = validate_training_authority(args.authority)
        result = {"training_dispatch_authority": str(args.authority.resolve()), "arms": len(authority["arms"])}
    elif args.command == "dispatch-training":
        result = dispatch_training(
            args.authority,
            args.arm,
            dry_run=args.dry_run,
            confirm_study_id=args.confirm_study_id,
        )
    elif args.command == "reconcile-training":
        result = reconcile_training(
            args.authority,
            args.arm,
            confirm_study_id=args.confirm_study_id,
        )
    elif args.command == "terminalize-training":
        result = terminalize_training(
            args.authority,
            args.arm,
            confirm_study_id=args.confirm_study_id,
        )
    elif args.command == "dispatch-eval":
        result = dispatch_eval(
            args.plan,
            args.task,
            dry_run=args.dry_run,
            confirm_study_id=args.confirm_study_id,
        )
    elif args.command == "reconcile-eval":
        result = reconcile_eval(
            args.plan,
            args.task,
            confirm_study_id=args.confirm_study_id,
        )
    else:
        path = materialize_eval_terminals(args.plan, confirm_study_id=args.confirm_study_id)
        result = {"terminal_provenance": str(path)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
