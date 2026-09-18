#!/usr/bin/env python3
"""Deterministically merge two validated format-v3 pass-only Qwen SFT exports.

Only aggregate counts, hashes, revisions, and stable error codes are returned or
logged. Task identifiers are treated as opaque set-membership keys and are never
included in the merge manifest or process output.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Mapping

FORMAT_VERSION = 3
MERGE_SCHEMA_VERSION = 4
MERGE_KIND = "qwen-sft-aggregate-merge"
REPAIR_SELECTION_KIND = "qwen-aggregate-repair-selection"
REPAIR_ATTESTATION_KIND = "qwen-direct-repair-attestation"
REPAIR_ATTESTATION_SCHEMA_VERSION = 2
REPAIR_SELECTION_COPY_FILENAME = "repair_selection_manifest.json"
REPAIR_SELECTION_TASK_COPY_FILENAME = "repair_selection_tasks.txt"
REPAIR_SELECTION_MISSING_ERROR_COPY_FILENAME = "repair_selection_missing_or_errored_tasks.txt"
REPAIR_SELECTION_STRICT_INVALID_PASS_COPY_FILENAME = "repair_selection_strict_invalid_pass_tasks.txt"
REPAIR_SELECTION_SOURCE_FILES = {
    REPAIR_SELECTION_COPY_FILENAME: "repair_manifest.json",
    REPAIR_SELECTION_TASK_COPY_FILENAME: "repair_tasks.txt",
    REPAIR_SELECTION_MISSING_ERROR_COPY_FILENAME: "repair_missing_or_errored_tasks.txt",
    REPAIR_SELECTION_STRICT_INVALID_PASS_COPY_FILENAME: "repair_strict_invalid_pass_tasks.txt",
}
REPAIR_ATTESTATION_COPY_FILENAME = "qwen_repair_attestation.json"
MAX_SEQUENCE_TOKENS = 262_144
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_JSONL_ROW_BYTES = 128 * 1024 * 1024
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
SPLIT_POLICY = "sha256(split_salt + NUL + stable task identity SHA-256) modulo 10000"
LOSS_MASK = "message.trainable; exactly one final assistant message is true"
TASK_IDENTITY = "sha256(taskset id + NUL + dataset revision + NUL + approved opaque task slug)"
EXPECTED_MODEL = "Qwen3.8-2.4T-A95B"
FORMAT_CONTRACT = {
    "assistant_finish_reason": "retained verbatim for every sampled assistant message",
    "assistant_tool_calls": "OpenAI function-call objects",
    "history_assistant_reasoning": "retained verbatim",
    "loss_mask": LOSS_MASK,
    "sample_unit": "one unique sampled assistant node with its root-to-node context",
    "target": "authentic reasoning_content, content, tool_calls, and finish_reason",
    "task_identity": TASK_IDENTITY,
}
TARGET_RENDERING_CONTRACT_FILENAME = "target-rendering-contract.json"
TARGET_RENDERING_CONTRACT_SHA256 = "29740bb5171087055faddc961a620c66235c14e7faad81adfbd1424e56fb7e31"
TARGET_RENDERING_CONTRACT = {
    "kind": "terminal-bench-sft-target-rendering",
    "renderer": {
        "config": {
            "enable_thinking": True,
            "name": "nemotron-3",
            "normalize_tool_response_wrappers": False,
            "preserve_all_thinking": True,
            "preserve_thinking_between_tool_calls": False,
            "truncate_history_thinking": False,
            "ultra": False,
        },
        "repository_revision": "044d9e2541f6a911cacae9da353fc063911ef1f8",
    },
    "schema_version": 1,
    "tokenizer": {
        "repository": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16",
        "revision": "d51eab0d1f979ebc26b546e634a04f450d99158e",
    },
}
REQUIRED_ARTIFACT_PATHS = {
    "task-split.json": Path("task-split.json"),
    TARGET_RENDERING_CONTRACT_FILENAME: Path(TARGET_RENDERING_CONTRACT_FILENAME),
    "train/train.jsonl": Path("train/train.jsonl"),
    "validation/train.jsonl": Path("validation/train.jsonl"),
}
OPTIONAL_ARTIFACT_PATHS = {
    "qwen_router_epochs.jsonl": Path("qwen_router_epochs.jsonl"),
}
ARTIFACT_PATHS = REQUIRED_ARTIFACT_PATHS | OPTIONAL_ARTIFACT_PATHS
ATTESTED_SOURCE_ARTIFACTS = (
    "config.toml",
    "inputs/task_file.txt",
    "provenance.txt",
    "results.jsonl",
    "direct_workers.json",
)
SELECTION_SOURCE_ARTIFACTS = {
    "config": "config.toml",
    "direct_workers": "direct_workers.json",
    "image_manifest": "inputs/image_manifest.json",
    "inputs_manifest": "inputs/manifest.json",
    "provenance": "provenance.txt",
    "results": "results.jsonl",
    "source_config": "inputs/source_config.toml",
    "task_file": "inputs/task_file.txt",
}
REQUIRED_SUBMODULES = (
    "deps/pydantic-config",
    "deps/renderers",
    "deps/verifiers",
)
AT_FDCWD = -100
RENAME_NOREPLACE = 1
ROW_FIELDS = {
    "assistant_target_count",
    "history_reasoning_policy",
    "is_correct",
    "messages",
    "reward",
    "source_episode_id",
    "source_node_index",
    "source_split_row_index",
    "source_trace_index",
    "source_trajectory_assistant_turn_count",
    "target_assistant_message_index",
    "target_assistant_turn_index",
    "target_finish_reason",
    "target_has_reasoning",
    "task_id",
    "tools",
    "transcript_fidelity",
}


class MergeError(RuntimeError):
    """A fail-closed merge error represented by a non-sensitive stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise MergeError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class FileArtifact:
    bytes: int
    sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {"bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class SplitContract:
    policy: str
    split_salt: str
    validation_permyriad: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "policy": self.policy,
            "split_salt": self.split_salt,
            "validation_permyriad": self.validation_permyriad,
        }


@dataclass(frozen=True, slots=True)
class ExportBundle:
    role: str
    root: Path
    manifest: FileArtifact
    artifacts: Mapping[str, FileArtifact]
    split: SplitContract
    train_tasks: frozenset[str]
    validation_tasks: frozenset[str]
    source_artifacts: Mapping[str, FileArtifact]
    exporter_sha256: str
    taskset_id: str
    dataset_revision: str
    input_traces: int
    approved_tasks: int
    routing_epoch: int | None
    declared_counts: Mapping[str, Any]
    exclusion: ExclusionBinding | None
    target_rendering_contract_body: bytes

    @property
    def tasks(self) -> frozenset[str]:
        return self.train_tasks | self.validation_tasks


@dataclass(frozen=True, slots=True)
class ExclusionBinding:
    manifest: FileArtifact
    artifacts: Mapping[str, FileArtifact]
    approved_task_count: int
    missing_or_errored_count: int
    strict_invalid_pass_count: int
    union_count: int


@dataclass(frozen=True, slots=True)
class SplitStats:
    rows: int
    tasks: int
    artifact: FileArtifact


@dataclass(frozen=True, slots=True)
class BundleStats:
    train: SplitStats
    validation: SplitStats

    @property
    def rows(self) -> int:
        return self.train.rows + self.validation.rows

    @property
    def tasks(self) -> int:
        return self.train.tasks + self.validation.tasks


@dataclass(frozen=True, slots=True)
class RepairSelection:
    artifact: FileArtifact
    task_count: int
    task_file_sha256: str
    repair_union_indices_sha256: str
    missing_or_errored_count: int
    strict_invalid_pass_count: int
    union_slugs: frozenset[str]
    missing_or_errored_slugs: frozenset[str]
    strict_invalid_pass_slugs: frozenset[str]
    selection_artifacts: Mapping[str, FileArtifact]
    selection_paths: Mapping[str, Path]
    source_artifacts: Mapping[str, FileArtifact]
    source_task_count: int
    source_routing_epoch: int
    repair_config_sha256: str
    materializer_sha256: str
    exporter_sha256: str
    repository_revision: str
    submodules: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class RepairAttestation:
    artifact: FileArtifact
    source_artifacts: Mapping[str, FileArtifact]
    task_count: int
    task_file_sha256: str
    taskset_id: str
    dataset_revision: str
    repository_revision: str
    submodules: Mapping[str, str]
    missing_or_errored_count: int
    strict_invalid_pass_count: int
    repair_union_indices_sha256: str


@dataclass(frozen=True, slots=True)
class RowIdentity:
    task_id: str
    source_episode_id: str
    source_node_index: int
    source_split_row_index: int
    source_trace_index: int
    source_trajectory_assistant_turn_count: int
    target_assistant_turn_index: int
    target_has_reasoning: bool


@dataclass(frozen=True, slots=True)
class MergeOptions:
    original_export_dir: Path
    original_export_manifest_sha256: str
    original_export_tree_sha256: str
    repair_export_dir: Path
    repair_export_manifest_sha256: str
    repair_export_tree_sha256: str
    repair_selection_manifest: Path
    repair_selection_manifest_sha256: str
    repair_attestation_manifest: Path
    repair_attestation_manifest_sha256: str
    output_dir: Path
    project_dir: Path
    expected_project_revision: str


class ArtifactSink:
    """Exclusive mode-0600 writer that hashes the exact bytes persisted."""

    def __init__(self, path: Path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        self._handle = os.fdopen(descriptor, "wb")
        self._digest = hashlib.sha256()
        self._bytes = 0

    def write(self, data: bytes) -> None:
        self._handle.write(data)
        self._digest.update(data)
        self._bytes += len(data)

    def close(self) -> FileArtifact:
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        return FileArtifact(bytes=self._bytes, sha256=self._digest.hexdigest())

    def abort(self) -> None:
        if not self._handle.closed:
            self._handle.close()


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MergeError("output_not_strict_json") from error


def _parse_json(body: bytes, code: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        return json.loads(
            body,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise MergeError(code) from error


def _parse_json_object(body: bytes, code: str) -> dict[str, Any]:
    value = _parse_json(body, code)
    if not isinstance(value, dict):
        raise MergeError(code)
    return value


def _open_regular(path: Path, code: str) -> tuple[BinaryIO, os.stat_result]:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        metadata = os.fstat(descriptor)
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise MergeError(code) from error
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise MergeError(code)
    return os.fdopen(descriptor, "rb"), metadata


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def _read_regular(
    path: Path,
    code: str,
    *,
    limit: int,
    required_mode: int | None = None,
) -> tuple[bytes, FileArtifact]:
    handle, before = _open_regular(path, code)
    if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
        handle.close()
        raise MergeError(code)
    try:
        body = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    except OSError as error:
        raise MergeError(code) from error
    finally:
        handle.close()
    if not _same_file(before, after):
        raise MergeError("source_changed")
    if len(body) > limit:
        raise MergeError(code)
    return body, FileArtifact(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


def _fingerprint_regular(path: Path, code: str, *, required_mode: int | None = None) -> FileArtifact:
    handle, before = _open_regular(path, code)
    if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
        handle.close()
        raise MergeError(code)
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(handle.fileno())
    except OSError as error:
        raise MergeError(code) from error
    finally:
        handle.close()
    if not _same_file(before, after):
        raise MergeError("source_changed")
    return FileArtifact(bytes=size, sha256=digest.hexdigest())


def _canonical_directory(path: Path, code: str) -> Path:
    absolute = path if path.is_absolute() else Path.cwd() / path
    normalized = Path(os.path.normpath(absolute))
    try:
        metadata = normalized.lstat()
        resolved = normalized.resolve(strict=True)
    except OSError as error:
        raise MergeError(code) from error
    if not stat.S_ISDIR(metadata.st_mode) or resolved != normalized:
        raise MergeError(code)
    return resolved


def _export_tree_sha256(path: Path, code: str) -> str:
    root = _canonical_directory(path, code)
    records: list[tuple[str, str, int, int, str]] = []
    try:
        root_metadata = root.lstat()
    except OSError as error:
        raise MergeError(code) from error
    records.append(("directory", ".", stat.S_IMODE(root_metadata.st_mode), 0, ""))
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            raise MergeError(code) from error
        for entry in entries:
            entry_path = Path(entry.path)
            relative = entry_path.relative_to(root).as_posix()
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise MergeError(code) from error
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISDIR(metadata.st_mode):
                try:
                    if entry_path.resolve(strict=True) != entry_path:
                        raise MergeError(code)
                except OSError as error:
                    raise MergeError(code) from error
                records.append(("directory", relative, mode, 0, ""))
                pending.append(entry_path)
            elif stat.S_ISREG(metadata.st_mode):
                artifact = _fingerprint_regular(entry_path, code)
                records.append(("file", relative, mode, artifact.bytes, artifact.sha256))
            else:
                raise MergeError(code)
    payload = json.dumps(records, ensure_ascii=True, separators=(",", ":"), sort_keys=False).encode() + b"\n"
    return hashlib.sha256(payload).hexdigest()


def _resolve_output(path: Path) -> tuple[Path, Path]:
    absolute = path if path.is_absolute() else Path.cwd() / path
    normalized = Path(os.path.normpath(absolute))
    if not normalized.name:
        raise MergeError("output_path_invalid")
    parent = _canonical_directory(normalized.parent, "output_parent_invalid")
    output = parent / normalized.name
    if output != normalized or output == parent:
        raise MergeError("output_path_invalid")
    return parent, output


def _artifact_record(value: object, code: str) -> FileArtifact:
    if not isinstance(value, dict) or set(value) != {"bytes", "sha256"}:
        raise MergeError(code)
    size = value.get("bytes")
    digest = value.get("sha256")
    if not _is_plain_int(size) or size < 0 or not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        raise MergeError(code)
    return FileArtifact(bytes=size, sha256=digest)


def _task_ids(value: object) -> frozenset[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or SHA256_PATTERN.fullmatch(item) is None for item in value
    ):
        raise MergeError("task_split_invalid")
    if value != sorted(value) or len(value) != len(set(value)):
        raise MergeError("task_split_invalid")
    return frozenset(value)


def _split_for_task(task_id: str, contract: SplitContract) -> str:
    digest = hashlib.sha256(f"{contract.split_salt}\0{task_id}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 10_000
    return "validation" if bucket < contract.validation_permyriad else "train"


def _task_identity_sha256(taskset_id: str, dataset_revision: str, slug: str) -> str:
    return hashlib.sha256(f"{taskset_id}\0{dataset_revision}\0{slug}".encode("utf-8")).hexdigest()


def _load_export(path: Path, role: str) -> ExportBundle:
    root = _canonical_directory(path, f"{role}_export_invalid")
    manifest_body, manifest_artifact = _read_regular(
        root / "manifest.json",
        f"{role}_manifest_invalid",
        limit=MAX_METADATA_BYTES,
    )
    manifest = _parse_json_object(manifest_body, f"{role}_manifest_invalid")
    expected_manifest_keys = {
        "artifacts",
        "config",
        "counts",
        "exporter",
        "format",
        "max_sequence_tokens",
        "selection",
        "source_artifacts",
        "split",
        "target_rendering",
    }
    if role == "original":
        expected_manifest_keys.add("routing_epochs")
        if "exclusion_selection" in manifest:
            expected_manifest_keys.add("exclusion_selection")
    if set(manifest) != expected_manifest_keys:
        raise MergeError(f"{role}_manifest_contract_invalid")
    exporter = manifest.get("exporter")
    format_contract = manifest.get("format")
    split_value = manifest.get("split")
    config = manifest.get("config")
    if (
        not isinstance(exporter, dict)
        or set(exporter) != {"file_sha256", "format_version"}
        or exporter.get("format_version") != FORMAT_VERSION
        or not isinstance(exporter.get("file_sha256"), str)
        or SHA256_PATTERN.fullmatch(exporter["file_sha256"]) is None
        or manifest.get("selection") != "pass-only"
        or manifest.get("max_sequence_tokens") != MAX_SEQUENCE_TOKENS
        or format_contract != FORMAT_CONTRACT
        or manifest.get("target_rendering") != TARGET_RENDERING_CONTRACT
        or not isinstance(config, dict)
        or set(config)
        != {
            "capture_model_io",
            "dataset_revision",
            "max_input_tokens",
            "max_output_tokens",
            "max_total_tokens",
            "model",
            "num_rollouts",
            "taskset_id",
        }
        or config.get("capture_model_io") is not True
        or config.get("model") != EXPECTED_MODEL
        or config.get("max_input_tokens") != MAX_SEQUENCE_TOKENS
        or config.get("max_output_tokens") != MAX_SEQUENCE_TOKENS
        or config.get("max_total_tokens") != MAX_SEQUENCE_TOKENS
        or not _is_plain_int(config.get("num_rollouts"))
        or config["num_rollouts"] != 1
        or not isinstance(config.get("taskset_id"), str)
        or not config["taskset_id"]
        or "\x00" in config["taskset_id"]
        or not isinstance(config.get("dataset_revision"), str)
        or GIT_SHA_PATTERN.fullmatch(config["dataset_revision"]) is None
        or not isinstance(split_value, dict)
        or split_value.get("policy") != SPLIT_POLICY
        or not isinstance(split_value.get("split_salt"), str)
        or not split_value["split_salt"]
        or "\x00" in split_value["split_salt"]
        or not _is_plain_int(split_value.get("validation_permyriad"))
        or not 0 <= split_value["validation_permyriad"] < 10_000
    ):
        raise MergeError(f"{role}_manifest_contract_invalid")
    split = SplitContract(
        policy=SPLIT_POLICY,
        split_salt=split_value["split_salt"],
        validation_permyriad=split_value["validation_permyriad"],
    )

    artifact_values = manifest.get("artifacts")
    expected_artifacts = set(REQUIRED_ARTIFACT_PATHS)
    if role == "original":
        expected_artifacts.update(OPTIONAL_ARTIFACT_PATHS)
    if not isinstance(artifact_values, dict) or set(artifact_values) != expected_artifacts:
        raise MergeError(f"{role}_manifest_artifacts_invalid")
    artifacts = {
        name: _artifact_record(artifact_values[name], f"{role}_manifest_artifacts_invalid") for name in artifact_values
    }
    for name in set(artifact_values) & set(OPTIONAL_ARTIFACT_PATHS):
        if _fingerprint_regular(root / ARTIFACT_PATHS[name], "artifact_invalid") != artifacts[name]:
            raise MergeError("artifact_hash_mismatch")
    target_rendering_contract_body, target_rendering_contract_artifact = _read_regular(
        root / ARTIFACT_PATHS[TARGET_RENDERING_CONTRACT_FILENAME],
        "target_rendering_contract_invalid",
        limit=MAX_METADATA_BYTES,
        required_mode=0o600,
    )
    if (
        target_rendering_contract_artifact != artifacts[TARGET_RENDERING_CONTRACT_FILENAME]
        or target_rendering_contract_artifact.sha256 != TARGET_RENDERING_CONTRACT_SHA256
        or _parse_json_object(target_rendering_contract_body, "target_rendering_contract_invalid")
        != TARGET_RENDERING_CONTRACT
    ):
        raise MergeError("target_rendering_contract_invalid")
    task_split_body, task_split_artifact = _read_regular(
        root / ARTIFACT_PATHS["task-split.json"],
        "task_split_invalid",
        limit=MAX_METADATA_BYTES,
    )
    if task_split_artifact != artifacts["task-split.json"]:
        raise MergeError("artifact_hash_mismatch")
    task_split = _parse_json_object(task_split_body, "task_split_invalid")
    if (
        set(task_split)
        != {
            "format_version",
            "split_salt",
            "validation_permyriad",
            "train_task_sha256",
            "validation_task_sha256",
        }
        or task_split.get("format_version") != FORMAT_VERSION
        or task_split.get("split_salt") != split.split_salt
        or task_split.get("validation_permyriad") != split.validation_permyriad
    ):
        raise MergeError("task_split_invalid")
    train_tasks = _task_ids(task_split.get("train_task_sha256"))
    validation_tasks = _task_ids(task_split.get("validation_task_sha256"))
    if train_tasks & validation_tasks:
        raise MergeError("task_split_overlap")
    if not train_tasks and not validation_tasks:
        raise MergeError("task_split_empty")
    if any(_split_for_task(task_id, split) != "train" for task_id in train_tasks) or any(
        _split_for_task(task_id, split) != "validation" for task_id in validation_tasks
    ):
        raise MergeError("task_split_assignment_invalid")
    counts = manifest.get("counts")
    source_artifact_values = manifest.get("source_artifacts")
    if not isinstance(counts, dict) or not isinstance(source_artifact_values, dict):
        raise MergeError(f"{role}_manifest_counts_invalid")
    source_artifacts = {
        name: _artifact_record(record, f"{role}_manifest_source_artifacts_invalid")
        for name, record in source_artifact_values.items()
    }
    if not set(SELECTION_SOURCE_ARTIFACTS.values()).issubset(source_artifacts):
        raise MergeError(f"{role}_manifest_source_artifacts_invalid")
    input_traces = counts.get("input_traces")
    approved_tasks = counts.get("approved_tasks", input_traces)
    if (
        not _is_plain_int(input_traces)
        or input_traces < len(train_tasks | validation_tasks)
        or not _is_plain_int(approved_tasks)
        or approved_tasks < input_traces
        or (role == "repair" and approved_tasks != input_traces)
    ):
        raise MergeError(f"{role}_manifest_counts_invalid")
    exclusion: ExclusionBinding | None = None
    if "exclusion_selection" in manifest:
        value = manifest["exclusion_selection"]
        artifact_values = value.get("artifacts") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "approved_task_count",
                "artifacts",
                "manifest",
                "missing_or_errored_count",
                "strict_invalid_pass_count",
                "union_count",
            }
            or not isinstance(artifact_values, dict)
            or set(artifact_values) != {"missing_or_errored_task_file", "strict_invalid_pass_task_file", "task_file"}
        ):
            raise MergeError(f"{role}_exclusion_contract_invalid")
        manifest_binding = _artifact_record(value.get("manifest"), f"{role}_exclusion_contract_invalid")
        exclusion_artifacts = {
            name: _artifact_record(record, f"{role}_exclusion_contract_invalid")
            for name, record in artifact_values.items()
        }
        count_values = {
            name: value.get(name)
            for name in (
                "approved_task_count",
                "missing_or_errored_count",
                "strict_invalid_pass_count",
                "union_count",
            )
        }
        missing_tasks = counts.get("exclusion_missing_tasks")
        excluded_present = counts.get("exclusion_selected_traces")
        if (
            any(not _is_plain_int(item) or item < 0 for item in count_values.values())
            or "approved_tasks" not in counts
            or count_values["approved_task_count"] != approved_tasks
            or count_values["missing_or_errored_count"] + count_values["strict_invalid_pass_count"]
            != count_values["union_count"]
            or counts.get("exclusion_missing_or_errored_tasks") != count_values["missing_or_errored_count"]
            or counts.get("exclusion_strict_invalid_pass_tasks") != count_values["strict_invalid_pass_count"]
            or not _is_plain_int(missing_tasks)
            or missing_tasks < 0
            or not _is_plain_int(excluded_present)
            or excluded_present < 0
            or input_traces + missing_tasks != approved_tasks
            or excluded_present + missing_tasks != count_values["union_count"]
        ):
            raise MergeError(f"{role}_exclusion_contract_invalid")
        exclusion = ExclusionBinding(
            manifest=manifest_binding,
            artifacts=exclusion_artifacts,
            approved_task_count=count_values["approved_task_count"],
            missing_or_errored_count=count_values["missing_or_errored_count"],
            strict_invalid_pass_count=count_values["strict_invalid_pass_count"],
            union_count=count_values["union_count"],
        )
    routing_epoch: int | None = None
    if role == "original":
        routing = manifest.get("routing_epochs")
        routing_inputs = routing.get("input_traces") if isinstance(routing, dict) else None
        if (
            not isinstance(routing, dict)
            or not _is_plain_int(routing.get("current_epoch"))
            or routing["current_epoch"] != 3
            or not isinstance(routing_inputs, dict)
            or set(routing_inputs) != {"1", "2", "3"}
            or any(not _is_plain_int(value) or value < 0 for value in routing_inputs.values())
            or sum(routing_inputs.values()) != input_traces
            or "qwen_router_epochs.jsonl" not in source_artifacts
            or source_artifacts["qwen_router_epochs.jsonl"] != artifacts["qwen_router_epochs.jsonl"]
        ):
            raise MergeError("original_routing_evidence_invalid")
        routing_epoch = 3
    return ExportBundle(
        role=role,
        root=root,
        manifest=manifest_artifact,
        artifacts=artifacts,
        split=split,
        train_tasks=train_tasks,
        validation_tasks=validation_tasks,
        source_artifacts=source_artifacts,
        exporter_sha256=exporter["file_sha256"],
        taskset_id=config["taskset_id"],
        dataset_revision=config["dataset_revision"],
        input_traces=input_traces,
        approved_tasks=approved_tasks,
        routing_epoch=routing_epoch,
        declared_counts=counts,
        exclusion=exclusion,
        target_rendering_contract_body=target_rendering_contract_body,
    )


def _validate_tool_call(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"function", "id", "type"}:
        raise MergeError("row_tool_contract_invalid")
    function = value.get("function")
    if (
        value.get("type") != "function"
        or not isinstance(value.get("id"), str)
        or not value["id"]
        or not isinstance(function, dict)
        or set(function) != {"arguments", "name"}
        or not isinstance(function.get("name"), str)
        or not function["name"]
        or not isinstance(function.get("arguments"), str)
    ):
        raise MergeError("row_tool_contract_invalid")
    _parse_json(function["arguments"].encode("utf-8"), "row_tool_contract_invalid")


def _validate_tool_schema(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise MergeError("row_tool_contract_invalid")
    for tool in value:
        function = tool.get("function") if isinstance(tool, dict) else None
        if (
            not isinstance(tool, dict)
            or tool.get("type", "function") != "function"
            or not isinstance(function, dict)
            or not isinstance(function.get("name"), str)
            or not function["name"]
            or not isinstance(function.get("description", ""), str)
            or not isinstance(function.get("parameters", {}), dict)
            or (function.get("strict") is not None and not isinstance(function["strict"], bool))
        ):
            raise MergeError("row_tool_contract_invalid")


def _validate_messages(messages: object, target_index: int) -> None:
    if not isinstance(messages, list) or not messages or target_index != len(messages) - 1:
        raise MergeError("row_target_invalid")
    targets: list[int] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or not isinstance(message.get("trainable"), bool):
            raise MergeError("row_target_invalid")
        role = message.get("role")
        content = message.get("content")
        if role not in {"assistant", "system", "tool", "user"} or not isinstance(content, str):
            raise MergeError("row_message_contract_invalid")
        if message["trainable"]:
            targets.append(index)
        if role == "assistant":
            if "finish_reason" not in message or not set(message).issubset(
                {"content", "finish_reason", "reasoning_content", "role", "tool_calls", "trainable"}
            ):
                raise MergeError("row_message_contract_invalid")
            reasoning = message.get("reasoning_content")
            if "reasoning_content" in message and not isinstance(reasoning, str):
                raise MergeError("row_reasoning_contract_invalid")
            finish_reason = message.get("finish_reason")
            if finish_reason is not None and (not isinstance(finish_reason, str) or not finish_reason):
                raise MergeError("row_finish_reason_contract_invalid")
            tool_calls = message.get("tool_calls")
            if tool_calls is not None:
                if not isinstance(tool_calls, list) or not tool_calls:
                    raise MergeError("row_tool_contract_invalid")
                for tool_call in tool_calls:
                    _validate_tool_call(tool_call)
        elif role == "tool":
            if not set(message).issubset({"content", "name", "role", "tool_call_id", "trainable"}):
                raise MergeError("row_message_contract_invalid")
            if not isinstance(message.get("tool_call_id"), str) or not message["tool_call_id"]:
                raise MergeError("row_tool_contract_invalid")
            if "name" in message and not isinstance(message["name"], str):
                raise MergeError("row_tool_contract_invalid")
        elif set(message) != {"content", "role", "trainable"}:
            raise MergeError("row_message_contract_invalid")
    if len(targets) != 1 or targets[0] != target_index or messages[target_index].get("role") != "assistant":
        raise MergeError("row_target_invalid")


def _validate_row(
    raw_line: bytes,
    expected_tasks: frozenset[str],
    *,
    require_routing_epoch: bool,
) -> RowIdentity:
    row = _parse_json_object(raw_line, "row_invalid")
    expected_fields = set(ROW_FIELDS)
    if require_routing_epoch:
        expected_fields.add("routing_epoch")
    if set(row) != expected_fields:
        raise MergeError("row_contract_invalid")
    task_id = row.get("task_id")
    reward = row.get("reward")
    messages = row.get("messages")
    if not isinstance(task_id, str) or SHA256_PATTERN.fullmatch(task_id) is None or task_id not in expected_tasks:
        raise MergeError("row_task_membership_invalid")
    if (
        isinstance(reward, bool)
        or not isinstance(reward, (int, float))
        or not math.isfinite(reward)
        or float(reward) != 1.0
        or row.get("is_correct") is not True
    ):
        raise MergeError("row_not_pass")
    if not _is_plain_int(row.get("assistant_target_count")) or row["assistant_target_count"] != 1:
        raise MergeError("row_target_invalid")
    target_index = row.get("target_assistant_message_index")
    if (
        not _is_plain_int(target_index)
        or target_index < 0
        or row.get("history_reasoning_policy") != "preserve_all_assistant_reasoning"
    ):
        raise MergeError("row_target_invalid")
    _validate_messages(messages, target_index)
    target_has_reasoning = row.get("target_has_reasoning")
    reasoning = messages[target_index].get("reasoning_content")
    if not isinstance(target_has_reasoning, bool) or target_has_reasoning != bool(str(reasoning or "").strip()):
        raise MergeError("row_reasoning_contract_invalid")
    target_finish_reason = row.get("target_finish_reason")
    if (
        not isinstance(target_finish_reason, str)
        or not target_finish_reason
        or messages[target_index].get("finish_reason") != target_finish_reason
    ):
        raise MergeError("row_finish_reason_contract_invalid")
    fidelity = row.get("transcript_fidelity")
    fidelity_fields = {
        "retained_assistant_reasoning_fields",
        "retained_sampled_finish_reasons",
        "source_assistant_reasoning_fields",
        "source_sampled_finish_reasons",
    }
    retained_reasoning_fields = sum(
        "reasoning_content" in message for message in messages if message.get("role") == "assistant"
    )
    retained_finish_reasons = sum(
        isinstance(message.get("finish_reason"), str) for message in messages if message.get("role") == "assistant"
    )
    if (
        not isinstance(fidelity, dict)
        or set(fidelity) != fidelity_fields
        or any(not _is_plain_int(fidelity.get(field)) or fidelity[field] < 0 for field in fidelity_fields)
        or fidelity["source_assistant_reasoning_fields"] != fidelity["retained_assistant_reasoning_fields"]
        or fidelity["source_sampled_finish_reasons"] != fidelity["retained_sampled_finish_reasons"]
        or fidelity["retained_assistant_reasoning_fields"] != retained_reasoning_fields
        or fidelity["retained_sampled_finish_reasons"] != retained_finish_reasons
    ):
        raise MergeError("row_transcript_fidelity_invalid")
    _validate_tool_schema(row.get("tools"))
    integer_fields = (
        "source_node_index",
        "source_split_row_index",
        "source_trace_index",
        "source_trajectory_assistant_turn_count",
        "target_assistant_turn_index",
    )
    if any(not _is_plain_int(row.get(field)) or row[field] < 0 for field in integer_fields):
        raise MergeError("row_source_contract_invalid")
    if (
        row["source_trajectory_assistant_turn_count"] < 1
        or row["target_assistant_turn_index"] >= row["source_trajectory_assistant_turn_count"]
        or not isinstance(row.get("source_episode_id"), str)
        or SHA256_PATTERN.fullmatch(row["source_episode_id"]) is None
    ):
        raise MergeError("row_source_contract_invalid")
    if require_routing_epoch:
        if not _is_plain_int(row.get("routing_epoch")) or row["routing_epoch"] not in {1, 2, 3}:
            raise MergeError("row_routing_contract_invalid")
    return RowIdentity(
        task_id=task_id,
        source_episode_id=row["source_episode_id"],
        source_node_index=row["source_node_index"],
        source_split_row_index=row["source_split_row_index"],
        source_trace_index=row["source_trace_index"],
        source_trajectory_assistant_turn_count=row["source_trajectory_assistant_turn_count"],
        target_assistant_turn_index=row["target_assistant_turn_index"],
        target_has_reasoning=target_has_reasoning,
    )


def _copy_split(
    bundle: ExportBundle,
    split_name: str,
    expected_tasks: frozenset[str],
    sink: ArtifactSink,
) -> SplitStats:
    artifact_name = "train/train.jsonl" if split_name == "train" else "validation/train.jsonl"
    expected_artifact = bundle.artifacts[artifact_name]
    handle, before = _open_regular(bundle.root / ARTIFACT_PATHS[artifact_name], "artifact_invalid")
    digest = hashlib.sha256()
    size = 0
    rows = 0
    seen_tasks: set[str] = set()
    task_rows: dict[str, list[RowIdentity]] = {}
    closed_tasks: set[str] = set()
    current_task: str | None = None
    try:
        while True:
            raw_line = handle.readline(MAX_JSONL_ROW_BYTES + 1)
            if not raw_line:
                break
            if len(raw_line) > MAX_JSONL_ROW_BYTES:
                raise MergeError("row_too_large")
            digest.update(raw_line)
            size += len(raw_line)
            if not raw_line.endswith(b"\n") or not raw_line.strip():
                raise MergeError("jsonl_invalid")
            identity = _validate_row(
                raw_line,
                expected_tasks,
                require_routing_epoch=bundle.role == "original",
            )
            if _split_for_task(identity.task_id, bundle.split) != split_name:
                raise MergeError("row_split_assignment_invalid")
            if identity.task_id != current_task:
                if identity.task_id in closed_tasks:
                    raise MergeError("task_rows_not_contiguous")
                if current_task is not None:
                    closed_tasks.add(current_task)
                current_task = identity.task_id
            seen_tasks.add(identity.task_id)
            task_rows.setdefault(identity.task_id, []).append(identity)
            sink.write(raw_line)
            rows += 1
        after = os.fstat(handle.fileno())
    except OSError as error:
        raise MergeError("artifact_invalid") from error
    finally:
        handle.close()
    if not _same_file(before, after):
        raise MergeError("source_changed")
    observed = FileArtifact(bytes=size, sha256=digest.hexdigest())
    if observed != expected_artifact:
        raise MergeError("artifact_hash_mismatch")
    if seen_tasks != set(expected_tasks):
        raise MergeError("task_split_membership_invalid")
    seen_episode_ids: set[str] = set()
    seen_trace_indices: set[int] = set()
    seen_split_indices: set[int] = set()
    for identities in task_rows.values():
        first = identities[0]
        if (
            len(identities) != first.source_trajectory_assistant_turn_count
            or [item.target_assistant_turn_index for item in identities] != list(range(len(identities)))
            or any(
                (
                    item.source_episode_id,
                    item.source_split_row_index,
                    item.source_trace_index,
                    item.source_trajectory_assistant_turn_count,
                )
                != (
                    first.source_episode_id,
                    first.source_split_row_index,
                    first.source_trace_index,
                    first.source_trajectory_assistant_turn_count,
                )
                for item in identities
            )
            or [item.source_node_index for item in identities]
            != sorted({item.source_node_index for item in identities})
            or first.source_episode_id in seen_episode_ids
            or first.source_trace_index in seen_trace_indices
            or first.source_split_row_index in seen_split_indices
        ):
            raise MergeError("task_row_group_invalid")
        if not any(item.target_has_reasoning for item in identities):
            raise MergeError("task_reasoning_contract_invalid")
        seen_episode_ids.add(first.source_episode_id)
        seen_trace_indices.add(first.source_trace_index)
        seen_split_indices.add(first.source_split_row_index)
    return SplitStats(rows=rows, tasks=len(seen_tasks), artifact=observed)


def _validate_declared_counts(bundle: ExportBundle, stats: BundleStats) -> None:
    counts = bundle.declared_counts
    expected = {
        "emitted_rows": stats.rows,
        "selected_traces": stats.tasks,
        "selected_pass_traces": stats.tasks,
        "train_rows": stats.train.rows,
        "train_traces": stats.train.tasks,
        "validation_rows": stats.validation.rows,
        "validation_traces": stats.validation.tasks,
    }
    if any(not _is_plain_int(counts.get(key, 0)) or counts.get(key, 0) != value for key, value in expected.items()):
        raise MergeError(f"{bundle.role}_manifest_counts_invalid")
    selected_failures = counts.get("selected_fail_traces", 0)
    if not _is_plain_int(selected_failures) or selected_failures != 0:
        raise MergeError(f"{bundle.role}_manifest_counts_invalid")


def _selection_artifact_record(value: object) -> FileArtifact:
    if not isinstance(value, dict) or set(value) != {"sha256", "size_bytes"}:
        raise MergeError("repair_selection_contract_invalid")
    size = value.get("size_bytes")
    digest = value.get("sha256")
    if not _is_plain_int(size) or size < 0 or not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        raise MergeError("repair_selection_contract_invalid")
    return FileArtifact(bytes=size, sha256=digest)


def _selection_slugs(body: bytes, *, allow_empty: bool) -> tuple[str, ...]:
    if body and not body.endswith(b"\n"):
        raise MergeError("repair_selection_contract_invalid")
    try:
        values = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise MergeError("repair_selection_contract_invalid") from error
    if any(not value or value.strip() != value or "\t" in value or "\x00" in value for value in values):
        raise MergeError("repair_selection_contract_invalid")
    if len(values) != len(set(values)) or (not allow_empty and not values):
        raise MergeError("repair_selection_contract_invalid")
    return tuple(values)


def _load_repair_selection(path: Path, expected_sha256: str) -> RepairSelection:
    if SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise MergeError("repair_selection_digest_invalid")
    body, artifact = _read_regular(
        path,
        "repair_selection_invalid",
        limit=MAX_METADATA_BYTES,
        required_mode=0o600,
    )
    if artifact.sha256 != expected_sha256:
        raise MergeError("repair_selection_digest_mismatch")
    manifest = _parse_json_object(body, "repair_selection_invalid")
    approval = manifest.get("approval")
    code = manifest.get("code")
    config = manifest.get("config")
    selection = manifest.get("selection")
    planner = manifest.get("planner")
    source = manifest.get("source")
    if (
        set(manifest) != {"approval", "code", "config", "kind", "planner", "schema_version", "selection", "source"}
        or manifest.get("kind") != REPAIR_SELECTION_KIND
        or not _is_plain_int(manifest.get("schema_version"))
        or manifest["schema_version"] != 2
        or not isinstance(approval, dict)
        or set(approval) != {"approved_task_count", "approved_task_file_sha256"}
        or not _is_plain_int(approval.get("approved_task_count"))
        or approval["approved_task_count"] < 1
        or not isinstance(approval.get("approved_task_file_sha256"), str)
        or SHA256_PATTERN.fullmatch(approval["approved_task_file_sha256"]) is None
        or not isinstance(code, dict)
        or set(code) != {"exporter_sha256", "materializer_sha256", "repository_revision", "submodules"}
        or not isinstance(code.get("exporter_sha256"), str)
        or SHA256_PATTERN.fullmatch(code["exporter_sha256"]) is None
        or not isinstance(code.get("materializer_sha256"), str)
        or SHA256_PATTERN.fullmatch(code["materializer_sha256"]) is None
        or not isinstance(code.get("repository_revision"), str)
        or GIT_SHA_PATTERN.fullmatch(code["repository_revision"]) is None
        or not isinstance(code.get("submodules"), dict)
        or set(code["submodules"]) != set(REQUIRED_SUBMODULES)
        or any(
            not isinstance(revision, str) or GIT_SHA_PATTERN.fullmatch(revision) is None
            for revision in code["submodules"].values()
        )
        or not isinstance(config, dict)
        or set(config)
        != {
            "capture_model_io",
            "enable_thinking",
            "max_concurrent",
            "max_total_tokens",
            "preserve_thinking",
            "provider_concurrency",
            "retry_class_count",
            "retry_policy_sha256",
            "sha256",
            "template_sha256",
        }
        or config.get("capture_model_io") is not True
        or config.get("enable_thinking") is not True
        or config.get("preserve_thinking") is not True
        or config.get("max_concurrent") != 64
        or config.get("max_total_tokens") != MAX_SEQUENCE_TOKENS
        or config.get("provider_concurrency") != 32
        or not _is_plain_int(config.get("retry_class_count"))
        or config["retry_class_count"] < 1
        or any(
            not isinstance(config.get(name), str) or SHA256_PATTERN.fullmatch(config[name]) is None
            for name in ("retry_policy_sha256", "sha256", "template_sha256")
        )
        or not isinstance(selection, dict)
        or set(selection)
        != {
            "approved_repair_count",
            "missing_or_errored_count",
            "missing_or_errored_indices_sha256",
            "missing_or_errored_task_file_sha256",
            "repair_union_indices_sha256",
            "strict_invalid_pass_count",
            "strict_invalid_pass_indices_sha256",
            "strict_invalid_pass_task_file_sha256",
            "task_file_sha256",
        }
        or not _is_plain_int(selection.get("approved_repair_count"))
        or selection["approved_repair_count"] < 1
        or not _is_plain_int(selection.get("missing_or_errored_count"))
        or selection["missing_or_errored_count"] < 0
        or not _is_plain_int(selection.get("strict_invalid_pass_count"))
        or selection["strict_invalid_pass_count"] < 0
        or selection["missing_or_errored_count"] + selection["strict_invalid_pass_count"]
        != selection["approved_repair_count"]
        or not isinstance(selection.get("task_file_sha256"), str)
        or SHA256_PATTERN.fullmatch(selection["task_file_sha256"]) is None
        or any(
            not isinstance(selection.get(name), str) or SHA256_PATTERN.fullmatch(selection[name]) is None
            for name in (
                "missing_or_errored_indices_sha256",
                "missing_or_errored_task_file_sha256",
                "repair_union_indices_sha256",
                "strict_invalid_pass_indices_sha256",
                "strict_invalid_pass_task_file_sha256",
            )
        )
        or not isinstance(planner, dict)
        or set(planner)
        != {
            "approved_task_count",
            "contract_verifiers_revision",
            "missing_or_errored_count",
            "module_sha256",
            "retained_count",
            "task_index_order_sha256",
        }
        or not _is_plain_int(planner.get("approved_task_count"))
        or not _is_plain_int(planner.get("missing_or_errored_count"))
        or not _is_plain_int(planner.get("retained_count"))
        or planner["missing_or_errored_count"] != selection["missing_or_errored_count"]
        or not isinstance(planner.get("contract_verifiers_revision"), str)
        or GIT_SHA_PATTERN.fullmatch(planner["contract_verifiers_revision"]) is None
        or not isinstance(planner.get("module_sha256"), str)
        or SHA256_PATTERN.fullmatch(planner["module_sha256"]) is None
        or not isinstance(planner.get("task_index_order_sha256"), str)
        or SHA256_PATTERN.fullmatch(planner["task_index_order_sha256"]) is None
        or not isinstance(source, dict)
        or set(source) != {"artifacts", "routing_epoch", "task_count"}
        or not _is_plain_int(source.get("routing_epoch"))
        or source["routing_epoch"] != 3
        or not _is_plain_int(source.get("task_count"))
        or source["task_count"] < 1
        or not isinstance(source.get("artifacts"), dict)
        or set(source["artifacts"]) != set(SELECTION_SOURCE_ARTIFACTS)
        or approval["approved_task_count"] != source["task_count"]
        or planner["approved_task_count"] != source["task_count"]
        or planner["retained_count"] + planner["missing_or_errored_count"] != source["task_count"]
    ):
        raise MergeError("repair_selection_contract_invalid")
    source_artifacts = {
        SELECTION_SOURCE_ARTIFACTS[label]: _selection_artifact_record(record)
        for label, record in source["artifacts"].items()
    }
    if source_artifacts["inputs/task_file.txt"].sha256 != approval["approved_task_file_sha256"]:
        raise MergeError("repair_selection_contract_invalid")
    selection_paths = {
        copy_name: (path if copy_name == REPAIR_SELECTION_COPY_FILENAME else path.parent / source_name)
        for copy_name, source_name in REPAIR_SELECTION_SOURCE_FILES.items()
    }
    selection_artifacts: dict[str, FileArtifact] = {REPAIR_SELECTION_COPY_FILENAME: artifact}
    selection_bodies: dict[str, bytes] = {REPAIR_SELECTION_COPY_FILENAME: body}
    for copy_name, source_path in selection_paths.items():
        if copy_name == REPAIR_SELECTION_COPY_FILENAME:
            continue
        selected_body, selected_artifact = _read_regular(
            source_path,
            "repair_selection_invalid",
            limit=MAX_METADATA_BYTES,
            required_mode=0o600,
        )
        selection_bodies[copy_name] = selected_body
        selection_artifacts[copy_name] = selected_artifact
    union_slugs = frozenset(_selection_slugs(selection_bodies[REPAIR_SELECTION_TASK_COPY_FILENAME], allow_empty=False))
    missing_slugs = frozenset(
        _selection_slugs(selection_bodies[REPAIR_SELECTION_MISSING_ERROR_COPY_FILENAME], allow_empty=True)
    )
    strict_slugs = frozenset(
        _selection_slugs(selection_bodies[REPAIR_SELECTION_STRICT_INVALID_PASS_COPY_FILENAME], allow_empty=True)
    )
    if (
        len(union_slugs) != selection["approved_repair_count"]
        or len(missing_slugs) != selection["missing_or_errored_count"]
        or len(strict_slugs) != selection["strict_invalid_pass_count"]
        or missing_slugs & strict_slugs
        or union_slugs != missing_slugs | strict_slugs
        or selection_artifacts[REPAIR_SELECTION_TASK_COPY_FILENAME].sha256 != selection["task_file_sha256"]
        or selection_artifacts[REPAIR_SELECTION_MISSING_ERROR_COPY_FILENAME].sha256
        != selection["missing_or_errored_task_file_sha256"]
        or selection_artifacts[REPAIR_SELECTION_STRICT_INVALID_PASS_COPY_FILENAME].sha256
        != selection["strict_invalid_pass_task_file_sha256"]
    ):
        raise MergeError("repair_selection_contract_invalid")
    return RepairSelection(
        artifact=artifact,
        task_count=selection["approved_repair_count"],
        task_file_sha256=selection["task_file_sha256"],
        repair_union_indices_sha256=selection["repair_union_indices_sha256"],
        missing_or_errored_count=selection["missing_or_errored_count"],
        strict_invalid_pass_count=selection["strict_invalid_pass_count"],
        union_slugs=union_slugs,
        missing_or_errored_slugs=missing_slugs,
        strict_invalid_pass_slugs=strict_slugs,
        selection_artifacts=selection_artifacts,
        selection_paths=selection_paths,
        source_artifacts=source_artifacts,
        source_task_count=source["task_count"],
        source_routing_epoch=source["routing_epoch"],
        repair_config_sha256=config["sha256"],
        materializer_sha256=code["materializer_sha256"],
        exporter_sha256=code["exporter_sha256"],
        repository_revision=code["repository_revision"],
        submodules={name: code["submodules"][name] for name in sorted(code["submodules"])},
    )


def _load_repair_attestation(
    path: Path,
    expected_sha256: str,
    repair_selection_sha256: str,
) -> RepairAttestation:
    if SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise MergeError("repair_attestation_digest_invalid")
    body, artifact = _read_regular(
        path,
        "repair_attestation_invalid",
        limit=MAX_METADATA_BYTES,
        required_mode=0o600,
    )
    if artifact.sha256 != expected_sha256:
        raise MergeError("repair_attestation_digest_mismatch")
    manifest = _parse_json_object(body, "repair_attestation_invalid")
    if set(manifest) != {
        "code",
        "corpus",
        "kind",
        "repair_selection_manifest_sha256",
        "routing",
        "selection",
        "schema_version",
        "source_artifacts",
    }:
        raise MergeError("repair_attestation_contract_invalid")
    source_values = manifest.get("source_artifacts")
    routing = manifest.get("routing")
    corpus = manifest.get("corpus")
    code = manifest.get("code")
    selection = manifest.get("selection")
    if (
        manifest.get("kind") != REPAIR_ATTESTATION_KIND
        or not _is_plain_int(manifest.get("schema_version"))
        or manifest["schema_version"] != REPAIR_ATTESTATION_SCHEMA_VERSION
        or manifest.get("repair_selection_manifest_sha256") != repair_selection_sha256
        or not isinstance(source_values, dict)
        or set(source_values) != set(ATTESTED_SOURCE_ARTIFACTS)
        or not isinstance(routing, dict)
        or set(routing)
        != {
            "manifest_schema_version",
            "provider_concurrency",
            "queue_size",
            "request_id_headers",
            "router_policy",
            "routing_epoch",
        }
        or not _is_plain_int(routing.get("routing_epoch"))
        or routing["routing_epoch"] != 1
        or not _is_plain_int(routing.get("manifest_schema_version"))
        or routing["manifest_schema_version"] != 3
        or not _is_plain_int(routing.get("provider_concurrency"))
        or routing["provider_concurrency"] != 32
        or not _is_plain_int(routing.get("queue_size"))
        or routing["queue_size"] != 32
        or routing.get("router_policy") != "consistent_hash"
        or routing.get("request_id_headers") != ["x-session-id"]
        or not isinstance(corpus, dict)
        or set(corpus) != {"dataset_revision", "task_count", "task_file_sha256", "taskset_id"}
        or not _is_plain_int(corpus.get("task_count"))
        or corpus["task_count"] < 1
        or not isinstance(corpus.get("task_file_sha256"), str)
        or SHA256_PATTERN.fullmatch(corpus["task_file_sha256"]) is None
        or not isinstance(corpus.get("taskset_id"), str)
        or not corpus["taskset_id"]
        or "\x00" in corpus["taskset_id"]
        or not isinstance(corpus.get("dataset_revision"), str)
        or GIT_SHA_PATTERN.fullmatch(corpus["dataset_revision"]) is None
        or not isinstance(code, dict)
        or set(code) != {"repository_revision", "submodules"}
        or not isinstance(code.get("repository_revision"), str)
        or GIT_SHA_PATTERN.fullmatch(code["repository_revision"]) is None
        or not isinstance(code.get("submodules"), dict)
        or set(code["submodules"]) != set(REQUIRED_SUBMODULES)
        or any(
            not isinstance(revision, str) or GIT_SHA_PATTERN.fullmatch(revision) is None
            for revision in code["submodules"].values()
        )
        or not isinstance(selection, dict)
        or set(selection)
        != {
            "missing_or_errored_count",
            "strict_invalid_pass_count",
            "union_count",
            "union_indices_sha256",
            "union_task_file_sha256",
        }
        or not _is_plain_int(selection.get("missing_or_errored_count"))
        or selection["missing_or_errored_count"] < 0
        or not _is_plain_int(selection.get("strict_invalid_pass_count"))
        or selection["strict_invalid_pass_count"] < 0
        or not _is_plain_int(selection.get("union_count"))
        or selection["union_count"] < 1
        or selection["missing_or_errored_count"] + selection["strict_invalid_pass_count"] != selection["union_count"]
        or selection["union_count"] != corpus.get("task_count")
        or not isinstance(selection.get("union_indices_sha256"), str)
        or SHA256_PATTERN.fullmatch(selection["union_indices_sha256"]) is None
        or not isinstance(selection.get("union_task_file_sha256"), str)
        or SHA256_PATTERN.fullmatch(selection["union_task_file_sha256"]) is None
        or selection["union_task_file_sha256"] != corpus.get("task_file_sha256")
    ):
        raise MergeError("repair_attestation_contract_invalid")
    source_artifacts = {
        name: _artifact_record(source_values[name], "repair_attestation_contract_invalid")
        for name in ATTESTED_SOURCE_ARTIFACTS
    }
    if source_artifacts["inputs/task_file.txt"].sha256 != corpus["task_file_sha256"]:
        raise MergeError("repair_attestation_contract_invalid")
    return RepairAttestation(
        artifact=artifact,
        source_artifacts=source_artifacts,
        task_count=corpus["task_count"],
        task_file_sha256=corpus["task_file_sha256"],
        taskset_id=corpus["taskset_id"],
        dataset_revision=corpus["dataset_revision"],
        repository_revision=code["repository_revision"],
        submodules={name: code["submodules"][name] for name in sorted(code["submodules"])},
        missing_or_errored_count=selection["missing_or_errored_count"],
        strict_invalid_pass_count=selection["strict_invalid_pass_count"],
        repair_union_indices_sha256=selection["union_indices_sha256"],
    )


def _run_git(project: Path, arguments: list[str], code: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(project), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise MergeError(code) from error
    if completed.stderr:
        raise MergeError(code)
    return completed.stdout


def _repository_provenance(project_dir: Path, expected_revision: str) -> dict[str, Any]:
    if GIT_SHA_PATTERN.fullmatch(expected_revision) is None:
        raise MergeError("project_revision_invalid")
    project = _canonical_directory(project_dir, "project_invalid")
    top_level = _run_git(project, ["rev-parse", "--show-toplevel"], "project_revision_unavailable").strip()
    head = _run_git(project, ["rev-parse", "HEAD"], "project_revision_unavailable").strip()
    status = _run_git(
        project,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        "project_status_unavailable",
    )
    if top_level != str(project) or head != expected_revision:
        raise MergeError("project_revision_mismatch")
    if status:
        raise MergeError("project_not_clean")
    revisions: dict[str, str] = {}
    for relative in REQUIRED_SUBMODULES:
        record = _run_git(project, ["ls-tree", head, "--", relative], "submodule_revision_unavailable").strip()
        fields = record.split(maxsplit=3)
        if (
            len(fields) != 4
            or fields[0] != "160000"
            or fields[1] != "commit"
            or GIT_SHA_PATTERN.fullmatch(fields[2]) is None
            or fields[3] != relative
        ):
            raise MergeError("submodule_revision_invalid")
        submodule = project / relative
        observed = _run_git(submodule, ["rev-parse", "HEAD"], "submodule_revision_unavailable").strip()
        submodule_status = _run_git(
            submodule,
            ["status", "--porcelain=v1", "--untracked-files=all"],
            "submodule_revision_unavailable",
        )
        if observed != fields[2] or submodule_status:
            raise MergeError("submodule_revision_mismatch")
        revisions[relative] = observed
    merger = project / "user" / "tianhaowu" / "terminal_bench_vmvm" / "merge_qwen_sft.py"
    exporter = project / "user" / "tianhaowu" / "terminal_bench_vmvm" / "export_sft.py"
    materializer = project / "user" / "tianhaowu" / "terminal_bench_vmvm" / "materialize_qwen_repair.py"
    merger_artifact = _fingerprint_regular(merger, "merger_code_invalid")
    exporter_artifact = _fingerprint_regular(exporter, "exporter_code_invalid")
    materializer_artifact = _fingerprint_regular(materializer, "materializer_code_invalid")
    return {
        "exporter_sha256": exporter_artifact.sha256,
        "materializer_sha256": materializer_artifact.sha256,
        "merger_sha256": merger_artifact.sha256,
        "repository_revision": head,
        "submodules": revisions,
    }


def _validate_code_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {
        "exporter_sha256",
        "materializer_sha256",
        "merger_sha256",
        "repository_revision",
        "submodules",
    }:
        raise MergeError("code_provenance_invalid")
    submodules = value.get("submodules")
    if (
        not isinstance(value.get("exporter_sha256"), str)
        or SHA256_PATTERN.fullmatch(value["exporter_sha256"]) is None
        or not isinstance(value.get("materializer_sha256"), str)
        or SHA256_PATTERN.fullmatch(value["materializer_sha256"]) is None
        or not isinstance(value.get("merger_sha256"), str)
        or SHA256_PATTERN.fullmatch(value["merger_sha256"]) is None
        or not isinstance(value.get("repository_revision"), str)
        or GIT_SHA_PATTERN.fullmatch(value["repository_revision"]) is None
        or not isinstance(submodules, dict)
        or set(submodules) != set(REQUIRED_SUBMODULES)
        or any(
            not isinstance(revision, str) or GIT_SHA_PATTERN.fullmatch(revision) is None
            for revision in submodules.values()
        )
    ):
        raise MergeError("code_provenance_invalid")
    return {
        "exporter_sha256": value["exporter_sha256"],
        "materializer_sha256": value["materializer_sha256"],
        "merger_sha256": value["merger_sha256"],
        "repository_revision": value["repository_revision"],
        "submodules": {name: submodules[name] for name in sorted(submodules)},
    }


def _write_exclusive(path: Path, body: bytes) -> FileArtifact:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise MergeError("output_write_failed") from error
    return FileArtifact(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    directories = [root]
    for current, names, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in names:
            child = current_path / name
            if child.is_symlink() or not child.is_dir():
                raise MergeError("output_tree_invalid")
            directories.append(child)
        for name in files:
            child = current_path / name
            metadata = child.lstat()
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise MergeError("output_mode_invalid")
    for directory in reversed(directories):
        os.chmod(directory, 0o700)
        _fsync_directory(directory)


def _publish_noreplace(staging: Path, output: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise MergeError("atomic_publish_unavailable")
    result = renameat2(
        AT_FDCWD,
        os.fsencode(staging),
        AT_FDCWD,
        os.fsencode(output),
        RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise MergeError("destination_exists")
        raise MergeError("atomic_publish_failed")
    _fsync_directory(output.parent)


def _bundle_manifest_binding(bundle: ExportBundle, tree_sha256: str) -> dict[str, Any]:
    return {
        "artifacts": {name: bundle.artifacts[name].as_dict() for name in sorted(bundle.artifacts)},
        "manifest": bundle.manifest.as_dict(),
        "source_task_file": bundle.source_artifacts["inputs/task_file.txt"].as_dict(),
        "tree_sha256": tree_sha256,
    }


def _counts(stats: BundleStats) -> dict[str, int]:
    return {
        "rows": stats.rows,
        "tasks": stats.tasks,
        "train_rows": stats.train.rows,
        "train_tasks": stats.train.tasks,
        "validation_rows": stats.validation.rows,
        "validation_tasks": stats.validation.tasks,
    }


def _validate_sources_unchanged(
    bundles: tuple[ExportBundle, ExportBundle],
    expected_tree_sha256: tuple[str, str],
    repair_selection: RepairSelection,
    repair_attestation_path: Path,
    repair_attestation_artifact: FileArtifact,
    repair_root: Path,
) -> None:
    for bundle, tree_sha256 in zip(bundles, expected_tree_sha256, strict=True):
        if _fingerprint_regular(bundle.root / "manifest.json", "source_changed") != bundle.manifest:
            raise MergeError("source_changed")
        for name, expected in bundle.artifacts.items():
            if _fingerprint_regular(bundle.root / ARTIFACT_PATHS[name], "source_changed") != expected:
                raise MergeError("source_changed")
        if _export_tree_sha256(bundle.root, "source_changed") != tree_sha256:
            raise MergeError("source_changed")
    for name, path in repair_selection.selection_paths.items():
        if (
            _fingerprint_regular(path, "source_changed", required_mode=0o600)
            != repair_selection.selection_artifacts[name]
        ):
            raise MergeError("source_changed")
    if (
        _fingerprint_regular(
            repair_attestation_path,
            "source_changed",
            required_mode=0o600,
        )
        != repair_attestation_artifact
    ):
        raise MergeError("source_changed")
    bundled_sidecars = {
        **repair_selection.selection_artifacts,
        REPAIR_ATTESTATION_COPY_FILENAME: repair_attestation_artifact,
    }
    for name, expected in bundled_sidecars.items():
        if _fingerprint_regular(repair_root / name, "source_changed", required_mode=0o600) != expected:
            raise MergeError("source_changed")


def merge_qwen_sft(
    options: MergeOptions,
    *,
    code_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate, merge, and atomically publish two SFT exports."""
    output_parent, output = _resolve_output(options.output_dir)
    if os.path.lexists(output):
        raise MergeError("destination_exists")
    bindings = {
        "original_manifest": options.original_export_manifest_sha256,
        "original_tree": options.original_export_tree_sha256,
        "repair_manifest": options.repair_export_manifest_sha256,
        "repair_tree": options.repair_export_tree_sha256,
    }
    if any(not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None for value in bindings.values()):
        raise MergeError("export_binding_invalid")

    original = _load_export(options.original_export_dir, "original")
    repair = _load_export(options.repair_export_dir, "repair")
    if original.manifest.sha256 != options.original_export_manifest_sha256:
        raise MergeError("original_manifest_binding_mismatch")
    if repair.manifest.sha256 != options.repair_export_manifest_sha256:
        raise MergeError("repair_manifest_binding_mismatch")
    if original.root == repair.root:
        raise MergeError("input_exports_overlap")
    if (
        output == original.root
        or output.is_relative_to(original.root)
        or output == repair.root
        or output.is_relative_to(repair.root)
    ):
        raise MergeError("output_overlaps_input")
    if original.split != repair.split:
        raise MergeError("split_contract_mismatch")
    if original.target_rendering_contract_body != repair.target_rendering_contract_body:
        raise MergeError("target_rendering_contract_mismatch")
    if (original.taskset_id, original.dataset_revision) != (
        repair.taskset_id,
        repair.dataset_revision,
    ):
        raise MergeError("task_namespace_mismatch")
    if original.tasks & repair.tasks:
        raise MergeError("source_task_overlap")
    merged_train_tasks = original.train_tasks | repair.train_tasks
    merged_validation_tasks = original.validation_tasks | repair.validation_tasks
    if merged_train_tasks & merged_validation_tasks:
        raise MergeError("merged_task_split_overlap")

    try:
        selection_path = options.repair_selection_manifest.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise MergeError("repair_selection_invalid") from error
    selection = _load_repair_selection(
        selection_path,
        options.repair_selection_manifest_sha256,
    )
    if (
        selection.source_task_count != original.approved_tasks
        or selection.source_routing_epoch != original.routing_epoch
        or any(original.source_artifacts.get(name) != artifact for name, artifact in selection.source_artifacts.items())
    ):
        raise MergeError("repair_selection_original_mismatch")
    expected_exclusion_artifacts = {
        "task_file": selection.selection_artifacts[REPAIR_SELECTION_TASK_COPY_FILENAME],
        "missing_or_errored_task_file": selection.selection_artifacts[REPAIR_SELECTION_MISSING_ERROR_COPY_FILENAME],
        "strict_invalid_pass_task_file": selection.selection_artifacts[
            REPAIR_SELECTION_STRICT_INVALID_PASS_COPY_FILENAME
        ],
    }
    if (
        original.exclusion is None
        or original.exclusion.manifest != selection.artifact
        or original.exclusion.artifacts != expected_exclusion_artifacts
        or original.exclusion.approved_task_count != selection.source_task_count
        or original.exclusion.missing_or_errored_count != selection.missing_or_errored_count
        or original.exclusion.strict_invalid_pass_count != selection.strict_invalid_pass_count
        or original.exclusion.union_count != selection.task_count
    ):
        raise MergeError("original_exclusion_selection_mismatch")
    union_task_ids = frozenset(
        _task_identity_sha256(original.taskset_id, original.dataset_revision, slug) for slug in selection.union_slugs
    )
    strict_invalid_pass_task_ids = frozenset(
        _task_identity_sha256(original.taskset_id, original.dataset_revision, slug)
        for slug in selection.strict_invalid_pass_slugs
    )
    if original.tasks & union_task_ids:
        raise MergeError("original_excluded_task_retained")
    if not strict_invalid_pass_task_ids.issubset(repair.tasks):
        raise MergeError("strict_invalid_pass_not_replaced")
    if not repair.tasks.issubset(union_task_ids):
        raise MergeError("repair_task_not_selected")
    attestation_path = options.repair_attestation_manifest
    if not attestation_path.is_absolute():
        attestation_path = Path.cwd() / attestation_path
    attestation_path = Path(os.path.normpath(attestation_path))
    attestation = _load_repair_attestation(
        attestation_path,
        options.repair_attestation_manifest_sha256,
        selection.artifact.sha256,
    )
    bundled_selection = {
        name: _fingerprint_regular(
            repair.root / name,
            "repair_selection_copy_invalid",
            required_mode=0o600,
        )
        for name in selection.selection_artifacts
    }
    bundled_attestation = _fingerprint_regular(
        repair.root / REPAIR_ATTESTATION_COPY_FILENAME,
        "repair_attestation_copy_invalid",
        required_mode=0o600,
    )
    if bundled_selection != selection.selection_artifacts:
        raise MergeError("repair_selection_copy_mismatch")
    if bundled_attestation != attestation.artifact:
        raise MergeError("repair_attestation_copy_mismatch")
    repair_config_artifact = repair.source_artifacts.get("inputs/source_config.toml")
    if (
        selection.task_count != repair.input_traces
        or selection.task_file_sha256 != repair.source_artifacts["inputs/task_file.txt"].sha256
        or repair_config_artifact is None
        or repair_config_artifact.sha256 != selection.repair_config_sha256
        or attestation.task_count != repair.input_traces
        or attestation.task_file_sha256 != selection.task_file_sha256
        or attestation.missing_or_errored_count != selection.missing_or_errored_count
        or attestation.strict_invalid_pass_count != selection.strict_invalid_pass_count
        or attestation.repair_union_indices_sha256 != selection.repair_union_indices_sha256
        or (attestation.taskset_id, attestation.dataset_revision) != (repair.taskset_id, repair.dataset_revision)
        or any(repair.source_artifacts.get(name) != artifact for name, artifact in attestation.source_artifacts.items())
    ):
        raise MergeError("repair_attestation_export_mismatch")
    if code_provenance is None:
        code = _validate_code_provenance(_repository_provenance(options.project_dir, options.expected_project_revision))
    else:
        code = _validate_code_provenance(code_provenance)
    if GIT_SHA_PATTERN.fullmatch(options.expected_project_revision) is None:
        raise MergeError("project_revision_invalid")
    if code["repository_revision"] != options.expected_project_revision:
        raise MergeError("project_revision_mismatch")
    if original.exporter_sha256 != code["exporter_sha256"] or repair.exporter_sha256 != code["exporter_sha256"]:
        raise MergeError("exporter_code_mismatch")
    if (
        selection.materializer_sha256 != code["materializer_sha256"]
        or selection.exporter_sha256 != code["exporter_sha256"]
        or selection.repository_revision != code["repository_revision"]
        or selection.submodules != code["submodules"]
        or attestation.repository_revision != code["repository_revision"]
        or attestation.submodules != code["submodules"]
    ):
        raise MergeError("repair_code_provenance_mismatch")
    if _export_tree_sha256(original.root, "original_export_snapshot_invalid") != options.original_export_tree_sha256:
        raise MergeError("original_export_snapshot_mismatch")
    if _export_tree_sha256(repair.root, "repair_export_snapshot_invalid") != options.repair_export_tree_sha256:
        raise MergeError("repair_export_snapshot_mismatch")

    staging: Path | None = Path(tempfile.mkdtemp(prefix=f".{output.name}.merge-", dir=output_parent))
    train_sink: ArtifactSink | None = None
    validation_sink: ArtifactSink | None = None
    try:
        assert staging is not None
        train_sink = ArtifactSink(staging / "train" / "train.jsonl")
        validation_sink = ArtifactSink(staging / "validation" / "train.jsonl")
        original_train = _copy_split(original, "train", original.train_tasks, train_sink)
        repair_train = _copy_split(repair, "train", repair.train_tasks, train_sink)
        original_validation = _copy_split(
            original,
            "validation",
            original.validation_tasks,
            validation_sink,
        )
        repair_validation = _copy_split(
            repair,
            "validation",
            repair.validation_tasks,
            validation_sink,
        )
        train_artifact = train_sink.close()
        train_sink = None
        validation_artifact = validation_sink.close()
        validation_sink = None
        original_stats = BundleStats(train=original_train, validation=original_validation)
        repair_stats = BundleStats(train=repair_train, validation=repair_validation)
        _validate_declared_counts(original, original_stats)
        _validate_declared_counts(repair, repair_stats)
        output_stats = BundleStats(
            train=SplitStats(
                rows=original_train.rows + repair_train.rows,
                tasks=len(merged_train_tasks),
                artifact=train_artifact,
            ),
            validation=SplitStats(
                rows=original_validation.rows + repair_validation.rows,
                tasks=len(merged_validation_tasks),
                artifact=validation_artifact,
            ),
        )

        task_split = {
            "format_version": FORMAT_VERSION,
            "split_salt": original.split.split_salt,
            "train_task_sha256": sorted(merged_train_tasks),
            "validation_permyriad": original.split.validation_permyriad,
            "validation_task_sha256": sorted(merged_validation_tasks),
        }
        task_split_artifact = _write_exclusive(staging / "task-split.json", _json_bytes(task_split))
        target_rendering_contract_artifact = _write_exclusive(
            staging / TARGET_RENDERING_CONTRACT_FILENAME,
            original.target_rendering_contract_body,
        )
        if target_rendering_contract_artifact != original.artifacts[TARGET_RENDERING_CONTRACT_FILENAME]:
            raise MergeError("target_rendering_contract_copy_mismatch")
        output_artifacts = {
            "task-split.json": task_split_artifact,
            TARGET_RENDERING_CONTRACT_FILENAME: target_rendering_contract_artifact,
            "train/train.jsonl": train_artifact,
            "validation/train.jsonl": validation_artifact,
        }
        merge_manifest = {
            "artifacts": {name: output_artifacts[name].as_dict() for name in sorted(output_artifacts)},
            "code": code,
            "counts": {
                "emitted_rows": output_stats.rows,
                "input_traces": output_stats.tasks,
                "selected_fail_traces": 0,
                "selected_pass_traces": output_stats.tasks,
                "selected_traces": output_stats.tasks,
                "train_rows": output_stats.train.rows,
                "train_traces": output_stats.train.tasks,
                "validation_rows": output_stats.validation.rows,
                "validation_traces": output_stats.validation.tasks,
            },
            "exporter": {
                "file_sha256": code["merger_sha256"],
                "format_version": FORMAT_VERSION,
            },
            "format": FORMAT_CONTRACT,
            "input_counts": {
                "original": _counts(original_stats),
                "repair": _counts(repair_stats),
            },
            "inputs": {
                "original": _bundle_manifest_binding(original, options.original_export_tree_sha256),
                "repair": _bundle_manifest_binding(repair, options.repair_export_tree_sha256),
                "repair_attestation_manifest": attestation.artifact.as_dict(),
                "repair_bundle_sidecars": {
                    REPAIR_ATTESTATION_COPY_FILENAME: bundled_attestation.as_dict(),
                    **{name: artifact.as_dict() for name, artifact in sorted(bundled_selection.items())},
                },
                "repair_selection_manifest": selection.artifact.as_dict(),
            },
            "kind": MERGE_KIND,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
            "schema_version": MERGE_SCHEMA_VERSION,
            "selection": "pass-only",
            "split": original.split.as_dict(),
            "target_rendering": TARGET_RENDERING_CONTRACT,
        }
        manifest_artifact = _write_exclusive(staging / "manifest.json", _json_bytes(merge_manifest))

        _validate_sources_unchanged(
            (original, repair),
            (options.original_export_tree_sha256, options.repair_export_tree_sha256),
            selection,
            attestation_path,
            attestation.artifact,
            repair.root,
        )
        if code_provenance is None:
            if (
                _validate_code_provenance(
                    _repository_provenance(options.project_dir, options.expected_project_revision)
                )
                != code
            ):
                raise MergeError("code_provenance_changed")
        _fsync_tree(staging)
        _publish_noreplace(staging, output)
        staging = None
    finally:
        if train_sink is not None:
            train_sink.abort()
        if validation_sink is not None:
            validation_sink.abort()
        if staging is not None and staging.exists():
            shutil.rmtree(staging)

    return {
        "manifest_sha256": manifest_artifact.sha256,
        "ok": True,
        "output_sha256": {
            "task_split": task_split_artifact.sha256,
            "target_rendering_contract": target_rendering_contract_artifact.sha256,
            "train": train_artifact.sha256,
            "validation": validation_artifact.sha256,
        },
        "rows": {
            "total": output_stats.rows,
            "train": output_stats.train.rows,
            "validation": output_stats.validation.rows,
        },
        "tasks": {
            "total": output_stats.tasks,
            "train": output_stats.train.tasks,
            "validation": output_stats.validation.tasks,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = StableArgumentParser(description=__doc__)
    parser.add_argument("--original-export-dir", type=Path, required=True)
    parser.add_argument("--original-export-manifest-sha256", required=True)
    parser.add_argument("--original-export-tree-sha256", required=True)
    parser.add_argument("--repair-export-dir", type=Path, required=True)
    parser.add_argument("--repair-export-manifest-sha256", required=True)
    parser.add_argument("--repair-export-tree-sha256", required=True)
    parser.add_argument("--repair-selection-manifest", type=Path, required=True)
    parser.add_argument("--repair-selection-manifest-sha256", required=True)
    parser.add_argument("--repair-attestation-manifest", type=Path, required=True)
    parser.add_argument("--repair-attestation-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--expected-project-revision", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        summary = merge_qwen_sft(
            MergeOptions(
                original_export_dir=args.original_export_dir,
                original_export_manifest_sha256=args.original_export_manifest_sha256,
                original_export_tree_sha256=args.original_export_tree_sha256,
                repair_export_dir=args.repair_export_dir,
                repair_export_manifest_sha256=args.repair_export_manifest_sha256,
                repair_export_tree_sha256=args.repair_export_tree_sha256,
                repair_selection_manifest=args.repair_selection_manifest,
                repair_selection_manifest_sha256=args.repair_selection_manifest_sha256,
                repair_attestation_manifest=args.repair_attestation_manifest,
                repair_attestation_manifest_sha256=args.repair_attestation_manifest_sha256,
                output_dir=args.output_dir,
                project_dir=args.project_dir,
                expected_project_revision=args.expected_project_revision,
            )
        )
    except MergeError as error:
        print(json.dumps({"code": error.code, "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "internal_error", "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
