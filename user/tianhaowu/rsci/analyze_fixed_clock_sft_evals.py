#!/usr/bin/env python3
"""Validate and analyze the fixed-clock SFT strict-evaluation grid."""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import math
import statistics
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

ANALYSIS_ID = "verifier_defect_fixed_clock_sft_analysis_v1"
EVAL_STUDY_ID = "verifier_defect_fixed_clock_sft_eval_v1"
TRAINING_STUDY_ID = "verifier_defect_fixed_clock_sft_v2"
SCHEMA_VERSION = 1
COMMON_STEP = 64
EXPECTED_TASKS = 82
EXPECTED_COMMON_TASKS = 55
EXPECTED_FINAL_TASKS = 27
EXPECTED_PROMPTS_PER_OPERATION = 200
EXPECTED_OPERATIONS = tuple(range(11, 46))
SELECTION_SEEDS = (20260805, 20260806, 20260807)
DOSE_LABELS = ("p0025", "p0050", "p0100")
DOSES = {
    "p0025": Fraction(1, 400),
    "p0050": Fraction(1, 200),
    "p0100": Fraction(1, 100),
}
BSG_ASSIGNMENTS = ("behavior", "shuffled", "global")
CONTRASTS = {
    "b_minus_s": ("behavior", "shuffled"),
    "s_minus_g": ("shuffled", "global"),
    "b_minus_g": ("behavior", "global"),
}
BANDS = {
    "retention_easy_op11_14": tuple(range(11, 15)),
    "discovered_bridge_op15_20": tuple(range(15, 21)),
    "retention_all_op11_20": tuple(range(11, 21)),
    "trained_strict_dead_op21_40": tuple(range(21, 41)),
    "unseen_extrapolation_op41_45": tuple(range(41, 46)),
    "all_op11_45": EXPECTED_OPERATIONS,
}
PRIMARY_BANDS = ("unseen_extrapolation_op41_45", "trained_strict_dead_op21_40")
RECIPIENT_NUMERIC_FEATURES = (
    "value_mismatch_count",
    "dependency_mismatch_count",
    "missing_nodes",
    "extra_nodes",
    "model_input_tokens",
    "assistant_tokens",
)
RECIPIENT_CATEGORICAL_FEATURES = ("answer_mismatch", "finish_reason")
DEFAULT_BOOTSTRAP_REPLICATES = 2_000
DEFAULT_BOOTSTRAP_SEED = 20260807
DEFAULT_EVAL_LAUNCH_MANIFEST = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-fixed-clock-sft-v1/eval_launch_manifest.json"
)


@dataclass(frozen=True)
class ValidatedResult:
    task: dict[str, Any]
    prompt_keys_by_op: dict[int, tuple[tuple[int, int, str, int], ...]]
    strict_by_op: dict[int, tuple[bool, ...]]
    answer_by_op: dict[int, tuple[bool, ...]]
    metrics: dict[str, Any]
    artifacts: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument(
        "--eval-launch-manifest",
        type=Path,
        default=DEFAULT_EVAL_LAUNCH_MANIFEST,
    )

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument(
        "--eval-launch-manifest",
        type=Path,
        default=DEFAULT_EVAL_LAUNCH_MANIFEST,
    )
    analyze.add_argument("--output", type=Path)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    configured = path.expanduser()
    if not configured.is_absolute():
        raise ValueError(f"Artifact path must be absolute: {configured}")
    resolved = configured.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return {
        "path": str(configured),
        "resolved_path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as handle:
        return tomllib.load(handle)


def write_json_once(path: Path, payload: object) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if not path.is_file() or path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"Refusing to replace a different deterministic analysis: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(encoded, encoding="utf-8")
    partial.replace(path)


def _require_int(value: object, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return value


def _arm_dimension(
    entry: dict[str, Any],
    task: dict[str, Any],
    training_arm: dict[str, Any],
    endpoint: str,
) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "logical_arm_label": entry["label"],
        "source_arm_label": entry.get("alias_of") or entry["label"],
        "is_alias": entry.get("alias_of") is not None,
        "selection_seed": entry["selection_seed"],
        "clock": entry["clock"],
        "dose": entry["dose"],
        "dose_label": entry["dose_label"],
        "assignment": entry["assignment"],
        "task_index": task["task_index"],
        "eval_id": task["eval_id"],
        "step": task["step"],
        "manifest_readout": task["readout"],
        "output_dir": task["output_dir"],
        "arm_contract_sha256": task.get("arm_contract_sha256"),
        "hard_recipient_rows": entry.get("hard_recipient_rows"),
        "raw_prefix_trajectories": entry.get("raw_prefix_trajectories"),
        "rows": entry["rows"],
        "source_max_steps": training_arm["max_steps"],
        "source_two_pass_steps": training_arm.get("two_pass_steps"),
        "source_schedule": training_arm["schedule"],
        "logical_two_pass_steps": None,
        "endpoint_provenance": "physical manifest readout",
        "selection_metadata": {
            key: value
            for key, value in entry.items()
            if key
            not in {
                "label",
                "alias_of",
                "dataset_path",
                "manifest_path",
                "parquet_sha256",
                "rows",
            }
        },
    }


def build_logical_grid(
    training_manifest: dict[str, Any],
    arm_index: dict[str, Any],
    eval_manifest: dict[str, Any],
) -> dict[str, Any]:
    if training_manifest.get("study_id") != TRAINING_STUDY_ID:
        raise ValueError("Training manifest has the wrong study identity")
    if eval_manifest.get("study_id") != EVAL_STUDY_ID:
        raise ValueError("Evaluation manifest has the wrong study identity")
    tasks = eval_manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != EXPECTED_TASKS:
        raise ValueError(f"Evaluation manifest must contain {EXPECTED_TASKS} physical tasks")
    if [task.get("task_index") for task in tasks] != list(range(EXPECTED_TASKS)):
        raise ValueError("Physical evaluation task indices are not ordered and contiguous")
    common_tasks = [task for task in tasks if task.get("readout") == "common"]
    final_tasks = [task for task in tasks if task.get("readout") == "final"]
    if (len(common_tasks), len(final_tasks)) != (EXPECTED_COMMON_TASKS, EXPECTED_FINAL_TASKS):
        raise ValueError("Physical common/final evaluation counts differ from 55/27")

    training_arms = training_manifest.get("arms")
    entries = arm_index.get("arms")
    if not isinstance(training_arms, list) or len(training_arms) != EXPECTED_COMMON_TASKS:
        raise ValueError("Training manifest must contain 55 canonical arms")
    if not isinstance(entries, list) or len(entries) != 64:
        raise ValueError("Arm index must contain 64 canonical-plus-alias entries")
    training_by_label = {arm["label"]: arm for arm in training_arms}
    entry_by_label = {entry["label"]: entry for entry in entries}
    if len(training_by_label) != len(training_arms) or len(entry_by_label) != len(entries):
        raise ValueError("Training or arm-index labels are duplicated")
    canonical_labels = {entry["label"] for entry in entries if entry.get("alias_of") is None}
    if canonical_labels != set(training_by_label):
        raise ValueError("Canonical arm-index labels differ from the training launch manifest")

    task_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for task in tasks:
        key = (task["arm_label"], task["readout"])
        if key in task_by_key:
            raise ValueError(f"Duplicate physical task for {key}")
        if task["arm_label"] not in training_by_label:
            raise ValueError(f"Task references an unknown canonical arm: {task['arm_label']}")
        task_by_key[key] = task

    common: list[dict[str, Any]] = []
    for entry in entries:
        canonical_label = entry.get("alias_of") or entry["label"]
        task = task_by_key.get((canonical_label, "common"))
        if task is None or task.get("step") != COMMON_STEP:
            raise ValueError(f"Logical arm {entry['label']} has no canonical step-64 task")
        common.append(
            _arm_dimension(
                entry,
                task,
                training_by_label[canonical_label],
                "common_step_64",
            )
        )

    distinct_final: list[dict[str, Any]] = []
    for task in final_tasks:
        entry = entry_by_label[task["arm_label"]]
        if entry.get("alias_of") is not None:
            raise ValueError("A physical final task unexpectedly targets an alias")
        arm = training_by_label[task["arm_label"]]
        if arm.get("readout_steps") != [COMMON_STEP, task["step"]] or task["step"] <= COMMON_STEP:
            raise ValueError(f"Final task differs from the declared final readout: {task['eval_id']}")
        distinct_final.append(_arm_dimension(entry, task, arm, "distinct_final"))

    common_lookup = {
        (record["selection_seed"], record["clock"], record["dose_label"], record["assignment"]): record
        for record in common
        if record["assignment"] != "clean"
    }
    final_lookup = {
        (record["selection_seed"], record["clock"], record["dose_label"], record["assignment"]): record
        for record in distinct_final
    }
    expected_common_dimensions = {
        (seed, clock, dose, assignment)
        for seed in SELECTION_SEEDS
        for clock in ("fixed_m", "fixed_raw")
        for dose in DOSE_LABELS
        for assignment in BSG_ASSIGNMENTS
    } | {(seed, "fixed_raw", dose, "iid") for seed in SELECTION_SEEDS for dose in DOSE_LABELS}
    if set(common_lookup) != expected_common_dimensions:
        raise ValueError("Logical common-step grid differs from the preregistered dimensions")
    expected_final_dimensions = {
        (seed, "fixed_raw", dose, assignment)
        for seed in SELECTION_SEEDS
        for dose in DOSE_LABELS[1:]
        for assignment in BSG_ASSIGNMENTS
    } | {(seed, "fixed_raw", dose, "iid") for seed in SELECTION_SEEDS for dose in DOSE_LABELS}
    if set(final_lookup) != expected_final_dimensions:
        raise ValueError("Distinct-final grid differs from the preregistered dimensions")

    two_pass = []
    for seed in SELECTION_SEEDS:
        for dose in DOSE_LABELS:
            for assignment in BSG_ASSIGNMENTS:
                source = (
                    common_lookup[(seed, "fixed_raw", dose, assignment)]
                    if dose == DOSE_LABELS[0]
                    else final_lookup[(seed, "fixed_raw", dose, assignment)]
                )
                two_pass.append(
                    {
                        **source,
                        "endpoint": "fixed_raw_two_pass_mixed",
                        "logical_two_pass_steps": source["step"],
                        "endpoint_provenance": (
                            "p0025 reuses the byte-identical fixed-M step-64 task; p0050/p0100 use their physical "
                            "distinct-final tasks"
                        ),
                    }
                )

    return {
        "training_by_label": training_by_label,
        "entry_by_label": entry_by_label,
        "task_by_eval_id": {task["eval_id"]: task for task in tasks},
        "endpoints": {
            "common_step_64": common,
            "distinct_final": distinct_final,
            "fixed_raw_two_pass_mixed": two_pass,
        },
    }


def validate_manifests(eval_launch_manifest: Path) -> dict[str, Any]:
    eval_launch_manifest = eval_launch_manifest.expanduser().resolve()
    import materialize_fixed_clock_sft_evals as eval_materializer
    import materialize_fixed_clock_sft_runs as training_materializer

    validated_eval = eval_materializer.validate_eval_launch_manifest(eval_launch_manifest)
    eval_manifest = validated_eval["manifest"]
    source_snapshot = Path(eval_manifest["source"]["snapshot_path"])
    validator_modules = {
        "materialize_fixed_clock_sft_evals.py": Path(eval_materializer.__file__).resolve(),
        "materialize_fixed_clock_sft_runs.py": Path(training_materializer.__file__).resolve(),
    }
    validator_identities = {}
    for name, live_path in validator_modules.items():
        pinned_path = source_snapshot / "user" / "tianhaowu" / "rsci" / name
        if file_sha256(live_path) != file_sha256(pinned_path):
            raise ValueError(f"Live {name} differs from the evaluator's pinned source snapshot")
        validator_identities[name] = {
            "live": file_identity(live_path),
            "pinned": file_identity(pinned_path),
        }
    import figure3_eval
    import solution_graph

    live_scorer_sha256 = file_sha256(Path(figure3_eval.__file__).resolve())
    live_solution_graph_sha256 = file_sha256(Path(solution_graph.__file__).resolve())
    if live_scorer_sha256 != eval_manifest["scorer"]["sha256"]:
        raise ValueError("Live figure3_eval.py differs from the evaluator's pinned scorer bytes")
    if live_solution_graph_sha256 != eval_manifest["solution_graph"]["sha256"]:
        raise ValueError("Live solution_graph.py differs from the evaluator's pinned scorer dependency")
    training_identity = eval_manifest["training_launch_manifest"]
    training_path = Path(training_identity["path"])
    validated_training = training_materializer.validate_launch_manifest(training_path)
    if validated_training["manifest_sha256"] != eval_manifest["training_launch_manifest_sha256"]:
        raise ValueError("Evaluation and training launch-manifest hashes differ")
    training_manifest = validated_training["manifest"]
    arm_index_path = Path(training_manifest["inputs"]["arm_index"]["path"])
    study_inputs = training_materializer.validate_study_inputs(
        arm_index_path,
        Path(training_manifest["inputs"]["base_model"]["path"]),
    )
    if study_inputs["arm_index"] != training_manifest["inputs"]["arm_index"]:
        raise ValueError("Validated arm-index identity differs from the training launch manifest")
    arm_index = read_json_object(arm_index_path)
    grid = build_logical_grid(training_manifest, arm_index, eval_manifest)
    return {
        "eval": validated_eval,
        "training": validated_training,
        "arm_index": arm_index,
        "arm_index_identity": study_inputs["arm_index"],
        "live_scorer": file_identity(Path(figure3_eval.__file__).resolve()),
        "live_solution_graph": file_identity(Path(solution_graph.__file__).resolve()),
        "validated_materializers": validator_identities,
        "grid": grid,
    }


def _scientific_eval_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(config)
    normalized["infer_config"] = "<transport>"
    normalized["eval"]["api_base_url"] = "<transport>"
    return normalized


def validate_runtime_config_semantics(
    base_config: dict[str, Any],
    runtime_config: dict[str, Any],
) -> None:
    from figure3_eval import normalized_inference_config

    if _scientific_eval_config(runtime_config) != _scientific_eval_config(base_config):
        raise ValueError("Runtime evaluation config changed a scientific field")
    if normalized_inference_config(runtime_config) != normalized_inference_config(base_config):
        raise ValueError("Runtime inference config changed a generation-semantic field")


def _assert_close(observed: object, expected: float, label: str) -> None:
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        raise ValueError(f"{label} is not numeric")
    value = float(observed)
    if not math.isfinite(value) or not math.isclose(value, expected, rel_tol=0.0, abs_tol=1e-15):
        raise ValueError(f"{label}={observed!r}, expected {expected!r}")


def _validate_metric_outcome(
    metrics: dict[str, Any],
    field: str,
    outcomes: dict[int, tuple[bool, ...]],
) -> None:
    section = metrics.get(field)
    if not isinstance(section, dict):
        raise ValueError(f"metrics.{field} is missing")
    total_correct = 0
    total_prompts = 0
    for operation in EXPECTED_OPERATIONS:
        values = outcomes[operation]
        correct = sum(values)
        total_correct += correct
        total_prompts += len(values)
        rate = correct / len(values)
        for kind in ("empirical", "unbiased"):
            try:
                observed = section["per_op"][str(operation)][kind]["pass@1"]
            except (KeyError, TypeError) as error:
                raise ValueError(f"metrics.{field}.per_op.{operation}.{kind}.pass@1 is missing") from error
            _assert_close(observed, rate, f"metrics.{field}.per_op.{operation}.{kind}.pass@1")
    total_rate = total_correct / total_prompts
    for kind in ("empirical", "unbiased"):
        try:
            observed = section["total"][kind]["pass@1"]
        except (KeyError, TypeError) as error:
            raise ValueError(f"metrics.{field}.total.{kind}.pass@1 is missing") from error
        _assert_close(observed, total_rate, f"metrics.{field}.total.{kind}.pass@1")


def validate_result(
    task: dict[str, Any],
    *,
    validated_eval: dict[str, Any],
    plan_cache: dict[Path, dict[str, Any]],
) -> ValidatedResult:
    from figure3_eval import (
        GENERATION_COMPLETION_NAME,
        GENERATION_MANIFEST_NAME,
        build_generation_manifest,
        canonical_generation_content,
        implementation_identity,
        load_config,
        load_rows,
        verify_generation_completion,
        verify_generation_manifest,
        verify_strict_results,
    )

    output_dir = Path(task["output_dir"])
    metrics_path = output_dir / "metrics.json"
    strict_path = output_dir / "strict_results.jsonl"
    generation_path = output_dir / "generations.jsonl"
    eval_config_path = output_dir / "configs" / "eval.toml"
    config_manifest_path = output_dir / "configs" / "manifest.json"
    base_config = read_toml(Path(task["eval_config"]["path"]))
    runtime_config = load_config(eval_config_path)
    validate_runtime_config_semantics(base_config, runtime_config)
    eval_config = runtime_config["eval"]
    expected_eval_fields = {
        "output_dir": str(output_dir),
        "model": task["model_path"],
        "operations": list(EXPECTED_OPERATIONS),
        "examples_per_operation": EXPECTED_PROMPTS_PER_OPERATION,
        "samples_per_prompt": 1,
        "pass_at": [1],
    }
    for field, expected in expected_eval_fields.items():
        if eval_config.get(field) != expected:
            raise ValueError(f"Runtime eval field {field}={eval_config.get(field)!r}, expected {expected!r}")

    config_manifest = read_json_object(config_manifest_path)
    eval_source = Path(str(config_manifest.get("eval_config_source", ""))).expanduser().resolve()
    inference_source = Path(str(config_manifest.get("inference_config_source", ""))).expanduser().resolve()
    if not eval_source.is_file() or file_sha256(eval_source) != config_manifest.get("eval_config_sha256"):
        raise ValueError(f"Snapshotted eval-config source identity differs: {config_manifest_path}")
    if not inference_source.is_file() or file_sha256(inference_source) != config_manifest.get(
        "inference_config_sha256"
    ):
        raise ValueError(f"Snapshotted inference-config source identity differs: {config_manifest_path}")
    if inference_source != Path(runtime_config["infer_config"]).expanduser().resolve():
        raise ValueError("Runtime inference source path differs from the eval config")
    if eval_source != eval_config_path.resolve() and read_toml(eval_source) != runtime_config:
        raise ValueError("Eval-config source and snapshot differ")
    import materialize_fixed_clock_sft_evals as eval_materializer

    runtime_manifest_path = eval_source.parent / "runtime_manifest.json"
    runtime_manifest = read_json_object(runtime_manifest_path)
    array_job_id = _require_int(runtime_manifest.get("array_job_id"), "runtime array job ID", minimum=1)
    task_index = _require_int(runtime_manifest.get("task_index"), "runtime task index", minimum=0)
    if task_index != task["task_index"] or runtime_manifest.get("eval_id") != task["eval_id"]:
        raise ValueError("Runtime manifest task identity differs from the evaluation task")
    expected_runtime_fields = {
        "schema_version": 1,
        "study_id": EVAL_STUDY_ID,
        "transport_port": eval_materializer.runtime_port(array_job_id, task_index),
        "eval_launch_manifest": file_identity(Path(validated_eval["manifest_path"])),
        "base_inference_config": task["inference_config"],
        "base_eval_config": task["eval_config"],
        "runtime_inference_config": file_identity(inference_source),
        "runtime_eval_config": file_identity(eval_source),
    }
    for field, expected in expected_runtime_fields.items():
        if runtime_manifest.get(field) != expected:
            raise ValueError(f"Runtime manifest {field} differs for {task['eval_id']}")

    submission_plan_identity = runtime_manifest.get("submission_plan")
    if not isinstance(submission_plan_identity, dict) or not isinstance(submission_plan_identity.get("path"), str):
        raise ValueError("Runtime manifest has no submission-plan identity")
    submission_plan_path = Path(submission_plan_identity["path"]).expanduser().resolve()
    if file_identity(submission_plan_path) != submission_plan_identity:
        raise ValueError("Runtime submission-plan bytes differ")
    if submission_plan_path not in plan_cache:
        plan_cache[submission_plan_path] = eval_materializer.validate_submission_plan(
            submission_plan_path,
            validated_eval,
        )
    validated_plan = plan_cache[submission_plan_path]
    if runtime_manifest.get("submission_plan_sha256") != validated_plan["plan_sha256"]:
        raise ValueError("Runtime submission-plan SHA-256 differs")
    plan_task = validated_plan["plan"]["tasks"][task_index]
    if runtime_manifest.get("checkpoint_inventory_sha256") != plan_task["checkpoint"]["inventory_sha256"]:
        raise ValueError("Runtime checkpoint inventory differs from the immutable submission plan")

    eval_root = Path(validated_eval["manifest"]["eval_root"])
    intent_path = eval_root / "submissions" / eval_materializer.SUBMISSION_INTENT_NAME
    receipt_path = eval_root / "submissions" / "jobs" / f"{array_job_id}.json"
    control_tmux = {
        "socket": eval_materializer.CONTROL_TMUX_SOCKET,
        "session": eval_materializer.CONTROL_TMUX_SESSION,
        "window": eval_materializer.CONTROL_TMUX_WINDOW,
    }
    plan = validated_plan["plan"]
    command = eval_materializer.submission_command(
        validated_eval["manifest"],
        plan_path=submission_plan_path,
        max_parallel=plan["max_parallel"],
        dependency=plan["dependency"],
    )
    expected_intent = eval_materializer.submission_intent(
        plan_sha256=validated_plan["plan_sha256"],
        plan_path=submission_plan_path,
        validated=validated_eval,
        command=command,
        control_tmux=control_tmux,
    )
    eval_materializer.validate_submission_intent(intent_path, expected_intent)
    eval_materializer._validate_receipt(
        receipt_path,
        plan_sha256=validated_plan["plan_sha256"],
        plan_path=submission_plan_path,
        validated=validated_eval,
        command=command,
        control_tmux=control_tmux,
    )
    from prime_rl.configs.inference import InferenceConfig
    from prime_rl.utils.config import cli

    expected_resolved_inference = cli(InferenceConfig, args=["@", str(inference_source)]).model_dump(
        exclude_none=True,
        mode="json",
    )
    resolved_inference_path = output_dir / "configs" / "inference.toml"
    if read_toml(resolved_inference_path) != expected_resolved_inference:
        raise ValueError("Resolved inference snapshot differs from its hash-bound runtime source")

    rows, hashes = load_rows(eval_config)
    if len(rows) != len(EXPECTED_OPERATIONS) * EXPECTED_PROMPTS_PER_OPERATION:
        raise ValueError(f"Evaluation row count differs for {task['eval_id']}")
    generation_manifest = build_generation_manifest(runtime_config, rows, hashes)
    verify_generation_manifest(output_dir / GENERATION_MANIFEST_NAME, generation_manifest)
    generation_digest, generation_records = canonical_generation_content(
        generation_path,
        rows,
        1,
    )
    generation_completion = verify_generation_completion(
        output_dir,
        generation_manifest,
        generation_digest,
        len(generation_records),
    )
    strict_records = verify_strict_results(strict_path, rows, generation_records)
    if len(strict_records) != len(rows):
        raise ValueError(f"Strict result count differs for {task['eval_id']}")

    prompt_keys_by_op: dict[int, list[tuple[int, int, str, int]]] = {operation: [] for operation in EXPECTED_OPERATIONS}
    strict_by_op: dict[int, list[bool]] = {operation: [] for operation in EXPECTED_OPERATIONS}
    answer_by_op: dict[int, list[bool]] = {operation: [] for operation in EXPECTED_OPERATIONS}
    for row, record in zip(rows, strict_records, strict=True):
        operation = int(row["op"])
        sample_rank = _require_int(record.get("sample_rank"), "strict sample_rank", minimum=0)
        key = (operation, int(row["__idx"]), str(row["id"]), sample_rank)
        if sample_rank != 0 or int(record.get("op", -1)) != operation or str(record.get("id", "")) != str(row["id"]):
            raise ValueError(f"Strict row key differs from held-out prompt: {key}")
        perfect = record.get("perfect")
        answer_correct = record.get("answer_correct")
        if not isinstance(perfect, bool) or not isinstance(answer_correct, bool):
            raise ValueError(f"Strict outcomes are not booleans for {key}")
        prompt_keys_by_op[operation].append(key)
        strict_by_op[operation].append(perfect)
        answer_by_op[operation].append(answer_correct)
    for operation in EXPECTED_OPERATIONS:
        keys = prompt_keys_by_op[operation]
        if len(keys) != EXPECTED_PROMPTS_PER_OPERATION or len(set(keys)) != len(keys):
            raise ValueError(f"OP{operation} does not contain 200 unique paired prompts")

    metrics = read_json_object(metrics_path)
    expected_metric_fields = {
        "model": task["model_path"],
        "operations": list(EXPECTED_OPERATIONS),
        "num_prompts": len(rows),
        "samples_per_prompt": 1,
        "num_generations": len(rows),
    }
    for field, expected in expected_metric_fields.items():
        if metrics.get(field) != expected:
            raise ValueError(f"metrics.{field}={metrics.get(field)!r}, expected {expected!r}")
    dataset_source = (
        {"data_dir": eval_config["data_dir"]}
        if "data_dir" in eval_config
        else {"data_sources": eval_config["data_sources"]}
    )
    for field, expected in dataset_source.items():
        if metrics.get(field) != expected:
            raise ValueError(f"metrics.{field} differs from the runtime evaluation config")
    if metrics.get("dataset_sha256_by_op") != hashes:
        raise ValueError("Metrics dataset hashes differ from the validated held-out files")
    expected_sampling = {
        "temperature": eval_config["temperature"],
        "top_p": eval_config["top_p"],
        "top_k": eval_config["top_k"],
        "max_tokens": eval_config["max_tokens"],
        "stop": eval_config["stop"],
        "skip_special_tokens": eval_config["skip_special_tokens"],
        "request_seed": eval_config.get("request_seed"),
    }
    if metrics.get("sampling") != expected_sampling:
        raise ValueError("Metrics sampling contract differs from the runtime evaluation config")
    _validate_metric_outcome(metrics, "strict_graph", {key: tuple(value) for key, value in strict_by_op.items()})
    _validate_metric_outcome(metrics, "answer_only", {key: tuple(value) for key, value in answer_by_op.items()})
    expected_generation_provenance = {
        **generation_completion,
        "generation_manifest": GENERATION_MANIFEST_NAME,
        "generation_completion": GENERATION_COMPLETION_NAME,
    }
    if metrics.get("generation_provenance") != expected_generation_provenance:
        raise ValueError("Metrics generation provenance differs from validated completion")
    scorer_identity = implementation_identity()
    expected_strict_provenance = {
        "implementation_sha256": scorer_identity,
        "strict_results_sha256": file_sha256(strict_path),
        "num_results": len(strict_records),
    }
    if metrics.get("strict_scoring_provenance") != expected_strict_provenance:
        raise ValueError("Metrics strict-scoring provenance differs")
    if metrics.get("implementation_sha256") != scorer_identity:
        raise ValueError("Metrics scorer implementation identity differs")

    artifacts = {
        "metrics": file_identity(metrics_path),
        "strict_results": file_identity(strict_path),
        "generation_manifest": file_identity(output_dir / GENERATION_MANIFEST_NAME),
        "generation_completion": file_identity(output_dir / GENERATION_COMPLETION_NAME),
        "config_manifest": file_identity(config_manifest_path),
        "runtime_manifest": file_identity(runtime_manifest_path),
        "submission_plan": file_identity(submission_plan_path),
        "submission_intent": file_identity(intent_path),
        "submission_receipt": file_identity(receipt_path),
        "checkpoint_inventory_sha256": plan_task["checkpoint"]["inventory_sha256"],
        "array_job_id": array_job_id,
        "canonical_generation_sha256": generation_digest,
    }
    return ValidatedResult(
        task=task,
        prompt_keys_by_op={key: tuple(value) for key, value in prompt_keys_by_op.items()},
        strict_by_op={key: tuple(value) for key, value in strict_by_op.items()},
        answer_by_op={key: tuple(value) for key, value in answer_by_op.items()},
        metrics=metrics,
        artifacts=artifacts,
    )


def load_results(
    tasks: list[dict[str, Any]],
    *,
    validated_eval: dict[str, Any],
    require_complete: bool,
) -> tuple[dict[str, ValidatedResult], list[str]]:
    results: dict[str, ValidatedResult] = {}
    missing = []
    reference_keys: dict[int, tuple[tuple[int, int, str, int], ...]] | None = None
    plan_cache: dict[Path, dict[str, Any]] = {}
    for task in tasks:
        metrics_path = Path(task["output_dir"]) / "metrics.json"
        if not metrics_path.is_file():
            missing.append(task["eval_id"])
            continue
        result = validate_result(task, validated_eval=validated_eval, plan_cache=plan_cache)
        if reference_keys is None:
            reference_keys = result.prompt_keys_by_op
        elif result.prompt_keys_by_op != reference_keys:
            raise ValueError(f"Held-out prompt keys differ for {task['eval_id']}")
        results[task["eval_id"]] = result
    if require_complete and missing:
        raise ValueError(f"Evaluation grid is incomplete: {len(missing)} missing; first={missing[:5]}")
    return results, missing


def _outcome_summary(outcomes: dict[int, tuple[bool, ...]]) -> dict[str, Any]:
    per_operation = {
        str(operation): sum(outcomes[operation]) / len(outcomes[operation]) for operation in EXPECTED_OPERATIONS
    }
    bands = {}
    for label, operations in BANDS.items():
        correct = sum(sum(outcomes[operation]) for operation in operations)
        prompts = sum(len(outcomes[operation]) for operation in operations)
        macro = sum(per_operation[str(operation)] for operation in operations) / len(operations)
        micro = correct / prompts
        if not math.isclose(macro, micro, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError(f"Band macro/micro differ despite balanced prompts: {label}")
        bands[label] = {
            "operations": list(operations),
            "n_operations": len(operations),
            "prompts_per_operation": EXPECTED_PROMPTS_PER_OPERATION,
            "n_prompts": prompts,
            "correct": correct,
            "macro_pass1": macro,
            "micro_pass1": micro,
        }
    return {"per_operation_pass1": per_operation, "bands": bands}


def summarize_result(result: ValidatedResult) -> dict[str, Any]:
    return {
        "task_index": result.task["task_index"],
        "eval_id": result.task["eval_id"],
        "arm_label": result.task["arm_label"],
        "step": result.task["step"],
        "readout": result.task["readout"],
        "strict": _outcome_summary(result.strict_by_op),
        "answer_only": _outcome_summary(result.answer_by_op),
        "artifacts": result.artifacts,
    }


def _paired_differences(
    left: ValidatedResult,
    right: ValidatedResult,
    *,
    outcome: str,
) -> dict[int, tuple[int, ...]]:
    if left.prompt_keys_by_op != right.prompt_keys_by_op:
        raise ValueError(f"Paired prompts differ: {left.task['eval_id']} vs {right.task['eval_id']}")
    left_values = left.strict_by_op if outcome == "strict" else left.answer_by_op
    right_values = right.strict_by_op if outcome == "strict" else right.answer_by_op
    return {
        operation: tuple(int(a) - int(b) for a, b in zip(left_values[operation], right_values[operation], strict=True))
        for operation in EXPECTED_OPERATIONS
    }


def _difference_summary(differences: dict[int, tuple[int, ...]]) -> dict[str, Any]:
    per_operation = {
        str(operation): sum(differences[operation]) / len(differences[operation]) for operation in EXPECTED_OPERATIONS
    }
    bands = {}
    for label, operations in BANDS.items():
        macro = sum(per_operation[str(operation)] for operation in operations) / len(operations)
        total = sum(sum(differences[operation]) for operation in operations)
        prompts = sum(len(differences[operation]) for operation in operations)
        micro = total / prompts
        if not math.isclose(macro, micro, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError(f"Paired band macro/micro differ despite balanced prompts: {label}")
        bands[label] = {
            "operations": list(operations),
            "n_paired_prompts": prompts,
            "macro_difference": macro,
            "micro_difference": micro,
        }
    return {"per_operation_difference": per_operation, "bands": bands}


def _endpoint_lookup(records: list[dict[str, Any]]) -> dict[tuple[int, str, str, str], dict[str, Any]]:
    lookup = {
        (record["selection_seed"], record["clock"], record["dose_label"], record["assignment"]): record
        for record in records
        if record["assignment"] != "clean"
    }
    if len(lookup) != sum(record["assignment"] != "clean" for record in records):
        raise ValueError("Logical endpoint contains duplicate dimensions")
    return lookup


def paired_contrast_cells(
    endpoint: str,
    records: list[dict[str, Any]],
    results: dict[str, ValidatedResult],
) -> list[dict[str, Any]]:
    lookup = _endpoint_lookup(records)
    cells = sorted(
        {
            (seed, clock, dose)
            for seed, clock, dose, assignment in lookup
            if assignment in BSG_ASSIGNMENTS
            and all((seed, clock, dose, required) in lookup for required in BSG_ASSIGNMENTS)
        }
    )
    output = []
    for seed, clock, dose in cells:
        arms = {assignment: lookup[(seed, clock, dose, assignment)] for assignment in BSG_ASSIGNMENTS}
        if endpoint == "distinct_final" and dose == DOSE_LABELS[0]:
            raise ValueError("Distinct-final endpoint must not synthesize minimum-dose B/S/G")
        steps = {record["step"] for record in arms.values()}
        if len(steps) != 1:
            raise ValueError(f"B/S/G steps differ within {endpoint}/{seed}/{clock}/{dose}: {steps}")
        cell_contrasts = {}
        strict_differences = {}
        for name, (left_assignment, right_assignment) in CONTRASTS.items():
            left_record = arms[left_assignment]
            right_record = arms[right_assignment]
            left_result = results[left_record["eval_id"]]
            right_result = results[right_record["eval_id"]]
            strict = _paired_differences(left_result, right_result, outcome="strict")
            answer = _paired_differences(left_result, right_result, outcome="answer")
            strict_differences[name] = strict
            cell_contrasts[name] = {
                "definition": f"{left_assignment} minus {right_assignment}",
                "left": left_record,
                "right": right_record,
                "strict": _difference_summary(strict),
                "answer_only": _difference_summary(answer),
            }
        for operation in EXPECTED_OPERATIONS:
            for b_minus_s, s_minus_g, b_minus_g in zip(
                strict_differences["b_minus_s"][operation],
                strict_differences["s_minus_g"][operation],
                strict_differences["b_minus_g"][operation],
                strict=True,
            ):
                if b_minus_g != b_minus_s + s_minus_g:
                    raise RuntimeError("Paired B-G != B-S + S-G")
        output.append(
            {
                "endpoint": endpoint,
                "selection_seed": seed,
                "clock": clock,
                "dose": arms["behavior"]["dose"],
                "dose_label": dose,
                "step": steps.pop(),
                "contrasts": cell_contrasts,
            }
        )
    return output


def _bootstrap_operation_seed(base_seed: int, operation: int) -> int:
    digest = hashlib.sha256(f"rsci-fixed-clock-bootstrap-v1\0{base_seed}\0{operation}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def bootstrap_band_values(
    results: dict[str, ValidatedResult],
    *,
    replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, dict[str, np.ndarray]]:
    _require_int(replicates, "bootstrap replicates", minimum=1)
    task_ids = sorted(results, key=lambda eval_id: results[eval_id].task["task_index"])
    values = {eval_id: {band: np.zeros(replicates, dtype=np.float64) for band in BANDS} for eval_id in task_ids}
    for operation in EXPECTED_OPERATIONS:
        matrix = np.asarray(
            [results[eval_id].strict_by_op[operation] for eval_id in task_ids],
            dtype=np.int16,
        )
        if matrix.shape != (len(task_ids), EXPECTED_PROMPTS_PER_OPERATION):
            raise ValueError(f"Bootstrap outcome matrix has an invalid shape for OP{operation}: {matrix.shape}")
        rng = np.random.Generator(np.random.PCG64(_bootstrap_operation_seed(seed, operation)))
        counts = rng.multinomial(
            EXPECTED_PROMPTS_PER_OPERATION,
            np.full(EXPECTED_PROMPTS_PER_OPERATION, 1.0 / EXPECTED_PROMPTS_PER_OPERATION),
            size=replicates,
        ).astype(np.int16)
        operation_rates = (counts @ matrix.T).astype(np.float64) / EXPECTED_PROMPTS_PER_OPERATION
        for band, operations in BANDS.items():
            if operation not in operations:
                continue
            scale = 1.0 / len(operations)
            for index, eval_id in enumerate(task_ids):
                values[eval_id][band] += operation_rates[:, index] * scale
    return values


def _percentile_interval(values: np.ndarray) -> dict[str, float]:
    lower, median, upper = np.quantile(values, (0.025, 0.5, 0.975), method="linear")
    return {"lower_2_5": float(lower), "median": float(median), "upper_97_5": float(upper)}


def attach_bootstrap_to_cells(
    cells: list[dict[str, Any]],
    bootstrap: dict[str, dict[str, np.ndarray]],
) -> None:
    for cell in cells:
        for contrast in cell["contrasts"].values():
            left = contrast["left"]["eval_id"]
            right = contrast["right"]["eval_id"]
            for band in BANDS:
                distribution = bootstrap[left][band] - bootstrap[right][band]
                contrast["strict"]["bands"][band]["paired_prompt_bootstrap_95"] = _percentile_interval(distribution)


def aggregate_contrast_cells(
    cells: list[dict[str, Any]],
    bootstrap: dict[str, dict[str, np.ndarray]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for cell in cells:
        key = (cell["endpoint"], cell["clock"], cell["dose_label"])
        grouped.setdefault(key, []).append(cell)
    output = []
    for (endpoint, clock, dose), group in sorted(grouped.items()):
        group.sort(key=lambda cell: cell["selection_seed"])
        if [cell["selection_seed"] for cell in group] != list(SELECTION_SEEDS):
            raise ValueError(f"Aggregate contrast cell lacks all three seeds: {endpoint}/{clock}/{dose}")
        contrast_output = {}
        for contrast_name in CONTRASTS:
            band_output = {}
            for band in BANDS:
                seed_estimates = [
                    cell["contrasts"][contrast_name]["strict"]["bands"][band]["macro_difference"] for cell in group
                ]
                bootstrap_distributions = []
                for cell in group:
                    contrast = cell["contrasts"][contrast_name]
                    left = contrast["left"]["eval_id"]
                    right = contrast["right"]["eval_id"]
                    bootstrap_distributions.append(bootstrap[left][band] - bootstrap[right][band])
                aggregate_distribution = np.mean(np.stack(bootstrap_distributions), axis=0)
                band_output[band] = {
                    "seed_estimates": {
                        str(cell["selection_seed"]): estimate
                        for cell, estimate in zip(group, seed_estimates, strict=True)
                    },
                    "mean_across_three_seeds": statistics.fmean(seed_estimates),
                    "sample_sd_across_three_seeds": statistics.stdev(seed_estimates),
                    "range_across_three_seeds": [min(seed_estimates), max(seed_estimates)],
                    "paired_prompt_bootstrap_95_of_observed_seed_mean": _percentile_interval(aggregate_distribution),
                }
            contrast_output[contrast_name] = band_output
        output.append(
            {
                "endpoint": endpoint,
                "clock": clock,
                "dose_label": dose,
                "dose": group[0]["dose"],
                "selection_seeds": list(SELECTION_SEEDS),
                "contrasts": contrast_output,
            }
        )
    return output


def iid_channel_analysis(
    grid: dict[str, Any],
    results: dict[str, ValidatedResult],
    bootstrap: dict[str, dict[str, np.ndarray]],
) -> dict[str, Any]:
    common_records = grid["endpoints"]["common_step_64"]
    clean_records = [record for record in common_records if record["assignment"] == "clean"]
    if len(clean_records) != 1:
        raise ValueError(f"Expected one shared C0 record, found {len(clean_records)}")
    clean = clean_records[0]
    if clean["step"] != COMMON_STEP:
        raise ValueError("Shared C0 is not evaluated at the common step")
    clean_result = results[clean["eval_id"]]

    iid_records = sorted(
        (record for record in common_records if record["assignment"] == "iid"),
        key=lambda record: (record["selection_seed"], record["dose_label"]),
    )
    expected_dimensions = {(seed, dose) for seed in SELECTION_SEEDS for dose in DOSE_LABELS}
    observed_dimensions = {(record["selection_seed"], record["dose_label"]) for record in iid_records}
    if len(iid_records) != len(expected_dimensions) or observed_dimensions != expected_dimensions:
        raise ValueError("Common-step I arms differ from the three-seed, three-dose contract")

    cells = []
    for record in iid_records:
        iid_result = results[record["eval_id"]]
        metadata = record["selection_metadata"]
        eligible_rows = _require_int(metadata.get("iid_eligible_rows"), "I eligible rows", minimum=1)
        recipient_rows = _require_int(record["hard_recipient_rows"], "I recipient rows", minimum=1)
        realized_rate = metadata.get("iid_realized_rate")
        _assert_close(realized_rate, recipient_rows / eligible_rows, "I realized recipient rate")
        candidate_overlap = _require_int(metadata.get("candidate_overlap"), "I candidate overlap", minimum=0)
        if candidate_overlap > recipient_rows:
            raise ValueError(f"I candidate overlap exceeds recipient rows: {record['logical_arm_label']}")
        strict = _difference_summary(_paired_differences(iid_result, clean_result, outcome="strict"))
        answer = _difference_summary(_paired_differences(iid_result, clean_result, outcome="answer"))
        for band in BANDS:
            strict["bands"][band]["paired_prompt_bootstrap_95"] = _percentile_interval(
                bootstrap[record["eval_id"]][band] - bootstrap[clean["eval_id"]][band]
            )
        cells.append(
            {
                "endpoint": "common_step_64",
                "selection_seed": record["selection_seed"],
                "dose": record["dose"],
                "dose_label": record["dose_label"],
                "step": COMMON_STEP,
                "iid": record,
                "shared_clean": clean,
                "iid_selection_diagnostics": {
                    "raw_prefix_trajectories": record["raw_prefix_trajectories"],
                    "eligible_strict_negative_rows": eligible_rows,
                    "realized_recipient_rows": recipient_rows,
                    "realized_recipient_rate": float(realized_rate),
                    "candidate_overlap_rows": candidate_overlap,
                    "candidate_overlap_fraction": candidate_overlap / recipient_rows,
                },
                "strict_iid_minus_clean": strict,
                "answer_only_iid_minus_clean": answer,
            }
        )

    dose_aggregates = []
    for dose in DOSE_LABELS:
        dose_cells = [cell for cell in cells if cell["dose_label"] == dose]
        dose_cells.sort(key=lambda cell: cell["selection_seed"])
        if [cell["selection_seed"] for cell in dose_cells] != list(SELECTION_SEEDS):
            raise ValueError(f"I-C0 dose {dose} lacks all three I selection seeds")
        bands = {}
        for band in BANDS:
            seed_estimates = [cell["strict_iid_minus_clean"]["bands"][band]["macro_difference"] for cell in dose_cells]
            mean_iid_bootstrap = np.mean(
                np.stack([bootstrap[cell["iid"]["eval_id"]][band] for cell in dose_cells]),
                axis=0,
            )
            mean_effect_bootstrap = mean_iid_bootstrap - bootstrap[clean["eval_id"]][band]
            bands[band] = {
                "iid_selection_seed_estimates_conditional_on_shared_clean": dict(
                    zip(map(str, SELECTION_SEEDS), seed_estimates, strict=True)
                ),
                "mean_across_three_iid_selections_minus_shared_clean": statistics.fmean(seed_estimates),
                "sample_sd_across_iid_selections_conditional_on_shared_clean": statistics.stdev(seed_estimates),
                "range_across_iid_selections_conditional_on_shared_clean": [min(seed_estimates), max(seed_estimates)],
                "paired_prompt_bootstrap_95_of_mean_iid_minus_shared_clean": _percentile_interval(
                    mean_effect_bootstrap
                ),
                "training_run_treatment_effect_test": None,
            }
        dose_aggregates.append(
            {
                "dose_label": dose,
                "dose": dose_cells[0]["dose"],
                "iid_selection_seeds": list(SELECTION_SEEDS),
                "shared_clean_training_runs": 1,
                "bands": bands,
            }
        )

    seed_dose_trends = []
    trend_inputs: dict[str, list[tuple[int, dict[str, Any], np.ndarray]]] = {band: [] for band in BANDS}
    for seed in SELECTION_SEEDS:
        seed_cells = [cell for cell in cells if cell["selection_seed"] == seed]
        seed_cells.sort(key=lambda cell: DOSE_LABELS.index(cell["dose_label"]))
        if [cell["dose_label"] for cell in seed_cells] != list(DOSE_LABELS):
            raise ValueError(f"I-C0 seed {seed} lacks the complete dose grid")
        for band in BANDS:
            values = [cell["strict_iid_minus_clean"]["bands"][band]["macro_difference"] for cell in seed_cells]
            slope_bootstrap = (
                bootstrap[seed_cells[2]["iid"]["eval_id"]][band] - bootstrap[seed_cells[0]["iid"]["eval_id"]][band]
            ) / 2.0
            trend = _trend(values)
            seed_dose_trends.append(
                {
                    "selection_seed": seed,
                    "band": band,
                    "iid_minus_shared_clean_trend": trend,
                    "paired_prompt_bootstrap_95_of_slope": _percentile_interval(slope_bootstrap),
                    "note": "C0 cancels from the within-seed dose slope but remains a single shared control.",
                }
            )
            trend_inputs[band].append((seed, trend, slope_bootstrap))

    dose_trends_across_selections = []
    for band, entries in trend_inputs.items():
        entries.sort(key=lambda entry: entry[0])
        slopes = [entry[1]["centered_log2_dose_slope_per_doubling"] for entry in entries]
        dose_trends_across_selections.append(
            {
                "band": band,
                "iid_selection_seed_slopes": dict(zip(map(str, SELECTION_SEEDS), slopes, strict=True)),
                "mean_slope_across_iid_selections": statistics.fmean(slopes),
                "sample_sd_across_iid_selections": statistics.stdev(slopes),
                "paired_prompt_bootstrap_95_of_observed_mean_slope": _percentile_interval(
                    np.mean(np.stack([entry[2] for entry in entries]), axis=0)
                ),
                "training_run_treatment_effect_test": None,
            }
        )

    final_lookup = _endpoint_lookup(grid["endpoints"]["distinct_final"])
    distinct_final_trends = []
    for seed in SELECTION_SEEDS:
        final_records = [final_lookup[(seed, "fixed_raw", dose, "iid")] for dose in DOSE_LABELS]
        for band in BANDS:
            distinct_final_trends.append(
                {
                    "selection_seed": seed,
                    "band": band,
                    "steps_by_dose": {
                        dose: record["step"] for dose, record in zip(DOSE_LABELS, final_records, strict=True)
                    },
                    "iid_absolute_strict_trend": _trend(
                        [_band_value(record, results, band) for record in final_records]
                    ),
                    "interpretation": (
                        "descriptive only: I dose, rows, optimizer steps, and example exposure differ; "
                        "the sole C0 has no matched distinct-final readout"
                    ),
                }
            )

    return {
        "contrast_definition": "I minus the single shared C0; positive means the iid arm performs better",
        "common_step_64_cells": cells,
        "common_step_64_by_dose": dose_aggregates,
        "common_step_64_seed_dose_trends": seed_dose_trends,
        "common_step_64_dose_trends_across_iid_selections": dose_trends_across_selections,
        "distinct_final_iid_dose_trends": distinct_final_trends,
        "decision_guard": (
            "The three I selection seeds share one C0 training run. Their dispersion measures I-selection "
            "variation conditional on that model, not treatment-effect uncertainty; no seed-level sign-flip or "
            "Holm test is reported for I-C0."
        ),
    }


def _band_value(record: dict[str, Any], results: dict[str, ValidatedResult], band: str) -> float:
    return _outcome_summary(results[record["eval_id"]].strict_by_op)["bands"][band]["macro_pass1"]


def _trend(values: list[float]) -> dict[str, Any]:
    if len(values) != 3:
        raise ValueError("Three-dose trend requires exactly three ordered values")
    low, middle, high = values
    adjacent = [middle - low, high - middle]
    if adjacent[0] > 0 and adjacent[1] > 0:
        monotonic = "increasing"
    elif adjacent[0] < 0 and adjacent[1] < 0:
        monotonic = "decreasing"
    elif adjacent == [0.0, 0.0]:
        monotonic = "flat"
    else:
        monotonic = "mixed_or_tied"
    return {
        "values_by_dose": dict(zip(DOSE_LABELS, values, strict=True)),
        "p0050_minus_p0025": adjacent[0],
        "p0100_minus_p0050": adjacent[1],
        "p0100_minus_p0025": high - low,
        "centered_log2_dose_slope_per_doubling": (high - low) / 2.0,
        "second_difference_curvature": low - 2.0 * middle + high,
        "monotonic_order": monotonic,
    }


def exact_sign_flip_p(values: list[float]) -> float:
    if not values:
        raise ValueError("Sign-flip test requires observations")
    observed = abs(statistics.fmean(values))
    tolerance = 1e-15
    extreme = 0
    total = 0
    for signs in itertools.product((-1.0, 1.0), repeat=len(values)):
        statistic = abs(statistics.fmean(sign * value for sign, value in zip(signs, values, strict=True)))
        extreme += statistic >= observed - tolerance
        total += 1
    return extreme / total


def _holm_adjust(p_values: list[float]) -> list[float]:
    order = sorted(range(len(p_values)), key=p_values.__getitem__)
    adjusted = [0.0] * len(p_values)
    running = 0.0
    count = len(p_values)
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (count - rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def _recipient_feature_table(
    parquet_path: Path,
    *,
    expected_rows: int,
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    import pyarrow.parquet as pq

    columns = (
        "source_kind",
        "candidate",
        "strict_correct",
        "answer_correct",
        *RECIPIENT_NUMERIC_FEATURES,
        *RECIPIENT_CATEGORICAL_FEATURES,
    )
    table = pq.read_table(parquet_path, columns=list(columns))
    values = {column: table[column].to_pylist() for column in columns}
    indices = [index for index, source in enumerate(values["source_kind"]) if source == "defect_recipient"]
    if len(indices) != expected_rows:
        raise ValueError(f"Parquet defect-recipient count differs: {parquet_path}")
    if any(
        values["candidate"][index] is not True
        or values["strict_correct"][index] is not False
        or values["answer_correct"][index] is not True
        for index in indices
    ):
        raise ValueError(f"Behavior recipients do not satisfy A=answer-correct/strict-wrong: {parquet_path}")
    selected = {
        feature: [values[feature][index] for index in indices]
        for feature in (*RECIPIENT_NUMERIC_FEATURES, *RECIPIENT_CATEGORICAL_FEATURES)
    }
    numeric = {}
    for feature in RECIPIENT_NUMERIC_FEATURES:
        array = np.asarray(selected[feature], dtype=np.float64)
        quantiles = np.quantile(array, (0.0, 0.25, 0.5, 0.75, 1.0), method="linear")
        numeric[feature] = {
            "mean": float(np.mean(array)),
            "sample_sd": float(np.std(array, ddof=1)),
            "min": float(quantiles[0]),
            "q25": float(quantiles[1]),
            "median": float(quantiles[2]),
            "q75": float(quantiles[3]),
            "max": float(quantiles[4]),
        }
    categorical = {}
    for feature in RECIPIENT_CATEGORICAL_FEATURES:
        counts: dict[str, int] = {}
        for value in selected[feature]:
            label = json.dumps(value, sort_keys=True)
            counts[label] = counts.get(label, 0) + 1
        categorical[feature] = {
            "counts": dict(sorted(counts.items())),
            "fractions": {label: count / expected_rows for label, count in sorted(counts.items())},
        }
    return {"rows": expected_rows, "numeric": numeric, "categorical": categorical}, selected


def _empirical_ks_distance(left: list[Any], right: list[Any]) -> float:
    left_array = np.sort(np.asarray(left, dtype=np.float64))
    right_array = np.sort(np.asarray(right, dtype=np.float64))
    support = np.unique(np.concatenate((left_array, right_array)))
    left_cdf = np.searchsorted(left_array, support, side="right") / len(left_array)
    right_cdf = np.searchsorted(right_array, support, side="right") / len(right_array)
    return float(np.max(np.abs(left_cdf - right_cdf)))


def _recipient_feature_distances(
    left: dict[str, list[Any]],
    right: dict[str, list[Any]],
) -> dict[str, Any]:
    numeric = {}
    for feature in RECIPIENT_NUMERIC_FEATURES:
        left_array = np.asarray(left[feature], dtype=np.float64)
        right_array = np.asarray(right[feature], dtype=np.float64)
        numeric[feature] = {
            "mean_difference_right_minus_left": float(np.mean(right_array) - np.mean(left_array)),
            "empirical_ks_distance": _empirical_ks_distance(left[feature], right[feature]),
        }
    categorical = {}
    for feature in RECIPIENT_CATEGORICAL_FEATURES:
        left_counts: dict[str, int] = {}
        right_counts: dict[str, int] = {}
        for value in left[feature]:
            label = json.dumps(value, sort_keys=True)
            left_counts[label] = left_counts.get(label, 0) + 1
        for value in right[feature]:
            label = json.dumps(value, sort_keys=True)
            right_counts[label] = right_counts.get(label, 0) + 1
        labels = set(left_counts) | set(right_counts)
        categorical[feature] = {
            "total_variation_distance": 0.5
            * sum(
                abs(left_counts.get(label, 0) / len(left[feature]) - right_counts.get(label, 0) / len(right[feature]))
                for label in labels
            )
        }
    return {"numeric": numeric, "categorical": categorical}


def _recipient_allocation_table(
    parquet_path: Path,
    *,
    expected_rows: int,
    expected_assignment: str,
) -> tuple[dict[str, Any], tuple[tuple[int, int, str, int], ...]]:
    import pyarrow.parquet as pq

    columns = (
        "op",
        "prompt_index",
        "prompt_id",
        "source_kind",
        "assignment",
        "candidate",
        "group_extra_positive_count",
    )
    table = pq.read_table(parquet_path, columns=list(columns))
    rows = [row for row in table.to_pylist() if row["source_kind"] == "defect_recipient"]
    if len(rows) != expected_rows:
        raise ValueError(f"Parquet hard-recipient count differs: {parquet_path}")
    if any(row["assignment"] != expected_assignment for row in rows):
        raise ValueError(f"Parquet recipient assignment differs from {expected_assignment}: {parquet_path}")

    groups: dict[tuple[int, int, str], list[int]] = defaultdict(list)
    operation_counts: Counter[int] = Counter()
    candidate_overlap = 0
    for row in rows:
        operation = _require_int(row["op"], "recipient operation")
        prompt_index = _require_int(row["prompt_index"], "recipient prompt index", minimum=0)
        prompt_id = row["prompt_id"]
        extra_count = _require_int(row["group_extra_positive_count"], "group extra-positive count", minimum=1)
        candidate = row["candidate"]
        if operation not in range(21, 41) or not isinstance(prompt_id, str) or not prompt_id:
            raise ValueError(f"Invalid hard-recipient prompt identity in {parquet_path}")
        if not isinstance(candidate, bool):
            raise ValueError(f"Recipient candidate flag is not boolean in {parquet_path}")
        groups[(operation, prompt_index, prompt_id)].append(extra_count)
        operation_counts[operation] += 1
        candidate_overlap += int(candidate)

    group_records = []
    for (operation, prompt_index, prompt_id), declared_counts in groups.items():
        recipient_count = len(declared_counts)
        if set(declared_counts) != {recipient_count}:
            raise ValueError(
                f"Per-row extra-positive count differs from the recipient count for "
                f"OP{operation}/prompt {prompt_index} in {parquet_path}"
            )
        group_records.append((operation, prompt_index, prompt_id, recipient_count))
    group_records.sort()
    group_histogram = Counter(record[3] for record in group_records)
    operation_counts_complete = {str(operation): operation_counts[operation] for operation in range(21, 41)}
    return (
        {
            "recipient_rows": expected_rows,
            "candidate_overlap_rows": candidate_overlap,
            "candidate_overlap_fraction": candidate_overlap / expected_rows,
            "counts_by_operation": operation_counts_complete,
            "shares_by_operation": {
                operation: count / expected_rows for operation, count in operation_counts_complete.items()
            },
            "distinct_prompt_groups": len(group_records),
            "recipient_count_per_prompt_histogram": {
                str(count): groups for count, groups in sorted(group_histogram.items())
            },
            "prompt_allocation_sha256": canonical_json_sha256(group_records),
        },
        tuple(group_records),
    )


def _normalized_histogram_tv(left: dict[str, int], right: dict[str, int]) -> float:
    left_total = sum(left.values())
    right_total = sum(right.values())
    if left_total <= 0 or right_total <= 0:
        raise ValueError("Allocation histograms must have positive totals")
    labels = set(left) | set(right)
    return 0.5 * sum(abs(left.get(label, 0) / left_total - right.get(label, 0) / right_total) for label in labels)


def selection_diagnostics(grid: dict[str, Any]) -> dict[str, Any]:
    common = _endpoint_lookup(grid["endpoints"]["common_step_64"])
    fixed_m = []
    fixed_raw = []
    collection_slopes = []
    feature_cache: dict[str, tuple[dict[str, Any], dict[str, list[Any]]]] = {}
    allocation_cache: dict[str, tuple[dict[str, Any], tuple[tuple[int, int, str, int], ...]]] = {}
    feature_values: dict[tuple[int, str, str], dict[str, list[Any]]] = {}
    for seed in SELECTION_SEEDS:
        prefixes = []
        for dose_label in DOSE_LABELS:
            for clock, destination in (("fixed_m", fixed_m), ("fixed_raw", fixed_raw)):
                record = common[(seed, clock, dose_label, "behavior")]
                source_arm = grid["training_by_label"][record["source_arm_label"]]
                arm_manifest = read_json_object(Path(source_arm["dataset_manifest"]["path"]))
                counts_by_op = arm_manifest.get("counts_by_op")
                if not isinstance(counts_by_op, dict):
                    raise ValueError(f"Arm manifest lacks counts_by_op: {record['source_arm_label']}")
                hard_counts = {str(operation): int(counts_by_op.get(str(operation), 0)) for operation in range(21, 41)}
                if sum(hard_counts.values()) != record["hard_recipient_rows"]:
                    raise ValueError(
                        f"Treatment OP counts differ from hard-recipient rows: {record['logical_arm_label']}"
                    )
                if clock == "fixed_m" and (record["hard_recipient_rows"], record["rows"], record["step"]) != (
                    512,
                    1024,
                    COMMON_STEP,
                ):
                    raise ValueError(f"Fixed-M behavior contract differs: {record['logical_arm_label']}")
                source_label = record["source_arm_label"]
                if source_label not in feature_cache:
                    feature_cache[source_label] = _recipient_feature_table(
                        Path(source_arm["parquet"]["path"]),
                        expected_rows=record["hard_recipient_rows"],
                    )
                feature_summary, raw_features = feature_cache[source_label]
                feature_values[(seed, clock, dose_label)] = raw_features
                destination.append(
                    {
                        **record,
                        "treatment_counts_by_op": hard_counts,
                        "treatment_shares_by_op": {
                            operation: count / record["hard_recipient_rows"] for operation, count in hard_counts.items()
                        },
                        "nominal_p_times_raw_prefix": float(DOSES[dose_label]) * record["raw_prefix_trajectories"],
                        "recipient_feature_summary": feature_summary,
                    }
                )
            prefix = common[(seed, "fixed_m", dose_label, "behavior")]["raw_prefix_trajectories"]
            prefixes.append(prefix)
        x = [math.log(float(DOSES[label])) for label in DOSE_LABELS]
        y = [math.log(prefix) for prefix in prefixes]
        x_mean = statistics.fmean(x)
        y_mean = statistics.fmean(y)
        slope = sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x, y, strict=True)) / sum(
            (x_value - x_mean) ** 2 for x_value in x
        )
        collection_slopes.append(
            {
                "selection_seed": seed,
                "raw_prefixes_by_dose": dict(zip(DOSE_LABELS, prefixes, strict=True)),
                "log_raw_prefix_on_log_nominal_p_slope": slope,
                "strict_dead_rejection_prediction": -1.0,
            }
        )
        raw_prefixes = {
            common[(seed, "fixed_raw", dose, assignment)]["raw_prefix_trajectories"]
            for dose in DOSE_LABELS
            for assignment in BSG_ASSIGNMENTS
        }
        if raw_prefixes != {prefixes[0]}:
            raise ValueError(f"Fixed-raw B/S/G arms do not share one prefix for seed {seed}")
    composition = []
    for seed in SELECTION_SEEDS:
        by_dose = {record["dose_label"]: record for record in fixed_m if record["selection_seed"] == seed}
        comparisons = {}
        for left, right in (("p0025", "p0050"), ("p0050", "p0100"), ("p0025", "p0100")):
            left_shares = by_dose[left]["treatment_shares_by_op"]
            right_shares = by_dose[right]["treatment_shares_by_op"]
            comparisons[f"{right}_vs_{left}"] = {
                "total_variation_distance_across_op21_40": 0.5
                * sum(abs(right_shares[str(operation)] - left_shares[str(operation)]) for operation in range(21, 41)),
                "per_operation_share_difference": {
                    str(operation): right_shares[str(operation)] - left_shares[str(operation)]
                    for operation in range(21, 41)
                },
                "recipient_feature_distances": _recipient_feature_distances(
                    feature_values[(seed, "fixed_m", left)],
                    feature_values[(seed, "fixed_m", right)],
                ),
            }
        composition.append({"selection_seed": seed, "fixed_m_behavior_composition_changes": comparisons})

    allocation_cells = []
    for seed in SELECTION_SEEDS:
        for clock in ("fixed_m", "fixed_raw"):
            for dose_label in DOSE_LABELS:
                arms = {}
                group_records = {}
                for assignment in BSG_ASSIGNMENTS:
                    record = common[(seed, clock, dose_label, assignment)]
                    source_label = record["source_arm_label"]
                    source_arm = grid["training_by_label"][source_label]
                    if source_label not in allocation_cache:
                        allocation_cache[source_label] = _recipient_allocation_table(
                            Path(source_arm["parquet"]["path"]),
                            expected_rows=record["hard_recipient_rows"],
                            expected_assignment=assignment,
                        )
                    allocation, records = allocation_cache[source_label]
                    declared_overlap = _require_int(
                        record["selection_metadata"].get("candidate_overlap"),
                        f"{record['logical_arm_label']} candidate overlap",
                        minimum=0,
                    )
                    if declared_overlap != allocation["candidate_overlap_rows"]:
                        raise ValueError(f"Candidate overlap differs from Parquet: {record['logical_arm_label']}")
                    arms[assignment] = {"arm": record, "allocation": allocation}
                    group_records[assignment] = records

                recipient_counts = {arms[assignment]["allocation"]["recipient_rows"] for assignment in BSG_ASSIGNMENTS}
                raw_prefixes = {arms[assignment]["arm"]["raw_prefix_trajectories"] for assignment in BSG_ASSIGNMENTS}
                if len(recipient_counts) != 1 or len(raw_prefixes) != 1:
                    raise ValueError(
                        f"B/S/G recipient count or raw prefix differs for seed={seed}, clock={clock}, dose={dose_label}"
                    )
                if group_records["behavior"] != group_records["shuffled"]:
                    raise ValueError(
                        f"B/S prompt allocation or per-group recipient histogram differs for "
                        f"seed={seed}, clock={clock}, dose={dose_label}"
                    )
                shuffled_groups = {record[:3] for record in group_records["shuffled"]}
                global_groups = {record[:3] for record in group_records["global"]}
                overlap = len(shuffled_groups & global_groups)
                union = len(shuffled_groups | global_groups)
                shuffled_shares = arms["shuffled"]["allocation"]["shares_by_operation"]
                global_shares = arms["global"]["allocation"]["shares_by_operation"]
                allocation_cells.append(
                    {
                        "selection_seed": seed,
                        "clock": clock,
                        "dose_label": dose_label,
                        "dose": arms["behavior"]["arm"]["dose"],
                        "assignments": arms,
                        "b_equals_s_prompt_allocation_and_group_histogram": True,
                        "s_minus_g_allocation": {
                            "operation_share_total_variation_distance": 0.5
                            * sum(
                                abs(shuffled_shares[str(operation)] - global_shares[str(operation)])
                                for operation in range(21, 41)
                            ),
                            "per_operation_share_difference_s_minus_g": {
                                str(operation): shuffled_shares[str(operation)] - global_shares[str(operation)]
                                for operation in range(21, 41)
                            },
                            "prompt_group_overlap": overlap,
                            "prompt_group_union": union,
                            "prompt_group_jaccard": overlap / union,
                            "fraction_of_s_prompt_groups_also_in_g": overlap / len(shuffled_groups),
                            "fraction_of_g_prompt_groups_also_in_s": overlap / len(global_groups),
                            "recipient_count_per_prompt_histogram_total_variation_distance": (
                                _normalized_histogram_tv(
                                    arms["shuffled"]["allocation"]["recipient_count_per_prompt_histogram"],
                                    arms["global"]["allocation"]["recipient_count_per_prompt_histogram"],
                                )
                            ),
                        },
                    }
                )
    return {
        "fixed_m_behavior": fixed_m,
        "fixed_raw_behavior": fixed_raw,
        "collection_cost_scaling": collection_slopes,
        "fixed_m_behavior_composition": composition,
        "b_s_g_prompt_allocation": allocation_cells,
    }


def dose_clock_analysis(
    grid: dict[str, Any],
    results: dict[str, ValidatedResult],
    bootstrap: dict[str, dict[str, np.ndarray]],
) -> dict[str, Any]:
    common = _endpoint_lookup(grid["endpoints"]["common_step_64"])
    seed_specific = []
    aggregate_inputs: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for assignment in BSG_ASSIGNMENTS:
        for band in BANDS:
            for seed in SELECTION_SEEDS:
                fixed_m_records = [common[(seed, "fixed_m", dose, assignment)] for dose in DOSE_LABELS]
                fixed_raw_records = [common[(seed, "fixed_raw", dose, assignment)] for dose in DOSE_LABELS]
                if fixed_m_records[0]["eval_id"] != fixed_raw_records[0]["eval_id"]:
                    raise ValueError("Minimum-dose fixed-raw alias does not reuse the fixed-M evaluation")
                fixed_m_values = [_band_value(record, results, band) for record in fixed_m_records]
                fixed_raw_values = [_band_value(record, results, band) for record in fixed_raw_records]
                fixed_m_trend = _trend(fixed_m_values)
                fixed_raw_trend = _trend(fixed_raw_values)
                interaction = (
                    fixed_raw_trend["centered_log2_dose_slope_per_doubling"]
                    - fixed_m_trend["centered_log2_dose_slope_per_doubling"]
                )
                did = {
                    dose: (fixed_raw_values[index] - fixed_raw_values[0]) - (fixed_m_values[index] - fixed_m_values[0])
                    for index, dose in enumerate(DOSE_LABELS[1:], start=1)
                }
                fixed_m_boot = [bootstrap[record["eval_id"]][band] for record in fixed_m_records]
                fixed_raw_boot = [bootstrap[record["eval_id"]][band] for record in fixed_raw_records]
                fixed_m_slope_boot = (fixed_m_boot[2] - fixed_m_boot[0]) / 2.0
                fixed_raw_slope_boot = (fixed_raw_boot[2] - fixed_raw_boot[0]) / 2.0
                interaction_boot = fixed_raw_slope_boot - fixed_m_slope_boot
                record = {
                    "selection_seed": seed,
                    "assignment": assignment,
                    "band": band,
                    "fixed_m": fixed_m_trend,
                    "fixed_raw_common_step": fixed_raw_trend,
                    "raw_minus_fixed_m_slope_interaction": interaction,
                    "clock_by_dose_difference_in_differences": did,
                    "paired_prompt_bootstrap_95": {
                        "fixed_m_slope": _percentile_interval(fixed_m_slope_boot),
                        "fixed_raw_slope": _percentile_interval(fixed_raw_slope_boot),
                        "slope_interaction": _percentile_interval(interaction_boot),
                    },
                }
                seed_specific.append(record)
                aggregate_inputs.setdefault((assignment, band), []).append(
                    {
                        **record,
                        "fixed_m_slope_boot": fixed_m_slope_boot,
                        "fixed_raw_slope_boot": fixed_raw_slope_boot,
                        "interaction_boot": interaction_boot,
                    }
                )

    aggregate = []
    for (assignment, band), records in sorted(aggregate_inputs.items()):
        records.sort(key=lambda record: record["selection_seed"])
        fixed_m_slopes = [record["fixed_m"]["centered_log2_dose_slope_per_doubling"] for record in records]
        fixed_raw_slopes = [
            record["fixed_raw_common_step"]["centered_log2_dose_slope_per_doubling"] for record in records
        ]
        interactions = [record["raw_minus_fixed_m_slope_interaction"] for record in records]
        aggregate.append(
            {
                "assignment": assignment,
                "band": band,
                "confirmatory_status": (
                    "primary_H1_behavior" if assignment == "behavior" and band in PRIMARY_BANDS else "exploratory"
                ),
                "selection_seeds": list(SELECTION_SEEDS),
                "fixed_m_slope": {
                    "seed_values": dict(zip(map(str, SELECTION_SEEDS), fixed_m_slopes, strict=True)),
                    "mean": statistics.fmean(fixed_m_slopes),
                    "sample_sd": statistics.stdev(fixed_m_slopes),
                    "assumption_conditional_two_sided_sign_flip_p": exact_sign_flip_p(fixed_m_slopes),
                    "multiplicity_adjustment": None,
                    "equivalence_margin": None,
                    "equivalence_tested": False,
                },
                "fixed_raw_common_step_slope": {
                    "seed_values": dict(zip(map(str, SELECTION_SEEDS), fixed_raw_slopes, strict=True)),
                    "mean": statistics.fmean(fixed_raw_slopes),
                    "sample_sd": statistics.stdev(fixed_raw_slopes),
                    "assumption_conditional_two_sided_sign_flip_p": exact_sign_flip_p(fixed_raw_slopes),
                    "multiplicity_adjustment": None,
                },
                "raw_minus_fixed_m_slope_interaction": {
                    "seed_values": dict(zip(map(str, SELECTION_SEEDS), interactions, strict=True)),
                    "mean": statistics.fmean(interactions),
                    "sample_sd": statistics.stdev(interactions),
                    "assumption_conditional_two_sided_sign_flip_p": exact_sign_flip_p(interactions),
                    "paired_prompt_bootstrap_95_of_observed_seed_mean": _percentile_interval(
                        np.mean(np.stack([record["interaction_boot"] for record in records]), axis=0)
                    ),
                },
            }
        )
    exploratory = [entry for entry in aggregate if entry["confirmatory_status"] == "exploratory"]
    exploratory_adjusted = _holm_adjust(
        [
            entry["raw_minus_fixed_m_slope_interaction"]["assumption_conditional_two_sided_sign_flip_p"]
            for entry in exploratory
        ]
    )
    for entry, adjusted in zip(exploratory, exploratory_adjusted, strict=True):
        entry["raw_minus_fixed_m_slope_interaction"]["holm_p_across_exploratory_assignment_band_interactions"] = (
            adjusted
        )
    primary = [entry for entry in aggregate if entry["assignment"] == "behavior" and entry["band"] in PRIMARY_BANDS]
    primary_adjusted = _holm_adjust(
        [
            entry["raw_minus_fixed_m_slope_interaction"]["assumption_conditional_two_sided_sign_flip_p"]
            for entry in primary
        ]
    )
    for entry, adjusted in zip(primary, primary_adjusted, strict=True):
        entry["raw_minus_fixed_m_slope_interaction"]["holm_p_across_two_primary_bands"] = adjusted

    two_pass_lookup = _endpoint_lookup(grid["endpoints"]["fixed_raw_two_pass_mixed"])
    two_pass = []
    for assignment in BSG_ASSIGNMENTS:
        for band in BANDS:
            for seed in SELECTION_SEEDS:
                records = [two_pass_lookup[(seed, "fixed_raw", dose, assignment)] for dose in DOSE_LABELS]
                two_pass.append(
                    {
                        "selection_seed": seed,
                        "assignment": assignment,
                        "band": band,
                        "steps_by_dose": {
                            dose: record["step"] for dose, record in zip(DOSE_LABELS, records, strict=True)
                        },
                        "trend": _trend([_band_value(record, results, band) for record in records]),
                        "interpretation": (
                            "approximately two dataset passes; mixes common and final manifest readouts and is not "
                            "optimizer-step or example-exposure matched"
                        ),
                    }
                )

    final_lookup = _endpoint_lookup(grid["endpoints"]["distinct_final"])
    final_two_dose = []
    for assignment in BSG_ASSIGNMENTS:
        for band in BANDS:
            for seed in SELECTION_SEEDS:
                low = final_lookup[(seed, "fixed_raw", "p0050", assignment)]
                high = final_lookup[(seed, "fixed_raw", "p0100", assignment)]
                final_two_dose.append(
                    {
                        "selection_seed": seed,
                        "assignment": assignment,
                        "band": band,
                        "p0050_step": low["step"],
                        "p0100_step": high["step"],
                        "p0100_minus_p0050": _band_value(high, results, band) - _band_value(low, results, band),
                        "interpretation": "descriptive only: dose, optimizer steps, rows, and example exposure all differ",
                    }
                )
    return {
        "common_step_64_seed_specific": seed_specific,
        "common_step_64_across_seeds": aggregate,
        "fixed_raw_two_pass_mixed": two_pass,
        "distinct_final_two_dose_descriptive": final_two_dose,
        "decision_guard": (
            "No equivalence margin was preregistered, so a non-significant fixed-M slope means no detected ordering, "
            "not proof of cancellation. Sign-flip p-values assume independent symmetric seed effects; deterministic "
            "selection seeds are a reproducibility screen, not randomized treatment assignment. With n=3 the "
            "two-sided p-value floor is 0.25 and the two-primary-test Holm floor is 0.5. Component fixed-M and "
            "fixed-raw slope p-values are unadjusted. Three doses and three selection seeds cannot establish a "
            "phase transition."
        ),
    }


def validation_status(validated: dict[str, Any]) -> dict[str, Any]:
    eval_manifest = validated["eval"]["manifest"]
    tasks = eval_manifest["tasks"]
    results, missing = load_results(tasks, validated_eval=validated["eval"], require_complete=False)
    partial = []
    for task in tasks:
        if task["eval_id"] not in missing:
            continue
        output_dir = Path(task["output_dir"])
        if output_dir.is_dir() and any(path.is_file() for path in output_dir.rglob("*")):
            partial.append(task["eval_id"])
    return {
        "analysis_id": ANALYSIS_ID,
        "eval_launch_manifest": file_identity(Path(validated["eval"]["manifest_path"])),
        "training_launch_manifest": file_identity(Path(validated["training"]["manifest_path"])),
        "arm_index": validated["arm_index_identity"],
        "physical_task_count": len(tasks),
        "validated_result_count": len(results),
        "missing_result_count": len(missing),
        "missing_eval_ids": missing,
        "partial_without_metrics_count": len(partial),
        "partial_without_metrics_eval_ids": partial,
        "complete": not missing,
    }


def build_analysis(validated: dict[str, Any]) -> dict[str, Any]:
    eval_manifest = validated["eval"]["manifest"]
    grid = validated["grid"]
    tasks = eval_manifest["tasks"]
    results, missing = load_results(tasks, validated_eval=validated["eval"], require_complete=True)
    if missing:
        raise RuntimeError("Complete-result validation returned missing tasks")
    bootstrap = bootstrap_band_values(results)

    arm_summaries = []
    for task in tasks:
        training_arm = grid["training_by_label"][task["arm_label"]]
        arm_summaries.append(
            {
                **summarize_result(results[task["eval_id"]]),
                "training": {
                    "rows": training_arm["rows"],
                    "max_steps": training_arm["max_steps"],
                    "two_pass_steps": training_arm["two_pass_steps"],
                    "schedule": training_arm["schedule"],
                    "metadata": training_arm["metadata"],
                },
            }
        )

    contrast_cells = {}
    aggregate_contrasts = {}
    for endpoint in ("common_step_64", "distinct_final", "fixed_raw_two_pass_mixed"):
        cells = paired_contrast_cells(endpoint, grid["endpoints"][endpoint], results)
        attach_bootstrap_to_cells(cells, bootstrap)
        contrast_cells[endpoint] = cells
        aggregate_contrasts[endpoint] = aggregate_contrast_cells(cells, bootstrap)

    result_artifacts = {task["eval_id"]: results[task["eval_id"]].artifacts for task in tasks}
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "study_id": EVAL_STUDY_ID,
        "provenance": {
            "analysis_implementation": file_identity(Path(__file__).resolve()),
            "eval_launch_manifest": file_identity(Path(validated["eval"]["manifest_path"])),
            "training_launch_manifest": file_identity(Path(validated["training"]["manifest_path"])),
            "arm_index": validated["arm_index_identity"],
            "validated_live_scorer": validated["live_scorer"],
            "validated_live_solution_graph": validated["live_solution_graph"],
            "validated_live_and_pinned_materializers": validated["validated_materializers"],
            "result_artifacts": result_artifacts,
        },
        "analysis_contract": {
            "operations": list(EXPECTED_OPERATIONS),
            "prompts_per_operation": EXPECTED_PROMPTS_PER_OPERATION,
            "bands": {label: list(operations) for label, operations in BANDS.items()},
            "primary_performance_band": "unseen_extrapolation_op41_45",
            "co_primary_mechanistic_band": "trained_strict_dead_op21_40",
            "contrast_sign": "left assignment minus right assignment; positive means left performs better",
            "contrasts": {name: list(pair) for name, pair in CONTRASTS.items()},
            "bootstrap": {
                "replicates": DEFAULT_BOOTSTRAP_REPLICATES,
                "seed": DEFAULT_BOOTSTRAP_SEED,
                "rng": "NumPy PCG64 with a SHA-256-derived independent seed per operation",
                "scheme": (
                    "paired prompts, resampled with replacement within operation using identical draws for every "
                    "arm and selection seed"
                ),
                "interval_scope": (
                    "pointwise, model-conditional, non-simultaneous percentile intervals without finite-population "
                    "correction"
                ),
                "numpy_version": np.__version__,
            },
            "selection_seed_replication_scope": (
                "B/S/G selection interventions have three selection seeds; I-C0 has three I selections but one "
                "shared clean training run"
            ),
            "iid_channel_contrast": {
                "definition": "I minus C0 at common step 64 on paired prompts",
                "iid_selection_seeds": list(SELECTION_SEEDS),
                "shared_clean_training_runs": 1,
                "treatment_effect_inference": "not estimable from one shared clean training run",
            },
            "fixed_m_recipient_features": {
                "numeric": list(RECIPIENT_NUMERIC_FEATURES),
                "categorical": list(RECIPIENT_CATEGORICAL_FEATURES),
                "numeric_distance": "empirical KS plus mean difference",
                "categorical_distance": "total variation",
            },
        },
        "logical_endpoint_index": grid["endpoints"],
        "physical_arm_summaries": arm_summaries,
        "paired_contrast_cells": contrast_cells,
        "paired_contrasts_across_seeds": aggregate_contrasts,
        "iid_channel_analysis": iid_channel_analysis(grid, results, bootstrap),
        "selection_diagnostics": selection_diagnostics(grid),
        "dose_clock_analysis": dose_clock_analysis(grid, results, bootstrap),
        "methodological_caveats": [
            "Three selection seeds and one training run per arm form a mechanistic screen, not a universal scaling law.",
            "Prompt-bootstrap intervals condition on the trained models and do not measure training-seed uncertainty.",
            "All nine I arms share one C0 model; I-selection dispersion conditional on C0 is not a replicated treatment-effect estimate.",
            "No seed-level sign-flip or Holm test is reported for I-C0 because the clean training run is not replicated.",
            "All prompt-bootstrap bands are pointwise, model-conditional, and non-simultaneous; they do not cover model-training variation.",
            "B/S/G sign-flip p-values require independent symmetric seed effects and are reproducibility screens, not randomized-treatment inference.",
            "Fixed-M and fixed-raw component-slope p-values are unadjusted; Holm correction is applied only to declared interaction families.",
            "The fixed-raw p0025 B/S/G view is a byte-identical fixed-M alias and is never an independent replicate.",
            "At common step 64, update and example-exposure counts match, but dataset coverage differs with row count.",
            "Distinct finals approximately match two dataset passes but differ in optimizer steps and example exposure.",
            "No equivalence margin was fixed, so failure to detect a fixed-M trend does not prove cancellation.",
            "A finite strict-dead bank, three positive doses, and three seeds cannot establish a phase transition or p-to-zero limit.",
            "B-G is algebraically B-S plus S-G and is not an independent third test.",
        ],
    }


def main() -> None:
    args = parse_args()
    validated = validate_manifests(args.eval_launch_manifest)
    if args.command == "validate":
        result = validation_status(validated)
    elif args.command == "analyze":
        result = build_analysis(validated)
        output = (
            args.output.expanduser().resolve()
            if args.output is not None
            else Path(validated["eval"]["manifest"]["eval_root"]) / "analysis" / f"{ANALYSIS_ID}.json"
        )
        write_json_once(output, result)
        result = {
            "analysis_id": ANALYSIS_ID,
            "output": str(output),
            "sha256": file_sha256(output),
            "physical_task_count": EXPECTED_TASKS,
            "bootstrap_replicates": DEFAULT_BOOTSTRAP_REPLICATES,
        }
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
