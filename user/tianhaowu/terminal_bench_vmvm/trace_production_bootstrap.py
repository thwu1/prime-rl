#!/usr/bin/env python3
"""Isolated, manifest-bound bootstrap for the production trace certifier."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

SHA256_RE = re.compile(r"[0-9a-f]{64}")
REVISION_RE = re.compile(r"[0-9a-f]{40}")
MAX_AUTHORIZATION_BYTES = 2 * 1024 * 1024
MAX_TREE_ENTRIES = 200_000
SUBMISSION_INTENT_TYPE = "terminal_bench_vmvm_production_trace_audit_launch_intent_v2"
SUBMISSION_HELD_TYPE = (
    "terminal_bench_vmvm_production_trace_audit_held_authorization_v2"
)
SUBMISSION_RECEIPT_TYPE = (
    "terminal_bench_vmvm_production_trace_audit_submission_receipt_v2"
)
SUBMISSION_PERMIT_TYPE = (
    "terminal_bench_vmvm_production_trace_audit_activation_permit_v2"
)
ADMISSION_SCHEMA_VERSION = 2
HELD_TIMEOUT_SECONDS = 982
FINAL_HELD_TIMEOUT_SECONDS = 40
ACTIVATION_TIMEOUT_SECONDS = 742
RESERVATION_LINK_COUNT = 2
PYCACHE_SINK = Path("/dev/null")
PHASE_FIELD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,95}")
IMPORTABLE_SUFFIXES = frozenset({".py", ".pyc", ".pyd", ".so"})
FORBIDDEN_IMPORT_NAMES = frozenset({"sitecustomize.py", "usercustomize.py"})
GIT_ENVIRONMENT = {
    "HOME": "/nonexistent",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
}
EXPECTED_ENVIRONMENT = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONNOUSERSITE",
    "PYTHONPYCACHEPREFIX",
    "PYTHONSAFEPATH",
    "THRIFT_TLS_CL_CERT_PATH",
    "THRIFT_TLS_CL_KEY_PATH",
}
RUNTIME_TOOL_PATHS = {
    "bash": "/usr/bin/bash",
    "chmod": "/usr/bin/chmod",
    "env": "/usr/bin/env",
    "git": "/usr/bin/git",
    "id": "/usr/bin/id",
    "mktemp": "/usr/bin/mktemp",
    "realpath": "/usr/bin/realpath",
    "rmdir": "/usr/bin/rmdir",
    "sacct": "/usr/bin/sacct",
    "sbatch": "/usr/bin/sbatch",
    "scancel": "/usr/bin/scancel",
    "scontrol": "/usr/bin/scontrol",
    "sha256sum": "/usr/bin/sha256sum",
    "sleep": "/usr/bin/sleep",
    "squeue": "/usr/bin/squeue",
    "stat": "/usr/bin/stat",
}


class BootstrapError(RuntimeError):
    """A stable, aggregate-only bootstrap failure."""


def fail(code: str) -> None:
    if re.fullmatch(r"[a-z0-9_]{1,96}", code) is None:
        code = "bootstrap_failed"
    raise BootstrapError(code)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _signature(value: os.stat_result) -> tuple[int, ...]:
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


def stable_bytes(
    path: Path,
    *,
    code: str,
    maximum: int,
    expected_sha256: str | None = None,
    expected_mode: int | None = None,
    expected_uid: int | None = None,
    allow_empty: bool = False,
) -> tuple[bytes, str]:
    descriptor = -1
    try:
        if not path.is_absolute() or Path(os.path.normpath(path)) != path:
            fail(code)
        if path.resolve(strict=True) != path or path.is_symlink():
            fail(code)
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or (before.st_size < 1 and not allow_empty)
            or before.st_size > maximum
            or (
                expected_mode is not None
                and stat.S_IMODE(before.st_mode) != expected_mode
            )
            or (expected_uid is not None and before.st_uid != expected_uid)
        ):
            fail(code)
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1 << 20, remaining))
            if not chunk:
                fail(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        visible = os.stat(path, follow_symlinks=False)
    except BootstrapError:
        raise
    except (OSError, RuntimeError) as error:
        raise BootstrapError(code) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    body = b"".join(chunks)
    digest = hashlib.sha256(body).hexdigest()
    if (
        _signature(before) != _signature(after)
        or _signature(after) != _signature(visible)
        or (expected_sha256 is not None and digest != expected_sha256)
    ):
        fail(code)
    return body, digest


def _stable_bytes_at(
    directory_fd: int,
    name: str,
    *,
    code: str,
    maximum: int,
    expected_mode: int,
    expected_uid: int,
) -> tuple[bytes, str]:
    descriptor = -1
    try:
        if not name or "/" in name or name in {".", ".."}:
            fail(code)
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 1
            or before.st_size > maximum
            or stat.S_IMODE(before.st_mode) != expected_mode
            or before.st_uid != expected_uid
        ):
            fail(code)
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1 << 20, remaining))
            if not chunk:
                fail(code)
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except BootstrapError:
        raise
    except OSError as error:
        raise BootstrapError(code) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    body = b"".join(chunks)
    if _signature(before) != _signature(after) or _signature(after) != _signature(
        visible
    ):
        fail(code)
    return body, hashlib.sha256(body).hexdigest()


def _descriptor_sha256(descriptor: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        try:
            block = os.pread(descriptor, min(1 << 20, size - offset), offset)
        except OSError as error:
            raise BootstrapError("verified_extension_changed") from error
        if not block:
            fail("verified_extension_changed")
        digest.update(block)
        offset += len(block)
    return digest.hexdigest()


def _sealed_memfd(body: bytes, name: str) -> int:
    descriptor = -1
    required = (
        fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
    )
    try:
        descriptor = os.memfd_create(
            name,
            os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
        )
        offset = 0
        while offset < len(body):
            written = os.write(descriptor, body[offset:])
            if written <= 0:
                fail("verified_extension_capture_failed")
            offset += written
        os.fchmod(descriptor, 0o400)
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, required)
        status = os.fstat(descriptor)
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 0
            or status.st_size != len(body)
            or fcntl.fcntl(descriptor, fcntl.F_GET_SEALS) != required
            or _descriptor_sha256(descriptor, status.st_size)
            != hashlib.sha256(body).hexdigest()
        ):
            fail("verified_extension_capture_failed")
        return descriptor
    except BootstrapError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise BootstrapError("verified_extension_capture_failed") from error


def _strict_json(raw: bytes, code: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
    except (UnicodeDecodeError, ValueError, TypeError) as error:
        raise BootstrapError(code) from error
    if not isinstance(value, dict):
        fail(code)
    return value


def load_authorization(path: Path, expected_sha256: str) -> dict[str, Any]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        fail("authorization_hash_invalid")
    raw, observed = stable_bytes(
        path,
        code="authorization_invalid",
        maximum=MAX_AUTHORIZATION_BYTES,
        expected_sha256=expected_sha256,
        expected_mode=0o400,
        expected_uid=os.getuid(),
    )
    value = _strict_json(raw, "authorization_invalid")
    if raw != canonical_json(value) + b"\n":
        fail("authorization_invalid")
    body = dict(value)
    embedded = body.pop("authorization_sha256", None)
    if (
        observed != expected_sha256
        or embedded != hashlib.sha256(canonical_json(body)).hexdigest()
        or value.get("artifact_type")
        != "terminal_bench_vmvm_production_trace_audit_authorization_v2"
        or value.get("schema_version") != 1
        or value.get("state") != "approved"
    ):
        fail("authorization_invalid")
    return value


def _load_envelope(
    directory_fd: int,
    name: str,
    kind: str,
    hash_field: str,
) -> tuple[dict[str, Any], str]:
    raw, digest = _stable_bytes_at(
        directory_fd,
        name,
        code="submission_admission_invalid",
        maximum=2 * 1024 * 1024,
        expected_mode=0o400,
        expected_uid=os.getuid(),
    )
    value = _strict_json(raw, "submission_admission_invalid")
    body = dict(value)
    embedded = body.pop(hash_field, None)
    if (
        raw != json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        or value.get("schema_version") != ADMISSION_SCHEMA_VERSION
        or value.get("artifact_type") != kind
        or embedded != hashlib.sha256(canonical_json(body)).hexdigest()
    ):
        fail("submission_admission_invalid")
    return value, digest


def _reservation_identity(
    status: os.stat_result,
    parent_status: os.stat_result,
) -> dict[str, int]:
    return {
        "device": status.st_dev,
        "inode": status.st_ino,
        "owner_uid": status.st_uid,
        "parent_device": parent_status.st_dev,
        "parent_inode": parent_status.st_ino,
    }


def _validate_reservation_identity(value: object) -> dict[str, int]:
    keys = {
        "device",
        "inode",
        "owner_uid",
        "parent_device",
        "parent_inode",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or any(type(value.get(key)) is not int or value[key] < 0 for key in keys)
        or value.get("inode") == 0
        or value.get("parent_inode") == 0
        or value.get("owner_uid") != os.getuid()
    ):
        fail("submission_admission_invalid")
    return dict(value)


def _validate_phase_certificate(
    value: object,
    *,
    timeout_seconds: int,
    allowed_states: frozenset[str],
) -> None:
    keys = {
        "converged",
        "elapsed_milliseconds",
        "explicit_conflict_fields",
        "final_mismatch_fields",
        "mismatch_fields",
        "mismatch_occurrences",
        "polls",
        "required_consecutive",
        "state",
        "timeout_seconds",
    }
    if not isinstance(value, dict) or set(value) != keys:
        fail("submission_admission_invalid")
    mismatch_fields = value.get("mismatch_fields")
    final_fields = value.get("final_mismatch_fields")
    conflicts = value.get("explicit_conflict_fields")
    occurrences = value.get("mismatch_occurrences")
    if (
        value.get("converged") is not True
        or type(value.get("polls")) is not int
        or value["polls"] < 2
        or type(value.get("elapsed_milliseconds")) is not int
        or value["elapsed_milliseconds"] < 0
        or value.get("required_consecutive") != 2
        or value.get("timeout_seconds") != timeout_seconds
        or value.get("state") not in allowed_states
        or not isinstance(mismatch_fields, list)
        or not isinstance(final_fields, list)
        or not isinstance(conflicts, list)
        or final_fields != []
        or conflicts != []
        or mismatch_fields != sorted(set(mismatch_fields))
        or any(
            not isinstance(field, str) or PHASE_FIELD_RE.fullmatch(field) is None
            for field in mismatch_fields
        )
        or not isinstance(occurrences, dict)
        or set(occurrences) != set(mismatch_fields)
        or any(
            not isinstance(field, str)
            or PHASE_FIELD_RE.fullmatch(field) is None
            or type(count) is not int
            or count < 1
            for field, count in occurrences.items()
        )
    ):
        fail("submission_admission_invalid")


def validate_submission_admission(
    authorization_path: Path,
    authorization_sha256: str,
    authorization: Mapping[str, Any],
    reservation: Path,
    job_id: str,
    job_name: str,
    expected_reservation_identity: Mapping[str, int],
) -> dict[str, Any]:
    submission = authorization.get("audit_submission")
    if (
        not isinstance(submission, dict)
        or submission.get("reservation_dir") != str(reservation)
        or submission.get("job_name") != job_name
        or not re.fullmatch(r"[1-9][0-9]{0,19}", job_id)
    ):
        fail("submission_admission_invalid")
    expected_identity = _validate_reservation_identity(expected_reservation_identity)
    parent_fd = -1
    reservation_fd = -1
    fresh_parent_fd = -1
    fresh_reservation_fd = -1

    def close_descriptors() -> None:
        nonlocal parent_fd, reservation_fd, fresh_parent_fd, fresh_reservation_fd
        for descriptor in (
            fresh_reservation_fd,
            fresh_parent_fd,
            reservation_fd,
            parent_fd,
        ):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        fresh_reservation_fd = -1
        fresh_parent_fd = -1
        reservation_fd = -1
        parent_fd = -1

    try:
        parent = reservation.parent
        if (
            not reservation.is_absolute()
            or Path(os.path.normpath(reservation)) != reservation
            or not reservation.name
            or parent.resolve(strict=True) != parent
            or parent.is_symlink()
        ):
            fail("submission_admission_invalid")
        parent_fd = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        parent_status = os.fstat(parent_fd)
        reservation_fd = os.open(
            reservation.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        status = os.fstat(reservation_fd)
        visible_status = os.stat(
            reservation.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        children = {entry.name for entry in os.scandir(reservation_fd)}
    except (OSError, RuntimeError) as error:
        close_descriptors()
        raise BootstrapError("submission_admission_invalid") from error
    expected_children = {
        "activation_permit.json",
        "held_authorization.json",
        "launch_intent.json",
        "submission_receipt.json",
    }
    if (
        not stat.S_ISDIR(status.st_mode)
        or stat.S_IMODE(status.st_mode) != 0o500
        or status.st_uid != os.getuid()
        or status.st_nlink != RESERVATION_LINK_COUNT
        or visible_status.st_nlink != RESERVATION_LINK_COUNT
        or not stat.S_ISDIR(parent_status.st_mode)
        or stat.S_IMODE(parent_status.st_mode) != 0o700
        or parent_status.st_uid != os.getuid()
        or _signature(status)[:2] != _signature(visible_status)[:2]
        or _reservation_identity(status, parent_status) != expected_identity
        or children != expected_children
    ):
        close_descriptors()
        fail("submission_admission_invalid")
    try:
        intent, intent_sha = _load_envelope(
            reservation_fd,
            "launch_intent.json",
            SUBMISSION_INTENT_TYPE,
            "launch_intent_sha256",
        )
        held, held_sha = _load_envelope(
            reservation_fd,
            "held_authorization.json",
            SUBMISSION_HELD_TYPE,
            "held_authorization_sha256",
        )
        receipt, receipt_sha = _load_envelope(
            reservation_fd,
            "submission_receipt.json",
            SUBMISSION_RECEIPT_TYPE,
            "submission_receipt_sha256",
        )
        permit, permit_sha = _load_envelope(
            reservation_fd,
            "activation_permit.json",
            SUBMISSION_PERMIT_TYPE,
            "activation_permit_sha256",
        )
    except BaseException:
        close_descriptors()
        raise
    auth_record = {"path": str(authorization_path), "sha256": authorization_sha256}
    expected_job = {"cluster": submission["cluster"], "id": job_id, "name": job_name}
    expected_wrapper_sha256 = authorization["source"]["artifacts"][
        "production_audit_wrapper"
    ]["sha256"]
    visibility = receipt.get("submission_visibility")
    if (
        set(intent)
        != {
            "artifact_type",
            "audit_authorization",
            "job_name_sha256",
            "launch_intent_sha256",
            "policy",
            "reservation_identity",
            "schema_version",
            "source_manifest_sha256",
            "state",
            "wrapper_sha256",
        }
        or set(held)
        != {
            "artifact_type",
            "audit_authorization",
            "held",
            "held_after_authorization",
            "held_authorization_sha256",
            "intent_sha256",
            "job",
            "reservation_identity",
            "schema_version",
            "state",
            "wrapper_sha256",
        }
        or set(receipt)
        != {
            "activation",
            "artifact_type",
            "audit_authorization",
            "held",
            "held_after_authorization",
            "held_before_release",
            "held_authorization",
            "intent_sha256",
            "job",
            "promotion_authorized",
            "release",
            "reservation_identity",
            "schema_version",
            "source_manifest_sha256",
            "state",
            "submission_receipt_sha256",
            "submission_visibility",
            "wrapper_sha256",
        }
        or set(permit)
        != {
            "activation_permit_sha256",
            "artifact_type",
            "audit_authorization",
            "job_id_sha256",
            "job_name_sha256",
            "reservation_identity",
            "schema_version",
            "state",
            "submission_receipt",
        }
        or intent.get("state") != "reserved"
        or held.get("state") != "held_authorized"
        or receipt.get("state") != "submitted"
        or permit.get("state") != "activated"
        or any(
            value.get("audit_authorization") != auth_record
            for value in (intent, held, receipt, permit)
        )
        or any(
            value.get("reservation_identity") != expected_identity
            for value in (intent, held, receipt, permit)
        )
        or intent.get("policy") != submission.get("policy")
        or intent.get("job_name_sha256")
        != hashlib.sha256(job_name.encode("ascii")).hexdigest()
        or intent.get("wrapper_sha256") != expected_wrapper_sha256
        or held.get("job") != expected_job
        or receipt.get("job") != expected_job
        or held.get("intent_sha256") != intent_sha
        or receipt.get("intent_sha256") != intent_sha
        or held.get("held") != receipt.get("held")
        or held.get("held_after_authorization")
        != receipt.get("held_after_authorization")
        or held.get("wrapper_sha256") != intent.get("wrapper_sha256")
        or receipt.get("wrapper_sha256") != intent.get("wrapper_sha256")
        or receipt.get("source_manifest_sha256") != intent.get("source_manifest_sha256")
        or not isinstance(intent.get("source_manifest_sha256"), str)
        or SHA256_RE.fullmatch(intent["source_manifest_sha256"]) is None
        or receipt.get("held_authorization")
        != {"path": str(reservation / "held_authorization.json"), "sha256": held_sha}
        or receipt.get("release") != {"attempts": 1, "outcome": "completed"}
        or receipt.get("promotion_authorized") is not False
        or not isinstance(visibility, dict)
        or set(visibility) != {"polls", "zero_rounds"}
        or type(visibility.get("polls")) is not int
        or visibility["polls"] < 1
        or type(visibility.get("zero_rounds")) is not int
        or visibility["zero_rounds"] < 0
        or permit.get("submission_receipt")
        != {"path": str(reservation / "submission_receipt.json"), "sha256": receipt_sha}
        or permit.get("job_id_sha256")
        != hashlib.sha256(job_id.encode("ascii")).hexdigest()
        or permit.get("job_name_sha256")
        != hashlib.sha256(job_name.encode("ascii")).hexdigest()
    ):
        close_descriptors()
        fail("submission_admission_invalid")
    try:
        _validate_phase_certificate(
            receipt.get("held"),
            timeout_seconds=HELD_TIMEOUT_SECONDS,
            allowed_states=frozenset({"PENDING"}),
        )
        _validate_phase_certificate(
            receipt.get("held_after_authorization"),
            timeout_seconds=FINAL_HELD_TIMEOUT_SECONDS,
            allowed_states=frozenset({"PENDING"}),
        )
        _validate_phase_certificate(
            receipt.get("held_before_release"),
            timeout_seconds=FINAL_HELD_TIMEOUT_SECONDS,
            allowed_states=frozenset({"PENDING"}),
        )
        _validate_phase_certificate(
            receipt.get("activation"),
            timeout_seconds=ACTIVATION_TIMEOUT_SECONDS,
            allowed_states=frozenset({"PENDING", "CONFIGURING", "RUNNING"}),
        )
    except BaseException:
        close_descriptors()
        raise
    try:
        final_parent_status = os.fstat(parent_fd)
        final_status = os.fstat(reservation_fd)
        final_visible_status = os.stat(
            reservation.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        final_children = {entry.name for entry in os.scandir(reservation_fd)}
        fresh_parent_fd = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
        )
        fresh_parent_status = os.fstat(fresh_parent_fd)
        fresh_reservation_fd = os.open(
            reservation.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=fresh_parent_fd,
        )
        fresh_status = os.fstat(fresh_reservation_fd)
    except (OSError, RuntimeError) as error:
        close_descriptors()
        raise BootstrapError("submission_admission_invalid") from error
    try:
        if (
            _signature(final_parent_status)[:2] != _signature(parent_status)[:2]
            or _signature(final_status) != _signature(status)
            or _signature(final_visible_status)[:2] != _signature(status)[:2]
            or _signature(fresh_parent_status)[:2] != _signature(parent_status)[:2]
            or _signature(fresh_status)[:2] != _signature(status)[:2]
            or final_children != expected_children
        ):
            fail("submission_admission_changed")
        return {
            "reservation": {
                "identity": expected_identity,
                "mode": "0500",
                "path": str(reservation),
            },
            "intent": {
                "path": str(reservation / "launch_intent.json"),
                "sha256": intent_sha,
            },
            "held_authorization": {
                "path": str(reservation / "held_authorization.json"),
                "sha256": held_sha,
            },
            "submission_receipt": {
                "path": str(reservation / "submission_receipt.json"),
                "sha256": receipt_sha,
            },
            "activation_permit": {
                "path": str(reservation / "activation_permit.json"),
                "sha256": permit_sha,
            },
            "job": expected_job,
        }
    finally:
        close_descriptors()


def tree_manifest_sha256(
    root: Path,
    *,
    code: str,
    expected_uid: int,
    forbid_customization: bool,
    allow_symlinks: bool = False,
    captured_files: dict[Path, str] | None = None,
) -> str:
    try:
        if root.resolve(strict=True) != root or root.is_symlink():
            fail(code)
        root_status = root.stat(follow_symlinks=False)
    except (OSError, RuntimeError) as error:
        raise BootstrapError(code) from error
    if (
        not stat.S_ISDIR(root_status.st_mode)
        or root_status.st_uid != expected_uid
        or stat.S_IMODE(root_status.st_mode) & 0o022
    ):
        fail(code)
    records: list[list[object]] = []
    pending = [(root, PurePosixPath("."))]
    while pending:
        directory, relative_root = pending.pop()
        try:
            before = directory.stat(follow_symlinks=False)
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise BootstrapError(code) from error
        for entry in entries:
            relative = (
                PurePosixPath(entry.name)
                if relative_root == PurePosixPath(".")
                else relative_root / entry.name
            )
            if len(records) >= MAX_TREE_ENTRIES:
                fail(code)
            try:
                status = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise BootstrapError(code) from error
            mode = stat.S_IMODE(status.st_mode)
            if status.st_uid != expected_uid or (
                not stat.S_ISLNK(status.st_mode) and mode & 0o022
            ):
                fail(code)
            if forbid_customization:
                if entry.name in FORBIDDEN_IMPORT_NAMES:
                    fail("runtime_customization_forbidden")
                if Path(entry.name).suffix == ".pyc":
                    fail("runtime_bytecode_forbidden")
            if stat.S_ISDIR(status.st_mode):
                records.append(
                    [
                        "directory",
                        relative.as_posix(),
                        mode,
                        status.st_uid,
                        status.st_gid,
                    ]
                )
                pending.append((Path(entry.path), relative))
            elif stat.S_ISREG(status.st_mode):
                body, digest = stable_bytes(
                    Path(entry.path),
                    code=code,
                    maximum=max(status.st_size, 1),
                    expected_mode=mode,
                    expected_uid=expected_uid,
                    allow_empty=True,
                )
                records.append(
                    [
                        "file",
                        relative.as_posix(),
                        mode,
                        status.st_uid,
                        status.st_gid,
                        len(body),
                        digest,
                    ]
                )
                if captured_files is not None:
                    captured_files[Path(entry.path).resolve(strict=True)] = digest
            elif stat.S_ISLNK(status.st_mode):
                if not allow_symlinks:
                    fail(code)
                try:
                    target = os.readlink(entry.path)
                    resolved = Path(entry.path).resolve(strict=True)
                    after = entry.stat(follow_symlinks=False)
                except (OSError, RuntimeError, ValueError) as error:
                    raise BootstrapError(code) from error
                if _signature(status) != _signature(after):
                    fail(code)
                target_body, target_digest = stable_bytes(
                    resolved,
                    code=code,
                    maximum=512 * 1024 * 1024,
                    expected_uid=expected_uid,
                    allow_empty=True,
                )
                target_status = resolved.stat(follow_symlinks=False)
                records.append(
                    [
                        "symlink",
                        relative.as_posix(),
                        target,
                        str(resolved),
                        stat.S_IMODE(target_status.st_mode),
                        target_status.st_uid,
                        target_status.st_gid,
                        len(target_body),
                        target_digest,
                    ]
                )
            else:
                fail(code)
        try:
            after = directory.stat(follow_symlinks=False)
        except OSError as error:
            raise BootstrapError(code) from error
        if _signature(before) != _signature(after):
            fail(code)
    return hashlib.sha256(
        canonical_json({"schema_version": 1, "records": sorted(records)})
    ).hexdigest()


def _git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            [
                "/usr/bin/git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.untrackedCache=false",
                "-C",
                str(root),
                *arguments,
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=GIT_ENVIRONMENT,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BootstrapError("source_checkout_invalid") from error
    if result.returncode != 0 or len(result.stdout) > 64 * 1024 * 1024:
        fail("source_checkout_invalid")
    return result.stdout


def _ignored_importables(root: Path) -> tuple[str, ...]:
    raw = _git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    paths: list[str] = []
    for entry in raw.rstrip(b"\0").split(b"\0"):
        if not entry:
            continue
        try:
            relative = entry.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise BootstrapError("source_ignored_importable_invalid") from error
        name = PurePosixPath(relative).name
        if (
            name in FORBIDDEN_IMPORT_NAMES
            or PurePosixPath(relative).suffix in IMPORTABLE_SUFFIXES
        ):
            paths.append(relative)
    return tuple(sorted(paths))


def _git_blob_sha1(body: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(body)}\0".encode("ascii"))
    digest.update(body)
    return digest.hexdigest()


def _validate_importable_git_tree(
    root: Path,
    revision: str,
    *,
    captured_files: dict[Path, str] | None = None,
) -> str:
    raw = _git(root, "ls-tree", "-r", "-z", revision)
    records: list[list[str]] = []
    for item in raw.rstrip(b"\0").split(b"\0"):
        if not item:
            continue
        try:
            header, raw_path = item.split(b"\t", 1)
            mode, object_type, object_id = header.split(b" ")
            relative = raw_path.decode("utf-8", errors="strict")
            expected_object = object_id.decode("ascii", errors="strict")
        except (UnicodeDecodeError, ValueError) as error:
            raise BootstrapError("source_import_manifest_invalid") from error
        relative_path = PurePosixPath(relative)
        if (
            relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or object_type != b"blob"
            or REVISION_RE.fullmatch(expected_object) is None
        ):
            continue
        if (
            relative_path.name not in FORBIDDEN_IMPORT_NAMES
            and relative_path.suffix not in IMPORTABLE_SUFFIXES
        ):
            continue
        if (
            relative_path.name in FORBIDDEN_IMPORT_NAMES
            or relative_path.suffix == ".pyc"
        ):
            fail("source_import_artifact_forbidden")
        if mode not in {b"100644", b"100755"}:
            fail("source_import_manifest_invalid")
        candidate = root.joinpath(*relative_path.parts)
        body, body_digest = stable_bytes(
            candidate,
            code="source_import_manifest_invalid",
            maximum=64 * 1024 * 1024,
            expected_uid=os.getuid(),
            allow_empty=True,
        )
        if _git_blob_sha1(body) != expected_object:
            fail("source_import_manifest_mismatch")
        if captured_files is not None:
            captured_files[candidate.resolve(strict=True)] = body_digest
        records.append([relative, mode.decode(), expected_object])
    if not records:
        fail("source_import_manifest_invalid")
    return hashlib.sha256(
        canonical_json({"schema_version": 1, "records": sorted(records)})
    ).hexdigest()


def _validate_checkout(source: dict[str, Any]) -> dict[Path, str]:
    root = Path(source["project_root"])
    revision = source["prime_rl_commit"]
    tree = source["prime_rl_git_tree"]
    if (
        root.resolve(strict=True) != root
        or REVISION_RE.fullmatch(revision) is None
        or REVISION_RE.fullmatch(tree) is None
        or _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() != b"HEAD"
    ):
        fail("source_checkout_invalid")
    if (
        _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        != revision
    ):
        fail("source_revision_mismatch")
    if _git(root, "rev-parse", "--verify", "HEAD^{tree}").decode().strip() != tree:
        fail("source_tree_mismatch")
    if _git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    ):
        fail("source_worktree_not_clean")
    if _ignored_importables(root):
        fail("source_ignored_importable_forbidden")
    expected_import_manifests = source.get("import_manifests")
    if not isinstance(expected_import_manifests, dict) or set(
        expected_import_manifests
    ) != {
        "prime_rl",
        "pydantic_config",
        "renderers",
        "verifiers",
    }:
        fail("source_import_manifest_invalid")
    captured_import_files: dict[Path, str] = {}
    observed_import_manifests = {
        "prime_rl": _validate_importable_git_tree(
            root,
            revision,
            captured_files=captured_import_files,
        ),
    }
    gitlinks = source.get("gitlinks")
    if not isinstance(gitlinks, dict) or set(gitlinks) != {
        "pydantic_config",
        "renderers",
        "verifiers",
    }:
        fail("source_gitlink_invalid")
    for label, relative in (
        ("verifiers", "deps/verifiers"),
        ("renderers", "deps/renderers"),
        ("pydantic_config", "deps/pydantic-config"),
    ):
        checkout = root / relative
        expected = gitlinks[label]
        record = _git(root, "ls-tree", "-z", revision, "--", relative)
        expected_record = f"160000 commit {expected}\t{relative}\0".encode()
        if record != expected_record:
            fail("source_gitlink_invalid")
        if (
            checkout.resolve(strict=True) != checkout
            or _git(checkout, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
            != expected
            or _git(
                checkout,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=none",
            )
            or _ignored_importables(checkout)
        ):
            fail("source_gitlink_checkout_invalid")
        observed_import_manifests[label] = _validate_importable_git_tree(
            checkout,
            expected,
            captured_files=captured_import_files,
        )
    if observed_import_manifests != expected_import_manifests:
        fail("source_import_manifest_mismatch")
    for record in source["artifacts"].values():
        stable_bytes(
            Path(record["path"]),
            code="source_artifact_invalid",
            maximum=64 * 1024 * 1024,
            expected_sha256=record["sha256"],
            expected_uid=os.getuid(),
        )
    # Close the last mutable interval before project source is imported.
    final_import_manifests = {
        "prime_rl": _validate_importable_git_tree(root, revision),
        **{
            label: _validate_importable_git_tree(root / relative, gitlinks[label])
            for label, relative in (
                ("verifiers", "deps/verifiers"),
                ("renderers", "deps/renderers"),
                ("pydantic_config", "deps/pydantic-config"),
            )
        },
    }
    if (
        _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        != revision
        or _git(root, "rev-parse", "--verify", "HEAD^{tree}").decode().strip() != tree
        or _git(
            root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        )
        or _ignored_importables(root)
        or final_import_manifests != expected_import_manifests
    ):
        fail("source_changed_before_exec")
    for label, relative in (
        ("verifiers", "deps/verifiers"),
        ("renderers", "deps/renderers"),
        ("pydantic_config", "deps/pydantic-config"),
    ):
        checkout = root / relative
        if (
            _git(checkout, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
            != gitlinks[label]
            or _git(
                checkout,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=none",
            )
            or _ignored_importables(checkout)
        ):
            fail("source_changed_before_exec")
    return captured_import_files


def _validate_environment(pycache_prefix: Path) -> None:
    if (
        set(os.environ) != EXPECTED_ENVIRONMENT
        or os.environ.get("HOME") != "/nonexistent"
        or os.environ.get("PATH") != "/usr/bin:/bin"
        or os.environ.get("LANG") != "C"
        or os.environ.get("LC_ALL") != "C"
        or os.environ.get("PYTHONDONTWRITEBYTECODE") != "1"
        or os.environ.get("PYTHONNOUSERSITE") != "1"
        or os.environ.get("PYTHONSAFEPATH") != "1"
        or os.environ.get("PYTHONPYCACHEPREFIX") != str(pycache_prefix)
        or any(
            name.startswith(("BASH_FUNC_", "LD_", "UV_", "GIT_")) for name in os.environ
        )
        or any(
            name in os.environ
            for name in ("BASH_ENV", "ENV", "VIRTUAL_ENV", "CONDA_PREFIX")
        )
    ):
        fail("environment_not_sanitized")
    if not (
        sys.flags.isolated
        and sys.flags.no_site
        and sys.flags.no_user_site
        and sys.flags.safe_path
        and sys.flags.dont_write_bytecode
        and "site" not in sys.modules
        and "sitecustomize" not in sys.modules
        and "usercustomize" not in sys.modules
    ):
        fail("python_isolation_invalid")


def _validate_pycache_prefix(path: Path) -> None:
    descriptor = -1
    try:
        if (
            path != PYCACHE_SINK
            or path.resolve(strict=True) != path
            or path.is_symlink()
        ):
            fail("pycache_prefix_invalid")
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        status = os.fstat(descriptor)
        visible = path.stat(follow_symlinks=False)
    except (OSError, RuntimeError) as error:
        raise BootstrapError("pycache_prefix_invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISCHR(status.st_mode)
        or stat.S_IMODE(status.st_mode) != 0o666
        or status.st_uid != 0
        or status.st_gid != 0
        or status.st_nlink != 1
        or os.major(status.st_rdev) != 1
        or os.minor(status.st_rdev) != 3
        or _signature(status) != _signature(visible)
    ):
        fail("pycache_prefix_invalid")
    sys.pycache_prefix = str(path)


def _runtime_roots(source: dict[str, Any]) -> tuple[Path, Path, Path, dict[Path, str]]:
    runtime = source["runtime"]
    python_record = runtime["python"]
    python_path = Path(python_record["path"])
    stdlib = Path(runtime["stdlib"]["path"])
    site_packages = Path(runtime["site_packages"]["path"])
    if Path(sys.executable).resolve(strict=True) != python_path:
        fail("python_runtime_invalid")
    if runtime.get("submission") != {
        "environment": "env_i_exact_allowlist",
        "sbatch_export": "NONE",
    }:
        fail("python_runtime_invalid")
    tools = runtime.get("tools")
    if not isinstance(tools, dict) or set(tools) != set(RUNTIME_TOOL_PATHS):
        fail("python_runtime_invalid")
    for label, expected_path in RUNTIME_TOOL_PATHS.items():
        record = tools.get(label)
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256"}
            or record.get("path") != expected_path
            or not isinstance(record.get("sha256"), str)
            or SHA256_RE.fullmatch(record["sha256"]) is None
        ):
            fail("python_runtime_invalid")
        stable_bytes(
            Path(expected_path),
            code="python_runtime_invalid",
            maximum=64 * 1024 * 1024,
            expected_sha256=record["sha256"],
            expected_mode=0o755,
            expected_uid=0,
        )
    stable_bytes(
        python_path,
        code="python_runtime_invalid",
        maximum=64 * 1024 * 1024,
        expected_sha256=python_record["sha256"],
        expected_mode=0o755,
        expected_uid=0,
    )
    if Path(sysconfig.get_path("stdlib")).resolve(strict=True) != stdlib:
        fail("python_runtime_invalid")
    site_files: dict[Path, str] = {}
    if (
        tree_manifest_sha256(
            stdlib,
            code="python_stdlib_manifest_invalid",
            expected_uid=0,
            # `-S` prevents the distribution-provided, root-owned
            # sitecustomize module from being imported at startup.  Its bytes
            # remain covered by the full stdlib manifest, and the origin audit
            # below rejects it if trusted project code imports it explicitly.
            forbid_customization=False,
            # The distro stdlib contains a small root-owned symlink closure.
            # Every target is captured by canonical path, metadata, and hash.
            allow_symlinks=True,
        )
        != runtime["stdlib"]["tree_sha256"]
        or tree_manifest_sha256(
            site_packages,
            code="python_site_manifest_invalid",
            expected_uid=os.getuid(),
            forbid_customization=True,
            captured_files=site_files,
        )
        != runtime["site_packages"]["tree_sha256"]
    ):
        fail("python_runtime_manifest_mismatch")
    return python_path, stdlib, site_packages, site_files


class _VerifiedSourceLoader(importlib.abc.Loader):
    def __init__(
        self,
        path: Path,
        expected_sha256: str,
        verify_origin: Callable[[], None] | None = None,
    ) -> None:
        self.path = path
        self.expected_sha256 = expected_sha256
        self.verify_origin = verify_origin

    def create_module(self, _spec: object) -> None:
        return None

    def exec_module(self, module: object) -> None:
        if self.verify_origin is not None:
            self.verify_origin()
        body, _digest = stable_bytes(
            self.path,
            code="verified_import_changed",
            maximum=64 * 1024 * 1024,
            expected_sha256=self.expected_sha256,
            expected_uid=os.getuid(),
            allow_empty=True,
        )
        try:
            code = compile(body, str(self.path), "exec", dont_inherit=True)
            exec(code, module.__dict__)  # type: ignore[attr-defined]
        except BootstrapError:
            raise
        except BaseException:
            fail("verified_import_execution_failed")
        if self.verify_origin is not None:
            self.verify_origin()
        stable_bytes(
            self.path,
            code="verified_import_changed",
            maximum=64 * 1024 * 1024,
            expected_sha256=self.expected_sha256,
            expected_uid=os.getuid(),
            allow_empty=True,
        )


class _VerifiedExtensionLoader(importlib.abc.Loader):
    def __init__(
        self,
        fullname: str,
        path: Path,
        expected_sha256: str,
        descriptor: int,
        delegate: importlib.abc.Loader,
        verify_origin: Callable[[], None] | None = None,
    ) -> None:
        self.fullname = fullname
        self.path = path
        self.expected_sha256 = expected_sha256
        self.descriptor = descriptor
        self.delegate = delegate
        self.verify_origin = verify_origin

    def _verify(self) -> None:
        try:
            status = os.fstat(self.descriptor)
            seals = fcntl.fcntl(self.descriptor, fcntl.F_GET_SEALS)
        except OSError as error:
            raise BootstrapError("verified_extension_changed") from error
        required = (
            fcntl.F_SEAL_SEAL
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
        )
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 0
            or seals != required
            or _descriptor_sha256(self.descriptor, status.st_size)
            != self.expected_sha256
        ):
            fail("verified_extension_changed")

    def create_module(self, spec: object) -> object | None:
        if self.verify_origin is not None:
            self.verify_origin()
        self._verify()
        create = getattr(self.delegate, "create_module", None)
        if not callable(create):
            return None
        try:
            module = create(spec)
        except BaseException:
            fail("verified_extension_load_failed")
        self._verify()
        if self.verify_origin is not None:
            self.verify_origin()
        return module

    def exec_module(self, module: object) -> None:
        if self.verify_origin is not None:
            self.verify_origin()
        self._verify()
        execute = getattr(self.delegate, "exec_module", None)
        if not callable(execute):
            fail("verified_extension_load_failed")
        try:
            execute(module)
        except BaseException:
            fail("verified_extension_load_failed")
        self._verify()
        if self.verify_origin is not None:
            self.verify_origin()


class _VerifiedImportFinder(importlib.abc.MetaPathFinder):
    def __init__(
        self,
        protected: tuple[Path, ...],
        files: dict[Path, str],
        original_meta_path: tuple[object, ...] = (),
        expected_sys_path: tuple[str, ...] = (),
    ) -> None:
        self.protected = protected
        self.files = files
        self.original_meta_path = original_meta_path
        self.expected_sys_path = expected_sys_path
        self.sealed_extensions: dict[str, tuple[int, Path, str]] = {}
        self.protected_descriptors: dict[Path, tuple[int, tuple[int, ...]]] = {}
        try:
            for root in protected:
                if (
                    not root.is_absolute()
                    or Path(os.path.normpath(root)) != root
                    or root.resolve(strict=True) != root
                    or root.is_symlink()
                ):
                    fail("verified_import_origin_invalid")
                descriptor = os.open(
                    root,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                )
                status = os.fstat(descriptor)
                if not stat.S_ISDIR(status.st_mode):
                    os.close(descriptor)
                    fail("verified_import_origin_invalid")
                self.protected_descriptors[root] = (
                    descriptor,
                    _signature(status),
                )
        except BaseException:
            self.close()
            raise
        self.manifest_directories: set[Path] = set()
        for candidate in files:
            for root in protected:
                if candidate == root or candidate.is_relative_to(root):
                    parent = candidate.parent
                    while parent == root or parent.is_relative_to(root):
                        self.manifest_directories.add(parent)
                        if parent == root:
                            break
                        parent = parent.parent
                    break

    def close(self) -> None:
        for descriptor, _path, _sha256 in self.sealed_extensions.values():
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.sealed_extensions.clear()
        for descriptor, _identity in self.protected_descriptors.values():
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.protected_descriptors.clear()

    def _revalidate_protected_roots(self) -> None:
        for root, (descriptor, identity) in self.protected_descriptors.items():
            fresh = -1
            try:
                if root.resolve(strict=True) != root or root.is_symlink():
                    fail("verified_import_origin_invalid")
                held_status = os.fstat(descriptor)
                fresh = os.open(
                    root,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                )
                fresh_status = os.fstat(fresh)
            except BootstrapError:
                raise
            except (OSError, RuntimeError) as error:
                raise BootstrapError("verified_import_origin_invalid") from error
            finally:
                if fresh >= 0:
                    os.close(fresh)
            if (
                not stat.S_ISDIR(held_status.st_mode)
                or not stat.S_ISDIR(fresh_status.st_mode)
                or _signature(held_status) != identity
                or _signature(fresh_status) != identity
            ):
                fail("verified_import_origin_invalid")

    def _protected_path(self, raw: str | os.PathLike[str]) -> Path | None:
        path = Path(raw)
        normalized = Path(os.path.normpath(path))
        lexical_roots = tuple(
            root for root in self.protected if path == root or path.is_relative_to(root)
        )
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise BootstrapError("verified_import_origin_invalid") from error
        resolved_roots = tuple(
            root
            for root in self.protected
            if resolved == root or resolved.is_relative_to(root)
        )
        if lexical_roots or resolved_roots:
            self._revalidate_protected_roots()
            if (
                not path.is_absolute()
                or normalized != path
                or resolved != path
                or lexical_roots != resolved_roots
            ):
                fail("verified_import_origin_invalid")
            return path
        return None

    def _verify_manifest_file(self, path: Path, expected_sha256: str) -> None:
        resolved = self._protected_path(path)
        if resolved is None or self.files.get(resolved) != expected_sha256:
            fail("unmanifested_import_forbidden")

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> object | None:
        del target
        self._revalidate_protected_roots()
        try:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        except (ImportError, OSError, ValueError) as error:
            raise BootstrapError("verified_import_resolution_failed") from error
        self._revalidate_protected_roots()
        if spec is None:
            return spec
        locations = spec.submodule_search_locations
        if locations is not None:
            for location in locations:
                resolved_location = self._protected_path(location)
                if (
                    resolved_location is not None
                    and resolved_location not in self.manifest_directories
                ):
                    fail("unmanifested_import_forbidden")
        if spec.origin in {None, "built-in", "frozen"}:
            return spec
        resolved = self._protected_path(spec.origin)
        if resolved is None:
            return spec
        expected_sha256 = self.files.get(resolved)
        if expected_sha256 is None or resolved.suffix == ".pyc":
            fail("unmanifested_import_forbidden")
        if resolved.suffix == ".py":
            spec.loader = _VerifiedSourceLoader(
                resolved,
                expected_sha256,
                lambda: self._verify_manifest_file(resolved, expected_sha256),
            )
            spec.cached = None
            return spec
        if any(
            str(resolved).endswith(suffix)
            for suffix in importlib.machinery.EXTENSION_SUFFIXES
        ):
            body, _digest = stable_bytes(
                resolved,
                code="verified_extension_changed",
                maximum=512 * 1024 * 1024,
                expected_sha256=expected_sha256,
                expected_uid=os.getuid(),
            )
            descriptor = _sealed_memfd(
                body, f"trace-extension-{fullname.rsplit('.', 1)[-1]}"
            )
            sealed_path = f"/proc/self/fd/{descriptor}"
            delegate = importlib.machinery.ExtensionFileLoader(fullname, sealed_path)
            spec.loader = _VerifiedExtensionLoader(
                fullname,
                resolved,
                expected_sha256,
                descriptor,
                delegate,
                lambda: self._verify_manifest_file(resolved, expected_sha256),
            )
            spec.origin = sealed_path
            spec.cached = None
            self.sealed_extensions[sealed_path] = (
                descriptor,
                resolved,
                expected_sha256,
            )
            return spec
        fail("unmanifested_import_forbidden")


def _install_import_guard(
    project: Path,
    site_packages: Path,
    verified_files: dict[Path, str],
) -> tuple[tuple[Path, ...], _VerifiedImportFinder]:
    protected = (
        project / "user/tianhaowu/terminal_bench_vmvm",
        project / "environments/vmvm_tb_v2",
        project / "deps/verifiers",
        project / "deps/renderers",
        project / "deps/pydantic-config/src",
        site_packages,
    )
    collisions = {
        "audit_traces",
        "certify_trace_smoke",
        "deployment_endpoint",
        "deployment_proxy_policy",
        "eval_run_identity",
        "guard_success_receipt",
        "inference_route_generation",
        "mobius_launch_certificate",
        "openai",
        "pydantic",
        "pydantic_config",
        "renderers",
        "sitecustomize",
        "tomli_w",
        "usercustomize",
        "verifiers",
        "vmvm_tb_v2",
        "yaml",
    }
    if collisions.intersection(sys.modules):
        fail("preexisting_module_collision")
    expected_meta_path = {
        importlib.machinery.BuiltinImporter,
        importlib.machinery.FrozenImporter,
        importlib.machinery.PathFinder,
    }
    if set(sys.meta_path) != expected_meta_path or len(sys.meta_path) != len(
        expected_meta_path
    ):
        fail("preexisting_import_hook_forbidden")
    original = tuple(sys.path)
    if not original or any(not Path(item).is_absolute() for item in original if item):
        fail("python_import_path_invalid")
    sys.path[:] = [str(path) for path in protected] + list(original)
    finder = _VerifiedImportFinder(
        protected,
        verified_files,
        tuple(sys.meta_path),
        tuple(sys.path),
    )
    sys.meta_path.insert(0, finder)

    def audit(event: str, arguments: tuple[object, ...]) -> None:
        if event != "open" or not arguments:
            return
        raw = arguments[0]
        if not isinstance(raw, (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(raw))
        if not path.is_absolute():
            return
        normalized = Path(os.path.normpath(path))
        lexical_roots = tuple(
            root for root in protected if path == root or path.is_relative_to(root)
        )
        if not lexical_roots:
            return
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise BootstrapError("verified_import_origin_invalid") from error
        resolved_roots = tuple(
            root
            for root in protected
            if resolved == root or resolved.is_relative_to(root)
        )
        if normalized != path or resolved != path or resolved_roots != lexical_roots:
            fail("verified_import_origin_invalid")
        if normalized.suffix == ".pyc" or normalized.name in FORBIDDEN_IMPORT_NAMES:
            fail("forbidden_import_artifact_open")

    sys.addaudithook(audit)
    return protected, finder


def _validate_import_origins(
    protected: tuple[Path, ...],
    stdlib: Path,
    finder: _VerifiedImportFinder,
) -> None:
    if (
        tuple(sys.meta_path) != (finder, *finder.original_meta_path)
        or tuple(sys.path) != finder.expected_sys_path
    ):
        fail("verified_import_guard_changed")
    finder._revalidate_protected_roots()
    allowed = (*protected, stdlib)
    for module in tuple(sys.modules.values()):
        origin = getattr(module, "__file__", None)
        if not isinstance(origin, str):
            continue
        sealed = finder.sealed_extensions.get(origin)
        if sealed is not None:
            descriptor, canonical_path, expected_sha256 = sealed
            finder._verify_manifest_file(canonical_path, expected_sha256)
            status = os.fstat(descriptor)
            if _descriptor_sha256(descriptor, status.st_size) != expected_sha256:
                fail("verified_extension_changed")
            continue
        path = Path(origin)
        if not path.is_absolute():
            fail("python_import_origin_invalid")
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise BootstrapError("python_import_origin_invalid") from error
        if not any(
            resolved == root or resolved.is_relative_to(root) for root in allowed
        ):
            fail("python_import_origin_invalid")
        if (
            any(resolved == root or resolved.is_relative_to(root) for root in protected)
            and resolved not in finder.files
        ):
            fail("unmanifested_import_forbidden")
        if resolved.suffix == ".pyc" or resolved.name in FORBIDDEN_IMPORT_NAMES:
            fail("forbidden_import_artifact_open")


def _controller_arguments(
    authorization_path: Path, authorization_sha256: str, value: dict[str, Any]
) -> list[str]:
    run = value["run"]
    scheduler = value["scheduler"]
    inputs = value["inputs"]
    return [
        str(Path(value["source"]["artifacts"]["production_certificate"]["path"])),
        str(Path(run["path"])),
        "--audit-authorization",
        str(authorization_path),
        "--audit-authorization-sha256",
        authorization_sha256,
        "--slurm-cluster",
        scheduler["cluster"],
        "--expected-task-file",
        inputs["task_file"]["path"],
        "--expected-task-file-sha256",
        inputs["task_file"]["sha256"],
        "--expected-production-config",
        inputs["production_config"]["path"],
        "--expected-production-config-sha256",
        inputs["production_config"]["sha256"],
        "--expected-launch-certificate",
        inputs["launch_certificate"]["path"],
        "--expected-launch-certificate-sha256",
        inputs["launch_certificate"]["sha256"],
        "--expected-oracle-receipt",
        inputs["oracle_receipt"]["path"],
        "--expected-oracle-receipt-sha256",
        inputs["oracle_receipt"]["sha256"],
        "--expected-traces",
        str(inputs["task_file"]["count"]),
    ]


def run(
    authorization_path: Path,
    authorization_sha256: str,
    controller_fd: int,
    controller_sha256: str,
    pycache_prefix: Path,
    reservation: Path,
    audit_job_id: str,
    audit_job_name: str,
    expected_reservation_identity: Mapping[str, int],
) -> int:
    authorization = load_authorization(authorization_path, authorization_sha256)
    submission_attestation = validate_submission_admission(
        authorization_path,
        authorization_sha256,
        authorization,
        reservation,
        audit_job_id,
        audit_job_name,
        expected_reservation_identity,
    )
    source = authorization.get("source")
    if not isinstance(source, dict):
        fail("authorization_source_invalid")
    _validate_environment(pycache_prefix)
    _validate_pycache_prefix(pycache_prefix)
    _python_path, stdlib, site_packages, site_files = _runtime_roots(source)
    source_files = _validate_checkout(source)
    project = Path(source["project_root"])
    protected, finder = _install_import_guard(
        project,
        site_packages,
        {**site_files, **source_files},
    )

    controller_path = Path(source["artifacts"]["production_certificate"]["path"])
    try:
        before = os.fstat(controller_fd)
        controller_source = b""
        offset = 0
        while offset < before.st_size:
            block = os.pread(
                controller_fd, min(1 << 20, before.st_size - offset), offset
            )
            if not block:
                fail("controller_source_invalid")
            controller_source += block
            offset += len(block)
        after = os.fstat(controller_fd)
    except OSError as error:
        raise BootstrapError("controller_source_invalid") from error
    expected_controller = source["artifacts"]["production_certificate"]["sha256"]
    canonical_source, canonical_sha256 = stable_bytes(
        controller_path,
        code="controller_source_invalid",
        maximum=64 * 1024 * 1024,
        expected_sha256=expected_controller,
        expected_uid=os.getuid(),
    )
    if (
        _signature(before) != _signature(after)
        or controller_sha256 != expected_controller
        or hashlib.sha256(controller_source).hexdigest() != expected_controller
        or canonical_sha256 != expected_controller
        or canonical_source != controller_source
    ):
        fail("controller_source_invalid")

    revalidation_calls = 0
    submission_revalidation_calls = 0

    def revalidate() -> dict[str, Any]:
        nonlocal revalidation_calls
        revalidation_calls += 1
        _validate_pycache_prefix(pycache_prefix)
        _runtime_roots(source)
        _validate_checkout(source)
        _validate_import_origins(protected, stdlib, finder)
        return source

    def revalidate_submission() -> dict[str, Any]:
        nonlocal submission_revalidation_calls
        submission_revalidation_calls += 1
        observed = validate_submission_admission(
            authorization_path,
            authorization_sha256,
            authorization,
            reservation,
            audit_job_id,
            audit_job_name,
            expected_reservation_identity,
        )
        if observed != submission_attestation:
            fail("submission_admission_changed")
        return observed

    namespace = {
        "__builtins__": __builtins__,
        "__file__": str(controller_path),
        "__name__": "__main__",
        "__package__": None,
        "__production_trace_runtime_revalidator__": revalidate,
        "__production_trace_submission_attestation__": submission_attestation,
        "__production_trace_submission_revalidator__": revalidate_submission,
    }
    old_argv = sys.argv
    sys.argv = _controller_arguments(
        authorization_path, authorization_sha256, authorization
    )
    try:
        exec(compile(controller_source, str(controller_path), "exec"), namespace)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
    finally:
        sys.argv = old_argv
        finder.close()
    if code == 0 and revalidation_calls != 1:
        fail("controller_revalidation_missing")
    if code == 0 and submission_revalidation_calls != 1:
        fail("submission_revalidation_missing")
    return code


def main() -> int:
    if len(sys.argv) != 13:
        fail("arguments_invalid")
    authorization_path = Path(sys.argv[1])
    authorization_sha256 = sys.argv[2]
    try:
        controller_fd = int(sys.argv[3])
    except ValueError as error:
        raise BootstrapError("arguments_invalid") from error
    controller_sha256 = sys.argv[4]
    pycache_prefix = Path(sys.argv[5])
    reservation = Path(sys.argv[6])
    audit_job_id = sys.argv[7]
    audit_job_name = sys.argv[8]
    raw_identity = sys.argv[9:13]
    if (
        controller_fd < 3
        or SHA256_RE.fullmatch(controller_sha256) is None
        or any(
            re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", item) is None
            for item in raw_identity
        )
    ):
        fail("arguments_invalid")
    expected_reservation_identity = {
        "device": int(raw_identity[0]),
        "inode": int(raw_identity[1]),
        "owner_uid": os.getuid(),
        "parent_device": int(raw_identity[2]),
        "parent_inode": int(raw_identity[3]),
    }
    _validate_reservation_identity(expected_reservation_identity)
    return run(
        authorization_path,
        authorization_sha256,
        controller_fd,
        controller_sha256,
        pycache_prefix,
        reservation,
        audit_job_id,
        audit_job_name,
        expected_reservation_identity,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as error:
        print(
            canonical_json({"code": str(error), "status": "error"}).decode(),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except BaseException:
        print('{"code":"bootstrap_failed","status":"error"}', file=sys.stderr)
        raise SystemExit(2) from None
