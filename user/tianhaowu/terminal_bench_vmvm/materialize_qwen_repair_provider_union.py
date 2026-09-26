#!/usr/bin/env python3
"""Privately intersect the sealed 1,153-task Qwen repair set with providers."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import finalize_qwen_repair_sft as repair_finalizer
import materialize_qwen_repair as repair_selection_materializer
import migrate_qwen_serving_generation as generation
from materialize_qwen_provider_union import (
    CANONICAL_SOURCE_COUNT,
    CANONICAL_SOURCE_SHA256,
    DEPLOYMENT_NAMESPACE,
    MixedMaterializationError,
    _canonical_json,
    _open_private_output_root,
    _read_private_artifact,
    _read_regular,
    _task_payload,
    derive_partition,
    materialize_sandoq_config,
    materialize_vmvm_config,
    publish_exclusive,
    sha256,
    verify_canonical_dataset,
)

SCHEMA_VERSION = 1
KIND = "qwen-repair-provider-partition"


class RepairProviderMaterializationError(ValueError):
    """A stable aggregate-only failure for private repair partitioning."""


def _selection_members(body: bytes, expected_count: int) -> tuple[str, ...]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RepairProviderMaterializationError("repair_selection_invalid") from error
    if (body and (not text.endswith("\n") or "\r" in text)) or not body:
        raise RepairProviderMaterializationError("repair_selection_invalid")
    values = tuple(text.splitlines())
    if len(values) != expected_count or len(values) != len(set(values)) or any(not value for value in values):
        raise RepairProviderMaterializationError("repair_selection_invalid")
    return values


def _load_selection(
    manifest: Path,
    manifest_sha256: str,
) -> tuple[repair_finalizer.RepairSelection, tuple[str, ...]]:
    expected_count = generation._load_contract()["repair"]["repair_union_count"]
    try:
        selection = repair_finalizer._load_repair_selection(
            manifest,
            manifest_sha256,
            expected_count,
        )
    except repair_finalizer.RepairFinalizationError as error:
        raise RepairProviderMaterializationError("repair_selection_invalid") from error
    members = _selection_members(
        selection.selection_bodies[repair_finalizer.SELECTION_TASK_COPY_FILENAME],
        expected_count,
    )
    return selection, members


def _validate_selection_source_and_code(
    selection: repair_finalizer.RepairSelection,
    historical_source_dir: Path,
) -> None:
    project = Path(__file__).resolve().parents[3]
    workflow = Path(__file__).resolve().parent
    try:
        submodules = repair_finalizer._validate_submodule_revisions(
            repair_finalizer._submodule_revisions(project, selection.repository_revision)
        )
        repair_finalizer._validate_selection_code(
            selection,
            project,
            workflow,
            selection.repository_revision,
            submodules,
        )
        if not generation.is_historical_source_generation(historical_source_dir):
            raise RepairProviderMaterializationError("repair_source_invalid")
        generation.audit_historical_source_generation(historical_source_dir)
        if repair_selection_materializer._source_fingerprints(historical_source_dir) != selection.source_artifacts:
            raise RepairProviderMaterializationError("repair_source_changed")
    except (
        OSError,
        repair_finalizer.RepairFinalizationError,
        generation.GenerationMigrationError,
        repair_selection_materializer.RepairMaterializationError,
    ) as error:
        raise RepairProviderMaterializationError("repair_selection_provenance_invalid") from error


def _partition_selection(
    members: tuple[str, ...],
    *,
    canonical_source: bytes,
    dataset: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    full = derive_partition(canonical_source, dataset)
    full_members = set(full.sandoq) | set(full.vmvm)
    selected = set(members)
    if len(selected) != len(members) or not selected.issubset(full_members):
        raise RepairProviderMaterializationError("repair_selection_not_canonical_subset")
    sandoq_members = tuple(member for member in members if member in set(full.sandoq))
    vmvm_members = tuple(member for member in members if member in set(full.vmvm))
    if (
        not sandoq_members
        or vmvm_members
        or set(sandoq_members) & set(vmvm_members)
        or set(sandoq_members) | set(vmvm_members) != selected
    ):
        raise RepairProviderMaterializationError("repair_provider_partition_invalid")
    return sandoq_members, vmvm_members


def _receipt_value(
    *,
    selection: repair_finalizer.RepairSelection,
    sandoq_count: int,
    vmvm_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "state": "materialized",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "canonical_source": {
            "count": CANONICAL_SOURCE_COUNT,
            "sha256": CANONICAL_SOURCE_SHA256,
        },
        "repair_selection": {
            "count": selection.task_count,
            "manifest_sha256": selection.sha256,
            "source_partition": selection.source_partition,
            "task_file_sha256": selection.task_file_sha256,
            "trace_contracts": selection.trace_contracts,
            "union_indices_sha256": selection.repair_union_indices_sha256,
        },
        "partition": {
            "disjoint": True,
            "exhaustive": True,
            "sandoq_count": sandoq_count,
            "vmvm_count": vmvm_count,
            "total_count": selection.task_count,
        },
    }


def _repair_vmvm_config(
    template_raw: bytes,
    task_file: Path,
    task_sha256: str,
    *,
    task_count: int,
) -> bytes:
    """Keep the sealed repair admission while deriving a 0/1 VMVM lane."""
    payload = materialize_vmvm_config(
        template_raw,
        task_file,
        task_sha256,
        task_count=task_count,
    )
    if task_count == 0:
        return payload
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RepairProviderMaterializationError("vmvm_repair_config_invalid") from error
    replacements = {
        "max_concurrent": generation.ROLLOUT_CONCURRENCY,
        "multiplex": generation.ROLLOUT_CONCURRENCY,
        "max_connections": generation.PROVIDER_CONCURRENCY,
        "max_keepalive_connections": generation.PROVIDER_CONCURRENCY,
    }
    for key, value in replacements.items():
        text, count = re.subn(
            rf"(?m)^(\s*{key}\s*=\s*)1\s*$",
            rf"\g<1>{value}",
            text,
        )
        if count != 1:
            raise RepairProviderMaterializationError("vmvm_repair_config_invalid")
    return text.encode("utf-8")


def materialize(
    *,
    source: Path,
    dataset: Path,
    sandoq_template: Path,
    vmvm_template: Path,
    repair_selection_manifest: Path,
    repair_selection_manifest_sha256: str,
    historical_source_dir: Path,
    sandoq_tasks: Path,
    vmvm_tasks: Path,
    sandoq_config: Path,
    vmvm_config: Path,
    receipt: Path,
    private_output_root: Path,
) -> dict[str, Any]:
    outputs = (sandoq_tasks, vmvm_tasks, sandoq_config, vmvm_config, receipt)
    try:
        with _open_private_output_root(
            private_output_root,
            outputs,
            forbidden_roots=(Path(__file__).resolve().parents[3], dataset),
            validate_existing=False,
        ) as private_root, repair_finalizer._hold_source_locks(historical_source_dir):
            source_raw = _read_regular(source)
            if sha256(source_raw) != CANONICAL_SOURCE_SHA256:
                raise RepairProviderMaterializationError("canonical_source_mismatch")
            resolved_dataset = verify_canonical_dataset(dataset)
            selection, selected_members = _load_selection(
                repair_selection_manifest,
                repair_selection_manifest_sha256,
            )
            _validate_selection_source_and_code(selection, historical_source_dir)
            sandoq_members, vmvm_members = _partition_selection(
                selected_members,
                canonical_source=source_raw,
                dataset=resolved_dataset,
            )
            sandoq_payload = _task_payload(sandoq_members)
            vmvm_payload = _task_payload(vmvm_members)
            sandoq_template_raw = _read_regular(sandoq_template)
            vmvm_template_raw = _read_regular(vmvm_template)
            sandoq_config_payload = materialize_sandoq_config(
                sandoq_template_raw,
                sandoq_tasks,
                sha256(sandoq_payload),
                task_count=len(sandoq_members),
            )
            vmvm_config_payload = _repair_vmvm_config(
                vmvm_template_raw,
                vmvm_tasks,
                sha256(vmvm_payload),
                task_count=len(vmvm_members),
            )
            receipt_value = _receipt_value(
                selection=selection,
                sandoq_count=len(sandoq_members),
                vmvm_count=len(vmvm_members),
            )
            try:
                repair_finalizer._validate_selection_unchanged(selection)
            except repair_finalizer.RepairFinalizationError as error:
                raise RepairProviderMaterializationError("repair_selection_changed") from error
            _validate_selection_source_and_code(selection, historical_source_dir)
            if (
                _read_regular(source) != source_raw
                or _read_regular(sandoq_template) != sandoq_template_raw
                or _read_regular(vmvm_template) != vmvm_template_raw
                or verify_canonical_dataset(dataset) != resolved_dataset
            ):
                raise RepairProviderMaterializationError("canonical_inputs_changed")
            publish_exclusive(
                private_root,
                [
                    (sandoq_tasks, sandoq_payload),
                    (vmvm_tasks, vmvm_payload),
                    (sandoq_config, sandoq_config_payload),
                    (vmvm_config, vmvm_config_payload),
                    (receipt, _canonical_json(receipt_value)),
                ],
            )
    except (MixedMaterializationError, repair_finalizer.RepairFinalizationError) as error:
        raise RepairProviderMaterializationError(str(error)) from error
    return {
        "state": "materialized",
        "repair_count": len(selected_members),
        "sandoq_count": len(sandoq_members),
        "vmvm_count": len(vmvm_members),
    }


def validate_materialization(
    *,
    source: Path,
    dataset: Path,
    sandoq_template: Path,
    vmvm_template: Path,
    repair_selection_manifest: Path,
    repair_selection_manifest_sha256: str,
    historical_source_dir: Path,
    sandoq_tasks: Path,
    vmvm_tasks: Path,
    sandoq_config: Path,
    vmvm_config: Path,
    receipt: Path,
    receipt_sha256: str,
    private_output_root: Path,
) -> dict[str, Any]:
    outputs = (sandoq_tasks, vmvm_tasks, sandoq_config, vmvm_config, receipt)
    try:
        with _open_private_output_root(
            private_output_root,
            outputs,
            forbidden_roots=(Path(__file__).resolve().parents[3], dataset),
        ) as private_root, repair_finalizer._hold_source_locks(historical_source_dir):
            source_raw = _read_regular(source)
            if sha256(source_raw) != CANONICAL_SOURCE_SHA256:
                raise RepairProviderMaterializationError("canonical_source_mismatch")
            resolved_dataset = verify_canonical_dataset(dataset)
            selection, selected_members = _load_selection(
                repair_selection_manifest,
                repair_selection_manifest_sha256,
            )
            _validate_selection_source_and_code(selection, historical_source_dir)
            sandoq_members, vmvm_members = _partition_selection(
                selected_members,
                canonical_source=source_raw,
                dataset=resolved_dataset,
            )
            sandoq_payload = _task_payload(sandoq_members)
            vmvm_payload = _task_payload(vmvm_members)
            expected = {
                sandoq_tasks: sandoq_payload,
                vmvm_tasks: vmvm_payload,
                sandoq_config: materialize_sandoq_config(
                    _read_regular(sandoq_template),
                    sandoq_tasks,
                    sha256(sandoq_payload),
                    task_count=len(sandoq_members),
                ),
                vmvm_config: _repair_vmvm_config(
                    _read_regular(vmvm_template),
                    vmvm_tasks,
                    sha256(vmvm_payload),
                    task_count=len(vmvm_members),
                ),
            }
            if any(_read_private_artifact(private_root, path) != body for path, body in expected.items()):
                raise RepairProviderMaterializationError("repair_provider_artifact_mismatch")
            receipt_raw = _read_private_artifact(private_root, receipt)
            value = _receipt_value(
                selection=selection,
                sandoq_count=len(sandoq_members),
                vmvm_count=len(vmvm_members),
            )
            try:
                repair_finalizer._validate_selection_unchanged(selection)
            except repair_finalizer.RepairFinalizationError as error:
                raise RepairProviderMaterializationError("repair_selection_changed") from error
            _validate_selection_source_and_code(selection, historical_source_dir)
            if sha256(receipt_raw) != receipt_sha256 or receipt_raw != _canonical_json(value):
                raise RepairProviderMaterializationError("repair_provider_receipt_invalid")
    except (MixedMaterializationError, repair_finalizer.RepairFinalizationError) as error:
        raise RepairProviderMaterializationError(str(error)) from error
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--sandoq-template", type=Path, required=True)
    parser.add_argument("--vmvm-template", type=Path, required=True)
    parser.add_argument("--repair-selection-manifest", type=Path, required=True)
    parser.add_argument("--repair-selection-manifest-sha256", required=True)
    parser.add_argument("--historical-source-dir", type=Path, required=True)
    parser.add_argument("--sandoq-tasks", type=Path, required=True)
    parser.add_argument("--vmvm-tasks", type=Path, required=True)
    parser.add_argument("--sandoq-config", type=Path, required=True)
    parser.add_argument("--vmvm-config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    args = parser.parse_args()
    workflow = Path(__file__).resolve().parent
    template_dir = workflow / "configs" / "eval" / DEPLOYMENT_NAMESPACE
    if (
        args.source.resolve(strict=True) != workflow / "configs/eval/mobius_valid_tasks_2500.txt"
        or args.sandoq_template.resolve(strict=True)
        != template_dir / "mobius_qwen_a95b_2500_sandoq.toml"
        or args.vmvm_template.resolve(strict=True)
        != template_dir / "mobius_qwen_a95b_2500_vmvm_host.toml"
    ):
        raise SystemExit("canonical_input_path_mismatch")
    try:
        summary = materialize(**vars(args))
    except (OSError, RepairProviderMaterializationError) as error:
        code = str(error) if isinstance(error, RepairProviderMaterializationError) else "materialization_failed"
        raise SystemExit(code) from None
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
