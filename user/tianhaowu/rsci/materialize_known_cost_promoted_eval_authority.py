#!/usr/bin/env python3
"""Seal promoted known-cost evaluation and join smoke plus Stage-2 results."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

import analyze_known_cost_boundary_results as boundary_results
import analyze_known_cost_training_readouts as training_readouts
import dispatch_known_cost_boundary as stage1_dispatch
import dispatch_known_cost_promotion as stage2_dispatch
import materialize_known_cost_eval_plan as eval_plan
import materialize_known_cost_postrun_authority as postrun_authority
import materialize_known_cost_promotion as promotion
import materialize_known_cost_training_completion as training_completion

SCHEMA_VERSION = 1
STUDY_ID = promotion.STUDY_ID
AUTHORITY_ARTIFACT_TYPE = "rsci_known_cost_promoted_eval_authority"
STAGE2_COMPLETION_ARTIFACT_TYPE = "rsci_known_cost_stage2_training_completion_receipt"
PROMOTED_RESULT_ARTIFACT_TYPE = "rsci_known_cost_promoted_boundary_results"
COMBINED_RESULT_ARTIFACT_TYPE = "rsci_known_cost_combined_boundary_results"
COMBINED_TRAINING_ARTIFACT_TYPE = "rsci_known_cost_combined_training_readouts"
PROMOTED_REQUEST_ARTIFACT_TYPE = "rsci_known_cost_promoted_checkpoint_eval_request"
PROMOTED_PLAN_IMPLEMENTATION_ID = "rsci-known-cost-promoted-checkpoint-eval-plan-v1"
PROMOTED_RESULT_ANALYSIS_ID = "known-cost-promoted-boundary-results-v1"
COMBINED_RESULT_ANALYSIS_ID = "known-cost-combined-boundary-results-v1"
COMBINED_TRAINING_ANALYSIS_ID = "known-cost-combined-training-readouts-v1"
AUTHORITY_NAME = "promoted_eval_authority.json"
STAGE2_COMPLETION_NAME = "stage2_training_completion_receipt.json"
PROMOTED_RESULT_NAME = "promoted_results.json"
COMBINED_RESULT_NAME = "combined_results.json"
SCRIPT_REPOSITORY_PATH = Path("user/tianhaowu/rsci/materialize_known_cost_promoted_eval_authority.py")
POSTRUN_IMPLEMENTATION_NAME = "promoted_eval_authority"
SHA256_RE = re.compile(r"[0-9a-f]{64}")


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
    return eval_plan.file_identity(path)


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


def _validate_self_hash(payload: dict[str, Any], label: str) -> str:
    self_hash = _require_sha256(payload.get("payload_without_self_hash_sha256"), f"{label} self hash")
    unhashed = dict(payload)
    unhashed.pop("payload_without_self_hash_sha256")
    if canonical_json_sha256(unhashed) != self_hash:
        raise ValueError(f"{label} self hash differs from its canonical payload")
    return self_hash


def _write_bytes_once(path: Path, content: bytes, label: str) -> None:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        if not resolved.is_file() or resolved.read_bytes() != content:
            raise FileExistsError(f"Refusing to replace a different immutable {label}: {resolved}")
        _require_read_only(resolved, label)
        return
    resolved.parent.mkdir(parents=True, exist_ok=True)
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
    _require_read_only(resolved, label)


def _write_json_once(path: Path, payload: dict[str, Any], label: str) -> dict[str, Any]:
    _write_bytes_once(path, canonical_json_bytes(payload), label)
    return file_identity(path)


def _read_canonical(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    _require_read_only(resolved, label)
    raw, value = eval_plan.read_json_object(resolved, require_canonical=True)
    return raw, value


def _run_exact_tool(implementation: Path, arguments: list[str]) -> dict[str, Any]:
    return promotion.launch._run_exact_validator(implementation, arguments)


def _recorded_implementation(
    record: object,
    *,
    repository_path: Path,
    label: str,
) -> tuple[Path, dict[str, Any]]:
    identity = _require_dict(record, label)
    path = Path(str(identity.get("path"))).expanduser().resolve()
    if promotion._repository_relative(path) != repository_path:
        raise ValueError(f"{label} records the wrong repository path")
    if file_identity(path) != identity:
        raise ValueError(f"{label} identity changed")
    _require_read_only(path, label)
    return path, identity


def _validate_postrun_pin(
    postrun_path: Path,
    initial_intent_identity: dict[str, Any],
) -> dict[str, Any]:
    record = postrun_authority.validate_authority(postrun_path)
    authority = record["authority"]
    bound = _require_dict(authority.get("initial_launch_authority"), "post-run launch authority")
    if bound.get("intent") != initial_intent_identity:
        raise ValueError("Post-run authority and promoted evaluation bind different initial intents")
    postrun_authority.validate_recorded_implementation(
        authority,
        name=POSTRUN_IMPLEMENTATION_NAME,
        implementation_path=Path(__file__),
    )
    for name, implementation_path in (
        ("eval_planner", Path(eval_plan.__file__)),
        ("result_analyzer", Path(boundary_results.__file__)),
        ("training_completion_materializer", Path(training_completion.__file__)),
    ):
        postrun_authority.validate_recorded_implementation(
            authority,
            name=name,
            implementation_path=implementation_path,
        )
    return record


def _validate_same_dose_spending(stage2_intent: dict[str, Any]) -> dict[str, Any]:
    decision = promotion._validate_smoke_spend_decision(stage2_intent.get("smoke_spend_decision"))
    if decision.get("proceed_to_full_grid") is not True:
        raise ValueError("Smoke spending did not authorize the promoted grid")
    qualifying = decision.get("qualifying_doses")
    if not isinstance(qualifying, list) or not qualifying:
        raise ValueError("Smoke spending has no same-dose all-clock qualifier")
    if any(float(dose) not in promotion.SMOKE_DOSES for dose in qualifying):
        raise ValueError("Smoke spending contains an unknown qualifying dose")
    return {
        "rule_id": promotion.RESULT_RULE_ID,
        "qualifying_doses": qualifying,
        "same_dose_required_at_every_preregistered_clock": True,
        "cross_dose_clock_aggregation_allowed": False,
        "stage2_spend": "exact remaining 26 arms; no dose-selected subset",
    }


def _state_artifact_inventory(
    state_root: Path,
    arm_filenames: tuple[str, ...],
    *,
    global_name: str,
    safe_arm_key: Any,
) -> dict[str, Any]:
    resolved = state_root.expanduser().resolve()
    global_path = resolved / global_name
    _read_canonical(global_path, "protected global dispatch intent")
    arms: dict[str, Any] = {}
    for filename in arm_filenames:
        arm_root = resolved / "arms" / safe_arm_key(filename)
        intent_path = arm_root / "submission_intent.json"
        receipt_path = arm_root / "receipt.json"
        _, arm_intent = _read_canonical(intent_path, f"{filename} protected arm intent")
        _, receipt = _read_canonical(receipt_path, f"{filename} protected submission receipt")
        batch_identity = _require_dict(arm_intent.get("batch_intent"), f"{filename} batch intent identity")
        batch_path = Path(str(batch_identity.get("path"))).expanduser().resolve()
        if batch_path.parent != resolved / "batches" or file_identity(batch_path) != batch_identity:
            raise ValueError(f"{filename} protected batch intent identity differs")
        _read_canonical(batch_path, f"{filename} protected batch intent")
        job_id = receipt.get("job_id")
        if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
            raise ValueError(f"{filename} protected submission receipt has an invalid job ID")
        arms[filename] = {
            "global_submission_intent": file_identity(global_path),
            "batch_submission_intent": batch_identity,
            "arm_submission_intent": file_identity(intent_path),
            "submission_receipt": file_identity(receipt_path),
            "submission_receipt_payload_sha256": canonical_json_sha256(receipt),
            "job_id": job_id,
        }
    if len({record["job_id"] for record in arms.values()}) != len(arms):
        raise ValueError("Protected dispatch receipts reuse a job ID")
    return {"state_root": str(resolved), "arms": arms}


def _validate_dispatch_receipts(
    *,
    initial_intent_path: Path,
    initial_intent: dict[str, Any],
    initial_intent_identity: dict[str, Any],
    promotion_authority: dict[str, Any],
    stage2_intent_path: Path,
    stage2_intent_identity: dict[str, Any],
) -> dict[str, Any]:
    stage1_source = _require_dict(initial_intent.get("control_plane_source"), "initial control-plane source")
    stage1_implementations = _require_dict(stage1_source.get("implementations"), "initial implementations")
    stage1_path, stage1_identity = _recorded_implementation(
        stage1_implementations.get("dispatcher"),
        repository_path=Path("user/tianhaowu/rsci/dispatch_known_cost_boundary.py"),
        label="historical Stage-1 dispatcher",
    )
    stage1_root = promotion.launch.REQUIRED_DISPATCH_STATE_ROOT.resolve()
    stage1_summary = _run_exact_tool(
        stage1_path,
        ["status", "--intent", str(initial_intent_path), "--state-root", str(stage1_root)],
    )
    expected_stage1_receipts = set(promotion.SMOKE_ARM_FILENAMES)
    stage1_status = _require_dict(stage1_summary.get("status"), "Stage-1 dispatcher status")
    if (
        stage1_summary.get("study_id") != STUDY_ID
        or stage1_summary.get("state_root") != str(stage1_root)
        or stage1_summary.get("authority") != initial_intent_identity
        or stage1_summary.get("scheduler_mutation") is not False
        or stage1_status.get("state") != "ready"
        or stage1_status.get("pending") != []
        or set(_require_dict(stage1_status.get("receipts"), "Stage-1 receipts")) != expected_stage1_receipts
    ):
        raise ValueError("Historical Stage-1 dispatcher does not report the exact four protected receipts")
    stage1 = _state_artifact_inventory(
        stage1_root,
        promotion.SMOKE_ARM_FILENAMES,
        global_name=stage1_dispatch.GLOBAL_INTENT_NAME,
        safe_arm_key=stage1_dispatch._safe_arm_key,
    )
    if stage1_status["receipts"] != {
        filename: stage1["arms"][filename]["job_id"] for filename in sorted(expected_stage1_receipts)
    }:
        raise ValueError("Stage-1 status and immutable receipt payloads disagree")

    stage2_source = _require_dict(
        promotion_authority.get("promotion_control_source"),
        "promotion control source",
    )
    stage2_implementations = _require_dict(stage2_source.get("implementations"), "promotion implementations")
    stage2_path, stage2_identity = _recorded_implementation(
        stage2_implementations.get("stage2_dispatcher"),
        repository_path=Path("user/tianhaowu/rsci/dispatch_known_cost_promotion.py"),
        label="historical Stage-2 dispatcher",
    )
    stage2_root = promotion.REQUIRED_STAGE2_STATE_ROOT.resolve()
    stage2_summary = _run_exact_tool(
        stage2_path,
        ["status", "--intent", str(stage2_intent_path), "--state-root", str(stage2_root)],
    )
    expected_stage2_receipts = set(promotion.remaining_arm_filenames())
    stage2_status = _require_dict(stage2_summary.get("status"), "Stage-2 dispatcher status")
    if (
        stage2_summary.get("study_id") != STUDY_ID
        or stage2_summary.get("stage") != "remaining_26_after_smoke_promotion"
        or stage2_summary.get("state_root") != str(stage2_root)
        or stage2_summary.get("authority") != stage2_intent_identity
        or stage2_summary.get("scheduler_mutation") is not False
        or stage2_status.get("state") != "ready"
        or stage2_status.get("pending") != []
        or set(_require_dict(stage2_status.get("receipts"), "Stage-2 receipts")) != expected_stage2_receipts
    ):
        raise ValueError("Historical Stage-2 dispatcher does not report the exact 26 protected receipts")
    stage2 = _state_artifact_inventory(
        stage2_root,
        promotion.remaining_arm_filenames(),
        global_name=stage2_dispatch.GLOBAL_INTENT_NAME,
        safe_arm_key=stage2_dispatch._safe_arm_key,
    )
    if stage2_status["receipts"] != {
        filename: stage2["arms"][filename]["job_id"] for filename in sorted(expected_stage2_receipts)
    }:
        raise ValueError("Stage-2 status and immutable receipt payloads disagree")
    all_job_ids = [record["job_id"] for record in [*stage1["arms"].values(), *stage2["arms"].values()]]
    if len(all_job_ids) != 30 or len(set(all_job_ids)) != 30:
        raise ValueError("The combined Stage-1 and Stage-2 protected receipts do not have 30 unique job IDs")
    return {
        "stage1": {
            **stage1,
            "dispatcher": stage1_identity,
            "validation_summary_sha256": canonical_json_sha256(stage1_summary),
        },
        "stage2": {
            **stage2,
            "dispatcher": stage2_identity,
            "validation_summary_sha256": canonical_json_sha256(stage2_summary),
        },
    }


def _stage2_completion_context(
    *,
    promotion_authority_path: Path,
    stage2_intent_path: Path,
    arm_filename: str,
    run_dir: Path,
    frozen_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    promotion_record = promotion.validate_promotion_authority(promotion_authority_path)
    stage2_record = promotion.validate_stage2_intent(stage2_intent_path)
    authority = promotion_record["authority"]
    promotion.validate_recorded_implementation(
        authority,
        name="promotion_materializer",
        implementation_path=Path(promotion.__file__),
    )
    intent = stage2_record["intent"]
    chain = _require_dict(intent.get("authority_chain"), "Stage-2 authority chain")
    if chain.get("promotion_authority") != promotion_record["identity"]:
        raise ValueError("Stage-2 completion inputs break the promotion authority chain")
    _validate_same_dose_spending(intent)
    authority_inputs = _require_dict(authority.get("inputs"), "promotion authority inputs")
    run_root = Path(str(authority_inputs.get("run_root"))).resolve()
    postrun_record = _validate_postrun_pin(
        run_root / postrun_authority.AUTHORITY_NAME,
        _require_dict(chain.get("initial_launch_intent"), "initial launch intent identity"),
    )
    remaining = list(promotion.remaining_arm_filenames())
    if arm_filename not in remaining:
        raise ValueError(f"Stage-2 completion arm is outside the promoted 26: {arm_filename}")
    runs = [
        _require_dict(run, "Stage-2 eligible run")
        for run in _require_list(intent.get("eligible_runs"), "Stage-2 eligible runs")
        if isinstance(run, dict) and run.get("arm_filename") == arm_filename
    ]
    if len(runs) != 1:
        raise ValueError(f"Stage-2 intent does not contain exactly one run for {arm_filename}")
    run = runs[0]
    run_dir = run_dir.expanduser().resolve()
    if Path(str(run.get("output_dir"))).expanduser().resolve() != run_dir:
        raise ValueError("Stage-2 completion run directory differs from the protected eligible run")

    source = _require_dict(authority.get("promotion_control_source"), "promotion control source")
    implementations = _require_dict(source.get("implementations"), "promotion implementations")
    dispatcher_path, dispatcher_identity = _recorded_implementation(
        implementations.get("stage2_dispatcher"),
        repository_path=Path("user/tianhaowu/rsci/dispatch_known_cost_promotion.py"),
        label="historical Stage-2 dispatcher",
    )
    state_root = promotion.REQUIRED_STAGE2_STATE_ROOT.resolve()
    global_path = state_root / stage2_dispatch.GLOBAL_INTENT_NAME
    arm_root = state_root / "arms" / stage2_dispatch._safe_arm_key(arm_filename)
    arm_intent_path = arm_root / "submission_intent.json"
    submission_receipt_path = arm_root / "receipt.json"
    _, arm_intent = _read_canonical(arm_intent_path, f"{arm_filename} Stage-2 arm intent")
    _, submission_receipt = _read_canonical(
        submission_receipt_path,
        f"{arm_filename} Stage-2 submission receipt",
    )
    _read_canonical(global_path, "Stage-2 global intent")
    batch_identity = _require_dict(arm_intent.get("batch_intent"), "Stage-2 batch intent identity")
    batch_path = Path(str(batch_identity.get("path"))).resolve()
    if batch_path.parent != state_root / "batches" or file_identity(batch_path) != batch_identity:
        raise ValueError("Stage-2 arm intent binds a different batch intent")
    _read_canonical(batch_path, "Stage-2 batch intent")
    arm_plan = _require_dict(arm_intent.get("arm_plan"), "Stage-2 arm plan")
    scheduler = _require_dict(arm_plan.get("scheduler"), "Stage-2 scheduler contract")
    job_id = submission_receipt.get("job_id")
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id < 1:
        raise ValueError("Stage-2 submission receipt has an invalid job ID")
    if (
        arm_plan.get("arm_filename") != arm_filename
        or Path(str(arm_plan.get("output_dir"))).resolve() != run_dir
        or arm_plan.get("sbatch") != run.get("sbatch")
        or arm_plan.get("source_provenance")
        != _require_dict(run.get("source_provenance"), "Stage-2 run source").get("manifest")
        or submission_receipt.get("arm_filename") != arm_filename
        or submission_receipt.get("comment") != arm_plan.get("comment")
        or submission_receipt.get("command") != arm_plan.get("command")
        or submission_receipt.get("global_submission_intent") != file_identity(global_path)
        or submission_receipt.get("arm_submission_intent") != file_identity(arm_intent_path)
    ):
        raise ValueError("Stage-2 protected submission artifacts differ from the eligible run")

    replay_paths = {
        "postrun_authority": Path(str(postrun_record["identity"]["path"])),
        "promotion_authority": Path(str(promotion_record["identity"]["path"])),
        "stage2_intent": Path(str(stage2_record["identity"]["path"])),
        "historical_stage2_dispatcher": dispatcher_path,
        "stage2_global_intent": global_path,
        "stage2_batch_intent": batch_path,
        "stage2_arm_intent": arm_intent_path,
        "stage2_submission_receipt": submission_receipt_path,
    }
    replay_before = training_completion._capture_identity_inventory(replay_paths)
    if frozen_replay is None:
        status_summary = _run_exact_tool(
            dispatcher_path,
            ["status", "--intent", str(stage2_intent_path), "--state-root", str(state_root)],
        )
    else:
        status_summary = _require_dict(
            frozen_replay.get("historical_stage2_status"),
            "frozen historical Stage-2 status",
        )
    replay_after = training_completion._capture_identity_inventory(replay_paths)
    training_completion._require_unchanged(replay_before, replay_after, "Historical Stage-2 replay")
    status = _require_dict(status_summary.get("status"), "historical Stage-2 status")
    if (
        status_summary.get("study_id") != STUDY_ID
        or status_summary.get("stage") != "remaining_26_after_smoke_promotion"
        or status_summary.get("state_root") != str(state_root)
        or status_summary.get("authority") != stage2_record["identity"]
        or status_summary.get("scheduler_mutation") is not False
        or status.get("state") != "ready"
        or status.get("pending") != []
        or _require_dict(status.get("receipts"), "historical Stage-2 receipts").get(arm_filename) != job_id
    ):
        raise ValueError("Historical Stage-2 dispatcher does not validate the protected arm receipt")

    resolved_configs = _require_dict(run.get("resolved_configs"), "Stage-2 resolved configs")
    if not {"trainer", "orchestrator"}.issubset(resolved_configs):
        raise ValueError("Stage-2 run does not bind trainer and orchestrator configs")
    evidence_paths = dict(replay_paths)
    config_paths: dict[str, Path] = {}
    for name, raw_identity in sorted(resolved_configs.items()):
        identity = _require_dict(raw_identity, f"Stage-2 resolved {name} config")
        path = Path(str(identity.get("path"))).resolve()
        if file_identity(path) != identity:
            raise ValueError(f"Stage-2 resolved {name} config changed")
        config_paths[name] = path
        evidence_paths[f"resolved_config_{name}"] = path
    sbatch_identity = _require_dict(run.get("sbatch"), "Stage-2 sbatch identity")
    sbatch_path = Path(str(sbatch_identity.get("path"))).resolve()
    if file_identity(sbatch_path) != sbatch_identity:
        raise ValueError("Stage-2 sealed sbatch changed")
    evidence_paths["sealed_sbatch"] = sbatch_path
    allocation_log_contract = training_completion._allocation_log_contract(sbatch_path, run_dir, job_id)
    allocation_logs = {stream: value["resolved_path"] for stream, value in allocation_log_contract.items()}
    allocation_log_identities = {stream: file_identity(path) for stream, path in sorted(allocation_logs.items())}
    for stream, path in allocation_logs.items():
        evidence_paths[f"stage2_allocation_{stream}_log"] = path
    completion, completion_paths = training_completion._completion_markers(
        run_dir,
        config_paths["trainer"],
        config_paths["orchestrator"],
    )
    evidence_paths.update(completion_paths)
    evidence_paths["stage2_completion_materializer"] = Path(__file__).resolve()
    stage2_submission = {
        "state_root": str(state_root),
        "global_submission_intent": file_identity(global_path),
        "batch_submission_intent": batch_identity,
        "arm_submission_intent": file_identity(arm_intent_path),
        "submission_receipt": {
            "identity": file_identity(submission_receipt_path),
            "canonical_payload_sha256": canonical_json_sha256(submission_receipt),
        },
        "job_id": job_id,
        "comment": arm_plan.get("comment"),
        "command": arm_plan.get("command"),
        "job_name": scheduler.get("job_name"),
        "account": scheduler.get("account"),
        "qos": scheduler.get("qos"),
        "sealed_qos_directive": scheduler.get("sealed_qos_directive"),
        "receipt_source": submission_receipt.get("source"),
        "allocation_logs": allocation_log_identities,
        "allocation_log_scheduler_specs": {
            stream: value["scheduler_spec"] for stream, value in allocation_log_contract.items()
        },
    }
    return {
        "promotion_authority": promotion_record["identity"],
        "postrun_authority": postrun_record["identity"],
        "stage2_intent": stage2_record["identity"],
        "initial_launch_intent": chain["initial_launch_intent"],
        "historical_stage2_dispatcher": dispatcher_identity,
        "historical_stage2_status": status_summary,
        "historical_stage2_status_sha256": canonical_json_sha256(status_summary),
        "stage2_submission": stage2_submission,
        "run_contract": {
            "arm_filename": arm_filename,
            "run_dir": str(run_dir),
            "eligible_run": run,
        },
        "completion_evidence": completion,
        "evidence_paths": evidence_paths,
        "replay_toctou": {"before": replay_before, "after": replay_after},
    }


def _stage2_scheduler_context(context: dict[str, Any]) -> dict[str, Any]:
    return {"stage1_submission": context["stage2_submission"]}


def build_stage2_completion_receipt(
    *,
    promotion_authority_path: Path,
    stage2_intent_path: Path,
    arm_filename: str,
    run_dir: Path,
    context: dict[str, Any],
    terminal_allocation: dict[str, Any],
    terminal_toctou_before: dict[str, dict[str, Any]],
    terminal_toctou_after: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    training_completion._require_unchanged(
        terminal_toctou_before,
        terminal_toctou_after,
        "Stage-2 completion evidence",
    )
    training_completion._validate_frozen_scheduler_evidence(
        terminal_allocation,
        _stage2_scheduler_context(context),
    )
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": STAGE2_COMPLETION_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "dispatch_stage": training_completion.STAGE2_DISPATCH_STAGE,
        "inputs": {
            "promotion_authority": str(promotion_authority_path.expanduser().resolve()),
            "stage2_intent": str(stage2_intent_path.expanduser().resolve()),
            "stage2_state_root": str(promotion.REQUIRED_STAGE2_STATE_ROOT.resolve()),
            "arm_filename": arm_filename,
            "run_dir": str(run_dir.expanduser().resolve()),
        },
        "implementation": {
            "repository_path": str(SCRIPT_REPOSITORY_PATH),
            **file_identity(Path(__file__)),
        },
        "authority_chain": {
            "initial_launch_intent": context["initial_launch_intent"],
            "postrun_authority": context["postrun_authority"],
            "promotion_authority": context["promotion_authority"],
            "stage2_intent": context["stage2_intent"],
            "historical_stage2_dispatcher": context["historical_stage2_dispatcher"],
            "historical_stage2_status": context["historical_stage2_status"],
            "historical_stage2_status_sha256": context["historical_stage2_status_sha256"],
        },
        "stage2_submission": context["stage2_submission"],
        "run_contract": context["run_contract"],
        "completion_evidence": context["completion_evidence"],
        "terminal_allocation": terminal_allocation,
        "toctou": {
            "historical_stage2_replay": context["replay_toctou"],
            "terminal_evidence_capture": {
                "before": terminal_toctou_before,
                "after": terminal_toctou_after,
            },
        },
        "claim_scope": {
            "proves_protected_stage2_allocation_completed_with_exit_code_zero": True,
            "proves_bound_console_logs_and_final_stable_checkpoint_existed": True,
            "proves_scientific_replay_or_metric_completeness": False,
            "proves_normal_trainer_process_exit": False,
            "requires_or_claims_wandb_exit_record": False,
            "is_distinct_from_stage1_completion_schema": True,
        },
    }
    receipt["payload_without_self_hash_sha256"] = canonical_json_sha256(receipt)
    return receipt


def _stage2_completion_context_from_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    inputs = _require_dict(receipt.get("inputs"), "Stage-2 completion inputs")
    chain = _require_dict(receipt.get("authority_chain"), "Stage-2 completion authority chain")
    return _stage2_completion_context(
        promotion_authority_path=Path(str(inputs.get("promotion_authority"))),
        stage2_intent_path=Path(str(inputs.get("stage2_intent"))),
        arm_filename=str(inputs.get("arm_filename")),
        run_dir=Path(str(inputs.get("run_dir"))),
        frozen_replay={"historical_stage2_status": chain.get("historical_stage2_status")},
    )


def _validate_stage2_completion_inputs(inputs: dict[str, Any], context: dict[str, Any]) -> None:
    contract = _require_dict(context.get("run_contract"), "Stage-2 completion run contract")
    expected = {
        "promotion_authority": context["promotion_authority"]["path"],
        "stage2_intent": context["stage2_intent"]["path"],
        "stage2_state_root": str(promotion.REQUIRED_STAGE2_STATE_ROOT.resolve()),
        "arm_filename": contract["arm_filename"],
        "run_dir": contract["run_dir"],
    }
    if inputs != expected:
        raise ValueError("Stage-2 completion receipt inputs differ from the protected authority chain")


def validate_stage2_completion_receipt(
    path: Path,
    *,
    recheck_live_scheduler: bool = False,
) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    raw, receipt = _read_canonical(resolved, "Stage-2 training completion receipt")
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("artifact_type") != STAGE2_COMPLETION_ARTIFACT_TYPE
        or receipt.get("study_id") != STUDY_ID
        or receipt.get("dispatch_stage") != training_completion.STAGE2_DISPATCH_STAGE
    ):
        raise ValueError("Stage-2 completion receipt has the wrong schema, artifact, study, or stage")
    expected_fields = {
        "schema_version",
        "artifact_type",
        "study_id",
        "dispatch_stage",
        "inputs",
        "implementation",
        "authority_chain",
        "stage2_submission",
        "run_contract",
        "completion_evidence",
        "terminal_allocation",
        "toctou",
        "claim_scope",
        "payload_without_self_hash_sha256",
    }
    if set(receipt) != expected_fields:
        raise ValueError("Stage-2 completion receipt has the wrong top-level schema")
    _validate_self_hash(receipt, "Stage-2 completion receipt")
    inputs = _require_dict(receipt.get("inputs"), "Stage-2 completion inputs")
    run_dir = Path(str(inputs.get("run_dir"))).resolve()
    if resolved != run_dir / STAGE2_COMPLETION_NAME:
        raise ValueError("Stage-2 completion receipt is not at its distinct adjacent path")
    expected_implementation = {
        "repository_path": str(SCRIPT_REPOSITORY_PATH),
        **file_identity(Path(__file__)),
    }
    if receipt.get("implementation") != expected_implementation:
        raise ValueError("Stage-2 completion receipt was built by a different implementation")
    context = _stage2_completion_context_from_receipt(receipt)
    _validate_stage2_completion_inputs(inputs, context)
    expected_chain = {
        "initial_launch_intent": context["initial_launch_intent"],
        "postrun_authority": context["postrun_authority"],
        "promotion_authority": context["promotion_authority"],
        "stage2_intent": context["stage2_intent"],
        "historical_stage2_dispatcher": context["historical_stage2_dispatcher"],
        "historical_stage2_status": context["historical_stage2_status"],
        "historical_stage2_status_sha256": context["historical_stage2_status_sha256"],
    }
    for field, expected in (
        ("authority_chain", expected_chain),
        ("stage2_submission", context["stage2_submission"]),
        ("run_contract", context["run_contract"]),
        ("completion_evidence", context["completion_evidence"]),
    ):
        if receipt.get(field) != expected:
            raise ValueError(f"Stage-2 completion receipt {field} differs from deterministic replay")
    toctou = _require_dict(receipt.get("toctou"), "Stage-2 completion TOCTOU")
    if set(toctou) != {"historical_stage2_replay", "terminal_evidence_capture"}:
        raise ValueError("Stage-2 completion receipt has the wrong TOCTOU schema")
    if toctou["historical_stage2_replay"] != context["replay_toctou"]:
        raise ValueError("Stage-2 historical replay identities differ")
    for phase_name in ("historical_stage2_replay", "terminal_evidence_capture"):
        phase = _require_dict(toctou.get(phase_name), f"{phase_name} TOCTOU")
        before = _require_dict(phase.get("before"), f"{phase_name} before")
        after = _require_dict(phase.get("after"), f"{phase_name} after")
        if set(phase) != {"before", "after"}:
            raise ValueError(f"{phase_name} TOCTOU has the wrong schema")
        training_completion._require_unchanged(before, after, phase_name)
    current = training_completion._capture_identity_inventory(context["evidence_paths"])
    if toctou["terminal_evidence_capture"]["after"] != current:
        raise ValueError("Stage-2 completion evidence changed after receipt creation")
    frozen = training_completion._validate_frozen_scheduler_evidence(
        receipt.get("terminal_allocation"),
        _stage2_scheduler_context(context),
    )
    live = None
    if recheck_live_scheduler:
        live = training_completion._query_terminal_allocation(
            training_completion._expected_scheduler_contract(_stage2_scheduler_context(context))
        )
        if live["row"] != frozen["row"]:
            raise ValueError("Live Stage-2 terminal allocation differs from the frozen receipt")
    expected_claims = {
        "proves_protected_stage2_allocation_completed_with_exit_code_zero": True,
        "proves_bound_console_logs_and_final_stable_checkpoint_existed": True,
        "proves_scientific_replay_or_metric_completeness": False,
        "proves_normal_trainer_process_exit": False,
        "requires_or_claims_wandb_exit_record": False,
        "is_distinct_from_stage1_completion_schema": True,
    }
    if receipt.get("claim_scope") != expected_claims:
        raise ValueError("Stage-2 completion receipt overstates or changes its claim scope")
    if canonical_json_bytes(receipt) != raw:
        raise ValueError("Stage-2 completion receipt is not canonical")
    return {"receipt": receipt, "identity": file_identity(resolved), "live_scheduler_recheck": live}


def materialize_stage2_completion_receipt(
    *,
    promotion_authority_path: Path,
    stage2_intent_path: Path,
    arm_filename: str,
    run_dir: Path,
) -> dict[str, Any]:
    resolved_run = run_dir.expanduser().resolve()
    output_path = resolved_run / STAGE2_COMPLETION_NAME
    if output_path.exists():
        validated = validate_stage2_completion_receipt(output_path)
        inputs = _require_dict(validated["receipt"].get("inputs"), "existing Stage-2 completion inputs")
        expected = {
            "promotion_authority": str(promotion_authority_path.expanduser().resolve()),
            "stage2_intent": str(stage2_intent_path.expanduser().resolve()),
            "stage2_state_root": str(promotion.REQUIRED_STAGE2_STATE_ROOT.resolve()),
            "arm_filename": arm_filename,
            "run_dir": str(resolved_run),
        }
        if inputs != expected:
            raise ValueError("Existing Stage-2 completion receipt belongs to different immutable inputs")
        return validated
    context = _stage2_completion_context(
        promotion_authority_path=promotion_authority_path,
        stage2_intent_path=stage2_intent_path,
        arm_filename=arm_filename,
        run_dir=resolved_run,
    )
    before = training_completion._capture_identity_inventory(context["evidence_paths"])
    terminal = training_completion._query_terminal_allocation(
        training_completion._expected_scheduler_contract(_stage2_scheduler_context(context))
    )
    after = training_completion._capture_identity_inventory(context["evidence_paths"])
    receipt = build_stage2_completion_receipt(
        promotion_authority_path=promotion_authority_path,
        stage2_intent_path=stage2_intent_path,
        arm_filename=arm_filename,
        run_dir=resolved_run,
        context=context,
        terminal_allocation=terminal,
        terminal_toctou_before=before,
        terminal_toctou_after=after,
    )
    _write_json_once(output_path, receipt, "Stage-2 training completion receipt")
    return validate_stage2_completion_receipt(output_path)


def validate_stage2_completion_for_training_readouts(
    run: dict[str, Any],
    authority: dict[str, Any],
) -> dict[str, Any]:
    run_dir = Path(str(run.get("run_dir"))).expanduser().resolve()
    binding = _require_dict(run.get("launch_binding"), "training-readout run launch binding")
    arm_filename = str(binding.get("arm_filename"))
    if arm_filename not in set(promotion.remaining_arm_filenames()):
        raise ValueError(f"Stage-2 training readouts received a smoke or unknown arm: {arm_filename}")
    validated = validate_stage2_completion_receipt(run_dir / STAGE2_COMPLETION_NAME)
    receipt = validated["receipt"]
    contract = _require_dict(receipt.get("run_contract"), f"{arm_filename} completion run contract")
    eligible_run = _require_dict(contract.get("eligible_run"), f"{arm_filename} completion eligible run")
    if (
        contract.get("arm_filename") != arm_filename
        or Path(str(contract.get("run_dir"))).resolve() != run_dir
        or canonical_json_sha256(eligible_run) != binding.get("launch_record_sha256")
    ):
        raise ValueError(f"Stage-2 training readout run differs from the promoted authority: {arm_filename}")
    authority_inputs = _require_dict(authority.get("inputs"), "post-run authority inputs")
    postrun_path = Path(str(authority_inputs.get("run_root"))).resolve() / postrun_authority.AUTHORITY_NAME
    expected_postrun = file_identity(postrun_path)
    receipt_chain = _require_dict(receipt.get("authority_chain"), "Stage-2 completion authority chain")
    if receipt_chain.get("postrun_authority") != expected_postrun:
        raise ValueError(f"Stage-2 completion and training consumer bind different post-run authority: {arm_filename}")
    return validated


def _completion_job_id(receipt: dict[str, Any], label: str) -> int:
    terminal = _require_dict(receipt.get("terminal_allocation"), f"{label} terminal allocation")
    row = _require_dict(terminal.get("row"), f"{label} terminal allocation row")
    raw = row.get("JobIDRaw", row.get("job_id"))
    if isinstance(raw, int) and not isinstance(raw, bool):
        value = raw
    elif isinstance(raw, str) and raw.isdecimal():
        value = int(raw)
    else:
        raise ValueError(f"{label} terminal allocation has no exact job ID")
    if value < 1:
        raise ValueError(f"{label} terminal allocation has an invalid job ID")
    return value


def _validate_training_completion(
    *,
    run: dict[str, Any],
    arm_filename: str,
    dispatch_stage: str,
    dispatch_record: dict[str, Any],
    pinned_stage1_implementation: dict[str, Any],
    pinned_stage2_implementation: dict[str, Any],
    initial_intent_identity: dict[str, Any],
    postrun_authority_identity: dict[str, Any],
    stage2_intent_identity: dict[str, Any],
    promotion_authority_identity: dict[str, Any],
) -> dict[str, Any]:
    run_dir = Path(str(run.get("output_dir"))).expanduser().resolve()
    if dispatch_stage == training_completion.STAGE1_DISPATCH_STAGE:
        path = run_dir / training_completion.RECEIPT_NAME
        envelope = training_completion.validate_receipt_envelope(
            path,
            supported_dispatch_stages={training_completion.STAGE1_DISPATCH_STAGE},
        )
        receipt = envelope["receipt"]
        implementation = _require_dict(
            receipt.get("implementation"),
            f"{arm_filename} Stage-1 completion implementation",
        )
        expected_implementation = {
            "repository_path": training_completion.SCRIPT_REPOSITORY_PATH,
            **pinned_stage1_implementation,
        }
        if implementation != expected_implementation:
            raise ValueError(f"{arm_filename} Stage-1 completion was not built by its pre-pinned implementation")
        implementation_path = Path(str(pinned_stage1_implementation["path"])).resolve()
        summary = _run_exact_tool(implementation_path, ["validate", "--receipt", str(path)])
        if summary.get("command") != "validate" or summary.get("receipt") != envelope["identity"]:
            raise ValueError(f"{arm_filename} Stage-1 completion validator returned a different receipt")
    elif dispatch_stage == training_completion.STAGE2_DISPATCH_STAGE:
        path = run_dir / STAGE2_COMPLETION_NAME
        validated = validate_stage2_completion_receipt(path)
        receipt = validated["receipt"]
        envelope = {"receipt": receipt, "identity": validated["identity"]}
        implementation = _require_dict(
            receipt.get("implementation"),
            f"{arm_filename} Stage-2 completion implementation",
        )
        expected_implementation = {
            "repository_path": str(SCRIPT_REPOSITORY_PATH),
            **pinned_stage2_implementation,
        }
        if implementation != expected_implementation:
            raise ValueError(f"{arm_filename} Stage-2 completion was not built by its pre-pinned implementation")
        summary = {
            "command": "validate-stage2-completion",
            "receipt": validated["identity"],
            "scheduler_mutation": False,
        }
    else:
        raise ValueError(f"Unsupported completion dispatch stage: {dispatch_stage}")
    if receipt.get("dispatch_stage") != dispatch_stage:
        raise ValueError(f"{arm_filename} completion receipt has the wrong dispatch stage")
    inputs = _require_dict(receipt.get("inputs"), f"{arm_filename} completion inputs")
    contract = _require_dict(receipt.get("run_contract"), f"{arm_filename} completion run contract")
    eligible_run = _require_dict(contract.get("eligible_run"), f"{arm_filename} completion eligible run")
    if (
        inputs.get("arm_filename") != arm_filename
        or Path(str(inputs.get("run_dir"))).expanduser().resolve() != run_dir
        or contract.get("arm_filename") != arm_filename
        or Path(str(contract.get("run_dir"))).expanduser().resolve() != run_dir
        or eligible_run != run
        or _completion_job_id(receipt, arm_filename) != dispatch_record["job_id"]
    ):
        raise ValueError(f"{arm_filename} completion receipt differs from its protected run and allocation")
    if dispatch_stage == training_completion.STAGE1_DISPATCH_STAGE:
        launch_authority = _require_dict(
            receipt.get("launch_authority"),
            f"{arm_filename} Stage-1 completion authority",
        )
        if launch_authority.get("initial_intent") != initial_intent_identity:
            raise ValueError(f"{arm_filename} Stage-1 completion binds a different initial intent")
    else:
        launch_authority = _require_dict(
            receipt.get("authority_chain"),
            f"{arm_filename} Stage-2 completion authority chain",
        )
        if (
            launch_authority.get("stage2_intent") != stage2_intent_identity
            or launch_authority.get("promotion_authority") != promotion_authority_identity
            or launch_authority.get("initial_launch_intent") != initial_intent_identity
            or launch_authority.get("postrun_authority") != postrun_authority_identity
        ):
            raise ValueError(f"{arm_filename} Stage-2 completion receipt breaks the promotion authority chain")
    return {
        "identity": envelope["identity"],
        "payload_without_self_hash_sha256": receipt["payload_without_self_hash_sha256"],
        "dispatch_stage": dispatch_stage,
        "job_id": dispatch_record["job_id"],
        "validation_summary_sha256": canonical_json_sha256(summary),
    }


def _planner_request_run(run: dict[str, Any]) -> dict[str, Any]:
    filename = str(run.get("arm_filename"))
    run_id = Path(filename).stem.replace("_", "-")
    resolved_configs = _require_dict(run.get("resolved_configs"), f"{filename} resolved configs")
    source = _require_dict(run.get("source_provenance"), f"{filename} source provenance")
    sbatch = _require_dict(run.get("sbatch"), f"{filename} sbatch")
    if set(resolved_configs) != {"trainer", "orchestrator", "inference"}:
        raise ValueError(f"{filename} has an incomplete resolved-config identity")
    return {
        "run_id": run_id,
        "run_dir": str(Path(str(run.get("output_dir"))).expanduser().resolve()),
        "arm_filename": filename,
        "launch_record_sha256": canonical_json_sha256(run),
        "resolved_configs": copy.deepcopy(resolved_configs),
        "source_provenance_manifest": copy.deepcopy(_require_dict(source.get("manifest"), f"{filename} manifest")),
        "sbatch": copy.deepcopy(sbatch),
    }


def build_authority(
    *,
    postrun_path: Path,
    promotion_authority_path: Path,
    stage2_intent_path: Path,
) -> dict[str, Any]:
    promotion_record = promotion.validate_promotion_authority(promotion_authority_path)
    promotion_authority = promotion_record["authority"]
    promotion.validate_recorded_implementation(
        promotion_authority,
        name="promotion_materializer",
        implementation_path=Path(promotion.__file__),
    )
    stage2_record = promotion.validate_stage2_intent(stage2_intent_path)
    stage2_intent = stage2_record["intent"]
    chain = _require_dict(stage2_intent.get("authority_chain"), "Stage-2 authority chain")
    if chain.get("promotion_authority") != promotion_record["identity"]:
        raise ValueError("Stage-2 intent and promoted evaluation bind different promotion authorities")
    spending = _validate_same_dose_spending(stage2_intent)

    initial_identity = _require_dict(chain.get("initial_launch_intent"), "initial launch intent identity")
    initial_path = Path(str(initial_identity.get("path"))).resolve()
    _, initial_intent = _read_canonical(initial_path, "initial launch intent")
    if file_identity(initial_path) != initial_identity:
        raise ValueError("Initial launch intent changed")
    promotion._validate_initial_smoke_partition(initial_intent)
    postrun_record = _validate_postrun_pin(postrun_path, initial_identity)

    dispatch = _validate_dispatch_receipts(
        initial_intent_path=initial_path,
        initial_intent=initial_intent,
        initial_intent_identity=initial_identity,
        promotion_authority=promotion_authority,
        stage2_intent_path=stage2_intent_path.expanduser().resolve(),
        stage2_intent_identity=stage2_record["identity"],
    )
    smoke_runs = {
        str(run["arm_filename"]): run
        for run in _require_list(initial_intent.get("eligible_runs"), "smoke eligible runs")
    }
    stage2_runs = {
        str(run["arm_filename"]): run
        for run in _require_list(stage2_intent.get("eligible_runs"), "Stage-2 eligible runs")
    }
    if list(smoke_runs) != list(promotion.SMOKE_ARM_FILENAMES):
        raise ValueError("Initial launch intent does not expose the exact smoke run order")
    if list(stage2_runs) != list(promotion.remaining_arm_filenames()):
        raise ValueError("Stage-2 intent does not expose the exact promoted run order")
    if set(smoke_runs) & set(stage2_runs) or set(smoke_runs) | set(stage2_runs) != set(
        promotion._expected_arm_filenames()
    ):
        raise ValueError("Smoke and Stage-2 run inventories do not form the exact disjoint 30-arm grid")

    postrun_implementations = _require_dict(
        _require_dict(postrun_record["authority"].get("postrun_control_source"), "post-run control source").get(
            "implementations"
        ),
        "post-run implementations",
    )
    completion_implementation = _require_dict(
        postrun_implementations.get("training_completion_materializer"),
        "pre-pinned training completion implementation",
    )
    if file_identity(Path(str(completion_implementation.get("path")))) != completion_implementation:
        raise ValueError("Pre-pinned training completion implementation changed")
    stage2_completion_implementation = _require_dict(
        postrun_implementations.get(POSTRUN_IMPLEMENTATION_NAME),
        "pre-pinned Stage-2 completion implementation",
    )
    if file_identity(Path(str(stage2_completion_implementation.get("path")))) != stage2_completion_implementation:
        raise ValueError("Pre-pinned Stage-2 completion implementation changed")

    combined_runs = []
    output_dirs = set()
    for filename in promotion._expected_arm_filenames():
        if filename in smoke_runs:
            stage = "initial_smoke"
            dispatch_stage = training_completion.STAGE1_DISPATCH_STAGE
            run = smoke_runs[filename]
            dispatch_record = dispatch["stage1"]["arms"][filename]
        else:
            stage = "stage2_remaining"
            dispatch_stage = training_completion.STAGE2_DISPATCH_STAGE
            run = stage2_runs[filename]
            dispatch_record = dispatch["stage2"]["arms"][filename]
        output_dir = str(Path(str(run.get("output_dir"))).expanduser().resolve())
        if output_dir in output_dirs:
            raise ValueError("Combined promoted run inventory reuses an output directory")
        output_dirs.add(output_dir)
        completion = _validate_training_completion(
            run=run,
            arm_filename=filename,
            dispatch_stage=dispatch_stage,
            dispatch_record=dispatch_record,
            pinned_stage1_implementation=completion_implementation,
            pinned_stage2_implementation=stage2_completion_implementation,
            initial_intent_identity=initial_identity,
            postrun_authority_identity=postrun_record["identity"],
            stage2_intent_identity=stage2_record["identity"],
            promotion_authority_identity=promotion_record["identity"],
        )
        planner_request_run = _planner_request_run(run)
        checkpoint_binding, _, _ = eval_plan.inspect_run(
            planner_request_run,
            eval_plan.DEFAULT_OPTIMIZER_TARGETS,
            eval_plan.DEFAULT_RAW_GROUP_TARGETS,
        )
        factors = boundary_results._derive_arm_factors(checkpoint_binding, run)
        combined_runs.append(
            {
                "arm_filename": filename,
                "stage": stage,
                "factors": factors.as_dict(),
                "run_record": copy.deepcopy(run),
                "run_record_sha256": canonical_json_sha256(run),
                "planner_request_run": planner_request_run,
                "clock_checkpoint_binding": checkpoint_binding,
                "protected_submission": dispatch_record,
                "training_completion": completion,
            }
        )

    analysis_identity = _require_dict(chain.get("result_analysis"), "smoke result analysis identity")
    analysis_path = Path(str(analysis_identity.get("path"))).resolve()
    if file_identity(analysis_path) != analysis_identity:
        raise ValueError("Passing smoke result analysis changed")
    _, smoke_analysis = _read_canonical(analysis_path, "passing smoke result analysis")
    if promotion._validate_smoke_spend_decision(smoke_analysis.get("smoke_spend_decision")) != _require_dict(
        stage2_intent.get("smoke_spend_decision"), "Stage-2 smoke decision"
    ):
        raise ValueError("Stage-2 intent and passing smoke result contain different spending decisions")
    smoke_plan_identity = _require_dict(
        _require_dict(smoke_analysis.get("provenance"), "smoke analysis provenance").get("eval_plan"),
        "smoke evaluation plan identity",
    )
    smoke_plan_path = Path(str(smoke_plan_identity.get("path"))).resolve()
    smoke_plan_validation = boundary_results.validate_plan_with_recorded_planner(smoke_plan_path)
    smoke_plan = smoke_plan_validation["plan"]
    if file_identity(smoke_plan_path) != smoke_plan_identity:
        raise ValueError("Passing smoke analysis plan identity changed")
    smoke_plan_runs = {
        str(_require_dict(run.get("launch_binding"), "smoke plan launch binding")["arm_filename"]): run
        for run in (_require_dict(item, "smoke plan run") for item in smoke_plan["runs"])
    }
    combined_by_filename = {record["arm_filename"]: record for record in combined_runs}
    if set(smoke_plan_runs) != set(promotion.SMOKE_ARM_FILENAMES):
        raise ValueError("Passing smoke plan does not cover the exact four initial runs")
    for filename in promotion.SMOKE_ARM_FILENAMES:
        if smoke_plan_runs[filename] != combined_by_filename[filename]["clock_checkpoint_binding"]:
            raise ValueError(f"Smoke plan and promoted authority clock/checkpoint binding differ for {filename}")

    initial_inputs = _require_dict(initial_intent.get("inputs"), "initial launch inputs")
    run_root = Path(str(initial_inputs.get("run_root"))).resolve()
    authority: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": AUTHORITY_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "inputs": {
            "run_root": str(run_root),
            "postrun_authority": str(postrun_path.expanduser().resolve()),
            "promotion_authority": str(promotion_authority_path.expanduser().resolve()),
            "stage2_intent": str(stage2_intent_path.expanduser().resolve()),
        },
        "authority_chain": {
            "initial_launch_intent": initial_identity,
            "postrun_authority": postrun_record["identity"],
            "promotion_authority": promotion_record["identity"],
            "passing_smoke_result": analysis_identity,
            "smoke_eval_plan": smoke_plan_identity,
            "stage2_intent": stage2_record["identity"],
        },
        "same_dose_spending": spending,
        "protected_dispatch": dispatch,
        "combined_run_inventory": {
            "arm_count": 30,
            "ordered_arm_filenames": list(promotion._expected_arm_filenames()),
            "initial_smoke_arm_filenames": list(promotion.SMOKE_ARM_FILENAMES),
            "promoted_arm_filenames": list(promotion.remaining_arm_filenames()),
            "runs": combined_runs,
        },
        "evaluation_contract": {
            "promoted_plan_partition": "exact remaining 26 only",
            "combined_result_partitions": ["immutable initial smoke4", "immutable promoted26"],
            "optimizer_step_targets": list(eval_plan.DEFAULT_OPTIMIZER_TARGETS),
            "raw_group_targets": list(eval_plan.DEFAULT_RAW_GROUP_TARGETS),
            "heldout_operations": list(eval_plan.OPERATIONS),
            "examples_per_operation": eval_plan.EXAMPLES_PER_OPERATION,
            "neutral_tag_count": eval_plan.TAG_COUNT,
            "request_seed": eval_plan.DEFAULT_REQUEST_SEED,
            "same_source_tagged_pairing": True,
            "one_h100_sequential_seven_shard_task_schema": True,
        },
        "stage2_training_readout_contract": {
            "implementation": stage2_completion_implementation,
            "artifact_type": STAGE2_COMPLETION_ARTIFACT_TYPE,
            "filename": STAGE2_COMPLETION_NAME,
            "dispatch_stage": training_completion.STAGE2_DISPATCH_STAGE,
            "validated_adjacent_receipt_required_before_and_after_each_run_readout": True,
            "completion_receipt_must_bind_allocation_stdout_and_stderr": True,
            "completion_receipt_must_bind_all_mutable_training_readout_inputs": True,
        },
        "implementation": {
            "repository_path": str(SCRIPT_REPOSITORY_PATH),
            **file_identity(Path(__file__)),
        },
        "checks": {
            "initial_smoke_intent_replayed": True,
            "passing_smoke_result_replayed_through_stage2_intent": True,
            "same_dose_passes_all_preregistered_clocks": True,
            "cross_dose_spending_forbidden": True,
            "stage1_protected_submission_receipts_complete": True,
            "stage2_protected_submission_receipts_complete": True,
            "all_30_training_completion_receipts_validated": True,
            "stage1_completion_fallback_for_stage2_arms_is_forbidden": True,
            "smoke_and_promoted_run_partitions_are_disjoint_and_exhaustive": True,
            "this_tool_performed_no_scheduler_mutation": True,
        },
        "claim_scope": {
            "finite_time_descriptive_readout_only": True,
            "proves_phase_transition": False,
            "proves_hysteresis": False,
            "proves_asymptotic_ceiling": False,
            "optimized_proxy_is_strict_pass_at_1": False,
        },
    }
    authority["payload_without_self_hash_sha256"] = canonical_json_sha256(authority)
    return authority


def authority_path(authority: dict[str, Any]) -> Path:
    run_root = Path(str(_require_dict(authority.get("inputs"), "authority inputs")["run_root"])).resolve()
    return run_root / AUTHORITY_NAME


def validate_authority(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    raw, observed = _read_canonical(resolved, "promoted evaluation authority")
    if (
        observed.get("schema_version") != SCHEMA_VERSION
        or observed.get("artifact_type") != AUTHORITY_ARTIFACT_TYPE
        or observed.get("study_id") != STUDY_ID
    ):
        raise ValueError("Promoted evaluation authority has the wrong schema, artifact type, or study")
    _validate_self_hash(observed, "promoted evaluation authority")
    if authority_path(observed) != resolved:
        raise ValueError("Promoted evaluation authority is not adjacent to its run root")
    inputs = _require_dict(observed.get("inputs"), "promoted evaluation inputs")
    expected = build_authority(
        postrun_path=Path(str(inputs.get("postrun_authority"))),
        promotion_authority_path=Path(str(inputs.get("promotion_authority"))),
        stage2_intent_path=Path(str(inputs.get("stage2_intent"))),
    )
    if raw != canonical_json_bytes(expected):
        raise ValueError("Promoted evaluation authority differs from full deterministic replay")
    return {"authority": observed, "identity": file_identity(resolved)}


def materialize_authority(
    *,
    postrun_path: Path,
    promotion_authority_path: Path,
    stage2_intent_path: Path,
) -> dict[str, Any]:
    authority = build_authority(
        postrun_path=postrun_path,
        promotion_authority_path=promotion_authority_path,
        stage2_intent_path=stage2_intent_path,
    )
    path = authority_path(authority)
    _write_json_once(path, authority, "promoted evaluation authority")
    return validate_authority(path)


def _promoted_runs(authority: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = _require_dict(authority.get("combined_run_inventory"), "combined run inventory")
    records = [_require_dict(item, "combined run") for item in _require_list(inventory.get("runs"), "combined runs")]
    promoted = [record for record in records if record.get("stage") == "stage2_remaining"]
    if [record.get("arm_filename") for record in promoted] != list(promotion.remaining_arm_filenames()):
        raise ValueError("Promoted evaluation authority does not expose the exact ordered remaining 26 runs")
    return [
        copy.deepcopy(_require_dict(record.get("planner_request_run"), "planner request run")) for record in promoted
    ]


def load_promoted_request(spec_path: Path) -> dict[str, Any]:
    raw, spec = eval_plan.read_json_object(spec_path)
    allowed = {
        "schema_version",
        "artifact_type",
        "study_id",
        "request_seed",
        "optimizer_step_targets",
        "raw_group_targets",
        "tagged_data_dir",
        "promoted_eval_authority",
    }
    unexpected = sorted(set(spec) - allowed)
    if unexpected:
        raise ValueError(f"Promoted eval request has unknown fields: {unexpected}")
    if (
        spec.get("schema_version") != SCHEMA_VERSION
        or spec.get("artifact_type") != PROMOTED_REQUEST_ARTIFACT_TYPE
        or spec.get("study_id") != STUDY_ID
    ):
        raise ValueError("Promoted eval request has the wrong schema, artifact type, or study")
    request_seed = eval_plan._require_int(
        spec.get("request_seed", eval_plan.DEFAULT_REQUEST_SEED),
        "request_seed",
        maximum=2**63 - 1,
    )
    optimizer_targets = eval_plan._require_int_list(
        spec.get("optimizer_step_targets", list(eval_plan.DEFAULT_OPTIMIZER_TARGETS)),
        "optimizer_step_targets",
        minimum=1,
        maximum=eval_plan.MAX_CHECKPOINT_STEP,
    )
    raw_targets = eval_plan._require_int_list(
        spec.get("raw_group_targets", list(eval_plan.DEFAULT_RAW_GROUP_TARGETS)),
        "raw_group_targets",
        minimum=1,
        maximum=10**9,
    )
    if request_seed != eval_plan.DEFAULT_REQUEST_SEED:
        raise ValueError("Promoted eval request changed the frozen request seed")
    if optimizer_targets != eval_plan.DEFAULT_OPTIMIZER_TARGETS:
        raise ValueError("Promoted eval request changed the preregistered optimizer clocks")
    if raw_targets != eval_plan.DEFAULT_RAW_GROUP_TARGETS:
        raise ValueError("Promoted eval request changed the preregistered raw-group clocks")
    tagged_data_dir = Path(spec.get("tagged_data_dir", eval_plan.DEFAULT_TAGGED_DATA_DIR)).expanduser().resolve()
    if not tagged_data_dir.is_dir():
        raise FileNotFoundError(tagged_data_dir)
    configured_authority = spec.get("promoted_eval_authority")
    if not isinstance(configured_authority, str) or not configured_authority:
        raise ValueError("Promoted eval request must name the immutable promoted_eval_authority")
    authority_record = validate_authority(Path(configured_authority))
    authority = authority_record["authority"]
    chain = _require_dict(authority.get("authority_chain"), "promoted authority chain")
    initial_identity = _require_dict(chain.get("initial_launch_intent"), "initial launch identity")
    _, initial_intent = _read_canonical(Path(str(initial_identity["path"])), "initial launch intent")
    initial_inputs = _require_dict(initial_intent.get("inputs"), "initial launch inputs")
    tokenizer_path = Path(str(initial_inputs.get("tokenizer_path"))).resolve()
    decision = _require_dict(initial_intent.get("preregistered_decision"), "initial launch decision")
    runs = _promoted_runs(authority)
    if len(runs) != 26 or len({run["run_id"] for run in runs}) != 26:
        raise ValueError("Promoted eval request does not contain 26 unique run IDs")
    return {
        "spec": {**file_identity(spec_path), "raw_sha256": eval_plan.bytes_sha256(raw)},
        "schema_version": SCHEMA_VERSION,
        "artifact_type": PROMOTED_REQUEST_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "request_seed": request_seed,
        "optimizer_step_targets": list(optimizer_targets),
        "raw_group_targets": list(raw_targets),
        "tagged_data_dir": str(tagged_data_dir),
        "promoted_eval_authority": authority_record["identity"],
        "launch": {
            "submission_intent": initial_identity,
            "payload_without_self_hash_sha256": initial_intent["payload_without_self_hash_sha256"],
            "tokenizer_path": str(tokenizer_path),
            "eligible_design": decision["eligible_design"],
            "eligible_arm_count": decision["eligible_arm_count"],
            "eligible_arm_filenames": decision["eligible_arm_filenames"],
            "launch_source": initial_intent["launch_source"],
        },
        "partition": {
            "name": "promoted_remaining_26",
            "arm_count": 26,
            "arm_filenames": list(promotion.remaining_arm_filenames()),
            "initial_smoke_arms_are_external_immutable_partition": list(promotion.SMOKE_ARM_FILENAMES),
        },
        "runs": runs,
    }


def _promoted_implementation_identities() -> dict[str, Any]:
    return {
        "planner": {
            "repository_path": str(SCRIPT_REPOSITORY_PATH),
            **file_identity(Path(__file__)),
        },
        "historical_planner_helpers": {
            "repository_path": eval_plan.SCRIPT_REPOSITORY_PATH,
            **file_identity(Path(eval_plan.__file__)),
        },
        "evaluator": {
            "repository_path": eval_plan.EVALUATOR_REPOSITORY_PATH,
            **file_identity(Path(eval_plan.figure3_eval.__file__)),
        },
        "strict_scorer": {
            "repository_path": eval_plan.SCORER_REPOSITORY_PATH,
            **file_identity(Path(eval_plan.figure3_eval.solution_graph.__file__)),
        },
        "tagged_eval_materializer": {
            "repository_path": eval_plan.TAGGED_MATERIALIZER_REPOSITORY_PATH,
            **file_identity(Path(eval_plan.tagged_eval.__file__)),
        },
        "training_tag_materializer": {
            "repository_path": eval_plan.tagged_eval.training_tags.IMPLEMENTATION_REPOSITORY_PATH,
            **file_identity(Path(eval_plan.tagged_eval.training_tags.__file__)),
        },
        "launch_intent_materializer": {
            "repository_path": str(eval_plan.launch_intent.CONTROL_PLANE_REPOSITORY_PATHS["launch_materializer"]),
            **file_identity(Path(eval_plan.launch_intent.__file__)),
        },
        "legacy_eval_source_map": {
            "repository_path": "user/tianhaowu/rsci/prepare_rl_checkpoint_eval.py",
            **file_identity(Path(eval_plan.legacy_eval.__file__)),
        },
    }


def build_promoted_plan(spec_path: Path, eval_root: Path) -> eval_plan.PlanBuild:
    request = load_promoted_request(spec_path)
    eval_root = eval_root.expanduser().resolve()
    optimizer_targets = tuple(request["optimizer_step_targets"])
    raw_targets = tuple(request["raw_group_targets"])
    implementations = _promoted_implementation_identities()
    imported_contract = eval_plan._imported_contract_identity()
    data, paired_seed_sequence_sha256 = eval_plan.evaluation_data_identity(
        Path(request["tagged_data_dir"]),
        request["request_seed"],
    )
    run_records = []
    selected_paths: dict[str, dict[int, Path]] = {}
    tokenizer_paths = set()
    for request_run in request["runs"]:
        run_record, paths, tokenizer_path = eval_plan.inspect_run(request_run, optimizer_targets, raw_targets)
        run_records.append(run_record)
        selected_paths[run_record["run_id"]] = paths
        tokenizer_paths.add(tokenizer_path.resolve())
    run_records.sort(key=lambda record: record["run_id"])
    tagged_tokenizer = Path(data["tagged"]["tokenizer"]["path"]).resolve()
    launch_tokenizer = Path(request["launch"]["tokenizer_path"]).resolve()
    if tagged_tokenizer != launch_tokenizer or tokenizer_paths != {tagged_tokenizer}:
        raise ValueError("Promoted run and held-out tag tokenizers differ from the initial launch tokenizer")
    models = eval_plan.deduplicate_model_records(run_records, selected_paths)
    seed_contract = {
        "base_request_seed": request["request_seed"],
        "tagged_common_random_numbers": {
            "mode": eval_plan.figure3_eval.KNOWN_COST_REQUEST_SEED_MODE,
            "derivation": "sha256-paired-source-v1(base_seed,op,source_sample_id,sample_rank)",
            "paired_across": "all six neutral-tag clones, initial smoke plan, and promoted plan",
            "source_count": len(eval_plan.OPERATIONS) * eval_plan.EXAMPLES_PER_OPERATION,
            "seed_sequence_sha256": paired_seed_sequence_sha256,
            "all_source_seeds_unique": True,
        },
        "untagged": {
            "mode": "sha256-v1(base_seed,op,id,row_index,sample_rank)",
            "paired_to_tagged": False,
            "purpose": "legacy-comparable descriptive readout",
        },
    }
    clock_contract = {
        "optimizer_step_targets": list(optimizer_targets),
        "raw_group_targets": list(raw_targets),
        "maximum_checkpoint_step": eval_plan.MAX_CHECKPOINT_STEP,
        "optimizer_rule": "an optimizer target must have that exact retained STABLE checkpoint",
        "raw_group_rule": (
            "an exact target uses its unique retained checkpoint; otherwise evaluate both retained bracket endpoints"
        ),
        "raw_group_checkpoint_semantics": (
            "the checkpoint at step v includes groups with finalized_before_optimizer_step < v"
        ),
        "nearest_checkpoint_substitution_allowed": False,
    }
    semantic_core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": eval_plan.ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "implementation_id": PROMOTED_PLAN_IMPLEMENTATION_ID,
        "request": request,
        "partition": request["partition"],
        "implementations": implementations,
        "imported_contract": imported_contract,
        "evaluation_data": data,
        "seed_contract": seed_contract,
        "clock_contract": clock_contract,
        "runs": run_records,
        "models": models,
        "receipt_contract": eval_plan._receipt_contract(),
    }
    plan_id = eval_plan.canonical_json_sha256(semantic_core)
    plan_root = eval_root / "plans" / plan_id
    evaluator_path = Path(implementations["evaluator"]["path"])
    tasks = []
    artifacts = []
    for task_index, model in enumerate(models):
        task, task_artifacts = eval_plan.build_task_bundle(
            model=model,
            task_index=task_index,
            plan_root=plan_root,
            evaluator_path=evaluator_path,
            tagged_data_dir=Path(request["tagged_data_dir"]),
            tokenizer_path=tagged_tokenizer,
            request_seed=request["request_seed"],
        )
        tasks.append(task)
        artifacts.extend(task_artifacts)
    artifact_paths = [artifact.path.resolve() for artifact in artifacts]
    if len(artifact_paths) != len(set(artifact_paths)):
        raise RuntimeError("Promoted evaluation config paths collide")
    output_dirs = [shard["output_dir"] for task in tasks for shard in task["shards"]]
    if len(output_dirs) != len(set(output_dirs)):
        raise RuntimeError("Promoted evaluation shard output roots collide")
    manifest = {
        **semantic_core,
        "plan_id": plan_id,
        "eval_root": str(eval_root),
        "plan_root": str(plan_root),
        "plan_path": str(plan_root / eval_plan.PLAN_NAME),
        "task_count": len(tasks),
        "shards_per_task": eval_plan.TAG_COUNT + 1,
        "tasks": tasks,
    }
    return eval_plan.PlanBuild(
        manifest,
        eval_plan.canonical_json_bytes(manifest),
        plan_root / eval_plan.PLAN_NAME,
        tuple(artifacts),
    )


def validate_promoted_plan(plan_path: Path) -> dict[str, Any]:
    resolved = plan_path.expanduser().resolve()
    _require_read_only(resolved, "promoted evaluation plan")
    raw, plan = eval_plan.read_json_object(resolved, require_canonical=True)
    if (
        plan.get("schema_version") != SCHEMA_VERSION
        or plan.get("artifact_type") != eval_plan.ARTIFACT_TYPE
        or plan.get("study_id") != STUDY_ID
        or plan.get("implementation_id") != PROMOTED_PLAN_IMPLEMENTATION_ID
    ):
        raise ValueError("Promoted evaluation plan has the wrong schema, artifact, study, or implementation")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or SHA256_RE.fullmatch(plan_id) is None:
        raise ValueError("Promoted evaluation plan has an invalid plan ID")
    expected_path = Path(str(plan.get("eval_root"))) / "plans" / plan_id / eval_plan.PLAN_NAME
    if expected_path.resolve() != resolved or plan.get("plan_path") != str(resolved):
        raise ValueError("Promoted evaluation plan is not at its content-addressed path")
    request = _require_dict(plan.get("request"), "promoted plan request")
    spec = _require_dict(request.get("spec"), "promoted plan request spec")
    expected = build_promoted_plan(Path(str(spec.get("path"))), Path(str(plan["eval_root"])))
    if expected.plan_path.resolve() != resolved or expected.manifest != plan:
        raise ValueError("Promoted evaluation plan differs from deterministic replay")
    eval_plan._validate_materialized_configs(expected)
    plan_sha256 = eval_plan.bytes_sha256(raw)
    receipts = eval_plan.validate_receipt_chain(plan=plan, plan_sha256=plan_sha256)
    return {
        "plan": plan,
        "plan_path": str(resolved),
        "plan_sha256": plan_sha256,
        "task_count": plan["task_count"],
        "model_count": len(plan["models"]),
        "receipts": receipts,
    }


def materialize_promoted_plan(
    spec_path: Path,
    eval_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    build = build_promoted_plan(spec_path, eval_root)
    if dry_run:
        return {
            "dry_run": True,
            "plan": build.manifest,
            "plan_path": str(build.plan_path),
            "plan_sha256": eval_plan.bytes_sha256(build.manifest_bytes),
            "config_count": len(build.config_artifacts),
        }
    if build.plan_path.exists():
        return {**validate_promoted_plan(build.plan_path), "dry_run": False, "already_materialized": True}
    for artifact in build.config_artifacts:
        _write_bytes_once(artifact.path, artifact.content, "promoted evaluation config")
    _write_bytes_once(build.plan_path, build.manifest_bytes, "promoted evaluation plan")
    return {**validate_promoted_plan(build.plan_path), "dry_run": False, "already_materialized": False}


def _require_all_tasks_succeeded(validation: dict[str, Any]) -> dict[str, str]:
    receipts = _require_dict(validation.get("receipts"), "evaluation receipt validation")
    statuses = _require_dict(receipts.get("task_statuses"), "evaluation task statuses")
    plan = _require_dict(validation.get("plan"), "validated evaluation plan")
    task_ids = [str(_require_dict(task, "evaluation task").get("task_id")) for task in plan["tasks"]]
    if set(statuses) != set(task_ids) or any(statuses[task_id] != "succeeded" for task_id in task_ids):
        raise ValueError("Every promoted evaluation task must have one terminal succeeded receipt")
    return {task_id: str(statuses[task_id]) for task_id in sorted(task_ids)}


def _authority_from_promoted_plan(plan: dict[str, Any]) -> dict[str, Any]:
    request = _require_dict(plan.get("request"), "promoted plan request")
    identity = _require_dict(request.get("promoted_eval_authority"), "promoted authority identity")
    path = Path(str(identity.get("path"))).resolve()
    if file_identity(path) != identity:
        raise ValueError("Promoted evaluation authority changed after plan materialization")
    return validate_authority(path)


def _run_contracts_by_filename(authority: dict[str, Any]) -> dict[str, dict[str, Any]]:
    inventory = _require_dict(authority.get("combined_run_inventory"), "combined run inventory")
    records = [_require_dict(record, "combined run") for record in inventory["runs"]]
    by_filename = {str(record.get("arm_filename")): record for record in records}
    if len(by_filename) != 30 or list(by_filename) != list(promotion._expected_arm_filenames()):
        raise ValueError("Promoted authority run contracts do not cover the ordered 30-arm grid")
    return by_filename


def _plan_outcomes(
    plan: dict[str, Any],
    *,
    partition: str,
) -> tuple[dict[str, boundary_results.TaskOutcomes], list[dict[str, Any]]]:
    outcomes = {}
    compact = []
    common_tagged = None
    common_untagged = None
    for raw_task in _require_list(plan.get("tasks"), f"{partition} plan tasks"):
        task = _require_dict(raw_task, f"{partition} plan task")
        task_id = str(task.get("task_id"))
        value = boundary_results.load_task_outcomes(task)
        if common_tagged is None:
            common_tagged = value.tagged_keys
            common_untagged = value.untagged_keys
        elif value.tagged_keys != common_tagged or value.untagged_keys != common_untagged:
            raise ValueError(f"{partition} task {task_id} does not share the partition source universe")
        outcomes[task_id] = value
        record = boundary_results.compact_task_outcomes(task_id, value)
        record["partition"] = partition
        compact.append(record)
    if not outcomes:
        raise ValueError(f"{partition} evaluation plan has no tasks")
    return outcomes, compact


def promoted_result_path(plan: dict[str, Any]) -> Path:
    return (Path(str(plan["plan_root"])) / "analysis" / PROMOTED_RESULT_NAME).resolve()


def build_promoted_result(plan_path: Path) -> dict[str, Any]:
    validation = validate_promoted_plan(plan_path)
    terminal = _require_all_tasks_succeeded(validation)
    plan = validation["plan"]
    authority_record = _authority_from_promoted_plan(plan)
    authority_chain = _require_dict(authority_record["authority"].get("authority_chain"), "authority chain")
    postrun_identity = _require_dict(authority_chain.get("postrun_authority"), "post-run authority identity")
    postrun_path = Path(str(postrun_identity.get("path"))).resolve()
    if file_identity(postrun_path) != postrun_identity:
        raise ValueError("Post-run authority changed after promoted evaluation authorization")
    postrun_record = postrun_authority.validate_authority(postrun_path)
    terminal_provenance = boundary_results.validate_terminal_receipts_with_recorded_dispatcher(
        Path(validation["plan_path"]),
        validation,
        postrun_record,
    )
    if terminal_provenance["summary"]["task_statuses"] != terminal:
        raise ValueError("Protected eval dispatcher and planner disagree on promoted task success")
    contracts = _run_contracts_by_filename(authority_record["authority"])
    promoted_filenames = set(promotion.remaining_arm_filenames())
    factors_by_run = {}
    for raw_run in _require_list(plan.get("runs"), "promoted plan runs"):
        run = _require_dict(raw_run, "promoted plan run")
        binding = _require_dict(run.get("launch_binding"), "promoted run launch binding")
        filename = str(binding.get("arm_filename"))
        if filename not in promoted_filenames:
            raise ValueError(f"Promoted plan contains a smoke or unknown arm: {filename}")
        contract = contracts[filename]
        launch_run = _require_dict(contract.get("run_record"), f"{filename} run contract")
        factors = boundary_results._derive_arm_factors(run, launch_run)
        factors_by_run[factors.run_id] = factors
    if {factor.arm_filename for factor in factors_by_run.values()} != promoted_filenames:
        raise ValueError("Promoted result does not cover the exact remaining 26 factor cells")
    training = training_readouts.build_training_readouts(
        plan,
        {run_id: factors.as_dict() for run_id, factors in factors_by_run.items()},
        postrun_record["authority"],
        completion_validator=validate_stage2_completion_for_training_readouts,
        completion_contract=_require_dict(
            authority_record["authority"].get("stage2_training_readout_contract"),
            "Stage-2 training readout contract",
        ),
    )
    outcomes_by_task, compact = _plan_outcomes(plan, partition="promoted26")
    occurrence_index = boundary_results._occurrence_index(plan, outcomes_by_task)
    readouts = boundary_results.build_clock_readouts(plan, factors_by_run, occurrence_index)
    expected_readout_count = 26 * (len(eval_plan.DEFAULT_OPTIMIZER_TARGETS) + len(eval_plan.DEFAULT_RAW_GROUP_TARGETS))
    if len(readouts) != expected_readout_count:
        raise ValueError("Promoted result does not contain every arm-by-clock readout")
    result_path = promoted_result_path(plan)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": PROMOTED_RESULT_ARTIFACT_TYPE,
        "analysis_id": PROMOTED_RESULT_ANALYSIS_ID,
        "study_id": STUDY_ID,
        "analysis_path": str(result_path),
        "provenance": {
            "implementation": {
                "repository_path": str(SCRIPT_REPOSITORY_PATH),
                **file_identity(Path(__file__)),
            },
            "promoted_eval_authority": authority_record["identity"],
            "promoted_eval_plan": file_identity(Path(validation["plan_path"])),
            "promoted_eval_plan_sha256": validation["plan_sha256"],
            "terminal_task_statuses": terminal,
            "recorded_eval_dispatcher": terminal_provenance["implementation"],
            "recorded_eval_dispatcher_validation_summary_sha256": terminal_provenance["summary_sha256"],
            "eval_terminal_provenance": terminal_provenance["identity"],
            "eval_terminal_provenance_payload_without_self_hash_sha256": terminal_provenance["artifact"][
                "payload_without_self_hash_sha256"
            ],
            "evaluator": plan["implementations"]["evaluator"],
            "strict_scorer": plan["implementations"]["strict_scorer"],
        },
        "partition": {
            "name": "promoted_remaining_26",
            "arm_count": 26,
            "arm_filenames": list(promotion.remaining_arm_filenames()),
        },
        "arm_factors": [factor.as_dict() for factor in sorted(factors_by_run.values(), key=lambda x: x.run_id)],
        "source_index": boundary_results._source_index_record(next(iter(outcomes_by_task.values()))),
        "task_outcomes": compact,
        "eval_terminal_provenance": terminal_provenance["artifact"],
        "training_readouts": training,
        "clock_readouts": [readout.record for readout in readouts],
        "claim_scope": {
            "finite_time_descriptive_readout_only": True,
            "requires_combined_smoke4_plus_promoted26_artifact_for_full_grid_contrasts": True,
            "proves_phase_transition": False,
            "proves_hysteresis": False,
            "proves_asymptotic_ceiling": False,
        },
    }
    report["payload_without_self_hash_sha256"] = canonical_json_sha256(report)
    return report


def validate_promoted_result(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    raw, report = _read_canonical(resolved, "promoted result analysis")
    if (
        report.get("schema_version") != SCHEMA_VERSION
        or report.get("artifact_type") != PROMOTED_RESULT_ARTIFACT_TYPE
        or report.get("analysis_id") != PROMOTED_RESULT_ANALYSIS_ID
        or report.get("study_id") != STUDY_ID
        or report.get("analysis_path") != str(resolved)
    ):
        raise ValueError("Promoted result analysis has the wrong schema, artifact, analysis, study, or path")
    _validate_self_hash(report, "promoted result analysis")
    provenance = _require_dict(report.get("provenance"), "promoted result provenance")
    plan_identity = _require_dict(provenance.get("promoted_eval_plan"), "promoted result plan identity")
    plan_path = Path(str(plan_identity.get("path"))).resolve()
    if file_identity(plan_path) != plan_identity:
        raise ValueError("Promoted result plan changed")
    expected = build_promoted_result(plan_path)
    if raw != canonical_json_bytes(expected):
        raise ValueError("Promoted result analysis differs from full deterministic replay")
    return {"analysis": report, "identity": file_identity(resolved)}


def analyze_promoted_plan(plan_path: Path) -> dict[str, Any]:
    report = build_promoted_result(plan_path)
    path = Path(report["analysis_path"])
    _write_json_once(path, report, "promoted result analysis")
    return validate_promoted_result(path)


def _same_outcomes(left: boundary_results.TaskOutcomes, right: boundary_results.TaskOutcomes) -> bool:
    if left.tagged_keys != right.tagged_keys or left.untagged_keys != right.untagged_keys:
        return False
    return all(
        boundary_results.np.array_equal(left.tagged[name], right.tagged[name])
        and boundary_results.np.array_equal(left.untagged[name], right.untagged[name])
        for name in boundary_results.OUTCOMES
    )


def _step_zero_checkpoint(plan: dict[str, Any], label: str) -> dict[str, Any]:
    matches = []
    for raw_model in _require_list(plan.get("models"), f"{label} models"):
        model = _require_dict(raw_model, f"{label} model")
        occurrences = [
            _require_dict(item, f"{label} occurrence")
            for item in _require_list(model.get("occurrences"), f"{label} occurrences")
        ]
        if any(occurrence.get("step") == 0 for occurrence in occurrences):
            matches.append(_require_dict(model.get("checkpoint"), f"{label} step-zero checkpoint"))
    if len(matches) != 1:
        raise ValueError(f"{label} plan has {len(matches)} shared step-zero checkpoint records")
    return matches[0]


def _validated_training_partition(
    report: object,
    *,
    expected_run_ids: set[str],
    label: str,
) -> dict[str, Any]:
    value = _require_dict(report, f"{label} training readouts")
    if (
        value.get("schema_version") != training_readouts.SCHEMA_VERSION
        or value.get("artifact_type") != training_readouts.ARTIFACT_TYPE
        or value.get("analysis_id") != training_readouts.ANALYSIS_ID
        or value.get("study_id") != STUDY_ID
    ):
        raise ValueError(f"{label} training readouts have the wrong schema, artifact, analysis, or study")
    self_hash = _require_sha256(
        value.get("payload_without_self_hash_sha256"),
        f"{label} training readout self hash",
    )
    unhashed = dict(value)
    unhashed.pop("payload_without_self_hash_sha256")
    if eval_plan.canonical_json_sha256(unhashed) != self_hash:
        raise ValueError(f"{label} training readout self hash differs")
    provenance = _require_dict(value.get("provenance"), f"{label} training provenance")
    run_artifacts = _require_dict(provenance.get("run_artifacts"), f"{label} training run artifacts")
    if set(run_artifacts) != expected_run_ids:
        raise ValueError(f"{label} training provenance has the wrong run inventory")
    readouts = [_require_dict(item, f"{label} arm-clock readout") for item in value["arm_clock_readouts"]]
    expected_clocks = {
        *(("optimizer_step", target) for target in eval_plan.DEFAULT_OPTIMIZER_TARGETS),
        *(("raw_groups", target) for target in eval_plan.DEFAULT_RAW_GROUP_TARGETS),
    }
    keys = []
    for readout in readouts:
        run_id = str(readout.get("run_id"))
        key = (str(readout.get("clock_kind")), readout.get("target"))
        if run_id not in expected_run_ids or key not in expected_clocks:
            raise ValueError(f"{label} training readout has an unknown run or clock")
        keys.append((run_id, *key))
    expected_keys = {(run_id, *clock) for run_id in expected_run_ids for clock in expected_clocks}
    if len(keys) != len(set(keys)) or set(keys) != expected_keys:
        raise ValueError(f"{label} training readouts do not cover every exact arm-by-clock cell")
    return value


def _combine_training_readouts(
    *,
    smoke_report: dict[str, Any],
    promoted_report: dict[str, Any],
    smoke_run_ids: set[str],
    promoted_run_ids: set[str],
    smoke_result_identity: dict[str, Any],
    promoted_result_identity: dict[str, Any],
) -> dict[str, Any]:
    smoke = _validated_training_partition(
        smoke_report.get("training_readouts"),
        expected_run_ids=smoke_run_ids,
        label="smoke4",
    )
    promoted = _validated_training_partition(
        promoted_report.get("training_readouts"),
        expected_run_ids=promoted_run_ids,
        label="promoted26",
    )
    smoke_provenance = _require_dict(smoke.get("provenance"), "smoke training provenance")
    promoted_provenance = _require_dict(promoted.get("provenance"), "promoted training provenance")
    if smoke_provenance.get("implementation") != promoted_provenance.get("implementation"):
        raise ValueError("Smoke and promoted training readouts used different pinned consumers")
    if smoke.get("availability") != promoted.get("availability"):
        raise ValueError("Smoke and promoted training readouts make different availability claims")
    run_artifacts = {
        **_require_dict(smoke_provenance.get("run_artifacts"), "smoke training run artifacts"),
        **_require_dict(promoted_provenance.get("run_artifacts"), "promoted training run artifacts"),
    }
    if len(run_artifacts) != 30:
        raise ValueError("Combined training provenance does not contain 30 unique runs")
    readouts = [
        *[_require_dict(item, "smoke training readout") for item in smoke["arm_clock_readouts"]],
        *[_require_dict(item, "promoted training readout") for item in promoted["arm_clock_readouts"]],
    ]
    readouts.sort(
        key=lambda item: (
            int(item["block_seed"]),
            str(item["family"]),
            float(item["dose"]),
            str(item["clock_kind"]),
            int(item["target"]),
        )
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": COMBINED_TRAINING_ARTIFACT_TYPE,
        "analysis_id": COMBINED_TRAINING_ANALYSIS_ID,
        "study_id": STUDY_ID,
        "claim_scope": smoke["claim_scope"],
        "availability": smoke["availability"],
        "provenance": {
            "implementation": smoke_provenance["implementation"],
            "immutable_smoke_result": smoke_result_identity,
            "immutable_promoted_result": promoted_result_identity,
            "run_artifacts": run_artifacts,
        },
        "partition_join": {
            "smoke_run_count": len(smoke_run_ids),
            "promoted_run_count": len(promoted_run_ids),
            "combined_run_count": len(run_artifacts),
            "readout_count": len(readouts),
            "all_six_preregistered_clocks_present_per_run": True,
        },
        "arm_clock_readouts": readouts,
    }
    report["payload_without_self_hash_sha256"] = eval_plan.canonical_json_sha256(report)
    return report


def combined_result_path(promoted_plan: dict[str, Any]) -> Path:
    return (Path(str(promoted_plan["plan_root"])) / "analysis" / COMBINED_RESULT_NAME).resolve()


def build_combined_result(
    *,
    smoke_analysis_path: Path,
    promoted_analysis_path: Path,
) -> dict[str, Any]:
    smoke_record = boundary_results.validate_analysis(smoke_analysis_path)
    promoted_record = validate_promoted_result(promoted_analysis_path)
    promoted_report = promoted_record["analysis"]
    promoted_provenance = _require_dict(promoted_report.get("provenance"), "promoted result provenance")
    promoted_plan_path = Path(str(_require_dict(promoted_provenance["promoted_eval_plan"], "promoted plan")["path"]))
    promoted_validation = validate_promoted_plan(promoted_plan_path)
    promoted_plan = promoted_validation["plan"]
    authority_record = _authority_from_promoted_plan(promoted_plan)
    authority = authority_record["authority"]
    authority_chain = _require_dict(authority.get("authority_chain"), "promoted authority chain")
    if authority_chain.get("passing_smoke_result") != smoke_record["analysis_identity"]:
        raise ValueError("Combined result smoke analysis differs from the promotion spending input")

    smoke_report = smoke_record["analysis"]
    smoke_provenance = _require_dict(smoke_report.get("provenance"), "smoke analysis provenance")
    smoke_plan_identity = _require_dict(smoke_provenance.get("eval_plan"), "smoke plan identity")
    smoke_plan_path = Path(str(smoke_plan_identity.get("path"))).resolve()
    smoke_validation = boundary_results.validate_plan_with_recorded_planner(smoke_plan_path)
    boundary_results.require_all_tasks_succeeded(smoke_validation)
    smoke_plan = smoke_validation["plan"]
    if authority_chain.get("smoke_eval_plan") != smoke_plan_identity:
        raise ValueError("Promoted authority and combined result bind different smoke plans")

    initial_intent, smoke_launch_runs = boundary_results._load_launch_authority(smoke_plan)
    if (
        _require_dict(initial_intent.get("preregistered_decision"), "smoke launch decision").get("eligible_design")
        != "four_arm_smoke_screen"
    ):
        raise ValueError("Combined result requires the exact initial four-arm smoke design")
    contracts = _run_contracts_by_filename(authority)
    factors_by_run = {}
    smoke_run_ids = set()
    for raw_run in _require_list(smoke_plan.get("runs"), "smoke plan runs"):
        run = _require_dict(raw_run, "smoke plan run")
        filename = str(_require_dict(run.get("launch_binding"), "smoke run binding")["arm_filename"])
        factors = boundary_results._derive_arm_factors(run, smoke_launch_runs[filename])
        factors_by_run[factors.run_id] = factors
        smoke_run_ids.add(factors.run_id)
    promoted_run_ids = set()
    for raw_run in _require_list(promoted_plan.get("runs"), "promoted plan runs"):
        run = _require_dict(raw_run, "promoted plan run")
        filename = str(_require_dict(run.get("launch_binding"), "promoted run binding")["arm_filename"])
        factors = boundary_results._derive_arm_factors(run, contracts[filename]["run_record"])
        if factors.run_id in factors_by_run:
            raise ValueError("Smoke and promoted plans reuse a run ID")
        factors_by_run[factors.run_id] = factors
        promoted_run_ids.add(factors.run_id)
    boundary_results._validate_factor_inventory(list(factors_by_run.values()), "full_30_arm_grid")
    if len(smoke_run_ids) != 4 or len(promoted_run_ids) != 26:
        raise ValueError("Combined result partitions are not exact smoke4 plus promoted26")
    combined_training = _combine_training_readouts(
        smoke_report=smoke_report,
        promoted_report=promoted_report,
        smoke_run_ids=smoke_run_ids,
        promoted_run_ids=promoted_run_ids,
        smoke_result_identity=smoke_record["analysis_identity"],
        promoted_result_identity=promoted_record["identity"],
    )

    smoke_outcomes, smoke_compact = _plan_outcomes(smoke_plan, partition="smoke4")
    promoted_outcomes, promoted_compact = _plan_outcomes(promoted_plan, partition="promoted26")
    smoke_first = next(iter(smoke_outcomes.values()))
    promoted_first = next(iter(promoted_outcomes.values()))
    if (
        smoke_first.tagged_keys != promoted_first.tagged_keys
        or smoke_first.untagged_keys != promoted_first.untagged_keys
    ):
        raise ValueError("Smoke and promoted plans do not share the same held-out source universe")
    smoke_step_zero = _step_zero_checkpoint(smoke_plan, "smoke")
    promoted_step_zero = _step_zero_checkpoint(promoted_plan, "promoted")
    if smoke_step_zero != promoted_step_zero:
        raise ValueError("Smoke and promoted plans bind different step-zero checkpoint inventories")
    smoke_index = boundary_results._occurrence_index(smoke_plan, smoke_outcomes)
    promoted_index = boundary_results._occurrence_index(promoted_plan, promoted_outcomes)
    if set(smoke_index) & set(promoted_index):
        raise ValueError("Smoke and promoted checkpoint occurrence keys overlap")
    smoke_initial = next(value[2] for (run_id, step), value in smoke_index.items() if step == 0)
    promoted_initial = next(value[2] for (run_id, step), value in promoted_index.items() if step == 0)
    if not _same_outcomes(smoke_initial, promoted_initial):
        raise ValueError("Repeated shared initialization evaluation differs across the two immutable plans")
    occurrence_index = {**smoke_index, **promoted_index}
    combined_plan = {"runs": [*smoke_plan["runs"], *promoted_plan["runs"]]}
    readouts = boundary_results.build_clock_readouts(combined_plan, factors_by_run, occurrence_index)
    expected_readouts = 30 * (len(eval_plan.DEFAULT_OPTIMIZER_TARGETS) + len(eval_plan.DEFAULT_RAW_GROUP_TARGETS))
    if len(readouts) != expected_readouts:
        raise ValueError("Combined result does not contain every arm-by-clock readout")
    contrasts = boundary_results.build_contrasts(readouts, "full_30_arm_grid")
    result_path = combined_result_path(promoted_plan)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": COMBINED_RESULT_ARTIFACT_TYPE,
        "analysis_id": COMBINED_RESULT_ANALYSIS_ID,
        "study_id": STUDY_ID,
        "analysis_path": str(result_path),
        "provenance": {
            "implementation": {
                "repository_path": str(SCRIPT_REPOSITORY_PATH),
                **file_identity(Path(__file__)),
            },
            "promoted_eval_authority": authority_record["identity"],
            "immutable_smoke_result": smoke_record["analysis_identity"],
            "immutable_smoke_plan": smoke_plan_identity,
            "immutable_promoted_result": promoted_record["identity"],
            "immutable_promoted_plan": file_identity(promoted_plan_path),
        },
        "partition_join": {
            "smoke_arm_count": 4,
            "promoted_arm_count": 26,
            "combined_arm_count": 30,
            "ordered_arm_filenames": list(promotion._expected_arm_filenames()),
            "shared_initialization_checkpoint": smoke_step_zero,
            "shared_initialization_repeated_eval_is_bit_exact": True,
            "same_source_universe_across_partitions": True,
        },
        "arm_factors": [factor.as_dict() for factor in sorted(factors_by_run.values(), key=lambda x: x.run_id)],
        "source_index": boundary_results._source_index_record(smoke_first),
        "task_outcomes": [*smoke_compact, *promoted_compact],
        "training_readouts": combined_training,
        "clock_readouts": [readout.record for readout in readouts],
        "contrasts": contrasts,
        "smoke_spend_decision": boundary_results.smoke_spend_decision(
            _require_list(contrasts["gate_dose_T_minus_G_by_block"], "combined G/T contrasts"),
            eligible_design="full_30_arm_grid",
        ),
        "claim_scope": {
            "finite_time_descriptive_readout_only": True,
            "exploratory_promoted_grid_after_preregistered_smoke_spending": True,
            "confirmatory_phase_or_hysteresis_claim_allowed": False,
            "proves_phase_transition": False,
            "proves_hysteresis": False,
            "proves_asymptotic_ceiling": False,
            "optimized_proxy_is_strict_pass_at_1": False,
        },
    }
    report["payload_without_self_hash_sha256"] = canonical_json_sha256(report)
    return report


def validate_combined_result(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    raw, report = _read_canonical(resolved, "combined result analysis")
    if (
        report.get("schema_version") != SCHEMA_VERSION
        or report.get("artifact_type") != COMBINED_RESULT_ARTIFACT_TYPE
        or report.get("analysis_id") != COMBINED_RESULT_ANALYSIS_ID
        or report.get("study_id") != STUDY_ID
        or report.get("analysis_path") != str(resolved)
    ):
        raise ValueError("Combined result has the wrong schema, artifact, analysis, study, or path")
    _validate_self_hash(report, "combined result analysis")
    provenance = _require_dict(report.get("provenance"), "combined result provenance")
    expected = build_combined_result(
        smoke_analysis_path=Path(str(_require_dict(provenance["immutable_smoke_result"], "smoke result")["path"])),
        promoted_analysis_path=Path(
            str(_require_dict(provenance["immutable_promoted_result"], "promoted result")["path"])
        ),
    )
    if raw != canonical_json_bytes(expected):
        raise ValueError("Combined result differs from full deterministic replay")
    return {"analysis": report, "identity": file_identity(resolved)}


def combine_results(
    *,
    smoke_analysis_path: Path,
    promoted_analysis_path: Path,
) -> dict[str, Any]:
    report = build_combined_result(
        smoke_analysis_path=smoke_analysis_path,
        promoted_analysis_path=promoted_analysis_path,
    )
    path = Path(report["analysis_path"])
    _write_json_once(path, report, "combined result analysis")
    return validate_combined_result(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage2_completion = subparsers.add_parser("materialize-stage2-completion")
    stage2_completion.add_argument("--promotion-authority", type=Path, required=True)
    stage2_completion.add_argument("--stage2-intent", type=Path, required=True)
    stage2_completion.add_argument("--arm", required=True)
    stage2_completion.add_argument("--run-dir", type=Path, required=True)
    validate_stage2_completion = subparsers.add_parser("validate-stage2-completion")
    validate_stage2_completion.add_argument("--receipt", type=Path, required=True)
    validate_stage2_completion.add_argument("--recheck-live-scheduler", action="store_true")

    materialize_authority_parser = subparsers.add_parser("materialize-authority")
    materialize_authority_parser.add_argument("--postrun-authority", type=Path, required=True)
    materialize_authority_parser.add_argument("--promotion-authority", type=Path, required=True)
    materialize_authority_parser.add_argument("--stage2-intent", type=Path, required=True)
    validate_authority_parser = subparsers.add_parser("validate-authority")
    validate_authority_parser.add_argument("--authority", type=Path, required=True)

    materialize_plan_parser = subparsers.add_parser("materialize-plan")
    materialize_plan_parser.add_argument("--spec", type=Path, required=True)
    materialize_plan_parser.add_argument("--eval-root", type=Path, default=eval_plan.DEFAULT_EVAL_ROOT)
    materialize_plan_parser.add_argument("--dry-run", action="store_true")
    validate_plan_parser = subparsers.add_parser("validate-plan")
    validate_plan_parser.add_argument("--plan", type=Path, required=True)
    runner_validate_parser = subparsers.add_parser("validate")
    runner_validate_parser.add_argument("--plan", type=Path, required=True)

    analyze_promoted_parser = subparsers.add_parser("analyze-promoted")
    analyze_promoted_parser.add_argument("--plan", type=Path, required=True)
    validate_promoted_parser = subparsers.add_parser("validate-promoted")
    validate_promoted_parser.add_argument("--analysis", type=Path, required=True)
    combine_parser = subparsers.add_parser("combine")
    combine_parser.add_argument("--smoke-analysis", type=Path, required=True)
    combine_parser.add_argument("--promoted-analysis", type=Path, required=True)
    validate_combined_parser = subparsers.add_parser("validate-combined")
    validate_combined_parser.add_argument("--analysis", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize-stage2-completion":
        result = materialize_stage2_completion_receipt(
            promotion_authority_path=args.promotion_authority,
            stage2_intent_path=args.stage2_intent,
            arm_filename=args.arm,
            run_dir=args.run_dir,
        )
        summary = {
            "command": args.command,
            "receipt": result["identity"],
            "scheduler_mutation": False,
        }
    elif args.command == "validate-stage2-completion":
        result = validate_stage2_completion_receipt(
            args.receipt,
            recheck_live_scheduler=args.recheck_live_scheduler,
        )
        summary = {
            "command": args.command,
            "receipt": result["identity"],
            "scheduler_mutation": False,
        }
    elif args.command == "materialize-authority":
        result = materialize_authority(
            postrun_path=args.postrun_authority,
            promotion_authority_path=args.promotion_authority,
            stage2_intent_path=args.stage2_intent,
        )
        summary = {
            "command": args.command,
            "authority": result["identity"],
            "combined_arm_count": 30,
            "scheduler_mutation": False,
        }
    elif args.command == "validate-authority":
        result = validate_authority(args.authority)
        summary = {
            "command": args.command,
            "authority": result["identity"],
            "combined_arm_count": 30,
            "scheduler_mutation": False,
        }
    elif args.command == "materialize-plan":
        result = materialize_promoted_plan(args.spec, args.eval_root, dry_run=args.dry_run)
        summary = {
            "command": args.command,
            "plan_id": result["plan"]["plan_id"],
            "plan_path": result["plan_path"],
            "plan_sha256": result["plan_sha256"],
            "dry_run": result["dry_run"],
        }
    elif args.command in {"validate", "validate-plan"}:
        result = validate_promoted_plan(args.plan)
        summary = {
            "command": "validate",
            "plan_id": result["plan"]["plan_id"],
            "plan_path": result["plan_path"],
            "plan_sha256": result["plan_sha256"],
        }
    elif args.command == "analyze-promoted":
        result = analyze_promoted_plan(args.plan)
        summary = {"command": args.command, "analysis": result["identity"]}
    elif args.command == "validate-promoted":
        result = validate_promoted_result(args.analysis)
        summary = {"command": args.command, "analysis": result["identity"]}
    elif args.command == "combine":
        result = combine_results(
            smoke_analysis_path=args.smoke_analysis,
            promoted_analysis_path=args.promoted_analysis,
        )
        summary = {"command": args.command, "analysis": result["identity"]}
    elif args.command == "validate-combined":
        result = validate_combined_result(args.analysis)
        summary = {"command": args.command, "analysis": result["identity"]}
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
