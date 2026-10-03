"""Deterministic materialization for private offline verifier catalogs.

The materializer delegates sandbox lifecycle operations to one immutable
worker executable.  The worker protocol has four operations:

``recover``
    Use the durable provider WAL to drain or retire every orphaned session
    and verify its cleanup receipt before any probe, build, or retry.

``probe``
    Start the exact dependency runtime image with networking disabled and
    return its compatibility fingerprint, complete installed distribution
    inventory, and exact requirement closure when already satisfied.

``build``
    In a trusted network-enabled builder, resolve or reproducibly build the
    complete wheel closure under the approved source/toolchain policy.  Write
    ``wheelhouse.tar`` to the supplied artifact directory and return its full
    manifest evidence.  A discovery request may return a universal closure;
    otherwise builds are repeated for every exact image.

``validate``
    Start a clean exact-image runtime with networking disabled, install the
    supplied wheelhouse with the declared no-index contract, run the closure
    probe, and verify process and sandbox cleanup.

The executable is invoked as::

    WORKER --request PATH --request-sha256 HEX \
        --response PATH --artifact-dir PATH

It must atomically create a canonical JSON response.  Worker stdout and stderr
are discarded so private task and dependency data cannot enter public logs.
Every response is bound to the request, executable, runtime attestation, and a
verified lifecycle record.  Completed response directories are reusable after
interruption; partial or ambiguous state fails closed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Literal, Mapping, Sequence

from terminal_bench_vmvm.offline_verifier_catalog import (
    _TASK_KEY_RE,
    CATALOG_SCHEMA_VERSION,
    CLOSURE_PROBE_CODE,
    IMAGE_INVENTORY_SCHEMA_VERSION,
    MAX_MANIFEST_BYTES,
    MAX_MARKER_ENVIRONMENT_KEYS,
    MAX_RUNTIME_TAGS,
    MAX_TASKS,
    MAX_TEXT_EVIDENCE_BYTES,
    RUNTIME_STAGING_ROOT,
    WHEELHOUSE_MANIFEST_SCHEMA_VERSION,
    CatalogIdentity,
    ExpectedTaskBinding,
    OfflineCatalogError,
    OfflineVerifierCatalog,
    RuntimeFingerprint,
    _allowlist_sha256,
    _canonical_private_json,
    _Closure,
    _deterministic_wheelhouse,
    _exact_keys,
    _fail,
    _FileSeal,
    _is_sha256,
    _parse_closure,
    _parse_toolchain,
    _Policy,
    _read_private_file,
    _sha256,
    _validate_closure,
    _validate_private_root,
    _validate_requirements,
    _validate_resolution_closure,
    _validate_root_requirements,
    _verified_source_digest,
    binding_plan_sha256,
    catalog_consumer_code_sha256,
    closure_probe_argv,
    closure_sha256,
    offline_install_argv,
    offline_install_environment,
    ordered_requirements_sha256,
    validate_runtime_staging_paths,
)
from terminal_bench_vmvm.source_wheels import (
    MAX_WHEELHOUSE_BYTES,
    atomic_write_bytes,
    canonical_json,
    is_digest_pinned_image,
    strict_json_loads,
)

MATERIALIZATION_PLAN_SCHEMA_VERSION = 2
WORKER_PROTOCOL_VERSION = 2
WORKER_COMPLETION_SCHEMA_VERSION = 1
PRIVATE_LAUNCH_RECEIPT_SCHEMA_VERSION = 2
MAX_PLAN_BYTES = 64 * 1024 * 1024
MAX_WORKER_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_WORKER_EXECUTABLE_BYTES = 256 * 1024 * 1024
MAX_CREDENTIAL_FILE_BYTES = 4 * 1024 * 1024
MAX_ROTATION_METADATA_BYTES = 64 * 1024
MAX_ROTATOR_HEARTBEAT_AGE_SECONDS = 300
MIN_ROTATING_CREDENTIAL_EXPIRY_MARGIN_SECONDS = 600
MAX_CLOCK_SKEW_SECONDS = 60
MAX_CONCURRENCY = 256
MAX_SHARED_POOL_PROBE_CONCURRENCY = 24
MAX_SHARED_POOL_BUILD_CONCURRENCY = 4
MAX_SHARED_POOL_VALIDATE_CONCURRENCY = 24
PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS = 5
MAX_TIMEOUT_SECONDS = 86_400
_RENAME_NOREPLACE = 1
_PR_SET_PDEATHSIG = 1
_LIBC = ctypes.CDLL(None, use_errno=True)

_ENVIRONMENT_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_ALLOWED_WORKER_ENVIRONMENT_NAMES = {
    "OCI_RUNNER_BASE_URL",
    "OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK",
    "OCI_RUNNER_CREATE_DEADLINE",
    "OCI_RUNNER_ECR_AUXILIARY_REGISTRIES",
    "OCI_RUNNER_ECR_CLIENT_CERT_PATH",
    "OCI_RUNNER_ECR_CREDENTIAL_TIMEOUT",
    "OCI_RUNNER_ECR_PULL_THROUGH_PREFIX",
    "OCI_RUNNER_ECR_REFRESH_INTERVAL",
    "OCI_RUNNER_ECR_REGION",
    "OCI_RUNNER_ECR_REGISTRY",
    "OCI_RUNNER_ECR_TOKEN_FILE",
    "OCI_RUNNER_ECR_TOKEN_METADATA_PATH",
    "OCI_RUNNER_ENVIRONMENT",
    "OCI_RUNNER_EXEC_TIMEOUT_CEILING",
    "OCI_RUNNER_GATEWAY_RETRY_ATTEMPTS",
    "OCI_RUNNER_GATEWAY_RETRY_INTERVAL",
    "OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES",
    "OCI_RUNNER_LEASE_DURATION",
    "OCI_RUNNER_OBSERVABILITY",
    "OCI_RUNNER_PODMAN_IGNORE_CHOWN_ERRORS",
    "OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE",
    "OCI_RUNNER_POOL_BOOTSTRAP_WORKERS",
    "OCI_RUNNER_POOL_CREATE_WORKERS",
    "OCI_RUNNER_POOL_DRAIN_TIMEOUT",
    "OCI_RUNNER_POOL_DRAIN_WORKERS",
    "OCI_RUNNER_POOL_EVENT_LOG",
    "OCI_RUNNER_POOL_HEARTBEAT_TIMEOUT",
    "OCI_RUNNER_POOL_MAX_REUSE_COUNT",
    "OCI_RUNNER_POOL_MIN_SIZE",
    "OCI_RUNNER_POOL_RENEW_INTERVAL",
    "OCI_RUNNER_POOL_RENEW_WORKERS",
    "OCI_RUNNER_POOL_REUSE_JITTER",
    "OCI_RUNNER_POOL_SIZE",
    "OCI_RUNNER_POOL_SOCKET",
    "OCI_RUNNER_POOL_WAL",
    "OCI_RUNNER_PULL_POLL_MAX_ERRORS",
    "OCI_RUNNER_PULL_TIMEOUT",
    "OCI_RUNNER_REQUIRE_RESOURCE_LIMITS",
    "OCI_RUNNER_SECRET_CACHE_TTL",
    "OCI_RUNNER_SESSION_REUSE",
    "OCI_RUNNER_TASK_NETWORK",
    "OCI_RUNNER_TASK_PIDS_LIMIT",
    "OCI_RUNNER_TOKEN_FILE",
    "PRIME_RL_OUTPUT_DIR",
    "REQUESTS_CA_BUNDLE",
    "SANDOQ_OWNER",
    "SLURM_JOB_ID",
    "SSL_CERT_FILE",
    "THRIFT_TLS_CL_CERT_PATH",
    "THRIFT_TLS_CL_KEY_PATH",
    "VF_SANDBOX_PROVIDER",
    "SANDOQ_CATALOG_WORKER_MODULE",
    "SANDOQ_CATALOG_WORKER_PYTHON",
    "SANDOQ_CATALOG_BUILDER_IMAGE",
    "SANDOQ_CATALOG_EXCLUSIVE_POOL",
    "SANDOQ_CATALOG_PYTHON_RUNTIME_MANIFEST_SHA256",
    "SANDOQ_CATALOG_WORKER_PROVISION_IDENTITY_SHA256",
    "SANDOQ_CATALOG_WORKER_SITE_MANIFEST",
    "SANDOQ_CATALOG_WORKER_SITE_MANIFEST_SHA256",
    "SANDOQ_CATALOG_WORKER_SITE_ROOT",
    "SANDOQ_PROVIDER_ROOT",
}
_WORKER_PATH_ENVIRONMENT_NAMES = {
    "OCI_RUNNER_ECR_CLIENT_CERT_PATH",
    "OCI_RUNNER_ECR_TOKEN_FILE",
    "OCI_RUNNER_ECR_TOKEN_METADATA_PATH",
    "OCI_RUNNER_POOL_EVENT_LOG",
    "OCI_RUNNER_POOL_SOCKET",
    "OCI_RUNNER_POOL_WAL",
    "OCI_RUNNER_TOKEN_FILE",
    "PRIME_RL_OUTPUT_DIR",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "THRIFT_TLS_CL_CERT_PATH",
    "THRIFT_TLS_CL_KEY_PATH",
    "SANDOQ_CATALOG_WORKER_MODULE",
    "SANDOQ_CATALOG_WORKER_PYTHON",
    "SANDOQ_CATALOG_WORKER_SITE_MANIFEST",
    "SANDOQ_CATALOG_WORKER_SITE_ROOT",
    "SANDOQ_PROVIDER_ROOT",
}
_WORKER_CREDENTIAL_FILE_ENVIRONMENT_NAMES = {
    "OCI_RUNNER_ECR_CLIENT_CERT_PATH",
    "OCI_RUNNER_ECR_TOKEN_FILE",
    "OCI_RUNNER_TOKEN_FILE",
    "THRIFT_TLS_CL_CERT_PATH",
    "THRIFT_TLS_CL_KEY_PATH",
}
_WORKER_ROTATING_CREDENTIAL_FILE_ENVIRONMENT_NAMES = {"OCI_RUNNER_ECR_TOKEN_FILE"}
_ECR_ROTATION_METADATA_ENVIRONMENT_NAME = "OCI_RUNNER_ECR_TOKEN_METADATA_PATH"
_WORKER_NONSECRET_METADATA_ENVIRONMENT_NAMES = {"OCI_RUNNER_SECRET_CACHE_TTL"}
_DIRECT_SECRET_NAME_RE = re.compile(r"(?:^|_)(?:API_KEY|ACCESS_KEY|BEARER|PASSWORD|PRIVATE_KEY|SECRET|TOKEN)(?:_|$)")
_PRIVATE_OUTPUT_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_REQUIRED_SANDOQ_ENVIRONMENT = {
    "OCI_RUNNER_ENVIRONMENT": "oci-runner-firecracker",
    "OCI_RUNNER_TASK_NETWORK": "none",
    "SANDOQ_CATALOG_EXCLUSIVE_POOL": "1",
    "VF_SANDBOX_PROVIDER": "sandoq",
}
_REQUIRED_SANDOQ_ENVIRONMENT_NAMES = frozenset(
    {
        *_REQUIRED_SANDOQ_ENVIRONMENT,
        "OCI_RUNNER_POOL_SOCKET",
        "OCI_RUNNER_POOL_WAL",
        "SANDOQ_CATALOG_EXCLUSIVE_POOL",
        "SANDOQ_OWNER",
    }
)


def _directory_identity(status: os.stat_result, code: str) -> tuple[int, int, int, int]:
    if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700 or status.st_uid != os.geteuid():
        _fail(code)
    return status.st_dev, status.st_ino, status.st_mode, status.st_uid


def _open_absolute_nofollow(path: Path, code: str) -> tuple[int, os.stat_result, str]:
    if (
        not path.is_absolute()
        or path.parent == path
        or ".." in path.parts
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in path.as_posix())
    ):
        _fail(code)
    descriptors: list[int] = []
    try:
        current = os.open(
            "/",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptors.append(current)
        root_status = os.fstat(current)
        ancestor_records = [
            {
                "device": root_status.st_dev,
                "inode": root_status.st_ino,
                "mode": root_status.st_mode,
                "owner": root_status.st_uid,
            }
        ]
        for part in path.parts[1:-1]:
            current = os.open(
                part,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            descriptors.append(current)
            current_status = os.fstat(current)
            if not stat.S_ISDIR(current_status.st_mode):
                _fail(code)
            ancestor_records.append(
                {
                    "device": current_status.st_dev,
                    "inode": current_status.st_ino,
                    "mode": current_status.st_mode,
                    "owner": current_status.st_uid,
                }
            )
        descriptor = os.open(
            path.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current,
        )
        status = os.fstat(descriptor)
    except OfflineCatalogError:
        if "descriptor" in locals():
            os.close(descriptor)
        for opened in reversed(descriptors):
            os.close(opened)
        raise
    except OSError as error:
        if "descriptor" in locals():
            os.close(descriptor)
        for opened in reversed(descriptors):
            os.close(opened)
        _fail(code, error)
    for opened in reversed(descriptors):
        os.close(opened)
    ancestor_sha256 = _sha256(canonical_json({"schema_version": 1, "ancestors": ancestor_records}))
    return descriptor, status, ancestor_sha256


def _credential_file_record(value: str) -> tuple[Path, os.stat_result, str]:
    path = Path(value)
    try:
        descriptor, status, ancestor_sha256 = _open_absolute_nofollow(path, "worker_credential_file_invalid")
        os.close(descriptor)
        if (
            not path.is_absolute()
            or path.as_posix() != value
            or ".." in path.parts
            or not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1
            or status.st_uid != os.geteuid()
            or stat.S_IMODE(status.st_mode) != 0o600
            or not 1 <= status.st_size <= MAX_CREDENTIAL_FILE_BYTES
        ):
            _fail("worker_credential_file_invalid")
    except OfflineCatalogError:
        raise
    except OSError as error:
        _fail("worker_credential_file_invalid", error)
    return path, status, ancestor_sha256


def _worker_environment_record(environment_names: Sequence[str]) -> tuple[dict[str, object], dict[str, str]]:
    names = tuple(environment_names)
    if (
        names != tuple(sorted(set(names)))
        or not _REQUIRED_SANDOQ_ENVIRONMENT_NAMES.issubset(names)
        or not all(
            isinstance(name, str)
            and _ENVIRONMENT_NAME_RE.fullmatch(name) is not None
            and name in _ALLOWED_WORKER_ENVIRONMENT_NAMES
            and (
                _DIRECT_SECRET_NAME_RE.search(name) is None
                or name in _WORKER_PATH_ENVIRONMENT_NAMES
                or name in _WORKER_NONSECRET_METADATA_ENVIRONMENT_NAMES
            )
            for name in names
        )
    ):
        _fail("worker_policy_invalid")
    ecr_token_enabled = "OCI_RUNNER_ECR_TOKEN_FILE" in names
    if ecr_token_enabled != (_ECR_ROTATION_METADATA_ENVIRONMENT_NAME in names):
        _fail("worker_policy_invalid")
    inherited: dict[str, str] = {}
    entries: list[dict[str, object]] = []
    for name in names:
        value = os.environ.get(name)
        if (
            value is None
            or not value
            or len(value.encode("utf-8")) > 4096
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
        ):
            _fail("worker_environment_missing")
        inherited[name] = value
        if name in _WORKER_PATH_ENVIRONMENT_NAMES:
            path = Path(value)
            if not path.is_absolute() or path.as_posix() != value or ".." in path.parts:
                _fail("worker_environment_invalid")
        if name in _WORKER_CREDENTIAL_FILE_ENVIRONMENT_NAMES:
            path, status, ancestor_sha256 = _credential_file_record(value)
            if name in _WORKER_ROTATING_CREDENTIAL_FILE_ENVIRONMENT_NAMES:
                evidence = {
                    "kind": "rotating-credential-file",
                    "path_sha256": _sha256(str(path).encode("utf-8")),
                    "owner": status.st_uid,
                    "mode": stat.S_IMODE(status.st_mode),
                    "links": status.st_nlink,
                    "ancestor_sha256": ancestor_sha256,
                }
            else:
                payload = _read_credential_file(path, status)
                evidence = {
                    "kind": "immutable-credential-file",
                    "path_sha256": _sha256(str(path).encode("utf-8")),
                    "device": status.st_dev,
                    "inode": status.st_ino,
                    "owner": status.st_uid,
                    "mode": stat.S_IMODE(status.st_mode),
                    "links": status.st_nlink,
                    "size": status.st_size,
                    "modified_ns": status.st_mtime_ns,
                    "changed_ns": status.st_ctime_ns,
                    "content_sha256": _sha256(payload),
                    "ancestor_sha256": ancestor_sha256,
                }
        elif name == _ECR_ROTATION_METADATA_ENVIRONMENT_NAME:
            path, status, ancestor_sha256 = _credential_file_record(value)
            evidence = {
                "kind": "rotation-metadata-file",
                "path_sha256": _sha256(str(path).encode("utf-8")),
                "owner": status.st_uid,
                "mode": stat.S_IMODE(status.st_mode),
                "links": status.st_nlink,
                "ancestor_sha256": ancestor_sha256,
            }
        else:
            evidence = {"kind": "value", "sha256": _sha256(value.encode("utf-8"))}
        entries.append({"name": name, "evidence": evidence})
    if any(inherited[name] != expected for name, expected in _REQUIRED_SANDOQ_ENVIRONMENT.items()):
        _fail("worker_environment_invalid")
    return {"schema_version": 1, "entries": entries}, inherited


def worker_environment_sha256(environment_names: Sequence[str]) -> str:
    """Return the redacted commitment for the exact inherited Sandoq configuration."""

    record, _ = _worker_environment_record(environment_names)
    return _sha256(canonical_json(record))


def worker_recovery_scope_sha256(environment_sha256: str) -> str:
    """Bind recovery to one redacted Sandoq owner and worker environment."""

    owner = os.environ.get("SANDOQ_OWNER")
    if (
        not _is_sha256(environment_sha256)
        or owner is None
        or not owner
        or len(owner.encode("utf-8")) > 4096
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in owner)
    ):
        _fail("worker_environment_invalid")
    return _sha256(
        canonical_json(
            {
                "schema_version": 1,
                "provider": "sandoq",
                "owner_sha256": _sha256(owner.encode("utf-8")),
                "environment_sha256": environment_sha256,
            }
        )
    )


def materializer_controller_code_sha256() -> str:
    """Hash this source-only controller and reject adjacent bytecode."""

    return _verified_source_digest((("offline_verifier_catalog_materializer", Path(__file__)),))


def _read_credential_file(
    path: Path,
    listed: os.stat_result,
    *,
    maximum: int = MAX_CREDENTIAL_FILE_BYTES,
) -> bytes:
    try:
        descriptor, opened, _ = _open_absolute_nofollow(path, "worker_credential_file_invalid")
        try:
            before = opened
            chunks: list[bytes] = []
            total = 0
            while chunk := os.read(descriptor, min(1024 * 1024, maximum + 1)):
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum:
                    _fail("worker_credential_file_invalid")
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        _fail("worker_credential_file_invalid", error)
    expected = (
        listed.st_dev,
        listed.st_ino,
        listed.st_mode,
        listed.st_nlink,
        listed.st_uid,
        listed.st_size,
        listed.st_mtime_ns,
        listed.st_ctime_ns,
    )
    if (
        not chunks
        or total != before.st_size
        or expected
        != (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_uid,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        or expected
        != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_uid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
    ):
        _fail("worker_credential_file_invalid")
    return b"".join(chunks)


def _rotation_audit_record(
    token_path: Path,
    metadata_path: Path,
    expected_rotator_sha256: str,
) -> dict[str, object]:
    _, token_status, _ = _credential_file_record(str(token_path))
    metadata_path, metadata_status, _ = _credential_file_record(str(metadata_path))
    payload = _read_credential_file(
        metadata_path,
        metadata_status,
        maximum=MAX_ROTATION_METADATA_BYTES,
    )
    try:
        raw = strict_json_loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        _fail("worker_credential_rotation_invalid", error)
    if not isinstance(raw, dict) or payload != canonical_json(raw):
        _fail("worker_credential_rotation_invalid")
    record = _exact_keys(
        raw,
        {
            "schema_version",
            "generation",
            "issued_at_unix",
            "heartbeat_at_unix",
            "expires_at_unix",
            "rotator_sha256",
            "token_file",
        },
        "worker_credential_rotation_invalid",
    )
    token = _exact_keys(
        record["token_file"],
        {
            "path_sha256",
            "device",
            "inode",
            "owner",
            "mode",
            "links",
            "size",
            "modified_ns",
            "changed_ns",
        },
        "worker_credential_rotation_invalid",
    )
    numeric = (
        record["schema_version"],
        record["generation"],
        record["issued_at_unix"],
        record["heartbeat_at_unix"],
        record["expires_at_unix"],
        token["device"],
        token["inode"],
        token["owner"],
        token["mode"],
        token["links"],
        token["size"],
        token["modified_ns"],
        token["changed_ns"],
    )
    now = int(time.time())
    observed_token = (
        token_status.st_dev,
        token_status.st_ino,
        token_status.st_uid,
        stat.S_IMODE(token_status.st_mode),
        token_status.st_nlink,
        token_status.st_size,
        token_status.st_mtime_ns,
        token_status.st_ctime_ns,
    )
    declared_token = (
        token["device"],
        token["inode"],
        token["owner"],
        token["mode"],
        token["links"],
        token["size"],
        token["modified_ns"],
        token["changed_ns"],
    )
    _, token_after, _ = _credential_file_record(str(token_path))
    if (
        not all(type(value) is int for value in numeric)
        or record["schema_version"] != 1
        or record["generation"] < 1
        or record["issued_at_unix"] < 0
        or record["heartbeat_at_unix"] < 0
        or record["expires_at_unix"] < 0
        or record["issued_at_unix"] > record["heartbeat_at_unix"]
        or record["heartbeat_at_unix"] > now + MAX_CLOCK_SKEW_SECONDS
        or now - record["heartbeat_at_unix"] > MAX_ROTATOR_HEARTBEAT_AGE_SECONDS
        or record["expires_at_unix"] - now < MIN_ROTATING_CREDENTIAL_EXPIRY_MARGIN_SECONDS
        or record["expires_at_unix"] <= record["heartbeat_at_unix"]
        or record["rotator_sha256"] != expected_rotator_sha256
        or token["path_sha256"] != _sha256(str(token_path).encode("utf-8"))
        or observed_token != declared_token
        or (
            token_after.st_dev,
            token_after.st_ino,
            token_after.st_uid,
            stat.S_IMODE(token_after.st_mode),
            token_after.st_nlink,
            token_after.st_size,
            token_after.st_mtime_ns,
            token_after.st_ctime_ns,
        )
        != observed_token
    ):
        _fail("worker_credential_rotation_invalid")
    return {
        "schema_version": 1,
        "metadata_sha256": _sha256(payload),
        "generation": record["generation"],
        "issued_at_unix": record["issued_at_unix"],
        "heartbeat_at_unix": record["heartbeat_at_unix"],
        "expires_at_unix": record["expires_at_unix"],
        "rotator_sha256": record["rotator_sha256"],
        "token_file": token,
    }


@dataclass(frozen=True)
class WorkerPolicy:
    executable_sha256: str
    runtime_sha256: str
    materializer_code_sha256: str
    cleanup_receipt_verifier_sha256: str
    environment_sha256: str
    recovery_scope_sha256: str
    ecr_rotator_sha256: str | None
    environment_names: tuple[str, ...]
    recovery_timeout_seconds: int
    probe_timeout_seconds: int
    build_timeout_seconds: int
    validate_timeout_seconds: int
    probe_concurrency: int
    build_concurrency: int
    validate_concurrency: int

    def record(self) -> dict[str, object]:
        return {
            "protocol_version": WORKER_PROTOCOL_VERSION,
            "executable_sha256": self.executable_sha256,
            "runtime_sha256": self.runtime_sha256,
            "materializer_code_sha256": self.materializer_code_sha256,
            "cleanup_receipt_verifier_sha256": self.cleanup_receipt_verifier_sha256,
            "environment_sha256": self.environment_sha256,
            "recovery_scope_sha256": self.recovery_scope_sha256,
            "ecr_rotator_sha256": self.ecr_rotator_sha256,
            "environment_names": list(self.environment_names),
            "timeouts_seconds": {
                "recover": self.recovery_timeout_seconds,
                "probe": self.probe_timeout_seconds,
                "build": self.build_timeout_seconds,
                "validate": self.validate_timeout_seconds,
            },
            "concurrency": {
                "probe": self.probe_concurrency,
                "build": self.build_concurrency,
                "validate": self.validate_concurrency,
            },
        }


@dataclass(frozen=True)
class MaterializationTask:
    task_key: str
    runtime_role: Literal["shared-agent", "separate-verifier"]
    image: str
    requirements: tuple[str, ...]
    requirements_sha256: str

    def expected_binding(self) -> ExpectedTaskBinding:
        return ExpectedTaskBinding(
            task_key=self.task_key,
            runtime_role=self.runtime_role,
            image=self.image,
            requirements=self.requirements,
        )


@dataclass(frozen=True)
class MaterializationPlan:
    path: Path
    seal: _FileSeal
    identity: CatalogIdentity
    policy: _Policy
    worker: WorkerPolicy
    expected_task_count: int
    tasks: tuple[MaterializationTask, ...]

    @classmethod
    def load(
        cls,
        path: Path,
        expected_sha256: str,
        *,
        project_root: Path,
        dataset_root: Path,
    ) -> "MaterializationPlan":
        if not path.is_absolute() or path.parent == path or not _is_sha256(expected_sha256):
            _fail("materialization_plan_path_invalid")
        root = _validate_private_root(path.parent, project_root, dataset_root)
        raw, seal = _canonical_private_json(
            root,
            path,
            expected_sha256,
            maximum=MAX_PLAN_BYTES,
            code="materialization_plan_invalid",
        )
        raw = _exact_keys(
            raw,
            {
                "schema_version",
                "identity",
                "identity_sha256",
                "policy",
                "worker",
                "expected_task_count",
                "tasks",
            },
            "materialization_plan_invalid",
        )
        identity = _parse_identity(raw["identity"])
        if (
            type(raw["schema_version"]) is not int
            or raw["schema_version"] != MATERIALIZATION_PLAN_SCHEMA_VERSION
            or raw["identity_sha256"] != identity.sha256
            or identity.catalog_consumer_code_sha256 != catalog_consumer_code_sha256()
        ):
            _fail("materialization_plan_invalid")
        policy = OfflineVerifierCatalog._parse_policy(raw["policy"], identity)
        worker = _parse_worker_policy(raw["worker"])
        expected_task_count = raw["expected_task_count"]
        if (
            isinstance(expected_task_count, bool)
            or not isinstance(expected_task_count, int)
            or not 1 <= expected_task_count <= MAX_TASKS
        ):
            _fail("materialization_plan_invalid")
        tasks = _parse_tasks(raw["tasks"])
        if (
            len(tasks) != expected_task_count
            or expected_task_count != identity.expected_task_count
            or binding_plan_sha256(task.expected_binding() for task in tasks) != identity.binding_plan_sha256
        ):
            _fail("materialization_plan_incomplete")
        return cls(
            path=path,
            seal=seal,
            identity=identity,
            policy=policy,
            worker=worker,
            expected_task_count=expected_task_count,
            tasks=tasks,
        )

    def revalidate(self) -> None:
        self.seal.read_verified(
            self.path.parent,
            maximum=MAX_PLAN_BYTES,
            code="materialization_plan_changed",
        )


@dataclass(frozen=True)
class ProbeResult:
    image: str
    requirements: tuple[str, ...]
    requirements_sha256: str
    runtime_fingerprint: RuntimeFingerprint
    marker_environment: dict[str, str]
    supported_tags: tuple[str, ...]
    installed_inventory: tuple[tuple[str, str], ...]
    installed_inventory_sha256: str
    satisfied: bool
    closure: _Closure | None


@dataclass(frozen=True)
class BuiltWheelhouse:
    scope: Literal["image", "universal"]
    image: str | None
    requirements: tuple[str, ...]
    requirements_sha256: str
    runtime_fingerprint: RuntimeFingerprint
    marker_environment: dict[str, str]
    supported_tags: tuple[str, ...]
    archive_path: Path
    archive_seal: _FileSeal
    archive_sha256: str
    manifest: dict[str, object]
    manifest_payload: bytes
    manifest_sha256: str
    closure: _Closure


@dataclass(frozen=True)
class WorkerResponse:
    result: dict[str, object]
    artifact_directory: Path


@dataclass
class ProviderAnchor:
    request_sha256: str
    run_nonce: str
    ready_path: Path
    stop_path: Path
    task: asyncio.Task[WorkerResponse]
    stopped: bool = False


def _parse_identity(value: object) -> CatalogIdentity:
    raw = _exact_keys(
        value,
        {
            "dataset_revision",
            "task_selection_sha256",
            "expected_task_count",
            "binding_plan_sha256",
            "catalog_consumer_code_sha256",
            "image_manifest_sha256",
            "requirements_extractor_sha256",
            "inventory_probe_code_sha256",
            "inventory_probe_environment_sha256",
            "inventory_probe_approval_sha256",
            "source_policy_sha256",
            "source_policy_approval_sha256",
            "approved_binary_artifacts_sha256",
            "approved_source_attestations_sha256",
            "approved_toolchains_sha256",
        },
        "materialization_identity_invalid",
    )
    try:
        return CatalogIdentity(**raw)  # type: ignore[arg-type]
    except TypeError as error:
        _fail("materialization_identity_invalid", error)


def _bounded_integer(value: object, maximum: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        _fail(code)
    return value


def _parse_worker_policy(value: object) -> WorkerPolicy:
    raw = _exact_keys(
        value,
        {
            "protocol_version",
            "executable_sha256",
            "runtime_sha256",
            "materializer_code_sha256",
            "cleanup_receipt_verifier_sha256",
            "environment_sha256",
            "recovery_scope_sha256",
            "ecr_rotator_sha256",
            "environment_names",
            "timeouts_seconds",
            "concurrency",
        },
        "worker_policy_invalid",
    )
    timeouts = _exact_keys(
        raw["timeouts_seconds"],
        {"recover", "probe", "build", "validate"},
        "worker_policy_invalid",
    )
    concurrency = _exact_keys(raw["concurrency"], {"probe", "build", "validate"}, "worker_policy_invalid")
    environment_names = raw["environment_names"]
    if (
        type(raw["protocol_version"]) is not int
        or raw["protocol_version"] != WORKER_PROTOCOL_VERSION
        or not _is_sha256(raw["executable_sha256"])
        or not _is_sha256(raw["runtime_sha256"])
        or raw["materializer_code_sha256"] != materializer_controller_code_sha256()
        or not _is_sha256(raw["cleanup_receipt_verifier_sha256"])
        or not _is_sha256(raw["environment_sha256"])
        or not _is_sha256(raw["recovery_scope_sha256"])
        or (raw["ecr_rotator_sha256"] is not None and not _is_sha256(raw["ecr_rotator_sha256"]))
        or not isinstance(environment_names, list)
        or environment_names != sorted(set(environment_names))
        or not all(
            isinstance(name, str)
            and _ENVIRONMENT_NAME_RE.fullmatch(name) is not None
            and name in _ALLOWED_WORKER_ENVIRONMENT_NAMES
            and (
                _DIRECT_SECRET_NAME_RE.search(name) is None
                or name in _WORKER_PATH_ENVIRONMENT_NAMES
                or name in _WORKER_NONSECRET_METADATA_ENVIRONMENT_NAMES
            )
            for name in environment_names
        )
        or not _REQUIRED_SANDOQ_ENVIRONMENT_NAMES.issubset(environment_names)
    ):
        _fail("worker_policy_invalid")
    if raw["environment_sha256"] != worker_environment_sha256(environment_names):
        _fail("worker_environment_changed")
    if raw["recovery_scope_sha256"] != worker_recovery_scope_sha256(str(raw["environment_sha256"])):
        _fail("worker_recovery_scope_invalid")
    ecr_enabled = "OCI_RUNNER_ECR_TOKEN_FILE" in environment_names
    if ecr_enabled != (_ECR_ROTATION_METADATA_ENVIRONMENT_NAME in environment_names) or ecr_enabled != (
        raw["ecr_rotator_sha256"] is not None
    ):
        _fail("worker_policy_invalid")
    probe_concurrency = _bounded_integer(concurrency["probe"], MAX_CONCURRENCY, "worker_policy_invalid")
    build_concurrency = _bounded_integer(concurrency["build"], MAX_CONCURRENCY, "worker_policy_invalid")
    validate_concurrency = _bounded_integer(concurrency["validate"], MAX_CONCURRENCY, "worker_policy_invalid")
    if "SANDOQ_CATALOG_EXCLUSIVE_POOL" in environment_names and (
        probe_concurrency > MAX_SHARED_POOL_PROBE_CONCURRENCY
        or build_concurrency > MAX_SHARED_POOL_BUILD_CONCURRENCY
        or validate_concurrency > MAX_SHARED_POOL_VALIDATE_CONCURRENCY
    ):
        # The materialization epoch owns one provider pool. Normal workers use
        # assignment-scoped release only; global recovery runs after all child
        # groups are extinct at phase boundaries.
        _fail("worker_shared_pool_concurrency_invalid")
    return WorkerPolicy(
        executable_sha256=str(raw["executable_sha256"]),
        runtime_sha256=str(raw["runtime_sha256"]),
        materializer_code_sha256=str(raw["materializer_code_sha256"]),
        cleanup_receipt_verifier_sha256=str(raw["cleanup_receipt_verifier_sha256"]),
        environment_sha256=str(raw["environment_sha256"]),
        recovery_scope_sha256=str(raw["recovery_scope_sha256"]),
        ecr_rotator_sha256=(str(raw["ecr_rotator_sha256"]) if raw["ecr_rotator_sha256"] is not None else None),
        environment_names=tuple(environment_names),
        recovery_timeout_seconds=_bounded_integer(
            timeouts["recover"],
            MAX_TIMEOUT_SECONDS,
            "worker_policy_invalid",
        ),
        probe_timeout_seconds=_bounded_integer(timeouts["probe"], MAX_TIMEOUT_SECONDS, "worker_policy_invalid"),
        build_timeout_seconds=_bounded_integer(timeouts["build"], MAX_TIMEOUT_SECONDS, "worker_policy_invalid"),
        validate_timeout_seconds=_bounded_integer(
            timeouts["validate"],
            MAX_TIMEOUT_SECONDS,
            "worker_policy_invalid",
        ),
        probe_concurrency=probe_concurrency,
        build_concurrency=build_concurrency,
        validate_concurrency=validate_concurrency,
    )


def _parse_tasks(value: object) -> tuple[MaterializationTask, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_TASKS:
        _fail("materialization_tasks_invalid")
    tasks: list[MaterializationTask] = []
    keys: list[str] = []
    for item in value:
        raw = _exact_keys(
            item,
            {
                "task_key",
                "runtime_role",
                "image",
                "requirements",
                "requirements_sha256",
                "binding_input_sha256",
            },
            "materialization_tasks_invalid",
        )
        task_key = raw["task_key"]
        runtime_role = raw["runtime_role"]
        image = raw["image"]
        requirements = _validate_requirements(raw["requirements"], "materialization_tasks_invalid")  # type: ignore[arg-type]
        requirement_digest = ordered_requirements_sha256(requirements)
        core = {key: raw[key] for key in raw if key != "binding_input_sha256"}
        if (
            not isinstance(task_key, str)
            or not task_key
            or len(task_key.encode("utf-8")) > 512
            or _TASK_KEY_RE.fullmatch(task_key) is None
            or task_key in keys
            or runtime_role not in {"shared-agent", "separate-verifier"}
            or not isinstance(image, str)
            or not is_digest_pinned_image(image)
            or raw["requirements_sha256"] != requirement_digest
            or raw["binding_input_sha256"] != _sha256(canonical_json(core))
        ):
            _fail("materialization_tasks_invalid")
        tasks.append(
            MaterializationTask(
                task_key=task_key,
                runtime_role=runtime_role,  # type: ignore[arg-type]
                image=image,
                requirements=requirements,
                requirements_sha256=requirement_digest,
            )
        )
        keys.append(task_key)
    if keys != sorted(keys):
        _fail("materialization_tasks_invalid")
    return tuple(tasks)


def materialization_plan_payload(
    *,
    identity: CatalogIdentity,
    worker: WorkerPolicy,
    approved_binary_artifacts: Sequence[str],
    approved_source_attestations: Sequence[str],
    approved_toolchains: Sequence[str],
    tasks: Iterable[ExpectedTaskBinding],
) -> bytes:
    """Create canonical private materialization input from extracted bindings."""

    if identity.catalog_consumer_code_sha256 != catalog_consumer_code_sha256():
        _fail("materialization_identity_invalid")
    parsed_worker = _parse_worker_policy(worker.record())
    if parsed_worker != worker:
        _fail("worker_policy_invalid")
    binaries = list(approved_binary_artifacts)
    sources = list(approved_source_attestations)
    toolchains = list(approved_toolchains)
    if (
        binaries != sorted(set(binaries))
        or not all(_is_sha256(value) for value in binaries)
        or _allowlist_sha256("binary-artifacts", binaries) != identity.approved_binary_artifacts_sha256
        or sources != sorted(set(sources))
        or not all(_is_sha256(value) for value in sources)
        or toolchains != sorted(set(toolchains))
        or not all(_is_sha256(value) for value in toolchains)
        or _allowlist_sha256("source-attestations", sources) != identity.approved_source_attestations_sha256
        or _allowlist_sha256("toolchains", toolchains) != identity.approved_toolchains_sha256
    ):
        _fail("materialization_policy_invalid")
    task_records: list[dict[str, object]] = []
    for task in tasks:
        requirements = _validate_requirements(task.requirements, "materialization_tasks_invalid")
        requirement_digest = ordered_requirements_sha256(requirements)
        core = {
            "task_key": task.task_key,
            "runtime_role": task.runtime_role,
            "image": task.image,
            "requirements": list(requirements),
            "requirements_sha256": requirement_digest,
        }
        task_records.append(
            {
                **core,
                "binding_input_sha256": _sha256(canonical_json(core)),
            }
        )
    task_records.sort(key=lambda item: str(item["task_key"]))
    parsed_tasks = _parse_tasks(task_records)
    if (
        len(parsed_tasks) != identity.expected_task_count
        or binding_plan_sha256(task.expected_binding() for task in parsed_tasks) != identity.binding_plan_sha256
    ):
        _fail("materialization_plan_incomplete")
    return canonical_json(
        {
            "schema_version": MATERIALIZATION_PLAN_SCHEMA_VERSION,
            "identity": identity.record(),
            "identity_sha256": identity.sha256,
            "policy": {
                "source_policy_sha256": identity.source_policy_sha256,
                "source_policy_approval_sha256": identity.source_policy_approval_sha256,
                "approved_binary_artifacts": binaries,
                "approved_binary_artifacts_sha256": identity.approved_binary_artifacts_sha256,
                "approved_source_attestations": sources,
                "approved_source_attestations_sha256": identity.approved_source_attestations_sha256,
                "approved_toolchains": toolchains,
                "approved_toolchains_sha256": identity.approved_toolchains_sha256,
            },
            "worker": worker.record(),
            "expected_task_count": len(task_records),
            "tasks": task_records,
        }
    )


@dataclass(frozen=True)
class _ExecutableSeal:
    path: Path
    device: int
    inode: int
    mode: int
    links: int
    size: int
    modified_ns: int
    changed_ns: int
    sha256: str

    def _matches(self, status: os.stat_result) -> bool:
        return (
            status.st_dev,
            status.st_ino,
            status.st_mode,
            status.st_nlink,
            status.st_size,
            status.st_mtime_ns,
            status.st_ctime_ns,
        ) == (
            self.device,
            self.inode,
            self.mode,
            self.links,
            self.size,
            self.modified_ns,
            self.changed_ns,
        )

    def open_verified_fd(self) -> int:
        try:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            before = os.fstat(descriptor)
            if not self._matches(before):
                _fail("worker_executable_changed")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            after = os.fstat(descriptor)
            if not self._matches(after) or digest.hexdigest() != self.sha256:
                _fail("worker_executable_changed")
            os.lseek(descriptor, 0, os.SEEK_SET)
            return descriptor
        except OfflineCatalogError:
            if "descriptor" in locals():
                os.close(descriptor)
            raise
        except OSError as error:
            if "descriptor" in locals():
                os.close(descriptor)
            _fail("worker_executable_changed", error)

    def read_verified(self) -> bytes:
        descriptor = self.open_verified_fd()
        try:
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @classmethod
    def load(cls, path: Path, expected_sha256: str) -> "_ExecutableSeal":
        if not path.is_absolute() or path.parent == path or not _is_sha256(expected_sha256):
            _fail("worker_executable_invalid")
        try:
            if path.resolve(strict=True) != path:
                _fail("worker_executable_invalid")
            listed = path.lstat()
            if (
                not stat.S_ISREG(listed.st_mode)
                or listed.st_nlink != 1
                or listed.st_mode & 0o111 == 0
                or listed.st_mode & 0o022
                or not 1 <= listed.st_size <= MAX_WORKER_EXECUTABLE_BYTES
            ):
                _fail("worker_executable_invalid")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                before = os.fstat(descriptor)
                digest = hashlib.sha256()
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
        except OfflineCatalogError:
            raise
        except OSError as error:
            _fail("worker_executable_invalid", error)
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        if identity != (
            listed.st_dev,
            listed.st_ino,
            listed.st_mode,
            listed.st_nlink,
            listed.st_size,
            listed.st_mtime_ns,
            listed.st_ctime_ns,
        ) or identity != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            _fail("worker_executable_invalid")
        observed = digest.hexdigest()
        if observed != expected_sha256:
            _fail("worker_executable_invalid")
        return cls(
            path=path,
            device=before.st_dev,
            inode=before.st_ino,
            mode=before.st_mode,
            links=before.st_nlink,
            size=before.st_size,
            modified_ns=before.st_mtime_ns,
            changed_ns=before.st_ctime_ns,
            sha256=observed,
        )

    def revalidate(self) -> None:
        try:
            observed = type(self).load(self.path, self.sha256)
        except OfflineCatalogError as error:
            _fail("worker_executable_changed", error)
        if observed != self:
            _fail("worker_executable_changed")


def _private_directory(path: Path, code: str) -> Path:
    try:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            _fail(code)
        status = path.lstat()
    except OfflineCatalogError:
        raise
    except OSError as error:
        _fail(code, error)
    if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700:
        _fail(code)
    return path


def _ensure_private_subdirectory(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        _fail("materialization_work_path_invalid")
    current = root
    for part in relative.parts:
        current /= part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        try:
            status = current.lstat()
        except OSError as error:
            _fail("materialization_work_path_invalid", error)
        if not stat.S_ISDIR(status.st_mode) or stat.S_IMODE(status.st_mode) != 0o700:
            _fail("materialization_work_path_invalid")
    return current


class _ExclusiveFileLock:
    def __init__(self, path: Path, code: str, *, directory_descriptor: int | None = None) -> None:
        self.path = path
        self.code = code
        self.directory_descriptor = directory_descriptor
        self.descriptor: int | None = None

    def __enter__(self) -> "_ExclusiveFileLock":
        try:
            target: str | Path = self.path
            if self.directory_descriptor is not None:
                if self.path.name in {"", ".", ".."}:
                    _fail(self.code)
                target = self.path.name
            descriptor = os.open(
                target,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self.directory_descriptor,
            )
            status = os.fstat(descriptor)
            if (
                not stat.S_ISREG(status.st_mode)
                or stat.S_IMODE(status.st_mode) != 0o600
                or status.st_nlink != 1
                or status.st_uid != os.geteuid()
            ):
                os.close(descriptor)
                _fail(self.code)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                os.close(descriptor)
                _fail(self.code, error)
            if self.directory_descriptor is not None:
                listed = os.stat(
                    self.path.name,
                    dir_fd=self.directory_descriptor,
                    follow_symlinks=False,
                )
                if (listed.st_dev, listed.st_ino) != (status.st_dev, status.st_ino):
                    os.close(descriptor)
                    _fail(self.code)
        except OfflineCatalogError:
            raise
        except OSError as error:
            _fail(self.code, error)
        self.descriptor = descriptor
        return self

    def __exit__(self, *_args: object) -> None:
        assert self.descriptor is not None
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self.descriptor = None


def _configure_worker_child(parent_pid: int) -> None:
    if _LIBC.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
        os._exit(127)
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def _process_start_ticks(pid: int) -> int | None:
    try:
        payload = Path(f"/proc/{pid}/stat").read_text()
        fields = payload[payload.rfind(")") + 2 :].split()
        value = int(fields[19])
        return value if value > 0 else None
    except (OSError, ValueError, IndexError):
        return None


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _wait_process_group_extinct(process_group: int, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while _process_group_exists(process_group):
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return True


async def _terminate_process_group(process_group: int) -> None:
    if process_group <= 1 or process_group == os.getpgrp():
        _fail("worker_process_group_invalid")
    if _process_group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if await _wait_process_group_extinct(process_group, 10):
        return
    try:
        os.killpg(process_group, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if not await _wait_process_group_extinct(process_group, 10):
        _fail("worker_process_group_cleanup_failed")


async def _terminate_stale_process_group(process_group: int, pid: int) -> None:
    if process_group <= 1 or process_group == os.getpgrp():
        _fail("worker_process_group_invalid")
    for requested_signal in (signal.SIGTERM, signal.SIGKILL):
        if _process_group_exists(process_group):
            try:
                os.killpg(process_group, requested_signal)
            except ProcessLookupError:
                pass
        for _ in range(200):
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            if not _process_group_exists(process_group):
                return
            await asyncio.sleep(0.05)
    _fail("worker_process_group_cleanup_failed")


async def _drain_task(task: asyncio.Future):
    """Wait for *task* without detaching it, and report outer cancellation.

    ``asyncio.shield`` prevents each cancellation of the current task from
    propagating into the cleanup task.  Cancellation is deliberately reported
    to the caller rather than swallowed: callers must finish their local/WAL
    bookkeeping and then propagate it.
    """

    waiter = asyncio.current_task()
    cancellation_depth = waiter.cancelling() if waiter is not None else 0
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            interrupted = True
        except BaseException:
            # A shielded task reports its own terminal exception from this
            # await.  Defer it to task.result() below so a cancellation already
            # observed by this waiter remains the primary outcome.
            if not task.done():
                raise
            break
    if waiter is not None and waiter.cancelling() > cancellation_depth:
        interrupted = True
    try:
        return task.result(), interrupted
    except BaseException as error:
        if interrupted and not isinstance(error, asyncio.CancelledError):
            raise asyncio.CancelledError from error
        raise


class WorkerRunner:
    def __init__(self, executable: Path, policy: WorkerPolicy, work_root: Path) -> None:
        self.policy = policy
        self.work_root = work_root
        self._recovery_lock = asyncio.Lock()
        source_executable = _ExecutableSeal.load(executable, policy.executable_sha256)
        executable_payload = source_executable.read_verified()
        executable_directory = _ensure_private_subdirectory(
            work_root,
            Path("worker") / policy.executable_sha256[:2],
        )
        staged_executable = executable_directory / policy.executable_sha256
        if staged_executable.exists():
            staged = _ExecutableSeal.load(staged_executable, policy.executable_sha256)
            if staged.read_verified() != executable_payload:
                _fail("worker_executable_changed")
        else:
            atomic_write_bytes(staged_executable, executable_payload, mode=0o500)
            staged = _ExecutableSeal.load(staged_executable, policy.executable_sha256)
        if any(entry != staged_executable for entry in executable_directory.iterdir()):
            _fail("worker_staging_not_isolated")
        source_executable.revalidate()
        self.executable = staged
        bytecode_root = _ensure_private_subdirectory(work_root, Path("python-bytecode-disabled"))
        if any(bytecode_root.iterdir()):
            _fail("worker_bytecode_present")
        environment = {
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPYCACHEPREFIX": str(bytecode_root),
            "PYTHONSAFEPATH": "1",
        }
        environment_record, inherited = _worker_environment_record(policy.environment_names)
        if _sha256(canonical_json(environment_record)) != policy.environment_sha256:
            _fail("worker_environment_changed")
        environment.update(inherited)
        self._inherited_environment = inherited
        self._credential_seals: list[_FileSeal] = []
        immutable_credentials = (
            _WORKER_CREDENTIAL_FILE_ENVIRONMENT_NAMES - _WORKER_ROTATING_CREDENTIAL_FILE_ENVIRONMENT_NAMES
        ).intersection(policy.environment_names)
        immutable_credential_evidence = {
            str(entry["name"]): entry["evidence"]  # type: ignore[index]
            for entry in environment_record["entries"]  # type: ignore[union-attr]
            if entry["name"] in immutable_credentials  # type: ignore[index]
        }
        self._rotating_credentials = {
            name: Path(inherited[name])
            for name in _WORKER_ROTATING_CREDENTIAL_FILE_ENVIRONMENT_NAMES.intersection(policy.environment_names)
        }
        if immutable_credentials:
            credential_root = _ensure_private_subdirectory(work_root, Path("credentials"))
            for name in sorted(immutable_credentials):
                source_path, listed, ancestor_sha256 = _credential_file_record(inherited[name])
                expected_credential = immutable_credential_evidence[name]
                if (
                    ancestor_sha256 != expected_credential["ancestor_sha256"]  # type: ignore[index]
                    or listed.st_dev != expected_credential["device"]  # type: ignore[index]
                    or listed.st_ino != expected_credential["inode"]  # type: ignore[index]
                    or stat.S_IMODE(listed.st_mode) != expected_credential["mode"]  # type: ignore[index]
                    or listed.st_nlink != expected_credential["links"]  # type: ignore[index]
                    or listed.st_uid != expected_credential["owner"]  # type: ignore[index]
                    or listed.st_size != expected_credential["size"]  # type: ignore[index]
                    or listed.st_mtime_ns != expected_credential["modified_ns"]  # type: ignore[index]
                    or listed.st_ctime_ns != expected_credential["changed_ns"]  # type: ignore[index]
                ):
                    _fail("worker_credential_file_changed")
                payload = _read_credential_file(source_path, listed)
                if _sha256(payload) != expected_credential["content_sha256"]:  # type: ignore[index]
                    _fail("worker_credential_file_changed")
                staged_path = credential_root / _sha256(name.encode("utf-8"))
                if os.path.lexists(staged_path):
                    observed, seal = _read_private_file(
                        work_root,
                        staged_path,
                        maximum=MAX_CREDENTIAL_FILE_BYTES,
                        code="worker_credential_file_changed",
                    )
                    if observed != payload:
                        _fail("worker_credential_file_changed")
                else:
                    atomic_write_bytes(staged_path, payload, mode=0o600)
                    _, seal = _read_private_file(
                        work_root,
                        staged_path,
                        maximum=MAX_CREDENTIAL_FILE_BYTES,
                        code="worker_credential_file_changed",
                    )
                self._credential_seals.append(seal)
                environment[name] = str(staged_path)
        self.environment = environment
        self._local_process_root = _ensure_private_subdirectory(work_root, Path("local-processes"))
        self._active_processes: dict[int, asyncio.subprocess.Process] = {}
        self._active_anchor_processes: set[int] = set()
        self._provider_epoch_active = False
        self._provider_epoch_directories: tuple[
            tuple[Path, tuple[int, int, int, int]], ...
        ] = ()

    @contextlib.contextmanager
    def provider_epoch(self):
        """Exclusively own both the configured broker socket and durable WAL."""

        if self._provider_epoch_active:
            _fail("materialization_epoch_invalid")
        source_paths = (
            Path(self._inherited_environment["OCI_RUNNER_POOL_SOCKET"]),
            Path(self._inherited_environment["OCI_RUNNER_POOL_WAL"]),
        )
        lock_paths = tuple(
            sorted(path.with_name(f".{path.name}.catalog-epoch.lock") for path in source_paths)
        )
        if len(set(lock_paths)) != 2:
            _fail("materialization_epoch_invalid")
        with contextlib.ExitStack() as stack:
            locked_directories: list[tuple[Path, tuple[int, int, int, int]]] = []
            for lock_path in lock_paths:
                descriptor, status, _ = _open_absolute_nofollow(
                    lock_path.parent,
                    "materialization_epoch_invalid",
                )
                stack.callback(os.close, descriptor)
                directory_identity = _directory_identity(
                    status,
                    "materialization_epoch_invalid",
                )
                stack.enter_context(
                    _ExclusiveFileLock(
                        lock_path,
                        "materialization_epoch_locked",
                        directory_descriptor=descriptor,
                    )
                )
                _revalidate_directory_path(
                    lock_path.parent,
                    directory_identity,
                    "materialization_epoch_invalid",
                )
                locked_directories.append((lock_path.parent, directory_identity))
            self._provider_epoch_active = True
            self._provider_epoch_directories = tuple(locked_directories)
            try:
                yield
            finally:
                try:
                    for directory, identity in self._provider_epoch_directories:
                        _revalidate_directory_path(
                            directory,
                            identity,
                            "materialization_epoch_invalid",
                        )
                finally:
                    self._provider_epoch_active = False
                    self._provider_epoch_directories = ()

    def require_provider_epoch(self) -> None:
        if not self._provider_epoch_active or len(self._provider_epoch_directories) != 2:
            _fail("materialization_epoch_not_held")
        for directory, identity in self._provider_epoch_directories:
            _revalidate_directory_path(
                directory,
                identity,
                "materialization_epoch_invalid",
            )

    def _revalidate_environment(self) -> None:
        record, inherited = _worker_environment_record(self.policy.environment_names)
        if (
            _sha256(canonical_json(record)) != self.policy.environment_sha256
            or inherited != self._inherited_environment
        ):
            _fail("worker_environment_changed")
        for seal in self._credential_seals:
            seal.read_verified(
                self.work_root,
                maximum=MAX_CREDENTIAL_FILE_BYTES,
                code="worker_credential_file_changed",
            )

    def _credential_rotation_sha256(self) -> str:
        entries: list[dict[str, object]] = []
        for name, expected_path in sorted(self._rotating_credentials.items()):
            path, _, _ = _credential_file_record(self._inherited_environment[name])
            if path != expected_path:
                _fail("worker_environment_changed")
            metadata_path = Path(self._inherited_environment[_ECR_ROTATION_METADATA_ENVIRONMENT_NAME])
            if self.policy.ecr_rotator_sha256 is None:
                _fail("worker_credential_rotation_invalid")
            entries.append(
                {
                    "name": name,
                    "audit": _rotation_audit_record(
                        path,
                        metadata_path,
                        self.policy.ecr_rotator_sha256,
                    ),
                }
            )
        return _sha256(canonical_json({"schema_version": 1, "entries": entries}))

    def _bind_rotation_audit(self, request: dict[str, object]) -> dict[str, object]:
        bound = dict(request)
        worker = dict(
            _exact_keys(
                request.get("worker"),
                {
                    "executable_sha256",
                    "runtime_sha256",
                    "materializer_code_sha256",
                    "cleanup_receipt_verifier_sha256",
                    "environment_sha256",
                    "recovery_scope_sha256",
                    "ecr_rotator_sha256",
                },
                "worker_request_invalid",
            )
        )
        worker["credential_rotation_sha256"] = self._credential_rotation_sha256()
        bound["worker"] = worker
        return bound

    async def _record_process(
        self,
        request_sha256: str,
        process: asyncio.subprocess.Process,
        response_path: Path,
    ) -> Path | None:
        start_ticks = _process_start_ticks(process.pid)
        try:
            process_group = os.getpgid(process.pid)
        except OSError:
            process_group = None
        if start_ticks is None or process_group != process.pid:
            await asyncio.sleep(0)
            if (
                process.returncode == 0
                and os.path.lexists(response_path)
                and await _wait_process_group_extinct(process.pid, 0.25)
            ):
                return None
            _fail("worker_process_identity_invalid")
        path = self._local_process_root / f"{request_sha256}.json"
        if os.path.lexists(path):
            _fail("worker_process_record_exists")
        atomic_write_bytes(
            path,
            canonical_json(
                {
                    "schema_version": 1,
                    "request_sha256": request_sha256,
                    "recovery_scope_sha256": self.policy.recovery_scope_sha256,
                    "pid": process.pid,
                    "process_group": process_group,
                    "start_ticks": start_ticks,
                }
            ),
            mode=0o400,
        )
        return path

    def _remove_process_record(self, path: Path) -> None:
        try:
            path.unlink()
            descriptor = os.open(
                self._local_process_root,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            _fail("worker_process_record_cleanup_failed", error)

    async def recover_stale_local_processes(self) -> None:
        interrupted = False
        try:
            for pid in sorted(self._active_processes):
                if pid in self._active_anchor_processes:
                    continue
                process = self._active_processes[pid]
                cleanup_task = asyncio.create_task(_terminate_process(process))
                _, cleanup_interrupted = await _drain_task(cleanup_task)
                interrupted = interrupted or cleanup_interrupted
                self._active_processes.pop(pid)
            for path in sorted(self._local_process_root.iterdir()):
                payload, _ = _read_private_file(
                    self.work_root,
                    path,
                    maximum=MAX_WORKER_RESPONSE_BYTES,
                    code="worker_process_record_invalid",
                )
                try:
                    raw = strict_json_loads(payload)
                except (TypeError, ValueError, json.JSONDecodeError) as error:
                    _fail("worker_process_record_invalid", error)
                if not isinstance(raw, dict) or payload != canonical_json(raw):
                    _fail("worker_process_record_invalid")
                record = _exact_keys(
                    raw,
                    {
                        "schema_version",
                        "request_sha256",
                        "recovery_scope_sha256",
                        "pid",
                        "process_group",
                        "start_ticks",
                    },
                    "worker_process_record_invalid",
                )
                pid = record["pid"]
                process_group = record["process_group"]
                start_ticks = record["start_ticks"]
                if (
                    type(record["schema_version"]) is not int
                    or record["schema_version"] != 1
                    or not _is_sha256(record["request_sha256"])
                    or record["recovery_scope_sha256"] != self.policy.recovery_scope_sha256
                    or type(pid) is not int
                    or type(process_group) is not int
                    or type(start_ticks) is not int
                    or pid <= 1
                    or process_group != pid
                    or pid == os.getpid()
                    or process_group == os.getpgrp()
                ):
                    _fail("worker_process_record_invalid")
                observed_start_ticks = _process_start_ticks(pid)
                if pid in self._active_anchor_processes:
                    anchor_process = self._active_processes.get(pid)
                    try:
                        observed_process_group = os.getpgid(pid)
                    except OSError:
                        observed_process_group = None
                    if (
                        anchor_process is None
                        or anchor_process.returncode is not None
                        or observed_start_ticks != start_ticks
                        or observed_process_group != process_group
                    ):
                        _fail("worker_process_identity_invalid")
                    continue
                if observed_start_ticks == start_ticks:
                    try:
                        if os.getpgid(pid) != process_group:
                            _fail("worker_process_identity_invalid")
                    except ProcessLookupError:
                        pass
                    else:
                        cleanup_task = asyncio.create_task(_terminate_stale_process_group(process_group, pid))
                        _, cleanup_interrupted = await _drain_task(cleanup_task)
                        interrupted = interrupted or cleanup_interrupted
                elif observed_start_ticks is None and _process_group_exists(process_group):
                    # A live process group whose recorded leader no longer
                    # exists may have reused this numeric PGID.  Without a
                    # matching leader start time (or a future cgroup/pidfd
                    # identity), signalling it could kill unrelated work.
                    _fail("worker_process_identity_ambiguous")
                elif observed_start_ticks is not None:
                    _fail("worker_process_identity_ambiguous")
                self._remove_process_record(path)
        except BaseException as error:
            if interrupted and not isinstance(error, asyncio.CancelledError):
                raise asyncio.CancelledError from error
            raise
        if interrupted:
            raise asyncio.CancelledError

    @staticmethod
    def _timeout(operation: str, policy: WorkerPolicy) -> int:
        return {
            "recover": policy.recovery_timeout_seconds,
            "probe": policy.probe_timeout_seconds,
            "build": policy.build_timeout_seconds,
            "validate": policy.validate_timeout_seconds,
        }[operation]

    async def invoke(self, request: dict[str, object]) -> WorkerResponse:
        self.require_provider_epoch()
        self._revalidate_environment()
        request = self._bind_rotation_audit(request)
        operation = request.get("operation")
        if operation not in {"recover", "probe", "build", "validate", "anchor"}:
            _fail("worker_request_invalid")
        return await self._invoke_bound(request)

    async def _invoke_bound(self, request: dict[str, object]) -> WorkerResponse:
        operation = request.get("operation")
        if operation not in {"recover", "probe", "build", "validate", "anchor"}:
            _fail("worker_request_invalid")
        request_sha256 = _sha256(canonical_json(request))
        job = _ensure_private_subdirectory(
            self.work_root,
            Path("jobs") / str(operation) / request_sha256[:2] / request_sha256,
        )
        job_lock = _ExclusiveFileLock(job / "invoke.lock", "worker_job_locked")
        job_lock.__enter__()
        try:
            return await self._invoke_once(request)
        finally:
            job_lock.__exit__()

    async def recover_provider(self, phase: str = "startup") -> dict[str, object]:
        self.require_provider_epoch()
        async with self._recovery_lock:
            response = await self.invoke(
                _recovery_request(self.policy, os.urandom(16).hex(), phase)
            )
            return _parse_recovery_result(
                response,
                self.policy,
                expected_phase=phase,
            )

    async def start_provider_anchor(self) -> ProviderAnchor:
        """Register one persistent broker client before launching a worker wave."""

        self.require_provider_epoch()
        self._revalidate_environment()
        run_nonce = os.urandom(16).hex()
        request = self._bind_rotation_audit(_anchor_request(self.policy, run_nonce))
        request_sha256 = _sha256(canonical_json(request))
        artifact_directory = _ensure_private_subdirectory(
            self.work_root,
            Path("jobs") / "anchor" / request_sha256[:2] / request_sha256 / "artifacts",
        )
        ready_path = artifact_directory / "anchor-ready.json"
        stop_path = artifact_directory / "anchor-stop.json"
        if os.path.lexists(ready_path) or os.path.lexists(stop_path):
            _fail("worker_anchor_state_invalid")
        task = asyncio.create_task(self._invoke_bound(request))
        anchor = ProviderAnchor(
            request_sha256=request_sha256,
            run_nonce=run_nonce,
            ready_path=ready_path,
            stop_path=stop_path,
            task=task,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.policy.recovery_timeout_seconds
        try:
            while not os.path.lexists(ready_path):
                if task.done():
                    await task
                    _fail("worker_anchor_start_failed")
                if loop.time() >= deadline:
                    _fail("worker_anchor_start_timeout")
                await asyncio.sleep(0.05)
            ready_payload, _ = _read_private_file(
                self.work_root,
                ready_path,
                maximum=MAX_WORKER_RESPONSE_BYTES,
                code="worker_anchor_state_invalid",
            )
            try:
                ready_raw = strict_json_loads(ready_payload)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                _fail("worker_anchor_state_invalid", error)
            if not isinstance(ready_raw, dict) or ready_payload != canonical_json(ready_raw):
                _fail("worker_anchor_state_invalid")
            ready = _exact_keys(
                ready_raw,
                {
                    "schema_version",
                    "request_sha256",
                    "recovery_scope_sha256",
                    "active_client_registered",
                    "pool_accepting",
                    "pool_draining",
                },
                "worker_anchor_state_invalid",
            )
            if (
                type(ready["schema_version"]) is not int
                or ready["schema_version"] != 1
                or ready["request_sha256"] != request_sha256
                or ready["recovery_scope_sha256"] != self.policy.recovery_scope_sha256
                or ready["active_client_registered"] is not True
                or ready["pool_accepting"] is not True
                or ready["pool_draining"] is not False
                or task.done()
            ):
                _fail("worker_anchor_state_invalid")
            return anchor
        except BaseException as error:
            if not task.done():
                task.cancel()
            cleanup_error: BaseException | None = None
            try:
                await _drain_task(task)
            except BaseException as observed:
                cleanup_error = observed
            if cleanup_error is not None:
                raise error.with_traceback(error.__traceback__) from cleanup_error
            raise

    async def stop_provider_anchor(
        self,
        anchor: ProviderAnchor,
        phase: Literal["final", "failure"],
    ) -> tuple[dict[str, object], bool]:
        """Ask the anchor to perform the sole quiescent drain and prove zero WAL."""

        self.require_provider_epoch()
        if anchor.stopped or phase not in {"final", "failure"} or anchor.task.done():
            _fail("worker_anchor_state_invalid")
        stop_payload = canonical_json(
            {
                "schema_version": 1,
                "request_sha256": anchor.request_sha256,
                "run_nonce": anchor.run_nonce,
                "phase": phase,
            }
        )
        if os.path.lexists(anchor.stop_path):
            _fail("worker_anchor_state_invalid")
        atomic_write_bytes(anchor.stop_path, stop_payload, mode=0o400)
        try:
            response, interrupted = await _drain_task(anchor.task)
        finally:
            anchor.stopped = True
        parsed = _parse_recovery_result(
            response,
            self.policy,
            expected_phase=phase,
            expected_anchor=True,
        )
        return parsed, interrupted

    async def _invoke_once(self, request: dict[str, object]) -> WorkerResponse:
        self._revalidate_environment()
        request_payload = canonical_json(request)
        request_sha256 = _sha256(request_payload)
        operation = request.get("operation")
        if operation not in {"recover", "probe", "build", "validate", "anchor"}:
            _fail("worker_request_invalid")
        worker = _exact_keys(
            request.get("worker"),
            {
                "executable_sha256",
                "runtime_sha256",
                "materializer_code_sha256",
                "cleanup_receipt_verifier_sha256",
                "environment_sha256",
                "recovery_scope_sha256",
                "ecr_rotator_sha256",
                "credential_rotation_sha256",
            },
            "worker_request_invalid",
        )
        expected_worker = {
            "executable_sha256": self.policy.executable_sha256,
            "runtime_sha256": self.policy.runtime_sha256,
            "materializer_code_sha256": self.policy.materializer_code_sha256,
            "cleanup_receipt_verifier_sha256": self.policy.cleanup_receipt_verifier_sha256,
            "environment_sha256": self.policy.environment_sha256,
            "recovery_scope_sha256": self.policy.recovery_scope_sha256,
            "ecr_rotator_sha256": self.policy.ecr_rotator_sha256,
        }
        if any(worker[key] != value for key, value in expected_worker.items()) or not _is_sha256(
            worker["credential_rotation_sha256"]
        ):
            _fail("worker_request_invalid")
        job = _ensure_private_subdirectory(
            self.work_root,
            Path("jobs") / str(operation) / request_sha256[:2] / request_sha256,
        )
        artifact_directory = _ensure_private_subdirectory(
            self.work_root,
            job.relative_to(self.work_root) / "artifacts",
        )
        request_path = job / "request.json"
        response_path = job / "response.json"
        completion_path = job / "controller-completion.json"
        if request_path.exists():
            observed, _ = _read_private_file(
                self.work_root,
                request_path,
                maximum=MAX_PLAN_BYTES,
                code="worker_request_changed",
            )
            if observed != request_payload:
                _fail("worker_request_changed")
        else:
            atomic_write_bytes(request_path, request_payload, mode=0o400)
        self.executable.revalidate()
        cached_response = os.path.lexists(response_path)
        cached_completion = os.path.lexists(completion_path)
        if cached_response != cached_completion:
            _fail("worker_response_incomplete")
        if not cached_response:
            executable_fd = self.executable.open_verified_fd()
            parent_pid = os.getpid()
            spawn_task = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    f"/proc/self/fd/{executable_fd}",
                    "--request",
                    str(request_path),
                    "--request-sha256",
                    request_sha256,
                    "--response",
                    str(response_path),
                    "--artifact-dir",
                    str(artifact_directory),
                    cwd=job,
                    env=self.environment,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                    pass_fds=(executable_fd,),
                    preexec_fn=lambda: _configure_worker_child(parent_pid),
                )
            )
            try:
                try:
                    process = await asyncio.shield(spawn_task)
                except asyncio.CancelledError as cancellation:
                    try:
                        process, _ = await _drain_task(spawn_task)
                    except BaseException as spawn_error:
                        raise cancellation from spawn_error
                    self._active_processes[process.pid] = process
                    if operation == "anchor":
                        self._active_anchor_processes.add(process.pid)
                    cleanup_task = asyncio.create_task(_terminate_process(process))
                    try:
                        await _drain_task(cleanup_task)
                    except BaseException as cleanup_error:
                        raise cancellation from cleanup_error
                    self._active_processes.pop(process.pid)
                    self._active_anchor_processes.discard(process.pid)
                    raise cancellation.with_traceback(cancellation.__traceback__)
            finally:
                os.close(executable_fd)
            self._active_processes[process.pid] = process
            if operation == "anchor":
                self._active_anchor_processes.add(process.pid)
            try:
                process_record = await self._record_process(
                    request_sha256,
                    process,
                    response_path,
                )
            except BaseException as error:
                cleanup_task = asyncio.create_task(_terminate_process(process))
                try:
                    _, cleanup_interrupted = await _drain_task(cleanup_task)
                except BaseException as cleanup_error:
                    if isinstance(error, asyncio.CancelledError):
                        raise error from cleanup_error
                    raise
                self._active_processes.pop(process.pid)
                self._active_anchor_processes.discard(process.pid)
                if cleanup_interrupted and not isinstance(error, asyncio.CancelledError):
                    raise asyncio.CancelledError from error
                raise error.with_traceback(error.__traceback__)
            if process_record is None:
                return_code = process.returncode
                assert return_code is not None
            else:
                try:
                    if operation == "anchor":
                        return_code = await process.wait()
                    else:
                        return_code = await asyncio.wait_for(
                            process.wait(),
                            timeout=self._timeout(str(operation), self.policy),
                        )
                except TimeoutError as error:
                    cleanup_task = asyncio.create_task(_terminate_process(process))
                    _, cleanup_interrupted = await _drain_task(cleanup_task)
                    self._active_processes.pop(process.pid)
                    self._active_anchor_processes.discard(process.pid)
                    self._remove_process_record(process_record)
                    if cleanup_interrupted:
                        raise asyncio.CancelledError from error
                    _fail(f"worker_{operation}_timeout", error)
                except asyncio.CancelledError as cancellation:
                    cleanup_task = asyncio.create_task(_terminate_process(process))
                    try:
                        await _drain_task(cleanup_task)
                    except BaseException as cleanup_error:
                        raise cancellation from cleanup_error
                    self._active_processes.pop(process.pid)
                    self._active_anchor_processes.discard(process.pid)
                    self._remove_process_record(process_record)
                    raise cancellation.with_traceback(cancellation.__traceback__)
            try:
                process_group_extinct = await _wait_process_group_extinct(process.pid, 0.25)
            except asyncio.CancelledError as cancellation:
                cleanup_task = asyncio.create_task(_terminate_process(process))
                try:
                    await _drain_task(cleanup_task)
                except BaseException as cleanup_error:
                    raise cancellation from cleanup_error
                self._active_processes.pop(process.pid)
                self._active_anchor_processes.discard(process.pid)
                if process_record is not None:
                    self._remove_process_record(process_record)
                raise cancellation.with_traceback(cancellation.__traceback__)
            if not process_group_extinct:
                cleanup_task = asyncio.create_task(_terminate_process(process))
                _, cleanup_interrupted = await _drain_task(cleanup_task)
                self._active_processes.pop(process.pid)
                self._active_anchor_processes.discard(process.pid)
                if process_record is not None:
                    self._remove_process_record(process_record)
                if cleanup_interrupted:
                    raise asyncio.CancelledError from OfflineCatalogError("worker_process_group_leaked")
                _fail("worker_process_group_leaked")
            if process_record is not None:
                self._remove_process_record(process_record)
            self._active_processes.pop(process.pid)
            self._active_anchor_processes.discard(process.pid)
            if return_code != 0:
                _fail(f"worker_{operation}_failed")
        self.executable.revalidate()
        request_observed, _ = _read_private_file(
            self.work_root,
            request_path,
            maximum=MAX_PLAN_BYTES,
            code="worker_request_changed",
        )
        if request_observed != request_payload:
            _fail("worker_request_changed")
        response_payload, _ = _read_private_file(
            self.work_root,
            response_path,
            maximum=MAX_WORKER_RESPONSE_BYTES,
            code="worker_response_invalid",
        )
        response_sha256 = _sha256(response_payload)
        if cached_response:
            completion_payload, _ = _read_private_file(
                self.work_root,
                completion_path,
                maximum=MAX_WORKER_RESPONSE_BYTES,
                code="worker_completion_invalid",
            )
            try:
                completion_raw = strict_json_loads(completion_payload)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                _fail("worker_completion_invalid", error)
            if not isinstance(completion_raw, dict) or completion_payload != canonical_json(completion_raw):
                _fail("worker_completion_invalid")
            completion = _exact_keys(
                completion_raw,
                {
                    "schema_version",
                    "request_sha256",
                    "response_sha256",
                    "response_size",
                    "worker_executable_sha256",
                    "worker_runtime_sha256",
                    "worker_environment_sha256",
                    "recovery_scope_sha256",
                },
                "worker_completion_invalid",
            )
            if (
                type(completion["schema_version"]) is not int
                or completion["schema_version"] != WORKER_COMPLETION_SCHEMA_VERSION
                or completion["request_sha256"] != request_sha256
                or completion["response_sha256"] != response_sha256
                or type(completion["response_size"]) is not int
                or completion["response_size"] != len(response_payload)
                or completion["worker_executable_sha256"] != self.policy.executable_sha256
                or completion["worker_runtime_sha256"] != self.policy.runtime_sha256
                or completion["worker_environment_sha256"] != self.policy.environment_sha256
                or completion["recovery_scope_sha256"] != self.policy.recovery_scope_sha256
            ):
                _fail("worker_completion_invalid")
        try:
            raw = strict_json_loads(response_payload)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            _fail("worker_response_invalid", error)
        if not isinstance(raw, dict) or response_payload != canonical_json(raw):
            _fail("worker_response_invalid")
        response = _exact_keys(
            raw,
            {
                "schema_version",
                "protocol_version",
                "operation",
                "request_sha256",
                "worker_executable_sha256",
                "worker_runtime_sha256",
                "worker_environment_sha256",
                "recovery_scope_sha256",
                "credential_rotation_sha256",
                "status",
                "lifecycle",
                "result",
            },
            "worker_response_invalid",
        )
        lifecycle = _exact_keys(
            response["lifecycle"],
            {
                "network",
                "session_started",
                "process_cleanup_verified",
                "cleanup_verified",
                "provider_cleanup",
            },
            "worker_lifecycle_unverified",
        )
        expected_network = {
            "recover": "control-plane",
            "anchor": "control-plane",
            "probe": "none",
            "build": "trusted-builder",
            "validate": "none",
        }[operation]
        expected_session_started = operation not in {"recover", "anchor"}
        if (
            type(response["schema_version"]) is not int
            or response["schema_version"] != 1
            or type(response["protocol_version"]) is not int
            or response["protocol_version"] != WORKER_PROTOCOL_VERSION
            or response["operation"] != operation
            or response["request_sha256"] != request_sha256
            or response["worker_executable_sha256"] != self.policy.executable_sha256
            or response["worker_runtime_sha256"] != self.policy.runtime_sha256
            or response["worker_environment_sha256"] != self.policy.environment_sha256
            or response["recovery_scope_sha256"] != self.policy.recovery_scope_sha256
            or response["credential_rotation_sha256"] != worker["credential_rotation_sha256"]
            or response["status"] != "complete"
            or lifecycle["network"] != expected_network
            or lifecycle["session_started"] is not expected_session_started
            or lifecycle["process_cleanup_verified"] is not True
            or lifecycle["cleanup_verified"] is not True
            or not isinstance(response["result"], dict)
        ):
            _fail("worker_lifecycle_unverified")
        provider_cleanup = lifecycle["provider_cleanup"]
        if operation in {"recover", "anchor"}:
            if provider_cleanup is not None:
                _fail("worker_lifecycle_unverified")
        else:
            cleanup = _exact_keys(
                provider_cleanup,
                {
                    "provider",
                    "request_sha256",
                    "recovery_scope_sha256",
                    "session_sha256",
                    "assignment_sha256",
                    "receipt_sha256",
                    "receipt_verifier_sha256",
                    "terminal_state",
                },
                "worker_lifecycle_unverified",
            )
            if (
                cleanup["provider"] != "sandoq"
                or cleanup["request_sha256"] != request_sha256
                or cleanup["recovery_scope_sha256"] != self.policy.recovery_scope_sha256
                or not _is_sha256(cleanup["session_sha256"])
                or not _is_sha256(cleanup["assignment_sha256"])
                or not _is_sha256(cleanup["receipt_sha256"])
                or cleanup["receipt_verifier_sha256"] != self.policy.cleanup_receipt_verifier_sha256
                or cleanup["terminal_state"] not in {"deleted", "recycled"}
            ):
                _fail("worker_lifecycle_unverified")
        if not cached_response:
            completion_payload = canonical_json(
                {
                    "schema_version": WORKER_COMPLETION_SCHEMA_VERSION,
                    "request_sha256": request_sha256,
                    "response_sha256": response_sha256,
                    "response_size": len(response_payload),
                    "worker_executable_sha256": self.policy.executable_sha256,
                    "worker_runtime_sha256": self.policy.runtime_sha256,
                    "worker_environment_sha256": self.policy.environment_sha256,
                    "recovery_scope_sha256": self.policy.recovery_scope_sha256,
                }
            )
            if os.path.lexists(completion_path):
                _fail("worker_completion_invalid")
            atomic_write_bytes(completion_path, completion_payload, mode=0o400)
            observed_completion, _ = _read_private_file(
                self.work_root,
                completion_path,
                maximum=MAX_WORKER_RESPONSE_BYTES,
                code="worker_completion_invalid",
            )
            if observed_completion != completion_payload:
                _fail("worker_completion_invalid")
        return WorkerResponse(result=response["result"], artifact_directory=artifact_directory)


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    await _terminate_process_group(process.pid)
    if process.returncode is None:
        await process.wait()
    if _process_group_exists(process.pid):
        _fail("worker_process_group_cleanup_failed")


def _compatibility_record(probe: ProbeResult) -> dict[str, object]:
    return {
        "runtime_fingerprint": probe.runtime_fingerprint.record(),
        "runtime_fingerprint_sha256": probe.runtime_fingerprint.sha256,
        "marker_environment": probe.marker_environment,
        "supported_tags": list(probe.supported_tags),
    }


_RECOVERY_PHASES = frozenset({"startup", "final", "failure"})


def _recovery_request(
    worker: WorkerPolicy,
    run_nonce: str,
    phase: str = "startup",
) -> dict[str, object]:
    if phase not in _RECOVERY_PHASES:
        _fail("worker_recovery_phase_invalid")
    return {
        "schema_version": 1,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "operation": "recover",
        "worker": {
            "executable_sha256": worker.executable_sha256,
            "runtime_sha256": worker.runtime_sha256,
            "materializer_code_sha256": worker.materializer_code_sha256,
            "cleanup_receipt_verifier_sha256": worker.cleanup_receipt_verifier_sha256,
            "environment_sha256": worker.environment_sha256,
            "recovery_scope_sha256": worker.recovery_scope_sha256,
            "ecr_rotator_sha256": worker.ecr_rotator_sha256,
        },
        "run_nonce": run_nonce,
        "phase": phase,
        "network": "control-plane",
        "recovery_contract": {
            "durable_provider_wal": True,
            "drain_or_retire_orphans": True,
            "require_cleanup_receipts": True,
        },
    }


def _anchor_request(worker: WorkerPolicy, run_nonce: str) -> dict[str, object]:
    if len(run_nonce) != 32 or any(character not in "0123456789abcdef" for character in run_nonce):
        _fail("worker_anchor_state_invalid")
    return {
        "schema_version": 1,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "operation": "anchor",
        "worker": {
            "executable_sha256": worker.executable_sha256,
            "runtime_sha256": worker.runtime_sha256,
            "materializer_code_sha256": worker.materializer_code_sha256,
            "cleanup_receipt_verifier_sha256": worker.cleanup_receipt_verifier_sha256,
            "environment_sha256": worker.environment_sha256,
            "recovery_scope_sha256": worker.recovery_scope_sha256,
            "ecr_rotator_sha256": worker.ecr_rotator_sha256,
        },
        "run_nonce": run_nonce,
        "network": "control-plane",
        "anchor_contract": {
            "active_client_required": True,
            "heartbeat_interval_seconds": PROVIDER_ANCHOR_HEARTBEAT_INTERVAL_SECONDS,
            "sole_terminal_drain": True,
            "zero_live_wal_required": True,
        },
    }


def _parse_recovery_result(
    response: WorkerResponse,
    policy: WorkerPolicy,
    *,
    expected_phase: str = "startup",
    expected_anchor: bool = False,
) -> dict[str, object]:
    expected_keys = {
        "durable_provider_wal",
        "recovery_attempted",
        "remaining_sessions",
        "cleanup_receipts_verified",
        "recovery_scope_sha256",
        "phase",
        "wal_snapshot_sha256",
        "recovery_receipt_sha256",
        "receipt_verifier_sha256",
    }
    if expected_anchor:
        expected_keys.add("anchor_liveness")
    raw = _exact_keys(
        response.result,
        expected_keys,
        "worker_recovery_unverified",
    )
    if (
        raw["durable_provider_wal"] is not True
        or raw["recovery_attempted"] is not True
        or raw["cleanup_receipts_verified"] is not True
        or raw["phase"] != expected_phase
        or type(raw["remaining_sessions"]) is not int
        or raw["remaining_sessions"] != 0
        or raw["recovery_scope_sha256"] != policy.recovery_scope_sha256
        or not _is_sha256(raw["wal_snapshot_sha256"])
        or not _is_sha256(raw["recovery_receipt_sha256"])
        or raw["receipt_verifier_sha256"] != policy.cleanup_receipt_verifier_sha256
    ):
        _fail("worker_recovery_unverified")
    if expected_anchor:
        liveness = _exact_keys(
            raw["anchor_liveness"],
            {"active_client_registered", "heartbeat_checks", "stop_received"},
            "worker_recovery_unverified",
        )
        if (
            liveness["active_client_registered"] is not True
            or type(liveness["heartbeat_checks"]) is not int
            or liveness["heartbeat_checks"] < 0
            or liveness["stop_received"] is not True
        ):
            _fail("worker_recovery_unverified")
    return dict(raw)


def _probe_request(task: MaterializationTask, plan: MaterializationPlan) -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "operation": "probe",
        "worker": {
            "executable_sha256": plan.worker.executable_sha256,
            "runtime_sha256": plan.worker.runtime_sha256,
            "materializer_code_sha256": plan.worker.materializer_code_sha256,
            "cleanup_receipt_verifier_sha256": plan.worker.cleanup_receipt_verifier_sha256,
            "environment_sha256": plan.worker.environment_sha256,
            "recovery_scope_sha256": plan.worker.recovery_scope_sha256,
            "ecr_rotator_sha256": plan.worker.ecr_rotator_sha256,
        },
        "runtime_role": task.runtime_role,
        "image": task.image,
        "requirements": list(task.requirements),
        "requirements_sha256": task.requirements_sha256,
        "network": "none",
        "attestation_policy": {
            "code_sha256": plan.identity.inventory_probe_code_sha256,
            "environment_sha256": plan.identity.inventory_probe_environment_sha256,
            "approval_sha256": plan.identity.inventory_probe_approval_sha256,
        },
    }


def _parse_compatibility(value: object) -> tuple[RuntimeFingerprint, dict[str, str], tuple[str, ...]]:
    raw = _exact_keys(
        value,
        {
            "runtime_fingerprint",
            "runtime_fingerprint_sha256",
            "marker_environment",
            "supported_tags",
        },
        "worker_compatibility_invalid",
    )
    fingerprint = RuntimeFingerprint.from_record(raw["runtime_fingerprint"])
    marker_environment = raw["marker_environment"]
    supported_tags = raw["supported_tags"]
    if (
        raw["runtime_fingerprint_sha256"] != fingerprint.sha256
        or not isinstance(marker_environment, dict)
        or not 1 <= len(marker_environment) <= MAX_MARKER_ENVIRONMENT_KEYS
        or "extra" in marker_environment
        or not all(
            isinstance(key, str)
            and key
            and len(key.encode("utf-8")) <= MAX_TEXT_EVIDENCE_BYTES
            and isinstance(item, str)
            and len(item.encode("utf-8")) <= MAX_TEXT_EVIDENCE_BYTES
            for key, item in marker_environment.items()
        )
        or fingerprint.marker_environment_sha256 != _sha256(canonical_json(marker_environment))
        or not isinstance(supported_tags, list)
        or not 1 <= len(supported_tags) <= MAX_RUNTIME_TAGS
        or not all(isinstance(tag, str) and tag for tag in supported_tags)
        or supported_tags != sorted(set(supported_tags))
        or fingerprint.supported_tags_sha256 != _sha256(canonical_json(supported_tags))
    ):
        _fail("worker_compatibility_invalid")
    return fingerprint, marker_environment, tuple(supported_tags)


def _parse_probe_result(
    response: WorkerResponse,
    task: MaterializationTask,
    plan: MaterializationPlan,
) -> ProbeResult:
    raw = _exact_keys(
        response.result,
        {
            "image",
            "requirements_sha256",
            "compatibility",
            "installed_inventory",
            "installed_inventory_sha256",
            "satisfied",
            "closure",
            "attestation",
        },
        "probe_result_invalid",
    )
    fingerprint, marker_environment, supported_tags = _parse_compatibility(raw["compatibility"])
    inventory = _validate_closure(raw["installed_inventory"], "probe_result_invalid")  # type: ignore[arg-type]
    attestation = _exact_keys(
        raw["attestation"],
        {"code_sha256", "environment_sha256", "approval_sha256"},
        "probe_result_invalid",
    )
    satisfied = raw["satisfied"]
    if (
        raw["image"] != task.image
        or raw["requirements_sha256"] != task.requirements_sha256
        or raw["installed_inventory_sha256"] != closure_sha256(inventory)
        or not isinstance(satisfied, bool)
        or (not task.requirements and not satisfied)
        or attestation["code_sha256"] != plan.identity.inventory_probe_code_sha256
        or attestation["environment_sha256"] != plan.identity.inventory_probe_environment_sha256
        or attestation["approval_sha256"] != plan.identity.inventory_probe_approval_sha256
    ):
        _fail("probe_result_invalid")
    closure = None
    if satisfied:
        closure = _parse_closure(raw["closure"], "probe_result_invalid")
        if (not task.requirements and closure.distributions) or not set(closure.distributions).issubset(set(inventory)):
            _fail("probe_result_invalid")
        _validate_root_requirements(task.requirements, closure, "probe_result_invalid")
    elif raw["closure"] is not None:
        _fail("probe_result_invalid")
    return ProbeResult(
        image=task.image,
        requirements=task.requirements,
        requirements_sha256=task.requirements_sha256,
        runtime_fingerprint=fingerprint,
        marker_environment=marker_environment,
        supported_tags=supported_tags,
        installed_inventory=inventory,
        installed_inventory_sha256=str(raw["installed_inventory_sha256"]),
        satisfied=satisfied,
        closure=closure,
    )


def _build_request(
    task: MaterializationTask,
    probe: ProbeResult,
    plan: MaterializationPlan,
    scope_policy: Literal["discover", "image"],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "operation": "build",
        "worker": {
            "executable_sha256": plan.worker.executable_sha256,
            "runtime_sha256": plan.worker.runtime_sha256,
            "materializer_code_sha256": plan.worker.materializer_code_sha256,
            "cleanup_receipt_verifier_sha256": plan.worker.cleanup_receipt_verifier_sha256,
            "environment_sha256": plan.worker.environment_sha256,
            "recovery_scope_sha256": plan.worker.recovery_scope_sha256,
            "ecr_rotator_sha256": plan.worker.ecr_rotator_sha256,
        },
        "image": task.image,
        "requirements": list(task.requirements),
        "requirements_sha256": task.requirements_sha256,
        "compatibility": _compatibility_record(probe),
        "scope_policy": scope_policy,
        "network": "trusted-builder",
        "policy": {
            "source_policy_sha256": plan.policy.source_policy_sha256,
            "source_policy_approval_sha256": plan.policy.source_policy_approval_sha256,
            "approved_binary_artifacts": sorted(plan.policy.approved_binary_artifacts),
            "approved_binary_artifacts_sha256": plan.identity.approved_binary_artifacts_sha256,
            "approved_source_attestations": sorted(plan.policy.approved_source_attestations),
            "approved_source_attestations_sha256": plan.identity.approved_source_attestations_sha256,
            "approved_toolchains": sorted(plan.policy.approved_toolchains),
            "approved_toolchains_sha256": plan.identity.approved_toolchains_sha256,
        },
        "artifact_contract": {
            "filename": "wheelhouse.tar",
            "deterministic_format": "ustar-sorted-zero-mtime-v1",
            "binary_only_unless_source_attested": True,
        },
    }


def _parse_build_result(
    response: WorkerResponse,
    task: MaterializationTask,
    probe: ProbeResult,
    plan: MaterializationPlan,
    scope_policy: Literal["discover", "image"],
) -> BuiltWheelhouse:
    raw = _exact_keys(
        response.result,
        {"scope", "image", "archive", "closure", "toolchain", "source_policy", "wheels"},
        "build_result_invalid",
    )
    scope = raw["scope"]
    image = raw["image"]
    if (
        scope not in {"image", "universal"}
        or (scope == "image" and image != task.image)
        or (scope == "universal" and image is not None)
        or (scope_policy == "image" and scope != "image")
    ):
        _fail("build_result_invalid")
    archive_record = _exact_keys(raw["archive"], {"filename", "sha256", "size"}, "build_result_invalid")
    if (
        archive_record["filename"] != "wheelhouse.tar"
        or not _is_sha256(archive_record["sha256"])
        or isinstance(archive_record["size"], bool)
        or not isinstance(archive_record["size"], int)
        or not 1 <= archive_record["size"] <= MAX_WHEELHOUSE_BYTES
    ):
        _fail("build_result_invalid")
    archive_path = response.artifact_directory / "wheelhouse.tar"
    archive_payload, archive_seal = _read_private_file(
        response.artifact_directory,
        archive_path,
        maximum=MAX_WHEELHOUSE_BYTES,
        code="build_artifact_invalid",
    )
    if archive_seal.sha256 != archive_record["sha256"] or archive_seal.size != archive_record["size"]:
        _fail("build_artifact_invalid")
    evidence, wheel_payloads = _deterministic_wheelhouse(archive_payload)
    closure = _parse_closure(raw["closure"], "build_result_invalid")
    toolchain_sha256, toolchain = _parse_toolchain(raw["toolchain"], plan.policy.approved_toolchains)
    if (
        toolchain["python_version"] != probe.runtime_fingerprint.python_full_version
        or toolchain["pip_version"] != probe.runtime_fingerprint.pip_version
    ):
        _fail("build_result_invalid")
    source_policy = _exact_keys(
        raw["source_policy"],
        {"policy_sha256", "approval_sha256"},
        "build_result_invalid",
    )
    if (
        source_policy["policy_sha256"] != plan.policy.source_policy_sha256
        or source_policy["approval_sha256"] != plan.policy.source_policy_approval_sha256
    ):
        _fail("build_result_invalid")
    raw_wheels = raw["wheels"]
    if not isinstance(raw_wheels, list) or len(raw_wheels) != len(evidence):
        _fail("build_result_invalid")
    wheel_records: list[dict[str, object]] = []
    for raw_wheel, observed in zip(raw_wheels, evidence, strict=True):
        wheel = _exact_keys(
            raw_wheel,
            {
                "distribution",
                "version",
                "filename",
                "size",
                "sha256",
                "universal",
                "origin",
                "binary_artifact_policy",
                "binary_artifact_policy_sha256",
                "source_attestation_sha256",
            },
            "build_result_invalid",
        )
        if (
            wheel["distribution"] != observed.distribution
            or wheel["version"] != observed.version
            or wheel["filename"] != observed.filename
            or type(wheel["size"]) is not int
            or wheel["size"] != observed.size
            or wheel["sha256"] != observed.sha256
            or wheel["universal"] is not observed.universal
            or wheel["origin"] not in {"binary", "source-build"}
        ):
            _fail("build_result_invalid")
        binary_policy = wheel["binary_artifact_policy"]
        binary_policy_sha256 = wheel["binary_artifact_policy_sha256"]
        source_attestation = wheel["source_attestation_sha256"]
        if wheel["origin"] == "binary":
            policy = _exact_keys(
                binary_policy,
                {
                    "schema_version",
                    "distribution",
                    "version",
                    "filename",
                    "size",
                    "sha256",
                    "source_url_sha256",
                    "source_snapshot_sha256",
                },
                "binary_input_unapproved",
            )
            policy_digest = _sha256(canonical_json(policy))
            if (
                type(policy["schema_version"]) is not int
                or policy["schema_version"] != 1
                or policy["distribution"] != observed.distribution
                or policy["version"] != observed.version
                or policy["filename"] != observed.filename
                or policy["size"] != observed.size
                or policy["sha256"] != observed.sha256
                or not _is_sha256(policy["source_url_sha256"])
                or not _is_sha256(policy["source_snapshot_sha256"])
                or binary_policy_sha256 != policy_digest
                or policy_digest not in plan.policy.approved_binary_artifacts
                or source_attestation is not None
            ):
                _fail("binary_input_unapproved")
        elif (
            binary_policy is not None
            or binary_policy_sha256 is not None
            or not _is_sha256(source_attestation)
            or source_attestation not in plan.policy.approved_source_attestations
        ):
            _fail("source_input_unapproved")
        wheel_records.append(dict(wheel))
    if scope == "universal" and not all(item.universal for item in evidence):
        _fail("build_result_invalid")
    if closure.distributions != tuple(sorted((item.distribution, item.version) for item in evidence)):
        _fail("build_result_invalid")
    _validate_resolution_closure(
        task.requirements,
        closure,
        wheel_payloads,
        probe.marker_environment,
        frozenset(probe.supported_tags),
    )
    manifest = {
        "schema_version": WHEELHOUSE_MANIFEST_SCHEMA_VERSION,
        "requirements": list(task.requirements),
        "requirements_sha256": task.requirements_sha256,
        "archive": {
            "sha256": archive_seal.sha256,
            "size": archive_seal.size,
        },
        "closure": closure.record(),
        "compatibility": {
            "scope": scope,
            "image": image,
            **_compatibility_record(probe),
        },
        "toolchain": {"record": toolchain, "sha256": toolchain_sha256},
        "source_policy": {
            "policy_sha256": plan.policy.source_policy_sha256,
            "approval_sha256": plan.policy.source_policy_approval_sha256,
        },
        "wheels": wheel_records,
    }
    manifest_payload = canonical_json(manifest)
    return BuiltWheelhouse(
        scope=scope,  # type: ignore[arg-type]
        image=image if isinstance(image, str) else None,
        requirements=task.requirements,
        requirements_sha256=task.requirements_sha256,
        runtime_fingerprint=probe.runtime_fingerprint,
        marker_environment=probe.marker_environment,
        supported_tags=probe.supported_tags,
        archive_path=archive_path,
        archive_seal=archive_seal,
        archive_sha256=archive_seal.sha256,
        manifest=manifest,
        manifest_payload=manifest_payload,
        manifest_sha256=_sha256(manifest_payload),
        closure=closure,
    )


def _validate_request(
    task: MaterializationTask,
    probe: ProbeResult,
    built: BuiltWheelhouse,
    plan: MaterializationPlan,
) -> dict[str, object]:
    built.archive_seal.read_verified(
        built.archive_path.parent,
        maximum=MAX_WHEELHOUSE_BYTES,
        code="build_artifact_changed",
    )
    evidence = _validation_evidence(task, probe, built)
    return {
        "schema_version": 1,
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "operation": "validate",
        "worker": {
            "executable_sha256": plan.worker.executable_sha256,
            "runtime_sha256": plan.worker.runtime_sha256,
            "materializer_code_sha256": plan.worker.materializer_code_sha256,
            "cleanup_receipt_verifier_sha256": plan.worker.cleanup_receipt_verifier_sha256,
            "environment_sha256": plan.worker.environment_sha256,
            "recovery_scope_sha256": plan.worker.recovery_scope_sha256,
            "ecr_rotator_sha256": plan.worker.ecr_rotator_sha256,
        },
        "runtime_role": task.runtime_role,
        "image": task.image,
        "requirements": list(task.requirements),
        "requirements_sha256": task.requirements_sha256,
        "compatibility": _compatibility_record(probe),
        "network": "none",
        "archive": {
            "path": str(built.archive_path),
            "sha256": built.archive_sha256,
            "size": built.archive_seal.size,
        },
        "closure": built.closure.record(),
        "validation_evidence": evidence,
    }


def _validation_evidence(
    task: MaterializationTask,
    probe: ProbeResult,
    built: BuiltWheelhouse,
) -> dict[str, object]:
    seed = _sha256(
        canonical_json(
            {
                "schema_version": 1,
                "image": task.image,
                "requirements_sha256": task.requirements_sha256,
                "runtime_fingerprint_sha256": probe.runtime_fingerprint.sha256,
                "archive_sha256": built.archive_sha256,
                "closure_sha256": built.closure.sha256,
            }
        )
    )
    runtime_root = RUNTIME_STAGING_ROOT / f"validate-{seed}"
    paths = {
        "archive": str(runtime_root / "wheelhouse.tar"),
        "wheel_directory": str(runtime_root / "wheels"),
        "site_directory": str(runtime_root / "site"),
        "install_request": str(runtime_root / "requirements.txt"),
        "probe_script": str(runtime_root / "closure-probe.py"),
        "probe_control": str(runtime_root / "closure-control.json"),
    }
    validate_runtime_staging_paths(tuple(paths.values()))
    install_request = "".join(
        f"{paths['wheel_directory']}/{wheel['filename']} --hash=sha256:{wheel['sha256']}\n"
        for wheel in built.manifest["wheels"]  # type: ignore[union-attr]
    ).encode("utf-8")
    install_argv = offline_install_argv(paths["site_directory"], paths["install_request"])
    install_environment = offline_install_environment()
    probe_control = canonical_json(
        {
            "schema_version": 1,
            "site_directory": paths["site_directory"],
            "requirements": list(task.requirements),
            "inventory": [list(item) for item in built.closure.distributions],
            "inventory_sha256": built.closure.sha256,
            "closure": [list(item) for item in built.closure.distributions],
            "closure_sha256": built.closure.sha256,
        }
    )
    probe_control_sha256 = _sha256(probe_control)
    probe_argv = closure_probe_argv(
        paths["probe_script"],
        paths["probe_control"],
        probe_control_sha256,
    )
    wheel_inventory = [
        {
            "filename": wheel["filename"],
            "sha256": wheel["sha256"],
            "size": wheel["size"],
        }
        for wheel in built.manifest["wheels"]  # type: ignore[union-attr]
    ]
    expected_probe_stdout = canonical_json({"count": len(built.closure.distributions), "status": "ok"}) + b"\n"
    return {
        "runtime_paths": paths,
        "wheel_inventory": wheel_inventory,
        "wheel_inventory_sha256": _sha256(canonical_json(wheel_inventory)),
        "install_request_sha256": _sha256(install_request),
        "install_argv_sha256": _sha256(canonical_json(list(install_argv))),
        "install_environment_sha256": _sha256(canonical_json(install_environment)),
        "probe_script_sha256": _sha256(CLOSURE_PROBE_CODE.encode("utf-8")),
        "probe_control_sha256": probe_control_sha256,
        "probe_argv_sha256": _sha256(canonical_json(list(probe_argv))),
        "expected_probe_stdout_sha256": _sha256(expected_probe_stdout),
        "expected_inventory_sha256": built.closure.sha256,
        "expected_closure_sha256": built.closure.sha256,
    }


def _parse_validate_result(
    response: WorkerResponse,
    task: MaterializationTask,
    probe: ProbeResult,
    built: BuiltWheelhouse,
) -> None:
    raw = _exact_keys(
        response.result,
        {
            "image",
            "requirements_sha256",
            "runtime_fingerprint_sha256",
            "archive_sha256",
            "closure_sha256",
            "observed",
        },
        "validation_result_invalid",
    )
    evidence = _validation_evidence(task, probe, built)
    observed = _exact_keys(
        raw["observed"],
        {
            "network",
            "network_isolation_verified",
            "archive_sha256",
            "wheel_inventory_sha256",
            "install_request_sha256",
            "install_argv_sha256",
            "install_environment_sha256",
            "install_exit_code",
            "probe_script_sha256",
            "probe_control_sha256",
            "probe_argv_sha256",
            "probe_exit_code",
            "probe_stdout_sha256",
            "observed_inventory_sha256",
            "observed_closure_sha256",
            "missing_distributions",
            "unexpected_distributions",
        },
        "validation_result_invalid",
    )
    if (
        raw["image"] != task.image
        or raw["requirements_sha256"] != task.requirements_sha256
        or raw["runtime_fingerprint_sha256"] != probe.runtime_fingerprint.sha256
        or raw["archive_sha256"] != built.archive_sha256
        or raw["closure_sha256"] != built.closure.sha256
        or observed["network"] != "none"
        or observed["network_isolation_verified"] is not True
        or observed["archive_sha256"] != built.archive_sha256
        or observed["wheel_inventory_sha256"] != evidence["wheel_inventory_sha256"]
        or observed["install_request_sha256"] != evidence["install_request_sha256"]
        or observed["install_argv_sha256"] != evidence["install_argv_sha256"]
        or observed["install_environment_sha256"] != evidence["install_environment_sha256"]
        or type(observed["install_exit_code"]) is not int
        or observed["install_exit_code"] != 0
        or observed["probe_script_sha256"] != evidence["probe_script_sha256"]
        or observed["probe_control_sha256"] != evidence["probe_control_sha256"]
        or observed["probe_argv_sha256"] != evidence["probe_argv_sha256"]
        or type(observed["probe_exit_code"]) is not int
        or observed["probe_exit_code"] != 0
        or observed["probe_stdout_sha256"] != evidence["expected_probe_stdout_sha256"]
        or observed["observed_inventory_sha256"] != evidence["expected_inventory_sha256"]
        or observed["observed_closure_sha256"] != evidence["expected_closure_sha256"]
        or type(observed["missing_distributions"]) is not int
        or observed["missing_distributions"] != 0
        or type(observed["unexpected_distributions"]) is not int
        or observed["unexpected_distributions"] != 0
    ):
        _fail("validation_result_invalid")


async def _bounded_map(
    items: Sequence[object],
    concurrency: int,
    operation,
) -> list[object]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(item: object) -> object:
        async with semaphore:
            return await operation(item)

    tasks = [asyncio.create_task(run(item)) for item in items]
    aggregate = asyncio.gather(*tasks)
    try:
        # Shield the aggregate so outer cancellation is translated into one
        # deliberate cancellation per child below.  Letting Task.cancel()
        # propagate through gather and then cancelling children again can
        # interrupt their first cancellation cleanup.
        return await asyncio.shield(aggregate)
    except BaseException as error:
        for task in tasks:
            if not task.done():
                task.cancel()
        drain = asyncio.ensure_future(asyncio.gather(*tasks, return_exceptions=True))
        drained_results, cleanup_interrupted = await _drain_task(drain)
        secondary_errors = [
            result
            for result in drained_results
            if isinstance(result, BaseException)
            and not isinstance(result, asyncio.CancelledError)
            and result is not error
        ]
        secondary_error: BaseException | None = None
        if len(secondary_errors) == 1:
            secondary_error = secondary_errors[0]
        elif secondary_errors:
            secondary_error = BaseExceptionGroup("worker batch cleanup failures", secondary_errors)
        if aggregate.done():
            try:
                aggregate.exception()
            except asyncio.CancelledError:
                pass
        if isinstance(error, asyncio.CancelledError):
            if secondary_error is not None:
                raise error from secondary_error
            raise error.with_traceback(error.__traceback__)
        if cleanup_interrupted:
            cancellation_cause: BaseException = error
            if secondary_error is not None:
                cancellation_cause = BaseExceptionGroup(
                    "worker batch failures during cancellation",
                    [error, secondary_error],
                )
            raise asyncio.CancelledError from cancellation_cause
        if secondary_error is not None:
            raise error.with_traceback(error.__traceback__) from secondary_error
        raise error.with_traceback(error.__traceback__)


def _raise_provider_anchor_lost(anchor: ProviderAnchor) -> None:
    if not anchor.task.done():
        _fail("provider_anchor_lost")
    try:
        anchor.task.result()
    except BaseException as error:
        _fail("provider_anchor_lost", error)
    _fail("provider_anchor_lost")


async def _bounded_map_with_anchor(
    anchor: ProviderAnchor,
    items: Sequence[object],
    concurrency: int,
    operation,
) -> list[object]:
    """Run a worker wave while continuously treating anchor exit as fatal."""

    if anchor.stopped or anchor.task.done():
        _raise_provider_anchor_lost(anchor)
    batch = asyncio.create_task(_bounded_map(items, concurrency, operation))
    try:
        completed, _ = await asyncio.wait(
            {batch, anchor.task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    except BaseException as error:
        batch.cancel()
        try:
            _, interrupted = await _drain_task(batch)
        except BaseException as cleanup_error:
            raise error.with_traceback(error.__traceback__) from cleanup_error
        if interrupted and not isinstance(error, asyncio.CancelledError):
            raise asyncio.CancelledError from error
        raise
    if anchor.task in completed:
        batch.cancel()
        try:
            await _drain_task(batch)
        except BaseException as cleanup_error:
            try:
                anchor.task.result()
            except BaseException as anchor_error:
                raise OfflineCatalogError("provider_anchor_lost") from BaseExceptionGroup(
                    "anchor loss and worker cleanup failed",
                    [anchor_error, cleanup_error],
                )
            raise OfflineCatalogError("provider_anchor_lost") from cleanup_error
        _raise_provider_anchor_lost(anchor)
    result = await batch
    if anchor.task.done():
        _raise_provider_anchor_lost(anchor)
    return result


class OfflineCatalogMaterializer:
    def __init__(
        self,
        plan: MaterializationPlan,
        runner: WorkerRunner,
        *,
        work_root: Path,
        output_root: Path,
        project_root: Path,
        dataset_root: Path,
    ) -> None:
        self.plan = plan
        self.runner = runner
        self.work_root = _validate_private_root(work_root, project_root, dataset_root)
        self.output_root = output_root
        self.project_root = project_root
        self.dataset_root = dataset_root
        if runner.work_root != self.work_root or runner.policy != plan.worker:
            _fail("materializer_worker_mismatch")
        if (
            os.path.lexists(output_root)
            or not output_root.is_absolute()
            or _PRIVATE_OUTPUT_NAME_RE.fullmatch(output_root.name) is None
        ):
            _fail("catalog_output_invalid")
        output_parent_descriptor, output_parent_status, _ = _open_absolute_nofollow(
            output_root.parent,
            "catalog_output_invalid",
        )
        try:
            self._output_parent_identity = _directory_identity(output_parent_status, "catalog_output_invalid")
        finally:
            os.close(output_parent_descriptor)
        protected = (
            project_root.resolve(strict=True),
            dataset_root.resolve(strict=True),
            work_root,
            plan.path.parent,
        )
        if any(
            output_root == root or output_root.is_relative_to(root) or root.is_relative_to(output_root)
            for root in protected
        ):
            _fail("catalog_output_overlap")

    async def materialize(self):
        self.runner.require_provider_epoch()
        self.plan.revalidate()
        anchor: ProviderAnchor | None = None
        try:
            await self.runner.recover_stale_local_processes()
            await self.runner.recover_provider("startup")
            anchor = await self.runner.start_provider_anchor()
            return await self._materialize_after_recovery(anchor)
        except BaseException as error:
            local_recovery_task = asyncio.create_task(self.runner.recover_stale_local_processes())
            try:
                _, local_recovery_interrupted = await _drain_task(local_recovery_task)
            except BaseException as local_recovery_error:
                _fail("worker_local_recovery_failed", local_recovery_error)
            anchor_failure: BaseException | None = None
            if anchor is not None and not anchor.stopped and anchor.task.done():
                try:
                    anchor.task.result()
                except BaseException as observed:
                    anchor_failure = observed
                anchor.stopped = True
            if anchor is not None and not anchor.stopped:
                recovery_task = asyncio.create_task(
                    self.runner.stop_provider_anchor(anchor, "failure")
                )
            else:
                recovery_task = asyncio.create_task(self.runner.recover_provider("failure"))
            recovery_interrupted = False
            try:
                _, recovery_interrupted = await _drain_task(recovery_task)
            except BaseException as recovery_error:
                # A dead or malformed anchor is already process-group gated by
                # ``invoke``. Only then may a fresh client perform fallback
                # recovery against the same epoch-locked socket and WAL.
                fallback_task = asyncio.create_task(self.runner.recover_provider("failure"))
                try:
                    _, fallback_interrupted = await _drain_task(fallback_task)
                except BaseException as fallback_error:
                    failures = [recovery_error, fallback_error]
                    if anchor_failure is not None:
                        failures.insert(0, anchor_failure)
                    _fail(
                        "worker_recovery_failed",
                        BaseExceptionGroup(
                            "anchor and fallback recovery failed",
                            failures,
                        ),
                    )
                recovery_interrupted = recovery_interrupted or fallback_interrupted
            if isinstance(error, asyncio.CancelledError) or local_recovery_interrupted or recovery_interrupted:
                raise asyncio.CancelledError from error
            raise error.with_traceback(error.__traceback__)

    async def _materialize_after_recovery(self, anchor: ProviderAnchor):
        unique_probe_tasks: dict[tuple[str, str, str], MaterializationTask] = {}
        for task in self.plan.tasks:
            unique_probe_tasks.setdefault(
                (task.runtime_role, task.image, task.requirements_sha256),
                task,
            )
        probe_inputs = [unique_probe_tasks[key] for key in sorted(unique_probe_tasks)]

        async def probe_one(raw_task: object) -> tuple[tuple[str, str, str], ProbeResult]:
            task = raw_task
            assert isinstance(task, MaterializationTask)
            response = await self.runner.invoke(_probe_request(task, self.plan))
            return (
                (task.runtime_role, task.image, task.requirements_sha256),
                _parse_probe_result(response, task, self.plan),
            )

        probe_pairs = await _bounded_map_with_anchor(
            anchor,
            probe_inputs,
            self.plan.worker.probe_concurrency,
            probe_one,
        )
        probes = dict(probe_pairs)  # type: ignore[arg-type]

        missing_groups: dict[tuple[str, str], list[MaterializationTask]] = {}
        for task in self.plan.tasks:
            probe = probes[(task.runtime_role, task.image, task.requirements_sha256)]
            if not probe.satisfied:
                missing_groups.setdefault(
                    (task.requirements_sha256, probe.runtime_fingerprint.sha256),
                    [],
                ).append(task)

        representative_inputs = [
            sorted(tasks, key=lambda task: (task.image, task.task_key, task.runtime_role))[0]
            for _, tasks in sorted(missing_groups.items())
        ]
        async def build_discovery(raw_task: object) -> tuple[tuple[str, str], MaterializationTask, BuiltWheelhouse]:
            task = raw_task
            assert isinstance(task, MaterializationTask)
            probe = probes[(task.runtime_role, task.image, task.requirements_sha256)]
            response = await self.runner.invoke(_build_request(task, probe, self.plan, "discover"))
            built = _parse_build_result(response, task, probe, self.plan, "discover")
            return (task.requirements_sha256, probe.runtime_fingerprint.sha256), task, built

        discovered = await _bounded_map_with_anchor(
            anchor,
            representative_inputs,
            self.plan.worker.build_concurrency,
            build_discovery,
        )
        built_by_task: dict[str, BuiltWheelhouse] = {}
        image_build_inputs: list[MaterializationTask] = []
        for raw in discovered:
            group_key, representative, built = raw  # type: ignore[misc]
            group = missing_groups[group_key]
            if built.scope == "universal":
                for task in group:
                    built_by_task[task.task_key] = built
                continue
            for task in group:
                if task.image == representative.image:
                    built_by_task[task.task_key] = built
                else:
                    image_build_inputs.append(task)

        unique_image_builds: dict[tuple[str, str], MaterializationTask] = {}
        for task in image_build_inputs:
            unique_image_builds.setdefault((task.image, task.requirements_sha256), task)

        async def build_image(raw_task: object) -> tuple[tuple[str, str], BuiltWheelhouse]:
            task = raw_task
            assert isinstance(task, MaterializationTask)
            probe = probes[(task.runtime_role, task.image, task.requirements_sha256)]
            response = await self.runner.invoke(_build_request(task, probe, self.plan, "image"))
            return (task.image, task.requirements_sha256), _parse_build_result(
                response,
                task,
                probe,
                self.plan,
                "image",
            )

        image_build_pairs = await _bounded_map_with_anchor(
            anchor,
            [unique_image_builds[key] for key in sorted(unique_image_builds)],
            self.plan.worker.build_concurrency,
            build_image,
        )
        image_builds = dict(image_build_pairs)  # type: ignore[arg-type]
        for task in image_build_inputs:
            built_by_task[task.task_key] = image_builds[(task.image, task.requirements_sha256)]

        validation_contracts: dict[
            str,
            tuple[MaterializationTask, ProbeResult, BuiltWheelhouse, dict[str, object]],
        ] = {}
        for task in self.plan.tasks:
            probe = probes[(task.runtime_role, task.image, task.requirements_sha256)]
            if probe.satisfied:
                continue
            built = built_by_task[task.task_key]
            request = _validate_request(task, probe, built, self.plan)
            validation_contracts.setdefault(
                _sha256(canonical_json(request)),
                (task, probe, built, request),
            )

        async def validate_one(raw_contract: object) -> None:
            task, probe, built, request = raw_contract  # type: ignore[misc]
            response = await self.runner.invoke(request)
            _parse_validate_result(response, task, probe, built)

        await _bounded_map_with_anchor(
            anchor,
            [validation_contracts[key] for key in sorted(validation_contracts)],
            self.plan.worker.validate_concurrency,
            validate_one,
        )
        self.plan.revalidate()
        self.runner.executable.revalidate()
        await self.runner.recover_stale_local_processes()
        final_recovery, interrupted = await self.runner.stop_provider_anchor(anchor, "final")
        if interrupted:
            raise asyncio.CancelledError
        self.plan.revalidate()
        self.runner.executable.revalidate()
        return self._publish(probes, built_by_task, final_recovery)

    def _publish(
        self,
        probes: Mapping[tuple[str, str, str], ProbeResult],
        built_by_task: Mapping[str, BuiltWheelhouse],
        final_recovery: Mapping[str, object],
    ):
        self.runner.require_provider_epoch()
        output_parent = self.output_root.parent
        parent_descriptor, parent_status, _ = _open_absolute_nofollow(
            output_parent,
            "catalog_output_changed",
        )
        try:
            parent_identity = _directory_identity(parent_status, "catalog_output_changed")
        except BaseException:
            os.close(parent_descriptor)
            raise
        if parent_identity != self._output_parent_identity:
            os.close(parent_descriptor)
            _fail("catalog_output_changed")
        lock_path = output_parent / f".{self.output_root.name}.publish.lock"
        publish_lock = _ExclusiveFileLock(
            lock_path,
            "catalog_publish_locked",
            directory_descriptor=parent_descriptor,
        )
        lock_acquired = False
        staging_descriptor: int | None = None
        try:
            publish_lock.__enter__()
            lock_acquired = True
            _revalidate_directory_path(output_parent, parent_identity, "catalog_output_changed")
            staging_name, staging_descriptor, staging_identity = _create_staging_directory(
                parent_descriptor,
                self.output_root.name,
            )
            staging = output_parent / staging_name
            expected_files: dict[str, tuple[str, int]] = {}
            requirement_sets: dict[str, dict[str, object]] = {}
            coverages: dict[str, dict[str, object]] = {}
            task_bindings: list[dict[str, object]] = []
            copied_archives: set[str] = set()
            copied_manifests: set[str] = set()
            copied_inventories: set[str] = set()
            for task in self.plan.tasks:
                probe = probes[(task.runtime_role, task.image, task.requirements_sha256)]
                requirement_sets[task.requirements_sha256] = {
                    "requirements": list(task.requirements),
                    "requirements_sha256": task.requirements_sha256,
                }
                if probe.satisfied:
                    assert probe.closure is not None
                    inventory = {
                        "schema_version": IMAGE_INVENTORY_SCHEMA_VERSION,
                        "image": task.image,
                        "requirements": list(task.requirements),
                        "requirements_sha256": task.requirements_sha256,
                        "runtime_fingerprint": probe.runtime_fingerprint.record(),
                        "runtime_fingerprint_sha256": probe.runtime_fingerprint.sha256,
                        "installed_inventory": [list(item) for item in probe.installed_inventory],
                        "installed_inventory_sha256": probe.installed_inventory_sha256,
                        "closure": probe.closure.record(),
                        "probe": {
                            "code_sha256": self.plan.identity.inventory_probe_code_sha256,
                            "environment_sha256": self.plan.identity.inventory_probe_environment_sha256,
                            "approval_sha256": self.plan.identity.inventory_probe_approval_sha256,
                        },
                    }
                    inventory_payload = canonical_json(inventory)
                    artifact_sha256 = _sha256(inventory_payload)
                    if artifact_sha256 not in copied_inventories:
                        _publish_content(
                            staging,
                            "inventories",
                            artifact_sha256,
                            ".json",
                            inventory_payload,
                            expected_files,
                        )
                        copied_inventories.add(artifact_sha256)
                    scope = "image"
                    image: str | None = task.image
                    mode = "image-inventory"
                else:
                    built = built_by_task[task.task_key]
                    artifact_sha256 = built.manifest_sha256
                    if built.archive_sha256 not in copied_archives:
                        archive = built.archive_seal.read_verified(
                            built.archive_path.parent,
                            maximum=MAX_WHEELHOUSE_BYTES,
                            code="build_artifact_changed",
                        )
                        _publish_content(
                            staging,
                            "archives",
                            built.archive_sha256,
                            ".tar",
                            archive,
                            expected_files,
                        )
                        copied_archives.add(built.archive_sha256)
                    if artifact_sha256 not in copied_manifests:
                        _publish_content(
                            staging,
                            "manifests",
                            artifact_sha256,
                            ".json",
                            built.manifest_payload,
                            expected_files,
                        )
                        copied_manifests.add(artifact_sha256)
                    scope = built.scope
                    image = built.image
                    mode = "wheelhouse"
                coverage_core = {
                    "requirements_sha256": task.requirements_sha256,
                    "runtime_fingerprint": probe.runtime_fingerprint.record(),
                    "runtime_fingerprint_sha256": probe.runtime_fingerprint.sha256,
                    "scope": scope,
                    "image": image,
                    "mode": mode,
                    "artifact_sha256": artifact_sha256,
                }
                coverage_sha256 = _sha256(canonical_json(coverage_core))
                coverages[coverage_sha256] = {
                    "coverage_sha256": coverage_sha256,
                    **coverage_core,
                }
                binding_core = {
                    "task_key": task.task_key,
                    "runtime_role": task.runtime_role,
                    "image": task.image,
                    "requirements_sha256": task.requirements_sha256,
                    "coverage_sha256": coverage_sha256,
                }
                task_bindings.append(
                    {
                        **binding_core,
                        "binding_sha256": _sha256(canonical_json(binding_core)),
                    }
                )
            catalog = {
                "schema_version": CATALOG_SCHEMA_VERSION,
                "identity": self.plan.identity.record(),
                "identity_sha256": self.plan.identity.sha256,
                "policy": {
                    "source_policy_sha256": self.plan.policy.source_policy_sha256,
                    "source_policy_approval_sha256": self.plan.policy.source_policy_approval_sha256,
                    "approved_binary_artifacts": sorted(self.plan.policy.approved_binary_artifacts),
                    "approved_binary_artifacts_sha256": (self.plan.identity.approved_binary_artifacts_sha256),
                    "approved_source_attestations": sorted(self.plan.policy.approved_source_attestations),
                    "approved_source_attestations_sha256": self.plan.identity.approved_source_attestations_sha256,
                    "approved_toolchains": sorted(self.plan.policy.approved_toolchains),
                    "approved_toolchains_sha256": self.plan.identity.approved_toolchains_sha256,
                },
                "requirement_sets": [requirement_sets[key] for key in sorted(requirement_sets)],
                "coverages": [coverages[key] for key in sorted(coverages)],
                "task_bindings": sorted(task_bindings, key=lambda item: str(item["task_key"])),
            }
            catalog_payload = canonical_json(catalog)
            catalog_sha256 = _sha256(catalog_payload)
            catalog_path = staging / "catalog.json"
            atomic_write_bytes(catalog_path, catalog_payload, mode=0o400)
            expected_files["catalog.json"] = (catalog_sha256, len(catalog_payload))
            launch_receipt = canonical_json(
                {
                    "schema_version": PRIVATE_LAUNCH_RECEIPT_SCHEMA_VERSION,
                    "catalog_file": "catalog.json",
                    "catalog_sha256": catalog_sha256,
                    "identity_sha256": self.plan.identity.sha256,
                    "expected_task_count": self.plan.expected_task_count,
                    "provider_epoch": {
                        "exclusive_socket_lock": True,
                        "exclusive_wal_lock": True,
                    },
                    "provider_recovery": dict(final_recovery),
                }
            )
            atomic_write_bytes(staging / "launch.json", launch_receipt, mode=0o400)
            expected_files["launch.json"] = (_sha256(launch_receipt), len(launch_receipt))
            listed_staging = os.stat(staging_name, dir_fd=parent_descriptor, follow_symlinks=False)
            if _directory_identity(listed_staging, "catalog_staging_invalid") != staging_identity:
                _fail("catalog_staging_invalid")
            catalog_reader = OfflineVerifierCatalog.load(
                catalog_path,
                catalog_sha256,
                self.plan.identity,
                project_root=self.project_root,
                dataset_root=self.dataset_root,
            )
            receipt = catalog_reader.preflight(
                (task.expected_binding() for task in self.plan.tasks),
                expected_task_count=self.plan.expected_task_count,
            )
            _seal_and_fsync_directory_tree(staging_descriptor, expected_files)
            os.fsync(parent_descriptor)
            _rename_noreplace_at(
                parent_descriptor,
                output_parent,
                parent_identity,
                staging_name,
                self.output_root.name,
                staging_identity,
            )
            try:
                final_descriptor = os.open(
                    self.output_root.name,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_descriptor,
                )
                try:
                    if (
                        _directory_identity(
                            os.fstat(final_descriptor),
                            "catalog_publish_failed",
                        )
                        != staging_identity
                    ):
                        _fail("catalog_publish_failed")
                    _seal_and_fsync_directory_tree(final_descriptor, expected_files)
                finally:
                    os.close(final_descriptor)
            except OfflineCatalogError:
                raise
            except OSError as publish_error:
                _fail("catalog_publish_failed", publish_error)
            _revalidate_named_directory(
                parent_descriptor,
                output_parent,
                parent_identity,
                self.output_root.name,
                staging_identity,
                "catalog_publish_failed",
            )
            os.fsync(parent_descriptor)
            _revalidate_named_directory(
                parent_descriptor,
                output_parent,
                parent_identity,
                self.output_root.name,
                staging_identity,
                "catalog_publish_failed",
            )
            return receipt
        finally:
            if staging_descriptor is not None:
                os.close(staging_descriptor)
            if lock_acquired:
                publish_lock.__exit__()
            os.close(parent_descriptor)
            # Failed staging directories remain private for forensic recovery.


def _revalidate_directory_path(
    path: Path,
    expected_identity: tuple[int, int, int, int],
    code: str,
) -> None:
    descriptor, status, _ = _open_absolute_nofollow(path, code)
    try:
        observed = _directory_identity(status, code)
    finally:
        os.close(descriptor)
    if observed != expected_identity:
        _fail(code)


def _create_staging_directory(
    parent_descriptor: int,
    output_name: str,
) -> tuple[str, int, tuple[int, int, int, int]]:
    for _ in range(128):
        name = f".{output_name}.staging-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        except OSError as error:
            _fail("catalog_staging_invalid", error)
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_descriptor,
            )
            os.fchmod(descriptor, 0o700)
            identity = _directory_identity(os.fstat(descriptor), "catalog_staging_invalid")
        except OfflineCatalogError:
            if "descriptor" in locals():
                os.close(descriptor)
            raise
        except OSError as error:
            if "descriptor" in locals():
                os.close(descriptor)
            _fail("catalog_staging_invalid", error)
        return name, descriptor, identity
    _fail("catalog_staging_invalid")


def _revalidate_named_directory(
    parent_descriptor: int,
    parent_path: Path,
    parent_identity: tuple[int, int, int, int],
    name: str,
    expected_identity: tuple[int, int, int, int],
    code: str,
) -> None:
    if _directory_identity(os.fstat(parent_descriptor), code) != parent_identity:
        _fail(code)
    try:
        listed = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as error:
        _fail(code, error)
    if _directory_identity(listed, code) != expected_identity:
        _fail(code)
    _revalidate_directory_path(parent_path, parent_identity, code)


def _private_file_identity(status: os.stat_result) -> tuple[int, ...]:
    if (
        not stat.S_ISREG(status.st_mode)
        or stat.S_IMODE(status.st_mode) != 0o400
        or status.st_nlink != 1
        or status.st_uid != os.geteuid()
    ):
        _fail("catalog_staging_invalid")
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_nlink,
        status.st_uid,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _seal_and_fsync_directory_tree(
    root_descriptor: int,
    expected_files: Mapping[str, tuple[str, int]],
) -> None:
    expected_directories = {""}
    for raw_path, (digest, size) in expected_files.items():
        path = PurePosixPath(raw_path)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
            or not _is_sha256(digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            _fail("catalog_staging_invalid")
        for index in range(1, len(path.parts)):
            expected_directories.add("/".join(path.parts[:index]))

    observed_files: dict[str, tuple[str, int]] = {}
    observed_directories: set[str] = set()

    def visit(directory_descriptor: int, prefix: str) -> None:
        directory_identity = _directory_identity(
            os.fstat(directory_descriptor),
            "catalog_staging_invalid",
        )
        observed_directories.add(prefix)
        try:
            names = sorted(os.listdir(directory_descriptor))
        except OSError as error:
            _fail("catalog_staging_invalid", error)
        for name in names:
            if name in {"", ".", ".."} or "/" in name or "\x00" in name:
                _fail("catalog_staging_invalid")
            relative = f"{prefix}/{name}" if prefix else name
            try:
                listed = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
                if stat.S_ISDIR(listed.st_mode):
                    child_descriptor = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_descriptor,
                    )
                    try:
                        child_identity = _directory_identity(
                            os.fstat(child_descriptor),
                            "catalog_staging_invalid",
                        )
                        if child_identity != _directory_identity(listed, "catalog_staging_invalid"):
                            _fail("catalog_staging_invalid")
                        visit(child_descriptor, relative)
                        final_listed = os.stat(
                            name,
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                        if child_identity != _directory_identity(final_listed, "catalog_staging_invalid"):
                            _fail("catalog_staging_invalid")
                    finally:
                        os.close(child_descriptor)
                elif stat.S_ISREG(listed.st_mode):
                    file_descriptor = os.open(
                        name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=directory_descriptor,
                    )
                    try:
                        before = os.fstat(file_descriptor)
                        identity = _private_file_identity(before)
                        if identity != _private_file_identity(listed):
                            _fail("catalog_staging_invalid")
                        digest = hashlib.sha256()
                        total = 0
                        while chunk := os.read(file_descriptor, 1024 * 1024):
                            digest.update(chunk)
                            total += len(chunk)
                        if identity != _private_file_identity(os.fstat(file_descriptor)):
                            _fail("catalog_staging_invalid")
                        final_listed = os.stat(
                            name,
                            dir_fd=directory_descriptor,
                            follow_symlinks=False,
                        )
                        if identity != _private_file_identity(final_listed):
                            _fail("catalog_staging_invalid")
                        observed_files[relative] = (digest.hexdigest(), total)
                        os.fsync(file_descriptor)
                    finally:
                        os.close(file_descriptor)
                else:
                    _fail("catalog_staging_invalid")
            except OfflineCatalogError:
                raise
            except OSError as error:
                _fail("catalog_staging_invalid", error)
        try:
            if sorted(os.listdir(directory_descriptor)) != names:
                _fail("catalog_staging_invalid")
            if (
                _directory_identity(
                    os.fstat(directory_descriptor),
                    "catalog_staging_invalid",
                )
                != directory_identity
            ):
                _fail("catalog_staging_invalid")
            os.fsync(directory_descriptor)
        except OSError as error:
            _fail("catalog_staging_invalid", error)

    visit(root_descriptor, "")
    if observed_files != dict(expected_files) or observed_directories != expected_directories:
        _fail("catalog_staging_invalid")


def _rename_noreplace_at(
    parent_descriptor: int,
    parent_path: Path,
    parent_identity: tuple[int, int, int, int],
    source_name: str,
    destination_name: str,
    source_identity: tuple[int, int, int, int],
) -> None:
    if (
        _PRIVATE_OUTPUT_NAME_RE.fullmatch(destination_name) is None
        or source_name in {"", ".", ".."}
        or "/" in source_name
        or "\x00" in source_name
    ):
        _fail("catalog_publish_failed")
    _revalidate_directory_path(parent_path, parent_identity, "catalog_output_changed")
    try:
        listed_source = os.stat(source_name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as error:
        _fail("catalog_publish_failed", error)
    if _directory_identity(listed_source, "catalog_staging_invalid") != source_identity:
        _fail("catalog_staging_invalid")
    try:
        renameat2 = _LIBC.renameat2
    except (AttributeError, OSError) as error:
        _fail("catalog_noreplace_unavailable", error)
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = renameat2(
        parent_descriptor,
        os.fsencode(source_name),
        parent_descriptor,
        os.fsencode(destination_name),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            _fail("catalog_output_changed")
        _fail("catalog_publish_failed", OSError(error_number, os.strerror(error_number)))
    try:
        listed_destination = os.stat(destination_name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as error:
        _fail("catalog_publish_failed", error)
    if _directory_identity(listed_destination, "catalog_publish_failed") != source_identity:
        _fail("catalog_publish_failed")
    _revalidate_directory_path(parent_path, parent_identity, "catalog_output_changed")


def _rename_noreplace(source: Path, destination: Path) -> None:
    if (
        not source.is_absolute()
        or not destination.is_absolute()
        or source.parent != destination.parent
        or source.name in {"", ".", ".."}
        or destination.name in {"", ".", ".."}
    ):
        _fail("catalog_publish_failed")
    parent_descriptor = None
    try:
        parent_descriptor, parent_status, _ = _open_absolute_nofollow(
            source.parent,
            "catalog_publish_failed",
        )
        parent_identity = _directory_identity(parent_status, "catalog_publish_failed")
        source_status = os.stat(source.name, dir_fd=parent_descriptor, follow_symlinks=False)
        source_identity = _directory_identity(source_status, "catalog_publish_failed")
        _rename_noreplace_at(
            parent_descriptor,
            source.parent,
            parent_identity,
            source.name,
            destination.name,
            source_identity,
        )
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _publish_content(
    root: Path,
    kind: str,
    digest: str,
    suffix: str,
    payload: bytes,
    expected_files: dict[str, tuple[str, int]],
) -> None:
    directory = root / kind / "sha256" / digest[:2]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for current in (root / kind, root / kind / "sha256", directory):
        current.chmod(0o700)
    path = directory / f"{digest}{suffix}"
    relative = path.relative_to(root).as_posix()
    if _sha256(payload) != digest:
        _fail("publish_content_invalid")
    expected = (digest, len(payload))
    if relative in expected_files and expected_files[relative] != expected:
        _fail("publish_content_invalid")
    expected_files[relative] = expected
    if path.exists():
        observed, _ = _read_private_file(
            root, path, maximum=max(MAX_MANIFEST_BYTES, MAX_WHEELHOUSE_BYTES), code="publish_content_invalid"
        )
        if observed != payload:
            _fail("publish_content_invalid")
        return
    atomic_write_bytes(path, payload, mode=0o400)


async def materialize_catalog(
    *,
    plan_path: Path,
    plan_sha256: str,
    worker_path: Path,
    work_root: Path,
    output_root: Path,
    project_root: Path,
    dataset_root: Path,
):
    plan = MaterializationPlan.load(
        plan_path,
        plan_sha256,
        project_root=project_root,
        dataset_root=dataset_root,
    )
    validated_work_root = _validate_private_root(work_root, project_root, dataset_root)
    with _ExclusiveFileLock(validated_work_root / ".materialize.lock", "materialization_already_running"):
        runner = WorkerRunner(worker_path, plan.worker, validated_work_root)
        with runner.provider_epoch():
            materializer = OfflineCatalogMaterializer(
                plan,
                runner,
                work_root=validated_work_root,
                output_root=output_root,
                project_root=project_root,
                dataset_root=dataset_root,
            )
            return await materializer.materialize()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    return parser.parse_args()


async def _materialize_with_signal_teardown(**arguments):
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    assert task is not None
    installed: list[signal.Signals] = []
    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(handled_signal, task.cancel)
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(handled_signal)
    try:
        return await materialize_catalog(**arguments)
    finally:
        for handled_signal in installed:
            loop.remove_signal_handler(handled_signal)


def main() -> int:
    args = _parse_args()
    try:
        receipt = asyncio.run(
            _materialize_with_signal_teardown(
                plan_path=args.plan,
                plan_sha256=args.plan_sha256,
                worker_path=args.worker,
                work_root=args.work_root,
                output_root=args.output_root,
                project_root=args.project_root,
                dataset_root=args.dataset_root,
            )
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        print(json.dumps({"status": "failed", "error_code": "cancelled"}, sort_keys=True))
        return 130
    except OfflineCatalogError as error:
        print(json.dumps({"status": "failed", "error_code": error.code}, sort_keys=True))
        return 1
    except BaseException:
        print(json.dumps({"status": "failed", "error_code": "unexpected_failure"}, sort_keys=True))
        return 1
    print(json.dumps(receipt.to_public_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
