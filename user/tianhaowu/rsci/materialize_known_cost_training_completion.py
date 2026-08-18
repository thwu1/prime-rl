#!/usr/bin/env python3
"""Materialize an immutable protected-training completion receipt."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import materialize_known_cost_boundary_launch as launch

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_training_completion_receipt"
STUDY_ID = launch.STUDY_ID
RECEIPT_NAME = "training_completion_receipt.json"
STAGE1_DISPATCH_STAGE = "stage1_initial"
STAGE2_DISPATCH_STAGE = "stage2_promotion"
SCRIPT_REPOSITORY_PATH = "user/tianhaowu/rsci/materialize_known_cost_training_completion.py"
LAUNCH_VALIDATOR_REPOSITORY_PATH = "user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py"
STAGE1_DISPATCHER_REPOSITORY_PATH = "user/tianhaowu/rsci/dispatch_known_cost_boundary.py"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ARM_FILENAME_RE = re.compile(r"[a-z0-9_]+\.toml")
JOB_ID_RE = re.compile(r"[1-9][0-9]*")
SACCT_FORMAT = "JobIDRaw,Comment%1000,JobName%200,Account%100,QOS%100,State%50,ExitCode,StdOut%1000,StdErr%1000"
JOINT_STOP_RE = re.compile(
    r"Draining pipeline \(reached joint stop: steps=(?P<step>[0-9]+)/(?P<min_step>[0-9]+), "
    r"finalized_groups=(?P<groups>[0-9]+)/(?P<min_groups>[0-9]+); cancelled "
    r"(?P<cancelled>[0-9]+) in-flight train rollout\(s\); any in-flight evals will complete\)"
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
WANDB_DIR_RE = re.compile(r"wandb: Run data is saved locally in (?P<path>\S+)\s*$", re.MULTILINE)


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _require_read_only(path: Path, label: str) -> None:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError(f"{label} must be read-only: {resolved}")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _reject_nonfinite_constant(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def read_canonical_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    raw = resolved.read_bytes()
    value = json.loads(
        raw.decode(),
        object_pairs_hook=_object_without_duplicate_keys,
        parse_constant=_reject_nonfinite_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {resolved}")
    if raw != canonical_json_bytes(value):
        raise ValueError(f"JSON artifact is not canonical: {resolved}")
    return raw, value


def _validate_self_hash(payload: dict[str, Any], label: str) -> str:
    self_hash = _require_sha256(payload.get("payload_without_self_hash_sha256"), f"{label} self hash")
    unhashed = dict(payload)
    unhashed.pop("payload_without_self_hash_sha256")
    if canonical_json_sha256(unhashed) != self_hash:
        raise ValueError(f"{label} self hash differs from its canonical payload")
    return self_hash


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} is not an RFC3339 UTC timestamp")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{label} is not UTC")
    return parsed


def _write_json_once_atomic(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    content = canonical_json_bytes(payload)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resolved.with_suffix(resolved.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if resolved.exists():
            if not resolved.is_file() or resolved.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace a different immutable completion receipt: {resolved}")
            _require_read_only(resolved, "Training completion receipt")
            return file_identity(resolved)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".partial",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o444)
            os.link(temporary, resolved)
            directory_descriptor = os.open(resolved.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary.unlink(missing_ok=True)
    _require_read_only(resolved, "Training completion receipt")
    return file_identity(resolved)


def _run_exact_tool(implementation: Path, arguments: list[str]) -> dict[str, Any]:
    return launch._run_exact_validator(implementation, arguments)


def _identity_matches(recorded: object, path: Path, label: str) -> dict[str, Any]:
    expected = _require_dict(recorded, label)
    actual = file_identity(path)
    if actual != expected:
        raise ValueError(f"{label} identity changed: {path}")
    return actual


def _repository_path(path: Path) -> str:
    parts = path.expanduser().resolve().parts
    marker = ("user", "tianhaowu", "rsci")
    matches = [
        index for index in range(len(parts) - len(marker) + 1) if tuple(parts[index : index + len(marker)]) == marker
    ]
    if len(matches) != 1:
        raise ValueError(f"Cannot derive one repository path from {path}")
    return Path(*parts[matches[0] :]).as_posix()


def _safe_arm_key(arm_filename: str) -> str:
    if ARM_FILENAME_RE.fullmatch(arm_filename) is None:
        raise ValueError(f"Unsafe arm filename: {arm_filename!r}")
    return arm_filename.removesuffix(".toml")


def _require_supported_dispatch_stage(
    receipt: dict[str, Any],
    *,
    supported_dispatch_stages: set[str],
) -> str:
    stage = receipt.get("dispatch_stage")
    if stage == STAGE2_DISPATCH_STAGE and stage not in supported_dispatch_stages:
        raise NotImplementedError("Stage-2 promotion completion receipts are not supported by this materializer")
    if not isinstance(stage, str) or stage not in supported_dispatch_stages:
        raise ValueError(f"Unsupported training completion dispatch stage: {stage!r}")
    return stage


def _directive_values(path: Path, name: str) -> list[str]:
    prefix = f"#SBATCH --{name}="
    return [
        line.removeprefix(prefix) for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(prefix)
    ]


def _allocation_log_contract(sbatch_path: Path, run_dir: Path, job_id: int) -> dict[str, dict[str, Any]]:
    contract = {}
    for stream, directive in (("stdout", "output"), ("stderr", "error")):
        values = _directive_values(sbatch_path, directive)
        if len(values) != 1:
            raise ValueError(f"Sealed Stage-1 sbatch has {len(values)} --{directive} directives, expected one")
        template = values[0]
        if template.count("%j") != 1 or "%" in template.replace("%j", ""):
            raise ValueError(f"Sealed Stage-1 --{directive} is not one exact %j allocation-log path")
        resolved = Path(template.replace("%j", str(job_id))).expanduser().resolve()
        if not resolved.is_relative_to(run_dir):
            raise ValueError(f"Sealed Stage-1 {stream} allocation log is outside the run directory")
        contract[stream] = {"scheduler_spec": template, "resolved_path": resolved}
    return contract


def _allocation_log_paths(sbatch_path: Path, run_dir: Path, job_id: int) -> dict[str, Path]:
    contract = _allocation_log_contract(sbatch_path, run_dir, job_id)
    return {stream: value["resolved_path"] for stream, value in contract.items()}


def _capture_identity_inventory(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    return {name: file_identity(paths[name]) for name in sorted(paths)}


def _require_unchanged(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    label: str,
) -> None:
    if before != after:
        changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
        raise RuntimeError(f"{label} changed during evidence capture: {changed}")


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _wandb_stream_path(run_dir: Path, log_text: str, expected_output_dir: Path, label: str) -> Path:
    directories = {Path(match.group("path")).expanduser().resolve() for match in WANDB_DIR_RE.finditer(log_text)}
    if len(directories) != 1:
        raise ValueError(f"{label} console log names {len(directories)} local W&B run directories, expected one")
    directory = directories.pop()
    expected_parent = expected_output_dir.expanduser().resolve() / "wandb"
    if directory.parent != expected_parent or not directory.name.startswith(("run-", "offline-run-")):
        raise ValueError(f"{label} local W&B directory is outside its sealed output: {directory}")
    if not directory.is_relative_to(run_dir):
        raise ValueError(f"{label} local W&B directory is outside the run root")
    streams = sorted(directory.glob("*.wandb"))
    if len(streams) != 1:
        raise ValueError(f"{label} local W&B directory contains {len(streams)} event streams")
    return streams[0].resolve()


def _completion_markers(
    run_dir: Path,
    trainer_config_path: Path,
    orchestrator_config_path: Path,
) -> tuple[dict[str, Any], dict[str, Path]]:
    trainer_log = run_dir / "logs" / "trainer.log"
    orchestrator_log = run_dir / "logs" / "orchestrator.log"
    trainer_identity = file_identity(trainer_log)
    orchestrator_identity = file_identity(orchestrator_log)
    trainer_text = ANSI_RE.sub("", trainer_log.read_text(encoding="utf-8"))
    orchestrator_text = ANSI_RE.sub("", orchestrator_log.read_text(encoding="utf-8"))
    trainer_config = _load_toml(trainer_config_path)
    orchestrator_config = _load_toml(orchestrator_config_path)
    trainer_output = Path(str(trainer_config.get("output_dir"))).expanduser().resolve()
    orchestrator_output = Path(str(orchestrator_config.get("output_dir"))).expanduser().resolve()
    if trainer_output != run_dir or orchestrator_output != run_dir:
        raise ValueError("Resolved trainer/orchestrator output directories differ from the eligible run")
    trainer_wandb = _wandb_stream_path(run_dir, trainer_text, trainer_output, "trainer")
    orchestrator_wandb = _wandb_stream_path(run_dir, orchestrator_text, orchestrator_output, "orchestrator")
    if trainer_wandb == orchestrator_wandb:
        raise ValueError("Trainer and orchestrator unexpectedly share one local W&B event stream")
    group_stats = run_dir / "rollouts" / "train_group_stats.jsonl"
    batch_attempts = run_dir / "rollouts" / "train_batch_attempts.jsonl"
    group_stats_identity = file_identity(group_stats)
    batch_attempts_identity = file_identity(batch_attempts)
    joint_matches = list(JOINT_STOP_RE.finditer(orchestrator_text))
    if len(joint_matches) != 1:
        raise ValueError(f"Orchestrator log contains {len(joint_matches)} exact joint-stop markers")
    joint = joint_matches[0]
    joint_stop = {key: int(value) for key, value in joint.groupdict().items()}
    final_step = _require_int(joint_stop["step"], "final checkpoint step", minimum=1)
    ordered_markers = (
        joint.group(0),
        f"Waiting for stable trainer weights at step {final_step} before exit",
        "Pipeline drained, exiting main loop",
        "Orchestrator step loop done in ",
        "Writing final checkpoint",
        "Orchestrator finished.",
    )
    offsets = []
    cursor = 0
    for marker in ordered_markers:
        position = orchestrator_text.find(marker, cursor)
        if position < 0:
            raise ValueError(f"Orchestrator log lacks ordered completion marker: {marker!r}")
        offsets.append(position)
        cursor = position + len(marker)
    if (
        "Orchestrator interrupted" in orchestrator_text
        or "Orchestrator cleanup complete (forced)." in orchestrator_text
    ):
        raise ValueError("Orchestrator reports a forced rather than clean completion")
    checkpoint_path = run_dir / "weights" / f"step_{final_step}"
    if not checkpoint_path.is_dir():
        raise FileNotFoundError(checkpoint_path)
    stable_path = checkpoint_path / "STABLE"
    stable_identity = file_identity(stable_path)
    return (
        {
            "trainer_console_log": trainer_identity,
            "orchestrator_console_log": orchestrator_identity,
            "resolved_training_configs": {
                "trainer": file_identity(trainer_config_path),
                "orchestrator": file_identity(orchestrator_config_path),
            },
            "training_group_ledger": group_stats_identity,
            "training_batch_attempt_ledger": batch_attempts_identity,
            "local_wandb_streams": {
                "trainer": file_identity(trainer_wandb),
                "orchestrator": file_identity(orchestrator_wandb),
            },
            "joint_stop": joint_stop,
            "ordered_completion_marker_offsets": offsets,
            "final_checkpoint_step": final_step,
            "final_checkpoint_path": str(checkpoint_path.resolve()),
            "final_stable_marker": stable_identity,
            "scope": {
                "clean_orchestrator_completion_markers_required": True,
                "final_stable_weight_checkpoint_required": True,
                "trainer_normal_exit_claimed": False,
                "wandb_exit_record_required_or_claimed": False,
                "scientific_replay_or_metric_completeness_claimed": False,
            },
        },
        {
            "trainer_console_log": trainer_log,
            "orchestrator_console_log": orchestrator_log,
            "training_group_ledger": group_stats,
            "training_batch_attempt_ledger": batch_attempts,
            "trainer_local_wandb_stream": trainer_wandb,
            "orchestrator_local_wandb_stream": orchestrator_wandb,
            "final_checkpoint_stable_marker": stable_path,
        },
    )


def _validate_stage1_chain(
    *,
    run: dict[str, Any],
    run_dir: Path,
    arm_filename: str,
    status_result: dict[str, Any],
    global_path: Path,
    batch_intent_path: Path,
    arm_intent_path: Path,
    submission_receipt_path: Path,
) -> dict[str, Any]:
    _, global_intent = read_canonical_json(global_path)
    _, arm_intent = read_canonical_json(arm_intent_path)
    _, submission_receipt = read_canonical_json(submission_receipt_path)
    plan = _require_dict(arm_intent.get("arm_plan"), "Stage-1 arm plan")
    scheduler = _require_dict(plan.get("scheduler"), "Stage-1 scheduler contract")
    if arm_intent.get("batch_intent") != file_identity(batch_intent_path):
        raise ValueError("Stage-1 arm intent and batch intent identity differ")
    if (
        plan.get("arm_filename") != arm_filename
        or Path(str(plan.get("output_dir"))).expanduser().resolve() != run_dir
        or plan.get("sbatch") != run.get("sbatch")
        or plan.get("source_provenance")
        != _require_dict(run.get("source_provenance"), "eligible run source provenance").get("manifest")
    ):
        raise ValueError("Stage-1 arm plan and eligible run identity differ")
    if scheduler.get("job_name") != run.get("job_name"):
        raise ValueError("Stage-1 scheduler job name and eligible run differ")
    job_id = _require_int(submission_receipt.get("job_id"), "Stage-1 receipt job_id", minimum=1)
    sbatch_path = Path(str(_require_dict(run.get("sbatch"), "eligible run sbatch").get("path"))).resolve()
    allocation_log_contract = _allocation_log_contract(sbatch_path, run_dir, job_id)
    allocation_log_identities = {
        stream: file_identity(value["resolved_path"]) for stream, value in allocation_log_contract.items()
    }
    if (
        submission_receipt.get("arm_filename") != arm_filename
        or submission_receipt.get("comment") != plan.get("comment")
        or submission_receipt.get("command") != plan.get("command")
        or submission_receipt.get("global_submission_intent") != file_identity(global_path)
        or submission_receipt.get("arm_submission_intent") != file_identity(arm_intent_path)
    ):
        raise ValueError("Stage-1 submission receipt and protected arm plan differ")
    status = _require_dict(status_result.get("status"), "historical dispatcher status")
    receipts = _require_dict(status.get("receipts"), "historical dispatcher receipt registry")
    if status.get("state") != "ready" or status.get("pending") != [] or receipts.get(arm_filename) != job_id:
        raise ValueError("Historical dispatcher does not report one ready protected receipt for the arm")
    return {
        "state_root": str(global_path.parent.resolve()),
        "global_submission_intent": file_identity(global_path),
        "batch_submission_intent": file_identity(batch_intent_path),
        "arm_submission_intent": file_identity(arm_intent_path),
        "submission_receipt": {
            "identity": file_identity(submission_receipt_path),
            "canonical_payload_sha256": canonical_json_sha256(submission_receipt),
        },
        "job_id": job_id,
        "comment": plan.get("comment"),
        "command": plan.get("command"),
        "job_name": scheduler.get("job_name"),
        "account": scheduler.get("account"),
        "qos": scheduler.get("qos"),
        "sealed_qos_directive": scheduler.get("sealed_qos_directive"),
        "receipt_source": submission_receipt.get("source"),
        "allocation_logs": allocation_log_identities,
        "allocation_log_scheduler_specs": {
            stream: value["scheduler_spec"] for stream, value in allocation_log_contract.items()
        },
        "historical_global_intent_payload_sha256": canonical_json_sha256(global_intent),
    }


def _collect_context(
    *,
    initial_intent_path: Path,
    state_root: Path,
    arm_filename: str,
    run_dir: Path,
    frozen_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initial_intent_path = initial_intent_path.expanduser().resolve()
    state_root = state_root.expanduser().resolve()
    run_dir = run_dir.expanduser().resolve()
    _safe_arm_key(arm_filename)
    _require_read_only(initial_intent_path, "Initial launch intent")
    _, intent = read_canonical_json(initial_intent_path)
    if (
        intent.get("schema_version") != launch.SCHEMA_VERSION
        or intent.get("artifact_type") != launch.ARTIFACT_TYPE
        or intent.get("study_id") != STUDY_ID
    ):
        raise ValueError("Initial launch intent has the wrong schema, artifact type, or study")
    intent_self_hash = _validate_self_hash(intent, "Initial launch intent")
    inputs = _require_dict(intent.get("inputs"), "initial launch inputs")
    tokenizer_path = Path(str(inputs.get("tokenizer_path"))).expanduser().resolve()
    validator = _require_dict(intent.get("implementation"), "historical launch validator")
    validator_path = Path(str(validator.get("path"))).expanduser().resolve()
    if _repository_path(validator_path) != LAUNCH_VALIDATOR_REPOSITORY_PATH:
        raise ValueError("Initial launch intent records the wrong historical launch validator")
    _identity_matches(validator, validator_path, "Historical launch validator")
    _require_read_only(validator_path, "Historical launch validator")
    control_source = _require_dict(intent.get("control_plane_source"), "initial control-plane source")
    implementations = _require_dict(control_source.get("implementations"), "initial control-plane implementations")
    dispatcher = _require_dict(implementations.get("dispatcher"), "historical Stage-1 dispatcher")
    dispatcher_path = Path(str(dispatcher.get("path"))).expanduser().resolve()
    if _repository_path(dispatcher_path) != STAGE1_DISPATCHER_REPOSITORY_PATH:
        raise ValueError("Initial launch intent records the wrong historical Stage-1 dispatcher")
    _identity_matches(dispatcher, dispatcher_path, "Historical Stage-1 dispatcher")
    _require_read_only(dispatcher_path, "Historical Stage-1 dispatcher")

    decision = _require_dict(intent.get("preregistered_decision"), "preregistered decision")
    eligible_filenames = _require_list(decision.get("eligible_arm_filenames"), "eligible arm filenames")
    if arm_filename not in eligible_filenames:
        raise ValueError(f"Arm is not eligible under the initial launch intent: {arm_filename}")
    runs = [
        _require_dict(item, "eligible run")
        for item in _require_list(intent.get("eligible_runs"), "eligible runs")
        if isinstance(item, dict) and item.get("arm_filename") == arm_filename
    ]
    if len(runs) != 1:
        raise ValueError(f"Initial launch intent does not contain exactly one eligible run for {arm_filename}")
    run = runs[0]
    if Path(str(run.get("output_dir"))).expanduser().resolve() != run_dir:
        raise ValueError("Requested run directory differs from the eligible arm output directory")
    policy = _require_dict(intent.get("dispatch_policy"), "initial dispatch policy")
    if Path(str(policy.get("required_state_root"))).expanduser().resolve() != state_root:
        raise ValueError("Requested Stage-1 state root differs from the launch intent")

    global_path = state_root / "global_submission_intent.json"
    arm_root = state_root / "arms" / _safe_arm_key(arm_filename)
    arm_intent_path = arm_root / "submission_intent.json"
    submission_receipt_path = arm_root / "receipt.json"
    for path, label in (
        (global_path, "Stage-1 global intent"),
        (arm_intent_path, "Stage-1 arm intent"),
        (submission_receipt_path, "Stage-1 submission receipt"),
    ):
        _require_read_only(path, label)
        read_canonical_json(path)
    _, untrusted_arm_intent = read_canonical_json(arm_intent_path)
    batch_identity = _require_dict(untrusted_arm_intent.get("batch_intent"), "Stage-1 batch intent identity")
    batch_intent_path = Path(str(batch_identity.get("path"))).expanduser().resolve()
    if batch_intent_path.parent != state_root / "batches":
        raise ValueError("Stage-1 batch intent is outside the exact protected state root")
    _identity_matches(batch_identity, batch_intent_path, "Stage-1 batch intent")
    _require_read_only(batch_intent_path, "Stage-1 batch intent")
    read_canonical_json(batch_intent_path)

    replay_paths = {
        "historical_launch_validator": validator_path,
        "historical_stage1_dispatcher": dispatcher_path,
        "initial_launch_intent": initial_intent_path,
        "stage1_arm_intent": arm_intent_path,
        "stage1_batch_intent": batch_intent_path,
        "stage1_global_intent": global_path,
        "stage1_submission_receipt": submission_receipt_path,
    }
    replay_before = _capture_identity_inventory(replay_paths)
    if frozen_replay is None:
        launch_summary = _run_exact_tool(
            validator_path,
            ["validate", "--intent", str(initial_intent_path), "--tokenizer", str(tokenizer_path)],
        )
    else:
        launch_summary = _require_dict(
            frozen_replay.get("historical_launch_validation_summary"),
            "frozen historical launch validation summary",
        )
    expected_launch_summary = {
        "command": "validate",
        "intent": file_identity(initial_intent_path),
        "eligible_design": decision.get("eligible_design"),
        "eligible_arm_count": decision.get("eligible_arm_count"),
        "submission_performed": False,
    }
    if launch_summary != expected_launch_summary:
        raise ValueError("Historical launch validator returned a different summary")
    if frozen_replay is None:
        status_result = _run_exact_tool(
            dispatcher_path,
            ["status", "--intent", str(initial_intent_path), "--state-root", str(state_root)],
        )
    else:
        status_result = _require_dict(
            frozen_replay.get("historical_stage1_status"),
            "frozen historical Stage-1 status",
        )
    replay_after = _capture_identity_inventory(replay_paths)
    _require_unchanged(replay_before, replay_after, "Historical launch/dispatch evidence")
    if (
        status_result.get("study_id") != STUDY_ID
        or status_result.get("state_root") != str(state_root)
        or status_result.get("authority") != file_identity(initial_intent_path)
        or status_result.get("scheduler_mutation") is not False
    ):
        raise ValueError("Historical Stage-1 dispatcher status returned the wrong authority")
    stage1 = _validate_stage1_chain(
        run=run,
        run_dir=run_dir,
        arm_filename=arm_filename,
        status_result=status_result,
        global_path=global_path,
        batch_intent_path=batch_intent_path,
        arm_intent_path=arm_intent_path,
        submission_receipt_path=submission_receipt_path,
    )

    resolved_configs = _require_dict(run.get("resolved_configs"), "eligible run resolved configs")
    if not {"trainer", "orchestrator"}.issubset(resolved_configs):
        raise ValueError("Eligible run does not bind both resolved trainer and orchestrator TOMLs")
    evidence_paths = dict(replay_paths)
    resolved_config_paths = {}
    for name, recorded in sorted(resolved_configs.items()):
        identity = _require_dict(recorded, f"resolved config {name}")
        path = Path(str(identity.get("path"))).expanduser().resolve()
        _identity_matches(identity, path, f"Resolved config {name}")
        evidence_paths[f"resolved_config_{name}"] = path
        resolved_config_paths[name] = path
    sbatch = _require_dict(run.get("sbatch"), "eligible run sbatch")
    sbatch_path = Path(str(sbatch.get("path"))).expanduser().resolve()
    _identity_matches(sbatch, sbatch_path, "Sealed sbatch")
    evidence_paths["sealed_sbatch"] = sbatch_path
    allocation_logs = _require_dict(stage1.get("allocation_logs"), "Stage-1 allocation logs")
    for stream in ("stdout", "stderr"):
        log_identity = _require_dict(allocation_logs.get(stream), f"Stage-1 {stream} allocation log")
        evidence_paths[f"stage1_allocation_{stream}_log"] = Path(str(log_identity.get("path"))).resolve()
    source = _require_dict(run.get("source_provenance"), "eligible run source provenance")
    source_manifest = _require_dict(source.get("manifest"), "eligible run source manifest")
    source_path = Path(str(source_manifest.get("path"))).expanduser().resolve()
    _identity_matches(source_manifest, source_path, "Source provenance manifest")
    evidence_paths["source_provenance_manifest"] = source_path
    completion, completion_paths = _completion_markers(
        run_dir,
        resolved_config_paths["trainer"],
        resolved_config_paths["orchestrator"],
    )
    evidence_paths.update(completion_paths)
    evidence_paths["completion_materializer"] = Path(__file__).resolve()
    return {
        "launch_authority": {
            "initial_intent": file_identity(initial_intent_path),
            "payload_without_self_hash_sha256": intent_self_hash,
            "historical_launch_validator": file_identity(validator_path),
            "historical_launch_validation_summary": launch_summary,
            "historical_launch_validation_summary_sha256": canonical_json_sha256(launch_summary),
            "historical_stage1_dispatcher": file_identity(dispatcher_path),
            "historical_stage1_status": status_result,
            "historical_stage1_status_summary_sha256": canonical_json_sha256(status_result),
        },
        "stage1_submission": stage1,
        "run_contract": {
            "arm_filename": arm_filename,
            "run_dir": str(run_dir),
            "eligible_run": run,
        },
        "completion_evidence": completion,
        "evidence_paths": evidence_paths,
        "replay_toctou": {"before": replay_before, "after": replay_after},
    }


def _expected_scheduler_contract(context: dict[str, Any]) -> dict[str, Any]:
    stage1 = _require_dict(context.get("stage1_submission"), "Stage-1 submission")
    allocation_logs = _require_dict(stage1.get("allocation_logs"), "Stage-1 allocation logs")
    scheduler_specs = _require_dict(
        stage1.get("allocation_log_scheduler_specs"),
        "Stage-1 allocation log scheduler specs",
    )
    return {
        "job_id": _require_int(stage1.get("job_id"), "Stage-1 job_id", minimum=1),
        "comment": stage1.get("comment"),
        "job_name": stage1.get("job_name"),
        "account": stage1.get("account"),
        "qos": stage1.get("qos"),
        "stdout_path": str(
            Path(str(_require_dict(allocation_logs.get("stdout"), "Stage-1 stdout log").get("path"))).resolve()
        ),
        "stderr_path": str(
            Path(str(_require_dict(allocation_logs.get("stderr"), "Stage-1 stderr log").get("path"))).resolve()
        ),
        "stdout_scheduler_spec": scheduler_specs.get("stdout"),
        "stderr_scheduler_spec": scheduler_specs.get("stderr"),
    }


def _parse_terminal_allocation(stdout: str, expected: dict[str, Any]) -> dict[str, Any]:
    rows = [line.rstrip("\r") for line in stdout.splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError(f"sacct returned {len(rows)} allocation rows; exactly one is required")
    fields = rows[0].split("|")
    if len(fields) != 9:
        raise ValueError(f"Malformed sacct allocation row: {rows[0]!r}")
    job_id_text, comment, job_name, account, qos, state, exit_code, stdout_path, stderr_path = (
        field.strip() for field in fields
    )
    if JOB_ID_RE.fullmatch(job_id_text) is None:
        raise ValueError(f"sacct returned a job-step or invalid allocation ID: {job_id_text!r}")
    job_id = int(job_id_text)
    normalized_log_paths = {}
    scheduler_log_values = {"stdout": stdout_path, "stderr": stderr_path}
    for stream in ("stdout", "stderr"):
        scheduler_value = scheduler_log_values[stream]
        expected_spec = expected[f"{stream}_scheduler_spec"]
        expected_path = expected[f"{stream}_path"]
        if scheduler_value == expected_spec:
            normalized = str(Path(scheduler_value.replace("%j", str(job_id))).expanduser().resolve())
        elif "%" not in scheduler_value:
            normalized = str(Path(scheduler_value).expanduser().resolve())
        else:
            raise ValueError(f"Terminal scheduler {stream} contains an unauthorized Slurm path pattern")
        if normalized != expected_path:
            raise ValueError(f"Terminal scheduler {stream} differs from the sealed allocation-log path")
        normalized_log_paths[stream] = normalized
    observed_identity = {
        "job_id": job_id,
        "comment": comment,
        "job_name": job_name,
        "account": account,
        "qos": qos,
        "stdout_path": normalized_log_paths["stdout"],
        "stderr_path": normalized_log_paths["stderr"],
    }
    expected_identity = {
        key: expected[key] for key in ("job_id", "comment", "job_name", "account", "qos", "stdout_path", "stderr_path")
    }
    if observed_identity != expected_identity:
        raise ValueError("Terminal scheduler allocation differs from the protected Stage-1 receipt")
    normalized_state = state.split(maxsplit=1)[0].rstrip("+")
    if normalized_state != "COMPLETED":
        raise ValueError(f"Protected training allocation is not terminal COMPLETED: {state!r}")
    if exit_code != "0:0":
        raise ValueError(f"Protected training allocation has a nonzero ExitCode: {exit_code!r}")
    return {
        **observed_identity,
        "stdout_scheduler_value": stdout_path,
        "stderr_scheduler_value": stderr_path,
        "raw_state": state,
        "normalized_state": normalized_state,
        "exit_code": exit_code,
    }


def _query_terminal_allocation(expected: dict[str, Any]) -> dict[str, Any]:
    job_id = _require_int(expected.get("job_id"), "scheduler job_id", minimum=1)
    command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--jobs",
        str(job_id),
        f"--format={SACCT_FORMAT}",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    row = _parse_terminal_allocation(completed.stdout, expected)
    return {
        "queried_at": _utc_now(),
        "command": command,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "row": row,
    }


def _validate_frozen_scheduler_evidence(value: object, context: dict[str, Any]) -> dict[str, Any]:
    evidence = _require_dict(value, "terminal scheduler evidence")
    if set(evidence) != {"queried_at", "command", "stdout_sha256", "row"}:
        raise ValueError("Terminal scheduler evidence has the wrong schema")
    _parse_utc(evidence.get("queried_at"), "terminal scheduler query time")
    _require_sha256(evidence.get("stdout_sha256"), "terminal sacct stdout")
    expected = _expected_scheduler_contract(context)
    expected_command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--jobs",
        str(expected["job_id"]),
        f"--format={SACCT_FORMAT}",
    ]
    if evidence.get("command") != expected_command:
        raise ValueError("Terminal scheduler evidence used the wrong sacct command")
    row = _require_dict(evidence.get("row"), "terminal allocation row")
    expected_row_identity = {
        key: expected[key] for key in ("job_id", "comment", "job_name", "account", "qos", "stdout_path", "stderr_path")
    }
    expected_row_identity.update({"normalized_state": "COMPLETED", "exit_code": "0:0"})
    if {key: row.get(key) for key in expected_row_identity} != expected_row_identity:
        raise ValueError("Frozen terminal allocation row differs from the protected scheduler contract")
    raw_state = row.get("raw_state")
    if not isinstance(raw_state, str) or raw_state.split(maxsplit=1)[0].rstrip("+") != "COMPLETED":
        raise ValueError("Frozen terminal allocation row is not COMPLETED")
    for stream in ("stdout", "stderr"):
        scheduler_value = row.get(f"{stream}_scheduler_value")
        if scheduler_value not in {expected[f"{stream}_scheduler_spec"], expected[f"{stream}_path"]}:
            raise ValueError(f"Frozen terminal allocation {stream} does not match its sealed scheduler path")
    if set(row) != {
        "job_id",
        "comment",
        "job_name",
        "account",
        "qos",
        "stdout_path",
        "stderr_path",
        "stdout_scheduler_value",
        "stderr_scheduler_value",
        "raw_state",
        "normalized_state",
        "exit_code",
    }:
        raise ValueError("Frozen terminal allocation row has the wrong schema")
    return evidence


def build_receipt(
    *,
    initial_intent_path: Path,
    state_root: Path,
    arm_filename: str,
    run_dir: Path,
    context: dict[str, Any],
    terminal_allocation: dict[str, Any],
    terminal_toctou_before: dict[str, dict[str, Any]],
    terminal_toctou_after: dict[str, dict[str, Any]],
    dispatch_stage: str = STAGE1_DISPATCH_STAGE,
) -> dict[str, Any]:
    _require_supported_dispatch_stage(
        {"dispatch_stage": dispatch_stage},
        supported_dispatch_stages={STAGE1_DISPATCH_STAGE},
    )
    _require_unchanged(terminal_toctou_before, terminal_toctou_after, "Training completion evidence")
    _validate_frozen_scheduler_evidence(terminal_allocation, context)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "dispatch_stage": dispatch_stage,
        "inputs": {
            "initial_launch_intent": str(initial_intent_path.expanduser().resolve()),
            "stage1_state_root": str(state_root.expanduser().resolve()),
            "arm_filename": arm_filename,
            "run_dir": str(run_dir.expanduser().resolve()),
        },
        "implementation": {
            "repository_path": SCRIPT_REPOSITORY_PATH,
            **file_identity(Path(__file__)),
        },
        "launch_authority": context["launch_authority"],
        "stage1_submission": context["stage1_submission"],
        "run_contract": context["run_contract"],
        "completion_evidence": context["completion_evidence"],
        "terminal_allocation": terminal_allocation,
        "toctou": {
            "historical_replay": context["replay_toctou"],
            "terminal_evidence_capture": {
                "before": terminal_toctou_before,
                "after": terminal_toctou_after,
            },
        },
        "claim_scope": {
            "proves_protected_allocation_completed_with_exit_code_zero": True,
            "proves_bound_console_logs_and_final_stable_checkpoint_existed": True,
            "proves_scientific_replay_or_metric_completeness": False,
            "proves_normal_trainer_process_exit": False,
            "requires_or_claims_wandb_exit_record": False,
            "stage2_completion_supported_by_this_materializer": False,
        },
    }
    receipt["payload_without_self_hash_sha256"] = canonical_json_sha256(receipt)
    return receipt


def write_receipt(path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("artifact_type") != ARTIFACT_TYPE
        or receipt.get("study_id") != STUDY_ID
    ):
        raise ValueError("Training completion receipt has the wrong schema, artifact type, or study")
    _require_supported_dispatch_stage(
        receipt,
        supported_dispatch_stages={STAGE1_DISPATCH_STAGE},
    )
    _validate_self_hash(receipt, "Training completion receipt")
    run_contract = _require_dict(receipt.get("run_contract"), "completion run contract")
    expected = Path(str(run_contract.get("run_dir"))).expanduser().resolve() / RECEIPT_NAME
    if path.expanduser().resolve() != expected:
        raise ValueError(f"Training completion receipt must be adjacent to the run output at {expected}")
    return _write_json_once_atomic(expected, receipt)


def _receipt_context(receipt: dict[str, Any]) -> dict[str, Any]:
    inputs = _require_dict(receipt.get("inputs"), "completion receipt inputs")
    launch_authority = _require_dict(receipt.get("launch_authority"), "completion launch authority")
    return _collect_context(
        initial_intent_path=Path(str(inputs.get("initial_launch_intent"))),
        state_root=Path(str(inputs.get("stage1_state_root"))),
        arm_filename=str(inputs.get("arm_filename")),
        run_dir=Path(str(inputs.get("run_dir"))),
        frozen_replay={
            "historical_launch_validation_summary": launch_authority.get("historical_launch_validation_summary"),
            "historical_stage1_status": launch_authority.get("historical_stage1_status"),
        },
    )


def validate_receipt_envelope(
    path: Path,
    *,
    supported_dispatch_stages: set[str],
    expected_artifact_type: str = ARTIFACT_TYPE,
    expected_receipt_name: str = RECEIPT_NAME,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    _require_read_only(resolved, "Training completion receipt")
    _, receipt = read_canonical_json(resolved)
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("artifact_type") != expected_artifact_type
        or receipt.get("study_id") != STUDY_ID
    ):
        raise ValueError("Training completion receipt has the wrong schema, artifact type, or study")
    _validate_self_hash(receipt, "Training completion receipt")
    _require_supported_dispatch_stage(receipt, supported_dispatch_stages=supported_dispatch_stages)
    inputs = _require_dict(receipt.get("inputs"), "completion receipt inputs")
    run_dir = Path(str(inputs.get("run_dir"))).expanduser().resolve()
    if resolved != run_dir / expected_receipt_name:
        raise ValueError("Training completion receipt is not adjacent to its recorded run output")
    return {"receipt": receipt, "identity": file_identity(resolved)}


def validate_receipt(path: Path, *, recheck_live_scheduler: bool = False) -> dict[str, Any]:
    envelope = validate_receipt_envelope(
        path,
        supported_dispatch_stages={STAGE1_DISPATCH_STAGE},
    )
    resolved = Path(str(envelope["identity"]["path"]))
    receipt = envelope["receipt"]
    implementation = _require_dict(receipt.get("implementation"), "completion implementation")
    expected_implementation = {"repository_path": SCRIPT_REPOSITORY_PATH, **file_identity(Path(__file__))}
    if implementation != expected_implementation:
        raise ValueError("Training completion receipt was built by a different implementation")

    context = _receipt_context(receipt)
    for field in ("launch_authority", "stage1_submission", "run_contract", "completion_evidence"):
        if receipt.get(field) != context[field]:
            raise ValueError(f"Training completion receipt {field} differs from frozen evidence")
    toctou = _require_dict(receipt.get("toctou"), "completion TOCTOU evidence")
    if set(toctou) != {"historical_replay", "terminal_evidence_capture"}:
        raise ValueError("Training completion receipt has the wrong TOCTOU schema")
    for label in ("historical_replay", "terminal_evidence_capture"):
        phase = _require_dict(toctou.get(label), f"{label} TOCTOU evidence")
        before = _require_dict(phase.get("before"), f"{label} before identities")
        after = _require_dict(phase.get("after"), f"{label} after identities")
        if set(phase) != {"before", "after"}:
            raise ValueError(f"{label} TOCTOU evidence has the wrong schema")
        _require_unchanged(before, after, label)
    if toctou["historical_replay"] != context["replay_toctou"]:
        raise ValueError("Historical replay identities differ from the completion receipt")
    current = _capture_identity_inventory(context["evidence_paths"])
    if toctou["terminal_evidence_capture"]["after"] != current:
        raise ValueError("Bound training completion evidence changed after receipt creation")
    frozen = _validate_frozen_scheduler_evidence(receipt.get("terminal_allocation"), context)
    live = None
    if recheck_live_scheduler:
        live = _query_terminal_allocation(_expected_scheduler_contract(context))
        if live["row"] != frozen["row"]:
            raise ValueError("Live terminal allocation row differs from the frozen receipt")
    claims = _require_dict(receipt.get("claim_scope"), "completion claim scope")
    expected_claims = {
        "proves_protected_allocation_completed_with_exit_code_zero": True,
        "proves_bound_console_logs_and_final_stable_checkpoint_existed": True,
        "proves_scientific_replay_or_metric_completeness": False,
        "proves_normal_trainer_process_exit": False,
        "requires_or_claims_wandb_exit_record": False,
        "stage2_completion_supported_by_this_materializer": False,
    }
    if claims != expected_claims:
        raise ValueError("Training completion receipt overstates or changes its claim scope")
    return {
        "receipt": receipt,
        "identity": file_identity(resolved),
        "live_scheduler_recheck": live,
    }


def validate_adjacent_receipt(
    run_dir: Path,
    *,
    arm_filename: str,
    initial_intent_identity: dict[str, Any] | None = None,
    recheck_live_scheduler: bool = False,
) -> dict[str, Any]:
    resolved_run = run_dir.expanduser().resolve()
    validated = validate_receipt(
        resolved_run / RECEIPT_NAME,
        recheck_live_scheduler=recheck_live_scheduler,
    )
    receipt = validated["receipt"]
    inputs = _require_dict(receipt.get("inputs"), "completion receipt inputs")
    contract = _require_dict(receipt.get("run_contract"), "completion run contract")
    eligible_run = _require_dict(contract.get("eligible_run"), "completion eligible run")
    if (
        inputs.get("arm_filename") != arm_filename
        or inputs.get("run_dir") != str(resolved_run)
        or contract.get("arm_filename") != arm_filename
        or contract.get("run_dir") != str(resolved_run)
        or eligible_run.get("arm_filename") != arm_filename
        or Path(str(eligible_run.get("output_dir"))).expanduser().resolve() != resolved_run
    ):
        raise ValueError("Adjacent training completion receipt belongs to a different arm or run directory")
    if initial_intent_identity is not None:
        launch_authority = _require_dict(receipt.get("launch_authority"), "completion launch authority")
        if launch_authority.get("initial_intent") != initial_intent_identity:
            raise ValueError("Training completion receipt binds a different initial launch intent")
    return validated


def materialize_receipt(
    *,
    initial_intent_path: Path,
    state_root: Path,
    arm_filename: str,
    run_dir: Path,
    dispatch_stage: str = STAGE1_DISPATCH_STAGE,
) -> dict[str, Any]:
    _require_supported_dispatch_stage(
        {"dispatch_stage": dispatch_stage},
        supported_dispatch_stages={STAGE1_DISPATCH_STAGE},
    )
    run_dir = run_dir.expanduser().resolve()
    output_path = run_dir / RECEIPT_NAME
    if output_path.exists():
        validated = validate_receipt(output_path)
        inputs = _require_dict(validated["receipt"].get("inputs"), "existing completion inputs")
        expected_inputs = {
            "initial_launch_intent": str(initial_intent_path.expanduser().resolve()),
            "stage1_state_root": str(state_root.expanduser().resolve()),
            "arm_filename": arm_filename,
            "run_dir": str(run_dir),
        }
        if inputs != expected_inputs:
            raise ValueError("Existing training completion receipt belongs to different inputs")
        return validated
    context = _collect_context(
        initial_intent_path=initial_intent_path,
        state_root=state_root,
        arm_filename=arm_filename,
        run_dir=run_dir,
    )
    before = _capture_identity_inventory(context["evidence_paths"])
    terminal = _query_terminal_allocation(_expected_scheduler_contract(context))
    after = _capture_identity_inventory(context["evidence_paths"])
    receipt = build_receipt(
        initial_intent_path=initial_intent_path,
        state_root=state_root,
        arm_filename=arm_filename,
        run_dir=run_dir,
        context=context,
        terminal_allocation=terminal,
        terminal_toctou_before=before,
        terminal_toctou_after=after,
        dispatch_stage=dispatch_stage,
    )
    write_receipt(output_path, receipt)
    return validate_receipt(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--initial-intent", type=Path, required=True)
    materialize.add_argument("--state-root", type=Path, required=True)
    materialize.add_argument("--arm", required=True)
    materialize.add_argument("--run-dir", type=Path, required=True)
    materialize.add_argument(
        "--dispatch-stage",
        choices=(STAGE1_DISPATCH_STAGE, STAGE2_DISPATCH_STAGE),
        default=STAGE1_DISPATCH_STAGE,
    )
    validate = subparsers.add_parser("validate")
    validate.add_argument("--receipt", type=Path, required=True)
    validate.add_argument("--recheck-live-scheduler", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        validated = materialize_receipt(
            initial_intent_path=args.initial_intent,
            state_root=args.state_root,
            arm_filename=args.arm,
            run_dir=args.run_dir,
            dispatch_stage=args.dispatch_stage,
        )
    else:
        validated = validate_receipt(
            args.receipt,
            recheck_live_scheduler=args.recheck_live_scheduler,
        )
    summary = {
        "command": args.command,
        "receipt": validated["identity"],
        "live_scheduler_rechecked": validated["live_scheduler_recheck"] is not None,
        "scheduler_mutation": False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
