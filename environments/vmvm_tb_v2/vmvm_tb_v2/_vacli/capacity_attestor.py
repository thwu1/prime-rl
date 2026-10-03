"""Emit one signed, run-bound VMVM capacity receipt from a live runtime."""

from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

REQUEST_KIND = "kimi-tb4-vmvm-capacity-request"
RECEIPT_KIND = "kimi-tb4-large-provider-capacity"
MEASUREMENT_METHOD = "in-runtime-cgroup-and-statvfs-v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
NONCE_RE = re.compile(r"[0-9a-f]{32}\Z")
MAX_BYTES = 4 * 1024 * 1024
VALIDITY = timedelta(days=8)
VALIDITY_SECONDS = int(VALIDITY.total_seconds())
PINNED_PUBLIC_KEY_SHA256 = "c5c6b7d6476b78bffe56666ca353ad71b9f3a11cd9a8219cabb5a81c43f95857"
GIB = 1024**3
MINIMUM_CAPACITY = {
    "actual_cpu_count": 32,
    "outer_memory_bytes": 36 * GIB,
    "disk_available_bytes": 105 * GIB,
}
COMMIT_SUFFIX = ".complete.json"
_SIGNING_KEY_LOCK = threading.Lock()
_SIGNING_KEY_PATH: str | None = None


class CapacityAttestationError(ValueError):
    """Capacity evidence could not be emitted without weakening its binding."""


def consume_capacity_signing_key() -> None:
    """Remove the host-only key path before any lease/container subprocess starts."""

    global _SIGNING_KEY_PATH
    with _SIGNING_KEY_LOCK:
        observed = os.environ.pop("VMVM_CAPACITY_PRIVATE_KEY", "")
        if _SIGNING_KEY_PATH is None:
            if not observed:
                raise CapacityAttestationError("capacity_binding_incomplete")
            _SIGNING_KEY_PATH = observed
        elif observed and observed != _SIGNING_KEY_PATH:
            raise CapacityAttestationError("capacity_binding_changed")


def _canonical(value: object) -> bytes:
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
        raise CapacityAttestationError("capacity_json_invalid") from error


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _identity(value: os.stat_result) -> tuple[int, ...]:
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


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_uid, stat.S_IMODE(value.st_mode)


def _owned_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
    )


def _absolute(path: Path) -> Path:
    if not path.is_absolute():
        raise CapacityAttestationError("capacity_path_invalid")
    absolute = Path(os.path.abspath(os.fspath(path)))
    if absolute != path:
        raise CapacityAttestationError("capacity_path_invalid")
    return absolute


def _open_private_directory(path: Path) -> tuple[int, tuple[int, int, int, int]]:
    absolute = _absolute(path)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open("/", flags)
    try:
        for component in absolute.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        visible = absolute.lstat()
        expected = _directory_identity(metadata)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or _directory_identity(visible) != expected
            or absolute.resolve(strict=True) != absolute
        ):
            raise CapacityAttestationError("capacity_private_parent_invalid")
    except OSError as error:
        os.close(descriptor)
        raise CapacityAttestationError("capacity_private_parent_invalid") from error
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, expected


def _public_bytes(path: Path) -> bytes:
    absolute = _absolute(path)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    directory_flags = flags | os.O_DIRECTORY
    parent = os.open("/", directory_flags)
    try:
        for component in absolute.parts[1:-1]:
            child = os.open(component, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(absolute.name, flags, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES or stat.S_IMODE(before.st_mode) & 0o022:
                raise CapacityAttestationError("capacity_public_key_invalid")
            chunks = bytearray()
            while chunk := os.read(descriptor, min(1 << 20, MAX_BYTES + 1 - len(chunks))):
                chunks.extend(chunk)
                if len(chunks) > MAX_BYTES:
                    raise CapacityAttestationError("capacity_public_key_invalid")
            after = os.fstat(descriptor)
            visible = os.stat(absolute.name, dir_fd=parent, follow_symlinks=False)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise CapacityAttestationError("capacity_public_key_invalid") from error
    finally:
        os.close(parent)
    if _identity(before) != _identity(after) or _identity(after) != _identity(visible):
        raise CapacityAttestationError("capacity_public_key_changed")
    return bytes(chunks)


def _validate_private_directory(
    path: Path,
    descriptor: int,
    expected: tuple[int, int, int, int],
) -> None:
    held = os.fstat(descriptor)
    visible = path.lstat()
    if (
        _directory_identity(held) != expected
        or _directory_identity(visible) != expected
        or path.resolve(strict=True) != path
    ):
        raise CapacityAttestationError("capacity_private_parent_changed")


def _read_private_at(parent: int, name: str) -> bytes:
    if not name or "/" in name or name in {".", ".."}:
        raise CapacityAttestationError("capacity_private_input_invalid")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except OSError as error:
        raise CapacityAttestationError("capacity_private_input_invalid") from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size > MAX_BYTES
        ):
            raise CapacityAttestationError("capacity_private_input_invalid")
        chunks = bytearray()
        while chunk := os.read(descriptor, min(1 << 20, MAX_BYTES + 1 - len(chunks))):
            chunks.extend(chunk)
            if len(chunks) > MAX_BYTES:
                raise CapacityAttestationError("capacity_private_input_invalid")
        after = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after) or _identity(after) != _identity(visible):
        raise CapacityAttestationError("capacity_private_input_changed")
    return bytes(chunks)


def _private_bytes(path: Path) -> bytes:
    absolute = _absolute(path)
    parent, parent_identity = _open_private_directory(absolute.parent)
    try:
        body = _read_private_at(parent, absolute.name)
        _validate_private_directory(absolute.parent, parent, parent_identity)
        return body
    finally:
        os.close(parent)


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CapacityAttestationError("capacity_json_invalid") from error
    if not isinstance(value, dict):
        raise CapacityAttestationError("capacity_json_invalid")
    return value


def prepare_request(
    *,
    identity: Mapping[str, Any],
    eval_run_identity_sha256: str,
    invocation_identity_sha256: str,
    manifest_sha256: str,
    selector_sha256: str,
    public_key: Path,
    output: Path,
) -> dict[str, Any]:
    source = identity.get("source")
    execution = identity.get("execution")
    environment = execution.get("vmvm_environment") if isinstance(execution, dict) else None
    runtime = execution.get("runtime") if isinstance(execution, dict) else None
    if (
        not isinstance(source, dict)
        or not isinstance(environment, dict)
        or not isinstance(runtime, dict)
        or runtime.get("type") != "vmvm"
        or any(
            SHA256_RE.fullmatch(str(value or "")) is None
            for value in (eval_run_identity_sha256, invocation_identity_sha256, manifest_sha256, selector_sha256)
        )
    ):
        raise CapacityAttestationError("capacity_request_invalid")
    try:
        public_body = _public_bytes(public_key)
        loaded_public_key = serialization.load_pem_public_key(public_body)
    except (OSError, ValueError) as error:
        raise CapacityAttestationError("capacity_public_key_invalid") from error
    if not isinstance(loaded_public_key, Ed25519PublicKey):
        raise CapacityAttestationError("capacity_public_key_invalid")
    if _sha256(public_body) != PINNED_PUBLIC_KEY_SHA256:
        raise CapacityAttestationError("capacity_public_key_untrusted")
    provider_source = {
        key: source.get(key)
        for key in (
            "prime_rl_commit",
            "verifiers_commit",
            "renderers_commit",
            "vmvm_tb_v2_sha256",
        )
    }
    request = {
        "schema_version": 1,
        "kind": REQUEST_KIND,
        "provider": "vmvm",
        "environment_identity": {
            "provider": "vmvm",
            "runtime": runtime,
            "environment": environment,
            "provider_source": provider_source,
        },
        "eval_run_identity_sha256": eval_run_identity_sha256,
        "invocation_identity_sha256": invocation_identity_sha256,
        "manifest_sha256": manifest_sha256,
        "selector_sha256": selector_sha256,
        "resource_multiplier": 2,
        "measurement_method": MEASUREMENT_METHOD,
        "public_key_sha256": _sha256(public_body),
    }
    _write_once(output, _canonical(request))
    return request


def _write_once(path: Path, body: bytes) -> None:
    absolute = _absolute(path)
    parent, parent_identity = _open_private_directory(absolute.parent)
    try:
        _write_once_at(parent, absolute.parent, parent_identity, absolute.name, body)
    finally:
        os.close(parent)


def _rename_noreplace(parent: int, source: str, destination: str) -> None:
    renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
    if renameat2 is None:
        raise CapacityAttestationError("capacity_noreplace_unavailable")
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    if renameat2(parent, os.fsencode(source), parent, os.fsencode(destination), 1) != 0:
        number = ctypes.get_errno()
        if number == errno.EEXIST:
            raise CapacityAttestationError("capacity_output_exists")
        if number in {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP}:
            raise CapacityAttestationError("capacity_noreplace_unsupported")
        raise CapacityAttestationError("capacity_output_publish_failed") from OSError(
            number,
            os.strerror(number),
        )


def _publish_direct_noreplace_at(parent: int, name: str, body: bytes) -> None:
    """Portable exclusive publication; exact-content validation is the commit test."""

    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=parent)
    except FileExistsError as error:
        raise CapacityAttestationError("capacity_output_exists") from error
    try:
        created = os.fstat(descriptor)
        if (
            not stat.S_ISREG(created.st_mode)
            or created.st_uid != os.getuid()
            or stat.S_IMODE(created.st_mode) != 0o600
            or created.st_nlink != 1
        ):
            raise CapacityAttestationError("capacity_output_staging_invalid")
        view = memoryview(body)
        while view:
            count = os.write(descriptor, view)
            if count < 1:
                raise CapacityAttestationError("capacity_output_write_failed")
            view = view[count:]
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        observed = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            observed.extend(chunk)
        held = os.fstat(descriptor)
        visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if bytes(observed) != body or _identity(held) != _identity(visible) or held.st_size != len(body):
            raise CapacityAttestationError("capacity_output_changed")
    finally:
        os.close(descriptor)


def _commit_body(name: str, body: bytes) -> bytes:
    return _canonical(
        {
            "schema_version": 1,
            "kind": "private-file-complete",
            "state": "complete",
            "file": {"name": name, "bytes": len(body), "sha256": _sha256(body)},
        }
    )


def _read_committed_at(parent: int, name: str) -> bytes:
    body = _read_private_at(parent, name)
    marker = _read_private_at(parent, f".{name}{COMMIT_SUFFIX}")
    if marker != _commit_body(name, body):
        raise CapacityAttestationError("capacity_commit_invalid")
    return body


def _write_once_at(
    parent: int,
    parent_path: Path,
    parent_identity: tuple[int, int, int, int],
    name: str,
    body: bytes,
) -> None:
    if not name or "/" in name or name in {".", ".."}:
        raise CapacityAttestationError("capacity_output_path_invalid")
    temporary = f".{name}.stage-{secrets.token_hex(8)}"
    marker_name = f".{name}{COMMIT_SUFFIX}"
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    marker_started = False
    try:
        target_exists = False
        marker_exists = False
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            target_exists = True
        try:
            os.stat(marker_name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            marker_exists = True
        if target_exists or marker_exists:
            if target_exists and marker_exists and _read_committed_at(parent, name) == body:
                _validate_private_directory(parent_path, parent, parent_identity)
                return
            raise CapacityAttestationError("capacity_output_exists")
        descriptor = os.open(temporary, flags, 0o600, dir_fd=parent)
        created = os.fstat(descriptor)
        if (
            not stat.S_ISREG(created.st_mode)
            or created.st_uid != os.getuid()
            or stat.S_IMODE(created.st_mode) != 0o600
            or created.st_nlink != 1
        ):
            raise CapacityAttestationError("capacity_output_staging_invalid")
        os.fchmod(descriptor, 0o600)
        view = memoryview(body)
        while view:
            count = os.write(descriptor, view)
            if count < 1:
                raise CapacityAttestationError("capacity_output_write_failed")
            view = view[count:]
        os.fsync(descriptor)
        written = os.fstat(descriptor)
        if _owned_identity(written) != (*_owned_identity(created)[:-1], len(body)):
            raise CapacityAttestationError("capacity_output_staging_changed")
        os.lseek(descriptor, 0, os.SEEK_SET)
        observed = bytearray()
        while chunk := os.read(descriptor, 1 << 20):
            observed.extend(chunk)
        visible_stage = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
        if bytes(observed) != body or _identity(visible_stage) != _identity(written):
            raise CapacityAttestationError("capacity_output_staging_changed")
        _validate_private_directory(parent_path, parent, parent_identity)
        os.fsync(parent)
        try:
            _rename_noreplace(parent, temporary, name)
        except CapacityAttestationError as error:
            if str(error) != "capacity_noreplace_unsupported":
                raise
            _publish_direct_noreplace_at(parent, name, body)
        else:
            visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
            held = os.fstat(descriptor)
            if (
                _identity(visible) != _identity(held)
                or _owned_identity(held) != _owned_identity(written)
                or held.st_size != len(body)
            ):
                raise CapacityAttestationError("capacity_output_changed")
            os.lseek(descriptor, 0, os.SEEK_SET)
            observed = bytearray()
            while chunk := os.read(descriptor, 1 << 20):
                observed.extend(chunk)
            if bytes(observed) != body:
                raise CapacityAttestationError("capacity_output_changed")
        if _read_private_at(parent, name) != body:
            raise CapacityAttestationError("capacity_output_changed")
        marker_started = True
        _publish_direct_noreplace_at(parent, marker_name, _commit_body(name, body))
        if _read_committed_at(parent, name) != body:
            raise CapacityAttestationError("capacity_commit_invalid")
        os.fsync(parent)
        _validate_private_directory(parent_path, parent, parent_identity)
    except BaseException as error:
        if marker_started:
            raise CapacityAttestationError("capacity_publication_indeterminate") from error
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CapacityAttestationError("capacity_receipt_invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CapacityAttestationError("capacity_receipt_invalid") from error
    if parsed.tzinfo != timezone.utc:
        raise CapacityAttestationError("capacity_receipt_invalid")
    return parsed


def _validate_existing_receipt(
    body: bytes,
    request: Mapping[str, Any],
    public_key: Ed25519PublicKey,
) -> None:
    envelope = _json_object(body)
    if _canonical(envelope) != body or set(envelope) != {
        "schema_version",
        "kind",
        "algorithm",
        "key_sha256",
        "payload",
        "signature",
    }:
        raise CapacityAttestationError("capacity_receipt_invalid")
    payload = envelope.get("payload")
    signature = envelope.get("signature")
    if (
        envelope.get("schema_version") != 2
        or envelope.get("kind") != RECEIPT_KIND
        or envelope.get("algorithm") != "ed25519"
        or envelope.get("key_sha256") != request.get("public_key_sha256")
        or not isinstance(payload, dict)
        or not isinstance(signature, str)
    ):
        raise CapacityAttestationError("capacity_receipt_invalid")
    expected_static = {
        "schema_version": 2,
        "kind": RECEIPT_KIND,
        "state": "passed",
        "provider": request.get("provider"),
        "environment_identity": request.get("environment_identity"),
        "eval_run_identity_sha256": request.get("eval_run_identity_sha256"),
        "invocation_identity_sha256": request.get("invocation_identity_sha256"),
        "manifest_sha256": request.get("manifest_sha256"),
        "selector_sha256": request.get("selector_sha256"),
        "resource_multiplier": request.get("resource_multiplier"),
        "measurement_method": request.get("measurement_method"),
    }
    dynamic = {
        "issued_at",
        "expires_at",
        "valid_for_seconds",
        "nonce",
        "runtime_instance_nonce",
        "measured_capacity",
    }
    measured = payload.get("measured_capacity")
    issued = _parse_utc(payload.get("issued_at"))
    expires = _parse_utc(payload.get("expires_at"))
    if (
        set(payload) != {*expected_static, *dynamic}
        or any(payload.get(key) != value for key, value in expected_static.items())
        or payload.get("valid_for_seconds") != VALIDITY_SECONDS
        or expires - issued != VALIDITY
        or NONCE_RE.fullmatch(str(payload.get("nonce", ""))) is None
        or NONCE_RE.fullmatch(str(payload.get("runtime_instance_nonce", ""))) is None
        or not isinstance(measured, dict)
        or set(measured) != set(MINIMUM_CAPACITY)
        or any(type(measured.get(key)) is not int for key in MINIMUM_CAPACITY)
        or any(measured[key] < minimum for key, minimum in MINIMUM_CAPACITY.items())
    ):
        raise CapacityAttestationError("capacity_receipt_invalid")
    try:
        public_key.verify(base64.b64decode(signature, validate=True), _canonical(payload))
    except (InvalidSignature, ValueError) as error:
        raise CapacityAttestationError("capacity_receipt_invalid") from error


def emit_capacity_receipt(
    runtime_instance_nonce: str,
    measure: Callable[[], Mapping[str, int]],
) -> None:
    request_raw = os.environ.get("VMVM_CAPACITY_REQUEST", "")
    receipt_raw = os.environ.get("VMVM_CAPACITY_RECEIPT", "")
    with _SIGNING_KEY_LOCK:
        private_key_raw = _SIGNING_KEY_PATH
    values = (request_raw, receipt_raw, private_key_raw)
    if not any(values):
        return
    if not all(values) or NONCE_RE.fullmatch(runtime_instance_nonce) is None:
        raise CapacityAttestationError("capacity_binding_incomplete")
    request_path = _absolute(Path(request_raw))
    receipt_path = _absolute(Path(receipt_raw))
    private_key_path = Path(private_key_raw)
    if (
        receipt_path.parent != request_path.parent
        or receipt_path.name != "vmvm_capacity_receipt.json"
        or request_path.name != "vmvm_capacity_request.json"
    ):
        raise CapacityAttestationError("capacity_binding_incomplete")
    parent, parent_identity = _open_private_directory(request_path.parent)
    try:
        request = _json_object(_read_committed_at(parent, request_path.name))
        _validate_private_directory(request_path.parent, parent, parent_identity)
    except BaseException:
        os.close(parent)
        raise
    if (
        set(request)
        != {
            "schema_version",
            "kind",
            "provider",
            "environment_identity",
            "eval_run_identity_sha256",
            "invocation_identity_sha256",
            "manifest_sha256",
            "selector_sha256",
            "resource_multiplier",
            "measurement_method",
            "public_key_sha256",
        }
        or request.get("schema_version") != 1
        or request.get("kind") != REQUEST_KIND
        or request.get("provider") != "vmvm"
        or request.get("resource_multiplier") != 2
        or request.get("measurement_method") != MEASUREMENT_METHOD
        or request.get("public_key_sha256") != PINNED_PUBLIC_KEY_SHA256
    ):
        os.close(parent)
        raise CapacityAttestationError("capacity_request_invalid")
    lock_name = f".{receipt_path.name}.lock"
    try:
        lock_descriptor = os.open(
            lock_name,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent,
        )
    except OSError as error:
        os.close(parent)
        raise CapacityAttestationError("capacity_lock_invalid") from error
    try:
        lock_metadata = os.fstat(lock_descriptor)
        visible_lock = os.stat(lock_name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != os.getuid()
            or stat.S_IMODE(lock_metadata.st_mode) != 0o600
            or lock_metadata.st_nlink != 1
            or _identity(lock_metadata) != _identity(visible_lock)
        ):
            raise CapacityAttestationError("capacity_lock_invalid")
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        _validate_private_directory(request_path.parent, parent, parent_identity)
        try:
            key_body = _private_bytes(private_key_path)
            key = serialization.load_pem_private_key(key_body, password=None)
        except (OSError, ValueError, TypeError) as error:
            raise CapacityAttestationError("capacity_private_key_invalid") from error
        if not isinstance(key, Ed25519PrivateKey):
            raise CapacityAttestationError("capacity_private_key_invalid")
        public_key = key.public_key()
        public_body = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if _sha256(public_body) != request.get("public_key_sha256"):
            raise CapacityAttestationError("capacity_private_key_mismatch")
        try:
            os.stat(receipt_path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            _validate_existing_receipt(
                _read_committed_at(parent, receipt_path.name),
                request,
                public_key,
            )
            _validate_private_directory(request_path.parent, parent, parent_identity)
            return
        measured = dict(measure())
        if (
            set(measured) != {"actual_cpu_count", "outer_memory_bytes", "disk_available_bytes"}
            or any(type(value) is not int or value < 1 for value in measured.values())
            or any(measured[key] < minimum for key, minimum in MINIMUM_CAPACITY.items())
        ):
            raise CapacityAttestationError("capacity_measurement_invalid")
        issued = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "schema_version": 2,
            "kind": RECEIPT_KIND,
            "state": "passed",
            "issued_at": issued.isoformat().replace("+00:00", "Z"),
            "expires_at": (issued + VALIDITY).isoformat().replace("+00:00", "Z"),
            "valid_for_seconds": VALIDITY_SECONDS,
            "nonce": os.urandom(16).hex(),
            "runtime_instance_nonce": runtime_instance_nonce,
            "provider": request["provider"],
            "environment_identity": request["environment_identity"],
            "eval_run_identity_sha256": request["eval_run_identity_sha256"],
            "invocation_identity_sha256": request["invocation_identity_sha256"],
            "manifest_sha256": request["manifest_sha256"],
            "selector_sha256": request["selector_sha256"],
            "resource_multiplier": request["resource_multiplier"],
            "measurement_method": request["measurement_method"],
            "measured_capacity": measured,
        }
        envelope = {
            "schema_version": 2,
            "kind": RECEIPT_KIND,
            "algorithm": "ed25519",
            "key_sha256": request["public_key_sha256"],
            "payload": payload,
            "signature": base64.b64encode(key.sign(_canonical(payload))).decode("ascii"),
        }
        _write_once_at(
            parent,
            request_path.parent,
            parent_identity,
            receipt_path.name,
            _canonical(envelope),
        )
    finally:
        os.close(lock_descriptor)
        os.close(parent)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-run-identity", type=Path, required=True)
    parser.add_argument("--eval-invocations", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--selector-sha256", required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from direct_kimi_workers import _run_binding

    try:
        identity_sha256, invocation_sha256, identity = _run_binding(
            args.eval_run_identity,
            args.eval_invocations,
            args.provenance,
        )
        prepare_request(
            identity=identity,
            eval_run_identity_sha256=identity_sha256,
            invocation_identity_sha256=invocation_sha256,
            manifest_sha256=args.manifest_sha256,
            selector_sha256=args.selector_sha256,
            public_key=args.public_key,
            output=args.output,
        )
    except Exception:
        raise SystemExit("vmvm_capacity_request_failed") from None
    print(identity_sha256, invocation_sha256, sep="\t")


if __name__ == "__main__":
    main()
