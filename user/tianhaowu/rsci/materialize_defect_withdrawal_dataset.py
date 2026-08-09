#!/usr/bin/env python3
"""Materialize and replay-validate a gradient-unseen withdrawal dataset."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, BinaryIO

import orjson
import torch

SCHEMA_VERSION = 1
ARTIFACT_TYPE = "rsci_defect_withdrawal_gradient_unseen_dataset"
SELF_HASH_FIELD = "payload_without_self_hash_sha256"
SOURCE_STEP = 4000
SOURCE_STEPS = 4000
MIN_OPERATION = 10
MAX_OPERATION = 40
QUOTA_PER_OPERATION = 147
PRODUCTION_STRATA = tuple(
    (template, mode)
    for template in ("crazy_zootopia", "movie_festival_awards", "teachers_in_school")
    for mode in ("forwardreverse", "normalforward")
)
SELECTION_RANK_DOMAIN = b"defect-withdrawal-v1-gradient-unseen-step4000-hash-rank-v1\0"
EXPECTED_EXCLUDED_INDICES_SHA256 = "e79c4adfdbe634c633ba121cc5f560d64cd3a2bfbb66382c586e14e74efdfbfb"
EXPECTED_SOURCE_OVERLAP_SHA256 = "b95c81bf4b637e0e56c54e4fe67f856b77acf22eb7c25ab5040dbade4be92c50"
EXPECTED_SELECTED_INDICES_SHA256 = "de04928fa4a114691d78402f6860eb8142e70530cdaf5d2d510cc08ce9b9bc4c"
EXPECTED_AVAILABLE_ROWS_TOTAL = 7_778
UPDATES = 375
GROUPS_PER_UPDATE = 4
INFLIGHT_GROUPS = 64
MINIMUM_TASK_PULL_CAPACITY = UPDATES * GROUPS_PER_UPDATE + INFLIGHT_GROUPS
EXPECTED_TOTAL_SAMPLES = 2_048_000
DATASET_ROOT = Path("/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/op10-40-balanced-31k")
OUTPUT_PATH = Path(
    "/checkpoint/ram-h100-2/tianhaowu/rsci/data/rl/defect-withdrawal-v1/unseen-gradient-step4000/train.jsonl"
)


@dataclass(frozen=True)
class SourceSpec:
    label: str
    root: Path
    expected_total_samples: int
    expected_total_problems: int


@dataclass(frozen=True)
class MaterializationSpec:
    dataset_path: Path
    dataset_manifest_path: Path
    audit_path: Path
    output_path: Path
    sources: tuple[SourceSpec, ...]
    step_count: int
    progress_step: int
    min_operation: int
    max_operation: int
    quota_per_operation: int
    strata: tuple[tuple[str, str], ...]
    minimum_task_pull_capacity: int
    expected_excluded_indices_sha256: str | None
    expected_source_overlap_sha256: str | None
    expected_selected_indices_sha256: str | None
    expected_available_rows_total: int | None
    implementation_path: Path


@dataclass(frozen=True)
class DatasetRow:
    index: int
    operation: int
    row_id: str
    template: str
    mode: str
    task_fingerprint: bytes
    id_fingerprint: bytes
    prompt_fingerprint: bytes


@dataclass(frozen=True)
class DatasetScan:
    rows: tuple[DatasetRow, ...]
    identity: dict[str, Any]
    rows_by_operation: dict[int, int]
    rows_by_stratum: dict[tuple[int, str, str], int]
    unique_ids: int
    unique_prompts: int


def production_spec() -> MaterializationSpec:
    run_prefix = "/checkpoint/ram-h100-2/tianhaowu/rsci/rl/base-op10-40-strict-r128-defect-answer"
    return MaterializationSpec(
        dataset_path=DATASET_ROOT / "train.jsonl",
        dataset_manifest_path=DATASET_ROOT / "dataset_manifest.json",
        audit_path=DATASET_ROOT / "audit.json",
        output_path=OUTPUT_PATH,
        sources=(
            SourceSpec(
                label="p00",
                root=Path(f"{run_prefix}-p00-eval11-45-v2"),
                expected_total_samples=EXPECTED_TOTAL_SAMPLES,
                expected_total_problems=16_000,
            ),
            SourceSpec(
                label="p05",
                root=Path(f"{run_prefix}-p05-eval11-45-v2"),
                expected_total_samples=EXPECTED_TOTAL_SAMPLES,
                expected_total_problems=20_140,
            ),
        ),
        step_count=SOURCE_STEPS,
        progress_step=SOURCE_STEP,
        min_operation=MIN_OPERATION,
        max_operation=MAX_OPERATION,
        quota_per_operation=QUOTA_PER_OPERATION,
        strata=PRODUCTION_STRATA,
        minimum_task_pull_capacity=MINIMUM_TASK_PULL_CAPACITY,
        expected_excluded_indices_sha256=EXPECTED_EXCLUDED_INDICES_SHA256,
        expected_source_overlap_sha256=EXPECTED_SOURCE_OVERLAP_SHA256,
        expected_selected_indices_sha256=EXPECTED_SELECTED_INDICES_SHA256,
        expected_available_rows_total=EXPECTED_AVAILABLE_ROWS_TOTAL,
        implementation_path=Path(__file__).resolve(),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("materialize")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", required=True, type=Path)
    return parser.parse_args()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    return resolved


def _small_file_identity(path: Path) -> dict[str, Any]:
    resolved = _regular_file(path)
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(_regular_file(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _task_fingerprint(prompt: str, answer: str) -> bytes:
    digest = hashlib.sha256()
    for value in (prompt, answer):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.digest()


def _index_digest(indices: set[int] | list[int] | tuple[int, ...]) -> str:
    digest = hashlib.sha256()
    for index in sorted(indices):
        digest.update(f"{index}\n".encode("ascii"))
    return digest.hexdigest()


def _stratum_records(counts: dict[tuple[int, str, str], int]) -> list[dict[str, Any]]:
    return [
        {
            "operation": operation,
            "template": template,
            "mode": mode,
            "rows": rows,
        }
        for (operation, template, mode), rows in sorted(counts.items())
    ]


def _scan_original_dataset(spec: MaterializationSpec) -> DatasetScan:
    path = _regular_file(spec.dataset_path)
    digest = hashlib.sha256()
    size_bytes = 0
    rows: list[DatasetRow] = []
    rows_by_operation = {operation: 0 for operation in range(spec.min_operation, spec.max_operation + 1)}
    rows_by_stratum = {
        (operation, template, mode): 0
        for operation in range(spec.min_operation, spec.max_operation + 1)
        for template, mode in spec.strata
    }
    id_fingerprints: set[bytes] = set()
    prompt_fingerprints: set[bytes] = set()

    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        for index, raw in enumerate(handle):
            if not raw.endswith(b"\n"):
                raise ValueError(f"Dataset row {index} is not newline-terminated: {path}")
            digest.update(raw)
            size_bytes += len(raw)
            row = orjson.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"Dataset row {index} is not an object: {path}")
            operation = row.get("op")
            row_id = row.get("id")
            prompt = row.get("prompt")
            answer = row.get("answer")
            template = row.get("template")
            mode = row.get("mode")
            if isinstance(operation, bool) or not isinstance(operation, int):
                raise ValueError(f"Dataset row {index} has invalid op: {operation!r}")
            if operation not in rows_by_operation:
                raise ValueError(f"Dataset row {index} has out-of-range op: {operation}")
            if not isinstance(row_id, str) or not row_id:
                raise ValueError(f"Dataset row {index} has invalid id")
            if not isinstance(prompt, str) or not prompt:
                raise ValueError(f"Dataset row {index} has invalid prompt")
            if not isinstance(answer, str) or not answer:
                raise ValueError(f"Dataset row {index} has invalid answer")
            if not isinstance(template, str) or not isinstance(mode, str) or (template, mode) not in spec.strata:
                raise ValueError(f"Dataset row {index} has invalid template/mode stratum: {(template, mode)!r}")
            id_fingerprint = hashlib.sha256(row_id.encode("utf-8")).digest()
            prompt_fingerprint = hashlib.sha256(prompt.encode("utf-8")).digest()
            id_fingerprints.add(id_fingerprint)
            prompt_fingerprints.add(prompt_fingerprint)
            rows_by_operation[operation] += 1
            rows_by_stratum[(operation, template, mode)] += 1
            rows.append(
                DatasetRow(
                    index=index,
                    operation=operation,
                    row_id=row_id,
                    template=template,
                    mode=mode,
                    task_fingerprint=_task_fingerprint(prompt, answer),
                    id_fingerprint=id_fingerprint,
                    prompt_fingerprint=prompt_fingerprint,
                )
            )
        after = os.fstat(handle.fileno())
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RuntimeError(f"Dataset changed while it was scanned: {path}")

    return DatasetScan(
        rows=tuple(rows),
        identity={
            "path": str(path),
            "bytes": size_bytes,
            "rows": len(rows),
            "sha256": digest.hexdigest(),
        },
        rows_by_operation=rows_by_operation,
        rows_by_stratum=rows_by_stratum,
        unique_ids=len(id_fingerprints),
        unique_prompts=len(prompt_fingerprints),
    )


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} must be {expected!r}, found {actual!r}")


def _validate_original_manifests(
    spec: MaterializationSpec,
    scan: DatasetScan,
) -> dict[str, Any]:
    dataset_manifest = _load_json_object(spec.dataset_manifest_path)
    audit = _load_json_object(spec.audit_path)
    files = dataset_manifest.get("files")
    if not isinstance(files, dict) or not isinstance(files.get("train"), dict):
        raise ValueError(f"Dataset manifest has no files.train: {spec.dataset_manifest_path}")
    declared_train = files["train"]
    audit_train = audit.get("train")
    if not isinstance(audit_train, dict):
        raise ValueError(f"Dataset audit has no train record: {spec.audit_path}")
    for label, record in (("dataset manifest", declared_train), ("dataset audit", audit_train)):
        _require_equal(
            str(Path(record.get("path", "")).expanduser().resolve()),
            scan.identity["path"],
            f"{label} train path",
        )
        _require_equal(record.get("rows"), scan.identity["rows"], f"{label} train rows")
        _require_equal(record.get("sha256"), scan.identity["sha256"], f"{label} train sha256")
    _require_equal(audit_train.get("unique_ids"), scan.unique_ids, "dataset audit unique_ids")
    _require_equal(audit_train.get("unique_prompts"), scan.unique_prompts, "dataset audit unique_prompts")
    declared_by_op = audit_train.get("by_op")
    if not isinstance(declared_by_op, dict):
        raise ValueError(f"Dataset audit has no train.by_op: {spec.audit_path}")
    expected_by_op = {str(key): value for key, value in scan.rows_by_operation.items()}
    _require_equal(declared_by_op, expected_by_op, "dataset audit train.by_op")
    _require_equal(scan.unique_ids, scan.identity["rows"], "original dataset unique IDs")
    _require_equal(scan.unique_prompts, scan.identity["rows"], "original dataset unique prompts")
    return {
        "train": scan.identity,
        "dataset_manifest": _small_file_identity(spec.dataset_manifest_path),
        "audit": _small_file_identity(spec.audit_path),
        "rows_by_operation": expected_by_op,
        "rows_by_stratum": _stratum_records(scan.rows_by_stratum),
        "unique_ids": scan.unique_ids,
        "unique_prompts": scan.unique_prompts,
    }


def _progress_values(path: Path) -> tuple[dict[str, int], dict[str, Any]]:
    resolved = _regular_file(path)
    payload = torch.load(resolved, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict) or "progress" not in payload:
        raise ValueError(f"Checkpoint has no progress object: {resolved}")
    progress = payload["progress"]

    def value(name: str) -> int:
        raw = progress.get(name) if isinstance(progress, dict) else getattr(progress, name, None)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"Checkpoint progress has invalid {name}: {raw!r}")
        return raw

    values = {
        "step": value("step"),
        "total_tokens": value("total_tokens"),
        "total_samples": value("total_samples"),
        "total_problems": value("total_problems"),
    }
    return values, _small_file_identity(resolved)


def _scan_rollout_file(
    path: Path,
    dataset_rows: tuple[DatasetRow, ...],
) -> tuple[dict[str, Any], set[int]]:
    resolved = _regular_file(path)
    digest = hashlib.sha256()
    size_bytes = 0
    row_count = 0
    task_indices: set[int] = set()
    with resolved.open("rb") as handle:
        before = os.fstat(handle.fileno())
        for line_number, raw in enumerate(handle, start=1):
            if not raw.endswith(b"\n"):
                raise ValueError(f"Rollout row {line_number} is not newline-terminated: {resolved}")
            digest.update(raw)
            size_bytes += len(raw)
            row_count += 1
            row = orjson.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"Rollout row {line_number} is not an object: {resolved}")
            if row.get("is_completed") is not True:
                raise ValueError(f"Rollout row {line_number} is incomplete: {resolved}")
            if row.get("errors") != []:
                raise ValueError(f"Rollout row {line_number} has errors: {resolved}")
            task = row.get("task")
            if not isinstance(task, dict):
                raise ValueError(f"Rollout row {line_number} has no task object: {resolved}")
            index = task.get("idx")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(dataset_rows):
                raise ValueError(f"Rollout row {line_number} has invalid task.idx {index!r}: {resolved}")
            prompt = task.get("prompt")
            answer = task.get("answer")
            if not isinstance(prompt, str) or not isinstance(answer, str):
                raise ValueError(f"Rollout row {line_number} has invalid task prompt/answer: {resolved}")
            if _task_fingerprint(prompt, answer) != dataset_rows[index].task_fingerprint:
                raise ValueError(
                    f"Rollout row {line_number} task.idx={index} does not match the original prompt/answer: {resolved}"
                )
            task_indices.add(index)
        after = os.fstat(handle.fileno())
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RuntimeError(f"Rollout file changed while it was scanned: {resolved}")
    return {
        "bytes": size_bytes,
        "rows": row_count,
        "sha256": digest.hexdigest(),
    }, task_indices


def _scan_source(
    spec: MaterializationSpec,
    source: SourceSpec,
    dataset_rows: tuple[DatasetRow, ...],
) -> tuple[dict[str, Any], set[int]]:
    root = source.root.expanduser().resolve()
    if source.root.is_symlink() or not root.is_dir():
        raise ValueError(f"Expected a regular source directory: {source.root}")
    progress_path = root / f"run_default/checkpoints/step_{spec.progress_step}/orchestrator/progress.pt"
    progress, progress_identity = _progress_values(progress_path)
    _require_equal(progress["step"], spec.progress_step, f"{source.label} progress.step")
    _require_equal(progress["total_samples"], source.expected_total_samples, f"{source.label} progress.total_samples")
    _require_equal(
        progress["total_problems"], source.expected_total_problems, f"{source.label} progress.total_problems"
    )

    file_records: list[dict[str, Any]] = []
    union_indices: set[int] = set()
    total_rows = 0
    total_bytes = 0
    per_step_unique_total = 0
    for step in range(spec.step_count):
        relative = Path("run_default/rollouts") / f"step_{step}" / "train_rollouts.jsonl"
        identity, step_indices = _scan_rollout_file(root / relative, dataset_rows)
        record = {"step": step, "relative_path": relative.as_posix(), **identity}
        file_records.append(record)
        total_rows += identity["rows"]
        total_bytes += identity["bytes"]
        per_step_unique_total += len(step_indices)
        union_indices.update(step_indices)

    _require_equal(total_rows, progress["total_samples"], f"{source.label} shipped rollout rows")
    _require_equal(
        per_step_unique_total,
        progress["total_problems"],
        f"{source.label} sum of per-step unique task indices",
    )
    return {
        "label": source.label,
        "root": str(root),
        "expected_total_samples": source.expected_total_samples,
        "expected_total_problems": source.expected_total_problems,
        "progress": {**progress, "file": progress_identity},
        "shipped_rollout_files": {
            "path_pattern": "run_default/rollouts/step_{step}/train_rollouts.jsonl",
            "first_step": 0,
            "last_step": spec.step_count - 1,
            "file_count": len(file_records),
            "total_bytes": total_bytes,
            "total_rows": total_rows,
            "sum_per_step_unique_task_indices": per_step_unique_total,
            "union_unique_task_indices": len(union_indices),
            "union_task_indices_sha256": _index_digest(union_indices),
            "task_index_digest_encoding": ("ascending zero-based decimal indices, one ASCII index and newline per row"),
            "file_records_aggregate_sha256": canonical_json_sha256(file_records),
            "file_records_aggregate_definition": "sha256(canonical-json ordered file records)",
        },
    }, union_indices


def _selection_rank(row: DatasetRow) -> tuple[bytes, str, int]:
    digest = hashlib.sha256(SELECTION_RANK_DOMAIN + row.row_id.encode("utf-8")).digest()
    return digest, row.row_id, row.index


def _proportional_stratum_quotas(
    capacities: dict[tuple[str, str], int],
    total_quota: int,
) -> dict[tuple[str, str], int]:
    total_capacity = sum(capacities.values())
    if total_capacity < total_quota:
        raise ValueError(f"Stratum capacity {total_capacity} is below quota {total_quota}")
    quotas = {}
    remainders = {}
    for stratum, capacity in capacities.items():
        quota, remainder = divmod(total_quota * capacity, total_capacity)
        quotas[stratum] = quota
        remainders[stratum] = remainder
    remaining = total_quota - sum(quotas.values())
    order = sorted(capacities, key=lambda stratum: (-remainders[stratum], *stratum))
    for stratum in order[:remaining]:
        quotas[stratum] += 1
    if sum(quotas.values()) != total_quota or any(quotas[stratum] > capacities[stratum] for stratum in quotas):
        raise RuntimeError("Largest-remainder stratum allocation is invalid")
    return quotas


def _select_rows(
    spec: MaterializationSpec,
    dataset_rows: tuple[DatasetRow, ...],
    excluded: set[int],
) -> tuple[set[int], dict[str, Any]]:
    available: dict[tuple[int, str, str], list[DatasetRow]] = {
        (operation, template, mode): []
        for operation in range(spec.min_operation, spec.max_operation + 1)
        for template, mode in spec.strata
    }
    for row in dataset_rows:
        if row.index not in excluded:
            available[(row.operation, row.template, row.mode)].append(row)
    available_by_operation = {
        operation: sum(len(available[(operation, *stratum)]) for stratum in spec.strata)
        for operation in range(spec.min_operation, spec.max_operation + 1)
    }
    deficient = {
        operation: rows for operation, rows in available_by_operation.items() if rows < spec.quota_per_operation
    }
    if deficient:
        raise ValueError(
            f"Insufficient gradient-unseen rows for quota_per_operation={spec.quota_per_operation}: {deficient}"
        )
    selected: set[int] = set()
    selected_by_stratum: dict[tuple[int, str, str], int] = {}
    for operation in range(spec.min_operation, spec.max_operation + 1):
        capacities = {stratum: len(available[(operation, *stratum)]) for stratum in spec.strata}
        quotas = _proportional_stratum_quotas(capacities, spec.quota_per_operation)
        for template, mode in spec.strata:
            stratum = (template, mode)
            ranked = sorted(available[(operation, template, mode)], key=_selection_rank)
            selected.update(row.index for row in ranked[: quotas[stratum]])
            selected_by_stratum[(operation, template, mode)] = quotas[stratum]
    expected_rows = (spec.max_operation - spec.min_operation + 1) * spec.quota_per_operation
    _require_equal(len(selected), expected_rows, "selected dataset rows")
    if len(selected) < spec.minimum_task_pull_capacity:
        raise ValueError(
            f"Selected dataset has {len(selected)} rows but the predeclared minimum task-pull capacity is "
            f"{spec.minimum_task_pull_capacity}"
        )
    available_counts = {stratum: len(rows) for stratum, rows in available.items()}
    total_available = sum(available_counts.values())
    return selected, {
        "selection_rule": (
            "within each operation, allocate quota across (template,mode) by Hamilton largest remainder "
            "proportional to gradient-unseen capacity; rank within stratum by seeded SHA-256"
        ),
        "stratum_allocation": "floor(quota*n_s/N_op), then largest remainders; ties by template,mode",
        "selection_rank_domain_hex": SELECTION_RANK_DOMAIN.hex(),
        "selection_rank": "sha256(domain || UTF-8 original id), ties by original id then original row index",
        "available_rows_by_operation": {str(key): value for key, value in available_by_operation.items()},
        "available_rows_by_stratum": _stratum_records(available_counts),
        "available_rows_total": total_available,
        "maximum_balanced_quota_per_operation": min(available_by_operation.values()),
        "selected_rows_by_operation": {
            str(operation): spec.quota_per_operation for operation in range(spec.min_operation, spec.max_operation + 1)
        },
        "selected_rows_by_stratum": _stratum_records(selected_by_stratum),
        "selected_rows": len(selected),
        "selected_indices_sha256": _index_digest(selected),
        "index_digest_encoding": "ascending zero-based decimal indices, one ASCII index and newline per row",
        "minimum_task_pull_capacity": spec.minimum_task_pull_capacity,
        "headroom_over_minimum_task_pull_capacity": len(selected) - spec.minimum_task_pull_capacity,
        "capacity_multiple_over_minimum": len(selected) / spec.minimum_task_pull_capacity,
    }


def _write_or_compare_output(
    spec: MaterializationSpec,
    selected: set[int],
    dataset_rows: tuple[DatasetRow, ...],
    expected_dataset_sha256: str,
    *,
    output_handle: BinaryIO | None,
    comparison_handle: BinaryIO | None,
) -> dict[str, Any]:
    if (output_handle is None) == (comparison_handle is None):
        raise ValueError("Exactly one output mode must be selected")
    digest = hashlib.sha256()
    size_bytes = 0
    row_count = 0
    selected_id_fingerprints: set[bytes] = set()
    selected_prompt_fingerprints: set[bytes] = set()
    source_digest = hashlib.sha256()
    comparison_before = os.fstat(comparison_handle.fileno()) if comparison_handle is not None else None
    with _regular_file(spec.dataset_path).open("rb") as source:
        source_before = os.fstat(source.fileno())
        for index, raw in enumerate(source):
            source_digest.update(raw)
            if index not in selected:
                continue
            expected = dataset_rows[index]
            if output_handle is not None:
                output_handle.write(raw)
            else:
                actual = comparison_handle.readline()
                if actual != raw:
                    raise ValueError(f"Materialized output differs from selected source row {index}")
            digest.update(raw)
            size_bytes += len(raw)
            row_count += 1
            selected_id_fingerprints.add(expected.id_fingerprint)
            selected_prompt_fingerprints.add(expected.prompt_fingerprint)
        source_after = os.fstat(source.fileno())
    if (source_before.st_ino, source_before.st_size, source_before.st_mtime_ns) != (
        source_after.st_ino,
        source_after.st_size,
        source_after.st_mtime_ns,
    ):
        raise RuntimeError(f"Dataset changed while selected rows were copied: {spec.dataset_path}")
    _require_equal(source_digest.hexdigest(), expected_dataset_sha256, "dataset hash on output pass")
    if comparison_handle is not None and comparison_handle.read(1) != b"":
        raise ValueError("Materialized output contains trailing data")
    if comparison_handle is not None:
        comparison_after = os.fstat(comparison_handle.fileno())
        if (
            comparison_before.st_ino,
            comparison_before.st_size,
            comparison_before.st_mtime_ns,
        ) != (
            comparison_after.st_ino,
            comparison_after.st_size,
            comparison_after.st_mtime_ns,
        ):
            raise RuntimeError(f"Materialized output changed while it was validated: {spec.output_path}")
    _require_equal(row_count, len(selected), "materialized output rows")
    _require_equal(len(selected_id_fingerprints), row_count, "materialized output unique IDs")
    _require_equal(len(selected_prompt_fingerprints), row_count, "materialized output unique prompts")
    return {
        "path": str(spec.output_path.expanduser().resolve()),
        "sha256": digest.hexdigest(),
        "bytes": size_bytes,
        "rows": row_count,
    }


def _implementation_identity(path: Path) -> dict[str, Any]:
    identity = _small_file_identity(path)
    identity["repo_relative_path"] = "user/tianhaowu/rsci/materialize_defect_withdrawal_dataset.py"
    identity.pop("path")
    return identity


def _build_payload(
    spec: MaterializationSpec,
    *,
    output_handle: BinaryIO | None,
    comparison_handle: BinaryIO | None,
) -> dict[str, Any]:
    if spec.step_count <= 0 or spec.progress_step != spec.step_count:
        raise ValueError("progress_step must equal the positive step_count")
    if spec.min_operation > spec.max_operation or spec.quota_per_operation <= 0:
        raise ValueError("Invalid operation range or quota")
    if (
        not spec.strata
        or len(spec.strata) != len(set(spec.strata))
        or any(not template or not mode for template, mode in spec.strata)
    ):
        raise ValueError("Template/mode strata must be non-empty and unique")
    labels = [source.label for source in spec.sources]
    roots = [str(source.root.expanduser().resolve()) for source in spec.sources]
    if len(labels) != len(set(labels)) or len(roots) != len(set(roots)) or not labels:
        raise ValueError("Source labels and roots must be non-empty and unique")

    dataset_scan = _scan_original_dataset(spec)
    original_dataset = _validate_original_manifests(spec, dataset_scan)
    source_records = []
    source_index_sets: dict[str, set[int]] = {}
    excluded: set[int] = set()
    for source in spec.sources:
        record, source_indices = _scan_source(spec, source, dataset_scan.rows)
        source_records.append(record)
        source_index_sets[source.label] = source_indices
        excluded.update(source_indices)
    source_pair_overlaps = []
    for first, second in combinations(labels, 2):
        overlap = source_index_sets[first] & source_index_sets[second]
        source_pair_overlaps.append(
            {
                "first_source": first,
                "second_source": second,
                "unique_indices": len(overlap),
                "indices_sha256": _index_digest(overlap),
            }
        )
    excluded_digest = _index_digest(excluded)
    if (
        spec.expected_excluded_indices_sha256 is not None
        and excluded_digest != spec.expected_excluded_indices_sha256
    ):
        raise ValueError(
            f"Combined exclusion digest changed: {excluded_digest} != {spec.expected_excluded_indices_sha256}"
        )
    if spec.expected_source_overlap_sha256 is not None:
        if len(source_pair_overlaps) != 1:
            raise ValueError("A precommitted source-overlap digest requires exactly two sources")
        _require_equal(
            source_pair_overlaps[0]["indices_sha256"],
            spec.expected_source_overlap_sha256,
            "source pair overlap digest",
        )
    selected, selection = _select_rows(spec, dataset_scan.rows, excluded)
    if spec.expected_available_rows_total is not None:
        _require_equal(
            selection["available_rows_total"],
            spec.expected_available_rows_total,
            "gradient-unseen available rows",
        )
    if spec.expected_selected_indices_sha256 is not None:
        _require_equal(
            selection["selected_indices_sha256"],
            spec.expected_selected_indices_sha256,
            "selected indices digest",
        )
    output = _write_or_compare_output(
        spec,
        selected,
        dataset_scan.rows,
        dataset_scan.identity["sha256"],
        output_handle=output_handle,
        comparison_handle=comparison_handle,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "parameters": {
            "step_count": spec.step_count,
            "progress_step": spec.progress_step,
            "min_operation": spec.min_operation,
            "max_operation": spec.max_operation,
            "quota_per_operation": spec.quota_per_operation,
            "strata": [{"template": template, "mode": mode} for template, mode in spec.strata],
            "expected_excluded_indices_sha256": spec.expected_excluded_indices_sha256,
            "expected_source_overlap_sha256": spec.expected_source_overlap_sha256,
            "expected_selected_indices_sha256": spec.expected_selected_indices_sha256,
            "expected_available_rows_total": spec.expected_available_rows_total,
        },
        "implementation": _implementation_identity(spec.implementation_path),
        "original_dataset": original_dataset,
        "sources": source_records,
        "exclusions": {
            "definition": (
                f"union of task.idx in optimizer-shipped train_rollouts.jsonl at steps 0..{spec.step_count - 1}"
            ),
            "unique_indices": len(excluded),
            "indices_sha256": excluded_digest,
            "index_digest_encoding": "ascending zero-based decimal indices, one ASCII index and newline per row",
            "task_identity_check": "task.idx plus exact SHA-256-bound task.prompt and task.answer",
            "original_dataset_id_in_rollout": False,
            "source_pair_overlaps": source_pair_overlaps,
        },
        "selection": selection,
        "output": output,
    }


def _manifest_path(output_path: Path) -> Path:
    return Path(f"{output_path}.manifest.json")


@contextmanager
def _dataset_lock(output_path: Path, *, exclusive: bool):
    lock_path = Path(f"{output_path}.materialize.lock")
    if exclusive:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b" if exclusive else "rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


def materialize_dataset(spec: MaterializationSpec) -> Path:
    output_path = spec.output_path.expanduser().resolve()
    manifest_path = _manifest_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    temporary_output = output_path.parent / f".{output_path.name}.{nonce}.partial"
    temporary_manifest = manifest_path.parent / f".{manifest_path.name}.{nonce}.partial"
    with _dataset_lock(output_path, exclusive=True):
        if output_path.exists() or output_path.is_symlink():
            raise FileExistsError(output_path)
        if manifest_path.exists() or manifest_path.is_symlink():
            raise FileExistsError(manifest_path)
        try:
            with temporary_output.open("xb") as output_handle, temporary_manifest.open("xb") as manifest_handle:
                payload = _build_payload(
                    spec,
                    output_handle=output_handle,
                    comparison_handle=None,
                )
                output_handle.flush()
                os.fsync(output_handle.fileno())
                payload[SELF_HASH_FIELD] = canonical_json_sha256(payload)
                canonical = _canonical_json_bytes(payload)
                manifest_handle.write(canonical)
                manifest_handle.flush()
                os.fsync(manifest_handle.fileno())
            temporary_output.replace(output_path)
            temporary_manifest.replace(manifest_path)
        finally:
            temporary_output.unlink(missing_ok=True)
            temporary_manifest.unlink(missing_ok=True)
    return manifest_path


def _canonical_manifest(path: Path) -> dict[str, Any]:
    resolved = _regular_file(path)
    raw = resolved.read_bytes()

    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON key in {resolved}: {key!r}")
            value[key] = item
        return value

    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    if not isinstance(payload, dict) or raw != _canonical_json_bytes(payload):
        raise ValueError(f"Manifest is not a canonical JSON object: {resolved}")
    recorded_hash = payload.get(SELF_HASH_FIELD)
    without_hash = dict(payload)
    without_hash.pop(SELF_HASH_FIELD, None)
    _require_equal(recorded_hash, canonical_json_sha256(without_hash), "manifest self hash")
    return payload


def _spec_from_manifest(payload: dict[str, Any], implementation_path: Path) -> MaterializationSpec:
    _require_equal(payload.get("schema_version"), SCHEMA_VERSION, "manifest schema_version")
    _require_equal(payload.get("artifact_type"), ARTIFACT_TYPE, "manifest artifact_type")
    parameters = payload.get("parameters")
    original = payload.get("original_dataset")
    output = payload.get("output")
    sources = payload.get("sources")
    if not isinstance(parameters, dict) or not isinstance(original, dict):
        raise ValueError("Manifest has invalid parameters or original_dataset")
    if not isinstance(output, dict) or not isinstance(sources, list) or not sources:
        raise ValueError("Manifest has invalid output or sources")
    train = original.get("train")
    dataset_manifest = original.get("dataset_manifest")
    audit = original.get("audit")
    if not isinstance(train, dict) or not isinstance(dataset_manifest, dict) or not isinstance(audit, dict):
        raise ValueError("Manifest has invalid original dataset identities")
    source_specs = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Manifest source record is not an object")
        source_specs.append(
            SourceSpec(
                label=source["label"],
                root=Path(source["root"]),
                expected_total_samples=source["expected_total_samples"],
                expected_total_problems=source["expected_total_problems"],
            )
        )
    selection = payload.get("selection")
    if not isinstance(selection, dict):
        raise ValueError("Manifest has invalid selection")
    return MaterializationSpec(
        dataset_path=Path(train["path"]),
        dataset_manifest_path=Path(dataset_manifest["path"]),
        audit_path=Path(audit["path"]),
        output_path=Path(output["path"]),
        sources=tuple(source_specs),
        step_count=parameters["step_count"],
        progress_step=parameters["progress_step"],
        min_operation=parameters["min_operation"],
        max_operation=parameters["max_operation"],
        quota_per_operation=parameters["quota_per_operation"],
        strata=tuple((record["template"], record["mode"]) for record in parameters["strata"]),
        minimum_task_pull_capacity=selection["minimum_task_pull_capacity"],
        expected_excluded_indices_sha256=parameters["expected_excluded_indices_sha256"],
        expected_source_overlap_sha256=parameters["expected_source_overlap_sha256"],
        expected_selected_indices_sha256=parameters["expected_selected_indices_sha256"],
        expected_available_rows_total=parameters["expected_available_rows_total"],
        implementation_path=implementation_path,
    )


def _spec_contract(spec: MaterializationSpec) -> dict[str, Any]:
    return {
        "dataset_path": str(spec.dataset_path.expanduser().resolve()),
        "dataset_manifest_path": str(spec.dataset_manifest_path.expanduser().resolve()),
        "audit_path": str(spec.audit_path.expanduser().resolve()),
        "output_path": str(spec.output_path.expanduser().resolve()),
        "sources": [
            {
                "label": source.label,
                "root": str(source.root.expanduser().resolve()),
                "expected_total_samples": source.expected_total_samples,
                "expected_total_problems": source.expected_total_problems,
            }
            for source in spec.sources
        ],
        "step_count": spec.step_count,
        "progress_step": spec.progress_step,
        "min_operation": spec.min_operation,
        "max_operation": spec.max_operation,
        "quota_per_operation": spec.quota_per_operation,
        "strata": [{"template": template, "mode": mode} for template, mode in spec.strata],
        "minimum_task_pull_capacity": spec.minimum_task_pull_capacity,
        "expected_excluded_indices_sha256": spec.expected_excluded_indices_sha256,
        "expected_source_overlap_sha256": spec.expected_source_overlap_sha256,
        "expected_selected_indices_sha256": spec.expected_selected_indices_sha256,
        "expected_available_rows_total": spec.expected_available_rows_total,
    }


def validate_materialized_dataset(
    manifest_path: Path,
    *,
    expected_spec: MaterializationSpec | None = None,
) -> dict[str, Any]:
    contract = expected_spec or production_spec()
    output_path = contract.output_path.expanduser().resolve()
    with _dataset_lock(output_path, exclusive=False):
        payload = _canonical_manifest(manifest_path)
        recorded_spec = _spec_from_manifest(payload, contract.implementation_path)
        _require_equal(
            _spec_contract(recorded_spec),
            _spec_contract(contract),
            "manifest materialization contract",
        )
        output_path = _regular_file(contract.output_path)
        if _manifest_path(output_path) != manifest_path.expanduser().resolve():
            raise ValueError(f"Manifest is not adjacent to its expected output: {manifest_path}")
        with output_path.open("rb") as comparison_handle:
            expected = _build_payload(
                contract,
                output_handle=None,
                comparison_handle=comparison_handle,
            )
        recorded = dict(payload)
        recorded.pop(SELF_HASH_FIELD)
        if recorded != expected:
            raise ValueError("Manifest evidence does not match the replayed source state")
        return payload


def main() -> None:
    args = parse_args()
    if args.command == "materialize":
        manifest = materialize_dataset(production_spec())
        print(manifest)
        return
    payload = validate_materialized_dataset(args.manifest)
    print(json.dumps({"status": "valid", "output": payload["output"]}, sort_keys=True))


if __name__ == "__main__":
    main()
