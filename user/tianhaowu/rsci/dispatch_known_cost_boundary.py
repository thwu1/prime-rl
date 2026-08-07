#!/usr/bin/env python3
"""Protected SLURM dispatcher for the sealed known-cost boundary pilot."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import materialize_known_cost_boundary_launch as launch

SCHEMA_VERSION = 1
STUDY_ID = launch.STUDY_ID
REQUIRED_DISPATCH_QOS = launch.REQUIRED_DISPATCH_QOS
REQUIRED_DISPATCH_STATE_ROOT = launch.REQUIRED_DISPATCH_STATE_ROOT.resolve()
MAX_ARMS_PER_INVOCATION = 5
COMMENT_PREFIX = "rsci-known-cost-v1-"
COMMENT_RE = re.compile(rf"{COMMENT_PREFIX}[0-9a-f]{{64}}")
JOB_ID_RE = re.compile(r"[1-9][0-9]*")
ARM_FILENAME_RE = re.compile(r"[a-z0-9_]+\.toml")
SCRIPT_REPOSITORY_PATH = "user/tianhaowu/rsci/dispatch_known_cost_boundary.py"
POSTRUN_AUTHORITY_NAME = "postrun_authority.json"
PROMOTION_AUTHORITY_NAME = "promotion_authority.json"
POSTRUN_AUTHORITY_REPOSITORY_PATH = "user/tianhaowu/rsci/materialize_known_cost_postrun_authority.py"
PROMOTION_AUTHORITY_REPOSITORY_PATH = "user/tianhaowu/rsci/materialize_known_cost_promotion.py"
GLOBAL_INTENT_NAME = "global_submission_intent.json"
STATE_LOCK_NAME = "dispatch.lock"
GLOBAL_ARTIFACT_TYPE = "rsci_known_cost_global_dispatch_intent"
BATCH_ARTIFACT_TYPE = "rsci_known_cost_dispatch_batch_intent"
ARM_ARTIFACT_TYPE = "rsci_known_cost_arm_dispatch_intent"
RECEIPT_ARTIFACT_TYPE = "rsci_known_cost_arm_submission_receipt"
START_MARKER_NAMES = (
    "checkpoints",
    "logs",
    "run_default",
    "wandb",
    "weights",
)
SBATCH_COMMAND_PREFIX = (
    "env",
    "-u",
    "SBATCH_OUTPUT",
    "-u",
    "SBATCH_ERROR",
    "sbatch",
    "--parsable",
)
SQUEUE_FORMAT = "%i|%1000k|%200j|%100a|%100q|%T"
SACCT_FORMAT = "JobIDRaw,Comment,JobName,Account,QOS,State"
TERMINAL_SLURM_STATES = {
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
    path = path.expanduser().resolve()
    content = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise FileExistsError(f"Refusing to replace a different immutable dispatch artifact: {path}")
        _require_read_only(path, "Immutable dispatch artifact")
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
    _require_read_only(path, "Immutable dispatch artifact")
    return file_identity(path)


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _safe_arm_key(arm_filename: str) -> str:
    if ARM_FILENAME_RE.fullmatch(arm_filename) is None:
        raise ValueError(f"Unsafe arm filename: {arm_filename!r}")
    return arm_filename.removesuffix(".toml")


def load_authority(intent_path: Path) -> dict[str, Any]:
    intent_path = intent_path.expanduser().resolve()
    _, untrusted = read_canonical_json(intent_path)
    inputs = _require_dict(untrusted.get("inputs"), "launch intent inputs")
    tokenizer_path = Path(str(inputs.get("tokenizer_path"))).expanduser().resolve()
    validated = launch.validate_intent(intent_path, tokenizer_path=tokenizer_path)
    intent = validated["intent"]
    launch.validate_control_plane_implementation(
        intent,
        name="dispatcher",
        implementation_path=Path(__file__),
    )
    if intent.get("study_id") != STUDY_ID:
        raise ValueError("Launch intent has the wrong study identity")
    protected = _require_dict(intent.get("protected_dispatch_plan"), "protected dispatch plan")
    if protected.get("status") != "content_addressed_inventory_only_not_scheduler_authorization":
        raise ValueError("Launch intent protected dispatch plan has the wrong status")
    payload = _require_dict(protected.get("payload"), "protected dispatch payload")
    payload_sha256 = _require_sha256(protected.get("payload_sha256"), "protected dispatch payload hash")
    if canonical_json_sha256(payload) != payload_sha256:
        raise ValueError("Protected dispatch payload hash differs")
    if (
        payload.get("study_id") != STUDY_ID
        or payload.get("eligible_design") != intent["preregistered_decision"]["eligible_design"]
    ):
        raise ValueError("Protected dispatch payload differs from the preregistered decision")
    if payload.get("required_qos") != REQUIRED_DISPATCH_QOS:
        raise ValueError("Protected dispatch payload has the wrong required QoS")
    if payload.get("max_live_arms") != MAX_ARMS_PER_INVOCATION:
        raise ValueError("Protected dispatch payload has the wrong study-wide live-arm cap")
    if payload.get("required_state_root") != str(REQUIRED_DISPATCH_STATE_ROOT):
        raise ValueError("Protected dispatch payload has the wrong required state root")
    if payload.get("scheduler_override_transport") != "explicit_sbatch_cli_v1":
        raise ValueError("Protected dispatch payload has the wrong scheduler override transport")

    full_runs = intent.get("eligible_runs")
    payload_arms = payload.get("eligible_arms")
    inventory = intent.get("arm_inventory")
    if not isinstance(full_runs, list) or not isinstance(payload_arms, list) or not isinstance(inventory, list):
        raise ValueError("Launch intent does not contain complete arm inventories")
    if any(not isinstance(item, dict) for collection in (full_runs, payload_arms, inventory) for item in collection):
        raise ValueError("Launch intent arm inventories must contain only objects")
    run_by_filename = {str(run.get("arm_filename")): run for run in full_runs}
    payload_by_filename = {str(arm.get("arm_filename")): arm for arm in payload_arms}
    inventory_by_filename = {str(arm.get("arm_filename")): arm for arm in inventory}
    eligible_filenames = intent["preregistered_decision"]["eligible_arm_filenames"]
    if (
        not isinstance(eligible_filenames, list)
        or any(not isinstance(filename, str) for filename in eligible_filenames)
        or len(set(eligible_filenames)) != len(eligible_filenames)
        or len(run_by_filename) != len(full_runs)
        or len(payload_by_filename) != len(payload_arms)
        or len(inventory_by_filename) != len(inventory)
        or set(run_by_filename) != set(eligible_filenames)
        or set(payload_by_filename) != set(eligible_filenames)
        or len(inventory_by_filename) != 30
    ):
        raise ValueError("Launch intent does not exactly partition eligible and excluded arms")
    for filename in eligible_filenames:
        run = run_by_filename[filename]
        arm = payload_by_filename[filename]
        expected = {
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
        if arm != expected:
            raise ValueError(f"Protected dispatch arm differs from sealed run {filename}")
        if inventory_by_filename[filename].get("decision_status") != "eligible":
            raise ValueError(f"Eligible arm is not marked eligible in the 30-arm inventory: {filename}")
    excluded = set(inventory_by_filename) - set(eligible_filenames)
    if any(inventory_by_filename[name].get("decision_status") != "excluded" for name in excluded):
        raise ValueError("The 30-arm inventory has an invalid excluded partition")

    policy = _require_dict(intent.get("dispatch_policy"), "dispatch policy")
    if policy.get("max_arms_per_dispatch") != MAX_ARMS_PER_INVOCATION:
        raise ValueError("Launch intent dispatch cap differs")
    if policy.get("max_live_arms") != MAX_ARMS_PER_INVOCATION:
        raise ValueError("Launch intent study-wide live-arm cap differs")
    if policy.get("required_environment_unsets") != ["SBATCH_OUTPUT", "SBATCH_ERROR"]:
        raise ValueError("Launch intent environment-unset contract differs")
    if policy.get("required_qos") != REQUIRED_DISPATCH_QOS:
        raise ValueError("Launch intent dispatch QoS differs")
    if policy.get("required_state_root") != str(REQUIRED_DISPATCH_STATE_ROOT):
        raise ValueError("Launch intent dispatch state root differs")
    if policy.get("required_scheduler_cli_overrides") != {
        "account": "sealed_sbatch_account",
        "comment": "content_addressed_per_arm",
        "qos": REQUIRED_DISPATCH_QOS,
    }:
        raise ValueError("Launch intent scheduler CLI override contract differs")
    control_tmux = _require_dict(policy.get("required_control_tmux"), "required control tmux")
    if set(control_tmux) != {"socket", "session", "window"} or any(
        not isinstance(control_tmux[key], str) or not control_tmux[key] for key in control_tmux
    ):
        raise ValueError("Launch intent control tmux contract is invalid")
    return {
        "intent": intent,
        "intent_path": str(intent_path),
        "intent_identity": validated["identity"],
        "tokenizer_path": str(tokenizer_path),
        "run_root": str(Path(inputs["run_root"]).expanduser().resolve()),
        "protected_payload": payload,
        "protected_payload_sha256": payload_sha256,
        "eligible_filenames": list(eligible_filenames),
        "run_by_filename": run_by_filename,
        "payload_by_filename": payload_by_filename,
        "inventory_by_filename": inventory_by_filename,
        "control_tmux": control_tmux,
        "required_qos": REQUIRED_DISPATCH_QOS,
    }


def _recorded_control_plane_validator(
    authority: dict[str, Any],
    *,
    name: str,
    repository_path: str,
) -> tuple[Path, dict[str, Any]]:
    intent = _require_dict(authority.get("intent"), "launch intent")
    source = _require_dict(intent.get("control_plane_source"), "launch control-plane source")
    implementations = _require_dict(source.get("implementations"), "launch control-plane implementations")
    identity = _require_dict(implementations.get(name), f"launch implementation {name}")
    path = Path(str(identity.get("path"))).expanduser().resolve()
    if launch._repository_relative(path).as_posix() != repository_path:
        raise ValueError(f"Launch intent records the wrong {name} repository path")
    if file_identity(path) != identity:
        raise ValueError(f"Launch intent {name} bytes changed")
    _require_read_only(path, f"Pinned {name}")
    return path, identity


def _validate_sidecar(
    *,
    path: Path,
    validator_path: Path,
    arguments: list[str],
    expected_summary: dict[str, Any],
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = path.expanduser().resolve()
    _require_read_only(resolved, label)
    raw_before, payload = read_canonical_json(resolved)
    identity = file_identity(resolved)
    summary = launch._run_exact_validator(validator_path, arguments)
    if summary != expected_summary | {"authority": identity}:
        raise ValueError(f"Recorded {label} validator returned a different summary")
    raw_after, replayed = read_canonical_json(resolved)
    if raw_after != raw_before or replayed != payload or file_identity(resolved) != identity:
        raise RuntimeError(f"{label} changed while its recorded validator ran")
    return payload, identity


def validate_sidecar_authorities(authority: dict[str, Any]) -> dict[str, Any]:
    intent_identity = _require_dict(authority.get("intent_identity"), "launch intent identity")
    run_root = Path(str(authority.get("run_root"))).expanduser().resolve()
    postrun_path = run_root / POSTRUN_AUTHORITY_NAME
    postrun_validator, pinned_postrun_validator = _recorded_control_plane_validator(
        authority,
        name="postrun_authority_materializer",
        repository_path=POSTRUN_AUTHORITY_REPOSITORY_PATH,
    )
    postrun, postrun_identity = _validate_sidecar(
        path=postrun_path,
        validator_path=postrun_validator,
        arguments=["validate", "--authority", str(postrun_path)],
        expected_summary={"command": "validate", "submission_performed": False},
        label="post-run authority",
    )
    initial = _require_dict(postrun.get("initial_launch_authority"), "post-run launch authority")
    if initial.get("intent") != intent_identity:
        raise ValueError("Post-run authority and Stage-1 launch intent differ")
    postrun_source = _require_dict(postrun.get("postrun_control_source"), "post-run control source")
    postrun_implementations = _require_dict(postrun_source.get("implementations"), "post-run implementations")
    dispatcher_identity = file_identity(Path(__file__))
    if postrun_implementations.get("stage1_dispatcher") != dispatcher_identity:
        raise ValueError("Post-run authority does not pin this exact Stage-1 dispatcher")
    contract = _require_dict(postrun.get("stage1_dispatch_contract"), "Stage-1 dispatch contract")
    if contract.get("implementation") != dispatcher_identity:
        raise ValueError("Post-run Stage-1 contract binds a different dispatcher")
    if postrun_implementations.get("authority_materializer") != pinned_postrun_validator:
        raise ValueError("Post-run authority was not built by the launch-pinned validator")

    decision = _require_dict(authority["intent"].get("preregistered_decision"), "launch decision")
    design = decision.get("eligible_design")
    promotion_path = run_root / PROMOTION_AUTHORITY_NAME
    promotion_identity = None
    if design == "four_arm_smoke_screen":
        promotion_validator, pinned_promotion_validator = _recorded_control_plane_validator(
            authority,
            name="promotion_authority_materializer",
            repository_path=PROMOTION_AUTHORITY_REPOSITORY_PATH,
        )
        promotion, promotion_identity = _validate_sidecar(
            path=promotion_path,
            validator_path=promotion_validator,
            arguments=["validate-authority", "--authority", str(promotion_path)],
            expected_summary={
                "command": "validate-authority",
                "remaining_arm_count": 26,
                "submission_performed": False,
            },
            label="promotion authority",
        )
        promotion_launch = _require_dict(
            promotion.get("initial_launch_authority"),
            "promotion launch authority",
        )
        if promotion_launch.get("intent") != intent_identity:
            raise ValueError("Promotion authority and Stage-1 launch intent differ")
        promotion_source = _require_dict(promotion.get("promotion_control_source"), "promotion control source")
        promotion_implementations = _require_dict(
            promotion_source.get("implementations"),
            "promotion implementations",
        )
        if promotion_implementations.get("promotion_materializer") != pinned_promotion_validator:
            raise ValueError("Promotion authority was not built by the launch-pinned validator")
    elif design == "full_30_arm_grid":
        if os.path.lexists(promotion_path):
            raise ValueError("A full-grid Stage-1 launch must not have a smoke promotion authority")
    else:
        raise ValueError(f"Unsupported Stage-1 eligible design: {design!r}")
    return {
        "postrun_authority": postrun_identity,
        "promotion_authority": promotion_identity,
    }


def bind_sidecar_authorities(authority: dict[str, Any]) -> dict[str, Any]:
    return {**authority, "sidecar_authorities": validate_sidecar_authorities(authority)}


def revalidate_locked_authority(
    intent_path: Path,
    *,
    initial_intent: dict[str, Any],
    initial_sidecars: dict[str, Any],
    operation: str,
) -> dict[str, Any]:
    authority = bind_sidecar_authorities(load_authority(intent_path))
    if authority["intent_identity"] != initial_intent:
        raise RuntimeError(f"Stage-1 launch intent changed before locked {operation}")
    if authority["sidecar_authorities"] != initial_sidecars:
        raise RuntimeError(f"Stage-1 sidecar authorities changed before locked {operation}")
    return authority


def _require_sidecar_identities(sidecars: dict[str, Any]) -> None:
    expected_fields = {"postrun_authority", "promotion_authority"}
    if set(sidecars) != expected_fields:
        raise ValueError("Stage-1 sidecar authority record has the wrong exact schema")
    postrun = _require_dict(sidecars.get("postrun_authority"), "post-run authority identity")
    postrun_path = Path(str(postrun.get("path")))
    _require_read_only(postrun_path, "Post-run authority")
    if file_identity(postrun_path) != postrun:
        raise ValueError("Post-run authority changed before Stage-1 submission")
    promotion = sidecars.get("promotion_authority")
    if promotion is not None:
        promotion = _require_dict(promotion, "promotion authority identity")
        promotion_path = Path(str(promotion.get("path")))
        _require_read_only(promotion_path, "Promotion authority")
        if file_identity(promotion_path) != promotion:
            raise ValueError("Promotion authority changed before Stage-1 submission")


def _require_launch_intent_identity(identity: dict[str, Any]) -> None:
    path = Path(str(identity.get("path")))
    _require_read_only(path, "Launch intent")
    if file_identity(path) != identity:
        raise ValueError("Launch intent changed before Stage-1 submission")


def select_arms(authority: dict[str, Any], requested: list[str]) -> list[dict[str, Any]]:
    if not requested:
        raise ValueError("At least one explicit --arm is required")
    if len(requested) > MAX_ARMS_PER_INVOCATION:
        raise ValueError(f"At most {MAX_ARMS_PER_INVOCATION} arms may be dispatched per invocation")
    if len(requested) != len(set(requested)):
        raise ValueError("Duplicate --arm values are forbidden")
    selected = []
    for filename in requested:
        inventory = authority["inventory_by_filename"].get(filename)
        if inventory is None:
            raise ValueError(f"Unknown arm outside the frozen 30-arm inventory: {filename}")
        if inventory.get("decision_status") != "eligible":
            raise ValueError(f"Arm is excluded by the preregistered kernel decision: {filename}")
        if filename not in authority["run_by_filename"]:
            raise ValueError(f"Eligible arm is absent from the protected dispatch payload: {filename}")
        selected.append(authority["run_by_filename"][filename])
    return selected


def validate_state_root(state_root: Path, authority: dict[str, Any]) -> Path:
    configured = state_root.expanduser()
    if not configured.is_absolute():
        raise ValueError("--state-root must be absolute")
    resolved = configured.resolve()
    if resolved != REQUIRED_DISPATCH_STATE_ROOT:
        raise ValueError(f"--state-root must exactly match the launch authority: {REQUIRED_DISPATCH_STATE_ROOT}")
    protected_roots = [Path(authority["run_root"]).resolve()]
    protected_roots.extend(Path(run["output_dir"]).resolve() for run in authority["run_by_filename"].values())
    for protected in protected_roots:
        if resolved == protected or resolved.is_relative_to(protected) or protected.is_relative_to(resolved):
            raise ValueError(f"Dispatch state root overlaps a production run directory: {protected}")
    return resolved


def _directive_values(path: Path, name: str) -> list[str]:
    prefix = f"#SBATCH --{name}="
    return [
        line.removeprefix(prefix) for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(prefix)
    ]


def scheduler_contract(run: dict[str, Any]) -> dict[str, Any]:
    sbatch = Path(run["sbatch"]["path"]).resolve()
    if file_identity(sbatch) != run["sbatch"]:
        raise ValueError(f"Sealed SLURM script changed for {run['arm_filename']}")
    account_values = _directive_values(sbatch, "account")
    job_name_values = _directive_values(sbatch, "job-name")
    qos_values = _directive_values(sbatch, "qos")
    comment_values = _directive_values(sbatch, "comment")
    if len(account_values) != 1 or len(job_name_values) != 1 or len(qos_values) > 1:
        raise ValueError(f"Sealed SLURM scheduler directives are ambiguous for {run['arm_filename']}")
    if comment_values:
        raise ValueError(f"Sealed SLURM script already has a comment for {run['arm_filename']}")
    projection = run["launcher_config_projection"]["projection"]["slurm"]
    if account_values[0] != projection["account"] or job_name_values[0] != run["job_name"]:
        raise ValueError(f"Sealed SLURM account or job name differs for {run['arm_filename']}")
    projected_qos = projection.get("qos")
    sealed_qos = qos_values[0] if qos_values else None
    if projected_qos is not None and projected_qos != REQUIRED_DISPATCH_QOS:
        raise ValueError(f"Launcher projection conflicts with the required QoS for {run['arm_filename']}")
    if sealed_qos is not None and sealed_qos != REQUIRED_DISPATCH_QOS:
        raise ValueError(f"Sealed SLURM script conflicts with the required QoS for {run['arm_filename']}")
    return {
        "account": account_values[0],
        "qos": REQUIRED_DISPATCH_QOS,
        "sealed_qos_directive": sealed_qos,
        "job_name": job_name_values[0],
    }


def submission_comment(authority: dict[str, Any], run: dict[str, Any]) -> str:
    material = {
        "domain": "rsci-known-cost-boundary-protected-dispatch-v1",
        "study_id": STUDY_ID,
        "launch_intent_sha256": authority["intent_identity"]["sha256"],
        "protected_dispatch_payload_sha256": authority["protected_payload_sha256"],
        "arm_filename": run["arm_filename"],
        "sbatch_sha256": run["sbatch"]["sha256"],
        "source_provenance_sha256": run["source_provenance"]["manifest"]["sha256"],
        "scientific_config_projection_sha256": run["scientific_config_projection"]["projection_sha256"],
        "launcher_config_projection_sha256": run["launcher_config_projection"]["projection_sha256"],
        "sidecar_authorities": _authority_sidecars(authority),
    }
    return f"{COMMENT_PREFIX}{canonical_json_sha256(material)}"


def build_arm_plan(authority: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    comment = submission_comment(authority, run)
    if COMMENT_RE.fullmatch(comment) is None:
        raise RuntimeError("Derived SLURM comment is invalid")
    scheduler = scheduler_contract(run)
    command = [
        *SBATCH_COMMAND_PREFIX,
        f"--comment={comment}",
        f"--qos={scheduler['qos']}",
        f"--account={scheduler['account']}",
        run["sbatch"]["path"],
    ]
    return {
        "arm_filename": run["arm_filename"],
        "output_dir": run["output_dir"],
        "sbatch": run["sbatch"],
        "source_provenance": run["source_provenance"]["manifest"],
        "comment": comment,
        "command": command,
        "scheduler": scheduler,
        "submission_environment": {
            "set": {},
            "remove_all_other_sbatch_variables": True,
            "scheduler_overrides_are_explicit_cli_arguments": True,
        },
    }


def _execution_environment(arm_plan: dict[str, Any]) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SBATCH_")}
    environment.update(arm_plan["submission_environment"]["set"])
    return environment


def _validate_arm_plan_sbatch(arm_plan: dict[str, Any]) -> None:
    path = Path(arm_plan["sbatch"]["path"])
    if file_identity(path) != arm_plan["sbatch"]:
        raise ValueError(f"Sealed SLURM script changed for {arm_plan['arm_filename']}")


def _dispatcher_identity() -> dict[str, Any]:
    return {
        "repository_path": SCRIPT_REPOSITORY_PATH,
        **file_identity(Path(__file__)),
    }


def _authority_sidecars(authority: dict[str, Any]) -> dict[str, Any]:
    sidecars = _require_dict(authority.get("sidecar_authorities"), "Stage-1 sidecar authorities")
    _require_sidecar_identities(sidecars)
    return sidecars


def global_intent(
    *,
    authority: dict[str, Any],
    state_root: Path,
    created_at: str,
) -> dict[str, Any]:
    _parse_utc(created_at, "global intent created_at")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": GLOBAL_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "state_root": str(state_root),
        "launch_intent": authority["intent_identity"],
        "protected_dispatch_payload_sha256": authority["protected_payload_sha256"],
        "eligible_design": authority["intent"]["preregistered_decision"]["eligible_design"],
        "eligible_arm_filenames": authority["eligible_filenames"],
        "sidecar_authorities": _authority_sidecars(authority),
        "control_tmux": authority["control_tmux"],
        "dispatcher": _dispatcher_identity(),
        "dispatch_contract": {
            "max_arms_per_invocation": MAX_ARMS_PER_INVOCATION,
            "max_live_arms": MAX_ARMS_PER_INVOCATION,
            "required_state_root": str(REQUIRED_DISPATCH_STATE_ROOT),
            "command_prefix": list(SBATCH_COMMAND_PREFIX),
            "scheduler_cli_option_order": ["comment", "qos", "account"],
            "scheduler_account_must_match_sealed_sbatch": True,
            "required_qos": REQUIRED_DISPATCH_QOS,
            "sealed_qos_directive_must_not_conflict": True,
            "ambiguous_submission_requires_exact_comment_reconciliation": True,
        },
    }


def validate_global_intent(path: Path, authority: dict[str, Any], state_root: Path) -> dict[str, Any]:
    _require_read_only(path, "Global dispatch intent")
    _, observed = read_canonical_json(path)
    expected = global_intent(
        authority=authority,
        state_root=state_root,
        created_at=str(observed.get("created_at")),
    )
    if observed != expected:
        raise ValueError("Global dispatch intent differs from the finalized launch authority")
    return observed


def batch_intent(
    *,
    global_path: Path,
    arm_plans: list[dict[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    _parse_utc(created_at, "batch intent created_at")
    _, global_record = read_canonical_json(global_path)
    sidecars = _require_dict(global_record.get("sidecar_authorities"), "global sidecar authorities")
    _require_sidecar_identities(sidecars)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": BATCH_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "global_submission_intent": file_identity(global_path),
        "sidecar_authorities": sidecars,
        "arm_count": len(arm_plans),
        "arms": [
            {
                "arm_filename": plan["arm_filename"],
                "comment": plan["comment"],
                "command": plan["command"],
            }
            for plan in arm_plans
        ],
    }


def validate_batch_intent(path: Path, global_path: Path) -> dict[str, Any]:
    _require_read_only(path, "Batch dispatch intent")
    raw, observed = read_canonical_json(path)
    if path.stem != hashlib.sha256(raw).hexdigest():
        raise ValueError(f"Batch intent filename is not its exact file SHA-256: {path}")
    if (
        observed.get("schema_version") != SCHEMA_VERSION
        or observed.get("artifact_type") != BATCH_ARTIFACT_TYPE
        or observed.get("study_id") != STUDY_ID
        or observed.get("global_submission_intent") != file_identity(global_path)
    ):
        raise ValueError(f"Batch intent has the wrong authority: {path}")
    _, global_record = read_canonical_json(global_path)
    if observed.get("sidecar_authorities") != global_record.get("sidecar_authorities"):
        raise ValueError(f"Batch intent binds different sidecar authorities: {path}")
    _require_sidecar_identities(_require_dict(observed.get("sidecar_authorities"), "batch sidecar authorities"))
    arms = observed.get("arms")
    if not isinstance(arms, list) or observed.get("arm_count") != len(arms) or not 1 <= len(arms) <= 5:
        raise ValueError(f"Batch intent has an invalid arm list: {path}")
    if any(
        not isinstance(arm, dict)
        or set(arm) != {"arm_filename", "comment", "command"}
        or not isinstance(arm["arm_filename"], str)
        or COMMENT_RE.fullmatch(str(arm["comment"])) is None
        or not isinstance(arm["command"], list)
        for arm in arms
    ):
        raise ValueError(f"Batch intent has a malformed arm entry: {path}")
    if len({arm["arm_filename"] for arm in arms}) != len(arms) or len({arm["comment"] for arm in arms}) != len(arms):
        raise ValueError(f"Batch intent repeats an arm or scheduler comment: {path}")
    return observed


def arm_intent(
    *,
    arm_plan: dict[str, Any],
    global_path: Path,
    batch_path: Path,
    created_at: str,
) -> dict[str, Any]:
    _parse_utc(created_at, "arm intent created_at")
    _, global_record = read_canonical_json(global_path)
    sidecars = _require_dict(global_record.get("sidecar_authorities"), "global sidecar authorities")
    _require_sidecar_identities(sidecars)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARM_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "global_submission_intent": file_identity(global_path),
        "batch_intent": file_identity(batch_path),
        "sidecar_authorities": sidecars,
        "arm_plan": arm_plan,
        "failure_policy": (
            "if no immutable receipt follows, never resubmit; reconcile only by the exact content-addressed comment"
        ),
    }


def validate_arm_intent(
    path: Path,
    *,
    arm_plan: dict[str, Any],
    global_path: Path,
) -> dict[str, Any]:
    _require_read_only(path, "Per-arm dispatch intent")
    _, observed = read_canonical_json(path)
    batch_identity = _require_dict(observed.get("batch_intent"), "arm intent batch identity")
    batch_path = Path(str(batch_identity.get("path")))
    if file_identity(batch_path) != batch_identity:
        raise ValueError(f"Arm intent batch identity changed: {path}")
    batch = validate_batch_intent(batch_path, global_path)
    expected_batch_entry = {
        "arm_filename": arm_plan["arm_filename"],
        "comment": arm_plan["comment"],
        "command": arm_plan["command"],
    }
    if expected_batch_entry not in batch["arms"]:
        raise ValueError(f"Arm plan differs from its batch intent: {path}")
    expected = arm_intent(
        arm_plan=arm_plan,
        global_path=global_path,
        batch_path=batch_path,
        created_at=str(observed.get("created_at")),
    )
    if observed != expected:
        raise ValueError(f"Per-arm dispatch intent differs: {path}")
    return observed


def _arm_paths(state_root: Path, arm_filename: str) -> tuple[Path, Path]:
    root = state_root / "arms" / _safe_arm_key(arm_filename)
    return root / "submission_intent.json", root / "receipt.json"


def _started_artifacts(run: dict[str, Any]) -> list[str]:
    root = Path(run["output_dir"])
    observed = [name for name in START_MARKER_NAMES if (root / name).exists()]
    observed.extend(path.name for path in root.glob("job_*.log"))
    return sorted(set(observed))


def parse_scheduler_rows(output: str, *, source: str) -> list[dict[str, Any]]:
    if source not in {"squeue", "sacct"}:
        raise ValueError(f"Unsupported scheduler source: {source}")
    records = []
    for line_number, raw_line in enumerate(output.splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = raw_line.strip().split("|")
        if len(fields) != 6:
            raise ValueError(f"Malformed {source} scheduler row {line_number}: {raw_line!r}")
        job_id, comment, job_name, account, qos, state = (field.strip() for field in fields[:6])
        if JOB_ID_RE.fullmatch(job_id) is None:
            raise ValueError(f"Unexpected {source} scheduler job ID on row {line_number}: {job_id!r}")
        records.append(
            {
                "job_id": int(job_id),
                "comment": comment,
                "job_name": job_name,
                "account": account,
                "qos": qos,
                "state": state,
                "source": source,
            }
        )
    return records


def scheduler_snapshot(*, start_time: datetime, job_names: list[str]) -> dict[str, Any]:
    if not job_names or any(not name or "," in name for name in job_names):
        raise ValueError("Scheduler queries require explicit comma-free eligible job names")
    name_filter = ",".join(sorted(set(job_names)))
    since = start_time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    squeue_command = ["squeue", "--noheader", "--name", name_filter, f"--format={SQUEUE_FORMAT}"]
    sacct_command = [
        "sacct",
        "--noheader",
        "--parsable2",
        "--allocations",
        "--name",
        name_filter,
        "--starttime",
        since,
        f"--format={SACCT_FORMAT}",
    ]
    squeue = subprocess.run(squeue_command, check=True, capture_output=True, text=True, timeout=60)
    sacct = subprocess.run(sacct_command, check=True, capture_output=True, text=True, timeout=60)
    records = parse_scheduler_rows(squeue.stdout, source="squeue")
    records.extend(parse_scheduler_rows(sacct.stdout, source="sacct"))
    return {
        "queried_at": _utc_now(),
        "start_time": since,
        "squeue_command": squeue_command,
        "squeue_stdout_sha256": hashlib.sha256(squeue.stdout.encode()).hexdigest(),
        "sacct_command": sacct_command,
        "sacct_stdout_sha256": hashlib.sha256(sacct.stdout.encode()).hexdigest(),
        "records": records,
    }


def _is_terminal_slurm_state(value: str) -> bool:
    normalized = value.split(maxsplit=1)[0].rstrip("+")
    return normalized in TERMINAL_SLURM_STATES


def enforce_study_live_cap(
    *,
    authority: dict[str, Any],
    status: dict[str, Any],
    snapshot: dict[str, Any],
    selected_new_count: int,
) -> dict[str, Any]:
    plans = {
        filename: build_arm_plan(authority, authority["run_by_filename"][filename])
        for filename in authority["eligible_filenames"]
    }
    arm_by_comment = {plan["comment"]: filename for filename, plan in plans.items()}
    arm_by_job_name = {plan["scheduler"]["job_name"]: filename for filename, plan in plans.items()}
    if len(arm_by_comment) != len(plans):
        raise ValueError("Eligible arms do not have unique protected scheduler comments")
    if len(arm_by_job_name) != len(plans):
        raise ValueError("Eligible arms do not have unique scheduler job names")
    arm_by_receipt_job = {job_id: filename for filename, job_id in status["receipts"].items()}
    observed: dict[int, dict[str, Any]] = {}
    for record in snapshot["records"]:
        comment_arm = arm_by_comment.get(record["comment"])
        job_name_arm = arm_by_job_name.get(record["job_name"])
        receipt_arm = arm_by_receipt_job.get(record["job_id"])
        prior = observed.get(record["job_id"])
        prior_arm = prior["arm_filename"] if prior is not None else None
        candidate_arms = {arm for arm in (comment_arm, job_name_arm, receipt_arm, prior_arm) if arm is not None}
        if not candidate_arms:
            continue
        if len(candidate_arms) != 1:
            raise ValueError(f"Protected job {record['job_id']} maps to two different arms")
        arm_filename = candidate_arms.pop()
        job = observed.setdefault(
            record["job_id"],
            {
                "job_id": record["job_id"],
                "arm_filename": arm_filename,
                "comment": "",
                "job_name": "",
                "account": "",
                "qos": "",
                "sources": set(),
                "states": set(),
            },
        )
        for field in ("comment", "job_name", "account", "qos"):
            if job[field] and record[field] and job[field] != record[field]:
                raise ValueError(f"Scheduler sources disagree for job {record['job_id']} field {field}")
            if not job[field]:
                job[field] = record[field]
        job["sources"].add(record["source"])
        job["states"].add(record["state"])
    missing_receipts = sorted(set(arm_by_receipt_job) - set(observed))
    if missing_receipts:
        raise RuntimeError(
            "Cannot establish terminal state for protected receipt job IDs: "
            + ", ".join(str(job_id) for job_id in missing_receipts)
        )
    live_jobs = []
    for job_id in sorted(observed):
        job = observed[job_id]
        sources = sorted(job["sources"])
        states = sorted(job["states"])
        if "squeue" in sources or any(not _is_terminal_slurm_state(state) for state in states):
            _validate_scheduler_match(job, plans[job["arm_filename"]])
            live_jobs.append(
                {
                    **{key: job[key] for key in ("job_id", "arm_filename", "comment")},
                    "sources": sources,
                    "states": states,
                }
            )
    result = {
        "max_live_arms": MAX_ARMS_PER_INVOCATION,
        "live_count": len(live_jobs),
        "selected_new_count": selected_new_count,
        "projected_live_count": len(live_jobs) + selected_new_count,
        "live_jobs": live_jobs,
    }
    if result["projected_live_count"] > MAX_ARMS_PER_INVOCATION:
        raise RuntimeError(
            f"Study-wide live-arm cap would be exceeded: {result['live_count']} live + "
            f"{selected_new_count} selected > {MAX_ARMS_PER_INVOCATION}"
        )
    return result


def matching_scheduler_jobs(
    snapshot: dict[str, Any],
    arm_plan: dict[str, Any],
    *,
    exact_comment_only: bool,
) -> dict[int, dict[str, Any]]:
    matches: dict[int, dict[str, Any]] = {}
    for record in snapshot["records"]:
        if exact_comment_only:
            selected = record["comment"] == arm_plan["comment"]
        else:
            selected = (
                record["comment"] == arm_plan["comment"] or record["job_name"] == arm_plan["scheduler"]["job_name"]
            )
        if not selected:
            continue
        job_id = record["job_id"]
        prior = matches.get(job_id)
        normalized = {key: record[key] for key in ("job_id", "comment", "job_name", "account", "qos", "state")}
        if prior is not None:
            for field in ("comment", "job_name", "account", "qos"):
                if prior[field] and normalized[field] and prior[field] != normalized[field]:
                    raise ValueError(f"Scheduler sources disagree for job {job_id} field {field}")
                if not prior[field]:
                    prior[field] = normalized[field]
            prior["sources"] = sorted(set(prior["sources"]) | {record["source"]})
            prior["states"] = sorted(set(prior["states"]) | {record["state"]})
        else:
            matches[job_id] = {
                **normalized,
                "sources": [record["source"]],
                "states": [record["state"]],
            }
    return matches


def _validate_scheduler_match(record: dict[str, Any], arm_plan: dict[str, Any]) -> None:
    expected = arm_plan["scheduler"]
    if record["comment"] != arm_plan["comment"]:
        raise ValueError("Scheduler record does not carry the exact content-addressed comment")
    if record["job_name"] != expected["job_name"] or record["account"] != expected["account"]:
        raise ValueError("Scheduler record changed the sealed job name or account")
    if expected["qos"] is not None and record["qos"] != expected["qos"]:
        raise ValueError("Scheduler record changed the sealed QoS")


def verify_direct_job(job_id: int, arm_plan: dict[str, Any]) -> dict[str, Any]:
    command = ["scontrol", "show", "job", str(job_id), "--oneliner"]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    fields = {}
    for name in ("Comment", "JobName", "Account", "QOS"):
        match = re.search(rf"(?:^|\s){name}=(\S+)", result.stdout)
        if match is None:
            raise ValueError(f"scontrol output has no {name} for job {job_id}")
        fields[name] = match.group(1)
    record = {
        "job_id": job_id,
        "comment": fields["Comment"],
        "job_name": fields["JobName"],
        "account": fields["Account"],
        "qos": fields["QOS"],
    }
    _validate_scheduler_match(record, arm_plan)
    return {
        "command": command,
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "record": record,
    }


def _validate_receipt_evidence(
    *,
    source: str,
    evidence: dict[str, Any],
    job_id: int,
    arm_plan: dict[str, Any],
) -> None:
    if source == "sbatch_stdout":
        if set(evidence) != {"command", "stdout_sha256", "record"}:
            raise ValueError("Direct submission evidence has the wrong fields")
        if evidence["command"] != ["scontrol", "show", "job", str(job_id), "--oneliner"]:
            raise ValueError("Direct submission evidence used the wrong scheduler command")
        _require_sha256(evidence["stdout_sha256"], "direct scheduler stdout hash")
        record = _require_dict(evidence["record"], "direct scheduler record")
        if record.get("job_id") != job_id:
            raise ValueError("Direct scheduler evidence has the wrong job ID")
        _validate_scheduler_match(record, arm_plan)
        return
    if set(evidence) != {"query", "exact_comment_matches"}:
        raise ValueError("Reconciliation evidence has the wrong fields")
    query = _require_dict(evidence["query"], "reconciliation query")
    expected_query_fields = {
        "queried_at",
        "start_time",
        "squeue_command",
        "squeue_stdout_sha256",
        "sacct_command",
        "sacct_stdout_sha256",
    }
    if set(query) != expected_query_fields:
        raise ValueError("Reconciliation query evidence has the wrong fields")
    _parse_utc(query["queried_at"], "reconciliation queried_at")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(query["start_time"])) is None:
        raise ValueError("Reconciliation scheduler start time is invalid")
    if not isinstance(query["squeue_command"], list) or query["squeue_command"][:1] != ["squeue"]:
        raise ValueError("Reconciliation squeue command is invalid")
    if not isinstance(query["sacct_command"], list) or query["sacct_command"][:1] != ["sacct"]:
        raise ValueError("Reconciliation sacct command is invalid")
    _require_sha256(query["squeue_stdout_sha256"], "reconciliation squeue stdout hash")
    _require_sha256(query["sacct_stdout_sha256"], "reconciliation sacct stdout hash")
    matches = evidence["exact_comment_matches"]
    if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict):
        raise ValueError("Reconciliation evidence must contain one exact comment match")
    record = matches[0]
    if record.get("job_id") != job_id:
        raise ValueError("Reconciliation scheduler evidence has the wrong job ID")
    _validate_scheduler_match(record, arm_plan)


def submission_receipt(
    *,
    arm_plan: dict[str, Any],
    global_path: Path,
    arm_intent_path: Path,
    job_id: int,
    source: str,
    sbatch_stdout: str | None,
    scheduler_evidence: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError("Receipt job_id is invalid")
    if source not in {"sbatch_stdout", "scheduler_reconciliation"}:
        raise ValueError("Receipt source is invalid")
    if source == "sbatch_stdout":
        if not isinstance(sbatch_stdout, str) or sbatch_stdout.split(";", maxsplit=1)[0] != str(job_id):
            raise ValueError("Direct receipt has invalid sbatch stdout")
    elif sbatch_stdout is not None:
        raise ValueError("Reconciled receipt cannot contain sbatch stdout")
    _validate_receipt_evidence(
        source=source,
        evidence=scheduler_evidence,
        job_id=job_id,
        arm_plan=arm_plan,
    )
    _, global_record = read_canonical_json(global_path)
    sidecars = _require_dict(global_record.get("sidecar_authorities"), "global sidecar authorities")
    _require_sidecar_identities(sidecars)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECEIPT_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "arm_filename": arm_plan["arm_filename"],
        "job_id": job_id,
        "comment": arm_plan["comment"],
        "command": arm_plan["command"],
        "submission_environment": arm_plan["submission_environment"],
        "global_submission_intent": file_identity(global_path),
        "arm_submission_intent": file_identity(arm_intent_path),
        "sidecar_authorities": sidecars,
        "source": source,
        "sbatch_stdout": sbatch_stdout,
        "scheduler_evidence": scheduler_evidence,
    }


def validate_receipt(
    path: Path,
    *,
    arm_plan: dict[str, Any],
    global_path: Path,
    arm_intent_path: Path,
) -> dict[str, Any]:
    _require_read_only(path, "Submission receipt")
    _, observed = read_canonical_json(path)
    expected = submission_receipt(
        arm_plan=arm_plan,
        global_path=global_path,
        arm_intent_path=arm_intent_path,
        job_id=observed.get("job_id"),
        source=observed.get("source"),
        sbatch_stdout=observed.get("sbatch_stdout"),
        scheduler_evidence=_require_dict(observed.get("scheduler_evidence"), "receipt scheduler evidence"),
    )
    if observed != expected:
        raise ValueError(f"Submission receipt differs for {arm_plan['arm_filename']}")
    return observed


def state_status(authority: dict[str, Any], state_root: Path) -> dict[str, Any]:
    global_path = state_root / GLOBAL_INTENT_NAME
    if not state_root.exists():
        return {
            "state": "pristine",
            "global_intent": None,
            "receipts": {},
            "pending": [],
        }
    allowed_root_names = {GLOBAL_INTENT_NAME, STATE_LOCK_NAME, "arms", "batches"}
    unexpected = sorted(path.name for path in state_root.iterdir() if path.name not in allowed_root_names)
    if unexpected:
        raise ValueError(f"Unexpected dispatch state artifacts: {unexpected}")
    arm_root = state_root / "arms"
    batch_root = state_root / "batches"
    has_children = (arm_root.exists() and any(arm_root.iterdir())) or (
        batch_root.exists() and any(batch_root.iterdir())
    )
    if not global_path.exists():
        if has_children:
            raise RuntimeError("Per-arm or batch state exists without the global submission intent")
        return {
            "state": "pristine",
            "global_intent": None,
            "receipts": {},
            "pending": [],
        }
    global_record = validate_global_intent(global_path, authority, state_root)
    if batch_root.exists():
        for path in batch_root.iterdir():
            if not path.is_file() or path.suffix != ".json":
                raise ValueError(f"Unexpected batch dispatch artifact: {path}")
            validate_batch_intent(path, global_path)
    known_keys = {_safe_arm_key(filename): filename for filename in authority["eligible_filenames"]}
    receipts = {}
    pending = []
    if arm_root.exists():
        for directory in arm_root.iterdir():
            if not directory.is_dir() or directory.name not in known_keys:
                raise ValueError(f"Unexpected per-arm dispatch state: {directory}")
            filename = known_keys[directory.name]
            run = authority["run_by_filename"][filename]
            arm_plan = build_arm_plan(authority, run)
            intent_path, receipt_path = _arm_paths(state_root, filename)
            if not intent_path.is_file():
                raise RuntimeError(f"Per-arm state has no submission intent: {directory}")
            validate_arm_intent(
                intent_path,
                arm_plan=arm_plan,
                global_path=global_path,
            )
            unexpected_files = sorted(
                path.name for path in directory.iterdir() if path.name not in {intent_path.name, receipt_path.name}
            )
            if unexpected_files:
                raise ValueError(f"Unexpected files in per-arm dispatch state: {unexpected_files}")
            if receipt_path.exists():
                receipt = validate_receipt(
                    receipt_path,
                    arm_plan=arm_plan,
                    global_path=global_path,
                    arm_intent_path=intent_path,
                )
                receipts[filename] = receipt["job_id"]
            else:
                pending.append(filename)
    if len(receipts.values()) != len(set(receipts.values())):
        raise ValueError("Submission receipts reuse a SLURM job ID")
    state = "ambiguous_submission_pending_reconciliation" if pending else "ready"
    return {
        "state": state,
        "global_intent": global_record,
        "receipts": dict(sorted(receipts.items())),
        "pending": sorted(pending),
    }


def require_control_tmux(contract: dict[str, Any]) -> dict[str, str]:
    expected = {
        "socket": str(contract.get("socket")),
        "session": str(contract.get("session")),
        "window": str(contract.get("window")),
    }
    tmux_value = os.environ.get("TMUX")
    if not tmux_value:
        raise ValueError("Actual known-cost dispatch must run inside the recorded control tmux")
    socket = tmux_value.split(",", maxsplit=1)[0]
    pane = os.environ.get("TMUX_PANE")
    if socket != expected["socket"] or not pane:
        raise ValueError("Control tmux socket or pane differs from the launch intent")
    result = subprocess.run(
        [
            "tmux",
            "-S",
            expected["socket"],
            "display-message",
            "-p",
            "-t",
            pane,
            "#{session_name}\t#{window_name}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    observed = result.stdout.rstrip("\n").split("\t")
    if observed != [expected["session"], expected["window"]]:
        raise ValueError(f"Control tmux target differs: {observed!r}")
    return expected


def _scheduler_start(global_record: dict[str, Any] | None) -> datetime:
    if global_record is None:
        return datetime.now(UTC) - timedelta(days=30)
    return _parse_utc(global_record["created_at"], "global intent created_at") - timedelta(days=1)


def _eligible_job_names(authority: dict[str, Any]) -> list[str]:
    return [authority["run_by_filename"][filename]["job_name"] for filename in authority["eligible_filenames"]]


def _preflight_selected_arms(
    *,
    selected_runs: list[dict[str, Any]],
    arm_plans: list[dict[str, Any]],
    status: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    if status["pending"]:
        raise RuntimeError(
            "A prior submission is ambiguous; run reconcile before any new dispatch: " + ", ".join(status["pending"])
        )
    checks = {}
    for run, plan in zip(selected_runs, arm_plans, strict=True):
        filename = run["arm_filename"]
        if filename in status["receipts"]:
            raise ValueError(f"Arm already has a protected submission receipt: {filename}")
        markers = _started_artifacts(run)
        matches = matching_scheduler_jobs(snapshot, plan, exact_comment_only=False)
        if markers or matches:
            raise ValueError(
                f"Arm is already started outside this dispatch attempt: {filename}; "
                f"markers={markers}, scheduler_job_ids={sorted(matches)}"
            )
        checks[filename] = {"runtime_markers": markers, "scheduler_job_ids": []}
    return checks


def _ensure_global_intent(
    *,
    authority: dict[str, Any],
    state_root: Path,
    control_tmux: dict[str, str],
) -> tuple[Path, dict[str, Any]]:
    if control_tmux != authority["control_tmux"]:
        raise ValueError("Control tmux differs from the launch intent")
    path = state_root / GLOBAL_INTENT_NAME
    if path.exists():
        return path, validate_global_intent(path, authority, state_root)
    payload = global_intent(
        authority=authority,
        state_root=state_root,
        created_at=_utc_now(),
    )
    _write_json_once_atomic(path, payload)
    return path, validate_global_intent(path, authority, state_root)


def _submit_one(
    *,
    arm_plan: dict[str, Any],
    global_path: Path,
    batch_path: Path,
    state_root: Path,
    sidecar_authorities: dict[str, Any],
    launch_intent_identity: dict[str, Any],
) -> dict[str, Any]:
    arm_intent_path, receipt_path = _arm_paths(state_root, arm_plan["arm_filename"])
    if arm_intent_path.exists() or receipt_path.exists():
        raise RuntimeError(f"Arm already has dispatch state: {arm_plan['arm_filename']}")
    _require_sidecar_identities(sidecar_authorities)
    _require_launch_intent_identity(launch_intent_identity)
    _validate_arm_plan_sbatch(arm_plan)
    _write_json_once_atomic(
        arm_intent_path,
        arm_intent(
            arm_plan=arm_plan,
            global_path=global_path,
            batch_path=batch_path,
            created_at=_utc_now(),
        ),
    )
    validate_arm_intent(
        arm_intent_path,
        arm_plan=arm_plan,
        global_path=global_path,
    )
    _validate_arm_plan_sbatch(arm_plan)
    _require_sidecar_identities(sidecar_authorities)
    _require_launch_intent_identity(launch_intent_identity)
    try:
        result = subprocess.run(
            arm_plan["command"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=_execution_environment(arm_plan),
        )
        _validate_arm_plan_sbatch(arm_plan)
        _require_sidecar_identities(sidecar_authorities)
        _require_launch_intent_identity(launch_intent_identity)
    except Exception as error:
        raise RuntimeError(
            f"Ambiguous sbatch outcome for {arm_plan['arm_filename']}; reconcile by exact comment"
        ) from error
    stdout = result.stdout.strip()
    job_id_text = stdout.split(";", maxsplit=1)[0]
    if result.returncode != 0 or JOB_ID_RE.fullmatch(job_id_text) is None:
        raise RuntimeError(
            f"Ambiguous sbatch outcome for {arm_plan['arm_filename']}; returncode={result.returncode}, "
            "reconcile by exact comment"
        )
    job_id = int(job_id_text)
    try:
        evidence = verify_direct_job(job_id, arm_plan)
    except Exception as error:
        raise RuntimeError(
            f"Submitted job {job_id} could not be verified for {arm_plan['arm_filename']}; reconcile by exact comment"
        ) from error
    receipt = submission_receipt(
        arm_plan=arm_plan,
        global_path=global_path,
        arm_intent_path=arm_intent_path,
        job_id=job_id,
        source="sbatch_stdout",
        sbatch_stdout=stdout,
        scheduler_evidence=evidence,
    )
    _write_json_once_atomic(receipt_path, receipt)
    validate_receipt(
        receipt_path,
        arm_plan=arm_plan,
        global_path=global_path,
        arm_intent_path=arm_intent_path,
    )
    return receipt


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    authority = bind_sidecar_authorities(load_authority(args.intent))
    initial_intent = authority["intent_identity"]
    initial_sidecars = authority["sidecar_authorities"]
    state_root = validate_state_root(args.state_root, authority)
    selected_runs = select_arms(authority, args.arm)
    arm_plans = [build_arm_plan(authority, run) for run in selected_runs]
    status = state_status(authority, state_root)
    snapshot = scheduler_snapshot(
        start_time=_scheduler_start(status["global_intent"]),
        job_names=_eligible_job_names(authority),
    )
    preflight = _preflight_selected_arms(
        selected_runs=selected_runs,
        arm_plans=arm_plans,
        status=status,
        snapshot=snapshot,
    )
    live_cap = enforce_study_live_cap(
        authority=authority,
        status=status,
        snapshot=snapshot,
        selected_new_count=len(arm_plans),
    )
    if args.dry_run:
        return {
            "study_id": STUDY_ID,
            "dry_run": True,
            "state_root": str(state_root),
            "selected_arms": [plan["arm_filename"] for plan in arm_plans],
            "preflight": preflight,
            "study_live_cap": live_cap,
            "commands": [shlex.join(plan["command"]) for plan in arm_plans],
            "comments": {plan["arm_filename"]: plan["comment"] for plan in arm_plans},
            "submission_environments": {plan["arm_filename"]: plan["submission_environment"] for plan in arm_plans},
            "submission_performed": False,
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual dispatch requires --confirm-study-id {STUDY_ID}")
    control_tmux = require_control_tmux(authority["control_tmux"])
    state_root.mkdir(parents=True, exist_ok=True)
    lock_path = state_root / STATE_LOCK_NAME
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        authority = revalidate_locked_authority(
            args.intent,
            initial_intent=initial_intent,
            initial_sidecars=initial_sidecars,
            operation="dispatch",
        )
        selected_runs = select_arms(authority, args.arm)
        arm_plans = [build_arm_plan(authority, run) for run in selected_runs]
        status = state_status(authority, state_root)
        snapshot = scheduler_snapshot(
            start_time=_scheduler_start(status["global_intent"]),
            job_names=_eligible_job_names(authority),
        )
        _preflight_selected_arms(
            selected_runs=selected_runs,
            arm_plans=arm_plans,
            status=status,
            snapshot=snapshot,
        )
        live_cap = enforce_study_live_cap(
            authority=authority,
            status=status,
            snapshot=snapshot,
            selected_new_count=len(arm_plans),
        )
        global_path, _ = _ensure_global_intent(
            authority=authority,
            state_root=state_root,
            control_tmux=control_tmux,
        )
        batch = batch_intent(
            global_path=global_path,
            arm_plans=arm_plans,
            created_at=_utc_now(),
        )
        batch_content = canonical_json_bytes(batch)
        batch_path = state_root / "batches" / f"{hashlib.sha256(batch_content).hexdigest()}.json"
        _write_json_once_atomic(batch_path, batch)
        validate_batch_intent(batch_path, global_path)
        receipts = {}
        for arm_plan in arm_plans:
            receipt = _submit_one(
                arm_plan=arm_plan,
                global_path=global_path,
                batch_path=batch_path,
                state_root=state_root,
                sidecar_authorities=authority["sidecar_authorities"],
                launch_intent_identity=authority["intent_identity"],
            )
            receipts[arm_plan["arm_filename"]] = receipt["job_id"]
        final_status = state_status(authority, state_root)
    return {
        "study_id": STUDY_ID,
        "dry_run": False,
        "state_root": str(state_root),
        "submitted_job_ids": receipts,
        "study_live_cap_at_submission": live_cap,
        "status": final_status,
    }


def _reconciliation_evidence(snapshot: dict[str, Any], matches: dict[int, dict[str, Any]]) -> dict[str, Any]:
    return {
        "query": {
            key: snapshot[key]
            for key in (
                "queried_at",
                "start_time",
                "squeue_command",
                "squeue_stdout_sha256",
                "sacct_command",
                "sacct_stdout_sha256",
            )
        },
        "exact_comment_matches": [matches[job_id] for job_id in sorted(matches)],
    }


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    authority = bind_sidecar_authorities(load_authority(args.intent))
    initial_intent = authority["intent_identity"]
    initial_sidecars = authority["sidecar_authorities"]
    state_root = validate_state_root(args.state_root, authority)
    selected_runs = select_arms(authority, args.arm)
    arm_plans = [build_arm_plan(authority, run) for run in selected_runs]
    status = state_status(authority, state_root)
    if status["global_intent"] is None:
        raise RuntimeError("There is no global submission intent to reconcile")
    snapshot = scheduler_snapshot(
        start_time=_scheduler_start(status["global_intent"]),
        job_names=_eligible_job_names(authority),
    )
    previews = {}
    for plan in arm_plans:
        intent_path, receipt_path = _arm_paths(state_root, plan["arm_filename"])
        if not intent_path.is_file():
            raise ValueError(f"Arm has no dispatch intent to reconcile: {plan['arm_filename']}")
        if receipt_path.exists():
            previews[plan["arm_filename"]] = {
                "state": "receipt_exists",
                "job_id": status["receipts"][plan["arm_filename"]],
            }
            continue
        matches = matching_scheduler_jobs(snapshot, plan, exact_comment_only=True)
        if len(matches) == 1:
            _validate_scheduler_match(next(iter(matches.values())), plan)
        previews[plan["arm_filename"]] = {
            "state": "exact_match" if len(matches) == 1 else "unresolved" if not matches else "ambiguous",
            "job_ids": sorted(matches),
        }
    if args.dry_run:
        return {
            "study_id": STUDY_ID,
            "dry_run": True,
            "reconciliation": previews,
            "scheduler_mutation": False,
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual reconciliation requires --confirm-study-id {STUDY_ID}")
    control_tmux = require_control_tmux(authority["control_tmux"])
    if status["global_intent"]["control_tmux"] != control_tmux:
        raise ValueError("Global dispatch intent belongs to a different control tmux")
    lock_path = state_root / STATE_LOCK_NAME
    recovered = {}
    unresolved = []
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        authority = revalidate_locked_authority(
            args.intent,
            initial_intent=initial_intent,
            initial_sidecars=initial_sidecars,
            operation="reconciliation",
        )
        selected_runs = select_arms(authority, args.arm)
        arm_plans = [build_arm_plan(authority, run) for run in selected_runs]
        status = state_status(authority, state_root)
        snapshot = scheduler_snapshot(
            start_time=_scheduler_start(status["global_intent"]),
            job_names=_eligible_job_names(authority),
        )
        global_path = state_root / GLOBAL_INTENT_NAME
        for plan in arm_plans:
            intent_path, receipt_path = _arm_paths(state_root, plan["arm_filename"])
            if receipt_path.exists():
                continue
            validate_arm_intent(intent_path, arm_plan=plan, global_path=global_path)
            matches = matching_scheduler_jobs(snapshot, plan, exact_comment_only=True)
            if len(matches) > 1:
                raise RuntimeError(
                    f"Multiple exact scheduler comment matches for {plan['arm_filename']}: {sorted(matches)}"
                )
            if not matches:
                unresolved.append(plan["arm_filename"])
                continue
            job_id = next(iter(matches))
            record = matches[job_id]
            _validate_scheduler_match(record, plan)
            _require_sidecar_identities(authority["sidecar_authorities"])
            evidence = _reconciliation_evidence(snapshot, matches)
            receipt = submission_receipt(
                arm_plan=plan,
                global_path=global_path,
                arm_intent_path=intent_path,
                job_id=job_id,
                source="scheduler_reconciliation",
                sbatch_stdout=None,
                scheduler_evidence=evidence,
            )
            _write_json_once_atomic(receipt_path, receipt)
            validate_receipt(
                receipt_path,
                arm_plan=plan,
                global_path=global_path,
                arm_intent_path=intent_path,
            )
            recovered[plan["arm_filename"]] = job_id
        final_status = state_status(authority, state_root)
    return {
        "study_id": STUDY_ID,
        "dry_run": False,
        "recovered_job_ids": recovered,
        "unresolved_arms": unresolved,
        "scheduler_mutation": False,
        "status": final_status,
    }


def status(args: argparse.Namespace) -> dict[str, Any]:
    authority = bind_sidecar_authorities(load_authority(args.intent))
    state_root = validate_state_root(args.state_root, authority)
    return {
        "study_id": STUDY_ID,
        "state_root": str(state_root),
        "authority": authority["intent_identity"],
        "status": state_status(authority, state_root),
        "scheduler_mutation": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    dispatch_parser = subparsers.add_parser("dispatch")
    dispatch_parser.add_argument("--intent", type=Path, required=True)
    dispatch_parser.add_argument("--state-root", type=Path, required=True)
    dispatch_parser.add_argument("--arm", action="append", required=True)
    dispatch_parser.add_argument("--confirm-study-id")
    dispatch_parser.add_argument("--dry-run", action="store_true")
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--intent", type=Path, required=True)
    reconcile_parser.add_argument("--state-root", type=Path, required=True)
    reconcile_parser.add_argument("--arm", action="append", required=True)
    reconcile_parser.add_argument("--confirm-study-id")
    reconcile_parser.add_argument("--dry-run", action="store_true")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--intent", type=Path, required=True)
    status_parser.add_argument("--state-root", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "dispatch":
        result = dispatch(args)
    elif args.command == "reconcile":
        result = reconcile(args)
    elif args.command == "status":
        result = status(args)
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
