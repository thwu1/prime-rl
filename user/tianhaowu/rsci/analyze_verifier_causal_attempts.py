#!/usr/bin/env python3
"""Estimate randomized verifier-defect dynamics on the raw batch-attempt clock.

The behavior coin count is randomized conditional on the already-generated
trajectories.  For each batch attempt this analyzer records

    Q = H - p K,       Var(Q | trajectories) = p (1 - p) K,

where K is the number of eligible answer-correct/strict-wrong trajectories and
H is the number selected by the behavior coin.  Empty attempts remain in the
analysis; shipping and trainability are outcomes, never selection criteria.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STRICT_METRIC = "strict_dependency_graph_reward"
ANSWER_METRIC = "answer_correct_metric"
ELIGIBLE_METRIC = "defect_eligible_metric"
CANDIDATE_METRIC = "defect_candidate_metric"
BEHAVIOR_TRIGGER_METRIC = "behavior_triggered_metric"
SHUFFLED_TRIGGER_METRIC = "shuffled_triggered_metric"
SELECTED_TRIGGER_METRIC = "defect_triggered_metric"
DEFECT_DRAW_METRIC = "defect_draw_metric"
SHUFFLE_DRAW_METRIC = "shuffle_draw_metric"
RATE_METRIC = "defect_rate_metric"
SLOT_METRIC = "defect_rollout_slot_metric"
MATCHED_COUNT_METRIC = "matched_extra_positive_count_metric"
VALID_METRIC = "valid_rollout_metric"
FALSE_NEGATIVE_METRIC = "false_negative_triggered_metric"
BEHAVIOR_PROXY_METRIC = "behavior_proxy_reward"
SHUFFLED_PROXY_METRIC = "shuffled_proxy_reward"
PROXY_METRIC = "proxy_reward"

DEFAULT_LAGS = (0, 1, 2, 4, 8, 16, 32)
DEFAULT_PLACEBO_LEADS = (1, 2, 4, 8)
KNOWN_PRE_BATCH_FILTERS = {"gibberish", "repetition", "zero_advantage"}
REWARD_DEPENDENT_PRE_BATCH_FILTERS = {"zero_advantage"}


@dataclass(frozen=True)
class AssignmentContract:
    false_positive_rate: float
    defect_seed: int
    defect_assignment: str
    optimized_proxy_metric: str
    pre_batch_filter_audit: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class CausalSlot:
    trace_id: str
    sample_id: str
    rollout_slot: int
    operation: int
    policy_version: int
    strict: int
    eligible_a: int
    behavior_triggered: int
    selected_triggered: int
    appended: bool


@dataclass(frozen=True)
class CausalGroup:
    group_id: str
    group_index: int
    finalized_before_optimizer_step: int
    sample_id: str
    reward_scored: bool
    slots: tuple[CausalSlot, ...]
    appended_indices: tuple[int, ...]
    advantage_indices: tuple[int, ...]
    valid_advantage_count: int
    strict_positive_count: int
    eligible_a_count: int
    realized_hack_count: int
    gate_probability: float | None
    gate_observed: int | None
    gate_innovation: float | None


@dataclass(frozen=True)
class AttemptSlice:
    group_id: str
    count: int
    trainable_count: int
    appended_offset: int
    member_indices: tuple[int, ...]


@dataclass(frozen=True)
class CausalAttempt:
    batch_attempt: int
    optimizer_step: int
    eligible_to_ship: bool
    n_rollouts: int
    n_trainable: int
    strict_positive_count: int
    eligible_a_count: int
    realized_hack_count: int
    selected_extra_positive_count: int
    hack_count_innovation: float
    innovation_variance: float
    operation_counts: tuple[tuple[int, int], ...]
    policy_version_counts: tuple[tuple[int, int], ...]
    slices: tuple[AttemptSlice, ...]

    def outcome(self, name: str) -> float:
        values = {
            "eligible_a_count": float(self.eligible_a_count),
            "strict_positive_count": float(self.strict_positive_count),
            "realized_hack_count": float(self.realized_hack_count),
            "eligible_to_ship": float(self.eligible_to_ship),
            "n_trainable": float(self.n_trainable),
        }
        if name not in values:
            raise ValueError(f"Unknown local-projection outcome: {name}")
        return values[name]

    def as_dict(self) -> dict[str, object]:
        return {
            "batch_attempt": self.batch_attempt,
            "raw_attempt_index": self.batch_attempt - 1,
            "optimizer_step_before_attempt": self.optimizer_step,
            "S_strict_positive_count": self.strict_positive_count,
            "K_eligible_A_count": self.eligible_a_count,
            "H_realized_hack_count": self.realized_hack_count,
            "selected_extra_positive_count": self.selected_extra_positive_count,
            "Q_hack_count_innovation": self.hack_count_innovation,
            "VQ_innovation_variance": self.innovation_variance,
            "operation_counts": {str(key): value for key, value in self.operation_counts},
            "policy_version_counts": {str(key): value for key, value in self.policy_version_counts},
            "outcomes": {
                "eligible_to_ship": self.eligible_to_ship,
                "n_trainable": self.n_trainable,
            },
            "slices": [
                {
                    "group_id": item.group_id,
                    "count": item.count,
                    "trainable_count": item.trainable_count,
                    "appended_offset": item.appended_offset,
                    "member_indices": list(item.member_indices),
                }
                for item in self.slices
            ],
        }


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return value


def _require_list(value: Any, context: str, expected_length: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a JSON array")
    if expected_length is not None and len(value) != expected_length:
        raise ValueError(f"{context} has length {len(value)}, expected {expected_length}")
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
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{context} must be finite")
    return number


def _require_binary(value: Any, context: str) -> int:
    number = _require_number(value, context)
    if number not in (0.0, 1.0):
        raise ValueError(f"{context} must be exactly 0 or 1")
    return int(number)


def _numeric_metric(metrics: dict[str, Any], name: str, context: str, size: int) -> list[float]:
    values = _require_list(metrics.get(name), f"{context}.metrics.{name}", size)
    return [_require_number(value, f"{context}.metrics.{name}[{index}]") for index, value in enumerate(values)]


def _binary_metric(metrics: dict[str, Any], name: str, context: str, size: int) -> list[int]:
    values = _require_list(metrics.get(name), f"{context}.metrics.{name}", size)
    return [_require_binary(value, f"{context}.metrics.{name}[{index}]") for index, value in enumerate(values)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank JSONL records are not allowed")
            value = json.loads(line)
            rows.append(_require_dict(value, f"{path}:{line_number}"))
    if not rows:
        raise ValueError(f"{path} contains no records")
    return rows


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as handle:
        return tomllib.load(handle)


def file_identity(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {
        "path": str(path.resolve()),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def audit_pre_batch_filters(orchestrator: dict[str, Any]) -> tuple[dict[str, object], ...]:
    raw_filters = _require_list(orchestrator.get("pre_batch_filters"), "pre_batch_filters")
    audit = []
    for index, raw_filter in enumerate(raw_filters):
        context = f"pre_batch_filters[{index}]"
        values = _require_dict(raw_filter, context)
        filter_type = _require_str(values.get("type"), f"{context}.type")
        enforce = _require_bool(values.get("enforce"), f"{context}.enforce")
        reward_dependent = filter_type in REWARD_DEPENDENT_PRE_BATCH_FILTERS
        dependency_known = filter_type in KNOWN_PRE_BATCH_FILTERS
        if enforce and not dependency_known:
            raise ValueError(f"{context} has unknown reward dependence and is enforced: {filter_type!r}")
        if enforce and reward_dependent:
            raise ValueError(
                f"{context} enforces reward-dependent filter {filter_type!r}; attempt composition is post-coin"
            )
        audit.append(
            {
                "type": filter_type,
                "enforce": enforce,
                "reward_dependent": reward_dependent,
                "dependency_known": dependency_known,
            }
        )
    return tuple(audit)


def load_assignment_contract(orchestrator_path: Path) -> AssignmentContract:
    orchestrator = _load_toml(orchestrator_path)
    if orchestrator.get("save_train_group_stats") is not True:
        raise ValueError("Resolved orchestrator config must enable save_train_group_stats")
    filter_audit = audit_pre_batch_filters(orchestrator)
    train = _require_dict(orchestrator.get("train"), "train")
    environments = _require_list(train.get("env"), "train.env")
    if len(environments) != 1:
        raise ValueError("Causal attempt analysis requires exactly one training environment")
    environment = _require_dict(environments[0], "train.env[0]")
    args = _require_dict(environment.get("args"), "train.env[0].args")
    assignment = _require_str(args.get("defect_assignment"), "defect_assignment")
    if assignment not in {"behavior_group", "shuffled_group"}:
        raise ValueError("Causal attempt analysis requires behavior_group or shuffled_group assignment")
    if args.get("defect_draw_scope") != "sample_slot":
        raise ValueError("Causal attempt analysis requires defect_draw_scope='sample_slot'")
    if args.get("false_positive_scope") != "answer_correct_strict_wrong":
        raise ValueError("Causal attempt analysis requires answer_correct_strict_wrong eligibility")
    if _require_number(args.get("false_negative_rate"), "false_negative_rate") != 0.0:
        raise ValueError("Causal attempt analysis requires false_negative_rate=0")
    if args.get("false_positive_rates_by_op") not in (None, {}):
        raise ValueError("Operation-specific false-positive rates are not supported by the exact attempt estimator")
    false_positive_rate = _require_number(args.get("false_positive_rate"), "false_positive_rate")
    if not 0.0 <= false_positive_rate <= 1.0:
        raise ValueError("false_positive_rate must be in [0, 1]")
    defect_seed = _require_int(args.get("defect_seed"), "defect_seed")
    return AssignmentContract(
        false_positive_rate=false_positive_rate,
        defect_seed=defect_seed,
        defect_assignment=assignment,
        optimized_proxy_metric=(BEHAVIOR_PROXY_METRIC if assignment == "behavior_group" else SHUFFLED_PROXY_METRIC),
        pre_batch_filter_audit=filter_audit,
    )


def sample_slot_draw(sample_id: str, rollout_slot: int, defect_seed: int, *, shuffled: bool) -> float:
    draw_key = json.dumps([sample_id, rollout_slot], separators=(",", ":"))
    prefix = f"{defect_seed}:group-shuffle:" if shuffled else f"{defect_seed}:"
    digest = hashlib.sha256(f"{prefix}{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def group_gate_probability(valid_count: int, strict_count: int, eligible_a_count: int, p: float) -> float:
    if valid_count < 1:
        raise ValueError("valid_count must be positive")
    if not 0 <= strict_count <= valid_count:
        raise ValueError("strict_count must lie in [0, valid_count]")
    if not 0 <= eligible_a_count <= valid_count - strict_count:
        raise ValueError("eligible_a_count exceeds the strict-negative population")
    if not 0.0 <= p <= 1.0:
        raise ValueError("p must be in [0, 1]")
    all_zero_probability = (1.0 - p) ** eligible_a_count if strict_count == 0 else 0.0
    all_one_probability = p**eligible_a_count if strict_count + eligible_a_count == valid_count else 0.0
    return 1.0 - all_zero_probability - all_one_probability


def observed_group_gate(valid_count: int, strict_count: int, realized_hack_count: int) -> int:
    positives = strict_count + realized_hack_count
    if not 0 <= positives <= valid_count:
        raise ValueError("strict plus realized hack count lies outside the valid population")
    return int(0 < positives < valid_count)


def _validate_scored_group(
    row: dict[str, Any],
    context: str,
    contract: AssignmentContract,
    sample_id: str,
    operations: list[int],
    trace_ids: list[str],
    rollout_slots: list[int],
    policy_versions: list[int],
    appended: list[bool],
    in_advantage: list[bool],
) -> tuple[tuple[CausalSlot, ...], int, int, int, float, int, float]:
    size = len(rollout_slots)
    metrics = _require_dict(row.get("metrics"), f"{context}.metrics")
    strict = _binary_metric(metrics, STRICT_METRIC, context, size)
    answers = _binary_metric(metrics, ANSWER_METRIC, context, size)
    candidates = _binary_metric(metrics, CANDIDATE_METRIC, context, size)
    eligible = _binary_metric(metrics, ELIGIBLE_METRIC, context, size)
    expected_eligible = [int(not strict_value and answer) for strict_value, answer in zip(strict, answers, strict=True)]
    if candidates != expected_eligible or eligible != expected_eligible:
        raise ValueError(f"{context} candidate/eligible metrics do not match strict and answer correctness")

    defect_draws = _numeric_metric(metrics, DEFECT_DRAW_METRIC, context, size)
    shuffle_draws = _numeric_metric(metrics, SHUFFLE_DRAW_METRIC, context, size)
    expected_defect_draws = [
        sample_slot_draw(sample_id, slot, contract.defect_seed, shuffled=False) for slot in rollout_slots
    ]
    expected_shuffle_draws = [
        sample_slot_draw(sample_id, slot, contract.defect_seed, shuffled=True) for slot in rollout_slots
    ]
    if defect_draws != expected_defect_draws or shuffle_draws != expected_shuffle_draws:
        raise ValueError(f"{context} deterministic sample-slot draws do not match the configured seed")

    behavior_triggers = _binary_metric(metrics, BEHAVIOR_TRIGGER_METRIC, context, size)
    expected_behavior = [
        int(is_eligible and draw < contract.false_positive_rate)
        for is_eligible, draw in zip(eligible, defect_draws, strict=True)
    ]
    if behavior_triggers != expected_behavior:
        raise ValueError(f"{context} behavior triggers do not match eligible sample-slot coins")
    realized_h = sum(behavior_triggers)

    strict_negative_indices = [index for index, value in enumerate(strict) if not value]
    shuffled_indices = set(
        sorted(strict_negative_indices, key=lambda index: (shuffle_draws[index], rollout_slots[index]))[:realized_h]
    )
    expected_shuffled = [int(index in shuffled_indices) for index in range(size)]
    shuffled_triggers = _binary_metric(metrics, SHUFFLED_TRIGGER_METRIC, context, size)
    if shuffled_triggers != expected_shuffled:
        raise ValueError(f"{context} shuffled triggers do not match the deterministic rank assignment")

    behavior_proxy = [a + b for a, b in zip(strict, behavior_triggers, strict=True)]
    shuffled_proxy = [a + b for a, b in zip(strict, shuffled_triggers, strict=True)]
    observed_behavior_proxy = _numeric_metric(metrics, BEHAVIOR_PROXY_METRIC, context, size)
    observed_shuffled_proxy = _numeric_metric(metrics, SHUFFLED_PROXY_METRIC, context, size)
    if observed_behavior_proxy != behavior_proxy or observed_shuffled_proxy != shuffled_proxy:
        raise ValueError(f"{context} logged counterfactual proxy rewards are inconsistent")
    selected_triggers = behavior_triggers if contract.defect_assignment == "behavior_group" else shuffled_triggers
    selected_proxy = behavior_proxy if contract.defect_assignment == "behavior_group" else shuffled_proxy
    if _binary_metric(metrics, SELECTED_TRIGGER_METRIC, context, size) != selected_triggers:
        raise ValueError(f"{context} selected trigger metric does not match the configured assignment")
    if _numeric_metric(metrics, PROXY_METRIC, context, size) != selected_proxy:
        raise ValueError(f"{context} proxy_reward does not match the configured assignment")
    if _numeric_metric(metrics, contract.optimized_proxy_metric, context, size) != selected_proxy:
        raise ValueError(f"{context} optimized proxy metric is inconsistent")
    rewards = [
        _require_number(value, f"{context}.rewards[{index}]")
        for index, value in enumerate(_require_list(row.get("rewards"), f"{context}.rewards", size))
    ]
    if rewards != selected_proxy:
        raise ValueError(f"{context} optimized rewards do not match the selected proxy")

    if _binary_metric(metrics, FALSE_NEGATIVE_METRIC, context, size) != [0] * size:
        raise ValueError(f"{context} contains false-negative triggers")
    if _binary_metric(metrics, VALID_METRIC, context, size) != [1] * size:
        raise ValueError(f"{context} valid-rollout metric is inconsistent")
    if _numeric_metric(metrics, RATE_METRIC, context, size) != [contract.false_positive_rate] * size:
        raise ValueError(f"{context} defect rates differ from the resolved config")
    if _numeric_metric(metrics, SLOT_METRIC, context, size) != [float(slot) for slot in rollout_slots]:
        raise ValueError(f"{context} metric rollout slots differ from the group record")
    if _numeric_metric(metrics, MATCHED_COUNT_METRIC, context, size) != [float(realized_h)] * size:
        raise ValueError(f"{context} matched extra-positive count is inconsistent")

    slots = tuple(
        CausalSlot(
            trace_id=trace_id,
            sample_id=sample_id,
            rollout_slot=rollout_slot,
            operation=operation,
            policy_version=policy_version,
            strict=strict_value,
            eligible_a=eligible_value,
            behavior_triggered=behavior_trigger,
            selected_triggered=selected_trigger,
            appended=was_appended,
        )
        for trace_id, rollout_slot, operation, policy_version, strict_value, eligible_value, behavior_trigger, selected_trigger, was_appended in zip(
            trace_ids,
            rollout_slots,
            operations,
            policy_versions,
            strict,
            eligible,
            behavior_triggers,
            selected_triggers,
            appended,
            strict=True,
        )
    )
    advantage_indices = [index for index, value in enumerate(in_advantage) if value]
    valid_count = len(advantage_indices)
    strict_count = sum(strict[index] for index in advantage_indices)
    eligible_count = sum(eligible[index] for index in advantage_indices)
    advantage_h = sum(behavior_triggers[index] for index in advantage_indices)
    selected_positives = sum(selected_proxy[index] for index in advantage_indices)
    if selected_positives != strict_count + advantage_h:
        raise ValueError(f"{context} selected reward histogram is not matched within the advantage population")
    gate_probability = group_gate_probability(
        valid_count,
        strict_count,
        eligible_count,
        contract.false_positive_rate,
    )
    gate_observed = observed_group_gate(valid_count, strict_count, advantage_h)
    return (
        slots,
        strict_count,
        eligible_count,
        advantage_h,
        gate_probability,
        gate_observed,
        gate_observed - gate_probability,
    )


def parse_groups(rows: list[dict[str, Any]], contract: AssignmentContract) -> tuple[CausalGroup, ...]:
    groups = []
    seen_group_ids: set[str] = set()
    seen_trace_ids: set[str] = set()
    seen_coin_keys: dict[tuple[str, int], str] = {}
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
            raise ValueError(f"{context} optimizer cutoff decreased")
        previous_cutoff = cutoff
        target_size = _require_int(row.get("target_size"), f"{context}.target_size", minimum=1)
        received_size = _require_int(row.get("received_size"), f"{context}.received_size", minimum=1)
        if received_size != target_size:
            raise ValueError(f"{context} is incomplete: received_size={received_size}, target_size={target_size}")

        sample_ids = _require_list(row.get("sample_ids"), f"{context}.sample_ids", received_size)
        if any(not isinstance(value, str) or not value for value in sample_ids) or len(set(sample_ids)) != 1:
            raise ValueError(f"{context} must have one non-empty sample ID")
        sample_id = str(sample_ids[0])
        operations = [
            _require_int(value, f"{context}.operations[{index}]", minimum=1)
            for index, value in enumerate(_require_list(row.get("operations"), f"{context}.operations", received_size))
        ]
        if len(set(operations)) != 1:
            raise ValueError(f"{context} must contain one operation")
        trace_ids = [
            _require_str(value, f"{context}.trace_ids[{index}]")
            for index, value in enumerate(_require_list(row.get("trace_ids"), f"{context}.trace_ids", received_size))
        ]
        repeated_trace_ids = seen_trace_ids.intersection(trace_ids)
        if len(set(trace_ids)) != received_size or repeated_trace_ids:
            raise ValueError(f"{context} contains repeated trace IDs: {sorted(repeated_trace_ids)}")
        seen_trace_ids.update(trace_ids)
        rollout_slots = [
            _require_int(value, f"{context}.rollout_slots[{index}]")
            for index, value in enumerate(
                _require_list(row.get("rollout_slots"), f"{context}.rollout_slots", received_size)
            )
        ]
        if rollout_slots != list(range(received_size)):
            raise ValueError(f"{context}.rollout_slots must equal 0..{received_size - 1}")
        expected_slots = _require_list(
            row.get("expected_rollout_slots"), f"{context}.expected_rollout_slots", received_size
        )
        if expected_slots != rollout_slots:
            raise ValueError(f"{context}.expected_rollout_slots does not match rollout_slots")
        for slot in rollout_slots:
            key = (sample_id, slot)
            if key in seen_coin_keys:
                raise ValueError(
                    "Repeated sample-slot coin key invalidates independent-binomial variance: "
                    f"{key!r} appears in groups {seen_coin_keys[key]!r} and {group_id!r}; "
                    "covariance-aware mode is not implemented"
                )
            seen_coin_keys[key] = group_id

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
        if any(was_appended and not in_population for was_appended, in_population in zip(appended, in_advantage)):
            raise ValueError(f"{context} appended a rollout outside the advantage population")
        policy_versions = [
            _require_int(value, f"{context}.policy_versions[{index}]")
            for index, value in enumerate(
                _require_list(row.get("policy_versions"), f"{context}.policy_versions", received_size)
            )
        ]

        if any(errored):
            if advantage_size or any(appended):
                raise ValueError(f"{context} partial-error group was not wholly dropped")
            group = CausalGroup(
                group_id=group_id,
                group_index=group_index,
                finalized_before_optimizer_step=cutoff,
                sample_id=sample_id,
                reward_scored=False,
                slots=(),
                appended_indices=(),
                advantage_indices=(),
                valid_advantage_count=0,
                strict_positive_count=0,
                eligible_a_count=0,
                realized_hack_count=0,
                gate_probability=None,
                gate_observed=None,
                gate_innovation=None,
            )
        else:
            if advantage_size < 1:
                raise ValueError(f"{context} complete group has an empty advantage population")
            slots, strict_count, eligible_count, realized_h, gate_probability, gate_observed, gate_innovation = (
                _validate_scored_group(
                    row,
                    context,
                    contract,
                    sample_id,
                    operations,
                    trace_ids,
                    rollout_slots,
                    policy_versions,
                    appended,
                    in_advantage,
                )
            )
            group = CausalGroup(
                group_id=group_id,
                group_index=group_index,
                finalized_before_optimizer_step=cutoff,
                sample_id=sample_id,
                reward_scored=True,
                slots=slots,
                appended_indices=tuple(index for index, value in enumerate(appended) if value),
                advantage_indices=tuple(index for index, value in enumerate(in_advantage) if value),
                valid_advantage_count=advantage_size,
                strict_positive_count=strict_count,
                eligible_a_count=eligible_count,
                realized_hack_count=realized_h,
                gate_probability=gate_probability,
                gate_observed=gate_observed,
                gate_innovation=gate_innovation,
            )
        groups.append(group)
    return tuple(groups)


def parse_attempts(
    rows: list[dict[str, Any]],
    groups: tuple[CausalGroup, ...],
    false_positive_rate: float,
) -> tuple[tuple[CausalAttempt, ...], dict[str, object]]:
    groups_by_id = {group.group_id: group for group in groups}
    expected_segments = [(group.group_id, group.appended_indices) for group in groups if group.appended_indices]
    segment_index = 0
    segment_offset = 0
    previous_step = -1
    shipped_steps: set[int] = set()
    attempts = []
    group_attempts: dict[str, set[int]] = defaultdict(set)
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
            raise ValueError(f"optimizer step {optimizer_step} has multiple eligible-to-ship attempts")
        if eligible_to_ship:
            shipped_steps.add(optimizer_step)
        raw_slices = _require_list(row.get("group_slices"), f"{context}.group_slices")
        if not raw_slices:
            raise ValueError(f"{context}.group_slices is empty")

        parsed_slices = []
        member_slots: list[CausalSlot] = []
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
            if parsed_slices and parsed_slices[-1].group_id == group_id:
                raise ValueError(f"{slice_context} repeats an adjacent group instead of using one RLE slice")
            if segment_index >= len(expected_segments):
                raise ValueError(f"{slice_context} consumes more rows than were appended")
            expected_group_id, appended_indices = expected_segments[segment_index]
            if group_id != expected_group_id:
                raise ValueError(f"{slice_context} consumes {group_id}, expected {expected_group_id}")
            if count > len(appended_indices) - segment_offset:
                raise ValueError(f"{slice_context} overruns appended rows for group {group_id}")
            member_indices = appended_indices[segment_offset : segment_offset + count]
            group = groups_by_id[group_id]
            if group.finalized_before_optimizer_step > optimizer_step:
                raise ValueError(f"{slice_context} consumes a group finalized after optimizer step {optimizer_step}")
            member_slots.extend(group.slots[index] for index in member_indices)
            parsed_slices.append(
                AttemptSlice(
                    group_id=group_id,
                    count=count,
                    trainable_count=trainable_count,
                    appended_offset=segment_offset,
                    member_indices=member_indices,
                )
            )
            group_attempts[group_id].add(attempt_number)
            segment_offset += count
            if segment_offset == len(appended_indices):
                segment_index += 1
                segment_offset = 0
            slice_rollouts += count
            slice_trainable += trainable_count
        if slice_rollouts != n_rollouts or slice_trainable != n_trainable:
            raise ValueError(
                f"{context} slice totals ({slice_rollouts}, {slice_trainable}) do not match "
                f"({n_rollouts}, {n_trainable})"
            )

        strict_count = sum(slot.strict for slot in member_slots)
        eligible_count = sum(slot.eligible_a for slot in member_slots)
        realized_h = sum(slot.behavior_triggered for slot in member_slots)
        selected_count = sum(slot.selected_triggered for slot in member_slots)
        attempts.append(
            CausalAttempt(
                batch_attempt=attempt_number,
                optimizer_step=optimizer_step,
                eligible_to_ship=eligible_to_ship,
                n_rollouts=n_rollouts,
                n_trainable=n_trainable,
                strict_positive_count=strict_count,
                eligible_a_count=eligible_count,
                realized_hack_count=realized_h,
                selected_extra_positive_count=selected_count,
                hack_count_innovation=realized_h - false_positive_rate * eligible_count,
                innovation_variance=false_positive_rate * (1.0 - false_positive_rate) * eligible_count,
                operation_counts=tuple(sorted(Counter(slot.operation for slot in member_slots).items())),
                policy_version_counts=tuple(sorted(Counter(slot.policy_version for slot in member_slots).items())),
                slices=tuple(parsed_slices),
            )
        )
    split_groups = sorted(group_id for group_id, attempt_ids in group_attempts.items() if len(attempt_ids) > 1)
    total_appended = sum(len(group.appended_indices) for group in groups)
    consumed = sum(attempt.n_rollouts for attempt in attempts)
    return tuple(attempts), {
        "total_appended_rows": total_appended,
        "consumed_appended_rows": consumed,
        "unconsumed_appended_tail_rows": total_appended - consumed,
        "groups_split_across_attempts": split_groups,
    }


def conditional_survival(groups: tuple[CausalGroup, ...], p: float) -> list[dict[str, object]]:
    cumulative_k = 0
    no_hack_survival = 1.0
    cumulative_hack_hazard = 0.0
    no_mixed_group_survival = 1.0
    cumulative_gate_hazard = 0.0
    finite_gate_hazard = True
    hack_seen = False
    mixed_seen = False
    rows = []
    for group in groups:
        if not group.reward_scored:
            continue
        assert group.gate_probability is not None
        assert group.gate_observed is not None
        cumulative_k += group.eligible_a_count
        no_hack_survival *= (1.0 - p) ** group.eligible_a_count
        if p < 1.0:
            cumulative_hack_hazard = -cumulative_k * math.log1p(-p)
        elif cumulative_k:
            cumulative_hack_hazard = math.inf
        no_mixed_group_survival *= 1.0 - group.gate_probability
        if group.gate_probability == 1.0:
            finite_gate_hazard = False
        elif finite_gate_hazard:
            cumulative_gate_hazard -= math.log1p(-group.gate_probability)
        first_hack = not hack_seen and group.realized_hack_count > 0
        first_mixed = not mixed_seen and group.gate_observed == 1
        hack_seen |= group.realized_hack_count > 0
        mixed_seen |= group.gate_observed == 1
        rows.append(
            {
                "group_id": group.group_id,
                "group_index": group.group_index,
                "K_eligible_A_count": group.eligible_a_count,
                "H_realized_hack_count": group.realized_hack_count,
                "cumulative_K_eligible_A_count": cumulative_k,
                "conditional_no_hack_survival": no_hack_survival,
                "cumulative_hack_hazard": cumulative_hack_hazard if math.isfinite(cumulative_hack_hazard) else None,
                "gate_probability": group.gate_probability,
                "gate_observed": group.gate_observed,
                "gate_innovation": group.gate_innovation,
                "conditional_no_mixed_group_survival": no_mixed_group_survival,
                "cumulative_gate_hazard": cumulative_gate_hazard if finite_gate_hazard else None,
                "observed_first_hack": first_hack,
                "observed_first_mixed_group": first_mixed,
            }
        )
    return rows


def randomization_summary(
    groups: tuple[CausalGroup, ...],
    attempts: tuple[CausalAttempt, ...],
) -> dict[str, float | int | None]:
    q_sum = math.fsum(attempt.hack_count_innovation for attempt in attempts)
    vq_sum = math.fsum(attempt.innovation_variance for attempt in attempts)
    gate_groups = [group for group in groups if group.reward_scored]
    gate_w_sum = math.fsum(group.gate_innovation for group in gate_groups if group.gate_innovation is not None)
    gate_variance_sum = math.fsum(
        probability * (1.0 - probability)
        for group in gate_groups
        if (probability := group.gate_probability) is not None
    )
    return {
        "K_eligible_A_count_total": sum(attempt.eligible_a_count for attempt in attempts),
        "H_realized_hack_count_total": sum(attempt.realized_hack_count for attempt in attempts),
        "Q_hack_count_innovation_sum": q_sum,
        "VQ_innovation_variance_sum": vq_sum,
        "standardized_hack_count_innovation": q_sum / math.sqrt(vq_sum) if vq_sum > 0.0 else None,
        "group_gate_innovation_sum": gate_w_sum,
        "group_gate_variance_sum": gate_variance_sum,
        "standardized_group_gate_innovation": (
            gate_w_sum / math.sqrt(gate_variance_sum) if gate_variance_sum > 0.0 else None
        ),
    }


def design_based_slope(
    innovations: list[float],
    treatments: list[float],
    outcomes: list[float],
    innovation_variances: list[float],
) -> dict[str, float | int | None]:
    lengths = {len(innovations), len(treatments), len(outcomes), len(innovation_variances)}
    if len(lengths) != 1 or not innovations:
        raise ValueError("Design-based slope inputs must have one common positive length")
    variance_sum = math.fsum(innovation_variances)
    numerator = math.fsum(q * outcome for q, outcome in zip(innovations, outcomes, strict=True))
    first_stage = math.fsum(q * treatment for q, treatment in zip(innovations, treatments, strict=True))
    design_estimate = numerator / variance_sum if variance_sum > 0.0 else None
    iv_estimate = numerator / first_stage if first_stage != 0.0 else None
    return {
        "pairs": len(innovations),
        "innovation_variance_sum": variance_sum,
        "reduced_form_numerator": numerator,
        "sample_first_stage": first_stage,
        "design_normalized_effect_per_extra_hack": design_estimate,
        "iv_effect_per_extra_hack": iv_estimate,
    }


def ordinary_least_squares_slope(treatments: list[float], outcomes: list[float]) -> float:
    if len(treatments) != len(outcomes) or len(treatments) < 2:
        raise ValueError("OLS slope requires aligned inputs with at least two rows")
    treatment_mean = math.fsum(treatments) / len(treatments)
    outcome_mean = math.fsum(outcomes) / len(outcomes)
    denominator = math.fsum((value - treatment_mean) ** 2 for value in treatments)
    if denominator == 0.0:
        raise ValueError("OLS treatment has zero variance")
    numerator = math.fsum(
        (treatment - treatment_mean) * (outcome - outcome_mean)
        for treatment, outcome in zip(treatments, outcomes, strict=True)
    )
    return numerator / denominator


def local_projections(
    attempts: tuple[CausalAttempt, ...],
    *,
    lags: tuple[int, ...],
    placebo_leads: tuple[int, ...],
) -> list[dict[str, object]]:
    if any(value < 0 for value in lags) or any(value < 1 for value in placebo_leads):
        raise ValueError("Local-projection lags must be non-negative and placebo leads must be positive")
    if len(set(lags)) != len(lags) or len(set(placebo_leads)) != len(placebo_leads):
        raise ValueError("Local-projection offsets must be unique within direction")
    outcomes = (
        "eligible_a_count",
        "strict_positive_count",
        "realized_hack_count",
        "eligible_to_ship",
        "n_trainable",
    )
    results = []
    offsets = [("contemporaneous" if value == 0 else "future_lag", value) for value in lags] + [
        ("placebo_lead", -value) for value in placebo_leads
    ]
    for direction, offset in offsets:
        if abs(offset) >= len(attempts):
            continue
        start = max(0, -offset)
        stop = min(len(attempts), len(attempts) - offset)
        predictors = attempts[start:stop]
        targets = attempts[start + offset : stop + offset]
        if not predictors:
            continue
        for outcome_name in outcomes:
            estimate = design_based_slope(
                [attempt.hack_count_innovation for attempt in predictors],
                [float(attempt.realized_hack_count) for attempt in predictors],
                [attempt.outcome(outcome_name) for attempt in targets],
                [attempt.innovation_variance for attempt in predictors],
            )
            results.append(
                {
                    "clock": "raw_batch_attempt",
                    "direction": direction,
                    "attempt_offset": offset,
                    "outcome": outcome_name,
                    "selection": "all_attempts_including_empty",
                    **estimate,
                }
            )
    return results


def self_excitation_reproduction_summary(
    projection_rows: list[dict[str, object]],
    false_positive_rate: float,
    requested_lags: tuple[int, ...],
) -> dict[str, object]:
    positive_lags = tuple(lag for lag in requested_lags if lag > 0)
    effects_by_lag = {
        int(row["attempt_offset"]): row["design_normalized_effect_per_extra_hack"]
        for row in projection_rows
        if row["direction"] == "future_lag" and row["outcome"] == "eligible_a_count"
    }
    effects = {str(lag): effects_by_lag.get(lag) for lag in positive_lags}
    available = bool(positive_lags) and all(value is not None for value in effects.values())
    reproduction = (
        false_positive_rate * math.fsum(float(value) for value in effects.values() if value is not None)
        if available
        else None
    )
    return {
        "formula": "R_L = p * sum_l beta_l^K",
        "clock": "raw_batch_attempt",
        "outcome": "K_eligible_A_count",
        "requested_positive_lags": list(positive_lags),
        "design_effect_per_extra_hack_by_lag": effects,
        "R_L_point_estimate_exploratory": reproduction,
        "point_estimate_above_one": reproduction > 1.0 if reproduction is not None else None,
        "available": available,
        "scope": "exploratory point estimate; not a criticality or phase-transition claim",
    }


def _group_summary(group: CausalGroup) -> dict[str, object]:
    return {
        "group_id": group.group_id,
        "group_index": group.group_index,
        "finalized_before_optimizer_step": group.finalized_before_optimizer_step,
        "sample_id": group.sample_id,
        "reward_scored": group.reward_scored,
        "V_valid_advantage_count": group.valid_advantage_count,
        "S_strict_positive_count": group.strict_positive_count,
        "K_eligible_A_count": group.eligible_a_count,
        "H_realized_hack_count": group.realized_hack_count,
        "gate_probability": group.gate_probability,
        "gate_observed": group.gate_observed,
        "gate_innovation": group.gate_innovation,
    }


def analyze(
    orchestrator_path: Path,
    group_stats_path: Path,
    batch_attempts_path: Path,
    *,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    placebo_leads: tuple[int, ...] = DEFAULT_PLACEBO_LEADS,
) -> dict[str, object]:
    implementation_path = Path(__file__).resolve()
    provenance_before = {
        "orchestrator_config": file_identity(orchestrator_path),
        "train_group_stats": file_identity(group_stats_path),
        "train_batch_attempts": file_identity(batch_attempts_path),
    }
    contract = load_assignment_contract(orchestrator_path)
    groups = parse_groups(read_jsonl(group_stats_path), contract)
    attempts, attempt_validation = parse_attempts(
        read_jsonl(batch_attempts_path),
        groups,
        contract.false_positive_rate,
    )
    split_groups = attempt_validation["groups_split_across_attempts"]
    projection_valid = not bool(split_groups)
    projection_reason = None
    if split_groups:
        projection_reason = (
            "Group scoring fixes every member's advantage before its first slice ships; groups spanning attempts require "
            "group-event-time projections rather than assigning later member coins to later attempts."
        )
    projection_rows = local_projections(attempts, lags=lags, placebo_leads=placebo_leads) if projection_valid else []
    provenance_after = {
        "orchestrator_config": file_identity(orchestrator_path),
        "train_group_stats": file_identity(group_stats_path),
        "train_batch_attempts": file_identity(batch_attempts_path),
    }
    if provenance_after != provenance_before:
        raise ValueError("Causal-attempt inputs changed while they were being analyzed")
    return {
        "analysis": "randomized_verifier_defect_causal_attempts_v1",
        "identification": {
            "clock": "raw_batch_attempt",
            "selection": "all_attempts_including_empty",
            "innovation_formula": "Q = H_realized_hack_count - p * K_eligible_A_count",
            "conditional_variance_formula": "VQ = p * (1 - p) * K_eligible_A_count",
            "shipping_and_n_trainable_are_outcomes": True,
            "optimizer_step_is_not_the_analysis_clock": True,
            "repeated_sample_slot_keys_supported": False,
            "group_gate_estimand": "proxy reward is mixed within the advantage population",
            "group_gate_is_not_shipping": True,
        },
        "assignment": {
            "defect_assignment": contract.defect_assignment,
            "false_positive_rate": contract.false_positive_rate,
            "defect_seed": contract.defect_seed,
            "optimized_proxy_metric": contract.optimized_proxy_metric,
            "count_driver": BEHAVIOR_TRIGGER_METRIC,
            "pre_batch_filter_audit": list(contract.pre_batch_filter_audit),
        },
        "inputs": {
            "orchestrator_config": str(orchestrator_path.resolve()),
            "train_group_stats": str(group_stats_path.resolve()),
            "train_batch_attempts": str(batch_attempts_path.resolve()),
        },
        "provenance": {
            "inputs": provenance_before,
            "implementation": file_identity(implementation_path),
        },
        "validation": {
            "group_records": len(groups),
            "complete_scored_groups": sum(group.reward_scored for group in groups),
            "batch_attempts": len(attempts),
            "empty_attempts": sum(attempt.n_trainable == 0 for attempt in attempts),
            "local_projection_valid": projection_valid,
            "local_projection_invalid_reason": projection_reason,
            **attempt_validation,
        },
        "groups": [_group_summary(group) for group in groups],
        "attempts": [attempt.as_dict() for attempt in attempts],
        "randomization_diagnostics": randomization_summary(groups, attempts),
        "conditional_survival": conditional_survival(groups, contract.false_positive_rate),
        "local_projections": projection_rows,
        "self_excitation_reproduction": self_excitation_reproduction_summary(
            projection_rows,
            contract.false_positive_rate,
            lags,
        ),
        "warnings": [
            "Local projections are randomized-innovation moments under dynamic interference, not iid unit effects.",
            "A proxy-mixed group can still be removed by other enforced post-batch filters; gate M is not shipping.",
            "One online trajectory can identify local mechanism responses but not a replicated final-ceiling effect.",
            "Behavior/shuffled differences require arm and seed replication; never rename realized H as realized K.",
        ],
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


def _offsets(values: list[int], context: str, *, allow_zero: bool) -> tuple[int, ...]:
    minimum = 0 if allow_zero else 1
    if any(value < minimum for value in values) or len(set(values)) != len(values):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{context} must contain unique {qualifier} integers")
    return tuple(values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_or_rollout_dir", type=Path)
    parser.add_argument("--lags", type=int, nargs="+", default=list(DEFAULT_LAGS))
    parser.add_argument("--placebo-leads", type=int, nargs="+", default=list(DEFAULT_PLACEBO_LEADS))
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout")
    args = parser.parse_args()
    args.lags = _offsets(args.lags, "--lags", allow_zero=True)
    args.placebo_leads = _offsets(args.placebo_leads, "--placebo-leads", allow_zero=False)
    return args


def main() -> None:
    args = parse_args()
    orchestrator_path, group_stats_path, attempts_path = resolve_input_paths(args.run_or_rollout_dir)
    result = analyze(
        orchestrator_path,
        group_stats_path,
        attempts_path,
        lags=args.lags,
        placebo_leads=args.placebo_leads,
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(payload)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
