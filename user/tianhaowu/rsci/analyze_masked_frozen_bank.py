#!/usr/bin/env python3
"""Replay the masked-verifier Stage-1 design on the frozen base-policy bank.

Run with ``uv run user/tianhaowu/rsci/analyze_masked_frozen_bank.py ...``.
The report is a deterministic, provenance-bound preflight; it is not an
estimate of outcomes after the policy has changed during training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

ANALYSIS_VERSION = "masked-frozen-bank-preflight-v1"
PHYSICAL_GROUP_SIZE = 128
SCHEDULE_SEED = 42
SCHEDULE_PREFIX_GROUPS = 12_000
DEFECT_SEEDS = (20260805, 20260806, 20260807)
UINT64_SPACE = 2**64

BANK_OPERATIONS = (10, 11, 12, *range(15, 41))
TRAIN_OPERATIONS = tuple(range(10, 41))
BANDS = {
    "op10_12": frozenset(range(10, 13)),
    "op15_20": frozenset(range(15, 21)),
    "op21_40": frozenset(range(21, 41)),
}

DEFAULT_BANK_ROOT = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/verifier-defect/frozen-base-op10-12-op15-40-r128-v1"
)
DEFAULT_TRAIN_DATASET = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k/train.jsonl")
EXPECTED_BANK_CONTRACT_SHA256 = "8e25af2c374ce70be2df3d4acaa8d38ea5a23960e8db55326be53dadd4aca085"
EXPECTED_TRAIN_DATASET_SHA256 = "59dd47898e1ba2e348f23c080b58f354ea56ea15a7bc39c33ac96aea5335afd8"

STRICT_RESULT_FIELDS = frozenset(
    {
        "op",
        "id",
        "__idx",
        "sample_rank",
        "template",
        "mode",
        "finish_reason",
        "perfect",
        "answer_correct",
        "candidate",
        "value_mismatch_count",
        "dependency_mismatch_count",
        "answer_mismatch",
        "extra_nodes",
        "missing_nodes",
        "defect_draw_u64",
        "defect_draw",
    }
)


@dataclass(frozen=True)
class ArmSpec:
    label: str
    assignment: str
    eligible_slot_count: int
    probability_numerator: int
    probability_denominator: int

    @property
    def probability(self) -> float:
        return self.probability_numerator / self.probability_denominator

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "assignment": self.assignment,
            "eligible_slot_count_L": self.eligible_slot_count,
            "false_positive_probability": self.probability,
            "false_positive_probability_exact": (f"{self.probability_numerator}/{self.probability_denominator}"),
        }


ARM_SPECS = (
    ArmSpec("a0", "behavior", 128, 0, 1),
    ArmSpec("a1", "behavior", 128, 1, 800),
    ArmSpec("a2", "behavior", 32, 1, 200),
    ArmSpec("a3", "behavior", 128, 1, 400),
    ArmSpec("a4", "behavior", 32, 1, 100),
    ArmSpec("aS", "shuffled", 128, 1, 400),
)
ARM_BY_LABEL = {arm.label: arm for arm in ARM_SPECS}


@dataclass(frozen=True)
class FileIdentity:
    path: str
    size_bytes: int
    sha256: str
    rows: int | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }
        if self.rows is not None:
            result["rows"] = self.rows
        return result


@dataclass(frozen=True)
class BankContract:
    root: Path
    manifest: dict[str, Any]
    completion: dict[str, Any]
    contract_sha256: str
    examples_per_operation: int
    groups: int
    trajectories: int
    bank_defect_seed: int
    manifest_identity: FileIdentity
    completion_identity: FileIdentity


@dataclass(frozen=True)
class TrainRecord:
    task_index: int
    operation: int
    sample_id: str


@dataclass(frozen=True)
class PromptRecord:
    operation: int
    prompt_index: int
    sample_id: str


@dataclass(frozen=True)
class GroupOutcome:
    strict_count: int
    candidate_count: int
    eligible_candidate_count: int
    trigger_count: int
    recipient_candidate_count: int
    expected_any_trigger: float
    expected_defect_only_any_trigger: float
    expected_nucleation: float
    expected_final_mixed: float

    @property
    def any_trigger(self) -> bool:
        return self.trigger_count > 0

    @property
    def defect_only_any_trigger(self) -> bool:
        return self.strict_count == 0 and self.trigger_count > 0

    @property
    def nucleated(self) -> bool:
        return self.strict_count == 0 and 0 < self.trigger_count < PHYSICAL_GROUP_SIZE

    @property
    def final_mixed(self) -> bool:
        positives = self.strict_count + self.trigger_count
        return 0 < positives < PHYSICAL_GROUP_SIZE


@dataclass
class MetricAccumulator:
    groups: int = 0
    strict_positive_slots: int = 0
    candidate_slots: int = 0
    eligible_candidate_slots: int = 0
    trigger_slots: int = 0
    recipient_candidate_slots: int = 0
    strict_dead_groups: int = 0
    clean_mixed_groups: int = 0
    candidate_support_groups: int = 0
    masked_support_groups: int = 0
    support_lost_groups: int = 0
    any_trigger_groups: int = 0
    defect_only_any_trigger_groups: int = 0
    nucleated_groups: int = 0
    final_mixed_groups: int = 0
    final_zero_groups: int = 0
    final_all_positive_groups: int = 0
    expected_any_trigger_groups: float = 0.0
    expected_defect_only_any_trigger_groups: float = 0.0
    expected_nucleated_groups: float = 0.0
    expected_final_mixed_groups: float = 0.0
    k_histogram: Counter[int] = field(default_factory=Counter)
    h_histogram: Counter[int] = field(default_factory=Counter)

    def add(self, outcome: GroupOutcome) -> None:
        s = outcome.strict_count
        c = outcome.candidate_count
        k = outcome.eligible_candidate_count
        h = outcome.trigger_count
        final_positives = s + h
        self.groups += 1
        self.strict_positive_slots += s
        self.candidate_slots += c
        self.eligible_candidate_slots += k
        self.trigger_slots += h
        self.recipient_candidate_slots += outcome.recipient_candidate_count
        self.strict_dead_groups += int(s == 0)
        self.clean_mixed_groups += int(0 < s < PHYSICAL_GROUP_SIZE)
        self.candidate_support_groups += int(c > 0)
        self.masked_support_groups += int(k > 0)
        self.support_lost_groups += int(c > 0 and k == 0)
        self.any_trigger_groups += int(outcome.any_trigger)
        self.defect_only_any_trigger_groups += int(outcome.defect_only_any_trigger)
        self.nucleated_groups += int(outcome.nucleated)
        self.final_mixed_groups += int(outcome.final_mixed)
        self.final_zero_groups += int(final_positives == 0)
        self.final_all_positive_groups += int(final_positives == PHYSICAL_GROUP_SIZE)
        self.expected_any_trigger_groups += outcome.expected_any_trigger
        self.expected_defect_only_any_trigger_groups += outcome.expected_defect_only_any_trigger
        self.expected_nucleated_groups += outcome.expected_nucleation
        self.expected_final_mixed_groups += outcome.expected_final_mixed
        self.k_histogram[k] += 1
        self.h_histogram[h] += 1

    def as_dict(self, arm: ArmSpec, *, include_histograms: bool) -> dict[str, object]:
        expected_triggers = arm.probability * self.eligible_candidate_slots
        result: dict[str, object] = {
            "groups": self.groups,
            "physical_slots": self.groups * PHYSICAL_GROUP_SIZE,
            "strict_positive_slots_S": self.strict_positive_slots,
            "candidate_slots_C": self.candidate_slots,
            "strict_dead_groups": self.strict_dead_groups,
            "clean_mixed_groups": self.clean_mixed_groups,
            "eligibility_and_support": {
                "eligible_candidate_slots_K": self.eligible_candidate_slots,
                "candidate_slots_excluded_C_minus_K": self.candidate_slots - self.eligible_candidate_slots,
                "candidate_retention_fraction_K_over_C": _ratio(self.eligible_candidate_slots, self.candidate_slots),
                "mean_K_per_group": _ratio(self.eligible_candidate_slots, self.groups),
                "candidate_support_groups_C_gt_0": self.candidate_support_groups,
                "masked_support_groups_K_gt_0": self.masked_support_groups,
                "support_lost_groups_C_gt_0_K_eq_0": self.support_lost_groups,
                "support_lost_fraction_of_candidate_groups": _ratio(
                    self.support_lost_groups, self.candidate_support_groups
                ),
            },
            "trigger_slots": {
                "expected_p_times_K": expected_triggers,
                "realized_H": self.trigger_slots,
                "calibration_residual_H_minus_pK": self.trigger_slots - expected_triggers,
            },
            "recipient_alignment": {
                "selected_extra_positive_slots": self.trigger_slots,
                "selected_recipients_that_are_behavior_candidates": self.recipient_candidate_slots,
                "candidate_recipient_fraction": _ratio(self.recipient_candidate_slots, self.trigger_slots),
            },
            "group_events": {
                "any_trigger_H_gt_0": _event_summary(self.expected_any_trigger_groups, self.any_trigger_groups),
                "defect_only_any_trigger_S_eq_0_H_gt_0": _event_summary(
                    self.expected_defect_only_any_trigger_groups,
                    self.defect_only_any_trigger_groups,
                ),
                "strict_dead_nucleation_S_eq_0_0_lt_H_lt_V": _event_summary(
                    self.expected_nucleated_groups, self.nucleated_groups
                ),
                "final_mixed_0_lt_S_plus_H_lt_V": _event_summary(
                    self.expected_final_mixed_groups, self.final_mixed_groups
                ),
                "final_zero_realized_groups": self.final_zero_groups,
                "final_all_positive_realized_groups": self.final_all_positive_groups,
            },
        }
        if include_histograms:
            result["K_histogram"] = {str(key): self.k_histogram[key] for key in sorted(self.k_histogram)}
            result["H_histogram"] = {str(key): self.h_histogram[key] for key in sorted(self.h_histogram)}
        return result


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def _event_summary(expected: float, realized: int) -> dict[str, int | float]:
    return {
        "expected_groups_exact_conditional_formula": expected,
        "realized_groups": realized,
        "calibration_residual_realized_minus_expected": realized - expected,
    }


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_identity(path: Path) -> FileIdentity:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return FileIdentity(str(path), size, digest.hexdigest())


def jsonl_identity(path: Path) -> FileIdentity:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    size = 0
    rows = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            digest.update(line)
            size += len(line)
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank JSONL records are not allowed")
            rows += 1
    return FileIdentity(str(path), size, digest.hexdigest(), rows)


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = orjson.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _require_int(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer >= {minimum}")
    return value


def _require_str(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _resolve_artifact(root: Path, value: Any, expected_name: str, context: str) -> Path:
    recorded = Path(_require_str(value, context))
    resolved = (root / recorded).resolve() if not recorded.is_absolute() else recorded.resolve()
    expected = (root / expected_name).resolve()
    if resolved != expected:
        raise ValueError(f"{context} resolves to {resolved}, expected {expected}")
    return resolved


def load_bank_contract(
    root: Path,
    *,
    expected_contract_sha256: str | None,
) -> BankContract:
    root = root.expanduser().resolve()
    manifest_path = root / "manifest.json"
    completion_path = root / "completion.json"
    manifest = _read_json_object(manifest_path)
    completion = _read_json_object(completion_path)
    if manifest.get("schema_version") != 1 or completion.get("schema_version") != 1:
        raise ValueError("Bank manifest and completion schema_version must both equal 1")
    contract_sha256 = _require_str(manifest.get("contract_sha256"), "manifest.contract_sha256")
    if len(contract_sha256) != 64:
        raise ValueError("manifest.contract_sha256 must contain 64 hex characters")
    if expected_contract_sha256 is not None and contract_sha256 != expected_contract_sha256:
        raise ValueError(f"Bank contract SHA-256 is {contract_sha256}, expected {expected_contract_sha256}")
    if completion.get("contract_sha256") != contract_sha256:
        raise ValueError("Bank manifest and completion contract SHA-256 values differ")
    contract = _require_dict(manifest.get("contract"), "manifest.contract")
    if canonical_json_sha256(contract) != contract_sha256:
        raise ValueError("manifest.contract_sha256 does not match the canonical contract object")
    if contract.get("operations") != list(BANK_OPERATIONS):
        raise ValueError(f"Bank operations must equal {list(BANK_OPERATIONS)}")
    examples = _require_int(contract.get("examples_per_operation"), "examples_per_operation", minimum=1)
    groups = examples * len(BANK_OPERATIONS)
    trajectories = groups * PHYSICAL_GROUP_SIZE
    expected = _require_dict(contract.get("expected"), "manifest.contract.expected")
    if expected != {"groups": groups, "batches": groups, "trajectories": trajectories}:
        raise ValueError("Bank expected group/batch/trajectory counts are inconsistent")
    sampling = _require_dict(contract.get("sampling"), "manifest.contract.sampling")
    if sampling.get("samples_per_prompt") != PHYSICAL_GROUP_SIZE:
        raise ValueError(f"Bank samples_per_prompt must equal {PHYSICAL_GROUP_SIZE}")
    if sampling.get("request_batch_size") != PHYSICAL_GROUP_SIZE:
        raise ValueError(f"Bank request_batch_size must equal {PHYSICAL_GROUP_SIZE}")
    scoring = _require_dict(contract.get("scoring"), "manifest.contract.scoring")
    if scoring.get("strict") != "released compare_solutions(...).perfect":
        raise ValueError("Bank strict-scoring contract differs")
    if scoring.get("candidate") != "answer_correct and not strict_correct":
        raise ValueError("Bank candidate contract differs")
    bank_defect_seed = _require_int(scoring.get("defect_seed"), "scoring.defect_seed")

    expected_artifacts = {
        "prompts": ("prompts.jsonl", groups, "(op,__idx)"),
        "generations": ("generations.jsonl", trajectories, "(op,__idx,sample_rank)"),
        "strict_results": ("strict_results.jsonl", trajectories, "(op,__idx,sample_rank)"),
    }
    contract_artifacts = _require_dict(contract.get("artifacts"), "manifest.contract.artifacts")
    completion_artifacts = _require_dict(completion.get("artifacts"), "completion.artifacts")
    if set(contract_artifacts) != set(expected_artifacts) or set(completion_artifacts) != set(expected_artifacts):
        raise ValueError("Bank artifacts must be exactly prompts, generations, and strict_results")
    for name, (filename, rows, ordering) in expected_artifacts.items():
        contract_record = _require_dict(contract_artifacts[name], f"contract.artifacts.{name}")
        completion_record = _require_dict(completion_artifacts[name], f"completion.artifacts.{name}")
        _resolve_artifact(root, contract_record.get("path"), filename, f"contract.artifacts.{name}.path")
        _resolve_artifact(root, completion_record.get("path"), filename, f"completion.artifacts.{name}.path")
        if contract_record.get("rows") != rows or completion_record.get("rows") != rows:
            raise ValueError(f"{name} row contract differs from {rows}")
        if contract_record.get("ordering") != ordering or completion_record.get("ordering") != ordering:
            raise ValueError(f"{name} ordering contract differs from {ordering}")

    manifest_identity = file_identity(manifest_path)
    completion_manifest = _require_dict(completion.get("manifest"), "completion.manifest")
    _resolve_artifact(root, completion_manifest.get("path"), "manifest.json", "completion.manifest.path")
    if completion_manifest.get("size_bytes") != manifest_identity.size_bytes:
        raise ValueError("completion.manifest.size_bytes does not match manifest.json")
    if completion_manifest.get("sha256") != manifest_identity.sha256:
        raise ValueError("completion.manifest.sha256 does not match manifest.json")
    completion_scoring = _require_dict(completion.get("scoring"), "completion.scoring")
    if completion_scoring.get("implementation_sha256") != scoring.get("implementation_sha256"):
        raise ValueError("Manifest and completion scoring implementation identities differ")
    return BankContract(
        root=root,
        manifest=manifest,
        completion=completion,
        contract_sha256=contract_sha256,
        examples_per_operation=examples,
        groups=groups,
        trajectories=trajectories,
        bank_defect_seed=bank_defect_seed,
        manifest_identity=manifest_identity,
        completion_identity=file_identity(completion_path),
    )


def _verify_completion_artifact(
    contract: BankContract,
    name: str,
    identity: FileIdentity,
) -> None:
    record = _require_dict(contract.completion["artifacts"][name], f"completion.artifacts.{name}")
    expected_rows = contract.groups if name == "prompts" else contract.trajectories
    if identity.rows != expected_rows:
        raise ValueError(f"{name} contains {identity.rows} rows, expected {expected_rows}")
    if record.get("size_bytes") != identity.size_bytes:
        raise ValueError(f"completion.artifacts.{name}.size_bytes does not match the file")
    if record.get("sha256") != identity.sha256:
        raise ValueError(f"completion.artifacts.{name}.sha256 does not match the file")


def _runtime_prompt(row: dict[str, Any], context: str) -> str:
    value = row.get("prompt")
    if value is None:
        for field_name in ("problem", "question"):
            if not isinstance(row.get(field_name), str):
                raise ValueError(f"{context}.{field_name} must be a string")
        value = f"<question> {str(row['problem']).strip()} {str(row['question']).strip()} </question> <solution>"
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} has an invalid runtime prompt")
    return value


def load_train_dataset(
    path: Path,
    *,
    examples_per_operation: int,
    expected_sha256: str | None,
) -> tuple[tuple[TrainRecord, ...], dict[str, tuple[int, str]], FileIdentity]:
    path = path.expanduser().resolve()
    digest = hashlib.sha256()
    size = 0
    records: list[TrainRecord] = []
    prompt_by_id: dict[str, tuple[int, str]] = {}
    prompts: set[str] = set()
    with path.open("rb") as handle:
        for task_index, line in enumerate(handle):
            digest.update(line)
            size += len(line)
            context = f"{path}:{task_index + 1}"
            if not line.strip():
                raise ValueError(f"{context}: blank JSONL records are not allowed")
            row = orjson.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{context}: record must be an object")
            sample_id = _require_str(row.get("id"), f"{context}.id")
            operation = _require_int(row.get("op"), f"{context}.op")
            expected_operation = TRAIN_OPERATIONS[task_index // examples_per_operation]
            if operation != expected_operation:
                raise ValueError(
                    f"{context}: operation {operation} violates grouped OP10-40 dataset order; "
                    f"expected {expected_operation}"
                )
            if sample_id in prompt_by_id:
                raise ValueError(f"{context}: duplicate sample id {sample_id}")
            prompt = _runtime_prompt(row, context)
            if prompt in prompts:
                raise ValueError(f"{context}: duplicate runtime prompt")
            prompts.add(prompt)
            prompt_by_id[sample_id] = (operation, prompt)
            records.append(TrainRecord(task_index, operation, sample_id))
    expected_rows = len(TRAIN_OPERATIONS) * examples_per_operation
    if len(records) != expected_rows:
        raise ValueError(f"Training dataset has {len(records)} rows, expected {expected_rows}")
    identity = FileIdentity(str(path), size, digest.hexdigest(), len(records))
    if expected_sha256 is not None and identity.sha256 != expected_sha256:
        raise ValueError(f"Training dataset SHA-256 is {identity.sha256}, expected {expected_sha256}")
    return tuple(records), prompt_by_id, identity


def load_bank_prompts(
    contract: BankContract,
    train_prompt_by_id: dict[str, tuple[int, str]],
) -> tuple[tuple[PromptRecord, ...], FileIdentity]:
    path = contract.root / "prompts.jsonl"
    digest = hashlib.sha256()
    size = 0
    records: list[PromptRecord] = []
    seen_ids: set[str] = set()
    with path.open("rb") as handle:
        for row_index, line in enumerate(handle):
            digest.update(line)
            size += len(line)
            context = f"{path}:{row_index + 1}"
            if not line.strip():
                raise ValueError(f"{context}: blank JSONL records are not allowed")
            row = orjson.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{context}: record must be an object")
            expected_operation = BANK_OPERATIONS[row_index // contract.examples_per_operation]
            expected_prompt_index = row_index % contract.examples_per_operation
            operation = _require_int(row.get("op"), f"{context}.op")
            prompt_index = _require_int(row.get("__idx"), f"{context}.__idx")
            sample_id = _require_str(row.get("id"), f"{context}.id")
            if (operation, prompt_index) != (expected_operation, expected_prompt_index):
                raise ValueError(
                    f"{context}: prompt order {(operation, prompt_index)} differs from "
                    f"{(expected_operation, expected_prompt_index)}"
                )
            if sample_id in seen_ids:
                raise ValueError(f"{context}: duplicate bank sample id {sample_id}")
            seen_ids.add(sample_id)
            train_record = train_prompt_by_id.get(sample_id)
            if train_record is None:
                raise ValueError(f"{context}: bank sample id is absent from the online training dataset")
            train_operation, train_prompt = train_record
            if train_operation != operation:
                raise ValueError(f"{context}: bank and training operations differ")
            if _runtime_prompt(row, context) != train_prompt:
                raise ValueError(f"{context}: bank and training runtime prompts differ")
            records.append(PromptRecord(operation, prompt_index, sample_id))
    if len(records) != contract.groups:
        raise ValueError(f"Bank prompts contain {len(records)} rows, expected {contract.groups}")
    identity = FileIdentity(str(path.resolve()), size, digest.hexdigest(), len(records))
    _verify_completion_artifact(contract, "prompts", identity)
    prompts_content = _require_dict(contract.manifest["contract"].get("prompts_content"), "prompts_content")
    if prompts_content.get("size_bytes") != size or prompts_content.get("sha256") != identity.sha256:
        raise ValueError("Bank prompts_content identity differs from prompts.jsonl")
    return tuple(records), identity


def scheduled_prefix(
    records: tuple[TrainRecord, ...],
    *,
    seed: int,
    prefix_groups: int,
) -> tuple[TrainRecord, ...]:
    if not 0 <= prefix_groups <= len(records):
        raise ValueError(f"prefix_groups must lie in [0, {len(records)}]")
    task_indices = list(range(len(records)))
    random.Random(seed).shuffle(task_indices)
    return tuple(records[index] for index in task_indices[:prefix_groups])


def sample_slot_key(sample_id: str, slot: int) -> str:
    return json.dumps([sample_id, slot], separators=(",", ":"))


def defect_draw_u64(sample_id: str, slot: int, defect_seed: int, *, shuffled: bool = False) -> int:
    prefix = f"{defect_seed}:group-shuffle:" if shuffled else f"{defect_seed}:"
    digest = hashlib.sha256(f"{prefix}{sample_slot_key(sample_id, slot)}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def eligible_slot_digest(sample_id: str, slot: int, defect_seed: int) -> bytes:
    key = sample_slot_key(sample_id, slot)
    return hashlib.sha256(f"{defect_seed}:eligible-slot-mask-v1:{key}".encode()).digest()


def eligible_slot_plan(sample_id: str, defect_seed: int, eligible_slot_count: int) -> tuple[int, ...]:
    if not 0 <= eligible_slot_count <= PHYSICAL_GROUP_SIZE:
        raise ValueError(f"eligible_slot_count must lie in [0, {PHYSICAL_GROUP_SIZE}]")
    ranked = sorted(
        range(PHYSICAL_GROUP_SIZE),
        key=lambda slot: (eligible_slot_digest(sample_id, slot, defect_seed), slot),
    )
    return tuple(ranked[:eligible_slot_count])


def runtime_trigger(draw_u64: int, arm: ArmSpec) -> bool:
    if not 0 <= draw_u64 < UINT64_SPACE:
        raise ValueError("draw_u64 must lie in [0, 2**64)")
    return draw_u64 / UINT64_SPACE < arm.probability


def exact_group_probabilities(s: int, k: int, arm: ArmSpec) -> tuple[float, float, float, float]:
    if not 0 <= s <= PHYSICAL_GROUP_SIZE:
        raise ValueError("s must lie in [0, V]")
    if not 0 <= k <= PHYSICAL_GROUP_SIZE - s:
        raise ValueError("k exceeds the strict-negative population")
    p = arm.probability
    no_trigger = (1.0 - p) ** k
    all_eligible_trigger = p**k
    any_trigger = 1.0 - no_trigger
    defect_only_any = any_trigger if s == 0 else 0.0
    nucleation = 1.0 - no_trigger - (all_eligible_trigger if k == PHYSICAL_GROUP_SIZE else 0.0) if s == 0 else 0.0
    final_mixed = (
        1.0 - (no_trigger if s == 0 else 0.0) - (all_eligible_trigger if s + k == PHYSICAL_GROUP_SIZE else 0.0)
    )
    return any_trigger, defect_only_any, nucleation, final_mixed


def group_outcomes(
    sample_id: str,
    strict: tuple[int, ...],
    candidate: tuple[int, ...],
    defect_seed: int,
    *,
    stored_draws: tuple[int, ...] | None = None,
) -> dict[str, GroupOutcome]:
    if len(strict) != PHYSICAL_GROUP_SIZE or len(candidate) != PHYSICAL_GROUP_SIZE:
        raise ValueError(f"strict and candidate vectors must have length {PHYSICAL_GROUP_SIZE}")
    if any(value not in (0, 1) for value in (*strict, *candidate)):
        raise ValueError("strict and candidate vectors must be binary")
    if any(a and b for a, b in zip(strict, candidate, strict=True)):
        raise ValueError("strict and candidate vectors must be disjoint")
    if stored_draws is not None and len(stored_draws) != PHYSICAL_GROUP_SIZE:
        raise ValueError(f"stored_draws must have length {PHYSICAL_GROUP_SIZE}")
    draws = stored_draws or tuple(defect_draw_u64(sample_id, slot, defect_seed) for slot in range(PHYSICAL_GROUP_SIZE))
    selected_32 = frozenset(eligible_slot_plan(sample_id, defect_seed, 32))
    s = sum(strict)
    c = sum(candidate)
    outcomes: dict[str, GroupOutcome] = {}
    for arm in ARM_SPECS:
        mask = range(PHYSICAL_GROUP_SIZE) if arm.eligible_slot_count == PHYSICAL_GROUP_SIZE else selected_32
        mask_set = frozenset(mask)
        eligible = tuple(slot for slot in mask_set if candidate[slot])
        triggered = tuple(slot for slot in eligible if runtime_trigger(draws[slot], arm))
        h = len(triggered)
        if arm.assignment == "behavior":
            recipient_candidate_count = h
        else:
            strict_negative = [slot for slot in mask_set if not strict[slot]]
            shuffle_draws = {
                slot: defect_draw_u64(sample_id, slot, defect_seed, shuffled=True) / UINT64_SPACE
                for slot in strict_negative
            }
            recipients = sorted(strict_negative, key=lambda slot: (shuffle_draws[slot], slot))[:h]
            if len(recipients) != h:
                raise ValueError("Shuffled recipient population is smaller than the behavior trigger count")
            recipient_candidate_count = sum(candidate[slot] for slot in recipients)
        probabilities = exact_group_probabilities(s, len(eligible), arm)
        outcomes[arm.label] = GroupOutcome(
            strict_count=s,
            candidate_count=c,
            eligible_candidate_count=len(eligible),
            trigger_count=h,
            recipient_candidate_count=recipient_candidate_count,
            expected_any_trigger=probabilities[0],
            expected_defect_only_any_trigger=probabilities[1],
            expected_nucleation=probabilities[2],
            expected_final_mixed=probabilities[3],
        )
    if outcomes["a3"].trigger_count != outcomes["aS"].trigger_count:
        raise RuntimeError("a3 and aS must preserve the exact behavior trigger count")
    return outcomes


def _validate_strict_row(
    row: object,
    *,
    prompt: PromptRecord,
    slot: int,
    bank_defect_seed: int,
    context: str,
) -> tuple[int, int, int]:
    if not isinstance(row, dict) or set(row) != STRICT_RESULT_FIELDS:
        fields = sorted(row) if isinstance(row, dict) else type(row).__name__
        raise ValueError(f"{context}: strict-result fields differ: {fields}")
    if row.get("op") != prompt.operation or row.get("__idx") != prompt.prompt_index:
        raise ValueError(f"{context}: strict-result operation/index differs from prompts.jsonl")
    if row.get("id") != prompt.sample_id or row.get("sample_rank") != slot:
        raise ValueError(f"{context}: strict-result group id/rank order differs")
    for field_name in ("perfect", "answer_correct", "candidate", "answer_mismatch"):
        if not isinstance(row.get(field_name), bool):
            raise ValueError(f"{context}.{field_name} must be boolean")
    perfect = int(row["perfect"])
    answer_correct = int(row["answer_correct"])
    candidate = int(row["candidate"])
    if candidate != int(answer_correct and not perfect):
        raise ValueError(f"{context}: candidate != answer_correct and not perfect")
    for field_name in (
        "value_mismatch_count",
        "dependency_mismatch_count",
        "extra_nodes",
        "missing_nodes",
    ):
        _require_int(row.get(field_name), f"{context}.{field_name}")
    draw_u64 = _require_int(row.get("defect_draw_u64"), f"{context}.defect_draw_u64")
    expected_draw_u64 = defect_draw_u64(prompt.sample_id, slot, bank_defect_seed)
    if draw_u64 != expected_draw_u64:
        raise ValueError(f"{context}: stored defect_draw_u64 does not match the bank hash contract")
    draw = row.get("defect_draw")
    if isinstance(draw, bool) or not isinstance(draw, (int, float)):
        raise ValueError(f"{context}.defect_draw must be numeric")
    if float(draw) != draw_u64 / UINT64_SPACE:
        raise ValueError(f"{context}: stored defect_draw does not equal defect_draw_u64 / 2**64")
    return perfect, candidate, draw_u64


def _stratum_keys(operation: int) -> tuple[tuple[str, str], ...]:
    band = next(name for name, operations in BANDS.items() if operation in operations)
    return (("all", "identified"), ("operation", str(operation)), ("band", band))


def _render_strata(
    accumulators: dict[tuple[str, str], MetricAccumulator],
    arm: ArmSpec,
) -> dict[str, object]:
    return {
        "all_identified": accumulators[("all", "identified")].as_dict(arm, include_histograms=True),
        "by_operation": {
            str(operation): accumulators[("operation", str(operation))].as_dict(arm, include_histograms=False)
            for operation in BANK_OPERATIONS
            if ("operation", str(operation)) in accumulators
        },
        "by_band": {
            band: accumulators[("band", band)].as_dict(arm, include_histograms=False)
            for band in BANDS
            if ("band", band) in accumulators
        },
    }


def _set_identity(values: set[str]) -> dict[str, object]:
    return {
        "count": len(values),
        "sorted_id_set_sha256": canonical_json_sha256(sorted(values)),
    }


def _set_overlap(left: set[str], right: set[str]) -> dict[str, object]:
    intersection = left & right
    union = left | right
    return {
        "left": _set_identity(left),
        "right": _set_identity(right),
        "intersection_count": len(intersection),
        "union_count": len(union),
        "left_only_count": len(left - right),
        "right_only_count": len(right - left),
        "symmetric_difference_count": len(left ^ right),
        "jaccard": _ratio(len(intersection), len(union)),
        "intersection_sorted_id_set_sha256": canonical_json_sha256(sorted(intersection)),
    }


def _event_value(summary: dict[str, object], event: str, field_name: str) -> float:
    group_events = _require_dict(summary["group_events"], "summary.group_events")
    event_summary = _require_dict(group_events[event], f"summary.group_events.{event}")
    value = event_summary[field_name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Event field {event}.{field_name} is not numeric")
    return float(value)


def _matched_pair_record(
    left: dict[str, object],
    right: dict[str, object],
    left_activated: set[str],
    right_activated: set[str],
) -> dict[str, object]:
    event_any = "any_trigger_H_gt_0"
    event_nucleation = "strict_dead_nucleation_S_eq_0_0_lt_H_lt_V"
    event_mixed = "final_mixed_0_lt_S_plus_H_lt_V"
    expected_field = "expected_groups_exact_conditional_formula"
    left_any = _event_value(left, event_any, expected_field)
    right_any = _event_value(right, event_any, expected_field)
    left_nucleation = _event_value(left, event_nucleation, expected_field)
    right_nucleation = _event_value(right, event_nucleation, expected_field)
    left_mixed = _event_value(left, event_mixed, expected_field)
    right_mixed = _event_value(right, event_mixed, expected_field)
    left_eligibility = _require_dict(left["eligibility_and_support"], "left.eligibility_and_support")
    right_eligibility = _require_dict(right["eligibility_and_support"], "right.eligibility_and_support")
    left_k = _require_int(left_eligibility["eligible_candidate_slots_K"], "left K")
    right_k = _require_int(right_eligibility["eligible_candidate_slots_K"], "right K")
    any_ratio = _ratio(right_any, left_any)
    nucleation_ratio = _ratio(right_nucleation, left_nucleation)
    margin_low = 1 / 1.20
    margin_high = 1.20
    return {
        "L32_over_L128_expected_any_trigger_ratio": any_ratio,
        "L32_over_L128_expected_nucleation_ratio": nucleation_ratio,
        "L32_over_L128_expected_final_mixed_ratio": _ratio(right_mixed, left_mixed),
        "mechanism_margin": [margin_low, margin_high],
        "mechanism_margin_pass": (
            any_ratio is not None
            and nucleation_ratio is not None
            and margin_low <= any_ratio <= margin_high
            and margin_low <= nucleation_ratio <= margin_high
        ),
        "K": {
            "L128": left_k,
            "L32": right_k,
            "four_times_L32_over_L128": _ratio(4 * right_k, left_k),
            "L128_minus_L32": left_k - right_k,
            "L32_support_lost_groups": right_eligibility["support_lost_groups_C_gt_0_K_eq_0"],
        },
        "realized_activated_group_overlap": _set_overlap(left_activated, right_activated),
    }


def _partial_identification_bounds(
    covered: dict[str, object],
    arm: ArmSpec,
    unidentified_groups: int,
) -> dict[str, object]:
    events = _require_dict(covered["group_events"], "covered.group_events")
    result_events: dict[str, object] = {}
    for event_name in (
        "any_trigger_H_gt_0",
        "defect_only_any_trigger_S_eq_0_H_gt_0",
        "strict_dead_nucleation_S_eq_0_0_lt_H_lt_V",
        "final_mixed_0_lt_S_plus_H_lt_V",
    ):
        summary = _require_dict(events[event_name], f"covered.group_events.{event_name}")
        expected = float(summary["expected_groups_exact_conditional_formula"])
        realized = int(summary["realized_groups"])
        result_events[event_name] = {
            "expected_group_count_bounds": [expected, expected + unidentified_groups],
            "realized_group_count_bounds": [realized, realized + unidentified_groups],
        }
    trigger_slots = _require_dict(covered["trigger_slots"], "covered.trigger_slots")
    expected_triggers = float(trigger_slots["expected_p_times_K"])
    realized_triggers = int(trigger_slots["realized_H"])
    max_missing_trigger_slots = unidentified_groups * arm.eligible_slot_count
    return {
        "identification": "bounds only; no OP13/14 outcome imputation",
        "unidentified_groups": unidentified_groups,
        "eligible_candidate_slots_K_bounds": [
            int(_require_dict(covered["eligibility_and_support"], "eligibility")["eligible_candidate_slots_K"]),
            int(_require_dict(covered["eligibility_and_support"], "eligibility")["eligible_candidate_slots_K"])
            + max_missing_trigger_slots,
        ],
        "expected_trigger_slots_bounds": [
            expected_triggers,
            expected_triggers + arm.probability * max_missing_trigger_slots,
        ],
        "realized_trigger_slots_bounds": [realized_triggers, realized_triggers + max_missing_trigger_slots],
        "group_events": result_events,
    }


def _scan_strict_results(
    contract: BankContract,
    prompts: tuple[PromptRecord, ...],
    prefix_covered_ids: set[str],
) -> tuple[
    FileIdentity,
    dict[tuple[int, str, str], dict[tuple[str, str], MetricAccumulator]],
    dict[tuple[int, str, str], set[str]],
    dict[tuple[int, str, str], set[str]],
    dict[str, int],
]:
    path = contract.root / "strict_results.jsonl"
    digest = hashlib.sha256()
    size = 0
    rows = 0
    accumulators: dict[tuple[int, str, str], dict[tuple[str, str], MetricAccumulator]] = defaultdict(
        lambda: defaultdict(MetricAccumulator)
    )
    activated: dict[tuple[int, str, str], set[str]] = defaultdict(set)
    supported: dict[tuple[int, str, str], set[str]] = defaultdict(set)
    strict: list[int] = []
    candidate: list[int] = []
    stored_draws: list[int] = []
    bank_counts = Counter[str]()
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            digest.update(line)
            size += len(line)
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank JSONL records are not allowed")
            group_index, slot = divmod(line_number - 1, PHYSICAL_GROUP_SIZE)
            if group_index >= len(prompts):
                raise ValueError(f"{path}:{line_number}: contains more groups than prompts.jsonl")
            prompt = prompts[group_index]
            row = orjson.loads(line)
            perfect, is_candidate, draw_u64 = _validate_strict_row(
                row,
                prompt=prompt,
                slot=slot,
                bank_defect_seed=contract.bank_defect_seed,
                context=f"{path}:{line_number}",
            )
            strict.append(perfect)
            candidate.append(is_candidate)
            stored_draws.append(draw_u64)
            rows += 1
            if slot != PHYSICAL_GROUP_SIZE - 1:
                continue

            strict_tuple = tuple(strict)
            candidate_tuple = tuple(candidate)
            stored_draw_tuple = tuple(stored_draws)
            bank_counts["strict_positive_slots"] += sum(strict_tuple)
            bank_counts["candidate_slots"] += sum(candidate_tuple)
            bank_counts["strict_dead_groups"] += int(not any(strict_tuple))
            bank_counts["clean_mixed_groups"] += int(0 < sum(strict_tuple) < PHYSICAL_GROUP_SIZE)
            bank_counts["all_strict_positive_groups"] += int(sum(strict_tuple) == PHYSICAL_GROUP_SIZE)
            in_prefix = prompt.sample_id in prefix_covered_ids
            for seed in DEFECT_SEEDS:
                outcomes = group_outcomes(
                    prompt.sample_id,
                    strict_tuple,
                    candidate_tuple,
                    seed,
                    stored_draws=stored_draw_tuple if seed == contract.bank_defect_seed else None,
                )
                for arm in ARM_SPECS:
                    outcome = outcomes[arm.label]
                    for key in _stratum_keys(prompt.operation):
                        accumulators[(seed, arm.label, "bank")][key].add(outcome)
                        if in_prefix:
                            accumulators[(seed, arm.label, "prefix")][key].add(outcome)
                    if outcome.any_trigger:
                        activated[(seed, arm.label, "bank")].add(prompt.sample_id)
                        if in_prefix:
                            activated[(seed, arm.label, "prefix")].add(prompt.sample_id)
                    if outcome.eligible_candidate_count > 0:
                        supported[(seed, arm.label, "bank")].add(prompt.sample_id)
                        if in_prefix:
                            supported[(seed, arm.label, "prefix")].add(prompt.sample_id)
            strict.clear()
            candidate.clear()
            stored_draws.clear()
    if strict or candidate or stored_draws:
        raise ValueError("strict_results.jsonl ends inside a 128-row group")
    identity = FileIdentity(str(path.resolve()), size, digest.hexdigest(), rows)
    _verify_completion_artifact(contract, "strict_results", identity)
    return identity, accumulators, activated, supported, dict(bank_counts)


def _overlap_report(
    activated: dict[tuple[int, str, str], set[str]],
    scope: str,
) -> dict[str, object]:
    within_comparisons = {
        "low_L128_a1_vs_L32_a2": ("a1", "a2"),
        "high_L128_a3_vs_L32_a4": ("a3", "a4"),
        "nested_L128_low_a1_vs_high_a3": ("a1", "a3"),
        "nested_L32_low_a2_vs_high_a4": ("a2", "a4"),
        "behavior_a3_vs_shuffled_aS": ("a3", "aS"),
    }
    within_seed = {
        str(seed): {
            name: _set_overlap(
                activated[(seed, left, scope)],
                activated[(seed, right, scope)],
            )
            for name, (left, right) in within_comparisons.items()
        }
        for seed in DEFECT_SEEDS
    }
    across_seed: dict[str, object] = {}
    for arm in ARM_SPECS:
        comparisons = {}
        for left_index, left_seed in enumerate(DEFECT_SEEDS):
            for right_seed in DEFECT_SEEDS[left_index + 1 :]:
                comparisons[f"{left_seed}_vs_{right_seed}"] = _set_overlap(
                    activated[(left_seed, arm.label, scope)],
                    activated[(right_seed, arm.label, scope)],
                )
        across_seed[arm.label] = comparisons
    return {"within_seed": within_seed, "across_seed": across_seed}


def analyze(
    bank_root: Path,
    train_dataset: Path,
    *,
    prefix_groups: int = SCHEDULE_PREFIX_GROUPS,
    schedule_seed: int = SCHEDULE_SEED,
    expected_contract_sha256: str | None = EXPECTED_BANK_CONTRACT_SHA256,
    expected_train_sha256: str | None = EXPECTED_TRAIN_DATASET_SHA256,
    runtime_environment_path: Path | None = None,
    train_source_path: Path | None = None,
) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[3]
    runtime_environment_path = runtime_environment_path or (repo_root / "user/tianhaowu/rsci/rsci_gsm_infinite.py")
    train_source_path = train_source_path or (repo_root / "src/prime_rl/orchestrator/train_source.py")
    implementation_before = {
        "analyzer": file_identity(Path(__file__).resolve()),
        "runtime_environment": file_identity(runtime_environment_path),
        "train_source": file_identity(train_source_path),
    }

    contract = load_bank_contract(
        bank_root,
        expected_contract_sha256=expected_contract_sha256,
    )
    train_records, train_prompt_by_id, train_identity = load_train_dataset(
        train_dataset,
        examples_per_operation=contract.examples_per_operation,
        expected_sha256=expected_train_sha256,
    )
    prompts, prompts_identity = load_bank_prompts(contract, train_prompt_by_id)
    bank_ids = {prompt.sample_id for prompt in prompts}
    train_ids = set(train_prompt_by_id)
    extra_train_ids = train_ids - bank_ids
    expected_extra_ids = {record.sample_id for record in train_records if record.operation in {13, 14}}
    if bank_ids - train_ids:
        raise ValueError("Some bank prompt ids are absent from the training dataset")
    if extra_train_ids != expected_extra_ids:
        raise ValueError("Training ids outside the bank must be exactly OP13/14")
    del train_prompt_by_id

    prefix = scheduled_prefix(train_records, seed=schedule_seed, prefix_groups=prefix_groups)
    prefix_ids = {record.sample_id for record in prefix}
    if len(prefix_ids) != len(prefix):
        raise ValueError("The scheduled first-epoch prefix unexpectedly repeats a sample id")
    prefix_covered_ids = prefix_ids & bank_ids
    prefix_unidentified = tuple(record for record in prefix if record.sample_id not in bank_ids)
    if any(record.operation not in {13, 14} for record in prefix_unidentified):
        raise ValueError("Only OP13/14 may be unidentified by the frozen bank")

    generations_identity = jsonl_identity(contract.root / "generations.jsonl")
    _verify_completion_artifact(contract, "generations", generations_identity)
    strict_identity, accumulators, activated, supported, bank_counts = _scan_strict_results(
        contract,
        prompts,
        prefix_covered_ids,
    )

    results: dict[str, object] = {}
    pair_calibration: dict[str, object] = {}
    for seed in DEFECT_SEEDS:
        seed_results: dict[str, object] = {}
        seed_pairs: dict[str, object] = {}
        for arm in ARM_SPECS:
            bank_summary = _render_strata(accumulators[(seed, arm.label, "bank")], arm)
            prefix_summary = _render_strata(accumulators[(seed, arm.label, "prefix")], arm)
            prefix_all = _require_dict(prefix_summary["all_identified"], "prefix all")
            seed_results[arm.label] = {
                "arm": arm.as_dict(),
                "frozen_bank": bank_summary,
                "scheduled_prefix_covered": prefix_summary,
                "scheduled_prefix_partial_identification": _partial_identification_bounds(
                    prefix_all,
                    arm,
                    len(prefix_unidentified),
                ),
                "activated_group_sets": {
                    "frozen_bank": _set_identity(activated[(seed, arm.label, "bank")]),
                    "scheduled_prefix_covered": _set_identity(activated[(seed, arm.label, "prefix")]),
                },
                "eligible_support_group_sets": {
                    "frozen_bank": _set_identity(supported[(seed, arm.label, "bank")]),
                    "scheduled_prefix_covered": _set_identity(supported[(seed, arm.label, "prefix")]),
                },
            }
        for scope in ("bank", "prefix"):
            rendered = {
                label: accumulators[(seed, label, scope)][("all", "identified")].as_dict(
                    ARM_BY_LABEL[label], include_histograms=False
                )
                for label in ("a1", "a2", "a3", "a4")
            }
            seed_pairs[scope] = {
                "low_a1_L128_vs_a2_L32": _matched_pair_record(
                    rendered["a1"],
                    rendered["a2"],
                    activated[(seed, "a1", scope)],
                    activated[(seed, "a2", scope)],
                ),
                "high_a3_L128_vs_a4_L32": _matched_pair_record(
                    rendered["a3"],
                    rendered["a4"],
                    activated[(seed, "a3", scope)],
                    activated[(seed, "a4", scope)],
                ),
            }
        results[str(seed)] = seed_results
        pair_calibration[str(seed)] = seed_pairs

    unidentified_by_operation = Counter(record.operation for record in prefix_unidentified)
    covered_by_operation = Counter(record.operation for record in prefix if record.sample_id in bank_ids)
    scheduled_by_operation = Counter(record.operation for record in prefix)
    analysis_contract = {
        "physical_group_size_V": PHYSICAL_GROUP_SIZE,
        "defect_seeds": list(DEFECT_SEEDS),
        "arms": [arm.as_dict() for arm in ARM_SPECS],
        "mask_rule": (
            "select the L smallest full SHA-256 digests of "
            "seed:eligible-slot-mask-v1:json([sample_id,slot]), tie-break by slot"
        ),
        "coin_rule": (
            "uint64 = first 8 big-endian SHA-256 bytes of seed:json([sample_id,slot]); "
            "runtime trigger is uint64/2**64 < p"
        ),
        "shuffle_rule": (
            "within masked strict negatives, sort first-64-bit "
            "seed:group-shuffle:json([sample_id,slot]) draws then slot; take H"
        ),
        "expected_any_trigger": "1 - (1-p)^K",
        "expected_strict_dead_nucleation": ("1[S=0] * (1 - (1-p)^K - 1[K=V] p^K)"),
        "expected_final_mixed": ("1 - 1[S=0](1-p)^K - 1[S+K=V]p^K"),
        "activated_set_unit": "sample_id with realized H > 0",
        "bands": {name: sorted(operations) for name, operations in BANDS.items()},
        "schedule": {
            "seed": schedule_seed,
            "prefix_groups": prefix_groups,
            "rule": "random.Random(seed).shuffle(list(range(num_tasks)))[:prefix_groups]",
            "clock": "initial dispatch order for the sole training environment",
        },
    }
    report: dict[str, object] = {
        "analysis_version": ANALYSIS_VERSION,
        "analysis_contract": analysis_contract,
        "analysis_contract_sha256": canonical_json_sha256(analysis_contract),
        "provenance": {
            "bank_contract_sha256": contract.contract_sha256,
            "bank_scoring_implementation_sha256": contract.manifest["contract"]["scoring"]["implementation_sha256"],
            "inputs": {
                "bank_manifest": contract.manifest_identity.as_dict(),
                "bank_completion": contract.completion_identity.as_dict(),
                "bank_prompts": prompts_identity.as_dict(),
                "bank_generations": generations_identity.as_dict(),
                "bank_strict_results": strict_identity.as_dict(),
                "online_train_dataset": train_identity.as_dict(),
            },
            "implementations": {name: identity.as_dict() for name, identity in implementation_before.items()},
            "python_version": sys.version,
        },
        "integrity": {
            "bank_contract_canonical_hash_validated": True,
            "completion_artifact_paths_sizes_rows_hashes_validated": True,
            "prompt_and_strict_group_order_validated": True,
            "strict_result_exact_schema_validated": True,
            "candidate_identity_validated_on_every_row": True,
            "stored_bank_draw_validated_on_every_row": True,
            "runtime_mask_and_coin_rules_replayed_independently": True,
            "train_dataset_order_ids_and_prompt_uniqueness_validated": True,
            "bank_train_id_and_prompt_join_validated": True,
            "bank_counts": {
                "groups": contract.groups,
                "trajectories": contract.trajectories,
                **bank_counts,
            },
        },
        "scheduled_prefix": {
            "train_dataset_groups": len(train_records),
            "requested_dispatch_prefix_groups": prefix_groups,
            "schedule_seed": schedule_seed,
            "scheduled_task_index_sequence_sha256": canonical_json_sha256([record.task_index for record in prefix]),
            "scheduled_sample_id_sequence_sha256": canonical_json_sha256([record.sample_id for record in prefix]),
            "scheduled_by_operation": {
                str(operation): scheduled_by_operation[operation] for operation in TRAIN_OPERATIONS
            },
            "covered_by_frozen_bank_groups": len(prefix_covered_ids),
            "covered_sample_id_set_sha256": canonical_json_sha256(sorted(prefix_covered_ids)),
            "covered_by_operation": {str(operation): covered_by_operation[operation] for operation in BANK_OPERATIONS},
            "unidentified_groups": len(prefix_unidentified),
            "unidentified_by_operation": {
                str(operation): unidentified_by_operation[operation] for operation in (13, 14)
            },
            "unidentified_sample_id_set_sha256": canonical_json_sha256(
                sorted(record.sample_id for record in prefix_unidentified)
            ),
            "finalization_caveat": (
                "This is the exact seed-42 initial dispatch prefix. Asynchronous rollout completion can "
                "change which dispatched groups form the first 12,000 finalized groups; use the audited "
                "train_group_stats stream for the realized G12000 clock."
            ),
            "projection_caveat": (
                "Covered values replay the frozen base-policy generation bank on exact scheduled prompt ids. "
                "OP13/14 are not imputed, and later policy-dependent K/H are not predicted."
            ),
        },
        "per_seed_arm": results,
        "matched_pair_calibration": pair_calibration,
        "activated_set_overlap": {
            "frozen_bank": _overlap_report(activated, "bank"),
            "scheduled_prefix_covered": _overlap_report(activated, "prefix"),
        },
    }
    implementation_after = {
        "analyzer": file_identity(Path(__file__).resolve()),
        "runtime_environment": file_identity(runtime_environment_path),
        "train_source": file_identity(train_source_path),
    }
    if implementation_after != implementation_before:
        raise RuntimeError("An analysis implementation file changed while the preflight was running")
    report["payload_without_self_hash_sha256"] = canonical_json_sha256(report)
    return report


def write_json_atomic(path: Path, payload: object) -> FileIdentity:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return file_identity(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank-root", type=Path, default=DEFAULT_BANK_ROOT)
    parser.add_argument("--train-dataset", type=Path, default=DEFAULT_TRAIN_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix-groups", type=int, default=SCHEDULE_PREFIX_GROUPS)
    parser.add_argument("--schedule-seed", type=int, default=SCHEDULE_SEED)
    parser.add_argument(
        "--expected-bank-contract-sha256",
        default=EXPECTED_BANK_CONTRACT_SHA256,
    )
    parser.add_argument(
        "--expected-train-sha256",
        default=EXPECTED_TRAIN_DATASET_SHA256,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = analyze(
        args.bank_root,
        args.train_dataset,
        prefix_groups=args.prefix_groups,
        schedule_seed=args.schedule_seed,
        expected_contract_sha256=args.expected_bank_contract_sha256,
        expected_train_sha256=args.expected_train_sha256,
    )
    identity = write_json_atomic(args.output, report)
    print(json.dumps({"output": identity.as_dict()}, sort_keys=True))


if __name__ == "__main__":
    main()
