#!/usr/bin/env python3
"""Materialize the append-only known-cost smoke-to-grid promotion authority."""

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
STUDY_ID = launch.STUDY_ID
AUTHORITY_ARTIFACT_TYPE = "rsci_known_cost_boundary_promotion_authority"
STAGE2_INTENT_ARTIFACT_TYPE = "rsci_known_cost_boundary_stage2_submission_intent"
AUTHORITY_NAME = "promotion_authority.json"
STAGE2_INTENT_NAME = "stage2_submission_intent.json"
RESULT_ARTIFACT_TYPE = "rsci_known_cost_boundary_results"
RESULT_ANALYSIS_ID = "known-cost-boundary-results-v1"
RESULT_RULE_ID = "op21_40_A_localization_did_v1"
MAX_LIVE_ARMS = 5
REQUIRED_QOS = "h100_ram_high"
REQUIRED_STAGE2_STATE_ROOT = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/dispatch/verifier-defect-known-cost-boundary-v1-stage2"
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_OBJECT_RE = re.compile(r"[0-9a-f]{40,64}")

SMOKE_ARM_FILENAMES = launch.SMOKE_ARM_FILENAMES
SMOKE_DOSES = (0.0125, 0.0375)
REQUIRED_SMOKE_CLOCKS = (
    ("optimizer_step", 375),
    ("optimizer_step", 750),
    ("raw_groups", 3000),
    ("raw_groups", 6000),
)
SMOKE_SPENDING_RULE = {
    "rule_id": RESULT_RULE_ID,
    "readout": "same-source tagged OP21-40 answer-correct/strict-wrong pass@1",
    "estimand": "D_p,c = L_T,p,c - L_G,p,c",
    "localization": ("L_a,p,c = mean_source(mean_selected_two_tags(A) - mean_unselected_four_tags(A))"),
    "block_seed": 20260808,
    "doses": list(SMOKE_DOSES),
    "threshold": 0.02,
    "comparison": "D_A = L_A(persistent_tag_T) - L_A(hidden_group_G)",
    "required_clocks": [{"clock_type": clock_type, "target": target} for clock_type, target in REQUIRED_SMOKE_CLOCKS],
    "raw_clock_rule": "linear interpolation on raw groups between both retained endpoints",
    "require_same_dose_across_all_clocks": True,
    "decision": ("proceed iff at least one fixed smoke dose has D_p,c >= 0.02 at every required clock"),
    "interpretation": "spending screen only; not a p-value or phase-transition test",
}

REPOSITORY_PATHS = {
    "promotion_materializer": Path("user/tianhaowu/rsci/materialize_known_cost_promotion.py"),
    "stage2_dispatcher": Path("user/tianhaowu/rsci/dispatch_known_cost_promotion.py"),
    "result_analyzer": Path("user/tianhaowu/rsci/analyze_known_cost_boundary_results.py"),
    "eval_planner": Path("user/tianhaowu/rsci/materialize_known_cost_eval_plan.py"),
    "known_cost_preflight": Path("user/tianhaowu/rsci/analyze_known_cost_boundary_preflight.py"),
    "launch_validator_helpers": Path("user/tianhaowu/rsci/materialize_known_cost_boundary_launch.py"),
    "stage1_dispatcher_helpers": Path("user/tianhaowu/rsci/dispatch_known_cost_boundary.py"),
    "source_provenance": Path("user/tianhaowu/rsci/source_provenance.py"),
}


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
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
        "sha256": sha256_file(resolved),
    }


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
        raw.decode("utf-8"),
        object_pairs_hook=_object_without_duplicate_keys,
        parse_constant=_reject_nonfinite_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {resolved}")
    if raw != canonical_json_bytes(value):
        raise ValueError(f"JSON artifact is not canonical: {resolved}")
    return raw, value


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


def _validate_stage1_dispatcher_content(
    initial_intent: dict[str, Any],
    implementation_path: Path,
) -> dict[str, Any]:
    initial_control = _require_dict(
        initial_intent.get("control_plane_source"),
        "initial control-plane source",
    )
    implementations = _require_dict(
        initial_control.get("implementations"),
        "initial control-plane implementations",
    )
    return _content_identity_matches(
        _require_dict(implementations.get("dispatcher"), "initial stage1 dispatcher"),
        implementation_path,
        "Promotion stage1 dispatcher helper",
    )


def _validate_self_hash(payload: dict[str, Any], label: str) -> str:
    self_hash = _require_sha256(
        payload.get("payload_without_self_hash_sha256"),
        f"{label} self hash",
    )
    unhashed = dict(payload)
    unhashed.pop("payload_without_self_hash_sha256")
    if canonical_json_sha256(unhashed) != self_hash:
        raise ValueError(f"{label} self hash differs from its canonical payload")
    return self_hash


def _write_json_once_atomic(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = path.expanduser().resolve()
    content = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if path.exists():
            if not path.is_file() or path.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace a different immutable artifact: {path}")
            _require_read_only(path, "Immutable promotion artifact")
            return file_identity(path)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".partial",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o444)
            os.link(temporary, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            temporary.unlink(missing_ok=True)
    _require_read_only(path, "Immutable promotion artifact")
    return file_identity(path)


def _expected_arm_filenames() -> tuple[str, ...]:
    filenames = tuple(launch._expected_arm_inventory())
    if len(filenames) != 30 or len(set(filenames)) != 30:
        raise RuntimeError("Known-cost launch validator does not declare 30 unique arms")
    return filenames


def remaining_arm_filenames() -> tuple[str, ...]:
    smoke = set(SMOKE_ARM_FILENAMES)
    filenames = tuple(filename for filename in _expected_arm_filenames() if filename not in smoke)
    if len(filenames) != 26 or smoke | set(filenames) != set(_expected_arm_filenames()):
        raise RuntimeError("The smoke and stage-2 partitions do not cover the exact 30-arm grid")
    return filenames


def _validate_initial_smoke_partition(intent: dict[str, Any]) -> None:
    if (
        intent.get("schema_version") != launch.SCHEMA_VERSION
        or intent.get("artifact_type") != launch.ARTIFACT_TYPE
        or intent.get("study_id") != STUDY_ID
    ):
        raise ValueError("Initial launch intent has the wrong schema, artifact type, or study")
    decision = _require_dict(intent.get("preregistered_decision"), "initial preregistered decision")
    if decision.get("eligible_design") != "four_arm_smoke_screen":
        raise ValueError("Promotion authority is permitted only for the four-arm smoke decision")
    if decision.get("eligible_arm_count") != 4 or decision.get("eligible_arm_filenames") != list(SMOKE_ARM_FILENAMES):
        raise ValueError("Initial launch intent does not authorize the exact four smoke arms")
    runs = _require_list(intent.get("eligible_runs"), "initial eligible runs")
    if [run.get("arm_filename") for run in runs if isinstance(run, dict)] != list(SMOKE_ARM_FILENAMES):
        raise ValueError("Initial eligible-run order differs from the exact smoke inventory")
    inventory = _require_list(intent.get("arm_inventory"), "initial arm inventory")
    if any(not isinstance(item, dict) for item in inventory):
        raise ValueError("Initial arm inventory entries must be objects")
    by_filename = {str(item.get("arm_filename")): item for item in inventory}
    if len(inventory) != 30 or len(by_filename) != 30 or tuple(by_filename) != _expected_arm_filenames():
        raise ValueError("Initial launch intent does not contain the ordered frozen 30-arm inventory")
    for filename in _expected_arm_filenames():
        expected_status = "eligible" if filename in SMOKE_ARM_FILENAMES else "excluded"
        if by_filename[filename].get("decision_status") != expected_status:
            raise ValueError(f"Initial arm partition is wrong for {filename}")


def _run_recorded_validator(
    implementation: Path,
    arguments: list[str],
) -> dict[str, Any]:
    return launch._run_exact_validator(implementation, arguments)


def _validated_initial_intent(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    _require_read_only(path, "Initial launch intent")
    raw_before, intent = read_canonical_json(path)
    _validate_self_hash(intent, "Initial launch intent")
    _validate_initial_smoke_partition(intent)
    inputs = _require_dict(intent.get("inputs"), "initial launch inputs")
    run_root = Path(str(inputs.get("run_root"))).expanduser().resolve()
    if path != run_root / launch.INTENT_NAME:
        raise ValueError("Initial launch intent is not adjacent to its recorded run root")
    tokenizer_path = Path(str(inputs.get("tokenizer_path"))).expanduser().resolve()
    recorded_validator = _require_dict(intent.get("implementation"), "initial launch validator")
    validator_path = Path(str(recorded_validator.get("path"))).expanduser().resolve()
    if _repository_relative(validator_path) != REPOSITORY_PATHS["launch_validator_helpers"]:
        raise ValueError("Initial intent records the wrong launch-validator repository path")
    _identity_matches(recorded_validator, validator_path, "Initial launch validator")
    _require_read_only(validator_path, "Initial launch validator")
    summary = _run_recorded_validator(
        validator_path,
        ["validate", "--intent", str(path), "--tokenizer", str(tokenizer_path)],
    )
    identity = file_identity(path)
    if summary.get("command") != "validate" or summary.get("intent") != identity:
        raise ValueError("Recorded launch validator did not validate the exact initial intent")
    if (
        summary.get("eligible_design") != "four_arm_smoke_screen"
        or summary.get("eligible_arm_count") != 4
        or summary.get("submission_performed") is not False
    ):
        raise ValueError("Recorded launch validator returned the wrong smoke decision")
    raw_after, replayed = read_canonical_json(path)
    if raw_after != raw_before or replayed != intent or file_identity(path) != identity:
        raise RuntimeError("Initial launch intent changed while its validator was running")
    return {
        "intent": intent,
        "identity": identity,
        "validator": recorded_validator,
        "validation_summary_sha256": canonical_json_sha256(summary),
        "run_root": run_root,
        "tokenizer_path": tokenizer_path,
    }


def _promotion_source_provenance(
    control_root: Path,
    initial: dict[str, Any],
) -> dict[str, Any]:
    control_root = control_root.expanduser().resolve()
    state = source_provenance.verify_snapshot(
        control_root,
        verify_imports=False,
        require_launch=False,
    )
    snapshot = Path(str(state.get("snapshot_path"))).resolve()
    if snapshot != control_root / source_provenance.SNAPSHOT_NAME:
        raise ValueError("Promotion control root does not own its recorded source snapshot")
    imported = {
        "promotion_materializer": Path(__file__).resolve(),
        "known_cost_preflight": Path(launch.preflight.__file__).resolve(),
        "launch_validator_helpers": Path(launch.__file__).resolve(),
        "stage1_dispatcher_helpers": Path(stage1_dispatch.__file__).resolve(),
        "source_provenance": Path(source_provenance.__file__).resolve(),
    }
    for name, path in imported.items():
        expected = snapshot / REPOSITORY_PATHS[name]
        if path != expected:
            raise ValueError(f"{name} must execute from the promotion control snapshot: {expected}")
    implementations = {name: file_identity(snapshot / relative) for name, relative in sorted(REPOSITORY_PATHS.items())}
    _content_identity_matches(
        initial["validator"],
        snapshot / REPOSITORY_PATHS["launch_validator_helpers"],
        "Promotion launch-validator helper",
    )
    dependencies = _require_dict(
        initial["intent"].get("implementation_dependencies"),
        "initial implementation dependencies",
    )
    for name, initial_name in (
        ("source_provenance", "source_provenance"),
        ("known_cost_preflight", "known_cost_preflight"),
    ):
        recorded = _require_dict(dependencies.get(initial_name), f"initial {initial_name} dependency")
        current_path = snapshot / REPOSITORY_PATHS[name]
        _content_identity_matches(recorded, current_path, f"Promotion {name} dependency")
    _validate_stage1_dispatcher_content(
        initial["intent"],
        snapshot / REPOSITORY_PATHS["stage1_dispatcher_helpers"],
    )
    provenance = launch._source_provenance_record(control_root, state)
    if GIT_OBJECT_RE.fullmatch(str(provenance.get("parent_commit_sha"))) is None:
        raise ValueError("Promotion source provenance has an invalid parent commit")
    _require_sha256(provenance.get("source_tree_sha256"), "promotion source tree")
    _require_sha256(provenance.get("runtime_identity_sha256"), "promotion runtime identity")
    return {**provenance, "snapshot_path": str(snapshot), "implementations": implementations}


def validate_recorded_implementation(
    authority: dict[str, Any],
    *,
    name: str,
    implementation_path: Path,
) -> dict[str, Any]:
    if name not in REPOSITORY_PATHS:
        raise ValueError(f"Unknown promotion implementation: {name}")
    source = _require_dict(authority.get("promotion_control_source"), "promotion control source")
    implementations = _require_dict(source.get("implementations"), "promotion implementations")
    if set(implementations) != set(REPOSITORY_PATHS):
        raise ValueError("Promotion authority has the wrong implementation inventory")
    expected = _require_dict(implementations.get(name), f"promotion implementation {name}")
    actual = file_identity(implementation_path)
    if actual != expected:
        raise ValueError(f"{name} is not executing from the authority-pinned source snapshot")
    return actual


def _validated_bound_preflight(initial: dict[str, Any]) -> dict[str, Any]:
    intent = initial["intent"]
    production = _require_dict(intent.get("production_preflight"), "initial production preflight")
    recorded = _require_dict(production.get("report"), "initial preflight report identity")
    path = Path(str(recorded.get("path"))).expanduser().resolve()
    _identity_matches(recorded, path, "Initial preflight report")
    _, report = read_canonical_json(path)
    _validate_self_hash(report, "Initial preflight report")
    config = _require_dict(report.get("config_audit"), "preflight config audit")
    arms = _require_dict(config.get("arms"), "preflight arm contracts")
    if config.get("arm_count") != 30 or set(arms) != set(_expected_arm_filenames()):
        raise ValueError("Initial preflight does not bind the exact 30-arm inventory")
    return {"path": path, "identity": recorded, "report": report, "arms": arms}


def _study_job_inventory(
    preflight_arms: dict[str, Any],
    initial_intent: dict[str, Any],
) -> list[dict[str, Any]]:
    smoke_runs = _require_list(initial_intent.get("eligible_runs"), "initial smoke runs")
    smoke_by_filename = {str(run.get("arm_filename")): run for run in smoke_runs if isinstance(run, dict)}
    accounts = {
        str(
            _require_dict(
                _require_dict(run.get("launcher_config_projection"), "launcher projection").get("projection"),
                "launcher projection payload",
            )["slurm"]["account"]
        )
        for run in smoke_by_filename.values()
    }
    if len(accounts) != 1:
        raise ValueError("Initial smoke runs do not share one sealed SLURM account")
    account = accounts.pop()
    inventory = []
    for filename in _expected_arm_filenames():
        arm = _require_dict(preflight_arms.get(filename), f"preflight arm {filename}")
        job_name = arm.get("job_name")
        if not isinstance(job_name, str) or not job_name or "," in job_name:
            raise ValueError(f"Preflight arm has an invalid scheduler job name: {filename}")
        if filename in smoke_by_filename and smoke_by_filename[filename].get("job_name") != job_name:
            raise ValueError(f"Initial sealed run and preflight job names differ for {filename}")
        inventory.append(
            {
                "arm_filename": filename,
                "stage": "initial_smoke" if filename in SMOKE_ARM_FILENAMES else "stage2_remaining",
                "job_name": job_name,
                "account": account,
                "qos": REQUIRED_QOS,
            }
        )
    if len({item["job_name"] for item in inventory}) != 30:
        raise ValueError("The frozen 30-arm scheduler job names are not unique")
    return inventory


def _pre_rl_state_scan(initial_intent: dict[str, Any]) -> dict[str, Any]:
    state_root = launch.REQUIRED_DISPATCH_STATE_ROOT.resolve()
    allowed_entries = {stage1_dispatch.STATE_LOCK_NAME}
    entries = sorted(path.name for path in state_root.iterdir()) if state_root.exists() else []
    unexpected = sorted(set(entries) - allowed_entries)
    if unexpected:
        raise ValueError(
            f"Promotion authority must precede every initial dispatch artifact; found {unexpected} under {state_root}"
        )
    runs = _require_list(initial_intent.get("eligible_runs"), "initial smoke runs")
    markers = {}
    for run in runs:
        record = _require_dict(run, "initial smoke run")
        filename = str(record.get("arm_filename"))
        observed = stage1_dispatch._started_artifacts(record)
        if observed:
            raise ValueError(f"Promotion authority must be materialized before smoke arm {filename} starts: {observed}")
        markers[filename] = {
            "output_dir": str(Path(str(record.get("output_dir"))).resolve()),
            "start_markers": [],
        }
    if list(markers) != list(SMOKE_ARM_FILENAMES):
        raise ValueError("Pre-RL scan did not cover the exact four smoke arms")
    return {
        "initial_dispatch_state_root": str(state_root),
        "initial_dispatch_state_root_exists": state_root.exists(),
        "state_root_entries": entries,
        "smoke_run_start_markers": markers,
    }


def _capture_pre_rl_observation(initial_intent: dict[str, Any]) -> dict[str, Any]:
    before = _pre_rl_state_scan(initial_intent)
    runs = _require_list(initial_intent.get("eligible_runs"), "initial smoke runs")
    job_names = [str(_require_dict(run, "initial smoke run").get("job_name")) for run in runs]
    if len(job_names) != 4 or len(set(job_names)) != 4 or any(not name or "," in name for name in job_names):
        raise ValueError("Pre-RL scheduler scan requires the exact four unique smoke job names")
    snapshot = stage1_dispatch.scheduler_snapshot(
        start_time=datetime.now(UTC) - timedelta(days=30),
        job_names=job_names,
    )
    if snapshot["records"]:
        jobs = sorted({int(record["job_id"]) for record in snapshot["records"]})
        raise ValueError(f"Promotion authority must be materialized before any smoke scheduler record exists: {jobs}")
    after = _pre_rl_state_scan(initial_intent)
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
    initial_intent: dict[str, Any],
) -> dict[str, Any]:
    value = _require_dict(observation, "pre-RL observation")
    if set(value) != {
        "schema_version",
        "observed_at",
        "initial_dispatch_lock",
        "lock_held_through_authority_write",
        "state_and_run_scan",
        "scheduler_scan",
    }:
        raise ValueError("Pre-RL observation has the wrong schema")
    if value.get("schema_version") != 1 or value.get("lock_held_through_authority_write") is not True:
        raise ValueError("Pre-RL observation does not prove serialized authority creation")
    observed_at = stage1_dispatch._parse_utc(value.get("observed_at"), "pre-RL observed_at")
    expected_state_root = launch.REQUIRED_DISPATCH_STATE_ROOT.resolve()
    expected_lock = expected_state_root / stage1_dispatch.STATE_LOCK_NAME
    if value.get("initial_dispatch_lock") != str(expected_lock):
        raise ValueError("Pre-RL observation used the wrong initial dispatch lock")

    scan = _require_dict(value.get("state_and_run_scan"), "pre-RL state and run scan")
    if set(scan) != {
        "initial_dispatch_state_root",
        "initial_dispatch_state_root_exists",
        "state_root_entries",
        "smoke_run_start_markers",
    }:
        raise ValueError("Pre-RL state and run scan has the wrong schema")
    if scan.get("initial_dispatch_state_root") != str(expected_state_root):
        raise ValueError("Pre-RL observation used the wrong initial dispatch state root")
    entries = scan.get("state_root_entries")
    if not isinstance(entries, list) or any(not isinstance(name, str) for name in entries):
        raise ValueError("Pre-RL state-root entries are invalid")
    if entries != [stage1_dispatch.STATE_LOCK_NAME]:
        raise ValueError("Pre-RL observation contains an initial dispatch artifact")
    if scan.get("initial_dispatch_state_root_exists") is not True:
        raise ValueError("Pre-RL observation did not hold the initial dispatch state-root lock")
    marker_records = _require_dict(scan.get("smoke_run_start_markers"), "smoke start markers")
    if set(marker_records) != set(SMOKE_ARM_FILENAMES):
        raise ValueError("Pre-RL observation did not cover the exact smoke arms")
    runs = {
        str(_require_dict(run, "initial smoke run").get("arm_filename")): _require_dict(run, "initial smoke run")
        for run in _require_list(initial_intent.get("eligible_runs"), "initial smoke runs")
    }
    for filename in SMOKE_ARM_FILENAMES:
        marker = _require_dict(marker_records.get(filename), f"smoke marker record {filename}")
        if marker != {
            "output_dir": str(Path(str(runs[filename].get("output_dir"))).resolve()),
            "start_markers": [],
        }:
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
    expected_job_names = sorted(str(run["job_name"]) for run in runs.values())
    if scheduler.get("job_names") != expected_job_names or scheduler.get("matching_job_count") != 0:
        raise ValueError("Pre-RL scheduler scan did not establish zero exact smoke jobs")
    start_time = scheduler.get("start_time")
    if not isinstance(start_time, str):
        raise ValueError("Pre-RL scheduler start time is invalid")
    parsed_start = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    lookback = observed_at - parsed_start
    if not timedelta(days=29) <= lookback <= timedelta(days=31):
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

    global_path = expected_state_root / stage1_dispatch.GLOBAL_INTENT_NAME
    if global_path.exists():
        _, global_intent = read_canonical_json(global_path)
        created_at = stage1_dispatch._parse_utc(
            global_intent.get("created_at"),
            "initial global dispatch created_at",
        )
        if created_at < observed_at:
            raise ValueError("Initial dispatch global intent predates the pre-RL promotion authority")
    return value


def build_promotion_authority(
    *,
    initial_intent_path: Path,
    control_root: Path,
    pre_rl_observation: dict[str, Any],
) -> dict[str, Any]:
    initial = _validated_initial_intent(initial_intent_path)
    validated_pre_rl_observation = _validate_pre_rl_observation(
        pre_rl_observation,
        initial["intent"],
    )
    preflight = _validated_bound_preflight(initial)
    promotion_source = _promotion_source_provenance(control_root, initial)
    remaining = remaining_arm_filenames()
    preflight_arms = preflight["arms"]
    remaining_contracts = [
        {
            "arm_filename": filename,
            **_require_dict(preflight_arms[filename], f"preflight arm {filename}"),
        }
        for filename in remaining
    ]
    if [contract["arm_filename"] for contract in remaining_contracts] != list(remaining):
        raise RuntimeError("Remaining arm contracts lost their frozen preflight order")
    initial_intent = initial["intent"]
    control_tmux = _require_dict(
        _require_dict(initial_intent.get("dispatch_policy"), "initial dispatch policy").get("required_control_tmux"),
        "initial control tmux",
    )
    job_inventory = _study_job_inventory(preflight_arms, initial_intent)
    run_root = initial["run_root"]
    authority: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": AUTHORITY_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "inputs": {
            "run_root": str(run_root),
            "initial_launch_intent": str(initial_intent_path.expanduser().resolve()),
            "promotion_control_root": str(control_root.expanduser().resolve()),
        },
        "initial_launch_authority": {
            "intent": initial["identity"],
            "recorded_validator": initial["validator"],
            "validation_summary_sha256": initial["validation_summary_sha256"],
            "tokenizer_path": str(initial["tokenizer_path"]),
            "launch_source": initial_intent["launch_source"],
            "production_preflight": {
                "report": preflight["identity"],
                "payload_without_self_hash_sha256": initial_intent["production_preflight"][
                    "payload_without_self_hash_sha256"
                ],
            },
            "eligible_design": "four_arm_smoke_screen",
            "smoke_arm_filenames": list(SMOKE_ARM_FILENAMES),
        },
        "pre_rl_observation": validated_pre_rl_observation,
        "promotion_control_source": promotion_source,
        "smoke_spending_rule": SMOKE_SPENDING_RULE,
        "stage2_arm_partition": {
            "initial_smoke_arm_count": 4,
            "initial_smoke_arm_filenames": list(SMOKE_ARM_FILENAMES),
            "remaining_arm_count": 26,
            "remaining_arm_filenames": list(remaining),
            "remaining_arm_contracts": remaining_contracts,
            "all_30_arm_filenames": list(_expected_arm_filenames()),
        },
        "study_scheduler_inventory": job_inventory,
        "stage2_dispatch_policy": {
            "submission_supported_by_this_tool": False,
            "manual_sbatch_is_not_authorized": True,
            "required_control_tmux": control_tmux,
            "required_state_root": str(REQUIRED_STAGE2_STATE_ROOT),
            "state_root_is_separate_from_initial_dispatch": (
                str(REQUIRED_STAGE2_STATE_ROOT) != str(launch.REQUIRED_DISPATCH_STATE_ROOT.resolve())
            ),
            "max_arms_per_dispatch": MAX_LIVE_ARMS,
            "max_live_arms_across_all_30_job_names": MAX_LIVE_ARMS,
            "required_qos": REQUIRED_QOS,
            "scheduler_override_transport": "explicit_sbatch_cli_v1",
            "required_environment_unsets": ["SBATCH_OUTPUT", "SBATCH_ERROR"],
            "forbidden_arm_filenames": list(SMOKE_ARM_FILENAMES),
        },
        "checks": {
            "initial_intent_replayed_by_its_recorded_pinned_validator": True,
            "initial_decision_is_exact_four_arm_smoke": True,
            "remaining_partition_is_exactly_26_of_the_frozen_30_arms": True,
            "spending_rule_is_frozen_before_smoke_rl_under_the_initial_dispatch_lock": True,
            "result_analyzer_and_stage2_implementations_are_content_pinned": True,
            "promotion_control_source_is_commit_environment_and_runtime_pinned": True,
            "stage2_state_root_is_fixed_and_separate": True,
            "this_tool_performed_no_submission": True,
        },
    }
    authority["payload_without_self_hash_sha256"] = canonical_json_sha256(authority)
    return authority


def write_promotion_authority(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    run_root = Path(str(_require_dict(authority.get("inputs"), "authority inputs")["run_root"])).resolve()
    expected = run_root / AUTHORITY_NAME
    if path.expanduser().resolve() != expected:
        raise ValueError(f"Promotion authority must be adjacent to the run root at {expected}")
    return _write_json_once_atomic(expected, authority)


def validate_promotion_authority(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    _require_read_only(path, "Promotion authority")
    raw, observed = read_canonical_json(path)
    if (
        observed.get("schema_version") != SCHEMA_VERSION
        or observed.get("artifact_type") != AUTHORITY_ARTIFACT_TYPE
        or observed.get("study_id") != STUDY_ID
    ):
        raise ValueError("Promotion authority has the wrong schema, artifact type, or study")
    _validate_self_hash(observed, "Promotion authority")
    inputs = _require_dict(observed.get("inputs"), "promotion authority inputs")
    run_root = Path(str(inputs.get("run_root"))).expanduser().resolve()
    if path != run_root / AUTHORITY_NAME:
        raise ValueError("Promotion authority is not adjacent to its recorded run root")
    expected = build_promotion_authority(
        initial_intent_path=Path(str(inputs.get("initial_launch_intent"))),
        control_root=Path(str(inputs.get("promotion_control_root"))),
        pre_rl_observation=_require_dict(
            observed.get("pre_rl_observation"),
            "promotion pre-RL observation",
        ),
    )
    if raw != canonical_json_bytes(expected):
        raise ValueError("Promotion authority differs from an independent replay of its static inputs")
    return {"authority": observed, "identity": file_identity(path)}


def materialize_promotion_authority(
    *,
    initial_intent_path: Path,
    control_root: Path,
) -> dict[str, Any]:
    initial_intent_path = initial_intent_path.expanduser().resolve()
    _, untrusted = read_canonical_json(initial_intent_path)
    inputs = _require_dict(untrusted.get("inputs"), "initial launch inputs")
    run_root = Path(str(inputs.get("run_root"))).expanduser().resolve()
    output_path = run_root / AUTHORITY_NAME
    if output_path.exists():
        validated = validate_promotion_authority(output_path)
        authority_inputs = _require_dict(validated["authority"].get("inputs"), "authority inputs")
        if authority_inputs.get("initial_launch_intent") != str(initial_intent_path) or authority_inputs.get(
            "promotion_control_root"
        ) != str(control_root.expanduser().resolve()):
            raise ValueError("Existing promotion authority belongs to different immutable inputs")
        return validated["identity"]

    state_root = launch.REQUIRED_DISPATCH_STATE_ROOT.resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    lock_path = state_root / stage1_dispatch.STATE_LOCK_NAME
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if output_path.exists():
            return validate_promotion_authority(output_path)["identity"]
        initial = _validated_initial_intent(initial_intent_path)
        observation = _capture_pre_rl_observation(initial["intent"])
        authority = build_promotion_authority(
            initial_intent_path=initial_intent_path,
            control_root=control_root,
            pre_rl_observation=observation,
        )
        return write_promotion_authority(output_path, authority)


def _analysis_clock_key(record: dict[str, Any]) -> tuple[str, int]:
    clock_type = record.get("clock_type", record.get("clock"))
    target = record.get("target")
    if clock_type not in {"optimizer_step", "raw_groups"}:
        raise ValueError("Smoke analysis target has an invalid clock type")
    if isinstance(target, bool) or not isinstance(target, int):
        raise ValueError("Smoke analysis target has an invalid clock target")
    return str(clock_type), target


def _validate_smoke_spend_decision(decision: object) -> dict[str, Any]:
    value = _require_dict(decision, "smoke spend decision")
    if value.get("rule_id") != RESULT_RULE_ID:
        raise ValueError("Result analysis used the wrong smoke spending rule")
    constants = _require_dict(value.get("constants"), "smoke spend constants")
    if constants.get("block_seed") != 20260808:
        raise ValueError("Smoke decision used the wrong randomization block")
    if constants.get("doses") != list(SMOKE_DOSES):
        raise ValueError("Smoke decision used the wrong paired doses")
    if constants.get("threshold") != 0.02:
        raise ValueError("Smoke decision used the wrong localization threshold")
    if constants.get("comparison") != "D_A = L_A(persistent_tag_T) - L_A(hidden_group_G)":
        raise ValueError("Smoke decision used the wrong T-minus-G comparison")
    if constants.get("L_definition") != ("mean(selected two tags) - mean(unselected four tags), paired by source"):
        raise ValueError("Smoke decision used the wrong localization definition")
    if constants.get("operation_band") != "op21_40":
        raise ValueError("Smoke decision used the wrong operation band")
    if constants.get("threshold_uses_unrounded_values") is not True:
        raise ValueError("Smoke decision did not threshold unrounded estimates")
    if constants.get("require_same_dose_across_all_clocks") is not True:
        raise ValueError("Smoke decision does not require one dose to pass every clock")
    required = _require_list(constants.get("required_clocks"), "smoke required clocks")
    if any(not isinstance(record, dict) for record in required):
        raise ValueError("Smoke required-clock entries must be objects")
    if tuple(_analysis_clock_key(record) for record in required) != REQUIRED_SMOKE_CLOCKS:
        raise ValueError("Smoke decision used the wrong four clocks")

    per_dose_raw = value.get("per_dose")
    if isinstance(per_dose_raw, dict):
        dose_records = list(per_dose_raw.values())
    elif isinstance(per_dose_raw, list):
        dose_records = per_dose_raw
    else:
        raise ValueError("Smoke decision per_dose must be an object or array")
    if any(not isinstance(record, dict) for record in dose_records):
        raise ValueError("Smoke per-dose entries must be objects")
    by_dose: dict[float, dict[str, Any]] = {}
    for record in dose_records:
        dose = record.get("nominal_p", record.get("dose"))
        if isinstance(dose, bool) or not isinstance(dose, (int, float)):
            raise ValueError("Smoke per-dose record has an invalid nominal dose")
        numeric_dose = float(dose)
        if numeric_dose in by_dose:
            raise ValueError("Smoke decision repeats a nominal dose")
        by_dose[numeric_dose] = record
    if set(by_dose) != set(SMOKE_DOSES):
        raise ValueError("Smoke decision does not contain exactly both smoke doses")

    computed_qualifying: list[float] = []
    for dose in SMOKE_DOSES:
        record = by_dose[dose]
        targets = record.get("targets", record.get("required_clock_results"))
        target_records = _require_list(targets, f"smoke targets for dose {dose}")
        if any(not isinstance(target, dict) for target in target_records):
            raise ValueError("Smoke target entries must be objects")
        by_clock: dict[tuple[str, int], dict[str, Any]] = {}
        for target in target_records:
            key = _analysis_clock_key(target)
            if key in by_clock:
                raise ValueError(f"Smoke dose {dose} repeats target {key}")
            by_clock[key] = target
        if tuple(by_clock) != REQUIRED_SMOKE_CLOCKS:
            raise ValueError(f"Smoke dose {dose} does not report the exact ordered four clocks")
        passes_all = True
        for key in REQUIRED_SMOKE_CLOCKS:
            target = by_clock[key]
            estimate = target.get("value", target.get("did"))
            if isinstance(estimate, bool) or not isinstance(estimate, (int, float)):
                raise ValueError(f"Smoke dose {dose} target {key} has no finite numeric estimate")
            numeric = float(estimate)
            if not (-float("inf") < numeric < float("inf")):
                raise ValueError(f"Smoke dose {dose} target {key} estimate is non-finite")
            expected_pass = numeric >= 0.02
            observed_pass = target.get("passes", target.get("passes_threshold"))
            if observed_pass is not expected_pass:
                raise ValueError(f"Smoke dose {dose} target {key} pass flag is inconsistent")
            passes_all = passes_all and expected_pass
        observed_all = record.get(
            "passes_all_required_clocks",
            record.get("qualifies"),
        )
        if observed_all is not passes_all:
            raise ValueError(f"Smoke dose {dose} all-clock decision is inconsistent")
        if passes_all:
            computed_qualifying.append(dose)
    qualifying = value.get("qualifying_doses")
    if qualifying != computed_qualifying:
        raise ValueError("Smoke decision qualifying doses are inconsistent with the four-clock values")
    proceed = value.get("proceed_to_full_grid")
    if proceed is not bool(computed_qualifying):
        raise ValueError("Smoke decision proceed flag is inconsistent with its qualifying doses")
    if value.get("applicable") is not True:
        raise ValueError("Smoke decision is not applicable to the four-arm smoke design")
    expected_status = "proceed_to_full_grid" if proceed else "stop_after_smoke"
    if value.get("decision_status") != expected_status:
        raise ValueError("Smoke decision status is inconsistent with its proceed flag")
    return value


def _validated_result_analysis(
    analysis_path: Path,
    authority_record: dict[str, Any],
) -> dict[str, Any]:
    authority = authority_record["authority"]
    source = _require_dict(authority.get("promotion_control_source"), "promotion control source")
    implementations = _require_dict(source.get("implementations"), "promotion implementations")
    analyzer_identity = _require_dict(implementations.get("result_analyzer"), "result analyzer identity")
    analyzer_path = Path(str(analyzer_identity.get("path"))).resolve()
    _identity_matches(analyzer_identity, analyzer_path, "Authority-pinned result analyzer")
    _require_read_only(analyzer_path, "Authority-pinned result analyzer")
    analysis_path = analysis_path.expanduser().resolve()
    _require_read_only(analysis_path, "Known-cost result analysis")
    raw_before, analysis = read_canonical_json(analysis_path)
    if (
        analysis.get("schema_version") != SCHEMA_VERSION
        or analysis.get("artifact_type") != RESULT_ARTIFACT_TYPE
        or analysis.get("analysis_id") != RESULT_ANALYSIS_ID
    ):
        raise ValueError("Known-cost result analysis has the wrong schema or analysis identity")
    _validate_self_hash(analysis, "Known-cost result analysis")
    summary = _run_recorded_validator(
        analyzer_path,
        ["validate", "--analysis", str(analysis_path)],
    )
    identity = file_identity(analysis_path)
    if summary.get("command") != "validate" or summary.get("analysis") != identity:
        raise ValueError("Pinned result analyzer did not validate the exact analysis artifact")
    raw_after, replayed = read_canonical_json(analysis_path)
    if raw_after != raw_before or replayed != analysis or file_identity(analysis_path) != identity:
        raise RuntimeError("Result analysis changed while its pinned validator was running")
    provenance = _require_dict(analysis.get("provenance"), "result analysis provenance")
    expected_analysis_implementation = {
        "repository_path": REPOSITORY_PATHS["result_analyzer"].as_posix(),
        **analyzer_identity,
    }
    if provenance.get("analysis_implementation") != expected_analysis_implementation:
        raise ValueError("Result analysis was not produced by the authority-pinned analyzer")
    initial_identity = authority["initial_launch_authority"]["intent"]
    if provenance.get("initial_launch_intent") != initial_identity:
        raise ValueError("Result analysis does not bind the exact initial smoke launch intent")
    decision = _validate_smoke_spend_decision(analysis.get("smoke_spend_decision"))
    if summary.get("smoke_proceed_to_full_grid") is not decision["proceed_to_full_grid"]:
        raise ValueError("Result analyzer summary and immutable decision disagree")
    return {
        "analysis": analysis,
        "identity": identity,
        "validator": analyzer_identity,
        "validation_summary_sha256": canonical_json_sha256(summary),
        "smoke_spend_decision": decision,
    }


def _validate_stage2_runs(
    authority: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[str]], dict[str, str]]:
    initial = authority["initial_launch_authority"]
    preflight_identity = _require_dict(
        _require_dict(initial.get("production_preflight"), "authority production preflight").get("report"),
        "authority preflight report identity",
    )
    preflight_path = Path(str(preflight_identity.get("path"))).resolve()
    _identity_matches(preflight_identity, preflight_path, "Authority-bound preflight report")
    _, preflight_report = read_canonical_json(preflight_path)
    tokenizer_path = Path(str(initial.get("tokenizer_path"))).resolve()
    partition = _require_dict(authority.get("stage2_arm_partition"), "stage2 arm partition")
    remaining = partition.get("remaining_arm_filenames")
    if remaining != list(remaining_arm_filenames()):
        raise ValueError("Promotion authority remaining-arm allowlist changed")
    config_audit = _require_dict(preflight_report.get("config_audit"), "preflight config audit")
    arm_reports = _require_dict(config_audit.get("arms"), "preflight arm reports")
    run_root = Path(str(_require_dict(authority.get("inputs"), "authority inputs")["run_root"])).resolve()
    runs = []
    for filename in remaining:
        arm_report = _require_dict(arm_reports.get(filename), f"preflight arm {filename}")
        expected_dir = Path(str(arm_report.get("output_dir"))).resolve()
        if expected_dir != run_root / f"block-{arm_report.get('block_seed')}" / expected_dir.name:
            raise ValueError(f"{filename} output directory is outside the exact study run root")
        runs.append(
            launch._validate_run(
                arm_filename=filename,
                arm_report=arm_report,
                preflight_report=preflight_report,
                tokenizer_path=tokenizer_path,
            )
        )
    initial_intent_path = Path(str(initial["intent"]["path"]))
    _, initial_intent = read_canonical_json(initial_intent_path)
    smoke_runs = _require_list(initial_intent.get("eligible_runs"), "initial eligible runs")
    all_runs = [*smoke_runs, *runs]
    unique_identities = launch._validate_unique_run_identities(all_runs)
    common_source = launch._validate_common_launch_source(all_runs)
    if common_source != initial.get("launch_source"):
        raise ValueError("Stage-2 runs do not use the exact initial launch source and environment")
    return runs, unique_identities, common_source


def build_stage2_intent(
    *,
    authority_path: Path,
    analysis_path: Path,
) -> dict[str, Any]:
    authority_record = validate_promotion_authority(authority_path)
    authority = authority_record["authority"]
    initial_identity_before = file_identity(Path(str(authority["initial_launch_authority"]["intent"]["path"])))
    analysis_record = _validated_result_analysis(analysis_path, authority_record)
    decision = analysis_record["smoke_spend_decision"]
    if decision.get("proceed_to_full_grid") is not True:
        raise ValueError("Smoke spending rule did not authorize promotion to the remaining grid")
    runs, unique_identities, common_source = _validate_stage2_runs(authority)
    initial_identity_after = file_identity(Path(initial_identity_before["path"]))
    if initial_identity_after != initial_identity_before:
        raise RuntimeError("Initial launch intent changed while materializing the stage-2 intent")
    remaining = list(remaining_arm_filenames())
    if [run["arm_filename"] for run in runs] != remaining:
        raise RuntimeError("Validated stage-2 run order differs from the exact remaining allowlist")
    scheduler_by_filename = {item["arm_filename"]: item for item in authority["study_scheduler_inventory"]}
    for run in runs:
        slurm = _require_dict(
            _require_dict(
                _require_dict(
                    run.get("launcher_config_projection"),
                    f"{run['arm_filename']} launcher projection",
                ).get("projection"),
                f"{run['arm_filename']} launcher projection payload",
            ).get("slurm"),
            f"{run['arm_filename']} SLURM projection",
        )
        scheduler = scheduler_by_filename[run["arm_filename"]]
        if slurm.get("account") != scheduler["account"] or run["job_name"] != scheduler["job_name"]:
            raise ValueError(f"{run['arm_filename']} sealed scheduler identity differs from the promotion authority")
    protected_payload = {
        "schema_version": 1,
        "study_id": STUDY_ID,
        "stage": "remaining_26_after_smoke_promotion",
        "max_live_arms_across_all_30_job_names": MAX_LIVE_ARMS,
        "required_qos": REQUIRED_QOS,
        "required_state_root": str(REQUIRED_STAGE2_STATE_ROOT),
        "scheduler_override_transport": "explicit_sbatch_cli_v1",
        "forbidden_initial_smoke_arms": list(SMOKE_ARM_FILENAMES),
        "eligible_arms": [
            {
                "arm_filename": run["arm_filename"],
                "output_dir": run["output_dir"],
                "job_name": run["job_name"],
                "wandb_name": run["wandb_name"],
                "sbatch": run["sbatch"],
                "source_provenance": run["source_provenance"]["manifest"],
                "scientific_config_projection_sha256": run["scientific_config_projection"]["projection_sha256"],
                "parsed_resolved_bundle_sha256": run["scientific_config_projection"]["parsed_resolved_bundle_sha256"],
                "launcher_config_projection_sha256": run["launcher_config_projection"]["projection_sha256"],
            }
            for run in runs
        ],
    }
    source = _require_dict(authority.get("promotion_control_source"), "promotion control source")
    implementations = _require_dict(source.get("implementations"), "promotion implementations")
    validate_recorded_implementation(
        authority,
        name="promotion_materializer",
        implementation_path=Path(__file__),
    )
    intent: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": STAGE2_INTENT_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "inputs": {
            "run_root": authority["inputs"]["run_root"],
            "promotion_authority": str(authority_path.expanduser().resolve()),
            "result_analysis": str(analysis_path.expanduser().resolve()),
        },
        "authority_chain": {
            "promotion_authority": authority_record["identity"],
            "initial_launch_intent": initial_identity_before,
            "result_analysis": analysis_record["identity"],
            "result_analyzer": analysis_record["validator"],
            "result_validation_summary_sha256": analysis_record["validation_summary_sha256"],
        },
        "smoke_spend_decision": decision,
        "promotion_control_source": source,
        "stage2_arm_partition": authority["stage2_arm_partition"],
        "study_scheduler_inventory": authority["study_scheduler_inventory"],
        "eligible_runs": runs,
        "unique_runtime_identities_across_all_30_arms": unique_identities,
        "common_launch_source_across_all_30_arms": common_source,
        "protected_dispatch_plan": {
            "status": "stage2_content_addressed_inventory_only_not_scheduler_authorization",
            "payload": protected_payload,
            "payload_sha256": canonical_json_sha256(protected_payload),
        },
        "dispatch_policy": authority["stage2_dispatch_policy"],
        "implementation": implementations["promotion_materializer"],
        "implementation_dependencies": {
            "launch_validator_helpers": implementations["launch_validator_helpers"],
            "known_cost_preflight": implementations["known_cost_preflight"],
            "eval_planner": implementations["eval_planner"],
            "result_analyzer": implementations["result_analyzer"],
            "source_provenance": implementations["source_provenance"],
            "stage2_dispatcher": implementations["stage2_dispatcher"],
            "stage1_dispatcher_helpers": implementations["stage1_dispatcher_helpers"],
        },
        "checks": {
            "promotion_authority_fully_replayed": True,
            "result_analysis_fully_replayed_by_pinned_analyzer": True,
            "same_dose_passes_all_four_preregistered_smoke_clocks": True,
            "remaining_26_runs_match_initial_preflight_contracts": True,
            "all_30_runs_share_initial_launch_source_and_environment": True,
            "initial_launch_intent_was_not_modified": True,
            "this_tool_performed_no_submission": True,
        },
    }
    intent["payload_without_self_hash_sha256"] = canonical_json_sha256(intent)
    return intent


def write_stage2_intent(path: Path, intent: dict[str, Any]) -> dict[str, Any]:
    run_root = Path(str(_require_dict(intent.get("inputs"), "stage2 inputs")["run_root"])).resolve()
    expected = run_root / STAGE2_INTENT_NAME
    if path.expanduser().resolve() != expected:
        raise ValueError(f"Stage-2 intent must be adjacent to the run root at {expected}")
    return _write_json_once_atomic(expected, intent)


def validate_stage2_intent(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    _require_read_only(path, "Stage-2 submission intent")
    raw, observed = read_canonical_json(path)
    if (
        observed.get("schema_version") != SCHEMA_VERSION
        or observed.get("artifact_type") != STAGE2_INTENT_ARTIFACT_TYPE
        or observed.get("study_id") != STUDY_ID
    ):
        raise ValueError("Stage-2 submission intent has the wrong schema, artifact type, or study")
    _validate_self_hash(observed, "Stage-2 submission intent")
    inputs = _require_dict(observed.get("inputs"), "stage2 intent inputs")
    run_root = Path(str(inputs.get("run_root"))).expanduser().resolve()
    if path != run_root / STAGE2_INTENT_NAME:
        raise ValueError("Stage-2 submission intent is not adjacent to its recorded run root")
    expected = build_stage2_intent(
        authority_path=Path(str(inputs.get("promotion_authority"))),
        analysis_path=Path(str(inputs.get("result_analysis"))),
    )
    if raw != canonical_json_bytes(expected):
        raise ValueError("Stage-2 intent differs from an independent replay of all chained inputs")
    return {"intent": observed, "identity": file_identity(path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize_authority = subparsers.add_parser("materialize-authority")
    materialize_authority.add_argument("--initial-intent", type=Path, required=True)
    materialize_authority.add_argument("--control-root", type=Path, required=True)

    validate_authority = subparsers.add_parser("validate-authority")
    validate_authority.add_argument("--authority", type=Path, required=True)

    materialize_stage2 = subparsers.add_parser("materialize-stage2")
    materialize_stage2.add_argument("--authority", type=Path, required=True)
    materialize_stage2.add_argument("--analysis", type=Path, required=True)

    validate_stage2 = subparsers.add_parser("validate-stage2")
    validate_stage2.add_argument("--intent", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize-authority":
        identity = materialize_promotion_authority(
            initial_intent_path=args.initial_intent,
            control_root=args.control_root,
        )
        result = {
            "command": "materialize-authority",
            "authority": identity,
            "remaining_arm_count": 26,
            "submission_performed": False,
        }
    elif args.command == "validate-authority":
        validated = validate_promotion_authority(args.authority)
        result = {
            "command": "validate-authority",
            "authority": validated["identity"],
            "remaining_arm_count": 26,
            "submission_performed": False,
        }
    elif args.command == "materialize-stage2":
        intent = build_stage2_intent(
            authority_path=args.authority,
            analysis_path=args.analysis,
        )
        run_root = Path(intent["inputs"]["run_root"])
        identity = write_stage2_intent(run_root / STAGE2_INTENT_NAME, intent)
        result = {
            "command": "materialize-stage2",
            "intent": identity,
            "eligible_arm_count": 26,
            "submission_performed": False,
        }
    elif args.command == "validate-stage2":
        validated = validate_stage2_intent(args.intent)
        result = {
            "command": "validate-stage2",
            "intent": validated["identity"],
            "eligible_arm_count": 26,
            "submission_performed": False,
        }
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
