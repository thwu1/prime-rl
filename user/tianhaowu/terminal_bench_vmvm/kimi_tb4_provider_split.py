#!/usr/bin/env python3
"""Materialize and certify a private, full-denominator Kimi TB4 provider split.

Membership is derived exclusively from one reviewed image/resource manifest.  No
task identifier is written to stdout or to the aggregate certificates.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ctypes
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import tomllib
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from audit_traces import (
    KIMI_K3_MAX_MODEL_IO_CONTRACT,
    _audit_trace,
    _task_slug,
)
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from direct_kimi_router import C23_CAPACITY_PROFILE, C64_W2_CAPACITY_PROFILE
from direct_kimi_workers import DirectKimiWorkerError, worker_generation_contract
from eval_run_identity import load_eval_run_identity_bytes

TOTAL_TASKS = 66
LEGACY_SANDOQ_TASKS = 31
LARGE_PROVIDER_TASKS = 32
GPU_UNSUPPORTED_TASKS = 3
CPU_TASKS = LEGACY_SANDOQ_TASKS + LARGE_PROVIDER_TASKS
COMPOSE_CPU_TASKS = 11
MAX_SEQUENCE_TOKENS = 262_144
SAMPLING_MAX_TOKENS = 32_768
TB4_MIN_CPU_PASS_RATE = 0.04
TB4_MAX_CPU_PASS_RATE = 0.22

GIB = 1024**3
LEGACY_CPU_COUNT = 8
LEGACY_OUTER_MEMORY_BYTES = 8 * GIB
LEGACY_DISK_AVAILABLE_BYTES = 100 * GIB
MIN_MEMORY_HEADROOM_BYTES = 2 * GIB
DISK_HEADROOM_BYTES = 5 * GIB
LARGE_RESOURCE_MULTIPLIER = 2
LARGE_MIN_CPU_COUNT = 32
LARGE_MIN_OUTER_MEMORY_BYTES = 36 * GIB
LARGE_MIN_DISK_AVAILABLE_BYTES = 105 * GIB

MANIFEST_KIND = "terminal-bench-4-image-resource-manifest"
MANIFEST_SCHEMA_VERSION = 2
PARTITION_KIND = "kimi-tb4-provider-partition"
PARTITION_SCHEMA_VERSION = 2
CAPACITY_KIND = "kimi-tb4-large-provider-capacity"
PROVIDER_CERTIFICATE_KIND = "direct-kimi-tb4-provider-partition"
UNION_CERTIFICATE_KIND = "direct-kimi-tb4-provider-union"

CANONICAL_TASK_FILE_SHA256 = "9485011ac4a953f4a4a1c7c5e78550b6d7de6f760a3859dac15a3610cf4ad892"
CANONICAL_IMAGE_MANIFEST_SHA256 = "6dd632029af8da52f99f1d364e983a5da2e855afeb6a2ea5fc84fd00e1683513"
CANONICAL_DATASET_ARCHIVE_SHA256 = "6d2c57cbcb1a75b5cdc0b0f989747fa68cdc65df8ff0a6893045a70ced7e668e"
CANONICAL_DATASET_CONTENT_SHA256 = "564a42a4e2ce0a5efd23758656e4e419b3566a36234dfc09bae1029bc15326b2"

LEGACY_SELECTOR = "legacy-sandoq.tasks.txt"
LARGE_SELECTOR = "large-provider.tasks.txt"
GPU_SELECTOR = "gpu-unsupported.tasks.txt"
PARTITION_RECEIPT = "partition.json"
MERGED_RESULTS = "results.jsonl"
UNION_CERTIFICATE = "certificate.json"
BUNDLE_COMMIT = ".complete.json"
FILE_COMMIT_SUFFIX = ".complete.json"

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{40,64}\Z")
IMAGE_RE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z")
TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z")
RFC3339_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
EXPECTED_DENYLIST = ["logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"]
PINNED_CAPACITY_PUBLIC_KEY_SHA256 = "c5c6b7d6476b78bffe56666ca353ad71b9f3a11cd9a8219cabb5a81c43f95857"
CAPACITY_VALIDITY = timedelta(days=8)
CAPACITY_VALIDITY_SECONDS = int(CAPACITY_VALIDITY.total_seconds())
CAPACITY_CLOCK_SKEW = timedelta(minutes=5)


class KimiProviderSplitError(ValueError):
    """A stable, aggregate-only failure from the split/certification path."""


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    cpu_count: int
    memory_bytes: int
    disk_bytes: int
    gpu_count: int


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    task_id: str
    agent_resources: ResourceRequest
    verifier_resources: ResourceRequest
    verifier_mode: Literal["shared", "separate"]
    requires_compose: bool


@dataclass(frozen=True, slots=True)
class Partition:
    legacy_sandoq: tuple[str, ...]
    large_provider: tuple[str, ...]
    gpu_unsupported: tuple[str, ...]
    verifier_modes: Mapping[str, str]
    compose_required: tuple[str, ...]


@dataclass(slots=True)
class _HeldEvidenceFile:
    name: str
    descriptor: int
    identity: tuple[int, ...]
    body: bytes


@dataclass(slots=True)
class _HeldRunEvidence:
    root: Path
    directory: int
    directory_identity: tuple[int, int, int, int]
    files: dict[str, _HeldEvidenceFile]

    def revalidate(self) -> None:
        _validate_private_parent(self.root, self.directory, self.directory_identity)
        for evidence in self.files.values():
            before = os.fstat(evidence.descriptor)
            visible = os.stat(evidence.name, dir_fd=self.directory, follow_symlinks=False)
            os.lseek(evidence.descriptor, 0, os.SEEK_SET)
            observed = bytearray()
            while chunk := os.read(evidence.descriptor, 1 << 20):
                observed.extend(chunk)
            after = os.fstat(evidence.descriptor)
            if (
                _stat_identity(before) != evidence.identity
                or _stat_identity(after) != evidence.identity
                or _stat_identity(visible) != evidence.identity
                or bytes(observed) != evidence.body
            ):
                raise KimiProviderSplitError("run_evidence_changed")
        _validate_private_parent(self.root, self.directory, self.directory_identity)

    def artifact(self, name: str) -> dict[str, Any]:
        evidence = self.files[name]
        return {
            "path": str(self.root / evidence.name),
            "bytes": len(evidence.body),
            "sha256": sha256_bytes(evidence.body),
        }

    def close(self) -> None:
        for evidence in self.files.values():
            os.close(evidence.descriptor)
        os.close(self.directory)


@dataclass(slots=True)
class _HeldArtifact:
    path: Path
    parent_path: Path
    parent: int
    parent_identity: tuple[int, int, int, int]
    name: str
    descriptor: int
    identity: tuple[int, ...]
    body: bytes
    private: bool


@dataclass(slots=True)
class _HeldArtifactSet:
    artifacts: dict[Path, _HeldArtifact]

    @classmethod
    def create(cls) -> _HeldArtifactSet:
        return cls(artifacts={})

    def capture(
        self,
        path: Path,
        *,
        code: str,
        maximum_bytes: int,
        private: bool,
    ) -> tuple[bytes, dict[str, Any]]:
        absolute = _absolute_path(path)
        existing = self.artifacts.get(absolute)
        if existing is not None:
            if private and not existing.private:
                raise KimiProviderSplitError(code)
            return existing.body, self.record(absolute)
        absolute, parent, descriptor, name = _open_anchored(
            absolute,
            directory=False,
            code=code,
        )
        try:
            before = os.fstat(descriptor)
            parent_metadata = os.fstat(parent)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size > maximum_bytes
                or (private and before.st_uid != os.getuid())
                or (private and stat.S_IMODE(before.st_mode) != 0o600)
                or (private and before.st_nlink != 1)
                or (
                    private
                    and (
                        not stat.S_ISDIR(parent_metadata.st_mode)
                        or parent_metadata.st_uid != os.getuid()
                        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
                    )
                )
            ):
                raise KimiProviderSplitError(code)
            body = bytearray()
            while chunk := os.read(descriptor, 1 << 20):
                body.extend(chunk)
                if len(body) > maximum_bytes:
                    raise KimiProviderSplitError(code)
            after = os.fstat(descriptor)
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                _stat_identity(before) != _stat_identity(after)
                or _stat_identity(after) != _stat_identity(visible)
                or len(body) != after.st_size
            ):
                raise KimiProviderSplitError(f"{code}_changed")
            captured = _HeldArtifact(
                path=absolute,
                parent_path=absolute.parent,
                parent=parent,
                parent_identity=_directory_identity(parent_metadata),
                name=name,
                descriptor=descriptor,
                identity=_stat_identity(after),
                body=bytes(body),
                private=private,
            )
            self.artifacts[absolute] = captured
        except BaseException:
            os.close(descriptor)
            os.close(parent)
            raise
        return captured.body, self.record(absolute)

    def record(self, path: Path) -> dict[str, Any]:
        artifact = self.artifacts[_absolute_path(path)]
        return {
            "path": str(artifact.path),
            "bytes": len(artifact.body),
            "sha256": sha256_bytes(artifact.body),
        }

    def revalidate(self) -> None:
        for artifact in self.artifacts.values():
            held_parent = os.fstat(artifact.parent)
            visible_parent = artifact.parent_path.lstat()
            if (
                _directory_identity(held_parent) != artifact.parent_identity
                or _directory_identity(visible_parent) != artifact.parent_identity
                or artifact.parent_path.resolve(strict=True) != artifact.parent_path
            ):
                raise KimiProviderSplitError("provider_artifact_changed")
            before = os.fstat(artifact.descriptor)
            visible = os.stat(
                artifact.name,
                dir_fd=artifact.parent,
                follow_symlinks=False,
            )
            os.lseek(artifact.descriptor, 0, os.SEEK_SET)
            body = bytearray()
            while chunk := os.read(artifact.descriptor, 1 << 20):
                body.extend(chunk)
            after = os.fstat(artifact.descriptor)
            if (
                _stat_identity(before) != artifact.identity
                or _stat_identity(after) != artifact.identity
                or _stat_identity(visible) != artifact.identity
                or bytes(body) != artifact.body
            ):
                raise KimiProviderSplitError("provider_artifact_changed")

    def close(self) -> None:
        for artifact in self.artifacts.values():
            os.close(artifact.descriptor)
            os.close(artifact.parent)


def canonical_json(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise KimiProviderSplitError("evidence_not_strict_json") from error


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _owned_file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
    )


def read_regular(
    path: Path,
    *,
    code: str,
    maximum_bytes: int = 128 * 1024 * 1024,
    private: bool = False,
    held: _HeldArtifactSet | None = None,
) -> bytes:
    body, _record = _read_regular_evidence(
        path,
        code=code,
        maximum_bytes=maximum_bytes,
        private=private,
        held=held,
    )
    return body


def _absolute_path(path: Path) -> Path:
    try:
        return Path(os.path.abspath(os.fspath(path)))
    except (OSError, TypeError, ValueError) as error:
        raise KimiProviderSplitError("path_invalid") from error


def _open_anchored(path: Path, *, directory: bool, code: str) -> tuple[Path, int, int, str]:
    """Open ``path`` without following any component and retain its parent."""

    absolute = _absolute_path(path)
    components = absolute.parts[1:]
    if not components and not directory:
        raise KimiProviderSplitError(code)
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    parent = os.open("/", directory_flags)
    try:
        for component in components[:-1]:
            child = os.open(component, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
        name = components[-1] if components else "."
        flags = directory_flags if directory else os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=parent)
    except OSError as error:
        os.close(parent)
        raise KimiProviderSplitError(code) from error
    return absolute, parent, descriptor, name


def _read_regular_evidence(
    path: Path,
    *,
    code: str,
    maximum_bytes: int = 128 * 1024 * 1024,
    private: bool = False,
    held: _HeldArtifactSet | None = None,
) -> tuple[bytes, dict[str, Any]]:
    if held is not None:
        return held.capture(
            path,
            code=code,
            maximum_bytes=maximum_bytes,
            private=private,
        )
    try:
        absolute, parent, descriptor, name = _open_anchored(path, directory=False, code=code)
    except KimiProviderSplitError:
        raise
    try:
        before = os.fstat(descriptor)
        parent_metadata = os.fstat(parent)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size > maximum_bytes
            or (private and (before.st_uid != os.getuid() or stat.S_IMODE(before.st_mode) != 0o600))
            or (private and before.st_nlink != 1)
            or (
                private
                and (
                    not stat.S_ISDIR(parent_metadata.st_mode)
                    or parent_metadata.st_uid != os.getuid()
                    or stat.S_IMODE(parent_metadata.st_mode) != 0o700
                )
            )
        ):
            raise KimiProviderSplitError(code)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > maximum_bytes:
                raise KimiProviderSplitError(code)
        after = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
    finally:
        os.close(descriptor)
        os.close(parent)
    if _stat_identity(before) != _stat_identity(after) or _stat_identity(after) != _stat_identity(visible):
        raise KimiProviderSplitError(f"{code}_changed")
    payload = bytes(body)
    return payload, {"path": str(absolute), "bytes": len(payload), "sha256": sha256_bytes(payload)}


def _json_object(payload: bytes, *, code: str, canonical: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KimiProviderSplitError(code) from error
    if not isinstance(value, dict) or (canonical and canonical_json(value) != payload):
        raise KimiProviderSplitError(code)
    return value


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _resource(value: object) -> ResourceRequest:
    keys = {"cpu_count", "memory_bytes", "disk_bytes", "gpu_count"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or not all(_positive_integer(value.get(key)) for key in keys - {"gpu_count"})
        or not _nonnegative_integer(value.get("gpu_count"))
    ):
        raise KimiProviderSplitError("resource_manifest_invalid")
    return ResourceRequest(**value)


def _manifest_entry(value: object) -> ManifestEntry:
    if not isinstance(value, dict) or set(value) != {
        "task_id",
        "images",
        "agent_resources",
        "verifier_resources",
        "verifier_mode",
        "runtime_requirements",
    }:
        raise KimiProviderSplitError("resource_manifest_invalid")
    task_id = value.get("task_id")
    images = value.get("images")
    verifier_mode = value.get("verifier_mode")
    runtime_requirements = value.get("runtime_requirements")
    if (
        not isinstance(task_id, str)
        or TASK_ID_RE.fullmatch(task_id) is None
        or not isinstance(images, dict)
        or set(images) != {"agent", "verifier"}
        or any(IMAGE_RE.fullmatch(str(images.get(role, ""))) is None for role in ("agent", "verifier"))
        or verifier_mode not in {"shared", "separate"}
        or not isinstance(runtime_requirements, dict)
        or set(runtime_requirements) != {"compose"}
        or not isinstance(runtime_requirements.get("compose"), bool)
    ):
        raise KimiProviderSplitError("resource_manifest_invalid")
    return ManifestEntry(
        task_id=task_id,
        agent_resources=_resource(value.get("agent_resources")),
        verifier_resources=_resource(value.get("verifier_resources")),
        verifier_mode=verifier_mode,
        requires_compose=runtime_requirements["compose"],
    )


def _phase_requests(entry: ManifestEntry) -> tuple[ResourceRequest, ResourceRequest]:
    return entry.agent_resources, entry.verifier_resources


def _legacy_admissible(entry: ManifestEntry) -> bool:
    if entry.requires_compose:
        return False
    for request in _phase_requests(entry):
        if (
            request.gpu_count != 0
            or request.cpu_count > LEGACY_CPU_COUNT
            or request.memory_bytes + MIN_MEMORY_HEADROOM_BYTES > LEGACY_OUTER_MEMORY_BYTES
            or request.disk_bytes + DISK_HEADROOM_BYTES > LEGACY_DISK_AVAILABLE_BYTES
        ):
            return False
    return True


def _manifest_source_valid(value: object) -> bool:
    return value == {
        "dataset_archive_sha256": CANONICAL_DATASET_ARCHIVE_SHA256,
        "dataset_content_sha256": CANONICAL_DATASET_CONTENT_SHA256,
        "image_manifest_sha256": CANONICAL_IMAGE_MANIFEST_SHA256,
        "task_file_sha256": CANONICAL_TASK_FILE_SHA256,
    }


def parse_manifest(payload: bytes, expected_sha256: str) -> tuple[dict[str, Any], tuple[ManifestEntry, ...]]:
    if SHA256_RE.fullmatch(expected_sha256 or "") is None or sha256_bytes(payload) != expected_sha256:
        raise KimiProviderSplitError("resource_manifest_digest_mismatch")
    value = _json_object(payload, code="resource_manifest_invalid", canonical=True)
    if (
        set(value) != {"schema_version", "kind", "source", "entries"}
        or value.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or value.get("kind") != MANIFEST_KIND
        or not _manifest_source_valid(value.get("source"))
        or not isinstance(value.get("entries"), list)
        or len(value["entries"]) != TOTAL_TASKS
    ):
        raise KimiProviderSplitError("resource_manifest_invalid")
    entries = tuple(_manifest_entry(item) for item in value["entries"])
    identifiers = [entry.task_id for entry in entries]
    if len(identifiers) != len(set(identifiers)):
        raise KimiProviderSplitError("resource_manifest_duplicate_member")
    if sha256_bytes(_selector_payload(identifiers)) != CANONICAL_TASK_FILE_SHA256:
        raise KimiProviderSplitError("resource_manifest_task_order_mismatch")
    image_manifest = {
        "images": {item["task_id"]: item["images"] for item in value["entries"]},
        "schema_version": 1,
        "source": "terminal-bench-prebuilt-v4.0.0-approved-66",
    }
    if sha256_bytes(canonical_json(image_manifest)) != CANONICAL_IMAGE_MANIFEST_SHA256:
        raise KimiProviderSplitError("resource_manifest_image_binding_mismatch")
    return value, entries


def derive_partition(entries: Sequence[ManifestEntry]) -> Partition:
    if len(entries) != TOTAL_TASKS or len({entry.task_id for entry in entries}) != TOTAL_TASKS:
        raise KimiProviderSplitError("partition_source_invalid")
    legacy: list[str] = []
    large: list[str] = []
    gpu: list[str] = []
    compose: list[str] = []
    modes: dict[str, str] = {}
    for entry in entries:
        modes[entry.task_id] = entry.verifier_mode
        gpu_count = max(request.gpu_count for request in _phase_requests(entry))
        if entry.requires_compose:
            compose.append(entry.task_id)
        if gpu_count:
            if gpu_count != 1:
                raise KimiProviderSplitError("gpu_partition_invalid")
            gpu.append(entry.task_id)
        elif _legacy_admissible(entry):
            legacy.append(entry.task_id)
        else:
            large.append(entry.task_id)
    gpu_members = set(gpu)
    if len(compose) != COMPOSE_CPU_TASKS or any(member in gpu_members for member in compose):
        raise KimiProviderSplitError("compose_partition_invalid")
    if (len(legacy), len(large), len(gpu)) != (
        LEGACY_SANDOQ_TASKS,
        LARGE_PROVIDER_TASKS,
        GPU_UNSUPPORTED_TASKS,
    ):
        raise KimiProviderSplitError("partition_cardinality_mismatch")
    groups = (set(legacy), set(large), set(gpu))
    if any(groups[index] & groups[other] for index in range(3) for other in range(index + 1, 3)):
        raise KimiProviderSplitError("partition_overlap")
    if set().union(*groups) != {entry.task_id for entry in entries}:
        raise KimiProviderSplitError("partition_not_exhaustive")
    large_entries = [entry for entry in entries if entry.task_id in groups[1]]
    required_cpu = max(
        request.cpu_count * LARGE_RESOURCE_MULTIPLIER for entry in large_entries for request in _phase_requests(entry)
    )
    required_memory = max(
        request.memory_bytes * LARGE_RESOURCE_MULTIPLIER
        for entry in large_entries
        for request in _phase_requests(entry)
    )
    required_disk = max(
        request.disk_bytes * LARGE_RESOURCE_MULTIPLIER for entry in large_entries for request in _phase_requests(entry)
    )
    if (
        required_cpu > LARGE_MIN_CPU_COUNT
        or required_memory + max(MIN_MEMORY_HEADROOM_BYTES, math.ceil(LARGE_MIN_OUTER_MEMORY_BYTES * 0.1))
        > LARGE_MIN_OUTER_MEMORY_BYTES
        or required_disk + DISK_HEADROOM_BYTES > LARGE_MIN_DISK_AVAILABLE_BYTES
    ):
        raise KimiProviderSplitError("large_provider_minimum_insufficient")
    return Partition(tuple(legacy), tuple(large), tuple(gpu), modes, tuple(compose))


def _selector_payload(members: Sequence[str]) -> bytes:
    return ("\n".join(members) + "\n").encode("utf-8")


def _partition_receipt_value(manifest_sha256: str, partition: Partition) -> dict[str, Any]:
    selectors = {
        "legacy_sandoq": _selector_payload(partition.legacy_sandoq),
        "large_provider": _selector_payload(partition.large_provider),
        "gpu_unsupported": _selector_payload(partition.gpu_unsupported),
    }
    return {
        "schema_version": PARTITION_SCHEMA_VERSION,
        "kind": PARTITION_KIND,
        "state": "materialized",
        "manifest_sha256": manifest_sha256,
        "partition": {
            "total": TOTAL_TASKS,
            "legacy_sandoq": LEGACY_SANDOQ_TASKS,
            "large_provider": LARGE_PROVIDER_TASKS,
            "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
            "compose_required_cpu": COMPOSE_CPU_TASKS,
            "disjoint": True,
            "exhaustive": True,
            "canonical_order": "manifest-entry-order",
        },
        "selectors": {role: {"bytes": len(body), "sha256": sha256_bytes(body)} for role, body in selectors.items()},
        "policy": {
            "legacy_sandoq": {
                "resource_multiplier": 1,
                "outer_cpu_count": LEGACY_CPU_COUNT,
                "outer_memory_bytes": LEGACY_OUTER_MEMORY_BYTES,
                "memory_headroom_bytes": MIN_MEMORY_HEADROOM_BYTES,
                "disk_available_bytes": LEGACY_DISK_AVAILABLE_BYTES,
                "disk_headroom_bytes": DISK_HEADROOM_BYTES,
                "compose_supported": False,
                "compose_required_tasks": 0,
            },
            "large_provider": {
                "resource_multiplier": LARGE_RESOURCE_MULTIPLIER,
                "minimum_actual_cpu_count": LARGE_MIN_CPU_COUNT,
                "minimum_outer_memory_bytes": LARGE_MIN_OUTER_MEMORY_BYTES,
                "minimum_disk_available_bytes": LARGE_MIN_DISK_AVAILABLE_BYTES,
                "compose_supported": True,
                "compose_required_tasks": COMPOSE_CPU_TASKS,
            },
            "gpu": "deterministic-unsupported-outcome",
        },
    }


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode)


def _validate_private_parent(path: Path, descriptor: int, expected: tuple[int, int, int, int]) -> None:
    try:
        held = os.fstat(descriptor)
        visible = path.lstat()
    except OSError as error:
        raise KimiProviderSplitError("output_parent_changed") from error
    if (
        _directory_identity(held) != expected
        or _directory_identity(visible) != expected
        or not stat.S_ISDIR(held.st_mode)
        or held.st_uid != os.getuid()
        or stat.S_IMODE(held.st_mode) != 0o700
        or path.resolve(strict=True) != path
    ):
        raise KimiProviderSplitError("output_parent_invalid")


def _open_private_parent(path: Path) -> tuple[Path, int, tuple[int, int, int, int]]:
    try:
        absolute, ancestor, descriptor, _name = _open_anchored(
            path,
            directory=True,
            code="output_parent_invalid",
        )
        os.close(ancestor)
    except KimiProviderSplitError:
        raise
    identity = _directory_identity(os.fstat(descriptor))
    try:
        _validate_private_parent(absolute, descriptor, identity)
    except BaseException:
        os.close(descriptor)
        raise
    return absolute, descriptor, identity


def _open_held_run_evidence(run_dir: Path) -> _HeldRunEvidence:
    try:
        root, directory, directory_identity = _open_private_parent(run_dir)
    except KimiProviderSplitError as error:
        raise KimiProviderSplitError("run_directory_invalid") from error
    files: dict[str, _HeldEvidenceFile] = {}
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        for name in ("eval_run_identity.json", "eval_invocations.jsonl", "provenance.txt"):
            try:
                descriptor = os.open(name, flags, dir_fd=directory)
            except OSError as error:
                raise KimiProviderSplitError("run_evidence_invalid") from error
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_nlink != 1
                    or before.st_size > 2 * 1024 * 1024
                ):
                    raise KimiProviderSplitError("run_evidence_invalid")
                body = bytearray()
                while chunk := os.read(descriptor, 1 << 20):
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise KimiProviderSplitError("run_evidence_invalid")
                after = os.fstat(descriptor)
                visible = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (
                    _stat_identity(before) != _stat_identity(after)
                    or _stat_identity(after) != _stat_identity(visible)
                    or len(body) != after.st_size
                ):
                    raise KimiProviderSplitError("run_evidence_changed")
                files[name] = _HeldEvidenceFile(
                    name=name,
                    descriptor=descriptor,
                    identity=_stat_identity(after),
                    body=bytes(body),
                )
            except BaseException:
                os.close(descriptor)
                raise
        evidence = _HeldRunEvidence(root, directory, directory_identity, files)
        evidence.revalidate()
        return evidence
    except BaseException:
        for evidence_file in files.values():
            os.close(evidence_file.descriptor)
        os.close(directory)
        raise


def _write_at(directory: int, name: str, payload: bytes) -> tuple[int, ...]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(name, flags, 0o600, dir_fd=directory)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written < 1:
                raise KimiProviderSplitError("artifact_write_failed")
            view = view[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        identity = _owned_file_identity(os.fstat(descriptor))
    finally:
        os.close(descriptor)
    return identity


def _verify_file_at(directory: int, name: str, expected: bytes) -> tuple[int, ...]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(name, flags, dir_fd=directory)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
        ):
            raise KimiProviderSplitError("published_artifact_invalid")
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    visible = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if (
        _stat_identity(before) != _stat_identity(after)
        or _stat_identity(after) != _stat_identity(visible)
        or bytes(body) != expected
    ):
        raise KimiProviderSplitError("published_artifact_changed")
    return _owned_file_identity(after)


def _verify_bundle_at(
    parent_descriptor: int,
    name: str,
    expected_identity: tuple[int, int, int, int],
    files: Mapping[str, bytes],
) -> None:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        metadata = os.fstat(descriptor)
        if _directory_identity(metadata) != expected_identity:
            raise KimiProviderSplitError("published_directory_changed")
        with os.scandir(descriptor) as iterator:
            names = {entry.name for entry in iterator}
        if names != set(files):
            raise KimiProviderSplitError("published_artifact_invalid")
        for filename, payload in files.items():
            _verify_file_at(descriptor, filename, payload)
        if _directory_identity(os.fstat(descriptor)) != expected_identity:
            raise KimiProviderSplitError("published_directory_changed")
    finally:
        os.close(descriptor)


def _committed_bundle_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    if BUNDLE_COMMIT in files:
        raise KimiProviderSplitError("output_filename_invalid")
    artifacts = {
        name: {"bytes": len(payload), "sha256": sha256_bytes(payload)} for name, payload in sorted(files.items())
    }
    binding = {"artifacts": artifacts}
    marker = {
        "schema_version": 1,
        "kind": "private-bundle-complete",
        "state": "complete",
        "artifacts": artifacts,
        "logical_bundle_sha256": sha256_bytes(canonical_json(binding)),
    }
    return {**files, BUNDLE_COMMIT: canonical_json(marker)}


def _file_commit_payload(name: str, body: bytes) -> bytes:
    return canonical_json(
        {
            "schema_version": 1,
            "kind": "private-file-complete",
            "state": "complete",
            "file": {"name": name, "bytes": len(body), "sha256": sha256_bytes(body)},
        }
    )


def _rename_noreplace(source: str, destination: str, parent_descriptor: int) -> None:
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise KimiProviderSplitError("rename_noreplace_unavailable")
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(parent_descriptor, os.fsencode(source), parent_descriptor, os.fsencode(destination), 1) != 0:
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise KimiProviderSplitError("output_already_exists")
        if error_number in {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP}:
            raise KimiProviderSplitError("rename_noreplace_unsupported")
        raise KimiProviderSplitError("atomic_publish_failed") from OSError(error_number, os.strerror(error_number))


def _publish_private_bundle_portable(
    parent: Path,
    parent_descriptor: int,
    parent_identity: tuple[int, int, int, int],
    output_name: str,
    files: Mapping[str, bytes],
) -> None:
    """Publish via an exclusive directory and a commit marker on rename-poor filesystems."""

    directory_descriptor: int | None = None
    marker_started = False
    try:
        os.mkdir(output_name, 0o700, dir_fd=parent_descriptor)
        directory_descriptor = os.open(
            output_name,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        directory_metadata = os.fstat(directory_descriptor)
        directory_identity = _directory_identity(directory_metadata)
        if (
            not stat.S_ISDIR(directory_metadata.st_mode)
            or directory_metadata.st_uid != os.getuid()
            or stat.S_IMODE(directory_metadata.st_mode) != 0o700
        ):
            raise KimiProviderSplitError("staging_directory_invalid")
        for name, payload in files.items():
            if name == BUNDLE_COMMIT:
                continue
            identity = _write_at(directory_descriptor, name, payload)
            if _verify_file_at(directory_descriptor, name, payload) != identity:
                raise KimiProviderSplitError("published_artifact_changed")
        os.fsync(directory_descriptor)
        visible = os.stat(output_name, dir_fd=parent_descriptor, follow_symlinks=False)
        if _directory_identity(visible) != directory_identity:
            raise KimiProviderSplitError("published_directory_changed")
        marker_started = True
        marker_identity = _write_at(directory_descriptor, BUNDLE_COMMIT, files[BUNDLE_COMMIT])
        if _verify_file_at(directory_descriptor, BUNDLE_COMMIT, files[BUNDLE_COMMIT]) != marker_identity:
            raise KimiProviderSplitError("published_artifact_changed")
        _verify_bundle_at(parent_descriptor, output_name, directory_identity, files)
        os.fsync(directory_descriptor)
        os.fsync(parent_descriptor)
        if (
            _directory_identity(os.stat(output_name, dir_fd=parent_descriptor, follow_symlinks=False))
            != directory_identity
        ):
            raise KimiProviderSplitError("published_directory_changed")
        _validate_private_parent(parent, parent_descriptor, parent_identity)
    except FileExistsError as error:
        raise KimiProviderSplitError("output_already_exists") from error
    except BaseException as error:
        if marker_started:
            raise KimiProviderSplitError("output_publication_indeterminate") from error
        raise
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _publish_private_bundle(output: Path, files: Mapping[str, bytes]) -> None:
    output = _absolute_path(output)
    if not output.name:
        raise KimiProviderSplitError("output_filename_invalid")
    parent, parent_descriptor, parent_identity = _open_private_parent(output.parent)
    files = _committed_bundle_files(files)
    stage_name = f".{output.name}.stage-{secrets.token_hex(8)}"
    stage_identity: tuple[int, int, int, int] | None = None
    stage_descriptor: int | None = None
    published = False
    try:
        try:
            existing = os.stat(output.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            existing_identity = _directory_identity(existing)
            if (
                not stat.S_ISDIR(existing.st_mode)
                or existing.st_uid != os.getuid()
                or stat.S_IMODE(existing.st_mode) != 0o700
            ):
                raise KimiProviderSplitError("output_already_exists")
            _verify_bundle_at(parent_descriptor, output.name, existing_identity, files)
            _validate_private_parent(parent, parent_descriptor, parent_identity)
            return
        os.mkdir(stage_name, 0o700, dir_fd=parent_descriptor)
        stage_descriptor = os.open(
            stage_name,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        stage_metadata = os.fstat(stage_descriptor)
        stage_identity = _directory_identity(stage_metadata)
        if (
            not stat.S_ISDIR(stage_metadata.st_mode)
            or stage_metadata.st_uid != os.getuid()
            or stat.S_IMODE(stage_metadata.st_mode) != 0o700
        ):
            raise KimiProviderSplitError("staging_directory_invalid")
        for name, payload in files.items():
            if not name or "/" in name or name in {".", ".."}:
                raise KimiProviderSplitError("output_filename_invalid")
            _write_at(stage_descriptor, name, payload)
        os.fsync(stage_descriptor)
        _validate_private_parent(parent, parent_descriptor, parent_identity)
        if _directory_identity(os.stat(stage_name, dir_fd=parent_descriptor, follow_symlinks=False)) != stage_identity:
            raise KimiProviderSplitError("staging_directory_changed")
        _verify_bundle_at(parent_descriptor, stage_name, stage_identity, files)
        os.fsync(parent_descriptor)
        try:
            _rename_noreplace(stage_name, output.name, parent_descriptor)
        except KimiProviderSplitError as error:
            if str(error) != "rename_noreplace_unsupported":
                raise
            _publish_private_bundle_portable(
                parent,
                parent_descriptor,
                parent_identity,
                output.name,
                files,
            )
            return
        published = True
        if _directory_identity(os.stat(output.name, dir_fd=parent_descriptor, follow_symlinks=False)) != stage_identity:
            raise KimiProviderSplitError("published_directory_changed")
        _verify_bundle_at(parent_descriptor, output.name, stage_identity, files)
        os.fsync(parent_descriptor)
        _validate_private_parent(parent, parent_descriptor, parent_identity)
    except BaseException as error:
        if published:
            raise KimiProviderSplitError("output_publication_indeterminate") from error
        raise
    finally:
        if stage_descriptor is not None:
            os.close(stage_descriptor)
        os.close(parent_descriptor)


def materialize_partition(manifest: Path, manifest_sha256: str, output: Path) -> dict[str, Any]:
    payload = read_regular(
        manifest,
        code="resource_manifest_invalid",
        maximum_bytes=8 * 1024 * 1024,
        private=True,
    )
    _value, entries = parse_manifest(payload, manifest_sha256)
    partition = derive_partition(entries)
    receipt = _partition_receipt_value(manifest_sha256, partition)
    files = {
        LEGACY_SELECTOR: _selector_payload(partition.legacy_sandoq),
        LARGE_SELECTOR: _selector_payload(partition.large_provider),
        GPU_SELECTOR: _selector_payload(partition.gpu_unsupported),
        PARTITION_RECEIPT: canonical_json(receipt),
    }
    _publish_private_bundle(output, files)
    return receipt


def _read_partition_bundle(
    directory: Path,
    manifest: Path,
    manifest_sha256: str,
    held: _HeldArtifactSet | None = None,
) -> tuple[Partition, dict[str, Any]]:
    try:
        root, descriptor, _identity = _open_private_parent(directory)
    except KimiProviderSplitError as error:
        raise KimiProviderSplitError("partition_bundle_invalid") from error
    else:
        os.close(descriptor)
    manifest_payload = read_regular(
        manifest,
        code="resource_manifest_invalid",
        maximum_bytes=8 * 1024 * 1024,
        private=True,
        held=held,
    )
    _value, entries = parse_manifest(manifest_payload, manifest_sha256)
    partition = derive_partition(entries)
    expected = _committed_bundle_files(
        {
            LEGACY_SELECTOR: _selector_payload(partition.legacy_sandoq),
            LARGE_SELECTOR: _selector_payload(partition.large_provider),
            GPU_SELECTOR: _selector_payload(partition.gpu_unsupported),
            PARTITION_RECEIPT: canonical_json(_partition_receipt_value(manifest_sha256, partition)),
        }
    )
    try:
        observed_names = {entry.name for entry in os.scandir(root)}
    except OSError as error:
        raise KimiProviderSplitError("partition_bundle_invalid") from error
    if observed_names != set(expected):
        raise KimiProviderSplitError("partition_bundle_invalid")
    for name, body in expected.items():
        observed = read_regular(
            root / name,
            code="partition_bundle_invalid",
            private=True,
            held=held,
        )
        if observed != body:
            raise KimiProviderSplitError("partition_bundle_invalid")
    return partition, _partition_receipt_value(manifest_sha256, partition)


def _artifact(
    path: Path,
    *,
    private: bool = False,
    held: _HeldArtifactSet | None = None,
) -> dict[str, Any]:
    _body, record = _read_regular_evidence(
        path,
        code="artifact_invalid",
        private=private,
        held=held,
    )
    return record


def _resolved_config(
    identity: Mapping[str, Any],
    held: _HeldArtifactSet | None = None,
) -> dict[str, Any]:
    record = identity.get("config", {}).get("resolved")
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise KimiProviderSplitError("run_identity_invalid")
    path = Path(str(record["path"]))
    body = read_regular(
        path,
        code="run_config_invalid",
        maximum_bytes=2 * 1024 * 1024,
        private=True,
        held=held,
    )
    if sha256_bytes(body) != record["sha256"]:
        raise KimiProviderSplitError("run_config_invalid")
    try:
        value = tomllib.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise KimiProviderSplitError("run_config_invalid") from error
    if not isinstance(value, dict):
        raise KimiProviderSplitError("run_config_invalid")
    return value


def _config_resource_multiplier(config: Mapping[str, Any]) -> float:
    taskset = config.get("taskset")
    multiplier = taskset.get("resource_multiplier") if isinstance(taskset, dict) else None
    if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)):
        raise KimiProviderSplitError("resource_multiplier_invalid")
    return float(multiplier)


def _provider_name(identity: Mapping[str, Any]) -> str:
    source = identity.get("source")
    if not isinstance(source, dict):
        raise KimiProviderSplitError("run_identity_invalid")
    provider = source.get("sandbox_provider", "vmvm")
    if provider not in {"sandoq", "vmvm"}:
        raise KimiProviderSplitError("provider_unsupported")
    return provider


def _environment_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    provider = _provider_name(identity)
    source = identity["source"]
    execution = identity.get("execution")
    if not isinstance(execution, dict):
        raise KimiProviderSplitError("run_identity_invalid")
    environment = execution.get(f"{provider}_environment")
    runtime = execution.get("runtime")
    if not isinstance(environment, dict) or not isinstance(runtime, dict) or runtime.get("type") != provider:
        raise KimiProviderSplitError("provider_environment_invalid")
    source_keys = (
        ("prime_rl_commit", "verifiers_commit", "renderers_commit", "vmvm_tb_v2_sha256")
        if provider == "vmvm"
        else (
            "prime_rl_commit",
            "verifiers_commit",
            "renderers_commit",
            "sandoq_provider_commit",
            "sandoq_provider_tree",
            "sandoq_site_sha256",
        )
    )
    provider_source = {key: source.get(key) for key in source_keys}
    if any(not isinstance(value, str) or not value for value in provider_source.values()):
        raise KimiProviderSplitError("provider_environment_invalid")
    return {
        "provider": provider,
        "runtime": runtime,
        "environment": environment,
        "provider_source": provider_source,
    }


def _model_contract(identity: Mapping[str, Any]) -> dict[str, Any]:
    contract = identity.get("contract")
    if not isinstance(contract, dict):
        raise KimiProviderSplitError("model_contract_invalid")
    expected_context = {
        "max_input_tokens": MAX_SEQUENCE_TOKENS,
        "max_output_tokens": MAX_SEQUENCE_TOKENS,
        "max_total_tokens": MAX_SEQUENCE_TOKENS,
    }
    if (
        contract.get("model") != "Kimi-K3"
        or contract.get("pass_at_1") is not True
        or contract.get("num_rollouts") != 1
        or contract.get("reasoning_effort") != "max"
        or contract.get("thinking") != {"enable_thinking": True, "preserve_thinking": True}
        or contract.get("context_tokens") != expected_context
        or contract.get("sampling_max_tokens") != SAMPLING_MAX_TOKENS
        or contract.get("capture_model_io") is not True
        or contract.get("outbound_body_denylist") != EXPECTED_DENYLIST
        or contract.get("retain_traces") is not False
    ):
        raise KimiProviderSplitError("model_contract_invalid")
    return {
        key: contract[key]
        for key in (
            "model",
            "pass_at_1",
            "num_rollouts",
            "reasoning_effort",
            "thinking",
            "context_tokens",
            "sampling_max_tokens",
            "capture_model_io",
            "outbound_body_denylist",
            "retain_traces",
        )
    }


def _deployment_spec_sha256(identity: Mapping[str, Any]) -> str:
    deployment = identity.get("deployment")
    if not isinstance(deployment, dict):
        raise KimiProviderSplitError("deployment_binding_invalid")
    digest = deployment.get("spec_sha256")
    if digest is None and isinstance(deployment.get("spec"), dict):
        digest = deployment["spec"].get("sha256")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise KimiProviderSplitError("deployment_binding_invalid")
    return digest


def _provider_neutral_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return all config semantics except the reviewed provider/partition deltas."""

    try:
        value = json.loads(canonical_json(config))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KimiProviderSplitError("run_config_invalid") from error
    if not isinstance(value, dict):
        raise KimiProviderSplitError("run_config_invalid")
    for key in ("num_tasks", "max_concurrent", "multiplex", "output_dir"):
        value.pop(key, None)
    client = value.get("client")
    taskset = value.get("taskset")
    harness = value.get("harness")
    if not all(isinstance(item, dict) for item in (client, taskset, harness)):
        raise KimiProviderSplitError("run_config_invalid")
    assert isinstance(client, dict) and isinstance(taskset, dict) and isinstance(harness, dict)
    for key in ("base_url", "max_connections", "max_keepalive_connections"):
        client.pop(key, None)
    for key in (
        "task_file",
        "task_file_sha256",
        "resource_multiplier",
        "image_manifest",
        "image_prefix",
        "image_tag",
    ):
        taskset.pop(key, None)
    harness.pop("runtime", None)
    return value


def _deployment_contract(
    identity: Mapping[str, Any],
    held: _HeldArtifactSet | None = None,
) -> dict[str, Any]:
    deployment = identity.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("kind") != "direct_kimi":
        raise KimiProviderSplitError("deployment_binding_invalid")
    worker = deployment.get("worker_manifest")
    router = deployment.get("router")
    smoke = deployment.get("smoke_checkpoint")
    if (
        not isinstance(worker, dict)
        or set(worker) != {"path", "sha256"}
        or not isinstance(worker.get("path"), str)
        or not Path(worker["path"]).is_absolute()
        or SHA256_RE.fullmatch(str(worker.get("sha256", ""))) is None
        or not isinstance(router, dict)
        or not isinstance(smoke, dict)
        or SHA256_RE.fullmatch(str(smoke.get("sha256", ""))) is None
        or SHA256_RE.fullmatch(str(deployment.get("endpoint_bundle_sha256", ""))) is None
    ):
        raise KimiProviderSplitError("deployment_binding_invalid")
    manifest_body, manifest_artifact = _read_regular_evidence(
        Path(worker["path"]),
        code="deployment_worker_manifest_invalid",
        maximum_bytes=4 * 1024 * 1024,
        private=True,
        held=held,
    )
    if manifest_artifact["sha256"] != worker["sha256"]:
        raise KimiProviderSplitError("deployment_worker_manifest_invalid")
    manifest = _json_object(
        manifest_body,
        code="deployment_worker_manifest_invalid",
        canonical=True,
    )
    try:
        generation = worker_generation_contract(manifest, revalidate_live_source=False)
    except (DirectKimiWorkerError, OSError, ValueError) as error:
        raise KimiProviderSplitError("deployment_worker_manifest_invalid") from error
    manifest_router = manifest["router"]
    expected_router = {
        "implementation": manifest_router.get("implementation"),
        "implementation_sha256": manifest_router.get("implementation_sha256"),
        "policy": manifest_router.get("policy"),
        "request_id_headers": manifest_router.get("request_id_headers"),
        "provider_concurrency": manifest_router.get("max_concurrent_requests"),
        "request_timeout_seconds": manifest_router.get("request_timeout_seconds"),
        "retries": manifest_router.get("retries"),
        "worker_count": len(manifest["workers"]),
    }
    if manifest_router.get("capacity_profile") in {C23_CAPACITY_PROFILE, C64_W2_CAPACITY_PROFILE}:
        expected_router.update(
            {
                "capacity_profile": manifest_router["capacity_profile"],
                "endpoint_identifier": manifest_router.get("endpoint_identifier"),
            }
        )
        if manifest_router["capacity_profile"] == C64_W2_CAPACITY_PROFILE:
            expected_router["per_worker_capacity"] = manifest_router.get("per_worker_capacity")
    elif "capacity_profile" in manifest_router:
        raise KimiProviderSplitError("deployment_worker_manifest_invalid")
    if (
        deployment.get("spec_sha256") != manifest.get("source_spec_sha256")
        or deployment.get("endpoint_bundle_sha256") != manifest.get("endpoint_bundle_sha256")
        or deployment.get("base_url") != f"http://127.0.0.1:{manifest_router.get('port')}/v1"
        or router != expected_router
    ):
        raise KimiProviderSplitError("deployment_worker_manifest_invalid")
    return {
        "kind": "direct_kimi",
        "worker_generation_sha256": sha256_bytes(canonical_json(generation)),
        "spec_sha256": _deployment_spec_sha256(identity),
        "endpoint_bundle_sha256": deployment["endpoint_bundle_sha256"],
        "router": json.loads(canonical_json(router)),
        "smoke_checkpoint_sha256": smoke["sha256"],
    }


def _shared_contract(
    identity: Mapping[str, Any],
    config: Mapping[str, Any],
    held: _HeldArtifactSet | None = None,
) -> dict[str, Any]:
    source = identity.get("source")
    if not isinstance(source, dict):
        raise KimiProviderSplitError("run_identity_invalid")
    revisions = {
        key: source.get(key)
        for key in (
            "prime_rl_commit",
            "prime_rl_tree_sha256",
            "verifiers_commit",
            "verifiers_tree_sha256",
            "renderers_commit",
            "renderers_tree_sha256",
        )
    }
    if any(
        (SHA256_RE if key.endswith("_sha256") else REVISION_RE).fullmatch(str(value or "")) is None
        for key, value in revisions.items()
    ):
        raise KimiProviderSplitError("source_closure_invalid")
    return {
        "model_contract": _model_contract(identity),
        "deployment_contract": _deployment_contract(identity, held),
        "provider_neutral_config_sha256": sha256_bytes(canonical_json(_provider_neutral_config(config))),
        "source_revisions": revisions,
    }


def _validate_run_identity(
    run_dir: Path,
    identity_body: bytes,
    invocation_body: bytes,
    provenance_body: bytes,
    *,
    role: Literal["legacy_sandoq", "large_provider"],
    expected_members: Sequence[str],
    selector_sha256: str,
    manifest_value: Mapping[str, Any],
    held: _HeldArtifactSet | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, str, str]:
    try:
        envelope = load_eval_run_identity_bytes(
            identity_body,
            run_dir=run_dir,
            verify_references=True,
            verify_saved_provenance=False,
        )
    except Exception as error:
        raise KimiProviderSplitError("run_identity_invalid") from error
    identity = envelope.get("identity")
    if not isinstance(identity, dict) or identity.get("role") != "kimi-direct-tb4":
        raise KimiProviderSplitError("run_identity_invalid")
    task_file = identity.get("inputs", {}).get("task_file")
    image_manifest = identity.get("inputs", {}).get("image_manifest")
    dataset = identity.get("dataset")
    if (
        not isinstance(task_file, dict)
        or task_file.get("sha256") != selector_sha256
        or task_file.get("count") != len(expected_members)
        or not isinstance(image_manifest, dict)
        or image_manifest.get("sha256") != manifest_value["source"]["image_manifest_sha256"]
        or not isinstance(dataset, dict)
        or dataset.get("content_sha256") != manifest_value["source"]["dataset_content_sha256"]
    ):
        raise KimiProviderSplitError("run_input_binding_invalid")
    task_path = Path(str(task_file.get("path", "")))
    task_body = read_regular(
        task_path,
        code="run_task_selector_invalid",
        maximum_bytes=1 << 20,
        private=True,
        held=held,
    )
    if sha256_bytes(task_body) != selector_sha256 or task_body != _selector_payload(expected_members):
        raise KimiProviderSplitError("run_task_selector_invalid")
    config = _resolved_config(identity, held)
    multiplier = _config_resource_multiplier(config)
    taskset = config.get("taskset")
    if not isinstance(taskset, dict) or taskset.get("enable_compose") is not True:
        raise KimiProviderSplitError("compose_contract_invalid")
    if multiplier != (1.0 if role == "legacy_sandoq" else float(LARGE_RESOURCE_MULTIPLIER)):
        raise KimiProviderSplitError("resource_multiplier_invalid")
    provider = _provider_name(identity)
    if role == "legacy_sandoq" and provider != "sandoq":
        raise KimiProviderSplitError("provider_mismatch")
    execution = identity.get("execution")
    if not isinstance(execution, dict) or execution.get("cleanup_must_succeed") is not True:
        raise KimiProviderSplitError("cleanup_contract_invalid")
    deployment_router = identity.get("deployment", {}).get("router")
    if provider == "sandoq":
        expected_concurrency = (
            deployment_router.get("provider_concurrency") if isinstance(deployment_router, dict) else None
        )
        if expected_concurrency not in {23, 24}:
            raise KimiProviderSplitError("execution_contract_invalid")
    else:
        expected_concurrency = 4
    if any(
        execution.get(key) != expected_concurrency
        for key in ("rollout_concurrency", "multiplex", "http_max_connections", "http_max_keepalive_connections")
    ):
        raise KimiProviderSplitError("execution_contract_invalid")
    _environment_identity(identity)
    shared = _shared_contract(identity, config, held)
    digest = envelope.get("eval_run_identity_sha256")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise KimiProviderSplitError("run_identity_invalid")
    invocation_sha256, slurm_job_id = _run_invocation_binding(
        invocation_body,
        provenance_body,
        digest,
    )
    return identity, shared, digest, invocation_sha256, slurm_job_id


def _run_invocation_binding(
    invocation_body: bytes,
    provenance_body: bytes,
    identity_sha256: str,
) -> tuple[str, str]:
    try:
        lines = provenance_body.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise KimiProviderSplitError("run_provenance_invalid") from error
    records: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or not value or key in records:
            raise KimiProviderSplitError("run_provenance_invalid")
        records[key] = value
    host = records.get("host")
    job_id = records.get("slurm_job_id")
    if (
        records.get("eval_run_identity_sha256") != identity_sha256
        or records.get("eval_run_role") != "kimi-direct-tb4"
        or not isinstance(host, str)
        or not host.strip()
        or re.fullmatch(r"[1-9][0-9]*", str(job_id or "")) is None
    ):
        raise KimiProviderSplitError("run_provenance_invalid")
    try:
        invocations = [json.loads(line) for line in invocation_body.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KimiProviderSplitError("run_invocation_invalid") from error
    if len(invocations) != 1:
        raise KimiProviderSplitError("run_invocation_invalid")
    invocation = invocations[0]
    if (
        not isinstance(invocation, dict)
        or set(invocation)
        != {
            "schema_version",
            "eval_run_identity_sha256",
            "role",
            "resume",
            "host",
            "slurm_job_id",
        }
        or invocation.get("schema_version") != 1
        or invocation.get("eval_run_identity_sha256") != identity_sha256
        or invocation.get("role") != "kimi-direct-tb4"
        or invocation.get("resume") is not False
        or invocation.get("host") != host
        or invocation.get("slurm_job_id") != job_id
    ):
        raise KimiProviderSplitError("run_invocation_invalid")
    binding = {
        "schema_version": 1,
        "kind": "kimi-tb4-eval-invocation",
        "eval_run_identity_sha256": identity_sha256,
        "host": host,
        "slurm_job_id": job_id,
    }
    return sha256_bytes(canonical_json(binding)), str(job_id)


def _validate_direct_router_receipt(
    path: Path,
    identity: Mapping[str, Any],
    *,
    minimum_chat_requests: int,
    identity_sha256: str,
    invocation_identity_sha256: str,
    held: _HeldArtifactSet | None = None,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    body, artifact = _read_regular_evidence(
        path,
        code="router_receipt_invalid",
        private=True,
        held=held,
    )
    marker_path = path.with_name(f".{path.name}.complete")
    marker_body, marker_artifact = _read_regular_evidence(
        marker_path,
        code="router_receipt_commit_invalid",
        maximum_bytes=64 * 1024,
        private=True,
        held=held,
    )
    expected_marker = canonical_json(
        {
            "schema_version": 1,
            "kind": "direct-kimi-file-publication",
            "files": {
                path.name: {"bytes": len(body), "sha256": sha256_bytes(body)},
            },
        }
    )
    if marker_body != expected_marker:
        raise KimiProviderSplitError("router_receipt_commit_invalid")
    value = _json_object(body, code="router_receipt_invalid")
    deployment = identity.get("deployment")
    if not isinstance(deployment, dict) or deployment.get("kind") != "direct_kimi":
        raise KimiProviderSplitError("router_receipt_unexpected")
    router = deployment.get("router")
    worker = deployment.get("worker_manifest")
    if not isinstance(router, dict) or not isinstance(worker, dict):
        raise KimiProviderSplitError("router_receipt_invalid")
    c23_profile = router.get("capacity_profile") == C23_CAPACITY_PROFILE
    w2_profile = router.get("capacity_profile") == C64_W2_CAPACITY_PROFILE
    profiled_capacity = c23_profile or w2_profile
    worker_count = 23 if c23_profile else 24
    zero_worker_counts_sha256 = sha256_bytes((json.dumps([0] * worker_count, separators=(",", ":")) + "\n").encode())
    expected = {
        "schema_version": 5 if w2_profile else 4 if c23_profile else 2,
        "kind": "direct-kimi-router-final",
        "state": "passed",
        "eval_run_identity_sha256": identity_sha256,
        "invocation_identity_sha256": invocation_identity_sha256,
        "worker_manifest_sha256": worker.get("sha256"),
        "endpoint_bundle_sha256": deployment.get("endpoint_bundle_sha256"),
        "active_workers": router.get("worker_count"),
        "implementation": router.get("implementation"),
        "implementation_sha256": router.get("implementation_sha256"),
        "policy": router.get("policy"),
        "request_id_headers": router.get("request_id_headers"),
        "request_timeout_seconds": router.get("request_timeout_seconds"),
        "retries": router.get("retries"),
        "source_generation_revalidated": True,
    }
    dynamic = {"max_active_requests", "total_requests", "chat_requests", "worker_request_counts_sha256"}
    digests = {"worker_request_counts_sha256"}
    if profiled_capacity:
        expected.update(
            {
                "capacity_profile": C64_W2_CAPACITY_PROFILE if w2_profile else C23_CAPACITY_PROFILE,
                "endpoint_identifier": router.get("endpoint_identifier"),
                "configured_capacity": router.get("provider_concurrency"),
                "configured_per_worker_capacity": 2 if w2_profile else 1,
                "active_forwarded_requests": 0,
                "worker_active_request_counts_sha256": zero_worker_counts_sha256,
                "active_worker_waiters": 0,
                "worker_waiting_request_counts_sha256": zero_worker_counts_sha256,
            }
        )
        dynamic.update(
            {
                "worker_session_counts_sha256",
                "max_active_chat_requests",
                "capacity_rejections",
                "queue_overflow_rejections",
                "route_tracking_overflows",
                "cross_route_anomalies",
                "tracked_sessions",
            }
        )
        digests.add("worker_session_counts_sha256")
    if w2_profile:
        expected.update(
            {
                "worker_queue_timeouts": 0,
                "upstream_http_429": 0,
                "upstream_http_5xx": 0,
            }
        )
        dynamic.update({"max_active_forwarded_requests", "worker_max_active_request_counts_sha256"})
        digests.add("worker_max_active_request_counts_sha256")
    if (
        set(value) != {*expected, *dynamic}
        or any(value.get(key) != item for key, item in expected.items())
        or (
            profiled_capacity
            and any(
                not _nonnegative_integer(value.get(key))
                for key in (
                    "configured_per_worker_capacity",
                    "active_forwarded_requests",
                    "active_worker_waiters",
                )
            )
        )
        or not all(
            _nonnegative_integer(value.get(key)) for key in ("max_active_requests", "total_requests", "chat_requests")
        )
        or not 1
        <= value["max_active_requests"]
        <= (64 if w2_profile else int(identity["execution"]["rollout_concurrency"]))
        or value["total_requests"] < value["chat_requests"]
        or value["chat_requests"] < minimum_chat_requests
        or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in digests)
        or (
            profiled_capacity
            and (
                not all(
                    _nonnegative_integer(value.get(key))
                    for key in (
                        "max_active_chat_requests",
                        "capacity_rejections",
                        "queue_overflow_rejections",
                        "route_tracking_overflows",
                        "cross_route_anomalies",
                        "tracked_sessions",
                    )
                )
                or value["max_active_chat_requests"] > router["provider_concurrency"]
                or value["max_active_chat_requests"] > value["max_active_requests"]
                or value["capacity_rejections"] != 0
                or value["queue_overflow_rejections"] != 0
                or value["route_tracking_overflows"] != 0
                or value["cross_route_anomalies"] != 0
                or value["tracked_sessions"] > value["chat_requests"]
            )
        )
        or (
            w2_profile
            and (
                not 1 <= value["max_active_forwarded_requests"] <= 48
                or value["max_active_forwarded_requests"] > value["max_active_requests"]
            )
        )
    ):
        raise KimiProviderSplitError("router_receipt_invalid")
    return body, artifact, marker_artifact


def _score(row: Mapping[str, Any]) -> int:
    rewards = row.get("rewards")
    if not isinstance(rewards, dict) or set(rewards) != {"solved"}:
        raise KimiProviderSplitError("provider_score_invalid")
    value = rewards["solved"]
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value not in {0, 1}
    ):
        raise KimiProviderSplitError("provider_score_invalid")
    return int(value)


def _audit_cpu_results(
    results: Path,
    expected_members: Sequence[str],
    verifier_modes: Mapping[str, str],
    held: _HeldArtifactSet | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    body, artifact = _read_regular_evidence(
        results,
        code="provider_results_invalid",
        maximum_bytes=512 * 1024 * 1024,
        private=True,
        held=held,
    )
    try:
        rows = [json.loads(line) for line in body.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KimiProviderSplitError("provider_results_invalid") from error
    if any(not isinstance(row, dict) for row in rows):
        raise KimiProviderSplitError("provider_results_invalid")
    expected = set(expected_members)
    by_task: dict[str, dict[str, Any]] = {}
    trace_ids: set[str] = set()
    model_io_turns = 0
    sampled_tokens = 0
    passes = 0
    for row in rows:
        try:
            task_id = _task_slug(row)
            problems = _audit_trace(
                row,
                require_reasoning=True,
                max_sequence_tokens=MAX_SEQUENCE_TOKENS,
                require_token_data=False,
                require_logprobs=False,
                require_model_io=True,
                model_io_contract=KIMI_K3_MAX_MODEL_IO_CONTRACT,
                require_request_graph_match=True,
                require_exact_provider_json=True,
            )
        except Exception as error:
            raise KimiProviderSplitError("provider_trace_audit_failed") from error
        trace_id = row.get("id")
        info = row.get("info")
        verifier = info.get("terminal_bench_verifier") if isinstance(info, dict) else None
        mode = verifier.get("mode") if isinstance(verifier, dict) else None
        if (
            task_id not in expected
            or task_id in by_task
            or not isinstance(trace_id, str)
            or not trace_id
            or trace_id in trace_ids
            or problems
            or row.get("is_completed") is not True
            or not isinstance(row.get("stop_condition"), str)
            or not row["stop_condition"].strip()
            or row["stop_condition"] == "error"
            or mode != verifier_modes[task_id]
        ):
            raise KimiProviderSplitError("provider_trace_audit_failed")
        passes += _score(row)
        by_task[task_id] = row
        trace_ids.add(trace_id)
        nodes = row.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, dict) or node.get("sampled") is not True:
                    continue
                if node.get("model_io") is not None:
                    model_io_turns += 1
                usage = node.get("usage")
                completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
                if (
                    isinstance(completion_tokens, int)
                    and not isinstance(completion_tokens, bool)
                    and completion_tokens >= 0
                ):
                    sampled_tokens += completion_tokens
    if (
        len(rows) != len(expected_members)
        or set(by_task) != expected
        or model_io_turns < len(rows)
        or sampled_tokens < 1
    ):
        raise KimiProviderSplitError("provider_trace_audit_failed")
    return (
        {
            "traces": len(rows),
            "tasks": len(by_task),
            "passes": passes,
            "failures": len(rows) - passes,
            "model_io_turns": model_io_turns,
            "sampled_tokens": sampled_tokens,
            "trace_failures": 0,
        },
        by_task,
        artifact,
    )


def _validate_job_bound_jsonl(body: bytes, slurm_job_id: str, *, wal: bool) -> None:
    if not body or not body.endswith(b"\n") or b"\r" in body:
        raise KimiProviderSplitError("sandoq_cleanup_invalid")
    observed = 0
    for line in body.splitlines():
        if not line.strip():
            continue
        value = _json_object(line, code="sandoq_cleanup_invalid")
        if (
            value.get("schema_version") != 2
            or (not wal and value.get("record_type") != "pool_event")
            or value.get("slurm_job_id") != slurm_job_id
        ):
            raise KimiProviderSplitError("sandoq_cleanup_run_mismatch")
        observed += 1
    if observed < 1:
        raise KimiProviderSplitError("sandoq_cleanup_invalid")


def _validate_sandoq_cleanup(
    path: Path,
    run_dir: Path,
    identity: Mapping[str, Any],
    identity_sha256: str,
    invocation_identity_sha256: str,
    slurm_job_id: str,
    expected_count: int,
    expected_concurrency: int,
    held: _HeldArtifactSet | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    body, cleanup_artifact = _read_regular_evidence(
        path,
        code="sandoq_cleanup_invalid",
        private=True,
        held=held,
    )
    value = _json_object(body, code="sandoq_cleanup_invalid")
    count_keys = {
        "recorded_outer_sessions",
        "verified_http_404",
        "already_absent",
        "deleted_and_verified",
        "assignments_acquired",
        "assignment_release_rows",
        "assignment_cancellation_rows",
        "cleanup_gateway_retry_count",
        "assignments_cleanup_verified",
        "assignment_event_order_high_water",
        "assignment_measured_high_water",
        "outer_sessions_created",
        "outer_sessions_deleted",
        "outer_session_high_water",
        "pool_drain_deleted",
        "gateway_close_warnings",
        "recovered_poisoned_assignments",
        "failures",
    }
    digest_keys = {"raw_audit_sha256", "pool_event_log_sha256", "pool_wal_sha256", "pool_drain_sha256"}
    if (
        set(value) != {"schema_version", "kind", "state", *count_keys, *digest_keys}
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-pool-cleanup"
        or value.get("state") != "passed"
        or any(not _nonnegative_integer(value.get(key)) for key in count_keys)
        or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in digest_keys)
        or value.get("failures") != 0
        or value["recorded_outer_sessions"] < 1
        or value["recorded_outer_sessions"] != value["verified_http_404"]
        or value["recorded_outer_sessions"] != value["outer_sessions_created"]
        or value["recorded_outer_sessions"] != value["outer_sessions_deleted"]
        or value["assignment_measured_high_water"] != expected_concurrency
        or not value["assignment_measured_high_water"] <= value["outer_session_high_water"] <= expected_concurrency
        or value["assignments_acquired"] < expected_count
        or value["assignments_cleanup_verified"] != value["assignments_acquired"]
        or value["assignment_release_rows"] + value["assignment_cancellation_rows"] != value["assignments_acquired"]
    ):
        raise KimiProviderSplitError("sandoq_cleanup_invalid")
    execution = identity.get("execution")
    environment = execution.get("sandoq_environment") if isinstance(execution, dict) else None
    if not isinstance(environment, dict):
        raise KimiProviderSplitError("sandoq_cleanup_invalid")
    raw_path = run_dir / "pool_cleanup_audit.json"
    event_path = run_dir / "pool_events.jsonl"
    wal_path = run_dir / "control" / "sandoq-pool.wal.jsonl"
    if (
        _absolute_path(Path(str(environment.get("pool_event_log", "")))) != _absolute_path(event_path)
        or _absolute_path(Path(str(environment.get("pool_wal", "")))) != _absolute_path(wal_path)
        or _absolute_path(path) != _absolute_path(run_dir / "sandoq_cleanup_audit.json")
    ):
        raise KimiProviderSplitError("sandoq_cleanup_run_mismatch")
    raw_body, raw_artifact = _read_regular_evidence(
        raw_path,
        code="sandoq_cleanup_invalid",
        maximum_bytes=32 * 1024 * 1024,
        private=True,
        held=held,
    )
    event_body, event_artifact = _read_regular_evidence(
        event_path,
        code="sandoq_cleanup_invalid",
        maximum_bytes=128 * 1024 * 1024,
        private=True,
        held=held,
    )
    wal_body, wal_artifact = _read_regular_evidence(
        wal_path,
        code="sandoq_cleanup_invalid",
        maximum_bytes=128 * 1024 * 1024,
        private=True,
        held=held,
    )
    _json_object(raw_body, code="sandoq_cleanup_invalid")
    _validate_job_bound_jsonl(event_body, slurm_job_id, wal=False)
    _validate_job_bound_jsonl(wal_body, slurm_job_id, wal=True)
    if (
        value["raw_audit_sha256"] != raw_artifact["sha256"]
        or value["pool_event_log_sha256"] != event_artifact["sha256"]
        or value["pool_wal_sha256"] != wal_artifact["sha256"]
    ):
        raise KimiProviderSplitError("sandoq_cleanup_run_mismatch")
    return (
        {
            "kind": "sandoq-pool-cleanup",
            "state": "passed",
            "eval_run_identity_sha256": identity_sha256,
            "invocation_identity_sha256": invocation_identity_sha256,
            "recorded_outer_sessions": value["recorded_outer_sessions"],
            "verified_http_404": value["verified_http_404"],
            "assignment_measured_high_water": value["assignment_measured_high_water"],
            "failures": 0,
        },
        {
            "cleanup_receipt": cleanup_artifact,
            "cleanup_raw_audit": raw_artifact,
            "cleanup_event_log": event_artifact,
            "cleanup_wal": wal_artifact,
        },
    )


_VMVM_LIFECYCLE_KEYS = {"schema_version", "kind", "runtime_instance_nonce", "eval_run_identity_sha256"}
_VMVM_CLEANUP_KEYS = {
    "schema_version",
    "kind",
    "runtime_instance_nonce",
    "cleanup_pass",
    "state",
    "attempted",
    "failures",
    "host_tunnel_count",
    "host_tunnels_closed",
    "network_firewall_present",
    "network_firewall_cleanup_completed",
    "session_present",
    "session_stop_completed",
    "fifo_present",
    "fifo_cleanup_completed",
    "compose_present",
    "compose_teardown_completed",
    "compose_directory_cleanup_completed",
    "container_present",
    "container_teardown_completed",
    "internal_network_present",
    "internal_network_teardown_completed",
    "ssh_master_stop_completed",
    "lease_process_was_alive",
    "lease_sigterm_sent",
    "lease_wait_completed",
    "lease_exit_code",
    "lease_sigkill_used",
    "release_on_exit_completed",
    "remote_deletion_verified",
    "eval_run_identity_sha256",
}


def _private_jsonl(
    path: Path,
    run_dir: Path,
    filename: str,
    held: _HeldArtifactSet | None = None,
) -> tuple[list[dict[str, Any]], bytes, dict[str, Any]]:
    expected = run_dir / "control" / filename
    if _absolute_path(path) != _absolute_path(expected):
        raise KimiProviderSplitError("vmvm_cleanup_invalid")
    body, artifact = _read_regular_evidence(
        path,
        code="vmvm_cleanup_invalid",
        maximum_bytes=16 * 1024 * 1024,
        private=True,
        held=held,
    )
    if not body or not body.endswith(b"\n") or b"\r" in body:
        raise KimiProviderSplitError("vmvm_cleanup_invalid")
    values: list[dict[str, Any]] = []
    for line in body.splitlines():
        value = _json_object(line, code="vmvm_cleanup_invalid")
        values.append(value)
    return values, body, artifact


def _validate_vmvm_cleanup(
    run_dir: Path,
    identity_sha256: str,
    invocation_identity_sha256: str,
    expected_runtime_count: int,
    held: _HeldArtifactSet | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], frozenset[str]]:
    lifecycle_path = run_dir / "control" / "vmvm_runtime_lifecycle.jsonl"
    cleanup_path = run_dir / "control" / "vmvm_cleanup_receipts.jsonl"
    lifecycle, lifecycle_body, lifecycle_artifact = _private_jsonl(
        lifecycle_path,
        run_dir,
        lifecycle_path.name,
        held,
    )
    cleanup, cleanup_body, cleanup_artifact = _private_jsonl(
        cleanup_path,
        run_dir,
        cleanup_path.name,
        held,
    )
    nonces: list[str] = []
    for value in lifecycle:
        nonce = value.get("runtime_instance_nonce")
        if (
            set(value) != _VMVM_LIFECYCLE_KEYS
            or value.get("schema_version") != 1
            or value.get("kind") != "vmvm-runtime-created"
            or re.fullmatch(r"[0-9a-f]{32}", str(nonce or "")) is None
            or value.get("eval_run_identity_sha256") != identity_sha256
        ):
            raise KimiProviderSplitError("vmvm_cleanup_invalid")
        nonces.append(str(nonce))
    if len(nonces) != expected_runtime_count or len(nonces) != len(set(nonces)):
        raise KimiProviderSplitError("vmvm_cleanup_incomplete")
    by_runtime: dict[str, list[dict[str, Any]]] = {}
    boolean_keys = {
        "network_firewall_present",
        "network_firewall_cleanup_completed",
        "session_present",
        "session_stop_completed",
        "fifo_present",
        "fifo_cleanup_completed",
        "compose_present",
        "compose_teardown_completed",
        "compose_directory_cleanup_completed",
        "container_present",
        "container_teardown_completed",
        "internal_network_present",
        "internal_network_teardown_completed",
        "ssh_master_stop_completed",
        "lease_process_was_alive",
        "lease_sigterm_sent",
        "lease_wait_completed",
        "lease_sigkill_used",
        "release_on_exit_completed",
        "remote_deletion_verified",
    }
    for value in cleanup:
        nonce = value.get("runtime_instance_nonce")
        if (
            set(value) != _VMVM_CLEANUP_KEYS
            or value.get("schema_version") != 1
            or value.get("kind") != "vmvm-runtime-cleanup"
            or nonce not in set(nonces)
            or not _positive_integer(value.get("cleanup_pass"))
            or value.get("state") != "passed"
            or value.get("eval_run_identity_sha256") != identity_sha256
            or any(not isinstance(value.get(key), bool) for key in boolean_keys)
            or type(value.get("attempted")) is not int
            or value.get("attempted") != 1
            or type(value.get("failures")) is not int
            or value.get("failures") != 0
            or type(value.get("host_tunnel_count")) is not int
            or type(value.get("host_tunnels_closed")) is not int
            or value.get("host_tunnel_count", -1) < 0
            or value.get("host_tunnel_count") != value.get("host_tunnels_closed")
            or value.get("network_firewall_cleanup_completed") is not True
            or value.get("session_stop_completed") is not True
            or value.get("fifo_cleanup_completed") is not True
            or value.get("compose_teardown_completed") is not True
            or value.get("compose_directory_cleanup_completed") is not True
            or value.get("container_teardown_completed") is not True
            or value.get("internal_network_teardown_completed") is not True
            or value.get("ssh_master_stop_completed") is not True
            or value.get("lease_process_was_alive") is not True
            or value.get("lease_sigterm_sent") is not True
            or value.get("lease_wait_completed") is not True
            or type(value.get("lease_exit_code")) is not int
            or value.get("lease_exit_code") != 0
            or value.get("lease_sigkill_used") is not False
            or value.get("release_on_exit_completed") is not True
            or value.get("remote_deletion_verified") is not False
        ):
            raise KimiProviderSplitError("vmvm_cleanup_invalid")
        by_runtime.setdefault(str(nonce), []).append(value)
    if set(by_runtime) != set(nonces) or any(
        [item["cleanup_pass"] for item in values] != list(range(1, len(values) + 1)) for values in by_runtime.values()
    ):
        raise KimiProviderSplitError("vmvm_cleanup_incomplete")
    if lifecycle_artifact["sha256"] != sha256_bytes(lifecycle_body) or cleanup_artifact["sha256"] != sha256_bytes(
        cleanup_body
    ):
        raise KimiProviderSplitError("vmvm_cleanup_changed")
    return (
        {
            "kind": "vmvm-runtime-cleanup",
            "state": "passed",
            "eval_run_identity_sha256": identity_sha256,
            "invocation_identity_sha256": invocation_identity_sha256,
            "runtime_instances": len(by_runtime),
            "cleanup_passes": len(cleanup),
            "release_on_exit_completed": len(by_runtime),
            "failures": 0,
        },
        {
            "lifecycle_receipt": lifecycle_artifact,
            "cleanup_receipt": cleanup_artifact,
        },
        frozenset(nonces),
    )


def _capacity_payload(
    receipt: Path,
    receipt_sha256: str,
    public_key: Path,
    public_key_sha256: str,
    *,
    manifest_sha256: str,
    selector_sha256: str,
    identity: Mapping[str, Any],
    identity_sha256: str,
    invocation_identity_sha256: str,
    runtime_instance_nonces: frozenset[str],
    held: _HeldArtifactSet | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    receipt_body, receipt_artifact = _read_regular_evidence(
        receipt,
        code="capacity_receipt_invalid",
        private=True,
        held=held,
    )
    receipt_commit = receipt.with_name(f".{receipt.name}{FILE_COMMIT_SUFFIX}")
    commit_body, commit_artifact = _read_regular_evidence(
        receipt_commit,
        code="capacity_commit_invalid",
        maximum_bytes=64 * 1024,
        private=True,
        held=held,
    )
    expected_commit = canonical_json(
        {
            "schema_version": 1,
            "kind": "private-file-complete",
            "state": "complete",
            "file": {
                "name": receipt.name,
                "bytes": len(receipt_body),
                "sha256": sha256_bytes(receipt_body),
            },
        }
    )
    key_body, key_artifact = _read_regular_evidence(
        public_key,
        code="capacity_public_key_invalid",
        maximum_bytes=64 * 1024,
        held=held,
    )
    if (
        commit_body != expected_commit
        or SHA256_RE.fullmatch(receipt_sha256 or "") is None
        or sha256_bytes(receipt_body) != receipt_sha256
        or SHA256_RE.fullmatch(public_key_sha256 or "") is None
        or sha256_bytes(key_body) != public_key_sha256
        or public_key_sha256 != PINNED_CAPACITY_PUBLIC_KEY_SHA256
    ):
        raise KimiProviderSplitError("capacity_binding_invalid")
    envelope = _json_object(receipt_body, code="capacity_receipt_invalid", canonical=True)
    if set(envelope) != {"schema_version", "kind", "algorithm", "key_sha256", "payload", "signature"}:
        raise KimiProviderSplitError("capacity_receipt_invalid")
    payload = envelope.get("payload")
    signature_text = envelope.get("signature")
    if (
        envelope.get("schema_version") != 2
        or envelope.get("kind") != CAPACITY_KIND
        or envelope.get("algorithm") != "ed25519"
        or envelope.get("key_sha256") != public_key_sha256
        or not isinstance(payload, dict)
        or not isinstance(signature_text, str)
    ):
        raise KimiProviderSplitError("capacity_receipt_invalid")
    try:
        signature = base64.b64decode(signature_text, validate=True)
        key = serialization.load_pem_public_key(key_body)
        if not isinstance(key, Ed25519PublicKey) or len(signature) != 64:
            raise KimiProviderSplitError("capacity_signature_invalid")
        key.verify(signature, canonical_json(payload))
    except (ValueError, TypeError, binascii.Error, InvalidSignature) as error:
        raise KimiProviderSplitError("capacity_signature_invalid") from error
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "issued_at",
        "expires_at",
        "valid_for_seconds",
        "nonce",
        "runtime_instance_nonce",
        "provider",
        "environment_identity",
        "eval_run_identity_sha256",
        "invocation_identity_sha256",
        "manifest_sha256",
        "selector_sha256",
        "resource_multiplier",
        "measurement_method",
        "measured_capacity",
    }
    capacity = payload.get("measured_capacity")
    provider = _provider_name(identity)
    issued_at = _parse_utc_timestamp(payload.get("issued_at"))
    expires_at = _parse_utc_timestamp(payload.get("expires_at"))
    now = datetime.now(timezone.utc)
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != 2
        or payload.get("kind") != CAPACITY_KIND
        or payload.get("state") != "passed"
        or issued_at is None
        or expires_at is None
        or issued_at > now + CAPACITY_CLOCK_SKEW
        or expires_at <= issued_at
        or expires_at - issued_at != CAPACITY_VALIDITY
        or payload.get("valid_for_seconds") != CAPACITY_VALIDITY_SECONDS
        or re.fullmatch(r"[0-9a-f]{32}", str(payload.get("nonce", ""))) is None
        or payload.get("runtime_instance_nonce") not in runtime_instance_nonces
        or payload.get("provider") != provider
        or provider != "vmvm"
        or payload.get("environment_identity") != _environment_identity(identity)
        or payload.get("eval_run_identity_sha256") != identity_sha256
        or payload.get("invocation_identity_sha256") != invocation_identity_sha256
        or payload.get("manifest_sha256") != manifest_sha256
        or payload.get("selector_sha256") != selector_sha256
        or payload.get("resource_multiplier") != LARGE_RESOURCE_MULTIPLIER
        or payload.get("measurement_method") != "in-runtime-cgroup-and-statvfs-v1"
        or not isinstance(capacity, dict)
        or set(capacity) != {"actual_cpu_count", "outer_memory_bytes", "disk_available_bytes"}
        or not all(_positive_integer(capacity.get(key)) for key in capacity)
        or capacity["actual_cpu_count"] < LARGE_MIN_CPU_COUNT
        or capacity["outer_memory_bytes"] < LARGE_MIN_OUTER_MEMORY_BYTES
        or capacity["disk_available_bytes"] < LARGE_MIN_DISK_AVAILABLE_BYTES
    ):
        raise KimiProviderSplitError("capacity_receipt_invalid")
    if receipt_artifact["sha256"] != receipt_sha256 or key_artifact["sha256"] != public_key_sha256:
        raise KimiProviderSplitError("capacity_evidence_changed")
    return payload, {
        "capacity_receipt": receipt_artifact,
        "capacity_receipt_commit": commit_artifact,
        "capacity_public_key": key_artifact,
    }


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or RFC3339_RE.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    if parsed.tzinfo != timezone.utc:
        return None
    return parsed


def _run_artifacts(
    run_dir: Path,
    results_artifact: Mapping[str, Any],
    run_evidence: _HeldRunEvidence,
    held: _HeldArtifactSet,
) -> dict[str, dict[str, Any]]:
    artifacts = {
        name: _artifact(run_dir / relative, private=True, held=held)
        for name, relative in {
            "config": "config.toml",
            "inputs_manifest": "inputs/manifest.json",
        }.items()
    }
    artifacts.update(
        {
            "eval_run_identity": run_evidence.artifact("eval_run_identity.json"),
            "eval_invocations": run_evidence.artifact("eval_invocations.jsonl"),
            "provenance": run_evidence.artifact("provenance.txt"),
        }
    )
    artifacts["results"] = dict(results_artifact)
    return artifacts


def _revalidate_artifacts(artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    for name, expected in artifacts.items():
        path = Path(str(expected.get("path", "")))
        observed = _artifact(path, private=name != "capacity_public_key")
        if observed != expected:
            raise KimiProviderSplitError("provider_artifact_changed")


def _open_private_writer_lock(path: Path) -> Any:
    absolute, parent, descriptor, name = _open_anchored(path, directory=False, code="writer_lock_missing")
    del absolute, name
    try:
        metadata = os.fstat(descriptor)
        parent_metadata = os.fstat(parent)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.getuid()
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        ):
            raise KimiProviderSplitError("writer_lock_invalid")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    finally:
        os.close(parent)


def _open_private_writer_lock_at(directory: int, name: str) -> Any:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except OSError as error:
        raise KimiProviderSplitError("writer_lock_missing") from error
    try:
        metadata = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or _stat_identity(metadata) != _stat_identity(visible)
        ):
            raise KimiProviderSplitError("writer_lock_invalid")
        return os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise


def _router_lock_path(identity_body: bytes) -> Path:
    envelope = _json_object(identity_body, code="run_identity_invalid")
    identity = envelope.get("identity")
    deployment = identity.get("deployment") if isinstance(identity, dict) else None
    worker = deployment.get("worker_manifest") if isinstance(deployment, dict) else None
    worker_path = worker.get("path") if isinstance(worker, dict) else None
    if (
        not isinstance(deployment, dict)
        or deployment.get("kind") != "direct_kimi"
        or not isinstance(worker_path, str)
        or not worker_path
    ):
        raise KimiProviderSplitError("deployment_binding_invalid")
    return _absolute_path(Path(worker_path)).parent / ".direct_router.lock"


def _self_sha256() -> str:
    return sha256_bytes(read_regular(Path(__file__), code="implementation_unreadable", maximum_bytes=4 * 1024 * 1024))


def _build_provider_certificate(
    *,
    role: Literal["legacy_sandoq", "large_provider"],
    run_dir: Path,
    partition_dir: Path,
    manifest: Path,
    manifest_sha256: str,
    capacity_receipt: Path | None = None,
    capacity_receipt_sha256: str | None = None,
    capacity_public_key: Path | None = None,
    capacity_public_key_sha256: str | None = None,
    publish_output: Path | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    run_dir = _absolute_path(run_dir)
    with ExitStack() as locks:
        retained = _HeldArtifactSet.create()
        locks.callback(retained.close)
        partition, partition_receipt = _read_partition_bundle(
            partition_dir,
            manifest,
            manifest_sha256,
            retained,
        )
        expected_members = partition.legacy_sandoq if role == "legacy_sandoq" else partition.large_provider
        selector_name = LEGACY_SELECTOR if role == "legacy_sandoq" else LARGE_SELECTOR
        selector_sha256 = partition_receipt["selectors"][role]["sha256"]
        run_evidence = _open_held_run_evidence(run_dir)
        locks.callback(run_evidence.close)
        router_lock_path = _router_lock_path(run_evidence.files["eval_run_identity.json"].body)
        router_lock = locks.enter_context(_open_private_writer_lock(router_lock_path))
        writer_lock = locks.enter_context(_open_private_writer_lock_at(run_evidence.directory, ".writer.lock"))
        for lock in (router_lock, writer_lock):
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise KimiProviderSplitError("writer_active") from error
        run_evidence.revalidate()
        manifest_body = read_regular(
            manifest,
            code="resource_manifest_invalid",
            maximum_bytes=8 * 1024 * 1024,
            private=True,
            held=retained,
        )
        manifest_value, _entries = parse_manifest(manifest_body, manifest_sha256)
        identity, shared, identity_sha256, invocation_identity_sha256, slurm_job_id = _validate_run_identity(
            run_dir,
            run_evidence.files["eval_run_identity.json"].body,
            run_evidence.files["eval_invocations.jsonl"].body,
            run_evidence.files["provenance.txt"].body,
            role=role,
            expected_members=expected_members,
            selector_sha256=selector_sha256,
            manifest_value=manifest_value,
            held=retained,
        )
        provider = _provider_name(identity)
        trace_audit, rows, results_artifact = _audit_cpu_results(
            run_dir / "results.jsonl",
            expected_members,
            partition.verifier_modes,
            retained,
        )
        artifacts = _run_artifacts(run_dir, results_artifact, run_evidence, retained)
        artifacts["selector"] = _artifact(
            partition_dir / selector_name,
            private=True,
            held=retained,
        )
        if identity.get("deployment", {}).get("kind") == "direct_kimi":
            router_path = run_dir / "direct_kimi_router_final.json"
            router_body, router_artifact, router_commit_artifact = _validate_direct_router_receipt(
                router_path,
                identity,
                minimum_chat_requests=len(expected_members),
                identity_sha256=identity_sha256,
                invocation_identity_sha256=invocation_identity_sha256,
                held=retained,
            )
            if router_artifact["sha256"] != sha256_bytes(router_body):
                raise KimiProviderSplitError("router_receipt_changed")
            artifacts["router_receipt"] = router_artifact
            artifacts["router_receipt_commit"] = router_commit_artifact
        capacity_summary: dict[str, Any] | None = None
        runtime_instance_nonces: frozenset[str] = frozenset()
        if provider == "sandoq":
            cleanup_path = run_dir / "sandoq_cleanup_audit.json"
            cleanup, cleanup_artifacts = _validate_sandoq_cleanup(
                cleanup_path,
                run_dir,
                identity,
                identity_sha256,
                invocation_identity_sha256,
                slurm_job_id,
                len(expected_members),
                int(identity["execution"]["rollout_concurrency"]),
                retained,
            )
            artifacts.update(cleanup_artifacts)
        else:
            expected_runtime_count = len(expected_members) + sum(
                partition.verifier_modes[member] == "separate" for member in expected_members
            )
            cleanup, cleanup_artifacts, runtime_instance_nonces = _validate_vmvm_cleanup(
                run_dir,
                identity_sha256,
                invocation_identity_sha256,
                expected_runtime_count,
                retained,
            )
            artifacts.update(cleanup_artifacts)
        if role == "large_provider":
            if provider != "vmvm":
                raise KimiProviderSplitError("large_provider_unsupported")
            if any(
                value is None
                for value in (
                    capacity_receipt,
                    capacity_receipt_sha256,
                    capacity_public_key,
                    capacity_public_key_sha256,
                )
            ):
                raise KimiProviderSplitError("capacity_receipt_required")
            assert capacity_receipt is not None
            assert capacity_receipt_sha256 is not None
            assert capacity_public_key is not None
            assert capacity_public_key_sha256 is not None
            capacity, capacity_artifacts = _capacity_payload(
                capacity_receipt,
                capacity_receipt_sha256,
                capacity_public_key,
                capacity_public_key_sha256,
                manifest_sha256=manifest_sha256,
                selector_sha256=selector_sha256,
                identity=identity,
                identity_sha256=identity_sha256,
                invocation_identity_sha256=invocation_identity_sha256,
                runtime_instance_nonces=runtime_instance_nonces,
                held=retained,
            )
            artifacts.update(capacity_artifacts)
            capacity_summary = {
                "provider": capacity["provider"],
                "resource_multiplier": capacity["resource_multiplier"],
                "measurement_method": capacity["measurement_method"],
                "measured_capacity": capacity["measured_capacity"],
                "issued_at": capacity["issued_at"],
                "expires_at": capacity["expires_at"],
                "runtime_instance_nonce_sha256": sha256_bytes(str(capacity["runtime_instance_nonce"]).encode("ascii")),
                "invocation_identity_sha256": capacity["invocation_identity_sha256"],
                "environment_identity_sha256": sha256_bytes(canonical_json(capacity["environment_identity"])),
                "public_key_sha256": capacity_public_key_sha256,
                "receipt_sha256": capacity_receipt_sha256,
            }
        elif any(
            value is not None
            for value in (
                capacity_receipt,
                capacity_receipt_sha256,
                capacity_public_key,
                capacity_public_key_sha256,
            )
        ):
            raise KimiProviderSplitError("unexpected_capacity_receipt")
        certificate = {
            "schema_version": 1,
            "kind": PROVIDER_CERTIFICATE_KIND,
            "state": "passed",
            "role": role,
            "sandbox_provider": provider,
            "task_count": len(expected_members),
            "rollouts_per_task": 1,
            "manifest_sha256": manifest_sha256,
            "partition_receipt_sha256": sha256_bytes(canonical_json(partition_receipt)),
            "selector_sha256": selector_sha256,
            "eval_run_identity_sha256": identity_sha256,
            "invocation_identity_sha256": invocation_identity_sha256,
            "run_dir": str(run_dir),
            "implementation_sha256": _self_sha256(),
            "shared_contract": shared,
            "trace_audit": trace_audit,
            "cleanup": cleanup,
            "capacity": capacity_summary,
            "artifacts": artifacts,
        }
        _revalidate_artifacts(artifacts)
        retained.revalidate()
        if (
            read_regular(
                manifest,
                code="resource_manifest_invalid",
                maximum_bytes=8 * 1024 * 1024,
                private=True,
            )
            != manifest_body
        ):
            raise KimiProviderSplitError("resource_manifest_changed")
        final_partition, final_receipt = _read_partition_bundle(
            partition_dir,
            manifest,
            manifest_sha256,
            retained,
        )
        if final_partition != partition or final_receipt != partition_receipt:
            raise KimiProviderSplitError("partition_bundle_changed")
        run_evidence.revalidate()
        retained.revalidate()
        if publish_output is not None:
            _write_private_once(publish_output, certificate)
            run_evidence.revalidate()
            retained.revalidate()
        return certificate, rows


def _write_private_once(path: Path, value: Mapping[str, Any]) -> None:
    path = _absolute_path(path)
    parent, parent_descriptor, parent_identity = _open_private_parent(path.parent)
    payload = canonical_json(value)
    marker_name = f".{path.name}{FILE_COMMIT_SUFFIX}"
    marker_payload = _file_commit_payload(path.name, payload)
    marker_started = False
    try:
        target_exists = False
        marker_exists = False
        try:
            os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            target_exists = True
        try:
            os.stat(marker_name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            marker_exists = True
        if target_exists or marker_exists:
            if target_exists and marker_exists:
                try:
                    _verify_file_at(parent_descriptor, path.name, payload)
                    _verify_file_at(parent_descriptor, marker_name, marker_payload)
                    _validate_private_parent(parent, parent_descriptor, parent_identity)
                except (KimiProviderSplitError, OSError):
                    pass
                else:
                    return
            raise KimiProviderSplitError("output_already_exists")
        published_identity = _write_at(parent_descriptor, path.name, payload)
        if _verify_file_at(parent_descriptor, path.name, payload) != published_identity:
            raise KimiProviderSplitError("published_artifact_changed")
        _validate_private_parent(parent, parent_descriptor, parent_identity)
        os.fsync(parent_descriptor)
        marker_started = True
        marker_identity = _write_at(parent_descriptor, marker_name, marker_payload)
        if _verify_file_at(parent_descriptor, marker_name, marker_payload) != marker_identity:
            raise KimiProviderSplitError("published_artifact_changed")
        if _verify_file_at(parent_descriptor, path.name, payload) != published_identity:
            raise KimiProviderSplitError("published_artifact_changed")
        os.fsync(parent_descriptor)
        _validate_private_parent(parent, parent_descriptor, parent_identity)
    except BaseException as error:
        if marker_started:
            raise KimiProviderSplitError("output_publication_indeterminate") from error
        raise
    finally:
        os.close(parent_descriptor)


def certify_provider(
    *,
    role: Literal["legacy_sandoq", "large_provider"],
    run_dir: Path,
    partition_dir: Path,
    manifest: Path,
    manifest_sha256: str,
    output: Path,
    capacity_receipt: Path | None = None,
    capacity_receipt_sha256: str | None = None,
    capacity_public_key: Path | None = None,
    capacity_public_key_sha256: str | None = None,
) -> dict[str, Any]:
    certificate, _rows = _build_provider_certificate(
        role=role,
        run_dir=run_dir,
        partition_dir=partition_dir,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        capacity_receipt=capacity_receipt,
        capacity_receipt_sha256=capacity_receipt_sha256,
        capacity_public_key=capacity_public_key,
        capacity_public_key_sha256=capacity_public_key_sha256,
        publish_output=output,
    )
    return certificate


def _load_bound_certificate(path: Path, expected_sha256: str) -> tuple[dict[str, Any], bytes]:
    body = read_regular(path, code="provider_certificate_invalid", private=True)
    marker = read_regular(
        path.with_name(f".{path.name}{FILE_COMMIT_SUFFIX}"),
        code="provider_certificate_commit_invalid",
        maximum_bytes=64 * 1024,
        private=True,
    )
    if SHA256_RE.fullmatch(expected_sha256 or "") is None or sha256_bytes(body) != expected_sha256:
        raise KimiProviderSplitError("provider_certificate_digest_mismatch")
    if marker != _file_commit_payload(path.name, body):
        raise KimiProviderSplitError("provider_certificate_commit_invalid")
    return _json_object(body, code="provider_certificate_invalid", canonical=True), body


def _artifact_path(certificate: Mapping[str, Any], name: str) -> Path:
    artifacts = certificate.get("artifacts")
    record = artifacts.get(name) if isinstance(artifacts, dict) else None
    if not isinstance(record, dict) or set(record) != {"path", "bytes", "sha256"}:
        raise KimiProviderSplitError("provider_certificate_invalid")
    path = Path(str(record["path"]))
    if _artifact(path, private=name != "capacity_public_key") != record:
        raise KimiProviderSplitError("provider_artifact_changed")
    return path


def _revalidate_provider_certificate(
    certificate: Mapping[str, Any],
    body: bytes,
    *,
    expected_role: Literal["legacy_sandoq", "large_provider"],
    partition_dir: Path,
    manifest: Path,
    manifest_sha256: str,
    trusted_capacity_key_sha256: str | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if certificate.get("role") != expected_role or certificate.get("implementation_sha256") != _self_sha256():
        raise KimiProviderSplitError("provider_certificate_invalid")
    run_dir = Path(str(certificate.get("run_dir", "")))
    capacity_receipt = None
    capacity_receipt_sha256 = None
    capacity_public_key = None
    capacity_public_key_sha256 = None
    if expected_role == "large_provider":
        capacity_receipt = _artifact_path(certificate, "capacity_receipt")
        capacity_public_key = _artifact_path(certificate, "capacity_public_key")
        capacity_receipt_sha256 = certificate["artifacts"]["capacity_receipt"]["sha256"]
        capacity_public_key_sha256 = certificate["artifacts"]["capacity_public_key"]["sha256"]
        if capacity_public_key_sha256 != trusted_capacity_key_sha256:
            raise KimiProviderSplitError("capacity_trust_root_mismatch")
    expected, rows = _build_provider_certificate(
        role=expected_role,
        run_dir=run_dir,
        partition_dir=partition_dir,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        capacity_receipt=capacity_receipt,
        capacity_receipt_sha256=capacity_receipt_sha256,
        capacity_public_key=capacity_public_key,
        capacity_public_key_sha256=capacity_public_key_sha256,
    )
    if body != canonical_json(expected):
        raise KimiProviderSplitError("provider_certificate_evidence_mismatch")
    return expected, rows


def _gpu_unsupported_row(task_id: str, manifest_sha256: str) -> dict[str, Any]:
    expected_name = f"terminal-bench/{task_id}"
    message = (
        f"taskset setup: UnsupportedTaskError: {expected_name}: "
        "requests GPU resources, but the current VMVM tenant is CPU-only"
    )
    return {
        "id": f"gpu-unsupported-{sha256_bytes((manifest_sha256 + chr(0) + task_id).encode())}",
        "task": {"name": expected_name, "resources": {"gpu": "1"}},
        "is_completed": True,
        "stop_condition": "error",
        "nodes": [],
        "rewards": {},
        "metrics": {},
        "errors": [{"type": "TasksetError", "message": message, "traceback": message}],
    }


def _merge_rows(
    entries: Sequence[ManifestEntry],
    partition: Partition,
    legacy_rows: Mapping[str, dict[str, Any]],
    large_rows: Mapping[str, dict[str, Any]],
    manifest_sha256: str,
) -> tuple[list[dict[str, Any]], int]:
    if set(legacy_rows) != set(partition.legacy_sandoq) or set(large_rows) != set(partition.large_provider):
        raise KimiProviderSplitError("provider_coverage_invalid")
    if set(legacy_rows) & set(large_rows):
        raise KimiProviderSplitError("provider_coverage_overlap")
    gpu = set(partition.gpu_unsupported)
    merged: list[dict[str, Any]] = []
    trace_ids: set[str] = set()
    passes = 0
    for entry in entries:
        if entry.task_id in legacy_rows:
            row = legacy_rows[entry.task_id]
            passes += _score(row)
        elif entry.task_id in large_rows:
            row = large_rows[entry.task_id]
            passes += _score(row)
        elif entry.task_id in gpu:
            row = _gpu_unsupported_row(entry.task_id, manifest_sha256)
        else:
            raise KimiProviderSplitError("merged_task_missing")
        trace_id = row.get("id")
        if not isinstance(trace_id, str) or not trace_id or trace_id in trace_ids:
            raise KimiProviderSplitError("merged_trace_id_invalid")
        trace_ids.add(trace_id)
        merged.append(row)
    if len(merged) != TOTAL_TASKS or len(trace_ids) != TOTAL_TASKS:
        raise KimiProviderSplitError("merged_coverage_invalid")
    return merged, passes


def merge_certified_runs(
    *,
    manifest: Path,
    manifest_sha256: str,
    partition_dir: Path,
    legacy_certificate: Path,
    legacy_certificate_sha256: str,
    large_certificate: Path,
    large_certificate_sha256: str,
    trusted_capacity_key_sha256: str,
    output: Path,
) -> dict[str, Any]:
    if trusted_capacity_key_sha256 != PINNED_CAPACITY_PUBLIC_KEY_SHA256:
        raise KimiProviderSplitError("capacity_trust_root_mismatch")
    manifest_body = read_regular(
        manifest,
        code="resource_manifest_invalid",
        maximum_bytes=8 * 1024 * 1024,
        private=True,
    )
    _manifest_value, entries = parse_manifest(manifest_body, manifest_sha256)
    partition, partition_receipt = _read_partition_bundle(partition_dir, manifest, manifest_sha256)
    legacy, legacy_body = _load_bound_certificate(legacy_certificate, legacy_certificate_sha256)
    large, large_body = _load_bound_certificate(large_certificate, large_certificate_sha256)
    legacy, legacy_rows = _revalidate_provider_certificate(
        legacy,
        legacy_body,
        expected_role="legacy_sandoq",
        partition_dir=partition_dir,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        trusted_capacity_key_sha256=None,
    )
    large, large_rows = _revalidate_provider_certificate(
        large,
        large_body,
        expected_role="large_provider",
        partition_dir=partition_dir,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        trusted_capacity_key_sha256=trusted_capacity_key_sha256,
    )
    if (
        legacy["shared_contract"] != large["shared_contract"]
        or legacy["eval_run_identity_sha256"] == large["eval_run_identity_sha256"]
        or legacy["sandbox_provider"] != "sandoq"
        or large["capacity"]["provider"] != large["sandbox_provider"]
    ):
        raise KimiProviderSplitError("provider_union_mismatch")
    rows, passes = _merge_rows(entries, partition, legacy_rows, large_rows, manifest_sha256)
    cpu_pass_rate = passes / CPU_TASKS
    if not TB4_MIN_CPU_PASS_RATE <= cpu_pass_rate <= TB4_MAX_CPU_PASS_RATE:
        raise KimiProviderSplitError("tb4_score_outside_expected_range")
    results_payload = b"".join(canonical_json(row) for row in rows)
    certificate = {
        "schema_version": 1,
        "kind": UNION_CERTIFICATE_KIND,
        "state": "passed",
        "model": "Kimi-K3",
        "task_count": TOTAL_TASKS,
        "rollouts_per_task": 1,
        "manifest_sha256": manifest_sha256,
        "partition_receipt_sha256": sha256_bytes(canonical_json(partition_receipt)),
        "partition": {
            "legacy_sandoq": LEGACY_SANDOQ_TASKS,
            "large_provider": LARGE_PROVIDER_TASKS,
            "gpu_unsupported": GPU_UNSUPPORTED_TASKS,
            "total": TOTAL_TASKS,
            "disjoint": True,
            "exhaustive": True,
        },
        "providers": {
            "legacy_sandoq": {
                "state": "passed",
                "sandbox_provider": legacy["sandbox_provider"],
                "task_count": legacy["task_count"],
                "passes": legacy["trace_audit"]["passes"],
                "cleanup_state": legacy["cleanup"]["state"],
            },
            "large_provider": {
                "state": "passed",
                "sandbox_provider": large["sandbox_provider"],
                "task_count": large["task_count"],
                "passes": large["trace_audit"]["passes"],
                "cleanup_state": large["cleanup"]["state"],
                "capacity": large["capacity"],
            },
        },
        "scores": {
            "passes": passes,
            "cpu_pass_rate": cpu_pass_rate,
            "all_task_pass_rate": passes / TOTAL_TASKS,
            "denominator": TOTAL_TASKS,
            "minimum_cpu_pass_rate": TB4_MIN_CPU_PASS_RATE,
            "maximum_cpu_pass_rate": TB4_MAX_CPU_PASS_RATE,
        },
        "trace_audit": {
            "cpu_traces": CPU_TASKS,
            "unsupported_gpu_outcomes": GPU_UNSUPPORTED_TASKS,
            "total_traces": TOTAL_TASKS,
            "model_io_turns": legacy["trace_audit"]["model_io_turns"] + large["trace_audit"]["model_io_turns"],
            "sampled_tokens": legacy["trace_audit"]["sampled_tokens"] + large["trace_audit"]["sampled_tokens"],
            "trace_failures": 0,
            "reasoning_required": True,
            "request_graph_match_required": True,
            "exact_provider_json_required": True,
            "max_sequence_tokens": MAX_SEQUENCE_TOKENS,
        },
        "artifacts": {
            "results": {"bytes": len(results_payload), "sha256": sha256_bytes(results_payload)},
            "legacy_certificate": {
                "bytes": len(legacy_body),
                "sha256": legacy_certificate_sha256,
            },
            "large_certificate": {
                "bytes": len(large_body),
                "sha256": large_certificate_sha256,
            },
        },
        "implementation_sha256": _self_sha256(),
    }
    _publish_private_bundle(
        output,
        {MERGED_RESULTS: results_payload, UNION_CERTIFICATE: canonical_json(certificate)},
    )
    return certificate


def _add_common_manifest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--partition-dir", type=Path, required=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    materialize = commands.add_parser("materialize")
    materialize.add_argument("--manifest", type=Path, required=True)
    materialize.add_argument("--manifest-sha256", required=True)
    materialize.add_argument("--output", type=Path, required=True)
    certify = commands.add_parser("certify")
    _add_common_manifest_arguments(certify)
    certify.add_argument("--role", choices=("legacy_sandoq", "large_provider"), required=True)
    certify.add_argument("--run-dir", type=Path, required=True)
    certify.add_argument("--capacity-receipt", type=Path)
    certify.add_argument("--capacity-receipt-sha256")
    certify.add_argument("--capacity-public-key", type=Path)
    certify.add_argument("--capacity-public-key-sha256")
    certify.add_argument("--output", type=Path, required=True)
    merge = commands.add_parser("merge")
    _add_common_manifest_arguments(merge)
    merge.add_argument("--legacy-certificate", type=Path, required=True)
    merge.add_argument("--legacy-certificate-sha256", required=True)
    merge.add_argument("--large-certificate", type=Path, required=True)
    merge.add_argument("--large-certificate-sha256", required=True)
    merge.add_argument("--trusted-capacity-key-sha256", required=True)
    merge.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "materialize":
            value = materialize_partition(args.manifest, args.manifest_sha256, args.output)
            result = {"state": "materialized", "partition": value["partition"]}
        elif args.command == "certify":
            value = certify_provider(
                role=args.role,
                run_dir=args.run_dir,
                partition_dir=args.partition_dir,
                manifest=args.manifest,
                manifest_sha256=args.manifest_sha256,
                output=args.output,
                capacity_receipt=args.capacity_receipt,
                capacity_receipt_sha256=args.capacity_receipt_sha256,
                capacity_public_key=args.capacity_public_key,
                capacity_public_key_sha256=args.capacity_public_key_sha256,
            )
            result = {"state": "passed", "role": value["role"], "task_count": value["task_count"]}
        else:
            value = merge_certified_runs(
                manifest=args.manifest,
                manifest_sha256=args.manifest_sha256,
                partition_dir=args.partition_dir,
                legacy_certificate=args.legacy_certificate,
                legacy_certificate_sha256=args.legacy_certificate_sha256,
                large_certificate=args.large_certificate,
                large_certificate_sha256=args.large_certificate_sha256,
                trusted_capacity_key_sha256=args.trusted_capacity_key_sha256,
                output=args.output,
            )
            result = {"state": "passed", "partition": value["partition"], "scores": value["scores"]}
    except Exception:
        raise SystemExit("kimi_tb4_provider_split_failed") from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
