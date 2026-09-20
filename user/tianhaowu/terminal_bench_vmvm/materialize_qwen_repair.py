#!/usr/bin/env python3
"""Materialize a private, approved repair selection from a terminal Qwen run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import direct_qwen_workers as direct
import export_sft as exporter
import migrate_qwen_router_affinity as migration
import migrate_qwen_serving_generation as serving_generation
from audit_traces import (
    QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT,
    qwen_repair_trace_contracts_value,
)

SCHEMA_VERSION = 3
MANIFEST_KIND = "qwen-aggregate-repair-selection"
TASK_FILENAME = "repair_tasks.txt"
MISSING_ERROR_TASK_FILENAME = "repair_missing_or_errored_tasks.txt"
STRICT_INVALID_PASS_TASK_FILENAME = "repair_strict_invalid_pass_tasks.txt"
CONFIG_FILENAME = "repair_config.toml"
MANIFEST_FILENAME = "repair_manifest.json"
MAX_TASK_FILE_BYTES = 16 * 1024 * 1024
REQUIRED_RUNTIME_SUBMODULES = (
    "deps/pydantic-config",
    "deps/renderers",
    "deps/verifiers",
)
CONFIG_TEMPLATE = Path(__file__).resolve().parent / "configs" / "eval" / "mobius_qwen_a95b_2500.toml"
SOURCE_ARTIFACTS = {
    "config": Path("config.toml"),
    "direct_workers": Path("direct_workers.json"),
    "inputs_manifest": Path("inputs/manifest.json"),
    "source_config": Path("inputs/source_config.toml"),
    "provenance": Path("provenance.txt"),
    "results": Path("results.jsonl"),
    "task_file": Path("inputs/task_file.txt"),
    "image_manifest": Path("inputs/image_manifest.json"),
}


class RepairMaterializationError(ValueError):
    """The source or requested repair selection is not safe to materialize."""


@dataclass(frozen=True, slots=True)
class TaskRecord:
    identifier: str


@dataclass(frozen=True, slots=True)
class SourceTracePartition:
    error_traces: int
    invalid_positive_traces: int
    positive_reward_traces: int
    retained_valid_positive_traces: int
    reward_zero_traces: int
    seen_traces: int
    superseded_legacy_empty_reasoning_traces: int
    unseen_tasks: int

    def as_dict(self, *, repair_tasks: int, source_task_count: int) -> dict[str, int | bool]:
        retained_original_tasks = self.retained_valid_positive_traces + self.reward_zero_traces
        if (
            self.positive_reward_traces
            != self.retained_valid_positive_traces + self.invalid_positive_traces
            or self.seen_traces
            != self.positive_reward_traces + self.reward_zero_traces + self.error_traces
            or source_task_count != self.seen_traces + self.unseen_tasks
            or source_task_count != retained_original_tasks + repair_tasks
        ):
            raise RepairMaterializationError("source_trace_partition_invalid")
        return {
            "error_traces": self.error_traces,
            "exhaustive": True,
            "invalid_positive_traces": self.invalid_positive_traces,
            "positive_reward_traces": self.positive_reward_traces,
            "repair_tasks": repair_tasks,
            "retained_original_tasks": retained_original_tasks,
            "retained_valid_positive_traces": self.retained_valid_positive_traces,
            "reward_zero_traces": self.reward_zero_traces,
            "seen_traces": self.seen_traces,
            "source_task_count": source_task_count,
            "superseded_legacy_empty_reasoning_traces": self.superseded_legacy_empty_reasoning_traces,
            "unseen_tasks": self.unseen_tasks,
        }


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _open_regular(path: Path, label: str) -> int:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise RepairMaterializationError(f"{label}_unreadable") from error
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise RepairMaterializationError(f"{label}_not_regular")
    return descriptor


def _read_regular(path: Path, label: str, *, limit: int) -> bytes:
    descriptor = _open_regular(path, label)
    try:
        with os.fdopen(descriptor, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError as error:
        raise RepairMaterializationError(f"{label}_unreadable") from error
    if len(data) > limit:
        raise RepairMaterializationError(f"{label}_too_large")
    return data


def _fingerprint_regular(path: Path, label: str) -> dict[str, int | str]:
    descriptor = _open_regular(path, label)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(descriptor, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError as error:
        raise RepairMaterializationError(f"{label}_unreadable") from error
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def _git_output(path: Path, arguments: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RepairMaterializationError("code_provenance_unavailable") from error
    if completed.stderr:
        raise RepairMaterializationError("code_provenance_unavailable")
    return completed.stdout


def _code_provenance() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[3]
    revision = migration._repository_revision()
    submodules: dict[str, str] = {}
    for relative in REQUIRED_RUNTIME_SUBMODULES:
        record = _git_output(repository, ["ls-tree", revision, "--", relative]).strip()
        fields = record.split(maxsplit=3)
        if (
            len(fields) != 4
            or fields[0] != "160000"
            or fields[1] != "commit"
            or re.fullmatch(r"[0-9a-f]{40}", fields[2]) is None
            or fields[3] != relative
        ):
            raise RepairMaterializationError("code_provenance_invalid")
        submodule = repository / relative
        observed = _git_output(submodule, ["rev-parse", "HEAD"]).strip()
        status = _git_output(submodule, ["status", "--porcelain=v1", "--untracked-files=all"])
        if observed != fields[2] or status:
            raise RepairMaterializationError("code_provenance_invalid")
        submodules[relative] = observed
    return {
        "exporter_sha256": _fingerprint_regular(
            Path(__file__).resolve().parent / "export_sft.py",
            "exporter",
        )["sha256"],
        "materializer_sha256": _fingerprint_regular(Path(__file__).resolve(), "materializer")["sha256"],
        "repository_revision": revision,
        "submodules": submodules,
    }


def _validated_code_provenance(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "exporter_sha256",
        "materializer_sha256",
        "repository_revision",
        "submodules",
    }:
        raise RepairMaterializationError("code_provenance_invalid")
    submodules = value.get("submodules")
    if (
        not isinstance(value.get("exporter_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["exporter_sha256"]) is None
        or not isinstance(value.get("materializer_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["materializer_sha256"]) is None
        or not isinstance(value.get("repository_revision"), str)
        or re.fullmatch(r"[0-9a-f]{40}", value["repository_revision"]) is None
        or not isinstance(submodules, dict)
        or set(submodules) != set(REQUIRED_RUNTIME_SUBMODULES)
        or any(
            not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None
            for revision in submodules.values()
        )
    ):
        raise RepairMaterializationError("code_provenance_invalid")
    return {
        "exporter_sha256": value["exporter_sha256"],
        "materializer_sha256": value["materializer_sha256"],
        "repository_revision": value["repository_revision"],
        "submodules": {name: submodules[name] for name in sorted(submodules)},
    }


def _source_fingerprints(source: Path) -> dict[str, dict[str, int | str]]:
    return {
        label: _fingerprint_regular(source / relative, f"source_{label}")
        for label, relative in SOURCE_ARTIFACTS.items()
    }


def _task_records(data: bytes, label: str) -> list[TaskRecord]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise RepairMaterializationError(f"{label}_invalid") from error
    records: list[TaskRecord] = []
    seen: set[str] = set()
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        line = raw.strip()
        identifier = line.split("\t", 1)[0]
        if not identifier:
            raise RepairMaterializationError(f"{label}_invalid")
        if identifier in seen:
            raise RepairMaterializationError(f"{label}_duplicates")
        seen.add(identifier)
        records.append(TaskRecord(identifier=identifier))
    if not records:
        raise RepairMaterializationError(f"{label}_empty")
    return records


def _taskset_records_in_evaluator_order(
    source_config: dict[str, Any],
    records: list[TaskRecord],
) -> list[TaskRecord]:
    taskset = source_config.get("taskset")
    dataset_value = taskset.get("dataset_dir") if isinstance(taskset, dict) else None
    if not isinstance(dataset_value, str) or not dataset_value:
        raise RepairMaterializationError("source_dataset_invalid")
    dataset_path = Path(dataset_value)
    if not dataset_path.is_absolute():
        dataset_path = Path.cwd() / dataset_path
    try:
        dataset = dataset_path.resolve(strict=True)
        metadata = dataset_path.lstat()
    except (OSError, RuntimeError) as error:
        raise RepairMaterializationError("source_dataset_invalid") from error
    if not stat.S_ISDIR(metadata.st_mode) or dataset != dataset_path:
        raise RepairMaterializationError("source_dataset_invalid")

    by_identifier = {record.identifier: record for record in records}
    ordered: list[TaskRecord] = []
    try:
        for candidate in sorted(dataset.iterdir()):
            record = by_identifier.get(candidate.name)
            if record is None:
                continue
            candidate_metadata = candidate.lstat()
            task_toml = candidate / "task.toml"
            instruction = candidate / "instruction.md"
            if (
                not stat.S_ISDIR(candidate_metadata.st_mode)
                or candidate.resolve(strict=True) != candidate
                or not stat.S_ISREG(task_toml.lstat().st_mode)
                or task_toml.resolve(strict=True) != task_toml
                or not stat.S_ISREG(instruction.lstat().st_mode)
                or instruction.resolve(strict=True) != instruction
            ):
                raise RepairMaterializationError("source_dataset_invalid")
            ordered.append(record)
    except OSError as error:
        raise RepairMaterializationError("source_dataset_invalid") from error
    if len(ordered) != len(records) or {record.identifier for record in ordered} != set(by_identifier):
        raise RepairMaterializationError("source_dataset_task_mapping_invalid")
    return ordered


def _parse_toml(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise RepairMaterializationError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise RepairMaterializationError(f"{label}_invalid")
    return value


def _replace_assignment(text: str, key: str, value: object) -> str:
    rendered = (
        json.dumps(value) if isinstance(value, str) else str(value).lower() if isinstance(value, bool) else str(value)
    )
    pattern = re.compile(rf"(?m)^(\s*{re.escape(key)}\s*=\s*).*$")
    rewritten, count = pattern.subn(lambda match: f"{match.group(1)}{rendered}", text)
    if count != 1:
        raise RepairMaterializationError(f"repair_config_{key}_not_unique")
    return rewritten


def _set_sampling_reasoning_effort(text: str) -> str:
    assignment = re.compile(r'(?m)^(\s*reasoning_effort\s*=\s*).*$')
    if len(assignment.findall(text)) > 1:
        raise RepairMaterializationError("repair_config_reasoning_effort_not_unique")
    if assignment.search(text):
        return assignment.sub(r'\g<1>"high"', text)
    table = re.compile(r"(?m)^\[sampling\]\s*$")
    rewritten, count = table.subn('[sampling]\nreasoning_effort = "high"', text)
    if count != 1:
        raise RepairMaterializationError("repair_config_sampling_not_unique")
    return rewritten


def _render_repair_config(
    template: bytes,
    source_config: dict[str, Any],
    *,
    task_file: Path,
    task_file_sha256: str,
    task_count: int,
    image_manifest: Path,
    image_manifest_sha256: str,
) -> bytes:
    try:
        text = template.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RepairMaterializationError("repair_config_template_invalid") from error
    taskset = source_config.get("taskset")
    if not isinstance(taskset, dict):
        raise RepairMaterializationError("source_config_taskset_invalid")
    for key in ("dataset_dir", "dataset_revision", "image_prefix", "image_tag"):
        value = taskset.get(key)
        if not isinstance(value, str) or not value:
            raise RepairMaterializationError("source_config_corpus_invalid")
        text = _replace_assignment(text, key, value)
    replacements: tuple[tuple[str, object], ...] = (
        ("num_tasks", task_count),
        ("task_file", str(task_file)),
        ("task_file_sha256", task_file_sha256),
        ("image_manifest", str(image_manifest)),
        ("image_manifest_sha256", image_manifest_sha256),
    )
    for key, value in replacements:
        text = _replace_assignment(text, key, value)
    return _set_sampling_reasoning_effort(text).encode()


def _validate_repair_config(
    config: dict[str, Any],
    *,
    task_file: Path,
    task_file_sha256: str,
    task_count: int,
    image_manifest: Path,
    image_manifest_sha256: str,
) -> None:
    client = config.get("client")
    sampling = config.get("sampling")
    template = sampling.get("chat_template_kwargs") if isinstance(sampling, dict) else None
    taskset = config.get("taskset")
    retries = config.get("retries")
    rollout = retries.get("rollout") if isinstance(retries, dict) else None
    retry_include = rollout.get("include") if isinstance(rollout, dict) else None
    try:
        provider_concurrency = direct.provider_concurrency(config)
    except direct.DirectWorkerError as error:
        raise RepairMaterializationError("repair_config_contract_invalid") from error
    if (
        config.get("model") != direct.EXPECTED_MODEL
        or config.get("num_tasks") != task_count
        or config.get("num_rollouts") != 1
        or config.get("max_concurrent") != direct.MAX_DIRECT_CONCURRENCY
        or config.get("multiplex") != direct.MAX_DIRECT_CONCURRENCY
        or any(config.get(key) != 262_144 for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"))
        or not isinstance(client, dict)
        or client.get("capture_model_io") is not True
        or provider_concurrency != direct.PRODUCTION_PROVIDER_CONCURRENCY
        or not isinstance(template, dict)
        or template.get("enable_thinking") is not True
        or template.get("preserve_thinking") is not True
        or sampling.get("reasoning_effort") != "high"
        or not isinstance(taskset, dict)
        or Path(str(taskset.get("task_file", ""))).resolve() != task_file.resolve()
        or taskset.get("task_file_sha256") != task_file_sha256
        or Path(str(taskset.get("image_manifest", ""))).resolve() != image_manifest.resolve()
        or taskset.get("image_manifest_sha256") != image_manifest_sha256
        or not isinstance(retry_include, list)
        or len(retry_include) != len(set(retry_include))
        or frozenset(retry_include) != direct.ROLLOUT_RETRY_POLICY
        or rollout.get("max_retries") != 2
    ):
        raise RepairMaterializationError("repair_config_contract_invalid")


def _load_resume_planner():
    return migration._load_verifiers_resume(direct.ADMISSION_VERIFIERS_REVISION)


def _plan_owed(source: Path, num_tasks: int) -> tuple[int, set[int]]:
    planner = _load_resume_planner()
    try:
        keep, owed = planner.plan(
            source,
            list(range(num_tasks)),
            1,
            False,
            require_exact_tokens=False,
            require_logprobs=False,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RepairMaterializationError("resume_plan_failed") from error
    if (
        not isinstance(keep, list)
        or any(isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 for offset in keep)
        or len(keep) != len(set(keep))
        or not isinstance(owed, dict)
        or any(
            isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < num_tasks or count != 1
            for index, count in owed.items()
        )
        or len(keep) + sum(owed.values()) != num_tasks
    ):
        raise RepairMaterializationError("resume_plan_invalid")
    return len(keep), set(owed)


def _indices_bytes(indices: set[int]) -> bytes:
    return "".join(f"{index}\n" for index in sorted(indices)).encode()


def _selected_task_bytes(records: list[TaskRecord], indices: set[int]) -> bytes:
    return "".join(f"{records[index].identifier}\n" for index in range(len(records)) if index in indices).encode()


def _strict_invalid_pass_indices(
    source: Path,
    ordered_records: list[TaskRecord],
    missing_or_errored_indices: set[int],
) -> tuple[set[int], SourceTracePartition]:
    """Find scored passes rejected by the exact exporter trainability contract."""
    results_path = source / SOURCE_ARTIFACTS["results"]
    descriptor = _open_regular(results_path, "source_results")
    seen: set[int] = set()
    errored: set[int] = set()
    invalid_passes: set[int] = set()
    positive_count = 0
    reward_zero_count = 0
    superseded_legacy_empty_reasoning_count = 0
    evaluator_order = tuple(record.identifier for record in ordered_records)
    try:
        before = os.fstat(descriptor)
        with os.fdopen(descriptor, "rb") as handle:
            for raw_line in handle:
                try:
                    trace = json.loads(raw_line)
                except (UnicodeDecodeError, ValueError) as error:
                    if not raw_line.endswith(b"\n"):
                        break
                    raise RepairMaterializationError("source_results_invalid") from error
                task = trace.get("task") if isinstance(trace, dict) else None
                index = task.get("idx") if isinstance(task, dict) else None
                try:
                    slug = (
                        exporter._opaque_task_slug(task, evaluator_order=evaluator_order)
                        if isinstance(task, dict)
                        else None
                    )
                except exporter.ExportError as error:
                    raise RepairMaterializationError("source_results_identity_invalid") from error
                if (
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or not 0 <= index < len(ordered_records)
                    or index in seen
                    or slug != ordered_records[index].identifier
                ):
                    raise RepairMaterializationError("source_results_identity_invalid")
                seen.add(index)
                errors = trace.get("errors")
                if not isinstance(errors, list):
                    raise RepairMaterializationError("source_results_invalid")
                if errors:
                    errored.add(index)
                    continue
                try:
                    reward = exporter._trace_reward(trace)
                except exporter.ExportError as error:
                    raise RepairMaterializationError("source_results_invalid") from error
                if reward == 0.0:
                    reward_zero_count += 1
                    stop_condition = trace.get("stop_condition")
                    if (
                        trace.get("is_completed") is not True
                        or not isinstance(stop_condition, str)
                        or not stop_condition
                    ):
                        raise RepairMaterializationError("source_results_invalid")
                    continue
                positive_count += 1
                try:
                    validated_nodes, _tools = exporter._validate_trainable_trace(
                        trace,
                        reward=reward,
                        max_sequence_tokens=262_144,
                        model_io_contract=QWEN3_A95B_EPOCH3_MODEL_IO_CONTRACT,
                    )
                except exporter.ExportError:
                    invalid_passes.add(index)
                else:
                    if any(
                        node.get("sampled") is True
                        and isinstance(node.get("message"), dict)
                        and isinstance(node["message"].get("reasoning_content"), str)
                        and not node["message"]["reasoning_content"].strip()
                        for node in validated_nodes
                    ):
                        superseded_legacy_empty_reasoning_count += 1
            after = os.fstat(handle.fileno())
    except OSError as error:
        raise RepairMaterializationError("source_results_unreadable") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise RepairMaterializationError("source_changed_during_materialization")
    missing = set(range(len(ordered_records))) - seen
    if errored | missing != missing_or_errored_indices or errored & missing:
        raise RepairMaterializationError("resume_plan_source_mismatch")
    partition = SourceTracePartition(
        error_traces=len(errored),
        invalid_positive_traces=len(invalid_passes),
        positive_reward_traces=positive_count,
        retained_valid_positive_traces=positive_count - len(invalid_passes),
        reward_zero_traces=reward_zero_count,
        seen_traces=len(seen),
        superseded_legacy_empty_reasoning_traces=superseded_legacy_empty_reasoning_count,
        unseen_tasks=len(missing),
    )
    return invalid_passes, partition


def _validate_source_contract(
    summary: dict[str, Any],
    *,
    expected_endpoints: int,
) -> None:
    if (
        summary.get("ok") is not True
        or summary.get("model") != direct.EXPECTED_MODEL
        or summary.get("endpoints") != expected_endpoints
        or summary.get("manifest_schema_version") != direct.ROUTER_MANIFEST_SCHEMA_VERSION
        or summary.get("provider_concurrency") != direct.PRODUCTION_PROVIDER_CONCURRENCY
        or summary.get("queue_size") != direct.MAX_DIRECT_CONCURRENCY - direct.PRODUCTION_PROVIDER_CONCURRENCY
        or summary.get("router_policy") != direct.ROUTER_POLICY
        or summary.get("request_id_headers") != list(direct.ROUTER_REQUEST_ID_HEADERS)
        or summary.get("routing_epoch") != 3
    ):
        raise RepairMaterializationError("source_routing_contract_invalid")


def _validate_published(
    output: Path,
    allow_incomplete: bool,
    *,
    expected_task_bytes: bytes,
    expected_missing_error_task_bytes: bytes,
    expected_strict_invalid_pass_task_bytes: bytes,
    expected_config_bytes: bytes,
    expected_manifest_bytes: bytes,
    approved_identifiers: set[str],
    image_manifest: Path,
    image_manifest_sha256: str,
) -> None:
    expected_names = {
        TASK_FILENAME,
        MISSING_ERROR_TASK_FILENAME,
        STRICT_INVALID_PASS_TASK_FILENAME,
        CONFIG_FILENAME,
        MANIFEST_FILENAME,
    }
    if allow_incomplete:
        expected_names.add(direct.MIGRATION_INCOMPLETE_FILENAME)
    if {entry.name for entry in output.iterdir()} != expected_names:
        raise RepairMaterializationError("published_artifacts_invalid")
    task_path = output / TASK_FILENAME
    missing_error_task_path = output / MISSING_ERROR_TASK_FILENAME
    strict_invalid_pass_task_path = output / STRICT_INVALID_PASS_TASK_FILENAME
    config_path = output / CONFIG_FILENAME
    manifest_path = output / MANIFEST_FILENAME
    for path in (
        task_path,
        missing_error_task_path,
        strict_invalid_pass_task_path,
        config_path,
        manifest_path,
    ):
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RepairMaterializationError("published_artifact_mode_invalid")
    task_bytes = _read_regular(task_path, "published_task_file", limit=MAX_TASK_FILE_BYTES)
    config_bytes = _read_regular(config_path, "published_config", limit=1 << 20)
    manifest_bytes = _read_regular(manifest_path, "published_manifest", limit=1 << 20)
    missing_error_task_bytes = _read_regular(
        missing_error_task_path,
        "published_missing_error_task_file",
        limit=MAX_TASK_FILE_BYTES,
    )
    strict_invalid_pass_task_bytes = _read_regular(
        strict_invalid_pass_task_path,
        "published_strict_invalid_pass_task_file",
        limit=MAX_TASK_FILE_BYTES,
    )
    if (
        task_bytes != expected_task_bytes
        or missing_error_task_bytes != expected_missing_error_task_bytes
        or strict_invalid_pass_task_bytes != expected_strict_invalid_pass_task_bytes
        or config_bytes != expected_config_bytes
        or manifest_bytes != expected_manifest_bytes
    ):
        raise RepairMaterializationError("published_artifact_hash_mismatch")
    records = _task_records(task_bytes, "published_task_file")
    missing_records = (
        _task_records(missing_error_task_bytes, "published_missing_error_task_file") if missing_error_task_bytes else []
    )
    strict_records = (
        _task_records(strict_invalid_pass_task_bytes, "published_strict_invalid_pass_task_file")
        if strict_invalid_pass_task_bytes
        else []
    )
    if any(record.identifier not in approved_identifiers for record in records):
        raise RepairMaterializationError("published_task_outside_approval")
    if {record.identifier for record in missing_records} & {record.identifier for record in strict_records} or {
        record.identifier for record in records
    } != {record.identifier for record in missing_records} | {record.identifier for record in strict_records}:
        raise RepairMaterializationError("published_task_partition_invalid")
    task_sha256 = _sha256_bytes(task_bytes)
    config = _parse_toml(config_bytes, "published_config")
    _validate_repair_config(
        config,
        task_file=task_path,
        task_file_sha256=task_sha256,
        task_count=len(records),
        image_manifest=image_manifest,
        image_manifest_sha256=image_manifest_sha256,
    )
    try:
        direct.validate_eval_config(
            config_path,
            approved_task_file=task_path,
            approved_task_file_sha256=task_sha256,
        )
    except direct.DirectWorkerError as error:
        raise RepairMaterializationError("published_config_validation_failed") from error


def materialize(
    source_dir: Path,
    approved_task_file: Path,
    approved_task_file_sha256: str,
    output_dir: Path,
    *,
    terminal_check: Callable[[str], bool] = migration.slurm_job_is_terminal,
) -> dict[str, Any]:
    if re.fullmatch(r"[0-9a-f]{64}", approved_task_file_sha256) is None:
        raise RepairMaterializationError("approval_sha256_invalid")
    try:
        source = source_dir.resolve(strict=True)
        output_parent = output_dir.parent.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise RepairMaterializationError("path_resolution_failed") from error
    output = output_parent / output_dir.name
    if output.exists() or output.is_symlink():
        raise RepairMaterializationError("destination_exists")
    if output == source or output.is_relative_to(source) or source.is_relative_to(output):
        raise RepairMaterializationError("destination_overlaps_source")

    approval_bytes = _read_regular(
        approved_task_file,
        "approval_task_file",
        limit=MAX_TASK_FILE_BYTES,
    )
    if _sha256_bytes(approval_bytes) != approved_task_file_sha256:
        raise RepairMaterializationError("approval_sha256_mismatch")
    approval_records = _task_records(approval_bytes, "approval_task_file")
    approved_identifiers = {record.identifier for record in approval_records}

    try:
        lock_context = migration._source_locks(source)
        with lock_context:
            job_ids = migration._provenance_job_ids(source / "provenance.txt")
            try:
                terminal = all(terminal_check(job_id) for job_id in job_ids)
            except Exception as error:
                raise RepairMaterializationError("source_job_state_unavailable") from error
            if not terminal:
                raise RepairMaterializationError("source_job_not_terminal")
            try:
                historical_source = serving_generation.is_historical_source_generation(source)
                source_summary = (
                    serving_generation.audit_historical_source_generation(source)
                    if historical_source
                    else direct.audit_run_directory(source)
                )
            except (direct.DirectWorkerError, serving_generation.GenerationMigrationError) as error:
                raise RepairMaterializationError("source_validation_failed") from error
            _validate_source_contract(
                source_summary,
                expected_endpoints=(
                    serving_generation._load_contract()["source_generation"]["worker_count"]
                    if historical_source
                    else direct.EXPECTED_ENDPOINTS
                ),
            )

            source_fingerprints = _source_fingerprints(source)
            source_task_bytes = _read_regular(
                source / SOURCE_ARTIFACTS["task_file"],
                "source_task_file",
                limit=MAX_TASK_FILE_BYTES,
            )
            source_records = _task_records(source_task_bytes, "source_task_file")
            if (
                approval_bytes != source_task_bytes
                or approved_task_file_sha256 != source_fingerprints["task_file"]["sha256"]
                or approval_records != source_records
            ):
                raise RepairMaterializationError("approval_source_mismatch")

            source_config_bytes = _read_regular(
                source / "config.toml",
                "source_config",
                limit=1 << 20,
            )
            source_config = _parse_toml(source_config_bytes, "source_config")
            num_tasks = source_config.get("num_tasks")
            if isinstance(num_tasks, bool) or not isinstance(num_tasks, int) or num_tasks != len(source_records):
                raise RepairMaterializationError("source_task_count_mismatch")
            ordered_source_records = _taskset_records_in_evaluator_order(source_config, source_records)
            task_index_order_sha256 = _sha256_bytes(
                "".join(
                    f"{index}\0{record.identifier}\n" for index, record in enumerate(ordered_source_records)
                ).encode()
            )

            retained_count, owed_indices = _plan_owed(source, num_tasks)
            strict_invalid_pass_indices, source_partition = _strict_invalid_pass_indices(
                source,
                ordered_source_records,
                owed_indices,
            )
            if strict_invalid_pass_indices & owed_indices:
                raise RepairMaterializationError("repair_selection_partition_invalid")
            selected_index_set = owed_indices | strict_invalid_pass_indices
            source_partition_value = source_partition.as_dict(
                repair_tasks=len(selected_index_set),
                source_task_count=num_tasks,
            )
            if source_partition.seen_traces != retained_count + source_partition.error_traces:
                raise RepairMaterializationError("source_trace_partition_invalid")
            missing_or_errored_indices_sha256 = _sha256_bytes(_indices_bytes(owed_indices))
            strict_invalid_pass_indices_sha256 = _sha256_bytes(_indices_bytes(strict_invalid_pass_indices))
            repair_union_indices_sha256 = _sha256_bytes(_indices_bytes(selected_index_set))
            if not selected_index_set:
                if (
                    _source_fingerprints(source) != source_fingerprints
                    or _taskset_records_in_evaluator_order(source_config, source_records) != ordered_source_records
                ):
                    raise RepairMaterializationError("source_changed_during_materialization")
                return {
                    "approved_repair_count": 0,
                    "approved_task_file_sha256": approved_task_file_sha256,
                    "missing_or_errored_count": 0,
                    "ok": True,
                    "repair_union_indices_sha256": repair_union_indices_sha256,
                    "status": "nothing_to_repair",
                    "strict_invalid_pass_count": 0,
                    "source_partition": source_partition_value,
                    "task_index_order_sha256": task_index_order_sha256,
                }
            code_provenance = _validated_code_provenance(_code_provenance())
            selected_indices = [index for index in range(num_tasks) if index in selected_index_set]
            selected_records = [ordered_source_records[index] for index in selected_indices]
            task_bytes = "".join(f"{record.identifier}\n" for record in selected_records).encode()
            task_sha256 = _sha256_bytes(task_bytes)
            missing_error_task_bytes = _selected_task_bytes(ordered_source_records, owed_indices)
            strict_invalid_pass_task_bytes = _selected_task_bytes(
                ordered_source_records,
                strict_invalid_pass_indices,
            )
            missing_error_task_sha256 = _sha256_bytes(missing_error_task_bytes)
            strict_invalid_pass_task_sha256 = _sha256_bytes(strict_invalid_pass_task_bytes)

            image_manifest = source / SOURCE_ARTIFACTS["image_manifest"]
            source_taskset = source_config.get("taskset")
            image_manifest_sha256 = (
                source_taskset.get("image_manifest_sha256") if isinstance(source_taskset, dict) else None
            )
            if (
                not isinstance(image_manifest_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", image_manifest_sha256) is None
                or source_fingerprints["image_manifest"]["sha256"] != image_manifest_sha256
            ):
                raise RepairMaterializationError("source_image_manifest_mismatch")

            template_bytes = _read_regular(CONFIG_TEMPLATE, "repair_config_template", limit=1 << 20)
            final_task_path = output / TASK_FILENAME
            config_bytes = _render_repair_config(
                template_bytes,
                source_config,
                task_file=final_task_path,
                task_file_sha256=task_sha256,
                task_count=len(selected_records),
                image_manifest=image_manifest,
                image_manifest_sha256=image_manifest_sha256,
            )
            config = _parse_toml(config_bytes, "repair_config")
            _validate_repair_config(
                config,
                task_file=final_task_path,
                task_file_sha256=task_sha256,
                task_count=len(selected_records),
                image_manifest=image_manifest,
                image_manifest_sha256=image_manifest_sha256,
            )
            config_sha256 = _sha256_bytes(config_bytes)
            retry_policy_bytes = "".join(f"{name}\n" for name in sorted(direct.ROLLOUT_RETRY_POLICY)).encode()
            manifest = {
                "approval": {
                    "approved_task_count": len(approval_records),
                    "approved_task_file_sha256": approved_task_file_sha256,
                },
                "code": code_provenance,
                "config": {
                    "capture_model_io": True,
                    "enable_thinking": True,
                    "max_concurrent": direct.MAX_DIRECT_CONCURRENCY,
                    "max_total_tokens": 262_144,
                    "preserve_thinking": True,
                    "provider_concurrency": direct.PRODUCTION_PROVIDER_CONCURRENCY,
                    "reasoning_effort": "high",
                    "retry_class_count": len(direct.ROLLOUT_RETRY_POLICY),
                    "retry_policy_sha256": _sha256_bytes(retry_policy_bytes),
                    "sha256": config_sha256,
                    "template_sha256": _sha256_bytes(template_bytes),
                },
                "kind": MANIFEST_KIND,
                "planner": {
                    "contract_verifiers_revision": direct.ADMISSION_VERIFIERS_REVISION,
                    "missing_or_errored_count": len(owed_indices),
                    "module_sha256": direct.ADMISSION_RESUME_MODULE_SHA256,
                    "retained_count": retained_count,
                    "approved_task_count": num_tasks,
                    "task_index_order_sha256": task_index_order_sha256,
                },
                "schema_version": SCHEMA_VERSION,
                "selection": {
                    "approved_repair_count": len(selected_records),
                    "missing_or_errored_count": len(owed_indices),
                    "missing_or_errored_indices_sha256": missing_or_errored_indices_sha256,
                    "missing_or_errored_task_file_sha256": missing_error_task_sha256,
                    "repair_union_indices_sha256": repair_union_indices_sha256,
                    "strict_invalid_pass_count": len(strict_invalid_pass_indices),
                    "strict_invalid_pass_indices_sha256": strict_invalid_pass_indices_sha256,
                    "strict_invalid_pass_task_file_sha256": strict_invalid_pass_task_sha256,
                    "task_file_sha256": task_sha256,
                },
                "source": {
                    "artifacts": source_fingerprints,
                    "routing_epoch": 3,
                    "task_count": num_tasks,
                },
                "source_partition": source_partition_value,
                "trace_contracts": qwen_repair_trace_contracts_value(),
            }
            manifest_bytes = _json_bytes(manifest)

            if (
                _source_fingerprints(source) != source_fingerprints
                or _taskset_records_in_evaluator_order(source_config, source_records) != ordered_source_records
                or _validated_code_provenance(_code_provenance()) != code_provenance
            ):
                raise RepairMaterializationError("source_changed_during_materialization")

            staging: Path | None = Path(tempfile.mkdtemp(prefix=f".{output.name}.repair-", dir=output_parent))
            try:
                assert staging is not None
                migration._atomic_write(staging / TASK_FILENAME, task_bytes)
                migration._atomic_write(staging / MISSING_ERROR_TASK_FILENAME, missing_error_task_bytes)
                migration._atomic_write(
                    staging / STRICT_INVALID_PASS_TASK_FILENAME,
                    strict_invalid_pass_task_bytes,
                )
                migration._atomic_write(staging / CONFIG_FILENAME, config_bytes)
                migration._atomic_write(staging / MANIFEST_FILENAME, manifest_bytes)

                def validate_published(path: Path, allow_incomplete: bool) -> None:
                    _validate_published(
                        path,
                        allow_incomplete,
                        expected_task_bytes=task_bytes,
                        expected_missing_error_task_bytes=missing_error_task_bytes,
                        expected_strict_invalid_pass_task_bytes=strict_invalid_pass_task_bytes,
                        expected_config_bytes=config_bytes,
                        expected_manifest_bytes=manifest_bytes,
                        approved_identifiers=approved_identifiers,
                        image_manifest=image_manifest,
                        image_manifest_sha256=image_manifest_sha256,
                    )

                migration._publish_directory(staging, output, validate_published)
                if not staging.exists():
                    staging = None
            finally:
                if staging is not None and staging.exists():
                    shutil.rmtree(staging)
    except migration.MigrationError as error:
        raise RepairMaterializationError(str(error)) from error

    return {
        "approved_repair_count": len(selected_records),
        "config_sha256": config_sha256,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "missing_or_errored_count": len(owed_indices),
        "ok": True,
        "repair_union_indices_sha256": repair_union_indices_sha256,
        "status": "materialized",
        "strict_invalid_pass_count": len(strict_invalid_pass_indices),
        "source_partition": source_partition_value,
        "task_file_sha256": task_sha256,
        "task_index_order_sha256": task_index_order_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--approved-task-file", type=Path, required=True)
    parser.add_argument("--approved-task-file-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = materialize(
            args.source_dir,
            args.approved_task_file,
            args.approved_task_file_sha256,
            args.output_dir,
        )
    except (OSError, RepairMaterializationError) as error:
        parser.error(str(error))
    print(json.dumps(summary, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
