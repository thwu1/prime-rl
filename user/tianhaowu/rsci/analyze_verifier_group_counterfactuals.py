#!/usr/bin/env python3
"""Replay behavior-conditioned and shuffled verifier defects from group audit logs.

This is a fixed-rollout counterfactual. It recomputes binary rewards for each
requested defect probability, then replays the recorded batch composition under
the enforced zero-advantage filter. It does not claim that later model rollouts
would remain unchanged under a different reward.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STRICT_METRIC = "strict_dependency_graph_reward"
CANDIDATE_METRIC = "defect_candidate_metric"
DEFECT_DRAW_METRIC = "defect_draw_metric"
SHUFFLE_DRAW_METRIC = "shuffle_draw_metric"
ROLLOUT_SLOT_METRIC = "defect_rollout_slot_metric"
REQUIRED_METRICS = (
    STRICT_METRIC,
    CANDIDATE_METRIC,
    DEFECT_DRAW_METRIC,
    SHUFFLE_DRAW_METRIC,
    ROLLOUT_SLOT_METRIC,
)


@dataclass(frozen=True)
class GroupRecord:
    group_id: str
    trace_ids: tuple[str, ...]
    rollout_slots: tuple[int, ...]
    strict: tuple[int, ...]
    candidate: tuple[int, ...]
    defect_draw: tuple[float, ...]
    shuffle_draw: tuple[float, ...]
    valid: tuple[bool, ...]
    advantage_indices: tuple[int, ...]
    appended_indices: tuple[int, ...]


@dataclass(frozen=True)
class GroupCounterfactual:
    behavior_rewards: tuple[int, ...]
    shuffled_rewards: tuple[int, ...]
    behavior_trigger_count: int
    behavior_triggers_in_advantage_population: int
    behavior_mixed: bool
    shuffled_mixed: bool


@dataclass(frozen=True)
class ManifestSlice:
    group_id: str
    count: int
    trainable_count: int
    appended_offset: int


@dataclass(frozen=True)
class BatchAttempt:
    batch_attempt: int
    optimizer_step: int
    eligible_to_ship: bool
    n_rollouts: int
    n_trainable: int
    group_slices: tuple[ManifestSlice, ...]


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return value


def _require_list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a JSON array")
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


def _require_binary(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (0, 1):
        raise ValueError(f"{context} must be exactly 0 or 1")
    return int(value)


def _require_integral_number(value: Any, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be an integer-valued number >= {minimum}")
    integer = int(value)
    if value != integer or integer < minimum:
        raise ValueError(f"{context} must be an integer-valued number >= {minimum}")
    return integer


def _require_draw(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a number in [0, 1)")
    draw = float(value)
    if not math.isfinite(draw) or not 0.0 <= draw < 1.0:
        raise ValueError(f"{context} must be a finite number in [0, 1), got {value!r}")
    return draw


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
            rows.append(_require_dict(value, f"{path}:{line_number}"))
    if not rows:
        raise ValueError(f"{path} contains no records")
    return rows


def parse_groups(rows: list[dict[str, Any]]) -> list[GroupRecord]:
    groups = []
    seen_group_ids: set[str] = set()
    seen_trace_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        context = f"group record {row_number}"
        group_id = _require_str(row.get("group_id"), f"{context}.group_id")
        if group_id in seen_group_ids:
            raise ValueError(f"{context}.group_id is duplicated: {group_id}")
        seen_group_ids.add(group_id)

        received_size = _require_int(row.get("received_size"), f"{context}.received_size", minimum=1)
        target_size = _require_int(row.get("target_size"), f"{context}.target_size", minimum=1)
        if received_size != target_size:
            raise ValueError(f"{context} is incomplete: received_size={received_size}, target_size={target_size}")

        trace_values = _require_list(row.get("trace_ids"), f"{context}.trace_ids")
        trace_ids = tuple(
            _require_str(value, f"{context}.trace_ids[{index}]") for index, value in enumerate(trace_values)
        )
        if len(trace_ids) != received_size:
            raise ValueError(f"{context}.trace_ids has length {len(trace_ids)}, expected received_size={received_size}")
        if len(set(trace_ids)) != len(trace_ids):
            raise ValueError(f"{context}.trace_ids contains duplicates")
        repeated_trace_ids = seen_trace_ids.intersection(trace_ids)
        if repeated_trace_ids:
            raise ValueError(f"{context}.trace_ids repeats globally unique IDs: {sorted(repeated_trace_ids)}")
        seen_trace_ids.update(trace_ids)

        raw_rollout_slots = _require_list(row.get("rollout_slots"), f"{context}.rollout_slots")
        rollout_slots = tuple(
            _require_int(value, f"{context}.rollout_slots[{index}]") for index, value in enumerate(raw_rollout_slots)
        )
        if rollout_slots != tuple(range(received_size)):
            raise ValueError(f"{context}.rollout_slots must equal the ordered range 0..{received_size - 1}")
        expected_rollout_slots = _require_list(row.get("expected_rollout_slots"), f"{context}.expected_rollout_slots")
        if expected_rollout_slots != list(range(received_size)):
            raise ValueError(f"{context}.expected_rollout_slots must equal the ordered range 0..{received_size - 1}")

        metrics = _require_dict(row.get("metrics"), f"{context}.metrics")
        missing_metrics = [name for name in REQUIRED_METRICS if name not in metrics]
        if missing_metrics:
            raise ValueError(f"{context}.metrics is missing required arrays: {missing_metrics}")
        metric_arrays = {}
        for name in REQUIRED_METRICS:
            values = _require_list(metrics[name], f"{context}.metrics.{name}")
            if len(values) != received_size:
                raise ValueError(
                    f"{context}.metrics.{name} has length {len(values)}, expected received_size={received_size}"
                )
            metric_arrays[name] = values

        strict = tuple(
            _require_binary(value, f"{context}.metrics.{STRICT_METRIC}[{index}]")
            for index, value in enumerate(metric_arrays[STRICT_METRIC])
        )
        candidate = tuple(
            _require_binary(value, f"{context}.metrics.{CANDIDATE_METRIC}[{index}]")
            for index, value in enumerate(metric_arrays[CANDIDATE_METRIC])
        )
        defect_draw = tuple(
            _require_draw(value, f"{context}.metrics.{DEFECT_DRAW_METRIC}[{index}]")
            for index, value in enumerate(metric_arrays[DEFECT_DRAW_METRIC])
        )
        shuffle_draw = tuple(
            _require_draw(value, f"{context}.metrics.{SHUFFLE_DRAW_METRIC}[{index}]")
            for index, value in enumerate(metric_arrays[SHUFFLE_DRAW_METRIC])
        )
        metric_rollout_slots = tuple(
            _require_integral_number(value, f"{context}.metrics.{ROLLOUT_SLOT_METRIC}[{index}]")
            for index, value in enumerate(metric_arrays[ROLLOUT_SLOT_METRIC])
        )
        if metric_rollout_slots != rollout_slots:
            raise ValueError(f"{context}.metrics.{ROLLOUT_SLOT_METRIC} does not match verifier-reported rollout_slots")

        errored_values = _require_list(row.get("errored"), f"{context}.errored")
        advantage_values = _require_list(row.get("in_advantage_population"), f"{context}.in_advantage_population")
        appended_values = _require_list(row.get("appended_to_batch"), f"{context}.appended_to_batch")
        for name, values in (
            ("errored", errored_values),
            ("in_advantage_population", advantage_values),
            ("appended_to_batch", appended_values),
        ):
            if len(values) != received_size:
                raise ValueError(f"{context}.{name} has length {len(values)}, expected received_size={received_size}")

        errored = tuple(
            _require_bool(value, f"{context}.errored[{index}]") for index, value in enumerate(errored_values)
        )
        in_advantage = tuple(
            _require_bool(value, f"{context}.in_advantage_population[{index}]")
            for index, value in enumerate(advantage_values)
        )
        appended = tuple(
            _require_bool(value, f"{context}.appended_to_batch[{index}]") for index, value in enumerate(appended_values)
        )
        advantage_population_size = _require_int(
            row.get("advantage_population_size"), f"{context}.advantage_population_size"
        )
        if advantage_population_size != sum(in_advantage):
            raise ValueError(
                f"{context}.advantage_population_size={advantage_population_size}, "
                f"but its membership mask sums to {sum(in_advantage)}"
            )

        for index, (is_strict, is_candidate, is_errored, in_population, was_appended) in enumerate(
            zip(strict, candidate, errored, in_advantage, appended, strict=True)
        ):
            if is_candidate and is_strict:
                raise ValueError(f"{context}[{index}] is both strict-correct and a defect candidate")
            if is_errored and (is_candidate or in_population or was_appended):
                raise ValueError(f"{context}[{index}] is errored but is candidate/in-advantage/appended")
            if was_appended and not in_population:
                raise ValueError(f"{context}[{index}] was appended without entering the advantage population")

        groups.append(
            GroupRecord(
                group_id=group_id,
                trace_ids=trace_ids,
                rollout_slots=rollout_slots,
                strict=strict,
                candidate=candidate,
                defect_draw=defect_draw,
                shuffle_draw=shuffle_draw,
                valid=tuple(not value for value in errored),
                advantage_indices=tuple(index for index, value in enumerate(in_advantage) if value),
                appended_indices=tuple(index for index, value in enumerate(appended) if value),
            )
        )
    return groups


def counterfactual_group(group: GroupRecord, probability: float) -> GroupCounterfactual:
    behavior_triggered = tuple(
        valid and candidate == 1 and draw < probability
        for valid, candidate, draw in zip(group.valid, group.candidate, group.defect_draw, strict=True)
    )
    behavior_trigger_count = sum(behavior_triggered)
    strict_negative_indices = [
        index
        for index, (valid, strict) in enumerate(zip(group.valid, group.strict, strict=True))
        if valid and not strict
    ]
    if behavior_trigger_count > len(strict_negative_indices):
        raise ValueError(
            f"Group {group.group_id} has K={behavior_trigger_count} behavior triggers but only "
            f"{len(strict_negative_indices)} strict negatives"
        )
    shuffled_indices = set(
        sorted(
            strict_negative_indices,
            key=lambda index: (group.shuffle_draw[index], group.rollout_slots[index]),
        )[:behavior_trigger_count]
    )

    behavior_rewards = tuple(
        int(valid and (strict == 1 or triggered))
        for valid, strict, triggered in zip(group.valid, group.strict, behavior_triggered, strict=True)
    )
    shuffled_rewards = tuple(
        int(valid and (strict == 1 or index in shuffled_indices))
        for index, (valid, strict) in enumerate(zip(group.valid, group.strict, strict=True))
    )
    if sorted(behavior_rewards) != sorted(shuffled_rewards):
        raise ValueError(f"Group {group.group_id} failed the matched reward-histogram invariant")

    behavior_advantage_rewards = [behavior_rewards[index] for index in group.advantage_indices]
    shuffled_advantage_rewards = [shuffled_rewards[index] for index in group.advantage_indices]
    return GroupCounterfactual(
        behavior_rewards=behavior_rewards,
        shuffled_rewards=shuffled_rewards,
        behavior_trigger_count=behavior_trigger_count,
        behavior_triggers_in_advantage_population=sum(behavior_triggered[index] for index in group.advantage_indices),
        behavior_mixed=set(behavior_advantage_rewards) == {0, 1},
        shuffled_mixed=set(shuffled_advantage_rewards) == {0, 1},
    )


def parse_attempts(
    rows: list[dict[str, Any]],
    groups: list[GroupRecord],
) -> tuple[list[BatchAttempt], int]:
    groups_by_id = {group.group_id: group for group in groups}
    expected_segments = [(group.group_id, len(group.appended_indices)) for group in groups if group.appended_indices]
    segment_index = 0
    offset_in_segment = 0
    consumed_members = 0
    seen_attempts: set[int] = set()
    attempts = []

    for row_number, row in enumerate(rows, start=1):
        context = f"batch attempt record {row_number}"
        batch_attempt = _require_int(row.get("batch_attempt"), f"{context}.batch_attempt", minimum=1)
        if batch_attempt in seen_attempts:
            raise ValueError(f"{context}.batch_attempt is duplicated: {batch_attempt}")
        seen_attempts.add(batch_attempt)
        if row_number > 1 and batch_attempt != attempts[-1].batch_attempt + 1:
            raise ValueError(
                f"{context}.batch_attempt={batch_attempt} is not consecutive after {attempts[-1].batch_attempt}"
            )

        optimizer_step = _require_int(row.get("optimizer_step"), f"{context}.optimizer_step")
        if attempts and optimizer_step < attempts[-1].optimizer_step:
            raise ValueError(f"{context}.optimizer_step={optimizer_step} decreased from {attempts[-1].optimizer_step}")
        eligible_to_ship = _require_bool(row.get("eligible_to_ship"), f"{context}.eligible_to_ship")
        n_rollouts = _require_int(row.get("n_rollouts"), f"{context}.n_rollouts", minimum=1)
        n_trainable = _require_int(row.get("n_trainable"), f"{context}.n_trainable")
        if n_trainable > n_rollouts:
            raise ValueError(f"{context}.n_trainable exceeds n_rollouts")

        raw_slices = _require_list(row.get("group_slices"), f"{context}.group_slices")
        if not raw_slices:
            raise ValueError(f"{context}.group_slices must not be empty")
        parsed_slices = []
        for slice_index, raw_slice in enumerate(raw_slices):
            slice_context = f"{context}.group_slices[{slice_index}]"
            values = _require_dict(raw_slice, slice_context)
            group_id = _require_str(values.get("group_id"), f"{slice_context}.group_id")
            count = _require_int(values.get("count"), f"{slice_context}.count", minimum=1)
            trainable_count = _require_int(values.get("trainable_count"), f"{slice_context}.trainable_count")
            if trainable_count > count:
                raise ValueError(f"{slice_context}.trainable_count exceeds count")
            if slice_index and parsed_slices[-1].group_id == group_id:
                raise ValueError(f"{slice_context} repeats an adjacent group instead of using RLE")
            if group_id not in groups_by_id:
                raise ValueError(f"{slice_context} references unknown group_id {group_id}")
            if segment_index >= len(expected_segments):
                raise ValueError(f"{slice_context} consumes more members than were appended")

            expected_group_id, expected_count = expected_segments[segment_index]
            if group_id != expected_group_id:
                raise ValueError(
                    f"{slice_context} references {group_id}, but appended member offset "
                    f"{consumed_members} belongs to {expected_group_id}"
                )
            remaining = expected_count - offset_in_segment
            if count > remaining:
                raise ValueError(
                    f"{slice_context}.count={count} overruns group {group_id}: "
                    f"offset={offset_in_segment}, appended_size={expected_count}"
                )
            parsed_slices.append(
                ManifestSlice(
                    group_id=group_id,
                    count=count,
                    trainable_count=trainable_count,
                    appended_offset=offset_in_segment,
                )
            )
            consumed_members += count
            offset_in_segment += count
            if offset_in_segment == expected_count:
                segment_index += 1
                offset_in_segment = 0

        if sum(item.count for item in parsed_slices) != n_rollouts:
            raise ValueError(
                f"{context}.group_slices count sums to {sum(item.count for item in parsed_slices)}, "
                f"expected n_rollouts={n_rollouts}"
            )
        if sum(item.trainable_count for item in parsed_slices) != n_trainable:
            raise ValueError(
                f"{context}.group_slices trainable_count sums to "
                f"{sum(item.trainable_count for item in parsed_slices)}, expected n_trainable={n_trainable}"
            )
        attempts.append(
            BatchAttempt(
                batch_attempt=batch_attempt,
                optimizer_step=optimizer_step,
                eligible_to_ship=eligible_to_ship,
                n_rollouts=n_rollouts,
                n_trainable=n_trainable,
                group_slices=tuple(parsed_slices),
            )
        )
    return attempts, consumed_members


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        raise ValueError("Cannot compute a rate with a zero denominator")
    return numerator / denominator


def _mode_summary(
    groups: list[GroupRecord],
    counterfactuals: dict[str, GroupCounterfactual],
    attempts: list[BatchAttempt],
    *,
    mode: str,
) -> dict[str, Any]:
    if mode not in {"behavior", "shuffled"}:
        raise ValueError(f"Unsupported mode: {mode}")
    mixed_by_group = {
        group_id: (counterfactual.behavior_mixed if mode == "behavior" else counterfactual.shuffled_mixed)
        for group_id, counterfactual in counterfactuals.items()
    }
    replayed_attempts = []
    total_trainable = 0
    empty_attempts = 0
    for attempt in attempts:
        n_trainable = sum(
            group_slice.count for group_slice in attempt.group_slices if mixed_by_group[group_slice.group_id]
        )
        total_trainable += n_trainable
        empty = n_trainable == 0
        empty_attempts += empty
        replayed_attempts.append(
            {
                "batch_attempt": attempt.batch_attempt,
                "optimizer_step_on_observed_run": attempt.optimizer_step,
                "n_rollouts": attempt.n_rollouts,
                "n_trainable": n_trainable,
                "empty": empty,
            }
        )

    groups_with_advantage_population = [group for group in groups if group.advantage_indices]
    mixed_groups = sum(mixed_by_group[group.group_id] for group in groups_with_advantage_population)
    return {
        "groups_with_advantage_population": len(groups_with_advantage_population),
        "mixed_groups": mixed_groups,
        "mixed_group_rate": _rate(mixed_groups, len(groups_with_advantage_population)),
        "n_trainable_total": total_trainable,
        "n_trainable_mean_per_attempt": _rate(total_trainable, len(attempts)),
        "empty_attempts": empty_attempts,
        "empty_attempt_rate": _rate(empty_attempts, len(attempts)),
        "attempts": replayed_attempts,
    }


def analyze(
    group_stats_path: Path,
    batch_attempts_path: Path,
    probabilities: list[float],
) -> dict[str, Any]:
    if not probabilities:
        raise ValueError("At least one defect probability is required")
    for probability in probabilities:
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValueError(f"Defect probabilities must be finite and in [0, 1], got {probability}")
    if len(set(probabilities)) != len(probabilities):
        raise ValueError(f"Defect probabilities must be unique, got {probabilities}")

    groups = parse_groups(read_jsonl(group_stats_path))
    attempts, consumed_members = parse_attempts(read_jsonl(batch_attempts_path), groups)
    groups_by_id = {group.group_id: group for group in groups}
    total_appended_members = sum(len(group.appended_indices) for group in groups)

    observed_empty_attempts = sum(attempt.n_trainable == 0 for attempt in attempts)
    results = []
    for probability in probabilities:
        counterfactuals = {group.group_id: counterfactual_group(group, probability) for group in groups}
        k_histogram = Counter(counterfactual.behavior_trigger_count for counterfactual in counterfactuals.values())
        behavior_trigger_count = sum(
            counterfactual.behavior_trigger_count for counterfactual in counterfactuals.values()
        )
        triggers_in_advantage_population = sum(
            counterfactual.behavior_triggers_in_advantage_population for counterfactual in counterfactuals.values()
        )
        groups_with_triggers = sum(
            counterfactual.behavior_trigger_count > 0 for counterfactual in counterfactuals.values()
        )
        results.append(
            {
                "p": probability,
                "matching": {
                    "groups_checked": len(groups),
                    "behavior_trigger_count": behavior_trigger_count,
                    "behavior_triggers_in_advantage_population": triggers_in_advantage_population,
                    "groups_with_behavior_triggers": groups_with_triggers,
                    "groups_with_behavior_trigger_rate": _rate(groups_with_triggers, len(groups)),
                    "K_histogram": {str(key): k_histogram[key] for key in sorted(k_histogram)},
                    "full_group_reward_histogram_mismatches": 0,
                },
                "behavior_conditioned": _mode_summary(groups, counterfactuals, attempts, mode="behavior"),
                "per_group_shuffled": _mode_summary(groups, counterfactuals, attempts, mode="shuffled"),
            }
        )

    referenced_groups = {group_slice.group_id for attempt in attempts for group_slice in attempt.group_slices}
    return {
        "analysis": "fixed_rollout_zero_advantage_filter_replay",
        "inputs": {
            "train_group_stats": str(group_stats_path.resolve()),
            "train_batch_attempts": str(batch_attempts_path.resolve()),
        },
        "validation": {
            "groups": len(groups),
            "unique_group_ids": len(groups_by_id),
            "unique_trace_ids": sum(len(group.trace_ids) for group in groups),
            "groups_referenced_by_manifests": len(referenced_groups),
            "batch_attempts": len(attempts),
            "manifest_slices": sum(len(attempt.group_slices) for attempt in attempts),
            "appended_members": total_appended_members,
            "manifest_consumed_members": consumed_members,
            "unconsumed_appended_tail_members": total_appended_members - consumed_members,
        },
        "observed": {
            "n_rollouts_total": sum(attempt.n_rollouts for attempt in attempts),
            "n_trainable_total": sum(attempt.n_trainable for attempt in attempts),
            "empty_attempts": observed_empty_attempts,
            "empty_attempt_rate": _rate(observed_empty_attempts, len(attempts)),
            "eligible_to_ship_attempts": sum(attempt.eligible_to_ship for attempt in attempts),
        },
        "counterfactuals": results,
    }


def _probability(value: str) -> float:
    probability = float(value)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise argparse.ArgumentTypeError(f"must be finite and in [0, 1], got {value}")
    return probability


def _resolve_input_paths(run_or_rollout_dir: Path) -> tuple[Path, Path]:
    candidate_rollout_dirs = (
        run_or_rollout_dir,
        run_or_rollout_dir / "rollouts",
        run_or_rollout_dir / "run_default" / "rollouts",
    )
    rollout_dir = next(
        (candidate for candidate in candidate_rollout_dirs if (candidate / "train_group_stats.jsonl").is_file()),
        None,
    )
    if rollout_dir is None:
        searched = ", ".join(str(path / "train_group_stats.jsonl") for path in candidate_rollout_dirs)
        raise FileNotFoundError(f"Could not find verifier group audit logs; searched: {searched}")
    return rollout_dir / "train_group_stats.jsonl", rollout_dir / "train_batch_attempts.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "run_or_rollout_dir",
        type=Path,
        help="Experiment output, run_default/, or rollouts/ directory",
    )
    parser.add_argument(
        "--p",
        dest="probabilities",
        type=_probability,
        nargs="+",
        required=True,
        help="One or more conditional defect probabilities, for example: --p 0 0.01 0.05",
    )
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    group_stats_path, batch_attempts_path = _resolve_input_paths(args.run_or_rollout_dir)
    result = analyze(group_stats_path, batch_attempts_path, args.probabilities)
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        sys.stdout.write(payload)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
