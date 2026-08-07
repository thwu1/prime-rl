#!/usr/bin/env python3
"""Analyze immutable known-cost boundary strict evaluations."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import analyze_known_cost_training_readouts as training_readouts
import figure3_eval
import materialize_known_cost_boundary_launch as launch
import materialize_known_cost_eval_plan as eval_plan
import materialize_known_cost_postrun_authority as postrun_authority
import numpy as np

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_boundary_results"
ANALYSIS_ID = "known-cost-boundary-results-v1"
SCRIPT_REPOSITORY_PATH = "user/tianhaowu/rsci/analyze_known_cost_boundary_results.py"
RESULT_NAME = "known_cost_boundary_results.json"

OUTCOMES = (
    "strict",
    "A_answer_correct_strict_wrong",
    "answer_wrong",
)
OPERATIONS = tuple(range(11, 46))
BANDS = {
    "op15_17": tuple(range(15, 18)),
    "op21_40": tuple(range(21, 41)),
    "op41_45": tuple(range(41, 46)),
}
TAG_COUNT = 6
EXPECTED_SOURCES_PER_OPERATION = 200
EXPECTED_SOURCE_COUNT = len(OPERATIONS) * EXPECTED_SOURCES_PER_OPERATION
REFERENCE_TAGS_BY_BLOCK = {
    20260808: (0, 1),
    20260809: (2, 3),
    20260810: (4, 5),
}
DOSE_LABELS = {
    0.0075: "p0075",
    0.0125: "p0125",
    0.0225: "p0225",
    0.0375: "p0375",
}
SMOKE_BLOCK_SEED = 20260808
SMOKE_DOSES = (0.0125, 0.0375)
SMOKE_THRESHOLD = 0.02
SMOKE_REQUIRED_CLOCKS = (
    ("optimizer_step", 375),
    ("optimizer_step", 750),
    ("raw_groups", 3000),
    ("raw_groups", 6000),
)
ARM_FILENAME_RE = re.compile(r"b(?P<seed>[0-9]+)_(?P<condition>clean|tax|[gt]_p[0-9]{4})\.toml")


@dataclass(frozen=True)
class ArmFactors:
    run_id: str
    arm_filename: str
    block_seed: int
    condition: str
    family: str
    dose: float
    dose_label: str
    reference_tags: tuple[int, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "arm_filename": self.arm_filename,
            "block_seed": self.block_seed,
            "condition": self.condition,
            "family": self.family,
            "dose": self.dose,
            "dose_label": self.dose_label,
            "reference_tags": list(self.reference_tags),
        }


@dataclass(frozen=True)
class TaskOutcomes:
    tagged_keys: tuple[tuple[int, str, str, int], ...]
    tagged: dict[str, np.ndarray]
    untagged_keys: tuple[tuple[int, int, str], ...]
    untagged: dict[str, np.ndarray]
    result_artifact_identities: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ClockReadout:
    factors: ArmFactors
    clock_kind: str
    target: int
    outcomes: TaskOutcomes
    summary: dict[str, Any]
    record: dict[str, Any]


def _require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _require_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _clean_float(value: float) -> float:
    result = float(value)
    return 0.0 if result == 0.0 else result


def _json_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank JSONL row at {path}:{line_number}")
            record = json.loads(line, object_pairs_hook=_json_without_duplicate_keys)
            if not isinstance(record, dict):
                raise ValueError(f"JSONL row is not an object at {path}:{line_number}")
            records.append(record)
    return records


def result_path_for_plan(plan: dict[str, Any]) -> Path:
    return (Path(str(plan["plan_root"])) / "analysis" / RESULT_NAME).resolve()


def require_all_tasks_succeeded(validation: dict[str, Any]) -> dict[str, str]:
    plan = _require_dict(validation.get("plan"), "validated plan")
    tasks = _require_list(plan.get("tasks"), "validated plan tasks")
    expected = [str(_require_dict(task, "task").get("task_id")) for task in tasks]
    if len(expected) != len(set(expected)) or any(not task_id for task_id in expected):
        raise ValueError("Plan task IDs are missing or duplicated")
    receipts = _require_dict(validation.get("receipts"), "validated receipts")
    statuses = _require_dict(receipts.get("task_statuses"), "receipt task statuses")
    if set(statuses) != set(expected):
        missing = sorted(set(expected) - set(statuses))
        extra = sorted(set(statuses) - set(expected))
        raise ValueError(f"Evaluation task receipt coverage differs: missing={missing}, extra={extra}")
    invalid = {task_id: statuses[task_id] for task_id in expected if statuses[task_id] != "succeeded"}
    if invalid:
        raise ValueError(f"Evaluation tasks are not all succeeded: {invalid}")
    return {task_id: "succeeded" for task_id in sorted(expected)}


def validate_plan_with_recorded_planner(plan_path: Path) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    eval_plan._require_read_only(plan_path, "Known-cost evaluation plan")
    raw_before, plan = eval_plan.read_json_object(plan_path, require_canonical=True)
    if plan.get("schema_version") != eval_plan.SCHEMA_VERSION or plan.get("artifact_type") != eval_plan.ARTIFACT_TYPE:
        raise ValueError("Known-cost evaluation plan has the wrong schema or artifact type")
    if plan.get("study_id") != eval_plan.STUDY_ID or plan.get("implementation_id") != eval_plan.PLAN_IMPLEMENTATION_ID:
        raise ValueError("Known-cost evaluation plan has the wrong study or implementation identity")
    plan_id = plan.get("plan_id")
    if not isinstance(plan_id, str) or eval_plan.SHA256_RE.fullmatch(plan_id) is None:
        raise ValueError("Known-cost evaluation plan has an invalid plan ID")
    expected_path = Path(str(plan.get("eval_root"))) / "plans" / plan_id / eval_plan.PLAN_NAME
    if expected_path.resolve() != plan_path or plan.get("plan_path") != str(plan_path):
        raise ValueError("Known-cost evaluation plan is not at its recorded collision-safe path")

    implementations = _require_dict(plan.get("implementations"), "evaluation plan implementations")
    recorded_planner = _require_dict(implementations.get("planner"), "recorded eval planner")
    if recorded_planner.get("repository_path") != eval_plan.SCRIPT_REPOSITORY_PATH:
        raise ValueError("Evaluation plan records the wrong planner repository path")
    planner_path = Path(str(recorded_planner.get("path"))).expanduser().resolve()
    recorded_planner_identity = {key: recorded_planner.get(key) for key in ("path", "size_bytes", "sha256")}
    if eval_plan.file_identity(planner_path) != recorded_planner_identity:
        raise ValueError("Recorded evaluation planner identity changed")
    eval_plan._require_read_only(planner_path, "Recorded evaluation planner")

    plan_identity_before = eval_plan.file_identity(plan_path)
    summary = launch._run_exact_validator(planner_path, ["validate", "--plan", str(plan_path)])
    receipts = eval_plan.validate_receipt_chain(
        plan=plan,
        plan_sha256=eval_plan.bytes_sha256(raw_before),
    )
    models = _require_list(plan.get("models"), "evaluation plan models")
    tasks = _require_list(plan.get("tasks"), "evaluation plan tasks")
    runs = _require_list(plan.get("runs"), "evaluation plan runs")
    if not models:
        raise ValueError("Evaluation plan has no model inventory")
    expected_summary = {
        "command": "validate",
        "dry_run": False,
        "already_materialized": None,
        "plan_id": plan_id,
        "plan_path": str(plan_path),
        "plan_sha256": eval_plan.bytes_sha256(raw_before),
        "run_count": len(runs),
        "model_count": len(models),
        "task_count": len(tasks),
        "shards_per_task": plan.get("shards_per_task"),
        "step_zero_occurrences": len(
            _require_list(_require_dict(models[0], "step-zero model").get("occurrences"), "step-zero occurrences")
        ),
        "receipts": receipts,
    }
    if summary != expected_summary:
        raise ValueError("Recorded evaluation planner returned a different validation summary")
    raw_after, replayed = eval_plan.read_json_object(plan_path, require_canonical=True)
    if raw_after != raw_before or replayed != plan or eval_plan.file_identity(plan_path) != plan_identity_before:
        raise RuntimeError("Evaluation plan changed while its recorded planner was validating it")
    return {
        "plan": plan,
        "plan_path": str(plan_path),
        "plan_sha256": expected_summary["plan_sha256"],
        "task_count": len(tasks),
        "model_count": len(models),
        "receipts": receipts,
        "recorded_planner": recorded_planner,
        "validation_summary_sha256": eval_plan.canonical_json_sha256(summary),
    }


def localization_by_source(tag_values: np.ndarray, selected_tags: tuple[int, int]) -> np.ndarray:
    values = np.asarray(tag_values, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != TAG_COUNT:
        raise ValueError(f"Tag outcomes must have shape (n, {TAG_COUNT})")
    selected = tuple(sorted(selected_tags))
    if len(selected) != 2 or len(set(selected)) != 2 or any(tag < 0 or tag >= TAG_COUNT for tag in selected):
        raise ValueError("Selected tags must contain two unique indices in [0, 6)")
    unselected = tuple(tag for tag in range(TAG_COUNT) if tag not in selected)
    return values[:, selected].mean(axis=1) - values[:, unselected].mean(axis=1)


def paired_localization_difference(
    treatment_tags: np.ndarray,
    control_tags: np.ndarray,
    selected_tags: tuple[int, int],
) -> np.ndarray:
    treatment = np.asarray(treatment_tags, dtype=np.float64)
    control = np.asarray(control_tags, dtype=np.float64)
    if treatment.shape != control.shape:
        raise ValueError("Paired T/G tag outcomes have different shapes")
    return localization_by_source(treatment, selected_tags) - localization_by_source(control, selected_tags)


def interpolate_task_outcomes(lower: TaskOutcomes, upper: TaskOutcomes, weight_upper: float) -> TaskOutcomes:
    weight = _require_number(weight_upper, "interpolation weight")
    if not 0.0 <= weight <= 1.0:
        raise ValueError("Interpolation weight must lie in [0, 1]")
    if lower.tagged_keys != upper.tagged_keys or lower.untagged_keys != upper.untagged_keys:
        raise ValueError("Raw-clock endpoints do not have identical source identities")
    if set(lower.tagged) != set(OUTCOMES) or set(upper.tagged) != set(OUTCOMES):
        raise ValueError("Raw-clock tagged endpoint outcomes are incomplete")
    if set(lower.untagged) != set(OUTCOMES) or set(upper.untagged) != set(OUTCOMES):
        raise ValueError("Raw-clock untagged endpoint outcomes are incomplete")
    tagged = {}
    untagged = {}
    for metric in OUTCOMES:
        if lower.tagged[metric].shape != upper.tagged[metric].shape:
            raise ValueError(f"Raw-clock tagged {metric} shapes differ")
        if lower.untagged[metric].shape != upper.untagged[metric].shape:
            raise ValueError(f"Raw-clock untagged {metric} shapes differ")
        tagged[metric] = (1.0 - weight) * lower.tagged[metric] + weight * upper.tagged[metric]
        untagged[metric] = (1.0 - weight) * lower.untagged[metric] + weight * upper.untagged[metric]
    return TaskOutcomes(lower.tagged_keys, tagged, lower.untagged_keys, untagged)


def _selector_summary(values: np.ndarray, operations: np.ndarray) -> dict[str, Any]:
    vector = np.asarray(values, dtype=np.float64)
    operation_vector = np.asarray(operations, dtype=np.int16)
    if vector.ndim != 1 or vector.shape != operation_vector.shape:
        raise ValueError("Outcome values and operations must be aligned vectors")

    def mean_for(selected_operations: tuple[int, ...]) -> float:
        mask = np.isin(operation_vector, selected_operations)
        if not np.any(mask):
            raise ValueError(f"No sources for operations {selected_operations}")
        return _clean_float(float(vector[mask].mean()))

    return {
        "all_op11_45": mean_for(OPERATIONS),
        "per_op": {str(operation): mean_for((operation,)) for operation in OPERATIONS},
        "bands": {name: mean_for(band) for name, band in BANDS.items()},
    }


def summarize_outcomes(outcomes: TaskOutcomes, selected_tags: tuple[int, int]) -> dict[str, Any]:
    tagged_operations = np.fromiter((key[0] for key in outcomes.tagged_keys), dtype=np.int16)
    untagged_operations = np.fromiter((key[0] for key in outcomes.untagged_keys), dtype=np.int16)
    selected = tuple(sorted(selected_tags))
    unselected = tuple(tag for tag in range(TAG_COUNT) if tag not in selected)
    summary = {}
    for metric in OUTCOMES:
        tagged = np.asarray(outcomes.tagged[metric], dtype=np.float64)
        untagged = np.asarray(outcomes.untagged[metric], dtype=np.float64)
        summary[metric] = {
            "untagged_pass_at_1": _selector_summary(untagged, untagged_operations),
            "tagged_all_pass_at_1": _selector_summary(tagged.mean(axis=1), tagged_operations),
            "tagged_selected_pass_at_1": _selector_summary(tagged[:, selected].mean(axis=1), tagged_operations),
            "tagged_unselected_pass_at_1": _selector_summary(
                tagged[:, unselected].mean(axis=1),
                tagged_operations,
            ),
            "tagged_L_selected_minus_unselected": _selector_summary(
                localization_by_source(tagged, selected),
                tagged_operations,
            ),
        }
    return summary


def _map_numeric_leaves(value: object, operation: Any) -> object:
    if isinstance(value, dict):
        return {key: _map_numeric_leaves(item, operation) for key, item in value.items()}
    if isinstance(value, list):
        return [_map_numeric_leaves(item, operation) for item in value]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Outcome summary contains a non-numeric leaf")
    return operation(float(value))


def subtract_summaries(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if set(left) != set(right):
        raise ValueError("Outcome summaries have different keys")

    def subtract_pair(left_value: object, right_value: object) -> object:
        if isinstance(left_value, dict) and isinstance(right_value, dict):
            if set(left_value) != set(right_value):
                raise ValueError("Outcome summary branches have different keys")
            return {key: subtract_pair(left_value[key], right_value[key]) for key in left_value}
        if (
            isinstance(left_value, bool)
            or isinstance(right_value, bool)
            or not isinstance(left_value, (int, float))
            or not isinstance(right_value, (int, float))
        ):
            raise ValueError("Outcome summary contains a non-numeric leaf")
        return _clean_float(float(left_value) - float(right_value))

    return subtract_pair(left, right)  # type: ignore[return-value]


def mean_summaries(values: list[dict[str, Any]]) -> dict[str, Any]:
    if not values:
        raise ValueError("Cannot average an empty summary collection")
    reference = values[0]

    def collect(nodes: list[object]) -> object:
        first = nodes[0]
        if isinstance(first, dict):
            keys = set(first)
            if any(not isinstance(node, dict) or set(node) != keys for node in nodes):
                raise ValueError("Outcome summaries have different structures")
            return {key: collect([node[key] for node in nodes]) for key in first}
        if any(isinstance(node, bool) or not isinstance(node, (int, float)) for node in nodes):
            raise ValueError("Outcome summary contains a non-numeric leaf")
        return _clean_float(math.fsum(float(node) for node in nodes) / len(nodes))

    return collect([reference, *values[1:]])  # type: ignore[return-value]


def _binary_value(value: object, label: str) -> int:
    if value not in (False, True, 0, 1, 0.0, 1.0):
        raise ValueError(f"{label} must be binary")
    return int(bool(value))


def _record_outcomes(record: dict[str, Any], *, tagged: bool, label: str) -> dict[str, int]:
    strict = _binary_value(record.get("perfect"), f"{label}.perfect")
    answer_correct = _binary_value(record.get("answer_correct"), f"{label}.answer_correct")
    candidate = _binary_value(
        record.get("answer_correct_strict_wrong", bool(answer_correct and not strict)),
        f"{label}.answer_correct_strict_wrong",
    )
    answer_wrong = _binary_value(record.get("answer_wrong", not answer_correct), f"{label}.answer_wrong")
    if tagged and ("answer_correct_strict_wrong" not in record or "answer_wrong" not in record):
        raise ValueError(f"{label} lacks known-cost outcomes")
    if candidate != int(answer_correct and not strict) or answer_wrong != int(not answer_correct):
        raise ValueError(f"{label} known-cost outcomes are inconsistent")
    if strict + candidate + answer_wrong != 1:
        raise ValueError(f"{label} strict/A/answer-wrong outcomes do not partition the source")
    return {
        "strict": strict,
        "A_answer_correct_strict_wrong": candidate,
        "answer_wrong": answer_wrong,
    }


def _validated_strict_records(shard: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    eval_plan._validate_completed_shard(shard)
    output_dir = Path(str(shard["output_dir"]))
    strict_path = output_dir / "strict_results.jsonl"
    artifacts_before = {name: eval_plan.file_identity(output_dir / name) for name in eval_plan.SUCCESS_ARTIFACT_NAMES}
    config = figure3_eval.load_config(Path(str(_require_dict(shard["eval_config"], "eval config identity")["path"])))
    rows, dataset_hashes = figure3_eval.load_rows(config["eval"])
    manifest = figure3_eval.build_generation_manifest(config, rows, dataset_hashes)
    figure3_eval.verify_generation_manifest(output_dir / figure3_eval.GENERATION_MANIFEST_NAME, manifest)
    generation_sha256, generation_records = figure3_eval.canonical_generation_content(
        output_dir / "generations.jsonl",
        rows,
        int(config["eval"]["samples_per_prompt"]),
    )
    figure3_eval.verify_generation_completion(
        output_dir,
        manifest,
        generation_sha256,
        len(generation_records),
    )
    verified = figure3_eval.verify_strict_results(strict_path, rows, generation_records)
    duplicate_checked = _read_jsonl_objects(strict_path)
    if eval_plan.canonical_json_sha256(verified) != eval_plan.canonical_json_sha256(duplicate_checked):
        raise ValueError(f"Strict results changed after deterministic verification: {strict_path}")
    artifacts_after = {name: eval_plan.file_identity(output_dir / name) for name in eval_plan.SUCCESS_ARTIFACT_NAMES}
    if artifacts_after != artifacts_before:
        raise ValueError(f"Evaluation artifacts changed while being analyzed: {output_dir}")
    return verified, {"output_dir": str(output_dir.resolve()), "artifacts": artifacts_before}


def _validate_operation_counts(keys: list[tuple[int, object]], label: str) -> None:
    counts = Counter(operation for operation, _ in keys)
    expected = {operation: EXPECTED_SOURCES_PER_OPERATION for operation in OPERATIONS}
    if counts != expected:
        raise ValueError(f"{label} source counts by operation differ: {dict(sorted(counts.items()))}")


def load_task_outcomes(task: dict[str, Any]) -> TaskOutcomes:
    shards = _require_list(task.get("shards"), f"task {task.get('task_id')} shards")
    by_shard_id = {}
    for raw_shard in shards:
        shard = _require_dict(raw_shard, "task shard")
        shard_id = shard.get("shard_id")
        if not isinstance(shard_id, str) or shard_id in by_shard_id:
            raise ValueError(f"Task {task.get('task_id')} has missing or duplicate shard IDs")
        by_shard_id[shard_id] = shard
    expected_shards = {"untagged", *(f"tag_{tag}" for tag in range(TAG_COUNT))}
    if set(by_shard_id) != expected_shards:
        raise ValueError(f"Task {task.get('task_id')} does not contain exactly seven required shards")

    artifact_identities = []
    untagged_records, identity = _validated_strict_records(by_shard_id["untagged"])
    artifact_identities.append({"shard_id": "untagged", **identity})
    untagged_rows: dict[tuple[int, int, str], dict[str, int]] = {}
    for index, record in enumerate(untagged_records):
        if _require_int(record.get("sample_rank"), f"untagged record {index} sample_rank") != 0:
            raise ValueError("Known-cost evaluation requires sample rank zero")
        source_id = record.get("id")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError(f"untagged record {index} has an invalid source ID")
        key = (
            _require_int(record.get("op"), f"untagged record {index} op", minimum=1),
            _require_int(record.get("__idx"), f"untagged record {index} __idx"),
            source_id,
        )
        if not key[2] or key in untagged_rows:
            raise ValueError(f"Task {task.get('task_id')} has invalid or duplicate untagged source {key}")
        untagged_rows[key] = _record_outcomes(record, tagged=False, label=f"untagged record {index}")
    untagged_keys = tuple(sorted(untagged_rows))
    _validate_operation_counts([(key[0], key[1:]) for key in untagged_keys], "untagged")

    tagged_by_tag: dict[int, dict[tuple[int, str], tuple[str, int, dict[str, int]]]] = {}
    for tag in range(TAG_COUNT):
        shard_id = f"tag_{tag}"
        records, identity = _validated_strict_records(by_shard_id[shard_id])
        artifact_identities.append({"shard_id": shard_id, **identity})
        sources = {}
        for index, record in enumerate(records):
            if _require_int(record.get("sample_rank"), f"{shard_id} record {index} sample_rank") != 0:
                raise ValueError("Known-cost evaluation requires sample rank zero")
            observed_tag = _require_int(record.get("neutral_tag_index"), f"{shard_id} record {index} tag")
            if observed_tag != tag:
                raise ValueError(f"{shard_id} contains tag {observed_tag}")
            operation = _require_int(record.get("op"), f"{shard_id} record {index} op", minimum=1)
            source_id = record.get("source_sample_id")
            raw_id = record.get("source_raw_id")
            request_seed = record.get("request_seed")
            if not isinstance(source_id, str) or not source_id or not isinstance(raw_id, str) or not raw_id:
                raise ValueError(f"{shard_id} record {index} has invalid source identity")
            seed = _require_int(request_seed, f"{shard_id} record {index} request_seed")
            key = (operation, source_id)
            if key in sources:
                raise ValueError(f"{shard_id} repeats source {key}")
            sources[key] = (
                raw_id,
                seed,
                _record_outcomes(record, tagged=True, label=f"{shard_id} record {index}"),
            )
        _validate_operation_counts(list(sources), shard_id)
        tagged_by_tag[tag] = sources

    reference_keys = set(tagged_by_tag[0])
    if any(set(tagged_by_tag[tag]) != reference_keys for tag in range(1, TAG_COUNT)):
        raise ValueError(f"Task {task.get('task_id')} tagged shards do not share one source universe")
    source_keys = []
    tagged_values = {metric: [] for metric in OUTCOMES}
    for operation, source_id in sorted(reference_keys):
        raw_ids = {tagged_by_tag[tag][(operation, source_id)][0] for tag in range(TAG_COUNT)}
        request_seeds = {tagged_by_tag[tag][(operation, source_id)][1] for tag in range(TAG_COUNT)}
        if len(raw_ids) != 1 or len(request_seeds) != 1:
            raise ValueError(f"Task {task.get('task_id')} source {(operation, source_id)} is not paired across tags")
        source_keys.append((operation, source_id, raw_ids.pop(), request_seeds.pop()))
        for metric in OUTCOMES:
            tagged_values[metric].append(
                [tagged_by_tag[tag][(operation, source_id)][2][metric] for tag in range(TAG_COUNT)]
            )
    if len(source_keys) != EXPECTED_SOURCE_COUNT:
        raise ValueError(f"Task {task.get('task_id')} has {len(source_keys)} tagged sources")
    if len(untagged_keys) != EXPECTED_SOURCE_COUNT:
        raise ValueError(f"Task {task.get('task_id')} has {len(untagged_keys)} untagged prompts")

    tagged_arrays = {metric: np.asarray(values, dtype=np.float64) for metric, values in tagged_values.items()}
    untagged_arrays = {
        metric: np.asarray([untagged_rows[key][metric] for key in untagged_keys], dtype=np.float64)
        for metric in OUTCOMES
    }
    return TaskOutcomes(
        tuple(source_keys),
        tagged_arrays,
        untagged_keys,
        untagged_arrays,
        tuple(artifact_identities),
    )


def _binary_tag_masks(values: np.ndarray) -> list[int]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != TAG_COUNT or not np.all(np.isin(array, (0.0, 1.0))):
        raise ValueError("Exact tagged source outcomes must be binary")
    weights = 1 << np.arange(TAG_COUNT, dtype=np.int64)
    return [int(value) for value in array.astype(np.int64) @ weights]


def _binary_vector(values: np.ndarray) -> list[int]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not np.all(np.isin(array, (0.0, 1.0))):
        raise ValueError("Exact untagged source outcomes must be binary")
    return [int(value) for value in array]


def compact_task_outcomes(task_id: str, outcomes: TaskOutcomes) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "result_artifacts": list(outcomes.result_artifact_identities),
        "tagged_encoding": "one integer per source; bit t is tag t and 1 means pass@1",
        "tagged_tag_bitmask_by_source": {metric: _binary_tag_masks(outcomes.tagged[metric]) for metric in OUTCOMES},
        "untagged_encoding": "one binary pass@1 value per prompt in the common untagged source index",
        "untagged_by_prompt": {metric: _binary_vector(outcomes.untagged[metric]) for metric in OUTCOMES},
    }


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _derive_arm_factors(
    run: dict[str, Any],
    launch_run: dict[str, Any],
) -> ArmFactors:
    run_id = str(run["run_id"])
    filename = str(run["launch_binding"]["arm_filename"])
    if launch_run.get("arm_filename") != filename:
        raise ValueError(f"Launch/run arm filename differs for {run_id}")
    match = ARM_FILENAME_RE.fullmatch(filename)
    if match is None:
        raise ValueError(f"Arm filename is outside the frozen design: {filename}")
    filename_seed = int(match.group("seed"))
    filename_condition = match.group("condition")

    resolved = _require_dict(run.get("resolved_configs"), f"{run_id} resolved configs")
    orchestrator_identity = _require_dict(resolved.get("orchestrator"), f"{run_id} orchestrator identity")
    inference_identity = _require_dict(resolved.get("inference"), f"{run_id} inference identity")
    orchestrator_path = Path(str(orchestrator_identity["path"]))
    inference_path = Path(str(inference_identity["path"]))
    if eval_plan.file_identity(orchestrator_path) != orchestrator_identity:
        raise ValueError(f"{run_id} orchestrator config changed")
    if eval_plan.file_identity(inference_path) != inference_identity:
        raise ValueError(f"{run_id} inference config changed")
    orchestrator = _load_toml(orchestrator_path)
    inference = _load_toml(inference_path)
    environments = _require_list(
        _require_dict(orchestrator.get("train"), f"{run_id} train").get("env"), f"{run_id} train.env"
    )
    if len(environments) != 1:
        raise ValueError(f"{run_id} must have exactly one training environment")
    args = _require_dict(_require_dict(environments[0], f"{run_id} train.env[0]").get("args"), f"{run_id} args")
    seed = _require_int(args.get("defect_seed"), f"{run_id} defect_seed")
    if inference.get("seed") != seed:
        raise ValueError(f"{run_id} inference seed differs from defect seed")
    dataset_path = Path(str(args.get("dataset_path")))
    if dataset_path.parent.name != f"block-{seed}":
        raise ValueError(f"{run_id} dataset path does not encode its block seed")
    if seed != filename_seed or launch_run.get("block_seed") != seed:
        raise ValueError(f"{run_id} block seed differs across filename/config/launch intent")
    if seed not in REFERENCE_TAGS_BY_BLOCK:
        raise ValueError(f"{run_id} has an unknown block seed")
    reference_tags = tuple(args.get("defect_reference_neutral_tags", ()))
    if reference_tags != REFERENCE_TAGS_BY_BLOCK[seed]:
        raise ValueError(f"{run_id} reference tags differ from the counterbalanced block")
    if args.get("defect_assignment") != "behavior_group":
        raise ValueError(f"{run_id} has the wrong recipient assignment")
    if args.get("false_positive_scope") != "answer_correct_strict_wrong":
        raise ValueError(f"{run_id} has the wrong false-positive scope")
    if args.get("defect_draw_scope") != "sample_slot" or args.get("defect_eligible_slot_count") != 128:
        raise ValueError(f"{run_id} has the wrong sample-slot contract")
    if args.get("defect_neutral_tag_count") != TAG_COUNT:
        raise ValueError(f"{run_id} has the wrong neutral-tag count")
    if _require_number(args.get("defect_gate_probability"), f"{run_id} alpha") != 1 / 3:
        raise ValueError(f"{run_id} has the wrong gate probability")
    if _require_number(args.get("strict_reward_weight"), f"{run_id} strict weight") != 1.0:
        raise ValueError(f"{run_id} has the wrong strict reward weight")

    dose = _require_number(args.get("false_positive_rate"), f"{run_id} dose")
    tax = _require_number(args.get("behavior_tax_c0"), f"{run_id} tax")
    gate_mode = args.get("defect_gate_mode")
    if dose == 0.0 and tax == 0.0 and gate_mode == "group":
        family = condition = dose_label = "clean"
    elif dose == 0.0 and tax == 0.03 and gate_mode == "group":
        family = condition = dose_label = "tax"
    elif dose in DOSE_LABELS and tax == 0.03 and gate_mode in {"group", "neutral_tag"}:
        family = "g" if gate_mode == "group" else "t"
        dose_label = DOSE_LABELS[dose]
        condition = f"{family}_{dose_label}"
        selected_tags = tuple(args.get("defect_selected_neutral_tags", ()))
        if family == "g" and selected_tags:
            raise ValueError(f"{run_id} hidden-group arm has selected visible tags")
        if family == "t" and selected_tags != reference_tags:
            raise ValueError(f"{run_id} persistent-tag selected tags differ from reference tags")
    else:
        raise ValueError(f"{run_id} does not match a frozen clean/tax/G/T cell")
    expected_condition = condition if family in {"g", "t"} else family
    if filename_condition != expected_condition:
        raise ValueError(f"{run_id} filename condition differs from resolved config")
    if (
        launch_run.get("condition") != expected_condition
        or launch_run.get("family") != family
        or _require_number(launch_run.get("nominal_p"), f"{run_id} launch nominal p") != dose
    ):
        raise ValueError(f"{run_id} launch factors differ from resolved config")
    return ArmFactors(run_id, filename, seed, condition, family, dose, dose_label, reference_tags)  # type: ignore[arg-type]


def _validate_factor_inventory(factors: list[ArmFactors], design: str) -> None:
    cells = {(item.block_seed, item.family, item.dose) for item in factors}
    if len(cells) != len(factors):
        raise ValueError("Known-cost arm factors contain duplicate cells")
    if design == "four_arm_smoke_screen":
        expected = {(SMOKE_BLOCK_SEED, family, dose) for family in ("g", "t") for dose in SMOKE_DOSES}
    elif design == "full_30_arm_grid":
        expected = set()
        for block in REFERENCE_TAGS_BY_BLOCK:
            expected.update({(block, "clean", 0.0), (block, "tax", 0.0)})
            expected.update((block, family, dose) for family in ("g", "t") for dose in DOSE_LABELS)
    else:
        raise ValueError(f"Unknown eligible design: {design!r}")
    if cells != expected:
        raise ValueError(
            f"Known-cost factor inventory differs: missing={sorted(expected - cells)}, extra={sorted(cells - expected)}"
        )


def _occurrence_index(
    plan: dict[str, Any], outcomes_by_task: dict[str, TaskOutcomes]
) -> dict[tuple[str, int], tuple[str, int, TaskOutcomes]]:
    tasks = _require_list(plan.get("tasks"), "plan tasks")
    task_by_model = {}
    for raw_task in tasks:
        task = _require_dict(raw_task, "plan task")
        model_key = str(task.get("model_key"))
        task_id = str(task.get("task_id"))
        if not model_key or task_id != model_key or model_key in task_by_model:
            raise ValueError("Plan tasks do not map one-to-one to model keys")
        task_by_model[model_key] = task_id
    models = _require_list(plan.get("models"), "plan models")
    if set(task_by_model) != {str(_require_dict(model, "model").get("model_key")) for model in models}:
        raise ValueError("Plan model and task inventories differ")
    index = {}
    for raw_model in models:
        model = _require_dict(raw_model, "plan model")
        model_key = str(model["model_key"])
        task_id = task_by_model[model_key]
        outcomes = outcomes_by_task[task_id]
        for raw_occurrence in _require_list(model.get("occurrences"), f"{model_key} occurrences"):
            occurrence = _require_dict(raw_occurrence, "model occurrence")
            run_id = str(occurrence.get("run_id"))
            step = _require_int(occurrence.get("step"), f"{model_key} occurrence step")
            raw_groups = _require_int(occurrence.get("raw_groups"), f"{model_key} occurrence raw groups")
            key = (run_id, step)
            if key in index:
                raise ValueError(f"Plan repeats model occurrence {key}")
            index[key] = (task_id, raw_groups, outcomes)
    return index


def _endpoint_record(
    run_id: str,
    step: int,
    expected_raw_groups: int,
    factors: ArmFactors,
    occurrence_index: dict[tuple[str, int], tuple[str, int, TaskOutcomes]],
) -> tuple[TaskOutcomes, dict[str, Any]]:
    key = (run_id, step)
    if key not in occurrence_index:
        raise ValueError(f"No evaluated task for checkpoint occurrence {key}")
    task_id, raw_groups, outcomes = occurrence_index[key]
    if raw_groups != expected_raw_groups:
        raise ValueError(f"Checkpoint occurrence {key} raw groups differ: {raw_groups} != {expected_raw_groups}")
    return outcomes, {
        "task_id": task_id,
        "step": step,
        "raw_groups": raw_groups,
        "summary": summarize_outcomes(outcomes, factors.reference_tags),
    }


def build_clock_readouts(
    plan: dict[str, Any],
    factors_by_run: dict[str, ArmFactors],
    occurrence_index: dict[tuple[str, int], tuple[str, int, TaskOutcomes]],
) -> list[ClockReadout]:
    readouts = []
    for raw_run in _require_list(plan.get("runs"), "plan runs"):
        run = _require_dict(raw_run, "plan run")
        run_id = str(run["run_id"])
        factors = factors_by_run[run_id]
        exposure_by_step = {
            _require_int(point.get("step"), f"{run_id} exposure step"): _require_int(
                point.get("raw_groups"),
                f"{run_id} exposure raw groups",
            )
            for point in (
                _require_dict(item, "checkpoint exposure")
                for item in _require_list(run.get("checkpoint_exposure_grid"), f"{run_id} exposure grid")
            )
        }
        for raw_target in _require_list(run.get("optimizer_clock_targets"), f"{run_id} optimizer clocks"):
            target = _require_dict(raw_target, "optimizer clock target")
            target_step = _require_int(target.get("target_step"), "optimizer target step", minimum=1)
            checkpoint_step = _require_int(target.get("checkpoint_step"), "optimizer checkpoint step", minimum=1)
            if checkpoint_step != target_step or checkpoint_step not in exposure_by_step:
                raise ValueError(f"{run_id} optimizer clock is not exact at {target_step}")
            outcomes, endpoint = _endpoint_record(
                run_id,
                checkpoint_step,
                exposure_by_step[checkpoint_step],
                factors,
                occurrence_index,
            )
            summary = endpoint["summary"]
            record = {
                **factors.as_dict(),
                "clock_kind": "optimizer_step",
                "target": target_step,
                "mode": "exact",
                "weight_upper": 0.0,
                "lower_endpoint": endpoint,
                "upper_endpoint": endpoint,
                "interpolated_summary": summary,
            }
            readouts.append(ClockReadout(factors, "optimizer_step", target_step, outcomes, summary, record))

        for raw_target in _require_list(run.get("raw_group_clock_targets"), f"{run_id} raw clocks"):
            target = _require_dict(raw_target, "raw clock target")
            target_raw = _require_int(target.get("target_raw_groups"), "raw-group target", minimum=1)
            mode = target.get("mode")
            if mode not in {"exact", "bracketed"}:
                raise ValueError(f"{run_id} raw clock has invalid mode {mode!r}")
            lower_point = _require_dict(target.get("lower"), "raw lower endpoint")
            upper_point = _require_dict(target.get("upper"), "raw upper endpoint")
            lower_step = _require_int(lower_point.get("step"), "raw lower step")
            upper_step = _require_int(upper_point.get("step"), "raw upper step")
            lower_raw = _require_int(lower_point.get("raw_groups"), "raw lower exposure")
            upper_raw = _require_int(upper_point.get("raw_groups"), "raw upper exposure")
            lower_outcomes, lower_endpoint = _endpoint_record(
                run_id,
                lower_step,
                lower_raw,
                factors,
                occurrence_index,
            )
            upper_outcomes, upper_endpoint = _endpoint_record(
                run_id,
                upper_step,
                upper_raw,
                factors,
                occurrence_index,
            )
            if mode == "exact":
                if lower_point != upper_point or lower_raw != target_raw:
                    raise ValueError(f"{run_id} exact raw clock endpoints differ")
                weight = 0.0
            else:
                if not lower_raw < target_raw < upper_raw:
                    raise ValueError(f"{run_id} raw target is not strictly bracketed")
                weight = (target_raw - lower_raw) / (upper_raw - lower_raw)
                recorded_weight = _require_number(target.get("interpolation_weight_upper"), "recorded raw weight")
                if recorded_weight != weight:
                    raise ValueError(f"{run_id} recorded raw interpolation weight differs")
            interpolated = interpolate_task_outcomes(lower_outcomes, upper_outcomes, weight)
            summary = summarize_outcomes(interpolated, factors.reference_tags)
            record = {
                **factors.as_dict(),
                "clock_kind": "raw_groups",
                "target": target_raw,
                "mode": mode,
                "weight_upper": weight,
                "lower_endpoint": lower_endpoint,
                "upper_endpoint": upper_endpoint,
                "interpolated_summary": summary,
            }
            readouts.append(ClockReadout(factors, "raw_groups", target_raw, interpolated, summary, record))
    readouts.sort(
        key=lambda item: (
            item.factors.block_seed,
            item.factors.family,
            item.factors.dose,
            item.clock_kind,
            item.target,
        )
    )
    return readouts


def _contrast_record(
    name: str,
    left: ClockReadout,
    right: ClockReadout,
    difference: dict[str, Any],
) -> dict[str, Any]:
    if (left.clock_kind, left.target) != (right.clock_kind, right.target):
        raise ValueError(f"{name} compares different clocks")
    if left.factors.block_seed != right.factors.block_seed:
        raise ValueError(f"{name} compares different randomization blocks")
    return {
        "contrast": name,
        "block_seed": left.factors.block_seed,
        "clock_kind": left.clock_kind,
        "target": left.target,
        "left_arm": left.factors.as_dict(),
        "right_arm": right.factors.as_dict(),
        "left_minus_right": difference,
    }


def _across_block_means(rows: list[dict[str, Any]], grouping_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    grouped: dict[tuple[object, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[field] for field in grouping_fields)].append(row)
    result = []
    for key, group in sorted(grouped.items()):
        result.append(
            {
                **dict(zip(grouping_fields, key, strict=True)),
                "block_seeds": sorted(int(row["block_seed"]) for row in group),
                "block_count": len(group),
                "descriptive_model_conditional_mean": mean_summaries(
                    [_require_dict(row["left_minus_right"], "contrast difference") for row in group]
                ),
            }
        )
    return result


def build_contrasts(readouts: list[ClockReadout], design: str) -> dict[str, Any]:
    by_cell = {}
    for readout in readouts:
        key = (
            readout.factors.block_seed,
            readout.factors.family,
            readout.factors.dose,
            readout.clock_kind,
            readout.target,
        )
        if key in by_cell:
            raise ValueError(f"Duplicate arm readout cell: {key}")
        by_cell[key] = readout

    tax_clean = []
    arm_tax = []
    gate_dose = []
    if design == "full_30_arm_grid":
        for block in REFERENCE_TAGS_BY_BLOCK:
            clocks = sorted(
                (kind, target)
                for candidate_block, family, dose, kind, target in by_cell
                if candidate_block == block and family == "clean" and dose == 0.0
            )
            for kind, target in clocks:
                clean = by_cell[(block, "clean", 0.0, kind, target)]
                tax = by_cell[(block, "tax", 0.0, kind, target)]
                tax_clean.append(
                    _contrast_record("tax_minus_clean", tax, clean, subtract_summaries(tax.summary, clean.summary))
                )
                for family in ("g", "t"):
                    for dose in DOSE_LABELS:
                        arm = by_cell[(block, family, dose, kind, target)]
                        record = _contrast_record(
                            "arm_minus_tax",
                            arm,
                            tax,
                            subtract_summaries(arm.summary, tax.summary),
                        )
                        record.update({"family": family, "dose": dose, "dose_label": DOSE_LABELS[dose]})
                        arm_tax.append(record)

    paired_rows_internal = []
    pair_groups = defaultdict(dict)
    for readout in readouts:
        if readout.factors.family in {"g", "t"}:
            key = (readout.factors.block_seed, readout.factors.dose, readout.clock_kind, readout.target)
            pair_groups[key][readout.factors.family] = readout
    for (block, dose, kind, target), pair in sorted(pair_groups.items()):
        if set(pair) != {"g", "t"}:
            raise ValueError(f"Incomplete G/T pair for {(block, dose, kind, target)}")
        group = pair["g"]
        tag = pair["t"]
        if group.factors.reference_tags != tag.factors.reference_tags:
            raise ValueError("Paired G/T arms have different reference tags")
        if group.outcomes.tagged_keys != tag.outcomes.tagged_keys:
            raise ValueError("Paired G/T arms have different tagged source identities")
        difference = subtract_summaries(tag.summary, group.summary)
        paired_d = {}
        operations = np.fromiter((key[0] for key in tag.outcomes.tagged_keys), dtype=np.int16)
        for metric in OUTCOMES:
            paired_d[metric] = _selector_summary(
                paired_localization_difference(
                    tag.outcomes.tagged[metric],
                    group.outcomes.tagged[metric],
                    tag.factors.reference_tags,
                ),
                operations,
            )
        record = _contrast_record("persistent_tag_T_minus_hidden_group_G", tag, group, difference)
        record.update(
            {
                "dose": dose,
                "dose_label": DOSE_LABELS[dose],
                "paired_localization_D_T_minus_G": paired_d,
            }
        )
        gate_dose.append(record)
        paired_rows_internal.append(record)

    dose_interactions = []
    rows_by_block_clock: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in gate_dose:
        rows_by_block_clock[(int(row["block_seed"]), str(row["clock_kind"]), int(row["target"]))].append(row)
    for (block, kind, target), rows in sorted(rows_by_block_clock.items()):
        by_dose = {float(row["dose"]): row for row in rows}
        for lower_dose, upper_dose in itertools.combinations(sorted(by_dose), 2):
            lower = by_dose[lower_dose]
            upper = by_dose[upper_dose]
            dose_interactions.append(
                {
                    "contrast": "gate_by_dose_interaction",
                    "block_seed": block,
                    "clock_kind": kind,
                    "target": target,
                    "lower_dose": lower_dose,
                    "upper_dose": upper_dose,
                    "T_minus_G_at_upper_minus_lower": subtract_summaries(
                        _require_dict(upper["left_minus_right"], "upper T-G contrast"),
                        _require_dict(lower["left_minus_right"], "lower T-G contrast"),
                    ),
                    "paired_localization_D_at_upper_minus_lower": subtract_summaries(
                        _require_dict(upper["paired_localization_D_T_minus_G"], "upper paired D"),
                        _require_dict(lower["paired_localization_D_T_minus_G"], "lower paired D"),
                    ),
                }
            )

    return {
        "tax_minus_clean_by_block": tax_clean,
        "arm_minus_tax_by_block": arm_tax,
        "gate_dose_T_minus_G_by_block": gate_dose,
        "gate_by_dose_interactions_by_block": dose_interactions,
        "across_block_descriptive_means": {
            "tax_minus_clean": _across_block_means(tax_clean, ("clock_kind", "target")) if tax_clean else [],
            "arm_minus_tax": _across_block_means(
                arm_tax,
                ("family", "dose", "dose_label", "clock_kind", "target"),
            )
            if arm_tax
            else [],
            "gate_dose_T_minus_G": _across_block_means(
                gate_dose,
                ("dose", "dose_label", "clock_kind", "target"),
            ),
        },
    }


def smoke_spend_decision(
    gate_dose_rows: list[dict[str, Any]],
    *,
    eligible_design: str,
) -> dict[str, Any]:
    by_key = {}
    for row in gate_dose_rows:
        if int(row["block_seed"]) != SMOKE_BLOCK_SEED or float(row["dose"]) not in SMOKE_DOSES:
            continue
        key = (float(row["dose"]), str(row["clock_kind"]), int(row["target"]))
        if key in by_key:
            raise ValueError(f"Duplicate smoke D_A row: {key}")
        paired = _require_dict(row.get("paired_localization_D_T_minus_G"), "paired localization D")
        candidate = _require_dict(paired.get("A_answer_correct_strict_wrong"), "paired A D")
        bands = _require_dict(candidate.get("bands"), "paired A D bands")
        by_key[key] = _require_number(bands.get("op21_40"), "paired OP21-40 A D")

    per_dose = []
    qualifying = []
    for dose in SMOKE_DOSES:
        targets = []
        for kind, target in SMOKE_REQUIRED_CLOCKS:
            key = (dose, kind, target)
            if key not in by_key:
                raise ValueError(f"Missing smoke D_A row: {key}")
            value = by_key[key]
            targets.append(
                {
                    "clock_type": kind,
                    "target": target,
                    "value": value,
                    "passes": value >= SMOKE_THRESHOLD,
                }
            )
        passes = all(item["passes"] for item in targets)
        if passes:
            qualifying.append(dose)
        per_dose.append(
            {
                "nominal_p": dose,
                "dose_label": DOSE_LABELS[dose],
                "targets": targets,
                "passes_all_required_clocks": passes,
            }
        )
    applicable = eligible_design == "four_arm_smoke_screen"
    proceed = applicable and bool(qualifying)
    return {
        "rule_id": "op21_40_A_localization_did_v1",
        "applicable": applicable,
        "constants": {
            "block_seed": SMOKE_BLOCK_SEED,
            "doses": list(SMOKE_DOSES),
            "threshold": SMOKE_THRESHOLD,
            "comparison": "D_A = L_A(persistent_tag_T) - L_A(hidden_group_G)",
            "L_definition": "mean(selected two tags) - mean(unselected four tags), paired by source",
            "operation_band": "op21_40",
            "required_clocks": [{"clock_type": kind, "target": target} for kind, target in SMOKE_REQUIRED_CLOCKS],
            "require_same_dose_across_all_clocks": True,
            "threshold_uses_unrounded_values": True,
        },
        "per_dose": per_dose,
        "qualifying_doses": qualifying,
        "proceed_to_full_grid": proceed,
        "decision_status": (
            "proceed_to_full_grid"
            if proceed
            else "stop_after_smoke"
            if applicable
            else "not_applicable_full_grid_already_eligible"
        ),
    }


def _load_launch_authority(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    request = _require_dict(plan.get("request"), "plan request")
    request_launch = _require_dict(request.get("launch"), "plan request launch")
    intent_identity = _require_dict(request_launch.get("submission_intent"), "launch intent identity")
    intent_path = Path(str(intent_identity.get("path"))).expanduser().resolve()
    tokenizer_path = Path(str(request_launch.get("tokenizer_path"))).expanduser().resolve()
    eval_plan._require_read_only(intent_path, "Initial launch intent")
    raw_before, intent = eval_plan.read_json_object(intent_path, require_canonical=True)
    if eval_plan.file_identity(intent_path) != intent_identity:
        raise ValueError("Launch intent identity differs from the eval plan")
    if (
        intent.get("schema_version") != launch.SCHEMA_VERSION
        or intent.get("artifact_type") != launch.ARTIFACT_TYPE
        or intent.get("study_id") != launch.STUDY_ID
    ):
        raise ValueError("Initial launch intent has the wrong schema, artifact type, or study")
    payload_sha256 = intent.get("payload_without_self_hash_sha256")
    if not isinstance(payload_sha256, str) or eval_plan.SHA256_RE.fullmatch(payload_sha256) is None:
        raise ValueError("Initial launch intent has an invalid self hash")
    payload = dict(intent)
    payload.pop("payload_without_self_hash_sha256")
    if eval_plan.canonical_json_sha256(payload) != payload_sha256:
        raise ValueError("Initial launch intent self hash differs from its canonical payload")
    inputs = _require_dict(intent.get("inputs"), "initial launch intent inputs")
    expected_intent_path = Path(str(inputs.get("run_root"))).expanduser().resolve() / launch.INTENT_NAME
    if intent_path != expected_intent_path:
        raise ValueError("Initial launch intent is not adjacent to its recorded run root")
    if Path(str(inputs.get("tokenizer_path"))).expanduser().resolve() != tokenizer_path:
        raise ValueError("Eval plan tokenizer differs from the initial launch intent")

    recorded_implementation = _require_dict(intent.get("implementation"), "recorded launch implementation")
    implementation_path = Path(str(recorded_implementation.get("path"))).expanduser().resolve()
    if launch._repository_relative(implementation_path) != launch.CONTROL_PLANE_REPOSITORY_PATHS["launch_materializer"]:
        raise ValueError("Initial launch intent records the wrong implementation repository path")
    if eval_plan.file_identity(implementation_path) != recorded_implementation:
        raise ValueError("Recorded launch implementation identity changed")
    eval_plan._require_read_only(implementation_path, "Recorded launch implementation")
    decision = _require_dict(intent.get("preregistered_decision"), "initial launch decision")
    summary = launch._run_exact_validator(
        implementation_path,
        ["validate", "--intent", str(intent_path), "--tokenizer", str(tokenizer_path)],
    )
    expected_summary = {
        "command": "validate",
        "intent": intent_identity,
        "eligible_design": decision.get("eligible_design"),
        "eligible_arm_count": decision.get("eligible_arm_count"),
        "submission_performed": False,
    }
    if summary != expected_summary:
        raise ValueError("Recorded launch implementation returned a different validation summary")
    raw_after, replayed = eval_plan.read_json_object(intent_path, require_canonical=True)
    if raw_after != raw_before or replayed != intent or eval_plan.file_identity(intent_path) != intent_identity:
        raise RuntimeError("Initial launch intent changed while its recorded implementation was validating it")

    eligible_runs = _require_list(intent.get("eligible_runs"), "launch eligible runs")
    by_filename = {}
    for raw_run in eligible_runs:
        run = _require_dict(raw_run, "launch eligible run")
        filename = str(run.get("arm_filename"))
        if not filename or filename in by_filename:
            raise ValueError("Launch eligible run filenames are missing or duplicated")
        by_filename[filename] = run
    return intent, by_filename


def _load_postrun_authority(
    intent: dict[str, Any],
    initial_intent_identity: dict[str, Any],
) -> dict[str, Any]:
    inputs = _require_dict(intent.get("inputs"), "initial launch inputs")
    run_root = Path(str(inputs.get("run_root"))).expanduser().resolve()
    record = postrun_authority.validate_authority(run_root / postrun_authority.AUTHORITY_NAME)
    authority = record["authority"]
    bound_launch = _require_dict(authority.get("initial_launch_authority"), "post-run launch authority")
    if bound_launch.get("intent") != initial_intent_identity:
        raise ValueError("Post-run authority and evaluation plan bind different initial launch intents")
    decision = _require_dict(intent.get("preregistered_decision"), "initial launch decision")
    for field in ("eligible_design", "eligible_arm_count", "eligible_arm_filenames"):
        if bound_launch.get(field) != decision.get(field):
            raise ValueError(f"Post-run authority and initial launch intent differ on {field}")
    postrun_authority.validate_recorded_implementation(
        authority,
        name="result_analyzer",
        implementation_path=Path(__file__),
    )
    return record


def validate_terminal_receipts_with_recorded_dispatcher(
    plan_path: Path,
    validation: dict[str, Any],
    postrun: dict[str, Any],
) -> dict[str, Any]:
    authority = _require_dict(postrun.get("authority"), "post-run authority")
    source = _require_dict(authority.get("postrun_control_source"), "post-run control source")
    implementations = _require_dict(source.get("implementations"), "post-run implementations")
    recorded_dispatcher = _require_dict(implementations.get("eval_dispatcher"), "recorded eval dispatcher")
    execution_contract = _require_dict(authority.get("eval_execution_contract"), "eval execution contract")
    if _require_dict(execution_contract.get("dispatcher"), "contract eval dispatcher") != recorded_dispatcher:
        raise ValueError("Post-run authority records inconsistent evaluation dispatcher identities")
    dispatcher_path = Path(str(recorded_dispatcher.get("path"))).expanduser().resolve()
    if launch._repository_relative(dispatcher_path) != postrun_authority.REPOSITORY_PATHS["eval_dispatcher"]:
        raise ValueError("Post-run authority records the wrong evaluation dispatcher repository path")
    postrun_authority.validate_recorded_implementation(
        authority,
        name="eval_dispatcher",
        implementation_path=dispatcher_path,
    )

    initial_plan_identity = eval_plan.file_identity(plan_path)
    summary = launch._run_exact_validator(
        dispatcher_path,
        ["validate-terminals", "--plan", str(plan_path)],
    )
    expected_fields = {
        "command",
        "study_id",
        "plan",
        "state_root",
        "global_dispatch_intent",
        "terminal_receipt_count",
        "runner_produced_receipt_count",
        "scheduler_recovered_failure_count",
        "task_statuses",
        "attempts",
        "terminal_provenance",
        "terminal_provenance_payload_without_self_hash_sha256",
        "live_scheduler_recheck_performed",
        "live_scheduler_recheck_count",
        "scheduler_mutation",
        "receipt_mutation",
    }
    if set(summary) != expected_fields:
        raise ValueError("Recorded evaluation dispatcher returned the wrong terminal-validation schema")
    if summary["command"] != "validate-terminals" or summary["study_id"] != eval_plan.STUDY_ID:
        raise ValueError("Recorded evaluation dispatcher returned the wrong validation identity")
    if summary["plan"] != initial_plan_identity:
        raise ValueError("Recorded evaluation dispatcher validated a different plan")
    terminal_identity = _require_dict(summary["terminal_provenance"], "terminal provenance identity")
    terminal_path = Path(str(terminal_identity.get("path"))).expanduser().resolve()
    expected_terminal_path = Path(str(validation["plan"]["plan_root"])).resolve() / "terminal_provenance.json"
    if terminal_path != expected_terminal_path or eval_plan.file_identity(terminal_path) != terminal_identity:
        raise ValueError("Recorded evaluation dispatcher returned a different terminal provenance artifact")
    _, terminal_artifact = eval_plan.read_json_object(terminal_path, require_canonical=True)
    terminal_self_hash = terminal_artifact.get("payload_without_self_hash_sha256")
    if (
        not isinstance(terminal_self_hash, str)
        or terminal_self_hash != summary["terminal_provenance_payload_without_self_hash_sha256"]
    ):
        raise ValueError("Terminal provenance self hash differs from dispatcher validation")
    unhashed_terminal = dict(terminal_artifact)
    unhashed_terminal.pop("payload_without_self_hash_sha256", None)
    if eval_plan.canonical_json_sha256(unhashed_terminal) != terminal_self_hash:
        raise ValueError("Terminal provenance artifact has an invalid self hash")
    if summary["live_scheduler_recheck_performed"] is not False or summary["live_scheduler_recheck_count"] != 0:
        raise ValueError("Scientific analysis must use the durable offline terminal replay")
    state_root = Path(str(summary["state_root"])).expanduser()
    if not state_root.is_absolute() or state_root.name != validation["plan"]["plan_id"]:
        raise ValueError("Recorded evaluation dispatcher returned an invalid content-addressed state root")
    global_identity = _require_dict(summary["global_dispatch_intent"], "global dispatch intent identity")
    if eval_plan.file_identity(Path(str(global_identity.get("path")))) != global_identity:
        raise ValueError("Global evaluation dispatch intent changed after exact validation")

    historical_receipts = _require_dict(validation.get("receipts"), "historical receipt validation")
    historical_statuses = _require_dict(historical_receipts.get("task_statuses"), "historical task statuses")
    if summary["task_statuses"] != historical_statuses:
        raise ValueError("Dispatcher and historical planner disagree on terminal task statuses")
    receipt_count = _require_int(summary["terminal_receipt_count"], "terminal receipt count")
    runner_count = _require_int(summary["runner_produced_receipt_count"], "runner receipt count")
    recovered_count = _require_int(
        summary["scheduler_recovered_failure_count"],
        "scheduler-recovered receipt count",
    )
    if receipt_count != historical_receipts.get("receipt_count") or runner_count + recovered_count != receipt_count:
        raise ValueError("Dispatcher and historical planner disagree on terminal receipt coverage")
    if summary["scheduler_mutation"] is not False or summary["receipt_mutation"] is not False:
        raise ValueError("Terminal receipt validation must be read-only")

    attempts = _require_list(summary["attempts"], "terminal provenance attempts")
    if len(attempts) != receipt_count:
        raise ValueError("Terminal provenance attempt inventory has the wrong size")
    expected_attempt_fields = {
        "task_id",
        "attempt",
        "status",
        "provenance_kind",
        "terminal_receipt",
        "task_dispatch_intent",
        "batch_dispatch_intent",
        "global_dispatch_intent",
        "submission_receipt",
        "sealed_batch_script",
        "job_id",
        "comment",
        "job_name",
        "account",
        "qos",
        "submitted_batch_script_sha256",
        "terminal_allocation",
    }
    attempts_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_attempts = set()
    seen_jobs = set()
    for raw_attempt in attempts:
        attempt = _require_dict(raw_attempt, "terminal provenance attempt")
        if set(attempt) != expected_attempt_fields:
            raise ValueError("Terminal provenance attempt has the wrong exact schema")
        task_id = str(attempt["task_id"])
        attempt_number = _require_int(attempt["attempt"], "terminal attempt", minimum=1)
        key = (task_id, attempt_number)
        job_id = attempt["job_id"]
        if not isinstance(job_id, str) or re.fullmatch(r"[1-9][0-9]*", job_id) is None:
            raise ValueError("Terminal provenance attempt has an invalid scheduler job ID")
        if key in seen_attempts or job_id in seen_jobs:
            raise ValueError("Terminal provenance repeats a task attempt or scheduler job")
        seen_attempts.add(key)
        seen_jobs.add(job_id)
        if attempt["status"] not in eval_plan.TERMINAL_RECEIPT_STATUSES:
            raise ValueError("Terminal provenance attempt has a nonterminal status")
        provenance_kind = attempt["provenance_kind"]
        if provenance_kind not in {"pinned_runner", "scheduler_recovered_failure"}:
            raise ValueError("Terminal provenance attempt has an unknown producer")
        if provenance_kind == "scheduler_recovered_failure" and attempt["status"] == "succeeded":
            raise ValueError("Scheduler recovery cannot synthesize evaluation success")
        if attempt["global_dispatch_intent"] != global_identity:
            raise ValueError("Terminal provenance attempts do not share the sealed global intent")
        for field in (
            "terminal_receipt",
            "task_dispatch_intent",
            "batch_dispatch_intent",
            "submission_receipt",
            "sealed_batch_script",
        ):
            identity = _require_dict(attempt[field], f"terminal provenance {field}")
            if eval_plan.file_identity(Path(str(identity.get("path")))) != identity:
                raise ValueError(f"Terminal provenance {field} changed after exact validation")
        if attempt["submitted_batch_script_sha256"] != attempt["sealed_batch_script"]["sha256"]:
            raise ValueError("Terminal provenance submitted script differs from its sealed script")
        allocation = _require_dict(attempt["terminal_allocation"], "terminal allocation evidence")
        if set(allocation) != {
            "queried_at",
            "sacct_command",
            "sacct_stdout",
            "sacct_stdout_sha256",
            "submitted_batch_script_command",
            "record",
            "submitted_batch_script_sha256",
        }:
            raise ValueError("Terminal allocation evidence has the wrong exact schema")
        record = _require_dict(allocation["record"], "terminal allocation record")
        if set(record) != {"job_id", "comment", "job_name", "account", "qos", "state", "exit_code"}:
            raise ValueError("Terminal allocation record has the wrong exact schema")
        expected_record_identity = {
            "job_id": job_id,
            "comment": attempt["comment"],
            "job_name": attempt["job_name"],
            "account": attempt["account"],
            "qos": attempt["qos"],
        }
        if any(record[field] != value for field, value in expected_record_identity.items()):
            raise ValueError("Terminal allocation record differs from its dispatch identity")
        expected_sacct = [
            "sacct",
            "--noheader",
            "--parsable2",
            "--allocations",
            "--jobs",
            job_id,
            "--format=JobIDRaw%32,JobName%256,State%64,ExitCode%32,Account%128,QOS%128,Comment%256",
        ]
        if allocation["sacct_command"] != expected_sacct:
            raise ValueError("Terminal allocation evidence records a different sacct query")
        if allocation["submitted_batch_script_command"] != [
            "scontrol",
            "write",
            "batch_script",
            job_id,
            "-",
        ]:
            raise ValueError("Terminal allocation evidence records a different submitted-script query")
        if allocation["submitted_batch_script_sha256"] != attempt["sealed_batch_script"]["sha256"]:
            raise ValueError("Terminal allocation evidence records a different submitted script")
        attempts_by_task[task_id].append(attempt)
    if set(attempts_by_task) != set(historical_statuses):
        raise ValueError("Terminal provenance has the wrong task coverage")
    derived_statuses = {}
    for task_id, task_attempts in attempts_by_task.items():
        ordered = sorted(task_attempts, key=lambda item: item["attempt"])
        if [item["attempt"] for item in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError(f"Terminal provenance attempts are not contiguous for {task_id}")
        derived_statuses[task_id] = ordered[-1]["status"]
    if derived_statuses != historical_statuses:
        raise ValueError("Terminal provenance latest statuses differ from historical validation")
    artifact_projection = {
        "plan": summary["plan"],
        "state_root": summary["state_root"],
        "global_dispatch_intent": summary["global_dispatch_intent"],
        "terminal_receipt_count": summary["terminal_receipt_count"],
        "runner_produced_receipt_count": summary["runner_produced_receipt_count"],
        "scheduler_recovered_failure_count": summary["scheduler_recovered_failure_count"],
        "task_statuses": summary["task_statuses"],
        "attempts": summary["attempts"],
        "scheduler_mutation": summary["scheduler_mutation"],
        "receipt_mutation": summary["receipt_mutation"],
    }
    if any(terminal_artifact.get(field) != value for field, value in artifact_projection.items()):
        raise ValueError("Terminal provenance artifact differs from dispatcher validation")
    if eval_plan.file_identity(plan_path) != initial_plan_identity:
        raise RuntimeError("Evaluation plan changed while the recorded dispatcher validated receipts")
    return {
        "implementation": recorded_dispatcher,
        "identity": terminal_identity,
        "artifact": terminal_artifact,
        "summary": summary,
        "summary_sha256": eval_plan.canonical_json_sha256(summary),
    }


def _source_index_record(outcomes: TaskOutcomes) -> dict[str, Any]:
    tagged = [[operation, source_id, raw_id, seed] for operation, source_id, raw_id, seed in outcomes.tagged_keys]
    untagged = [[operation, index, source_id] for operation, index, source_id in outcomes.untagged_keys]
    return {
        "tagged_key_schema": ["operation", "source_sample_id", "source_raw_id", "request_seed"],
        "tagged_source_count": len(tagged),
        "tagged_sources": tagged,
        "tagged_source_sequence_sha256": eval_plan.canonical_json_sha256(tagged),
        "untagged_key_schema": ["operation", "row_index", "id"],
        "untagged_prompt_count": len(untagged),
        "untagged_prompts": untagged,
        "untagged_prompt_sequence_sha256": eval_plan.canonical_json_sha256(untagged),
    }


def build_analysis(plan_path: Path) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    validation = validate_plan_with_recorded_planner(plan_path)
    terminal_statuses = require_all_tasks_succeeded(validation)
    plan = validation["plan"]
    if plan.get("study_id") != eval_plan.STUDY_ID:
        raise ValueError("Known-cost result analyzer received the wrong study")
    initial_plan_identity = eval_plan.file_identity(plan_path)
    intent, launch_runs = _load_launch_authority(plan)
    design = str(_require_dict(intent.get("preregistered_decision"), "launch decision")["eligible_design"])
    initial_launch_intent = _require_dict(
        _require_dict(_require_dict(plan["request"], "plan request")["launch"], "request launch")["submission_intent"],
        "initial launch intent",
    )
    postrun = _load_postrun_authority(intent, initial_launch_intent)
    terminal_provenance = validate_terminal_receipts_with_recorded_dispatcher(
        plan_path,
        validation,
        postrun,
    )

    factors_by_run = {}
    for raw_run in _require_list(plan.get("runs"), "plan runs"):
        run = _require_dict(raw_run, "plan run")
        filename = str(_require_dict(run.get("launch_binding"), "run launch binding")["arm_filename"])
        if filename not in launch_runs:
            raise ValueError(f"Plan run is absent from launch intent: {filename}")
        factors = _derive_arm_factors(run, launch_runs[filename])
        if factors.run_id in factors_by_run:
            raise ValueError(f"Duplicate run ID: {factors.run_id}")
        factors_by_run[factors.run_id] = factors
    _validate_factor_inventory(list(factors_by_run.values()), design)
    training = training_readouts.build_training_readouts(
        plan,
        {run_id: factors.as_dict() for run_id, factors in factors_by_run.items()},
        postrun["authority"],
    )

    outcomes_by_task = {}
    compact_outcomes = []
    common_tagged_keys = None
    common_untagged_keys = None
    for raw_task in _require_list(plan.get("tasks"), "plan tasks"):
        task = _require_dict(raw_task, "plan task")
        task_id = str(task["task_id"])
        outcomes = load_task_outcomes(task)
        if common_tagged_keys is None:
            common_tagged_keys = outcomes.tagged_keys
            common_untagged_keys = outcomes.untagged_keys
        elif outcomes.tagged_keys != common_tagged_keys or outcomes.untagged_keys != common_untagged_keys:
            raise ValueError(f"Task {task_id} does not share the common source universe")
        outcomes_by_task[task_id] = outcomes
        compact_outcomes.append(compact_task_outcomes(task_id, outcomes))
    if not outcomes_by_task or common_tagged_keys is None or common_untagged_keys is None:
        raise ValueError("Plan has no completed evaluation tasks")

    occurrence_index = _occurrence_index(plan, outcomes_by_task)
    readouts = build_clock_readouts(plan, factors_by_run, occurrence_index)
    contrasts = build_contrasts(readouts, design)
    smoke = smoke_spend_decision(
        _require_list(contrasts["gate_dose_T_minus_G_by_block"], "G/T contrast rows"),
        eligible_design=design,
    )
    analysis_path = result_path_for_plan(plan)
    implementation = eval_plan.file_identity(Path(__file__))
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "analysis_id": ANALYSIS_ID,
        "study_id": eval_plan.STUDY_ID,
        "analysis_path": str(analysis_path),
        "provenance": {
            "analysis_implementation": {
                "repository_path": SCRIPT_REPOSITORY_PATH,
                **implementation,
            },
            "training_readout_implementation": training["provenance"]["implementation"],
            "eval_plan": initial_plan_identity,
            "recorded_eval_planner": validation["recorded_planner"],
            "recorded_eval_planner_validation_summary_sha256": validation["validation_summary_sha256"],
            "recorded_eval_dispatcher": terminal_provenance["implementation"],
            "recorded_eval_dispatcher_validation_summary_sha256": terminal_provenance["summary_sha256"],
            "terminal_provenance": terminal_provenance["identity"],
            "terminal_provenance_payload_without_self_hash_sha256": terminal_provenance["artifact"][
                "payload_without_self_hash_sha256"
            ],
            "initial_launch_intent": initial_launch_intent,
            "postrun_authority": postrun["identity"],
            "evaluator": plan["implementations"]["evaluator"],
            "strict_scorer": plan["implementations"]["strict_scorer"],
            "run_source_manifests": {
                run_id: _require_dict(run["launch_binding"], "run launch binding")["source_provenance_manifest"]
                for run_id, run in sorted(
                    ((str(raw["run_id"]), _require_dict(raw, "plan run")) for raw in plan["runs"]),
                )
            },
        },
        "authority": {
            "eligible_design": design,
            "initial_launch_intent_payload_sha256": intent["payload_without_self_hash_sha256"],
            "eligible_arm_filenames": intent["preregistered_decision"]["eligible_arm_filenames"],
            "postrun_authority": postrun["identity"],
        },
        "completeness": {
            "expected_task_count": len(plan["tasks"]),
            "expected_task_ids": sorted(terminal_statuses),
            "terminal_status_by_task": terminal_statuses,
            "all_tasks_succeeded": True,
            "receipt_count_including_retries": validation["receipts"]["receipt_count"],
            "runner_produced_receipt_count": terminal_provenance["summary"]["runner_produced_receipt_count"],
            "scheduler_recovered_failure_count": terminal_provenance["summary"]["scheduler_recovered_failure_count"],
            "terminal_receipt_provenance": terminal_provenance["summary"]["attempts"],
        },
        "eval_terminal_provenance": terminal_provenance["artifact"],
        "claim_scope": {
            "summary_type": "descriptive and model-conditional",
            "prompt_pairing_conditions_on_realized_trained_models": True,
            "treatment_effect_uncertainty_estimated": False,
            "causal_treatment_effect_claim_valid": False,
            "phase_transition_claim_valid": False,
            "hysteresis_claim_valid": False,
            "final_ceiling_claim_valid": False,
            "allowed_claim": "finite-time known-cost localization screen at sealed clocks",
            "training_diagnostics_are_descriptive": True,
        },
        "arm_factors": [item.as_dict() for item in sorted(factors_by_run.values(), key=lambda value: value.run_id)],
        "source_index": _source_index_record(outcomes_by_task[sorted(outcomes_by_task)[0]]),
        "task_source_outcomes": sorted(compact_outcomes, key=lambda item: item["task_id"]),
        "arm_clock_readouts": [readout.record for readout in readouts],
        "training_readouts": training,
        "contrasts": contrasts,
        "smoke_spend_decision": smoke,
        "validation_contract": {
            "python_api": "validate_analysis(pathlib.Path)",
            "command": [
                "uv",
                "run",
                "--no-sync",
                SCRIPT_REPOSITORY_PATH,
                "validate",
                "--analysis",
                str(analysis_path),
            ],
            "submission_performed": False,
        },
    }
    report["payload_without_self_hash_sha256"] = eval_plan.canonical_json_sha256(report)
    if eval_plan.file_identity(plan_path) != initial_plan_identity:
        raise ValueError("Evaluation plan changed while results were analyzed")
    for task_id, outcomes in outcomes_by_task.items():
        for shard in outcomes.result_artifact_identities:
            output_dir = Path(str(shard["output_dir"]))
            for name, expected in _require_dict(shard["artifacts"], "result artifacts").items():
                if eval_plan.file_identity(output_dir / name) != expected:
                    raise ValueError(f"Task {task_id} result artifact changed while results were analyzed: {name}")
    return report


def analyze_plan(plan_path: Path) -> dict[str, Any]:
    report = build_analysis(plan_path)
    analysis_path = Path(report["analysis_path"])
    eval_plan._write_bytes_once(analysis_path, eval_plan.canonical_json_bytes(report))
    return validate_analysis(analysis_path)


def validate_analysis(analysis_path: Path) -> dict[str, Any]:
    analysis_path = analysis_path.expanduser().resolve()
    eval_plan._require_read_only(analysis_path, "Known-cost result analysis")
    raw, report = eval_plan.read_json_object(analysis_path, require_canonical=True)
    if report.get("schema_version") != SCHEMA_VERSION or report.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Known-cost result analysis has the wrong schema or artifact type")
    if report.get("analysis_id") != ANALYSIS_ID or report.get("study_id") != eval_plan.STUDY_ID:
        raise ValueError("Known-cost result analysis has the wrong analysis or study identity")
    if report.get("analysis_path") != str(analysis_path):
        raise ValueError("Known-cost result analysis path differs")
    self_hash = report.get("payload_without_self_hash_sha256")
    payload = dict(report)
    payload.pop("payload_without_self_hash_sha256", None)
    if self_hash != eval_plan.canonical_json_sha256(payload):
        raise ValueError("Known-cost result analysis self-hash differs")
    provenance = _require_dict(report.get("provenance"), "analysis provenance")
    plan_identity = _require_dict(provenance.get("eval_plan"), "analysis eval plan")
    plan_path = Path(str(plan_identity["path"]))
    if eval_plan.file_identity(plan_path) != plan_identity:
        raise ValueError("Analysis eval plan identity changed")
    expected = build_analysis(plan_path)
    if expected != report:
        raise ValueError("Known-cost result analysis differs from full deterministic replay")
    if eval_plan.canonical_json_bytes(report) != raw:
        raise ValueError("Known-cost result analysis is not canonical")
    return {
        "analysis": report,
        "analysis_identity": eval_plan.file_identity(analysis_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--plan", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--analysis", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "analyze":
        result = analyze_plan(args.plan)
    else:
        result = validate_analysis(args.analysis)
    print(
        json.dumps(
            {
                "command": args.command,
                "analysis": result["analysis_identity"],
                "smoke_proceed_to_full_grid": result["analysis"]["smoke_spend_decision"]["proceed_to_full_grid"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
