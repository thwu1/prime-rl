#!/usr/bin/env python3
"""Measure verifier-defect curriculum rotation in legacy shipped rollout cohorts."""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import copy
import hashlib
import json
import math
import os
import tempfile
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson

EXPECTED_BATCH_ROWS = 512
EXPECTED_GROUP_SIZE = 128
PRIMARY_BANDS = ((10, 14), (15, 20), (21, 40))
ESTIMAND_ID = "saved_shipped_cohort_conditional"


@dataclass(frozen=True)
class FileSnapshot:
    step: int
    path: Path
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class ArmContract:
    label: str
    run_dir: Path
    rollout_dir: Path
    probability: float
    config_path: Path
    config_sha256: str
    configured_dataset: Path
    batch_rows: int = EXPECTED_BATCH_ROWS
    group_size: int = EXPECTED_GROUP_SIZE


@dataclass(frozen=True)
class Observation:
    task_idx: int
    step: int
    proxy: int
    strict: int
    answer_correct: int
    candidate: int
    trigger: int
    proxy_metric_explicit: bool
    candidate_metric_explicit: bool
    trigger_metric_explicit: bool


@dataclass
class GroupAggregate:
    task_idx: int
    operation: int
    saved_rows: int = 0
    proxy_positive: int = 0
    strict_positive: int = 0
    answer_correct: int = 0
    candidate: int = 0
    trigger: int = 0
    rows_by_step: dict[int, int] = field(default_factory=dict)

    def add(self, observation: Observation) -> None:
        self.saved_rows += 1
        self.proxy_positive += observation.proxy
        self.strict_positive += observation.strict
        self.answer_correct += observation.answer_correct
        self.candidate += observation.candidate
        self.trigger += observation.trigger
        self.rows_by_step[observation.step] = self.rows_by_step.get(observation.step, 0) + 1

    def merge(self, other: GroupAggregate) -> None:
        if self.task_idx != other.task_idx or self.operation != other.operation:
            raise ValueError("Cannot merge aggregates from different tasks")
        self.saved_rows += other.saved_rows
        self.proxy_positive += other.proxy_positive
        self.strict_positive += other.strict_positive
        self.answer_correct += other.answer_correct
        self.candidate += other.candidate
        self.trigger += other.trigger
        for step, count in other.rows_by_step.items():
            self.rows_by_step[step] = self.rows_by_step.get(step, 0) + count

    @property
    def first_step(self) -> int:
        return min(self.rows_by_step)

    @property
    def last_step(self) -> int:
        return max(self.rows_by_step)

    @property
    def anchor_step(self) -> int:
        target = (self.saved_rows - 1) // 2
        cumulative = 0
        for step, count in sorted(self.rows_by_step.items()):
            cumulative += count
            if cumulative > target:
                return step
        raise AssertionError("Group has no anchor step")


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binary_metric(value: Any, context: str) -> int:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric not in (0.0, 1.0):
        raise ValueError(f"{context} must be binary, got {value!r}")
    return int(numeric)


def parse_rollout_payload(payload: dict[str, Any], contract: ArmContract, step: int) -> Observation:
    if payload.get("is_completed") is not True:
        raise ValueError(f"{contract.label} step {step}: saved rollout is not completed")
    if payload.get("errors") != []:
        raise ValueError(f"{contract.label} step {step}: saved rollout contains errors")

    task = payload.get("task")
    rewards = payload.get("rewards")
    metrics = payload.get("metrics")
    if not isinstance(task, dict) or not isinstance(rewards, dict) or not isinstance(metrics, dict):
        raise ValueError(f"{contract.label} step {step}: rollout lacks task/rewards/metrics objects")
    task_idx = task.get("idx")
    if not isinstance(task_idx, int) or isinstance(task_idx, bool):
        raise ValueError(f"{contract.label} step {step}: task.idx is not an integer")

    reward = _binary_metric(rewards.get("reward"), "rewards.reward")
    strict = _binary_metric(metrics.get("strict_dependency_graph_reward"), "strict_dependency_graph_reward")
    answer_correct = _binary_metric(metrics.get("answer_correct_metric"), "answer_correct_metric")
    expected_candidate = int(answer_correct == 1 and strict == 0)

    proxy_metric_explicit = "proxy_reward" in metrics
    candidate_metric_explicit = "defect_candidate_metric" in metrics
    trigger_metric_explicit = "defect_triggered_metric" in metrics
    if contract.probability > 0 and not all(
        (proxy_metric_explicit, candidate_metric_explicit, trigger_metric_explicit, "defect_draw_metric" in metrics)
    ):
        raise ValueError(f"{contract.label} step {step}: defective arm lacks explicit defect audit metrics")

    proxy = _binary_metric(metrics["proxy_reward"], "proxy_reward") if proxy_metric_explicit else reward
    candidate = (
        _binary_metric(metrics["defect_candidate_metric"], "defect_candidate_metric")
        if candidate_metric_explicit
        else expected_candidate
    )
    trigger = (
        _binary_metric(metrics["defect_triggered_metric"], "defect_triggered_metric") if trigger_metric_explicit else 0
    )
    if reward != proxy:
        raise ValueError(f"{contract.label} step {step}: optimized reward does not equal proxy reward")
    if candidate != expected_candidate:
        raise ValueError(f"{contract.label} step {step}: candidate identity is violated")
    if trigger and not candidate:
        raise ValueError(f"{contract.label} step {step}: a non-candidate triggered")
    if proxy != max(strict, trigger):
        raise ValueError(f"{contract.label} step {step}: proxy=max(strict, trigger) is violated")
    draw = metrics.get("defect_draw_metric")
    if draw is not None:
        numeric_draw = float(draw)
        if not 0.0 <= numeric_draw < 1.0:
            raise ValueError(f"{contract.label} step {step}: defect draw is outside [0, 1)")
        if trigger != int(candidate and numeric_draw < contract.probability):
            raise ValueError(f"{contract.label} step {step}: trigger=(candidate and draw<p) is violated")

    return Observation(
        task_idx=task_idx,
        step=step,
        proxy=proxy,
        strict=strict,
        answer_correct=answer_correct,
        candidate=candidate,
        trigger=trigger,
        proxy_metric_explicit=proxy_metric_explicit,
        candidate_metric_explicit=candidate_metric_explicit,
        trigger_metric_explicit=trigger_metric_explicit,
    )


def _file_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "sha256": sha256_file(path),
    }


def load_dataset_operations(path: Path) -> tuple[list[int], dict[str, Any]]:
    path = path.expanduser().resolve()
    digest = hashlib.sha256()
    operations: list[int] = []
    size_bytes = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, 1):
            digest.update(line)
            size_bytes += len(line)
            payload = orjson.loads(line)
            operation = payload.get("op")
            if not isinstance(operation, int) or isinstance(operation, bool):
                raise ValueError(f"Dataset row {line_number} has invalid op={operation!r}")
            operations.append(operation)
    if not operations:
        raise ValueError(f"Dataset is empty: {path}")
    return operations, {
        "path": str(path),
        "size_bytes": size_bytes,
        "sha256": digest.hexdigest(),
        "rows": len(operations),
        "operation_counts": dict(sorted(collections.Counter(operations).items())),
    }


def _single_train_environment(config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    train = config.get("train")
    environments = train.get("env") if isinstance(train, dict) else None
    if not isinstance(environments, list) or len(environments) != 1 or not isinstance(environments[0], dict):
        raise ValueError(f"Expected exactly one training environment in {config_path}")
    return environments[0]


def load_arm_contract(label: str, run_dir: Path, train_dataset: Path) -> ArmContract:
    run_dir = run_dir.expanduser().resolve()
    config_path = run_dir / "configs" / "orchestrator.toml"
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    environment = _single_train_environment(config, config_path)
    args = environment.get("args")
    if not isinstance(args, dict):
        raise ValueError(f"Training environment lacks args in {config_path}")
    configured_dataset = Path(str(args.get("dataset_path", ""))).expanduser().resolve()
    if configured_dataset != train_dataset.resolve():
        raise ValueError(
            f"{label} configured dataset differs from requested dataset: {configured_dataset} != {train_dataset.resolve()}"
        )
    probability = float(args.get("false_positive_rate", 0.0))
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"{label} false_positive_rate is outside [0, 1]: {probability}")
    batch_rows = int(config.get("batch_size", -1))
    group_size = int(environment.get("group_size", config.get("group_size", -1)))
    if batch_rows != EXPECTED_BATCH_ROWS or group_size != EXPECTED_GROUP_SIZE:
        raise ValueError(
            f"{label} requires batch_size={EXPECTED_BATCH_ROWS}, group_size={EXPECTED_GROUP_SIZE}; "
            f"found {batch_rows}, {group_size}"
        )
    output_dir = Path(str(config.get("output_dir", ""))).expanduser().resolve()
    rollout_dir = output_dir / "rollouts"
    if not rollout_dir.is_dir():
        raise FileNotFoundError(f"Rollout directory does not exist: {rollout_dir}")
    return ArmContract(
        label=label,
        run_dir=run_dir,
        rollout_dir=rollout_dir,
        probability=probability,
        config_path=config_path,
        config_sha256=sha256_file(config_path),
        configured_dataset=configured_dataset,
        batch_rows=batch_rows,
        group_size=group_size,
    )


def snapshot_rollout_files(rollout_dir: Path, cutoff: int | None = None) -> list[FileSnapshot]:
    by_step: dict[int, Path] = {}
    for path in rollout_dir.glob("step_*/train_rollouts.jsonl"):
        step_text = path.parent.name.removeprefix("step_")
        if not step_text.isdigit():
            continue
        step = int(step_text)
        if step in by_step:
            raise ValueError(f"Duplicate rollout file for step {step} under {rollout_dir}")
        by_step[step] = path
    if not by_step:
        raise FileNotFoundError(f"No train_rollouts.jsonl files under {rollout_dir}")
    last_step = max(by_step) if cutoff is None else cutoff
    if last_step < 0:
        raise ValueError(f"Cutoff must be nonnegative, got {last_step}")
    expected = set(range(last_step + 1))
    missing = sorted(expected - set(by_step))
    if missing:
        raise ValueError(f"Rollout file prefix is not contiguous through step {last_step}; missing {missing[:20]}")
    snapshots = []
    for step in range(last_step + 1):
        path = by_step[step]
        stat = path.stat()
        snapshots.append(FileSnapshot(step=step, path=path, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns))
    return snapshots


def parse_rollout_file(
    snapshot: FileSnapshot,
    contract: ArmContract,
    dataset_operations: list[int],
) -> tuple[list[Observation], dict[str, Any], dict[str, int]]:
    before = snapshot.path.stat()
    if (before.st_size, before.st_mtime_ns) != (snapshot.size_bytes, snapshot.mtime_ns):
        raise RuntimeError(f"Rollout file changed after snapshot: {snapshot.path}")
    digest = hashlib.sha256()
    observations = []
    explicit = collections.Counter()
    with snapshot.path.open("rb") as handle:
        for line_number, line in enumerate(handle, 1):
            digest.update(line)
            payload = orjson.loads(line)
            observation = parse_rollout_payload(payload, contract, snapshot.step)
            if not 0 <= observation.task_idx < len(dataset_operations):
                raise ValueError(
                    f"{contract.label} step {snapshot.step} row {line_number}: task.idx={observation.task_idx} "
                    f"outside dataset of {len(dataset_operations)} rows"
                )
            observations.append(observation)
            explicit["proxy_metric_explicit"] += observation.proxy_metric_explicit
            explicit["candidate_metric_explicit"] += observation.candidate_metric_explicit
            explicit["trigger_metric_explicit"] += observation.trigger_metric_explicit
    after = snapshot.path.stat()
    if (after.st_size, after.st_mtime_ns) != (snapshot.size_bytes, snapshot.mtime_ns):
        raise RuntimeError(f"Rollout file changed while parsing: {snapshot.path}")
    if len(observations) != contract.batch_rows:
        raise ValueError(
            f"{contract.label} step {snapshot.step} has {len(observations)} rows; expected {contract.batch_rows}"
        )
    return (
        observations,
        {
            "step": snapshot.step,
            "size_bytes": snapshot.size_bytes,
            "mtime_ns": snapshot.mtime_ns,
            "sha256": digest.hexdigest(),
            "rows": len(observations),
        },
        dict(explicit),
    )


def reconstruct_groups(
    observations: list[Observation],
    dataset_operations: list[int],
    group_size: int = EXPECTED_GROUP_SIZE,
) -> tuple[list[GroupAggregate], list[dict[str, Any]], dict[str, Any]]:
    by_task_step: dict[tuple[int, int], GroupAggregate] = {}
    for observation in observations:
        operation = dataset_operations[observation.task_idx]
        key = (observation.task_idx, observation.step)
        aggregate = by_task_step.setdefault(
            key,
            GroupAggregate(task_idx=observation.task_idx, operation=operation),
        )
        aggregate.add(observation)

    by_task: dict[int, list[GroupAggregate]] = collections.defaultdict(list)
    for (task_idx, _), aggregate in sorted(by_task_step.items()):
        by_task[task_idx].append(aggregate)

    complete: list[GroupAggregate] = []
    fragments: list[dict[str, Any]] = []
    multiple_cluster_tasks = 0
    for task_idx, step_aggregates in sorted(by_task.items()):
        clusters: list[GroupAggregate] = []
        for aggregate in step_aggregates:
            if not clusters or aggregate.first_step > clusters[-1].last_step + 1:
                clusters.append(copy.deepcopy(aggregate))
            else:
                clusters[-1].merge(aggregate)
        multiple_cluster_tasks += int(len(clusters) > 1)
        for cluster in clusters:
            span = cluster.last_step - cluster.first_step
            if cluster.saved_rows == group_size and span <= 1:
                complete.append(cluster)
                continue
            reason = "incomplete_saved_fragment" if cluster.saved_rows < group_size else "ambiguous_overfull_cluster"
            fragments.append(
                {
                    "task_idx": task_idx,
                    "operation": cluster.operation,
                    "saved_rows": cluster.saved_rows,
                    "first_step": cluster.first_step,
                    "last_step": cluster.last_step,
                    "step_span": span,
                    "reason": reason,
                }
            )

    fragment_sizes = collections.Counter(item["saved_rows"] for item in fragments)
    fragment_operations = collections.Counter(item["operation"] for item in fragments)
    fragment_reasons = collections.Counter(item["reason"] for item in fragments)
    coverage = {
        "observed_task_indices": len(by_task),
        "reconstructed_task_step_clusters": len(complete) + len(fragments),
        "complete_exact_groups": len(complete),
        "complete_rows": len(complete) * group_size,
        "excluded_fragment_clusters": len(fragments),
        "excluded_fragment_rows": sum(item["saved_rows"] for item in fragments),
        "fragment_count_by_saved_rows": dict(sorted(fragment_sizes.items())),
        "fragment_count_by_operation": dict(sorted(fragment_operations.items())),
        "fragment_count_by_reason": dict(sorted(fragment_reasons.items())),
        "tasks_with_multiple_step_clusters": multiple_cluster_tasks,
        "complete_group_step_span_counts": dict(
            sorted(collections.Counter(group.last_step - group.first_step for group in complete).items())
        ),
        "fragment_examples": fragments[:20],
    }
    return complete, fragments, coverage


def _blank_operation_row() -> dict[str, int]:
    return {
        "raw_complete_groups": 0,
        "mixed_proxy_groups": 0,
        "mixed_strict_groups": 0,
        "defect_activated_groups": 0,
        "proxy_positive_rows": 0,
        "strict_positive_rows": 0,
        "answer_correct_rows": 0,
        "candidate_rows": 0,
        "trigger_rows": 0,
    }


def summarize_groups(groups: list[GroupAggregate], operation_values: list[int]) -> dict[str, Any]:
    by_operation = {operation: _blank_operation_row() for operation in operation_values}
    for group in groups:
        row = by_operation[group.operation]
        row["raw_complete_groups"] += 1
        row["mixed_proxy_groups"] += int(0 < group.proxy_positive < group.saved_rows)
        row["mixed_strict_groups"] += int(0 < group.strict_positive < group.saved_rows)
        row["defect_activated_groups"] += int(
            group.strict_positive == 0 and 0 < group.proxy_positive < group.saved_rows
        )
        row["proxy_positive_rows"] += group.proxy_positive
        row["strict_positive_rows"] += group.strict_positive
        row["answer_correct_rows"] += group.answer_correct
        row["candidate_rows"] += group.candidate
        row["trigger_rows"] += group.trigger

    def total(field: str) -> int:
        return sum(row[field] for row in by_operation.values())

    def mean_operation(field: str) -> float | None:
        denominator = total(field)
        if denominator == 0:
            return None
        return sum(operation * row[field] for operation, row in by_operation.items()) / denominator

    band_counts = {}
    for lower, upper in PRIMARY_BANDS:
        name = f"op{lower}_{upper}"
        band_counts[name] = {
            field: sum(row[field] for operation, row in by_operation.items() if lower <= operation <= upper)
            for field in (
                "raw_complete_groups",
                "mixed_proxy_groups",
                "mixed_strict_groups",
                "defect_activated_groups",
                "strict_positive_rows",
                "candidate_rows",
                "trigger_rows",
            )
        }

    complete_groups = total("raw_complete_groups")
    mixed_groups = total("mixed_proxy_groups")
    candidates = total("candidate_rows")
    return {
        "estimand": ESTIMAND_ID,
        "summary": {
            "raw_complete_groups": complete_groups,
            "mixed_proxy_groups": mixed_groups,
            "mixed_strict_groups": total("mixed_strict_groups"),
            "defect_activated_groups": total("defect_activated_groups"),
            "proxy_positive_rows": total("proxy_positive_rows"),
            "strict_positive_rows": total("strict_positive_rows"),
            "answer_correct_rows": total("answer_correct_rows"),
            "candidate_rows": candidates,
            "trigger_rows": total("trigger_rows"),
            "mixed_proxy_fraction_of_complete": mixed_groups / complete_groups if complete_groups else None,
            "trigger_fraction_of_candidates": total("trigger_rows") / candidates if candidates else None,
            "mean_operation_raw_complete": mean_operation("raw_complete_groups"),
            "mean_operation_mixed_proxy": mean_operation("mixed_proxy_groups"),
            "mean_operation_mixed_strict": mean_operation("mixed_strict_groups"),
            "mean_operation_defect_activated": mean_operation("defect_activated_groups"),
        },
        "bands": band_counts,
        "by_operation": {str(operation): by_operation[operation] for operation in operation_values},
    }


def build_windows(
    groups: list[GroupAggregate],
    min_operation: int,
    max_operation: int,
    max_step: int,
    common_end_step: int,
    window_size: int,
) -> dict[str, Any]:
    operation_values = list(range(min_operation, max_operation + 1))
    windows: dict[str, tuple[int, int]] = {
        "all": (0, max_step),
        "common": (0, common_end_step),
        "early": (0, window_size - 1),
        "late": (common_end_step - window_size + 1, common_end_step),
    }
    for start in range(0, max_step + 1, window_size):
        end = min(start + window_size - 1, max_step)
        windows[f"steps_{start:04d}_{end:04d}"] = (start, end)
    output = {}
    for name, (start, end) in windows.items():
        selected = [group for group in groups if start <= group.anchor_step <= end]
        output[name] = {
            "step_start": start,
            "step_end": end,
            **summarize_groups(selected, operation_values),
        }
    return output


def analyze_arm_snapshot(
    contract: ArmContract,
    snapshots: list[FileSnapshot],
    dataset_operations: list[int],
    common_end_step: int,
    window_size: int,
) -> dict[str, Any]:
    observations: list[Observation] = []
    file_identities = []
    explicit_counts = collections.Counter()
    for snapshot in snapshots:
        file_observations, identity, counts = parse_rollout_file(snapshot, contract, dataset_operations)
        observations.extend(file_observations)
        file_identities.append(identity)
        explicit_counts.update(counts)
    complete, _, group_coverage = reconstruct_groups(observations, dataset_operations, contract.group_size)
    min_operation = min(dataset_operations)
    max_operation = max(dataset_operations)
    windows = build_windows(
        complete,
        min_operation,
        max_operation,
        snapshots[-1].step,
        common_end_step,
        window_size,
    )
    rollout_manifest_payload = [
        {"step": row["step"], "size_bytes": row["size_bytes"], "sha256": row["sha256"]} for row in file_identities
    ]
    return {
        "label": contract.label,
        "probability": contract.probability,
        "run_dir": str(contract.run_dir),
        "rollout_dir": str(contract.rollout_dir),
        "config": {
            "path": str(contract.config_path),
            "size_bytes": contract.config_path.stat().st_size,
            "sha256": contract.config_sha256,
        },
        "rollout_manifest": {
            "step_start": snapshots[0].step,
            "step_end": snapshots[-1].step,
            "file_count": len(file_identities),
            "row_count": len(observations),
            "size_bytes": sum(row["size_bytes"] for row in file_identities),
            "sha256": canonical_json_sha256(rollout_manifest_payload),
            "files": file_identities,
        },
        "metric_provenance": {
            "rows": len(observations),
            **dict(sorted(explicit_counts.items())),
            "clean_arm_proxy_fallback": "rewards.reward=strict" if contract.probability == 0 else None,
            "clean_arm_candidate_fallback": (
                "answer_correct_metric=1 and strict_dependency_graph_reward=0" if contract.probability == 0 else None
            ),
        },
        "group_coverage": group_coverage,
        "windows": windows,
    }


def _parse_labeled_values(values: list[str], value_name: str) -> dict[str, str]:
    parsed = {}
    for value in values:
        label, separator, raw = value.partition("=")
        if not separator or not label or not raw:
            raise ValueError(f"{value_name} must use LABEL=VALUE, got {value!r}")
        if label in parsed:
            raise ValueError(f"Duplicate {value_name} label: {label}")
        parsed[label] = raw
    return parsed


def _common_comparison(arms: dict[str, Any], control_label: str) -> dict[str, Any]:
    comparison = {}
    control = arms[control_label]["windows"]["common"]["summary"]
    for label, arm in arms.items():
        current = arm["windows"]["common"]
        summary = current["summary"]
        hard = current["bands"]["op21_40"]
        mixed = summary["mixed_proxy_groups"]
        raw = summary["raw_complete_groups"]
        values = {
            "raw_complete_groups": raw,
            "mixed_proxy_groups": mixed,
            "defect_activated_groups": summary["defect_activated_groups"],
            "hard_raw_share": hard["raw_complete_groups"] / raw if raw else None,
            "hard_mixed_share": hard["mixed_proxy_groups"] / mixed if mixed else None,
            "hard_mixed_groups": hard["mixed_proxy_groups"],
            "hard_defect_activated_groups": hard["defect_activated_groups"],
            "mean_operation_mixed_proxy": summary["mean_operation_mixed_proxy"],
        }
        control_mean = control["mean_operation_mixed_proxy"]
        values["delta_mean_operation_mixed_vs_control"] = (
            values["mean_operation_mixed_proxy"] - control_mean
            if values["mean_operation_mixed_proxy"] is not None and control_mean is not None
            else None
        )
        comparison[label] = values
    return comparison


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-dataset", type=Path, required=True)
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=RUN_DIR",
        help="Repeat for each labeled legacy run directory.",
    )
    parser.add_argument(
        "--cutoff",
        action="append",
        default=[],
        metavar="LABEL=STEP",
        help="Optional inclusive optimizer-step cutoff per arm.",
    )
    parser.add_argument("--window-size", type=int, default=300)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.window_size <= 0:
        raise ValueError("--window-size must be positive")
    run_values = _parse_labeled_values(args.run, "run")
    cutoff_values = _parse_labeled_values(args.cutoff, "cutoff")
    unknown_cutoffs = sorted(set(cutoff_values) - set(run_values))
    if unknown_cutoffs:
        raise ValueError(f"Cutoffs have no matching runs: {unknown_cutoffs}")

    train_dataset = args.train_dataset.expanduser().resolve()
    dataset_operations, dataset_identity = load_dataset_operations(train_dataset)
    contracts = {
        label: load_arm_contract(label, Path(path), train_dataset) for label, path in sorted(run_values.items())
    }
    snapshots = {
        label: snapshot_rollout_files(
            contract.rollout_dir,
            int(cutoff_values[label]) if label in cutoff_values else None,
        )
        for label, contract in contracts.items()
    }
    minimum_max_step = min(files[-1].step for files in snapshots.values())
    complete_windows = (minimum_max_step + 1) // args.window_size
    if complete_windows == 0:
        raise ValueError("Runs do not contain one complete comparison window")
    common_end_step = complete_windows * args.window_size - 1
    snapshot_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    workers = args.workers or min(len(contracts), max(1, os.cpu_count() or 1), 4)
    work = [
        (contracts[label], snapshots[label], dataset_operations, common_end_step, args.window_size)
        for label in sorted(contracts)
    ]
    if workers == 1:
        results = [analyze_arm_snapshot(*item) for item in work]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(analyze_arm_snapshot, *item) for item in work]
            results = [future.result() for future in futures]
    arms = {result["label"]: result for result in results}
    control_label = min(contracts, key=lambda label: (contracts[label].probability, label))
    analyzer_identity = _file_identity(Path(__file__).resolve())
    manifest_payload = {
        "analyzer_sha256": analyzer_identity["sha256"],
        "dataset_sha256": dataset_identity["sha256"],
        "window_size": args.window_size,
        "common_end_step": common_end_step,
        "arms": {
            label: {
                "probability": arm["probability"],
                "config_sha256": arm["config"]["sha256"],
                "rollout_manifest_sha256": arm["rollout_manifest"]["sha256"],
                "step_end": arm["rollout_manifest"]["step_end"],
            }
            for label, arm in sorted(arms.items())
        },
    }
    output = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "snapshot_at": snapshot_at,
        "estimand": {
            "id": ESTIMAND_ID,
            "population": (
                "Exactly-128-row task-step clusters observable in saved train_rollouts.jsonl files from "
                "shipped nonempty optimizer cohorts."
            ),
            "not_identified": [
                "All attempted prompt groups: zero-trainable batch attempts have no saved rollout file.",
                "Errored or pre-batch-filtered rollouts absent from shipped cohorts.",
                "Population prevalence of trainability or verifier defects over all dispatched trajectories.",
            ],
            "group_identity_limitation": (
                "Legacy traces omit group UUID and rollout slot. Rows are conservatively clustered by task.idx "
                "across the same or adjacent optimizer-step files; non-128 and overfull clusters are excluded."
            ),
        },
        "analysis": {
            "batch_rows": EXPECTED_BATCH_ROWS,
            "group_size": EXPECTED_GROUP_SIZE,
            "window_size": args.window_size,
            "primary_bands": [list(band) for band in PRIMARY_BANDS],
            "common_step_start": 0,
            "common_step_end": common_end_step,
            "control_label": control_label,
            "manifest_sha256": canonical_json_sha256(manifest_payload),
            "manifest": manifest_payload,
        },
        "analyzer": analyzer_identity,
        "dataset": dataset_identity,
        "arms": arms,
        "common_step_comparison": _common_comparison(arms, control_label),
    }

    encoded = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
        return
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=output_path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    temporary.replace(output_path)
    print(output_path)


if __name__ == "__main__":
    main()
