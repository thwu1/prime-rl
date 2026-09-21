#!/usr/bin/env python3
"""Materialize and certify the sealed 1,233-task Sandoq continuation."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import tomllib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Iterator, Mapping

from audit_traces import (
    QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
    _summarize_traces,
)
from certify_direct_qwen_sandoq_partition import _provider_source, validate_cleanup
from direct_qwen_union_contract import (
    FULL_CONTEXT_TOKENS,
    HOST_HARNESS_CONTRACT,
    UnionContractError,
    canonical_json,
    sha256_bytes,
    validate_shared_identity,
)
from materialize_qwen_provider_union import (
    CANONICAL_DATASET_REVISION,
    CANONICAL_DATASET_TREE,
    CANONICAL_SANDOQ_TEMPLATE_SHA256,
    CANONICAL_SOURCE_COUNT,
    CANONICAL_SOURCE_SHA256,
    DEPLOYMENT_NAMESPACE,
    SANDOQ_COUNT,
    VMVM_COUNT,
    MixedMaterializationError,
    derive_partition,
    materialize_sandoq_config,
    verify_canonical_dataset,
)

SCHEMA_VERSION = 1
PLAN_KIND = "qwen-sandoq-source-continuation-plan"
RECEIPT_KIND = "qwen-sandoq-source-continuation-materialization"
IDENTITY_KIND = "qwen-sandoq-source-continuation-identity"
CERTIFICATE_KIND = "direct-qwen-sandoq-source-continuation"
BASE_REVISION = "f58af6b387affd1ecd72db2dea2882f6dd28c35d"

CONTINUATION_COUNT = 1_233
CANONICAL_RETAINED_COUNT = 1_267
SANDOQ_RETAINED_COUNT = 1_266
RETAINED_TRAINABLE_POSITIVE_COUNT = 749
RETAINED_ZERO_REWARD_COUNT = 517
MISSING_OR_ERRORED_COUNT = 1_151
UNSEEN_COUNT = 1_108
ERROR_COUNT = 43
INVALID_POSITIVE_COUNT = 82
CURRENT_IMAGE_MANIFEST_SHA256 = "a3fb4ec9ac9d1ee8376013013f171584c288321923f2050177157edac58340c8"
CURRENT_IMAGE_MANIFEST_SIZE = 641_151

SELECTION_MANIFEST_SHA256 = "6727459dc91bab0165c414a1786644ab87bcf121096a4a5fa50da5b344733cb2"
PROVIDER_RECEIPT_SHA256 = "7ace7cd3731d81a6926c76436151a2c80e7a6098d1f84f0b975afa441663daf4"
CONTINUATION_TASK_SHA256 = "760dbc88fa47580da3334e2d3aa98bad25271c7795cbd59f7aba86ae06438929"
SELECTED_INDICES_SHA256 = "f4b14ef9162b8b216632d8d4897b9c80da201ced42b14e5411106c3a7b0e9605"
ACCEPTED_INDICES_SHA256 = "094f87b5e8b1fd1b3863dc85db62ab4c6ab20807e1062eb73efd67d79955f368"
EVALUATOR_ORDER_SHA256 = "764d8148426f52e42c1ec6b5944d1eb4a24f5f522849a3e93c8af07db85f6ac3"
CONTINUATION_TRACE_CONTRACT = {
    "id": "qwen3-a95b-direct-medium",
    "sha256": "c83833ac8950a17a1d9e7a65ac1fe8f585376a838e4737ce92b20c8eaa4ab777",
}

EPOCH3_ARTIFACTS = {
    "config.toml": "b74832ba6b3684a8b814de41e374033a1d1b32ddb758966b96a95673a88685bd",
    "direct_workers.json": "33c7f847272272782666c883d26b18617e13f8ef50888508927c3ec313b91ee9",
    "inputs/image_manifest.json": "118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009",
    "inputs/manifest.json": "0fce4170e588cb91b55bb7240730821a8e6911e91e993fbb095fb20dfcc723f9",
    "inputs/source_config.toml": "708ce4d941404ae17092e01e24779c0a056f45c92a5f8d26636a36b81624d9ef",
    "inputs/task_file.txt": CANONICAL_SOURCE_SHA256,
    "provenance.txt": "11ef2ad07822658815cf87d653f5738b3c8e29c335ddb1fc43dbdd6a6a3a0161",
    "results.jsonl": "4b4221826019fc7e0615393246e05620b605b3c19a2be35f26afb8adc085a641",
}
EPOCH_TRANSITION_ARTIFACTS = {
    "inputs/manifest.epoch-2.json": "0be45db4f82e75e30a7506fe4fa6f417a61b595ca95cfe0710a039f3401e3178",
    "inputs/source_config.epoch-1.toml": "e6869142781f192318c98b63cf8fc0004b5722878dec88eb9273ea6a6d916262",
    "inputs/source_config.epoch-2.toml": "6c481c13b33f6160593ef73f1d425bdaaa42861fae6cad1de2f17aac90869e7c",
    "qwen_router_admission_transition.json": "e47b5e9db49efd4ec5af8c84499e3e360c2843e9d907eb5e94383c84c42fe939",
    "qwen_router_epoch1_rows.sha256": "1444e660ac0e34e4e0c8bdc902e55ed94e21efb1d85b5b6d9a32adfad7f5ee30",
    "qwen_router_epoch2_lineage.jsonl": "1d48e5c10ea95ba4e374c679dacbaacd70ac4dc278c45bcf12c490f9c8e8ab98",
    "qwen_router_transition.json": "c23e45adc624b767b034de4dfe41d9781b982939173a4b6e766e356f199571f9",
}
EPOCH3_ROUTING = {
    "routing_epoch": 3,
    "manifest_schema_version": 3,
    "model": "Qwen3.8-2.4T-A95B",
    "worker_count": 16,
    "rollout_concurrency": 64,
    "provider_concurrency": 32,
    "queue_size": 32,
    "router_policy": "consistent_hash",
    "request_id_headers": ["x-session-id"],
    "manifest_sha256": EPOCH3_ARTIFACTS["direct_workers.json"],
    "spec_sha256": "516c386c646abda61b73ffe2b2a820c38a826e2311327154cd775ed29e60215a",
    "endpoint_bundle_sha256": "77b513b09002201df0464586e0ac69932348f7fcdbe298213e910be74275160b",
}
SOURCE_PARTITION = {
    "error_traces": ERROR_COUNT,
    "exhaustive": True,
    "invalid_positive_traces": INVALID_POSITIVE_COUNT,
    "positive_reward_traces": 831,
    "repair_tasks": CONTINUATION_COUNT,
    "retained_original_tasks": CANONICAL_RETAINED_COUNT,
    "retained_valid_positive_traces": RETAINED_TRAINABLE_POSITIVE_COUNT,
    "reward_zero_traces": 518,
    "seen_traces": 1_392,
    "source_task_count": CANONICAL_SOURCE_COUNT,
    "superseded_legacy_empty_reasoning_traces": 1,
    "unseen_tasks": UNSEEN_COUNT,
}
EXECUTION_CONTRACT = {
    "reasoning_effort": "medium",
    "task_network": "public",
    "rollout_concurrency": 64,
    "multiplex": 64,
    "http_max_connections": 32,
    "http_max_keepalive_connections": 32,
    "pool_size": 64,
    "pool_min_size": 0,
    "max_input_tokens": 262_144,
    "max_output_tokens": 262_144,
    "max_total_tokens": 262_144,
    "sampling_max_tokens": 32_768,
    "rollout_retries": 0,
    "verifier_runtime_retries": 0,
}
EXPECTED_SELECTION_SOURCE_ARTIFACTS = {
    "config": EPOCH3_ARTIFACTS["config.toml"],
    "direct_workers": EPOCH3_ARTIFACTS["direct_workers.json"],
    "image_manifest": EPOCH3_ARTIFACTS["inputs/image_manifest.json"],
    "inputs_manifest": EPOCH3_ARTIFACTS["inputs/manifest.json"],
    "provenance": EPOCH3_ARTIFACTS["provenance.txt"],
    "results": EPOCH3_ARTIFACTS["results.jsonl"],
    "source_config": EPOCH3_ARTIFACTS["inputs/source_config.toml"],
    "task_file": EPOCH3_ARTIFACTS["inputs/task_file.txt"],
}
CODE_FILES = (
    "audit_traces.py",
    "direct_qwen_workers.py",
    "run_direct_qwen_eval_driver.sh",
    "run_qwen_direct_eval.sbatch",
    "sandoq_source_continuation.py",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
MAX_PRIVATE_BYTES = 64 << 20


class SourceContinuationError(ValueError):
    """Stable aggregate-only failure."""


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise SourceContinuationError("arguments_invalid")


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    sha256: str
    size_bytes: int
    identity: tuple[int, ...]

    def record(self) -> dict[str, int | str]:
        return {"sha256": self.sha256, "size_bytes": self.size_bytes}


@dataclass(slots=True)
class PublishedOutputs:
    root: Path
    descriptor: int
    root_identity: tuple[int, ...]
    entries: tuple[tuple[str, tuple[int, int], bytes], ...]

    def rollback(self) -> None:
        if self.descriptor < 0:
            return
        try:
            for name, identity, _body in self.entries:
                try:
                    observed = os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
                    if (observed.st_dev, observed.st_ino) == identity:
                        os.unlink(name, dir_fd=self.descriptor)
                except OSError:
                    pass
            os.fsync(self.descriptor)
        finally:
            os.close(self.descriptor)
            self.descriptor = -1

    def commit(self) -> None:
        if self.descriptor < 0:
            raise SourceContinuationError("publication_invalid")
        try:
            listed = os.stat(self.root, follow_symlinks=False)
            if (
                _directory_identity(os.fstat(self.descriptor)) != self.root_identity
                or _directory_identity(listed) != self.root_identity
            ):
                raise SourceContinuationError("publication_root_changed")
            for name, identity, body in self.entries:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=self.descriptor,
                )
                try:
                    before = os.fstat(descriptor)
                    payload = bytearray()
                    while chunk := os.read(descriptor, 1 << 20):
                        payload.extend(chunk)
                    after = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
                if (
                    (before.st_dev, before.st_ino) != identity
                    or _file_identity(before) != _file_identity(after)
                    or before.st_uid != os.getuid()
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_nlink != 1
                    or bytes(payload) != body
                ):
                    raise SourceContinuationError("publication_changed")
        except BaseException:
            self.rollback()
            raise
        os.close(self.descriptor)
        self.descriptor = -1


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json(value: object) -> bytes:
    try:
        return canonical_json(value)
    except UnionContractError as error:
        raise SourceContinuationError("evidence_not_strict_json") from error


def _plain_int(value: object, expected: int | None = None) -> bool:
    valid = isinstance(value, int) and not isinstance(value, bool)
    return valid and (expected is None or value == expected)


def _normalized_absolute(path: Path, code: str) -> Path:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        raise SourceContinuationError(code)
    return path


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        stat.S_IMODE(value.st_mode),
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode)


@dataclass(slots=True)
class PrivateDirectory:
    path: Path
    descriptor: int
    initial: os.stat_result

    @classmethod
    def open(cls, path: Path, code: str, *, create: bool = False) -> PrivateDirectory:
        path = _normalized_absolute(path, code)
        if create:
            try:
                path.mkdir(mode=0o700)
            except FileExistsError as error:
                raise SourceContinuationError(code) from error
            except OSError as error:
                raise SourceContinuationError(code) from error
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            metadata = os.fstat(descriptor)
            observed = os.stat(path, follow_symlinks=False)
        except OSError as error:
            if "descriptor" in locals():
                os.close(descriptor)
            raise SourceContinuationError(code) from error
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or _directory_identity(metadata) != _directory_identity(observed)
        ):
            os.close(descriptor)
            raise SourceContinuationError(code)
        return cls(path, descriptor, metadata)

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1

    def __enter__(self) -> PrivateDirectory:
        return self

    def __exit__(self, *_args: object) -> None:
        try:
            self.validate("private_directory_changed")
        finally:
            self.close()

    def validate(self, code: str) -> None:
        try:
            held = os.fstat(self.descriptor)
            observed_fd = os.open(
                self.path,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            )
            observed = os.fstat(observed_fd)
        except OSError as error:
            raise SourceContinuationError(code) from error
        finally:
            if "observed_fd" in locals():
                os.close(observed_fd)
        if not (_directory_identity(self.initial) == _directory_identity(held) == _directory_identity(observed)):
            raise SourceContinuationError(code)

    def _parent_fd(self, relative: str, code: str) -> tuple[int, str]:
        path = PurePath(relative)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise SourceContinuationError(code)
        parent = os.dup(self.descriptor)
        try:
            for part in path.parts[:-1]:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent,
                )
                metadata = os.fstat(child)
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.getuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o700
                ):
                    os.close(child)
                    raise SourceContinuationError(code)
                os.close(parent)
                parent = child
        except (OSError, SourceContinuationError) as error:
            os.close(parent)
            if isinstance(error, SourceContinuationError):
                raise
            raise SourceContinuationError(code) from error
        return parent, path.parts[-1]

    def read(self, relative: str, code: str, *, max_bytes: int = MAX_PRIVATE_BYTES) -> bytes:
        parent, name = self._parent_fd(relative, code)
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1
                or before.st_size > max_bytes
            ):
                raise SourceContinuationError(code)
            body = bytearray()
            while chunk := os.read(descriptor, 1 << 20):
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise SourceContinuationError(code)
            after = os.fstat(descriptor)
            listed = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError as error:
            raise SourceContinuationError(code) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)
        if _file_identity(before) != _file_identity(after) or _file_identity(after) != _file_identity(listed):
            raise SourceContinuationError(code)
        return bytes(body)

    @contextmanager
    def open_binary(self, relative: str, code: str) -> Iterator[Any]:
        parent, name = self._parent_fd(relative, code)
        descriptor = -1
        handle = None
        before = None
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1
            ):
                raise SourceContinuationError(code)
            handle = os.fdopen(descriptor, "rb")
            descriptor = -1
            yield handle
            after = os.fstat(handle.fileno())
            listed = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if _file_identity(before) != _file_identity(after) or _file_identity(after) != _file_identity(listed):
                raise SourceContinuationError(code)
        except OSError as error:
            raise SourceContinuationError(code) from error
        finally:
            if handle is not None:
                handle.close()
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)

    def snapshot(self, relative: str, code: str) -> ArtifactSnapshot:
        parent, name = self._parent_fd(relative, code)
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1
            ):
                raise SourceContinuationError(code)
            digest = hashlib.sha256()
            size = 0
            while chunk := os.read(descriptor, 1 << 20):
                digest.update(chunk)
                size += len(chunk)
            after = os.fstat(descriptor)
            listed = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError as error:
            raise SourceContinuationError(code) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(parent)
        if _file_identity(before) != _file_identity(after) or _file_identity(after) != _file_identity(listed):
            raise SourceContinuationError(code)
        return ArtifactSnapshot(digest.hexdigest(), size, _file_identity(after))

    def artifact(self, relative: str, code: str) -> dict[str, int | str]:
        return self.snapshot(relative, code).record()

    def lock(self, relative: str, stack: ExitStack, code: str) -> None:
        parent, name = self._parent_fd(relative, code)
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
        except OSError as error:
            os.close(parent)
            raise SourceContinuationError(code) from error
        os.close(parent)
        handle = stack.enter_context(os.fdopen(descriptor, "rb"))
        metadata = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_nlink != 1
        ):
            raise SourceContinuationError(code)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SourceContinuationError("source_or_run_active") from error

        def validate_lock() -> None:
            try:
                held = os.fstat(handle.fileno())
                listed = os.stat(relative, dir_fd=self.descriptor, follow_symlinks=False)
            except OSError as error:
                raise SourceContinuationError("source_or_run_lock_changed") from error
            if _file_identity(metadata) != _file_identity(held) or _file_identity(held) != _file_identity(listed):
                raise SourceContinuationError("source_or_run_lock_changed")

        stack.callback(validate_lock)

    def publish(self, outputs: list[tuple[Path, bytes]], code: str) -> PublishedOutputs:
        names: list[str] = []
        for path, _body in outputs:
            if _normalized_absolute(path, code).parent != self.path or path.name in names:
                raise SourceContinuationError(code)
            names.append(path.name)
        if any(os.path.lexists(path) for path, _body in outputs):
            raise SourceContinuationError("output_exists")
        temporary: list[str] = []
        published: list[tuple[str, tuple[int, int]]] = []
        try:
            for index, (path, body) in enumerate(outputs):
                name = f".{path.name}.tmp.{os.getpid()}.{index}"
                descriptor = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=self.descriptor,
                )
                temporary.append(name)
                with os.fdopen(descriptor, "wb") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                    metadata = os.fstat(handle.fileno())
                    if metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
                        raise SourceContinuationError(code)
                os.link(
                    name,
                    path.name,
                    src_dir_fd=self.descriptor,
                    dst_dir_fd=self.descriptor,
                    follow_symlinks=False,
                )
                published.append((path.name, (metadata.st_dev, metadata.st_ino)))
                listed = os.stat(path.name, dir_fd=self.descriptor, follow_symlinks=False)
                if (
                    not stat.S_ISREG(listed.st_mode)
                    or listed.st_uid != os.getuid()
                    or stat.S_IMODE(listed.st_mode) != 0o600
                    or listed.st_nlink != 2
                ):
                    raise SourceContinuationError(code)
                os.unlink(name, dir_fd=self.descriptor)
                temporary.remove(name)
                final = os.stat(path.name, dir_fd=self.descriptor, follow_symlinks=False)
                if final.st_nlink != 1:
                    raise SourceContinuationError(code)
            for name, identity in published:
                final = os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
                if (
                    (final.st_dev, final.st_ino) != identity
                    or not stat.S_ISREG(final.st_mode)
                    or final.st_uid != os.getuid()
                    or stat.S_IMODE(final.st_mode) != 0o600
                    or final.st_nlink != 1
                ):
                    raise SourceContinuationError(code)
            os.fsync(self.descriptor)
            self.validate("private_directory_changed")
            return PublishedOutputs(
                self.path,
                os.dup(self.descriptor),
                _directory_identity(os.fstat(self.descriptor)),
                tuple(
                    (path.name, identity, body)
                    for (path, body), (_name, identity) in zip(
                        outputs,
                        published,
                        strict=True,
                    )
                ),
            )
        except Exception as error:
            for name in temporary:
                try:
                    os.unlink(name, dir_fd=self.descriptor)
                except OSError:
                    pass
            for name, identity in reversed(published):
                try:
                    current = os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == identity:
                        os.unlink(name, dir_fd=self.descriptor)
                except OSError:
                    pass
            if isinstance(error, SourceContinuationError):
                raise
            raise SourceContinuationError(code) from error


def _private_read(path: Path, code: str, *, max_bytes: int = MAX_PRIVATE_BYTES) -> bytes:
    path = _normalized_absolute(path, code)
    with PrivateDirectory.open(path.parent, code) as root:
        return root.read(path.name, code, max_bytes=max_bytes)


def _read_regular(path: Path, code: str, *, max_bytes: int = MAX_PRIVATE_BYTES) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise SourceContinuationError(code)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise SourceContinuationError(code)
        after = os.fstat(descriptor)
        listed = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise SourceContinuationError(code) from error
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    if _file_identity(before) != _file_identity(after) or _file_identity(after) != _file_identity(listed):
        raise SourceContinuationError(code)
    return bytes(body)


def _read_owned_private_file(path: Path, code: str, *, max_bytes: int = MAX_PRIVATE_BYTES) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size > max_bytes
        ):
            raise SourceContinuationError(code)
        body = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise SourceContinuationError(code)
        after = os.fstat(descriptor)
        listed = path.lstat()
    except OSError as error:
        raise SourceContinuationError(code) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if _file_identity(before) != _file_identity(after) or _file_identity(after) != _file_identity(listed):
        raise SourceContinuationError(code)
    return bytes(body)


def _parse_json(body: bytes, code: str, *, canonical: bool = False) -> dict[str, Any]:
    def reject_constant(_value: str) -> None:
        raise ValueError("non-finite number")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(
            body,
            object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise SourceContinuationError(code) from error
    if not isinstance(value, dict) or (canonical and _json(value) != body):
        raise SourceContinuationError(code)
    return value


def _task_members(body: bytes, code: str, *, count: int) -> tuple[str, ...]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SourceContinuationError(code) from error
    if not text.endswith("\n") or "\r" in text:
        raise SourceContinuationError(code)
    members = tuple(text.splitlines())
    if (
        len(members) != count
        or len(members) != len(set(members))
        or any(not member or member.strip() != member or "/" in member or "\\" in member for member in members)
    ):
        raise SourceContinuationError(code)
    return members


def _artifact_value(body: bytes) -> dict[str, int | str]:
    return {"sha256": _sha256(body), "size_bytes": len(body)}


def _git(root: Path, *arguments: str, code: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SourceContinuationError(code) from error
    if completed.stderr:
        raise SourceContinuationError(code)
    return completed.stdout.strip()


def _code_binding() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[3]
    revision = _git(repository, "rev-parse", "HEAD", code="code_provenance_invalid")
    tree = _git(repository, "rev-parse", "HEAD^{tree}", code="code_provenance_invalid")
    status = _git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        code="code_provenance_invalid",
    )
    ancestor = subprocess.run(
        ["git", "-C", str(repository), "merge-base", "--is-ancestor", BASE_REVISION, revision],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    if (
        status
        or ancestor.returncode != 0
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or re.fullmatch(r"[0-9a-f]{40}", tree) is None
    ):
        raise SourceContinuationError("code_provenance_invalid")
    workflow = Path(__file__).resolve().parent
    files: dict[str, str] = {}
    for name in CODE_FILES:
        files[name] = _sha256(_read_regular(workflow / name, "code_provenance_invalid"))
    return {
        "base_revision": BASE_REVISION,
        "repository_revision": revision,
        "repository_tree": tree,
        "files": files,
    }


def _selection_value(manifest_body: bytes) -> dict[str, Any]:
    if _sha256(manifest_body) != SELECTION_MANIFEST_SHA256:
        raise SourceContinuationError("selection_manifest_invalid")
    value = _parse_json(manifest_body, "selection_manifest_invalid")
    selection = value.get("selection")
    source = value.get("source")
    partition = value.get("source_partition")
    planner = value.get("planner")
    approval = value.get("approval")
    trace_contracts = value.get("trace_contracts")
    artifacts = source.get("artifacts") if isinstance(source, Mapping) else None
    if (
        value.get("schema_version") != 3
        or value.get("kind") != "qwen-aggregate-repair-selection"
        or not isinstance(selection, Mapping)
        or selection.get("approved_repair_count") != CONTINUATION_COUNT
        or selection.get("missing_or_errored_count") != MISSING_OR_ERRORED_COUNT
        or selection.get("strict_invalid_pass_count") != INVALID_POSITIVE_COUNT
        or selection.get("task_file_sha256") != CONTINUATION_TASK_SHA256
        or selection.get("repair_union_indices_sha256") != SELECTED_INDICES_SHA256
        or not isinstance(source, Mapping)
        or source.get("routing_epoch") != 3
        or source.get("task_count") != CANONICAL_SOURCE_COUNT
        or not isinstance(artifacts, Mapping)
        or set(artifacts) != set(EXPECTED_SELECTION_SOURCE_ARTIFACTS)
        or any(
            not isinstance(artifacts.get(name), Mapping)
            or artifacts[name].get("sha256") != digest
            or not _plain_int(artifacts[name].get("size_bytes"))
            or artifacts[name]["size_bytes"] < 1
            for name, digest in EXPECTED_SELECTION_SOURCE_ARTIFACTS.items()
        )
        or partition != SOURCE_PARTITION
        or not isinstance(planner, Mapping)
        or planner.get("approved_task_count") != CANONICAL_SOURCE_COUNT
        or planner.get("task_index_order_sha256") != EVALUATOR_ORDER_SHA256
        or approval
        != {
            "approved_task_count": CANONICAL_SOURCE_COUNT,
            "approved_task_file_sha256": CANONICAL_SOURCE_SHA256,
        }
        or not isinstance(trace_contracts, Mapping)
        or set(trace_contracts) != {"repair", "source"}
    ):
        raise SourceContinuationError("selection_manifest_invalid")
    return value


def _provider_receipt_value(receipt_body: bytes) -> dict[str, Any]:
    if _sha256(receipt_body) != PROVIDER_RECEIPT_SHA256:
        raise SourceContinuationError("provider_receipt_invalid")
    value = _parse_json(receipt_body, "provider_receipt_invalid")
    selection = value.get("repair_selection")
    partition = value.get("partition")
    if (
        set(value)
        != {
            "canonical_source",
            "deployment_namespace",
            "kind",
            "partition",
            "repair_selection",
            "schema_version",
            "state",
        }
        or value.get("schema_version") != 1
        or value.get("kind") != "qwen-repair-provider-partition"
        or value.get("state") != "materialized"
        or value.get("deployment_namespace") != DEPLOYMENT_NAMESPACE
        or value.get("canonical_source") != {"count": CANONICAL_SOURCE_COUNT, "sha256": CANONICAL_SOURCE_SHA256}
        or not isinstance(selection, Mapping)
        or selection.get("count") != CONTINUATION_COUNT
        or selection.get("manifest_sha256") != SELECTION_MANIFEST_SHA256
        or selection.get("task_file_sha256") != CONTINUATION_TASK_SHA256
        or selection.get("union_indices_sha256") != SELECTED_INDICES_SHA256
        or selection.get("source_partition") != SOURCE_PARTITION
        or partition
        != {
            "disjoint": True,
            "exhaustive": True,
            "sandoq_count": CONTINUATION_COUNT,
            "total_count": CONTINUATION_COUNT,
            "vmvm_count": 0,
        }
    ):
        raise SourceContinuationError("provider_receipt_invalid")
    return value


def _source_jobs_finality(root: PrivateDirectory) -> dict[str, Any]:
    try:
        import migrate_qwen_router_affinity as migration

        provenance = Path(f"/proc/self/fd/{root.descriptor}/provenance.txt")
        job_ids = migration._provenance_job_ids(provenance)
        terminal = [migration.slurm_job_is_terminal(job_id) for job_id in job_ids]
    except Exception as error:
        raise SourceContinuationError("epoch3_source_job_state_unavailable") from error
    if not terminal or not all(terminal):
        raise SourceContinuationError("epoch3_source_job_not_terminal")
    return {"all_terminal": True, "referenced_job_count": len(job_ids)}


@contextmanager
def _hold_source_run(source_run: Path) -> Iterator[PrivateDirectory]:
    source_run = _normalized_absolute(source_run, "epoch3_source_invalid")
    with PrivateDirectory.open(source_run, "epoch3_source_invalid") as root, ExitStack() as locks:
        root.lock(".writer.lock", locks, "epoch3_source_lock_invalid")
        root.lock(".direct_router.lock", locks, "epoch3_source_lock_invalid")
        yield root


def _validate_source_run(
    source_run: Path,
    *,
    held_root: PrivateDirectory | None = None,
) -> dict[str, Any]:
    source_run = _normalized_absolute(source_run, "epoch3_source_invalid")
    if held_root is None:
        with _hold_source_run(source_run) as root:
            return _validate_source_run(source_run, held_root=root)
    if held_root.path != source_run:
        raise SourceContinuationError("epoch3_source_invalid")
    held_root.validate("epoch3_source_changed")
    job_finality = _source_jobs_finality(held_root)
    artifacts: dict[str, dict[str, int | str]] = {}
    for relative, expected in {**EPOCH3_ARTIFACTS, **EPOCH_TRANSITION_ARTIFACTS}.items():
        observed = held_root.artifact(relative, "epoch3_source_artifact_invalid")
        if observed["sha256"] != expected:
            raise SourceContinuationError("epoch3_source_artifact_invalid")
        artifacts[relative] = observed
    try:
        import migrate_qwen_serving_generation as generation

        summary = generation.audit_historical_source_generation(source_run)
    except Exception as error:
        raise SourceContinuationError("epoch3_source_audit_invalid") from error
    if (
        summary.get("ok") is not True
        or summary.get("routing_epoch") != EPOCH3_ROUTING["routing_epoch"]
        or summary.get("manifest_schema_version") != EPOCH3_ROUTING["manifest_schema_version"]
        or summary.get("model") != EPOCH3_ROUTING["model"]
        or summary.get("endpoints") != EPOCH3_ROUTING["worker_count"]
        or summary.get("spec_sha256") != EPOCH3_ROUTING["spec_sha256"]
        or summary.get("endpoint_bundle_sha256") != EPOCH3_ROUTING["endpoint_bundle_sha256"]
        or summary.get("provider_concurrency") != EPOCH3_ROUTING["provider_concurrency"]
        or summary.get("queue_size") != EPOCH3_ROUTING["queue_size"]
        or summary.get("router_policy") != EPOCH3_ROUTING["router_policy"]
        or summary.get("request_id_headers") != EPOCH3_ROUTING["request_id_headers"]
    ):
        raise SourceContinuationError("epoch3_source_audit_invalid")
    for relative, expected in {**EPOCH3_ARTIFACTS, **EPOCH_TRANSITION_ARTIFACTS}.items():
        if held_root.artifact(relative, "epoch3_source_changed")["sha256"] != expected:
            raise SourceContinuationError("epoch3_source_changed")
    held_root.validate("epoch3_source_changed")
    return {
        "routing": EPOCH3_ROUTING,
        "job_finality": job_finality,
        "artifacts": {name: artifacts[name] for name in sorted(EPOCH3_ARTIFACTS)},
        "transition_artifacts": {name: artifacts[name] for name in sorted(EPOCH_TRANSITION_ARTIFACTS)},
    }


def _validate_config(
    body: bytes,
    *,
    task_file: Path,
    dataset: Path,
    image_manifest: Path,
) -> dict[str, Any]:
    try:
        config = tomllib.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SourceContinuationError("continuation_config_invalid") from error
    client = config.get("client")
    sampling = config.get("sampling")
    taskset = config.get("taskset")
    harness = config.get("harness")
    runtime = harness.get("runtime") if isinstance(harness, Mapping) else None
    retries = config.get("retries")
    rollout_retries = retries.get("rollout") if isinstance(retries, Mapping) else None
    timeouts = config.get("timeout")
    try:
        configured_task = Path(str(taskset["task_file"]))
        configured_dataset = Path(str(taskset["dataset_dir"])).resolve(strict=True)
        configured_image_manifest = Path(str(taskset["image_manifest"])).resolve(strict=True)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError) as error:
        raise SourceContinuationError("continuation_config_invalid") from error
    if (
        config.get("model") != "Qwen3.8-2.4T-A95B"
        or config.get("num_tasks") != CONTINUATION_COUNT
        or config.get("num_rollouts") != 1
        or config.get("max_turns") != 200
        or config.get("max_concurrent") != EXECUTION_CONTRACT["rollout_concurrency"]
        or config.get("multiplex") != EXECUTION_CONTRACT["multiplex"]
        or any(config.get(key) != 262_144 for key in ("max_input_tokens", "max_output_tokens", "max_total_tokens"))
        or config.get("rich") is not False
        or config.get("retain_traces") is not False
        or not isinstance(client, Mapping)
        or client.get("type") != "eval"
        or client.get("capture_model_io") is not True
        or client.get("timeout") != 7_200
        or client.get("connect_timeout") != 30
        or client.get("max_connections") != EXECUTION_CONTRACT["http_max_connections"]
        or client.get("max_keepalive_connections") != EXECUTION_CONTRACT["http_max_keepalive_connections"]
        or set(client.get("outbound_body_denylist", []))
        != {"logprobs", "prompt_logprobs", "return_token_ids", "top_logprobs"}
        or not isinstance(sampling, Mapping)
        or sampling.get("reasoning_effort") != "medium"
        or sampling.get("temperature") != 0.7
        or sampling.get("top_p") != 0.95
        or sampling.get("top_k") != 20
        or sampling.get("max_tokens") != EXECUTION_CONTRACT["sampling_max_tokens"]
        or sampling.get("chat_template_kwargs") != {"enable_thinking": True, "preserve_thinking": True}
        or not isinstance(taskset, Mapping)
        or configured_task != task_file
        or taskset.get("task_file_sha256") != CONTINUATION_TASK_SHA256
        or taskset.get("dataset_revision") != CANONICAL_DATASET_REVISION
        or configured_dataset != dataset
        or configured_image_manifest != image_manifest
        or taskset.get("image_manifest_sha256") != CURRENT_IMAGE_MANIFEST_SHA256
        or _sha256(
            _read_owned_private_file(
                configured_image_manifest,
                "continuation_image_manifest_invalid",
            )
        )
        != CURRENT_IMAGE_MANIFEST_SHA256
        or taskset.get("verifier_runtime_retries") != 0
        or not isinstance(harness, Mapping)
        or harness.get("id") != "terminal-bench-sandoq-host"
        or harness.get("request_timeout_seconds") != 15_000
        or not isinstance(runtime, Mapping)
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("session_timeout") != 43_200
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "none"
        or runtime.get("expected_environment") != "oci-runner"
        or not isinstance(rollout_retries, Mapping)
        or rollout_retries.get("max_retries") != 0
        or timeouts != {"setup": 3_600, "rollout": 36_000, "finalize": 3_600, "scoring": 21_600}
    ):
        raise SourceContinuationError("continuation_config_invalid")
    return config


def _lineage_value(
    *,
    selection: Mapping[str, Any],
    source_run: Mapping[str, Any],
    provider_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    source_artifacts = selection.get("source", {}).get("artifacts")
    observed_artifacts = source_run.get("artifacts")
    mapping = {
        "config": "config.toml",
        "direct_workers": "direct_workers.json",
        "image_manifest": "inputs/image_manifest.json",
        "inputs_manifest": "inputs/manifest.json",
        "provenance": "provenance.txt",
        "results": "results.jsonl",
        "source_config": "inputs/source_config.toml",
        "task_file": "inputs/task_file.txt",
    }
    if (
        not isinstance(source_artifacts, Mapping)
        or not isinstance(observed_artifacts, Mapping)
        or any(source_artifacts.get(name) != observed_artifacts.get(relative) for name, relative in mapping.items())
    ):
        raise SourceContinuationError("selection_source_binding_invalid")
    return {
        "selection": {
            "manifest_sha256": SELECTION_MANIFEST_SHA256,
            "provider_receipt_sha256": PROVIDER_RECEIPT_SHA256,
            "task_file_sha256": CONTINUATION_TASK_SHA256,
            "selected_indices_sha256": SELECTED_INDICES_SHA256,
            "accepted_indices_sha256": ACCEPTED_INDICES_SHA256,
            "evaluator_order_sha256": EVALUATOR_ORDER_SHA256,
            "selection_trace_contracts": selection["trace_contracts"],
            "continuation_trace_contract": CONTINUATION_TRACE_CONTRACT,
        },
        "epoch3_source": source_run,
        "provider_partition": provider_receipt["partition"],
    }


def _partition_value() -> dict[str, Any]:
    return {
        "canonical_task_count": CANONICAL_SOURCE_COUNT,
        "canonical_sandoq_count": SANDOQ_COUNT,
        "canonical_vmvm_count": VMVM_COUNT,
        "continuation_count": CONTINUATION_COUNT,
        "canonical_retained_count": CANONICAL_RETAINED_COUNT,
        "sandoq_retained_count": SANDOQ_RETAINED_COUNT,
        "retained_trainable_positive_count": RETAINED_TRAINABLE_POSITIVE_COUNT,
        "retained_zero_reward_nonexported_count": RETAINED_ZERO_REWARD_COUNT,
        "unseen_count": UNSEEN_COUNT,
        "error_count": ERROR_COUNT,
        "invalid_positive_count": INVALID_POSITIVE_COUNT,
        "disjoint": True,
        "exhaustive": True,
        "continuation_semantics": "unseen-errors-and-invalid-positive-pass-only",
        "retained_zero_reward_semantics": "scored-failure-not-exported",
    }


def _validate_canonical_partition(
    *,
    source_body: bytes,
    dataset: Path,
    task_body: bytes,
) -> None:
    selected_members = _task_members(
        task_body,
        "provider_task_invalid",
        count=CONTINUATION_COUNT,
    )
    try:
        canonical_partition = derive_partition(source_body, dataset)
    except MixedMaterializationError as error:
        raise SourceContinuationError("canonical_partition_invalid") from error
    selected = set(selected_members)
    sandoq = set(canonical_partition.sandoq)
    vmvm = set(canonical_partition.vmvm)
    retained_sandoq = sandoq - selected
    if (
        canonical_partition.no_network_count != CANONICAL_SOURCE_COUNT
        or len(selected) != CONTINUATION_COUNT
        or not selected.issubset(sandoq)
        or selected & vmvm
        or len(retained_sandoq) != SANDOQ_RETAINED_COUNT
        or retained_sandoq & selected
        or retained_sandoq | selected != sandoq
        or len(retained_sandoq | vmvm) != CANONICAL_RETAINED_COUNT
        or len(sandoq | vmvm) != CANONICAL_SOURCE_COUNT
    ):
        raise SourceContinuationError("canonical_partition_invalid")


def _receipt_value(
    *,
    lineage: Mapping[str, Any],
    task_body: bytes,
    config_body: bytes,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        "state": "materialized",
        "deployment_namespace": DEPLOYMENT_NAMESPACE,
        "lineage": lineage,
        "partition": _partition_value(),
        "execution": EXECUTION_CONTRACT,
        "artifacts": {
            "task_file": _artifact_value(task_body),
            "config": _artifact_value(config_body),
        },
    }


def _plan_value(
    *,
    private_root: Path,
    task_output: Path,
    config_output: Path,
    receipt_output: Path,
    plan_output: Path,
    canonical_source: Path,
    canonical_dataset: Path,
    canonical_template: Path,
    canonical_image_manifest: Path,
    epoch3_source_run: Path,
    selection_manifest: Path,
    provider_receipt: Path,
    provider_task_file: Path,
    receipt: Mapping[str, Any],
    code: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "state": "materialized",
        "private_root": {"path": str(private_root), "mode": "0700"},
        "inputs": {
            "epoch3_source_run": str(epoch3_source_run),
            "selection_manifest": {
                "path": str(selection_manifest),
                "sha256": SELECTION_MANIFEST_SHA256,
                "mode": "0600",
            },
            "provider_receipt": {
                "path": str(provider_receipt),
                "sha256": PROVIDER_RECEIPT_SHA256,
                "mode": "0600",
            },
            "provider_task_file": {
                "path": str(provider_task_file),
                "sha256": CONTINUATION_TASK_SHA256,
                "mode": "0600",
            },
            "canonical_source": {
                "path": str(canonical_source),
                "sha256": CANONICAL_SOURCE_SHA256,
                "count": CANONICAL_SOURCE_COUNT,
            },
            "canonical_dataset": {
                "path": str(canonical_dataset),
                "revision": CANONICAL_DATASET_REVISION,
                "tree": CANONICAL_DATASET_TREE,
            },
            "canonical_template": {
                "path": str(canonical_template),
                "sha256": CANONICAL_SANDOQ_TEMPLATE_SHA256,
            },
            "canonical_image_manifest": {
                "path": str(canonical_image_manifest),
                "sha256": CURRENT_IMAGE_MANIFEST_SHA256,
                "size_bytes": CURRENT_IMAGE_MANIFEST_SIZE,
                "mode": "0600",
            },
        },
        "outputs": {
            "task_file": {
                "path": str(task_output),
                "sha256": CONTINUATION_TASK_SHA256,
                "count": CONTINUATION_COUNT,
                "mode": "0600",
            },
            "config": {
                "path": str(config_output),
                "sha256": receipt["artifacts"]["config"]["sha256"],
                "mode": "0600",
            },
            "receipt": {
                "path": str(receipt_output),
                "sha256": _sha256(_json(receipt)),
                "mode": "0600",
            },
            "plan": {"path": str(plan_output), "mode": "0600"},
        },
        "materialization": receipt,
        "code": code,
    }


def _canonical_paths(
    canonical_source: Path,
    canonical_dataset: Path,
    canonical_template: Path,
) -> tuple[Path, Path, Path, bytes, bytes]:
    workflow = Path(__file__).resolve().parent
    wanted_source = workflow / "configs/eval/mobius_valid_tasks_2500.txt"
    wanted_template = workflow / "configs/eval" / DEPLOYMENT_NAMESPACE / "mobius_qwen_a95b_2500_sandoq.toml"
    try:
        resolved_source = canonical_source.resolve(strict=True)
        resolved_template = canonical_template.resolve(strict=True)
    except OSError as error:
        raise SourceContinuationError("canonical_input_invalid") from error
    if resolved_source != wanted_source or resolved_template != wanted_template:
        raise SourceContinuationError("canonical_input_invalid")
    source_body = _read_regular(resolved_source, "canonical_source_invalid")
    template_body = _read_regular(resolved_template, "canonical_template_invalid")
    if _sha256(source_body) != CANONICAL_SOURCE_SHA256 or _sha256(template_body) != CANONICAL_SANDOQ_TEMPLATE_SHA256:
        raise SourceContinuationError("canonical_input_invalid")
    try:
        dataset = verify_canonical_dataset(canonical_dataset)
    except MixedMaterializationError as error:
        raise SourceContinuationError("canonical_dataset_invalid") from error
    return resolved_source, dataset, resolved_template, source_body, template_body


def _canonical_image_manifest(template_body: bytes) -> tuple[Path, bytes]:
    try:
        template = tomllib.loads(template_body.decode("utf-8"))
        taskset = template["taskset"]
        path = Path(str(taskset["image_manifest"]))
        declared_sha256 = taskset["image_manifest_sha256"]
        resolved = path.resolve(strict=True)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, OSError) as error:
        raise SourceContinuationError("canonical_image_manifest_invalid") from error
    if (
        not path.is_absolute()
        or path != Path(os.path.normpath(path))
        or resolved != path
        or declared_sha256 != CURRENT_IMAGE_MANIFEST_SHA256
    ):
        raise SourceContinuationError("canonical_image_manifest_invalid")
    body = _read_owned_private_file(path, "canonical_image_manifest_invalid", max_bytes=2 << 20)
    if len(body) != CURRENT_IMAGE_MANIFEST_SIZE or _sha256(body) != CURRENT_IMAGE_MANIFEST_SHA256:
        raise SourceContinuationError("canonical_image_manifest_invalid")
    return path, body


def _finish_materialization(
    *,
    epoch3_source_run: Path,
    selection_manifest: Path,
    selection_body: bytes,
    selection: Mapping[str, Any],
    selection_task: bytes,
    provider_receipt: Path,
    provider_receipt_body: bytes,
    provider_receipt_value: Mapping[str, Any],
    provider_task_file: Path,
    task_body: bytes,
    source_path: Path,
    source_body: bytes,
    dataset: Path,
    template_path: Path,
    template_body: bytes,
    image_manifest_path: Path,
    image_manifest_body: bytes,
    private_root: Path,
    task_output: Path,
    config_output: Path,
    receipt_output: Path,
    plan_output: Path,
) -> dict[str, Any]:
    publication: PublishedOutputs | None = None
    try:
        with _hold_source_run(epoch3_source_run) as source_root:
            source_run = _validate_source_run(epoch3_source_run, held_root=source_root)
            try:
                config_body = materialize_sandoq_config(
                    template_body,
                    task_output,
                    CONTINUATION_TASK_SHA256,
                    task_count=CONTINUATION_COUNT,
                )
            except MixedMaterializationError as error:
                raise SourceContinuationError("continuation_config_invalid") from error
            _validate_config(
                config_body,
                task_file=task_output,
                dataset=dataset,
                image_manifest=image_manifest_path,
            )
            code = _code_binding()
            lineage = _lineage_value(
                selection=selection,
                source_run=source_run,
                provider_receipt=provider_receipt_value,
            )
            receipt = _receipt_value(lineage=lineage, task_body=task_body, config_body=config_body)
            plan = _plan_value(
                private_root=private_root,
                task_output=task_output,
                config_output=config_output,
                receipt_output=receipt_output,
                plan_output=plan_output,
                canonical_source=source_path,
                canonical_dataset=dataset,
                canonical_template=template_path,
                canonical_image_manifest=image_manifest_path,
                epoch3_source_run=epoch3_source_run,
                selection_manifest=selection_manifest,
                provider_receipt=provider_receipt,
                provider_task_file=provider_task_file,
                receipt=receipt,
                code=code,
            )
            receipt_body = _json(receipt)
            plan_body = _json(plan)
            with PrivateDirectory.open(private_root, "private_root_invalid", create=True) as output_root:
                publication = output_root.publish(
                    [
                        (task_output, task_body),
                        (config_output, config_body),
                        (receipt_output, receipt_body),
                        (plan_output, plan_body),
                    ],
                    "materialization_publish_failed",
                )
            if (
                _private_read(selection_manifest, "selection_changed") != selection_body
                or _private_read(
                    selection_manifest.parent / "repair_tasks.txt",
                    "selection_changed",
                )
                != selection_task
                or _private_read(provider_receipt, "provider_input_changed") != provider_receipt_body
                or _private_read(provider_task_file, "provider_input_changed") != task_body
                or _read_regular(source_path, "canonical_input_changed") != source_body
                or _read_regular(template_path, "canonical_input_changed") != template_body
                or _read_owned_private_file(
                    image_manifest_path,
                    "canonical_input_changed",
                    max_bytes=2 << 20,
                )
                != image_manifest_body
                or _code_binding() != code
                or _validate_source_run(epoch3_source_run, held_root=source_root) != source_run
                or verify_canonical_dataset(dataset) != dataset
            ):
                raise SourceContinuationError("materialization_input_changed")
    except BaseException:
        if publication is not None:
            publication.rollback()
        raise
    if publication is None:
        raise SourceContinuationError("materialization_publish_failed")
    publication.commit()
    return {
        "state": "materialized",
        "task_count": CONTINUATION_COUNT,
        "retained_sandoq_count": SANDOQ_RETAINED_COUNT,
        "plan_sha256": _sha256(plan_body),
        "task_file_sha256": CONTINUATION_TASK_SHA256,
        "config_sha256": _sha256(config_body),
        "receipt_sha256": _sha256(receipt_body),
    }


def materialize(
    *,
    epoch3_source_run: Path,
    selection_manifest: Path,
    provider_receipt: Path,
    provider_task_file: Path,
    canonical_source: Path,
    canonical_dataset: Path,
    canonical_template: Path,
    private_root: Path,
    task_output: Path,
    config_output: Path,
    receipt_output: Path,
    plan_output: Path,
) -> dict[str, Any]:
    private_root = _normalized_absolute(private_root, "private_root_invalid")
    outputs = (task_output, config_output, receipt_output, plan_output)
    if len(set(outputs)) != len(outputs) or any(
        _normalized_absolute(path, "output_path_invalid").parent != private_root for path in outputs
    ):
        raise SourceContinuationError("output_path_invalid")
    selection_manifest = _normalized_absolute(selection_manifest, "selection_manifest_invalid")
    provider_receipt = _normalized_absolute(provider_receipt, "provider_receipt_invalid")
    provider_task_file = _normalized_absolute(provider_task_file, "provider_task_invalid")
    if selection_manifest.name != "repair_manifest.json":
        raise SourceContinuationError("selection_manifest_invalid")

    try:
        private_parent = private_root.parent.resolve(strict=True)
        candidate_root = private_parent / private_root.name
        protected = (
            Path(__file__).resolve().parents[3],
            _normalized_absolute(epoch3_source_run, "epoch3_source_invalid").resolve(strict=True),
            selection_manifest.parent.resolve(strict=True),
            provider_receipt.parent.resolve(strict=True),
            provider_task_file.parent.resolve(strict=True),
            _normalized_absolute(canonical_source, "canonical_source_invalid").resolve(strict=True).parent,
            _normalized_absolute(canonical_dataset, "canonical_dataset_invalid").resolve(strict=True),
            _normalized_absolute(canonical_template, "canonical_template_invalid").resolve(strict=True).parent,
        )
    except (OSError, RuntimeError) as error:
        raise SourceContinuationError("private_root_invalid") from error
    if (
        candidate_root != private_root
        or os.path.lexists(private_root)
        or any(
            candidate_root == item
            or candidate_root.is_relative_to(item)
            or item.is_relative_to(candidate_root)
            for item in protected
        )
    ):
        raise SourceContinuationError("private_root_invalid")

    selection_body = _private_read(selection_manifest, "selection_manifest_invalid")
    selection = _selection_value(selection_body)
    selection_task = _private_read(
        selection_manifest.parent / "repair_tasks.txt",
        "selection_task_invalid",
    )
    provider_receipt_body = _private_read(provider_receipt, "provider_receipt_invalid")
    provider_receipt_value = _provider_receipt_value(provider_receipt_body)
    task_body = _private_read(provider_task_file, "provider_task_invalid")
    if task_body != selection_task or _sha256(task_body) != CONTINUATION_TASK_SHA256:
        raise SourceContinuationError("provider_task_invalid")
    source_path, dataset, template_path, source_body, template_body = _canonical_paths(
        canonical_source,
        canonical_dataset,
        canonical_template,
    )
    image_manifest_path, image_manifest_body = _canonical_image_manifest(template_body)
    _validate_canonical_partition(
        source_body=source_body,
        dataset=dataset,
        task_body=task_body,
    )

    return _finish_materialization(
        epoch3_source_run=epoch3_source_run,
        selection_manifest=selection_manifest,
        selection_body=selection_body,
        selection=selection,
        selection_task=selection_task,
        provider_receipt=provider_receipt,
        provider_receipt_body=provider_receipt_body,
        provider_receipt_value=provider_receipt_value,
        provider_task_file=provider_task_file,
        task_body=task_body,
        source_path=source_path,
        source_body=source_body,
        dataset=dataset,
        template_path=template_path,
        template_body=template_body,
        image_manifest_path=image_manifest_path,
        image_manifest_body=image_manifest_body,
        private_root=private_root,
        task_output=task_output,
        config_output=config_output,
        receipt_output=receipt_output,
        plan_output=plan_output,
    )


def _validate_source_lineage(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "routing",
        "job_finality",
        "artifacts",
        "transition_artifacts",
    }:
        raise SourceContinuationError("plan_lineage_invalid")
    if value.get("routing") != EPOCH3_ROUTING:
        raise SourceContinuationError("plan_lineage_invalid")
    finality = value.get("job_finality")
    if (
        not isinstance(finality, Mapping)
        or set(finality) != {"all_terminal", "referenced_job_count"}
        or finality.get("all_terminal") is not True
        or not _plain_int(finality.get("referenced_job_count"))
        or finality["referenced_job_count"] < 1
    ):
        raise SourceContinuationError("plan_lineage_invalid")
    for field, expected in (
        ("artifacts", EPOCH3_ARTIFACTS),
        ("transition_artifacts", EPOCH_TRANSITION_ARTIFACTS),
    ):
        artifacts = value.get(field)
        if (
            not isinstance(artifacts, Mapping)
            or set(artifacts) != set(expected)
            or any(
                not isinstance(artifacts.get(name), Mapping)
                or set(artifacts[name]) != {"sha256", "size_bytes"}
                or artifacts[name].get("sha256") != digest
                or not _plain_int(artifacts[name].get("size_bytes"))
                or artifacts[name]["size_bytes"] < 1
                for name, digest in expected.items()
            )
        ):
            raise SourceContinuationError("plan_lineage_invalid")


def _validate_receipt(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "deployment_namespace",
            "lineage",
            "partition",
            "execution",
            "artifacts",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != RECEIPT_KIND
        or value.get("state") != "materialized"
        or value.get("deployment_namespace") != DEPLOYMENT_NAMESPACE
        or value.get("partition") != _partition_value()
        or value.get("execution") != EXECUTION_CONTRACT
    ):
        raise SourceContinuationError("materialization_receipt_invalid")
    lineage = value.get("lineage")
    if not isinstance(lineage, Mapping) or set(lineage) != {
        "selection",
        "epoch3_source",
        "provider_partition",
    }:
        raise SourceContinuationError("materialization_receipt_invalid")
    selection = lineage.get("selection")
    if (
        not isinstance(selection, Mapping)
        or set(selection)
        != {
            "manifest_sha256",
            "provider_receipt_sha256",
            "task_file_sha256",
            "selected_indices_sha256",
            "accepted_indices_sha256",
            "evaluator_order_sha256",
            "selection_trace_contracts",
            "continuation_trace_contract",
        }
        or selection.get("manifest_sha256") != SELECTION_MANIFEST_SHA256
        or selection.get("provider_receipt_sha256") != PROVIDER_RECEIPT_SHA256
        or selection.get("task_file_sha256") != CONTINUATION_TASK_SHA256
        or selection.get("selected_indices_sha256") != SELECTED_INDICES_SHA256
        or selection.get("accepted_indices_sha256") != ACCEPTED_INDICES_SHA256
        or selection.get("evaluator_order_sha256") != EVALUATOR_ORDER_SHA256
        or not isinstance(selection.get("selection_trace_contracts"), Mapping)
        or selection.get("continuation_trace_contract") != CONTINUATION_TRACE_CONTRACT
        or selection["selection_trace_contracts"].get("repair") == CONTINUATION_TRACE_CONTRACT
    ):
        raise SourceContinuationError("materialization_receipt_invalid")
    _validate_source_lineage(lineage.get("epoch3_source"))
    if lineage.get("provider_partition") != {
        "disjoint": True,
        "exhaustive": True,
        "sandoq_count": CONTINUATION_COUNT,
        "total_count": CONTINUATION_COUNT,
        "vmvm_count": 0,
    }:
        raise SourceContinuationError("materialization_receipt_invalid")
    artifacts = value.get("artifacts")
    if (
        not isinstance(artifacts, Mapping)
        or set(artifacts) != {"task_file", "config"}
        or artifacts.get("task_file", {}).get("sha256") != CONTINUATION_TASK_SHA256
        or any(
            not isinstance(artifacts.get(name), Mapping)
            or set(artifacts[name]) != {"sha256", "size_bytes"}
            or SHA256_RE.fullmatch(str(artifacts[name].get("sha256", ""))) is None
            or not _plain_int(artifacts[name].get("size_bytes"))
            or artifacts[name]["size_bytes"] < 1
            for name in ("task_file", "config")
        )
    ):
        raise SourceContinuationError("materialization_receipt_invalid")
    return value


@dataclass(frozen=True, slots=True)
class ValidatedPlan:
    value: dict[str, Any]
    sha256: str
    private_root: Path
    task_file: Path
    task_body: bytes
    config: Path
    config_body: bytes
    receipt: Path
    dataset: Path


def _record_path(record: object, code: str) -> Path:
    if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
        raise SourceContinuationError(code)
    return _normalized_absolute(Path(record["path"]), code)


def _validate_recorded_inputs(
    *,
    inputs: Mapping[str, Any],
    receipt: Mapping[str, Any],
    source_body: bytes,
    dataset: Path,
    source_root: PrivateDirectory | None = None,
) -> None:
    selection_path = _record_path(inputs.get("selection_manifest"), "plan_input_binding_invalid")
    provider_receipt_path = _record_path(
        inputs.get("provider_receipt"),
        "plan_input_binding_invalid",
    )
    provider_task_path = _record_path(
        inputs.get("provider_task_file"),
        "plan_input_binding_invalid",
    )
    epoch3_source = _record_path(
        {"path": inputs.get("epoch3_source_run")},
        "plan_input_binding_invalid",
    )
    if selection_path.name != "repair_manifest.json":
        raise SourceContinuationError("plan_input_binding_invalid")
    selection_body = _private_read(selection_path, "selection_manifest_invalid")
    selection = _selection_value(selection_body)
    selection_task = _private_read(
        selection_path.parent / "repair_tasks.txt",
        "selection_task_invalid",
    )
    provider_receipt_body = _private_read(provider_receipt_path, "provider_receipt_invalid")
    provider_receipt = _provider_receipt_value(provider_receipt_body)
    provider_task = _private_read(provider_task_path, "provider_task_invalid")
    source_run = _validate_source_run(epoch3_source, held_root=source_root)
    if (
        selection_task != provider_task
        or _sha256(provider_task) != CONTINUATION_TASK_SHA256
        or receipt.get("lineage")
        != _lineage_value(
            selection=selection,
            source_run=source_run,
            provider_receipt=provider_receipt,
        )
    ):
        raise SourceContinuationError("plan_input_binding_invalid")
    _validate_canonical_partition(
        source_body=source_body,
        dataset=dataset,
        task_body=provider_task,
    )


def validate_plan(
    *,
    plan: Path,
    plan_sha256: str,
    task_file: Path,
    task_file_sha256: str,
    config: Path,
    plan_root: PrivateDirectory | None = None,
    source_root: PrivateDirectory | None = None,
) -> ValidatedPlan:
    if SHA256_RE.fullmatch(plan_sha256 or "") is None:
        raise SourceContinuationError("plan_digest_invalid")
    plan = _normalized_absolute(plan, "plan_invalid")
    if plan_root is None:
        with PrivateDirectory.open(plan.parent, "private_root_invalid") as held_plan:
            return validate_plan(
                plan=plan,
                plan_sha256=plan_sha256,
                task_file=task_file,
                task_file_sha256=task_file_sha256,
                config=config,
                plan_root=held_plan,
                source_root=source_root,
            )
    if plan_root.path != plan.parent:
        raise SourceContinuationError("plan_invalid")
    plan_body = plan_root.read(plan.name, "plan_invalid")
    if _sha256(plan_body) != plan_sha256:
        raise SourceContinuationError("plan_digest_mismatch")
    value = _parse_json(plan_body, "plan_invalid", canonical=True)
    if (
        set(value)
        != {
            "schema_version",
            "kind",
            "state",
            "private_root",
            "inputs",
            "outputs",
            "materialization",
            "code",
        }
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("kind") != PLAN_KIND
        or value.get("state") != "materialized"
    ):
        raise SourceContinuationError("plan_invalid")
    root_record = value.get("private_root")
    inputs = value.get("inputs")
    outputs = value.get("outputs")
    if (
        not isinstance(root_record, Mapping)
        or set(root_record) != {"path", "mode"}
        or root_record.get("mode") != "0700"
        or not isinstance(inputs, Mapping)
        or set(inputs)
        != {
            "epoch3_source_run",
            "selection_manifest",
            "provider_receipt",
            "provider_task_file",
            "canonical_source",
            "canonical_dataset",
            "canonical_template",
            "canonical_image_manifest",
        }
        or not isinstance(outputs, Mapping)
        or set(outputs) != {"task_file", "config", "receipt", "plan"}
    ):
        raise SourceContinuationError("plan_invalid")
    private_root = _normalized_absolute(Path(str(root_record["path"])), "plan_invalid")
    plan_record_path = _record_path(outputs.get("plan"), "plan_invalid")
    planned_task = _record_path(outputs.get("task_file"), "plan_invalid")
    planned_config = _record_path(outputs.get("config"), "plan_invalid")
    planned_receipt = _record_path(outputs.get("receipt"), "plan_invalid")
    if (
        plan != plan_record_path
        or plan.parent != private_root
        or task_file != planned_task
        or config != planned_config
        or any(path.parent != private_root for path in (planned_task, planned_config, planned_receipt))
        or task_file_sha256 != CONTINUATION_TASK_SHA256
        or outputs["task_file"]
        != {
            "path": str(planned_task),
            "sha256": CONTINUATION_TASK_SHA256,
            "count": CONTINUATION_COUNT,
            "mode": "0600",
        }
        or outputs["plan"] != {"path": str(plan), "mode": "0600"}
    ):
        raise SourceContinuationError("plan_output_binding_invalid")
    receipt_value = _validate_receipt(value.get("materialization"))
    if outputs["config"] != {
        "path": str(planned_config),
        "sha256": receipt_value["artifacts"]["config"]["sha256"],
        "mode": "0600",
    } or outputs["receipt"] != {
        "path": str(planned_receipt),
        "sha256": _sha256(_json(receipt_value)),
        "mode": "0600",
    }:
        raise SourceContinuationError("plan_output_binding_invalid")
    canonical_source = _record_path(inputs.get("canonical_source"), "plan_input_binding_invalid")
    canonical_dataset = _record_path(inputs.get("canonical_dataset"), "plan_input_binding_invalid")
    canonical_template = _record_path(inputs.get("canonical_template"), "plan_input_binding_invalid")
    source_path, dataset, template_path, source_body, template_body = _canonical_paths(
        canonical_source,
        canonical_dataset,
        canonical_template,
    )
    image_manifest_path, image_manifest_body = _canonical_image_manifest(template_body)
    if (
        inputs["canonical_source"]
        != {
            "path": str(source_path),
            "sha256": CANONICAL_SOURCE_SHA256,
            "count": CANONICAL_SOURCE_COUNT,
        }
        or inputs["canonical_dataset"]
        != {
            "path": str(dataset),
            "revision": CANONICAL_DATASET_REVISION,
            "tree": CANONICAL_DATASET_TREE,
        }
        or inputs["canonical_template"] != {"path": str(template_path), "sha256": CANONICAL_SANDOQ_TEMPLATE_SHA256}
        or inputs["canonical_image_manifest"]
        != {
            "path": str(image_manifest_path),
            "sha256": CURRENT_IMAGE_MANIFEST_SHA256,
            "size_bytes": CURRENT_IMAGE_MANIFEST_SIZE,
            "mode": "0600",
        }
        or _sha256(source_body) != CANONICAL_SOURCE_SHA256
        or len(image_manifest_body) != CURRENT_IMAGE_MANIFEST_SIZE
    ):
        raise SourceContinuationError("plan_input_binding_invalid")
    for name, digest in (
        ("selection_manifest", SELECTION_MANIFEST_SHA256),
        ("provider_receipt", PROVIDER_RECEIPT_SHA256),
        ("provider_task_file", CONTINUATION_TASK_SHA256),
    ):
        record = inputs.get(name)
        _record_path(record, "plan_input_binding_invalid")
        if (
            not isinstance(record, Mapping)
            or set(record) != {"path", "sha256", "mode"}
            or record.get("sha256") != digest
            or record.get("mode") != "0600"
        ):
            raise SourceContinuationError("plan_input_binding_invalid")
    _validate_recorded_inputs(
        inputs=inputs,
        receipt=receipt_value,
        source_body=source_body,
        dataset=dataset,
        source_root=source_root,
    )
    if value.get("code") != _code_binding():
        raise SourceContinuationError("plan_code_changed")

    if plan_root.path != private_root:
        raise SourceContinuationError("private_root_invalid")
    task_body = plan_root.read(planned_task.name, "plan_task_invalid")
    config_body = plan_root.read(planned_config.name, "plan_config_invalid")
    receipt_body = plan_root.read(planned_receipt.name, "plan_receipt_invalid")
    current_plan = plan_root.read(plan.name, "plan_invalid")
    if (
        current_plan != plan_body
        or _sha256(task_body) != CONTINUATION_TASK_SHA256
        or len(_task_members(task_body, "plan_task_invalid", count=CONTINUATION_COUNT)) != CONTINUATION_COUNT
        or _sha256(config_body) != outputs["config"]["sha256"]
        or receipt_body != _json(receipt_value)
        or _sha256(receipt_body) != outputs["receipt"]["sha256"]
    ):
        raise SourceContinuationError("plan_artifact_invalid")
    try:
        expected_config = materialize_sandoq_config(
            template_body,
            planned_task,
            CONTINUATION_TASK_SHA256,
            task_count=CONTINUATION_COUNT,
        )
    except MixedMaterializationError as error:
        raise SourceContinuationError("plan_config_invalid") from error
    if config_body != expected_config:
        raise SourceContinuationError("plan_config_invalid")
    _validate_config(
        config_body,
        task_file=planned_task,
        dataset=dataset,
        image_manifest=image_manifest_path,
    )
    return ValidatedPlan(
        value=value,
        sha256=plan_sha256,
        private_root=private_root,
        task_file=planned_task,
        task_body=task_body,
        config=planned_config,
        config_body=config_body,
        receipt=planned_receipt,
        dataset=dataset,
    )


def _run_record_path(record: object, expected: Path) -> str:
    if not isinstance(record, Mapping) or record.get("path") != str(expected):
        raise SourceContinuationError("run_identity_binding_invalid")
    digest = record.get("sha256")
    if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
        raise SourceContinuationError("run_identity_binding_invalid")
    return digest


def _validate_run_identity(
    *,
    run: Path,
    root: PrivateDirectory,
    validated: ValidatedPlan,
    expected_snapshots: Mapping[str, ArtifactSnapshot],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot_context: tempfile.TemporaryDirectory[str] | None = None
    try:
        import eval_run_identity as eval_identity

        live_anchored = Path(f"/proc/self/fd/{root.descriptor}")
        snapshot_context = tempfile.TemporaryDirectory(prefix="qwen-continuation-evidence-")
        anchored = Path(snapshot_context.name)
        os.chmod(anchored, 0o700)
        for relative in (
            "eval_run_identity.json",
            "direct_workers.json",
            "config.toml",
            "provenance.txt",
            "inputs/manifest.json",
            "inputs/source_config.toml",
            "inputs/task_file.txt",
            "inputs/image_manifest.json",
        ):
            body = root.read(relative, "run_evidence_invalid")
            expected = expected_snapshots.get(relative)
            if expected is None or _sha256(body) != expected.sha256 or len(body) != expected.size:
                raise SourceContinuationError("run_evidence_invalid")
            destination = anchored / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(body)
            destination.chmod(0o600)
        envelope = eval_identity.load_eval_run_identity(
            anchored / "eval_run_identity.json",
            verify_references=False,
        )
        identity = envelope["identity"]
        config_section = identity["config"]
        inputs = identity["inputs"]
        deployment = identity["deployment"]
        source_config_sha = _run_record_path(
            config_section.get("source"),
            run / "inputs/source_config.toml",
        )
        _run_record_path(config_section.get("resolved"), run / "config.toml")
        _run_record_path(inputs.get("manifest"), run / "inputs/manifest.json")
        task_sha = _run_record_path(inputs.get("task_file"), run / "inputs/task_file.txt")
        image_sha = _run_record_path(inputs.get("image_manifest"), run / "inputs/image_manifest.json")
        worker_sha = _run_record_path(deployment.get("worker_manifest"), run / "direct_workers.json")
        expected_artifacts = {
            "eval_run_identity.json": expected_snapshots["eval_run_identity.json"].sha256,
            "config.toml": config_section["resolved"]["sha256"],
            "inputs/source_config.toml": source_config_sha,
            "inputs/manifest.json": inputs["manifest"]["sha256"],
            "inputs/task_file.txt": task_sha,
            "inputs/image_manifest.json": image_sha,
            "direct_workers.json": worker_sha,
        }
        for relative, expected in expected_artifacts.items():
            if expected_snapshots[relative].sha256 != expected:
                raise SourceContinuationError("run_artifact_invalid")
        if (
            inputs["task_file"].get("count") != CONTINUATION_COUNT
            or task_sha != CONTINUATION_TASK_SHA256
            or source_config_sha != _sha256(validated.config_body)
            or root.read("inputs/task_file.txt", "run_task_invalid") != validated.task_body
            or root.read("inputs/source_config.toml", "run_config_invalid") != validated.config_body
            or identity.get("role") != "qwen-direct"
            or identity.get("source", {}).get("sandbox_provider") != "sandoq"
            or identity.get("source", {}).get("prime_rl_commit") != validated.value["code"]["repository_revision"]
        ):
            raise SourceContinuationError("run_identity_binding_invalid")
        if (
            image_sha != CURRENT_IMAGE_MANIFEST_SHA256
            or image_sha != identity["source"].get("derived_image_manifest_sha256")
            or validated.value["inputs"]["canonical_image_manifest"].get("sha256") != CURRENT_IMAGE_MANIFEST_SHA256
        ):
            raise SourceContinuationError("run_identity_binding_invalid")
        eval_identity._verify_source_record(identity["source"])
        if verify_canonical_dataset(Path(identity["dataset"]["path"])) != validated.dataset:
            raise SourceContinuationError("run_identity_binding_invalid")
        resolved_config = eval_identity._load_resolved_config(anchored / "config.toml")
        observed_contract, observed_execution = eval_identity._contract(
            resolved_config,
            "Qwen3.8-2.4T-A95B",
            role="qwen-direct",
            sandbox_provider="sandoq",
        )
        observed_inputs, observed_source_config = eval_identity._input_identity(
            live_anchored / "inputs",
            resolved_config,
            CONTINUATION_TASK_SHA256,
            CONTINUATION_COUNT,
        )
        if (
            observed_contract != identity["contract"]
            or any(identity["execution"].get(key) != item for key, item in observed_execution.items())
            or observed_inputs != inputs
            or observed_source_config != config_section["source"]
            or observed_inputs["manifest"]["sha256"] != expected_snapshots["inputs/manifest.json"].sha256
            or observed_inputs["task_file"]["sha256"]
            != expected_snapshots["inputs/task_file.txt"].sha256
            or observed_inputs["image_manifest"]["sha256"]
            != expected_snapshots["inputs/image_manifest.json"].sha256
            or observed_source_config["sha256"]
            != expected_snapshots["inputs/source_config.toml"].sha256
            or Path(str(resolved_config.get("output_dir"))).resolve() != run.resolve(strict=True)
            or Path(str(resolved_config.get("taskset", {}).get("task_file"))).resolve(strict=True)
            != (run / "inputs/task_file.txt").resolve(strict=True)
            or resolved_config.get("taskset", {}).get("task_file_sha256") != CONTINUATION_TASK_SHA256
            or resolved_config.get("num_tasks") != CONTINUATION_COUNT
            or resolved_config.get("client", {}).get("base_url") != deployment.get("base_url")
        ):
            raise SourceContinuationError("run_identity_contract_invalid")
        eval_identity._verify_saved_provenance(
            anchored,
            identity,
            envelope["eval_run_identity_sha256"],
        )

        anchored_identity = copy.deepcopy(identity)
        anchored_identity["config"]["source"]["path"] = str(anchored / "inputs/source_config.toml")
        anchored_identity["inputs"]["task_file"]["path"] = str(anchored / "inputs/task_file.txt")
        anchored_identity["deployment"]["worker_manifest"]["path"] = str(anchored / "direct_workers.json")
        shared, execution = validate_shared_identity(
            anchored_identity,
            expected_provider="sandoq",
            expected_task_file=anchored / "inputs/task_file.txt",
            expected_task_sha256=CONTINUATION_TASK_SHA256,
            expected_count=CONTINUATION_COUNT,
            expected_config=anchored / "inputs/source_config.toml",
            expected_dataset=validated.dataset,
        )
    except SourceContinuationError:
        raise
    except Exception as error:
        raise SourceContinuationError("run_identity_invalid") from error
    finally:
        if snapshot_context is not None:
            snapshot_context.cleanup()
    if (
        shared.get("contract", {}).get("sampling_max_tokens") != EXECUTION_CONTRACT["sampling_max_tokens"]
        or shared.get("contract", {}).get("harness") != HOST_HARNESS_CONTRACT
        or shared.get("deployment", {}).get("worker_count") != 24
    ):
        raise SourceContinuationError("run_identity_contract_invalid")
    return envelope, shared, execution


def _validate_execution(execution: object) -> None:
    if not isinstance(execution, Mapping):
        raise SourceContinuationError("run_execution_invalid")
    environment = execution.get("sandoq_environment")
    runtime = execution.get("runtime")
    if (
        execution.get("cleanup_must_succeed") is not True
        or execution.get("rollout_concurrency") != EXECUTION_CONTRACT["rollout_concurrency"]
        or execution.get("multiplex") != EXECUTION_CONTRACT["multiplex"]
        or execution.get("http_max_connections") != EXECUTION_CONTRACT["http_max_connections"]
        or execution.get("http_max_keepalive_connections") != EXECUTION_CONTRACT["http_max_keepalive_connections"]
        or not isinstance(environment, Mapping)
        or environment.get("environment") != "oci-runner"
        or environment.get("task_network") != "public"
        or environment.get("pool_size") != EXECUTION_CONTRACT["pool_size"]
        or environment.get("pool_min_size") != EXECUTION_CONTRACT["pool_min_size"]
        or environment.get("tunnel_policy") != "host-interception-no-tunnel"
        or not isinstance(runtime, Mapping)
        or runtime.get("type") != "sandoq"
        or runtime.get("mode") != "oci-runner"
        or runtime.get("network_access") is not True
        or runtime.get("host_tunnel") != "none"
        or runtime.get("expected_environment") != "oci-runner"
    ):
        raise SourceContinuationError("run_execution_invalid")


def _continuation_identity(
    *,
    validated: ValidatedPlan,
    envelope: Mapping[str, Any],
    shared: Mapping[str, Any],
    provider_source: Mapping[str, Any],
    results_sha256: str,
    traces: Mapping[str, int],
    cleanup: Mapping[str, Any],
    cleanup_hashes: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": IDENTITY_KIND,
        "state": "passed",
        "plan_sha256": validated.sha256,
        "selection": "sealed-source-continuation",
        "partition": _partition_value(),
        "lineage": validated.value["materialization"]["lineage"],
        "run": {
            "task_count": CONTINUATION_COUNT,
            "task_file_sha256": CONTINUATION_TASK_SHA256,
            "config_sha256": _sha256(validated.config_body),
            "eval_run_identity_sha256": envelope["eval_run_identity_sha256"],
            "results_sha256": results_sha256,
            "worker_manifest_sha256": envelope["identity"]["deployment"]["worker_manifest"]["sha256"],
            "worker_count": 24,
            "trace_audit": traces,
            "pool_cleanup": cleanup,
            "sanitized_cleanup_source_hashes": cleanup_hashes,
        },
        "merge_contract": {
            "provider": "sandoq",
            "canonical_count": SANDOQ_COUNT,
            "retained_count": SANDOQ_RETAINED_COUNT,
            "replacement_count": CONTINUATION_COUNT,
            "disjoint": True,
            "exhaustive": True,
            "original_order_required": True,
            "replacement_policy": "pass-only-current-medium-trace-contract",
            "zero_reward_policy": "retain-scored-failures-without-export",
        },
        "shared_contract": shared,
        "shared_contract_sha256": sha256_bytes(_json(shared)),
        "provider_source": provider_source,
    }


def _certificate_value(
    *,
    validated: ValidatedPlan,
    identity_sha256: str,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    run = identity["run"]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": CERTIFICATE_KIND,
        "state": "passed",
        "sandbox_provider": "sandoq",
        "task_count": CONTINUATION_COUNT,
        "selection": "sealed-source-continuation",
        "plan_sha256": validated.sha256,
        "continuation_identity_sha256": identity_sha256,
        "eval_run_identity_sha256": run["eval_run_identity_sha256"],
        "results_sha256": run["results_sha256"],
        "worker_manifest_sha256": run["worker_manifest_sha256"],
        "worker_count": 24,
        "task_file_sha256": CONTINUATION_TASK_SHA256,
        "config_sha256": run["config_sha256"],
        "trace_audit": run["trace_audit"],
        "pool_cleanup": run["pool_cleanup"],
        "sanitized_cleanup_source_hashes": run["sanitized_cleanup_source_hashes"],
        "partition": identity["partition"],
        "lineage": identity["lineage"],
        "merge_contract": identity["merge_contract"],
        "shared_contract": identity["shared_contract"],
        "shared_contract_sha256": identity["shared_contract_sha256"],
        "provider_source": identity["provider_source"],
    }


def _run_evidence_snapshots(root: PrivateDirectory) -> dict[str, ArtifactSnapshot]:
    return {
        name: root.snapshot(name, "run_evidence_invalid")
        for name in (
            "eval_run_identity.json",
            "direct_workers.json",
            "results.jsonl",
            "sandoq_cleanup_audit.json",
            "config.toml",
            "provenance.txt",
            "inputs/manifest.json",
            "inputs/source_config.toml",
            "inputs/task_file.txt",
            "inputs/image_manifest.json",
        )
    }


def _audit_results_anchored(
    root: PrivateDirectory,
    expected_task_body: bytes,
) -> tuple[str, dict[str, int]]:
    if _sha256(expected_task_body) != CONTINUATION_TASK_SHA256:
        raise SourceContinuationError("continuation_evidence_invalid")
    try:
        expected = {
            line.strip().split("\t", 1)[0]
            for line in expected_task_body.decode("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    except UnicodeDecodeError as error:
        raise SourceContinuationError("continuation_evidence_invalid") from error
    if len(expected) != CONTINUATION_COUNT:
        raise SourceContinuationError("continuation_evidence_invalid")

    digest = hashlib.sha256()

    def traces(handle: Any) -> Iterator[dict[str, Any]]:
        for raw in handle:
            digest.update(raw)
            if not raw.strip():
                continue
            try:
                trace = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SourceContinuationError("continuation_evidence_invalid") from error
            if not isinstance(trace, dict):
                raise SourceContinuationError("continuation_evidence_invalid")
            yield trace

    with root.open_binary("results.jsonl", "continuation_evidence_invalid") as handle:
        summary, failed = _summarize_traces(
            traces(handle),
            expected_slugs=expected,
            expected_count=CONTINUATION_COUNT,
            rollouts_per_task=1,
            require_reasoning=True,
            require_token_data=False,
            require_logprobs=False,
            require_model_io=True,
            aggregate_only=True,
            model_io_contract=QWEN3_A95B_DIRECT_MEDIUM_MODEL_IO_CONTRACT,
            require_request_graph_match=True,
            max_sequence_tokens=FULL_CONTEXT_TOKENS,
        )
    if failed or summary.get("model_io_turns", 0) < CONTINUATION_COUNT:
        raise SourceContinuationError("continuation_evidence_invalid")
    allowed = (
        "traces",
        "tasks",
        "sampled_tokens",
        "model_io_turns",
        "provider_reported_zero_reasoning_tool_turns",
        "provider_explicit_empty_reasoning_tool_turns",
    )
    counts = {key: summary[key] for key in allowed}
    if any(not _plain_int(value) or value < 0 for value in counts.values()):
        raise SourceContinuationError("continuation_evidence_invalid")
    return digest.hexdigest(), counts


def _certify_bound(
    *,
    plan: Path,
    plan_sha256: str,
    run: Path,
    plan_root: PrivateDirectory,
    source_root: PrivateDirectory,
    run_root: PrivateDirectory,
    validated: ValidatedPlan,
    planned_task: Path,
    planned_config: Path,
    identity_output: Path,
    output: Path,
) -> tuple[PublishedOutputs, dict[str, Any]]:
    before = _run_evidence_snapshots(run_root)
    envelope, shared, execution = _validate_run_identity(
        run=run,
        root=run_root,
        validated=validated,
        expected_snapshots=before,
    )
    _validate_execution(execution)
    try:
        results_sha256, traces = _audit_results_anchored(run_root, validated.task_body)
        with run_root.open_binary(
            "sandoq_cleanup_audit.json",
            "continuation_evidence_invalid",
        ) as cleanup_handle:
            cleanup, cleanup_hashes = validate_cleanup(
                Path(f"/proc/self/fd/{cleanup_handle.fileno()}"),
                expected_task_count=CONTINUATION_COUNT,
                expected_concurrency=EXECUTION_CONTRACT["rollout_concurrency"],
            )
        provider_source = _provider_source(envelope["identity"])
    except Exception as error:
        raise SourceContinuationError("continuation_evidence_invalid") from error
    if (
        traces.get("traces") != CONTINUATION_COUNT
        or traces.get("tasks") != CONTINUATION_COUNT
        or traces.get("model_io_turns", 0) < CONTINUATION_COUNT
        or cleanup.get("assignment_attempts", 0) < CONTINUATION_COUNT
        or cleanup.get("failures") != 0
        or cleanup.get("zero_drop") is not True
        or results_sha256 != before["results.jsonl"].sha256
        or cleanup.get("audit_sha256") != before["sandoq_cleanup_audit.json"].sha256
        or envelope["identity"]["deployment"]["worker_manifest"]["sha256"] != before["direct_workers.json"].sha256
    ):
        raise SourceContinuationError("continuation_evidence_invalid")
    trace_proof = dict(traces)
    trace_proof.update(
        {
            "contract": CONTINUATION_TRACE_CONTRACT,
            "contract_passed": True,
            "error_traces": 0,
            "sequence_length_violations": 0,
        }
    )
    cleanup_proof = dict(cleanup)
    cleanup_proof["all_assignments_verified"] = True
    identity = _continuation_identity(
        validated=validated,
        envelope=envelope,
        shared=shared,
        provider_source=provider_source,
        results_sha256=results_sha256,
        traces=trace_proof,
        cleanup=cleanup_proof,
        cleanup_hashes=cleanup_hashes,
    )
    identity_body = _json(identity)
    identity_sha256 = _sha256(identity_body)
    certificate = _certificate_value(
        validated=validated,
        identity_sha256=identity_sha256,
        identity=identity,
    )
    certificate_body = _json(certificate)
    source_run = _validate_source_run(
        Path(validated.value["inputs"]["epoch3_source_run"]),
        held_root=source_root,
    )
    if source_run != validated.value["materialization"]["lineage"]["epoch3_source"]:
        raise SourceContinuationError("epoch3_source_changed")
    revalidated = validate_plan(
        plan=plan,
        plan_sha256=plan_sha256,
        task_file=planned_task,
        task_file_sha256=CONTINUATION_TASK_SHA256,
        config=planned_config,
        plan_root=plan_root,
        source_root=source_root,
    )
    after = _run_evidence_snapshots(run_root)
    if revalidated.value != validated.value or after != before:
        raise SourceContinuationError("source_changed_during_certification")
    run_root.validate("run_directory_changed")
    result = {
        "state": "passed",
        "task_count": CONTINUATION_COUNT,
        "identity_sha256": identity_sha256,
        "certificate_sha256": _sha256(certificate_body),
    }
    publication = run_root.publish(
        [(identity_output, identity_body), (output, certificate_body)],
        "certificate_publish_failed",
    )
    return publication, result


def certify(
    *,
    plan: Path,
    plan_sha256: str,
    run: Path,
    cleanup_audit: Path,
    identity_output: Path,
    output: Path,
) -> dict[str, Any]:
    plan = _normalized_absolute(plan, "plan_invalid")
    run = _normalized_absolute(run, "run_directory_invalid")
    cleanup_audit = _normalized_absolute(cleanup_audit, "cleanup_path_invalid")
    identity_output = _normalized_absolute(identity_output, "output_path_invalid")
    output = _normalized_absolute(output, "output_path_invalid")
    if (
        cleanup_audit != run / "sandoq_cleanup_audit.json"
        or identity_output != run / "source_continuation_identity.json"
        or output != run / "qwen_sandoq_source_continuation_certificate.json"
        or identity_output == output
    ):
        raise SourceContinuationError("output_or_cleanup_binding_invalid")
    publication: PublishedOutputs | None = None
    try:
        with PrivateDirectory.open(plan.parent, "private_root_invalid") as plan_root:
            plan_value = _parse_json(
                plan_root.read(plan.name, "plan_invalid"),
                "plan_invalid",
                canonical=True,
            )
            planned_task = _record_path(
                plan_value.get("outputs", {}).get("task_file"),
                "plan_invalid",
            )
            planned_config = _record_path(
                plan_value.get("outputs", {}).get("config"),
                "plan_invalid",
            )
            initial = validate_plan(
                plan=plan,
                plan_sha256=plan_sha256,
                task_file=planned_task,
                task_file_sha256=CONTINUATION_TASK_SHA256,
                config=planned_config,
                plan_root=plan_root,
            )
            source_path = Path(initial.value["inputs"]["epoch3_source_run"])
            with _hold_source_run(source_path) as source_root:
                validated = validate_plan(
                    plan=plan,
                    plan_sha256=plan_sha256,
                    task_file=planned_task,
                    task_file_sha256=CONTINUATION_TASK_SHA256,
                    config=planned_config,
                    plan_root=plan_root,
                    source_root=source_root,
                )
                with PrivateDirectory.open(run, "run_directory_invalid") as run_root, ExitStack() as locks:
                    run_root.lock(".writer.lock", locks, "run_lock_invalid")
                    publication, result = _certify_bound(
                        plan=plan,
                        plan_sha256=plan_sha256,
                        run=run,
                        plan_root=plan_root,
                        source_root=source_root,
                        run_root=run_root,
                        validated=validated,
                        planned_task=planned_task,
                        planned_config=planned_config,
                        identity_output=identity_output,
                        output=output,
                    )
    except BaseException:
        if publication is not None:
            publication.rollback()
        raise
    if publication is None:
        raise SourceContinuationError("certificate_publish_failed")
    publication.commit()
    return result


def _parser() -> StableArgumentParser:
    parser = StableArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    materializer = commands.add_parser("materialize")
    materializer.add_argument("--epoch3-source-run", type=Path, required=True)
    materializer.add_argument("--selection-manifest", type=Path, required=True)
    materializer.add_argument("--provider-receipt", type=Path, required=True)
    materializer.add_argument("--provider-task-file", type=Path, required=True)
    materializer.add_argument("--canonical-source", type=Path, required=True)
    materializer.add_argument("--canonical-dataset", type=Path, required=True)
    materializer.add_argument("--canonical-template", type=Path, required=True)
    materializer.add_argument("--private-root", type=Path, required=True)
    materializer.add_argument("--task-output", type=Path, required=True)
    materializer.add_argument("--config-output", type=Path, required=True)
    materializer.add_argument("--receipt-output", type=Path, required=True)
    materializer.add_argument("--plan-output", type=Path, required=True)

    validator = commands.add_parser("validate-plan")
    validator.add_argument("--plan", type=Path, required=True)
    validator.add_argument("--plan-sha256", required=True)
    validator.add_argument("--task-file", type=Path, required=True)
    validator.add_argument("--task-file-sha256", required=True)
    validator.add_argument("--config", type=Path, required=True)

    certifier = commands.add_parser("certify")
    certifier.add_argument("--plan", type=Path, required=True)
    certifier.add_argument("--plan-sha256", required=True)
    certifier.add_argument("--run", type=Path, required=True)
    certifier.add_argument("--cleanup-audit", type=Path, required=True)
    certifier.add_argument("--identity-output", type=Path, required=True)
    certifier.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "materialize":
            result = materialize(
                epoch3_source_run=args.epoch3_source_run,
                selection_manifest=args.selection_manifest,
                provider_receipt=args.provider_receipt,
                provider_task_file=args.provider_task_file,
                canonical_source=args.canonical_source,
                canonical_dataset=args.canonical_dataset,
                canonical_template=args.canonical_template,
                private_root=args.private_root,
                task_output=args.task_output,
                config_output=args.config_output,
                receipt_output=args.receipt_output,
                plan_output=args.plan_output,
            )
        elif args.command == "validate-plan":
            validated = validate_plan(
                plan=args.plan,
                plan_sha256=args.plan_sha256,
                task_file=args.task_file,
                task_file_sha256=args.task_file_sha256,
                config=args.config,
            )
            result = {
                "state": "valid",
                "task_count": CONTINUATION_COUNT,
                "plan_sha256": validated.sha256,
            }
        else:
            result = certify(
                plan=args.plan,
                plan_sha256=args.plan_sha256,
                run=args.run,
                cleanup_audit=args.cleanup_audit,
                identity_output=args.identity_output,
                output=args.output,
            )
    except SourceContinuationError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("source_continuation_failed") from None
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
