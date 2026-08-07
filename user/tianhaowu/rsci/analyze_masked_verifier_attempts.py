#!/usr/bin/env python3
"""Audit masked verifier-defect groups and their raw training-attempt clock."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANALYSIS_VERSION = "masked_verifier_defect_attempts_v5"
PHYSICAL_GROUP_SIZE = 128
NEUTRAL_TAG_COUNT = 6
NEUTRAL_TAG_COLUMN = "neutral_tag_index"
TARGET_ATTEMPTED_GROUPS = 12_000
TARGET_SHIPPED_UPDATES = 1_500
HARD_GUARD_ATTEMPTED_GROUPS = 20_000
HARD_GUARD_SHIPPED_UPDATES = 3_000

STRICT_METRIC = "strict_dependency_graph_reward"
ANSWER_METRIC = "answer_correct_metric"
CANDIDATE_METRIC = "defect_candidate_metric"
SCOPE_ELIGIBLE_METRIC = "defect_scope_eligible_metric"
EFFECTIVE_ELIGIBLE_METRIC = "defect_eligible_metric"
GATE_ELIGIBLE_METRIC = "defect_gate_eligible_metric"
SLOT_MASK_METRIC = "defect_slot_mask_metric"
SLOT_RANK_METRIC = "defect_slot_rank_metric"
ELIGIBLE_SLOT_COUNT_METRIC = "defect_eligible_slot_count_metric"
BEHAVIOR_TRIGGER_METRIC = "behavior_triggered_metric"
SHUFFLED_TRIGGER_METRIC = "shuffled_triggered_metric"
MIN_BEHAVIOR_TRIGGER_METRIC = "min_behavior_triggered_metric"
SELECTED_TRIGGER_METRIC = "defect_triggered_metric"
FALSE_NEGATIVE_METRIC = "false_negative_triggered_metric"
DEFECT_DRAW_METRIC = "defect_draw_metric"
SHUFFLE_DRAW_METRIC = "shuffle_draw_metric"
RATE_METRIC = "defect_rate_metric"
NOMINAL_RATE_METRIC = "defect_nominal_rate_metric"
CONDITIONAL_RATE_METRIC = "defect_conditional_rate_metric"
GATE_OPEN_METRIC = "defect_gate_open_metric"
GATE_DRAW_METRIC = "defect_gate_draw_metric"
GATE_PROBABILITY_METRIC = "defect_gate_probability_metric"
GATE_MODE_METRIC = "defect_gate_mode_metric"
TEMPLATE_INDEX_METRIC = "defect_template_index_metric"
SELECTED_TEMPLATE_INDEX_METRIC = "defect_selected_template_index_metric"
ROLLOUT_SLOT_METRIC = "defect_rollout_slot_metric"
MATCHED_COUNT_METRIC = "matched_extra_positive_count_metric"
VALID_METRIC = "valid_rollout_metric"
BEHAVIOR_PROXY_METRIC = "behavior_proxy_reward"
SHUFFLED_PROXY_METRIC = "shuffled_proxy_reward"
MIN_BEHAVIOR_PROXY_METRIC = "min_behavior_proxy_reward"
PROXY_METRIC = "proxy_reward"
UNTAXED_PROXY_METRIC = "untaxed_proxy_reward"
NET_BEHAVIOR_REWARD_METRIC = "defect_net_behavior_reward_metric"
BEHAVIOR_UNTAXED_PROXY_METRIC = "behavior_untaxed_proxy_reward"
SHUFFLED_UNTAXED_PROXY_METRIC = "shuffled_untaxed_proxy_reward"
MIN_BEHAVIOR_UNTAXED_PROXY_METRIC = "min_behavior_untaxed_proxy_reward"
BEHAVIOR_NET_REWARD_METRIC = "behavior_net_behavior_reward_metric"
SHUFFLED_NET_REWARD_METRIC = "shuffled_net_behavior_reward_metric"
MIN_BEHAVIOR_NET_REWARD_METRIC = "min_behavior_net_behavior_reward_metric"
BEHAVIOR_TAX_C0_METRIC = "behavior_tax_c0_metric"
BEHAVIOR_TAX_APPLIED_METRIC = "behavior_tax_applied_metric"
STRICT_REWARD_WEIGHT_METRIC = "strict_reward_weight_metric"
NEUTRAL_TAG_INDEX_METRIC = "defect_neutral_tag_index_metric"
NEUTRAL_TAG_SELECTED_METRIC = "defect_neutral_tag_selected_metric"
NEUTRAL_TAG_COUNT_METRIC = "defect_neutral_tag_count_metric"
SELECTED_NEUTRAL_TAG_COUNT_METRIC = "defect_selected_neutral_tag_count_metric"

GSM_TEMPLATES = (
    "crazy_zootopia",
    "movie_festival_awards",
    "teachers_in_school",
)
TEMPLATE_INDEX = {template: index for index, template in enumerate(GSM_TEMPLATES)}
GATE_MODE_INDEX = {"none": 0, "group": 1, "template": 2, "neutral_tag": 3}


@dataclass(frozen=True)
class MaskedContract:
    environment_name: str
    defect_assignment: str
    false_positive_rate: float
    defect_seed: int
    eligible_slot_count: int
    defect_gate_mode: str = "none"
    defect_gate_probability: float = 1.0
    defect_selected_template: str | None = None
    dataset_path: Path | None = None
    physical_group_size: int = PHYSICAL_GROUP_SIZE
    defect_neutral_tag_count: int = NEUTRAL_TAG_COUNT
    defect_selected_neutral_tags: tuple[int, ...] = ()
    defect_reference_neutral_tags: tuple[int, ...] = ()
    behavior_tax_c0: float = 0.0
    strict_reward_weight: float = 1.0

    @property
    def optimized_proxy_metric(self) -> str:
        prefix = self.defect_assignment.removesuffix("_group")
        return f"{prefix}_proxy_reward"

    @property
    def conditional_false_positive_rate(self) -> float:
        return self.false_positive_rate / self.defect_gate_probability

    @property
    def requires_tagged_dataset(self) -> bool:
        return self.defect_gate_mode == "neutral_tag" or bool(self.defect_reference_neutral_tags)


@dataclass(frozen=True)
class DatasetSample:
    template: str
    neutral_tag_index: int | None = None
    operation: int | None = None


@dataclass(frozen=True)
class AuditedSlot:
    strict: int
    candidate: int
    effective_eligible: int
    behavior_triggered: int
    selected_triggered: int
    neutral_tag_index: int | None
    neutral_tag_selected: bool
    tax_applied: float
    net_behavior_reward: float
    proxy_reward: float
    appended: bool


@dataclass(frozen=True)
class AuditedGroup:
    group_id: str
    group_index: int
    finalized_before_optimizer_step: int
    sample_id: str
    template: str | None
    neutral_tag_index: int | None
    neutral_tag_selected: bool
    gate_open: bool
    reward_scored: bool
    errored_count: int
    valid_count: int
    valid_masked_count: int
    strict_positive_count: int
    candidate_count: int
    scope_eligible_count: int
    effective_eligible_count: int
    behavior_trigger_count: int
    selected_trigger_count: int
    selected_candidate_count: int
    selected_original_trigger_count: int
    tax_applied_total: float
    net_behavior_reward_total: float
    proxy_rewards: tuple[float, ...]
    mixed_activation_probability: float | None
    mixed_activation_observed: bool | None
    slots: tuple[AuditedSlot, ...]
    appended_indices: tuple[int, ...]

    def as_dict(self, contract: MaskedContract) -> dict[str, object]:
        defect_only_triggered = (
            self.reward_scored and self.strict_positive_count == 0 and self.behavior_trigger_count > 0
        )
        defect_only_activation = bool(defect_only_triggered and self.behavior_trigger_count < self.valid_count)
        return {
            "group_id": self.group_id,
            "group_index": self.group_index,
            "finalized_before_optimizer_step": self.finalized_before_optimizer_step,
            "sample_id": self.sample_id,
            "template": self.template,
            "neutral_tag_index": self.neutral_tag_index,
            "neutral_tag_selected": self.neutral_tag_selected,
            "defect_gate_open": self.gate_open,
            "reward_scored": self.reward_scored,
            "errored_count": self.errored_count,
            "V_physical_target_size": contract.physical_group_size,
            "V_valid_count": self.valid_count,
            "L_masked_slot_count": contract.eligible_slot_count,
            "M_valid_masked_slot_count": self.valid_masked_count,
            "S_strict_positive_count": self.strict_positive_count,
            "C_candidate_count": self.candidate_count,
            "E_scope_eligible_count": self.scope_eligible_count,
            "K_effective_eligible_count": self.effective_eligible_count,
            "H_behavior_trigger_count": self.behavior_trigger_count,
            "selected_extra_positive_count": self.selected_trigger_count,
            "selected_behavior_candidate_count": self.selected_candidate_count,
            "selected_behavior_candidate_fraction": (
                self.selected_candidate_count / self.selected_trigger_count if self.selected_trigger_count else None
            ),
            "selected_original_behavior_trigger_count": self.selected_original_trigger_count,
            "selected_original_behavior_trigger_fraction": (
                self.selected_original_trigger_count / self.selected_trigger_count
                if self.selected_trigger_count
                else None
            ),
            "behavior_tax_applied_total": self.tax_applied_total,
            "selected_net_behavior_reward_total": self.net_behavior_reward_total,
            "proxy_reward_histogram": _reward_histogram(self.proxy_rewards),
            "negative_proxy_reward_count": sum(value < 0.0 for value in self.proxy_rewards),
            "mixed_activation_probability_exact": self.mixed_activation_probability,
            "mixed_activation_observed": self.mixed_activation_observed,
            "defect_only_triggered_observed": defect_only_triggered,
            "defect_only_activation_observed": defect_only_activation,
            "appended_count": len(self.appended_indices),
        }


@dataclass(frozen=True)
class AuditedAttempt:
    batch_attempt: int
    optimizer_step: int
    eligible_to_ship: bool
    n_rollouts: int
    n_trainable: int
    strict_positive_count: int
    candidate_count: int
    effective_eligible_count: int
    behavior_trigger_count: int
    selected_trigger_count: int
    selected_candidate_count: int
    selected_original_trigger_count: int
    tax_applied_total: float
    net_behavior_reward_total: float
    proxy_rewards: tuple[float, ...]
    group_slices: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "batch_attempt": self.batch_attempt,
            "raw_attempt_index": self.batch_attempt - 1,
            "optimizer_step_before_attempt": self.optimizer_step,
            "eligible_to_ship": self.eligible_to_ship,
            "n_rollouts": self.n_rollouts,
            "n_trainable": self.n_trainable,
            "S_strict_positive_count": self.strict_positive_count,
            "C_candidate_count": self.candidate_count,
            "A_candidate_prevalence": self.candidate_count / self.n_rollouts,
            "K_effective_eligible_count": self.effective_eligible_count,
            "H_behavior_trigger_count": self.behavior_trigger_count,
            "selected_extra_positive_count": self.selected_trigger_count,
            "selected_behavior_candidate_count": self.selected_candidate_count,
            "selected_behavior_candidate_fraction": (
                self.selected_candidate_count / self.selected_trigger_count if self.selected_trigger_count else None
            ),
            "selected_original_behavior_trigger_count": self.selected_original_trigger_count,
            "selected_original_behavior_trigger_fraction": (
                self.selected_original_trigger_count / self.selected_trigger_count
                if self.selected_trigger_count
                else None
            ),
            "behavior_tax_applied_total": self.tax_applied_total,
            "selected_net_behavior_reward_total": self.net_behavior_reward_total,
            "proxy_reward_histogram": _reward_histogram(self.proxy_rewards),
            "negative_proxy_reward_count": sum(value < 0.0 for value in self.proxy_rewards),
            "group_slices": list(self.group_slices),
        }


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _require_list(value: Any, context: str, length: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    if length is not None and len(value) != length:
        raise ValueError(f"{context} has length {len(value)}, expected {length}")
    return value


def _require_str(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _require_int(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer >= {minimum}")
    return value


def _require_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _require_nonnegative_number(value: Any, context: str) -> float:
    result = _require_number(value, context)
    if result < 0.0:
        raise ValueError(f"{context} must be non-negative")
    return result


def _normalize_neutral_tags(value: Any, context: str) -> tuple[int, ...]:
    tags = _require_list(value, context)
    normalized = tuple(_require_int(tag, f"{context}[{index}]") for index, tag in enumerate(tags))
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{context} must not contain duplicates")
    if any(tag >= NEUTRAL_TAG_COUNT for tag in normalized):
        raise ValueError(f"{context} must contain only indices in [0, {NEUTRAL_TAG_COUNT})")
    return tuple(sorted(normalized))


def _reward_histogram(values: tuple[float, ...] | list[float]) -> dict[str, int]:
    counts: dict[float, int] = defaultdict(int)
    for value in values:
        counts[0.0 if value == 0.0 else value] += 1
    return {json.dumps(value, allow_nan=False): counts[value] for value in sorted(counts)}


def _require_binary(value: Any, context: str) -> int:
    result = _require_number(value, context)
    if result not in (0.0, 1.0):
        raise ValueError(f"{context} must be exactly 0 or 1")
    return int(result)


def _binary_metric(metrics: dict[str, Any], name: str, context: str, size: int) -> list[int]:
    values = _require_list(metrics.get(name), f"{context}.metrics.{name}", size)
    return [_require_binary(value, f"{context}.metrics.{name}[{index}]") for index, value in enumerate(values)]


def _numeric_metric(metrics: dict[str, Any], name: str, context: str, size: int) -> list[float]:
    values = _require_list(metrics.get(name), f"{context}.metrics.{name}", size)
    return [_require_number(value, f"{context}.metrics.{name}[{index}]") for index, value in enumerate(values)]


def file_identity(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"path": str(path.resolve()), "size_bytes": size, "sha256": digest.hexdigest()}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank records are not allowed")
            rows.append(_require_dict(json.loads(line), f"{path}:{line_number}"))
    if not rows:
        raise ValueError(f"{path} contains no records")
    return rows


def load_contract(orchestrator_path: Path) -> MaskedContract:
    if not orchestrator_path.is_file():
        raise FileNotFoundError(orchestrator_path)
    with orchestrator_path.open("rb") as handle:
        orchestrator = tomllib.load(handle)
    if orchestrator.get("save_train_group_stats") is not True:
        raise ValueError("Resolved orchestrator config must enable save_train_group_stats")
    if orchestrator.get("group_size") != PHYSICAL_GROUP_SIZE:
        raise ValueError(f"Resolved orchestrator group_size must equal {PHYSICAL_GROUP_SIZE}")
    if orchestrator.get("batch_size") != 512:
        raise ValueError("Resolved orchestrator batch_size must equal 512")
    if orchestrator.get("max_steps") != HARD_GUARD_SHIPPED_UPDATES:
        raise ValueError(f"Resolved orchestrator max_steps must equal {HARD_GUARD_SHIPPED_UPDATES}")
    if orchestrator.get("max_finalized_groups") != HARD_GUARD_ATTEMPTED_GROUPS:
        raise ValueError(f"Resolved orchestrator max_finalized_groups must equal {HARD_GUARD_ATTEMPTED_GROUPS}")
    if orchestrator.get("stop_when") != {
        "min_steps": TARGET_SHIPPED_UPDATES,
        "min_finalized_groups": TARGET_ATTEMPTED_GROUPS,
        "step_multiple": 50,
    }:
        raise ValueError("Resolved orchestrator stop_when does not match the preregistered joint target")
    checkpoint = _require_dict(orchestrator.get("ckpt"), "ckpt")
    if checkpoint.get("interval") != 25 or checkpoint.get("keep_interval") != 50:
        raise ValueError("Resolved orchestrator checkpoint cadence must save every 25 and retain every 50 steps")
    if orchestrator.get("drop_context_limits_before_advantage") is not False:
        raise ValueError("Resolved orchestrator config must explicitly disable pre-advantage context-limit dropping")
    train = _require_dict(orchestrator.get("train"), "train")
    environments = _require_list(train.get("env"), "train.env")
    if len(environments) != 1:
        raise ValueError("Masked attempt analysis requires exactly one training environment")
    environment = _require_dict(environments[0], "train.env[0]")
    if environment.get("group_size") != PHYSICAL_GROUP_SIZE:
        raise ValueError(f"train.env[0].group_size must equal {PHYSICAL_GROUP_SIZE}")
    environment_name = _require_str(environment.get("name"), "train.env[0].name")
    args = _require_dict(environment.get("args"), "train.env[0].args")
    if args.get("min_op") != 10 or args.get("max_op") != 40:
        raise ValueError("Masked Stage-1 training must use exactly OP10-40")
    if args.get("require_unique_prompts") is not True:
        raise ValueError("Masked Stage-1 training must require unique prompts")
    assignment = _require_str(args.get("defect_assignment"), "train.env[0].args.defect_assignment")
    if assignment not in {"behavior_group", "shuffled_group", "min_behavior_group"}:
        raise ValueError("defect_assignment must be behavior_group, shuffled_group, or min_behavior_group")
    if args.get("defect_draw_scope") != "sample_slot":
        raise ValueError("defect_draw_scope must explicitly equal 'sample_slot'")
    if args.get("false_positive_scope") != "answer_correct_strict_wrong":
        raise ValueError("false_positive_scope must explicitly equal 'answer_correct_strict_wrong'")
    if _require_number(args.get("false_negative_rate"), "false_negative_rate") != 0.0:
        raise ValueError("false_negative_rate must equal zero")
    if args.get("false_positive_rates_by_op") not in (None, {}):
        raise ValueError("Operation-specific false-positive rates are not supported")
    rate = _require_number(args.get("false_positive_rate"), "false_positive_rate")
    if not 0.0 <= rate <= 1.0:
        raise ValueError("false_positive_rate must lie in [0, 1]")
    seed = _require_int(args.get("defect_seed"), "defect_seed")
    eligible_slot_count = _require_int(args.get("defect_eligible_slot_count"), "defect_eligible_slot_count")
    if eligible_slot_count > PHYSICAL_GROUP_SIZE:
        raise ValueError(f"defect_eligible_slot_count must not exceed {PHYSICAL_GROUP_SIZE}")
    gate_mode = args.get("defect_gate_mode", "none")
    if gate_mode not in GATE_MODE_INDEX:
        raise ValueError(f"defect_gate_mode must be one of {sorted(GATE_MODE_INDEX)}")
    gate_probability = _require_number(args.get("defect_gate_probability", 1.0), "defect_gate_probability")
    if not 0.0 < gate_probability <= 1.0:
        raise ValueError("defect_gate_probability must lie in (0, 1]")
    neutral_tag_count = _require_int(
        args.get("defect_neutral_tag_count", NEUTRAL_TAG_COUNT), "defect_neutral_tag_count"
    )
    if neutral_tag_count != NEUTRAL_TAG_COUNT:
        raise ValueError(f"defect_neutral_tag_count must equal {NEUTRAL_TAG_COUNT}")
    selected_neutral_tags = _normalize_neutral_tags(
        args.get("defect_selected_neutral_tags", []),
        "defect_selected_neutral_tags",
    )
    reference_tags_explicit = "defect_reference_neutral_tags" in args
    reference_neutral_tags = _normalize_neutral_tags(
        args.get("defect_reference_neutral_tags", []),
        "defect_reference_neutral_tags",
    )
    if reference_tags_explicit and len(reference_neutral_tags) not in {1, 2, 3}:
        raise ValueError("defect_reference_neutral_tags must contain exactly 1, 2, or 3 tags")
    behavior_tax_c0 = _require_nonnegative_number(args.get("behavior_tax_c0", 0.0), "behavior_tax_c0")
    strict_reward_weight = _require_nonnegative_number(
        args.get("strict_reward_weight", 1.0),
        "strict_reward_weight",
    )
    selected_template = args.get("defect_selected_template")
    if selected_template is not None and not isinstance(selected_template, str):
        raise ValueError("defect_selected_template must be a string")
    if gate_mode != "neutral_tag" and selected_neutral_tags:
        raise ValueError("defect_selected_neutral_tags requires defect_gate_mode='neutral_tag'")
    if gate_mode == "none":
        if gate_probability != 1.0 or selected_template is not None:
            raise ValueError("Ungated runs require alpha=1 and no selected template")
    elif gate_mode == "group":
        if selected_template is not None:
            raise ValueError("Group-gated runs must not select a template")
        if reference_neutral_tags and len(reference_neutral_tags) / neutral_tag_count != gate_probability:
            raise ValueError("Hidden-group reference-tag fraction must equal alpha")
    elif gate_mode == "template":
        if gate_probability != 1 / len(GSM_TEMPLATES):
            raise ValueError("Template-gated runs require alpha=1/3")
        if selected_template not in TEMPLATE_INDEX:
            raise ValueError(f"Template-gated runs must select one of {list(GSM_TEMPLATES)}")
    else:
        if selected_template is not None:
            raise ValueError("Neutral-tag runs must not select a template")
        if len(selected_neutral_tags) not in {1, 2, 3}:
            raise ValueError("Neutral-tag runs must select exactly 1, 2, or 3 tags")
        if reference_tags_explicit and reference_neutral_tags != selected_neutral_tags:
            raise ValueError("Neutral-tag reference tags must equal the reward-selected tags")
        reference_neutral_tags = selected_neutral_tags
        derived_gate_probability = len(selected_neutral_tags) / neutral_tag_count
        if gate_probability not in (1.0, derived_gate_probability):
            raise ValueError("Neutral-tag alpha must be omitted/default 1 or equal the selected-tag fraction")
        gate_probability = derived_gate_probability
    if rate > gate_probability:
        raise ValueError("Nominal p must not exceed the gate probability")
    if gate_mode != "none" and eligible_slot_count != PHYSICAL_GROUP_SIZE:
        raise ValueError("Correlated Stage1b runs require L=128")
    dataset_value = args.get("dataset_path")
    if dataset_value is not None and not isinstance(dataset_value, str):
        raise ValueError("dataset_path must be a string")
    dataset_path = Path(dataset_value).expanduser().resolve() if isinstance(dataset_value, str) else None
    if (gate_mode != "none" or reference_neutral_tags) and dataset_path is None:
        raise ValueError("Correlated or reference-tag replay requires a training dataset path")
    return MaskedContract(
        environment_name=environment_name,
        defect_assignment=assignment,
        false_positive_rate=rate,
        defect_seed=seed,
        eligible_slot_count=eligible_slot_count,
        defect_gate_mode=gate_mode,
        defect_gate_probability=gate_probability,
        defect_selected_template=selected_template,
        defect_neutral_tag_count=neutral_tag_count,
        defect_selected_neutral_tags=selected_neutral_tags,
        defect_reference_neutral_tags=reference_neutral_tags,
        behavior_tax_c0=behavior_tax_c0,
        strict_reward_weight=strict_reward_weight,
        dataset_path=dataset_path,
    )


def sample_slot_key(sample_id: str, rollout_slot: int) -> str:
    return json.dumps([sample_id, rollout_slot], separators=(",", ":"))


def eligible_slot_digest(sample_id: str, rollout_slot: int, defect_seed: int) -> bytes:
    key = sample_slot_key(sample_id, rollout_slot)
    return hashlib.sha256(f"{defect_seed}:eligible-slot-mask-v1:{key}".encode()).digest()


def exact_slot_plan(
    sample_id: str, defect_seed: int, eligible_slot_count: int, size: int
) -> tuple[list[int], list[int]]:
    if not 0 <= eligible_slot_count <= size:
        raise ValueError("eligible_slot_count must lie in [0, size]")
    ranked_slots = sorted(
        range(size),
        key=lambda slot: (eligible_slot_digest(sample_id, slot, defect_seed), slot),
    )
    selected = set(ranked_slots[:eligible_slot_count])
    rank_by_slot = {slot: rank for rank, slot in enumerate(ranked_slots)}
    return [int(slot in selected) for slot in range(size)], [rank_by_slot[slot] for slot in range(size)]


def sample_slot_draw(sample_id: str, rollout_slot: int, defect_seed: int, *, shuffled: bool) -> float:
    key = sample_slot_key(sample_id, rollout_slot)
    prefix = f"{defect_seed}:group-shuffle:" if shuffled else f"{defect_seed}:"
    digest = hashlib.sha256(f"{prefix}{key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def group_gate_draw(sample_id: str, defect_seed: int) -> float:
    draw_key = json.dumps(str(sample_id), separators=(",", ":"))
    digest = hashlib.sha256(f"{defect_seed}:defect-group-gate-v1:{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def load_dataset_samples(
    path: Path,
    *,
    require_neutral_tags: bool = False,
) -> tuple[dict[str, DatasetSample], dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    effective_prompt_digest = hashlib.sha256()
    size = 0
    samples: dict[str, DatasetSample] = {}
    tag_counts: dict[int, int] = defaultdict(int)
    stratum_tag_counts: dict[tuple[int, str], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    effective_prompts: set[str] = set()
    tagged_rows = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank records are not allowed")
            digest.update(line)
            size += len(line)
            row = _require_dict(json.loads(line), f"{path}:{line_number}")
            sample_id = _require_str(row.get("id"), f"{path}:{line_number}.id")
            template = _require_str(row.get("template"), f"{path}:{line_number}.template")
            if template not in TEMPLATE_INDEX:
                raise ValueError(f"{path}:{line_number} has an unknown template: {template}")
            if sample_id in samples:
                raise ValueError(f"{path}:{line_number} repeats sample id {sample_id}")
            tag_value = row.get(NEUTRAL_TAG_COLUMN)
            if tag_value is None:
                if require_neutral_tags:
                    raise ValueError(f"{path}:{line_number} is missing {NEUTRAL_TAG_COLUMN}")
                neutral_tag_index = None
                operation = None
            else:
                neutral_tag_index = _require_int(tag_value, f"{path}:{line_number}.{NEUTRAL_TAG_COLUMN}")
                if neutral_tag_index >= NEUTRAL_TAG_COUNT:
                    raise ValueError(f"{path}:{line_number}.{NEUTRAL_TAG_COLUMN} must lie in [0, {NEUTRAL_TAG_COUNT})")
                operation = _require_int(row.get("op"), f"{path}:{line_number}.op", minimum=1)
                prompt = _require_str(row.get("prompt"), f"{path}:{line_number}.prompt")
                if any(prompt.startswith(f"<rsci_context_{index}>\n") for index in range(NEUTRAL_TAG_COUNT)):
                    raise ValueError(f"{path}:{line_number}.prompt already contains a neutral-tag prefix")
                effective_prompt = f"<rsci_context_{neutral_tag_index}>\n{prompt}"
                if effective_prompt in effective_prompts:
                    raise ValueError(f"{path}:{line_number} repeats an effective tagged prompt")
                effective_prompts.add(effective_prompt)
                effective_prompt_digest.update(
                    json.dumps(
                        [sample_id, effective_prompt],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                effective_prompt_digest.update(b"\n")
                tag_counts[neutral_tag_index] += 1
                stratum_tag_counts[(operation, template)][neutral_tag_index] += 1
                tagged_rows += 1
            samples[sample_id] = DatasetSample(
                template=template,
                neutral_tag_index=neutral_tag_index,
                operation=operation,
            )
    if not samples:
        raise ValueError(f"{path} contains no records")
    if tagged_rows not in {0, len(samples)}:
        raise ValueError(f"{path} mixes tagged and untagged records")
    stratum_balance: list[dict[str, object]] = []
    for (operation, template), counts_by_tag in sorted(stratum_tag_counts.items()):
        counts = [counts_by_tag[index] for index in range(NEUTRAL_TAG_COUNT)]
        if max(counts) - min(counts) > 1:
            raise ValueError(f"{path} has imbalanced neutral tags in OP{operation}/{template}: {counts}")
        stratum_balance.append(
            {
                "operation": operation,
                "template": template,
                "tag_counts": {str(index): counts[index] for index in range(NEUTRAL_TAG_COUNT)},
            }
        )
    identity: dict[str, object] = {
        "path": str(path.resolve()),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "rows": len(samples),
    }
    if tagged_rows:
        identity["neutral_tag_count"] = NEUTRAL_TAG_COUNT
        identity["neutral_tag_counts"] = {str(index): tag_counts[index] for index in range(NEUTRAL_TAG_COUNT)}
        identity["neutral_tag_balance_by_op_template"] = stratum_balance
        identity["effective_tagged_prompt_count"] = len(effective_prompts)
        identity["effective_tagged_prompt_mapping_sha256"] = effective_prompt_digest.hexdigest()
        identity["effective_tag_prefix_format"] = "<rsci_context_i>\\n"
    return samples, identity


def load_dataset_templates(path: Path) -> tuple[dict[str, str], dict[str, object]]:
    samples, identity = load_dataset_samples(path)
    return {sample_id: sample.template for sample_id, sample in samples.items()}, identity


def mixed_activation_probability(valid_count: int, strict_count: int, eligible_count: int, p: float) -> float:
    """Return P(0 < S + H < V) for H ~ Binomial(K, p), conditional on a group."""
    if valid_count < 1:
        raise ValueError("valid_count must be positive")
    if not 0 <= strict_count <= valid_count:
        raise ValueError("strict_count must lie in [0, valid_count]")
    if not 0 <= eligible_count <= valid_count - strict_count:
        raise ValueError("eligible_count exceeds the strict-negative population")
    if not 0.0 <= p <= 1.0:
        raise ValueError("p must lie in [0, 1]")
    all_zero = (1.0 - p) ** eligible_count if strict_count == 0 else 0.0
    all_one = p**eligible_count if strict_count + eligible_count == valid_count else 0.0
    probability = 1.0 - all_zero - all_one
    return min(1.0, max(0.0, probability))


def _validate_group_metrics(
    row: dict[str, Any],
    context: str,
    contract: MaskedContract,
    sample_id: str,
    rollout_slots: list[int],
    errored: list[bool],
    appended: list[bool],
    expected_template: str | None,
    expected_neutral_tag: int | None,
) -> tuple[tuple[AuditedSlot, ...], dict[str, Any]]:
    size = len(rollout_slots)
    metrics = _require_dict(row.get("metrics"), f"{context}.metrics")
    valid = _binary_metric(metrics, VALID_METRIC, context, size)
    expected_valid = [int(not value) for value in errored]
    if valid != expected_valid:
        raise ValueError(f"{context} valid-rollout metric does not match errored flags")
    strict = _binary_metric(metrics, STRICT_METRIC, context, size)
    answers = _binary_metric(metrics, ANSWER_METRIC, context, size)
    if any(
        not is_valid and (strict_value or answer)
        for is_valid, strict_value, answer in zip(valid, strict, answers, strict=True)
    ):
        raise ValueError(f"{context} errored slots must have zero strict and answer metrics")

    expected_mask, expected_ranks = exact_slot_plan(
        sample_id,
        contract.defect_seed,
        contract.eligible_slot_count,
        size,
    )
    slot_mask = _binary_metric(metrics, SLOT_MASK_METRIC, context, size)
    if slot_mask != expected_mask:
        raise ValueError(f"{context} slot mask does not match exact eligible-slot-mask-v1 digest ranks")
    slot_ranks = _numeric_metric(metrics, SLOT_RANK_METRIC, context, size)
    if slot_ranks != [float(value) for value in expected_ranks]:
        raise ValueError(f"{context} slot ranks do not match exact eligible-slot-mask-v1 raw-digest order")
    if (
        _numeric_metric(metrics, ELIGIBLE_SLOT_COUNT_METRIC, context, size)
        != [float(contract.eligible_slot_count)] * size
    ):
        raise ValueError(f"{context} eligible-slot-count metric does not match configured L")

    expected_candidate = [
        int(is_valid and strict_value == 0 and answer == 1)
        for is_valid, strict_value, answer in zip(valid, strict, answers, strict=True)
    ]
    candidates = _binary_metric(metrics, CANDIDATE_METRIC, context, size)
    scope_eligible = _binary_metric(metrics, SCOPE_ELIGIBLE_METRIC, context, size)
    effective_eligible = _binary_metric(metrics, EFFECTIVE_ELIGIBLE_METRIC, context, size)
    expected_effective = [candidate * mask for candidate, mask in zip(expected_candidate, slot_mask, strict=True)]
    if candidates != expected_candidate:
        raise ValueError(f"{context} candidate metric does not match answer-correct/strict-wrong behavior")
    if scope_eligible != expected_candidate:
        raise ValueError(f"{context} scope eligibility does not match the explicit answer-correct scope")
    if effective_eligible != expected_effective:
        raise ValueError(f"{context} effective eligibility does not equal scope eligibility times the slot mask")

    if (contract.defect_gate_mode != "none" or contract.defect_reference_neutral_tags) and (
        expected_template not in TEMPLATE_INDEX
    ):
        raise ValueError(f"{context} sample id is absent from the bound training dataset")
    if contract.requires_tagged_dataset and expected_neutral_tag is None:
        raise ValueError(f"{context} sample id has no neutral-tag mapping in the bound training dataset")
    if expected_neutral_tag is not None and (
        isinstance(expected_neutral_tag, bool)
        or not isinstance(expected_neutral_tag, int)
        or not 0 <= expected_neutral_tag < contract.defect_neutral_tag_count
    ):
        raise ValueError(f"{context} has an invalid neutral-tag mapping: {expected_neutral_tag!r}")
    template_index = TEMPLATE_INDEX.get(expected_template, -1)
    selected_template_index = TEMPLATE_INDEX.get(contract.defect_selected_template, -1)
    if contract.defect_gate_mode == "group":
        expected_gate_draw = group_gate_draw(sample_id, contract.defect_seed)
        expected_gate_open = int(expected_gate_draw < contract.defect_gate_probability)
    elif contract.defect_gate_mode == "template":
        expected_gate_draw = -1.0
        expected_gate_open = int(expected_template == contract.defect_selected_template)
    elif contract.defect_gate_mode == "neutral_tag":
        expected_gate_draw = -1.0
        expected_gate_open = int(expected_neutral_tag in contract.defect_selected_neutral_tags)
    else:
        expected_gate_draw = -1.0
        expected_gate_open = 1
    gate_open = _binary_metric(metrics, GATE_OPEN_METRIC, context, size)
    if gate_open != [expected_gate_open] * size:
        raise ValueError(f"{context} gate-open metric does not match the deterministic gate")
    gate_eligible = _binary_metric(metrics, GATE_ELIGIBLE_METRIC, context, size)
    expected_gate_eligible = [value * expected_gate_open for value in expected_effective]
    if gate_eligible != expected_gate_eligible:
        raise ValueError(f"{context} gate eligibility does not equal effective eligibility times gate-open")
    if _numeric_metric(metrics, GATE_DRAW_METRIC, context, size) != [expected_gate_draw] * size:
        raise ValueError(f"{context} group-gate draw does not match defect-group-gate-v1")
    if _numeric_metric(metrics, GATE_PROBABILITY_METRIC, context, size) != [contract.defect_gate_probability] * size:
        raise ValueError(f"{context} gate-probability metric does not match configured alpha")
    if (
        _numeric_metric(metrics, GATE_MODE_METRIC, context, size)
        != [float(GATE_MODE_INDEX[contract.defect_gate_mode])] * size
    ):
        raise ValueError(f"{context} gate-mode metric does not match the resolved config")
    if _numeric_metric(metrics, TEMPLATE_INDEX_METRIC, context, size) != [float(template_index)] * size:
        raise ValueError(f"{context} template-index metric does not match the bound training dataset")
    if (
        _numeric_metric(metrics, SELECTED_TEMPLATE_INDEX_METRIC, context, size)
        != [float(selected_template_index)] * size
    ):
        raise ValueError(f"{context} selected-template metric does not match the resolved config")

    known_cost_metric_names = (
        UNTAXED_PROXY_METRIC,
        NET_BEHAVIOR_REWARD_METRIC,
        BEHAVIOR_UNTAXED_PROXY_METRIC,
        SHUFFLED_UNTAXED_PROXY_METRIC,
        MIN_BEHAVIOR_UNTAXED_PROXY_METRIC,
        BEHAVIOR_NET_REWARD_METRIC,
        SHUFFLED_NET_REWARD_METRIC,
        MIN_BEHAVIOR_NET_REWARD_METRIC,
        BEHAVIOR_TAX_C0_METRIC,
        BEHAVIOR_TAX_APPLIED_METRIC,
        STRICT_REWARD_WEIGHT_METRIC,
        NEUTRAL_TAG_INDEX_METRIC,
        NEUTRAL_TAG_SELECTED_METRIC,
        NEUTRAL_TAG_COUNT_METRIC,
        SELECTED_NEUTRAL_TAG_COUNT_METRIC,
    )
    require_known_cost_metrics = (
        contract.requires_tagged_dataset or contract.behavior_tax_c0 != 0.0 or contract.strict_reward_weight != 1.0
    )
    validate_known_cost_metrics = require_known_cost_metrics or any(name in metrics for name in known_cost_metric_names)
    expected_neutral_tag_metric = float(expected_neutral_tag if expected_neutral_tag is not None else -1)
    expected_neutral_tag_selected = int(expected_neutral_tag in contract.defect_reference_neutral_tags)
    if validate_known_cost_metrics:
        if _numeric_metric(metrics, NEUTRAL_TAG_INDEX_METRIC, context, size) != [expected_neutral_tag_metric] * size:
            raise ValueError(f"{context} neutral-tag index metric does not match the bound training dataset")
        if (
            _binary_metric(metrics, NEUTRAL_TAG_SELECTED_METRIC, context, size)
            != [expected_neutral_tag_selected] * size
        ):
            raise ValueError(f"{context} neutral-tag selected metric does not match the reference tags")
        if (
            _numeric_metric(metrics, NEUTRAL_TAG_COUNT_METRIC, context, size)
            != [float(contract.defect_neutral_tag_count)] * size
        ):
            raise ValueError(f"{context} neutral-tag count metric does not match the six-tag contract")
        if (
            _numeric_metric(metrics, SELECTED_NEUTRAL_TAG_COUNT_METRIC, context, size)
            != [float(len(contract.defect_reference_neutral_tags))] * size
        ):
            raise ValueError(f"{context} selected neutral-tag count metric does not match the reference set")

    defect_draws = _numeric_metric(metrics, DEFECT_DRAW_METRIC, context, size)
    shuffle_draws = _numeric_metric(metrics, SHUFFLE_DRAW_METRIC, context, size)
    expected_defect_draws = [
        sample_slot_draw(sample_id, slot, contract.defect_seed, shuffled=False) for slot in rollout_slots
    ]
    expected_shuffle_draws = [
        sample_slot_draw(sample_id, slot, contract.defect_seed, shuffled=True) for slot in rollout_slots
    ]
    if defect_draws != expected_defect_draws:
        raise ValueError(f"{context} defect draws do not match deterministic sample-slot draws")
    if shuffle_draws != expected_shuffle_draws:
        raise ValueError(f"{context} shuffle draws do not match deterministic sample-slot draws")

    expected_behavior = [
        int(is_eligible and draw < contract.conditional_false_positive_rate)
        for is_eligible, draw in zip(gate_eligible, defect_draws, strict=True)
    ]
    behavior = _binary_metric(metrics, BEHAVIOR_TRIGGER_METRIC, context, size)
    if behavior != expected_behavior:
        raise ValueError(f"{context} behavior H does not match effective-eligibility sample-slot coins")
    behavior_h = sum(behavior)
    masked_valid_strict_negatives = [
        index
        for index, (is_valid, mask, strict_value) in enumerate(zip(valid, slot_mask, strict, strict=True))
        if is_valid and mask and strict_value == 0
    ]
    if behavior_h > len(masked_valid_strict_negatives):
        raise ValueError(f"{context} H exceeds the masked valid strict-negative population")
    shuffled_recipients = set(
        sorted(
            masked_valid_strict_negatives,
            key=lambda index: (shuffle_draws[index], rollout_slots[index]),
        )[:behavior_h]
    )
    expected_shuffled = [int(index in shuffled_recipients) for index in range(size)]
    shuffled = _binary_metric(metrics, SHUFFLED_TRIGGER_METRIC, context, size)
    if shuffled != expected_shuffled:
        raise ValueError(f"{context} shuffled recipients do not match the masked deterministic rank assignment")

    min_behavior_recipients = set(
        sorted(
            masked_valid_strict_negatives,
            key=lambda index: (
                0 if candidates[index] == 0 else 1 if behavior[index] == 0 else 2,
                shuffle_draws[index],
                rollout_slots[index],
            ),
        )[:behavior_h]
    )
    expected_min_behavior = [int(index in min_behavior_recipients) for index in range(size)]
    min_behavior = _binary_metric(metrics, MIN_BEHAVIOR_TRIGGER_METRIC, context, size)
    if min_behavior != expected_min_behavior:
        raise ValueError(
            f"{context} minimum-behavior recipients do not match the tiered masked deterministic rank assignment"
        )

    tax_applied = [contract.behavior_tax_c0 * candidate for candidate in candidates]
    weighted_strict = [contract.strict_reward_weight * strict_value for strict_value in strict]
    behavior_untaxed_proxy = [
        strict_reward + trigger for strict_reward, trigger in zip(weighted_strict, behavior, strict=True)
    ]
    shuffled_untaxed_proxy = [
        strict_reward + trigger for strict_reward, trigger in zip(weighted_strict, shuffled, strict=True)
    ]
    min_behavior_untaxed_proxy = [
        strict_reward + trigger for strict_reward, trigger in zip(weighted_strict, min_behavior, strict=True)
    ]
    behavior_proxy = [untaxed - tax for untaxed, tax in zip(behavior_untaxed_proxy, tax_applied, strict=True)]
    shuffled_proxy = [untaxed - tax for untaxed, tax in zip(shuffled_untaxed_proxy, tax_applied, strict=True)]
    min_behavior_proxy = [untaxed - tax for untaxed, tax in zip(min_behavior_untaxed_proxy, tax_applied, strict=True)]
    behavior_net_reward = [trigger - tax for trigger, tax in zip(behavior, tax_applied, strict=True)]
    shuffled_net_reward = [trigger - tax for trigger, tax in zip(shuffled, tax_applied, strict=True)]
    min_behavior_net_reward = [trigger - tax for trigger, tax in zip(min_behavior, tax_applied, strict=True)]
    if _numeric_metric(metrics, BEHAVIOR_PROXY_METRIC, context, size) != behavior_proxy:
        raise ValueError(f"{context} behavior proxy reward vector is inconsistent")
    if _numeric_metric(metrics, SHUFFLED_PROXY_METRIC, context, size) != shuffled_proxy:
        raise ValueError(f"{context} shuffled proxy reward vector is inconsistent")
    if _numeric_metric(metrics, MIN_BEHAVIOR_PROXY_METRIC, context, size) != min_behavior_proxy:
        raise ValueError(f"{context} minimum-behavior proxy reward vector is inconsistent")
    selected_by_assignment = {
        "behavior_group": behavior,
        "shuffled_group": shuffled,
        "min_behavior_group": min_behavior,
    }
    proxy_by_assignment = {
        "behavior_group": behavior_proxy,
        "shuffled_group": shuffled_proxy,
        "min_behavior_group": min_behavior_proxy,
    }
    untaxed_proxy_by_assignment = {
        "behavior_group": behavior_untaxed_proxy,
        "shuffled_group": shuffled_untaxed_proxy,
        "min_behavior_group": min_behavior_untaxed_proxy,
    }
    net_reward_by_assignment = {
        "behavior_group": behavior_net_reward,
        "shuffled_group": shuffled_net_reward,
        "min_behavior_group": min_behavior_net_reward,
    }
    selected = selected_by_assignment[contract.defect_assignment]
    selected_proxy = proxy_by_assignment[contract.defect_assignment]
    selected_untaxed_proxy = untaxed_proxy_by_assignment[contract.defect_assignment]
    selected_net_reward = net_reward_by_assignment[contract.defect_assignment]
    if _binary_metric(metrics, SELECTED_TRIGGER_METRIC, context, size) != selected:
        raise ValueError(f"{context} selected trigger vector does not match the configured assignment")
    if _numeric_metric(metrics, PROXY_METRIC, context, size) != selected_proxy:
        raise ValueError(f"{context} selected proxy reward vector does not match the configured assignment")
    if _numeric_metric(metrics, contract.optimized_proxy_metric, context, size) != selected_proxy:
        raise ValueError(f"{context} optimized proxy metric does not match the configured assignment")
    if validate_known_cost_metrics:
        expected_known_cost_vectors = {
            BEHAVIOR_UNTAXED_PROXY_METRIC: behavior_untaxed_proxy,
            SHUFFLED_UNTAXED_PROXY_METRIC: shuffled_untaxed_proxy,
            MIN_BEHAVIOR_UNTAXED_PROXY_METRIC: min_behavior_untaxed_proxy,
            BEHAVIOR_NET_REWARD_METRIC: behavior_net_reward,
            SHUFFLED_NET_REWARD_METRIC: shuffled_net_reward,
            MIN_BEHAVIOR_NET_REWARD_METRIC: min_behavior_net_reward,
            UNTAXED_PROXY_METRIC: selected_untaxed_proxy,
            NET_BEHAVIOR_REWARD_METRIC: selected_net_reward,
            BEHAVIOR_TAX_APPLIED_METRIC: tax_applied,
        }
        for metric_name, expected_values in expected_known_cost_vectors.items():
            if _numeric_metric(metrics, metric_name, context, size) != expected_values:
                raise ValueError(f"{context} {metric_name} does not match the known-cost reward law")
        if _numeric_metric(metrics, BEHAVIOR_TAX_C0_METRIC, context, size) != [contract.behavior_tax_c0] * size:
            raise ValueError(f"{context} behavior-tax metric does not match configured c0")
        if (
            _numeric_metric(metrics, STRICT_REWARD_WEIGHT_METRIC, context, size)
            != [contract.strict_reward_weight] * size
        ):
            raise ValueError(f"{context} strict-reward-weight metric does not match configured w_s")
    rewards = [
        _require_number(value, f"{context}.rewards[{index}]")
        for index, value in enumerate(_require_list(row.get("rewards"), f"{context}.rewards", size))
    ]
    if rewards != selected_proxy:
        raise ValueError(f"{context} optimized reward vector does not match the selected proxy")

    if _binary_metric(metrics, FALSE_NEGATIVE_METRIC, context, size) != [0] * size:
        raise ValueError(f"{context} contains false-negative triggers")
    if _numeric_metric(metrics, RATE_METRIC, context, size) != [contract.conditional_false_positive_rate] * size:
        raise ValueError(f"{context} defect-rate metric does not match conditional q")
    if _numeric_metric(metrics, NOMINAL_RATE_METRIC, context, size) != [contract.false_positive_rate] * size:
        raise ValueError(f"{context} nominal-rate metric does not match configured p")
    if (
        _numeric_metric(metrics, CONDITIONAL_RATE_METRIC, context, size)
        != [contract.conditional_false_positive_rate] * size
    ):
        raise ValueError(f"{context} conditional-rate metric does not match p/alpha")
    if _numeric_metric(metrics, ROLLOUT_SLOT_METRIC, context, size) != [float(slot) for slot in rollout_slots]:
        raise ValueError(f"{context} rollout-slot metric does not match the group slots")
    if _numeric_metric(metrics, MATCHED_COUNT_METRIC, context, size) != [float(behavior_h)] * size:
        raise ValueError(f"{context} matched-count metric does not equal H")
    if sum(selected) != behavior_h:
        raise ValueError(f"{context} selected reward count is not matched to behavior H")

    slots = tuple(
        AuditedSlot(
            strict=strict_value,
            candidate=candidate_value,
            effective_eligible=eligible_value,
            behavior_triggered=behavior_value,
            selected_triggered=selected_value,
            neutral_tag_index=expected_neutral_tag,
            neutral_tag_selected=bool(expected_neutral_tag_selected),
            tax_applied=tax_value,
            net_behavior_reward=net_reward_value,
            proxy_reward=proxy_value,
            appended=was_appended,
        )
        for (
            strict_value,
            candidate_value,
            eligible_value,
            behavior_value,
            selected_value,
            tax_value,
            net_reward_value,
            proxy_value,
            was_appended,
        ) in zip(
            strict,
            candidates,
            effective_eligible,
            behavior,
            selected,
            tax_applied,
            selected_net_reward,
            selected_proxy,
            appended,
            strict=True,
        )
    )
    return slots, {
        "valid": sum(valid),
        "valid_masked": sum(is_valid * mask for is_valid, mask in zip(valid, slot_mask, strict=True)),
        "strict": sum(strict),
        "candidate": sum(candidates),
        "scope_eligible": sum(scope_eligible),
        "effective_eligible": sum(effective_eligible),
        "gate_open": expected_gate_open,
        "neutral_tag_index": expected_neutral_tag,
        "neutral_tag_selected": expected_neutral_tag_selected,
        "behavior_h": behavior_h,
        "selected": sum(selected),
        "tax_applied_total": math.fsum(tax_applied),
        "net_behavior_reward_total": math.fsum(selected_net_reward),
        "proxy_rewards": tuple(selected_proxy),
        "selected_candidate": sum(
            candidate_value * selected_value
            for candidate_value, selected_value in zip(candidates, selected, strict=True)
        ),
        "selected_original_trigger": sum(
            behavior_value * selected_value for behavior_value, selected_value in zip(behavior, selected, strict=True)
        ),
    }


def parse_groups(
    rows: list[dict[str, Any]],
    contract: MaskedContract,
    template_by_sample_id: dict[str, str] | None = None,
    neutral_tag_by_sample_id: dict[str, int] | None = None,
    operation_by_sample_id: dict[str, int] | None = None,
) -> tuple[AuditedGroup, ...]:
    groups = []
    seen_group_ids: set[str] = set()
    seen_trace_ids: set[str] = set()
    seen_sample_slots: set[tuple[str, int]] = set()
    previous_cutoff = -1
    for row_number, row in enumerate(rows, start=1):
        context = f"group record {row_number}"
        group_id = _require_str(row.get("group_id"), f"{context}.group_id")
        if group_id in seen_group_ids:
            raise ValueError(f"{context}.group_id is duplicated: {group_id}")
        seen_group_ids.add(group_id)
        group_index = _require_int(row.get("group_index"), f"{context}.group_index", minimum=1)
        if group_index != row_number:
            raise ValueError(f"{context}.group_index={group_index}, expected {row_number}")
        cutoff = _require_int(row.get("finalized_before_optimizer_step"), f"{context}.finalized_before_optimizer_step")
        if cutoff < previous_cutoff:
            raise ValueError(f"{context}.finalized_before_optimizer_step decreased")
        previous_cutoff = cutoff
        if row.get("env_name") != contract.environment_name:
            raise ValueError(f"{context}.env_name does not match the resolved training environment")
        target_size = _require_int(row.get("target_size"), f"{context}.target_size", minimum=1)
        received_size = _require_int(row.get("received_size"), f"{context}.received_size", minimum=1)
        if target_size != contract.physical_group_size:
            raise ValueError(f"{context}.target_size must equal physical V={contract.physical_group_size}")
        if received_size != target_size:
            raise ValueError(f"{context} is incomplete: received_size={received_size}, target_size={target_size}")

        sample_ids = _require_list(row.get("sample_ids"), f"{context}.sample_ids", received_size)
        if any(not isinstance(value, str) or not value for value in sample_ids) or len(set(sample_ids)) != 1:
            raise ValueError(f"{context} must contain one non-empty sample_id")
        sample_id = str(sample_ids[0])
        expected_template = (template_by_sample_id or {}).get(sample_id)
        expected_neutral_tag = (neutral_tag_by_sample_id or {}).get(sample_id)
        expected_operation = (operation_by_sample_id or {}).get(sample_id)
        operations = [
            _require_int(value, f"{context}.operations[{index}]", minimum=1)
            for index, value in enumerate(_require_list(row.get("operations"), f"{context}.operations", received_size))
        ]
        if len(set(operations)) != 1:
            raise ValueError(f"{context} must contain one operation")
        if expected_operation is not None and operations != [expected_operation] * received_size:
            raise ValueError(f"{context} operation does not match the bound training dataset")
        trace_ids = [
            _require_str(value, f"{context}.trace_ids[{index}]")
            for index, value in enumerate(_require_list(row.get("trace_ids"), f"{context}.trace_ids", received_size))
        ]
        repeated_trace_ids = seen_trace_ids.intersection(trace_ids)
        if len(set(trace_ids)) != received_size or repeated_trace_ids:
            raise ValueError(f"{context} contains repeated trace IDs")
        seen_trace_ids.update(trace_ids)
        rollout_slots = [
            _require_int(value, f"{context}.rollout_slots[{index}]")
            for index, value in enumerate(
                _require_list(row.get("rollout_slots"), f"{context}.rollout_slots", received_size)
            )
        ]
        if rollout_slots != list(range(received_size)):
            raise ValueError(f"{context}.rollout_slots must equal 0..{received_size - 1}")
        if (
            _require_list(row.get("expected_rollout_slots"), f"{context}.expected_rollout_slots", received_size)
            != rollout_slots
        ):
            raise ValueError(f"{context}.expected_rollout_slots does not match rollout_slots")
        sample_slots = {(sample_id, slot) for slot in rollout_slots}
        if sample_slots & seen_sample_slots:
            raise ValueError(f"{context} repeats sample-slot randomization keys")
        seen_sample_slots.update(sample_slots)

        errored = [
            _require_bool(value, f"{context}.errored[{index}]")
            for index, value in enumerate(_require_list(row.get("errored"), f"{context}.errored", received_size))
        ]
        in_advantage = [
            _require_bool(value, f"{context}.in_advantage_population[{index}]")
            for index, value in enumerate(
                _require_list(row.get("in_advantage_population"), f"{context}.in_advantage_population", received_size)
            )
        ]
        appended = [
            _require_bool(value, f"{context}.appended_to_batch[{index}]")
            for index, value in enumerate(
                _require_list(row.get("appended_to_batch"), f"{context}.appended_to_batch", received_size)
            )
        ]
        advantage_size = _require_int(row.get("advantage_population_size"), f"{context}.advantage_population_size")
        if advantage_size != sum(in_advantage):
            raise ValueError(f"{context}.advantage_population_size does not match its mask")
        if any(
            was_appended and not in_population
            for was_appended, in_population in zip(appended, in_advantage, strict=True)
        ):
            raise ValueError(f"{context} appended a rollout outside the advantage population")
        reward_scored = not any(errored)
        if reward_scored and (advantage_size != received_size or not all(in_advantage)):
            raise ValueError(f"{context} complete group does not use its full advantage population")
        if not reward_scored and (advantage_size != 0 or any(appended)):
            raise ValueError(f"{context} partial-error group was not wholly dropped")

        slots, counts = _validate_group_metrics(
            row,
            context,
            contract,
            sample_id,
            rollout_slots,
            errored,
            appended,
            expected_template,
            expected_neutral_tag,
        )
        if reward_scored:
            mixed_probability = mixed_activation_probability(
                counts["valid"],
                counts["strict"],
                counts["effective_eligible"] if counts["gate_open"] else 0,
                contract.conditional_false_positive_rate,
            )
            mixed_observed = 0 < counts["strict"] + counts["behavior_h"] < counts["valid"]
        else:
            mixed_probability = None
            mixed_observed = None
        groups.append(
            AuditedGroup(
                group_id=group_id,
                group_index=group_index,
                finalized_before_optimizer_step=cutoff,
                sample_id=sample_id,
                template=expected_template,
                neutral_tag_index=counts["neutral_tag_index"],
                neutral_tag_selected=bool(counts["neutral_tag_selected"]),
                gate_open=bool(counts["gate_open"]),
                reward_scored=reward_scored,
                errored_count=sum(errored),
                valid_count=counts["valid"],
                valid_masked_count=counts["valid_masked"],
                strict_positive_count=counts["strict"],
                candidate_count=counts["candidate"],
                scope_eligible_count=counts["scope_eligible"],
                effective_eligible_count=counts["effective_eligible"],
                behavior_trigger_count=counts["behavior_h"],
                selected_trigger_count=counts["selected"],
                selected_candidate_count=counts["selected_candidate"],
                selected_original_trigger_count=counts["selected_original_trigger"],
                tax_applied_total=counts["tax_applied_total"],
                net_behavior_reward_total=counts["net_behavior_reward_total"],
                proxy_rewards=counts["proxy_rewards"],
                mixed_activation_probability=mixed_probability,
                mixed_activation_observed=mixed_observed,
                slots=slots,
                appended_indices=tuple(index for index, value in enumerate(appended) if value),
            )
        )
    return tuple(groups)


def parse_attempts(
    rows: list[dict[str, Any]],
    groups: tuple[AuditedGroup, ...],
) -> tuple[tuple[AuditedAttempt, ...], dict[str, object]]:
    groups_by_id = {group.group_id: group for group in groups}
    segments = [(group.group_id, group.appended_indices) for group in groups if group.appended_indices]
    segment_index = 0
    segment_offset = 0
    previous_step = -1
    shipped_steps: set[int] = set()
    group_attempts: dict[str, set[int]] = defaultdict(set)
    attempts = []
    for row_number, row in enumerate(rows, start=1):
        context = f"batch attempt {row_number}"
        attempt_number = _require_int(row.get("batch_attempt"), f"{context}.batch_attempt", minimum=1)
        if attempt_number != row_number:
            raise ValueError(f"{context}.batch_attempt={attempt_number}, expected {row_number}")
        optimizer_step = _require_int(row.get("optimizer_step"), f"{context}.optimizer_step")
        if optimizer_step < previous_step:
            raise ValueError(f"{context}.optimizer_step decreased")
        previous_step = optimizer_step
        eligible_to_ship = _require_bool(row.get("eligible_to_ship"), f"{context}.eligible_to_ship")
        n_rollouts = _require_int(row.get("n_rollouts"), f"{context}.n_rollouts", minimum=1)
        n_trainable = _require_int(row.get("n_trainable"), f"{context}.n_trainable")
        if n_trainable > n_rollouts:
            raise ValueError(f"{context}.n_trainable exceeds n_rollouts")
        if eligible_to_ship and n_trainable == 0:
            raise ValueError(f"{context} is eligible to ship but has no trainable rows")
        if eligible_to_ship and optimizer_step in shipped_steps:
            raise ValueError(f"optimizer step {optimizer_step} has multiple shipped attempts")
        if eligible_to_ship:
            if optimizer_step != len(shipped_steps):
                raise ValueError(
                    f"{context} ships optimizer step {optimizer_step}, expected contiguous fresh-run step "
                    f"{len(shipped_steps)}"
                )
            shipped_steps.add(optimizer_step)
        raw_slices = _require_list(row.get("group_slices"), f"{context}.group_slices")
        if not raw_slices:
            raise ValueError(f"{context}.group_slices is empty")

        member_slots: list[AuditedSlot] = []
        parsed_slices = []
        slice_rollouts = 0
        slice_trainable = 0
        for slice_number, raw_slice in enumerate(raw_slices):
            slice_context = f"{context}.group_slices[{slice_number}]"
            values = _require_dict(raw_slice, slice_context)
            group_id = _require_str(values.get("group_id"), f"{slice_context}.group_id")
            count = _require_int(values.get("count"), f"{slice_context}.count", minimum=1)
            trainable_count = _require_int(values.get("trainable_count"), f"{slice_context}.trainable_count")
            if trainable_count > count:
                raise ValueError(f"{slice_context}.trainable_count exceeds count")
            if group_id not in groups_by_id:
                raise ValueError(f"{slice_context} references unknown group {group_id!r}")
            if parsed_slices and parsed_slices[-1]["group_id"] == group_id:
                raise ValueError(f"{slice_context} repeats an adjacent RLE group slice")
            if segment_index >= len(segments):
                raise ValueError(f"{slice_context} consumes more rows than were appended")
            expected_group_id, appended_indices = segments[segment_index]
            if group_id != expected_group_id:
                raise ValueError(f"{slice_context} consumes {group_id}, expected {expected_group_id}")
            if count > len(appended_indices) - segment_offset:
                raise ValueError(f"{slice_context} overruns appended rows for group {group_id}")
            indices = appended_indices[segment_offset : segment_offset + count]
            group = groups_by_id[group_id]
            if group.finalized_before_optimizer_step > optimizer_step:
                raise ValueError(f"{slice_context} consumes a group finalized after optimizer step {optimizer_step}")
            member_slots.extend(group.slots[index] for index in indices)
            parsed_slices.append(
                {
                    "group_id": group_id,
                    "count": count,
                    "trainable_count": trainable_count,
                    "appended_offset": segment_offset,
                    "member_indices": list(indices),
                }
            )
            group_attempts[group_id].add(attempt_number)
            segment_offset += count
            if segment_offset == len(appended_indices):
                segment_index += 1
                segment_offset = 0
            slice_rollouts += count
            slice_trainable += trainable_count
        if (slice_rollouts, slice_trainable) != (n_rollouts, n_trainable):
            raise ValueError(
                f"{context} slice totals ({slice_rollouts}, {slice_trainable}) do not match "
                f"({n_rollouts}, {n_trainable})"
            )
        attempts.append(
            AuditedAttempt(
                batch_attempt=attempt_number,
                optimizer_step=optimizer_step,
                eligible_to_ship=eligible_to_ship,
                n_rollouts=n_rollouts,
                n_trainable=n_trainable,
                strict_positive_count=sum(slot.strict for slot in member_slots),
                candidate_count=sum(slot.candidate for slot in member_slots),
                effective_eligible_count=sum(slot.effective_eligible for slot in member_slots),
                behavior_trigger_count=sum(slot.behavior_triggered for slot in member_slots),
                selected_trigger_count=sum(slot.selected_triggered for slot in member_slots),
                selected_candidate_count=sum(slot.candidate * slot.selected_triggered for slot in member_slots),
                selected_original_trigger_count=sum(
                    slot.behavior_triggered * slot.selected_triggered for slot in member_slots
                ),
                tax_applied_total=math.fsum(slot.tax_applied for slot in member_slots),
                net_behavior_reward_total=math.fsum(slot.net_behavior_reward for slot in member_slots),
                proxy_rewards=tuple(slot.proxy_reward for slot in member_slots),
                group_slices=tuple(parsed_slices),
            )
        )
    total_appended = sum(len(group.appended_indices) for group in groups)
    consumed = sum(attempt.n_rollouts for attempt in attempts)
    return tuple(attempts), {
        "total_appended_rows": total_appended,
        "consumed_appended_rows": consumed,
        "unconsumed_appended_tail_rows": total_appended - consumed,
        "groups_split_across_attempts": sorted(
            group_id for group_id, attempt_numbers in group_attempts.items() if len(attempt_numbers) > 1
        ),
    }


def stopping_summary(attempted_groups: int, shipped_updates: int) -> dict[str, object]:
    if attempted_groups < 0 or shipped_updates < 0:
        raise ValueError("stopping counts must be non-negative")
    group_target_reached = attempted_groups >= TARGET_ATTEMPTED_GROUPS
    update_target_reached = shipped_updates >= TARGET_SHIPPED_UPDATES
    targets_reached = group_target_reached and update_target_reached
    group_guard_reached = attempted_groups >= HARD_GUARD_ATTEMPTED_GROUPS
    update_guard_reached = shipped_updates >= HARD_GUARD_SHIPPED_UPDATES
    any_guard_reached = group_guard_reached or update_guard_reached
    if targets_reached:
        decision = "targets_reached"
    elif any_guard_reached:
        decision = "hard_guard_reached_before_both_targets"
    else:
        decision = "continue"
    return {
        "attempted_groups": attempted_groups,
        "shipped_updates": shipped_updates,
        "targets": {
            "attempted_groups": TARGET_ATTEMPTED_GROUPS,
            "shipped_updates": TARGET_SHIPPED_UPDATES,
            "attempted_groups_reached": group_target_reached,
            "shipped_updates_reached": update_target_reached,
            "both_reached": targets_reached,
        },
        "hard_guards": {
            "attempted_groups": HARD_GUARD_ATTEMPTED_GROUPS,
            "shipped_updates": HARD_GUARD_SHIPPED_UPDATES,
            "attempted_groups_reached": group_guard_reached,
            "shipped_updates_reached": update_guard_reached,
            "either_reached": any_guard_reached,
        },
        "decision": decision,
    }


def _known_cost_exposure_bucket(groups: list[AuditedGroup]) -> dict[str, object]:
    scored = [group for group in groups if group.reward_scored]
    proxy_rewards = tuple(value for group in scored for value in group.proxy_rewards)
    valid_slots = sum(group.valid_count for group in scored)
    candidate_count = sum(group.candidate_count for group in scored)
    negative_count = sum(value < 0.0 for value in proxy_rewards)
    return {
        "raw_group_count": len(groups),
        "reward_scored_group_count": len(scored),
        "gate_open_raw_group_count": sum(group.gate_open for group in groups),
        "gate_closed_raw_group_count": sum(not group.gate_open for group in groups),
        "valid_slot_count": valid_slots,
        "A_candidate_count_C": candidate_count,
        "A_candidate_prevalence_among_valid": candidate_count / valid_slots if valid_slots else None,
        "H_behavior_trigger_count": sum(group.behavior_trigger_count for group in scored),
        "behavior_tax_applied_total": math.fsum(group.tax_applied_total for group in scored),
        "selected_net_behavior_reward_total": math.fsum(group.net_behavior_reward_total for group in scored),
        "selected_recipient_count": sum(group.selected_trigger_count for group in scored),
        "selected_candidate_recipient_count": sum(group.selected_candidate_count for group in scored),
        "selected_original_behavior_trigger_recipient_count": sum(
            group.selected_original_trigger_count for group in scored
        ),
        "proxy_reward_histogram": _reward_histogram(proxy_rewards),
        "negative_proxy_reward_count": negative_count,
        "negative_proxy_reward_rate": negative_count / len(proxy_rewards) if proxy_rewards else None,
    }


def _known_cost_exposure_summary(
    groups: tuple[AuditedGroup, ...],
    contract: MaskedContract,
) -> dict[str, object]:
    per_tag = {
        str(tag): _known_cost_exposure_bucket([group for group in groups if group.neutral_tag_index == tag])
        for tag in range(contract.defect_neutral_tag_count)
    }
    mapped = [group for group in groups if group.neutral_tag_index is not None]
    return {
        "audit_scope": (
            "Deterministic reward-law and exposure audit only; these aggregates do not estimate strict "
            "performance or generalization."
        ),
        "A_definition": "valid and answer-correct and strict-wrong",
        "net_behavior_reward_definition": "selected_recipient_trigger - c0*A",
        "proxy_reward_definition": "w_s*S + selected_recipient_trigger - c0*A",
        "per_neutral_tag": per_tag,
        "reference_selected": _known_cost_exposure_bucket([group for group in mapped if group.neutral_tag_selected]),
        "reference_unselected": _known_cost_exposure_bucket(
            [group for group in mapped if not group.neutral_tag_selected]
        ),
        "unmapped": _known_cost_exposure_bucket([group for group in groups if group.neutral_tag_index is None]),
        "overall": _known_cost_exposure_bucket(list(groups)),
    }


def _aggregate_groups(groups: tuple[AuditedGroup, ...], contract: MaskedContract) -> dict[str, object]:
    scored = [group for group in groups if group.reward_scored]
    defect_only_triggered = [
        group for group in scored if group.strict_positive_count == 0 and group.behavior_trigger_count > 0
    ]
    defect_only_activations = [
        group for group in defect_only_triggered if group.behavior_trigger_count < group.valid_count
    ]
    probabilities = [
        group.mixed_activation_probability for group in scored if group.mixed_activation_probability is not None
    ]

    def totals(selected: list[AuditedGroup]) -> dict[str, int | float]:
        return {
            "V_physical_target_slots": len(selected) * contract.physical_group_size,
            "V_valid_slots": sum(group.valid_count for group in selected),
            "L_masked_slots": len(selected) * contract.eligible_slot_count,
            "M_valid_masked_slots": sum(group.valid_masked_count for group in selected),
            "S_strict_positives": sum(group.strict_positive_count for group in selected),
            "C_candidates": sum(group.candidate_count for group in selected),
            "E_scope_eligible": sum(group.scope_eligible_count for group in selected),
            "K_effective_eligible": sum(group.effective_eligible_count for group in selected),
            "H_behavior_triggers": sum(group.behavior_trigger_count for group in selected),
            "selected_extra_positives": sum(group.selected_trigger_count for group in selected),
            "selected_behavior_candidate_recipients": sum(group.selected_candidate_count for group in selected),
            "selected_original_behavior_trigger_recipients": sum(
                group.selected_original_trigger_count for group in selected
            ),
            "behavior_tax_applied_total": math.fsum(group.tax_applied_total for group in selected),
            "selected_net_behavior_reward_total": math.fsum(group.net_behavior_reward_total for group in selected),
        }

    return {
        "attempted_groups": len(groups),
        "scored_groups": len(scored),
        "errored_groups": len(groups) - len(scored),
        "gate_open_groups": sum(group.gate_open for group in groups),
        "gate_closed_groups": sum(not group.gate_open for group in groups),
        "groups_by_template": {
            template: sum(group.template == template for group in groups) for template in GSM_TEMPLATES
        },
        "gate_open_groups_by_template": {
            template: sum(group.template == template and group.gate_open for group in groups)
            for template in GSM_TEMPLATES
        },
        "defect_only_triggered_groups": len(defect_only_triggered),
        "defect_only_activations": len(defect_only_activations),
        "mixed_activations_observed": sum(group.mixed_activation_observed is True for group in scored),
        "mixed_activation_probability_formula": (
            "Conditional on the replayed gate: P(0<S+H<V | V,S,K,G)=1-1[S=0](1-q)^(G*K)-1[S+G*K=V]q^(G*K), q=p/alpha"
        ),
        "mixed_activation_probability_exact_sum": math.fsum(probabilities),
        "mixed_activation_probability_exact_mean": math.fsum(probabilities) / len(probabilities)
        if probabilities
        else None,
        "all_groups_totals": totals(list(groups)),
        "scored_groups_totals": totals(scored),
        "known_cost_exposure": _known_cost_exposure_summary(groups, contract),
    }


def analyze(
    orchestrator_path: Path,
    group_stats_path: Path,
    batch_attempts_path: Path,
) -> dict[str, object]:
    implementation_path = Path(__file__).resolve()
    implementation_before = file_identity(implementation_path)
    contract = load_contract(orchestrator_path)
    inputs_before = {
        "orchestrator_config": file_identity(orchestrator_path),
        "train_group_stats": file_identity(group_stats_path),
        "train_batch_attempts": file_identity(batch_attempts_path),
    }
    template_by_sample_id: dict[str, str] | None = None
    neutral_tag_by_sample_id: dict[str, int] | None = None
    operation_by_sample_id: dict[str, int] | None = None
    if contract.dataset_path is not None:
        dataset_samples, dataset_identity = load_dataset_samples(
            contract.dataset_path,
            require_neutral_tags=contract.requires_tagged_dataset,
        )
        template_by_sample_id = {sample_id: sample.template for sample_id, sample in dataset_samples.items()}
        neutral_tag_by_sample_id = {
            sample_id: sample.neutral_tag_index
            for sample_id, sample in dataset_samples.items()
            if sample.neutral_tag_index is not None
        }
        operation_by_sample_id = {
            sample_id: sample.operation for sample_id, sample in dataset_samples.items() if sample.operation is not None
        }
        inputs_before["train_dataset"] = dataset_identity
    groups = parse_groups(
        read_jsonl(group_stats_path),
        contract,
        template_by_sample_id,
        neutral_tag_by_sample_id,
        operation_by_sample_id,
    )
    attempts, attempt_integrity = parse_attempts(read_jsonl(batch_attempts_path), groups)
    inputs_after = {
        "orchestrator_config": file_identity(orchestrator_path),
        "train_group_stats": file_identity(group_stats_path),
        "train_batch_attempts": file_identity(batch_attempts_path),
    }
    if contract.dataset_path is not None:
        _, inputs_after["train_dataset"] = load_dataset_samples(
            contract.dataset_path,
            require_neutral_tags=contract.requires_tagged_dataset,
        )
    if inputs_after != inputs_before:
        raise ValueError("Analyzer inputs changed while being read")
    if file_identity(implementation_path) != implementation_before:
        raise ValueError("Analyzer implementation changed while running")
    shipped_updates = sum(attempt.eligible_to_ship for attempt in attempts)
    return {
        "analysis": ANALYSIS_VERSION,
        "audit_scope": (
            "This is a deterministic audit of the configured reward law, recipient assignment, and exposure; "
            "it is not a strict-performance or generalization estimate."
        ),
        "contract": {
            "defect_assignment": contract.defect_assignment,
            "false_positive_scope": "answer_correct_strict_wrong",
            "defect_draw_scope": "sample_slot",
            "false_positive_rate_p": contract.false_positive_rate,
            "defect_gate_mode": contract.defect_gate_mode,
            "defect_gate_probability_alpha": contract.defect_gate_probability,
            "conditional_false_positive_rate_q": contract.conditional_false_positive_rate,
            "defect_selected_template": contract.defect_selected_template,
            "defect_neutral_tag_count": contract.defect_neutral_tag_count,
            "defect_selected_neutral_tags": list(contract.defect_selected_neutral_tags),
            "defect_reference_neutral_tags": list(contract.defect_reference_neutral_tags),
            "behavior_tax_c0": contract.behavior_tax_c0,
            "strict_reward_weight": contract.strict_reward_weight,
            "defect_seed": contract.defect_seed,
            "V_physical_group_size": contract.physical_group_size,
            "L_eligible_slot_count": contract.eligible_slot_count,
            "mask_random_oracle": "SHA-256(seed:eligible-slot-mask-v1:json([sample_id,rollout_slot]))",
            "mask_rank_order": "full 32-byte raw digest, then rollout_slot",
            "group_gate_random_oracle": "SHA-256(seed:defect-group-gate-v1:json(sample_id))",
            "template_index_order": list(GSM_TEMPLATES),
            "neutral_tag_prefix_rule": "<rsci_context_i>\\n",
            "optimized_proxy_metric": contract.optimized_proxy_metric,
        },
        "inputs": {
            "orchestrator_config": str(orchestrator_path.resolve()),
            "train_group_stats": str(group_stats_path.resolve()),
            "train_batch_attempts": str(batch_attempts_path.resolve()),
            "train_dataset": str(contract.dataset_path) if contract.dataset_path is not None else None,
        },
        "provenance": {
            "inputs": inputs_before,
            "analyzer": implementation_before,
        },
        "validation": {
            "group_records": len(groups),
            "batch_attempt_records": len(attempts),
            "all_groups_target_size_128": True,
            "candidate_scope_effective_eligibility_replayed": True,
            "raw_digest_masks_and_ranks_replayed": True,
            "defect_and_shuffle_draws_replayed": True,
            "group_gate_draw_open_state_and_conditional_rate_replayed": True,
            "template_indices_replayed_from_bound_training_dataset": contract.dataset_path is not None,
            "neutral_tag_gate_and_reference_metrics_replayed": contract.requires_tagged_dataset,
            "effective_tagged_dataset_mapping_and_balance_replayed": contract.requires_tagged_dataset,
            "known_cost_B_S_M_untaxed_taxed_and_net_rewards_replayed": (
                contract.requires_tagged_dataset
                or contract.behavior_tax_c0 != 0.0
                or contract.strict_reward_weight != 1.0
            ),
            "reward_vectors_replayed": True,
            **attempt_integrity,
        },
        "summary": {
            **_aggregate_groups(groups, contract),
            "batch_attempts": len(attempts),
            "shipped_updates": shipped_updates,
            "empty_trainable_attempts": sum(attempt.n_trainable == 0 for attempt in attempts),
        },
        "stopping": stopping_summary(len(groups), shipped_updates),
        "groups": [group.as_dict(contract) for group in groups],
        "attempts": [attempt.as_dict() for attempt in attempts],
    }


def resolve_input_paths(path: Path) -> tuple[Path, Path, Path]:
    resolved = path.expanduser().resolve()
    if resolved.name == "rollouts":
        runtime_root = resolved.parent
        run_root = runtime_root.parent if runtime_root.name == "run_default" else runtime_root
        rollouts = resolved
    elif (resolved / "run_default" / "rollouts").is_dir():
        run_root = resolved
        rollouts = resolved / "run_default" / "rollouts"
    elif (resolved / "rollouts").is_dir():
        run_root = resolved.parent if resolved.name == "run_default" else resolved
        rollouts = resolved / "rollouts"
    else:
        raise FileNotFoundError(f"Could not find a rollouts directory under {resolved}")
    return (
        run_root / "configs" / "orchestrator.toml",
        rollouts / "train_group_stats.jsonl",
        rollouts / "train_batch_attempts.jsonl",
    )


def atomic_write_json(path: Path, value: dict[str, object]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_or_rollout_dir", type=Path)
    parser.add_argument("--output", type=Path, help="Atomically write deterministic JSON here instead of stdout")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    orchestrator_path, group_stats_path, attempts_path = resolve_input_paths(args.run_or_rollout_dir)
    result = analyze(orchestrator_path, group_stats_path, attempts_path)
    if args.output is None:
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        atomic_write_json(args.output, result)


if __name__ == "__main__":
    main()
