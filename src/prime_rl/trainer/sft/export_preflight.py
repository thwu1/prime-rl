"""Fail-closed rendering preflight for attested format-v3 SFT exports."""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import math
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import renderers
from renderers import Nemotron3RendererConfig, create_renderer
from renderers.base import Renderer, build_training_sample
from transformers import AutoTokenizer
from transformers.tokenization_utils import PreTrainedTokenizer

from prime_rl.configs.sft import LossMaskConfig, SFTConfig, SFTDataConfig
from prime_rl.trainer.sft.data import (
    _canonicalize_attested_messages,
    _canonicalize_attested_tools,
    _message_is_trainable,
)
from prime_rl.utils.chat_template import deserialize_tool_calls, normalize_messages, strip_message_content

ATTESTATION_KIND = "prime-rl-sft-render-preflight"
ATTESTATION_SCHEMA_VERSION = 2
EXPORT_FORMAT_VERSION = 3
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_JSONL_ROW_BYTES = 128 * 1024 * 1024
SHA256_HEX = frozenset("0123456789abcdef")
GIT_SHA_LENGTH = 40
TARGET_RENDERING_CONTRACT_FILENAME = "target-rendering-contract.json"
TARGET_RENDERING_CONTRACT_SHA256 = "305d66d12152b6de0f045a4fff3bd53adaaac173bcf8bbdc766efe4ceab3e981"
TOKENIZER_TREE_ALGORITHM = "sha256-path-mode-size-content-v1"
EXPECTED_TARGET_RENDERING_CONTRACT: dict[str, Any] = {
    "dataset_format_version": EXPORT_FORMAT_VERSION,
    "kind": "terminal-bench-sft-target-rendering",
    "loss_mask": {"assistant": True, "system": False, "tool": False, "user": False},
    "max_sequence_tokens": 262_144,
    "pack_function": "fixed_stack",
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
    "schema_version": 2,
    "tokenizer": {
        "repository": "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16",
        "revision": "d51eab0d1f979ebc26b546e634a04f450d99158e",
        "trust_remote_code": False,
    },
}
SOURCE_VALIDATION_KEYS = frozenset(
    {
        "max_sequence_tokens",
        "model_io_contract",
        "require_exact_provider_json",
        "require_model_io",
        "require_reasoning",
        "require_request_graph_match",
    }
)
SUPPORTED_MODEL_IO_CONTRACTS = frozenset(
    {
        "qwen3-a95b",
        "qwen3-a95b-epoch3",
        "qwen3-a95b-epoch3-source+qwen3-a95b-repair",
    }
)
REQUIRED_EXPORT_ARTIFACTS = {
    "task-split.json",
    TARGET_RENDERING_CONTRACT_FILENAME,
    "train/train.jsonl",
    "validation/train.jsonl",
}
CODE_PATHS = (
    "packages/prime-rl-configs/src/prime_rl/configs/sft.py",
    "packages/prime-rl-configs/src/prime_rl/configs/trainer.py",
    "src/prime_rl/trainer/model.py",
    "src/prime_rl/trainer/sft/data.py",
    "src/prime_rl/trainer/sft/export_preflight.py",
    "src/prime_rl/trainer/sft/train.py",
)
ROW_FIELDS = frozenset(
    {
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
)


class SFTPreflightError(RuntimeError):
    """A preflight failure represented only by a non-sensitive stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FileArtifact:
    bytes: int
    sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {"bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class TokenizerTree:
    algorithm: str
    file_count: int
    total_bytes: int
    sha256: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "algorithm": self.algorithm,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class TokenizerSnapshotBinding:
    path: Path
    repository: str
    revision: str
    tree: TokenizerTree

    def as_dict(self) -> dict[str, Any]:
        return {
            "local_files_only": True,
            "path": str(self.path),
            "repository": self.repository,
            "revision": self.revision,
            "tree": self.tree.as_dict(),
            "trust_remote_code": False,
        }


@dataclass(frozen=True)
class ExportBinding:
    root: Path
    manifest: FileArtifact
    artifacts: Mapping[str, FileArtifact]
    manifest_value: Mapping[str, Any]
    source_validation: Mapping[str, Any]
    target_rendering: Mapping[str, Any]


@dataclass(frozen=True)
class RenderingSummary:
    rows: int
    rendered_tokens: int
    max_rendered_tokens: int
    trainable_tokens: int
    reasoning_fields: int
    nonempty_reasoning_fields: int
    reasoning_fields_rendered: int

    def as_dict(self) -> dict[str, int]:
        return {
            "max_rendered_tokens": self.max_rendered_tokens,
            "nonempty_reasoning_fields": self.nonempty_reasoning_fields,
            "reasoning_fields": self.reasoning_fields,
            "reasoning_fields_rendered": self.reasoning_fields_rendered,
            "rendered_tokens": self.rendered_tokens,
            "rows": self.rows,
            "trainable_tokens": self.trainable_tokens,
        }


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in SHA256_HEX for character in value)


def _valid_git_sha(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == GIT_SHA_LENGTH and all(character in SHA256_HEX for character in value)
    )


def _contains_json_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_contains_json_null(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_json_null(item) for item in value)
    return False


def _contains_nonfinite_number(value: object) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_contains_nonfinite_number(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_nonfinite_number(item) for item in value)
    return False


def _same_file(before: os.stat_result, after: os.stat_result) -> bool:
    return (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def _open_regular(path: Path, code: str, *, required_mode: int | None = None):
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SFTPreflightError(code) from error
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or (
        required_mode is not None and stat.S_IMODE(metadata.st_mode) != required_mode
    ):
        os.close(descriptor)
        raise SFTPreflightError(code)
    return os.fdopen(descriptor, "rb"), metadata


def _read_regular(
    path: Path,
    code: str,
    *,
    max_bytes: int | None = None,
    required_mode: int | None = None,
) -> tuple[bytes, FileArtifact]:
    source, before = _open_regular(path, code, required_mode=required_mode)
    try:
        body = source.read() if max_bytes is None else source.read(max_bytes + 1)
        after = os.fstat(source.fileno())
    finally:
        source.close()
    if not _same_file(before, after) or (max_bytes is not None and len(body) > max_bytes):
        raise SFTPreflightError(code)
    return body, FileArtifact(len(body), hashlib.sha256(body).hexdigest())


def _fingerprint_regular(path: Path, code: str, *, required_mode: int | None = None) -> FileArtifact:
    source, before = _open_regular(path, code, required_mode=required_mode)
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := source.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(source.fileno())
    finally:
        source.close()
    if not _same_file(before, after):
        raise SFTPreflightError(code)
    return FileArtifact(size, digest.hexdigest())


def _parse_json_object(body: bytes, code: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise SFTPreflightError(code) from error
    if not isinstance(value, dict):
        raise SFTPreflightError(code)
    return value


def _artifact(value: object, code: str) -> FileArtifact:
    if not isinstance(value, dict) or set(value) != {"bytes", "sha256"}:
        raise SFTPreflightError(code)
    size = value.get("bytes")
    digest = value.get("sha256")
    if not _is_plain_int(size) or size < 0 or not _valid_sha256(digest):
        raise SFTPreflightError(code)
    return FileArtifact(size, digest)


def _canonical_directory(path: Path, code: str) -> Path:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise SFTPreflightError(code)
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise SFTPreflightError(code) from error
    if not stat.S_ISDIR(metadata.st_mode) or resolved != path:
        raise SFTPreflightError(code)
    return resolved


def _same_snapshot_entry(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_uid,
        before.st_gid,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_uid,
        after.st_gid,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _update_tokenizer_tree_digest(
    digest: Any,
    *,
    kind: bytes,
    relative_path: bytes,
    mode: int,
    size: int,
    content_sha256: bytes = b"",
) -> None:
    digest.update(kind)
    digest.update(len(relative_path).to_bytes(8, "big"))
    digest.update(relative_path)
    digest.update(mode.to_bytes(4, "big"))
    digest.update(size.to_bytes(8, "big"))
    digest.update(content_sha256)


def _snapshot_directory_entries(descriptor: int, code: str) -> list[bytes]:
    try:
        with os.scandir(descriptor) as entries:
            names = [os.fsencode(entry.name) for entry in entries]
    except OSError as error:
        raise SFTPreflightError(code) from error
    if len(names) != len(set(names)):
        raise SFTPreflightError(code)
    return sorted(names)


def _fingerprint_tokenizer_snapshot(path: Path, code: str = "tokenizer_snapshot_invalid") -> TokenizerTree:
    root = _canonical_directory(path, code)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        root_descriptor = os.open(root, flags)
    except OSError as error:
        raise SFTPreflightError(code) from error

    digest = hashlib.sha256(b"prime-rl-tokenizer-tree\0v1\0")
    file_count = 0
    total_bytes = 0
    expected_owner = os.geteuid()

    def scan_directory(descriptor: int, relative_path: bytes) -> None:
        nonlocal file_count, total_bytes
        before = os.fstat(descriptor)
        if not stat.S_ISDIR(before.st_mode) or before.st_uid != expected_owner or stat.S_IMODE(before.st_mode) != 0o500:
            raise SFTPreflightError(code)
        _update_tokenizer_tree_digest(
            digest,
            kind=b"D",
            relative_path=relative_path,
            mode=stat.S_IMODE(before.st_mode),
            size=0,
        )
        names = _snapshot_directory_entries(descriptor, code)
        for name_bytes in names:
            name = os.fsdecode(name_bytes)
            child_relative = name_bytes if not relative_path else relative_path + b"/" + name_bytes
            try:
                metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except OSError as error:
                raise SFTPreflightError(code) from error
            if metadata.st_uid != expected_owner:
                raise SFTPreflightError(code)
            if stat.S_ISDIR(metadata.st_mode):
                try:
                    child_descriptor = os.open(name, flags, dir_fd=descriptor)
                except OSError as error:
                    raise SFTPreflightError(code) from error
                try:
                    if not _same_snapshot_entry(metadata, os.fstat(child_descriptor)):
                        raise SFTPreflightError(code)
                    scan_directory(child_descriptor, child_relative)
                finally:
                    os.close(child_descriptor)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o400:
                raise SFTPreflightError(code)
            file_flags = os.O_RDONLY | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                file_flags |= os.O_NOFOLLOW
            try:
                file_descriptor = os.open(name, file_flags, dir_fd=descriptor)
            except OSError as error:
                raise SFTPreflightError(code) from error
            content_digest = hashlib.sha256()
            size = 0
            try:
                opened = os.fstat(file_descriptor)
                if (
                    not _same_snapshot_entry(metadata, opened)
                    or not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or stat.S_IMODE(opened.st_mode) != 0o400
                ):
                    raise SFTPreflightError(code)
                while chunk := os.read(file_descriptor, 1 << 20):
                    content_digest.update(chunk)
                    size += len(chunk)
                after = os.fstat(file_descriptor)
            except OSError as error:
                raise SFTPreflightError(code) from error
            finally:
                os.close(file_descriptor)
            if not _same_snapshot_entry(opened, after) or size != opened.st_size:
                raise SFTPreflightError(code)
            _update_tokenizer_tree_digest(
                digest,
                kind=b"F",
                relative_path=child_relative,
                mode=stat.S_IMODE(opened.st_mode),
                size=size,
                content_sha256=content_digest.digest(),
            )
            file_count += 1
            total_bytes += size
        if _snapshot_directory_entries(descriptor, code) != names or not _same_snapshot_entry(
            before, os.fstat(descriptor)
        ):
            raise SFTPreflightError(code)

    try:
        root_before = os.fstat(root_descriptor)
        scan_directory(root_descriptor, b"")
        root_after = os.fstat(root_descriptor)
    finally:
        os.close(root_descriptor)
    try:
        path_after = root.lstat()
        resolved_after = root.resolve(strict=True)
    except OSError as error:
        raise SFTPreflightError(code) from error
    if (
        file_count < 1
        or not _same_snapshot_entry(root_before, root_after)
        or not _same_snapshot_entry(root_before, path_after)
        or resolved_after != root
    ):
        raise SFTPreflightError(code)
    return TokenizerTree(
        algorithm=TOKENIZER_TREE_ALGORITHM,
        file_count=file_count,
        total_bytes=total_bytes,
        sha256=digest.hexdigest(),
    )


def _parse_tokenizer_snapshot(value: object, code: str) -> TokenizerSnapshotBinding:
    tokenizer_contract = EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]
    if not isinstance(value, dict) or set(value) != {
        "local_files_only",
        "path",
        "repository",
        "revision",
        "tree",
        "trust_remote_code",
    }:
        raise SFTPreflightError(code)
    path_value = value.get("path")
    tree_value = value.get("tree")
    if (
        not isinstance(path_value, str)
        or not path_value
        or not Path(path_value).is_absolute()
        or Path(path_value) != Path(os.path.normpath(path_value))
        or value.get("repository") != tokenizer_contract["repository"]
        or value.get("revision") != tokenizer_contract["revision"]
        or value.get("local_files_only") is not True
        or value.get("trust_remote_code") is not False
        or not isinstance(tree_value, dict)
        or set(tree_value) != {"algorithm", "file_count", "sha256", "total_bytes"}
        or tree_value.get("algorithm") != TOKENIZER_TREE_ALGORITHM
        or not _is_plain_int(tree_value.get("file_count"))
        or tree_value["file_count"] < 1
        or not _is_plain_int(tree_value.get("total_bytes"))
        or tree_value["total_bytes"] < 0
        or not _valid_sha256(tree_value.get("sha256"))
    ):
        raise SFTPreflightError(code)
    return TokenizerSnapshotBinding(
        path=Path(path_value),
        repository=tokenizer_contract["repository"],
        revision=tokenizer_contract["revision"],
        tree=TokenizerTree(
            algorithm=tree_value["algorithm"],
            file_count=tree_value["file_count"],
            total_bytes=tree_value["total_bytes"],
            sha256=tree_value["sha256"],
        ),
    )


def _bind_tokenizer_snapshot(
    path: Path | None,
    expected_sha256: str | None,
) -> TokenizerSnapshotBinding | None:
    if (path is None) != (expected_sha256 is None):
        raise SFTPreflightError("tokenizer_snapshot_binding_invalid")
    if path is None:
        return None
    if not _valid_sha256(expected_sha256):
        raise SFTPreflightError("tokenizer_snapshot_digest_invalid")
    canonical_path = _canonical_directory(path, "tokenizer_snapshot_invalid")
    tree = _fingerprint_tokenizer_snapshot(canonical_path)
    if tree.sha256 != expected_sha256:
        raise SFTPreflightError("tokenizer_snapshot_digest_mismatch")
    tokenizer_contract = EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]
    return TokenizerSnapshotBinding(
        path=canonical_path,
        repository=tokenizer_contract["repository"],
        revision=tokenizer_contract["revision"],
        tree=tree,
    )


def _assert_tokenizer_snapshot(snapshot: TokenizerSnapshotBinding) -> None:
    if _fingerprint_tokenizer_snapshot(snapshot.path) != snapshot.tree:
        raise SFTPreflightError("tokenizer_snapshot_changed")


def _source_validation_policy(value: object, code: str) -> dict[str, int | bool | str]:
    if (
        not isinstance(value, dict)
        or set(value) != SOURCE_VALIDATION_KEYS
        or value.get("require_reasoning") is not True
        or value.get("require_model_io") is not True
        or value.get("require_request_graph_match") is not True
        or value.get("model_io_contract") not in SUPPORTED_MODEL_IO_CONTRACTS
        or not isinstance(value.get("require_exact_provider_json"), bool)
        or not _is_plain_int(value.get("max_sequence_tokens"))
        or value["max_sequence_tokens"] != EXPECTED_TARGET_RENDERING_CONTRACT["max_sequence_tokens"]
    ):
        raise SFTPreflightError(code)
    return {key: value[key] for key in sorted(SOURCE_VALIDATION_KEYS)}


def _load_export_binding(export_root: Path, expected_manifest_sha256: str) -> ExportBinding:
    if not _valid_sha256(expected_manifest_sha256):
        raise SFTPreflightError("export_manifest_digest_invalid")
    root = _canonical_directory(export_root, "export_root_invalid")
    manifest_body, manifest_artifact = _read_regular(
        root / "manifest.json",
        "export_manifest_invalid",
        max_bytes=MAX_METADATA_BYTES,
        required_mode=0o600,
    )
    if manifest_artifact.sha256 != expected_manifest_sha256:
        raise SFTPreflightError("export_manifest_digest_mismatch")
    manifest = _parse_json_object(manifest_body, "export_manifest_invalid")
    exporter = manifest.get("exporter")
    artifacts_value = manifest.get("artifacts")
    target_rendering = manifest.get("target_rendering")
    max_tokens = manifest.get("max_sequence_tokens")
    source_validation = _source_validation_policy(
        manifest.get("source_validation"),
        "export_source_validation_invalid",
    )
    if (
        not isinstance(exporter, dict)
        or set(exporter) != {"file_sha256", "format_version"}
        or not _is_plain_int(exporter.get("format_version"))
        or exporter.get("format_version") != EXPORT_FORMAT_VERSION
        or not _valid_sha256(exporter.get("file_sha256"))
        or target_rendering != EXPECTED_TARGET_RENDERING_CONTRACT
        or not _is_plain_int(max_tokens)
        or max_tokens != EXPECTED_TARGET_RENDERING_CONTRACT["max_sequence_tokens"]
        or not isinstance(artifacts_value, dict)
        or not REQUIRED_EXPORT_ARTIFACTS.issubset(artifacts_value)
        or set(artifacts_value) - REQUIRED_EXPORT_ARTIFACTS not in (set(), {"qwen_router_epochs.jsonl"})
    ):
        raise SFTPreflightError("export_manifest_contract_invalid")
    artifacts = {name: _artifact(value, "export_manifest_contract_invalid") for name, value in artifacts_value.items()}
    for name, expected in artifacts.items():
        path = root / name
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise SFTPreflightError("export_artifact_invalid") from error
        if not resolved.is_relative_to(root) or resolved != path:
            raise SFTPreflightError("export_artifact_invalid")
        if _fingerprint_regular(path, "export_artifact_invalid", required_mode=0o600) != expected:
            raise SFTPreflightError("export_artifact_digest_mismatch")
    contract_body, contract_artifact = _read_regular(
        root / TARGET_RENDERING_CONTRACT_FILENAME,
        "target_rendering_contract_invalid",
        max_bytes=MAX_METADATA_BYTES,
        required_mode=0o600,
    )
    if (
        contract_artifact.sha256 != TARGET_RENDERING_CONTRACT_SHA256
        or _parse_json_object(contract_body, "target_rendering_contract_invalid") != EXPECTED_TARGET_RENDERING_CONTRACT
    ):
        raise SFTPreflightError("target_rendering_contract_invalid")
    return ExportBinding(root, manifest_artifact, artifacts, manifest, source_validation, target_rendering)


def _validate_tool_call(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"function", "id", "type"} or value.get("type") != "function":
        raise SFTPreflightError("row_tool_contract_invalid")
    function = value.get("function")
    if (
        not isinstance(value.get("id"), str)
        or not value["id"]
        or not isinstance(function, dict)
        or set(function) != {"arguments", "name"}
        or not isinstance(function.get("name"), str)
        or not function["name"]
        or not isinstance(function.get("arguments"), str)
    ):
        raise SFTPreflightError("row_tool_contract_invalid")
    arguments = _parse_json_object(function["arguments"].encode(), "row_tool_arguments_invalid")
    if _contains_json_null(arguments) or _contains_nonfinite_number(arguments):
        raise SFTPreflightError("row_tool_arguments_invalid")


def _validate_tools(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise SFTPreflightError("row_tool_contract_invalid")
    for tool in value:
        function = tool.get("function") if isinstance(tool, dict) else None
        if (
            not isinstance(tool, dict)
            or set(tool) != {"type", "function"}
            or tool.get("type") != "function"
            or not isinstance(function, dict)
            or not {"description", "name", "parameters"}.issubset(function)
            or not set(function).issubset({"description", "name", "parameters", "strict"})
            or not isinstance(function.get("name"), str)
            or not function["name"]
            or not isinstance(function.get("description"), str)
            or not isinstance(function.get("parameters"), dict)
            or _contains_json_null(function["parameters"])
            or ("strict" in function and not isinstance(function["strict"], bool))
        ):
            raise SFTPreflightError("row_tool_contract_invalid")
    return _canonicalize_attested_tools(value)


def _validate_messages(value: object, target_index: int) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list) or not value or target_index != len(value) - 1:
        raise SFTPreflightError("row_target_invalid")
    messages: list[dict[str, Any]] = []
    targets: list[int] = []
    reasoning_fields = 0
    for index, message in enumerate(value):
        if not isinstance(message, dict) or not isinstance(message.get("trainable"), bool):
            raise SFTPreflightError("row_message_contract_invalid")
        role = message.get("role")
        content = message.get("content")
        if role not in {"assistant", "system", "tool", "user"} or not isinstance(content, str):
            raise SFTPreflightError("row_message_contract_invalid")
        if message["trainable"]:
            targets.append(index)
        if role == "assistant":
            if "finish_reason" not in message or not set(message).issubset(
                {"content", "finish_reason", "reasoning_content", "role", "tool_calls", "trainable"}
            ):
                raise SFTPreflightError("row_message_contract_invalid")
            if "reasoning_content" in message:
                reasoning_fields += 1
                if not isinstance(message["reasoning_content"], str):
                    raise SFTPreflightError("row_reasoning_contract_invalid")
            finish_reason = message.get("finish_reason")
            if finish_reason == "length":
                raise SFTPreflightError("row_finish_reason_length")
            if finish_reason is not None and finish_reason not in {"stop", "tool_calls"}:
                raise SFTPreflightError("row_finish_reason_contract_invalid")
            calls = message.get("tool_calls")
            if calls is not None:
                if not isinstance(calls, list) or not calls:
                    raise SFTPreflightError("row_tool_contract_invalid")
                for call in calls:
                    _validate_tool_call(call)
        elif role == "tool":
            if not set(message).issubset({"content", "name", "role", "tool_call_id", "trainable"}):
                raise SFTPreflightError("row_message_contract_invalid")
            if not isinstance(message.get("tool_call_id"), str) or not message["tool_call_id"]:
                raise SFTPreflightError("row_tool_contract_invalid")
            if "name" in message and (not isinstance(message["name"], str) or not message["name"]):
                raise SFTPreflightError("row_tool_contract_invalid")
        elif set(message) != {"content", "role", "trainable"}:
            raise SFTPreflightError("row_message_contract_invalid")
        messages.append(copy.deepcopy(message))
    if targets != [target_index] or messages[target_index].get("role") != "assistant":
        raise SFTPreflightError("row_target_invalid")
    return messages, reasoning_fields


def _prepare_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = normalize_messages(_canonicalize_attested_messages(messages), default_role="assistant")
    normalized = deserialize_tool_calls(normalized)
    return strip_message_content(normalized)


def _validate_and_render_row(
    row: Mapping[str, Any],
    tokenizer: PreTrainedTokenizer,
    renderer: Renderer,
    max_sequence_tokens: int,
) -> RenderingSummary:
    if set(row) not in {ROW_FIELDS, ROW_FIELDS | {"routing_epoch"}}:
        raise SFTPreflightError("row_contract_invalid")
    integer_fields = (
        "source_node_index",
        "source_split_row_index",
        "source_trace_index",
        "source_trajectory_assistant_turn_count",
        "target_assistant_turn_index",
    )
    reward = row.get("reward")
    if (
        any(not _is_plain_int(row.get(field)) or row[field] < 0 for field in integer_fields)
        or row.get("source_trajectory_assistant_turn_count", 0) < 1
        or row.get("target_assistant_turn_index", 0) >= row.get("source_trajectory_assistant_turn_count", 0)
        or not _valid_sha256(row.get("source_episode_id"))
        or not _valid_sha256(row.get("task_id"))
        or isinstance(reward, bool)
        or not isinstance(reward, (int, float))
        or not math.isfinite(reward)
        or row.get("is_correct") is not (reward > 0)
        or (
            "routing_epoch" in row
            and (not _is_plain_int(row["routing_epoch"]) or row["routing_epoch"] not in {1, 2, 3})
        )
    ):
        raise SFTPreflightError("row_source_contract_invalid")
    target_index = row.get("target_assistant_message_index")
    if not _is_plain_int(target_index) or target_index < 0 or row.get("assistant_target_count") != 1:
        raise SFTPreflightError("row_target_invalid")
    messages, reasoning_fields = _validate_messages(row.get("messages"), target_index)
    if row.get("history_reasoning_policy") != "preserve_all_assistant_reasoning":
        raise SFTPreflightError("row_reasoning_contract_invalid")
    target = messages[target_index]
    target_finish_reason = row.get("target_finish_reason")
    if target_finish_reason not in {"stop", "tool_calls"} or target_finish_reason != target.get("finish_reason"):
        raise SFTPreflightError("row_finish_reason_contract_invalid")
    if row.get("target_has_reasoning") != bool(str(target.get("reasoning_content") or "").strip()):
        raise SFTPreflightError("row_reasoning_contract_invalid")
    fidelity = row.get("transcript_fidelity")
    fidelity_fields = {
        "retained_assistant_reasoning_fields",
        "retained_sampled_finish_reasons",
        "source_assistant_reasoning_fields",
        "source_sampled_finish_reasons",
    }
    finish_reason_fields = sum(
        isinstance(message.get("finish_reason"), str) for message in messages if message.get("role") == "assistant"
    )
    if (
        not isinstance(fidelity, dict)
        or set(fidelity) != fidelity_fields
        or any(not _is_plain_int(fidelity.get(field)) or fidelity[field] < 0 for field in fidelity_fields)
        or fidelity["source_assistant_reasoning_fields"] != fidelity["retained_assistant_reasoning_fields"]
        or fidelity["source_sampled_finish_reasons"] != fidelity["retained_sampled_finish_reasons"]
        or fidelity["retained_assistant_reasoning_fields"] != reasoning_fields
        or fidelity["retained_sampled_finish_reasons"] != finish_reason_fields
    ):
        raise SFTPreflightError("row_transcript_fidelity_invalid")
    tools = _validate_tools(row.get("tools"))
    prepared = _prepare_messages(messages)
    rendered = renderer.render(prepared, tools=tools)
    if (
        len(rendered.token_ids) != len(rendered.message_indices)
        or len(rendered.token_ids) != len(rendered.sampled_mask)
        or not rendered.token_ids
        or len(rendered.token_ids) > max_sequence_tokens
    ):
        raise SFTPreflightError("row_render_contract_invalid")
    token_ids, loss_mask = build_training_sample(
        renderer,
        prepared,
        role_to_mask=lambda message: _message_is_trainable(message, LossMaskConfig()),
        tools=tools,
    )
    attributed_target_mask = [
        message_index == target_index and sampled
        for message_index, sampled in zip(rendered.message_indices, rendered.sampled_mask, strict=True)
    ]
    target_sampled_indices = [index for index, selected in enumerate(attributed_target_mask) if selected]
    if (
        not target_sampled_indices
        or token_ids != rendered.token_ids
        or loss_mask != attributed_target_mask
        or not any(loss_mask[1:])
    ):
        raise SFTPreflightError("row_loss_mask_invalid")
    last_target_sampled = target_sampled_indices[-1]
    if (
        tokenizer.eos_token_id is None
        or token_ids[last_target_sampled] != tokenizer.eos_token_id
        or any(rendered.sampled_mask[last_target_sampled + 1 :])
    ):
        raise SFTPreflightError("row_eos_contract_invalid")
    rendered_reasoning = 0
    nonempty_reasoning = 0
    for index, message in enumerate(prepared):
        reasoning = message.get("reasoning_content")
        if not isinstance(reasoning, str) or not reasoning.strip():
            continue
        nonempty_reasoning += 1
        without_reasoning = copy.deepcopy(prepared)
        del without_reasoning[index]["reasoning_content"]
        without_ids, without_mask = build_training_sample(
            renderer,
            without_reasoning,
            role_to_mask=lambda item: _message_is_trainable(item, LossMaskConfig()),
            tools=tools,
        )
        if without_ids == rendered.token_ids:
            raise SFTPreflightError("row_reasoning_not_rendered")
        if message["trainable"] and [
            token for token, selected in zip(without_ids, without_mask, strict=True) if selected
        ] == [token for token, selected in zip(token_ids, loss_mask, strict=True) if selected]:
            raise SFTPreflightError("row_reasoning_not_trainable")
        rendered_reasoning += 1
    return RenderingSummary(
        rows=1,
        rendered_tokens=len(rendered.token_ids),
        max_rendered_tokens=len(rendered.token_ids),
        trainable_tokens=sum(loss_mask[1:]),
        reasoning_fields=reasoning_fields,
        nonempty_reasoning_fields=nonempty_reasoning,
        reasoning_fields_rendered=rendered_reasoning,
    )


def _scan_split(
    path: Path,
    expected: FileArtifact,
    tokenizer: PreTrainedTokenizer,
    renderer: Renderer,
    max_sequence_tokens: int,
) -> RenderingSummary:
    source, before = _open_regular(path, "export_split_invalid", required_mode=0o600)
    digest = hashlib.sha256()
    size = 0
    summary = RenderingSummary(0, 0, 0, 0, 0, 0, 0)
    try:
        while raw_line := source.readline(MAX_JSONL_ROW_BYTES + 1):
            if len(raw_line) > MAX_JSONL_ROW_BYTES or not raw_line.endswith(b"\n") or not raw_line.strip():
                raise SFTPreflightError("export_split_invalid")
            digest.update(raw_line)
            size += len(raw_line)
            row = _parse_json_object(raw_line, "export_row_invalid")
            try:
                row_summary = _validate_and_render_row(row, tokenizer, renderer, max_sequence_tokens)
            except SFTPreflightError:
                raise
            except Exception:
                raise SFTPreflightError("row_render_failed") from None
            summary = RenderingSummary(
                rows=summary.rows + 1,
                rendered_tokens=summary.rendered_tokens + row_summary.rendered_tokens,
                max_rendered_tokens=max(summary.max_rendered_tokens, row_summary.max_rendered_tokens),
                trainable_tokens=summary.trainable_tokens + row_summary.trainable_tokens,
                reasoning_fields=summary.reasoning_fields + row_summary.reasoning_fields,
                nonempty_reasoning_fields=summary.nonempty_reasoning_fields + row_summary.nonempty_reasoning_fields,
                reasoning_fields_rendered=summary.reasoning_fields_rendered + row_summary.reasoning_fields_rendered,
            )
        after = os.fstat(source.fileno())
    finally:
        source.close()
    if not _same_file(before, after) or FileArtifact(size, digest.hexdigest()) != expected:
        raise SFTPreflightError("export_split_digest_mismatch")
    return summary


def _load_render_tokenizer(snapshot: TokenizerSnapshotBinding | None) -> PreTrainedTokenizer:
    tokenizer_contract = EXPECTED_TARGET_RENDERING_CONTRACT["tokenizer"]
    if snapshot is not None:
        _assert_tokenizer_snapshot(snapshot)
        tokenizer = AutoTokenizer.from_pretrained(
            str(snapshot.path),
            local_files_only=True,
            trust_remote_code=False,
        )
        _assert_tokenizer_snapshot(snapshot)
        return tokenizer
    return AutoTokenizer.from_pretrained(
        tokenizer_contract["repository"],
        revision=tokenizer_contract["revision"],
        trust_remote_code=tokenizer_contract["trust_remote_code"],
    )


def _render_export(
    binding: ExportBinding,
    tokenizer_snapshot: TokenizerSnapshotBinding | None = None,
) -> dict[str, Any]:
    tokenizer = _load_render_tokenizer(tokenizer_snapshot)
    renderer_contract = EXPECTED_TARGET_RENDERING_CONTRACT["renderer"]
    renderer_config = Nemotron3RendererConfig.model_validate(renderer_contract["config"])
    renderer = create_renderer(tokenizer, renderer_config)
    max_tokens = EXPECTED_TARGET_RENDERING_CONTRACT["max_sequence_tokens"]
    summaries = {
        split: _scan_split(
            binding.root / split / "train.jsonl",
            binding.artifacts[f"{split}/train.jsonl"],
            tokenizer,
            renderer,
            max_tokens,
        )
        for split in ("train", "validation")
    }
    total = RenderingSummary(
        rows=sum(summary.rows for summary in summaries.values()),
        rendered_tokens=sum(summary.rendered_tokens for summary in summaries.values()),
        max_rendered_tokens=max(summary.max_rendered_tokens for summary in summaries.values()),
        trainable_tokens=sum(summary.trainable_tokens for summary in summaries.values()),
        reasoning_fields=sum(summary.reasoning_fields for summary in summaries.values()),
        nonempty_reasoning_fields=sum(summary.nonempty_reasoning_fields for summary in summaries.values()),
        reasoning_fields_rendered=sum(summary.reasoning_fields_rendered for summary in summaries.values()),
    )
    if tokenizer_snapshot is not None:
        _assert_tokenizer_snapshot(tokenizer_snapshot)
    return {**total.as_dict(), "splits": {name: summary.as_dict() for name, summary in summaries.items()}}


def _validate_rendering_counts(binding: ExportBinding, rendering: Mapping[str, Any]) -> None:
    counts = binding.manifest_value.get("counts")
    splits = rendering.get("splits")
    if (
        not isinstance(counts, dict)
        or not isinstance(splits, dict)
        or not isinstance(splits.get("train"), dict)
        or not isinstance(splits.get("validation"), dict)
        or counts.get("emitted_rows") != rendering.get("rows")
        or counts.get("train_rows") != splits["train"].get("rows")
        or counts.get("validation_rows") != splits["validation"].get("rows")
    ):
        raise SFTPreflightError("export_row_count_mismatch")


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
        raise SFTPreflightError(code) from error
    if completed.stderr:
        raise SFTPreflightError(code)
    return completed.stdout


def _dependency_versions() -> dict[str, str]:
    return {
        "datasets": importlib.metadata.version("datasets"),
        "renderers": importlib.metadata.version("renderers"),
        "tokenizers": importlib.metadata.version("tokenizers"),
        "transformers": importlib.metadata.version("transformers"),
    }


def _repository_provenance(project: Path, expected_revision: str) -> dict[str, Any]:
    root = _canonical_directory(project, "project_path_invalid")
    if Path(__file__).resolve(strict=True).parents[4] != root:
        raise SFTPreflightError("project_runtime_origin_mismatch")
    if not _valid_git_sha(expected_revision):
        raise SFTPreflightError("project_revision_invalid")
    if _run_git(root, ["rev-parse", "--show-toplevel"], "project_revision_invalid").strip() != str(root):
        raise SFTPreflightError("project_revision_invalid")
    if _run_git(root, ["rev-parse", "HEAD"], "project_revision_invalid").strip() != expected_revision:
        raise SFTPreflightError("project_revision_mismatch")
    if _run_git(root, ["status", "--porcelain=v1", "--untracked-files=all"], "project_status_invalid"):
        raise SFTPreflightError("project_not_clean")
    renderer_revision = EXPECTED_TARGET_RENDERING_CONTRACT["renderer"]["repository_revision"]
    record = _run_git(root, ["ls-tree", expected_revision, "--", "deps/renderers"], "renderer_revision_invalid")
    fields = record.strip().split(maxsplit=3)
    renderer_root = root / "deps" / "renderers"
    expected_renderer_module = renderer_root / "renderers" / "__init__.py"
    if (
        len(fields) != 4
        or fields[:2] != ["160000", "commit"]
        or fields[2] != renderer_revision
        or fields[3] != "deps/renderers"
        or _run_git(renderer_root, ["rev-parse", "HEAD"], "renderer_revision_invalid").strip() != renderer_revision
        or _run_git(renderer_root, ["status", "--porcelain=v1", "--untracked-files=all"], "renderer_revision_invalid")
        or Path(renderers.__file__).resolve(strict=True) != expected_renderer_module
    ):
        raise SFTPreflightError("renderer_revision_invalid")
    source = {
        relative: _fingerprint_regular(root / relative, "project_source_invalid").as_dict() for relative in CODE_PATHS
    }
    return {
        "dependencies": _dependency_versions(),
        "project_revision": expected_revision,
        "renderer_repository_revision": renderer_revision,
        "source": source,
    }


def _write_attestation(
    path: Path,
    value: Mapping[str, Any],
    *,
    before_publish: Callable[[], None] | None = None,
) -> FileArtifact:
    body = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode() + b"\n"
    descriptor = -1
    directory_descriptor = -1
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        output = os.fdopen(descriptor, "wb")
        with output:
            descriptor = -1
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        if before_publish is not None:
            before_publish()
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        temporary = None
        os.fsync(directory_descriptor)
    except OSError as error:
        raise SFTPreflightError("attestation_write_failed") from error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if directory_descriptor >= 0:
            try:
                os.close(directory_descriptor)
            except OSError:
                pass
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return FileArtifact(len(body), hashlib.sha256(body).hexdigest())


def create_sft_preflight_attestation(
    *,
    export_root: Path,
    expected_manifest_sha256: str,
    project_dir: Path,
    expected_project_revision: str,
    expected_require_exact_provider_json: bool,
    output: Path,
    tokenizer_snapshot_path: Path | None = None,
    expected_tokenizer_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    """Render every exported row and write an aggregate-only immutable attestation."""
    if not output.is_absolute() or output != Path(os.path.normpath(output)) or os.path.lexists(output):
        raise SFTPreflightError("attestation_path_invalid")
    _canonical_directory(output.parent, "attestation_path_invalid")
    if not isinstance(expected_require_exact_provider_json, bool):
        raise SFTPreflightError("source_validation_expectation_invalid")
    tokenizer_snapshot = _bind_tokenizer_snapshot(
        tokenizer_snapshot_path,
        expected_tokenizer_snapshot_sha256,
    )
    binding = _load_export_binding(export_root, expected_manifest_sha256)
    if binding.source_validation["require_exact_provider_json"] is not expected_require_exact_provider_json:
        raise SFTPreflightError("source_validation_expectation_mismatch")
    code = _repository_provenance(project_dir, expected_project_revision)
    rendering = _render_export(binding, tokenizer_snapshot)
    if rendering["rows"] < 1 or rendering["trainable_tokens"] < 1:
        raise SFTPreflightError("export_has_no_trainable_rows")
    _validate_rendering_counts(binding, rendering)
    if _repository_provenance(project_dir, expected_project_revision) != code:
        raise SFTPreflightError("project_changed_during_preflight")
    rebound = _load_export_binding(binding.root, binding.manifest.sha256)
    if (
        rebound.manifest != binding.manifest
        or rebound.artifacts != binding.artifacts
        or rebound.source_validation != binding.source_validation
    ):
        raise SFTPreflightError("export_changed_during_preflight")
    value = {
        "code": code,
        "expected_require_exact_provider_json": expected_require_exact_provider_json,
        "export": {
            "artifacts": {name: artifact.as_dict() for name, artifact in sorted(binding.artifacts.items())},
            "manifest": binding.manifest.as_dict(),
            "root": str(binding.root),
        },
        "kind": ATTESTATION_KIND,
        "rendering": rendering,
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "source_validation": binding.source_validation,
        "target_rendering": EXPECTED_TARGET_RENDERING_CONTRACT,
    }
    if tokenizer_snapshot is not None:
        value["tokenizer_snapshot"] = tokenizer_snapshot.as_dict()
    _validate_attestation_value(value)
    artifact = _write_attestation(
        output,
        value,
        before_publish=(lambda: _assert_tokenizer_snapshot(tokenizer_snapshot))
        if tokenizer_snapshot is not None
        else None,
    )
    return {
        "attestation_sha256": artifact.sha256,
        "require_exact_provider_json": expected_require_exact_provider_json,
        "rendering": {key: item for key, item in rendering.items() if key != "splits"},
        "status": "attested",
    }


def _format_v3_root(data: SFTDataConfig) -> Path | None:
    candidate = Path(data.name)
    if candidate.name not in {"train", "validation"}:
        return None
    try:
        candidate = candidate.resolve(strict=True)
    except OSError:
        return None
    root = candidate.parent
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return None
    body, _artifact_value = _read_regular(manifest_path, "export_manifest_invalid", max_bytes=MAX_METADATA_BYTES)
    manifest = _parse_json_object(body, "export_manifest_invalid")
    exporter = manifest.get("exporter")
    if (
        isinstance(exporter, dict)
        and _is_plain_int(exporter.get("format_version"))
        and exporter.get("format_version") == EXPORT_FORMAT_VERSION
    ):
        return root
    return None


def _validate_attestation_value(value: Mapping[str, Any]) -> TokenizerSnapshotBinding | None:
    required_keys = {
        "code",
        "expected_require_exact_provider_json",
        "export",
        "kind",
        "rendering",
        "schema_version",
        "source_validation",
        "target_rendering",
    }
    if set(value) not in {frozenset(required_keys), frozenset(required_keys | {"tokenizer_snapshot"})}:
        raise SFTPreflightError("attestation_contract_invalid")
    if (
        value.get("kind") != ATTESTATION_KIND
        or value.get("schema_version") != ATTESTATION_SCHEMA_VERSION
        or value.get("target_rendering") != EXPECTED_TARGET_RENDERING_CONTRACT
    ):
        raise SFTPreflightError("attestation_contract_invalid")
    code = value.get("code")
    export = value.get("export")
    rendering = value.get("rendering")
    tokenizer_snapshot = (
        _parse_tokenizer_snapshot(value["tokenizer_snapshot"], "attestation_contract_invalid")
        if "tokenizer_snapshot" in value
        else None
    )
    source_validation = _source_validation_policy(value.get("source_validation"), "attestation_contract_invalid")
    if (
        not isinstance(value.get("expected_require_exact_provider_json"), bool)
        or value["expected_require_exact_provider_json"] is not source_validation["require_exact_provider_json"]
        or not isinstance(code, dict)
        or set(code) != {"dependencies", "project_revision", "renderer_repository_revision", "source"}
        or not _valid_git_sha(code.get("project_revision"))
        or code.get("renderer_repository_revision")
        != EXPECTED_TARGET_RENDERING_CONTRACT["renderer"]["repository_revision"]
        or not isinstance(code.get("dependencies"), dict)
        or set(code["dependencies"]) != {"datasets", "renderers", "tokenizers", "transformers"}
        or any(not isinstance(version, str) or not version for version in code["dependencies"].values())
        or not isinstance(code.get("source"), dict)
        or set(code["source"]) != set(CODE_PATHS)
        or any(_artifact(record, "attestation_contract_invalid").bytes < 1 for record in code["source"].values())
        or not isinstance(export, dict)
        or set(export) != {"artifacts", "manifest", "root"}
        or not isinstance(export.get("root"), str)
        or not isinstance(export.get("artifacts"), dict)
        or not REQUIRED_EXPORT_ARTIFACTS.issubset(export["artifacts"])
        or not isinstance(rendering, dict)
        or set(rendering)
        != {
            "max_rendered_tokens",
            "nonempty_reasoning_fields",
            "reasoning_fields",
            "reasoning_fields_rendered",
            "rendered_tokens",
            "rows",
            "splits",
            "trainable_tokens",
        }
        or any(
            not _is_plain_int(rendering.get(field)) or rendering[field] < 0
            for field in (
                "max_rendered_tokens",
                "nonempty_reasoning_fields",
                "reasoning_fields",
                "reasoning_fields_rendered",
                "rendered_tokens",
                "rows",
                "trainable_tokens",
            )
        )
        or rendering.get("nonempty_reasoning_fields") > rendering.get("reasoning_fields")
        or rendering.get("reasoning_fields_rendered") != rendering.get("nonempty_reasoning_fields")
        or rendering.get("rows", 0) < 1
        or rendering.get("trainable_tokens", 0) < 1
    ):
        raise SFTPreflightError("attestation_contract_invalid")
    _artifact(export["manifest"], "attestation_contract_invalid")
    for record in export["artifacts"].values():
        _artifact(record, "attestation_contract_invalid")
    splits = rendering["splits"]
    if not isinstance(splits, dict) or set(splits) != {"train", "validation"}:
        raise SFTPreflightError("attestation_contract_invalid")
    for split in splits.values():
        if not isinstance(split, dict) or set(split) != set(RenderingSummary.__dataclass_fields__):
            raise SFTPreflightError("attestation_contract_invalid")
        if any(not _is_plain_int(item) or item < 0 for item in split.values()):
            raise SFTPreflightError("attestation_contract_invalid")
        if (
            split["nonempty_reasoning_fields"] > split["reasoning_fields"]
            or split["reasoning_fields_rendered"] != split["nonempty_reasoning_fields"]
        ):
            raise SFTPreflightError("attestation_contract_invalid")
    if (
        rendering["max_rendered_tokens"] != max(split["max_rendered_tokens"] for split in splits.values())
        or rendering["max_rendered_tokens"] > EXPECTED_TARGET_RENDERING_CONTRACT["max_sequence_tokens"]
        or any(
            rendering[field] != sum(split[field] for split in splits.values())
            for field in (
                "reasoning_fields",
                "nonempty_reasoning_fields",
                "reasoning_fields_rendered",
                "rendered_tokens",
                "rows",
                "trainable_tokens",
            )
        )
    ):
        raise SFTPreflightError("attestation_contract_invalid")
    return tokenizer_snapshot


def _validate_config_binding(
    config: SFTConfig, data_configs: list[SFTDataConfig], attestation: Mapping[str, Any]
) -> None:
    contract = EXPECTED_TARGET_RENDERING_CONTRACT
    tokenizer = contract["tokenizer"]
    renderer = contract["renderer"]
    if (
        config.tokenizer.name != tokenizer["repository"]
        or config.tokenizer.revision != tokenizer["revision"]
        or config.tokenizer.trust_remote_code is not tokenizer["trust_remote_code"]
        or config.tokenizer.chat_template is not None
        or config.renderer is None
        or config.renderer.model_dump(mode="json") != renderer["config"]
    ):
        raise SFTPreflightError("training_rendering_contract_mismatch")
    export_root = Path(attestation["export"]["root"])
    max_rendered = attestation["rendering"]["max_rendered_tokens"]
    for data in data_configs:
        path = Path(data.name)
        if (
            not path.is_absolute()
            or path not in {export_root / "train", export_root / "validation"}
            or any(value is not None for value in (data.subsets, data.splits, data.probabilities))
            or data.loss_mask.model_dump(mode="json") != contract["loss_mask"]
            or data.pack_function != contract["pack_function"]
            or data.seq_len < max_rendered
            or data.seq_len > contract["max_sequence_tokens"]
        ):
            raise SFTPreflightError("training_data_contract_mismatch")


def load_attested_sft_tokenizer(config: SFTConfig) -> PreTrainedTokenizer | None:
    """Load a schema-v2 bound snapshot locally, or return None for a legacy attestation."""
    data_configs = [config.data] if isinstance(config.data, SFTDataConfig) else []
    if config.val is not None:
        data_configs.append(config.val.data)
    bindings = {(data.preflight_attestation, data.preflight_attestation_sha256) for data in data_configs}
    if len(bindings) != 1:
        raise SFTPreflightError("training_attestation_binding_mismatch")
    attestation_path, expected_sha256 = next(iter(bindings))
    if attestation_path is None or expected_sha256 is None:
        raise SFTPreflightError("training_attestation_binding_mismatch")
    body, artifact = _read_regular(
        attestation_path,
        "attestation_invalid",
        max_bytes=MAX_METADATA_BYTES,
        required_mode=0o600,
    )
    if artifact.sha256 != expected_sha256:
        raise SFTPreflightError("attestation_digest_mismatch")
    attestation = _parse_json_object(body, "attestation_invalid")
    tokenizer_snapshot = _validate_attestation_value(attestation)
    if tokenizer_snapshot is None:
        return None
    _validate_config_binding(config, data_configs, attestation)
    tokenizer = _load_render_tokenizer(tokenizer_snapshot)
    tokenizer.pad_token_id = tokenizer.eos_token_id
    _assert_tokenizer_snapshot(tokenizer_snapshot)
    return tokenizer


def validate_sft_training_preflight(config: SFTConfig) -> bool:
    """Recheck a pinned preflight and every bound artifact at trainer startup."""
    data_configs = [config.data] if isinstance(config.data, SFTDataConfig) else []
    if config.val is not None:
        data_configs.append(config.val.data)
    if not data_configs:
        return False
    bindings = {(data.preflight_attestation, data.preflight_attestation_sha256) for data in data_configs}
    format_v3_roots = {_format_v3_root(data) for data in data_configs}
    format_v3_roots.discard(None)
    if any(path is None or digest is None for path, digest in bindings):
        if format_v3_roots:
            raise SFTPreflightError("format_v3_preflight_required")
        if len(bindings) != 1 or bindings != {(None, None)}:
            raise SFTPreflightError("training_attestation_binding_mismatch")
        return False
    if len(bindings) != 1:
        raise SFTPreflightError("training_attestation_binding_mismatch")
    attestation_path, expected_sha256 = next(iter(bindings))
    assert attestation_path is not None and expected_sha256 is not None
    body, artifact = _read_regular(
        attestation_path,
        "attestation_invalid",
        max_bytes=MAX_METADATA_BYTES,
        required_mode=0o600,
    )
    if artifact.sha256 != expected_sha256:
        raise SFTPreflightError("attestation_digest_mismatch")
    attestation = _parse_json_object(body, "attestation_invalid")
    tokenizer_snapshot = _validate_attestation_value(attestation)
    export = attestation["export"]
    binding = _load_export_binding(Path(export["root"]), export["manifest"]["sha256"])
    if (
        binding.manifest.as_dict() != export["manifest"]
        or {name: item.as_dict() for name, item in binding.artifacts.items()} != export["artifacts"]
        or binding.source_validation != attestation["source_validation"]
        or binding.source_validation["require_exact_provider_json"]
        is not attestation["expected_require_exact_provider_json"]
    ):
        raise SFTPreflightError("attested_export_changed")
    project = Path(__file__).resolve().parents[4]
    observed_code = _repository_provenance(project, attestation["code"]["project_revision"])
    if observed_code != attestation["code"]:
        raise SFTPreflightError("attested_code_changed")
    _validate_config_binding(config, data_configs, attestation)
    if format_v3_roots and format_v3_roots != {binding.root}:
        raise SFTPreflightError("training_data_contract_mismatch")
    observed_rendering = _render_export(binding, tokenizer_snapshot)
    if observed_rendering != attestation["rendering"]:
        raise SFTPreflightError("attested_rendering_mismatch")
    _validate_rendering_counts(binding, observed_rendering)
    rebound = _load_export_binding(binding.root, binding.manifest.sha256)
    if (
        rebound.manifest != binding.manifest
        or rebound.artifacts != binding.artifacts
        or rebound.source_validation != binding.source_validation
    ):
        raise SFTPreflightError("attested_export_changed")
    if _repository_provenance(project, attestation["code"]["project_revision"]) != observed_code:
        raise SFTPreflightError("attested_code_changed")
    if tokenizer_snapshot is not None:
        _assert_tokenizer_snapshot(tokenizer_snapshot)
    return True
