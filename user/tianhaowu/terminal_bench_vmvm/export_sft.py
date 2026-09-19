#!/usr/bin/env python3
"""Export audited Verifiers v1 evaluation traces as a deterministic SFT dataset.

The exporter is intentionally non-interactive and redacted: stdout/stderr contain only
aggregate counts and stable error codes. Task identifiers, prompts, messages, tool payloads,
raw trace rows, and captured provider bodies are never logged.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import direct_qwen_workers as direct_workers
from audit_traces import (
    DEFAULT_MAX_SEQUENCE_TOKENS,
    TRAINABLE_FINISH_REASONS,
    _audit_trace,
    _valid_redundant_provider_specific_fields,
    _valid_tool_arguments,
)

FORMAT_VERSION = 3
SPLIT_BUCKETS = 10_000
DEFAULT_VALIDATION_PERMYRIAD = 500
DEFAULT_SPLIT_SALT = "terminal-bench-vmvm-sft-v1"
ROUTING_EPOCH_INDEX_KIND = "qwen-routing-epoch-index"
ROUTING_TRANSITION_KIND = "qwen-direct-router-policy-transition"
ROUTING_EPOCH_INDEX_FILENAME = "qwen_router_epochs.jsonl"
ROUTING_TRANSITION_FILENAME = "qwen_router_transition.json"
ROUTING_ADMISSION_TRANSITION_FILENAME = "qwen_router_admission_transition.json"
ROUTING_EPOCH1_ROWS_FILENAME = "qwen_router_epoch1_rows.sha256"
ROUTING_EPOCH2_LINEAGE_FILENAME = "qwen_router_epoch2_lineage.jsonl"
DIRECT_WORKERS_FILENAME = "direct_workers.json"
REPAIR_SELECTION_KIND = "qwen-aggregate-repair-selection"
REPAIR_SELECTION_SCHEMA_VERSION = 2
REPAIR_SELECTION_MANIFEST_FILENAME = "repair_manifest.json"
REPAIR_SELECTION_TASK_FILENAME = "repair_tasks.txt"
REPAIR_MISSING_ERROR_TASK_FILENAME = "repair_missing_or_errored_tasks.txt"
REPAIR_STRICT_INVALID_PASS_TASK_FILENAME = "repair_strict_invalid_pass_tasks.txt"
MAX_ROUTING_EPOCH_INDEX_BYTES = 16 * 1024 * 1024
MAX_ROUTING_TRANSITION_BYTES = 2 * 1024 * 1024
MAX_REPAIR_SELECTION_BYTES = 16 * 1024 * 1024
MAX_TARGET_RENDERING_CONTRACT_BYTES = 64 * 1024
SHA256_HEX_CHARS = frozenset("0123456789abcdef")
FORBIDDEN_REQUEST_FIELDS = frozenset({"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"})
REQUIRED_RUN_ARTIFACTS = (
    "config.toml",
    "provenance.txt",
    "inputs/manifest.json",
    "inputs/source_config.toml",
    "inputs/task_file.txt",
)
IMAGE_MANIFEST_ARTIFACT = "inputs/image_manifest.json"
REQUIRED_RUNTIME_SUBMODULES = (
    "deps/pydantic-config",
    "deps/renderers",
    "deps/verifiers",
)
TARGET_RENDERING_CONTRACT_FILENAME = "target-rendering-contract.json"
TARGET_RENDERING_CONTRACT_PATH = (
    Path(__file__).resolve().parent / "configs" / "sft" / TARGET_RENDERING_CONTRACT_FILENAME
)
TARGET_RENDERING_CONTRACT_SHA256 = "305d66d12152b6de0f045a4fff3bd53adaaac173bcf8bbdc766efe4ceab3e981"
TARGET_RENDERING_CONTRACT = {
    "dataset_format_version": 3,
    "kind": "terminal-bench-sft-target-rendering",
    "loss_mask": {"assistant": True, "system": False, "tool": False, "user": False},
    "max_sequence_tokens": DEFAULT_MAX_SEQUENCE_TOKENS,
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

Selection = Literal["pass-only", "all-outcomes"]


class ExportError(RuntimeError):
    """A fail-closed export error represented by a non-sensitive stable code."""

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
class ExportOptions:
    results: Path
    output_dir: Path
    selection: Selection
    expected_count: int | None = None
    validation_permyriad: int = DEFAULT_VALIDATION_PERMYRIAD
    split_salt: str = DEFAULT_SPLIT_SALT
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE_TOKENS
    routing_epoch_index: Path | None = None
    exclusion_selection_manifest: Path | None = None
    exclusion_selection_manifest_sha256: str | None = None
    require_task_index_binding: bool = False
    require_exact_provider_json: bool = False


@dataclass(frozen=True)
class RoutingEpochIndex:
    artifact: FileArtifact
    body: bytes
    admission_transition_artifact: FileArtifact | None
    direct_workers_artifact: FileArtifact
    epoch1_rows_artifact: FileArtifact
    epoch2_lineage_artifact: FileArtifact | None
    transition_artifact: FileArtifact
    current_epoch: int
    results_sha256: str
    transition_sha256: str
    row_sha256: tuple[str, ...]
    routing_epochs: tuple[int, ...]


@dataclass(frozen=True)
class TaskIdentityContext:
    taskset_id: str
    dataset_revision: str
    approved_slugs: frozenset[str]
    approved_slug_order: tuple[str, ...]


@dataclass(frozen=True)
class TargetRenderingContract:
    artifact: FileArtifact
    body: bytes
    value: Mapping[str, Any]


@dataclass(frozen=True)
class ExclusionSelection:
    manifest_path: Path
    manifest_artifact: FileArtifact
    artifact_paths: Mapping[str, Path]
    artifacts: Mapping[str, FileArtifact]
    approved_task_count: int
    missing_or_errored_slugs: frozenset[str]
    strict_invalid_pass_slugs: frozenset[str]
    union_slugs: frozenset[str]
    source_artifacts: Mapping[str, FileArtifact]

    @property
    def count(self) -> int:
        return len(self.union_slugs)


class JSONLSink:
    """Exclusive JSONL writer that hashes the exact bytes it persists."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        self._file = os.fdopen(os.open(path, flags, 0o600), "wb")
        self._digest = hashlib.sha256()
        self.rows = 0
        self.bytes = 0

    def write(self, row: dict[str, Any]) -> None:
        try:
            encoded = (
                json.dumps(
                    row,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
        except (TypeError, ValueError) as error:
            raise ExportError("output_row_not_strict_json") from error
        self._file.write(encoded)
        self._digest.update(encoded)
        self.rows += 1
        self.bytes += len(encoded)

    def close(self) -> FileArtifact:
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        return FileArtifact(bytes=self.bytes, sha256=self._digest.hexdigest())


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ExportError("input_not_strict_json") from error


def _json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _contains_json_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_contains_json_null(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_json_null(item) for item in value)
    return False


def _open_regular(path: Path):
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ExportError("source_artifact_open_failed") from error
    descriptor = os.fstat(fd)
    if not stat.S_ISREG(descriptor.st_mode):
        os.close(fd)
        raise ExportError("source_artifact_not_regular")
    return os.fdopen(fd, "rb"), descriptor


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


def _read_stable_file(
    path: Path,
    *,
    max_bytes: int | None = None,
    required_mode: int | None = None,
) -> tuple[bytes, FileArtifact]:
    source, before = _open_regular(path)
    if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
        source.close()
        raise ExportError("source_artifact_mode_invalid")
    try:
        body = source.read() if max_bytes is None else source.read(max_bytes + 1)
        after = os.fstat(source.fileno())
    finally:
        source.close()
    if not _same_file(before, after):
        raise ExportError("source_artifact_changed")
    if max_bytes is not None and len(body) > max_bytes:
        raise ExportError("source_artifact_too_large")
    return body, FileArtifact(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


def _fingerprint_stable_file(path: Path, *, required_mode: int | None = None) -> FileArtifact:
    source, before = _open_regular(path)
    if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
        source.close()
        raise ExportError("source_artifact_mode_invalid")
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
        raise ExportError("source_artifact_changed")
    return FileArtifact(bytes=size, sha256=digest.hexdigest())


@contextmanager
def _hold_source_locks(run_dir: Path, *, require_router_lock: bool) -> Iterator[None]:
    """Hold direct-router then evaluator locks so no cutover can begin during export."""
    descriptors: list[int] = []
    try:
        for filename in (".direct_router.lock", ".writer.lock"):
            path = run_dir / filename
            if not os.path.lexists(path):
                if require_router_lock:
                    raise ExportError("source_lock_missing")
                continue
            flags = os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags)
            except OSError as error:
                raise ExportError("source_lock_open_failed") from error
            descriptors.append(descriptor)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ExportError("source_lock_not_regular")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ExportError("source_run_is_active") from error
            after = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (
                after.st_dev,
                after.st_ino,
            ):
                raise ExportError("source_lock_replaced")
        yield
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _parse_json_object(body: bytes, code: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError()),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise ExportError(code) from error
    if not isinstance(value, dict):
        raise ExportError(code)
    return value


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in SHA256_HEX_CHARS for character in value)


def _valid_git_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(character in SHA256_HEX_CHARS for character in value)


def _task_identity_context(
    taskset: Mapping[str, Any],
    task_file_body: bytes,
    *,
    expected_task_count: int,
) -> TaskIdentityContext:
    taskset_id = taskset.get("id")
    dataset_revision = taskset.get("dataset_revision")
    if (
        not isinstance(taskset_id, str)
        or not taskset_id
        or "\x00" in taskset_id
        or not _valid_git_sha(dataset_revision)
    ):
        raise ExportError("resolved_config_task_identity_invalid")
    try:
        task_file_text = task_file_body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ExportError("approved_task_list_invalid") from error
    approved_slugs: set[str] = set()
    for line in task_file_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        slug = stripped.split("\t", 1)[0]
        if not slug or "\x00" in slug:
            raise ExportError("approved_task_list_invalid")
        if slug in approved_slugs:
            raise ExportError("approved_task_list_duplicates")
        approved_slugs.add(slug)
    if not approved_slugs:
        raise ExportError("approved_task_list_invalid")
    if len(approved_slugs) != expected_task_count:
        raise ExportError("approved_task_list_count_mismatch")
    return TaskIdentityContext(
        taskset_id=taskset_id,
        dataset_revision=dataset_revision,
        approved_slugs=frozenset(approved_slugs),
        approved_slug_order=tuple(sorted(approved_slugs)),
    )


def _opaque_task_slug(
    task: Mapping[str, Any],
    *,
    evaluator_order: tuple[str, ...] | None = None,
) -> str:
    slug = task.get("slug")
    derived: str | None = None
    if evaluator_order is not None and "name" not in task:
        raise ExportError("trace_task_name_invalid")
    if "name" in task:
        name = task["name"]
        if not isinstance(name, str) or not name or "\x00" in name:
            raise ExportError("trace_task_name_invalid")
        derived = name.rsplit("/", 1)[-1]
        if not derived or derived in {".", ".."}:
            raise ExportError("trace_task_name_invalid")
    if slug is None:
        slug = derived
    elif derived is not None and slug != derived:
        raise ExportError("trace_task_identity_mismatch")
    if not isinstance(slug, str) or not slug or "\x00" in slug or "/" in slug or slug in {".", ".."}:
        raise ExportError("trace_task_slug_invalid")
    if evaluator_order is not None:
        index = task.get("idx")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(evaluator_order)
            or evaluator_order[index] != slug
        ):
            raise ExportError("trace_task_identity_mismatch")
    return slug


def _task_identity_sha256(context: TaskIdentityContext, task: Mapping[str, Any]) -> str:
    slug = _opaque_task_slug(task)
    if slug not in context.approved_slugs:
        raise ExportError("trace_task_slug_not_approved")
    try:
        identity = "\x00".join((context.taskset_id, context.dataset_revision, slug)).encode("utf-8")
    except UnicodeEncodeError as error:
        raise ExportError("trace_task_slug_invalid") from error
    return hashlib.sha256(identity).hexdigest()


def _selection_artifact(value: object) -> FileArtifact:
    if not isinstance(value, dict) or set(value) != {"sha256", "size_bytes"}:
        raise ExportError("exclusion_selection_invalid")
    size = value.get("size_bytes")
    digest = value.get("sha256")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0 or not _valid_sha256(digest):
        raise ExportError("exclusion_selection_invalid")
    return FileArtifact(bytes=size, sha256=digest)


def _selection_task_slugs(body: bytes, *, allow_empty: bool) -> tuple[str, ...]:
    if body and not body.endswith(b"\n"):
        raise ExportError("exclusion_selection_invalid")
    try:
        lines = body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ExportError("exclusion_selection_invalid") from error
    if any(not line or line.strip() != line or "\t" in line or "\x00" in line for line in lines):
        raise ExportError("exclusion_selection_invalid")
    if len(lines) != len(set(lines)) or (not allow_empty and not lines):
        raise ExportError("exclusion_selection_invalid")
    return tuple(lines)


def _selection_indices_sha256(slugs: frozenset[str], approved_slugs: frozenset[str]) -> str:
    ordered = sorted(approved_slugs)
    body = "".join(f"{index}\n" for index, slug in enumerate(ordered) if slug in slugs).encode()
    return hashlib.sha256(body).hexdigest()


def _selection_task_order_sha256(approved_slugs: frozenset[str]) -> str:
    body = "".join(f"{index}\0{slug}\n" for index, slug in enumerate(sorted(approved_slugs))).encode()
    return hashlib.sha256(body).hexdigest()


def _git_output(
    repository: Path,
    arguments: list[str],
    *,
    error_code: str = "exclusion_selection_code_invalid",
) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ExportError(error_code) from error
    if completed.stderr:
        raise ExportError(error_code)
    return completed.stdout


def _load_target_rendering_contract() -> TargetRenderingContract:
    body, artifact = _read_stable_file(
        TARGET_RENDERING_CONTRACT_PATH,
        max_bytes=MAX_TARGET_RENDERING_CONTRACT_BYTES,
    )
    if artifact.sha256 != TARGET_RENDERING_CONTRACT_SHA256:
        raise ExportError("target_rendering_contract_hash_mismatch")
    value = _parse_json_object(body, "target_rendering_contract_invalid")
    if value != TARGET_RENDERING_CONTRACT:
        raise ExportError("target_rendering_contract_invalid")

    repository = Path(__file__).resolve().parents[3]
    record = (
        _git_output(
            repository,
            ["ls-tree", "HEAD", "--", "deps/renderers"],
            error_code="target_renderer_revision_invalid",
        )
        .strip()
        .split(maxsplit=3)
    )
    if (
        len(record) != 4
        or record[:2] != ["160000", "commit"]
        or record[2] != value["renderer"]["repository_revision"]
        or record[3] != "deps/renderers"
    ):
        raise ExportError("target_renderer_revision_invalid")
    return TargetRenderingContract(artifact=artifact, body=body, value=value)


def _validate_selection_code(code: object) -> None:
    if not isinstance(code, dict) or set(code) != {
        "exporter_sha256",
        "materializer_sha256",
        "repository_revision",
        "submodules",
    }:
        raise ExportError("exclusion_selection_invalid")
    repository = Path(__file__).resolve().parents[3]
    revision = code.get("repository_revision")
    submodules = code.get("submodules")
    materializer = Path(__file__).resolve().parent / "materialize_qwen_repair.py"
    if (
        not _valid_git_sha(revision)
        or not _valid_sha256(code.get("exporter_sha256"))
        or code["exporter_sha256"] != _fingerprint_stable_file(Path(__file__).resolve()).sha256
        or not _valid_sha256(code.get("materializer_sha256"))
        or code["materializer_sha256"] != _fingerprint_stable_file(materializer).sha256
        or not isinstance(submodules, dict)
        or set(submodules) != set(REQUIRED_RUNTIME_SUBMODULES)
        or any(not _valid_git_sha(value) for value in submodules.values())
        or _git_output(repository, ["rev-parse", "HEAD"]).strip() != revision
    ):
        raise ExportError("exclusion_selection_code_invalid")
    for relative, expected in submodules.items():
        record = _git_output(repository, ["ls-tree", revision, "--", relative]).strip().split(maxsplit=3)
        if len(record) != 4 or record[:3] != ["160000", "commit", expected] or record[3] != relative:
            raise ExportError("exclusion_selection_code_invalid")
        submodule = repository / relative
        if _git_output(submodule, ["rev-parse", "HEAD"]).strip() != expected or _git_output(
            submodule, ["status", "--porcelain=v1", "--untracked-files=all"]
        ):
            raise ExportError("exclusion_selection_code_invalid")


def _load_exclusion_selection(
    path: Path,
    expected_sha256: str,
    *,
    source_artifacts: Mapping[str, FileArtifact],
    task_identity: TaskIdentityContext,
) -> ExclusionSelection:
    if not _valid_sha256(expected_sha256):
        raise ExportError("exclusion_selection_digest_invalid")
    absolute = path if path.is_absolute() else Path.cwd() / path
    normalized = Path(os.path.normpath(absolute))
    try:
        resolved = normalized.resolve(strict=True)
        metadata = normalized.lstat()
    except OSError as error:
        raise ExportError("exclusion_selection_invalid") from error
    if resolved != normalized or not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ExportError("exclusion_selection_invalid")
    body, manifest_artifact = _read_stable_file(
        resolved,
        max_bytes=MAX_REPAIR_SELECTION_BYTES,
        required_mode=0o600,
    )
    if manifest_artifact.sha256 != expected_sha256:
        raise ExportError("exclusion_selection_digest_mismatch")
    manifest = _parse_json_object(body, "exclusion_selection_invalid")
    approval = manifest.get("approval")
    code = manifest.get("code")
    config = manifest.get("config")
    planner = manifest.get("planner")
    selection = manifest.get("selection")
    source = manifest.get("source")
    if (
        set(manifest) != {"approval", "code", "config", "kind", "planner", "schema_version", "selection", "source"}
        or manifest.get("kind") != REPAIR_SELECTION_KIND
        or manifest.get("schema_version") != REPAIR_SELECTION_SCHEMA_VERSION
        or not isinstance(approval, dict)
        or set(approval) != {"approved_task_count", "approved_task_file_sha256"}
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
        or not isinstance(source, dict)
        or set(source) != {"artifacts", "routing_epoch", "task_count"}
    ):
        raise ExportError("exclusion_selection_invalid")
    approved_count = approval.get("approved_task_count")
    union_count = selection.get("approved_repair_count")
    missing_count = selection.get("missing_or_errored_count")
    strict_count = selection.get("strict_invalid_pass_count")
    retained_count = planner.get("retained_count")
    if (
        isinstance(approved_count, bool)
        or not isinstance(approved_count, int)
        or approved_count != len(task_identity.approved_slugs)
        or approval.get("approved_task_file_sha256") != source_artifacts["inputs/task_file.txt"].sha256
        or planner.get("approved_task_count") != approved_count
        or isinstance(retained_count, bool)
        or not isinstance(retained_count, int)
        or isinstance(missing_count, bool)
        or not isinstance(missing_count, int)
        or isinstance(strict_count, bool)
        or not isinstance(strict_count, int)
        or isinstance(union_count, bool)
        or not isinstance(union_count, int)
        or min(retained_count, missing_count, strict_count, union_count) < 0
        or union_count < 1
        or retained_count + missing_count != approved_count
        or missing_count + strict_count != union_count
        or union_count > approved_count
        or planner.get("missing_or_errored_count") != missing_count
        or planner.get("contract_verifiers_revision") != direct_workers.ADMISSION_VERIFIERS_REVISION
        or planner.get("module_sha256") != direct_workers.ADMISSION_RESUME_MODULE_SHA256
        or planner.get("task_index_order_sha256") != _selection_task_order_sha256(task_identity.approved_slugs)
        or source.get("routing_epoch") != 3
        or source.get("task_count") != approved_count
        or config.get("capture_model_io") is not True
        or config.get("enable_thinking") is not True
        or config.get("preserve_thinking") is not True
        or config.get("max_concurrent") != direct_workers.MAX_DIRECT_CONCURRENCY
        or config.get("provider_concurrency") != direct_workers.PRODUCTION_PROVIDER_CONCURRENCY
        or config.get("max_total_tokens") != DEFAULT_MAX_SEQUENCE_TOKENS
        or config.get("retry_class_count") != len(direct_workers.ROLLOUT_RETRY_POLICY)
        or any(not _valid_sha256(config.get(name)) for name in ("retry_policy_sha256", "sha256", "template_sha256"))
    ):
        raise ExportError("exclusion_selection_contract_invalid")
    retry_bytes = "".join(f"{name}\n" for name in sorted(direct_workers.ROLLOUT_RETRY_POLICY)).encode()
    if config["retry_policy_sha256"] != hashlib.sha256(retry_bytes).hexdigest():
        raise ExportError("exclusion_selection_contract_invalid")
    _validate_selection_code(code)

    source_values = source.get("artifacts")
    source_names = {
        "config": "config.toml",
        "direct_workers": DIRECT_WORKERS_FILENAME,
        "image_manifest": "inputs/image_manifest.json",
        "inputs_manifest": "inputs/manifest.json",
        "provenance": "provenance.txt",
        "results": "results.jsonl",
        "source_config": "inputs/source_config.toml",
        "task_file": "inputs/task_file.txt",
    }
    if not isinstance(source_values, dict) or set(source_values) != set(source_names):
        raise ExportError("exclusion_selection_contract_invalid")
    selection_sources = {source_names[name]: _selection_artifact(record) for name, record in source_values.items()}
    if any(source_artifacts.get(name) != artifact for name, artifact in selection_sources.items()):
        raise ExportError("exclusion_selection_source_mismatch")

    artifact_paths = {
        "task_file": resolved.parent / REPAIR_SELECTION_TASK_FILENAME,
        "missing_or_errored_task_file": resolved.parent / REPAIR_MISSING_ERROR_TASK_FILENAME,
        "strict_invalid_pass_task_file": resolved.parent / REPAIR_STRICT_INVALID_PASS_TASK_FILENAME,
    }
    artifact_bodies: dict[str, bytes] = {}
    artifacts: dict[str, FileArtifact] = {}
    for name, artifact_path in artifact_paths.items():
        artifact_bodies[name], artifacts[name] = _read_stable_file(
            artifact_path,
            max_bytes=MAX_REPAIR_SELECTION_BYTES,
            required_mode=0o600,
        )
    union_order = _selection_task_slugs(artifact_bodies["task_file"], allow_empty=False)
    missing_order = _selection_task_slugs(artifact_bodies["missing_or_errored_task_file"], allow_empty=True)
    strict_order = _selection_task_slugs(artifact_bodies["strict_invalid_pass_task_file"], allow_empty=True)
    union = frozenset(union_order)
    missing = frozenset(missing_order)
    strict = frozenset(strict_order)
    evaluator_order = {slug: index for index, slug in enumerate(sorted(task_identity.approved_slugs))}
    if (
        len(union_order) != union_count
        or len(missing_order) != missing_count
        or len(strict_order) != strict_count
        or missing & strict
        or union != missing | strict
        or not union.issubset(task_identity.approved_slugs)
        or list(union_order) != sorted(union, key=evaluator_order.__getitem__)
        or list(missing_order) != sorted(missing, key=evaluator_order.__getitem__)
        or list(strict_order) != sorted(strict, key=evaluator_order.__getitem__)
        or artifacts["task_file"].sha256 != selection.get("task_file_sha256")
        or artifacts["missing_or_errored_task_file"].sha256 != selection.get("missing_or_errored_task_file_sha256")
        or artifacts["strict_invalid_pass_task_file"].sha256 != selection.get("strict_invalid_pass_task_file_sha256")
        or selection.get("missing_or_errored_indices_sha256")
        != _selection_indices_sha256(missing, task_identity.approved_slugs)
        or selection.get("strict_invalid_pass_indices_sha256")
        != _selection_indices_sha256(strict, task_identity.approved_slugs)
        or selection.get("repair_union_indices_sha256")
        != _selection_indices_sha256(union, task_identity.approved_slugs)
    ):
        raise ExportError("exclusion_selection_contract_invalid")
    return ExclusionSelection(
        manifest_path=resolved,
        manifest_artifact=manifest_artifact,
        artifact_paths=artifact_paths,
        artifacts=artifacts,
        approved_task_count=approved_count,
        missing_or_errored_slugs=missing,
        strict_invalid_pass_slugs=strict,
        union_slugs=union,
        source_artifacts=selection_sources,
    )


def _assert_exclusion_selection_unchanged(selection: ExclusionSelection) -> None:
    if _fingerprint_stable_file(selection.manifest_path, required_mode=0o600) != selection.manifest_artifact:
        raise ExportError("exclusion_selection_changed")
    for name, path in selection.artifact_paths.items():
        if _fingerprint_stable_file(path, required_mode=0o600) != selection.artifacts[name]:
            raise ExportError("exclusion_selection_changed")


def _validate_optional_image_manifest(
    run_dir: Path,
    inputs_manifest: Mapping[str, Any],
    taskset: Mapping[str, Any],
    bodies: dict[str, bytes],
    artifacts: dict[str, FileArtifact],
) -> None:
    """Accept only a completely absent or completely bound image manifest."""

    image_path = run_dir / IMAGE_MANIFEST_ARTIFACT
    path_declared = "image_manifest" in taskset
    digest_declared = "image_manifest_sha256" in taskset
    manifest_declared = "image_manifest" in inputs_manifest
    snapshot_present = os.path.lexists(image_path)

    if not any((path_declared, digest_declared, manifest_declared, snapshot_present)):
        return
    if not all((path_declared, digest_declared, manifest_declared, snapshot_present)):
        raise ExportError("image_manifest_binding_invalid")

    record = inputs_manifest["image_manifest"]
    configured_path = taskset["image_manifest"]
    configured_digest = taskset["image_manifest_sha256"]
    if (
        not isinstance(record, dict)
        or set(record) != {"source", "snapshot", "sha256"}
        or not isinstance(record.get("source"), str)
        or not record["source"]
        or not isinstance(record.get("snapshot"), str)
        or not record["snapshot"]
        or not _valid_sha256(record.get("sha256"))
        or not isinstance(configured_path, str)
        or not configured_path
        or not _valid_sha256(configured_digest)
    ):
        raise ExportError("image_manifest_binding_invalid")

    try:
        body, artifact = _read_stable_file(image_path)
        expected_path = image_path.resolve(strict=True)
        manifest_path = Path(record["snapshot"]).resolve(strict=True)
        resolved_config_path = Path(configured_path).resolve(strict=True)
    except (ExportError, OSError, RuntimeError) as error:
        raise ExportError("image_manifest_binding_invalid") from error
    if (
        manifest_path != expected_path
        or resolved_config_path != expected_path
        or record["sha256"] != artifact.sha256
        or configured_digest != artifact.sha256
    ):
        raise ExportError("image_manifest_binding_invalid")
    bodies[IMAGE_MANIFEST_ARTIFACT] = body
    artifacts[IMAGE_MANIFEST_ARTIFACT] = artifact


def _validate_run_provenance(
    run_dir: Path,
    max_sequence_tokens: int,
) -> tuple[dict[str, FileArtifact], dict[str, Any], TaskIdentityContext]:
    bodies: dict[str, bytes] = {}
    artifacts: dict[str, FileArtifact] = {}
    for relative in REQUIRED_RUN_ARTIFACTS:
        body, artifact = _read_stable_file(run_dir / relative)
        bodies[relative] = body
        artifacts[relative] = artifact

    inputs_manifest = _parse_json_object(bodies["inputs/manifest.json"], "input_manifest_invalid")
    expected_snapshots = {
        "config": "inputs/source_config.toml",
        "task_file": "inputs/task_file.txt",
    }
    for key, relative in expected_snapshots.items():
        record = inputs_manifest.get(key)
        if not isinstance(record, dict) or record.get("sha256") != artifacts[relative].sha256:
            raise ExportError("input_manifest_digest_mismatch")

    try:
        config = tomllib.loads(bodies["config.toml"].decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ExportError("resolved_config_invalid") from error

    client = config.get("client")
    sampling = config.get("sampling")
    taskset = config.get("taskset")
    if not isinstance(client, dict) or client.get("type") != "eval":
        raise ExportError("resolved_config_client_invalid")
    if client.get("capture_model_io") is not True:
        raise ExportError("resolved_config_model_io_disabled")
    denylist = client.get("outbound_body_denylist")
    if not isinstance(denylist, list) or not FORBIDDEN_REQUEST_FIELDS.issubset(denylist):
        raise ExportError("resolved_config_forbidden_request_fields_not_denied")
    if not isinstance(sampling, dict):
        raise ExportError("resolved_config_sampling_invalid")
    chat_kwargs = sampling.get("chat_template_kwargs")
    if not isinstance(chat_kwargs, dict) or chat_kwargs.get("enable_thinking") is not True:
        raise ExportError("resolved_config_thinking_disabled")
    if chat_kwargs.get("preserve_thinking") is not True:
        raise ExportError("resolved_config_thinking_not_preserved")
    if not isinstance(taskset, dict):
        raise ExportError("resolved_config_taskset_invalid")
    if taskset.get("task_file_sha256") != artifacts["inputs/task_file.txt"].sha256:
        raise ExportError("resolved_config_task_digest_mismatch")
    _validate_optional_image_manifest(run_dir, inputs_manifest, taskset, bodies, artifacts)
    num_tasks = config.get("num_tasks")
    if isinstance(num_tasks, bool) or not isinstance(num_tasks, int) or num_tasks < 1:
        raise ExportError("resolved_config_task_count_invalid")
    task_identity = _task_identity_context(
        taskset,
        bodies["inputs/task_file.txt"],
        expected_task_count=num_tasks,
    )

    limits: dict[str, int] = {}
    for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= max_sequence_tokens:
            raise ExportError("resolved_config_token_limit_invalid")
        limits[key] = value
    model = config.get("model")
    if not isinstance(model, str) or not model:
        raise ExportError("resolved_config_model_invalid")
    num_rollouts = config.get("num_rollouts")
    if isinstance(num_rollouts, bool) or not isinstance(num_rollouts, int) or num_rollouts < 1:
        raise ExportError("resolved_config_rollout_count_invalid")
    return (
        artifacts,
        {
            "capture_model_io": True,
            "dataset_revision": task_identity.dataset_revision,
            "model": model,
            "num_rollouts": num_rollouts,
            "taskset_id": task_identity.taskset_id,
            **limits,
        },
        task_identity,
    )


def _parse_epoch2_lineage(body: bytes) -> dict[str, int]:
    if body and not body.endswith(b"\n"):
        raise ExportError("routing_epoch2_lineage_invalid")
    lineage: dict[str, int] = {}
    for raw_line in body.splitlines(keepends=True):
        if not raw_line.endswith(b"\n") or not raw_line.strip():
            raise ExportError("routing_epoch2_lineage_invalid")
        record = _parse_json_object(raw_line, "routing_epoch2_lineage_invalid")
        digest = record.get("row_sha256")
        epoch = record.get("routing_epoch")
        if (
            set(record) != {"row_sha256", "routing_epoch"}
            or not _valid_sha256(digest)
            or isinstance(epoch, bool)
            or not isinstance(epoch, int)
            or epoch not in {1, 2}
            or digest in lineage
        ):
            raise ExportError("routing_epoch2_lineage_invalid")
        lineage[digest] = epoch
    return lineage


def _load_epoch3_routing_provenance(
    *,
    resolved_run: Path,
    source_artifacts: Mapping[str, FileArtifact],
    index_artifact: FileArtifact,
    index_body: bytes,
    header: Mapping[str, Any],
    row_sha256: list[str],
    routing_epochs: list[int],
) -> RoutingEpochIndex:
    artifact_paths = {
        DIRECT_WORKERS_FILENAME: (resolved_run / DIRECT_WORKERS_FILENAME, MAX_ROUTING_TRANSITION_BYTES),
        ROUTING_TRANSITION_FILENAME: (resolved_run / ROUTING_TRANSITION_FILENAME, MAX_ROUTING_TRANSITION_BYTES),
        ROUTING_ADMISSION_TRANSITION_FILENAME: (
            resolved_run / ROUTING_ADMISSION_TRANSITION_FILENAME,
            MAX_ROUTING_TRANSITION_BYTES,
        ),
        ROUTING_EPOCH1_ROWS_FILENAME: (
            resolved_run / ROUTING_EPOCH1_ROWS_FILENAME,
            MAX_ROUTING_EPOCH_INDEX_BYTES,
        ),
        ROUTING_EPOCH2_LINEAGE_FILENAME: (
            resolved_run / ROUTING_EPOCH2_LINEAGE_FILENAME,
            MAX_ROUTING_EPOCH_INDEX_BYTES,
        ),
    }
    bodies: dict[str, bytes] = {}
    artifacts: dict[str, FileArtifact] = {}
    for name, (path, max_bytes) in artifact_paths.items():
        bodies[name], artifacts[name] = _read_stable_file(path, max_bytes=max_bytes)

    _parse_json_object(bodies[DIRECT_WORKERS_FILENAME], "routing_direct_workers_invalid")
    _parse_json_object(bodies[ROUTING_TRANSITION_FILENAME], "routing_transition_invalid")
    _parse_json_object(
        bodies[ROUTING_ADMISSION_TRANSITION_FILENAME],
        "routing_admission_transition_invalid",
    )
    if artifacts[ROUTING_TRANSITION_FILENAME].sha256 != header["transition_sha256"]:
        raise ExportError("routing_transition_mismatch")
    if artifacts[ROUTING_ADMISSION_TRANSITION_FILENAME].sha256 != header["admission_transition_sha256"]:
        raise ExportError("routing_admission_transition_mismatch")

    try:
        routing_summary = direct_workers.audit_run_directory(resolved_run)
    except direct_workers.DirectWorkerError as error:
        raise ExportError("routing_schema3_provenance_invalid") from error
    if (
        routing_summary.get("routing_epoch") != 3
        or routing_summary.get("manifest_schema_version") != direct_workers.ROUTER_MANIFEST_SCHEMA_VERSION
        or routing_summary.get("manifest_sha256") != artifacts[DIRECT_WORKERS_FILENAME].sha256
    ):
        raise ExportError("routing_schema3_provenance_invalid")

    for name, (path, max_bytes) in artifact_paths.items():
        if _read_stable_file(path, max_bytes=max_bytes)[1] != artifacts[name]:
            raise ExportError("routing_schema3_provenance_changed")
    if _read_stable_file(resolved_run / "provenance.txt")[1] != source_artifacts["provenance.txt"]:
        raise ExportError("source_provenance_changed")

    epoch1_body = bodies[ROUTING_EPOCH1_ROWS_FILENAME]
    if epoch1_body and not epoch1_body.endswith(b"\n"):
        raise ExportError("routing_epoch1_rows_invalid")
    try:
        epoch1_hashes = epoch1_body.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise ExportError("routing_epoch1_rows_invalid") from error
    if any(not _valid_sha256(digest) for digest in epoch1_hashes) or len(epoch1_hashes) != len(set(epoch1_hashes)):
        raise ExportError("routing_epoch1_rows_invalid")

    epoch2_lineage = _parse_epoch2_lineage(bodies[ROUTING_EPOCH2_LINEAGE_FILENAME])
    if {digest for digest, epoch in epoch2_lineage.items() if epoch == 1} != set(epoch1_hashes):
        raise ExportError("routing_epoch_index_classification_mismatch")
    observed = dict(zip(row_sha256, routing_epochs, strict=True))
    if not set(epoch2_lineage).issubset(observed) or any(
        observed[digest] != epoch for digest, epoch in epoch2_lineage.items()
    ):
        raise ExportError("routing_epoch_index_classification_mismatch")
    if any(digest not in epoch2_lineage and epoch != 3 for digest, epoch in observed.items()):
        raise ExportError("routing_epoch_index_classification_mismatch")

    return RoutingEpochIndex(
        artifact=index_artifact,
        body=index_body,
        admission_transition_artifact=artifacts[ROUTING_ADMISSION_TRANSITION_FILENAME],
        direct_workers_artifact=artifacts[DIRECT_WORKERS_FILENAME],
        epoch1_rows_artifact=artifacts[ROUTING_EPOCH1_ROWS_FILENAME],
        epoch2_lineage_artifact=artifacts[ROUTING_EPOCH2_LINEAGE_FILENAME],
        transition_artifact=artifacts[ROUTING_TRANSITION_FILENAME],
        current_epoch=3,
        results_sha256=header["results_sha256"],
        transition_sha256=header["transition_sha256"],
        row_sha256=tuple(row_sha256),
        routing_epochs=tuple(routing_epochs),
    )


def _load_routing_epoch_index(
    path: Path,
    *,
    run_dir: Path,
    source_artifacts: Mapping[str, FileArtifact],
) -> RoutingEpochIndex:
    if path.is_symlink():
        raise ExportError("routing_epoch_index_symlink_forbidden")
    try:
        resolved = path.resolve(strict=True)
        resolved_run = run_dir.resolve(strict=True)
    except OSError as error:
        raise ExportError("routing_epoch_index_path_invalid") from error
    body, artifact = _read_stable_file(resolved, max_bytes=MAX_ROUTING_EPOCH_INDEX_BYTES)
    if not body or not body.endswith(b"\n"):
        raise ExportError("routing_epoch_index_invalid")
    lines = body.splitlines(keepends=True)
    if any(not line.endswith(b"\n") or not line.strip() for line in lines):
        raise ExportError("routing_epoch_index_invalid")
    header = _parse_json_object(lines[0], "routing_epoch_index_header_invalid")
    if set(header) != {
        "schema_version",
        "kind",
        "results_sha256",
        "transition_sha256",
        "admission_transition_sha256",
        "routing_epoch",
        "row_count",
    }:
        raise ExportError("routing_epoch_index_header_invalid")
    row_count = header.get("row_count")
    current_epoch = header.get("routing_epoch")
    admission_transition_sha256 = header.get("admission_transition_sha256")
    if (
        isinstance(header.get("schema_version"), bool)
        or not isinstance(header.get("schema_version"), int)
        or header["schema_version"] != 1
        or header.get("kind") != ROUTING_EPOCH_INDEX_KIND
        or not _valid_sha256(header.get("results_sha256"))
        or not _valid_sha256(header.get("transition_sha256"))
        or isinstance(current_epoch, bool)
        or not isinstance(current_epoch, int)
        or current_epoch not in {2, 3}
        or (current_epoch == 2 and admission_transition_sha256 is not None)
        or (current_epoch == 3 and not _valid_sha256(admission_transition_sha256))
        or isinstance(row_count, bool)
        or not isinstance(row_count, int)
        or row_count < 0
        or len(lines) != row_count + 1
    ):
        raise ExportError("routing_epoch_index_header_invalid")

    row_sha256: list[str] = []
    routing_epochs: list[int] = []
    for expected_row, raw_line in enumerate(lines[1:]):
        record = _parse_json_object(raw_line, "routing_epoch_index_record_invalid")
        if set(record) != {"row", "row_sha256", "routing_epoch"}:
            raise ExportError("routing_epoch_index_record_invalid")
        row = record.get("row")
        epoch = record.get("routing_epoch")
        digest = record.get("row_sha256")
        if (
            isinstance(row, bool)
            or not isinstance(row, int)
            or row != expected_row
            or not _valid_sha256(digest)
            or isinstance(epoch, bool)
            or not isinstance(epoch, int)
            or epoch not in range(1, current_epoch + 1)
        ):
            raise ExportError("routing_epoch_index_record_invalid")
        row_sha256.append(digest)
        routing_epochs.append(epoch)
    if len(row_sha256) != len(set(row_sha256)):
        raise ExportError("routing_epoch_index_duplicate_row_hash")

    if current_epoch == 3:
        return _load_epoch3_routing_provenance(
            resolved_run=resolved_run,
            source_artifacts=source_artifacts,
            index_artifact=artifact,
            index_body=body,
            header=header,
            row_sha256=row_sha256,
            routing_epochs=routing_epochs,
        )

    transition_path = resolved_run / ROUTING_TRANSITION_FILENAME
    transition_body, transition_artifact = _read_stable_file(
        transition_path,
        max_bytes=MAX_ROUTING_TRANSITION_BYTES,
    )
    transition = _parse_json_object(transition_body, "routing_transition_invalid")
    if (
        set(transition)
        != {
            "schema_version",
            "kind",
            "source",
            "resume_plan",
            "from_router",
            "to_router",
            "child",
        }
        or not isinstance(transition.get("source"), dict)
        or isinstance(transition.get("schema_version"), bool)
        or not isinstance(transition.get("schema_version"), int)
        or transition["schema_version"] != 1
        or transition.get("kind") != ROUTING_TRANSITION_KIND
        or transition_artifact.sha256 != header["transition_sha256"]
    ):
        raise ExportError("routing_transition_mismatch")

    source = transition["source"]
    resume_plan = transition.get("resume_plan")
    from_router = transition.get("from_router")
    to_router = transition.get("to_router")
    child = transition.get("child")
    source_hash_fields = (
        "config_sha256",
        "source_config_sha256",
        "inputs_manifest_sha256",
        "provenance_sha256",
        "results_sha256",
        "direct_workers_sha256",
    )
    source_revision_fields = ("prime_rl", "verifiers", "renderers")
    resume_integer_fields = (
        "retained_results_size_bytes",
        "retained_row_count",
        "owed_rollout_count",
    )
    if (
        set(source)
        != {
            "canonical_path",
            "slurm_job_id",
            "prime_rl",
            "verifiers",
            "renderers",
            "config_sha256",
            "source_config_sha256",
            "inputs_manifest_sha256",
            "provenance_sha256",
            "results_sha256",
            "results_size_bytes",
            "direct_workers_sha256",
        }
        or any(not _valid_sha256(source.get(key)) for key in source_hash_fields)
        or any(not _valid_git_sha(source.get(key)) for key in source_revision_fields)
        or not isinstance(source.get("canonical_path"), str)
        or not Path(source["canonical_path"]).is_absolute()
        or source["canonical_path"] == str(resolved_run)
        or not isinstance(source.get("slurm_job_id"), str)
        or not source["slurm_job_id"].isdigit()
        or source["slurm_job_id"].startswith("0")
        or isinstance(source.get("results_size_bytes"), bool)
        or not isinstance(source.get("results_size_bytes"), int)
        or source["results_size_bytes"] < 0
        or not isinstance(resume_plan, dict)
        or set(resume_plan)
        != {
            "retained_results_sha256",
            "retained_results_size_bytes",
            "retained_row_count",
            "owed_rollout_count",
            "epoch1_row_hashes_sha256",
        }
        or not _valid_sha256(resume_plan.get("retained_results_sha256"))
        or not _valid_sha256(resume_plan.get("epoch1_row_hashes_sha256"))
        or any(
            isinstance(resume_plan.get(key), bool) or not isinstance(resume_plan.get(key), int) or resume_plan[key] < 0
            for key in resume_integer_fields
        )
        or resume_plan["owed_rollout_count"] < 1
        or not isinstance(from_router, dict)
        or isinstance(from_router.get("manifest_schema_version"), bool)
        or not isinstance(from_router.get("manifest_schema_version"), int)
        or from_router
        != {
            "manifest_schema_version": 1,
            "policy": "round_robin",
            "request_id_headers": [],
        }
        or not isinstance(to_router, dict)
        or set(to_router)
        != {
            "manifest_schema_version",
            "policy",
            "request_id_headers",
            "spec_sha256",
            "endpoint_bundle_sha256",
            "direct_workers_sha256",
        }
        or isinstance(to_router.get("manifest_schema_version"), bool)
        or not isinstance(to_router.get("manifest_schema_version"), int)
        or to_router.get("manifest_schema_version") != 2
        or to_router.get("policy") != "consistent_hash"
        or to_router.get("request_id_headers") != ["x-session-id"]
        or not _valid_sha256(to_router.get("spec_sha256"))
        or not _valid_sha256(to_router.get("endpoint_bundle_sha256"))
        or not _valid_sha256(to_router.get("direct_workers_sha256"))
        or not isinstance(child, dict)
        or set(child)
        != {
            "canonical_path",
            "routing_epoch",
            "config_sha256",
            "source_config_sha256",
            "inputs_manifest_sha256",
        }
        or child.get("canonical_path") != str(resolved_run)
        or isinstance(child.get("routing_epoch"), bool)
        or not isinstance(child.get("routing_epoch"), int)
        or child.get("routing_epoch") != 2
        or child.get("config_sha256") != source_artifacts["config.toml"].sha256
        or child.get("source_config_sha256") != source_artifacts["inputs/source_config.toml"].sha256
        or child.get("inputs_manifest_sha256") != source_artifacts["inputs/manifest.json"].sha256
    ):
        raise ExportError("routing_transition_invalid")

    direct_workers_body, direct_workers_artifact = _read_stable_file(
        resolved_run / DIRECT_WORKERS_FILENAME,
        max_bytes=MAX_ROUTING_TRANSITION_BYTES,
    )
    _parse_json_object(direct_workers_body, "routing_direct_workers_invalid")
    if direct_workers_artifact.sha256 != to_router["direct_workers_sha256"]:
        raise ExportError("routing_direct_workers_hash_mismatch")

    epoch1_rows_body, epoch1_rows_artifact = _read_stable_file(
        resolved_run / ROUTING_EPOCH1_ROWS_FILENAME,
        max_bytes=MAX_ROUTING_EPOCH_INDEX_BYTES,
    )
    if epoch1_rows_artifact.sha256 != resume_plan["epoch1_row_hashes_sha256"]:
        raise ExportError("routing_epoch1_rows_hash_mismatch")
    if epoch1_rows_body and not epoch1_rows_body.endswith(b"\n"):
        raise ExportError("routing_epoch1_rows_invalid")
    try:
        epoch1_row_hashes = epoch1_rows_body.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise ExportError("routing_epoch1_rows_invalid") from error
    if (
        any(not _valid_sha256(digest) for digest in epoch1_row_hashes)
        or len(epoch1_row_hashes) != len(set(epoch1_row_hashes))
        or len(epoch1_row_hashes) != resume_plan["retained_row_count"]
    ):
        raise ExportError("routing_epoch1_rows_invalid")
    expected_epoch1 = set(epoch1_row_hashes)
    observed_epoch1 = {digest for digest, epoch in zip(row_sha256, routing_epochs, strict=True) if epoch == 1}
    if observed_epoch1 != expected_epoch1:
        raise ExportError("routing_epoch_index_classification_mismatch")

    provenance_body, observed_provenance_artifact = _read_stable_file(resolved_run / "provenance.txt")
    if observed_provenance_artifact != source_artifacts["provenance.txt"]:
        raise ExportError("source_provenance_changed")
    try:
        provenance_lines = provenance_body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ExportError("source_provenance_invalid") from error
    transition_markers = [
        value
        for line in provenance_lines
        for key, separator, value in (line.partition("="),)
        if separator and key == "qwen_router_transition_sha256"
    ]
    if transition_markers != [header["transition_sha256"]]:
        raise ExportError("routing_transition_provenance_mismatch")
    routing_epoch_markers = [
        value
        for line in provenance_lines
        for key, separator, value in (line.partition("="),)
        if separator and key == "qwen_router_epoch"
    ]
    if routing_epoch_markers != ["2"]:
        raise ExportError("routing_transition_provenance_mismatch")

    return RoutingEpochIndex(
        artifact=artifact,
        body=body,
        admission_transition_artifact=None,
        direct_workers_artifact=direct_workers_artifact,
        epoch1_rows_artifact=epoch1_rows_artifact,
        epoch2_lineage_artifact=None,
        transition_artifact=transition_artifact,
        current_epoch=2,
        results_sha256=header["results_sha256"],
        transition_sha256=header["transition_sha256"],
        row_sha256=tuple(row_sha256),
        routing_epochs=tuple(routing_epochs),
    )


def _reasoning_text(message: Mapping[str, Any]) -> str | None:
    for key in ("reasoning", "reasoning_content"):
        value = message.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _content_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not (
                isinstance(part, dict)
                and set(part) == {"type", "text"}
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            ):
                raise ExportError("captured_response_content_invalid")
            parts.append(part["text"])
        return "".join(parts)
    raise ExportError("captured_response_content_invalid")


def _flat_tool_calls(calls: object, *, nested: bool) -> list[tuple[str, str, str]]:
    if calls is None:
        return []
    if not isinstance(calls, list):
        raise ExportError("captured_response_tool_calls_invalid")
    flattened: list[tuple[str, str, str]] = []
    for call in calls:
        if not isinstance(call, dict):
            raise ExportError("captured_response_tool_calls_invalid")
        if nested:
            if set(call) != {"id", "type", "function"} or call.get("type") != "function":
                raise ExportError("captured_response_tool_calls_invalid")
            function = call.get("function")
            if not isinstance(function, dict) or set(function) != {"name", "arguments"}:
                raise ExportError("captured_response_tool_calls_invalid")
        else:
            if set(call) != {"id", "name", "arguments"}:
                raise ExportError("captured_response_tool_calls_invalid")
            function = call
        if not isinstance(function, dict):
            raise ExportError("captured_response_tool_calls_invalid")
        call_id = call.get("id")
        name = function.get("name")
        arguments = function.get("arguments")
        if (
            not isinstance(call_id, str)
            or not call_id
            or not isinstance(name, str)
            or not name
            or not _valid_tool_arguments(arguments)
        ):
            raise ExportError("captured_response_tool_calls_invalid")
        flattened.append((call_id, name, arguments))
    return flattened


def _validate_usage(node_usage: object, response_body: dict[str, Any], kind: str) -> None:
    if not isinstance(node_usage, dict):
        raise ExportError("captured_response_usage_missing")
    response_usage = response_body.get("usage")
    if not isinstance(response_usage, dict):
        raise ExportError("captured_response_usage_missing")

    def token_count(value: object, *, positive: bool = False) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or (positive and value == 0):
            raise ExportError("captured_response_usage_invalid")
        return value

    prompt = token_count(response_usage.get("prompt_tokens"))
    completion = token_count(response_usage.get("completion_tokens"), positive=True)
    if kind == "normalized_stream_response":
        expected = {"prompt_tokens": prompt, "completion_tokens": completion}
        cached = response_usage.get("cached_input_tokens")
        reasoning = response_usage.get("reasoning_tokens")
    else:
        prompt_details = response_usage.get("prompt_tokens_details")
        completion_details = response_usage.get("completion_tokens_details")
        cached = prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
        reasoning = completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else None
        expected = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
        }
    if cached is not None:
        cached = token_count(cached)
        if kind == "exact_provider_json":
            if cached > prompt:
                raise ExportError("captured_response_usage_invalid")
            expected["prompt_tokens"] = prompt - cached
        expected["cached_input_tokens"] = cached
    if reasoning is not None:
        reasoning = token_count(reasoning)
        if reasoning > completion:
            raise ExportError("captured_response_usage_invalid")
        expected["reasoning_tokens"] = reasoning
    observed = {
        key: node_usage.get(key)
        for key in ("prompt_tokens", "completion_tokens", "cached_input_tokens", "reasoning_tokens")
        if node_usage.get(key) is not None
    }
    for key, value in observed.items():
        token_count(value, positive=key == "completion_tokens")
    if observed != expected:
        raise ExportError("captured_response_usage_mismatch")


def _validate_captured_response(node: dict[str, Any]) -> None:
    model_io = node.get("model_io")
    response = model_io.get("response") if isinstance(model_io, dict) else None
    if not isinstance(response, dict) or not isinstance(response.get("body"), dict):
        raise ExportError("captured_response_invalid")
    kind = response.get("kind")
    body = response["body"]
    if kind == "exact_provider_json":
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ExportError("captured_response_invalid")
        raw_message = choices[0].get("message")
        raw_finish = choices[0].get("finish_reason")
        nested_calls = True
    elif kind == "normalized_stream_response":
        raw_message = body.get("message")
        raw_finish = body.get("finish_reason")
        nested_calls = False
    else:
        raise ExportError("captured_response_invalid")
    if not isinstance(raw_message, dict):
        raise ExportError("captured_response_invalid")
    if raw_message.get("role") != "assistant":
        raise ExportError("captured_response_invalid")
    allowed_raw_message_keys = {
        "role",
        "content",
        "provider_state",
        "reasoning",
        "reasoning_content",
        "reasoning_details",
        "tool_calls",
    }
    if kind == "exact_provider_json":
        allowed_raw_message_keys.add("provider_specific_fields")
    if "role" not in raw_message or not set(raw_message).issubset(allowed_raw_message_keys):
        raise ExportError("captured_response_invalid")
    if not _valid_redundant_provider_specific_fields(raw_message):
        raise ExportError("captured_response_invalid")
    if "reasoning" in raw_message and "reasoning_content" in raw_message:
        raise ExportError("captured_response_invalid")

    message = node.get("message")
    if not isinstance(message, dict):
        raise ExportError("captured_response_message_mismatch")
    if any(
        source.get(field) is not None
        for source in (raw_message, message)
        for field in ("provider_state", "reasoning_details")
    ):
        raise ExportError("unsupported_assistant_state")
    if _content_text(raw_message.get("content")) != _content_text(message.get("content")):
        raise ExportError("captured_response_message_mismatch")
    if (_reasoning_text(raw_message) or "") != (message.get("reasoning_content") or ""):
        raise ExportError("captured_response_reasoning_mismatch")
    if _flat_tool_calls(raw_message.get("tool_calls"), nested=nested_calls) != _flat_tool_calls(
        message.get("tool_calls"), nested=False
    ):
        raise ExportError("captured_response_tool_calls_mismatch")
    finish_reason = node.get("finish_reason")
    if not isinstance(finish_reason, str) or not finish_reason:
        raise ExportError("captured_response_finish_reason_invalid")
    if raw_finish != finish_reason:
        raise ExportError("captured_response_finish_reason_mismatch")
    _validate_usage(node.get("usage"), body, kind)


def _normalize_tool_call(call: object) -> dict[str, Any]:
    if not isinstance(call, dict):
        raise ExportError("assistant_tool_call_invalid")
    if isinstance(call.get("function"), dict):
        function = call["function"]
        call_type = call.get("type", "function")
    else:
        function = call
        call_type = "function"
    call_id = call.get("id")
    name = function.get("name")
    arguments = function.get("arguments")
    if (
        call_type != "function"
        or not isinstance(call_id, str)
        or not call_id
        or not isinstance(name, str)
        or not name
        or not isinstance(arguments, str)
    ):
        raise ExportError("assistant_tool_call_invalid")
    if not _valid_tool_arguments(arguments):
        raise ExportError("assistant_tool_arguments_not_json")
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _normalize_tools(tools: object) -> list[dict[str, Any]]:
    if not isinstance(tools, list) or not tools:
        raise ExportError("tool_schema_missing")
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or set(tool) != {"type", "function"} or tool.get("type") != "function":
            raise ExportError("tool_schema_invalid")
        function = tool.get("function")
        if (
            not isinstance(function, dict)
            or not {"name"}.issubset(function)
            or not set(function).issubset({"name", "description", "parameters", "strict"})
        ):
            raise ExportError("tool_schema_invalid")
        name = function.get("name")
        description = function.get("description", "")
        parameters = function.get("parameters", {})
        strict = function.get("strict")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(description, str)
            or not isinstance(parameters, dict)
            or _contains_json_null(parameters)
            or (strict is not None and not isinstance(strict, bool))
        ):
            raise ExportError("tool_schema_invalid")
        normalized_function = {
            "description": description,
            "name": name,
            "parameters": copy.deepcopy(parameters),
        }
        if strict is not None:
            normalized_function["strict"] = strict
        normalized.append({"type": "function", "function": normalized_function})
    _canonical_json_bytes(normalized)
    return normalized


def _stable_trace_tools(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] | None = None
    selected_digest: str | None = None
    full_requests = 0
    for node in nodes:
        if node.get("sampled") is not True:
            continue
        model_io = node.get("model_io")
        request = model_io.get("request") if isinstance(model_io, dict) else None
        if not isinstance(request, dict):
            raise ExportError("model_request_missing")
        if request.get("kind") == "full":
            body = request.get("body")
            if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
                raise ExportError("full_model_request_invalid")
            tools = _normalize_tools(body.get("tools"))
            digest = _json_sha256(tools)
            if selected_digest is not None and digest != selected_digest:
                raise ExportError("tool_schema_changed_within_trace")
            selected = tools
            selected_digest = digest
            full_requests += 1
        elif request.get("kind") == "delta":
            changed = (
                set(request.get("set_fields") or {})
                | set(request.get("remove_fields") or [])
                | set(request.get("append_fields") or {})
            )
            if "tools" in changed:
                raise ExportError("tool_schema_changed_within_trace")
        else:
            raise ExportError("model_request_invalid")
    if full_requests == 0 or selected is None:
        raise ExportError("tool_schema_missing")
    return selected


def _root_path(nodes: list[dict[str, Any]], node_id: int) -> list[int]:
    path: list[int] = []
    seen: set[int] = set()
    current: int | None = node_id
    while current is not None:
        if (
            isinstance(current, bool)
            or not isinstance(current, int)
            or not 0 <= current < len(nodes)
            or current in seen
        ):
            raise ExportError("message_graph_invalid")
        seen.add(current)
        path.append(current)
        parent = nodes[current].get("parent")
        if parent is not None and (isinstance(parent, bool) or not isinstance(parent, int)):
            raise ExportError("message_graph_invalid")
        current = parent
    path.reverse()
    return path


def _normalize_message(node: object, *, target: bool) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise ExportError("message_invalid")
    message = node.get("message")
    if not isinstance(message, dict):
        raise ExportError("message_invalid")
    role = message.get("role")
    content = message.get("content")
    if role not in {"system", "user", "assistant", "tool"}:
        raise ExportError("message_invalid")
    allowed_keys = {
        "assistant": {
            "role",
            "content",
            "provider_state",
            "reasoning_content",
            "reasoning_details",
            "tool_calls",
        },
        "system": {"role", "content"},
        "tool": {"role", "content", "name", "tool_call_id"},
        "user": {"role", "content"},
    }[role]
    required_keys = {"role"} if role == "assistant" else {"role", "content"}
    if not required_keys.issubset(message) or not set(message).issubset(allowed_keys):
        raise ExportError("message_invalid")
    if role == "assistant":
        if any(message.get(field) is not None for field in ("provider_state", "reasoning_details")):
            raise ExportError("unsupported_assistant_state")
        if content is not None and not isinstance(content, str):
            raise ExportError("message_content_invalid")
        normalized: dict[str, Any] = {
            "role": "assistant",
            "content": content or "",
            "finish_reason": None,
            "trainable": target,
        }
        reasoning = message.get("reasoning_content")
        if reasoning is not None:
            if not isinstance(reasoning, str):
                raise ExportError("assistant_reasoning_invalid")
            normalized["reasoning_content"] = reasoning
        if node.get("sampled") is True:
            finish_reason = node.get("finish_reason")
            if finish_reason not in TRAINABLE_FINISH_REASONS:
                raise ExportError("assistant_finish_reason_invalid")
            normalized["finish_reason"] = finish_reason
        calls = message.get("tool_calls")
        if calls:
            if not isinstance(calls, list):
                raise ExportError("assistant_tool_call_invalid")
            normalized["tool_calls"] = [_normalize_tool_call(call) for call in calls]
        return normalized

    if not isinstance(content, str):
        raise ExportError("message_content_invalid")
    normalized = {"role": role, "content": content, "trainable": False}
    if role == "tool":
        call_id = message.get("tool_call_id")
        if not isinstance(call_id, str) or not call_id:
            raise ExportError("tool_message_invalid")
        normalized["tool_call_id"] = call_id
        name = message.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise ExportError("tool_message_invalid")
            normalized["name"] = name
    return normalized


def _target_rows(
    trace: dict[str, Any],
    *,
    source_trace_index: int,
    source_split_row_index: int,
    source_trace_sha256: str,
    task_sha256: str,
    reward: float,
    tools: list[dict[str, Any]],
    routing_epoch: int | None,
) -> Iterator[dict[str, Any]]:
    raw_nodes = trace.get("nodes")
    if not isinstance(raw_nodes, list) or not all(isinstance(node, dict) for node in raw_nodes):
        raise ExportError("message_graph_invalid")
    nodes = list(raw_nodes)
    sampled_ids = [index for index, node in enumerate(nodes) if node.get("sampled") is True]
    for target_turn_index, node_id in enumerate(sampled_ids):
        path = _root_path(nodes, node_id)
        messages = [_normalize_message(nodes[path_id], target=path_id == node_id) for path_id in path]
        if (
            not messages
            or messages[-1].get("role") != "assistant"
            or messages[-1].get("trainable") is not True
            or sum(message.get("trainable") is True for message in messages) != 1
        ):
            raise ExportError("target_message_invalid")
        source_reasoning_fields = sum(
            isinstance(nodes[path_id].get("message"), dict) and "reasoning_content" in nodes[path_id]["message"]
            for path_id in path
            if nodes[path_id].get("message", {}).get("role") == "assistant"
        )
        retained_reasoning_fields = sum(
            "reasoning_content" in message for message in messages if message.get("role") == "assistant"
        )
        source_finish_reasons = sum(
            nodes[path_id].get("sampled") is True
            for path_id in path
            if nodes[path_id].get("message", {}).get("role") == "assistant"
        )
        retained_finish_reasons = sum(
            isinstance(message.get("finish_reason"), str) for message in messages if message.get("role") == "assistant"
        )
        if source_reasoning_fields != retained_reasoning_fields or source_finish_reasons != retained_finish_reasons:
            raise ExportError("transcript_fidelity_mismatch")
        row = {
            "assistant_target_count": 1,
            "history_reasoning_policy": "preserve_all_assistant_reasoning",
            "is_correct": reward > 0,
            "messages": messages,
            "reward": reward,
            "source_episode_id": source_trace_sha256,
            "source_node_index": node_id,
            "source_split_row_index": source_split_row_index,
            "source_trace_index": source_trace_index,
            "source_trajectory_assistant_turn_count": len(sampled_ids),
            "target_assistant_message_index": len(messages) - 1,
            "target_assistant_turn_index": target_turn_index,
            "target_finish_reason": messages[-1]["finish_reason"],
            "target_has_reasoning": bool(str(messages[-1].get("reasoning_content") or "").strip()),
            "task_id": task_sha256,
            "tools": tools,
            "transcript_fidelity": {
                "retained_assistant_reasoning_fields": retained_reasoning_fields,
                "retained_sampled_finish_reasons": retained_finish_reasons,
                "source_assistant_reasoning_fields": source_reasoning_fields,
                "source_sampled_finish_reasons": source_finish_reasons,
            },
        }
        if routing_epoch is not None:
            row["routing_epoch"] = routing_epoch
        yield row


def _trace_reward(trace: dict[str, Any]) -> float:
    rewards = trace.get("rewards")
    if not isinstance(rewards, dict) or not rewards:
        raise ExportError("trace_reward_missing")
    values = list(rewards.values())
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values
    ):
        raise ExportError("trace_reward_invalid")
    reward = float(sum(values))
    if reward not in {0.0, 1.0}:
        raise ExportError("trace_reward_not_binary")
    return reward


def _contains_unsupported_provider_state(value: object) -> bool:
    if isinstance(value, dict):
        return any(value.get(key) is not None for key in ("provider_state", "reasoning_details")) or any(
            _contains_unsupported_provider_state(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_unsupported_provider_state(item) for item in value)
    return False


def _validate_trainable_trace(
    trace: dict[str, Any],
    *,
    reward: float,
    max_sequence_tokens: int,
    require_exact_provider_json: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the exact strict validation used before any SFT row is emitted."""
    if _contains_unsupported_provider_state(trace):
        raise ExportError("unsupported_assistant_state")
    if trace.get("is_completed") is not True:
        raise ExportError("trace_not_completed")
    stop_condition = trace.get("stop_condition")
    if not isinstance(stop_condition, str) or not stop_condition:
        raise ExportError("trace_stop_condition_invalid")
    raw_nodes = trace.get("nodes")
    if not isinstance(raw_nodes, list) or not all(isinstance(node, dict) for node in raw_nodes):
        raise ExportError("message_graph_invalid")
    nodes = list(raw_nodes)
    for node in nodes:
        message = node.get("message")
        if isinstance(message, dict) and message.get("role") == "assistant":
            calls = message.get("tool_calls")
            if isinstance(calls, list):
                for call in calls:
                    _normalize_tool_call(call)
        if node.get("sampled") is not True:
            continue
        finish_reason = node.get("finish_reason")
        if not isinstance(finish_reason, str) or not finish_reason:
            raise ExportError("captured_response_finish_reason_invalid")
        if finish_reason == "length":
            raise ExportError("sampled_finish_reason_length")
        if finish_reason not in TRAINABLE_FINISH_REASONS:
            raise ExportError("assistant_finish_reason_invalid")
    problems = _audit_trace(
        trace,
        require_reasoning=True,
        max_sequence_tokens=max_sequence_tokens,
        require_token_data=False,
        require_logprobs=False,
        require_model_io=True,
        require_request_graph_match=True,
        require_exact_provider_json=require_exact_provider_json,
    )
    if problems:
        if "normalized_stream_response_disallowed" in problems:
            raise ExportError("normalized_stream_response_disallowed")
        response_semantic_suffixes = (
            "_model_io_response_semantics_invalid",
            "_model_io_response_finish_reason_invalid",
            "_model_io_response_message_mismatch",
            "_model_io_response_finish_reason_mismatch",
            "_model_io_response_usage_mismatch",
            "_model_io_response_model_mismatch",
        )
        if all(problem.endswith(response_semantic_suffixes) for problem in problems):
            for node in nodes:
                if node.get("sampled") is True:
                    _validate_captured_response(node)
        raise ExportError("trace_validation_failed")
    for node in nodes:
        if node.get("sampled") is True:
            _validate_captured_response(node)
    tools = _stable_trace_tools(nodes)
    probe_rows = list(
        _target_rows(
            trace,
            source_trace_index=0,
            source_split_row_index=0,
            source_trace_sha256="0" * 64,
            task_sha256="0" * 64,
            reward=reward,
            tools=tools,
            routing_epoch=None,
        )
    )
    if not probe_rows:
        raise ExportError("trace_has_no_sft_targets")
    return nodes, tools


def _split_for_task(task_sha256: str, *, salt: str, validation_permyriad: int) -> str:
    digest = hashlib.sha256(f"{salt}\0{task_sha256}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % SPLIT_BUCKETS
    return "validation" if bucket < validation_permyriad else "train"


def _write_json(path: Path, value: object) -> FileArtifact:
    body = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    with os.fdopen(os.open(path, flags, 0o600), "wb") as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    return FileArtifact(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


def _write_bytes(path: Path, body: bytes) -> FileArtifact:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    with os.fdopen(os.open(path, flags, 0o600), "wb") as output:
        output.write(body)
        output.flush()
        os.fsync(output.fileno())
    return FileArtifact(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _validate_options(options: ExportOptions) -> None:
    if options.selection not in {"pass-only", "all-outcomes"}:
        raise ExportError("selection_invalid")
    if options.expected_count is not None and options.expected_count < 1:
        raise ExportError("expected_count_invalid")
    if not 0 <= options.validation_permyriad < SPLIT_BUCKETS:
        raise ExportError("validation_permyriad_invalid")
    if not options.split_salt:
        raise ExportError("split_salt_invalid")
    if options.max_sequence_tokens < 1:
        raise ExportError("max_sequence_tokens_invalid")
    if not isinstance(options.require_task_index_binding, bool):
        raise ExportError("task_index_binding_invalid")
    if not isinstance(options.require_exact_provider_json, bool):
        raise ExportError("exact_provider_json_requirement_invalid")
    if (options.exclusion_selection_manifest is None) != (options.exclusion_selection_manifest_sha256 is None):
        raise ExportError("exclusion_selection_arguments_invalid")
    if options.exclusion_selection_manifest is not None and (
        options.selection != "pass-only" or options.routing_epoch_index is None
    ):
        raise ExportError("exclusion_selection_arguments_invalid")
    if os.path.lexists(options.output_dir):
        raise ExportError("output_already_exists")
    try:
        if options.output_dir.resolve().is_relative_to(options.results.parent.resolve()):
            raise ExportError("output_inside_source_run")
    except OSError as error:
        raise ExportError("path_resolution_failed") from error


def export_sft(options: ExportOptions) -> dict[str, Any]:
    """Validate and atomically export one run; return only aggregate metadata."""
    _validate_options(options)
    target_rendering_contract = _load_target_rendering_contract()
    run_dir = options.results.parent
    output_parent = options.output_dir.parent
    output_parent.mkdir(parents=True, exist_ok=True)

    with _hold_source_locks(
        run_dir,
        require_router_lock=options.routing_epoch_index is not None,
    ):
        source_artifacts, config_summary, task_identity = _validate_run_provenance(
            run_dir,
            options.max_sequence_tokens,
        )
        routing_index: RoutingEpochIndex | None = None
        if options.routing_epoch_index is not None:
            routing_index = _load_routing_epoch_index(
                options.routing_epoch_index,
                run_dir=run_dir,
                source_artifacts=source_artifacts,
            )
            source_artifacts[ROUTING_EPOCH_INDEX_FILENAME] = routing_index.artifact
            source_artifacts[DIRECT_WORKERS_FILENAME] = routing_index.direct_workers_artifact
            source_artifacts[ROUTING_EPOCH1_ROWS_FILENAME] = routing_index.epoch1_rows_artifact
            source_artifacts[ROUTING_TRANSITION_FILENAME] = routing_index.transition_artifact
            if routing_index.admission_transition_artifact is not None:
                source_artifacts[ROUTING_ADMISSION_TRANSITION_FILENAME] = routing_index.admission_transition_artifact
            if routing_index.epoch2_lineage_artifact is not None:
                source_artifacts[ROUTING_EPOCH2_LINEAGE_FILENAME] = routing_index.epoch2_lineage_artifact
        results_artifact = _fingerprint_stable_file(options.results)
        source_artifacts["results.jsonl"] = results_artifact
        exclusion_selection: ExclusionSelection | None = None
        if options.exclusion_selection_manifest is not None:
            assert options.exclusion_selection_manifest_sha256 is not None
            exclusion_selection = _load_exclusion_selection(
                options.exclusion_selection_manifest,
                options.exclusion_selection_manifest_sha256,
                source_artifacts=source_artifacts,
                task_identity=task_identity,
            )
        source, source_before = _open_regular(options.results)
        temporary = Path(tempfile.mkdtemp(prefix=f".{options.output_dir.name}.", dir=output_parent))
        published = False
        train_sink: JSONLSink | None = None
        validation_sink: JSONLSink | None = None
        try:
            train_sink = JSONLSink(temporary / "train" / "train.jsonl")
            validation_sink = JSONLSink(temporary / "validation" / "train.jsonl")
            sinks = {"train": train_sink, "validation": validation_sink}
            counts: Counter[str] = Counter()
            split_task_hashes: dict[str, set[str]] = {"train": set(), "validation": set()}
            split_trace_indices = {"train": 0, "validation": 0}
            seen_trace_ids: set[str] = set()
            seen_source_rows: set[str] = set()
            seen_task_slugs: set[str] = set()
            seen_missing_or_error_slugs: set[str] = set()
            seen_strict_invalid_pass_slugs: set[str] = set()
            source_digest = hashlib.sha256()
            ignored_incomplete_tail = False

            for source_trace_index, raw_line in enumerate(source):
                source_digest.update(raw_line)
                try:
                    trace = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    if exclusion_selection is not None and not raw_line.endswith(b"\n"):
                        ignored_incomplete_tail = True
                        break
                    if not raw_line.strip():
                        raise ExportError("results_jsonl_blank_line") from error
                    if not raw_line.endswith(b"\n"):
                        raise ExportError("results_jsonl_unterminated") from error
                    raise ExportError("results_jsonl_invalid") from error
                source_trace_sha256 = hashlib.sha256(raw_line).hexdigest()
                routing_epoch: int | None = None
                if routing_index is not None:
                    if source_trace_index >= len(routing_index.row_sha256):
                        raise ExportError("routing_epoch_index_row_count_mismatch")
                    if routing_index.row_sha256[source_trace_index] != source_trace_sha256:
                        raise ExportError("routing_epoch_index_row_hash_mismatch")
                    routing_epoch = routing_index.routing_epochs[source_trace_index]
                    counts[f"routing_epoch_{routing_epoch}_input_traces"] += 1
                if not isinstance(trace, dict):
                    raise ExportError("trace_not_object")
                counts["input_traces"] += 1

                trace_id = trace.get("id")
                task = trace.get("task")
                if not isinstance(trace_id, str) or not trace_id or not isinstance(task, dict):
                    raise ExportError("trace_identity_invalid")
                trace_id_sha256 = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()
                if trace_id_sha256 in seen_trace_ids:
                    raise ExportError("duplicate_trace_id")
                seen_trace_ids.add(trace_id_sha256)
                if source_trace_sha256 in seen_source_rows:
                    raise ExportError("duplicate_trace_row")
                seen_source_rows.add(source_trace_sha256)
                task_slug = _opaque_task_slug(
                    task,
                    evaluator_order=(
                        task_identity.approved_slug_order
                        if exclusion_selection is not None or options.require_task_index_binding
                        else None
                    ),
                )
                if exclusion_selection is not None and task_slug in seen_task_slugs:
                    raise ExportError("duplicate_task_trace")
                seen_task_slugs.add(task_slug)
                task_sha256 = _task_identity_sha256(task_identity, task)

                errors = trace.get("errors")
                if not isinstance(errors, list):
                    raise ExportError("trace_errors_invalid")
                if exclusion_selection is not None and task_slug in exclusion_selection.union_slugs:
                    if task_slug in exclusion_selection.missing_or_errored_slugs:
                        if not errors:
                            raise ExportError("exclusion_selection_category_mismatch")
                        seen_missing_or_error_slugs.add(task_slug)
                        counts["excluded_error_traces"] += 1
                    else:
                        if errors:
                            raise ExportError("exclusion_selection_category_mismatch")
                        try:
                            reward = _trace_reward(trace)
                        except ExportError as error:
                            raise ExportError("exclusion_selection_category_mismatch") from error
                        if reward != 1.0:
                            raise ExportError("exclusion_selection_category_mismatch")
                        counts["scored_pass_traces"] += 1
                        try:
                            _validate_trainable_trace(
                                trace,
                                reward=reward,
                                max_sequence_tokens=options.max_sequence_tokens,
                                require_exact_provider_json=options.require_exact_provider_json,
                            )
                        except ExportError:
                            pass
                        else:
                            raise ExportError("exclusion_selection_category_mismatch")
                        seen_strict_invalid_pass_slugs.add(task_slug)
                    counts["exclusion_selected_traces"] += 1
                    continue
                if errors:
                    if exclusion_selection is not None:
                        raise ExportError("exclusion_selection_incomplete")
                    counts["excluded_error_traces"] += 1
                    continue
                reward = _trace_reward(trace)
                counts["scored_pass_traces" if reward > 0 else "scored_fail_traces"] += 1
                if trace.get("is_completed") is not True:
                    raise ExportError("trace_not_completed")
                stop_condition = trace.get("stop_condition")
                if not isinstance(stop_condition, str) or not stop_condition:
                    raise ExportError("trace_stop_condition_invalid")
                if options.selection == "pass-only" and reward == 0:
                    counts["selection_excluded_fail_traces"] += 1
                    continue

                _nodes, tools = _validate_trainable_trace(
                    trace,
                    reward=reward,
                    max_sequence_tokens=options.max_sequence_tokens,
                    require_exact_provider_json=options.require_exact_provider_json,
                )
                split = _split_for_task(
                    task_sha256,
                    salt=options.split_salt,
                    validation_permyriad=options.validation_permyriad,
                )
                split_task_hashes[split].add(task_sha256)
                source_split_row_index = split_trace_indices[split]
                emitted = 0
                for row in _target_rows(
                    trace,
                    source_trace_index=source_trace_index,
                    source_split_row_index=source_split_row_index,
                    source_trace_sha256=source_trace_sha256,
                    task_sha256=task_sha256,
                    reward=reward,
                    tools=tools,
                    routing_epoch=routing_epoch,
                ):
                    sinks[split].write(row)
                    emitted += 1
                if emitted == 0:
                    raise ExportError("trace_has_no_sft_targets")
                counts["selected_traces"] += 1
                counts["selected_pass_traces" if reward > 0 else "selected_fail_traces"] += 1
                counts["emitted_rows"] += emitted
                counts[f"{split}_traces"] += 1
                counts[f"{split}_rows"] += emitted
                if routing_epoch is not None:
                    counts[f"routing_epoch_{routing_epoch}_selected_traces"] += 1
                    counts[f"routing_epoch_{routing_epoch}_emitted_rows"] += emitted
                split_trace_indices[split] += 1

            source_after = os.fstat(source.fileno())
            if not _same_file(source_before, source_after):
                raise ExportError("results_jsonl_changed")
            results_sha256 = source_digest.hexdigest()
            if FileArtifact(bytes=source_after.st_size, sha256=results_sha256) != results_artifact:
                raise ExportError("results_jsonl_changed")
            if routing_index is not None:
                if counts["input_traces"] != len(routing_index.row_sha256):
                    raise ExportError("routing_epoch_index_row_count_mismatch")
                if results_sha256 != routing_index.results_sha256:
                    raise ExportError("routing_epoch_index_results_hash_mismatch")
            if exclusion_selection is None:
                if options.expected_count is not None and counts["input_traces"] != options.expected_count:
                    raise ExportError("input_trace_count_mismatch")
                counts["approved_tasks"] = len(task_identity.approved_slugs)
            else:
                unseen = task_identity.approved_slugs - seen_task_slugs
                expected_unseen = exclusion_selection.missing_or_errored_slugs - seen_missing_or_error_slugs
                if (
                    seen_strict_invalid_pass_slugs != exclusion_selection.strict_invalid_pass_slugs
                    or unseen != expected_unseen
                    or (ignored_incomplete_tail and not unseen)
                    or seen_task_slugs - exclusion_selection.union_slugs
                    != task_identity.approved_slugs - exclusion_selection.union_slugs
                    or counts["input_traces"] + len(unseen) != exclusion_selection.approved_task_count
                    or options.expected_count != exclusion_selection.approved_task_count
                ):
                    raise ExportError("exclusion_selection_accounting_mismatch")
                counts["approved_tasks"] = exclusion_selection.approved_task_count
                counts["exclusion_missing_tasks"] = len(unseen)
                counts["exclusion_missing_or_errored_tasks"] = len(exclusion_selection.missing_or_errored_slugs)
                counts["exclusion_strict_invalid_pass_tasks"] = len(exclusion_selection.strict_invalid_pass_slugs)
            if counts["selected_traces"] == 0:
                raise ExportError("no_selected_traces")
            if split_task_hashes["train"] & split_task_hashes["validation"]:
                raise ExportError("task_split_overlap")

            train_artifact = train_sink.close()
            train_sink = None
            validation_artifact = validation_sink.close()
            validation_sink = None
            source_artifacts["results.jsonl"] = results_artifact
            retained_routing_index_artifact: FileArtifact | None = None
            if routing_index is not None:
                retained_routing_index_artifact = _write_bytes(
                    temporary / ROUTING_EPOCH_INDEX_FILENAME,
                    routing_index.body,
                )
                if retained_routing_index_artifact != routing_index.artifact:
                    raise ExportError("routing_epoch_index_copy_mismatch")
            task_split = {
                "format_version": FORMAT_VERSION,
                "split_salt": options.split_salt,
                "validation_permyriad": options.validation_permyriad,
                "train_task_sha256": sorted(split_task_hashes["train"]),
                "validation_task_sha256": sorted(split_task_hashes["validation"]),
            }
            task_split_artifact = _write_json(temporary / "task-split.json", task_split)
            retained_target_rendering_contract_artifact = _write_bytes(
                temporary / TARGET_RENDERING_CONTRACT_FILENAME,
                target_rendering_contract.body,
            )
            if retained_target_rendering_contract_artifact != target_rendering_contract.artifact:
                raise ExportError("target_rendering_contract_copy_mismatch")

            output_artifacts = {
                "task-split.json": task_split_artifact.as_dict(),
                TARGET_RENDERING_CONTRACT_FILENAME: retained_target_rendering_contract_artifact.as_dict(),
                "train/train.jsonl": train_artifact.as_dict(),
                "validation/train.jsonl": validation_artifact.as_dict(),
            }
            if retained_routing_index_artifact is not None:
                output_artifacts[ROUTING_EPOCH_INDEX_FILENAME] = retained_routing_index_artifact.as_dict()
            manifest = {
                "artifacts": output_artifacts,
                "config": config_summary,
                "counts": dict(sorted(counts.items())),
                "exporter": {
                    "file_sha256": _read_stable_file(Path(__file__).resolve())[1].sha256,
                    "format_version": FORMAT_VERSION,
                },
                "format": {
                    "assistant_tool_calls": "OpenAI function-call objects",
                    "assistant_finish_reason": "retained verbatim for every sampled assistant message",
                    "history_assistant_reasoning": "retained verbatim",
                    "loss_mask": "message.trainable; exactly one final assistant message is true",
                    "sample_unit": "one unique sampled assistant node with its root-to-node context",
                    "target": "authentic reasoning_content, content, tool_calls, and finish_reason",
                    "task_identity": "sha256(taskset id + NUL + dataset revision + NUL + approved opaque task slug)",
                },
                "max_sequence_tokens": options.max_sequence_tokens,
                "selection": options.selection,
                "source_artifacts": {key: value.as_dict() for key, value in sorted(source_artifacts.items())},
                "split": {
                    "policy": "sha256(split_salt + NUL + stable task identity SHA-256) modulo 10000",
                    "split_salt": options.split_salt,
                    "validation_permyriad": options.validation_permyriad,
                },
                "target_rendering": target_rendering_contract.value,
            }
            if exclusion_selection is not None:
                manifest["exclusion_selection"] = {
                    "artifacts": {
                        name: artifact.as_dict() for name, artifact in sorted(exclusion_selection.artifacts.items())
                    },
                    "approved_task_count": exclusion_selection.approved_task_count,
                    "manifest": exclusion_selection.manifest_artifact.as_dict(),
                    "missing_or_errored_count": len(exclusion_selection.missing_or_errored_slugs),
                    "strict_invalid_pass_count": len(exclusion_selection.strict_invalid_pass_slugs),
                    "union_count": exclusion_selection.count,
                }
            if routing_index is not None:
                routing_epoch_manifest = {
                    "current_epoch": routing_index.current_epoch,
                    "emitted_rows": {
                        str(epoch): counts[f"routing_epoch_{epoch}_emitted_rows"]
                        for epoch in range(1, routing_index.current_epoch + 1)
                    },
                    "epoch1_row_hashes_sha256": routing_index.epoch1_rows_artifact.sha256,
                    "index_sha256": routing_index.artifact.sha256,
                    "input_traces": {
                        str(epoch): counts[f"routing_epoch_{epoch}_input_traces"]
                        for epoch in range(1, routing_index.current_epoch + 1)
                    },
                    "results_sha256": routing_index.results_sha256,
                    "row_mapping": "one unique SHA-256 mapping per physical results.jsonl row",
                    "transition_sha256": routing_index.transition_sha256,
                }
                if routing_index.admission_transition_artifact is not None:
                    routing_epoch_manifest["admission_transition_sha256"] = (
                        routing_index.admission_transition_artifact.sha256
                    )
                if routing_index.epoch2_lineage_artifact is not None:
                    routing_epoch_manifest["epoch2_lineage_sha256"] = routing_index.epoch2_lineage_artifact.sha256
                manifest["routing_epochs"] = routing_epoch_manifest
            if exclusion_selection is not None:
                _assert_exclusion_selection_unchanged(exclusion_selection)
            if _fingerprint_stable_file(TARGET_RENDERING_CONTRACT_PATH) != target_rendering_contract.artifact:
                raise ExportError("target_rendering_contract_changed")
            _write_json(temporary / "manifest.json", manifest)
            _fsync_dir(temporary / "train")
            _fsync_dir(temporary / "validation")
            _fsync_dir(temporary)
            if exclusion_selection is not None:
                _assert_exclusion_selection_unchanged(exclusion_selection)
            if _fingerprint_stable_file(TARGET_RENDERING_CONTRACT_PATH) != target_rendering_contract.artifact:
                raise ExportError("target_rendering_contract_changed")
            if os.path.lexists(options.output_dir):
                raise ExportError("output_already_exists")
            os.replace(temporary, options.output_dir)
            _fsync_dir(output_parent)
            published = True
            summary = {
                "approved_tasks": counts.get("approved_tasks", counts["input_traces"]),
                "excluded_error_traces": counts["excluded_error_traces"],
                "input_traces": counts["input_traces"],
                "output_sha256": {
                    "manifest": _read_stable_file(options.output_dir / "manifest.json")[1].sha256,
                    "target_rendering_contract": retained_target_rendering_contract_artifact.sha256,
                    "train": train_artifact.sha256,
                    "validation": validation_artifact.sha256,
                },
                "rows": {
                    "total": counts["emitted_rows"],
                    "train": counts["train_rows"],
                    "validation": counts["validation_rows"],
                },
                "selected_traces": counts["selected_traces"],
                "selection": options.selection,
                "status": "exported",
            }
            if exclusion_selection is not None:
                summary["exclusion"] = {
                    "excluded_present_traces": counts["exclusion_selected_traces"],
                    "missing_tasks": counts["exclusion_missing_tasks"],
                    "missing_or_errored_count": counts["exclusion_missing_or_errored_tasks"],
                    "selection_manifest_sha256": exclusion_selection.manifest_artifact.sha256,
                    "strict_invalid_pass_count": counts["exclusion_strict_invalid_pass_tasks"],
                    "union_count": exclusion_selection.count,
                }
            if routing_index is not None:
                if retained_routing_index_artifact is None:
                    raise ExportError("routing_epoch_index_copy_missing")
                summary["output_sha256"]["routing_epoch_index"] = retained_routing_index_artifact.sha256
                summary["routing_epoch_rows"] = {
                    str(epoch): counts[f"routing_epoch_{epoch}_emitted_rows"]
                    for epoch in range(1, routing_index.current_epoch + 1)
                }
            return summary
        finally:
            source.close()
            for sink in (train_sink, validation_sink):
                if sink is not None and not sink._file.closed:
                    sink._file.close()
            if not published and temporary.exists():
                shutil.rmtree(temporary)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--selection", choices=("pass-only", "all-outcomes"), required=True)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--validation-permyriad", type=int, default=DEFAULT_VALIDATION_PERMYRIAD)
    parser.add_argument("--split-salt", default=DEFAULT_SPLIT_SALT)
    parser.add_argument("--max-sequence-tokens", type=int, default=DEFAULT_MAX_SEQUENCE_TOKENS)
    parser.add_argument(
        "--routing-epoch-index",
        type=Path,
        help="strictly validate and retain a hash-bound qwen_router_epochs.jsonl sidecar",
    )
    parser.add_argument("--exclusion-selection-manifest", type=Path)
    parser.add_argument("--exclusion-selection-manifest-sha256")
    parser.add_argument("--require-task-index-binding", action="store_true")
    parser.add_argument("--require-exact-provider-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    options = ExportOptions(
        results=args.results,
        output_dir=args.output_dir,
        selection=args.selection,
        expected_count=args.expected_count,
        validation_permyriad=args.validation_permyriad,
        split_salt=args.split_salt,
        max_sequence_tokens=args.max_sequence_tokens,
        routing_epoch_index=args.routing_epoch_index,
        exclusion_selection_manifest=args.exclusion_selection_manifest,
        exclusion_selection_manifest_sha256=args.exclusion_selection_manifest_sha256,
        require_task_index_binding=args.require_task_index_binding,
        require_exact_provider_json=args.require_exact_provider_json,
    )
    try:
        summary = export_sft(options)
    except ExportError as error:
        print(json.dumps({"code": error.code, "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"code": "internal_error", "status": "error"}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
