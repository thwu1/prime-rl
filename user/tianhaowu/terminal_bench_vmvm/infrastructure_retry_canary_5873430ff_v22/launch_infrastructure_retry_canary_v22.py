#!/usr/bin/env python3
"""Submit exactly one hash-bound, opaque infrastructure retry canary v22."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OWNER = "tianhaowu"
OWNER_UID = 656177
EXPECTED_USER_ID = f"{OWNER}({OWNER_UID})"
CLUSTER = "fair-cw-use2-3"
BASE = Path("/checkpoint/ram/tianhaowu/terminal_bench_vmvm")
ARTIFACT_ROOT = BASE / "oracle/infrastructure_retry_canary_5873430ff_v22"
ARTIFACT_ROOT_ENTRIES = {
    "README.md": 0o500,
    "audit_infrastructure_retry_canary_v22.py": 0o500,
    "build_infrastructure_retry_selection_v22.py": 0o500,
    "launch_infrastructure_retry_canary_v22.py": 0o500,
    "packaging-26.3-py3-none-any.whl.snapshot.json": 0o400,
    "run_infrastructure_retry_canary_v22.sbatch": 0o500,
    "test_retry_canary_v22_public.py": 0o500,
    "test_retry_launcher_v22_public.py": 0o500,
    "test_retry_postrun_audit_v22_public.py": 0o500,
}
CANONICAL_SELF = ARTIFACT_ROOT / "launch_infrastructure_retry_canary_v22.py"
GENERATOR = ARTIFACT_ROOT / "build_infrastructure_retry_selection_v22.py"
GENERATOR_SHA256 = "4b13ea20ebf4b63057c752efe86044aa2f54a52e87426ec033fbd8e087334fad"
JOB_WRAPPER = ARTIFACT_ROOT / "run_infrastructure_retry_canary_v22.sbatch"
JOB_WRAPPER_SHA256 = "ba819113d0105ea8e747b3bbda5f12f4dbc4f59cbc7657e7e836d5376848583c"
V1_LAUNCHER = (
    BASE
    / "oracle/infrastructure_retry_canary_63dc81dee_v1/launch_infrastructure_retry_canary.py"
)
V1_LAUNCHER_SHA256 = "7312687438b5d2b3f7879c777e8140939d66f7daa7bc7c0de4f1ea8491e71b63"
PYTHON_REAL = Path(
    "/storage/home/tianhaowu/.local/share/uv/python/"
    "cpython-3.13.15-linux-aarch64-gnu/bin/python3.13"
)
PYTHON_SHA256 = "f53c112756a06959fd532fa70e3108f89b90550c71f5c1afc26f8985c772a121"

SOURCE_ROOT = BASE / "sources/prime-rl-5873430ff-v22"
SOURCE_REVISION = "5873430ffbabc32672368c7df74f56023865d2b5"
SOURCE_TREE = "e7d9d5a8cf4ca06b9ff6496ea4318154c6fcd730"
VERIFIERS_REVISION = "615b1a30ee3d23cf8d835b64174229c19da887bc"
RENDERERS_REVISION = "044d9e2541f6a911cacae9da353fc063911ef1f8"
PYDANTIC_CONFIG_REVISION = "896ade4e69d8d8dff2d4b0a431b7e1c7c12d638f"
VMVM_SHA256 = "1e7c8ac2906a45d8212d609b5900fdc3d30f91ba73d4bcdb1c36dfc8bfdd09e2"
WORKFLOW = SOURCE_ROOT / "user/tianhaowu/terminal_bench_vmvm"
RUN_SBATCH = WORKFLOW / "run_oracle.sbatch"
RUN_SBATCH_SHA256 = "9f4e746a5a05217f43c684b1d5737a846555d284ea0fb924466358181e0d253c"
X86_UV = Path("/storage/home/tianhaowu/.local/x86_64/bin/uv")
X86_UV_SHA256 = "ec831939765474162efb6c8c813e2b10908b26b04eaf98ac3e2972fa12d189b9"
X86_SITE = BASE / "python_x86_64"
PACKAGING_SNAPSHOT = ARTIFACT_ROOT / "packaging-26.3-py3-none-any.whl.snapshot.json"
PACKAGING_SNAPSHOT_SHA256 = (
    "6025752344370d775f1a22e6c9d3f3bfaa57f9b5e17e2b296088864dfdc14761"
)
PACKAGING_WHEEL_SHA256 = (
    "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c"
)
PACKAGING_MEMBER_MANIFEST_SHA256 = (
    "d02fb4c0b14244ef8a78ef2b91c29d988754c230c977089eb0c65eb5152e6ea4"
)

SELECTION_ROOT = BASE / "oracle/mobius_infrastructure_retry_selection_5873430ff_v22"
TASK_FILE = SELECTION_ROOT / "retry.tasks.txt"
ROLE_FILE = SELECTION_ROOT / "selection_roles.private.json"
SELECTION_RECEIPT = SELECTION_ROOT / "selection_receipt.json"
OUTPUT_ROOT = BASE / "oracle/mobius_infrastructure_retry_run_5873430ff_v22"
RESERVATION = Path(f"{OUTPUT_ROOT}.launch-reservation")
LOG_ROOT = BASE / "logs/mobius_infrastructure_retry_run_5873430ff_v22"
INTENT = RESERVATION / "launch_intent.json"
ENVIRONMENT_FILE = RESERVATION / "slurm_environment.bin"
SUBMISSION_RECEIPT = RESERVATION / "submission_receipt.json"
FAILURE_CERTIFICATE = RESERVATION / "submission_failure.json"

HELD_POLL_INTERVAL_SECONDS = 2
HELD_REQUIRED_CONSECUTIVE = 2
HELD_CONVERGENCE_TIMEOUT_SECONDS = 982
ACTIVATION_POLL_INTERVAL_SECONDS = 2
ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS = 742
ACTIVATION_PUBLICATION_SLACK_SECONDS = 30
RELEASE_QUERY_MAX_SECONDS = 20
CANCEL_IDENTITY_POLL_INTERVAL_SECONDS = 2
CANCEL_IDENTITY_CONVERGENCE_TIMEOUT_SECONDS = 180
CANCEL_PRECONTROL_TIMEOUT_SECONDS = 90
CANCEL_TERMINAL_POLL_INTERVAL_SECONDS = 2
CANCEL_TERMINAL_CONVERGENCE_TIMEOUT_SECONDS = 300
WRAPPER_GATE_TIMEOUT_SECONDS = 900
TLS_PATH_ENV_NAMES = (
    "THRIFT_TLS_CL_CERT_PATH",
    "THRIFT_TLS_CL_KEY_PATH",
)
TLS_DIGEST_ENV_NAMES = {
    "THRIFT_TLS_CL_CERT_PATH": "RETRY_THRIFT_TLS_CL_CERT_SHA256",
    "THRIFT_TLS_CL_KEY_PATH": "RETRY_THRIFT_TLS_CL_KEY_SHA256",
}
X2P_NAMES = ("X2P_ENV", "X2P_CFG_ENV", "X2P_PROXY_URL")
X2P_DIGEST_ENV_NAMES = {
    "X2P_ENV": "RETRY_X2P_ENV_SHA256",
    "X2P_CFG_ENV": "RETRY_X2P_CFG_ENV_SHA256",
    "X2P_PROXY_URL": "RETRY_X2P_PROXY_URL_SHA256",
}
X2P_MAX_VALUE_BYTES = 4096
TLS_EXPECTED_MODE = 0o500
TLS_EXPECTED_SIZE = 5580
PEM_BLOCK_RE = re.compile(
    rb"-----BEGIN ([A-Z][A-Z0-9 ]*)-----\r?\n"
    rb"([A-Za-z0-9+/=\r\n]+?)"
    rb"-----END \1-----"
)


def _deadline_iteration_bound(timeout_seconds: int, interval_seconds: int) -> int:
    """Return a fail-safe cap that cannot precede a normally paced deadline."""

    if timeout_seconds <= 0 or interval_seconds <= 0:
        raise RuntimeError("invalid_poll_timing")
    return math.ceil(timeout_seconds / interval_seconds) + 2


HELD_POLL_MAX_ITERATIONS = _deadline_iteration_bound(
    HELD_CONVERGENCE_TIMEOUT_SECONDS, HELD_POLL_INTERVAL_SECONDS
)
ACTIVATION_POLL_MAX_ITERATIONS = _deadline_iteration_bound(
    ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS, ACTIVATION_POLL_INTERVAL_SECONDS
)
CANCEL_IDENTITY_POLL_MAX_ITERATIONS = _deadline_iteration_bound(
    CANCEL_IDENTITY_CONVERGENCE_TIMEOUT_SECONDS,
    CANCEL_IDENTITY_POLL_INTERVAL_SECONDS,
)
CANCEL_TERMINAL_POLL_MAX_ITERATIONS = _deadline_iteration_bound(
    CANCEL_TERMINAL_CONVERGENCE_TIMEOUT_SECONDS,
    CANCEL_TERMINAL_POLL_INTERVAL_SECONDS,
)
TERMINAL_STATES = {
    "BOOT_FAIL",
    "CANCELLED",
    "COMPLETED",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "REVOKED",
    "TIMEOUT",
}
ACTIVE_STATES = {"CONFIGURING", "PENDING", "RUNNING"}
IDENTITY_CONFLICT_FIELDS = {"JobId", "JobName", "UserId"}
MISMATCH_FIELD_ALLOWLIST = {
    "Account",
    "Command",
    "Dependency",
    "JobId",
    "JobName",
    "MinMemoryNode",
    "NumCPUs",
    "NumNodes",
    "Partition",
    "QOS",
    "Requeue",
    "Restarts",
    "StdErr",
    "StdOut",
    "TimeLimit",
    "UserId",
    "WorkDir",
    "activation_JobState",
    "activation_NodeList",
    "activation_accounting",
    "activation_hold",
    "activation_squeue",
    "candidate_provenance",
    "cancellation_accounting",
    "cancellation_allocation",
    "cancellation_allocation_state",
    "cancellation_squeue",
    "cancellation_steps",
    "held_BatchHost",
    "held_JobState",
    "held_NodeList",
    "held_Priority",
    "held_Reason",
    "held_StartTime",
    "held_accounting",
    "held_squeue",
    "held_steps",
    "missing_JobId",
    "missing_JobName",
    "missing_UserId",
    "scontrol_record",
    "scontrol_unavailable",
}
_CLEANUP_IN_PROGRESS = False

DATASET = BASE / "datasets/mobius-ac1f30b9"
DATASET_REVISION = "ac1f30b9ac0e6c6a20a9fe423900d9ed28a6d366"
IMAGE_MANIFEST = BASE / "mobius_images.json"
IMAGE_MANIFEST_SHA256 = (
    "118157378884021d2fc12dd83e7d9576ca606a5d229a2bd34c203d745212e009"
)
IMAGE_PREFIX = "vmvm-registry.fbinfra.net/terminal_bench"
IMAGE_TAG = "mobius-9b6988a3faf0"

EXPECTED_SELECTED = 19
EXPECTED_CANDIDATES = 15
EXPECTED_CONTROLS = 4
MINIMUM_CANDIDATE_RECOVERIES = 6
MINIMUM_VALID = EXPECTED_CONTROLS + MINIMUM_CANDIDATE_RECOVERIES
ATTEMPT_POLICY = {
    "sandbox_error": {
        "retry_scope": "exception_type_only",
        "infra_retries": 4,
        "maximum_attempts": 5,
    },
    "asyncio_timeout_error": {
        "retry_scope": "none",
        "infra_retries": 0,
        "maximum_attempts": 1,
    },
    "timeout_category_candidates": {
        "count": 11,
        "classification_only": True,
        "category_does_not_enable_retries": True,
    },
    "timeout_bounds_seconds": {"setup": 7200, "validate": 21600, "session": 43200},
    "broad_harness_error_retry": False,
}
SHA_RE = re.compile(r"[0-9a-f]{64}")
JOB_RE = re.compile(r"[1-9][0-9]*")
SAFE_CODE_RE = re.compile(r"[a-z0-9_]{1,96}")
SLUG_RE = re.compile(r"[^/\\\x00-\x1f\x7f]+")


class LaunchInterrupted(BaseException):
    """Internal signal sentinel; never serialized verbatim."""


def _credential_identity(value: os.stat_result) -> tuple[int, ...]:
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


def _descriptor_canonical_path(
    descriptor: int, code: str = "tls_credential_invalid"
) -> Path:
    """Resolve the kernel-bound target of an already-open descriptor."""

    try:
        raw = os.readlink(f"/proc/self/fd/{descriptor}")
    except OSError as error:
        raise LauncherError(code) from error
    path = Path(raw)
    if (
        not raw
        or raw.endswith(" (deleted)")
        or "\x00" in raw
        or "\n" in raw
        or "\r" in raw
        or not path.is_absolute()
        or path != Path(os.path.normpath(path))
    ):
        fail(code)
    return path


def _read_credential(descriptor: int, size: int, code: str) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        try:
            block = os.pread(descriptor, min(1 << 20, size - offset), offset)
        except OSError as error:
            raise LauncherError(code) from error
        if not block:
            fail(code)
        chunks.append(block)
        offset += len(block)
    return b"".join(chunks)


def _pem_profile(raw: bytes) -> str:
    """Classify only the exact combined PEM form allowed for shared bindings."""

    labels: list[bytes] = []
    position = 0
    for match in PEM_BLOCK_RE.finditer(raw):
        if raw[position : match.start()].strip(b" \t\r\n"):
            return "invalid"
        compact_body = b"".join(match.group(2).split())
        if not compact_body:
            return "invalid"
        try:
            decoded = base64.b64decode(compact_body, validate=True)
        except (ValueError, binascii.Error):
            return "invalid"
        if not decoded:
            return "invalid"
        labels.append(match.group(1))
        position = match.end()
    if raw[position:].strip(b" \t\r\n"):
        return "invalid"
    counts = Counter(labels)
    if len(labels) == 3 and counts == {
        b"CERTIFICATE": 2,
        b"RSA PRIVATE KEY": 1,
    }:
        return "combined"
    return "other"


class StableCredential:
    """A private, open descriptor binding for one launcher TLS input."""

    __slots__ = (
        "descriptor",
        "environment_name",
        "parent_descriptor",
        "path",
        "pem_profile",
        "raw_path",
        "sha256",
        "signature",
    )

    def __init__(
        self,
        *,
        environment_name: str,
        raw_path: Path,
        path: Path,
        parent_descriptor: int,
        descriptor: int,
        signature: tuple[int, ...],
        sha256: str,
        pem_profile: str,
    ) -> None:
        self.environment_name = environment_name
        self.raw_path = raw_path
        self.path = path
        self.parent_descriptor = parent_descriptor
        self.descriptor = descriptor
        self.signature = signature
        self.sha256 = sha256
        self.pem_profile = pem_profile

    def __repr__(self) -> str:
        return "StableCredential(<private>)"

    def revalidate(self) -> None:
        fresh_parent = -1
        fresh_raw = -1
        try:
            descriptor_status = os.fstat(self.descriptor)
            path_status = os.stat(
                self.path.name,
                dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
            fresh_parent = os.open(
                self.path.parent,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            original_parent = os.fstat(self.parent_descriptor)
            current_parent = os.fstat(fresh_parent)
            fresh_raw = os.open(
                self.raw_path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            raw_status = os.fstat(fresh_raw)
            raw_canonical = _descriptor_canonical_path(
                fresh_raw, "tls_credential_changed"
            )
            if (
                _credential_identity(descriptor_status) != self.signature
                or _credential_identity(path_status) != self.signature
                or _credential_identity(raw_status) != self.signature
            ):
                fail("tls_credential_changed")
            raw = _read_credential(
                self.descriptor, TLS_EXPECTED_SIZE, "tls_credential_changed"
            )
            canonical = self.path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise LauncherError("tls_credential_changed") from error
        finally:
            if fresh_raw >= 0:
                os.close(fresh_raw)
            if fresh_parent >= 0:
                os.close(fresh_parent)
        if (
            canonical != self.path
            or self.path.is_symlink()
            or raw_canonical != self.path
            or _credential_identity(descriptor_status) != self.signature
            or _credential_identity(path_status) != self.signature
            or _credential_identity(raw_status) != self.signature
            or (original_parent.st_dev, original_parent.st_ino)
            != (current_parent.st_dev, current_parent.st_ino)
            or hashlib.sha256(raw).hexdigest() != self.sha256
            or _pem_profile(raw) != self.pem_profile
        ):
            fail("tls_credential_changed")

    def close(self) -> None:
        descriptor, parent_descriptor = self.descriptor, self.parent_descriptor
        self.descriptor = -1
        self.parent_descriptor = -1
        first_error: OSError | None = None
        for candidate in (descriptor, parent_descriptor):
            if candidate < 0:
                continue
            try:
                os.close(candidate)
            except OSError as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error


def _capture_tls_credential(environment_name: str, raw_path: str) -> StableCredential:
    parent_descriptor = -1
    descriptor = -1
    binding: StableCredential | None = None
    try:
        raw_path_object = Path(raw_path)
        if (
            environment_name not in TLS_PATH_ENV_NAMES
            or not raw_path
            or "\x00" in raw_path
            or "\n" in raw_path
            or "\r" in raw_path
            or not raw_path_object.is_absolute()
            or raw_path_object != Path(os.path.normpath(raw_path_object))
        ):
            fail("tls_credential_invalid")
        descriptor = os.open(
            raw_path_object,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        path = _descriptor_canonical_path(descriptor)
        if (
            path.parent.resolve(strict=True) != path.parent
            or path.resolve(strict=True) != path
            or path.is_symlink()
        ):
            fail("tls_credential_invalid")
        parent_descriptor = os.open(
            path.parent,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        visible_before = os.stat(
            path.name, dir_fd=parent_descriptor, follow_symlinks=False
        )
        if (
            _credential_identity(before) != _credential_identity(visible_before)
            or not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != TLS_EXPECTED_MODE
            or before.st_uid != OWNER_UID
            or before.st_nlink != 1
            or before.st_size != TLS_EXPECTED_SIZE
        ):
            fail("tls_credential_invalid")
        raw = _read_credential(descriptor, before.st_size, "tls_credential_invalid")
        after = os.fstat(descriptor)
        visible_after = os.stat(
            path.name, dir_fd=parent_descriptor, follow_symlinks=False
        )
        if (
            _credential_identity(before) != _credential_identity(after)
            or _credential_identity(after) != _credential_identity(visible_after)
        ):
            fail("tls_credential_changed")
        binding = StableCredential(
            environment_name=environment_name,
            raw_path=raw_path_object,
            path=path,
            parent_descriptor=parent_descriptor,
            descriptor=descriptor,
            signature=_credential_identity(after),
            sha256=hashlib.sha256(raw).hexdigest(),
            pem_profile=_pem_profile(raw),
        )
        parent_descriptor = -1
        descriptor = -1
        try:
            binding.revalidate()
        except BaseException:
            binding.close()
            raise
        return binding
    except LauncherError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise LauncherError("tls_credential_invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def capture_tls_credentials(
    environment: Mapping[str, str] | None = None,
) -> dict[str, StableCredential]:
    values = os.environ if environment is None else environment
    bindings: dict[str, StableCredential] = {}
    try:
        for name in TLS_PATH_ENV_NAMES:
            value = values.get(name)
            if not isinstance(value, str) or not value:
                fail("tls_credential_environment_invalid")
            bindings[name] = _capture_tls_credential(name, value)
        _validate_tls_credential_pair(bindings)
        return bindings
    except BaseException:
        close_tls_credentials(bindings)
        raise


def close_tls_credentials(bindings: Mapping[str, StableCredential]) -> None:
    for name in TLS_PATH_ENV_NAMES:
        binding = bindings.get(name)
        if binding is None:
            continue
        try:
            binding.close()
        except OSError:
            pass


def _validate_tls_credential_pair(
    bindings: Mapping[str, StableCredential],
) -> None:
    first = bindings[TLS_PATH_ENV_NAMES[0]]
    second = bindings[TLS_PATH_ENV_NAMES[1]]
    same_inode = first.signature[:2] == second.signature[:2]
    same_target = first.path == second.path
    same_digest = first.sha256 == second.sha256
    if any((same_inode, same_target, same_digest)) and not (
        same_inode
        and same_target
        and same_digest
        and first.pem_profile == "combined"
        and second.pem_profile == "combined"
    ):
        fail("tls_credential_pair_invalid")


def revalidate_tls_credentials(bindings: Mapping[str, StableCredential]) -> None:
    if set(bindings) != set(TLS_PATH_ENV_NAMES):
        fail("tls_credential_binding_invalid")
    for name in TLS_PATH_ENV_NAMES:
        binding = bindings[name]
        if binding.environment_name != name:
            fail("tls_credential_binding_invalid")
        binding.revalidate()
    _validate_tls_credential_pair(bindings)


def private_tls_environment(
    bindings: Mapping[str, StableCredential],
) -> dict[str, str]:
    revalidate_tls_credentials(bindings)
    values: dict[str, str] = {}
    for name in TLS_PATH_ENV_NAMES:
        binding = bindings[name]
        values[name] = str(binding.path)
        values[TLS_DIGEST_ENV_NAMES[name]] = binding.sha256
    return values


def validate_private_tls_environment(values: Mapping[str, str]) -> dict[str, str]:
    expected = set(TLS_PATH_ENV_NAMES) | set(TLS_DIGEST_ENV_NAMES.values())
    if set(values) != expected or any(not isinstance(value, str) for value in values.values()):
        fail("tls_credential_binding_invalid")
    paths = [Path(values[name]) for name in TLS_PATH_ENV_NAMES]
    digests = [values[TLS_DIGEST_ENV_NAMES[name]] for name in TLS_PATH_ENV_NAMES]
    if (
        any(
            not str(path)
            or "\x00" in str(path)
            or "\n" in str(path)
            or "\r" in str(path)
            or not path.is_absolute()
            or path != Path(os.path.normpath(path))
            for path in paths
        )
        or any(SHA_RE.fullmatch(digest) is None for digest in digests)
        or (paths[0] == paths[1]) != (digests[0] == digests[1])
    ):
        fail("tls_credential_binding_invalid")
    return dict(values)


def _parse_slurm_environment(raw: bytes) -> dict[str, str]:
    try:
        if not raw or not raw.endswith(b"\0"):
            fail("slurm_environment_invalid")
        parsed: dict[str, str] = {}
        for entry in raw[:-1].split(b"\0"):
            key_raw, value_raw = entry.split(b"=", 1)
            key = key_raw.decode("utf-8", errors="strict")
            value = value_raw.decode("utf-8", errors="strict")
            if not key or key in parsed:
                fail("slurm_environment_invalid")
            parsed[key] = value
    except (UnicodeDecodeError, ValueError) as error:
        raise LauncherError("slurm_environment_invalid") from error
    return parsed


def parse_private_tls_environment(raw: bytes) -> dict[str, str]:
    parsed = _parse_slurm_environment(raw)
    return validate_private_tls_environment(
        {
            name: parsed.get(name, "")
            for name in (*TLS_PATH_ENV_NAMES, *TLS_DIGEST_ENV_NAMES.values())
        }
    )


def validate_private_x2p_environment(values: Mapping[str, str]) -> dict[str, str]:
    if set(values) != set(X2P_NAMES):
        fail("x2p_environment_invalid")
    validated: dict[str, str] = {}
    for name in X2P_NAMES:
        value = values.get(name)
        if (
            not isinstance(value, str)
            or not value
            or any(character in value for character in "\x00\r\n")
        ):
            fail("x2p_environment_invalid")
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise LauncherError("x2p_environment_invalid") from error
        if len(encoded) > X2P_MAX_VALUE_BYTES:
            fail("x2p_environment_invalid")
        validated[name] = value
    return validated


def capture_x2p_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if environment is None else environment
    if {name for name in X2P_NAMES if name in source} != set(X2P_NAMES):
        fail("x2p_environment_invalid")
    return validate_private_x2p_environment(
        {name: source.get(name, "") for name in X2P_NAMES}
    )


def x2p_environment_sha256(values: Mapping[str, str]) -> dict[str, str]:
    validated = validate_private_x2p_environment(values)
    return {
        name: sha256_bytes(validated[name].encode("utf-8")) for name in X2P_NAMES
    }


def validate_x2p_environment_sha256(values: Mapping[str, str]) -> dict[str, str]:
    if set(values) != set(X2P_NAMES):
        fail("x2p_environment_commitment_invalid")
    commitments = dict(values)
    if any(
        not isinstance(commitments[name], str)
        or SHA_RE.fullmatch(commitments[name]) is None
        for name in X2P_NAMES
    ):
        fail("x2p_environment_commitment_invalid")
    return commitments


def private_x2p_environment(values: Mapping[str, str]) -> dict[str, str]:
    validated = validate_private_x2p_environment(values)
    commitments = x2p_environment_sha256(validated)
    return {
        **validated,
        **{X2P_DIGEST_ENV_NAMES[name]: commitments[name] for name in X2P_NAMES},
    }


def parse_private_x2p_environment(raw: bytes) -> dict[str, str]:
    parsed = _parse_slurm_environment(raw)
    values = validate_private_x2p_environment(
        {name: parsed.get(name, "") for name in X2P_NAMES}
    )
    commitments = validate_x2p_environment_sha256(
        {name: parsed.get(X2P_DIGEST_ENV_NAMES[name], "") for name in X2P_NAMES}
    )
    if commitments != x2p_environment_sha256(values):
        fail("x2p_environment_commitment_invalid")
    return values


def _load_frozen(path: Path, digest: str, name: str):
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1 << 20, remaining))
            if not chunk:
                raise RuntimeError("frozen_dependency_short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise RuntimeError("frozen_dependency_unavailable") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    raw = b"".join(chunks)

    def identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_uid,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    if (
        path.is_symlink()
        or path.resolve(strict=True) != path
        or identity(before) != identity(after)
        or identity(after) != identity(path_after)
        or not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o500
        or before.st_uid != OWNER_UID
        or before.st_nlink != 1
        or __import__("hashlib").sha256(raw).hexdigest() != digest
    ):
        raise RuntimeError("frozen_dependency_invalid")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)  # noqa: S102
    return module


V1 = _load_frozen(V1_LAUNCHER, V1_LAUNCHER_SHA256, "retry_launcher_v1_frozen")
LauncherError = V1.LauncherError
fail = V1.fail
canonical_json = V1.canonical_json
sha256_bytes = V1.sha256_bytes
strict_json = V1.strict_json
file_bytes = V1.file_bytes
require_directory = V1.require_directory
clean_environment = V1.clean_environment
git_output = V1.git_output
bounded_run = V1.bounded_run
validate_tmux_ancestry = V1.validate_tmux_ancestry
environment_bytes = V1.environment_bytes
write_once = V1.write_once
envelope = V1.envelope
sync_directory = V1.sync_directory
scheduler_matches = V1.scheduler_matches
lookup_submission = V1.lookup_submission
parse_scontrol_record = V1.parse_scontrol_record
if V1.QUERY_TIMEOUT_SECONDS != RELEASE_QUERY_MAX_SECONDS:
    raise RuntimeError("release_query_bound_mismatch")


def _artifact_directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def validate_artifact_root_inventory(
    root: Path = ARTIFACT_ROOT,
    expected: Mapping[str, int] = ARTIFACT_ROOT_ENTRIES,
) -> None:
    """Require one stable, canonical directory containing exactly nine files."""

    directory_fd = -1
    fresh_fd = -1
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        if root.is_symlink() or root.resolve(strict=True) != root:
            fail("artifact_root_inventory_invalid")
        directory_fd = os.open(root, flags)
        before = os.fstat(directory_fd)
        names_before = os.listdir(directory_fd)
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o700
            or before.st_uid != OWNER_UID
            or before.st_nlink != 2
            or len(names_before) != len(expected)
            or set(names_before) != set(expected)
        ):
            fail("artifact_root_inventory_invalid")
        for name, mode in expected.items():
            status = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(status.st_mode)
                or stat.S_IMODE(status.st_mode) != mode
                or status.st_uid != OWNER_UID
                or status.st_nlink != 1
            ):
                fail("artifact_root_inventory_invalid")
        after = os.fstat(directory_fd)
        names_after = os.listdir(directory_fd)
        fresh_fd = os.open(root, flags)
        current = os.fstat(fresh_fd)
        names_current = os.listdir(fresh_fd)
        if (
            _artifact_directory_identity(before) != _artifact_directory_identity(after)
            or _artifact_directory_identity(after)
            != _artifact_directory_identity(current)
            or names_after != names_before
            or names_current != names_before
            or root.resolve(strict=True) != root
        ):
            fail("artifact_root_inventory_invalid")
    except LauncherError:
        raise
    except (OSError, RuntimeError) as error:
        raise LauncherError("artifact_root_inventory_invalid") from error
    finally:
        if fresh_fd >= 0:
            os.close(fresh_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


class LifecycleFailure(LauncherError):
    """Stable lifecycle failure carrying only allowlisted aggregate telemetry."""

    def __init__(
        self,
        code: str,
        *,
        held_validation: Mapping[str, Any] | None = None,
        release: Mapping[str, Any] | None = None,
        cancellation: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.held_validation = dict(held_validation) if held_validation is not None else None
        self.release = dict(release) if release is not None else None
        self.cancellation = dict(cancellation) if cancellation is not None else None


def _query_timeout(deadline: float | None) -> float:
    if deadline is None:
        return float(V1.QUERY_TIMEOUT_SECONDS)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LauncherError("scheduler_query_deadline_exhausted")
    return min(float(V1.QUERY_TIMEOUT_SECONDS), remaining)


def _bounded_poll_sleep(deadline: float, interval: int) -> bool:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    time.sleep(min(float(interval), remaining))
    return time.monotonic() < deadline


def invoke_sbatch(command: Sequence[str]) -> tuple[str, int, str]:
    """Invoke the sole sbatch and reap its process group on every exit path."""
    outcome = "completed"
    with (
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        try:
            process = subprocess.Popen(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=SOURCE_ROOT,
                env=clean_environment(),
                start_new_session=True,
            )
        except OSError:
            return "exec_error", 127, ""
        try:
            try:
                return_code = process.wait(timeout=V1.SUBMIT_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                outcome = "timeout"
                return_code = 124
        except BaseException:
            for process_signal in (signal.SIGTERM, signal.SIGKILL):
                if process.poll() is not None:
                    break
                try:
                    os.killpg(process.pid, process_signal)
                except OSError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    continue
            raise
        if outcome == "timeout":
            cleanup_failed = False
            for process_signal in (signal.SIGTERM, signal.SIGKILL):
                if process.poll() is not None:
                    break
                try:
                    os.killpg(process.pid, process_signal)
                except ProcessLookupError:
                    pass
                except OSError:
                    cleanup_failed = True
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    cleanup_failed = True
            if process.poll() is None:
                cleanup_failed = True
            if cleanup_failed:
                outcome = "cleanup_failed"
            return_code = process.returncode if process.returncode is not None else 124
        stdout_file.flush()
        stderr_file.flush()
        if (
            os.fstat(stdout_file.fileno()).st_size > V1.MAX_COMMAND_OUTPUT
            or os.fstat(stderr_file.fileno()).st_size > V1.MAX_COMMAND_OUTPUT
        ):
            return "malformed", return_code, ""
        stdout_file.seek(0)
        try:
            stdout = stdout_file.read().decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return "malformed", return_code, ""
    return outcome, return_code, stdout


def _validate_outer_environment(environment: Mapping[str, str]) -> None:
    expected_names = {
        "APPROVED_RETRY_LAUNCHER_SHA256",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "TMUX",
        "TMUX_PANE",
        "THRIFT_TLS_CL_CERT_PATH",
        "THRIFT_TLS_CL_KEY_PATH",
        "USER",
        *X2P_NAMES,
    }
    if (
        set(environment) != expected_names
        or environment.get("HOME") != "/storage/home/tianhaowu"
        or environment.get("PATH") != "/usr/bin:/bin"
        or environment.get("LANG") != "C"
        or environment.get("LC_ALL") != "C"
        or environment.get("USER") != OWNER
        or environment.get("LOGNAME") != OWNER
        or environment.get("PYTHONDONTWRITEBYTECODE") != "1"
    ):
        fail("outer_environment_invalid")


def validate_invocation() -> tuple[str, dict[str, StableCredential], dict[str, str]]:
    _validate_outer_environment(os.environ)
    if (
        Path(__file__) != CANONICAL_SELF
        or Path(sys.argv[0]) != CANONICAL_SELF
        or CANONICAL_SELF.resolve(strict=True) != CANONICAL_SELF
        or Path.cwd() != Path("/storage/home/tianhaowu")
        or os.getuid() != OWNER_UID
        or os.geteuid() != OWNER_UID
        or Path(sys.executable).resolve(strict=True) != PYTHON_REAL
    ):
        fail("outer_environment_invalid")
    approved = os.environ["APPROVED_RETRY_LAUNCHER_SHA256"]
    if SHA_RE.fullmatch(approved) is None:
        fail("launcher_approval_missing")
    validate_artifact_root_inventory()
    file_bytes(CANONICAL_SELF, expected_sha256=approved, mode=0o500, maximum=1 << 20)
    file_bytes(PYTHON_REAL, expected_sha256=PYTHON_SHA256, maximum=64 << 20)
    validate_tmux_ancestry()
    x2p_values = capture_x2p_environment()
    return approved, capture_tls_credentials(), x2p_values


def load_generator():
    raw = file_bytes(
        GENERATOR, expected_sha256=GENERATOR_SHA256, mode=0o500, maximum=1 << 20
    )
    module = types.ModuleType("retry_canary_v22_frozen_generator")
    module.__file__ = str(GENERATOR)
    try:
        exec(compile(raw, str(GENERATOR), "exec"), module.__dict__)  # noqa: S102
    except Exception as error:
        raise LauncherError("generator_import_invalid") from error
    if Path(module.__file__).resolve(strict=True) != GENERATOR:
        fail("generator_import_invalid")
    return module


def expected_packaging_provenance() -> dict[str, object]:
    return {
        "name": "packaging",
        "version": "26.3",
        "wheel_sha256": PACKAGING_WHEEL_SHA256,
        "wheel_size": 129_956,
        "member_count": 29,
        "member_manifest_sha256": PACKAGING_MEMBER_MANIFEST_SHA256,
        "snapshot": {
            "path": str(PACKAGING_SNAPSHOT),
            "sha256": PACKAGING_SNAPSHOT_SHA256,
            "mode": "0400",
            "uid": OWNER_UID,
            "nlink": 1,
        },
        "loader": "restricted_in_memory_exact_wheel_sources_v1",
        "site_imports": False,
        "pyc_reads": False,
    }


def validate_selection_receipt(value: Mapping[str, Any]) -> tuple[str, str, str]:
    body = dict(value)
    envelope_sha = body.pop("selection_receipt_sha256", None)
    if not isinstance(envelope_sha, str) or envelope_sha != sha256_bytes(
        canonical_json(body)
    ):
        fail("selection_receipt_invalid")
    generator = body.get("generator")
    execution_source = body.get("execution_source")
    exclusion = body.get("source_wheel_exclusion")
    module_import_closure = body.get("module_import_closure")
    selection = body.get("selection")
    launch = body.get("launch_contract")
    union = body.get("final_union")
    role = selection.get("role_file") if isinstance(selection, dict) else None
    counts = selection.get("counts") if isinstance(selection, dict) else None
    task = selection.get("task_file") if isinstance(selection, dict) else None
    if (
        set(body)
        != {
            "artifact_type",
            "attempt_policy",
            "execution_source",
            "final_union",
            "generator",
            "launch_contract",
            "module_import_closure",
            "prior_repair",
            "schema_version",
            "selection",
            "source_oracle",
            "source_wheel_exclusion",
            "state",
        }
        or body.get("schema_version") != 1
        or body.get("artifact_type")
        != "terminal_bench_vmvm_infrastructure_retry_selection_v22"
        or body.get("state") != "prepared"
        or generator != {"path": str(GENERATOR), "sha256": GENERATOR_SHA256}
        or body.get("attempt_policy") != ATTEMPT_POLICY
        or module_import_closure
        != {"packaging": expected_packaging_provenance()}
        or not isinstance(execution_source, dict)
        or set(execution_source)
        != {
            "path",
            "revision",
            "tree",
            "verifiers_revision",
            "vmvm_tb_v2_sha256",
        }
        or execution_source.get("path") != str(SOURCE_ROOT)
        or execution_source.get("revision") != SOURCE_REVISION
        or execution_source.get("tree") != SOURCE_TREE
        or execution_source.get("verifiers_revision") != VERIFIERS_REVISION
        or execution_source.get("vmvm_tb_v2_sha256") != VMVM_SHA256
        or not isinstance(exclusion, dict)
        or exclusion.get("input_entries") != 9
        or exclusion.get("scope") != "all_probe_entries"
        or exclusion.get("recovered_valid") != 0
        or exclusion.get("cardinality_receipt_sha256")
        != "7a9a73082231b6cbba1ce25ec83e362e40654f8b6471611795092717e4dcf1f8"
        or exclusion.get("cardinality_completion_sha256")
        != "573b8e9f6c5ce0ae3457540f19702e57cb552d45324cdc1cae36ff7b292ee76a"
        or not isinstance(counts, dict)
        or counts.get("retry_candidates") != EXPECTED_CANDIDATES
        or counts.get("controls") != EXPECTED_CONTROLS
        or counts.get("selected") != EXPECTED_SELECTED
        or selection.get("category_counts") != {"image": 1, "network": 3, "timeout": 11}
        or not isinstance(launch, dict)
        or launch.get("infra_retries") != 4
        or launch.get("max_concurrent") != 4
        or launch.get("minimum_valid") != MINIMUM_VALID
        or launch.get("setup_timeout_seconds") != 7200
        or launch.get("validate_timeout_seconds") != 21600
        or launch.get("session_timeout_seconds") != 43200
        or not isinstance(union, dict)
        or union.get("base_valid_after_completed_repairs") != 2494
        or union.get("minimum_retry_recoveries") != MINIMUM_CANDIDATE_RECOVERIES
        or union.get("projected_minimum_valid") != 2500
        or union.get("required_minimum_valid") != 2500
    ):
        fail("selection_receipt_invalid")
    if (
        not isinstance(task, dict)
        or task.get("path") != str(TASK_FILE)
        or task.get("mode") != "0600"
        or task.get("count") != EXPECTED_SELECTED
        or not isinstance(task.get("sha256"), str)
        or SHA_RE.fullmatch(task["sha256"]) is None
        or not isinstance(role, dict)
        or role.get("path") != str(ROLE_FILE)
        or role.get("mode") != "0600"
        or role.get("candidate_count") != EXPECTED_CANDIDATES
        or role.get("control_count") != EXPECTED_CONTROLS
        or not isinstance(role.get("sha256"), str)
        or SHA_RE.fullmatch(role["sha256"]) is None
    ):
        fail("selection_receipt_invalid")
    return task["sha256"], role["sha256"], envelope_sha


def validate_selection() -> tuple[str, str, str, str]:
    require_directory(SELECTION_ROOT, 0o700)
    try:
        children = {item.name for item in os.scandir(SELECTION_ROOT)}
    except OSError as error:
        raise LauncherError("selection_directory_invalid") from error
    if children != {TASK_FILE.name, ROLE_FILE.name, SELECTION_RECEIPT.name}:
        fail("selection_directory_invalid")
    receipt_raw = file_bytes(SELECTION_RECEIPT, mode=0o600, maximum=1 << 20)
    task_sha, role_sha, envelope_sha = validate_selection_receipt(
        strict_json(receipt_raw)
    )
    task_raw = file_bytes(
        TASK_FILE, expected_sha256=task_sha, mode=0o600, maximum=1 << 20
    )
    role_raw = file_bytes(
        ROLE_FILE, expected_sha256=role_sha, mode=0o600, maximum=1 << 20
    )
    try:
        task_text = task_raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LauncherError("selection_task_file_invalid") from error
    tasks = task_text.splitlines()
    roles = strict_json(role_raw)
    candidates = roles.get("candidates")
    controls = roles.get("controls")
    categories = roles.get("candidate_categories")
    primary = roles.get("candidate_primary_category")
    if (
        not task_raw.endswith(b"\n")
        or len(tasks) != EXPECTED_SELECTED
        or len(tasks) != len(set(tasks))
        or any(
            SLUG_RE.fullmatch(task) is None or task.strip() != task for task in tasks
        )
        or canonical_json(roles) + b"\n" != role_raw
        or set(roles)
        != {
            "schema_version",
            "kind",
            "candidates",
            "candidate_categories",
            "candidate_primary_category",
            "controls",
        }
        or roles.get("schema_version") != 1
        or roles.get("kind") != "terminal_bench_vmvm_infrastructure_retry_roles"
        or not isinstance(candidates, list)
        or not isinstance(controls, list)
        or not isinstance(categories, dict)
        or not isinstance(primary, dict)
        or len(candidates) != EXPECTED_CANDIDATES
        or len(controls) != EXPECTED_CONTROLS
        or len(candidates) != len(set(candidates))
        or len(controls) != len(set(controls))
        or set(candidates) & set(controls)
        or set(tasks) != set(candidates) | set(controls)
        or set(categories) != set(candidates)
        or set(primary) != set(candidates)
        or any(
            not isinstance(values, list)
            or not values
            or any(value not in {"timeout", "network", "image"} for value in values)
            or primary.get(slug) != values[0]
            for slug, values in categories.items()
        )
        or Counter(primary.values())
        != Counter({"timeout": 11, "network": 3, "image": 1})
    ):
        fail("selection_roles_invalid")
    return task_sha, role_sha, sha256_bytes(receipt_raw), envelope_sha


def validate_launch_dependencies(generator: Any) -> None:
    validate_artifact_root_inventory()
    try:
        v1 = generator.load_v1()
        generator.validate_execution_source(v1)
        generator.validate_source_wheel_cardinality(v1)
    except Exception as error:
        raise LauncherError("source_validation_failed") from error
    if (
        generator.SOURCE_ROOT != SOURCE_ROOT
        or generator.SOURCE_REVISION != SOURCE_REVISION
        or generator.SOURCE_TREE != SOURCE_TREE
        or generator.VERIFIERS_REVISION != VERIFIERS_REVISION
        or generator.RENDERERS_REVISION != RENDERERS_REVISION
        or generator.PYDANTIC_CONFIG_REVISION != PYDANTIC_CONFIG_REVISION
        or generator.VMVM_SHA256 != VMVM_SHA256
    ):
        fail("source_validation_failed")
    try:
        if (
            generator.PACKAGING_SNAPSHOT != PACKAGING_SNAPSHOT
            or generator.PACKAGING_SNAPSHOT_SHA256 != PACKAGING_SNAPSHOT_SHA256
            or generator.PACKAGING_VERSION != "26.3"
            or generator.PACKAGING_WHEEL_SHA256 != PACKAGING_WHEEL_SHA256
            or generator.PACKAGING_MEMBER_MANIFEST_SHA256
            != PACKAGING_MEMBER_MANIFEST_SHA256
            or generator.packaging_provenance() != expected_packaging_provenance()
        ):
            fail("packaging_dependency_invalid")
        generator.load_packaging_snapshot()
        file_bytes(
            PACKAGING_SNAPSHOT,
            expected_sha256=PACKAGING_SNAPSHOT_SHA256,
            mode=0o400,
            maximum=1 << 20,
        )
    except LauncherError:
        raise
    except Exception as error:
        raise LauncherError("packaging_dependency_invalid") from error
    git_environment = {
        **clean_environment(),
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }
    symbolic = bounded_run(
        ["/usr/bin/git", "-C", str(DATASET), "symbolic-ref", "-q", "HEAD"],
        timeout=30,
        env=git_environment,
    )
    if (
        git_output(DATASET, "rev-parse", "--verify", "HEAD").strip() != DATASET_REVISION
        or symbolic.returncode != 1
        or symbolic.stdout
        or symbolic.stderr
        or git_output(DATASET, "status", "--porcelain=v1", "--untracked-files=all")
        != ""
        or git_output(
            DATASET,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            ":(glob)**/_version.py",
        )
        != ""
    ):
        fail("dataset_identity_invalid")
    file_bytes(IMAGE_MANIFEST, expected_sha256=IMAGE_MANIFEST_SHA256)
    file_bytes(RUN_SBATCH, expected_sha256=RUN_SBATCH_SHA256)
    file_bytes(JOB_WRAPPER, expected_sha256=JOB_WRAPPER_SHA256, mode=0o500)
    file_bytes(V1_LAUNCHER, expected_sha256=V1_LAUNCHER_SHA256, mode=0o500)
    file_bytes(X86_UV, expected_sha256=X86_UV_SHA256)
    require_directory(X86_SITE, 0o755)
    validate_artifact_root_inventory()
    if not (X86_SITE / "pydantic").is_dir():
        fail("x86_runtime_invalid")


def _token_path(kind: str, token: str) -> Path:
    if re.fullmatch(r"[0-9a-f]{24}", token) is None:
        fail("launch_token_invalid")
    return RESERVATION / f"{kind}_{token}.json"


def authorization_bytes(
    *,
    launcher_sha: str,
    token: str,
    job_name: str,
    task_sha: str,
    role_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
    x2p_sha256: Mapping[str, str],
) -> tuple[Path, bytes, str]:
    if job_name != f"mirc-{token}":
        fail("job_authorization_identity_invalid")
    x2p_commitments = validate_x2p_environment_sha256(x2p_sha256)
    path = _token_path("job_authorization", token)
    body = {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_job_authorization",
        "state": "held_identity_authorized",
        "cluster": CLUSTER,
        "job_name": job_name,
        "launch_token": token,
        "reservation": str(RESERVATION),
        "authorization_path": str(path),
        "launcher_sha256": launcher_sha,
        "job_wrapper_sha256": JOB_WRAPPER_SHA256,
        "source_revision": SOURCE_REVISION,
        "source_tree": SOURCE_TREE,
        "verifiers_revision": VERIFIERS_REVISION,
        "vmvm_tb_v2_sha256": VMVM_SHA256,
        "x2p_environment_sha256": x2p_commitments,
        "module_import_closure": {
            "packaging": expected_packaging_provenance(),
        },
        "selection": {
            "receipt_file_sha256": receipt_file_sha,
            "receipt_sha256": receipt_sha,
            "task_file_sha256": task_sha,
            "role_file_sha256": role_sha,
            "selected": EXPECTED_SELECTED,
            "retry_candidates": EXPECTED_CANDIDATES,
            "controls": EXPECTED_CONTROLS,
        },
        "held_identity_required_consecutive": HELD_REQUIRED_CONSECUTIVE,
    }
    raw = envelope(body, "authorization_sha256")
    return path, raw, sha256_bytes(raw)


def activation_permit_bytes(
    *, token: str, job_name: str, authorization_sha: str
) -> tuple[Path, bytes, str]:
    if job_name != f"mirc-{token}" or SHA_RE.fullmatch(authorization_sha) is None:
        fail("activation_permit_identity_invalid")
    path = _token_path("activation_permit", token)
    body = {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_activation_permit",
        "state": "activate",
        "cluster": CLUSTER,
        "job_name": job_name,
        "launch_token": token,
        "reservation": str(RESERVATION),
        "authorization_sha256": authorization_sha,
        "submission_receipt": str(SUBMISSION_RECEIPT),
        "job_wrapper_sha256": JOB_WRAPPER_SHA256,
    }
    raw = envelope(body, "activation_permit_sha256")
    return path, raw, sha256_bytes(raw)


def slurm_environment(
    task_sha: str,
    role_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
    *,
    launcher_sha: str,
    token: str,
    job_name: str,
    authorization_path: Path,
    authorization_sha: str,
    activation_permit_path: Path,
    activation_permit_sha: str,
    tls_credentials: Mapping[str, StableCredential] | None = None,
    private_tls_values: Mapping[str, str] | None = None,
    private_x2p_values: Mapping[str, str] | None = None,
) -> dict[str, str]:
    if (tls_credentials is None) == (private_tls_values is None):
        fail("tls_credential_binding_invalid")
    tls_values = (
        private_tls_environment(tls_credentials)
        if tls_credentials is not None
        else validate_private_tls_environment(private_tls_values or {})
    )
    if private_x2p_values is None:
        fail("x2p_environment_invalid")
    x2p_values = private_x2p_environment(private_x2p_values)
    return {
        "ASYNCIO_TIMEOUT_MAX_ATTEMPTS": "1",
        "BROAD_HARNESS_ERROR_RETRY": "0",
        "DATASET_DIR": str(DATASET),
        "DATASET_REVISION": DATASET_REVISION,
        "ENABLE_COMPOSE": "0",
        "HOME": "/storage/home/tianhaowu",
        "IMAGE_MANIFEST": str(IMAGE_MANIFEST),
        "IMAGE_MANIFEST_SHA256": IMAGE_MANIFEST_SHA256,
        "IMAGE_PREFIX": IMAGE_PREFIX,
        "IMAGE_TAG": IMAGE_TAG,
        "INFRA_RETRIES": "4",
        "LANG": "C",
        "LC_ALL": "C",
        "LOGNAME": OWNER,
        "MAX_CONCURRENT": "4",
        "MINIMUM_PASS_RATE": "0",
        "MINIMUM_VALID": str(MINIMUM_VALID),
        "ORACLE_SOLUTION_NETWORK_MODE": "public",
        "OUTPUT_DIR": str(OUTPUT_ROOT),
        "PATH": "/usr/bin:/bin",
        "PROJECT_DIR": str(SOURCE_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_BIN_X86_64": "python3",
        "PYTHON_SITE_X86_64": str(X86_SITE),
        "RERUN_INVALID": "0",
        "RESOURCE_MULTIPLIER": "2",
        "RETRY_EXCEPTION_CLASS": "SandboxError",
        "RETRY_ACTIVATION_PERMIT_FILE": str(activation_permit_path),
        "RETRY_ACTIVATION_PERMIT_SHA256": activation_permit_sha,
        "RETRY_AUTHORIZATION_FILE": str(authorization_path),
        "RETRY_AUTHORIZATION_SHA256": authorization_sha,
        "RETRY_EXPECTED_JOB_NAME": job_name,
        "RETRY_GENERATOR_SHA256": GENERATOR_SHA256,
        "RETRY_JOB_WRAPPER_SHA256": JOB_WRAPPER_SHA256,
        "RETRY_LAUNCHER_SHA256": launcher_sha,
        "RETRY_LAUNCH_TOKEN": token,
        "RETRY_RESERVATION": str(RESERVATION),
        "RETRY_SOURCE_REVISION": SOURCE_REVISION,
        "RETRY_SOURCE_TREE": SOURCE_TREE,
        "RETRY_VERIFIERS_REVISION": VERIFIERS_REVISION,
        "RETRY_VMVM_SHA256": VMVM_SHA256,
        "RETRY_SUBMISSION_RECEIPT": str(SUBMISSION_RECEIPT),
        "RETRY_WRAPPER_GATE_TIMEOUT_SECONDS": str(WRAPPER_GATE_TIMEOUT_SECONDS),
        "SELECTION_RECEIPT_FILE_SHA256": receipt_file_sha,
        "SELECTION_RECEIPT_SHA256": receipt_sha,
        "SELECTION_ROLE_FILE": str(ROLE_FILE),
        "SELECTION_ROLE_FILE_SHA256": role_sha,
        "SESSION_TIMEOUT": "43200",
        "SETUP_TIMEOUT": "7200",
        "SLURM_EXPORT_ENV": "NONE",
        "TASK_FILE": str(TASK_FILE),
        "TASK_FILE_SHA256": task_sha,
        "TIMEOUT_MULTIPLIER": "4",
        "TZ": "UTC",
        "USER": OWNER,
        "USE_DECLARED_IMAGES": "0",
        "UV_BIN_X86_64": str(X86_UV),
        "VACLI_CONTAINER_PRIVILEGED": "1",
        "VACLI_IMAGE_PULL_TIMEOUT_SECONDS": "7200",
        "VACLI_LEASE_RETRIES": "20",
        "VACLI_MAX_CONCURRENT_LEASES": "2",
        "VACLI_MAX_PULL_RETRIES": "20",
        "VALIDATE_TIMEOUT": "21600",
        **tls_values,
        **x2p_values,
    }


def acquire_reservation(
    launcher_sha: str,
    task_sha: str,
    role_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
    token: str,
    authorization_path: Path,
    authorization_sha: str,
    activation_permit_path: Path,
    activation_permit_sha: str,
    x2p_sha256: Mapping[str, str],
    environment_raw: bytes,
    submission_started_at: str,
) -> tuple[str, str]:
    x2p_commitments = validate_x2p_environment_sha256(x2p_sha256)
    for path in (OUTPUT_ROOT, RESERVATION, LOG_ROOT):
        if path.exists() or path.is_symlink():
            fail("launch_namespace_not_fresh")
    try:
        RESERVATION.mkdir(mode=0o700)
        sync_directory(RESERVATION.parent)
        LOG_ROOT.mkdir(mode=0o700)
        sync_directory(LOG_ROOT.parent)
    except OSError as error:
        raise LauncherError("launch_reservation_failed") from error
    require_directory(RESERVATION, 0o700)
    require_directory(LOG_ROOT, 0o700)
    environment_sha = write_once(ENVIRONMENT_FILE, environment_raw, 0o400)
    intent_body = {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_launch_intent",
        "state": "submitting",
        "launcher_sha256": launcher_sha,
        "generator_sha256": GENERATOR_SHA256,
        "job_wrapper_sha256": JOB_WRAPPER_SHA256,
        "source_revision": SOURCE_REVISION,
        "source_tree": SOURCE_TREE,
        "verifiers_revision": VERIFIERS_REVISION,
        "vmvm_tb_v2_sha256": VMVM_SHA256,
        "x2p_environment_sha256": x2p_commitments,
        "selection": {
            "receipt_file_sha256": receipt_file_sha,
            "receipt_sha256": receipt_sha,
            "task_file_sha256": task_sha,
            "role_file_sha256": role_sha,
            "selected": EXPECTED_SELECTED,
            "retry_candidates": EXPECTED_CANDIDATES,
            "controls": EXPECTED_CONTROLS,
        },
        "attempt_policy": ATTEMPT_POLICY,
        "module_import_closure": {
            "packaging": expected_packaging_provenance(),
        },
        "launch": {
            "cluster": CLUSTER,
            "job_name": f"mirc-{token}",
            "launch_token": token,
            "submission_started_at": submission_started_at,
            "output_dir": str(OUTPUT_ROOT),
            "environment_sha256": environment_sha,
            "max_concurrent": 4,
            "max_concurrent_leases": 2,
            "minimum_valid": MINIMUM_VALID,
            "slurm_time_limit": "7-00:00:00",
            "submit_held": True,
            "held_identity_required_consecutive": HELD_REQUIRED_CONSECUTIVE,
            "authorization": {
                "path": str(authorization_path),
                "sha256": authorization_sha,
            },
            "activation_permit": {
                "path": str(activation_permit_path),
                "sha256": activation_permit_sha,
            },
        },
    }
    intent_raw = envelope(intent_body, "intent_sha256")
    intent_file_sha = write_once(INTENT, intent_raw, 0o400)
    sync_directory(RESERVATION)
    return intent_file_sha, environment_sha


def sbatch_command(job_name: str) -> list[str]:
    log_path = LOG_ROOT / "oracle_%j.log"
    return [
        "/usr/bin/sbatch",
        "-M",
        CLUSTER,
        "--parsable",
        "--hold",
        f"--job-name={job_name}",
        f"--chdir={SOURCE_ROOT}",
        "--time=7-00:00:00",
        f"--output={log_path}",
        f"--error={log_path}",
        "--open-mode=truncate",
        f"--export-file={ENVIRONMENT_FILE}",
        str(JOB_WRAPPER),
    ]


def _identity_field_observation(
    record: Mapping[str, str], job_id: str, job_name: str
) -> tuple[set[str], set[str]]:
    missing: set[str] = set()
    conflicts: set[str] = set()
    expected = {
        "JobId": job_id,
        "JobName": job_name,
        "UserId": EXPECTED_USER_ID,
    }
    for field, expected_value in expected.items():
        value = record.get(field)
        if not isinstance(value, str) or not value:
            missing.add(f"missing_{field}")
        elif value != expected_value:
            conflicts.add(field)
    return missing, conflicts


def identity_mismatches(
    record: Mapping[str, str],
    job_id: str,
    job_name: str,
    *,
    expected_num_nodes: str = "1",
) -> tuple[set[str], set[str]]:
    log_path = str(LOG_ROOT / f"oracle_{job_id}.log")
    expected = {
        "Command": str(JOB_WRAPPER),
        "WorkDir": str(SOURCE_ROOT),
        "StdOut": log_path,
        "StdErr": log_path,
        "Account": "ram",
        "Partition": "cpu_x86",
        "QOS": "cpu_x86_lowest",
        "TimeLimit": "7-00:00:00",
        "NumCPUs": "8",
        "NumNodes": expected_num_nodes,
        "MinMemoryNode": "16G",
        "Dependency": "(null)",
        "Requeue": "0",
        "Restarts": "0",
    }
    mismatches = {key for key, value in expected.items() if record.get(key) != value}
    missing, conflicts = _identity_field_observation(record, job_id, job_name)
    mismatches.update(missing)
    mismatches.update(conflicts)
    return mismatches, conflicts


SCONTROL_ALLOCATION_CATEGORY_VALUES = {
    "NumNodes": {"expected_one", "missing", "other", "zero"},
    "NodeList": {"assigned_or_other", "empty", "missing", "null_token"},
    "BatchHost": {"assigned_or_other", "empty", "missing", "null_token"},
}
HELD_ACCOUNTING_STATUSES = {"absent", "exact", "shape", "unavailable"}


def _scontrol_allocation_categories(
    record: Mapping[str, str] | None,
) -> dict[str, str]:
    """Classify allocation fields without retaining scheduler-provided values."""

    if record is None:
        return {field: "missing" for field in SCONTROL_ALLOCATION_CATEGORY_VALUES}

    def node_count(value: str | None) -> str:
        if value is None or value == "":
            return "missing"
        if value == "1":
            return "expected_one"
        if value == "0":
            return "zero"
        return "other"

    def allocation_name(value: str | None) -> str:
        if value is None:
            return "missing"
        if value == "":
            return "empty"
        if value == "(null)":
            return "null_token"
        return "assigned_or_other"

    return {
        "BatchHost": allocation_name(record.get("BatchHost")),
        "NodeList": allocation_name(record.get("NodeList")),
        "NumNodes": node_count(record.get("NumNodes")),
    }


def _new_scontrol_category_counts() -> dict[str, Counter[str]]:
    return {
        field: Counter({category: 0 for category in sorted(allowed)})
        for field, allowed in sorted(SCONTROL_ALLOCATION_CATEGORY_VALUES.items())
    }


def _record_scontrol_categories(
    counts: Mapping[str, Counter[str]], categories: Mapping[str, str]
) -> None:
    for field, allowed in SCONTROL_ALLOCATION_CATEGORY_VALUES.items():
        category = categories.get(field)
        if category not in allowed:
            raise RuntimeError("scontrol_allocation_category_invalid")
        counts[field][category] += 1


def _serialized_category_counts(
    counts: Mapping[str, Counter[str]],
) -> dict[str, dict[str, int]]:
    return {
        field: dict(sorted(counter.items()))
        for field, counter in sorted(counts.items())
    }


def _record_mismatch_occurrences(
    counts: Counter[str], fields: Sequence[str]
) -> None:
    counts.update(fields)


def _scheduler_record(
    job_id: str, *, deadline: float | None = None
) -> tuple[dict[str, str] | None, set[str]]:
    try:
        result = bounded_run(
            ["/usr/bin/scontrol", "-M", CLUSTER, "show", "job", "-o", job_id],
            timeout=_query_timeout(deadline),
        )
    except LauncherError:
        return None, {"scontrol_unavailable"}
    if result.returncode != 0 or result.stderr:
        return None, {"scontrol_unavailable"}
    try:
        return parse_scontrol_record(result.stdout.strip()), set()
    except LauncherError:
        return None, {"scontrol_record"}


def _pipe_rows(
    command: Sequence[str],
    width: int,
    code: str,
    *,
    deadline: float | None = None,
) -> list[list[str]]:
    try:
        result = bounded_run(command, timeout=_query_timeout(deadline))
    except LauncherError as error:
        raise LauncherError(code) from error
    if result.returncode != 0 or result.stderr:
        fail(code)
    rows = [line.split("|") for line in result.stdout.splitlines() if line.strip()]
    if any(len(row) != width for row in rows):
        fail(code)
    return rows


def held_snapshot(
    job_id: str, job_name: str, *, deadline: float | None = None
) -> tuple[bool, tuple[str, ...], tuple[str, ...], dict[str, Any]]:
    record, problems = _scheduler_record(job_id, deadline=deadline)
    mismatches = set(problems)
    conflicts: set[str] = set()
    allocation_categories = _scontrol_allocation_categories(record)
    if record is not None:
        identity_problems, identity_conflicts = identity_mismatches(
            record, job_id, job_name, expected_num_nodes="1-1"
        )
        mismatches.update(identity_problems)
        conflicts.update(identity_conflicts)
        held_expected = {
            "JobState": "PENDING",
            "Reason": "JobHeldUser",
            "Priority": "0",
            "StartTime": "Unknown",
        }
        mismatches.update(
            f"held_{key}"
            for key, value in held_expected.items()
            if record.get(key) != value
        )
        # A held one-node request is represented by this cluster as the exact
        # requested range ``1-1`` with NodeList either omitted or empty.  This
        # exception is held-only; activation below still requires an allocated
        # one-node record.
        if "NodeList" in record and record["NodeList"] != "":
            mismatches.add("held_NodeList")
        if record.get("BatchHost") not in {None, "(null)"}:
            mismatches.add("held_BatchHost")
    try:
        queue_rows = _pipe_rows(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--noheader",
                "--jobs",
                job_id,
                "--format=%A|%j|%T|%r",
            ],
            4,
            "held_squeue_unavailable",
            deadline=deadline,
        )
    except LauncherError:
        mismatches.add("held_squeue")
    else:
        for row in queue_rows:
            if not row[0]:
                mismatches.add("missing_JobId")
            elif row[0] != job_id:
                conflicts.add("JobId")
            if not row[1]:
                mismatches.add("missing_JobName")
            elif row[1] != job_name:
                conflicts.add("JobName")
        if queue_rows != [[job_id, job_name, "PENDING", "JobHeldUser"]]:
            mismatches.add("held_squeue")
    accounting_status = "unavailable"
    try:
        accounting = _pipe_rows(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,State,Start,NodeList",
            ],
            5,
            "held_accounting_unavailable",
            deadline=deadline,
        )
    except LauncherError:
        mismatches.add("held_accounting")
    else:
        for row in accounting:
            if not row[0]:
                mismatches.add("missing_JobId")
            elif row[0] != job_id:
                conflicts.add("JobId")
            if not row[1]:
                mismatches.add("missing_JobName")
            elif row[1] != job_name:
                conflicts.add("JobName")
        accounting_has_shape_mismatch = (
            len(accounting) != 1
            or accounting[0][0] != job_id
            or accounting[0][1] != job_name
            or _scheduler_state(accounting[0][2]) != "PENDING"
            or accounting[0][3] not in {"Unknown", "N/A", ""}
            or accounting[0][4] not in {"None assigned", "(null)", "", "N/A"}
        )
        if not accounting:
            accounting_status = "absent"
            mismatches.add("held_accounting")
        elif accounting_has_shape_mismatch:
            accounting_status = "shape"
            mismatches.add("held_accounting")
        else:
            accounting_status = "exact"
    try:
        all_rows = _pipe_rows(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "-j",
                job_id,
                "--format=JobIDRaw,State",
            ],
            2,
            "held_steps_unavailable",
            deadline=deadline,
        )
    except LauncherError:
        mismatches.add("held_steps")
    else:
        for row in all_rows:
            if not row[0]:
                mismatches.add("missing_JobId")
            elif row[0] != job_id and not row[0].startswith(f"{job_id}."):
                conflicts.add("JobId")
        if (
            len(all_rows) != 1
            or all_rows[0][0] != job_id
            or _scheduler_state(all_rows[0][1]) != "PENDING"
        ):
            mismatches.add("held_steps")
    mismatches.update(conflicts)
    return (
        not mismatches,
        tuple(sorted(mismatches)),
        tuple(sorted(conflicts)),
        {
            "held_accounting_status": accounting_status,
            "scontrol_allocation_categories": allocation_categories,
        },
    )


def poll_held_convergence(job_id: str, job_name: str) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + HELD_CONVERGENCE_TIMEOUT_SECONDS
    consecutive = 0
    observed: set[str] = set()
    occurrences: Counter[str] = Counter()
    conflicts_seen: set[str] = set()
    accounting_counts = Counter(
        {status: 0 for status in sorted(HELD_ACCOUNTING_STATUSES)}
    )
    allocation_counts = _new_scontrol_category_counts()
    final_mismatches: tuple[str, ...] = ()
    final_accounting_status = "unavailable"
    final_allocation_categories = _scontrol_allocation_categories(None)
    polls = 0

    def telemetry(converged: bool, identity_status: str) -> dict[str, Any]:
        return {
            "telemetry_schema": "deadline_poll_v1",
            "deadline_seconds": HELD_CONVERGENCE_TIMEOUT_SECONDS,
            "max_iterations": HELD_POLL_MAX_ITERATIONS,
            "converged": converged,
            "identity_status": identity_status,
            "explicit_conflict_fields": sorted(conflicts_seen),
            "polls": polls,
            "required_consecutive": HELD_REQUIRED_CONSECUTIVE,
            "consecutive_exact": consecutive if not conflicts_seen else 0,
            "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
            "observed_mismatch_fields": sorted(observed),
            "mismatch_field_count": len(observed),
            "mismatch_field_occurrences": dict(sorted(occurrences.items())),
            "final_mismatch_fields": list(final_mismatches),
            "held_accounting_status_counts": dict(sorted(accounting_counts.items())),
            "final_held_accounting_status": final_accounting_status,
            "scontrol_allocation_category_counts": _serialized_category_counts(
                allocation_counts
            ),
            "final_scontrol_allocation_categories": dict(
                sorted(final_allocation_categories.items())
            ),
        }

    while polls < HELD_POLL_MAX_ITERATIONS and time.monotonic() < deadline:
        exact, mismatches, conflicts, details = held_snapshot(
            job_id, job_name, deadline=deadline
        )
        polls += 1
        final_mismatches = mismatches
        final_accounting_status = details["held_accounting_status"]
        final_allocation_categories = details["scontrol_allocation_categories"]
        observed.update(mismatches)
        _record_mismatch_occurrences(occurrences, mismatches)
        accounting_counts[final_accounting_status] += 1
        _record_scontrol_categories(allocation_counts, final_allocation_categories)
        conflicts_seen.update(conflicts)
        if conflicts_seen:
            return telemetry(False, "explicit_identity_conflict")
        consecutive = consecutive + 1 if exact else 0
        if consecutive >= HELD_REQUIRED_CONSECUTIVE:
            return telemetry(True, "converged")
        if not _bounded_poll_sleep(deadline, HELD_POLL_INTERVAL_SECONDS):
            break
    return telemetry(False, "unavailable_or_incomplete")


def _scheduler_state(value: str | None) -> str:
    if not isinstance(value, str) or not value:
        return "UNKNOWN"
    return value.split()[0].rstrip("+")


def post_release_snapshot(
    job_id: str, job_name: str, *, deadline: float | None = None
) -> tuple[bool, str, tuple[str, ...], tuple[str, ...], dict[str, Any]]:
    record, problems = _scheduler_record(job_id, deadline=deadline)
    mismatches = set(problems)
    conflicts: set[str] = set()
    allocation_categories = _scontrol_allocation_categories(record)
    state = "UNKNOWN"
    if record is not None:
        identity_problems, identity_conflicts = identity_mismatches(
            record, job_id, job_name
        )
        mismatches.update(identity_problems)
        conflicts.update(identity_conflicts)
        state = _scheduler_state(record.get("JobState"))
        node_list = record.get("NodeList")
        if (
            not isinstance(node_list, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._,\[\]-]*", node_list) is None
            or node_list in {"N/A", "None", "Unknown"}
        ):
            mismatches.add("activation_NodeList")
        if state not in ACTIVE_STATES | TERMINAL_STATES:
            mismatches.add("activation_JobState")
        if state == "PENDING" and (
            record.get("Reason") == "JobHeldUser" or record.get("Priority") == "0"
        ):
            mismatches.add("activation_hold")
    try:
        queue_rows = _pipe_rows(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--noheader",
                "--jobs",
                job_id,
                "--format=%A|%j|%T|%r",
            ],
            4,
            "activation_squeue_unavailable",
            deadline=deadline,
        )
    except LauncherError:
        mismatches.add("activation_squeue")
    else:
        for row in queue_rows:
            if not row[0]:
                mismatches.add("missing_JobId")
            elif row[0] != job_id:
                conflicts.add("JobId")
            if not row[1]:
                mismatches.add("missing_JobName")
            elif row[1] != job_name:
                conflicts.add("JobName")
        if state in ACTIVE_STATES:
            if (
                len(queue_rows) != 1
                or queue_rows[0][:3] != [job_id, job_name, state]
                or (state == "PENDING" and queue_rows[0][3] == "JobHeldUser")
            ):
                mismatches.add("activation_squeue")
        elif state in TERMINAL_STATES and queue_rows:
            mismatches.add("activation_squeue")
    try:
        accounting = _pipe_rows(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,State",
            ],
            3,
            "activation_accounting_unavailable",
            deadline=deadline,
        )
    except LauncherError:
        mismatches.add("activation_accounting")
    else:
        for row in accounting:
            if not row[0]:
                mismatches.add("missing_JobId")
            elif row[0] != job_id:
                conflicts.add("JobId")
            if not row[1]:
                mismatches.add("missing_JobName")
            elif row[1] != job_name:
                conflicts.add("JobName")
        if (
            len(accounting) != 1
            or accounting[0][:2] != [job_id, job_name]
            or _scheduler_state(accounting[0][2]) != state
        ):
            mismatches.add("activation_accounting")
    mismatches.update(conflicts)
    return (
        not mismatches,
        state,
        tuple(sorted(mismatches)),
        tuple(sorted(conflicts)),
        {"scontrol_allocation_categories": allocation_categories},
    )


def poll_activation(job_id: str, job_name: str) -> tuple[dict[str, Any], str]:
    started = time.monotonic()
    deadline = started + ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS
    observed: set[str] = set()
    occurrences: Counter[str] = Counter()
    conflicts_seen: set[str] = set()
    allocation_counts = _new_scontrol_category_counts()
    consecutive = 0
    last_state = "UNKNOWN"
    final_mismatches: tuple[str, ...] = ()
    final_allocation_categories = _scontrol_allocation_categories(None)
    polls = 0

    def telemetry(converged: bool, identity_status: str) -> dict[str, Any]:
        return {
            "telemetry_schema": "deadline_poll_v1",
            "deadline_seconds": ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS,
            "max_iterations": ACTIVATION_POLL_MAX_ITERATIONS,
            "converged": converged,
            "identity_status": identity_status,
            "explicit_conflict_fields": sorted(conflicts_seen),
            "polls": polls,
            "consecutive_exact": consecutive if not conflicts_seen else 0,
            "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
            "observed_mismatch_fields": sorted(observed),
            "mismatch_field_count": len(observed),
            "mismatch_field_occurrences": dict(sorted(occurrences.items())),
            "final_mismatch_fields": list(final_mismatches),
            "scontrol_allocation_category_counts": _serialized_category_counts(
                allocation_counts
            ),
            "final_scontrol_allocation_categories": dict(
                sorted(final_allocation_categories.items())
            ),
            "state_class": (
                "terminal" if last_state in TERMINAL_STATES else "active"
                if last_state in ACTIVE_STATES
                else "unknown"
            ),
        }

    while polls < ACTIVATION_POLL_MAX_ITERATIONS and time.monotonic() < deadline:
        exact, state, mismatches, conflicts, details = post_release_snapshot(
            job_id, job_name, deadline=deadline
        )
        polls += 1
        last_state = state
        final_mismatches = mismatches
        final_allocation_categories = details["scontrol_allocation_categories"]
        observed.update(mismatches)
        _record_mismatch_occurrences(occurrences, mismatches)
        _record_scontrol_categories(allocation_counts, final_allocation_categories)
        conflicts_seen.update(conflicts)
        if conflicts_seen:
            value = telemetry(False, "explicit_identity_conflict")
            value["state_class"] = "unknown"
            return value, state
        consecutive = consecutive + 1 if exact else 0
        if consecutive >= 2:
            return telemetry(True, "converged"), state
        if not _bounded_poll_sleep(deadline, ACTIVATION_POLL_INTERVAL_SECONDS):
            break
    return telemetry(False, "unavailable_or_incomplete"), last_state


def invoke_control_once(arguments: Sequence[str]) -> str:
    try:
        result = bounded_run(arguments, timeout=V1.QUERY_TIMEOUT_SECONDS)
    except LauncherError:
        return "unknown"
    return "completed" if result.returncode == 0 else "nonzero"


def prove_candidate_identity(
    job_id: str, job_name: str, candidate_provenance: str
) -> dict[str, Any]:
    if candidate_provenance not in {"sbatch_stdout", "sbatch_and_name", "name_lookup"}:
        raise LifecycleFailure(
            "cancellation_unconfirmed",
            cancellation={
                "identity_status": "invalid_provenance",
                "identity_converged": False,
                "identity_poll_attempts": 0,
                "candidate_provenance": "invalid",
                "observed_mismatch_fields": ["candidate_provenance"],
                "mismatch_field_occurrences": {"candidate_provenance": 1},
                "final_mismatch_fields": ["candidate_provenance"],
                "explicit_conflict_fields": [],
                "telemetry_schema": "deadline_poll_v1",
                "identity_deadline_seconds": CANCEL_IDENTITY_CONVERGENCE_TIMEOUT_SECONDS,
                "identity_max_iterations": CANCEL_IDENTITY_POLL_MAX_ITERATIONS,
                "identity_elapsed_milliseconds": 0,
            },
        )
    started = time.monotonic()
    deadline = started + CANCEL_IDENTITY_CONVERGENCE_TIMEOUT_SECONDS
    observed: set[str] = set()
    occurrences: Counter[str] = Counter()
    final_mismatches: tuple[str, ...] = ()
    polls = 0

    def telemetry(status: str, converged: bool, conflicts: Sequence[str]) -> dict[str, Any]:
        return {
            "telemetry_schema": "deadline_poll_v1",
            "identity_deadline_seconds": CANCEL_IDENTITY_CONVERGENCE_TIMEOUT_SECONDS,
            "identity_max_iterations": CANCEL_IDENTITY_POLL_MAX_ITERATIONS,
            "identity_status": status,
            "identity_converged": converged,
            "identity_poll_attempts": polls,
            "candidate_provenance": candidate_provenance,
            "observed_mismatch_fields": sorted(observed),
            "mismatch_field_occurrences": dict(sorted(occurrences.items())),
            "final_mismatch_fields": list(final_mismatches),
            "explicit_conflict_fields": sorted(conflicts),
            "identity_elapsed_milliseconds": int(
                (time.monotonic() - started) * 1000
            ),
        }

    while polls < CANCEL_IDENTITY_POLL_MAX_ITERATIONS and time.monotonic() < deadline:
        record, problems = _scheduler_record(job_id, deadline=deadline)
        polls += 1
        mismatches = set(problems)
        conflicts: set[str] = set()
        if record is not None:
            missing, conflicts = _identity_field_observation(
                record, job_id, job_name
            )
            mismatches.update(missing)
        mismatches.update(conflicts)
        final_mismatches = tuple(sorted(mismatches))
        observed.update(mismatches)
        _record_mismatch_occurrences(occurrences, final_mismatches)
        if conflicts:
            return telemetry("explicit_identity_conflict", False, conflicts)
        if not mismatches:
            return telemetry("converged", True, ())
        if not _bounded_poll_sleep(deadline, CANCEL_IDENTITY_POLL_INTERVAL_SECONDS):
            break
    return telemetry("unavailable_or_incomplete", False, ())


def terminal_snapshot(
    job_id: str, job_name: str, *, deadline: float | None = None
) -> dict[str, Any]:
    """Classify one pre-control or terminal-proof scheduler observation.

    Empty or missing identity fields are incomplete.  A nonempty JobId, JobName,
    or UserId that differs from the exact expected value is an explicit conflict.
    Callers must treat a conflict as monotonic and issue no later control command.
    """

    mismatches: set[str] = set()
    conflicts: set[str] = set()
    identity_incomplete = False
    record, record_problems = _scheduler_record(job_id, deadline=deadline)
    mismatches.update(record_problems)
    if record is None:
        identity_incomplete = True
    else:
        missing, record_conflicts = _identity_field_observation(
            record, job_id, job_name
        )
        mismatches.update(missing)
        mismatches.update(record_conflicts)
        conflicts.update(record_conflicts)
        identity_incomplete = bool(missing)
    if conflicts:
        return {
            "snapshot_status": "explicit_identity_conflict",
            "state": "UNKNOWN",
            "mismatch_fields": tuple(sorted(mismatches)),
            "explicit_conflict_fields": tuple(sorted(conflicts)),
            "step_signature": (),
        }
    try:
        queue_rows = _pipe_rows(
            [
                "/usr/bin/squeue",
                "-M",
                CLUSTER,
                "--noheader",
                "--jobs",
                job_id,
                "--format=%A|%j",
            ],
            2,
            "cancellation_squeue_unavailable",
            deadline=deadline,
        )
    except LauncherError:
        mismatches.add("cancellation_squeue")
        identity_incomplete = True
    else:
        for row in queue_rows:
            if not row[0]:
                mismatches.add("missing_JobId")
                identity_incomplete = True
            elif row[0] != job_id:
                conflicts.add("JobId")
            if not row[1]:
                mismatches.add("missing_JobName")
                identity_incomplete = True
            elif row[1] != job_name:
                conflicts.add("JobName")
        if queue_rows:
            mismatches.add("cancellation_squeue")
    try:
        allocation = _pipe_rows(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "--allocations",
                "-j",
                job_id,
                "--format=JobIDRaw,JobName,State",
            ],
            3,
            "cancellation_accounting_unavailable",
            deadline=deadline,
        )
    except LauncherError:
        mismatches.add("cancellation_accounting")
        identity_incomplete = True
        allocation = []
    else:
        for row in allocation:
            if not row[0]:
                mismatches.add("missing_JobId")
                identity_incomplete = True
            elif row[0] != job_id:
                conflicts.add("JobId")
            if not row[1]:
                mismatches.add("missing_JobName")
                identity_incomplete = True
            elif row[1] != job_name:
                conflicts.add("JobName")
    try:
        all_rows = _pipe_rows(
            [
                "/usr/bin/sacct",
                "-M",
                CLUSTER,
                "--noheader",
                "--parsable2",
                "-j",
                job_id,
                "--format=JobIDRaw,State",
            ],
            2,
            "cancellation_steps_unavailable",
            deadline=deadline,
        )
    except LauncherError:
        mismatches.add("cancellation_steps")
        identity_incomplete = True
        all_rows = []
    else:
        for row in all_rows:
            if not row[0]:
                mismatches.add("missing_JobId")
                identity_incomplete = True
            elif row[0] != job_id and not row[0].startswith(f"{job_id}."):
                conflicts.add("JobId")
    if conflicts:
        mismatches.update(conflicts)
        return {
            "snapshot_status": "explicit_identity_conflict",
            "state": "UNKNOWN",
            "mismatch_fields": tuple(sorted(mismatches)),
            "explicit_conflict_fields": tuple(sorted(conflicts)),
            "step_signature": (),
        }
    state = "UNKNOWN"
    if len(allocation) != 1 or allocation[0][:2] != [job_id, job_name]:
        mismatches.add("cancellation_allocation")
        identity_incomplete = True
    else:
        state = _scheduler_state(allocation[0][2])
        if state not in TERMINAL_STATES:
            mismatches.add("cancellation_allocation_state")
    if (
        not all_rows
        or any(
            row[0] != job_id and not row[0].startswith(f"{job_id}.") for row in all_rows
        )
        or any(_scheduler_state(row[1]) not in TERMINAL_STATES for row in all_rows)
    ):
        mismatches.add("cancellation_steps")
        if not all_rows:
            identity_incomplete = True
    signature = tuple((row[0], _scheduler_state(row[1])) for row in all_rows)
    if identity_incomplete:
        snapshot_status = "unavailable_or_incomplete"
    elif not mismatches:
        snapshot_status = "terminal"
    else:
        snapshot_status = "active"
    return {
        "snapshot_status": snapshot_status,
        "state": state,
        "mismatch_fields": tuple(sorted(mismatches)),
        "explicit_conflict_fields": (),
        "step_signature": signature,
    }


def cancel_and_prove(
    job_id: str,
    job_name: str,
    start_date: str,
    *,
    candidate_provenance: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", start_date):
        fail("cancellation_unconfirmed")
    identity_proof = prove_candidate_identity(job_id, job_name, candidate_provenance)
    trusted_sbatch_candidate = candidate_provenance in {
        "sbatch_stdout",
        "sbatch_and_name",
    }
    if identity_proof["identity_status"] == "explicit_identity_conflict":
        raise LifecycleFailure(
            "cancellation_unconfirmed",
            cancellation={
                **identity_proof,
                "cancel_attempts": 0,
                "cancel_command_outcome": "not_authorized",
            },
        )
    if identity_proof["identity_converged"] is not True and not trusted_sbatch_candidate:
        raise LifecycleFailure(
            "cancellation_unconfirmed",
            cancellation={
                **identity_proof,
                "cancel_attempts": 0,
                "cancel_command_outcome": "not_authorized",
            },
        )
    pre_control_deadline = time.monotonic() + CANCEL_PRECONTROL_TIMEOUT_SECONDS
    pre_control = terminal_snapshot(job_id, job_name, deadline=pre_control_deadline)
    pre_control_status = pre_control["snapshot_status"]
    if pre_control_status == "explicit_identity_conflict":
        conflict_fields = sorted(
            set(identity_proof["explicit_conflict_fields"])
            | set(pre_control["explicit_conflict_fields"])
        )
        raise LifecycleFailure(
            "cancellation_unconfirmed",
            cancellation={
                **identity_proof,
                "identity_status": "explicit_identity_conflict",
                "identity_converged": False,
                "explicit_conflict_fields": conflict_fields,
                "pre_control_snapshot_status": pre_control_status,
                "pre_control_mismatch_fields": list(pre_control["mismatch_fields"]),
                "cancel_attempts": 0,
                "cancel_command_outcome": "not_authorized",
            },
        )
    if (
        pre_control_status == "unavailable_or_incomplete"
        and not trusted_sbatch_candidate
    ):
        raise LifecycleFailure(
            "cancellation_unconfirmed",
            cancellation={
                **identity_proof,
                "pre_control_snapshot_status": pre_control_status,
                "pre_control_mismatch_fields": list(pre_control["mismatch_fields"]),
                "cancel_attempts": 0,
                "cancel_command_outcome": "not_authorized",
            },
        )
    state = pre_control["state"]
    cancel_outcome = "not_needed"
    if pre_control_status != "terminal":
        cancel_outcome = invoke_control_once(
            ["/usr/bin/scancel", "-M", CLUSTER, job_id]
        )
    started = time.monotonic()
    deadline = started + CANCEL_TERMINAL_CONVERGENCE_TIMEOUT_SECONDS
    consecutive = 0
    previous_signature: tuple[str, tuple[tuple[str, str], ...]] | None = None
    observed: set[str] = set()
    occurrences: Counter[str] = Counter()
    final_mismatches: tuple[str, ...] = ()
    polls = 0
    while (
        polls < CANCEL_TERMINAL_POLL_MAX_ITERATIONS
        and time.monotonic() < deadline
    ):
        snapshot = terminal_snapshot(job_id, job_name, deadline=deadline)
        polls += 1
        snapshot_status = snapshot["snapshot_status"]
        state = snapshot["state"]
        mismatches = snapshot["mismatch_fields"]
        final_mismatches = mismatches
        step_signature = snapshot["step_signature"]
        observed.update(mismatches)
        _record_mismatch_occurrences(occurrences, mismatches)
        if snapshot_status == "explicit_identity_conflict":
            raise LifecycleFailure(
                "cancellation_unconfirmed",
                cancellation={
                    **identity_proof,
                    "identity_status": "explicit_identity_conflict",
                    "identity_converged": False,
                    "explicit_conflict_fields": sorted(
                        set(identity_proof["explicit_conflict_fields"])
                        | set(snapshot["explicit_conflict_fields"])
                    ),
                    "pre_control_snapshot_status": pre_control_status,
                    "pre_control_mismatch_fields": list(
                        pre_control["mismatch_fields"]
                    ),
                    "cancel_attempts": 0 if cancel_outcome == "not_needed" else 1,
                    "cancel_command_outcome": cancel_outcome,
                    "terminal_state": state,
                    "terminal_telemetry_schema": "deadline_poll_v1",
                    "terminal_deadline_seconds": CANCEL_TERMINAL_CONVERGENCE_TIMEOUT_SECONDS,
                    "terminal_max_iterations": CANCEL_TERMINAL_POLL_MAX_ITERATIONS,
                    "proof_polls": polls,
                    "consecutive_exact": 0,
                    "elapsed_milliseconds": int(
                        (time.monotonic() - started) * 1000
                    ),
                    "observed_terminal_mismatch_fields": sorted(observed),
                    "terminal_mismatch_field_occurrences": dict(
                        sorted(occurrences.items())
                    ),
                    "final_terminal_mismatch_fields": list(final_mismatches),
                },
            )
        signature = (state, step_signature)
        consecutive = (
            consecutive + 1
            if snapshot_status == "terminal" and signature == previous_signature
            else int(snapshot_status == "terminal")
        )
        previous_signature = signature if snapshot_status == "terminal" else None
        if consecutive >= 2:
            return {
                **identity_proof,
                "pre_control_snapshot_status": pre_control_status,
                "pre_control_mismatch_fields": list(pre_control["mismatch_fields"]),
                "cancel_attempts": 0 if cancel_outcome == "not_needed" else 1,
                "cancel_command_outcome": cancel_outcome,
                "terminal_state": state,
                "terminal_telemetry_schema": "deadline_poll_v1",
                "terminal_deadline_seconds": CANCEL_TERMINAL_CONVERGENCE_TIMEOUT_SECONDS,
                "terminal_max_iterations": CANCEL_TERMINAL_POLL_MAX_ITERATIONS,
                "proof_polls": polls,
                "consecutive_exact": consecutive,
                "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
                "observed_terminal_mismatch_fields": sorted(observed),
                "terminal_mismatch_field_occurrences": dict(
                    sorted(occurrences.items())
                ),
                "final_terminal_mismatch_fields": list(final_mismatches),
            }
        if not _bounded_poll_sleep(deadline, CANCEL_TERMINAL_POLL_INTERVAL_SECONDS):
            break
    raise LifecycleFailure(
        "cancellation_unconfirmed",
        cancellation={
            **identity_proof,
            "pre_control_snapshot_status": pre_control_status,
            "pre_control_mismatch_fields": list(pre_control["mismatch_fields"]),
            "cancel_attempts": 0 if cancel_outcome == "not_needed" else 1,
            "cancel_command_outcome": cancel_outcome,
            "terminal_state": state,
            "terminal_telemetry_schema": "deadline_poll_v1",
            "terminal_deadline_seconds": CANCEL_TERMINAL_CONVERGENCE_TIMEOUT_SECONDS,
            "terminal_max_iterations": CANCEL_TERMINAL_POLL_MAX_ITERATIONS,
            "proof_polls": polls,
            "consecutive_exact": consecutive,
            "elapsed_milliseconds": int((time.monotonic() - started) * 1000),
            "observed_terminal_mismatch_fields": sorted(observed),
            "terminal_mismatch_field_occurrences": dict(sorted(occurrences.items())),
            "final_terminal_mismatch_fields": list(final_mismatches),
        },
    )


def terminal_body(
    *,
    state: str,
    code: str | None,
    launcher_sha: str,
    intent_file_sha: str,
    environment_sha: str,
    task_sha: str,
    role_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
    job_id: str | None,
    job_name: str,
    token: str,
    authorization_path: Path,
    authorization_sha: str,
    activation_permit_path: Path,
    activation_permit_sha: str,
    x2p_sha256: Mapping[str, str],
    held_validation: Mapping[str, Any] | None,
    release: Mapping[str, Any] | None,
    cancellation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    x2p_commitments = validate_x2p_environment_sha256(x2p_sha256)
    return {
        "schema_version": 1,
        "kind": "terminal_bench_vmvm_infrastructure_retry_v22_submission",
        "state": state,
        "code": code,
        "launcher_sha256": launcher_sha,
        "generator_sha256": GENERATOR_SHA256,
        "job_wrapper_sha256": JOB_WRAPPER_SHA256,
        "intent_sha256": intent_file_sha,
        "environment_sha256": environment_sha,
        "source_revision": SOURCE_REVISION,
        "source_tree": SOURCE_TREE,
        "verifiers_revision": VERIFIERS_REVISION,
        "vmvm_tb_v2_sha256": VMVM_SHA256,
        "x2p_environment_sha256": x2p_commitments,
        "selection": {
            "receipt_file_sha256": receipt_file_sha,
            "receipt_sha256": receipt_sha,
            "task_file_sha256": task_sha,
            "role_file_sha256": role_sha,
            "selected": EXPECTED_SELECTED,
            "retry_candidates": EXPECTED_CANDIDATES,
            "controls": EXPECTED_CONTROLS,
        },
        "attempt_policy": ATTEMPT_POLICY,
        "module_import_closure": {
            "packaging": expected_packaging_provenance(),
        },
        "scheduler": {
            "cluster": CLUSTER,
            "job_id": job_id,
            "job_name": job_name,
            "launch_token": token,
            "submission_attempts": 1,
            "time_limit": "7-00:00:00",
            "submitted_held": True,
        },
        "lifecycle": {
            "protocol": "held_two_phase_deadline_v2",
            "authorization": {
                "path": str(authorization_path),
                "sha256": authorization_sha,
                "mode": "0400",
            },
            "activation_permit": {
                "path": str(activation_permit_path),
                "sha256": activation_permit_sha,
                "mode": "0400",
                "published_last": True,
            },
            "held_validation": dict(held_validation) if held_validation else None,
            "release": dict(release) if release else None,
            "cancellation": dict(cancellation) if cancellation else None,
        },
        "acceptance": {
            "minimum_valid": MINIMUM_VALID,
            "all_controls_valid": True,
            "minimum_retry_recoveries": MINIMUM_CANDIDATE_RECOVERIES,
            "projected_union_valid": 2500,
        },
        "automatic_union_or_promotion": False,
    }


def _valid_field_names(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(
            isinstance(field, str)
            and field in MISMATCH_FIELD_ALLOWLIST
            for field in value
        )
        and value == sorted(set(value))
    )


def _valid_occurrence_counts(
    value: object, observed: object, polls: object
) -> bool:
    return (
        isinstance(value, dict)
        and _valid_field_names(observed)
        and type(polls) is int
        and set(value) == set(observed)
        and all(
            isinstance(field, str)
            and type(count) is int
            and 1 <= count <= polls
            for field, count in value.items()
        )
    )


def _valid_scontrol_category_telemetry(
    counts: object, final: object, polls: object
) -> bool:
    if (
        not isinstance(counts, dict)
        or not isinstance(final, dict)
        or type(polls) is not int
        or set(counts) != set(SCONTROL_ALLOCATION_CATEGORY_VALUES)
        or set(final) != set(SCONTROL_ALLOCATION_CATEGORY_VALUES)
    ):
        return False
    for field, allowed in SCONTROL_ALLOCATION_CATEGORY_VALUES.items():
        field_counts = counts.get(field)
        if (
            not isinstance(field_counts, dict)
            or set(field_counts) != allowed
            or any(type(count) is not int or count < 0 for count in field_counts.values())
            or sum(field_counts.values()) != polls
            or final.get(field) not in allowed
            or field_counts[final[field]] < 1
        ):
            return False
    return True


def _valid_poll_telemetry(
    value: object,
    *,
    deadline_seconds: int,
    max_iterations: int,
    require_success: bool,
    held: bool,
) -> bool:
    if not isinstance(value, dict):
        return False
    generic = {
        "consecutive_exact",
        "converged",
        "deadline_seconds",
        "elapsed_milliseconds",
        "explicit_conflict_fields",
        "final_mismatch_fields",
        "final_scontrol_allocation_categories",
        "identity_status",
        "max_iterations",
        "mismatch_field_count",
        "mismatch_field_occurrences",
        "observed_mismatch_fields",
        "polls",
        "scontrol_allocation_category_counts",
        "telemetry_schema",
    }
    expected = generic | (
        {
            "final_held_accounting_status",
            "final_pre_authorization_mismatch_fields",
            "held_accounting_status_counts",
            "post_authorization_mismatch_fields",
            "required_consecutive",
        }
        if held
        else {"attempts", "command_outcome", "observed_state", "state_class"}
    )
    polls = value.get("polls")
    observed = value.get("observed_mismatch_fields")
    final = value.get("final_mismatch_fields")
    if (
        set(value) != expected
        or value.get("telemetry_schema") != "deadline_poll_v1"
        or value.get("deadline_seconds") != deadline_seconds
        or value.get("max_iterations") != max_iterations
        or type(polls) is not int
        or not 1 <= polls <= max_iterations
        or type(value.get("converged")) is not bool
        or value.get("identity_status")
        not in {"converged", "explicit_identity_conflict", "unavailable_or_incomplete"}
        or type(value.get("consecutive_exact")) is not int
        or not 0 <= value["consecutive_exact"] <= polls
        or type(value.get("elapsed_milliseconds")) is not int
        or value["elapsed_milliseconds"] < 0
        or not _valid_field_names(observed)
        or value.get("mismatch_field_count") != len(observed)
        or not _valid_field_names(final)
        or not set(final).issubset(observed)
        or not _valid_field_names(value.get("explicit_conflict_fields"))
        or not set(value["explicit_conflict_fields"]).issubset(
            IDENTITY_CONFLICT_FIELDS
        )
        or not set(value["explicit_conflict_fields"]).issubset(observed)
        or not _valid_occurrence_counts(
            value.get("mismatch_field_occurrences"), observed, polls
        )
        or not _valid_scontrol_category_telemetry(
            value.get("scontrol_allocation_category_counts"),
            value.get("final_scontrol_allocation_categories"),
            polls,
        )
    ):
        return False
    if held:
        accounting = value.get("held_accounting_status_counts")
        if (
            value.get("required_consecutive") != HELD_REQUIRED_CONSECUTIVE
            or not isinstance(accounting, dict)
            or set(accounting) != HELD_ACCOUNTING_STATUSES
            or any(type(count) is not int or count < 0 for count in accounting.values())
            or sum(accounting.values()) != polls
            or value.get("final_held_accounting_status")
            not in HELD_ACCOUNTING_STATUSES
            or accounting[value["final_held_accounting_status"]] < 1
            or not _valid_field_names(
                value.get("final_pre_authorization_mismatch_fields")
            )
            or not _valid_field_names(value.get("post_authorization_mismatch_fields"))
        ):
            return False
    elif (
        value.get("attempts") != 1
        or value.get("command_outcome") not in {"completed", "nonzero", "unknown"}
        or value.get("state_class") not in {"active", "terminal", "unknown"}
        or value.get("observed_state") not in ACTIVE_STATES | TERMINAL_STATES | {"UNKNOWN"}
    ):
        return False
    if require_success:
        return (
            value.get("converged") is True
            and value.get("identity_status") == "converged"
            and value.get("explicit_conflict_fields") == []
            and type(value.get("consecutive_exact")) is int
            and value["consecutive_exact"] >= 2
            and value["final_mismatch_fields"] == []
        )
    return True


def validate_submission_receipt(
    value: Mapping[str, Any],
    *,
    launcher_sha: str,
    task_sha: str,
    role_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
    x2p_sha256: Mapping[str, str],
) -> tuple[str, str, str, str, Path, str, Path, str]:
    x2p_commitments = validate_x2p_environment_sha256(x2p_sha256)
    body = dict(value)
    envelope_sha = body.pop("submission_receipt_sha256", None)
    scheduler = body.get("scheduler")
    selection = body.get("selection")
    lifecycle = body.get("lifecycle")
    authorization = (
        lifecycle.get("authorization") if isinstance(lifecycle, dict) else None
    )
    permit = lifecycle.get("activation_permit") if isinstance(lifecycle, dict) else None
    held = lifecycle.get("held_validation") if isinstance(lifecycle, dict) else None
    release = lifecycle.get("release") if isinstance(lifecycle, dict) else None
    job_id = scheduler.get("job_id") if isinstance(scheduler, dict) else None
    job_name = scheduler.get("job_name") if isinstance(scheduler, dict) else None
    if (
        not isinstance(envelope_sha, str)
        or envelope_sha != sha256_bytes(canonical_json(body))
        or set(body)
        != {
            "acceptance",
            "attempt_policy",
            "automatic_union_or_promotion",
            "code",
            "environment_sha256",
            "generator_sha256",
            "intent_sha256",
            "job_wrapper_sha256",
            "kind",
            "launcher_sha256",
            "lifecycle",
            "module_import_closure",
            "scheduler",
            "schema_version",
            "selection",
            "source_revision",
            "source_tree",
            "state",
            "verifiers_revision",
            "vmvm_tb_v2_sha256",
            "x2p_environment_sha256",
        }
        or body.get("schema_version") != 1
        or body.get("kind") != "terminal_bench_vmvm_infrastructure_retry_v22_submission"
        or body.get("state") != "submitted"
        or body.get("code") is not None
        or body.get("launcher_sha256") != launcher_sha
        or body.get("generator_sha256") != GENERATOR_SHA256
        or body.get("job_wrapper_sha256") != JOB_WRAPPER_SHA256
        or body.get("source_revision") != SOURCE_REVISION
        or body.get("source_tree") != SOURCE_TREE
        or body.get("verifiers_revision") != VERIFIERS_REVISION
        or body.get("vmvm_tb_v2_sha256") != VMVM_SHA256
        or body.get("x2p_environment_sha256") != x2p_commitments
        or body.get("attempt_policy") != ATTEMPT_POLICY
        or body.get("module_import_closure")
        != {"packaging": expected_packaging_provenance()}
        or body.get("acceptance")
        != {
            "minimum_valid": MINIMUM_VALID,
            "all_controls_valid": True,
            "minimum_retry_recoveries": MINIMUM_CANDIDATE_RECOVERIES,
            "projected_union_valid": 2500,
        }
        or body.get("automatic_union_or_promotion") is not False
        or selection
        != {
            "receipt_file_sha256": receipt_file_sha,
            "receipt_sha256": receipt_sha,
            "task_file_sha256": task_sha,
            "role_file_sha256": role_sha,
            "selected": EXPECTED_SELECTED,
            "retry_candidates": EXPECTED_CANDIDATES,
            "controls": EXPECTED_CONTROLS,
        }
        or not isinstance(scheduler, dict)
        or set(scheduler)
        != {
            "cluster",
            "job_id",
            "job_name",
            "launch_token",
            "submission_attempts",
            "submitted_held",
            "time_limit",
        }
        or scheduler.get("cluster") != CLUSTER
        or not isinstance(job_id, str)
        or JOB_RE.fullmatch(job_id) is None
        or not isinstance(job_name, str)
        or V1.JOB_NAME_RE.fullmatch(job_name) is None
        or not isinstance(scheduler.get("launch_token"), str)
        or re.fullmatch(r"[0-9a-f]{24}", scheduler["launch_token"]) is None
        or job_name != f"mirc-{scheduler['launch_token']}"
        or scheduler.get("submission_attempts") != 1
        or scheduler.get("submitted_held") is not True
        or scheduler.get("time_limit") != "7-00:00:00"
        or not isinstance(body.get("intent_sha256"), str)
        or SHA_RE.fullmatch(body["intent_sha256"]) is None
        or not isinstance(body.get("environment_sha256"), str)
        or SHA_RE.fullmatch(body["environment_sha256"]) is None
        or not isinstance(lifecycle, dict)
        or set(lifecycle)
        != {
            "activation_permit",
            "authorization",
            "cancellation",
            "held_validation",
            "protocol",
            "release",
        }
        or lifecycle.get("protocol") != "held_two_phase_deadline_v2"
        or lifecycle.get("cancellation") is not None
        or not isinstance(authorization, dict)
        or not isinstance(permit, dict)
        or authorization.get("path")
        != str(_token_path("job_authorization", scheduler["launch_token"]))
        or authorization.get("mode") != "0400"
        or not isinstance(authorization.get("sha256"), str)
        or SHA_RE.fullmatch(authorization["sha256"]) is None
        or permit.get("path")
        != str(_token_path("activation_permit", scheduler["launch_token"]))
        or permit.get("mode") != "0400"
        or permit.get("published_last") is not True
        or not isinstance(permit.get("sha256"), str)
        or SHA_RE.fullmatch(permit["sha256"]) is None
        or not _valid_poll_telemetry(
            held,
            deadline_seconds=HELD_CONVERGENCE_TIMEOUT_SECONDS,
            max_iterations=HELD_POLL_MAX_ITERATIONS,
            require_success=True,
            held=True,
        )
        or held.get("final_pre_authorization_mismatch_fields") != []
        or held.get("post_authorization_mismatch_fields") != []
        or not _valid_poll_telemetry(
            release,
            deadline_seconds=ACTIVATION_CONVERGENCE_TIMEOUT_SECONDS,
            max_iterations=ACTIVATION_POLL_MAX_ITERATIONS,
            require_success=True,
            held=False,
        )
        or release.get("state_class") != "active"
        or release.get("observed_state") not in ACTIVE_STATES
    ):
        fail("submission_receipt_invalid")
    return (
        job_id,
        job_name,
        body["intent_sha256"],
        envelope_sha,
        Path(authorization["path"]),
        authorization["sha256"],
        Path(permit["path"]),
        permit["sha256"],
    )


def publish_authorization(path: Path, raw: bytes, digest: str) -> None:
    if path.parent != RESERVATION or path.exists() or path.is_symlink():
        fail("authorization_path_invalid")
    if sha256_bytes(raw) != digest:
        fail("authorization_hash_invalid")
    write_once(path, raw, 0o400)
    sync_directory(RESERVATION)


def authorize_held_job(
    job_id: str,
    job_name: str,
    authorization_path: Path,
    authorization_raw: bytes,
    authorization_sha: str,
) -> dict[str, Any]:
    telemetry = poll_held_convergence(job_id, job_name)
    telemetry["final_pre_authorization_mismatch_fields"] = None
    telemetry["post_authorization_mismatch_fields"] = None
    if telemetry.get("explicit_conflict_fields"):
        raise LifecycleFailure(
            "scheduler_identity_conflict", held_validation=telemetry
        )
    if telemetry.get("converged") is not True:
        raise LifecycleFailure(
            "held_identity_not_converged", held_validation=telemetry
        )
    exact_before, mismatches_before, conflicts_before, _details_before = held_snapshot(
        job_id, job_name
    )
    telemetry["final_pre_authorization_mismatch_fields"] = list(mismatches_before)
    telemetry["explicit_conflict_fields"] = sorted(
        set(telemetry["explicit_conflict_fields"]) | set(conflicts_before)
    )
    if telemetry["explicit_conflict_fields"]:
        telemetry["identity_status"] = "explicit_identity_conflict"
        raise LifecycleFailure(
            "scheduler_identity_conflict", held_validation=telemetry
        )
    if not exact_before:
        raise LifecycleFailure(
            "held_state_lost_before_authorization", held_validation=telemetry
        )
    publish_authorization(authorization_path, authorization_raw, authorization_sha)
    exact_after, mismatches_after, conflicts_after, _details_after = held_snapshot(
        job_id, job_name
    )
    telemetry["post_authorization_mismatch_fields"] = list(mismatches_after)
    telemetry["explicit_conflict_fields"] = sorted(
        set(telemetry["explicit_conflict_fields"]) | set(conflicts_after)
    )
    if telemetry["explicit_conflict_fields"]:
        telemetry["identity_status"] = "explicit_identity_conflict"
        raise LifecycleFailure(
            "scheduler_identity_conflict", held_validation=telemetry
        )
    if not exact_after:
        raise LifecycleFailure(
            "held_state_lost_after_authorization", held_validation=telemetry
        )
    return telemetry


def release_and_reconcile(job_id: str, job_name: str) -> dict[str, Any]:
    outcome = invoke_control_once(
        ["/usr/bin/scontrol", "-M", CLUSTER, "release", job_id]
    )
    activation, state = poll_activation(job_id, job_name)
    record = {
        "attempts": 1,
        "command_outcome": outcome,
        "observed_state": state,
        **activation,
    }
    if activation.get("explicit_conflict_fields"):
        raise LifecycleFailure("scheduler_identity_conflict", release=record)
    if activation.get("converged") is not True:
        raise LifecycleFailure("activation_not_converged", release=record)
    if state in TERMINAL_STATES:
        raise LifecycleFailure("activation_terminal_before_permit", release=record)
    return record


def _seal_reservation() -> None:
    sync_directory(RESERVATION)
    os.chmod(RESERVATION, 0o500, follow_symlinks=False)
    sync_directory(RESERVATION)
    sync_directory(RESERVATION.parent)
    require_directory(RESERVATION, 0o500)


def publish_success(
    body: Mapping[str, Any],
    *,
    authorization_path: Path,
    authorization_sha: str,
    activation_permit_path: Path,
    activation_permit_raw: bytes,
    activation_permit_sha: str,
    commit_state: dict[str, bool],
) -> str:
    if commit_state != {"committed": False}:
        fail("success_commit_state_invalid")
    if (
        os.path.lexists(FAILURE_CERTIFICATE)
        or os.path.lexists(SUBMISSION_RECEIPT)
        or os.path.lexists(activation_permit_path)
    ):
        fail("terminal_receipt_conflict")
    file_bytes(authorization_path, expected_sha256=authorization_sha, mode=0o400)
    receipt_raw = envelope(body, "submission_receipt_sha256")
    if sha256_bytes(activation_permit_raw) != activation_permit_sha:
        fail("activation_permit_hash_invalid")
    if stat.S_IMODE(RESERVATION.stat(follow_symlinks=False).st_mode) != 0o700:
        fail("success_reservation_invalid")
    expected_before = {
        INTENT.name,
        ENVIRONMENT_FILE.name,
        authorization_path.name,
    }
    if {entry.name for entry in os.scandir(RESERVATION)} != expected_before:
        fail("success_reservation_invalid")
    blocked = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    receipt_written = False
    permit_written = False
    try:
        digest = write_once(SUBMISSION_RECEIPT, receipt_raw, 0o400)
        receipt_written = True
        file_bytes(
            SUBMISSION_RECEIPT,
            expected_sha256=digest,
            mode=0o400,
            maximum=1 << 20,
        )
        # The permit is the final directory entry.  Admission becomes visible
        # only when the complete directory is changed to mode 0500 below.
        write_once(activation_permit_path, activation_permit_raw, 0o400)
        permit_written = True
        file_bytes(
            activation_permit_path,
            expected_sha256=activation_permit_sha,
            mode=0o400,
            maximum=1 << 20,
        )
        expected_children = expected_before | {
            SUBMISSION_RECEIPT.name,
            activation_permit_path.name,
        }
        if {entry.name for entry in os.scandir(RESERVATION)} != expected_children:
            fail("success_reservation_invalid")
        sync_directory(RESERVATION)
        os.chmod(RESERVATION, 0o500, follow_symlinks=False)
        # chmod is the admission commit point.  Update in-memory state before
        # any further fallible operation or signal delivery.
        commit_state["committed"] = True
        sync_directory(RESERVATION)
        sync_directory(RESERVATION.parent)
        return digest
    except BaseException:
        if not commit_state["committed"]:
            rollback_failed = False
            for path, written in (
                (activation_permit_path, permit_written),
                (SUBMISSION_RECEIPT, receipt_written),
            ):
                if not written:
                    continue
                try:
                    path.unlink()
                except OSError:
                    rollback_failed = True
            try:
                sync_directory(RESERVATION)
            except BaseException:  # noqa: BLE001 - preserve a fail-closed rollback
                rollback_failed = True
            if rollback_failed:
                raise LifecycleFailure("success_publication_rollback_failed") from None
        raise
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def publish_failure(body: Mapping[str, Any]) -> str:
    try:
        permit_present = any(
            entry.name.startswith("activation_permit_")
            for entry in os.scandir(RESERVATION)
        )
    except OSError as error:
        raise LauncherError("failure_reservation_unavailable") from error
    if (
        os.path.lexists(FAILURE_CERTIFICATE)
        or os.path.lexists(SUBMISSION_RECEIPT)
        or permit_present
    ):
        fail("terminal_receipt_conflict")
    try:
        observed_mode = stat.S_IMODE(RESERVATION.stat(follow_symlinks=False).st_mode)
    except OSError as error:
        raise LauncherError("failure_reservation_unavailable") from error
    if observed_mode == 0o500:
        os.chmod(RESERVATION, 0o700, follow_symlinks=False)
        sync_directory(RESERVATION.parent)
    elif observed_mode != 0o700:
        fail("failure_reservation_invalid")
    raw = envelope(body, "failure_certificate_sha256")
    digest = write_once(FAILURE_CERTIFICATE, raw, 0o400)
    _seal_reservation()
    file_bytes(FAILURE_CERTIFICATE, expected_sha256=digest, mode=0o400, maximum=1 << 20)
    return digest


def verify_generation(
    generator: Any,
    task_sha: str,
    role_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
) -> None:
    try:
        result = generator.prepare(GENERATOR_SHA256, verify_only=True)
    except Exception as error:
        raise LauncherError("selection_verification_failed") from error
    if result != {
        "state": "verified",
        "selected": EXPECTED_SELECTED,
        "retry_candidates": EXPECTED_CANDIDATES,
        "controls": EXPECTED_CONTROLS,
        "task_file_sha256": task_sha,
        "role_file_sha256": role_sha,
        "selection_receipt_file_sha256": receipt_file_sha,
        "selection_receipt_sha256": receipt_sha,
        "projected_minimum_valid": 2500,
    }:
        fail("selection_verification_failed")


def immediate_pre_submit_revalidation(
    *,
    launcher_sha: str,
    generator: Any,
    task_sha: str,
    role_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
    intent_sha: str,
    environment_sha: str,
    environment_raw: bytes,
    authorization_raw: bytes,
    authorization_sha: str,
    activation_permit_raw: bytes,
    activation_permit_sha: str,
    job_name: str,
    start_date: str,
    tls_credentials: Mapping[str, StableCredential],
) -> None:
    validate_tmux_ancestry()
    verify_generation(generator, task_sha, role_sha, receipt_file_sha, receipt_sha)
    observed = validate_selection()
    if observed != (task_sha, role_sha, receipt_file_sha, receipt_sha):
        fail("selection_changed")
    validate_launch_dependencies(generator)
    if OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink():
        fail("launch_namespace_not_fresh")
    require_directory(RESERVATION, 0o700)
    require_directory(LOG_ROOT, 0o700)
    try:
        children = {entry.name for entry in os.scandir(RESERVATION)}
        log_children = {entry.name for entry in os.scandir(LOG_ROOT)}
    except OSError as error:
        raise LauncherError("launch_reservation_invalid") from error
    if children != {INTENT.name, ENVIRONMENT_FILE.name} or log_children:
        fail("launch_reservation_invalid")
    file_bytes(INTENT, expected_sha256=intent_sha, mode=0o400, maximum=1 << 20)
    if (
        file_bytes(
            ENVIRONMENT_FILE,
            expected_sha256=environment_sha,
            mode=0o400,
            maximum=1 << 20,
        )
        != environment_raw
    ):
        fail("slurm_environment_changed")
    if (
        sha256_bytes(authorization_raw) != authorization_sha
        or sha256_bytes(activation_permit_raw) != activation_permit_sha
    ):
        fail("authorization_precommit_changed")
    if scheduler_matches(job_name, start_date):
        fail("scheduler_name_not_fresh")
    # These are the final filesystem reads before the sole sbatch call.
    # Earlier validation cannot substitute for them.
    file_bytes(
        CANONICAL_SELF, expected_sha256=launcher_sha, mode=0o500, maximum=1 << 20
    )
    file_bytes(GENERATOR, expected_sha256=GENERATOR_SHA256, mode=0o500, maximum=1 << 20)
    file_bytes(
        PACKAGING_SNAPSHOT,
        expected_sha256=PACKAGING_SNAPSHOT_SHA256,
        mode=0o400,
        maximum=1 << 20,
    )
    file_bytes(
        JOB_WRAPPER, expected_sha256=JOB_WRAPPER_SHA256, mode=0o500, maximum=1 << 20
    )
    validate_artifact_root_inventory()
    # Keep the exact caller-provided TLS files descriptor-bound through the
    # final pre-sbatch gate.  Their paths and digests exist only in the private
    # mode-0400 export file, never in public receipts or console output.
    revalidate_tls_credentials(tls_credentials)


def parse_sbatch_response(
    outcome: str,
    return_code: int,
    stdout: str,
) -> tuple[str | None, str]:
    candidate: str | None = None
    lines = stdout.splitlines()
    if outcome == "completed" and return_code == 0 and len(lines) == 1:
        fields = lines[0].split(";", 1)
        if JOB_RE.fullmatch(fields[0]) is not None and (
            len(fields) == 1 or fields[1] == CLUSTER
        ):
            candidate = fields[0]
        else:
            outcome = "malformed"
    elif outcome == "completed" and return_code == 0:
        outcome = "malformed"
    elif outcome == "completed":
        outcome = "nonzero"
    if outcome == "cleanup_failed":
        fail("sbatch_cleanup_failed")
    return candidate, outcome


def resolve_submission(
    candidate: str | None,
    outcome: str,
    job_name: str,
    start_date: str,
) -> tuple[str | None, str | None]:
    lookup_state, recovered = lookup_submission(job_name, start_date)
    if lookup_state == "unique" and recovered is not None:
        if candidate is not None and candidate != recovered:
            fail("submission_identity_ambiguous")
        return recovered, "sbatch_and_name" if candidate is not None else "name_lookup"
    if candidate is not None:
        fail("submission_visibility_ambiguous")
    if lookup_state != "zero_proved":
        fail("submission_outcome_unknown")
    return None, None


def submit_once(
    launcher_sha: str,
    generator: Any,
    task_sha: str,
    role_sha: str,
    receipt_file_sha: str,
    receipt_sha: str,
    tls_credentials: Mapping[str, StableCredential],
    x2p_values: Mapping[str, str],
) -> tuple[str, str]:
    private_x2p_values = validate_private_x2p_environment(x2p_values)
    x2p_sha256 = x2p_environment_sha256(private_x2p_values)
    submission_started_at = datetime.now(UTC)
    start_date = submission_started_at.date().isoformat()
    token = secrets.token_hex(12)
    job_name = f"mirc-{token}"
    if scheduler_matches(job_name, start_date):
        fail("scheduler_name_not_fresh")
    authorization_path, authorization_raw, authorization_sha = authorization_bytes(
        launcher_sha=launcher_sha,
        token=token,
        job_name=job_name,
        task_sha=task_sha,
        role_sha=role_sha,
        receipt_file_sha=receipt_file_sha,
        receipt_sha=receipt_sha,
        x2p_sha256=x2p_sha256,
    )
    activation_permit_path, activation_permit_raw, activation_permit_sha = (
        activation_permit_bytes(
            token=token,
            job_name=job_name,
            authorization_sha=authorization_sha,
        )
    )
    environment_raw = environment_bytes(
        slurm_environment(
            task_sha,
            role_sha,
            receipt_file_sha,
            receipt_sha,
            launcher_sha=launcher_sha,
            token=token,
            job_name=job_name,
            authorization_path=authorization_path,
            authorization_sha=authorization_sha,
            activation_permit_path=activation_permit_path,
            activation_permit_sha=activation_permit_sha,
            tls_credentials=tls_credentials,
            private_x2p_values=private_x2p_values,
        )
    )
    intent_sha, environment_sha = acquire_reservation(
        launcher_sha,
        task_sha,
        role_sha,
        receipt_file_sha,
        receipt_sha,
        token,
        authorization_path,
        authorization_sha,
        activation_permit_path,
        activation_permit_sha,
        x2p_sha256,
        environment_raw,
        submission_started_at.isoformat(timespec="seconds"),
    )
    candidate: str | None = None
    candidate_provenance: str | None = None
    seen_direct_candidate = False
    explicit_conflict_fields: set[str] = set()
    held_validation: dict[str, Any] | None = None
    release_record: dict[str, Any] | None = None
    commit_state = {"committed": False}
    original_code = "launch_failed"
    try:
        immediate_pre_submit_revalidation(
            launcher_sha=launcher_sha,
            generator=generator,
            task_sha=task_sha,
            role_sha=role_sha,
            receipt_file_sha=receipt_file_sha,
            receipt_sha=receipt_sha,
            intent_sha=intent_sha,
            environment_sha=environment_sha,
            environment_raw=environment_raw,
            authorization_raw=authorization_raw,
            authorization_sha=authorization_sha,
            activation_permit_raw=activation_permit_raw,
            activation_permit_sha=activation_permit_sha,
            job_name=job_name,
            start_date=start_date,
            tls_credentials=tls_credentials,
        )
        outcome, return_code, stdout = invoke_sbatch(sbatch_command(job_name))
        candidate, outcome = parse_sbatch_response(outcome, return_code, stdout)
        if candidate is not None:
            seen_direct_candidate = True
            candidate_provenance = "sbatch_stdout"
        candidate, resolved_provenance = resolve_submission(
            candidate, outcome, job_name, start_date
        )
        if resolved_provenance is not None:
            candidate_provenance = resolved_provenance
        if candidate is not None:
            held_validation = authorize_held_job(
                candidate,
                job_name,
                authorization_path,
                authorization_raw,
                authorization_sha,
            )
            release_record = release_and_reconcile(candidate, job_name)
            success_body = terminal_body(
                state="submitted",
                code=None,
                launcher_sha=launcher_sha,
                intent_file_sha=intent_sha,
                environment_sha=environment_sha,
                task_sha=task_sha,
                role_sha=role_sha,
                receipt_file_sha=receipt_file_sha,
                receipt_sha=receipt_sha,
                job_id=candidate,
                job_name=job_name,
                token=token,
                authorization_path=authorization_path,
                authorization_sha=authorization_sha,
                activation_permit_path=activation_permit_path,
                activation_permit_sha=activation_permit_sha,
                x2p_sha256=x2p_sha256,
                held_validation=held_validation,
                release=release_record,
                cancellation=None,
            )
            receipt_digest = publish_success(
                success_body,
                authorization_path=authorization_path,
                authorization_sha=authorization_sha,
                activation_permit_path=activation_permit_path,
                activation_permit_raw=activation_permit_raw,
                activation_permit_sha=activation_permit_sha,
                commit_state=commit_state,
            )
            return candidate, receipt_digest
        failure_code = {
            "exec_error": "sbatch_exec_failed_no_job",
            "malformed": "sbatch_response_invalid_no_job",
            "nonzero": "sbatch_rejected_no_job",
            "timeout": "sbatch_timeout_no_job",
        }.get(outcome, "sbatch_failed_no_job")
        fail(failure_code)
    except BaseException as error:
        if commit_state["committed"]:
            raise
        if isinstance(error, LifecycleFailure):
            if error.held_validation is not None:
                held_validation = error.held_validation
                fields = error.held_validation.get("explicit_conflict_fields", [])
                if isinstance(fields, list):
                    explicit_conflict_fields.update(
                        field for field in fields if isinstance(field, str)
                    )
            if error.release is not None:
                release_record = error.release
                fields = error.release.get("explicit_conflict_fields", [])
                if isinstance(fields, list):
                    explicit_conflict_fields.update(
                        field for field in fields if isinstance(field, str)
                    )
        # Cleanup is bounded.  The installed signal handler consults this flag
        # so repeated delivery cannot strand a known allocation mid-cancel.
        global _CLEANUP_IN_PROGRESS
        _CLEANUP_IN_PROGRESS = True
        if isinstance(error, LauncherError) and SAFE_CODE_RE.fullmatch(str(error)):
            original_code = str(error)
        elif isinstance(error, LaunchInterrupted):
            original_code = "launch_interrupted"
        cancellation: dict[str, Any] = {
            "required": False,
            "confirmed": True,
            "reason": "no_job_proved",
        }
        recovery_ambiguous = False
        try:
            lookup_state, recovered = lookup_submission(job_name, start_date)
            if lookup_state == "unique" and recovered is not None:
                if candidate is not None and candidate != recovered:
                    recovery_ambiguous = True
                else:
                    candidate = recovered
                    candidate_provenance = (
                        "sbatch_and_name"
                        if seen_direct_candidate
                        else "name_lookup"
                    )
            elif candidate is not None or lookup_state != "zero_proved":
                recovery_ambiguous = True
        except BaseException:  # noqa: BLE001 - recovery failures are ambiguity
            recovery_ambiguous = True
        candidate_cancelled = False
        if candidate is not None and explicit_conflict_fields:
            recovery_ambiguous = True
            cancellation = {
                "required": True,
                "confirmed": False,
                "identity_status": "explicit_identity_conflict",
                "identity_converged": False,
                "candidate_provenance": candidate_provenance,
                "explicit_conflict_fields": sorted(explicit_conflict_fields),
                "cancel_attempts": 0,
                "cancel_command_outcome": "not_authorized",
            }
        elif candidate is not None:
            try:
                if candidate_provenance is None:
                    raise LifecycleFailure("cancellation_unconfirmed")
                proof = cancel_and_prove(
                    candidate,
                    job_name,
                    start_date,
                    candidate_provenance=candidate_provenance,
                )
                cancellation = {"required": True, "confirmed": True, **proof}
                candidate_cancelled = True
            except BaseException as cancellation_error:  # noqa: BLE001
                recovery_ambiguous = True
                if (
                    isinstance(cancellation_error, LifecycleFailure)
                    and cancellation_error.cancellation is not None
                ):
                    fields = cancellation_error.cancellation.get(
                        "explicit_conflict_fields", []
                    )
                    if isinstance(fields, list):
                        explicit_conflict_fields.update(
                            field for field in fields if isinstance(field, str)
                        )
                    cancellation = {
                        "required": True,
                        "confirmed": False,
                        **cancellation_error.cancellation,
                    }
        if recovery_ambiguous:
            original_code = "cancellation_unconfirmed"
            cancellation = {
                **cancellation,
                "required": candidate is not None,
                "confirmed": False,
                "known_candidate_cancelled": candidate_cancelled,
                "reason": "cancellation_unconfirmed",
            }
            if explicit_conflict_fields:
                cancellation = {
                    **cancellation,
                    "identity_status": "explicit_identity_conflict",
                    "identity_converged": False,
                    "explicit_conflict_fields": sorted(explicit_conflict_fields),
                    "cancel_attempts": cancellation.get("cancel_attempts", 0),
                    "cancel_command_outcome": cancellation.get(
                        "cancel_command_outcome", "not_authorized"
                    ),
                }
        failure_state = (
            "ambiguous" if original_code == "cancellation_unconfirmed" else "failed"
        )
        failure_body = terminal_body(
            state=failure_state,
            code=original_code,
            launcher_sha=launcher_sha,
            intent_file_sha=intent_sha,
            environment_sha=environment_sha,
            task_sha=task_sha,
            role_sha=role_sha,
            receipt_file_sha=receipt_file_sha,
            receipt_sha=receipt_sha,
            job_id=candidate,
            job_name=job_name,
            token=token,
            authorization_path=authorization_path,
            authorization_sha=authorization_sha,
            activation_permit_path=activation_permit_path,
            activation_permit_sha=activation_permit_sha,
            x2p_sha256=x2p_sha256,
            held_validation=held_validation,
            release=release_record,
            cancellation=cancellation,
        )
        try:
            if RESERVATION.exists() and not FAILURE_CERTIFICATE.exists():
                publish_failure(failure_body)
        except BaseException:  # noqa: BLE001 - never mask cancellation ambiguity
            if original_code != "cancellation_unconfirmed":
                original_code = "failure_certificate_unavailable"
        raise LauncherError(original_code) from None


def main(argv: Sequence[str] | None = None) -> int:
    global _CLEANUP_IN_PROGRESS
    _CLEANUP_IN_PROGRESS = False
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        fail("arguments_forbidden")
    launcher_sha, tls_credentials, x2p_values = validate_invocation()
    try:
        generator = load_generator()
        task_sha, role_sha, receipt_file_sha, receipt_sha = validate_selection()
        verify_generation(generator, task_sha, role_sha, receipt_file_sha, receipt_sha)
        validate_launch_dependencies(generator)
    except BaseException:
        close_tls_credentials(tls_credentials)
        raise
    previous_handlers: dict[signal.Signals, Any] = {}

    def interrupt(signum: int, _frame: Any) -> None:
        if _CLEANUP_IN_PROGRESS:
            return
        raise LaunchInterrupted(signum)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous_handlers[signum] = signal.signal(signum, interrupt)
    try:
        job_id, submission_sha = submit_once(
            launcher_sha,
            generator,
            task_sha,
            role_sha,
            receipt_file_sha,
            receipt_sha,
            tls_credentials,
            x2p_values,
        )
    finally:
        _CLEANUP_IN_PROGRESS = False
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        close_tls_credentials(tls_credentials)
    print(
        json.dumps(
            {
                "state": "submitted",
                "job_id": job_id,
                "submission_receipt_sha256": submission_sha,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    try:
        raise SystemExit(main())
    except LauncherError as error:
        code = str(error)
        if SAFE_CODE_RE.fullmatch(code) is None:
            code = "launch_failed"
        print(
            json.dumps({"state": "aborted", "code": code}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except LaunchInterrupted:
        print(
            json.dumps(
                {"state": "aborted", "code": "launch_interrupted"}, sort_keys=True
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except Exception:  # noqa: BLE001 - never expose scheduler or task details
        print(
            json.dumps({"state": "aborted", "code": "launch_failed"}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
