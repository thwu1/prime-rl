#!/usr/bin/env python3
"""Replay and freeze the defect-withdrawal continuation ledgers."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_defect_withdrawal_training_ledger_audit"
STUDY_ID = "verifier-defect-withdrawal-v1"
OUTPUT_NAME = "training_ledger_audit.json"
SELF_HASH_FIELD = "payload_without_self_hash_sha256"
FORK_MANIFEST_NAME = "withdrawal_seed_manifest.json"
FORK_ARTIFACT_TYPE = "rsci_defect_withdrawal_seed_manifest"
ENVIRONMENT_NAME = "op10-40-strict"
STRICT_METRIC = "strict_dependency_graph_reward"
ARM_FALSE_POSITIVE_RATES = {
    "p05_on": 0.05,
    "p05_off": 0.0,
    "p00_clean": 0.0,
}
IMPLEMENTATION_REPOSITORY_PATH = "user/tianhaowu/rsci/audit_defect_withdrawal_training.py"


@dataclass(frozen=True)
class EndpointContract:
    step: int
    expected_new_updates: int
    off_minimum_informative_hard_clean_groups: int


@dataclass(frozen=True)
class AuditContract:
    source_step: int
    final_step: int
    group_size: int
    dataset_rows: int
    minimum_operation: int
    maximum_operation: int
    hard_minimum_operation: int
    hard_maximum_operation: int
    endpoints: tuple[EndpointContract, ...]


PRODUCTION_CONTRACT = AuditContract(
    source_step=4_000,
    final_step=4_375,
    group_size=128,
    dataset_rows=4_557,
    minimum_operation=10,
    maximum_operation=40,
    hard_minimum_operation=21,
    hard_maximum_operation=40,
    endpoints=(
        EndpointContract(
            step=4_250,
            expected_new_updates=250,
            off_minimum_informative_hard_clean_groups=250,
        ),
        EndpointContract(
            step=4_375,
            expected_new_updates=375,
            off_minimum_informative_hard_clean_groups=375,
        ),
    ),
)


@dataclass(frozen=True)
class DatasetTask:
    row_id: str
    operation: int


@dataclass(frozen=True)
class GroupRecord:
    group_id: str
    task_idx: int
    operation: int
    finalized_before_optimizer_step: int
    appended_size: int
    informative_hard_clean: bool


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _duplicate_key_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> Any:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def _parse_json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode(),
            object_pairs_hook=_duplicate_key_guard,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _regular_file(path: Path, label: str) -> Path:
    configured = path.expanduser().absolute()
    if configured.is_symlink() or not configured.is_file():
        raise ValueError(f"{label} must be a regular file: {configured}")
    return configured.resolve()


def _file_identity(path: Path, label: str) -> dict[str, Any]:
    resolved = _regular_file(path, label)
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    signature_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    signature_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    current = resolved.stat()
    signature_current = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
    if signature_before != signature_after or signature_before != signature_current:
        raise RuntimeError(f"{label} changed while it was hashed: {resolved}")
    return {
        "path": str(resolved),
        "size_bytes": before.st_size,
        "sha256": digest.hexdigest(),
    }


def _read_canonical_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = _regular_file(path, label)
    raw = resolved.read_bytes()
    value = _parse_json_object(raw, label)
    if raw != canonical_json_bytes(value):
        raise ValueError(f"{label} is not canonical JSON: {resolved}")
    identity = _file_identity(resolved, label)
    if identity["size_bytes"] != len(raw) or identity["sha256"] != hashlib.sha256(raw).hexdigest():
        raise RuntimeError(f"{label} changed while it was read: {resolved}")
    return value, identity


def _verify_self_hash(value: dict[str, Any], label: str) -> None:
    recorded = value.get(SELF_HASH_FIELD)
    unhashed = {key: item for key, item in value.items() if key != SELF_HASH_FIELD}
    if recorded != canonical_json_sha256(unhashed):
        raise ValueError(f"{label} self hash differs")


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _require_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _require_list(value: object, label: str, length: int | None = None) -> list[Any]:
    if not isinstance(value, list) or (length is not None and len(value) != length):
        suffix = "" if length is None else f" of length {length}"
        raise ValueError(f"{label} must be an array{suffix}")
    return value


def _stream_jsonl(path: Path, label: str) -> tuple[Iterator[tuple[int, dict[str, Any]]], dict[str, Any]]:
    resolved = _regular_file(path, label)
    handle = resolved.open("rb")
    before = os.fstat(handle.fileno())
    digest = hashlib.sha256()

    def rows() -> Iterator[tuple[int, dict[str, Any]]]:
        try:
            row_count = 0
            for row_count, raw in enumerate(handle, start=1):
                digest.update(raw)
                if not raw.endswith(b"\n"):
                    raise ValueError(f"{label} row {row_count} is not newline-terminated")
                if not raw.strip():
                    raise ValueError(f"{label} row {row_count} is empty")
                yield row_count, _parse_json_object(raw, f"{label} row {row_count}")
            if row_count == 0:
                raise ValueError(f"{label} is empty")
            after = os.fstat(handle.fileno())
            signature_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            signature_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            current = resolved.stat()
            signature_current = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            if signature_before != signature_after or signature_before != signature_current:
                raise RuntimeError(f"{label} changed while it was read: {resolved}")
        finally:
            handle.close()

    identity = {
        "path": str(resolved),
        "size_bytes": before.st_size,
        "sha256": digest,
    }
    return rows(), identity


def _finish_stream_identity(identity: dict[str, Any]) -> dict[str, Any]:
    digest = identity["sha256"]
    if not hasattr(digest, "hexdigest"):
        raise TypeError("JSONL stream identity was already finalized")
    return {**identity, "sha256": digest.hexdigest()}


def _scan_dataset(path: Path, contract: AuditContract) -> tuple[tuple[DatasetTask, ...], dict[str, Any]]:
    rows, pending_identity = _stream_jsonl(path, "continuation dataset")
    tasks = []
    seen_ids: set[str] = set()
    counts = {operation: 0 for operation in range(contract.minimum_operation, contract.maximum_operation + 1)}
    for row_number, row in rows:
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            raise ValueError(f"continuation dataset row {row_number}.id must be a non-empty string")
        if row_id in seen_ids:
            raise ValueError(f"continuation dataset row {row_number} repeats id {row_id!r}")
        seen_ids.add(row_id)
        operation = _require_int(row.get("op"), f"continuation dataset row {row_number}.op")
        if operation not in counts:
            raise ValueError(f"continuation dataset row {row_number} has OP{operation} outside the contract")
        counts[operation] += 1
        tasks.append(DatasetTask(row_id=row_id, operation=operation))
    identity = _finish_stream_identity(pending_identity)
    if len(tasks) != contract.dataset_rows:
        raise ValueError(f"continuation dataset has {len(tasks)} rows, expected {contract.dataset_rows}")
    operation_count = contract.maximum_operation - contract.minimum_operation + 1
    if contract.dataset_rows % operation_count:
        raise ValueError("dataset_rows must be divisible by the operation count")
    expected_per_operation = contract.dataset_rows // operation_count
    if any(count != expected_per_operation for count in counts.values()):
        raise ValueError(
            f"continuation dataset is not exactly balanced at {expected_per_operation} rows per operation: {counts}"
        )
    return tuple(tasks), {**identity, "rows": len(tasks), "rows_by_operation": {str(k): v for k, v in counts.items()}}


def _load_fork_and_config(
    arm: str,
    run_root: Path,
    contract: AuditContract,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    manifest_path = run_root / FORK_MANIFEST_NAME
    manifest, manifest_identity = _read_canonical_json(manifest_path, "withdrawal fork manifest")
    _verify_self_hash(manifest, "withdrawal fork manifest")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("artifact_type") != FORK_ARTIFACT_TYPE
        or manifest.get("arm") != arm
        or manifest.get("source_step") != contract.source_step
        or manifest.get("final_step") != contract.final_step
    ):
        raise ValueError("withdrawal fork manifest identity or clock contract differs")
    destination = manifest.get("destination")
    if not isinstance(destination, dict) or destination.get("root") != str(run_root):
        raise ValueError("withdrawal fork manifest destination differs from the audited run")

    config_path = run_root / "configs" / "orchestrator.toml"
    config_identity = _file_identity(config_path, "resolved orchestrator config")
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    expected_output = run_root / "run_default"
    if (
        config.get("output_dir") != str(expected_output)
        or config.get("max_steps") != contract.final_step
        or config.get("group_size") != contract.group_size
        or config.get("save_train_group_stats") is not True
        or config.get("train_source_max_epochs") != 1
    ):
        raise ValueError("resolved orchestrator ledger/no-wrap contract differs")
    checkpoint = config.get("ckpt")
    if not isinstance(checkpoint, dict) or checkpoint.get("resume_step") != contract.source_step:
        raise ValueError("resolved orchestrator resume step differs")
    train = config.get("train")
    environments = train.get("env") if isinstance(train, dict) else None
    if not isinstance(environments, list) or len(environments) != 1 or not isinstance(environments[0], dict):
        raise ValueError("resolved orchestrator must contain exactly one training environment")
    environment = environments[0]
    arguments = environment.get("args")
    if environment.get("name") != ENVIRONMENT_NAME or not isinstance(arguments, dict):
        raise ValueError("resolved training environment identity differs")
    expected_rate = ARM_FALSE_POSITIVE_RATES[arm]
    if (
        arguments.get("false_positive_rate") != expected_rate
        or arguments.get("min_op") != contract.minimum_operation
        or arguments.get("max_op") != contract.maximum_operation
        or arguments.get("require_unique_prompts") is not True
    ):
        raise ValueError("resolved training environment rate or dataset-range contract differs")
    dataset_path_value = arguments.get("dataset_path")
    if not isinstance(dataset_path_value, str):
        raise ValueError("resolved training dataset_path must be a string")
    dataset_path = Path(dataset_path_value).expanduser().resolve()
    training_dataset = destination.get("training_dataset")
    if not isinstance(training_dataset, dict):
        raise ValueError("withdrawal fork manifest lacks its training-dataset binding")
    return (
        {"identity": manifest_identity, "record": manifest, "training_dataset": training_dataset},
        {"identity": config_identity, "record": config},
        dataset_path,
    )


def _validate_dataset_binding(
    training_dataset: dict[str, Any],
    dataset: dict[str, Any],
    manifest_identity: dict[str, Any],
) -> None:
    recorded_dataset = training_dataset.get("dataset")
    comparable_dataset = {key: dataset[key] for key in ("path", "size_bytes", "sha256")}
    if recorded_dataset != comparable_dataset:
        raise ValueError("continuation dataset differs from the fork-bound identity")
    if training_dataset.get("adjacent_manifest") != manifest_identity:
        raise ValueError("continuation dataset manifest differs from the fork-bound identity")
    binding = training_dataset.get("manifest_dataset_binding")
    if not isinstance(binding, dict) or binding.get("path") != dataset["path"] or binding.get("sha256") != dataset["sha256"]:
        raise ValueError("continuation dataset manifest binding differs")


def _binary_metric(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be null or numeric binary")
    number = float(value)
    if not math.isfinite(number) or number not in (0.0, 1.0):
        raise ValueError(f"{label} must be null or numeric binary")
    return int(number)


def _scan_groups(
    path: Path,
    tasks: tuple[DatasetTask, ...],
    contract: AuditContract,
) -> tuple[tuple[GroupRecord, ...], dict[str, Any]]:
    rows, pending_identity = _stream_jsonl(path, "training group ledger")
    groups = []
    seen_group_ids: set[str] = set()
    seen_task_indices: set[int] = set()
    seen_sample_ids: set[str] = set()
    previous_cutoff = contract.source_step
    for row_number, row in rows:
        context = f"training group ledger row {row_number}"
        group_id = row.get("group_id")
        if not isinstance(group_id, str) or not group_id or group_id in seen_group_ids:
            raise ValueError(f"{context}.group_id must be non-empty and globally unique")
        seen_group_ids.add(group_id)
        if _require_int(row.get("group_index"), f"{context}.group_index", minimum=1) != row_number:
            raise ValueError(f"{context}.group_index is not contiguous")
        if row.get("env_name") != ENVIRONMENT_NAME:
            raise ValueError(f"{context}.env_name differs")
        task_idx = _require_int(row.get("task_idx"), f"{context}.task_idx")
        if task_idx >= len(tasks):
            raise ValueError(f"{context}.task_idx is outside the bound continuation dataset")
        if task_idx in seen_task_indices:
            raise ValueError(f"{context}.task_idx repeats continuation task {task_idx}")
        seen_task_indices.add(task_idx)
        expected_task = tasks[task_idx]
        if expected_task.row_id in seen_sample_ids:
            raise ValueError(f"{context} repeats continuation sample id {expected_task.row_id!r}")
        seen_sample_ids.add(expected_task.row_id)
        cutoff = _require_int(row.get("finalized_before_optimizer_step"), f"{context}.cutoff")
        if not contract.source_step <= cutoff <= contract.final_step or cutoff < previous_cutoff:
            raise ValueError(f"{context}.finalized_before_optimizer_step is outside or decreases")
        previous_cutoff = cutoff
        target_size = _require_int(row.get("target_size"), f"{context}.target_size", minimum=1)
        received_size = _require_int(row.get("received_size"), f"{context}.received_size", minimum=1)
        if target_size != contract.group_size or received_size != target_size:
            raise ValueError(f"{context} does not contain one complete physical group")
        sample_ids = _require_list(row.get("sample_ids"), f"{context}.sample_ids", received_size)
        operations = _require_list(row.get("operations"), f"{context}.operations", received_size)
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
        if _require_int(row.get("advantage_population_size"), f"{context}.advantage_population_size") != sum(
            in_advantage
        ):
            raise ValueError(f"{context}.advantage_population_size differs from its mask")
        for index, (sample_id, operation, is_error, in_population, was_appended) in enumerate(
            zip(sample_ids, operations, errored, in_advantage, appended, strict=True)
        ):
            if in_population and is_error:
                raise ValueError(f"{context} puts errored rollout {index} in the advantage population")
            if was_appended and not in_population:
                raise ValueError(f"{context} appends rollout {index} outside the advantage population")
            if not is_error and (
                sample_id != expected_task.row_id or operation != expected_task.operation
            ):
                raise ValueError(f"{context} rollout {index} differs from task_idx-bound dataset identity")
            if sample_id not in (None, expected_task.row_id):
                raise ValueError(f"{context} rollout {index} has a different sample identity")
            if operation not in (None, expected_task.operation):
                raise ValueError(f"{context} rollout {index} has a different operation")

        metrics = row.get("metrics")
        if not isinstance(metrics, dict):
            raise ValueError(f"{context}.metrics must be an object")
        strict_raw = metrics.get(STRICT_METRIC)
        if strict_raw is None and any(in_advantage):
            raise ValueError(f"{context}.metrics lacks {STRICT_METRIC}")
        strict_values = (
            [None] * received_size
            if strict_raw is None
            else [
                _binary_metric(value, f"{context}.metrics.{STRICT_METRIC}[{index}]")
                for index, value in enumerate(_require_list(strict_raw, f"{context}.metrics.{STRICT_METRIC}", received_size))
            ]
        )
        advantage_strict = []
        for index, in_population in enumerate(in_advantage):
            if not in_population:
                continue
            value = strict_values[index]
            if value is None:
                raise ValueError(f"{context} has a null strict reward in its advantage population")
            advantage_strict.append(value)
        informative = (
            contract.hard_minimum_operation <= expected_task.operation <= contract.hard_maximum_operation
            and set(advantage_strict) == {0, 1}
        )
        groups.append(
            GroupRecord(
                group_id=group_id,
                task_idx=task_idx,
                operation=expected_task.operation,
                finalized_before_optimizer_step=cutoff,
                appended_size=sum(appended),
                informative_hard_clean=informative,
            )
        )
    identity = _finish_stream_identity(pending_identity)
    return tuple(groups), identity


def _scan_attempts(
    path: Path,
    groups: tuple[GroupRecord, ...],
    contract: AuditContract,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rows, pending_identity = _stream_jsonl(path, "training batch-attempt ledger")
    appended_segments = [(group.group_id, group.appended_size) for group in groups if group.appended_size]
    group_by_id = {group.group_id: group for group in groups}
    segment_index = 0
    segment_offset = 0
    previous_step = contract.source_step
    eligible_steps: list[int] = []
    attempted_rollouts = 0
    trainable_rollouts = 0
    attempt_count = 0
    for row_number, row in rows:
        attempt_count = row_number
        context = f"training batch-attempt ledger row {row_number}"
        if _require_int(row.get("batch_attempt"), f"{context}.batch_attempt", minimum=1) != row_number:
            raise ValueError(f"{context}.batch_attempt is not contiguous")
        optimizer_step = _require_int(row.get("optimizer_step"), f"{context}.optimizer_step")
        if not contract.source_step <= optimizer_step <= contract.final_step or optimizer_step < previous_step:
            raise ValueError(f"{context}.optimizer_step is outside or decreases")
        previous_step = optimizer_step
        eligible = _require_bool(row.get("eligible_to_ship"), f"{context}.eligible_to_ship")
        n_rollouts = _require_int(row.get("n_rollouts"), f"{context}.n_rollouts", minimum=1)
        n_trainable = _require_int(row.get("n_trainable"), f"{context}.n_trainable")
        if n_trainable > n_rollouts:
            raise ValueError(f"{context}.n_trainable exceeds n_rollouts")
        expected_eligible = optimizer_step < contract.final_step and n_trainable > 0
        if eligible != expected_eligible:
            raise ValueError(f"{context}.eligible_to_ship differs from the completed-run clock contract")
        if eligible:
            eligible_steps.append(optimizer_step)
        slices = _require_list(row.get("group_slices"), f"{context}.group_slices")
        if not slices:
            raise ValueError(f"{context}.group_slices is empty")
        sliced_rollouts = 0
        sliced_trainable = 0
        for slice_index, raw_slice in enumerate(slices):
            slice_context = f"{context}.group_slices[{slice_index}]"
            if not isinstance(raw_slice, dict):
                raise ValueError(f"{slice_context} must be an object")
            group_id = raw_slice.get("group_id")
            if group_id not in group_by_id or segment_index >= len(appended_segments):
                raise ValueError(f"{slice_context} references an unavailable group")
            count = _require_int(raw_slice.get("count"), f"{slice_context}.count", minimum=1)
            trainable_count = _require_int(raw_slice.get("trainable_count"), f"{slice_context}.trainable_count")
            if trainable_count > count:
                raise ValueError(f"{slice_context}.trainable_count exceeds count")
            expected_group_id, expected_count = appended_segments[segment_index]
            if group_id != expected_group_id or count > expected_count - segment_offset:
                raise ValueError(f"{slice_context} does not consume the appended-group FIFO")
            if group_by_id[group_id].finalized_before_optimizer_step > optimizer_step:
                raise ValueError(f"{slice_context} consumes a group finalized after this optimizer step")
            segment_offset += count
            if segment_offset == expected_count:
                segment_index += 1
                segment_offset = 0
            sliced_rollouts += count
            sliced_trainable += trainable_count
        if (sliced_rollouts, sliced_trainable) != (n_rollouts, n_trainable):
            raise ValueError(f"{context} slice totals differ from its batch totals")
        attempted_rollouts += n_rollouts
        trainable_rollouts += n_trainable
    identity = _finish_stream_identity(pending_identity)
    expected_steps = list(range(contract.source_step, contract.final_step))
    if eligible_steps != expected_steps:
        missing = sorted(set(expected_steps) - set(eligible_steps))
        repeated = sorted(step for step in set(eligible_steps) if eligible_steps.count(step) > 1)
        unexpected = sorted(set(eligible_steps) - set(expected_steps))
        raise ValueError(
            "eligible optimizer steps differ from the exact continuation clock: "
            f"missing={missing}, repeated={repeated}, unexpected={unexpected}"
        )
    remaining_appended = sum(count for _group_id, count in appended_segments[segment_index:]) - segment_offset
    return (
        {
            "batch_attempt_records": attempt_count,
            "eligible_shipped_updates": len(eligible_steps),
            "eligible_optimizer_steps_sha256": hashlib.sha256(
                "".join(f"{step}\n" for step in eligible_steps).encode("ascii")
            ).hexdigest(),
            "attempted_rollouts": attempted_rollouts,
            "trainable_rollouts": trainable_rollouts,
            "consumed_appended_rollouts": sum(group.appended_size for group in groups) - remaining_appended,
            "unconsumed_appended_rollouts_at_clean_stop": remaining_appended,
            "eligible_steps": tuple(eligible_steps),
        },
        identity,
    )


def _checkpoint_evidence(run_root: Path, step: int) -> dict[str, Any]:
    root = run_root / "weights" / f"step_{step}"
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"checkpoint step {step} is not a regular directory: {root}")
    return {
        "path": str(root.resolve()),
        "stable_marker": _file_identity(root / "STABLE", f"checkpoint step {step} STABLE marker"),
        "config": _file_identity(root / "config.json", f"checkpoint step {step} config"),
    }


def _contract_record(contract: AuditContract) -> dict[str, Any]:
    return {
        "source_step": contract.source_step,
        "final_step": contract.final_step,
        "group_size": contract.group_size,
        "dataset_rows": contract.dataset_rows,
        "operation_range": [contract.minimum_operation, contract.maximum_operation],
        "informative_hard_operation_range": [
            contract.hard_minimum_operation,
            contract.hard_maximum_operation,
        ],
        "environment_name": ENVIRONMENT_NAME,
        "strict_metric": STRICT_METRIC,
        "endpoint_cutoff_rule": "finalized_before_optimizer_step < checkpoint_step",
        "informative_group_definition": (
            "task operation is in the informative hard range and the in-advantage-population "
            "strict reward set is exactly {0, 1}"
        ),
        "endpoints": [
            {
                "step": endpoint.step,
                "expected_new_updates": endpoint.expected_new_updates,
                "off_minimum_informative_hard_clean_groups": (
                    endpoint.off_minimum_informative_hard_clean_groups
                ),
            }
            for endpoint in contract.endpoints
        ],
    }


def build_audit(
    arm: str,
    run_root: Path,
    *,
    contract: AuditContract = PRODUCTION_CONTRACT,
) -> dict[str, Any]:
    if arm not in ARM_FALSE_POSITIVE_RATES:
        raise ValueError(f"Unknown withdrawal arm: {arm}")
    root = run_root.expanduser().resolve()
    if run_root.expanduser().absolute().is_symlink() or not root.is_dir():
        raise ValueError(f"Withdrawal run root must be a regular directory: {run_root}")
    fork, config, dataset_path = _load_fork_and_config(arm, root, contract)
    dataset_tasks, dataset_identity = _scan_dataset(dataset_path, contract)
    dataset_manifest_path = Path(f"{dataset_path}.manifest.json")
    dataset_manifest_identity = _file_identity(dataset_manifest_path, "continuation dataset manifest")
    _validate_dataset_binding(fork["training_dataset"], dataset_identity, dataset_manifest_identity)
    rollout_root = root / "run_default" / "rollouts"
    groups, group_identity = _scan_groups(rollout_root / "train_group_stats.jsonl", dataset_tasks, contract)
    attempt_summary, attempt_identity = _scan_attempts(
        rollout_root / "train_batch_attempts.jsonl",
        groups,
        contract,
    )
    endpoint_summaries = []
    for endpoint in contract.endpoints:
        endpoint_groups = [group for group in groups if group.finalized_before_optimizer_step < endpoint.step]
        informative = sum(group.informative_hard_clean for group in endpoint_groups)
        shipped = sum(step < endpoint.step for step in attempt_summary["eligible_steps"])
        minimum = endpoint.off_minimum_informative_hard_clean_groups if arm == "p05_off" else 0
        if shipped != endpoint.expected_new_updates:
            raise ValueError(
                f"step {endpoint.step} has {shipped} shipped updates, expected {endpoint.expected_new_updates}"
            )
        if informative < minimum:
            raise ValueError(
                f"step {endpoint.step} has {informative} informative hard clean groups, minimum {minimum}"
            )
        endpoint_summaries.append(
            {
                "checkpoint": _checkpoint_evidence(root, endpoint.step),
                "new_updates_shipped": shipped,
                "expected_new_updates": endpoint.expected_new_updates,
                "finalized_groups_before_checkpoint": len(endpoint_groups),
                "unique_task_ids_before_checkpoint": len(endpoint_groups),
                "no_repeated_task_ids_before_checkpoint": True,
                "informative_hard_clean_groups_before_checkpoint": informative,
                "minimum_informative_hard_clean_groups": minimum,
                "passes": True,
            }
        )
    ordered_task_indices = [group.task_idx for group in groups]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "study_id": STUDY_ID,
        "arm": arm,
        "run_root": str(root),
        "passed": True,
        "implementation": {
            "repository_path": IMPLEMENTATION_REPOSITORY_PATH,
            **{
                key: value
                for key, value in _file_identity(Path(__file__), "ledger-audit implementation").items()
                if key != "path"
            },
        },
        "contract": _contract_record(contract),
        "inputs": {
            "withdrawal_fork_manifest": fork["identity"],
            "resolved_orchestrator_config": config["identity"],
            "continuation_dataset": dataset_identity,
            "continuation_dataset_manifest": dataset_manifest_identity,
            "training_group_ledger": group_identity,
            "training_batch_attempt_ledger": attempt_identity,
        },
        "ledger_integrity": {
            "finalized_group_records": len(groups),
            "unique_task_indices": len(ordered_task_indices),
            "unique_sample_ids": len(ordered_task_indices),
            "no_repeated_task_ids_over_full_continuation": True,
            "ordered_task_indices_sha256": hashlib.sha256(
                "".join(f"{index}\n" for index in ordered_task_indices).encode("ascii")
            ).hexdigest(),
            **{key: value for key, value in attempt_summary.items() if key != "eligible_steps"},
        },
        "endpoint_audits": endpoint_summaries,
    }
    return {**payload, SELF_HASH_FIELD: canonical_json_sha256(payload)}


def _write_once(path: Path, content: bytes) -> None:
    configured = path.expanduser().absolute()
    if configured.is_symlink():
        raise ValueError(f"Refusing a symlink audit output: {configured}")
    configured.parent.mkdir(parents=True, exist_ok=True)
    lock_path = configured.with_suffix(configured.suffix + ".lock")
    with lock_path.open("a", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        if configured.exists():
            if not configured.is_file() or configured.read_bytes() != content:
                raise FileExistsError(f"Refusing to replace a different ledger audit: {configured}")
            if stat.S_IMODE(configured.stat().st_mode) & 0o222:
                raise ValueError(f"Existing ledger audit is writable: {configured}")
            return
        descriptor, temporary_name = tempfile.mkstemp(
            dir=configured.parent,
            prefix=f".{configured.name}.",
            suffix=".partial",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o444)
            os.link(temporary, configured)
        finally:
            temporary.unlink(missing_ok=True)


def materialize_audit(
    arm: str,
    run_root: Path,
    *,
    contract: AuditContract = PRODUCTION_CONTRACT,
) -> Path:
    audit = build_audit(arm, run_root, contract=contract)
    path = run_root.expanduser().resolve() / OUTPUT_NAME
    _write_once(path, canonical_json_bytes(audit))
    validate_audit(path, arm=arm, run_root=run_root, contract=contract)
    return path


def validate_audit(
    path: Path,
    *,
    arm: str,
    run_root: Path,
    contract: AuditContract = PRODUCTION_CONTRACT,
) -> dict[str, Any]:
    audit, _identity = _read_canonical_json(path, "training ledger audit")
    _verify_self_hash(audit, "training ledger audit")
    expected = build_audit(arm, run_root, contract=contract)
    if audit != expected:
        raise ValueError("training ledger audit differs from independent replay")
    if stat.S_IMODE(path.expanduser().resolve().stat().st_mode) & 0o222:
        raise ValueError("training ledger audit must be read-only")
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("materialize", "validate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--arm", required=True, choices=sorted(ARM_FALSE_POSITIVE_RATES))
        subparser.add_argument("--run-root", required=True, type=Path)
        if command == "validate":
            subparser.add_argument("--audit", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        result: object = {"audit": str(materialize_audit(args.arm, args.run_root))}
    else:
        result = validate_audit(args.audit, arm=args.arm, run_root=args.run_root)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
