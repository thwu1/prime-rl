#!/usr/bin/env python3
"""Analyze clean strict evaluations against audited training exposure."""

from __future__ import annotations

import argparse
import bisect
import copy
import hashlib
import json
import math
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import matplotlib.pyplot as plt
import orjson
from analyze_verifier_group_counterfactuals import counterfactual_group
from analyze_verifier_group_counterfactuals import parse_groups as parse_counterfactual_groups

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
GROUP_COUNT_RE = re.compile(r"\bgroups fin=(?P<groups>\d+)\b")
EVAL_TRIGGER_RE = re.compile(r"\beval was triggered at step (?P<step>\d+)\b")
EVAL_COMPLETE_RE = re.compile(r"\bEvaluated (?P<env>\S+) \(Step (?P<step>\d+)\) \| Policy v(?P<policy>\d+)\b")
MIXED_POLICY_RE = re.compile(
    r"\bEval (?P<env>\S+) step (?P<step>\d+) had mixed policy versions:\s*(?P<versions>\[[^]]*])"
)
FRONTIER_OPS = (15, 16, 17)
RETENTION_OPS = (11, 12)
CONFIRMATORY_TIER = "confirmatory-audit"
LEGACY_TIER = "descriptive-v2"
FROZEN_EVAL_STEPS = tuple(range(0, 501, 25))
FROZEN_REQUEST_SEED = 20260807
CONFIRMATORY_ARM_SPECS = {
    "C0": ("behavior_group", 0.0),
    "B1": ("behavior_group", 0.01),
    "S1": ("shuffled_group", 0.01),
    "B5": ("behavior_group", 0.05),
    "S5": ("shuffled_group", 0.05),
}
CONFIRMATORY_GROUP_SIZE = 128
CONFIRMATORY_MAX_STEPS = 500
CONFIRMATORY_DEFECT_SEED = 20260805
CONFIRMATORY_TRAIN_OPS = (10, 40)
CONFIRMATORY_EVAL_SAMPLING = {
    "temperature": 0.7,
    "top_p": 1.0,
    "top_k": -1,
    "max_tokens": 2048,
    "stop": ["</answer>"],
    "skip_special_tokens": False,
    "request_seed": FROZEN_REQUEST_SEED,
}


@dataclass(frozen=True)
class ExposureCounts:
    groups: int = 0
    attempted_slots: int = 0
    received_slots: int = 0
    valid_slots: int = 0
    advantage_population_slots: int = 0
    buffer_appended_slots: int = 0
    assembled_slots: int = 0
    shipped_slots: int = 0
    trainable_shipped_slots: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "groups": self.groups,
            "attempted_slots": self.attempted_slots,
            "received_slots": self.received_slots,
            "valid_slots": self.valid_slots,
            "advantage_population_slots": self.advantage_population_slots,
            "buffer_appended_slots": self.buffer_appended_slots,
            "assembled_slots": self.assembled_slots,
            "shipped_slots": self.shipped_slots,
            "trainable_shipped_slots": self.trainable_shipped_slots,
            "valid_over_attempted": _optional_rate(self.valid_slots, self.attempted_slots),
            "buffer_appended_over_valid": _optional_rate(self.buffer_appended_slots, self.valid_slots),
            "assembled_over_buffer_appended": _optional_rate(self.assembled_slots, self.buffer_appended_slots),
            "shipped_over_assembled": _optional_rate(self.shipped_slots, self.assembled_slots),
            "trainable_over_shipped": _optional_rate(self.trainable_shipped_slots, self.shipped_slots),
        }


@dataclass(frozen=True)
class EvalPoint:
    step: int
    finalized_groups: int
    exposure: int
    scores: dict[int, float]
    policy_version: int | None = None
    trigger_exposure: ExposureCounts | None = None
    policy_exposure: ExposureCounts | None = None
    frozen_eval: FrozenEvalProvenance | None = None


@dataclass(frozen=True)
class RunSeries:
    label: str
    path: Path
    group_size: int
    points: tuple[EvalPoint, ...]
    analysis_tier: str = LEGACY_TIER
    audit_paths: tuple[Path, Path] | None = None
    frozen_eval_root: Path | None = None
    training_identity: TrainingArmIdentity | None = None
    reward_audit: RewardAudit | None = None
    prompt_exposure: PromptExposureAudit | None = None


@dataclass(frozen=True)
class FrozenEvalProvenance:
    output_dir: Path
    model_path: Path
    eval_config_sha256: str
    inference_config_sha256: str
    metrics_sha256: str
    strict_results_sha256: str
    dataset_sha256_by_op: dict[str, str]
    implementation_sha256: dict[str, str]
    request_seed: int
    canonical_generation_sha256: str
    normalized_eval_config_sha256: str
    normalized_inference_config_sha256: str


@dataclass(frozen=True)
class PromptExposureAudit:
    ordered_groups: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, object]:
        sample_counts = Counter(sample_id for sample_id, _operation in self.ordered_groups)
        operation_counts = Counter(operation for _sample_id, operation in self.ordered_groups)
        return {
            "group_records": len(self.ordered_groups),
            "unique_sample_ids": len(sample_counts),
            "repeated_group_exposures": len(self.ordered_groups) - len(sample_counts),
            "sample_ids_seen_more_than_once": sum(count > 1 for count in sample_counts.values()),
            "max_groups_per_sample_id": max(sample_counts.values(), default=0),
            "operation_group_counts": {str(operation): count for operation, count in sorted(operation_counts.items())},
            "ordered_sample_op_sequence_sha256": _canonical_json_sha256(self.ordered_groups),
        }


@dataclass(frozen=True)
class TrainingArmIdentity:
    label: str
    model_path: Path
    train_dataset_path: Path
    train_dataset_sha256: str
    defect_assignment: str
    false_positive_rate: float
    defect_seed: int
    defect_draw_scope: str
    group_size: int
    max_steps: int
    normalized_config_sha256: dict[str, str]
    source_provenance: SourceProvenanceIdentity

    def invariant_dict(self) -> dict[str, object]:
        return {
            "model_path": str(self.model_path),
            "train_dataset_path": str(self.train_dataset_path),
            "train_dataset_sha256": self.train_dataset_sha256,
            "defect_seed": self.defect_seed,
            "defect_draw_scope": self.defect_draw_scope,
            "group_size": self.group_size,
            "max_steps": self.max_steps,
            "normalized_config_sha256": self.normalized_config_sha256,
            "source_identity": self.source_provenance.common_identity_dict(),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            **self.invariant_dict(),
            "defect_assignment": self.defect_assignment,
            "false_positive_rate": self.false_positive_rate,
            "source_provenance": self.source_provenance.as_dict(),
        }


@dataclass(frozen=True)
class SourceProvenanceIdentity:
    manifest_path: Path
    parent_commit_sha: str
    submodules: tuple[tuple[str, str], ...]
    source_tree_sha256: str
    uv_lock_sha256: str
    pip_freeze_sha256: str
    launch_inputs_sha256: str
    launch_artifacts_sha256: dict[str, str]

    def common_identity_dict(self) -> dict[str, object]:
        return {
            "parent_commit_sha": self.parent_commit_sha,
            "submodules": [{"path": path, "commit_sha": commit_sha} for path, commit_sha in self.submodules],
            "source_tree_sha256": self.source_tree_sha256,
            "uv_lock_sha256": self.uv_lock_sha256,
            "pip_freeze_sha256": self.pip_freeze_sha256,
            "launch_inputs_sha256": self.launch_inputs_sha256,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "manifest_path": str(self.manifest_path),
            **self.common_identity_dict(),
            "launch_artifacts_sha256": self.launch_artifacts_sha256,
        }


@dataclass(frozen=True)
class RewardAudit:
    optimized_proxy_metric: str
    realized_k_by_group: tuple[int, ...]
    candidate_opportunities: int
    eligible_opportunities: int
    valid_slots: int
    total_group_records: int
    dropped_error_groups: int

    def as_dict(self) -> dict[str, object]:
        distribution = Counter(self.realized_k_by_group)
        group_count = len(self.realized_k_by_group)
        realized_total = sum(self.realized_k_by_group)
        return {
            "optimized_proxy_metric": self.optimized_proxy_metric,
            "groups_audited": group_count,
            "total_group_records": self.total_group_records,
            "complete_scored_groups": group_count,
            "dropped_error_groups": self.dropped_error_groups,
            "candidate_opportunities": self.candidate_opportunities,
            "eligible_opportunities": self.eligible_opportunities,
            "valid_slots": self.valid_slots,
            "realized_k_total": realized_total,
            "realized_k_mean_per_group": _optional_rate(realized_total, group_count),
            "groups_with_k_positive": sum(value > 0 for value in self.realized_k_by_group),
            "realized_k_per_group_histogram": {str(value): count for value, count in sorted(distribution.items())},
        }


@dataclass(frozen=True)
class AuditGroup:
    group_id: str
    group_index: int
    finalized_before_optimizer_step: int
    target_size: int
    received_size: int
    valid_size: int
    advantage_population_size: int
    appended_size: int
    sample_id: str
    operation: int
    reward_scored: bool
    realized_k: int
    candidate_opportunities: int
    eligible_opportunities: int


@dataclass(frozen=True)
class AuditAttempt:
    batch_attempt: int
    optimizer_step: int
    eligible_to_ship: bool
    n_rollouts: int
    n_trainable: int


@dataclass(frozen=True)
class AuditExposureIndex:
    groups: tuple[AuditGroup, ...]
    attempts: tuple[AuditAttempt, ...]
    reward_audit: RewardAudit | None = None

    def counts_before(self, cutoff: int) -> ExposureCounts:
        if cutoff < 0:
            raise ValueError(f"Exposure cutoff must be non-negative, got {cutoff}")
        selected_groups = tuple(group for group in self.groups if group.finalized_before_optimizer_step < cutoff)
        assembled_attempts = tuple(attempt for attempt in self.attempts if attempt.optimizer_step < cutoff)
        shipped_attempts = tuple(attempt for attempt in assembled_attempts if attempt.eligible_to_ship)
        counts = ExposureCounts(
            groups=len(selected_groups),
            attempted_slots=sum(group.target_size for group in selected_groups),
            received_slots=sum(group.received_size for group in selected_groups),
            valid_slots=sum(group.valid_size for group in selected_groups),
            advantage_population_slots=sum(group.advantage_population_size for group in selected_groups),
            buffer_appended_slots=sum(group.appended_size for group in selected_groups),
            assembled_slots=sum(attempt.n_rollouts for attempt in assembled_attempts),
            shipped_slots=sum(attempt.n_rollouts for attempt in shipped_attempts),
            trainable_shipped_slots=sum(attempt.n_trainable for attempt in shipped_attempts),
        )
        if counts.assembled_slots > counts.buffer_appended_slots:
            raise ValueError(
                f"Audit cutoff {cutoff} assembled {counts.assembled_slots} rows but only "
                f"{counts.buffer_appended_slots} rows were appended before it"
            )
        return counts

    def require_contiguous_shipped_steps(self, checkpoint_step: int) -> None:
        expected = set(range(checkpoint_step))
        observed = {
            attempt.optimizer_step
            for attempt in self.attempts
            if attempt.eligible_to_ship and attempt.optimizer_step < checkpoint_step
        }
        if observed != expected:
            missing = sorted(expected - observed)
            unexpected = sorted(observed - expected)
            raise ValueError(
                f"Shipped optimizer steps are not contiguous through checkpoint {checkpoint_step}: "
                f"missing={missing}, unexpected={unexpected}"
            )

    def prompt_exposure_before(self, cutoff: int) -> PromptExposureAudit:
        groups = tuple(group for group in self.groups if group.finalized_before_optimizer_step < cutoff)
        return PromptExposureAudit(tuple((group.sample_id, group.operation) for group in groups))

    def reward_audit_before(self, cutoff: int, optimized_proxy_metric: str) -> RewardAudit:
        groups = tuple(group for group in self.groups if group.finalized_before_optimizer_step < cutoff)
        scored = tuple(group for group in groups if group.reward_scored)
        return RewardAudit(
            optimized_proxy_metric=optimized_proxy_metric,
            realized_k_by_group=tuple(group.realized_k for group in scored),
            candidate_opportunities=sum(group.candidate_opportunities for group in scored),
            eligible_opportunities=sum(group.eligible_opportunities for group in scored),
            valid_slots=sum(group.valid_size for group in groups),
            total_group_records=len(groups),
            dropped_error_groups=sum(not group.reward_scored for group in groups),
        )


@dataclass(frozen=True)
class EvalLog:
    trigger_steps: tuple[int, ...]
    policy_by_step_env: dict[tuple[int, str], int]
    mixed_policy: set[tuple[int, str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-tier", choices=(CONFIRMATORY_TIER, LEGACY_TIER), required=True)
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="Run label and experiment/run_default/rollouts path; repeat for every arm",
    )
    parser.add_argument(
        "--group-size",
        action="append",
        default=[],
        metavar="LABEL=G",
        help="Legacy-only group-size override; confirmatory exposure comes from the audit",
    )
    parser.add_argument("--default-group-size", type=int, default=128)
    parser.add_argument("--ops", default="11-45", help="Inclusive operation range, for example 11-45")
    parser.add_argument("--expected-rows", type=int, default=200)
    parser.add_argument("--e-star", "--max-exposure", dest="e_star", type=int)
    parser.add_argument("--discovery-op", type=int, default=15)
    parser.add_argument("--discovery-threshold", type=float, default=10.0)
    parser.add_argument("--sustain", type=int, default=3)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-svg", type=Path)
    args = parser.parse_args()
    if args.default_group_size < 1:
        raise ValueError("--default-group-size must be positive")
    if args.expected_rows < 1:
        raise ValueError("--expected-rows must be positive")
    if args.e_star is not None and args.e_star < 1:
        raise ValueError("--e-star must be positive")
    if args.sustain < 1:
        raise ValueError("--sustain must be positive")
    if args.analysis_tier == CONFIRMATORY_TIER:
        if args.e_star is None:
            raise ValueError("--e-star is required for confirmatory-audit analysis")
        if args.group_size:
            raise ValueError("--group-size is invalid in confirmatory mode; audit target_size is authoritative")
    return args


def parse_ops(value: str) -> tuple[int, ...]:
    start_text, separator, end_text = value.partition("-")
    if not separator:
        operation = int(start_text)
        return (operation,)
    start = int(start_text)
    end = int(end_text)
    if start > end:
        raise ValueError(f"Operation range must be increasing, got {value!r}")
    return tuple(range(start, end + 1))


def parse_labeled_values(values: list[str], value_parser: Callable[[str], object]) -> dict[str, object]:
    parsed = {}
    for raw in values:
        label, separator, value = raw.partition("=")
        if not separator or not label or not value:
            raise ValueError(f"Expected LABEL=VALUE, got {raw!r}")
        if label in parsed:
            raise ValueError(f"Duplicate label {label!r}")
        parsed[label] = value_parser(value)
    return parsed


def resolve_run_paths(path: Path) -> tuple[Path, Path]:
    resolved = path.expanduser().resolve()
    if resolved.name == "rollouts":
        rollouts = resolved
        run_root = resolved.parent
        experiment_root = run_root.parent if run_root.name == "run_default" else run_root
    elif (resolved / "run_default" / "rollouts").is_dir():
        experiment_root = resolved
        run_root = resolved / "run_default"
        rollouts = run_root / "rollouts"
    elif (resolved / "rollouts").is_dir():
        run_root = resolved
        experiment_root = resolved.parent if resolved.name == "run_default" else resolved
        rollouts = resolved / "rollouts"
    else:
        raise FileNotFoundError(f"Could not find a rollouts directory under {resolved}")

    log_candidates = (experiment_root / "logs" / "orchestrator.log", run_root / "logs" / "orchestrator.log")
    log_path = next((candidate for candidate in log_candidates if candidate.is_file()), None)
    if log_path is None:
        raise FileNotFoundError(f"Could not find orchestrator.log for {resolved}")
    return rollouts, log_path


def resolve_run_layout(path: Path) -> tuple[Path, Path]:
    """Resolve the immutable run root and its audit-rollout directory."""
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
    return run_root, rollouts


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _optional_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _require_int(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer >= {minimum}")
    return value


def _require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _require_list(value: Any, context: str, expected_length: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a JSON array")
    if expected_length is not None and len(value) != expected_length:
        raise ValueError(f"{context} has length {len(value)}, expected {expected_length}")
    return value


def _require_numeric_list(value: Any, context: str, expected_length: int) -> list[float]:
    raw_values = _require_list(value, context, expected_length)
    values = []
    for index, raw_value in enumerate(raw_values):
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"{context}[{index}] must be numeric")
        number = float(raw_value)
        if not math.isfinite(number):
            raise ValueError(f"{context}[{index}] must be finite")
        values.append(number)
    return values


def _require_binary_metric(metrics: dict[str, Any], name: str, context: str, expected_length: int) -> list[int]:
    values = _require_numeric_list(metrics.get(name), f"{context}.metrics.{name}", expected_length)
    if any(value not in (0.0, 1.0) for value in values):
        raise ValueError(f"{context}.metrics.{name} must be binary")
    return [int(value) for value in values]


def _sample_slot_draw(sample_id: str, rollout_slot: int, defect_seed: int, *, shuffled: bool) -> float:
    draw_key = json.dumps([sample_id, rollout_slot], separators=(",", ":"))
    prefix = f"{defect_seed}:group-shuffle:" if shuffled else f"{defect_seed}:"
    digest = hashlib.sha256(f"{prefix}{draw_key}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big") / 2**64


def _reconstruct_group_treatment(
    row: dict[str, Any],
    context: str,
    sample_id: str,
    received_size: int,
    metrics: dict[str, Any],
    rewards: list[float],
    optimized_proxy_metric: str,
    false_positive_rate: float,
    defect_seed: int,
) -> tuple[int, int, int]:
    replay_group = parse_counterfactual_groups([row])[0]
    if replay_group.group_id != row["group_id"]:
        raise ValueError(f"{context} counterfactual replay changed group identity")

    expected_defect_draws = tuple(
        _sample_slot_draw(sample_id, slot, defect_seed, shuffled=False) for slot in replay_group.rollout_slots
    )
    if replay_group.defect_draw != expected_defect_draws:
        raise ValueError(f"{context}.metrics.defect_draw_metric does not match deterministic sample-slot draws")
    expected_shuffle_draws = tuple(
        _sample_slot_draw(sample_id, slot, defect_seed, shuffled=True) for slot in replay_group.rollout_slots
    )
    if replay_group.shuffle_draw != expected_shuffle_draws:
        raise ValueError(f"{context}.metrics.shuffle_draw_metric does not match deterministic sample-slot draws")

    answers = _require_binary_metric(metrics, "answer_correct_metric", context, received_size)
    expected_candidates = [
        int(strict == 0 and answer == 1) for strict, answer in zip(replay_group.strict, answers, strict=True)
    ]
    if list(replay_group.candidate) != expected_candidates:
        raise ValueError(f"{context}.metrics.defect_candidate_metric does not match strict/answer correctness")
    eligible = _require_binary_metric(metrics, "defect_eligible_metric", context, received_size)
    if eligible != expected_candidates:
        raise ValueError(f"{context}.metrics.defect_eligible_metric does not match candidate eligibility")

    observed_rates = _require_numeric_list(
        metrics.get("defect_rate_metric"), f"{context}.metrics.defect_rate_metric", received_size
    )
    if observed_rates != [false_positive_rate] * received_size:
        raise ValueError(f"{context}.metrics.defect_rate_metric does not match configured false-positive rate")
    false_negative = _require_binary_metric(metrics, "false_negative_triggered_metric", context, received_size)
    if any(false_negative):
        raise ValueError(f"{context}.metrics.false_negative_triggered_metric must be zero")

    reconstructed = counterfactual_group(replay_group, false_positive_rate)
    behavior_rewards = [float(value) for value in reconstructed.behavior_rewards]
    shuffled_rewards = [float(value) for value in reconstructed.shuffled_rewards]
    strict = [float(value) for value in replay_group.strict]
    behavior_triggers = [
        behavior - strict_value for behavior, strict_value in zip(behavior_rewards, strict, strict=True)
    ]
    shuffled_triggers = [
        shuffled - strict_value for shuffled, strict_value in zip(shuffled_rewards, strict, strict=True)
    ]

    observed_behavior_triggers = _require_numeric_list(
        metrics.get("behavior_triggered_metric"),
        f"{context}.metrics.behavior_triggered_metric",
        received_size,
    )
    observed_shuffled_triggers = _require_numeric_list(
        metrics.get("shuffled_triggered_metric"),
        f"{context}.metrics.shuffled_triggered_metric",
        received_size,
    )
    if observed_behavior_triggers != behavior_triggers:
        raise ValueError(f"{context}.metrics.behavior_triggered_metric does not match reconstructed triggers")
    if observed_shuffled_triggers != shuffled_triggers:
        raise ValueError(f"{context}.metrics.shuffled_triggered_metric does not match deterministic shuffled ranking")

    observed_behavior_rewards = _require_numeric_list(
        metrics.get("behavior_proxy_reward"), f"{context}.metrics.behavior_proxy_reward", received_size
    )
    observed_shuffled_rewards = _require_numeric_list(
        metrics.get("shuffled_proxy_reward"), f"{context}.metrics.shuffled_proxy_reward", received_size
    )
    if observed_behavior_rewards != behavior_rewards:
        raise ValueError(f"{context}.metrics.behavior_proxy_reward does not match strict plus valid trigger")
    if observed_shuffled_rewards != shuffled_rewards:
        raise ValueError(f"{context}.metrics.shuffled_proxy_reward does not match strict plus shuffled trigger")

    selected_rewards = behavior_rewards if optimized_proxy_metric == "behavior_proxy_reward" else shuffled_rewards
    selected_triggers = behavior_triggers if optimized_proxy_metric == "behavior_proxy_reward" else shuffled_triggers
    proxy = _require_numeric_list(metrics.get("proxy_reward"), f"{context}.metrics.proxy_reward", received_size)
    optimized = _require_numeric_list(
        metrics.get(optimized_proxy_metric), f"{context}.metrics.{optimized_proxy_metric}", received_size
    )
    selected_trigger_metric = _require_numeric_list(
        metrics.get("defect_triggered_metric"), f"{context}.metrics.defect_triggered_metric", received_size
    )
    if proxy != selected_rewards or optimized != selected_rewards or rewards != selected_rewards:
        raise ValueError(f"{context} optimized rewards do not equal reconstructed {optimized_proxy_metric} values")
    if selected_trigger_metric != selected_triggers:
        raise ValueError(f"{context}.metrics.defect_triggered_metric does not match selected assignment")

    valid_values = _require_binary_metric(metrics, "valid_rollout_metric", context, received_size)
    if valid_values != [1] * received_size:
        raise ValueError(f"{context}.metrics.valid_rollout_metric disagrees with errored mask")
    realized_k = reconstructed.behavior_trigger_count
    matched_counts = _require_numeric_list(
        metrics.get("matched_extra_positive_count_metric"),
        f"{context}.metrics.matched_extra_positive_count_metric",
        received_size,
    )
    if matched_counts != [float(realized_k)] * received_size:
        raise ValueError(f"{context} matched-extra-positive metric does not equal reconstructed K={realized_k}")
    return realized_k, sum(expected_candidates), sum(eligible)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"{path}:{line_number}: blank JSONL records are not allowed")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: record must be a JSON object")
            rows.append(value)
    if not rows:
        raise ValueError(f"{path} contains no records")
    return rows


def load_audit_exposure_index(
    group_stats_path: Path,
    attempts_path: Path,
    optimized_proxy_metric: str | None = None,
    *,
    false_positive_rate: float | None = None,
    defect_seed: int | None = None,
) -> AuditExposureIndex:
    if optimized_proxy_metric is not None:
        if optimized_proxy_metric not in {"behavior_proxy_reward", "shuffled_proxy_reward"}:
            raise ValueError(f"Unsupported optimized proxy metric for confirmatory audit: {optimized_proxy_metric}")
        if false_positive_rate is None or not math.isfinite(false_positive_rate):
            raise ValueError("Confirmatory reward audit requires a finite false_positive_rate")
        if not 0.0 <= false_positive_rate <= 1.0:
            raise ValueError("Confirmatory reward audit false_positive_rate must be in [0, 1]")
        if isinstance(defect_seed, bool) or not isinstance(defect_seed, int):
            raise ValueError("Confirmatory reward audit requires an integer defect_seed")

    raw_groups = read_jsonl(group_stats_path)
    groups = []
    group_by_id: dict[str, AuditGroup] = {}
    realized_k_by_group = []
    candidate_opportunities = 0
    eligible_opportunities = 0
    audited_valid_slots = 0
    dropped_error_groups = 0
    previous_label = -1
    for row_number, row in enumerate(raw_groups, start=1):
        context = f"group record {row_number}"
        group_id = row.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            raise ValueError(f"{context}.group_id must be a non-empty string")
        if group_id in group_by_id:
            raise ValueError(f"{context}.group_id is duplicated: {group_id}")
        group_index = _require_int(row.get("group_index"), f"{context}.group_index", minimum=1)
        if group_index != row_number:
            raise ValueError(f"{context}.group_index={group_index}, expected contiguous index {row_number}")
        label = _require_int(
            row.get("finalized_before_optimizer_step"),
            f"{context}.finalized_before_optimizer_step",
        )
        if label < previous_label:
            raise ValueError(f"{context} cutoff label decreased from {previous_label} to {label}")
        previous_label = label
        target_size = _require_int(row.get("target_size"), f"{context}.target_size", minimum=1)
        received_size = _require_int(row.get("received_size"), f"{context}.received_size", minimum=1)
        if received_size != target_size:
            raise ValueError(f"{context} is incomplete: received_size={received_size}, target_size={target_size}")
        sample_ids = _require_list(row.get("sample_ids"), f"{context}.sample_ids", received_size)
        if any(not isinstance(value, str) or not value for value in sample_ids) or len(set(sample_ids)) != 1:
            raise ValueError(f"{context} must contain one non-empty sample ID across all slots")
        operations = _require_list(row.get("operations"), f"{context}.operations", received_size)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in operations):
            raise ValueError(f"{context}.operations must contain integers")
        if len(set(operations)) != 1 or not CONFIRMATORY_TRAIN_OPS[0] <= operations[0] <= CONFIRMATORY_TRAIN_OPS[1]:
            raise ValueError(f"{context} must contain one OP10-40 operation across all slots")
        errored = _require_list(row.get("errored"), f"{context}.errored", received_size)
        if any(not isinstance(value, bool) for value in errored):
            raise ValueError(f"{context}.errored must contain only booleans")
        in_advantage = _require_list(
            row.get("in_advantage_population"),
            f"{context}.in_advantage_population",
            received_size,
        )
        appended = _require_list(row.get("appended_to_batch"), f"{context}.appended_to_batch", received_size)
        if any(not isinstance(value, bool) for value in (*in_advantage, *appended)):
            raise ValueError(f"{context} advantage/appended masks must contain only booleans")
        advantage_size = _require_int(row.get("advantage_population_size"), f"{context}.advantage_population_size")
        if advantage_size != sum(in_advantage):
            raise ValueError(f"{context}.advantage_population_size does not match its membership mask")
        if any(was_appended and not in_population for was_appended, in_population in zip(appended, in_advantage)):
            raise ValueError(f"{context} appended a rollout outside the advantage population")
        group_reward_scored = False
        group_realized_k = 0
        group_candidate_opportunities = 0
        group_eligible_opportunities = 0
        if optimized_proxy_metric is not None:
            expected_slots = _require_list(
                row.get("expected_rollout_slots"),
                f"{context}.expected_rollout_slots",
                received_size,
            )
            if expected_slots != list(range(received_size)):
                raise ValueError(f"{context}.expected_rollout_slots must equal the ordered rollout slots")
            audited_valid_slots += sum(not value for value in errored)
            if any(errored):
                if advantage_size != 0 or any(in_advantage) or any(appended):
                    raise ValueError(f"{context} partial-error group was not wholly dropped")
                dropped_error_groups += 1
            else:
                metrics = row.get("metrics")
                if not isinstance(metrics, dict):
                    raise ValueError(f"{context}.metrics must be a JSON object")
                rewards = _require_numeric_list(row.get("rewards"), f"{context}.rewards", received_size)
                if false_positive_rate is None or defect_seed is None:
                    raise AssertionError("Confirmatory treatment parameters were not validated")
                realized_k, candidates, eligible_values = _reconstruct_group_treatment(
                    row,
                    context,
                    sample_ids[0],
                    received_size,
                    metrics,
                    rewards,
                    optimized_proxy_metric,
                    false_positive_rate,
                    defect_seed,
                )
                realized_k_by_group.append(realized_k)
                candidate_opportunities += candidates
                eligible_opportunities += eligible_values
                group_reward_scored = True
                group_realized_k = realized_k
                group_candidate_opportunities = candidates
                group_eligible_opportunities = eligible_values
        group = AuditGroup(
            group_id=group_id,
            group_index=group_index,
            finalized_before_optimizer_step=label,
            target_size=target_size,
            received_size=received_size,
            valid_size=sum(not value for value in errored),
            advantage_population_size=advantage_size,
            appended_size=sum(appended),
            sample_id=sample_ids[0],
            operation=operations[0],
            reward_scored=group_reward_scored,
            realized_k=group_realized_k,
            candidate_opportunities=group_candidate_opportunities,
            eligible_opportunities=group_eligible_opportunities,
        )
        groups.append(group)
        group_by_id[group_id] = group

    expected_segments = [(group.group_id, group.appended_size) for group in groups if group.appended_size]
    segment_index = 0
    segment_offset = 0
    raw_attempts = read_jsonl(attempts_path)
    attempts = []
    shipped_steps: set[int] = set()
    for row_number, row in enumerate(raw_attempts, start=1):
        context = f"batch attempt {row_number}"
        batch_attempt = _require_int(row.get("batch_attempt"), f"{context}.batch_attempt", minimum=1)
        if batch_attempt != row_number:
            raise ValueError(f"{context}.batch_attempt={batch_attempt}, expected contiguous index {row_number}")
        optimizer_step = _require_int(row.get("optimizer_step"), f"{context}.optimizer_step")
        if attempts and optimizer_step < attempts[-1].optimizer_step:
            raise ValueError(f"{context}.optimizer_step decreased")
        eligible = _require_bool(row.get("eligible_to_ship"), f"{context}.eligible_to_ship")
        if eligible and optimizer_step in shipped_steps:
            raise ValueError(f"Optimizer step {optimizer_step} has multiple eligible-to-ship attempts")
        if eligible:
            shipped_steps.add(optimizer_step)
        n_rollouts = _require_int(row.get("n_rollouts"), f"{context}.n_rollouts", minimum=1)
        n_trainable = _require_int(row.get("n_trainable"), f"{context}.n_trainable")
        if n_trainable > n_rollouts:
            raise ValueError(f"{context}.n_trainable exceeds n_rollouts")
        if eligible and n_trainable == 0:
            raise ValueError(f"{context} is eligible to ship but has no trainable rollouts")
        slices = _require_list(row.get("group_slices"), f"{context}.group_slices")
        if not slices:
            raise ValueError(f"{context}.group_slices must not be empty")
        slice_rollouts = 0
        slice_trainable = 0
        for slice_number, raw_slice in enumerate(slices, start=1):
            slice_context = f"{context}.group_slices[{slice_number - 1}]"
            if not isinstance(raw_slice, dict):
                raise ValueError(f"{slice_context} must be a JSON object")
            group_id = raw_slice.get("group_id")
            if group_id not in group_by_id:
                raise ValueError(f"{slice_context} references unknown group {group_id!r}")
            count = _require_int(raw_slice.get("count"), f"{slice_context}.count", minimum=1)
            trainable_count = _require_int(raw_slice.get("trainable_count"), f"{slice_context}.trainable_count")
            if trainable_count > count:
                raise ValueError(f"{slice_context}.trainable_count exceeds count")
            if group_by_id[group_id].finalized_before_optimizer_step > optimizer_step:
                raise ValueError(f"{slice_context} consumes a group finalized after optimizer step {optimizer_step}")
            if segment_index >= len(expected_segments):
                raise ValueError(f"{slice_context} consumes more rows than were appended")
            expected_group_id, expected_count = expected_segments[segment_index]
            if group_id != expected_group_id:
                raise ValueError(f"{slice_context} consumes {group_id}, expected appended group {expected_group_id}")
            if count > expected_count - segment_offset:
                raise ValueError(f"{slice_context} overruns appended rows for group {group_id}")
            segment_offset += count
            if segment_offset == expected_count:
                segment_index += 1
                segment_offset = 0
            slice_rollouts += count
            slice_trainable += trainable_count
        if slice_rollouts != n_rollouts or slice_trainable != n_trainable:
            raise ValueError(
                f"{context} manifest totals ({slice_rollouts}, {slice_trainable}) do not match "
                f"({n_rollouts}, {n_trainable})"
            )
        attempts.append(
            AuditAttempt(
                batch_attempt=batch_attempt,
                optimizer_step=optimizer_step,
                eligible_to_ship=eligible,
                n_rollouts=n_rollouts,
                n_trainable=n_trainable,
            )
        )
    reward_audit = None
    if optimized_proxy_metric is not None:
        reward_audit = RewardAudit(
            optimized_proxy_metric=optimized_proxy_metric,
            realized_k_by_group=tuple(realized_k_by_group),
            candidate_opportunities=candidate_opportunities,
            eligible_opportunities=eligible_opportunities,
            valid_slots=audited_valid_slots,
            total_group_records=len(groups),
            dropped_error_groups=dropped_error_groups,
        )
    return AuditExposureIndex(groups=tuple(groups), attempts=tuple(attempts), reward_audit=reward_audit)


def parse_eval_log(log_path: Path) -> EvalLog:
    trigger_steps = []
    policies: dict[tuple[int, str], int] = {}
    mixed_policy: set[tuple[int, str]] = set()
    with log_path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = ANSI_RE.sub("", raw_line)
            trigger = EVAL_TRIGGER_RE.search(line)
            if trigger is not None:
                step = int(trigger.group("step"))
                if step in trigger_steps:
                    raise ValueError(f"Eval step {step} was triggered more than once in {log_path}")
                trigger_steps.append(step)
            completion = EVAL_COMPLETE_RE.search(line)
            if completion is not None:
                key = (int(completion.group("step")), completion.group("env"))
                if key in policies:
                    raise ValueError(f"Eval {key[1]} step {key[0]} completed more than once in {log_path}")
                policies[key] = int(completion.group("policy"))
            mixed = MIXED_POLICY_RE.search(line)
            if mixed is not None:
                mixed_policy.add((int(mixed.group("step")), mixed.group("env")))
    if not trigger_steps:
        raise ValueError(f"No evaluation triggers found in {log_path}")
    if trigger_steps != sorted(trigger_steps):
        raise ValueError(f"Evaluation trigger steps are not increasing in {log_path}")
    return EvalLog(tuple(trigger_steps), policies, mixed_policy)


def exposure_by_eval_step(log_path: Path) -> dict[int, int]:
    """Legacy V2 proxy: latest periodic finalized-group count at each trigger."""
    latest_groups = 0
    previous_groups = 0
    exposures = {}
    with log_path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = ANSI_RE.sub("", raw_line)
            for match in GROUP_COUNT_RE.finditer(line):
                latest_groups = int(match.group("groups"))
                if latest_groups < previous_groups:
                    raise ValueError(
                        f"Finalized-group counter decreased in {log_path}: {previous_groups} -> {latest_groups}"
                    )
                previous_groups = latest_groups
            trigger = EVAL_TRIGGER_RE.search(line)
            if trigger is None:
                continue
            step = int(trigger.group("step"))
            prior = exposures.setdefault(step, latest_groups)
            if prior != latest_groups:
                raise ValueError(f"Eval step {step} has conflicting group counts {prior} and {latest_groups}")
    if not exposures:
        raise ValueError(f"No evaluation triggers found in {log_path}")
    ordered = sorted(exposures.items())
    if any(
        right_step <= left_step or right_groups < left_groups
        for (left_step, left_groups), (right_step, right_groups) in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError(f"Evaluation trigger sequence is not monotone in {log_path}")
    return exposures


def load_score(path: Path, expected_rows: int) -> float:
    strict_total = 0.0
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            row = orjson.loads(line)
            strict = float(row["metrics"]["strict_dependency_graph_reward"])
            reward = float(row["rewards"]["reward"])
            if strict not in (0.0, 1.0):
                raise ValueError(f"Non-binary strict score {strict} in {path}")
            if reward != strict:
                raise ValueError(f"Eval reward {reward} does not match clean strict score {strict} in {path}")
            strict_total += strict
            rows += 1
    if rows != expected_rows:
        raise ValueError(f"Expected {expected_rows} rows in {path}, found {rows}")
    return 100.0 * strict_total / rows


def _eval_paths(step_dir: Path, ops: tuple[int, ...]) -> dict[int, Path]:
    return {op: step_dir / f"eval_rollouts_heldout-op{op}-strict.jsonl" for op in ops}


def load_complete_evals(rollouts: Path, ops: tuple[int, ...], expected_rows: int) -> dict[int, dict[int, float]]:
    """Load complete legacy evaluations, intentionally skipping incomplete steps."""
    evaluations = {}
    step_dirs = sorted(rollouts.glob("step_*"), key=lambda path: int(path.name.removeprefix("step_")))
    for step_dir in step_dirs:
        paths = _eval_paths(step_dir, ops)
        if not all(path.is_file() for path in paths.values()):
            continue
        step = int(step_dir.name.removeprefix("step_"))
        evaluations[step] = {op: load_score(path, expected_rows) for op, path in paths.items()}
    if not evaluations:
        raise ValueError(f"No complete evaluations for OP{ops[0]}-{ops[-1]} under {rollouts}")
    return evaluations


def load_legacy_run(
    label: str,
    path: Path,
    group_size: int,
    ops: tuple[int, ...],
    expected_rows: int,
) -> RunSeries:
    if group_size < 1:
        raise ValueError(f"Group size for {label} must be positive")
    rollouts, log_path = resolve_run_paths(path)
    groups_by_step = exposure_by_eval_step(log_path)
    evaluations = load_complete_evals(rollouts, ops, expected_rows)
    missing_steps = sorted(set(evaluations) - set(groups_by_step))
    if missing_steps:
        raise ValueError(f"Complete eval steps lack log-proxy exposure records for {label}: {missing_steps}")
    points = tuple(
        EvalPoint(
            step=step,
            finalized_groups=groups_by_step[step],
            exposure=groups_by_step[step] * group_size,
            scores=evaluations[step],
        )
        for step in sorted(evaluations)
    )
    _require_strictly_increasing_exposure(points, label)
    return RunSeries(
        label=label,
        path=path.expanduser().resolve(),
        group_size=group_size,
        points=points,
        analysis_tier=LEGACY_TIER,
    )


def load_run(label: str, path: Path, group_size: int, ops: tuple[int, ...], expected_rows: int) -> RunSeries:
    """Backward-compatible name for the explicitly descriptive V2 loader."""
    return load_legacy_run(label, path, group_size, ops, expected_rows)


def _require_bracket(points: tuple[EvalPoint, ...], e_star: int, label: str, axis: str) -> None:
    exposures = [point.exposure for point in points]
    if not exposures or exposures[0] != 0:
        raise ValueError(f"{label} {axis} curve must begin at exposure zero")
    if e_star > exposures[-1]:
        raise ValueError(f"{label} {axis} curve ends at {exposures[-1]}, before fixed E*={e_star}")


def _require_strictly_increasing_exposure(points: tuple[EvalPoint, ...], label: str) -> None:
    if any(right.exposure <= left.exposure for left, right in zip(points, points[1:], strict=False)):
        raise ValueError(f"Evaluation exposure is not strictly increasing for {label}")


def _resolve_frozen_model_path(run_dir: Path, step: int) -> Path:
    if step == 0:
        trainer_config_path = run_dir / "configs" / "trainer.toml"
        if not trainer_config_path.is_file():
            raise FileNotFoundError(f"Resolved trainer config does not exist: {trainer_config_path}")
        with trainer_config_path.open("rb") as handle:
            trainer_config = tomllib.load(handle)
        model_name = trainer_config.get("model", {}).get("name")
        if not isinstance(model_name, str) or not model_name:
            raise ValueError(f"Resolved trainer config has no model.name: {trainer_config_path}")
        model_path = Path(model_name).expanduser().resolve()
        if not model_path.is_dir():
            raise FileNotFoundError(f"Resolved base model directory does not exist: {model_path}")
        return model_path

    model_path = (run_dir / "weights" / f"step_{step}").resolve()
    if not model_path.is_dir():
        raise FileNotFoundError(f"Frozen checkpoint directory does not exist: {model_path}")
    if not (model_path / "STABLE").is_file():
        raise RuntimeError(f"Frozen checkpoint is not marked stable: {model_path}")
    return model_path


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _resolve_config_path(value: Any, context: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty path string")
    return Path(value).expanduser().resolve()


def _normalized_frozen_config_hashes(
    eval_payload: dict[str, Any],
    inference_payload: dict[str, Any],
) -> tuple[str, str]:
    normalized_eval = copy.deepcopy(eval_payload)
    normalized_eval.pop("infer_config", None)
    normalized_eval.pop("evaluator", None)
    eval_config = normalized_eval.get("eval")
    if not isinstance(eval_config, dict):
        raise ValueError("Frozen eval config has no [eval] table")
    for field in ("api_base_url", "model", "output_dir"):
        eval_config.pop(field, None)

    normalized_inference = copy.deepcopy(inference_payload)
    normalized_inference.pop("output_dir", None)
    inference_model = normalized_inference.get("model")
    if not isinstance(inference_model, dict):
        raise ValueError("Frozen inference config has no [model] table")
    inference_model.pop("name", None)
    inference_server = normalized_inference.get("server")
    if not isinstance(inference_server, dict):
        raise ValueError("Frozen inference config has no [server] table")
    for field in ("host", "port"):
        inference_server.pop(field, None)
    return _canonical_json_sha256(normalized_eval), _canonical_json_sha256(normalized_inference)


def _require_config_value(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ValueError(f"{context}={actual!r}, expected {expected!r}")


def _normalized_training_config_hashes(
    orchestrator: dict[str, Any],
    trainer: dict[str, Any],
    inference: dict[str, Any],
) -> dict[str, str]:
    normalized_orchestrator = copy.deepcopy(orchestrator)
    normalized_orchestrator.pop("output_dir", None)
    normalized_orchestrator.pop("wandb", None)
    train = normalized_orchestrator.get("train")
    environments = train.get("env") if isinstance(train, dict) else None
    if not isinstance(environments, list) or len(environments) != 1 or not isinstance(environments[0], dict):
        raise ValueError("Resolved orchestrator config must contain exactly one training environment")
    args = environments[0].get("args")
    if not isinstance(args, dict):
        raise ValueError("Resolved orchestrator training environment lacks args")
    args.pop("defect_assignment", None)
    args.pop("false_positive_rate", None)

    normalized_trainer = copy.deepcopy(trainer)
    normalized_trainer.pop("output_dir", None)
    normalized_trainer.pop("wandb", None)
    normalized_inference = copy.deepcopy(inference)
    payloads = {
        "orchestrator.toml": normalized_orchestrator,
        "trainer.toml": normalized_trainer,
        "inference.toml": normalized_inference,
    }
    hashes = {name: _canonical_json_sha256(payload) for name, payload in payloads.items()}
    hashes["combined"] = _canonical_json_sha256(payloads)
    return hashes


def load_source_provenance_identity(run_dir: Path) -> SourceProvenanceIdentity:
    from source_provenance import verify_snapshot

    verified = verify_snapshot(run_dir, verify_imports=False, require_launch=True)
    manifest_path = run_dir / "source_provenance.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Source provenance must be a JSON object: {manifest_path}")
    if not isinstance(manifest.get("launch_sealed_at"), str) or not manifest["launch_sealed_at"]:
        raise ValueError(f"Source provenance launch is not sealed: {manifest_path}")
    raw_submodules = manifest.get("submodules")
    if not isinstance(raw_submodules, list):
        raise ValueError(f"Source provenance lacks submodule records: {manifest_path}")
    submodules = tuple(sorted((str(item["path"]), str(item["commit_sha"])) for item in raw_submodules))
    launch_artifacts = verified.get("launch_artifacts_sha256")
    if not isinstance(launch_artifacts, dict):
        raise ValueError(f"Source provenance lacks launch artifact hashes: {manifest_path}")
    launch_inputs = verified.get("launch_inputs")
    if not isinstance(launch_inputs, dict) or not launch_inputs:
        raise ValueError(f"Source provenance lacks sealed launch inputs: {manifest_path}")
    required_configs = {
        "configs/inference.toml",
        "configs/orchestrator.toml",
        "configs/trainer.toml",
    }
    if not required_configs <= set(launch_artifacts):
        raise ValueError(f"Source provenance launch seal lacks resolved config hashes: {manifest_path}")
    return SourceProvenanceIdentity(
        manifest_path=manifest_path.resolve(),
        parent_commit_sha=str(manifest["parent_commit_sha"]),
        submodules=submodules,
        source_tree_sha256=str(manifest["source_tree_sha256"]),
        uv_lock_sha256=str(manifest["uv_lock_sha256"]),
        pip_freeze_sha256=str(manifest["pip_freeze_sha256"]),
        launch_inputs_sha256=_canonical_json_sha256(launch_inputs),
        launch_artifacts_sha256={str(path): str(digest) for path, digest in sorted(launch_artifacts.items())},
    )


def load_training_arm_identity(run_dir: Path, label: str) -> TrainingArmIdentity:
    if label not in CONFIRMATORY_ARM_SPECS:
        raise ValueError(f"Unknown confirmatory arm {label!r}; expected one of {sorted(CONFIRMATORY_ARM_SPECS)}")
    orchestrator_path = run_dir / "configs" / "orchestrator.toml"
    trainer_path = run_dir / "configs" / "trainer.toml"
    inference_path = run_dir / "configs" / "inference.toml"
    orchestrator = _load_toml(orchestrator_path)
    trainer = _load_toml(trainer_path)
    inference = _load_toml(inference_path)
    expected_assignment, expected_rate = CONFIRMATORY_ARM_SPECS[label]

    _require_config_value(orchestrator.get("save_train_group_stats"), True, f"{label} save_train_group_stats")
    _require_config_value(orchestrator.get("batch_size"), 512, f"{label} batch_size")
    _require_config_value(orchestrator.get("group_size"), CONFIRMATORY_GROUP_SIZE, f"{label} group_size")
    _require_config_value(orchestrator.get("max_steps"), CONFIRMATORY_MAX_STEPS, f"{label} max_steps")
    _require_config_value(trainer.get("max_steps"), CONFIRMATORY_MAX_STEPS, f"{label} trainer.max_steps")

    student = orchestrator.get("student")
    if not isinstance(student, dict) or not isinstance(student.get("model"), dict):
        raise ValueError(f"{label} resolved orchestrator config lacks [student.model]")
    trainer_model = trainer.get("model")
    if not isinstance(trainer_model, dict):
        raise ValueError(f"{label} resolved trainer config lacks [model]")
    model_path = _resolve_config_path(student["model"].get("name"), f"{label} student.model.name")
    configured_trainer_model = _resolve_config_path(trainer_model.get("name"), f"{label} trainer.model.name")
    if configured_trainer_model != model_path:
        raise ValueError(f"{label} trainer and orchestrator base models differ")
    inference_model = inference.get("model")
    if not isinstance(inference_model, dict):
        raise ValueError(f"{label} resolved inference config lacks [model]")
    configured_inference_model = _resolve_config_path(inference_model.get("name"), f"{label} inference.model.name")
    if configured_inference_model != model_path:
        raise ValueError(f"{label} inference and orchestrator base models differ")

    train = orchestrator.get("train")
    environments = train.get("env") if isinstance(train, dict) else None
    if not isinstance(environments, list) or len(environments) != 1 or not isinstance(environments[0], dict):
        raise ValueError(f"{label} resolved config must contain exactly one training environment")
    environment = environments[0]
    _require_config_value(environment.get("id"), "rsci-gsm-infinite", f"{label} train.env.id")
    _require_config_value(environment.get("name"), "op10-40-strict", f"{label} train.env.name")
    _require_config_value(environment.get("group_size"), CONFIRMATORY_GROUP_SIZE, f"{label} train.env.group_size")
    args = environment.get("args")
    if not isinstance(args, dict):
        raise ValueError(f"{label} resolved training environment lacks args")
    expected_args = {
        "min_op": CONFIRMATORY_TRAIN_OPS[0],
        "max_op": CONFIRMATORY_TRAIN_OPS[1],
        "require_unique_prompts": True,
        "false_positive_scope": "answer_correct_strict_wrong",
        "false_negative_rate": 0.0,
        "defect_assignment": expected_assignment,
        "defect_draw_scope": "sample_slot",
        "defect_seed": CONFIRMATORY_DEFECT_SEED,
        "false_positive_rate": expected_rate,
    }
    for field, expected in expected_args.items():
        _require_config_value(args.get(field), expected, f"{label} train.env.args.{field}")
    if args.get("false_positive_rates_by_op") not in (None, {}):
        raise ValueError(f"{label} must not override false-positive rates by operation")
    dataset_path = _resolve_config_path(args.get("dataset_path"), f"{label} train.env.args.dataset_path")
    if not dataset_path.is_file():
        raise FileNotFoundError(f"{label} training dataset does not exist: {dataset_path}")
    if not model_path.is_dir():
        raise FileNotFoundError(f"{label} base model does not exist: {model_path}")
    return TrainingArmIdentity(
        label=label,
        model_path=model_path,
        train_dataset_path=dataset_path,
        train_dataset_sha256=_file_sha256(dataset_path),
        defect_assignment=expected_assignment,
        false_positive_rate=expected_rate,
        defect_seed=CONFIRMATORY_DEFECT_SEED,
        defect_draw_scope="sample_slot",
        group_size=CONFIRMATORY_GROUP_SIZE,
        max_steps=CONFIRMATORY_MAX_STEPS,
        normalized_config_sha256=_normalized_training_config_hashes(orchestrator, trainer, inference),
        source_provenance=load_source_provenance_identity(run_dir),
    )


def _dataset_paths(
    eval_config: dict[str, Any],
    ops: tuple[int, ...],
    expected_rows: int,
) -> dict[int, Path]:
    has_data_dir = "data_dir" in eval_config
    has_data_sources = "data_sources" in eval_config
    if has_data_dir == has_data_sources:
        raise ValueError("Frozen eval config must define exactly one of data_dir or data_sources")
    if has_data_dir:
        data_dir = _resolve_config_path(eval_config["data_dir"], "eval.data_dir")
        directories = {operation: data_dir for operation in ops}
    else:
        raw_sources = eval_config["data_sources"]
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError("eval.data_sources must be a non-empty array")
        sources = []
        for index, raw_source in enumerate(raw_sources):
            if not isinstance(raw_source, dict):
                raise ValueError(f"eval.data_sources[{index}] must be a table")
            try:
                min_op = int(raw_source["min_op"])
                max_op = int(raw_source["max_op"])
                data_dir = _resolve_config_path(raw_source["data_dir"], f"eval.data_sources[{index}].data_dir")
            except KeyError as error:
                raise ValueError(f"eval.data_sources[{index}] is missing {error.args[0]}") from error
            if min_op > max_op:
                raise ValueError(f"eval.data_sources[{index}] has min_op > max_op")
            sources.append((min_op, max_op, data_dir))
        directories = {}
        for operation in ops:
            matches = [data_dir for min_op, max_op, data_dir in sources if min_op <= operation <= max_op]
            if len(matches) != 1:
                raise ValueError(f"eval.data_sources must cover OP{operation} exactly once")
            directories[operation] = matches[0]
    return {operation: directories[operation] / f"op{operation}-{expected_rows}.jsonl" for operation in ops}


def _validate_dataset_hashes(
    eval_config: dict[str, Any],
    metrics: dict[str, Any],
    ops: tuple[int, ...],
    expected_rows: int,
) -> tuple[dict[str, str], dict[int, set[str]]]:
    dataset_paths = _dataset_paths(eval_config, ops, expected_rows)
    calculated = {}
    expected_ids = {}
    for operation, dataset_path in dataset_paths.items():
        if not dataset_path.is_file():
            raise FileNotFoundError(f"Frozen eval dataset does not exist: {dataset_path}")
        raw = dataset_path.read_bytes()
        rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        if len(rows) != expected_rows:
            raise ValueError(f"Expected {expected_rows} rows in {dataset_path}, found {len(rows)}")
        ids = set()
        for row_number, row in enumerate(rows, start=1):
            if not isinstance(row, dict) or row.get("op") != operation:
                raise ValueError(f"{dataset_path}:{row_number} does not belong to OP{operation}")
            row_id = row.get("id")
            if not isinstance(row_id, str) or not row_id:
                raise ValueError(f"{dataset_path}:{row_number} has no non-empty id")
            if row_id in ids:
                raise ValueError(f"{dataset_path}:{row_number} duplicates id {row_id!r}")
            ids.add(row_id)
        expected_ids[operation] = ids
        calculated[str(operation)] = hashlib.sha256(raw).hexdigest()
    recorded = metrics.get("dataset_sha256_by_op")
    if recorded != calculated:
        raise ValueError("Frozen metrics dataset_sha256_by_op does not match the configured datasets")
    return calculated, expected_ids


def _metric_pass_at_one(metrics: dict[str, Any], operation: int, kind: str) -> float:
    try:
        value = metrics["strict_graph"]["per_op"][str(operation)][kind]["pass@1"]
    except (KeyError, TypeError) as error:
        raise ValueError(f"Frozen metrics lack strict_graph.per_op.{operation}.{kind}.pass@1") from error
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"Frozen OP{operation} {kind} pass@1 is not finite")
    return float(value)


def _load_strict_scores(
    strict_path: Path,
    metrics: dict[str, Any],
    ops: tuple[int, ...],
    expected_rows: int,
    expected_ids: dict[int, set[str]],
) -> dict[int, float]:
    rows = read_jsonl(strict_path)
    expected_total = len(ops) * expected_rows
    if len(rows) != expected_total:
        raise ValueError(f"Expected {expected_total} strict rows in {strict_path}, found {len(rows)}")
    correct = {operation: 0 for operation in ops}
    counts = {operation: 0 for operation in ops}
    seen: set[tuple[int, str, int]] = set()
    for row_number, row in enumerate(rows, start=1):
        context = f"{strict_path}:{row_number}"
        operation = _require_int(row.get("op"), f"{context}.op")
        if operation not in correct:
            raise ValueError(f"{context}.op={operation} is outside OP{ops[0]}-{ops[-1]}")
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            raise ValueError(f"{context}.id must be a non-empty string")
        if row_id not in expected_ids[operation]:
            raise ValueError(f"{context}.id={row_id!r} is absent from the frozen OP{operation} dataset")
        sample_rank = _require_int(row.get("sample_rank"), f"{context}.sample_rank")
        if sample_rank != 0:
            raise ValueError(f"{context}.sample_rank={sample_rank}, expected exactly 0")
        key = (operation, row_id, sample_rank)
        if key in seen:
            raise ValueError(f"{context} duplicates strict result key {key}")
        seen.add(key)
        perfect = row.get("perfect")
        answer_correct = row.get("answer_correct")
        if not isinstance(perfect, bool) or not isinstance(answer_correct, bool):
            raise ValueError(f"{context} perfect and answer_correct must be booleans")
        counts[operation] += 1
        correct[operation] += perfect
    wrong_counts = {operation: count for operation, count in counts.items() if count != expected_rows}
    if wrong_counts:
        raise ValueError(f"Frozen strict per-operation row counts are incomplete: {wrong_counts}")
    observed_ids = {operation: {row_id for op, row_id, _rank in seen if op == operation} for operation in ops}
    if observed_ids != expected_ids:
        raise ValueError("Frozen strict result IDs do not exactly match the configured datasets")

    scores = {}
    for operation in ops:
        fraction = correct[operation] / expected_rows
        for kind in ("empirical", "unbiased"):
            recorded = _metric_pass_at_one(metrics, operation, kind)
            if not math.isclose(recorded, fraction, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError(f"Frozen OP{operation} {kind} pass@1={recorded} does not match strict rows {fraction}")
        scores[operation] = 100.0 * fraction
    try:
        total_pass = float(metrics["strict_graph"]["total"]["empirical"]["pass@1"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Frozen metrics lack strict_graph.total.empirical.pass@1") from error
    expected_total_pass = sum(correct.values()) / expected_total
    if not math.isclose(total_pass, expected_total_pass, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("Frozen total strict pass@1 does not match strict_results.jsonl")
    return scores


def _canonical_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_generation_provenance(
    output_dir: Path,
    eval_payload: dict[str, Any],
    metrics: dict[str, Any],
    expected_dataset_hashes: dict[str, str],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    from figure3_eval import (
        GENERATION_COMPLETION_NAME,
        GENERATION_MANIFEST_NAME,
        build_generation_manifest,
        canonical_generation_content,
        load_rows,
        verify_generation_completion,
        verify_generation_manifest,
    )

    eval_config = eval_payload["eval"]
    rows, dataset_hashes = load_rows(eval_config)
    if dataset_hashes != expected_dataset_hashes:
        raise ValueError("Generation contract dataset hashes differ from strict-eval datasets")
    manifest = build_generation_manifest(eval_payload, rows, dataset_hashes)
    verify_generation_manifest(output_dir / GENERATION_MANIFEST_NAME, manifest)
    digest, generation_records = canonical_generation_content(
        output_dir / "generations.jsonl",
        rows,
        int(eval_config["samples_per_prompt"]),
    )
    completion = verify_generation_completion(
        output_dir,
        manifest,
        digest,
        len(generation_records),
    )
    expected_metrics_provenance = {
        **completion,
        "generation_manifest": GENERATION_MANIFEST_NAME,
        "generation_completion": GENERATION_COMPLETION_NAME,
    }
    if metrics.get("generation_provenance") != expected_metrics_provenance:
        raise ValueError("Frozen metrics generation_provenance does not match generation completion")
    return digest, rows, generation_records


def _frozen_implementation_identity(run_dir: Path) -> tuple[Path, dict[str, str]]:
    source_dir = run_dir / "source_snapshot" / "user" / "tianhaowu" / "rsci"
    evaluator_path = (source_dir / "figure3_eval.py").resolve()
    scorer_path = (source_dir / "solution_graph.py").resolve()
    missing = [str(path) for path in (evaluator_path, scorer_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Frozen evaluator/scorer source files are missing: {missing}")
    return evaluator_path, {
        "figure3_eval.py": _file_sha256(evaluator_path),
        "solution_graph.py": _file_sha256(scorer_path),
    }


def load_frozen_eval(
    run_dir: Path,
    step: int,
    ops: tuple[int, ...],
    expected_rows: int,
) -> tuple[dict[int, float], FrozenEvalProvenance]:
    output_dir = run_dir / "evals" / "op11-45" / f"step_{step}"
    metrics_path = output_dir / "metrics.json"
    strict_path = output_dir / "strict_results.jsonl"
    eval_config_path = output_dir / "configs" / "eval.toml"
    inference_config_path = output_dir / "configs" / "inference.toml"
    required = (metrics_path, strict_path, eval_config_path, inference_config_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing scheduled frozen checkpoint step {step} artifacts: {missing}")

    model_path = _resolve_frozen_model_path(run_dir, step)
    eval_payload = _load_toml(eval_config_path)
    inference_payload = _load_toml(inference_config_path)
    eval_config = eval_payload.get("eval")
    if not isinstance(eval_config, dict):
        raise ValueError(f"Frozen eval config has no [eval] table: {eval_config_path}")
    inference_model = inference_payload.get("model")
    if not isinstance(inference_model, dict):
        raise ValueError(f"Frozen inference config has no [model] table: {inference_config_path}")
    expected_evaluator, expected_implementation = _frozen_implementation_identity(run_dir)
    configured_evaluator = _resolve_config_path(eval_payload.get("evaluator"), f"{eval_config_path}:evaluator")
    if configured_evaluator != expected_evaluator:
        raise ValueError(f"Frozen eval evaluator does not match pinned source: {configured_evaluator}")
    configured_inference = _resolve_config_path(eval_payload.get("infer_config"), f"{eval_config_path}:infer_config")
    if configured_inference != inference_config_path.resolve():
        raise ValueError(f"Frozen eval infer_config does not match {inference_config_path}")
    configured_output = _resolve_config_path(eval_config.get("output_dir"), f"{eval_config_path}:eval.output_dir")
    if configured_output != output_dir.resolve():
        raise ValueError(f"Frozen eval output_dir does not match scheduled step directory {output_dir}")
    for context, value in (
        ("eval.model", eval_config.get("model")),
        ("inference.model.name", inference_model.get("name")),
    ):
        configured_model = _resolve_config_path(value, f"{eval_config_path}:{context}")
        if configured_model != model_path:
            raise ValueError(f"Frozen {context} model path mismatch at step {step}: {configured_model} != {model_path}")
    if eval_config.get("operations") != list(ops):
        raise ValueError(f"Frozen eval operations must be exactly OP{ops[0]}-{ops[-1]}")
    if eval_config.get("examples_per_operation") != expected_rows:
        raise ValueError(f"Frozen eval examples_per_operation must equal {expected_rows}")
    if eval_config.get("samples_per_prompt") != 1 or eval_config.get("pass_at") != [1]:
        raise ValueError("Frozen confirmatory eval requires samples_per_prompt=1 and pass_at=[1]")
    if eval_config.get("request_seed") != FROZEN_REQUEST_SEED:
        raise ValueError(f"Frozen eval request_seed must equal {FROZEN_REQUEST_SEED}")
    for field, expected in CONFIRMATORY_EVAL_SAMPLING.items():
        _require_config_value(eval_config.get(field), expected, f"Frozen eval {field}")

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if not isinstance(metrics, dict):
        raise ValueError(f"Frozen metrics must be a JSON object: {metrics_path}")
    recorded_model = _resolve_config_path(metrics.get("model"), f"{metrics_path}:model")
    if recorded_model != model_path:
        raise ValueError(f"Frozen metrics model path mismatch at step {step}: {recorded_model} != {model_path}")
    expected_total = len(ops) * expected_rows
    expected_metric_fields = {
        "operations": list(ops),
        "num_prompts": expected_total,
        "samples_per_prompt": 1,
        "num_generations": expected_total,
    }
    for field, expected in expected_metric_fields.items():
        if metrics.get(field) != expected:
            raise ValueError(f"Frozen metrics {field}={metrics.get(field)!r}, expected {expected!r}")
    sampling = metrics.get("sampling")
    if not isinstance(sampling, dict):
        raise ValueError("Frozen metrics lack sampling provenance")
    for field in (
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "stop",
        "skip_special_tokens",
        "request_seed",
    ):
        if sampling.get(field) != eval_config.get(field):
            raise ValueError(f"Frozen metrics sampling.{field} does not match eval config")
    dataset_field = "data_dir" if "data_dir" in eval_config else "data_sources"
    if metrics.get(dataset_field) != eval_config.get(dataset_field):
        raise ValueError(f"Frozen metrics {dataset_field} does not match eval config")
    implementation_hashes = metrics.get("implementation_sha256")
    if (
        not isinstance(implementation_hashes, dict)
        or set(implementation_hashes) != {"figure3_eval.py", "solution_graph.py"}
        or any(
            not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in implementation_hashes.values()
        )
    ):
        raise ValueError("Frozen metrics lack valid implementation_sha256 provenance")
    if implementation_hashes != expected_implementation:
        raise ValueError("Frozen evaluator implementation hashes do not match the pinned source snapshot")

    dataset_hashes, expected_ids = _validate_dataset_hashes(eval_config, metrics, ops, expected_rows)
    canonical_generation_sha256, generation_rows, generation_records = _validate_generation_provenance(
        output_dir,
        eval_payload,
        metrics,
        dataset_hashes,
    )
    from figure3_eval import verify_strict_results

    strict_records = verify_strict_results(strict_path, generation_rows, generation_records)
    expected_scoring_provenance = {
        "implementation_sha256": expected_implementation,
        "strict_results_sha256": _file_sha256(strict_path),
        "num_results": expected_total,
    }
    if metrics.get("strict_scoring_provenance") != expected_scoring_provenance:
        raise ValueError("Frozen strict_scoring_provenance does not match deterministic strict results")
    if len(strict_records) != expected_total:
        raise ValueError(f"Deterministic rescoring produced {len(strict_records)} rows, expected {expected_total}")
    scores = _load_strict_scores(strict_path, metrics, ops, expected_rows, expected_ids)
    normalized_eval_hash, normalized_inference_hash = _normalized_frozen_config_hashes(
        eval_payload,
        inference_payload,
    )
    provenance = FrozenEvalProvenance(
        output_dir=output_dir.resolve(),
        model_path=model_path,
        eval_config_sha256=_file_sha256(eval_config_path),
        inference_config_sha256=_file_sha256(inference_config_path),
        metrics_sha256=_file_sha256(metrics_path),
        strict_results_sha256=_file_sha256(strict_path),
        dataset_sha256_by_op=dataset_hashes,
        implementation_sha256=dict(implementation_hashes),
        request_seed=FROZEN_REQUEST_SEED,
        canonical_generation_sha256=canonical_generation_sha256,
        normalized_eval_config_sha256=normalized_eval_hash,
        normalized_inference_config_sha256=normalized_inference_hash,
    )
    return scores, provenance


def load_confirmatory_run(
    label: str,
    path: Path,
    ops: tuple[int, ...],
    expected_rows: int,
    e_star: int,
    scheduled_steps: tuple[int, ...] = FROZEN_EVAL_STEPS,
) -> RunSeries:
    if ops != tuple(range(11, 46)):
        raise ValueError("Confirmatory frozen analysis requires the complete OP11-45 suite")
    if not scheduled_steps or scheduled_steps[0] != 0:
        raise ValueError("Frozen checkpoint schedule must begin at step 0")
    if tuple(sorted(set(scheduled_steps))) != scheduled_steps:
        raise ValueError("Frozen checkpoint schedule must be strictly increasing and unique")
    run_dir, rollouts = resolve_run_layout(path)
    training_identity = load_training_arm_identity(run_dir, label)
    group_stats_path = rollouts / "train_group_stats.jsonl"
    attempts_path = rollouts / "train_batch_attempts.jsonl"
    optimized_proxy_metric = f"{training_identity.defect_assignment.removesuffix('_group')}_proxy_reward"
    audit = load_audit_exposure_index(
        group_stats_path,
        attempts_path,
        optimized_proxy_metric,
        false_positive_rate=training_identity.false_positive_rate,
        defect_seed=training_identity.defect_seed,
    )
    exposure_by_step = {step: audit.counts_before(step) for step in scheduled_steps}
    upper_step = next(
        (step for step in scheduled_steps if exposure_by_step[step].attempted_slots >= e_star),
        None,
    )
    if upper_step is None:
        last_step = scheduled_steps[-1]
        raise ValueError(
            f"{label} fixed E*={e_star} exceeds audited E_policy={exposure_by_step[last_step].attempted_slots} "
            f"at final scheduled checkpoint step {last_step}"
        )
    required_steps = tuple(step for step in scheduled_steps if step <= upper_step)
    audit.require_contiguous_shipped_steps(upper_step)
    points = []
    reference_dataset_hashes: dict[str, str] | None = None
    reference_implementation_hashes: dict[str, str] | None = None
    for step in required_steps:
        scores, frozen_eval = load_frozen_eval(run_dir, step, ops, expected_rows)
        if reference_dataset_hashes is None:
            reference_dataset_hashes = frozen_eval.dataset_sha256_by_op
        elif frozen_eval.dataset_sha256_by_op != reference_dataset_hashes:
            raise ValueError(f"{label} frozen checkpoint step {step} changed the evaluation datasets")
        if reference_implementation_hashes is None:
            reference_implementation_hashes = frozen_eval.implementation_sha256
        elif frozen_eval.implementation_sha256 != reference_implementation_hashes:
            raise ValueError(f"{label} frozen checkpoint step {step} changed evaluator implementation hashes")
        policy_exposure = exposure_by_step[step]
        points.append(
            EvalPoint(
                step=step,
                finalized_groups=policy_exposure.groups,
                exposure=policy_exposure.attempted_slots,
                scores=scores,
                policy_version=step,
                policy_exposure=policy_exposure,
                frozen_eval=frozen_eval,
            )
        )
    policy_points = tuple(points)
    if policy_points[0].exposure != 0:
        raise ValueError(f"{label} frozen step-0 checkpoint must have E_policy=0")
    _require_strictly_increasing_exposure(policy_points, f"{label} frozen policy")
    _require_bracket(policy_points, e_star, label, "frozen policy")
    target_sizes = {group.target_size for group in audit.groups}
    if target_sizes != {CONFIRMATORY_GROUP_SIZE}:
        raise ValueError(f"{label} audit target sizes must all equal {CONFIRMATORY_GROUP_SIZE}, got {target_sizes}")
    return RunSeries(
        label=label,
        path=run_dir,
        group_size=CONFIRMATORY_GROUP_SIZE,
        points=policy_points,
        analysis_tier=CONFIRMATORY_TIER,
        audit_paths=(group_stats_path.resolve(), attempts_path.resolve()),
        frozen_eval_root=(run_dir / "evals" / "op11-45").resolve(),
        training_identity=training_identity,
        reward_audit=audit.reward_audit_before(upper_step, optimized_proxy_metric),
        prompt_exposure=audit.prompt_exposure_before(upper_step),
    )


def mean_score(point: EvalPoint, operations: tuple[int, ...]) -> float:
    missing = set(operations) - set(point.scores)
    if missing:
        raise ValueError(f"Step {point.step} lacks operations {sorted(missing)}")
    return math.fsum(point.scores[operation] for operation in operations) / len(operations)


def interpolate(points: tuple[EvalPoint, ...], exposure: int, operations: tuple[int, ...]) -> float:
    exposures = [point.exposure for point in points]
    if not exposures[0] <= exposure <= exposures[-1]:
        raise ValueError(f"Exposure {exposure} is outside [{exposures[0]}, {exposures[-1]}]")
    right = bisect.bisect_left(exposures, exposure)
    if exposures[right] == exposure:
        return mean_score(points[right], operations)
    left = right - 1
    left_value = mean_score(points[left], operations)
    right_value = mean_score(points[right], operations)
    fraction = (exposure - exposures[left]) / (exposures[right] - exposures[left])
    return left_value + fraction * (right_value - left_value)


def normalized_auc(
    points: tuple[EvalPoint, ...],
    start_exposure: int,
    end_exposure: int,
    operations: tuple[int, ...],
) -> float:
    if end_exposure <= start_exposure:
        raise ValueError("AUC interval must have positive width")
    coordinates = [(start_exposure, interpolate(points, start_exposure, operations))]
    coordinates.extend(
        (point.exposure, mean_score(point, operations))
        for point in points
        if start_exposure < point.exposure < end_exposure
    )
    coordinates.append((end_exposure, interpolate(points, end_exposure, operations)))
    area = math.fsum(
        (right_x - left_x) * (left_y + right_y) / 2.0
        for (left_x, left_y), (right_x, right_y) in zip(coordinates, coordinates[1:], strict=False)
    )
    return area / (end_exposure - start_exposure)


def sustained_discovery(
    series: RunSeries,
    operation: int,
    threshold: float,
    sustain: int,
    max_exposure: int,
) -> dict[str, object]:
    eligible_points = tuple(point for point in series.points if point.exposure <= max_exposure)
    if not eligible_points:
        raise ValueError(f"Run {series.label} has no observed evaluation at or before E*={max_exposure}")
    for index in range(len(eligible_points) - sustain + 1):
        window = eligible_points[index : index + sustain]
        if all(point.scores[operation] >= threshold for point in window):
            point = window[0]
            lower_exposure = eligible_points[index - 1].exposure if index else point.exposure
            return {
                "status": "observed",
                "observed": True,
                "step": point.step,
                "exposure": point.exposure,
                "interval": [lower_exposure, point.exposure],
                "confirmation_step": window[-1].step,
                "confirmation_exposure": window[-1].exposure,
                "administrative_e_star": max_exposure,
            }
    pending = 0
    for point in reversed(eligible_points):
        if point.scores[operation] < threshold:
            break
        pending += 1
    last = eligible_points[-1]
    return {
        "status": "right_censored",
        "observed": False,
        "right_censored_exposure": last.exposure,
        "right_censored_step": last.step,
        "administrative_e_star": max_exposure,
        "pending_above_threshold_count": min(pending, sustain - 1),
    }


def _bracket(points: tuple[EvalPoint, ...], exposure: int) -> dict[str, object]:
    exposures = [point.exposure for point in points]
    right_index = bisect.bisect_left(exposures, exposure)
    if exposures[right_index] == exposure:
        point = points[right_index]
        return {"left_step": point.step, "right_step": point.step, "weight_on_right": 0.0}
    left = points[right_index - 1]
    right = points[right_index]
    weight = (exposure - left.exposure) / (right.exposure - left.exposure)
    return {"left_step": left.step, "right_step": right.step, "weight_on_right": weight}


def validate_confirmatory_runs(runs: tuple[RunSeries, ...]) -> None:
    labels = [run.label for run in runs]
    if len(labels) != len(set(labels)) or set(labels) != set(CONFIRMATORY_ARM_SPECS):
        raise ValueError(f"Confirmatory analysis requires exactly C0/B1/S1/B5/S5, got {labels}")
    reference_identity: tuple[str, dict[str, object]] | None = None
    reference_baseline: tuple[str, dict[int, float], dict[str, str], str] | None = None
    reference_implementation: tuple[str, int, dict[str, str]] | None = None
    reference_frozen_configs: tuple[str, int, str, str] | None = None
    for run in runs:
        if run.training_identity is None or run.reward_audit is None or run.prompt_exposure is None:
            raise ValueError(f"{run.label} lacks resolved training identity, group reward audit, or prompt exposure")
        expected_assignment, expected_rate = CONFIRMATORY_ARM_SPECS[run.label]
        if (
            run.training_identity.label != run.label
            or run.training_identity.defect_assignment != expected_assignment
            or run.training_identity.false_positive_rate != expected_rate
        ):
            raise ValueError(f"{run.label} resolved training identity does not match its preregistered arm")
        invariants = run.training_identity.invariant_dict()
        if reference_identity is None:
            reference_identity = (run.label, invariants)
        elif invariants != reference_identity[1]:
            raise ValueError(f"Resolved training invariants differ between {reference_identity[0]} and {run.label}")
        for point in run.points:
            if point.frozen_eval is None:
                raise ValueError(f"{run.label} step {point.step} lacks frozen-eval provenance")
            implementation = point.frozen_eval.implementation_sha256
            if reference_implementation is None:
                reference_implementation = (run.label, point.step, implementation)
            elif implementation != reference_implementation[2]:
                reference_label, reference_step, _hashes = reference_implementation
                raise ValueError(
                    f"Frozen evaluator implementation hashes differ between "
                    f"{reference_label} step {reference_step} and {run.label} step {point.step}"
                )
            frozen_configs = (
                point.frozen_eval.normalized_eval_config_sha256,
                point.frozen_eval.normalized_inference_config_sha256,
            )
            if reference_frozen_configs is None:
                reference_frozen_configs = (run.label, point.step, *frozen_configs)
            elif frozen_configs != reference_frozen_configs[2:]:
                raise ValueError(
                    f"Normalized frozen eval/inference configs differ between "
                    f"{reference_frozen_configs[0]} step {reference_frozen_configs[1]} "
                    f"and {run.label} step {point.step}"
                )
        step_zero = [point for point in run.points if point.step == 0]
        if len(step_zero) != 1 or step_zero[0].frozen_eval is None:
            raise ValueError(f"{run.label} must contain exactly one provenance-complete frozen step-0 eval")
        point = step_zero[0]
        provenance = point.frozen_eval
        if provenance.request_seed != FROZEN_REQUEST_SEED:
            raise ValueError(f"{run.label} frozen request seed differs from {FROZEN_REQUEST_SEED}")
        if provenance.model_path != run.training_identity.model_path:
            raise ValueError(f"{run.label} frozen step-0 model differs from its resolved training base model")
        if reference_baseline is None:
            reference_baseline = (
                run.label,
                point.scores,
                provenance.dataset_sha256_by_op,
                provenance.canonical_generation_sha256,
            )
            continue
        previous_label, previous_scores, previous_hashes, previous_digest = reference_baseline
        if provenance.dataset_sha256_by_op != previous_hashes:
            raise ValueError(
                f"Frozen step-0 dataset hashes differ between {previous_label} and {run.label} "
                f"for the shared base model"
            )
        if provenance.canonical_generation_sha256 != previous_digest:
            raise ValueError(
                f"Frozen step-0 canonical generation digests differ between {previous_label} and {run.label}"
            )
        if point.scores != previous_scores:
            raise ValueError(
                f"Frozen step-0 scores differ between {previous_label} and {run.label} for the shared base model"
            )


def summarize(
    runs: tuple[RunSeries, ...],
    common_start: int,
    common_end: int,
    discovery_op: int,
    discovery_threshold: float,
    sustain: int,
    *,
    analysis_tier: str = LEGACY_TIER,
    endpoint_selection: str = "posthoc_common_support",
) -> dict[str, object]:
    if analysis_tier == CONFIRMATORY_TIER:
        validate_confirmatory_runs(runs)
    summaries = {}
    for run in runs:
        endpoint_scores = {
            "frontier_op15_17_percent": interpolate(run.points, common_end, FRONTIER_OPS),
            "retention_op11_12_percent": interpolate(run.points, common_end, RETENTION_OPS),
            "op13_17_percent": interpolate(run.points, common_end, tuple(range(13, 18))),
            f"op{discovery_op}_percent": interpolate(run.points, common_end, (discovery_op,)),
        }
        run_summary: dict[str, object] = {
            "path": str(run.path),
            "group_size": run.group_size,
            "num_complete_evals": len(run.points),
            "last_step": run.points[-1].step,
            "frontier_op15_17_auc_percent": normalized_auc(run.points, common_start, common_end, FRONTIER_OPS),
            "retention_op11_12_auc_percent": normalized_auc(run.points, common_start, common_end, RETENTION_OPS),
            "sustained_discovery": sustained_discovery(run, discovery_op, discovery_threshold, sustain, common_end),
        }
        if analysis_tier == CONFIRMATORY_TIER:
            assert run.training_identity is not None
            assert run.reward_audit is not None
            assert run.prompt_exposure is not None
            run_summary.update(
                {
                    "audit_paths": [str(path) for path in run.audit_paths or ()],
                    "frozen_eval_root": str(run.frozen_eval_root),
                    "last_attempted_slot_exposure": run.points[-1].exposure,
                    "at_fixed_attempted_slot_exposure": endpoint_scores,
                    "fixed_e_star_attempted_slots": common_end,
                    "attempted_slot_e_star_bracket": _bracket(run.points, common_end),
                    "scheduled_checkpoint_steps": [point.step for point in run.points],
                    "resolved_training_arm": run.training_identity.as_dict(),
                    "group_reward_audit_through_e_star_bracket": run.reward_audit.as_dict(),
                    "prompt_exposure_through_e_star_bracket": run.prompt_exposure.as_dict(),
                }
            )
            run_summary["curve"] = [
                {
                    "step": point.step,
                    "policy_version": point.policy_version,
                    "E_policy": point.policy_exposure.as_dict() if point.policy_exposure else None,
                    "frozen_eval": {
                        "output_dir": str(point.frozen_eval.output_dir),
                        "model_path": str(point.frozen_eval.model_path),
                        "eval_config_sha256": point.frozen_eval.eval_config_sha256,
                        "inference_config_sha256": point.frozen_eval.inference_config_sha256,
                        "metrics_sha256": point.frozen_eval.metrics_sha256,
                        "strict_results_sha256": point.frozen_eval.strict_results_sha256,
                        "dataset_sha256_by_op": point.frozen_eval.dataset_sha256_by_op,
                        "implementation_sha256": point.frozen_eval.implementation_sha256,
                        "request_seed": point.frozen_eval.request_seed,
                        "canonical_generation_sha256": point.frozen_eval.canonical_generation_sha256,
                        "normalized_eval_config_sha256": point.frozen_eval.normalized_eval_config_sha256,
                        "normalized_inference_config_sha256": (point.frozen_eval.normalized_inference_config_sha256),
                    }
                    if point.frozen_eval
                    else None,
                    "frontier_op15_17_percent": mean_score(point, FRONTIER_OPS),
                    "retention_op11_12_percent": mean_score(point, RETENTION_OPS),
                    f"op{discovery_op}_percent": point.scores[discovery_op],
                }
                for point in run.points
            ]
        else:
            run_summary["last_log_proxy_exposure"] = run.points[-1].exposure
            run_summary["at_common_log_proxy_exposure"] = endpoint_scores
            run_summary["curve"] = [
                {
                    "step": point.step,
                    "E_log_proxy": point.exposure,
                    "finalized_groups_log_proxy": point.finalized_groups,
                    "frontier_op15_17_percent": mean_score(point, FRONTIER_OPS),
                    "retention_op11_12_percent": mean_score(point, RETENTION_OPS),
                    f"op{discovery_op}_percent": point.scores[discovery_op],
                }
                for point in run.points
            ]
        summaries[run.label] = run_summary

    confirmatory = analysis_tier == CONFIRMATORY_TIER
    result: dict[str, object] = {
        "analysis_tier": analysis_tier,
        "artifact_audit_valid": confirmatory,
        "preregistered_pilot_valid": confirmatory,
        "causal_claim_valid": False,
        "phase_transition_claim_valid": False,
        "endpoint_selection": endpoint_selection,
        ("common_attempted_slot_exposure_interval" if confirmatory else "common_log_proxy_exposure_interval"): [
            common_start,
            common_end,
        ],
        "frontier_operations": list(FRONTIER_OPS),
        "retention_operations": list(RETENTION_OPS),
        "discovery_rule": {
            "operation": discovery_op,
            "threshold_percent": discovery_threshold,
            "consecutive_evaluations": sustain,
            "event_time": "first checkpoint in the sustained window",
            "confirmation_must_be_at_or_before_e_star": True,
        },
        "runs": summaries,
    }
    if confirmatory:
        runs_by_label = {run.label: run for run in runs}
        frontier_auc = {
            label: float(summaries[label]["frontier_op15_17_auc_percent"]) for label in CONFIRMATORY_ARM_SPECS
        }
        low_dose_component = frontier_auc["B1"] - frontier_auc["S1"]
        high_dose_component = frontier_auc["B5"] - frontier_auc["S5"]
        interaction = low_dose_component - high_dose_component

        pair_audits = {}
        for dose, behavior_label, shuffled_label in (("p01", "B1", "S1"), ("p05", "B5", "S5")):
            behavior_run = runs_by_label[behavior_label]
            shuffled_run = runs_by_label[shuffled_label]
            behavior_audit = behavior_run.reward_audit
            shuffled_audit = shuffled_run.reward_audit
            assert behavior_audit is not None and shuffled_audit is not None
            behavior_prompts = behavior_run.prompt_exposure
            shuffled_prompts = shuffled_run.prompt_exposure
            assert behavior_prompts is not None and shuffled_prompts is not None
            behavior_sequence = behavior_prompts.ordered_groups
            shuffled_sequence = shuffled_prompts.ordered_groups
            common_length = min(len(behavior_sequence), len(shuffled_sequence))
            prefix_matches = 0
            for behavior_group, shuffled_group in zip(behavior_sequence, shuffled_sequence, strict=False):
                if behavior_group != shuffled_group:
                    break
                prefix_matches += 1
            positional_matches = sum(
                behavior_group == shuffled_group
                for behavior_group, shuffled_group in zip(behavior_sequence, shuffled_sequence, strict=False)
            )
            behavior_summary = behavior_audit.as_dict()
            shuffled_summary = shuffled_audit.as_dict()
            behavior_mean = behavior_summary["realized_k_mean_per_group"]
            shuffled_mean = shuffled_summary["realized_k_mean_per_group"]
            behavior_candidate_rate = _optional_rate(behavior_audit.candidate_opportunities, behavior_audit.valid_slots)
            shuffled_candidate_rate = _optional_rate(shuffled_audit.candidate_opportunities, shuffled_audit.valid_slots)
            pair_audits[dose] = {
                "behavior_arm": behavior_label,
                "shuffled_arm": shuffled_label,
                "independent_online_arms": True,
                "realized_histograms_expected_identical_across_arms": False,
                "ordered_sample_op_comparison_through_e_star_bracket": {
                    "behavior_groups": len(behavior_sequence),
                    "shuffled_groups": len(shuffled_sequence),
                    "common_positions": common_length,
                    "matching_prefix_groups": prefix_matches,
                    "matching_prefix_rate_over_common_positions": _optional_rate(prefix_matches, common_length),
                    "matching_positions": positional_matches,
                    "matching_position_rate_over_common_positions": _optional_rate(positional_matches, common_length),
                    "sequences_identical": behavior_sequence == shuffled_sequence,
                },
                "total_group_record_difference_B_minus_S": (
                    behavior_audit.total_group_records - shuffled_audit.total_group_records
                ),
                "complete_scored_group_difference_B_minus_S": (
                    len(behavior_audit.realized_k_by_group) - len(shuffled_audit.realized_k_by_group)
                ),
                "candidate_opportunity_difference_B_minus_S": (
                    behavior_audit.candidate_opportunities - shuffled_audit.candidate_opportunities
                ),
                "candidate_opportunity_rate_per_valid_slot": {
                    "behavior": behavior_candidate_rate,
                    "shuffled": shuffled_candidate_rate,
                    "difference_B_minus_S": (
                        behavior_candidate_rate - shuffled_candidate_rate
                        if behavior_candidate_rate is not None and shuffled_candidate_rate is not None
                        else None
                    ),
                },
                "eligible_opportunity_difference_B_minus_S": (
                    behavior_audit.eligible_opportunities - shuffled_audit.eligible_opportunities
                ),
                "valid_slot_difference_B_minus_S": behavior_audit.valid_slots - shuffled_audit.valid_slots,
                "realized_k_total_difference_B_minus_S": (
                    int(behavior_summary["realized_k_total"]) - int(shuffled_summary["realized_k_total"])
                ),
                "realized_k_mean_per_group_difference_B_minus_S": (
                    float(behavior_mean) - float(shuffled_mean)
                    if behavior_mean is not None and shuffled_mean is not None
                    else None
                ),
            }
        result.update(
            {
                "estimand": "piecewise-linear clean strict pass@1 versus exact audited E_policy.attempted_slots",
                "primary_exposure": "E_policy.attempted_slots",
                "evaluation_source": "immutable frozen checkpoints under RUN_DIR/evals/op11-45/step_N",
                "fixed_e_star_attempted_slots": common_end,
                "full_scheduled_checkpoint_steps": list(FROZEN_EVAL_STEPS),
                "exposure_definition": {
                    "E_policy.attempted_slots(v)": "sum(target_size) where finalized_before_optimizer_step < v",
                    "audit_counts": (
                        "attempted, received, valid, advantage-population, assembled, shipped, "
                        "and trainable-shipped slots are emitted separately"
                    ),
                },
                "preregistered_primary_interaction": {
                    "formula": "[AUC15:17(B1)-AUC15:17(S1)]-[AUC15:17(B5)-AUC15:17(S5)]",
                    "B1_auc_percent": frontier_auc["B1"],
                    "S1_auc_percent": frontier_auc["S1"],
                    "B5_auc_percent": frontier_auc["B5"],
                    "S5_auc_percent": frontier_auc["S5"],
                    "B1_minus_S1_percent_points": low_dose_component,
                    "B5_minus_S5_percent_points": high_dose_component,
                    "interaction_percent_points": interaction,
                    "preregistered_direction": "positive",
                    "direction_observed": "positive"
                    if interaction > 0.0
                    else "zero"
                    if interaction == 0.0
                    else "negative",
                },
                "online_pair_opportunity_divergence": pair_audits,
                "scientific_scope": "one-seed mechanism screen",
                "warnings": [
                    "One seed can screen the proposed mechanism but cannot support a causal-effect or phase-transition claim.",
                    "B/S arms are independent online runs: within-group counterfactual histograms are matched, but realized K and opportunity counts need not match across arms.",
                ],
            }
        )
    else:
        result.update(
            {
                "estimand": "descriptive clean strict pass@1 versus periodic finalized-group log proxy",
                "exposure_source": "latest_logged_groups_fin_times_configured_group_size",
                "warnings": [
                    "Legacy V2 lacks train_group_stats.jsonl and train_batch_attempts.jsonl provenance.",
                    "E_log_proxy is neither exact E_trigger nor exact E_policy.",
                    "AUC and discovery timing are descriptive and not valid for confirmatory causal claims.",
                ],
            }
        )
    return result


def plot_runs(
    runs: tuple[RunSeries, ...],
    common_end: int,
    discovery_op: int,
    discovery_threshold: float,
    output: Path,
) -> None:
    tiers = {run.analysis_tier for run in runs}
    if len(tiers) != 1:
        raise ValueError(f"Cannot plot mixed analysis tiers: {sorted(tiers)}")
    confirmatory = tiers == {CONFIRMATORY_TIER}
    x_label = (
        "audited E_policy.attempted_slots (thousands)"
        if confirmatory
        else "E_log_proxy (thousands; mixed-policy descriptive only)"
    )
    figure_title = (
        "Frozen-checkpoint strict evaluation aligned by audited E_policy.attempted_slots"
        if confirmatory
        else "Live mixed-policy descriptive curves aligned by E_log_proxy"
    )
    panels = (
        (f"Strict frontier OP{FRONTIER_OPS[0]}-{FRONTIER_OPS[-1]}", FRONTIER_OPS),
        (f"Strict retention OP{RETENTION_OPS[0]}-{RETENTION_OPS[-1]}", RETENTION_OPS),
        (f"Strict OP{discovery_op}", (discovery_op,)),
    )
    plt.rcParams["svg.hashsalt"] = "rsci-verifier-exposure"
    figure, axes = plt.subplots(1, 3, figsize=(14.5, 4.4), sharex=True)
    colors = plt.cm.tab10.colors
    for axis, (panel_title, operations) in zip(axes, panels, strict=True):
        for index, run in enumerate(runs):
            color = colors[index % len(colors)]
            exposures = [point.exposure / 1000.0 for point in run.points]
            values = [mean_score(point, operations) for point in run.points]
            axis.plot(exposures, values, color=color, alpha=0.25, linewidth=1.5)
            shared_points = [point for point in run.points if point.exposure <= common_end]
            shared_x = [point.exposure / 1000.0 for point in shared_points]
            shared_y = [mean_score(point, operations) for point in shared_points]
            if shared_points[-1].exposure < common_end:
                shared_x.append(common_end / 1000.0)
                shared_y.append(interpolate(run.points, common_end, operations))
            axis.plot(shared_x, shared_y, marker="o", markersize=3.2, linewidth=2.0, color=color, label=run.label)
        axis.axvline(common_end / 1000.0, color="#666666", linestyle="--", linewidth=1.0)
        axis.set_title(panel_title)
        axis.set_xlabel(x_label)
        axis.grid(alpha=0.25, linestyle="--")
    axes[0].set_ylabel("clean strict pass@1 (%)")
    axes[2].axhline(discovery_threshold, color="#999999", linestyle=":", linewidth=1.0)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.92),
        ncols=max(1, len(runs)),
        frameon=False,
    )
    figure.suptitle(figure_title, y=0.99)
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.84))
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"Date": None} if output.suffix.lower() == ".svg" else None
    figure.savefig(output, bbox_inches="tight", metadata=metadata)
    plt.close(figure)


def main() -> None:
    args = parse_args()
    ops = parse_ops(args.ops)
    if not set((*FRONTIER_OPS, *RETENTION_OPS, args.discovery_op)) <= set(ops):
        raise ValueError("--ops must include frontier, retention, and discovery operations")
    run_paths = parse_labeled_values(args.run, Path)
    group_sizes = parse_labeled_values(args.group_size, int)
    unknown_group_sizes = set(group_sizes) - set(run_paths)
    if unknown_group_sizes:
        raise ValueError(f"Group-size overrides reference unknown runs: {sorted(unknown_group_sizes)}")

    if args.analysis_tier == CONFIRMATORY_TIER:
        assert args.e_star is not None
        runs = tuple(
            load_confirmatory_run(
                label,
                path,
                ops,
                args.expected_rows,
                args.e_star,
            )
            for label, path in run_paths.items()
        )
        common_start = 0
        common_end = args.e_star
        endpoint_selection = "fixed_preregistered_e_star"
    else:
        runs = tuple(
            load_legacy_run(
                label,
                path,
                int(group_sizes.get(label, args.default_group_size)),
                ops,
                args.expected_rows,
            )
            for label, path in run_paths.items()
        )
        common_start = max(run.points[0].exposure for run in runs)
        common_end = args.e_star if args.e_star is not None else min(run.points[-1].exposure for run in runs)
        endpoint_selection = "fixed_descriptive_e_star" if args.e_star is not None else "posthoc_common_support"
        if common_end <= common_start:
            raise ValueError(f"Runs have no common positive exposure interval: [{common_start}, {common_end}]")
        for run in runs:
            if not run.points[0].exposure <= common_end <= run.points[-1].exposure:
                raise ValueError(
                    f"Requested descriptive endpoint {common_end} is outside {run.label}'s range "
                    f"[{run.points[0].exposure}, {run.points[-1].exposure}]"
                )

    result = summarize(
        runs,
        common_start,
        common_end,
        args.discovery_op,
        args.discovery_threshold,
        args.sustain,
        analysis_tier=args.analysis_tier,
        endpoint_selection=endpoint_selection,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_svg is not None:
        plot_runs(runs, common_end, args.discovery_op, args.discovery_threshold, args.output_svg)
    endpoint_key = (
        "at_fixed_attempted_slot_exposure"
        if args.analysis_tier == CONFIRMATORY_TIER
        else "at_common_log_proxy_exposure"
    )
    compact = {
        label: {
            "frontier_auc": values["frontier_op15_17_auc_percent"],
            "retention_auc": values["retention_op11_12_auc_percent"],
            "endpoint_scores": values[endpoint_key],
            "sustained_discovery": values["sustained_discovery"],
        }
        for label, values in result["runs"].items()
    }
    print(
        json.dumps(
            {
                "analysis_tier": args.analysis_tier,
                "common_attempted_slots" if args.analysis_tier == CONFIRMATORY_TIER else "common_exposure": common_end,
                "runs": compact,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
