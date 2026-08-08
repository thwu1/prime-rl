#!/usr/bin/env python3
"""Freeze the pre-result task plan for known-cost checkpoint kernel probes."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

import probe_known_cost_checkpoint_kernel as checkpoint_probe

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_checkpoint_kernel_plan"
STUDY_ID = "verifier-defect-known-cost-boundary-v1"
RUN_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/rl/verifier-defect-known-cost-boundary-v1")
ANALYSIS_ROOT = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-checkpoint-kernel-v1"
)
SOURCE_PROBE = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/analysis/known-cost-tag-kernel-v2/probe"
)
EXPECTED_ARMS = {
    "b20260808_g_p0125.toml": "g-p0125",
    "b20260808_t_p0125.toml": "t-p0125",
    "b20260808_g_p0375.toml": "g-p0375",
    "b20260808_t_p0375.toml": "t-p0375",
}
CHECKPOINT_STEPS = (375, 750, 1500)
PREREGISTRATION_PATH = Path(
    "user/tianhaowu/rsci/configs/rl/known_cost_checkpoint_kernel_v1/PREREGISTRATION.md"
)
README_PATH = Path("user/tianhaowu/rsci/configs/rl/known_cost_checkpoint_kernel_v1/README.md")


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


def read_canonical_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    raw = resolved.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {resolved}")
    if raw != canonical_json_bytes(value):
        raise ValueError(f"JSON is not canonical: {resolved}")
    return raw, value


def validate_self_hashed_artifact(
    path: Path,
    *,
    artifact_type: str,
    study_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError(f"Artifact is writable: {resolved}")
    _, value = read_canonical_json(resolved)
    if value.get("artifact_type") != artifact_type or value.get("study_id") != study_id:
        raise ValueError(f"Artifact type or study differs: {resolved}")
    payload = dict(value)
    self_hash = payload.pop("payload_without_self_hash_sha256", None)
    if self_hash != canonical_json_sha256(payload):
        raise ValueError(f"Artifact self hash differs: {resolved}")
    checks = value.get("checks")
    if not isinstance(checks, dict) or not checks or any(check is not True for check in checks.values()):
        raise ValueError(f"Artifact checks are not all true: {resolved}")
    return value, file_identity(resolved)


def expected_paths(intent: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Path]]:
    eligible = intent.get("eligible_runs")
    if not isinstance(eligible, list) or len(eligible) != len(EXPECTED_ARMS):
        raise ValueError("Submission intent does not contain exactly four eligible smoke runs")
    by_filename = {}
    for run in eligible:
        if not isinstance(run, dict):
            raise ValueError("Submission intent eligible run is not an object")
        filename = run.get("arm_filename")
        if filename in by_filename:
            raise ValueError(f"Duplicate eligible arm {filename}")
        by_filename[filename] = run
    if set(by_filename) != set(EXPECTED_ARMS):
        raise ValueError("Submission intent eligible arm partition differs from the fixed smoke four")

    tasks = [
        {
            "task_id": "reference-step-0000",
            "role": "matched_bfloat16_roundtrip_reference",
            "arm_filename": None,
            "condition": "reference",
            "family": None,
            "nominal_p": None,
            "checkpoint_step": 0,
            "model_path": intent["inputs"]["tokenizer_path"],
            "completion_receipt_path": None,
            "result_relative_path": "results/reference/step_0/kernel.json",
        }
    ]
    future_paths = []
    for filename, condition in EXPECTED_ARMS.items():
        run = by_filename[filename]
        if run.get("condition") != condition.replace("-", "_"):
            raise ValueError(f"Condition label differs for {filename}")
        run_dir = Path(str(run.get("output_dir"))).expanduser().resolve()
        if run_dir.parent.parent != RUN_ROOT or run_dir.name != condition:
            raise ValueError(f"Run output path differs for {filename}: {run_dir}")
        projection = run.get("scientific_config_projection", {}).get("projection", {})
        if projection.get("ckpt") != {"interval": 25, "keep_interval": 25, "keep_last": 4}:
            raise ValueError(f"Checkpoint retention differs for {filename}")
        if projection.get("orchestrator", {}).get("stop_when") != {
            "min_finalized_groups": 12000,
            "min_steps": 1500,
            "step_multiple": 50,
        }:
            raise ValueError(f"Joint stop contract differs for {filename}")
        receipt_path = run_dir / "training_completion_receipt.json"
        future_paths.append(receipt_path)
        for step in CHECKPOINT_STEPS:
            checkpoint = run_dir / "weights" / f"step_{step}"
            future_paths.extend((checkpoint / "model.safetensors", checkpoint / "STABLE"))
            tasks.append(
                {
                    "task_id": f"{condition}-step-{step:04d}",
                    "role": "trained_hf_readout_checkpoint",
                    "arm_filename": filename,
                    "condition": condition,
                    "family": run.get("family"),
                    "nominal_p": run.get("nominal_p"),
                    "checkpoint_step": step,
                    "model_path": str(checkpoint),
                    "completion_receipt_path": str(receipt_path),
                    "result_relative_path": f"results/{condition}/step_{step}/kernel.json",
                }
            )
    if len(tasks) != 13 or len({task["task_id"] for task in tasks}) != 13:
        raise RuntimeError("Checkpoint kernel plan did not produce 13 unique primary tasks")
    return tasks, future_paths


def capture_pre_result_observation(intent: dict[str, Any]) -> dict[str, Any]:
    tasks, paths = expected_paths(intent)
    existing = [str(path) for path in paths if path.exists()]
    existing_results = sorted(str(path) for path in (ANALYSIS_ROOT / "plans").glob("*/results/**/kernel.json"))
    existing.extend(existing_results)
    if existing:
        raise FileExistsError(f"Checkpoint-kernel inputs or outputs already exist, first={existing[0]}")
    return {
        "future_input_path_inventory": sorted(str(path) for path in paths),
        "result_relative_path_inventory": sorted(task["result_relative_path"] for task in tasks),
        "all_future_checkpoints_receipts_and_results_absent": True,
        "existing_path_count": 0,
    }


def validate_pre_result_observation(intent: dict[str, Any], observation: object) -> dict[str, Any]:
    if not isinstance(observation, dict):
        raise ValueError("Pre-result observation is not an object")
    tasks, paths = expected_paths(intent)
    expected = {
        "future_input_path_inventory": sorted(str(path) for path in paths),
        "result_relative_path_inventory": sorted(task["result_relative_path"] for task in tasks),
        "all_future_checkpoints_receipts_and_results_absent": True,
        "existing_path_count": 0,
    }
    if observation != expected:
        raise ValueError("Pre-result observation does not cover the exact task inventory")
    return expected


def build_plan_payload(
    *,
    intent_path: Path,
    postrun_authority_path: Path,
    promotion_authority_path: Path,
    source_probe_dir: Path,
    pre_result_observation: dict[str, Any],
) -> dict[str, Any]:
    intent_path = intent_path.expanduser().resolve()
    postrun_authority_path = postrun_authority_path.expanduser().resolve()
    promotion_authority_path = promotion_authority_path.expanduser().resolve()
    source_probe_dir = source_probe_dir.expanduser().resolve()
    if intent_path != RUN_ROOT / "submission_intent.json":
        raise ValueError("Checkpoint-kernel plan requires the production submission intent")
    if postrun_authority_path != RUN_ROOT / "postrun_authority.json":
        raise ValueError("Checkpoint-kernel plan requires the production post-run authority")
    if promotion_authority_path != RUN_ROOT / "promotion_authority.json":
        raise ValueError("Checkpoint-kernel plan requires the production promotion authority")
    if source_probe_dir != SOURCE_PROBE:
        raise ValueError("Checkpoint-kernel plan requires the sealed production source probe")

    intent, intent_identity = validate_self_hashed_artifact(
        intent_path,
        artifact_type="rsci_known_cost_boundary_submission_intent",
        study_id=STUDY_ID,
    )
    postrun, postrun_identity = validate_self_hashed_artifact(
        postrun_authority_path,
        artifact_type="rsci_known_cost_postrun_authority",
        study_id=STUDY_ID,
    )
    promotion, promotion_identity = validate_self_hashed_artifact(
        promotion_authority_path,
        artifact_type="rsci_known_cost_boundary_promotion_authority",
        study_id=STUDY_ID,
    )
    for authority, label in ((postrun, "post-run"), (promotion, "promotion")):
        inputs = authority.get("inputs")
        if not isinstance(inputs, dict) or Path(str(inputs.get("initial_launch_intent"))).resolve() != intent_path:
            raise ValueError(f"{label} authority binds another initial intent")
        if Path(str(inputs.get("run_root"))).resolve() != RUN_ROOT:
            raise ValueError(f"{label} authority binds another run root")

    tasks, _ = expected_paths(intent)
    validate_pre_result_observation(intent, pre_result_observation)
    source = checkpoint_probe.validate_source_probe(source_probe_dir)
    source_manifest = source["manifest"]
    source_model_path = Path(str(source_manifest["inputs"]["model"]["configured_name"]))
    source_record = {
        "directory": str(source_probe_dir),
        "manifest": file_identity(source_probe_dir / checkpoint_probe.initial_probe.MANIFEST_NAME),
        "dataset": file_identity(source_probe_dir / checkpoint_probe.initial_probe.DATASET_NAME),
        "pairs": source_manifest["selection"]["pairs"],
        "tagged_pairs": source_manifest["selection"]["tagged_pairs"],
        "objective": source_manifest["objective"],
        "source_model": source_manifest["inputs"]["model"],
        "validation": source["validation"],
    }
    repository_root = Path(__file__).resolve().parents[3]
    preregistration = file_identity(repository_root / PREREGISTRATION_PATH)
    readme = file_identity(repository_root / README_PATH)

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "inputs": {
            "submission_intent": intent_identity,
            "postrun_authority": postrun_identity,
            "promotion_authority": promotion_identity,
            "source_probe": source_record,
            "reference_model": {
                "model": checkpoint_probe.initial_probe.model_identity(source_model_path),
                "architecture": checkpoint_probe.architecture_signature(source_model_path),
                "normalized_config": checkpoint_probe.normalized_config_signature(source_model_path),
                "tokenizer_semantics": checkpoint_probe.tokenizer_semantic_signature(source_model_path),
                "source_storage_dtypes": checkpoint_probe.model_storage_dtypes(source_model_path),
                "probe_weight_transform": (
                    "load source in float32, explicitly round floating parameters and buffers through "
                    "bfloat16, then probe in float32"
                ),
            },
        },
        "pre_result_observation": pre_result_observation,
        "tasks": tasks,
        "runtime_contract": checkpoint_probe.runtime_contract(),
        "analysis_rule": {
            "selected_tags": [0, 1],
            "localization_ratio": "(ell_S^T G_t delta_S) / ((1/6) 1^T G_t 1)",
            "tenfold_amplification_threshold": (
                "at two consecutive clocks: abs(R_t)>=10*abs(R_0), abs(N_t)>=10*abs(N_0), "
                "D_t>=0.5*D_0, and the measured combined-gradient finite slope has the common nonzero N sign"
            ),
            "conditional_repeat": (
                "test [375,750] then [750,1500] per arm; repeat only the first qualifying pair in fresh GPU "
                "processes; both repeats must retain every threshold and sign condition"
            ),
            "practical_effect_calibrated": False,
            "can_change_smoke_promotion": False,
        },
        "readiness_policy": {
            "future_checkpoint_hashes_claimed_by_plan": False,
            "trained_task_requires_read_only_readiness_manifest": True,
            "readiness_must_bind_authority_pinned_completion_validation": True,
            "readiness_must_bind_exact_intermediate_checkpoint_inventory_and_stable_marker": True,
            "step0_requires_separate_pre_execution_authority": True,
        },
        "execution_policy": {
            "submission_channel": "protected control tmux only",
            "attempt_output": "attempt-local candidate; canonical output forbidden during GPU execution",
            "publication": "terminalizer hard-links candidate after COMPLETED/0:0 and input TOCTOU validation",
            "technical_retry_is_scientific_repeat": False,
            "already_complete_run_is_execution_evidence": False,
        },
        "scope": {
            "primary_task_count": 13,
            "fixed_pair_hf_readout_geometry": True,
            "fresh_on_policy_pair_geometry": False,
            "production_adam_dppo_replay": False,
            "causal_training_effect_identified": False,
            "phase_transition_identified": False,
            "hysteresis_identified": False,
            "submission_performed": False,
        },
        "documentation": {
            "preregistration": preregistration,
            "readme": readme,
        },
        "implementation": {
            "plan_materializer": checkpoint_probe.source_identity(Path(__file__)),
            "checkpoint_probe": checkpoint_probe.source_identity(Path(checkpoint_probe.__file__)),
        },
        "checks": {
            "exact_smoke_four_bound": True,
            "exact_13_primary_tasks_frozen": True,
            "matched_bfloat16_step0_reference_required": True,
            "all_future_inputs_and_outputs_absent_before_plan": True,
            "immutable_launch_and_postrun_authorities_bound": True,
            "supplement_cannot_change_smoke_promotion": True,
            "this_tool_performed_no_submission": True,
        },
    }


def build_plan(**kwargs: Any) -> dict[str, Any]:
    payload = build_plan_payload(**kwargs)
    plan_id = canonical_json_sha256(payload)
    plan = {**payload, "plan_id": plan_id}
    plan["payload_without_self_hash_sha256"] = canonical_json_sha256(plan)
    return plan


def write_plan(output_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    output_root = output_root.expanduser().resolve()
    if output_root != ANALYSIS_ROOT / "plans":
        raise ValueError(f"Plan output root must be {ANALYSIS_ROOT / 'plans'}")
    path = output_root / str(plan["plan_id"]) / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json_bytes(plan)
    lock_path = output_root / ".materialize.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            if path.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace different plan: {path}")
            return file_identity(path)
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".plan.")
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
    return file_identity(path)


def validate_plan(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if stat.S_IMODE(resolved.stat().st_mode) & 0o222:
        raise ValueError("Checkpoint-kernel plan is writable")
    raw, observed = read_canonical_json(resolved)
    if observed.get("schema_version") != SCHEMA_VERSION or observed.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Checkpoint-kernel plan has the wrong schema or artifact type")
    payload = dict(observed)
    self_hash = payload.pop("payload_without_self_hash_sha256", None)
    if self_hash != canonical_json_sha256(payload):
        raise ValueError("Checkpoint-kernel plan self hash differs")
    inputs = observed.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Checkpoint-kernel plan lacks inputs")
    expected = build_plan(
        intent_path=Path(str(inputs["submission_intent"]["path"])),
        postrun_authority_path=Path(str(inputs["postrun_authority"]["path"])),
        promotion_authority_path=Path(str(inputs["promotion_authority"]["path"])),
        source_probe_dir=Path(str(inputs["source_probe"]["directory"])),
        pre_result_observation=observed["pre_result_observation"],
    )
    if raw != canonical_json_bytes(expected):
        raise ValueError("Checkpoint-kernel plan differs from deterministic replay")
    expected_path = ANALYSIS_ROOT / "plans" / str(observed["plan_id"]) / "plan.json"
    if resolved != expected_path:
        raise ValueError(f"Checkpoint-kernel plan is not content-addressed at {expected_path}")
    return file_identity(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--intent", type=Path, required=True)
    materialize.add_argument("--postrun-authority", type=Path, required=True)
    materialize.add_argument("--promotion-authority", type=Path, required=True)
    materialize.add_argument("--source-probe", type=Path, default=SOURCE_PROBE)
    materialize.add_argument("--output-root", type=Path, default=ANALYSIS_ROOT / "plans")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--plan", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        intent, _ = validate_self_hashed_artifact(
            args.intent,
            artifact_type="rsci_known_cost_boundary_submission_intent",
            study_id=STUDY_ID,
        )
        observation = capture_pre_result_observation(intent)
        plan = build_plan(
            intent_path=args.intent,
            postrun_authority_path=args.postrun_authority,
            promotion_authority_path=args.promotion_authority,
            source_probe_dir=args.source_probe,
            pre_result_observation=observation,
        )
        identity = write_plan(args.output_root, plan)
        validated = validate_plan(Path(str(identity["path"])))
        summary = {"command": "materialize", "plan_id": plan["plan_id"], "plan": validated}
    else:
        validated = validate_plan(args.plan)
        _, plan = read_canonical_json(args.plan)
        summary = {"command": "validate", "plan_id": plan["plan_id"], "plan": validated}
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
