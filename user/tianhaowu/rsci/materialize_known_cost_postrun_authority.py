#!/usr/bin/env python3
"""Freeze known-cost post-run analysis and evaluation execution before RL."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import dispatch_known_cost_boundary as stage1_dispatch
import materialize_known_cost_boundary_launch as launch
import source_provenance

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_postrun_authority"
STUDY_ID = launch.STUDY_ID
AUTHORITY_NAME = "postrun_authority.json"
RESULT_ARTIFACT_TYPE = "rsci_known_cost_boundary_results"
RESULT_ANALYSIS_ID = "known-cost-boundary-results-v1"
REQUIRED_QOS = launch.REQUIRED_DISPATCH_QOS
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_OBJECT_RE = re.compile(r"[0-9a-f]{40,64}")

REPOSITORY_PATHS = {
    "authority_materializer": Path("user/tianhaowu/rsci/materialize_known_cost_postrun_authority.py"),
    "eval_dispatcher": Path("user/tianhaowu/rsci/dispatch_known_cost_eval.py"),
    "eval_planner": Path("user/tianhaowu/rsci/materialize_known_cost_eval_plan.py"),
    "eval_runner": Path("user/tianhaowu/rsci/run_known_cost_eval_task.py"),
    "known_cost_preflight": Path("user/tianhaowu/rsci/analyze_known_cost_boundary_preflight.py"),
    "launch_validator_helpers": Path("user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py"),
    "promoted_eval_authority": Path("user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py"),
    "result_analyzer": Path("user/tianhaowu/rsci/analyze_known_cost_boundary_results.py"),
    "source_provenance": Path("user/tianhaowu/rsci/source_provenance.py"),
    "stage1_dispatcher": Path("user/tianhaowu/rsci/dispatch_known_cost_boundary.py"),
    "training_completion_materializer": Path("user/tianhaowu/rsci/materialize_known_cost_training_completion.py"),
    "training_replay": Path("user/tianhaowu/rsci/analyze_masked_verifier_attempts.py"),
    "training_readout_consumer": Path("user/tianhaowu/rsci/analyze_known_cost_training_readouts.py"),
}


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


def file_identity(path: Path) -> dict[str, Any]:
    return launch.file_identity(path)


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
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


def _write_json_once_atomic(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    content = canonical_json_bytes(payload)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resolved.with_suffix(resolved.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if resolved.exists():
            if not resolved.is_file() or resolved.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace a different immutable post-run authority: {resolved}")
            _require_read_only(resolved, "Post-run authority")
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
    _require_read_only(resolved, "Post-run authority")
    return file_identity(resolved)


def _repository_relative(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    parts = resolved.parts
    marker = ("user", "tianhaowu", "rsci")
    matches = [
        index for index in range(len(parts) - len(marker) + 1) if tuple(parts[index : index + len(marker)]) == marker
    ]
    if len(matches) != 1:
        raise ValueError(f"Cannot derive one repository-relative RSCI path from {resolved}")
    relative = Path(*parts[matches[0] :])
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"Unsafe repository-relative path: {relative}")
    return relative


def _identity_matches(recorded: object, path: Path, label: str) -> dict[str, Any]:
    expected = _require_dict(recorded, label)
    actual = file_identity(path)
    if actual != expected:
        raise ValueError(f"{label} identity changed: {path}")
    return actual


def _content_identity_matches(recorded: object, path: Path, label: str) -> dict[str, Any]:
    expected = _require_dict(recorded, label)
    actual = file_identity(path)
    if actual["size_bytes"] != expected.get("size_bytes") or actual["sha256"] != expected.get("sha256"):
        raise ValueError(f"{label} content differs: {path}")
    return actual


def expected_arm_filenames() -> tuple[str, ...]:
    filenames = tuple(launch._expected_arm_inventory())
    if len(filenames) != 30 or len(set(filenames)) != 30:
        raise RuntimeError("Known-cost launch validator does not declare 30 unique arms")
    return filenames


def _validate_design_partition(intent: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    decision = _require_dict(intent.get("preregistered_decision"), "initial preregistered decision")
    design = decision.get("eligible_design")
    if design == "full_30_arm_grid":
        expected = expected_arm_filenames()
    elif design == "four_arm_smoke_screen":
        expected = tuple(launch.SMOKE_ARM_FILENAMES)
    else:
        raise ValueError(f"Initial launch intent has an unsupported eligible design: {design!r}")
    if decision.get("eligible_arm_count") != len(expected) or decision.get("eligible_arm_filenames") != list(expected):
        raise ValueError(f"Initial launch intent does not authorize the exact {design} partition")
    runs = _require_list(intent.get("eligible_runs"), "initial eligible runs")
    if len(runs) != len(expected) or any(not isinstance(run, dict) for run in runs):
        raise ValueError("Initial launch intent has a malformed eligible-run inventory")
    if [run.get("arm_filename") for run in runs] != list(expected):
        raise ValueError("Initial eligible-run order differs from its exact preregistered partition")
    inventory = _require_list(intent.get("arm_inventory"), "initial arm inventory")
    if any(not isinstance(item, dict) for item in inventory):
        raise ValueError("Initial arm inventory entries must be objects")
    if [str(item.get("arm_filename")) for item in inventory] != list(expected_arm_filenames()):
        raise ValueError("Initial launch intent does not contain the ordered frozen 30-arm inventory")
    eligible = set(expected)
    for item in inventory:
        filename = str(item["arm_filename"])
        expected_status = "eligible" if filename in eligible else "excluded"
        if item.get("decision_status") != expected_status:
            raise ValueError(f"Initial launch partition status differs for {filename}")
    return str(design), expected


def _validated_initial_intent(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    _require_read_only(resolved, "Initial launch intent")
    raw_before, intent = read_canonical_json(resolved)
    if (
        intent.get("schema_version") != launch.SCHEMA_VERSION
        or intent.get("artifact_type") != launch.ARTIFACT_TYPE
        or intent.get("study_id") != STUDY_ID
    ):
        raise ValueError("Initial launch intent has the wrong schema, artifact type, or study")
    _validate_self_hash(intent, "Initial launch intent")
    design, eligible_filenames = _validate_design_partition(intent)
    inputs = _require_dict(intent.get("inputs"), "initial launch inputs")
    run_root = Path(str(inputs.get("run_root"))).expanduser().resolve()
    if resolved != run_root / launch.INTENT_NAME:
        raise ValueError("Initial launch intent is not adjacent to its recorded run root")
    tokenizer_path = Path(str(inputs.get("tokenizer_path"))).expanduser().resolve()
    if not tokenizer_path.exists():
        raise FileNotFoundError(tokenizer_path)
    recorded_validator = _require_dict(intent.get("implementation"), "initial launch validator")
    validator_path = Path(str(recorded_validator.get("path"))).expanduser().resolve()
    if _repository_relative(validator_path) != REPOSITORY_PATHS["launch_validator_helpers"]:
        raise ValueError("Initial intent records the wrong launch-validator repository path")
    _identity_matches(recorded_validator, validator_path, "Initial launch validator")
    _require_read_only(validator_path, "Initial launch validator")
    summary = launch._run_exact_validator(
        validator_path,
        ["validate", "--intent", str(resolved), "--tokenizer", str(tokenizer_path)],
    )
    expected_summary = {
        "command": "validate",
        "intent": file_identity(resolved),
        "eligible_design": design,
        "eligible_arm_count": len(eligible_filenames),
        "submission_performed": False,
    }
    if summary != expected_summary:
        raise ValueError("Recorded launch validator returned a different validation summary")
    raw_after, replayed = read_canonical_json(resolved)
    identity = file_identity(resolved)
    if raw_after != raw_before or replayed != intent or identity != expected_summary["intent"]:
        raise RuntimeError("Initial launch intent changed while its recorded validator was running")
    return {
        "intent": intent,
        "identity": identity,
        "validator": recorded_validator,
        "validation_summary_sha256": canonical_json_sha256(summary),
        "run_root": run_root,
        "tokenizer_path": tokenizer_path,
        "eligible_design": design,
        "eligible_filenames": eligible_filenames,
    }


def _validated_bound_preflight(initial: dict[str, Any]) -> dict[str, Any]:
    production = _require_dict(initial["intent"].get("production_preflight"), "initial production preflight")
    recorded = _require_dict(production.get("report"), "initial preflight report identity")
    path = Path(str(recorded.get("path"))).expanduser().resolve()
    _identity_matches(recorded, path, "Initial preflight report")
    _, report = read_canonical_json(path)
    self_hash = _validate_self_hash(report, "Initial preflight report")
    config = _require_dict(report.get("config_audit"), "preflight config audit")
    arms = _require_dict(config.get("arms"), "preflight arm contracts")
    if config.get("arm_count") != 30 or set(arms) != set(expected_arm_filenames()):
        raise ValueError("Initial preflight does not bind the exact 30-arm inventory")
    if production.get("payload_without_self_hash_sha256") != self_hash:
        raise ValueError("Initial launch intent binds a different preflight self hash")
    return {"path": path, "identity": recorded, "report": report, "arms": arms, "self_hash": self_hash}


def _arm_observation_inventory(initial: dict[str, Any], preflight: dict[str, Any]) -> list[dict[str, Any]]:
    runs = {
        str(_require_dict(run, "initial eligible run").get("arm_filename")): _require_dict(
            run,
            "initial eligible run",
        )
        for run in _require_list(initial["intent"].get("eligible_runs"), "initial eligible runs")
    }
    if tuple(runs) != initial["eligible_filenames"]:
        raise ValueError("Initial eligible runs changed after launch validation")
    eligible = set(initial["eligible_filenames"])
    inventory = []
    for filename in expected_arm_filenames():
        arm = _require_dict(preflight["arms"].get(filename), f"preflight arm {filename}")
        job_name = arm.get("job_name")
        output_dir = Path(str(arm.get("output_dir"))).expanduser().resolve()
        if not isinstance(job_name, str) or not job_name or "," in job_name:
            raise ValueError(f"Preflight arm has an invalid scheduler job name: {filename}")
        if filename in eligible:
            run = runs[filename]
            if run.get("job_name") != job_name or Path(str(run.get("output_dir"))).resolve() != output_dir:
                raise ValueError(f"Eligible run and preflight scheduler/output identity differ for {filename}")
        inventory.append(
            {
                "arm_filename": filename,
                "eligible": filename in eligible,
                "job_name": job_name,
                "output_dir": str(output_dir),
            }
        )
    if len({item["job_name"] for item in inventory}) != 30:
        raise ValueError("The frozen 30-arm scheduler job names are not unique")
    if len({item["output_dir"] for item in inventory}) != 30:
        raise ValueError("The frozen 30-arm output directories are not unique")
    return inventory


def _postrun_source_provenance(control_root: Path, initial: dict[str, Any]) -> dict[str, Any]:
    resolved_root = control_root.expanduser().resolve()
    state = source_provenance.verify_snapshot(
        resolved_root,
        verify_imports=False,
        require_launch=False,
    )
    snapshot = Path(str(state.get("snapshot_path"))).resolve()
    if snapshot != resolved_root / source_provenance.SNAPSHOT_NAME:
        raise ValueError("Post-run control root does not own its recorded source snapshot")
    imported = {
        "authority_materializer": Path(__file__).resolve(),
        "known_cost_preflight": Path(launch.preflight.__file__).resolve(),
        "launch_validator_helpers": Path(launch.__file__).resolve(),
        "source_provenance": Path(source_provenance.__file__).resolve(),
        "stage1_dispatcher": Path(stage1_dispatch.__file__).resolve(),
    }
    for name, path in imported.items():
        expected = snapshot / REPOSITORY_PATHS[name]
        if path != expected:
            raise ValueError(f"{name} must execute from the post-run control snapshot: {expected}")
    implementations = {name: file_identity(snapshot / relative) for name, relative in sorted(REPOSITORY_PATHS.items())}

    _content_identity_matches(
        initial["validator"],
        snapshot / REPOSITORY_PATHS["launch_validator_helpers"],
        "Post-run launch-validator helper",
    )
    dependencies = _require_dict(
        initial["intent"].get("implementation_dependencies"),
        "initial implementation dependencies",
    )
    for successor_name, initial_name in (
        ("known_cost_preflight", "known_cost_preflight"),
        ("source_provenance", "source_provenance"),
    ):
        _content_identity_matches(
            _require_dict(dependencies.get(initial_name), f"initial {initial_name} dependency"),
            snapshot / REPOSITORY_PATHS[successor_name],
            f"Post-run {successor_name} dependency",
        )
    control_source = _require_dict(initial["intent"].get("control_plane_source"), "initial control-plane source")
    historical = _require_dict(control_source.get("implementations"), "initial control-plane implementations")
    for successor_name, historical_name in (
        ("eval_planner", "eval_planner"),
        ("stage1_dispatcher", "dispatcher"),
    ):
        _content_identity_matches(
            _require_dict(historical.get(historical_name), f"initial {historical_name} implementation"),
            snapshot / REPOSITORY_PATHS[successor_name],
            f"Post-run {successor_name}",
        )
    provenance = launch._source_provenance_record(resolved_root, state)
    if GIT_OBJECT_RE.fullmatch(str(provenance.get("parent_commit_sha"))) is None:
        raise ValueError("Post-run source provenance has an invalid parent commit")
    _require_sha256(provenance.get("source_tree_sha256"), "post-run source tree")
    _require_sha256(provenance.get("runtime_identity_sha256"), "post-run runtime identity")
    return {
        **provenance,
        "snapshot_path": str(snapshot),
        "implementations": implementations,
    }


def validate_recorded_implementation(
    authority: dict[str, Any],
    *,
    name: str,
    implementation_path: Path,
) -> dict[str, Any]:
    if name not in REPOSITORY_PATHS:
        raise ValueError(f"Unknown post-run implementation: {name}")
    source = _require_dict(authority.get("postrun_control_source"), "post-run control source")
    implementations = _require_dict(source.get("implementations"), "post-run implementations")
    if set(implementations) != set(REPOSITORY_PATHS):
        raise ValueError("Post-run authority has the wrong implementation inventory")
    expected = _require_dict(implementations.get(name), f"post-run implementation {name}")
    actual = file_identity(implementation_path)
    if actual != expected:
        raise ValueError(f"{name} is not executing from the authority-pinned source snapshot")
    return actual


def _pre_rl_state_scan(arm_inventory: list[dict[str, Any]]) -> dict[str, Any]:
    state_root = launch.REQUIRED_DISPATCH_STATE_ROOT.resolve()
    allowed_entries = {stage1_dispatch.STATE_LOCK_NAME}
    entries = sorted(path.name for path in state_root.iterdir()) if state_root.exists() else []
    unexpected = sorted(set(entries) - allowed_entries)
    if unexpected:
        raise ValueError(
            f"Post-run authority must precede every initial dispatch artifact; found {unexpected} under {state_root}"
        )
    markers = {}
    for arm in arm_inventory:
        filename = str(arm["arm_filename"])
        observed = stage1_dispatch._started_artifacts({"output_dir": arm["output_dir"]})
        if observed:
            raise ValueError(f"Post-run authority must be materialized before arm {filename} starts: {observed}")
        markers[filename] = {
            "output_dir": arm["output_dir"],
            "start_markers": [],
        }
    return {
        "initial_dispatch_state_root": str(state_root),
        "initial_dispatch_state_root_exists": state_root.exists(),
        "state_root_entries": entries,
        "all_arm_start_markers": markers,
    }


def _capture_pre_rl_observation(arm_inventory: list[dict[str, Any]]) -> dict[str, Any]:
    before = _pre_rl_state_scan(arm_inventory)
    job_names = [str(arm["job_name"]) for arm in arm_inventory]
    if len(job_names) != 30 or len(set(job_names)) != 30:
        raise ValueError("Pre-RL scheduler scan requires the exact 30 unique study job names")
    snapshot = stage1_dispatch.scheduler_snapshot(
        start_time=datetime.now(UTC) - timedelta(days=30),
        job_names=job_names,
    )
    if snapshot["records"]:
        jobs = sorted({int(record["job_id"]) for record in snapshot["records"]})
        raise ValueError(f"Post-run authority must be materialized before any study scheduler record exists: {jobs}")
    after = _pre_rl_state_scan(arm_inventory)
    if before != after:
        raise RuntimeError("Initial dispatch state changed during the pre-RL authority observation")
    return {
        "schema_version": 1,
        "observed_at": snapshot["queried_at"],
        "initial_dispatch_lock": str(launch.REQUIRED_DISPATCH_STATE_ROOT.resolve() / stage1_dispatch.STATE_LOCK_NAME),
        "lock_held_through_authority_write": True,
        "state_and_run_scan": after,
        "scheduler_scan": {
            "job_names": sorted(job_names),
            "start_time": snapshot["start_time"],
            "squeue_command": snapshot["squeue_command"],
            "squeue_stdout_sha256": snapshot["squeue_stdout_sha256"],
            "sacct_command": snapshot["sacct_command"],
            "sacct_stdout_sha256": snapshot["sacct_stdout_sha256"],
            "matching_job_count": 0,
        },
    }


def _validate_pre_rl_observation(
    observation: object,
    arm_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    value = _require_dict(observation, "pre-RL observation")
    expected_fields = {
        "schema_version",
        "observed_at",
        "initial_dispatch_lock",
        "lock_held_through_authority_write",
        "state_and_run_scan",
        "scheduler_scan",
    }
    if set(value) != expected_fields:
        raise ValueError("Pre-RL observation has the wrong schema")
    if value.get("schema_version") != 1 or value.get("lock_held_through_authority_write") is not True:
        raise ValueError("Pre-RL observation does not prove serialized authority creation")
    observed_at = stage1_dispatch._parse_utc(value.get("observed_at"), "pre-RL observed_at")
    state_root = launch.REQUIRED_DISPATCH_STATE_ROOT.resolve()
    expected_lock = state_root / stage1_dispatch.STATE_LOCK_NAME
    if value.get("initial_dispatch_lock") != str(expected_lock):
        raise ValueError("Pre-RL observation used the wrong initial dispatch lock")

    scan = _require_dict(value.get("state_and_run_scan"), "pre-RL state and run scan")
    if set(scan) != {
        "initial_dispatch_state_root",
        "initial_dispatch_state_root_exists",
        "state_root_entries",
        "all_arm_start_markers",
    }:
        raise ValueError("Pre-RL state and run scan has the wrong schema")
    if scan.get("initial_dispatch_state_root") != str(state_root):
        raise ValueError("Pre-RL observation used the wrong initial dispatch state root")
    if scan.get("initial_dispatch_state_root_exists") is not True:
        raise ValueError("Pre-RL observation did not hold the initial dispatch state-root lock")
    if scan.get("state_root_entries") != [stage1_dispatch.STATE_LOCK_NAME]:
        raise ValueError("Pre-RL observation contains an initial dispatch artifact")
    marker_records = _require_dict(scan.get("all_arm_start_markers"), "all-arm start markers")
    if set(marker_records) != set(expected_arm_filenames()):
        raise ValueError("Pre-RL observation did not cover the exact 30-arm inventory")
    arms_by_filename = {str(arm["arm_filename"]): arm for arm in arm_inventory}
    for filename in expected_arm_filenames():
        expected_marker = {
            "output_dir": arms_by_filename[filename]["output_dir"],
            "start_markers": [],
        }
        if marker_records.get(filename) != expected_marker:
            raise ValueError(f"Pre-RL marker record differs for {filename}")

    scheduler = _require_dict(value.get("scheduler_scan"), "pre-RL scheduler scan")
    expected_scheduler_fields = {
        "job_names",
        "start_time",
        "squeue_command",
        "squeue_stdout_sha256",
        "sacct_command",
        "sacct_stdout_sha256",
        "matching_job_count",
    }
    if set(scheduler) != expected_scheduler_fields:
        raise ValueError("Pre-RL scheduler scan has the wrong schema")
    expected_job_names = sorted(str(arm["job_name"]) for arm in arm_inventory)
    if scheduler.get("job_names") != expected_job_names or scheduler.get("matching_job_count") != 0:
        raise ValueError("Pre-RL scheduler scan did not establish zero exact study jobs")
    start_time = scheduler.get("start_time")
    if not isinstance(start_time, str):
        raise ValueError("Pre-RL scheduler start time is invalid")
    parsed_start = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    if not timedelta(days=29) <= observed_at - parsed_start <= timedelta(days=31):
        raise ValueError("Pre-RL scheduler scan did not cover the required 30-day lookback")
    name_filter = ",".join(expected_job_names)
    expected_squeue = [
        "squeue",
        "--noheader",
        "--name",
        name_filter,
        f"--format={stage1_dispatch.SQUEUE_FORMAT}",
    ]
    expected_sacct = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--name",
        name_filter,
        "--starttime",
        start_time,
        f"--format={stage1_dispatch.SACCT_FORMAT}",
    ]
    if scheduler.get("squeue_command") != expected_squeue:
        raise ValueError("Pre-RL squeue command is invalid")
    if scheduler.get("sacct_command") != expected_sacct:
        raise ValueError("Pre-RL sacct command is invalid")
    _require_sha256(scheduler.get("squeue_stdout_sha256"), "pre-RL squeue output")
    _require_sha256(scheduler.get("sacct_stdout_sha256"), "pre-RL sacct output")

    global_path = state_root / stage1_dispatch.GLOBAL_INTENT_NAME
    if global_path.exists():
        _, global_intent = read_canonical_json(global_path)
        created_at = stage1_dispatch._parse_utc(
            global_intent.get("created_at"),
            "initial global dispatch created_at",
        )
        if created_at < observed_at:
            raise ValueError("Initial dispatch global intent predates the post-run authority")
    return value


def build_authority(
    *,
    initial_intent_path: Path,
    control_root: Path,
    pre_rl_observation: dict[str, Any],
) -> dict[str, Any]:
    initial = _validated_initial_intent(initial_intent_path)
    preflight = _validated_bound_preflight(initial)
    arm_inventory = _arm_observation_inventory(initial, preflight)
    observation = _validate_pre_rl_observation(pre_rl_observation, arm_inventory)
    postrun_source = _postrun_source_provenance(control_root, initial)
    implementations = _require_dict(postrun_source.get("implementations"), "post-run implementations")
    authority: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "inputs": {
            "run_root": str(initial["run_root"]),
            "initial_launch_intent": str(initial_intent_path.expanduser().resolve()),
            "postrun_control_root": str(control_root.expanduser().resolve()),
        },
        "initial_launch_authority": {
            "intent": initial["identity"],
            "recorded_validator": initial["validator"],
            "validation_summary_sha256": initial["validation_summary_sha256"],
            "tokenizer_path": str(initial["tokenizer_path"]),
            "production_preflight": {
                "report": preflight["identity"],
                "payload_without_self_hash_sha256": preflight["self_hash"],
            },
            "eligible_design": initial["eligible_design"],
            "eligible_arm_count": len(initial["eligible_filenames"]),
            "eligible_arm_filenames": list(initial["eligible_filenames"]),
        },
        "pre_rl_observation": observation,
        "arm_observation_inventory": arm_inventory,
        "postrun_control_source": postrun_source,
        "result_analysis_contract": {
            "artifact_type": RESULT_ARTIFACT_TYPE,
            "analysis_id": RESULT_ANALYSIS_ID,
            "implementation": implementations["result_analyzer"],
            "must_bind_this_authority": True,
            "all_eval_tasks_must_have_succeeded_receipts": True,
        },
        "training_replay_contract": {
            "implementation": implementations["training_replay"],
            "supersedes_incompatible_preflight_replay_for_keep_interval_25": True,
            "must_replay_exact_group_and_attempt_logs": True,
        },
        "stage1_dispatch_contract": {
            "implementation": implementations["stage1_dispatcher"],
            "required_for_every_actual_stage1_dispatch": True,
            "must_validate_postrun_and_smoke_promotion_sidecars_under_dispatch_lock": True,
            "sidecar_identities_must_bind_global_batch_arm_and_receipt_chain": True,
            "direct_dispatch_without_sidecar_validation_authorized": False,
        },
        "training_readout_contract": {
            "implementation": implementations["training_readout_consumer"],
            "completion_receipt_implementation": implementations["training_completion_materializer"],
            "completion_receipt_artifact_type": "rsci_known_cost_training_completion_receipt",
            "completion_receipt_filename": "training_completion_receipt.json",
            "completion_receipt_dispatch_stage": "stage1_initial",
            "stage2_completion_receipt_supported": False,
            "validated_adjacent_receipt_required_per_eligible_run": True,
            "completion_receipt_must_bind_allocation_stdout_and_stderr": True,
            "completion_receipt_must_bind_all_mutable_training_readout_inputs": True,
            "must_bind_exact_training_replay_and_local_event_streams": True,
            "remote_wandb_api_authorized": False,
            "raw_clock_trainer_metrics_must_remain_endpoint_bracketed": True,
            "must_be_embedded_in_result_analysis": True,
        },
        "eval_execution_contract": {
            "planner": implementations["eval_planner"],
            "runner": implementations["eval_runner"],
            "dispatcher": implementations["eval_dispatcher"],
            "required_qos": REQUIRED_QOS,
            "max_tasks_per_dispatch": 5,
            "max_live_jobs": 5,
            "manual_sbatch_authorized": False,
            "must_bind_this_authority": True,
        },
        "checks": {
            "both_preregistered_kernel_branches_supported": True,
            "exact_historical_launch_validator_replayed": True,
            "initial_launch_preflight_and_tokenizer_bound": True,
            "all_30_job_names_and_output_start_markers_absent_before_rl": True,
            "pre_rl_observation_serialized_under_exact_stage1_dispatch_lock": True,
            "result_analyzer_training_consumer_eval_runner_and_eval_dispatcher_content_pinned": True,
            "training_completion_receipt_materializer_content_pinned_before_rl": True,
            "actual_stage1_dispatcher_enforces_pinned_sidecars_directly": True,
            "postrun_source_is_commit_environment_and_runtime_pinned": True,
            "this_tool_performed_no_submission": True,
        },
    }
    authority["payload_without_self_hash_sha256"] = canonical_json_sha256(authority)
    return authority


def write_authority(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    run_root = Path(str(_require_dict(authority.get("inputs"), "authority inputs")["run_root"])).resolve()
    expected = run_root / AUTHORITY_NAME
    if path.expanduser().resolve() != expected:
        raise ValueError(f"Post-run authority must be adjacent to the run root at {expected}")
    return _write_json_once_atomic(expected, authority)


def validate_authority(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    _require_read_only(resolved, "Post-run authority")
    raw, observed = read_canonical_json(resolved)
    if (
        observed.get("schema_version") != SCHEMA_VERSION
        or observed.get("artifact_type") != ARTIFACT_TYPE
        or observed.get("study_id") != STUDY_ID
    ):
        raise ValueError("Post-run authority has the wrong schema, artifact type, or study")
    _validate_self_hash(observed, "Post-run authority")
    inputs = _require_dict(observed.get("inputs"), "authority inputs")
    run_root = Path(str(inputs.get("run_root"))).expanduser().resolve()
    if resolved != run_root / AUTHORITY_NAME:
        raise ValueError("Post-run authority is not adjacent to its recorded run root")
    expected = build_authority(
        initial_intent_path=Path(str(inputs.get("initial_launch_intent"))),
        control_root=Path(str(inputs.get("postrun_control_root"))),
        pre_rl_observation=_require_dict(observed.get("pre_rl_observation"), "pre-RL observation"),
    )
    if raw != canonical_json_bytes(expected):
        raise ValueError("Post-run authority differs from an independent replay of its static inputs")
    return {"authority": observed, "identity": file_identity(resolved)}


def materialize_authority(*, initial_intent_path: Path, control_root: Path) -> dict[str, Any]:
    initial_intent_path = initial_intent_path.expanduser().resolve()
    initial = _validated_initial_intent(initial_intent_path)
    output_path = initial["run_root"] / AUTHORITY_NAME
    state_root = launch.REQUIRED_DISPATCH_STATE_ROOT.resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    state_lock_path = state_root / stage1_dispatch.STATE_LOCK_NAME
    with state_lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if output_path.exists():
            validated = validate_authority(output_path)
            inputs = _require_dict(validated["authority"].get("inputs"), "authority inputs")
            if inputs.get("initial_launch_intent") != str(initial_intent_path) or inputs.get(
                "postrun_control_root"
            ) != str(control_root.expanduser().resolve()):
                raise ValueError("Existing post-run authority belongs to different immutable inputs")
            return validated["identity"]
        initial = _validated_initial_intent(initial_intent_path)
        preflight = _validated_bound_preflight(initial)
        arm_inventory = _arm_observation_inventory(initial, preflight)
        observation = _capture_pre_rl_observation(arm_inventory)
        authority = build_authority(
            initial_intent_path=initial_intent_path,
            control_root=control_root,
            pre_rl_observation=observation,
        )
        write_authority(output_path, authority)
        return validate_authority(output_path)["identity"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--initial-intent", type=Path, required=True)
    materialize.add_argument("--control-root", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--authority", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        identity = materialize_authority(
            initial_intent_path=args.initial_intent,
            control_root=args.control_root,
        )
        summary = {"command": "materialize", "authority": identity, "submission_performed": False}
    else:
        validated = validate_authority(args.authority)
        summary = {"command": "validate", "authority": validated["identity"], "submission_performed": False}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
