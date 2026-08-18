#!/usr/bin/env python3
"""Materialize and independently replay sealed known-cost checkpoint evaluations."""

from __future__ import annotations

import argparse
import bisect
import copy
import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import figure3_eval
import materialize_known_cost_boundary_launch as launch_intent
import materialize_known_cost_tagged_eval as tagged_eval
import prepare_rl_checkpoint_eval as legacy_eval
import tomli_w

DATA_SOURCES = legacy_eval.DATA_SOURCES

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_known_cost_checkpoint_eval_plan"
REQUEST_ARTIFACT_TYPE = "rsci_known_cost_checkpoint_eval_request"
RECEIPT_ARTIFACT_TYPE = "rsci_known_cost_eval_attempt_receipt"
STUDY_ID = "verifier-defect-known-cost-boundary-v1"
PLAN_IMPLEMENTATION_ID = "rsci-known-cost-checkpoint-eval-plan-v1"
PLAN_NAME = "plan.json"
MAX_CHECKPOINT_STEP = 1_500
OPERATIONS = tuple(range(11, 46))
EXAMPLES_PER_OPERATION = 200
TAG_COUNT = 6
DEFAULT_REQUEST_SEED = 20_260_807
DEFAULT_OPTIMIZER_TARGETS = (375, 750, 1_500)
DEFAULT_RAW_GROUP_TARGETS = (3_000, 6_000, 12_000)
DEFAULT_TAGGED_DATA_DIR = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/known-cost-boundary-v1/eval-tagged")
DEFAULT_EVAL_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/evals/verifier-defect-known-cost-boundary-v1")
SCRIPT_REPOSITORY_PATH = "user/tianhaowu/rsci/materialize_known_cost_eval_plan.py"
EVALUATOR_REPOSITORY_PATH = "user/tianhaowu/rsci/figure3_eval.py"
SCORER_REPOSITORY_PATH = "user/tianhaowu/rsci/solution_graph.py"
TAGGED_MATERIALIZER_REPOSITORY_PATH = "user/tianhaowu/rsci/materialize_known_cost_tagged_eval.py"
RUN_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
STEP_DIR_RE = re.compile(r"step_([0-9]+)")
RECEIPT_NAME_RE = re.compile(r"attempt_([0-9]{4})\.json")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
TERMINAL_RECEIPT_STATUSES = frozenset({"succeeded", "failed", "cancelled", "preempted"})
SUCCESS_ARTIFACT_NAMES = (
    "generation_manifest.json",
    "generation_completion.json",
    "generations.jsonl",
    "strict_results.jsonl",
    "metrics.json",
)


@dataclass(frozen=True)
class ConfigArtifact:
    path: Path
    content: bytes

    def identity(self) -> dict[str, Any]:
        return bytes_identity(self.path, self.content)


@dataclass(frozen=True)
class PlanBuild:
    manifest: dict[str, Any]
    manifest_bytes: bytes
    plan_path: Path
    config_artifacts: tuple[ConfigArtifact, ...]


def canonical_json_bytes(value: object, *, indent: int | None = 2) -> bytes:
    options: dict[str, Any] = {
        "ensure_ascii": False,
        "allow_nan": False,
        "sort_keys": True,
    }
    if indent is None:
        options["separators"] = (",", ":")
    else:
        options["indent"] = indent
    return (json.dumps(value, **options) + "\n").encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value, indent=None).rstrip(b"\n")).hexdigest()


def bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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


def bytes_identity(path: Path, content: bytes) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    return {
        "path": str(resolved),
        "size_bytes": len(content),
        "sha256": bytes_sha256(content),
    }


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _reject_nonfinite_constant(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def read_json_object(path: Path, *, require_canonical: bool = False) -> tuple[bytes, dict[str, Any]]:
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
    if require_canonical and raw != canonical_json_bytes(value):
        raise ValueError(f"JSON artifact is not canonical: {resolved}")
    return raw, value


def read_toml(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    with resolved.open("rb") as handle:
        return tomllib.load(handle)


def directory_identity(path: Path, *, require_stable: bool) -> dict[str, Any]:
    configured = path.expanduser()
    if not configured.is_absolute():
        raise ValueError(f"Model path must be absolute: {configured}")
    resolved = configured.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(resolved)
    if require_stable and not (resolved / "STABLE").is_file():
        raise ValueError(f"Model directory has no STABLE marker: {resolved}")
    if not (resolved / "config.json").is_file():
        raise ValueError(f"Model directory has no config.json: {resolved}")

    paths = sorted(
        (candidate for candidate in resolved.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(resolved).as_posix(),
    )
    if not paths or not any(path.suffix == ".safetensors" for path in paths):
        raise ValueError(f"Model directory has no safetensors weights: {resolved}")
    inventory = []
    for candidate in paths:
        entry: dict[str, Any] = {
            "path": candidate.relative_to(resolved).as_posix(),
            "size_bytes": candidate.stat().st_size,
            "sha256": file_sha256(candidate),
        }
        if candidate.is_symlink():
            entry["symlink_target"] = os.readlink(candidate)
        inventory.append(entry)
    return {
        "path": str(configured),
        "resolved_path": str(resolved),
        "file_count": len(inventory),
        "size_bytes": sum(item["size_bytes"] for item in inventory),
        "inventory": inventory,
        "inventory_sha256": canonical_json_sha256(inventory),
    }


def _require_int(value: object, label: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        interval = f"[{minimum}, {maximum}]" if maximum is not None else f"[{minimum}, infinity)"
        raise ValueError(f"{label} must lie in {interval}")
    return value


def _require_int_list(
    value: object,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    values = tuple(_require_int(item, f"{label} item", minimum=minimum, maximum=maximum) for item in value)
    if tuple(sorted(set(values))) != values:
        raise ValueError(f"{label} must be strictly increasing and unique")
    return values


def eligible_runs_from_launch_intent(intent: dict[str, Any]) -> list[dict[str, Any]]:
    if intent.get("schema_version") != launch_intent.SCHEMA_VERSION:
        raise ValueError("Known-cost launch intent has the wrong schema version")
    if intent.get("artifact_type") != launch_intent.ARTIFACT_TYPE or intent.get("study_id") != STUDY_ID:
        raise ValueError("Known-cost launch intent has the wrong artifact or study identity")
    decision = intent.get("preregistered_decision")
    if not isinstance(decision, dict):
        raise ValueError("Known-cost launch intent has no preregistered decision")
    filenames = decision.get("eligible_arm_filenames")
    count = decision.get("eligible_arm_count")
    raw_runs = intent.get("eligible_runs")
    if (
        not isinstance(filenames, list)
        or not filenames
        or any(not isinstance(filename, str) or not filename.endswith(".toml") for filename in filenames)
        or len(filenames) != len(set(filenames))
        or count != len(filenames)
        or not isinstance(raw_runs, list)
        or len(raw_runs) != len(filenames)
    ):
        raise ValueError("Known-cost launch intent has an invalid eligible-run inventory")
    by_filename = {}
    for index, raw_run in enumerate(raw_runs):
        if not isinstance(raw_run, dict):
            raise ValueError(f"Known-cost launch eligible_runs[{index}] is not an object")
        filename = raw_run.get("arm_filename")
        if not isinstance(filename, str) or filename in by_filename:
            raise ValueError("Known-cost launch eligible runs have missing or duplicate arm filenames")
        by_filename[filename] = raw_run
    if set(by_filename) != set(filenames):
        raise ValueError("Known-cost launch eligible runs do not exactly cover the preregistered decision")

    runs = []
    run_ids = set()
    run_dirs = set()
    for filename in filenames:
        raw_run = by_filename[filename]
        run_id = Path(filename).stem.replace("_", "-")
        if RUN_ID_RE.fullmatch(run_id) is None or run_id in run_ids:
            raise ValueError(f"Cannot derive one unique safe run ID from {filename!r}")
        run_dir = Path(str(raw_run.get("output_dir"))).expanduser().resolve()
        if not run_dir.is_dir() or run_dir in run_dirs:
            raise ValueError(f"Known-cost eligible run directory is missing or duplicated: {run_dir}")
        resolved_configs = raw_run.get("resolved_configs")
        source = raw_run.get("source_provenance")
        sbatch = raw_run.get("sbatch")
        if not isinstance(resolved_configs, dict) or not isinstance(source, dict) or not isinstance(sbatch, dict):
            raise ValueError(f"Known-cost eligible run {filename} lacks sealed runtime identities")
        required_configs = {"trainer", "orchestrator", "inference"}
        if set(resolved_configs) != required_configs or not isinstance(source.get("manifest"), dict):
            raise ValueError(f"Known-cost eligible run {filename} has an incomplete sealed identity")
        run_ids.add(run_id)
        run_dirs.add(run_dir)
        runs.append(
            {
                "run_id": run_id,
                "run_dir": str(run_dir),
                "arm_filename": filename,
                "launch_record_sha256": canonical_json_sha256(raw_run),
                "resolved_configs": copy.deepcopy(resolved_configs),
                "source_provenance_manifest": copy.deepcopy(source["manifest"]),
                "sbatch": copy.deepcopy(sbatch),
            }
        )
    return sorted(runs, key=lambda run: run["run_id"])


def load_request(spec_path: Path) -> dict[str, Any]:
    raw, spec = read_json_object(spec_path)
    allowed = {
        "schema_version",
        "artifact_type",
        "study_id",
        "request_seed",
        "optimizer_step_targets",
        "raw_group_targets",
        "tagged_data_dir",
        "launch_intent",
    }
    unexpected = sorted(set(spec) - allowed)
    if unexpected:
        raise ValueError(f"Known-cost eval request has unknown fields: {unexpected}")
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Known-cost eval request has the wrong schema version")
    if spec.get("artifact_type") != REQUEST_ARTIFACT_TYPE:
        raise ValueError("Known-cost eval request has the wrong artifact type")
    if spec.get("study_id") != STUDY_ID:
        raise ValueError("Known-cost eval request has the wrong study identity")
    request_seed = _require_int(
        spec.get("request_seed", DEFAULT_REQUEST_SEED),
        "request_seed",
        maximum=2**63 - 1,
    )
    if request_seed != DEFAULT_REQUEST_SEED:
        raise ValueError(f"request_seed must equal the frozen common seed {DEFAULT_REQUEST_SEED}")
    optimizer_targets = _require_int_list(
        spec.get("optimizer_step_targets", list(DEFAULT_OPTIMIZER_TARGETS)),
        "optimizer_step_targets",
        minimum=1,
        maximum=MAX_CHECKPOINT_STEP,
    )
    raw_targets = _require_int_list(
        spec.get("raw_group_targets", list(DEFAULT_RAW_GROUP_TARGETS)),
        "raw_group_targets",
        minimum=1,
        maximum=10**9,
    )
    if optimizer_targets != DEFAULT_OPTIMIZER_TARGETS:
        raise ValueError(f"optimizer_step_targets must equal the preregistered {DEFAULT_OPTIMIZER_TARGETS}")
    if raw_targets != DEFAULT_RAW_GROUP_TARGETS:
        raise ValueError(f"raw_group_targets must equal the preregistered {DEFAULT_RAW_GROUP_TARGETS}")
    tagged_data_dir = Path(spec.get("tagged_data_dir", DEFAULT_TAGGED_DATA_DIR)).expanduser().resolve()
    if not tagged_data_dir.is_dir():
        raise FileNotFoundError(tagged_data_dir)
    configured_launch_intent = spec.get("launch_intent")
    if not isinstance(configured_launch_intent, str) or not configured_launch_intent:
        raise ValueError("Known-cost eval request must name the immutable launch_intent")
    launch_path = Path(configured_launch_intent).expanduser().resolve()
    _, untrusted_intent = read_json_object(launch_path, require_canonical=True)
    launch_inputs = untrusted_intent.get("inputs")
    if not isinstance(launch_inputs, dict) or not isinstance(launch_inputs.get("tokenizer_path"), str):
        raise ValueError("Known-cost launch intent does not name its validation tokenizer")
    launch_tokenizer = Path(launch_inputs["tokenizer_path"]).expanduser().resolve()
    validated_launch = launch_intent.validate_intent(launch_path, tokenizer_path=launch_tokenizer)
    intent = validated_launch["intent"]
    launch_intent.validate_control_plane_implementation(
        intent,
        name="eval_planner",
        implementation_path=Path(__file__),
    )
    runs = eligible_runs_from_launch_intent(intent)
    decision = intent["preregistered_decision"]
    return {
        "spec": {
            **file_identity(spec_path),
            "raw_sha256": bytes_sha256(raw),
        },
        "schema_version": SCHEMA_VERSION,
        "artifact_type": REQUEST_ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "request_seed": request_seed,
        "optimizer_step_targets": list(optimizer_targets),
        "raw_group_targets": list(raw_targets),
        "tagged_data_dir": str(tagged_data_dir),
        "launch": {
            "submission_intent": validated_launch["identity"],
            "payload_without_self_hash_sha256": intent["payload_without_self_hash_sha256"],
            "tokenizer_path": str(launch_tokenizer),
            "eligible_design": decision["eligible_design"],
            "eligible_arm_count": decision["eligible_arm_count"],
            "eligible_arm_filenames": decision["eligible_arm_filenames"],
            "launch_source": intent["launch_source"],
        },
        "runs": runs,
    }


def _count_jsonl_rows(path: Path) -> int:
    rows = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank JSONL row at {path}:{line_number}")
            rows += 1
    return rows


def _untagged_dataset_path(operation: int) -> Path:
    matches = [
        Path(source["data_dir"]) / f"op{operation}-{EXAMPLES_PER_OPERATION}.jsonl"
        for source in DATA_SOURCES
        if int(source["min_op"]) <= operation <= int(source["max_op"])
    ]
    if len(matches) != 1:
        raise ValueError(f"Untagged DATA_SOURCES map OP{operation} to {len(matches)} paths")
    return matches[0].expanduser().resolve()


def _tagged_seed_sequence(path: Path, operation: int, request_seed: int) -> list[tuple[int, str, int]]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank tagged JSONL row at {path}:{line_number}")
            row = json.loads(line, object_pairs_hook=_object_without_duplicate_keys)
            if not isinstance(row, dict):
                raise ValueError(f"Tagged row is not an object at {path}:{line_number}")
            if row.get("op") != operation:
                raise ValueError(f"Tagged row has wrong operation at {path}:{line_number}")
            source_id = row.get("source_sample_id")
            if not isinstance(source_id, str) or not source_id:
                raise ValueError(f"Tagged row has invalid source_sample_id at {path}:{line_number}")
            by_source[source_id].append(row)
    if len(by_source) != EXAMPLES_PER_OPERATION:
        raise ValueError(f"OP{operation} tagged collection has {len(by_source)} sources")

    sequence = []
    for source_id, rows in by_source.items():
        tags = sorted(row.get("neutral_tag_index") for row in rows)
        if tags != list(range(TAG_COUNT)):
            raise ValueError(f"OP{operation} source {source_id} does not have exactly six tags")
        seeds = {
            figure3_eval.derive_request_seed(
                row,
                request_seed,
                request_seed_mode=figure3_eval.KNOWN_COST_REQUEST_SEED_MODE,
            )
            for row in rows
        }
        if len(seeds) != 1:
            raise RuntimeError(f"OP{operation} source {source_id} tags do not share one request seed")
        sequence.append((operation, source_id, seeds.pop()))
    return sequence


def evaluation_data_identity(tagged_data_dir: Path, request_seed: int) -> tuple[dict[str, Any], str]:
    untagged = []
    tagged = []
    tokenizer_identity: dict[str, Any] | None = None
    tag_contract: dict[str, Any] | None = None
    sidecar_bytes = []
    seed_sequence: list[tuple[int, str, int]] = []
    for operation in OPERATIONS:
        untagged_path = _untagged_dataset_path(operation)
        untagged_rows = _count_jsonl_rows(untagged_path)
        if untagged_rows != EXAMPLES_PER_OPERATION:
            raise ValueError(f"OP{operation} untagged dataset has {untagged_rows} rows")
        untagged_identity = {"operation": operation, "rows": untagged_rows, **file_identity(untagged_path)}
        untagged.append(untagged_identity)

        output_path = (tagged_data_dir / f"op{operation}-1200.jsonl").resolve()
        manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
        validated = tagged_eval.validate_tagged_eval(
            manifest_path=manifest_path,
            output_path=output_path,
        )
        manifest = validated["manifest"]
        counts = manifest.get("counts")
        if not isinstance(counts, dict):
            raise ValueError(f"OP{operation} tagged sidecar has no counts")
        expected_tag_counts = {str(index): EXAMPLES_PER_OPERATION for index in range(TAG_COUNT)}
        if (
            counts.get("source_rows") != EXAMPLES_PER_OPERATION
            or counts.get("clone_rows") != EXAMPLES_PER_OPERATION * TAG_COUNT
            or counts.get("clone_by_tag") != expected_tag_counts
            or counts.get("source_by_operation") != {str(operation): EXAMPLES_PER_OPERATION}
        ):
            raise ValueError(f"OP{operation} tagged sidecar does not describe 200 paired sources")
        input_identity = manifest.get("input")
        if not isinstance(input_identity, dict):
            raise ValueError(f"OP{operation} tagged sidecar has no source identity")
        for field in ("sha256", "size_bytes", "rows"):
            if input_identity.get(field) != untagged_identity.get(field):
                raise ValueError(f"OP{operation} tagged source differs from the untagged held-out shard")
        observed_tokenizer = manifest.get("tag_tokenization")
        observed_contract = manifest.get("tag_contract")
        if tokenizer_identity is None:
            tokenizer_identity = copy.deepcopy(observed_tokenizer)
            tag_contract = copy.deepcopy(observed_contract)
        elif observed_tokenizer != tokenizer_identity or observed_contract != tag_contract:
            raise ValueError(f"OP{operation} changed the tagged tokenizer or literal tag contract")
        raw_manifest = manifest_path.read_bytes()
        sidecar_bytes.append(raw_manifest)
        tagged.append(
            {
                "operation": operation,
                "output": file_identity(output_path),
                "sidecar": file_identity(manifest_path),
                "source": input_identity,
                "manifest_sha256": validated["manifest_sha256"],
            }
        )
        seed_sequence.extend(_tagged_seed_sequence(output_path, operation, request_seed))

    if tokenizer_identity is None or tag_contract is None:
        raise RuntimeError("Tagged data identity is unexpectedly empty")
    if tokenizer_identity.get("equal_token_counts") is not True:
        raise ValueError("Known-cost tag prefixes do not have equal token counts")
    if tokenizer_identity.get("common_token_count") != 13:
        raise ValueError("Known-cost tag prefixes no longer have the preregistered 13-token length")
    if len(seed_sequence) != len(OPERATIONS) * EXAMPLES_PER_OPERATION:
        raise RuntimeError("Paired seed sequence does not contain 7,000 held-out sources")
    seeds = [record[2] for record in seed_sequence]
    if len(seeds) != len(set(seeds)):
        raise ValueError("Paired request-seed derivation collided across held-out sources")
    seed_sequence_sha256 = canonical_json_sha256(seed_sequence)
    data = {
        "operations": list(OPERATIONS),
        "examples_per_operation": EXAMPLES_PER_OPERATION,
        "untagged": {
            "data_sources": copy.deepcopy(DATA_SOURCES),
            "datasets": untagged,
            "prompt_count": len(OPERATIONS) * EXAMPLES_PER_OPERATION,
        },
        "tagged": {
            "data_dir": str(tagged_data_dir),
            "datasets": tagged,
            "source_prompt_count": len(OPERATIONS) * EXAMPLES_PER_OPERATION,
            "clone_prompt_count": len(OPERATIONS) * EXAMPLES_PER_OPERATION * TAG_COUNT,
            "sidecar_bundle_sha256": bytes_sha256(b"".join(sidecar_bytes)),
            "tag_contract": tag_contract,
            "tokenizer": tokenizer_identity,
        },
    }
    return data, seed_sequence_sha256


def _resolve_audit_paths(run_dir: Path, orchestrator: dict[str, Any]) -> tuple[Path, Path]:
    configured_output = orchestrator.get("output_dir")
    candidates = [run_dir / "rollouts"]
    if isinstance(configured_output, str) and configured_output:
        candidates.append(Path(configured_output).expanduser().resolve() / "rollouts")
    pairs = []
    for root in dict.fromkeys(path.resolve() for path in candidates):
        group_stats = root / "train_group_stats.jsonl"
        attempts = root / "train_batch_attempts.jsonl"
        if group_stats.is_file() and attempts.is_file():
            pairs.append((group_stats, attempts))
        elif group_stats.exists() or attempts.exists():
            raise FileNotFoundError(f"Incomplete training audit pair under {root}")
    if len(pairs) != 1:
        raise ValueError(f"Expected exactly one training audit pair for {run_dir}, found {len(pairs)}")
    return pairs[0]


def _load_clock_audit(group_stats_path: Path, attempts_path: Path) -> dict[str, Any]:
    labels = []
    group_ids = set()
    with group_stats_path.open("r", encoding="utf-8") as handle:
        for row_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank group audit record at {group_stats_path}:{row_number}")
            row = json.loads(line, object_pairs_hook=_object_without_duplicate_keys)
            if not isinstance(row, dict):
                raise ValueError(f"Group audit record is not an object at {group_stats_path}:{row_number}")
            if row.get("group_index") != row_number:
                raise ValueError(f"Group audit index is not contiguous at {group_stats_path}:{row_number}")
            group_id = row.get("group_id")
            if not isinstance(group_id, str) or not group_id or group_id in group_ids:
                raise ValueError(f"Group audit has an invalid or duplicate group_id at row {row_number}")
            group_ids.add(group_id)
            label = _require_int(
                row.get("finalized_before_optimizer_step"),
                f"group audit row {row_number} finalized_before_optimizer_step",
            )
            if labels and label < labels[-1]:
                raise ValueError(f"Group audit optimizer labels decrease at row {row_number}")
            labels.append(label)

    shipped_steps = set()
    previous_optimizer_step = -1
    with attempts_path.open("r", encoding="utf-8") as handle:
        for row_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank batch audit record at {attempts_path}:{row_number}")
            row = json.loads(line, object_pairs_hook=_object_without_duplicate_keys)
            if not isinstance(row, dict):
                raise ValueError(f"Batch audit record is not an object at {attempts_path}:{row_number}")
            if row.get("batch_attempt") != row_number:
                raise ValueError(f"Batch audit index is not contiguous at {attempts_path}:{row_number}")
            optimizer_step = _require_int(row.get("optimizer_step"), f"batch audit row {row_number} optimizer_step")
            if optimizer_step < previous_optimizer_step:
                raise ValueError(f"Batch audit optimizer steps decrease at row {row_number}")
            previous_optimizer_step = optimizer_step
            eligible = row.get("eligible_to_ship")
            if not isinstance(eligible, bool):
                raise ValueError(f"Batch audit eligible_to_ship is not boolean at row {row_number}")
            if eligible:
                if optimizer_step in shipped_steps:
                    raise ValueError(f"Optimizer step {optimizer_step} was shipped more than once")
                shipped_steps.add(optimizer_step)
    return {
        "group_labels": tuple(labels),
        "shipped_steps": frozenset(shipped_steps),
        "group_stats": file_identity(group_stats_path),
        "batch_attempts": file_identity(attempts_path),
    }


def raw_groups_before_step(group_labels: tuple[int, ...], step: int) -> int:
    _require_int(step, "checkpoint step", maximum=MAX_CHECKPOINT_STEP)
    return bisect.bisect_left(group_labels, step)


def resolve_raw_clock_bracket(
    checkpoint_exposures: list[dict[str, int]],
    target_raw_groups: int,
) -> dict[str, Any]:
    target = _require_int(target_raw_groups, "raw-group target", minimum=1)
    if not checkpoint_exposures:
        raise ValueError("Checkpoint exposure grid is empty")
    points = [
        {
            "step": _require_int(point.get("step"), "checkpoint exposure step", maximum=MAX_CHECKPOINT_STEP),
            "raw_groups": _require_int(point.get("raw_groups"), "checkpoint exposure raw_groups"),
        }
        for point in checkpoint_exposures
    ]
    if [point["step"] for point in points] != sorted({point["step"] for point in points}):
        raise ValueError("Checkpoint exposure steps must be strictly increasing and unique")
    if points[0] != {"step": 0, "raw_groups": 0}:
        raise ValueError("Checkpoint exposure grid must start at step 0 and zero raw groups")
    if any(left["raw_groups"] > right["raw_groups"] for left, right in zip(points, points[1:], strict=False)):
        raise ValueError("Checkpoint raw-group exposure must be nondecreasing")

    exact = [point for point in points if point["raw_groups"] == target]
    if len(exact) > 1:
        raise ValueError(
            f"Raw-group target {target} is exact at multiple retained checkpoints; the policy is ambiguous"
        )
    if exact:
        return {
            "target_raw_groups": target,
            "mode": "exact",
            "lower": exact[0],
            "upper": exact[0],
            "analysis_rule": "use the exact retained checkpoint; interpolation weight is zero",
        }

    lower_candidates = [point for point in points if point["raw_groups"] < target]
    upper_candidates = [point for point in points if point["raw_groups"] > target]
    if not lower_candidates or not upper_candidates:
        interval = [points[0]["raw_groups"], points[-1]["raw_groups"]]
        raise ValueError(f"Raw-group target {target} is not bracketed by retained checkpoints {interval}")
    lower_count = max(point["raw_groups"] for point in lower_candidates)
    upper_count = min(point["raw_groups"] for point in upper_candidates)
    lower = max((point for point in lower_candidates if point["raw_groups"] == lower_count), key=lambda p: p["step"])
    upper = min((point for point in upper_candidates if point["raw_groups"] == upper_count), key=lambda p: p["step"])
    if lower["step"] >= upper["step"]:
        raise RuntimeError(f"Invalid raw-clock bracket for target {target}: {lower}, {upper}")
    return {
        "target_raw_groups": target,
        "mode": "bracketed",
        "lower": lower,
        "upper": upper,
        "interpolation_weight_upper": (target - lower_count) / (upper_count - lower_count),
        "analysis_rule": (
            "evaluate both retained endpoints and interpolate on the raw-group axis; neither endpoint is "
            "reported or relabeled as the target"
        ),
    }


def discover_retained_steps(run_dir: Path) -> list[dict[str, Any]]:
    weights_dir = run_dir / "weights"
    if not weights_dir.is_dir():
        raise FileNotFoundError(weights_dir)
    records = []
    observed_steps = set()
    for path in sorted(weights_dir.iterdir(), key=lambda candidate: candidate.name):
        match = STEP_DIR_RE.fullmatch(path.name)
        if match is None:
            continue
        step = int(match.group(1))
        if step == 0 or step > MAX_CHECKPOINT_STEP:
            continue
        if step in observed_steps:
            raise ValueError(f"Duplicate retained checkpoint step {step} under {weights_dir}")
        observed_steps.add(step)
        if not path.is_dir() or not (path / "STABLE").is_file():
            raise ValueError(f"Retained checkpoint is not stable: {path}")
        records.append(
            {
                "step": step,
                "path": str(path.resolve()),
                "stable_marker": file_identity(path / "STABLE"),
            }
        )
    records.sort(key=lambda record: record["step"])
    if not records:
        raise ValueError(f"No stable retained checkpoints through step {MAX_CHECKPOINT_STEP}: {weights_dir}")
    return records


def _validate_training_contract(
    run_id: str,
    trainer: dict[str, Any],
    orchestrator: dict[str, Any],
    optimizer_targets: tuple[int, ...],
    raw_targets: tuple[int, ...],
) -> tuple[Path, Path]:
    max_optimizer = max(optimizer_targets)
    max_raw = max(raw_targets)
    if _require_int(trainer.get("max_steps"), f"{run_id} trainer.max_steps", minimum=1) < max_optimizer:
        raise ValueError(f"{run_id} trainer.max_steps does not cover optimizer targets")
    ckpt = trainer.get("ckpt")
    if not isinstance(ckpt, dict) or ckpt.get("interval") != 25 or ckpt.get("keep_interval") != 25:
        raise ValueError(f"{run_id} must retain every 25-step checkpoint")
    model = trainer.get("model")
    tokenizer = trainer.get("tokenizer")
    if not isinstance(model, dict) or not isinstance(model.get("name"), str):
        raise ValueError(f"{run_id} trainer config has no model.name")
    if not isinstance(tokenizer, dict) or not isinstance(tokenizer.get("name"), str):
        raise ValueError(f"{run_id} trainer config has no tokenizer.name")

    if orchestrator.get("save_train_group_stats") is not True:
        raise ValueError(f"{run_id} must enable save_train_group_stats")
    stop_when = orchestrator.get("stop_when")
    if not isinstance(stop_when, dict):
        raise ValueError(f"{run_id} orchestrator config has no stop_when contract")
    if _require_int(stop_when.get("min_steps"), f"{run_id} stop_when.min_steps") < max_optimizer:
        raise ValueError(f"{run_id} stop_when.min_steps does not cover optimizer targets")
    if _require_int(stop_when.get("min_finalized_groups"), f"{run_id} stop_when.min_finalized_groups") < max_raw:
        raise ValueError(f"{run_id} stop_when.min_finalized_groups does not cover raw-group targets")
    return Path(model["name"]).expanduser().resolve(), Path(tokenizer["name"]).expanduser().resolve()


def _roles_for_step(
    step: int,
    optimizer_targets: list[dict[str, int]],
    raw_targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    roles = []
    if step == 0:
        roles.append({"clock": "initialization", "role": "exact", "target": 0})
    roles.extend(
        {"clock": "optimizer_step", "role": "exact", "target": target["target_step"]}
        for target in optimizer_targets
        if target["checkpoint_step"] == step
    )
    for target in raw_targets:
        if target["lower"]["step"] == step:
            roles.append(
                {
                    "clock": "raw_groups",
                    "role": "exact" if target["mode"] == "exact" else "lower_bracket",
                    "target": target["target_raw_groups"],
                }
            )
        if target["mode"] != "exact" and target["upper"]["step"] == step:
            roles.append({"clock": "raw_groups", "role": "upper_bracket", "target": target["target_raw_groups"]})
    return sorted(roles, key=lambda role: (role["clock"], role["target"], role["role"]))


def inspect_run(
    request_run: dict[str, Any],
    optimizer_targets: tuple[int, ...],
    raw_targets: tuple[int, ...],
) -> tuple[dict[str, Any], dict[int, Path], Path]:
    run_id = request_run["run_id"]
    run_dir = Path(request_run["run_dir"]).resolve()
    trainer_path = run_dir / "configs" / "trainer.toml"
    orchestrator_path = run_dir / "configs" / "orchestrator.toml"
    inference_path = run_dir / "configs" / "inference.toml"
    resolved_config_identities = {
        "trainer": file_identity(trainer_path),
        "orchestrator": file_identity(orchestrator_path),
        "inference": file_identity(inference_path),
    }
    if resolved_config_identities != request_run.get("resolved_configs"):
        raise ValueError(f"{run_id} resolved configs differ from the immutable launch intent")
    source_manifest = request_run.get("source_provenance_manifest")
    if not isinstance(source_manifest, dict) or not isinstance(source_manifest.get("path"), str):
        raise ValueError(f"{run_id} launch intent has no source-provenance manifest identity")
    if file_identity(Path(source_manifest["path"])) != source_manifest:
        raise ValueError(f"{run_id} source-provenance manifest differs from the immutable launch intent")
    sbatch = request_run.get("sbatch")
    if not isinstance(sbatch, dict) or not isinstance(sbatch.get("path"), str):
        raise ValueError(f"{run_id} launch intent has no SLURM identity")
    if file_identity(Path(sbatch["path"])) != sbatch:
        raise ValueError(f"{run_id} SLURM artifact differs from the immutable launch intent")
    trainer = read_toml(trainer_path)
    orchestrator = read_toml(orchestrator_path)
    if not inference_path.is_file():
        raise FileNotFoundError(inference_path)
    base_model, tokenizer_path = _validate_training_contract(
        run_id,
        trainer,
        orchestrator,
        optimizer_targets,
        raw_targets,
    )
    retained = discover_retained_steps(run_dir)
    retained_by_step = {record["step"]: Path(record["path"]) for record in retained}
    missing_optimizer = sorted(set(optimizer_targets) - set(retained_by_step))
    if missing_optimizer:
        raise ValueError(f"{run_id} lacks exact optimizer target checkpoints: {missing_optimizer}")

    group_stats_path, attempts_path = _resolve_audit_paths(run_dir, orchestrator)
    audit = _load_clock_audit(group_stats_path, attempts_path)
    exposure_grid = [{"step": 0, "raw_groups": 0}]
    exposure_grid.extend(
        {
            "step": record["step"],
            "raw_groups": raw_groups_before_step(audit["group_labels"], record["step"]),
        }
        for record in retained
    )
    raw_clock_targets = [resolve_raw_clock_bracket(exposure_grid, target) for target in raw_targets]
    optimizer_clock_targets = [{"target_step": target, "checkpoint_step": target} for target in optimizer_targets]
    selected_steps = {0, *optimizer_targets}
    for target in raw_clock_targets:
        selected_steps.add(target["lower"]["step"])
        selected_steps.add(target["upper"]["step"])
    max_selected = max(selected_steps)
    expected_shipped = set(range(max_selected))
    missing_shipped = sorted(expected_shipped - set(audit["shipped_steps"]))
    if missing_shipped:
        raise ValueError(
            f"{run_id} shipped optimizer steps are not contiguous through {max_selected}: {missing_shipped}"
        )
    selected_paths = {0: base_model}
    selected_paths.update({step: retained_by_step[step] for step in selected_steps if step})
    selected = [
        {
            "step": point["step"],
            "raw_groups": point["raw_groups"],
            "roles": _roles_for_step(point["step"], optimizer_clock_targets, raw_clock_targets),
        }
        for point in exposure_grid
        if point["step"] in selected_steps
    ]
    return (
        {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "launch_binding": {
                "arm_filename": request_run["arm_filename"],
                "launch_record_sha256": request_run["launch_record_sha256"],
                "source_provenance_manifest": source_manifest,
                "sbatch": sbatch,
            },
            "resolved_configs": resolved_config_identities,
            "base_model_path": str(base_model),
            "tokenizer_path": str(tokenizer_path),
            "retained_checkpoints": retained,
            "clock_audit": {
                "group_stats": audit["group_stats"],
                "batch_attempts": audit["batch_attempts"],
                "group_records": len(audit["group_labels"]),
                "eligible_shipped_steps": len(audit["shipped_steps"]),
                "raw_group_semantics": (
                    "count records with finalized_before_optimizer_step strictly below the checkpoint step"
                ),
            },
            "checkpoint_exposure_grid": exposure_grid,
            "optimizer_clock_targets": optimizer_clock_targets,
            "raw_group_clock_targets": raw_clock_targets,
            "selected_checkpoints": selected,
        },
        selected_paths,
        tokenizer_path,
    )


def deduplicate_model_records(
    run_records: list[dict[str, Any]],
    selected_paths: dict[str, dict[int, Path]],
) -> list[dict[str, Any]]:
    identity_cache: dict[tuple[Path, bool], dict[str, Any]] = {}

    def identity(path: Path, *, require_stable: bool) -> dict[str, Any]:
        resolved = path.resolve()
        key = (resolved, require_stable)
        if key not in identity_cache:
            identity_cache[key] = directory_identity(resolved, require_stable=require_stable)
        return identity_cache[key]

    base_identities = {
        record["run_id"]: identity(selected_paths[record["run_id"]][0], require_stable=False) for record in run_records
    }
    base_paths = {value["resolved_path"] for value in base_identities.values()}
    base_hashes = {value["inventory_sha256"] for value in base_identities.values()}
    if len(base_paths) != 1 or len(base_hashes) != 1:
        raise ValueError("Known-cost runs do not share one byte-identical step-0 model")
    base_identity = next(iter(base_identities.values()))
    models = [
        {
            "model_key": f"step0__{base_identity['inventory_sha256'][:20]}",
            "step_zero_deduplicated": True,
            "checkpoint": base_identity,
            "occurrences": [
                {
                    "run_id": record["run_id"],
                    "step": 0,
                    "raw_groups": 0,
                    "roles": next(
                        selected["roles"] for selected in record["selected_checkpoints"] if selected["step"] == 0
                    ),
                }
                for record in sorted(run_records, key=lambda item: item["run_id"])
            ],
        }
    ]
    for record in sorted(run_records, key=lambda item: item["run_id"]):
        for selected in record["selected_checkpoints"]:
            step = selected["step"]
            if step == 0:
                continue
            checkpoint = identity(selected_paths[record["run_id"]][step], require_stable=True)
            models.append(
                {
                    "model_key": f"{record['run_id']}__step_{step}__{checkpoint['inventory_sha256'][:20]}",
                    "step_zero_deduplicated": False,
                    "checkpoint": checkpoint,
                    "occurrences": [
                        {
                            "run_id": record["run_id"],
                            "step": step,
                            "raw_groups": selected["raw_groups"],
                            "roles": selected["roles"],
                        }
                    ],
                }
            )
    model_keys = [model["model_key"] for model in models]
    if len(model_keys) != len(set(model_keys)):
        raise RuntimeError("Collision in derived checkpoint model keys")
    return models


def _inference_config(
    model_path: str,
    output_dir: Path,
    port: int,
    tokenizer_path: Path,
) -> dict[str, Any]:
    return {
        "output_dir": str(output_dir.resolve()),
        "gpu_memory_utilization": 0.8,
        "enable_prefix_caching": True,
        "enable_fp32_lm_head": True,
        "api_server_count": 1,
        "data_parallel_size_local": 1,
        "seed": 0,
        "server": {
            "host": "0.0.0.0",
            "port": port,
            "liveness_timeout_seconds": 30.0,
        },
        "model": {
            "name": model_path,
            "dtype": "auto",
            "max_model_len": 2_048,
            "enforce_eager": False,
            "trust_remote_code": False,
            "tool_call_parser": "None",
            "reasoning_parser": "None",
        },
        "parallel": {"tp": 1, "dp": 1},
        "deployment": {"type": "single_node", "gpus_per_node": 1},
        "vllm_extra": {
            "max_num_seqs": 256,
            "tokenizer": str(tokenizer_path.resolve()),
        },
        "log": {
            "level": "info",
            "vf_level": "info",
            "json_logging": False,
            "log_data": False,
            "interval": 10.0,
        },
    }


def _eval_common(
    *,
    inference_path: Path,
    evaluator_path: Path,
    output_dir: Path,
    model_path: str,
    port: int,
    request_seed: int,
) -> dict[str, Any]:
    return {
        "infer_config": str(inference_path.resolve()),
        "evaluator": str(evaluator_path.resolve()),
        "eval": {
            "operations": list(OPERATIONS),
            "examples_per_operation": EXAMPLES_PER_OPERATION,
            "output_dir": str(output_dir.resolve()),
            "model": model_path,
            "api_base_url": f"http://127.0.0.1:{port}/v1",
            "samples_per_prompt": 1,
            "pass_at": [1],
            "max_tokens": 2_048,
            "temperature": 0.7,
            "top_p": 1.0,
            "top_k": -1,
            "request_seed": request_seed,
            "stop": ["</answer>"],
            "skip_special_tokens": False,
            "request_timeout_seconds": 3_600.0,
            "max_concurrent_prompts": 128,
            "max_retries": 2,
            "overwrite": False,
        },
    }


def build_task_bundle(
    *,
    model: dict[str, Any],
    task_index: int,
    plan_root: Path,
    evaluator_path: Path,
    tagged_data_dir: Path,
    tokenizer_path: Path,
    request_seed: int,
) -> tuple[dict[str, Any], tuple[ConfigArtifact, ...]]:
    model_key = model["model_key"]
    model_path = model["checkpoint"]["resolved_path"]
    port = 20_000 + task_index
    if not 1 <= port <= 65_535:
        raise ValueError(f"Derived task port is invalid: {port}")
    config_root = plan_root / "configs" / model_key
    result_root = plan_root / "results" / model_key
    inference_path = config_root / "inference.toml"
    inference = _inference_config(
        model_path,
        result_root / "deployment",
        port,
        tokenizer_path,
    )
    artifacts = [ConfigArtifact(inference_path, tomli_w.dumps(inference).encode("utf-8"))]

    shards = []
    untagged_output = result_root / "untagged"
    untagged_path = config_root / "untagged" / "eval.toml"
    untagged = _eval_common(
        inference_path=inference_path,
        evaluator_path=evaluator_path,
        output_dir=untagged_output,
        model_path=model_path,
        port=port,
        request_seed=request_seed,
    )
    untagged["eval"]["data_sources"] = copy.deepcopy(DATA_SOURCES)
    artifacts.append(ConfigArtifact(untagged_path, tomli_w.dumps(untagged).encode("utf-8")))
    shards.append(
        {
            "shard_id": "untagged",
            "view": "untagged",
            "neutral_tag_index": None,
            "output_dir": str(untagged_output.resolve()),
            "eval_config": bytes_identity(untagged_path, artifacts[-1].content),
        }
    )
    for tag_index in range(TAG_COUNT):
        output_dir = result_root / "tagged" / f"tag_{tag_index}"
        eval_path = config_root / "tagged" / f"tag_{tag_index}" / "eval.toml"
        evaluation = _eval_common(
            inference_path=inference_path,
            evaluator_path=evaluator_path,
            output_dir=output_dir,
            model_path=model_path,
            port=port,
            request_seed=request_seed,
        )
        evaluation["eval"].update(
            {
                "data_dir": str(tagged_data_dir.resolve()),
                "dataset_rows_per_operation": EXAMPLES_PER_OPERATION * TAG_COUNT,
                "neutral_tag_filter": tag_index,
                "prompt_transform": figure3_eval.KNOWN_COST_PROMPT_TRANSFORM,
                "request_seed_mode": figure3_eval.KNOWN_COST_REQUEST_SEED_MODE,
            }
        )
        content = tomli_w.dumps(evaluation).encode("utf-8")
        artifacts.append(ConfigArtifact(eval_path, content))
        shards.append(
            {
                "shard_id": f"tag_{tag_index}",
                "view": "tagged",
                "neutral_tag_index": tag_index,
                "output_dir": str(output_dir.resolve()),
                "eval_config": bytes_identity(eval_path, content),
            }
        )
    if len({shard["output_dir"] for shard in shards}) != TAG_COUNT + 1:
        raise RuntimeError(f"Task {model_key} has colliding shard output directories")
    config_identities = [artifact.identity() for artifact in artifacts]
    task = {
        "task_index": task_index,
        "task_id": model_key,
        "model_key": model_key,
        "model_path": model_path,
        "checkpoint_inventory_sha256": model["checkpoint"]["inventory_sha256"],
        "transport_port": port,
        "result_root": str(result_root.resolve()),
        "inference_config": config_identities[0],
        "shards": shards,
        "config_bundle_sha256": canonical_json_sha256(config_identities),
        "receipt_dir": str((plan_root / "receipts" / model_key).resolve()),
    }
    return task, tuple(artifacts)


def _implementation_identities() -> dict[str, Any]:
    return {
        "planner": {
            "repository_path": SCRIPT_REPOSITORY_PATH,
            **file_identity(Path(__file__)),
        },
        "evaluator": {
            "repository_path": EVALUATOR_REPOSITORY_PATH,
            **file_identity(Path(figure3_eval.__file__)),
        },
        "strict_scorer": {
            "repository_path": SCORER_REPOSITORY_PATH,
            **file_identity(Path(figure3_eval.solution_graph.__file__)),
        },
        "tagged_eval_materializer": {
            "repository_path": TAGGED_MATERIALIZER_REPOSITORY_PATH,
            **file_identity(Path(tagged_eval.__file__)),
        },
        "training_tag_materializer": {
            "repository_path": tagged_eval.training_tags.IMPLEMENTATION_REPOSITORY_PATH,
            **file_identity(Path(tagged_eval.training_tags.__file__)),
        },
        "launch_intent_materializer": {
            "repository_path": str(launch_intent.CONTROL_PLANE_REPOSITORY_PATHS["launch_materializer"]),
            **file_identity(Path(launch_intent.__file__)),
        },
        "legacy_eval_source_map": {
            "repository_path": "user/tianhaowu/rsci/prepare_rl_checkpoint_eval.py",
            **file_identity(Path(legacy_eval.__file__)),
        },
    }


def _imported_contract_identity() -> dict[str, Any]:
    expected_prefixes = tuple(f"<rsci_context_{index}>\n" for index in range(TAG_COUNT))
    observed = {
        "tag_count": {
            "planner": TAG_COUNT,
            "evaluator": figure3_eval.KNOWN_COST_TAG_COUNT,
            "heldout_materializer": tagged_eval.EXPECTED_TAG_COUNT,
            "training_materializer": tagged_eval.training_tags.TAG_COUNT,
        },
        "tag_prefixes": {
            "planner": list(expected_prefixes),
            "evaluator": list(figure3_eval.KNOWN_COST_TAG_PREFIXES),
            "heldout_materializer": list(tagged_eval.EXPECTED_TAG_PREFIXES),
            "training_materializer": list(tagged_eval.training_tags.TAG_PREFIXES),
        },
        "operations": {
            "planner": list(OPERATIONS),
            "heldout_materializer": list(tagged_eval.KNOWN_OPERATIONS),
        },
        "prompt_transform": figure3_eval.KNOWN_COST_PROMPT_TRANSFORM,
        "request_seed_mode": figure3_eval.KNOWN_COST_REQUEST_SEED_MODE,
        "untagged_data_sources": copy.deepcopy(DATA_SOURCES),
        "evaluator_generator_implementation_sha256": figure3_eval.generator_implementation_sha256(),
    }
    if set(observed["tag_count"].values()) != {TAG_COUNT}:
        raise ValueError("Imported known-cost tag counts diverged")
    for prefixes in observed["tag_prefixes"].values():
        if tuple(prefixes) != expected_prefixes:
            raise ValueError("Imported known-cost literal tag prefixes diverged")
    if any(tuple(operations) != OPERATIONS for operations in observed["operations"].values()):
        raise ValueError("Imported known-cost held-out operation ranges diverged")
    if observed["prompt_transform"] != "known_cost_neutral_tag_v1":
        raise ValueError("Imported known-cost prompt-transform identity diverged")
    if observed["request_seed_mode"] != "paired_source_v1":
        raise ValueError("Imported known-cost request-seed identity diverged")
    return {"values": observed, "canonical_sha256": canonical_json_sha256(observed)}


def _receipt_contract() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECEIPT_ARTIFACT_TYPE,
        "path_template": "receipts/<task_id>/attempt_<four-digit-attempt>.json",
        "attempt_numbering": "contiguous from 1",
        "terminal_statuses": sorted(TERMINAL_RECEIPT_STATUSES),
        "retry_rule": (
            "a retry must reference the exact SHA-256 of the preceding terminal receipt; no receipt may follow "
            "a succeeded receipt"
        ),
        "resume_rule": (
            "all attempts reuse the immutable shard output roots; figure3_eval generation manifests and "
            "completion records govern safe resume/quarantine"
        ),
        "success_rule": "one succeeded receipt requires all seven shard artifact inventories",
        "success_artifacts_per_shard": list(SUCCESS_ARTIFACT_NAMES),
        "submission": "not implemented by this materializer",
    }


def build_plan(spec_path: Path, eval_root: Path) -> PlanBuild:
    request = load_request(spec_path)
    eval_root = eval_root.expanduser().resolve()
    optimizer_targets = tuple(request["optimizer_step_targets"])
    raw_targets = tuple(request["raw_group_targets"])
    implementations = _implementation_identities()
    imported_contract = _imported_contract_identity()
    data, paired_seed_sequence_sha256 = evaluation_data_identity(
        Path(request["tagged_data_dir"]),
        request["request_seed"],
    )

    run_records = []
    selected_paths: dict[str, dict[int, Path]] = {}
    tokenizer_paths = set()
    for request_run in request["runs"]:
        run_record, paths, tokenizer_path = inspect_run(request_run, optimizer_targets, raw_targets)
        run_records.append(run_record)
        selected_paths[run_record["run_id"]] = paths
        tokenizer_paths.add(tokenizer_path.resolve())
    run_records.sort(key=lambda record: record["run_id"])
    tagged_tokenizer_path = Path(data["tagged"]["tokenizer"]["path"]).expanduser().resolve()
    launch_tokenizer_path = Path(request["launch"]["tokenizer_path"]).expanduser().resolve()
    if tagged_tokenizer_path != launch_tokenizer_path:
        raise ValueError("Held-out tag tokenizer differs from the immutable RL launch tokenizer")
    if tokenizer_paths != {tagged_tokenizer_path}:
        raise ValueError(
            "Training tokenizer paths differ from the exact tokenizer used to validate the held-out tag prefixes"
        )
    models = deduplicate_model_records(run_records, selected_paths)
    seed_contract = {
        "base_request_seed": request["request_seed"],
        "tagged_common_random_numbers": {
            "mode": figure3_eval.KNOWN_COST_REQUEST_SEED_MODE,
            "derivation": "sha256-paired-source-v1(base_seed,op,source_sample_id,sample_rank)",
            "paired_across": "all six neutral-tag clones of each source prompt and every checkpoint",
            "source_count": len(OPERATIONS) * EXAMPLES_PER_OPERATION,
            "seed_sequence_sha256": paired_seed_sequence_sha256,
            "all_source_seeds_unique": True,
        },
        "untagged": {
            "mode": "sha256-v1(base_seed,op,id,row_index,sample_rank)",
            "paired_to_tagged": False,
            "purpose": "legacy-comparable readout; CRN pairing is defined across the six tagged clones",
        },
    }
    clock_contract = {
        "optimizer_step_targets": list(optimizer_targets),
        "raw_group_targets": list(raw_targets),
        "maximum_checkpoint_step": MAX_CHECKPOINT_STEP,
        "optimizer_rule": "an optimizer target must have that exact retained STABLE checkpoint",
        "raw_group_rule": (
            "an exact target uses its unique retained checkpoint; otherwise evaluate the nearest lower and upper "
            "raw-exposure endpoints and interpolate without relabeling either endpoint"
        ),
        "raw_group_checkpoint_semantics": (
            "the checkpoint at step v includes groups with finalized_before_optimizer_step < v"
        ),
        "nearest_checkpoint_substitution_allowed": False,
    }
    semantic_core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "implementation_id": PLAN_IMPLEMENTATION_ID,
        "request": request,
        "implementations": implementations,
        "imported_contract": imported_contract,
        "evaluation_data": data,
        "seed_contract": seed_contract,
        "clock_contract": clock_contract,
        "runs": run_records,
        "models": models,
        "receipt_contract": _receipt_contract(),
    }
    plan_id = canonical_json_sha256(semantic_core)
    plan_root = eval_root / "plans" / plan_id
    evaluator_path = Path(implementations["evaluator"]["path"])
    tasks = []
    artifacts = []
    for task_index, model in enumerate(models):
        task, task_artifacts = build_task_bundle(
            model=model,
            task_index=task_index,
            plan_root=plan_root,
            evaluator_path=evaluator_path,
            tagged_data_dir=Path(request["tagged_data_dir"]),
            tokenizer_path=tagged_tokenizer_path,
            request_seed=request["request_seed"],
        )
        tasks.append(task)
        artifacts.extend(task_artifacts)
    artifact_paths = [artifact.path.resolve() for artifact in artifacts]
    if len(artifact_paths) != len(set(artifact_paths)):
        raise RuntimeError("Generated config paths collide")
    output_dirs = [shard["output_dir"] for task in tasks for shard in task["shards"]]
    if len(output_dirs) != len(set(output_dirs)):
        raise RuntimeError("Generated shard output roots collide")
    manifest = {
        **semantic_core,
        "plan_id": plan_id,
        "eval_root": str(eval_root),
        "plan_root": str(plan_root),
        "plan_path": str(plan_root / PLAN_NAME),
        "task_count": len(tasks),
        "shards_per_task": TAG_COUNT + 1,
        "tasks": tasks,
    }
    manifest_bytes = canonical_json_bytes(manifest)
    return PlanBuild(manifest, manifest_bytes, plan_root / PLAN_NAME, tuple(artifacts))


def _write_bytes_once(path: Path, content: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise ValueError(f"Refusing to replace a different immutable artifact: {path}")
        _require_read_only(path, "Immutable evaluation artifact")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    _require_read_only(path, "Immutable evaluation artifact")


def _validate_materialized_configs(build: PlanBuild) -> None:
    for artifact in build.config_artifacts:
        path = artifact.path.resolve()
        _require_read_only(path, "Materialized evaluation config")
        if not path.is_file() or path.read_bytes() != artifact.content:
            raise ValueError(f"Materialized config differs from the sealed plan: {path}")
    for task in build.manifest["tasks"]:
        for shard in task["shards"]:
            figure3_eval.load_config(Path(shard["eval_config"]["path"]))


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo != UTC:
        raise ValueError(f"{label} must use UTC")
    return parsed


def _validate_completed_shard(shard: dict[str, Any]) -> None:
    config = figure3_eval.load_config(Path(shard["eval_config"]["path"]))
    eval_config = config["eval"]
    output_dir = Path(shard["output_dir"])
    rows, dataset_hashes = figure3_eval.load_rows(eval_config)
    manifest = figure3_eval.build_generation_manifest(config, rows, dataset_hashes)
    figure3_eval.verify_generation_manifest(output_dir / figure3_eval.GENERATION_MANIFEST_NAME, manifest)
    generation_sha256, generation_records = figure3_eval.canonical_generation_content(
        output_dir / "generations.jsonl",
        rows,
        int(eval_config["samples_per_prompt"]),
    )
    completion = figure3_eval.verify_generation_completion(
        output_dir,
        manifest,
        generation_sha256,
        len(generation_records),
    )
    strict_records = figure3_eval.verify_strict_results(
        output_dir / "strict_results.jsonl",
        rows,
        generation_records,
    )
    metrics = figure3_eval.load_json_object(output_dir / "metrics.json")
    expected_count = len(rows) * int(eval_config["samples_per_prompt"])
    expected_fields = {
        "model": eval_config["model"],
        "dataset_sha256_by_op": dataset_hashes,
        "operations": list(OPERATIONS),
        "num_prompts": len(rows),
        "samples_per_prompt": 1,
        "num_generations": expected_count,
        "generation_provenance": {
            **completion,
            "generation_manifest": figure3_eval.GENERATION_MANIFEST_NAME,
            "generation_completion": figure3_eval.GENERATION_COMPLETION_NAME,
        },
    }
    for field, expected in expected_fields.items():
        if metrics.get(field) != expected:
            raise ValueError(f"Completed shard metrics {field} differs: {output_dir}")
    if len(strict_records) != expected_count:
        raise ValueError(f"Completed shard strict result count differs: {output_dir}")

    def outcomes(field: str) -> dict[tuple[str, int], dict[int, bool]]:
        values: dict[tuple[str, int], dict[int, bool]] = defaultdict(dict)
        for record in strict_records:
            key = (str(record["op"]), int(record["__idx"]))
            rank = int(record["sample_rank"])
            if rank in values[key]:
                raise ValueError(f"Completed shard has a duplicate strict rank for {key}: {output_dir}")
            values[key][rank] = bool(record[field])
        return values

    expected_aggregates = {
        "strict_graph": figure3_eval.aggregate_pass_at_k(outcomes("perfect"), [1]),
        "answer_only": figure3_eval.aggregate_pass_at_k(outcomes("answer_correct"), [1]),
    }
    known_cost_contract = figure3_eval.known_cost_tag_shard_contract(eval_config)
    if known_cost_contract is not None:
        expected_aggregates.update(
            {
                "answer_correct_strict_wrong": figure3_eval.aggregate_pass_at_k(
                    outcomes("answer_correct_strict_wrong"),
                    [1],
                ),
                "answer_wrong": figure3_eval.aggregate_pass_at_k(outcomes("answer_wrong"), [1]),
                "known_cost_tag_shard": known_cost_contract,
            }
        )
    for field, expected in expected_aggregates.items():
        if metrics.get(field) != expected:
            raise ValueError(f"Completed shard metrics {field} differs from deterministic rescoring: {output_dir}")
    implementation = figure3_eval.implementation_identity()
    expected_scoring = {
        "implementation_sha256": implementation,
        "strict_results_sha256": figure3_eval.file_sha256(output_dir / "strict_results.jsonl"),
        "num_results": expected_count,
    }
    if metrics.get("implementation_sha256") != implementation:
        raise ValueError(f"Completed shard evaluator implementation differs: {output_dir}")
    if metrics.get("strict_scoring_provenance") != expected_scoring:
        raise ValueError(f"Completed shard strict-scoring provenance differs: {output_dir}")


def _validate_success_artifacts(receipt: dict[str, Any], task: dict[str, Any]) -> None:
    shard_records = receipt.get("shards")
    if not isinstance(shard_records, list) or len(shard_records) != len(task["shards"]):
        raise ValueError(f"Succeeded receipt for {task['task_id']} must inventory all seven shards")
    by_id = {record.get("shard_id"): record for record in shard_records if isinstance(record, dict)}
    if set(by_id) != {shard["shard_id"] for shard in task["shards"]}:
        raise ValueError(f"Succeeded receipt for {task['task_id']} has a wrong shard inventory")
    for shard in task["shards"]:
        record = by_id[shard["shard_id"]]
        if record.get("output_dir") != shard["output_dir"]:
            raise ValueError(f"Receipt output root differs for {task['task_id']}/{shard['shard_id']}")
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != set(SUCCESS_ARTIFACT_NAMES):
            raise ValueError(f"Receipt artifacts differ for {task['task_id']}/{shard['shard_id']}")
        output_dir = Path(shard["output_dir"])
        for name in SUCCESS_ARTIFACT_NAMES:
            expected = file_identity(output_dir / name)
            if artifacts[name] != expected:
                raise ValueError(f"Receipt artifact changed for {task['task_id']}/{shard['shard_id']}/{name}")
        _validate_completed_shard(shard)


def validate_receipt_chain(
    *,
    plan: dict[str, Any],
    plan_sha256: str,
) -> dict[str, Any]:
    plan_root = Path(plan["plan_root"])
    task_by_id = {task["task_id"]: task for task in plan["tasks"]}
    receipts_root = plan_root / "receipts"
    if not receipts_root.exists():
        return {"receipt_count": 0, "task_statuses": {}}
    unexpected_root_entries = sorted(path.name for path in receipts_root.iterdir() if not path.is_dir())
    if unexpected_root_entries:
        raise ValueError(f"Unexpected entries in the receipt root: {unexpected_root_entries}")
    unknown_dirs = sorted(
        path.name for path in receipts_root.iterdir() if path.is_dir() and path.name not in task_by_id
    )
    if unknown_dirs:
        raise ValueError(f"Receipt directories reference unknown tasks: {unknown_dirs}")
    receipt_count = 0
    task_statuses = {}
    for task_id, task in task_by_id.items():
        task_dir = receipts_root / task_id
        if not task_dir.exists():
            continue
        if not task_dir.is_dir():
            raise ValueError(f"Receipt task path is not a directory: {task_dir}")
        paths = sorted(task_dir.iterdir())
        attempts = []
        for path in paths:
            match = RECEIPT_NAME_RE.fullmatch(path.name)
            if match is None:
                raise ValueError(f"Unexpected receipt filename: {path}")
            attempts.append((int(match.group(1)), path))
        if [attempt for attempt, _ in attempts] != list(range(1, len(attempts) + 1)):
            raise ValueError(f"Receipt attempts are not contiguous for {task_id}")
        predecessor_sha256 = None
        predecessor_status = None
        for attempt, path in attempts:
            _require_read_only(path, "Evaluation attempt receipt")
            raw, receipt = read_json_object(path, require_canonical=True)
            expected = {
                "schema_version": SCHEMA_VERSION,
                "artifact_type": RECEIPT_ARTIFACT_TYPE,
                "plan_id": plan["plan_id"],
                "plan_sha256": plan_sha256,
                "task_id": task_id,
                "attempt": attempt,
                "predecessor_receipt_sha256": predecessor_sha256,
                "config_bundle_sha256": task["config_bundle_sha256"],
                "checkpoint_inventory_sha256": task["checkpoint_inventory_sha256"],
                "result_root": task["result_root"],
            }
            for field, value in expected.items():
                if receipt.get(field) != value:
                    raise ValueError(f"Receipt {field} differs: {path}")
            status = receipt.get("status")
            if status not in TERMINAL_RECEIPT_STATUSES:
                raise ValueError(f"Receipt status is not terminal: {path}")
            if predecessor_status == "succeeded":
                raise ValueError(f"Receipt follows a succeeded attempt: {path}")
            started_at = _parse_timestamp(receipt.get("started_at"), f"{path} started_at")
            finished_at = _parse_timestamp(receipt.get("finished_at"), f"{path} finished_at")
            if finished_at < started_at:
                raise ValueError(f"Receipt finishes before it starts: {path}")
            scheduler = receipt.get("scheduler")
            if not isinstance(scheduler, dict):
                raise ValueError(f"Receipt has no scheduler identity: {path}")
            job_id = scheduler.get("job_id")
            array_task_id = scheduler.get("array_task_id")
            if not isinstance(job_id, str) or not job_id.isdecimal() or int(job_id) < 1:
                raise ValueError(f"Receipt scheduler.job_id is invalid: {path}")
            if array_task_id is not None:
                _require_int(array_task_id, f"{path} scheduler.array_task_id")
            exit_code = receipt.get("exit_code")
            if status == "succeeded":
                if exit_code != 0:
                    raise ValueError(f"Succeeded receipt has a nonzero exit code: {path}")
                _validate_success_artifacts(receipt, task)
            else:
                if exit_code is not None:
                    _require_int(exit_code, f"{path} exit_code")
                if not isinstance(receipt.get("failure"), str) or not receipt["failure"]:
                    raise ValueError(f"Unsuccessful receipt has no failure description: {path}")
            predecessor_sha256 = bytes_sha256(raw)
            predecessor_status = status
            receipt_count += 1
        if attempts:
            task_statuses[task_id] = predecessor_status
    return {"receipt_count": receipt_count, "task_statuses": task_statuses}


def validate_plan(plan_path: Path) -> dict[str, Any]:
    plan_path = plan_path.expanduser().resolve()
    _require_read_only(plan_path, "Evaluation plan")
    raw, manifest = read_json_object(plan_path, require_canonical=True)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("Known-cost eval plan has the wrong schema or artifact type")
    if manifest.get("study_id") != STUDY_ID or manifest.get("implementation_id") != PLAN_IMPLEMENTATION_ID:
        raise ValueError("Known-cost eval plan has the wrong study or implementation identity")
    plan_id = manifest.get("plan_id")
    if not isinstance(plan_id, str) or SHA256_RE.fullmatch(plan_id) is None:
        raise ValueError("Known-cost eval plan has an invalid plan_id")
    expected_path = Path(manifest.get("eval_root", "")) / "plans" / plan_id / PLAN_NAME
    if expected_path.resolve() != plan_path or manifest.get("plan_path") != str(plan_path):
        raise ValueError("Known-cost eval plan is not at its collision-safe recorded path")
    request = manifest.get("request")
    if not isinstance(request, dict) or not isinstance(request.get("spec"), dict):
        raise ValueError("Known-cost eval plan has no replayable request identity")
    expected = build_plan(Path(request["spec"]["path"]), Path(manifest["eval_root"]))
    if expected.plan_path.resolve() != plan_path or expected.manifest != manifest:
        raise ValueError("Known-cost eval plan differs from independent replay")
    _validate_materialized_configs(expected)
    plan_sha256 = bytes_sha256(raw)
    receipts = validate_receipt_chain(plan=manifest, plan_sha256=plan_sha256)
    return {
        "plan": manifest,
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha256,
        "task_count": manifest["task_count"],
        "model_count": len(manifest["models"]),
        "receipts": receipts,
    }


def materialize_plan(spec_path: Path, eval_root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    build = build_plan(spec_path, eval_root)
    if dry_run:
        return {
            "dry_run": True,
            "plan": build.manifest,
            "plan_path": str(build.plan_path),
            "plan_sha256": bytes_sha256(build.manifest_bytes),
            "config_count": len(build.config_artifacts),
        }
    if build.plan_path.exists():
        validated = validate_plan(build.plan_path)
        return {**validated, "dry_run": False, "already_materialized": True}
    for artifact in build.config_artifacts:
        _write_bytes_once(artifact.path, artifact.content)
    _write_bytes_once(build.plan_path, build.manifest_bytes)
    validated = validate_plan(build.plan_path)
    return {**validated, "dry_run": False, "already_materialized": False}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--spec", type=Path, required=True)
    materialize.add_argument("--eval-root", type=Path, default=DEFAULT_EVAL_ROOT)
    materialize.add_argument("--dry-run", action="store_true")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--plan", type=Path, required=True)
    return parser.parse_args()


def _summary(result: dict[str, Any], command: str) -> dict[str, Any]:
    plan = result["plan"]
    return {
        "command": command,
        "dry_run": result.get("dry_run", False),
        "already_materialized": result.get("already_materialized"),
        "plan_id": plan["plan_id"],
        "plan_path": result["plan_path"],
        "plan_sha256": result["plan_sha256"],
        "run_count": len(plan["runs"]),
        "model_count": len(plan["models"]),
        "task_count": plan["task_count"],
        "shards_per_task": plan["shards_per_task"],
        "step_zero_occurrences": len(plan["models"][0]["occurrences"]),
        "receipts": result.get("receipts"),
    }


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        result = materialize_plan(args.spec, args.eval_root, dry_run=args.dry_run)
    else:
        result = validate_plan(args.plan)
    print(json.dumps(_summary(result, args.command), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
