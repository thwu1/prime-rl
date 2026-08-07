#!/usr/bin/env python3
"""Protected dispatcher for the promoted 26-arm known-cost stage-2 grid."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import dispatch_known_cost_boundary as base_dispatch
import materialize_known_cost_promotion as promotion

SCHEMA_VERSION = 1
STUDY_ID = promotion.STUDY_ID
MAX_ARMS_PER_INVOCATION = 5
MAX_LIVE_ARMS = promotion.MAX_LIVE_ARMS
REQUIRED_QOS = promotion.REQUIRED_QOS
REQUIRED_STATE_ROOT = promotion.REQUIRED_STAGE2_STATE_ROOT.resolve()
COMMENT_PREFIX = "rsci-known-cost-v1-stage2-"
COMMENT_RE = re.compile(rf"{COMMENT_PREFIX}[0-9a-f]{{64}}")
ARM_FILENAME_RE = re.compile(r"[a-z0-9_]+\.toml")
JOB_ID_RE = re.compile(r"[1-9][0-9]*")
SCRIPT_REPOSITORY_PATH = "user/tianhaowu/rsci/dispatch_known_cost_promotion.py"
GLOBAL_INTENT_NAME = "global_stage2_submission_intent.json"
STATE_LOCK_NAME = "stage2_dispatch.lock"
GLOBAL_ARTIFACT_TYPE = "rsci_known_cost_stage2_global_dispatch_intent"
BATCH_ARTIFACT_TYPE = "rsci_known_cost_stage2_dispatch_batch_intent"
ARM_ARTIFACT_TYPE = "rsci_known_cost_stage2_arm_dispatch_intent"
RECEIPT_ARTIFACT_TYPE = "rsci_known_cost_stage2_arm_submission_receipt"
SBATCH_COMMAND_PREFIX = (
    "env",
    "-u",
    "SBATCH_OUTPUT",
    "-u",
    "SBATCH_ERROR",
    "sbatch",
    "--parsable",
)

canonical_json_bytes = base_dispatch.canonical_json_bytes
canonical_json_sha256 = base_dispatch.canonical_json_sha256
file_identity = base_dispatch.file_identity
read_canonical_json = base_dispatch.read_canonical_json
parse_scheduler_rows = base_dispatch.parse_scheduler_rows
scheduler_snapshot = base_dispatch.scheduler_snapshot


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
    return base_dispatch._write_json_once_atomic(path, payload)


def _require_read_only(path: Path, label: str) -> None:
    base_dispatch._require_read_only(path, label)


def _dispatcher_identity() -> dict[str, Any]:
    return {
        "repository_path": SCRIPT_REPOSITORY_PATH,
        **file_identity(Path(__file__)),
    }


def load_authority(intent_path: Path) -> dict[str, Any]:
    intent_path = intent_path.expanduser().resolve()
    validated = promotion.validate_stage2_intent(intent_path)
    intent = validated["intent"]
    if intent.get("study_id") != STUDY_ID:
        raise ValueError("Stage-2 intent has the wrong study identity")
    inputs = _require_dict(intent.get("inputs"), "stage2 intent inputs")
    authority_path = Path(str(inputs.get("promotion_authority"))).expanduser().resolve()
    authority_record = promotion.validate_promotion_authority(authority_path)
    authority = authority_record["authority"]
    promotion.validate_recorded_implementation(
        authority,
        name="stage2_dispatcher",
        implementation_path=Path(__file__),
    )
    promotion.validate_recorded_implementation(
        authority,
        name="stage1_dispatcher_helpers",
        implementation_path=Path(base_dispatch.__file__),
    )

    chain = _require_dict(intent.get("authority_chain"), "stage2 authority chain")
    if chain.get("promotion_authority") != authority_record["identity"]:
        raise ValueError("Stage-2 intent does not bind the exact promotion authority")
    if chain.get("initial_launch_intent") != authority["initial_launch_authority"]["intent"]:
        raise ValueError("Stage-2 intent and promotion authority bind different initial intents")

    protected = _require_dict(intent.get("protected_dispatch_plan"), "protected stage2 plan")
    if protected.get("status") != "stage2_content_addressed_inventory_only_not_scheduler_authorization":
        raise ValueError("Stage-2 protected dispatch plan has the wrong status")
    payload = _require_dict(protected.get("payload"), "protected stage2 payload")
    payload_sha256 = _require_sha256(protected.get("payload_sha256"), "protected stage2 payload hash")
    if canonical_json_sha256(payload) != payload_sha256:
        raise ValueError("Protected stage2 payload hash differs")
    if (
        payload.get("study_id") != STUDY_ID
        or payload.get("stage") != "remaining_26_after_smoke_promotion"
        or payload.get("max_live_arms_across_all_30_job_names") != MAX_LIVE_ARMS
        or payload.get("required_qos") != REQUIRED_QOS
        or payload.get("required_state_root") != str(REQUIRED_STATE_ROOT)
        or payload.get("scheduler_override_transport") != "explicit_sbatch_cli_v1"
        or payload.get("forbidden_initial_smoke_arms") != list(promotion.SMOKE_ARM_FILENAMES)
    ):
        raise ValueError("Protected stage2 payload has the wrong dispatch contract")

    partition = _require_dict(intent.get("stage2_arm_partition"), "stage2 arm partition")
    eligible_filenames = partition.get("remaining_arm_filenames")
    if eligible_filenames != list(promotion.remaining_arm_filenames()):
        raise ValueError("Stage-2 intent does not authorize the exact remaining 26 arms")
    if partition.get("initial_smoke_arm_filenames") != list(promotion.SMOKE_ARM_FILENAMES):
        raise ValueError("Stage-2 intent changed the forbidden initial smoke arms")
    full_runs = intent.get("eligible_runs")
    payload_arms = payload.get("eligible_arms")
    if not isinstance(full_runs, list) or not isinstance(payload_arms, list):
        raise ValueError("Stage-2 intent has incomplete eligible-run inventories")
    if any(not isinstance(item, dict) for item in [*full_runs, *payload_arms]):
        raise ValueError("Stage-2 eligible-run inventories must contain only objects")
    run_by_filename = {str(run.get("arm_filename")): run for run in full_runs}
    payload_by_filename = {str(arm.get("arm_filename")): arm for arm in payload_arms}
    if (
        len(full_runs) != 26
        or len(payload_arms) != 26
        or len(run_by_filename) != 26
        or len(payload_by_filename) != 26
        or list(run_by_filename) != eligible_filenames
        or list(payload_by_filename) != eligible_filenames
    ):
        raise ValueError("Stage-2 protected payload does not contain the ordered remaining 26 arms")
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
            raise ValueError(f"Protected stage2 arm differs from sealed run {filename}")

    scheduler_inventory = intent.get("study_scheduler_inventory")
    if not isinstance(scheduler_inventory, list) or len(scheduler_inventory) != 30:
        raise ValueError("Stage-2 intent does not bind all 30 scheduler job names")
    if any(not isinstance(item, dict) for item in scheduler_inventory):
        raise ValueError("Study scheduler inventory entries must be objects")
    scheduler_by_filename = {str(item.get("arm_filename")): item for item in scheduler_inventory}
    if (
        len(scheduler_by_filename) != 30
        or list(scheduler_by_filename) != list(promotion._expected_arm_filenames())
        or len({str(item.get("job_name")) for item in scheduler_inventory}) != 30
    ):
        raise ValueError("Study scheduler inventory is not the exact ordered 30-arm grid")
    for filename in eligible_filenames:
        item = scheduler_by_filename[filename]
        run = run_by_filename[filename]
        slurm = _require_dict(
            _require_dict(
                _require_dict(run.get("launcher_config_projection"), "launcher projection").get("projection"),
                "launcher projection payload",
            ).get("slurm"),
            "launcher SLURM projection",
        )
        if (
            item.get("stage") != "stage2_remaining"
            or item.get("job_name") != run["job_name"]
            or item.get("account") != slurm.get("account")
            or item.get("qos") != REQUIRED_QOS
        ):
            raise ValueError(f"Stage-2 scheduler inventory differs for {filename}")
    for filename in promotion.SMOKE_ARM_FILENAMES:
        if scheduler_by_filename[filename].get("stage") != "initial_smoke":
            raise ValueError(f"Initial smoke scheduler inventory differs for {filename}")

    policy = _require_dict(intent.get("dispatch_policy"), "stage2 dispatch policy")
    if (
        policy.get("required_state_root") != str(REQUIRED_STATE_ROOT)
        or policy.get("state_root_is_separate_from_initial_dispatch") is not True
        or policy.get("max_arms_per_dispatch") != MAX_ARMS_PER_INVOCATION
        or policy.get("max_live_arms_across_all_30_job_names") != MAX_LIVE_ARMS
        or policy.get("required_qos") != REQUIRED_QOS
        or policy.get("scheduler_override_transport") != "explicit_sbatch_cli_v1"
        or policy.get("required_environment_unsets") != ["SBATCH_OUTPUT", "SBATCH_ERROR"]
        or policy.get("forbidden_arm_filenames") != list(promotion.SMOKE_ARM_FILENAMES)
    ):
        raise ValueError("Stage-2 dispatch policy differs from the protected contract")
    control_tmux = _require_dict(policy.get("required_control_tmux"), "required control tmux")
    if set(control_tmux) != {"socket", "session", "window"} or any(
        not isinstance(control_tmux[key], str) or not control_tmux[key] for key in control_tmux
    ):
        raise ValueError("Stage-2 control tmux contract is invalid")
    return {
        "intent": intent,
        "intent_path": str(intent_path),
        "intent_identity": validated["identity"],
        "promotion_authority": authority,
        "promotion_authority_identity": authority_record["identity"],
        "initial_intent_identity": chain["initial_launch_intent"],
        "analysis_identity": chain["result_analysis"],
        "protected_payload": payload,
        "protected_payload_sha256": payload_sha256,
        "eligible_filenames": eligible_filenames,
        "run_by_filename": run_by_filename,
        "payload_by_filename": payload_by_filename,
        "scheduler_inventory": scheduler_inventory,
        "scheduler_by_filename": scheduler_by_filename,
        "control_tmux": control_tmux,
        "run_root": str(Path(str(inputs.get("run_root"))).resolve()),
    }


def select_arms(authority: dict[str, Any], requested: list[str]) -> list[dict[str, Any]]:
    if not requested:
        raise ValueError("At least one explicit --arm is required")
    if len(requested) > MAX_ARMS_PER_INVOCATION:
        raise ValueError(f"At most {MAX_ARMS_PER_INVOCATION} arms may be dispatched per invocation")
    if len(requested) != len(set(requested)):
        raise ValueError("Duplicate --arm values are forbidden")
    selected = []
    for filename in requested:
        if filename in promotion.SMOKE_ARM_FILENAMES:
            raise ValueError(f"Initial smoke arms are forbidden from stage-2 dispatch: {filename}")
        if filename not in authority["run_by_filename"]:
            if filename in promotion._expected_arm_filenames():
                raise ValueError(f"Arm is not authorized by the exact stage-2 allowlist: {filename}")
            raise ValueError(f"Unknown arm outside the frozen 30-arm inventory: {filename}")
        selected.append(authority["run_by_filename"][filename])
    return selected


def validate_state_root(state_root: Path, authority: dict[str, Any]) -> Path:
    configured = state_root.expanduser()
    if not configured.is_absolute():
        raise ValueError("--state-root must be absolute")
    resolved = configured.resolve()
    if resolved != REQUIRED_STATE_ROOT:
        raise ValueError(f"--state-root must exactly match the stage-2 authority: {REQUIRED_STATE_ROOT}")
    if resolved == promotion.launch.REQUIRED_DISPATCH_STATE_ROOT.resolve():
        raise ValueError("Stage-2 state root must be separate from initial dispatch state")
    protected_roots = [Path(authority["run_root"]).resolve()]
    protected_roots.extend(Path(run["output_dir"]).resolve() for run in authority["run_by_filename"].values())
    for protected in protected_roots:
        if resolved == protected or resolved.is_relative_to(protected) or protected.is_relative_to(resolved):
            raise ValueError(f"Stage-2 dispatch state root overlaps a production run directory: {protected}")
    return resolved


def scheduler_contract(run: dict[str, Any]) -> dict[str, Any]:
    contract = base_dispatch.scheduler_contract(run)
    if contract["qos"] != REQUIRED_QOS:
        raise ValueError(f"Stage-2 run has the wrong required QoS: {run['arm_filename']}")
    return contract


def submission_comment(authority: dict[str, Any], run: dict[str, Any]) -> str:
    material = {
        "domain": "rsci-known-cost-boundary-stage2-protected-dispatch-v1",
        "study_id": STUDY_ID,
        "stage2_intent_sha256": authority["intent_identity"]["sha256"],
        "promotion_authority_sha256": authority["promotion_authority_identity"]["sha256"],
        "initial_launch_intent_sha256": authority["initial_intent_identity"]["sha256"],
        "result_analysis_sha256": authority["analysis_identity"]["sha256"],
        "protected_dispatch_payload_sha256": authority["protected_payload_sha256"],
        "arm_filename": run["arm_filename"],
        "sbatch_sha256": run["sbatch"]["sha256"],
        "source_provenance_sha256": run["source_provenance"]["manifest"]["sha256"],
        "scientific_config_projection_sha256": run["scientific_config_projection"]["projection_sha256"],
        "launcher_config_projection_sha256": run["launcher_config_projection"]["projection_sha256"],
    }
    return f"{COMMENT_PREFIX}{canonical_json_sha256(material)}"


def build_arm_plan(authority: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    if run["arm_filename"] in promotion.SMOKE_ARM_FILENAMES:
        raise ValueError("Stage-2 arm plan cannot contain an initial smoke arm")
    comment = submission_comment(authority, run)
    if COMMENT_RE.fullmatch(comment) is None:
        raise RuntimeError("Derived stage-2 scheduler comment is invalid")
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


def global_intent(
    *,
    authority: dict[str, Any],
    state_root: Path,
    created_at: str,
) -> dict[str, Any]:
    _parse_utc(created_at, "stage2 global intent created_at")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": GLOBAL_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "state_root": str(state_root),
        "stage2_submission_intent": authority["intent_identity"],
        "promotion_authority": authority["promotion_authority_identity"],
        "initial_launch_intent": authority["initial_intent_identity"],
        "result_analysis": authority["analysis_identity"],
        "protected_dispatch_payload_sha256": authority["protected_payload_sha256"],
        "eligible_arm_filenames": authority["eligible_filenames"],
        "all_30_scheduler_job_names": [item["job_name"] for item in authority["scheduler_inventory"]],
        "control_tmux": authority["control_tmux"],
        "dispatcher": _dispatcher_identity(),
        "dispatch_contract": {
            "max_arms_per_invocation": MAX_ARMS_PER_INVOCATION,
            "max_live_arms_across_all_30_job_names": MAX_LIVE_ARMS,
            "required_state_root": str(REQUIRED_STATE_ROOT),
            "command_prefix": list(SBATCH_COMMAND_PREFIX),
            "scheduler_cli_option_order": ["comment", "qos", "account"],
            "scheduler_account_must_match_sealed_sbatch": True,
            "required_qos": REQUIRED_QOS,
            "all_inherited_sbatch_variables_removed": True,
            "ambiguous_submission_requires_exact_comment_reconciliation": True,
            "initial_smoke_arms_forbidden": list(promotion.SMOKE_ARM_FILENAMES),
        },
    }


def validate_global_intent(path: Path, authority: dict[str, Any], state_root: Path) -> dict[str, Any]:
    _require_read_only(path, "Stage-2 global dispatch intent")
    _, observed = read_canonical_json(path)
    expected = global_intent(
        authority=authority,
        state_root=state_root,
        created_at=str(observed.get("created_at")),
    )
    if observed != expected:
        raise ValueError("Stage-2 global intent differs from the finalized authority")
    return observed


def batch_intent(
    *,
    global_path: Path,
    arm_plans: list[dict[str, Any]],
    created_at: str,
) -> dict[str, Any]:
    _parse_utc(created_at, "stage2 batch intent created_at")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": BATCH_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "global_submission_intent": file_identity(global_path),
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
    _require_read_only(path, "Stage-2 batch dispatch intent")
    raw, observed = read_canonical_json(path)
    if path.stem != hashlib.sha256(raw).hexdigest():
        raise ValueError(f"Stage-2 batch filename is not its exact file SHA-256: {path}")
    if (
        observed.get("schema_version") != SCHEMA_VERSION
        or observed.get("artifact_type") != BATCH_ARTIFACT_TYPE
        or observed.get("study_id") != STUDY_ID
        or observed.get("global_submission_intent") != file_identity(global_path)
    ):
        raise ValueError(f"Stage-2 batch intent has the wrong authority: {path}")
    arms = observed.get("arms")
    if not isinstance(arms, list) or observed.get("arm_count") != len(arms) or not 1 <= len(arms) <= 5:
        raise ValueError(f"Stage-2 batch intent has an invalid arm list: {path}")
    if any(
        not isinstance(arm, dict)
        or set(arm) != {"arm_filename", "comment", "command"}
        or arm["arm_filename"] in promotion.SMOKE_ARM_FILENAMES
        or COMMENT_RE.fullmatch(str(arm["comment"])) is None
        or not isinstance(arm["command"], list)
        for arm in arms
    ):
        raise ValueError(f"Stage-2 batch intent has a malformed arm entry: {path}")
    if len({arm["arm_filename"] for arm in arms}) != len(arms) or len({arm["comment"] for arm in arms}) != len(arms):
        raise ValueError(f"Stage-2 batch repeats an arm or scheduler comment: {path}")
    return observed


def arm_intent(
    *,
    arm_plan: dict[str, Any],
    global_path: Path,
    batch_path: Path,
    created_at: str,
) -> dict[str, Any]:
    _parse_utc(created_at, "stage2 arm intent created_at")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARM_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "created_at": created_at,
        "global_submission_intent": file_identity(global_path),
        "batch_intent": file_identity(batch_path),
        "arm_plan": arm_plan,
        "failure_policy": (
            "if no immutable receipt follows, never resubmit; reconcile only by the exact "
            "content-addressed stage2 comment"
        ),
    }


def validate_arm_intent(
    path: Path,
    *,
    arm_plan: dict[str, Any],
    global_path: Path,
) -> dict[str, Any]:
    _require_read_only(path, "Stage-2 per-arm dispatch intent")
    _, observed = read_canonical_json(path)
    batch_identity = _require_dict(observed.get("batch_intent"), "stage2 arm batch identity")
    batch_path = Path(str(batch_identity.get("path")))
    if file_identity(batch_path) != batch_identity:
        raise ValueError(f"Stage-2 arm batch identity changed: {path}")
    batch = validate_batch_intent(batch_path, global_path)
    expected_entry = {
        "arm_filename": arm_plan["arm_filename"],
        "comment": arm_plan["comment"],
        "command": arm_plan["command"],
    }
    if expected_entry not in batch["arms"]:
        raise ValueError(f"Stage-2 arm plan differs from its batch intent: {path}")
    expected = arm_intent(
        arm_plan=arm_plan,
        global_path=global_path,
        batch_path=batch_path,
        created_at=str(observed.get("created_at")),
    )
    if observed != expected:
        raise ValueError(f"Stage-2 per-arm dispatch intent differs: {path}")
    return observed


def _arm_paths(state_root: Path, arm_filename: str) -> tuple[Path, Path]:
    root = state_root / "arms" / _safe_arm_key(arm_filename)
    return root / "submission_intent.json", root / "receipt.json"


def matching_scheduler_jobs(
    snapshot: dict[str, Any],
    arm_plan: dict[str, Any],
    *,
    exact_comment_only: bool,
) -> dict[int, dict[str, Any]]:
    return base_dispatch.matching_scheduler_jobs(
        snapshot,
        arm_plan,
        exact_comment_only=exact_comment_only,
    )


def _validate_scheduler_match(record: dict[str, Any], arm_plan: dict[str, Any]) -> None:
    base_dispatch._validate_scheduler_match(record, arm_plan)


def _merge_scheduler_records(snapshot: dict[str, Any], authority: dict[str, Any]) -> dict[int, dict[str, Any]]:
    by_name = {item["job_name"]: item for item in authority["scheduler_inventory"]}
    stage2_plans = {
        filename: build_arm_plan(authority, authority["run_by_filename"][filename])
        for filename in authority["eligible_filenames"]
    }
    by_comment = {plan["comment"]: filename for filename, plan in stage2_plans.items()}
    if len(by_comment) != len(stage2_plans):
        raise ValueError("Stage-2 arms do not have unique protected scheduler comments")
    observed: dict[int, dict[str, Any]] = {}
    for record in snapshot["records"]:
        name_item = by_name.get(record["job_name"])
        comment_arm = by_comment.get(record["comment"])
        if name_item is None and comment_arm is None:
            raise ValueError(f"Scheduler query returned job outside the frozen 30-name inventory: {record['job_id']}")
        name_arm = None if name_item is None else name_item["arm_filename"]
        candidate_arms = {arm for arm in (name_arm, comment_arm) if arm is not None}
        prior = observed.get(record["job_id"])
        if prior is not None:
            candidate_arms.add(prior["arm_filename"])
        if len(candidate_arms) != 1:
            raise ValueError(f"Scheduler job {record['job_id']} maps to different known-cost arms")
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
    return observed


def enforce_study_live_cap(
    *,
    authority: dict[str, Any],
    status: dict[str, Any],
    snapshot: dict[str, Any],
    selected_new_count: int,
) -> dict[str, Any]:
    if isinstance(selected_new_count, bool) or not isinstance(selected_new_count, int) or selected_new_count < 0:
        raise ValueError("selected_new_count must be a nonnegative integer")
    observed = _merge_scheduler_records(snapshot, authority)
    receipt_to_arm = {job_id: filename for filename, job_id in status["receipts"].items()}
    missing_receipts = sorted(set(receipt_to_arm) - set(observed))
    if missing_receipts:
        raise RuntimeError(
            "Cannot establish terminal state for stage-2 receipt job IDs: "
            + ", ".join(str(job_id) for job_id in missing_receipts)
        )
    live_jobs = []
    for job_id in sorted(observed):
        job = observed[job_id]
        receipt_arm = receipt_to_arm.get(job_id)
        if receipt_arm is not None and receipt_arm != job["arm_filename"]:
            raise ValueError(f"Stage-2 receipt job {job_id} maps to a different scheduler arm")
        sources = sorted(job["sources"])
        states = sorted(job["states"])
        is_live = "squeue" in sources or any(not base_dispatch._is_terminal_slurm_state(state) for state in states)
        if not is_live:
            continue
        filename = job["arm_filename"]
        scheduler_item = authority["scheduler_by_filename"][filename]
        if filename in authority["run_by_filename"]:
            plan = build_arm_plan(authority, authority["run_by_filename"][filename])
            _validate_scheduler_match(job, plan)
        elif (
            job["job_name"] != scheduler_item["job_name"]
            or job["account"] != scheduler_item["account"]
            or job["qos"] != scheduler_item["qos"]
        ):
            raise ValueError(f"Live initial-smoke scheduler identity changed for {filename}")
        live_jobs.append(
            {
                "job_id": job_id,
                "arm_filename": filename,
                "stage": scheduler_item["stage"],
                "comment": job["comment"],
                "sources": sources,
                "states": states,
            }
        )
    result = {
        "max_live_arms_across_all_30_job_names": MAX_LIVE_ARMS,
        "queried_job_name_count": len(authority["scheduler_inventory"]),
        "live_count": len(live_jobs),
        "selected_new_count": selected_new_count,
        "projected_live_count": len(live_jobs) + selected_new_count,
        "live_jobs": live_jobs,
    }
    if result["projected_live_count"] > MAX_LIVE_ARMS:
        raise RuntimeError(
            f"Study-wide live-arm cap would be exceeded across all 30 names: "
            f"{result['live_count']} live + {selected_new_count} selected > {MAX_LIVE_ARMS}"
        )
    return result


def verify_direct_job(job_id: int, arm_plan: dict[str, Any]) -> dict[str, Any]:
    return base_dispatch.verify_direct_job(job_id, arm_plan)


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
        raise ValueError("Stage-2 receipt job_id is invalid")
    if source not in {"sbatch_stdout", "scheduler_reconciliation"}:
        raise ValueError("Stage-2 receipt source is invalid")
    if source == "sbatch_stdout":
        if not isinstance(sbatch_stdout, str) or sbatch_stdout.split(";", maxsplit=1)[0] != str(job_id):
            raise ValueError("Direct stage-2 receipt has invalid sbatch stdout")
    elif sbatch_stdout is not None:
        raise ValueError("Reconciled stage-2 receipt cannot contain sbatch stdout")
    base_dispatch._validate_receipt_evidence(
        source=source,
        evidence=scheduler_evidence,
        job_id=job_id,
        arm_plan=arm_plan,
    )
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
    _require_read_only(path, "Stage-2 submission receipt")
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
        raise ValueError(f"Stage-2 receipt differs for {arm_plan['arm_filename']}")
    return observed


def state_status(authority: dict[str, Any], state_root: Path) -> dict[str, Any]:
    global_path = state_root / GLOBAL_INTENT_NAME
    if not state_root.exists():
        return {"state": "pristine", "global_intent": None, "receipts": {}, "pending": []}
    allowed_root_names = {GLOBAL_INTENT_NAME, STATE_LOCK_NAME, "arms", "batches"}
    unexpected = sorted(path.name for path in state_root.iterdir() if path.name not in allowed_root_names)
    if unexpected:
        raise ValueError(f"Unexpected stage-2 dispatch state artifacts: {unexpected}")
    arm_root = state_root / "arms"
    batch_root = state_root / "batches"
    has_children = (arm_root.exists() and any(arm_root.iterdir())) or (
        batch_root.exists() and any(batch_root.iterdir())
    )
    if not global_path.exists():
        if has_children:
            raise RuntimeError("Stage-2 per-arm or batch state exists without the global intent")
        return {"state": "pristine", "global_intent": None, "receipts": {}, "pending": []}
    global_record = validate_global_intent(global_path, authority, state_root)
    if batch_root.exists():
        for path in batch_root.iterdir():
            if not path.is_file() or path.suffix != ".json":
                raise ValueError(f"Unexpected stage-2 batch artifact: {path}")
            validate_batch_intent(path, global_path)
    known_keys = {_safe_arm_key(filename): filename for filename in authority["eligible_filenames"]}
    receipts = {}
    pending = []
    if arm_root.exists():
        for directory in arm_root.iterdir():
            if not directory.is_dir() or directory.name not in known_keys:
                raise ValueError(f"Unexpected stage-2 per-arm state: {directory}")
            filename = known_keys[directory.name]
            plan = build_arm_plan(authority, authority["run_by_filename"][filename])
            intent_path, receipt_path = _arm_paths(state_root, filename)
            if not intent_path.is_file():
                raise RuntimeError(f"Stage-2 per-arm state has no submission intent: {directory}")
            validate_arm_intent(intent_path, arm_plan=plan, global_path=global_path)
            unexpected_files = sorted(
                path.name for path in directory.iterdir() if path.name not in {intent_path.name, receipt_path.name}
            )
            if unexpected_files:
                raise ValueError(f"Unexpected files in stage-2 per-arm state: {unexpected_files}")
            if receipt_path.exists():
                receipt = validate_receipt(
                    receipt_path,
                    arm_plan=plan,
                    global_path=global_path,
                    arm_intent_path=intent_path,
                )
                receipts[filename] = receipt["job_id"]
            else:
                pending.append(filename)
    if len(receipts.values()) != len(set(receipts.values())):
        raise ValueError("Stage-2 receipts reuse a SLURM job ID")
    state = "ambiguous_submission_pending_reconciliation" if pending else "ready"
    return {
        "state": state,
        "global_intent": global_record,
        "receipts": dict(sorted(receipts.items())),
        "pending": sorted(pending),
    }


def require_control_tmux(contract: dict[str, Any]) -> dict[str, str]:
    return base_dispatch.require_control_tmux(contract)


def _scheduler_start(global_record: dict[str, Any] | None) -> datetime:
    if global_record is None:
        return datetime.now(UTC) - timedelta(days=30)
    return _parse_utc(global_record["created_at"], "stage2 global intent created_at") - timedelta(days=1)


def _all_study_job_names(authority: dict[str, Any]) -> list[str]:
    names = [str(item["job_name"]) for item in authority["scheduler_inventory"]]
    if len(names) != 30 or len(set(names)) != 30:
        raise ValueError("Scheduler query does not contain the exact 30 unique study job names")
    return names


def _preflight_selected_arms(
    *,
    selected_runs: list[dict[str, Any]],
    arm_plans: list[dict[str, Any]],
    status: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    if status["pending"]:
        raise RuntimeError(
            "A prior stage-2 submission is ambiguous; reconcile before dispatch: " + ", ".join(status["pending"])
        )
    checks = {}
    for run, plan in zip(selected_runs, arm_plans, strict=True):
        filename = run["arm_filename"]
        if filename in status["receipts"]:
            raise ValueError(f"Stage-2 arm already has a protected receipt: {filename}")
        markers = base_dispatch._started_artifacts(run)
        matches = matching_scheduler_jobs(snapshot, plan, exact_comment_only=False)
        if markers or matches:
            raise ValueError(
                f"Stage-2 arm is already started outside this dispatch attempt: {filename}; "
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
        raise ValueError("Control tmux differs from the stage-2 authority")
    path = state_root / GLOBAL_INTENT_NAME
    if path.exists():
        return path, validate_global_intent(path, authority, state_root)
    payload = global_intent(authority=authority, state_root=state_root, created_at=_utc_now())
    _write_json_once_atomic(path, payload)
    return path, validate_global_intent(path, authority, state_root)


def _submit_one(
    *,
    arm_plan: dict[str, Any],
    global_path: Path,
    batch_path: Path,
    state_root: Path,
) -> dict[str, Any]:
    arm_intent_path, receipt_path = _arm_paths(state_root, arm_plan["arm_filename"])
    if arm_intent_path.exists() or receipt_path.exists():
        raise RuntimeError(f"Stage-2 arm already has dispatch state: {arm_plan['arm_filename']}")
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
    validate_arm_intent(arm_intent_path, arm_plan=arm_plan, global_path=global_path)
    _validate_arm_plan_sbatch(arm_plan)
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
    except Exception as error:
        raise RuntimeError(
            f"Ambiguous sbatch outcome for {arm_plan['arm_filename']}; reconcile by exact stage2 comment"
        ) from error
    stdout = result.stdout.strip()
    job_id_text = stdout.split(";", maxsplit=1)[0]
    if result.returncode != 0 or JOB_ID_RE.fullmatch(job_id_text) is None:
        raise RuntimeError(
            f"Ambiguous sbatch outcome for {arm_plan['arm_filename']}; returncode={result.returncode}, "
            "reconcile by exact stage2 comment"
        )
    job_id = int(job_id_text)
    try:
        evidence = verify_direct_job(job_id, arm_plan)
    except Exception as error:
        raise RuntimeError(
            f"Submitted job {job_id} could not be verified for {arm_plan['arm_filename']}; "
            "reconcile by exact stage2 comment"
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
    authority = load_authority(args.intent)
    state_root = validate_state_root(args.state_root, authority)
    selected_runs = select_arms(authority, args.arm)
    plans = [build_arm_plan(authority, run) for run in selected_runs]
    status = state_status(authority, state_root)
    snapshot = scheduler_snapshot(
        start_time=_scheduler_start(status["global_intent"]),
        job_names=_all_study_job_names(authority),
    )
    preflight = _preflight_selected_arms(
        selected_runs=selected_runs,
        arm_plans=plans,
        status=status,
        snapshot=snapshot,
    )
    live_cap = enforce_study_live_cap(
        authority=authority,
        status=status,
        snapshot=snapshot,
        selected_new_count=len(plans),
    )
    if args.dry_run:
        return {
            "study_id": STUDY_ID,
            "stage": "remaining_26_after_smoke_promotion",
            "dry_run": True,
            "state_root": str(state_root),
            "selected_arms": [plan["arm_filename"] for plan in plans],
            "preflight": preflight,
            "study_live_cap": live_cap,
            "commands": [shlex.join(plan["command"]) for plan in plans],
            "comments": {plan["arm_filename"]: plan["comment"] for plan in plans},
            "submission_environments": {plan["arm_filename"]: plan["submission_environment"] for plan in plans},
            "submission_performed": False,
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual stage-2 dispatch requires --confirm-study-id {STUDY_ID}")
    control_tmux = require_control_tmux(authority["control_tmux"])
    state_root.mkdir(parents=True, exist_ok=True)
    lock_path = state_root / STATE_LOCK_NAME
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        authority = load_authority(args.intent)
        selected_runs = select_arms(authority, args.arm)
        plans = [build_arm_plan(authority, run) for run in selected_runs]
        status = state_status(authority, state_root)
        snapshot = scheduler_snapshot(
            start_time=_scheduler_start(status["global_intent"]),
            job_names=_all_study_job_names(authority),
        )
        _preflight_selected_arms(
            selected_runs=selected_runs,
            arm_plans=plans,
            status=status,
            snapshot=snapshot,
        )
        live_cap = enforce_study_live_cap(
            authority=authority,
            status=status,
            snapshot=snapshot,
            selected_new_count=len(plans),
        )
        global_path, _ = _ensure_global_intent(
            authority=authority,
            state_root=state_root,
            control_tmux=control_tmux,
        )
        batch = batch_intent(global_path=global_path, arm_plans=plans, created_at=_utc_now())
        batch_content = canonical_json_bytes(batch)
        batch_path = state_root / "batches" / f"{hashlib.sha256(batch_content).hexdigest()}.json"
        _write_json_once_atomic(batch_path, batch)
        validate_batch_intent(batch_path, global_path)
        receipts = {}
        for plan in plans:
            receipt = _submit_one(
                arm_plan=plan,
                global_path=global_path,
                batch_path=batch_path,
                state_root=state_root,
            )
            receipts[plan["arm_filename"]] = receipt["job_id"]
        final_status = state_status(authority, state_root)
    return {
        "study_id": STUDY_ID,
        "stage": "remaining_26_after_smoke_promotion",
        "dry_run": False,
        "state_root": str(state_root),
        "submitted_job_ids": receipts,
        "study_live_cap_at_submission": live_cap,
        "status": final_status,
    }


def _reconciliation_evidence(
    snapshot: dict[str, Any],
    matches: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    return base_dispatch._reconciliation_evidence(snapshot, matches)


def reconcile(args: argparse.Namespace) -> dict[str, Any]:
    authority = load_authority(args.intent)
    state_root = validate_state_root(args.state_root, authority)
    selected_runs = select_arms(authority, args.arm)
    plans = [build_arm_plan(authority, run) for run in selected_runs]
    status = state_status(authority, state_root)
    if status["global_intent"] is None:
        raise RuntimeError("There is no stage-2 global submission intent to reconcile")
    snapshot = scheduler_snapshot(
        start_time=_scheduler_start(status["global_intent"]),
        job_names=_all_study_job_names(authority),
    )
    previews = {}
    for plan in plans:
        intent_path, receipt_path = _arm_paths(state_root, plan["arm_filename"])
        if not intent_path.is_file():
            raise ValueError(f"Stage-2 arm has no dispatch intent to reconcile: {plan['arm_filename']}")
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
            "stage": "remaining_26_after_smoke_promotion",
            "dry_run": True,
            "reconciliation": previews,
            "scheduler_mutation": False,
        }
    if args.confirm_study_id != STUDY_ID:
        raise ValueError(f"Actual stage-2 reconciliation requires --confirm-study-id {STUDY_ID}")
    control_tmux = require_control_tmux(authority["control_tmux"])
    if status["global_intent"]["control_tmux"] != control_tmux:
        raise ValueError("Stage-2 global intent belongs to a different control tmux")
    lock_path = state_root / STATE_LOCK_NAME
    recovered = {}
    unresolved = []
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        authority = load_authority(args.intent)
        status = state_status(authority, state_root)
        snapshot = scheduler_snapshot(
            start_time=_scheduler_start(status["global_intent"]),
            job_names=_all_study_job_names(authority),
        )
        global_path = state_root / GLOBAL_INTENT_NAME
        for plan in plans:
            intent_path, receipt_path = _arm_paths(state_root, plan["arm_filename"])
            if receipt_path.exists():
                continue
            validate_arm_intent(intent_path, arm_plan=plan, global_path=global_path)
            matches = matching_scheduler_jobs(snapshot, plan, exact_comment_only=True)
            if len(matches) > 1:
                raise RuntimeError(
                    f"Multiple exact stage-2 scheduler matches for {plan['arm_filename']}: {sorted(matches)}"
                )
            if not matches:
                unresolved.append(plan["arm_filename"])
                continue
            job_id = next(iter(matches))
            record = matches[job_id]
            _validate_scheduler_match(record, plan)
            receipt = submission_receipt(
                arm_plan=plan,
                global_path=global_path,
                arm_intent_path=intent_path,
                job_id=job_id,
                source="scheduler_reconciliation",
                sbatch_stdout=None,
                scheduler_evidence=_reconciliation_evidence(snapshot, matches),
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
        "stage": "remaining_26_after_smoke_promotion",
        "dry_run": False,
        "recovered_job_ids": recovered,
        "unresolved_arms": unresolved,
        "scheduler_mutation": False,
        "status": final_status,
    }


def status(args: argparse.Namespace) -> dict[str, Any]:
    authority = load_authority(args.intent)
    state_root = validate_state_root(args.state_root, authority)
    return {
        "study_id": STUDY_ID,
        "stage": "remaining_26_after_smoke_promotion",
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
