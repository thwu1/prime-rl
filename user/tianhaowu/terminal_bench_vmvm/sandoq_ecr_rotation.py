#!/usr/bin/env python3
"""Rotate a file-backed ECR password and guard a long Sandoq rollout.

Secret bytes are never printed, hashed, or written to telemetry.  The login-side
service atomically replaces the mode-0600 token in its existing directory.  The
batch-side guard records only timestamps and generations, and reserves enough
of the last-known 12-hour lifetime to terminate the evaluator and run verified
Sandoq cleanup if rotation stops.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import platform
import pwd
import re
import secrets
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from direct_qwen_union_contract import (
    UnionContractError,
    canonical_json,
    read_regular,
    sha256_bytes,
    write_exclusive,
)

TOKEN_LIFETIME_SECONDS = 12 * 60 * 60
REFRESH_INTERVAL_SECONDS = 4 * 60 * 60
DEFAULT_HEARTBEAT_SECONDS = 60
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 5 * 60
DEFAULT_CLEANUP_RESERVE_SECONDS = 4 * 60 * 60
DEFAULT_FAIL_CLOSED_BEFORE_EXPIRY_SECONDS = 4 * 60 * 60
DEFAULT_TERMINATION_TIMEOUT_SECONDS = 120
DEFAULT_CLEANUP_TIMEOUT_SECONDS = 2 * 60 * 60
DEFAULT_FINAL_SAFETY_SECONDS = 10 * 60
MAX_SECRET_BYTES = 64 * 1024
MAX_EVENT_LOG_BYTES = 64 * 1024 * 1024
MAX_RESULTS_BYTES = 16 * 1024 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GIT_REVISION_RE = re.compile(r"[0-9a-f]{40}")
VERIFIED_CLEANUP_BASE_URL = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
VERIFIED_CLEANUP_CONCURRENCY = 32


class RotationError(RuntimeError):
    pass


class GuardViolation(RotationError):
    pass


class Clock(Protocol):
    def time(self) -> float: ...

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def time(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass(frozen=True, slots=True)
class RotationConfig:
    token_file: Path
    state_file: Path
    event_log: Path
    client_cert_path: Path | None = None
    ucloud_executable: str = "ucloud"
    region: str = "us-east-2"
    refresh_interval_seconds: int = REFRESH_INTERVAL_SECONDS
    heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS
    retry_seconds: int = 5 * 60
    command_timeout_seconds: int = 60


@dataclass(frozen=True, slots=True)
class GuardConfig:
    token_file: Path
    state_file: Path
    event_log: Path
    heartbeat_timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
    cleanup_reserve_seconds: int = DEFAULT_CLEANUP_RESERVE_SECONDS
    fail_closed_before_expiry_seconds: int = DEFAULT_FAIL_CLOSED_BEFORE_EXPIRY_SECONDS
    termination_timeout_seconds: int = DEFAULT_TERMINATION_TIMEOUT_SECONDS
    cleanup_timeout_seconds: int = DEFAULT_CLEANUP_TIMEOUT_SECONDS
    final_safety_seconds: int = DEFAULT_FINAL_SAFETY_SECONDS
    poll_seconds: int = 30
    required_machine: str = "x86_64"


def _plain_integer(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _integer_time(clock: Clock) -> int:
    value = int(clock.time())
    if value < 0:
        raise RotationError("clock_invalid")
    return value


def _validate_private_parent(path: Path) -> Path:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise RotationError("credential_path_invalid")
    parent = path.parent
    try:
        parent_stat = parent.stat()
    except OSError as error:
        raise RotationError("credential_directory_invalid") from error
    if (
        parent.is_symlink()
        or parent.resolve(strict=True) != parent
        or not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
    ):
        raise RotationError("credential_directory_invalid")
    if stat.S_IMODE(parent_stat.st_mode) != 0o700:
        raise RotationError("credential_directory_permissions_invalid")
    return parent


def _validate_existing_private_file(path: Path, *, allow_missing: bool) -> None:
    if not os.path.lexists(path):
        if allow_missing:
            return
        raise RotationError("private_file_missing")
    try:
        value = path.lstat()
    except OSError as error:
        raise RotationError("private_file_invalid") from error
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_nlink != 1
    ):
        raise RotationError("private_file_invalid")


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace(path: Path, payload: bytes, *, secret: bool) -> None:
    parent = _validate_private_parent(path)
    _validate_existing_private_file(path, allow_missing=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    _validate_existing_private_file(path, allow_missing=False)
    if secret:
        # Intentionally do not fingerprint or reopen the credential here.
        return


def _token_identity(path: Path) -> dict[str, int]:
    _validate_private_parent(path)
    _validate_existing_private_file(path, allow_missing=False)
    value = path.lstat()
    return {
        "token_device": value.st_dev,
        "token_inode": value.st_ino,
        "token_mtime_ns": value.st_mtime_ns,
    }


def _lock_path(token_file: Path, purpose: str) -> Path:
    return token_file.with_name(f".{token_file.name}.{purpose}.lock")


@contextlib.contextmanager
def _file_lock(path: Path, *, exclusive: bool, nonblocking: bool = False):
    _validate_private_parent(path)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise RotationError("rotation_lock_invalid")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        if nonblocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, operation)
        except BlockingIOError as error:
            raise RotationError("rotation_lock_busy") from error
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _validate_paths(token_file: Path, state_file: Path, event_log: Path) -> None:
    service_lock = _lock_path(token_file, "service")
    transaction_lock = _lock_path(token_file, "transaction")
    paths = (token_file, state_file, event_log, service_lock, transaction_lock)
    if any(not path.is_absolute() or path != Path(os.path.normpath(path)) for path in paths):
        raise RotationError("rotation_path_invalid")
    if len(set(paths)) != len(paths):
        raise RotationError("rotation_path_alias")
    for path in paths:
        _validate_private_parent(path)
    existing = []
    for path in paths:
        if os.path.lexists(path):
            metadata = path.lstat()
            existing.append((metadata.st_dev, metadata.st_ino))
    if len(existing) != len(set(existing)):
        raise RotationError("rotation_path_alias")


def read_secret_silent(path: Path) -> None:
    """Validate readability and shape without returning, printing, or hashing bytes."""
    _validate_private_parent(path)
    _validate_existing_private_file(path, allow_missing=False)
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        payload = bytearray()
        while chunk := os.read(descriptor, 4096):
            payload.extend(chunk)
            if len(payload) > MAX_SECRET_BYTES:
                break
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    file_identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if (
        file_identity(before) != file_identity(after)
        or len(payload) < 1
        or len(payload) > MAX_SECRET_BYTES
    ):
        raise RotationError("credential_read_proof_failed")
    token = bytes(payload[:-1] if payload.endswith(b"\n") else payload)
    if (
        not token
        or token.strip() != token
        or b"\n" in token
        or b"\r" in token
        or b"\x00" in token
    ):
        raise RotationError("credential_read_proof_failed")
    try:
        token.decode("ascii")
    except UnicodeDecodeError as error:
        raise RotationError("credential_read_proof_failed") from error


def _client_cert_environment(explicit_path: Path | None) -> dict[str, str]:
    """Mirror the authoritative provider's ucloud-only x509 selection."""
    environment = os.environ.copy()
    existing_cert = environment.pop("THRIFT_TLS_CL_CERT_PATH", "").strip()
    existing_key = environment.pop("THRIFT_TLS_CL_KEY_PATH", "").strip()
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise RotationError("ecr_client_certificate_invalid")
        environment["THRIFT_TLS_CL_CERT_PATH"] = str(explicit_path)
        environment["THRIFT_TLS_CL_KEY_PATH"] = str(explicit_path)
        return environment
    if existing_cert and existing_key:
        environment["THRIFT_TLS_CL_CERT_PATH"] = existing_cert
        environment["THRIFT_TLS_CL_KEY_PATH"] = existing_key
        return environment
    username = pwd.getpwuid(os.getuid()).pw_name
    discovered = Path("/var/facebook/credentials") / username / "x509" / f"{username}.pem"
    if discovered.is_file():
        environment["THRIFT_TLS_CL_CERT_PATH"] = str(discovered)
        environment["THRIFT_TLS_CL_KEY_PATH"] = str(discovered)
    return environment


def mint_ecr_token(
    executable: str,
    region: str,
    timeout_seconds: int,
    *,
    client_cert_path: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> bytes:
    if not executable or any(character in executable for character in "\r\n="):
        raise RotationError("ucloud_executable_invalid")
    if not region or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in region):
        raise RotationError("ecr_region_invalid")
    command = [
        executable,
        "ecr",
        "get-credentials",
        "--prod",
        "--region",
        region,
        "--log-level",
        "error",
    ]
    try:
        completed = runner(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            env=_client_cert_environment(client_cert_path),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RotationError("ecr_mint_failed") from error
    if not isinstance(completed.stdout, bytes):
        raise RotationError("ecr_mint_failed")
    token = completed.stdout
    if token.endswith(b"\n"):
        token = token[:-1]
    if (
        completed.returncode != 0
        or not token
        or len(token) > MAX_SECRET_BYTES
        or b"\n" in token
        or b"\r" in token
        or b"\x00" in token
        or token.strip() != token
    ):
        raise RotationError("ecr_mint_failed")
    try:
        token.decode("ascii")
    except UnicodeDecodeError as error:
        raise RotationError("ecr_mint_failed") from error
    return token


class DurableEventLog:
    def __init__(self, path: Path, *, kind: str) -> None:
        parent = _validate_private_parent(path)
        _validate_existing_private_file(path, allow_missing=True)
        if os.path.lexists(path):
            raise RotationError("event_log_requires_fresh_namespace")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        self._handle = os.fdopen(descriptor, "wb", buffering=0)
        self._path = path
        self._parent = parent
        self._kind = kind
        _fsync_directory(parent)

    def append(
        self,
        *,
        event: str,
        timestamp: int,
        generation: int,
        issued_at: int | None,
        expires_at: int | None,
        detail: str = "ok",
    ) -> None:
        if not event or not detail or any(character in event + detail for character in "\r\n"):
            raise RotationError("event_invalid")
        record = {
            "schema_version": 1,
            "kind": self._kind,
            "event": event,
            "timestamp_unix": timestamp,
            "generation": generation,
            "issued_at_unix": issued_at,
            "expires_at_unix": expires_at,
            "detail": detail,
        }
        self._handle.write(canonical_json(record))
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()


def _state_value(
    *,
    status: str,
    generation: int,
    issued_at: int | None,
    heartbeat_at: int,
    consecutive_failures: int,
    token_identity: Mapping[str, int],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "sandoq-ecr-rotation-state",
        "status": status,
        "generation": generation,
        "issued_at_unix": issued_at,
        "expires_at_unix": None if issued_at is None else issued_at + TOKEN_LIFETIME_SECONDS,
        "refresh_due_unix": None if issued_at is None else issued_at + REFRESH_INTERVAL_SECONDS,
        "heartbeat_at_unix": heartbeat_at,
        "consecutive_mint_failures": consecutive_failures,
        "atomic_same_path": True,
        "token_lifetime_seconds": TOKEN_LIFETIME_SECONDS,
        "refresh_interval_seconds": REFRESH_INTERVAL_SECONDS,
        "token_device": token_identity["token_device"],
        "token_inode": token_identity["token_inode"],
        "token_mtime_ns": token_identity["token_mtime_ns"],
    }


def _write_state(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_replace(path, canonical_json(value), secret=False)


def load_rotation_state(path: Path) -> dict[str, Any]:
    try:
        _validate_private_parent(path)
        _validate_existing_private_file(path, allow_missing=False)
    except RotationError as error:
        raise GuardViolation("rotation_state_invalid") from error
    try:
        raw = read_regular(path, max_bytes=64 * 1024)
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnionContractError) as error:
        raise GuardViolation("rotation_state_invalid") from error
    expected = {
        "schema_version",
        "kind",
        "status",
        "generation",
        "issued_at_unix",
        "expires_at_unix",
        "refresh_due_unix",
        "heartbeat_at_unix",
        "consecutive_mint_failures",
        "atomic_same_path",
        "token_lifetime_seconds",
        "refresh_interval_seconds",
        "token_device",
        "token_inode",
        "token_mtime_ns",
    }
    issued = value.get("issued_at_unix") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("schema_version") != 1
        or value.get("kind") != "sandoq-ecr-rotation-state"
        or value.get("status") not in {"running", "degraded", "stopped"}
        or not _plain_integer(value.get("generation"), minimum=1)
        or not _plain_integer(issued, minimum=0)
        or value.get("expires_at_unix") != issued + TOKEN_LIFETIME_SECONDS
        or value.get("refresh_due_unix") != issued + REFRESH_INTERVAL_SECONDS
        or not _plain_integer(value.get("heartbeat_at_unix"), minimum=issued)
        or not _plain_integer(value.get("consecutive_mint_failures"))
        or value.get("atomic_same_path") is not True
        or value.get("token_lifetime_seconds") != TOKEN_LIFETIME_SECONDS
        or value.get("refresh_interval_seconds") != REFRESH_INTERVAL_SECONDS
        or any(
            not _plain_integer(value.get(key))
            for key in ("token_device", "token_inode", "token_mtime_ns")
        )
    ):
        raise GuardViolation("rotation_state_invalid")
    return value


def _previous_generation(state_file: Path) -> tuple[int, int | None, int, dict[str, int] | None]:
    if not os.path.lexists(state_file):
        return 0, None, 0, None
    try:
        value = load_rotation_state(state_file)
    except GuardViolation as error:
        raise RotationError("prior_rotation_state_invalid") from error
    token_identity = {
        key: value[key] for key in ("token_device", "token_inode", "token_mtime_ns")
    }
    return (
        value["generation"],
        value["issued_at_unix"],
        value["consecutive_mint_failures"],
        token_identity,
    )


def _run_rotation_service_locked(
    config: RotationConfig,
    *,
    clock: Clock | None = None,
    mint: Callable[[], bytes] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    max_iterations: int | None = None,
) -> None:
    clock = clock or SystemClock()
    stop_requested = stop_requested or (lambda: False)
    if (
        config.refresh_interval_seconds != REFRESH_INTERVAL_SECONDS
        or config.heartbeat_seconds < 1
        or config.heartbeat_seconds > DEFAULT_HEARTBEAT_TIMEOUT_SECONDS // 2
        or config.retry_seconds < 1
        or config.retry_seconds >= REFRESH_INTERVAL_SECONDS
    ):
        raise RotationError("rotation_policy_invalid")
    generation, issued_at, consecutive_failures, token_identity = _previous_generation(config.state_file)
    event_log = DurableEventLog(config.event_log, kind="sandoq-ecr-rotation-event")
    now = _integer_time(clock)
    monotonic_now = clock.monotonic()
    if monotonic_now < 0:
        raise RotationError("clock_invalid")
    event_log.append(
        event="rotator_started",
        timestamp=now,
        generation=generation,
        issued_at=issued_at,
        expires_at=None if issued_at is None else issued_at + TOKEN_LIFETIME_SECONDS,
    )
    next_refresh = now
    last_wall = now
    last_monotonic = monotonic_now
    iterations = 0
    try:
        while not stop_requested():
            now = _integer_time(clock)
            monotonic_now = clock.monotonic()
            if now < last_wall or monotonic_now < last_monotonic:
                raise RotationError("rotation_clock_rollback")
            last_wall = now
            last_monotonic = monotonic_now
            status = "degraded" if consecutive_failures else "running"
            if now >= next_refresh:
                try:
                    token = (
                        mint()
                        if mint is not None
                        else mint_ecr_token(
                            config.ucloud_executable,
                            config.region,
                            config.command_timeout_seconds,
                            client_cert_path=config.client_cert_path,
                        )
                    )
                    if (
                        not isinstance(token, bytes)
                        or not token
                        or len(token) > MAX_SECRET_BYTES
                        or any(character in token for character in (b"\n", b"\r", b"\x00"))
                        or token.strip() != token
                    ):
                        raise RotationError("ecr_mint_failed")
                    try:
                        token.decode("ascii")
                    except UnicodeDecodeError as error:
                        raise RotationError("ecr_mint_failed") from error
                    with _file_lock(
                        _lock_path(config.token_file, "transaction"),
                        exclusive=True,
                    ):
                        _atomic_replace(config.token_file, token + b"\n", secret=True)
                        token_identity = _token_identity(config.token_file)
                        generation += 1
                        issued_at = now
                        consecutive_failures = 0
                        status = "running"
                        _write_state(
                            config.state_file,
                            _state_value(
                                status=status,
                                generation=generation,
                                issued_at=issued_at,
                                heartbeat_at=now,
                                consecutive_failures=consecutive_failures,
                                token_identity=token_identity,
                            ),
                        )
                    next_refresh = now + config.refresh_interval_seconds
                    event_log.append(
                        event="token_replaced",
                        timestamp=now,
                        generation=generation,
                        issued_at=issued_at,
                        expires_at=issued_at + TOKEN_LIFETIME_SECONDS,
                    )
                except RotationError:
                    consecutive_failures += 1
                    status = "degraded"
                    next_refresh = now + config.retry_seconds
                    event_log.append(
                        event="mint_failed",
                        timestamp=now,
                        generation=generation,
                        issued_at=issued_at,
                        expires_at=None if issued_at is None else issued_at + TOKEN_LIFETIME_SECONDS,
                        detail="prior_token_retained",
                    )
                    if issued_at is None:
                        raise
            assert issued_at is not None and token_identity is not None
            with _file_lock(
                _lock_path(config.token_file, "transaction"),
                exclusive=True,
            ):
                if _token_identity(config.token_file) != token_identity:
                    raise RotationError("credential_changed_outside_rotator")
                state = _state_value(
                    status=status,
                    generation=generation,
                    issued_at=issued_at,
                    heartbeat_at=now,
                    consecutive_failures=consecutive_failures,
                    token_identity=token_identity,
                )
                _write_state(config.state_file, state)
            event_log.append(
                event="heartbeat",
                timestamp=now,
                generation=generation,
                issued_at=issued_at,
                expires_at=issued_at + TOKEN_LIFETIME_SECONDS,
                detail=status,
            )
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            clock.sleep(config.heartbeat_seconds)
    finally:
        try:
            now = max(_integer_time(clock), last_wall)
        except BaseException:
            now = last_wall
        if issued_at is not None:
            stopped = _state_value(
                status="stopped",
                generation=generation,
                issued_at=issued_at,
                heartbeat_at=now,
                consecutive_failures=consecutive_failures,
                token_identity=token_identity,
            )
            with _file_lock(
                _lock_path(config.token_file, "transaction"),
                exclusive=True,
            ):
                _write_state(config.state_file, stopped)
        event_log.append(
            event="rotator_stopped",
            timestamp=now,
            generation=generation,
            issued_at=issued_at,
            expires_at=None if issued_at is None else issued_at + TOKEN_LIFETIME_SECONDS,
        )
        event_log.close()


def run_rotation_service(
    config: RotationConfig,
    *,
    clock: Clock | None = None,
    mint: Callable[[], bytes] | None = None,
    stop_requested: Callable[[], bool] | None = None,
    max_iterations: int | None = None,
) -> None:
    _validate_paths(config.token_file, config.state_file, config.event_log)
    with _file_lock(
        _lock_path(config.token_file, "service"),
        exclusive=True,
        nonblocking=True,
    ):
        _run_rotation_service_locked(
            config,
            clock=clock,
            mint=mint,
            stop_requested=stop_requested,
            max_iterations=max_iterations,
        )


def validate_guard_state(
    state: Mapping[str, Any],
    *,
    now: int,
    config: GuardConfig,
    prior: Mapping[str, Any] | None,
) -> None:
    if state.get("status") == "stopped":
        raise GuardViolation("rotator_stopped")
    heartbeat = state["heartbeat_at_unix"]
    expires = state["expires_at_unix"]
    if heartbeat > now + 30 or now - heartbeat > config.heartbeat_timeout_seconds:
        raise GuardViolation("rotator_heartbeat_stale")
    if now >= expires - max(
        config.cleanup_reserve_seconds,
        config.fail_closed_before_expiry_seconds,
    ):
        raise GuardViolation("credential_cleanup_reserve_reached")
    if prior is not None:
        if state["heartbeat_at_unix"] < prior["heartbeat_at_unix"]:
            raise GuardViolation("rotation_heartbeat_rollback")
        if state["generation"] < prior["generation"]:
            raise GuardViolation("rotation_generation_rollback")
        if state["generation"] == prior["generation"] and (
            state["issued_at_unix"] != prior["issued_at_unix"]
            or state["expires_at_unix"] != prior["expires_at_unix"]
        ):
            raise GuardViolation("rotation_generation_inconsistent")
        if state["generation"] > prior["generation"] and state["issued_at_unix"] <= prior["issued_at_unix"]:
            raise GuardViolation("rotation_generation_inconsistent")


def load_guard_snapshot(config: GuardConfig) -> dict[str, Any]:
    _validate_paths(config.token_file, config.state_file, config.event_log)
    with _file_lock(
        _lock_path(config.token_file, "transaction"),
        exclusive=False,
    ):
        state = load_rotation_state(config.state_file)
        expected_identity = {
            key: state[key] for key in ("token_device", "token_inode", "token_mtime_ns")
        }
        if _token_identity(config.token_file) != expected_identity:
            raise GuardViolation("rotation_token_identity_mismatch")
        read_secret_silent(config.token_file)
    return state


def _guard_event(log: DurableEventLog, event: str, now: int, state: Mapping[str, Any], detail: str = "ok") -> None:
    log.append(
        event=event,
        timestamp=now,
        generation=int(state["generation"]),
        issued_at=int(state["issued_at_unix"]),
        expires_at=int(state["expires_at_unix"]),
        detail=detail,
    )


PROCESS_GROUP_POLL_SECONDS = 0.05
SUPERVISOR_HANDSHAKE_ENV = "SANDOQ_CLEANUP_SUPERVISOR_SOCKET"
SUPERVISOR_HANDSHAKE_KIND = "sandoq-cleanup-supervisor-v1"
SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 30


@dataclass
class _SupervisorChannel:
    connection: socket.socket
    parent_descriptor: int
    root_descriptor: int
    root_name: str
    root_identity: tuple[int, ...]
    socket_identity: tuple[int, ...]
    closed: bool = False

    def fileno(self) -> int:
        return self.connection.fileno()

    def recv(self, size: int, flags: int = 0) -> bytes:
        return self.connection.recv(size, flags)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        error: BaseException | None = None
        try:
            self.connection.close()
        except BaseException as caught:
            error = caught
        try:
            _remove_supervisor_socket(
                parent_descriptor=self.parent_descriptor,
                root_descriptor=self.root_descriptor,
                root_name=self.root_name,
                root_identity=self.root_identity,
                socket_identity=self.socket_identity,
            )
        except BaseException as caught:
            if error is None:
                error = caught
        if error is not None:
            raise error


def _supervisor_root_identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_nlink)


def _supervisor_socket_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
        value.st_ctime_ns,
    )


def _remove_supervisor_socket(
    *,
    parent_descriptor: int,
    root_descriptor: int,
    root_name: str,
    root_identity: tuple[int, ...],
    socket_identity: tuple[int, ...] | None,
) -> None:
    error: BaseException | None = None
    try:
        root_status = os.fstat(root_descriptor)
        named_root = os.stat(root_name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            _supervisor_root_identity(root_status) != root_identity
            or _supervisor_root_identity(named_root) != root_identity
        ):
            raise GuardViolation("supervisor_socket_cleanup_failed")
        try:
            named_socket = os.stat(
                "channel.sock", dir_fd=root_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            named_socket = None
        if socket_identity is None:
            if named_socket is not None:
                raise GuardViolation("supervisor_socket_cleanup_failed")
        else:
            if (
                named_socket is None
                or _supervisor_socket_identity(named_socket) != socket_identity
            ):
                raise GuardViolation("supervisor_socket_cleanup_failed")
            os.unlink("channel.sock", dir_fd=root_descriptor)
            os.fsync(root_descriptor)
        if _supervisor_root_identity(
            os.stat(root_name, dir_fd=parent_descriptor, follow_symlinks=False)
        ) != root_identity:
            raise GuardViolation("supervisor_socket_cleanup_failed")
        os.rmdir(root_name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    except BaseException as caught:
        error = caught
    finally:
        for descriptor in (root_descriptor, parent_descriptor):
            try:
                os.close(descriptor)
            except OSError as caught:
                if error is None:
                    error = caught
    if error is not None:
        if isinstance(error, GuardViolation):
            raise error
        raise GuardViolation("supervisor_socket_cleanup_failed") from error


def _peer_credentials(channel: socket.socket) -> tuple[int, int, int]:
    try:
        raw = channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", raw)
    except (AttributeError, OSError, struct.error) as error:
        raise GuardViolation("supervisor_handshake_failed") from error


def _supervisor_channel_alive(channel: _SupervisorChannel) -> bool:
    try:
        readable, _, exceptional = select.select([channel], [], [channel], 0)
        if exceptional:
            raise GuardViolation("supervisor_channel_failed")
        if not readable:
            return True
        payload = channel.recv(1, socket.MSG_PEEK)
    except (OSError, ValueError) as error:
        raise GuardViolation("supervisor_channel_failed") from error
    if payload == b"":
        return False
    raise GuardViolation("supervisor_channel_protocol_violation")


def _process_group_id(process: Any) -> int:
    process_id = getattr(process, "pid", None)
    if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 1:
        raise GuardViolation("process_group_invalid")
    return process_id


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError as error:
        raise GuardViolation("process_group_uninspectable") from error
    return True


def _wait_process_group_extinct(
    process_group_id: int,
    deadline: float,
    *,
    group_exists: Callable[[int], bool] = _process_group_exists,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    while group_exists(process_group_id):
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleep(min(PROCESS_GROUP_POLL_SECONDS, remaining))
    return True


def _terminate_process_group(
    process: Any,
    timeout: int,
    *,
    group_exists: Callable[[int], bool] = _process_group_exists,
    send_group_signal: Callable[[int, int], None] = os.killpg,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    if timeout < 1:
        raise GuardViolation("process_group_cleanup_failed")
    process_group_id = _process_group_id(process)
    started = monotonic()
    deadline = started + timeout
    graceful_deadline = started + timeout / 2
    if group_exists(process_group_id):
        try:
            send_group_signal(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=max(0.001, graceful_deadline - monotonic()))
        except subprocess.TimeoutExpired:
            pass
    if _wait_process_group_extinct(
        process_group_id,
        graceful_deadline,
        group_exists=group_exists,
        monotonic=monotonic,
        sleep=sleep,
    ):
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.001, deadline - monotonic()))
            except subprocess.TimeoutExpired as error:
                raise GuardViolation("process_group_cleanup_failed") from error
        if process.poll() is None:
            raise GuardViolation("process_group_cleanup_failed")
        return
    try:
        send_group_signal(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=max(0.001, deadline - monotonic()))
        except subprocess.TimeoutExpired:
            pass
    if not _wait_process_group_extinct(
        process_group_id,
        deadline,
        group_exists=group_exists,
        monotonic=monotonic,
        sleep=sleep,
    ) or process.poll() is None:
        raise GuardViolation("process_group_cleanup_failed")


def _run_cleanup_command(
    command: Sequence[str],
    *,
    timeout: int,
    termination_timeout: int,
    process_factory: Callable[..., Any],
    group_exists: Callable[[int], bool],
    terminate_process_group: Callable[[Any, int], None],
) -> int:
    if timeout <= termination_timeout or termination_timeout < 1:
        raise GuardViolation("cleanup_policy_invalid")
    try:
        process = process_factory(
            list(command),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except BaseException as error:
        raise GuardViolation("cleanup_failed") from error
    try:
        try:
            returncode = process.wait(timeout=timeout - termination_timeout)
        except subprocess.TimeoutExpired as error:
            terminate_process_group(process, termination_timeout)
            raise GuardViolation("cleanup_failed") from error
        if group_exists(_process_group_id(process)):
            terminate_process_group(process, termination_timeout)
            raise GuardViolation("cleanup_process_group_survived")
        if returncode != 0:
            raise GuardViolation("cleanup_failed")
        return returncode
    except BaseException as error:
        try:
            if group_exists(_process_group_id(process)):
                terminate_process_group(process, termination_timeout)
        except BaseException as termination_error:
            error.add_note(f"cleanup process-group teardown failed: {termination_error!r}")
        raise


def _start_supervised_evaluator(
    command: Sequence[str],
    *,
    process_factory: Callable[..., Any],
    termination_timeout: int,
    terminate_process_group: Callable[[Any, int], None],
) -> tuple[Any, _SupervisorChannel]:
    socket_parent = Path("/tmp")
    parent_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    try:
        parent_descriptor = os.open(socket_parent, parent_flags)
    except OSError as error:
        raise GuardViolation("supervisor_socket_setup_failed") from error
    root_descriptor = -1
    root_identity: tuple[int, ...] | None = None
    socket_identity: tuple[int, ...] | None = None
    socket_root = Path(tempfile.mkdtemp(prefix=f"sandoq-supervisor-{os.getuid()}-", dir="/tmp"))
    root_name = socket_root.name
    socket_path = socket_root / "channel.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    connection: socket.socket | None = None
    process = None
    try:
        socket_root.chmod(0o700)
        initial_root = socket_root.lstat()
        root_identity = _supervisor_root_identity(initial_root)
        root_descriptor = os.open(root_name, parent_flags, dir_fd=parent_descriptor)
        root_status = os.fstat(root_descriptor)
        named_root = os.stat(root_name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            root_identity != _supervisor_root_identity(root_status)
            or root_identity != _supervisor_root_identity(named_root)
            or not stat.S_ISDIR(root_status.st_mode)
            or root_status.st_uid != os.getuid()
            or stat.S_IMODE(root_status.st_mode) != 0o700
        ):
            raise GuardViolation("supervisor_socket_setup_failed")
        listener.bind(str(socket_path))
        os.chmod("channel.sock", 0o600, dir_fd=root_descriptor, follow_symlinks=False)
        socket_status = os.stat(
            "channel.sock", dir_fd=root_descriptor, follow_symlinks=False
        )
        socket_identity = _supervisor_socket_identity(socket_status)
        if (
            not stat.S_ISSOCK(socket_status.st_mode)
            or socket_status.st_uid != os.getuid()
            or stat.S_IMODE(socket_status.st_mode) != 0o600
            or socket_status.st_nlink != 1
        ):
            raise GuardViolation("supervisor_socket_setup_failed")
        listener.listen(1)
        listener.settimeout(SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS)
        environment = os.environ.copy()
        environment[SUPERVISOR_HANDSHAKE_ENV] = str(socket_path)
        wrapped_command = [
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "exec-supervised",
            "--",
            *command,
        ]
        process = process_factory(
            wrapped_command,
            start_new_session=True,
            env=environment,
        )
        connection, _address = listener.accept()
        connection.settimeout(SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS)
        peer_pid, peer_uid, _peer_gid = _peer_credentials(connection)
        hello_raw = connection.recv(4097)
        if len(hello_raw) > 4096:
            raise GuardViolation("supervisor_handshake_failed")
        try:
            hello = json.loads(hello_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GuardViolation("supervisor_handshake_failed") from error
        expected_pid = _process_group_id(process)
        expected_start_ticks = _process_start_ticks(expected_pid)
        if (
            peer_uid != os.getuid()
            or peer_pid != expected_pid
            or hello
            != {
                "schema_version": 1,
                "kind": f"{SUPERVISOR_HANDSHAKE_KIND}-hello",
                "evaluator_pid": expected_pid,
                "evaluator_process_group_id": expected_pid,
                "evaluator_start_ticks": expected_start_ticks,
            }
        ):
            raise GuardViolation("supervisor_handshake_failed")
        nonce = secrets.token_hex(32)
        payload = {
            "schema_version": 1,
            "kind": SUPERVISOR_HANDSHAKE_KIND,
            "nonce": nonce,
            "guard_pid": os.getpid(),
            "guard_start_ticks": _process_start_ticks(os.getpid()),
            "evaluator_pid": expected_pid,
            "evaluator_start_ticks": expected_start_ticks,
            "evaluator_process_group_id": expected_pid,
        }
        connection.sendall(canonical_json(payload))
        response = connection.recv(4097)
        if len(response) > 4096:
            raise GuardViolation("supervisor_handshake_failed")
        try:
            acknowledgement = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GuardViolation("supervisor_handshake_failed") from error
        if acknowledgement != {
            "schema_version": 1,
            "kind": f"{SUPERVISOR_HANDSHAKE_KIND}-ack",
            "nonce": nonce,
            "evaluator_pid": expected_pid,
            "evaluator_start_ticks": expected_start_ticks,
        }:
            raise GuardViolation("supervisor_handshake_failed")
        connection.setblocking(False)
    except BaseException as error:
        with contextlib.suppress(OSError):
            listener.close()
        if connection is not None:
            with contextlib.suppress(OSError):
                connection.close()
        if root_descriptor >= 0 and root_identity is not None:
            try:
                _remove_supervisor_socket(
                    parent_descriptor=parent_descriptor,
                    root_descriptor=root_descriptor,
                    root_name=root_name,
                    root_identity=root_identity,
                    socket_identity=socket_identity,
                )
            except BaseException as cleanup_error:
                error.add_note(f"supervisor socket cleanup failed: {cleanup_error!r}")
        else:
            if root_descriptor >= 0:
                os.close(root_descriptor)
            elif root_identity is not None:
                try:
                    named_root = os.stat(
                        root_name, dir_fd=parent_descriptor, follow_symlinks=False
                    )
                    if _supervisor_root_identity(named_root) != root_identity:
                        raise GuardViolation("supervisor_socket_cleanup_failed")
                    os.rmdir(root_name, dir_fd=parent_descriptor)
                    os.fsync(parent_descriptor)
                except BaseException as cleanup_error:
                    error.add_note(f"supervisor socket cleanup failed: {cleanup_error!r}")
            os.close(parent_descriptor)
        if process is not None:
            try:
                terminate_process_group(process, termination_timeout)
            except BaseException as termination_error:
                error.add_note(
                    f"evaluator process-group teardown failed: {termination_error!r}"
                )
        if isinstance(error, GuardViolation):
            raise
        raise GuardViolation("supervisor_handshake_failed") from error
    listener.close()
    assert connection is not None
    assert root_identity is not None and socket_identity is not None
    return process, _SupervisorChannel(
        connection,
        parent_descriptor,
        root_descriptor,
        root_name,
        root_identity,
        socket_identity,
    )


def exec_supervised_evaluator(command: Sequence[str]) -> None:
    """Authenticate the post-exec evaluator process, retain liveness FD, then exec."""
    socket_value = os.environ.get(SUPERVISOR_HANDSHAKE_ENV)
    if (
        not command
        or socket_value is None
        or not socket_value
        or "\x00" in socket_value
        or not Path(socket_value).is_absolute()
    ):
        raise GuardViolation("supervisor_handshake_failed")
    channel = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        channel.settimeout(SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS)
        channel.connect(socket_value)
        evaluator_pid = os.getpid()
        evaluator_start_ticks = _process_start_ticks(evaluator_pid)
        hello = {
            "schema_version": 1,
            "kind": f"{SUPERVISOR_HANDSHAKE_KIND}-hello",
            "evaluator_pid": evaluator_pid,
            "evaluator_process_group_id": os.getpgrp(),
            "evaluator_start_ticks": evaluator_start_ticks,
        }
        channel.sendall(canonical_json(hello))
        payload_raw = channel.recv(4097)
        if len(payload_raw) > 4096:
            raise GuardViolation("supervisor_handshake_failed")
        try:
            payload = json.loads(payload_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GuardViolation("supervisor_handshake_failed") from error
        peer_pid, peer_uid, _peer_gid = _peer_credentials(channel)
        if (
            peer_uid != os.getuid()
            or peer_pid != os.getppid()
            or payload.get("schema_version") != 1
            or payload.get("kind") != SUPERVISOR_HANDSHAKE_KIND
            or not isinstance(payload.get("nonce"), str)
            or re.fullmatch(r"[0-9a-f]{64}", payload["nonce"]) is None
            or payload.get("guard_pid") != peer_pid
            or payload.get("guard_start_ticks") != _process_start_ticks(peer_pid)
            or payload.get("evaluator_pid") != evaluator_pid
            or payload.get("evaluator_start_ticks") != evaluator_start_ticks
            or payload.get("evaluator_process_group_id") != os.getpgrp()
        ):
            raise GuardViolation("supervisor_handshake_failed")
        acknowledgement = {
            "schema_version": 1,
            "kind": f"{SUPERVISOR_HANDSHAKE_KIND}-ack",
            "nonce": payload["nonce"],
            "evaluator_pid": evaluator_pid,
            "evaluator_start_ticks": evaluator_start_ticks,
        }
        channel.sendall(canonical_json(acknowledgement))
        channel.settimeout(None)
        os.set_inheritable(channel.fileno(), True)
        environment = os.environ.copy()
        environment.pop(SUPERVISOR_HANDSHAKE_ENV, None)
        environment["SANDOQ_CLEANUP_SUPERVISOR_CHANNEL_FD"] = str(channel.fileno())
        os.execvpe(command[0], list(command), environment)
    except BaseException:
        channel.close()
        raise


def _process_start_ticks(process_id: int) -> int:
    if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 1:
        raise GuardViolation("supervisor_handshake_failed")
    try:
        raw = Path(f"/proc/{process_id}/stat").read_bytes()
        fields = raw[raw.rindex(b")") + 2 :].split()
        value = int(fields[19])
    except (OSError, ValueError, IndexError) as error:
        raise GuardViolation("supervisor_handshake_failed") from error
    if value <= 0:
        raise GuardViolation("supervisor_handshake_failed")
    return value


def supervise_rollout(
    config: GuardConfig,
    evaluator_command: Sequence[str],
    cleanup_command: Sequence[str],
    *,
    clock: Clock | None = None,
    machine: Callable[[], str] = platform.machine,
    process_factory: Callable[..., Any] = subprocess.Popen,
    cleanup_process_factory: Callable[..., Any] = subprocess.Popen,
    process_group_exists: Callable[[int], bool] = _process_group_exists,
    terminate_process_group: Callable[[Any, int], None] = _terminate_process_group,
    evaluator_starter: Callable[..., tuple[Any, Any]] = _start_supervised_evaluator,
    stop_requested: Callable[[], bool] | None = None,
) -> int:
    clock = clock or SystemClock()
    stop_requested = stop_requested or (lambda: False)
    if (
        not evaluator_command
        or not cleanup_command
        or config.heartbeat_timeout_seconds < 1
        or config.poll_seconds < 1
        or config.termination_timeout_seconds < 2
        or config.cleanup_timeout_seconds <= config.termination_timeout_seconds
        or config.final_safety_seconds < 1
        or config.cleanup_reserve_seconds
        < config.termination_timeout_seconds + config.cleanup_timeout_seconds + config.final_safety_seconds
        or config.fail_closed_before_expiry_seconds < 1
        or config.fail_closed_before_expiry_seconds > config.cleanup_reserve_seconds
    ):
        raise RotationError("guard_policy_invalid")
    _validate_paths(config.token_file, config.state_file, config.event_log)
    if machine().lower() != config.required_machine.lower():
        raise GuardViolation("batch_architecture_invalid")
    log = DurableEventLog(config.event_log, kind="sandoq-ecr-guard-event")
    process = None
    supervisor_channel = None
    prior: dict[str, Any] | None = None
    trigger: str | None = None
    evaluator_code = 1
    pending_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    cleanup_succeeded = False
    evaluator_attempted = False
    last_wall: int | None = None
    last_monotonic: float | None = None
    heartbeat_value: int | None = None
    heartbeat_monotonic: float | None = None
    try:
        now = _integer_time(clock)
        monotonic_now = clock.monotonic()
        state = load_guard_snapshot(config)
        validate_guard_state(state, now=now, config=config, prior=None)
        _guard_event(log, "guard_started", now, state)
        _guard_event(log, "initial_read_verified", now, state, detail=config.required_machine)
        prior = state
        last_wall = now
        last_monotonic = monotonic_now
        heartbeat_value = state["heartbeat_at_unix"]
        heartbeat_monotonic = monotonic_now
        evaluator_attempted = True
        process, supervisor_channel = evaluator_starter(
            evaluator_command,
            process_factory=process_factory,
            termination_timeout=config.termination_timeout_seconds,
            terminate_process_group=terminate_process_group,
        )
        _guard_event(log, "evaluator_started", now, state)
        while True:
            evaluator_code = process.poll()
            now = _integer_time(clock)
            monotonic_now = clock.monotonic()
            if stop_requested():
                trigger = "guard_signal_requested"
                assert prior is not None
                _guard_event(log, "guard_triggered", now, prior, detail=trigger)
                break
            try:
                if (
                    last_wall is None
                    or last_monotonic is None
                    or now < last_wall
                    or monotonic_now < last_monotonic
                ):
                    raise GuardViolation("guard_clock_rollback")
                state = load_guard_snapshot(config)
                validate_guard_state(state, now=now, config=config, prior=prior)
                if state["generation"] != prior["generation"]:
                    _guard_event(log, "generation_read_verified", now, state)
                if state["heartbeat_at_unix"] != heartbeat_value:
                    heartbeat_value = state["heartbeat_at_unix"]
                    heartbeat_monotonic = monotonic_now
                elif (
                    heartbeat_monotonic is None
                    or monotonic_now - heartbeat_monotonic > config.heartbeat_timeout_seconds
                ):
                    raise GuardViolation("rotator_heartbeat_stale")
                prior = state
                last_wall = now
                last_monotonic = monotonic_now
                _guard_event(log, "heartbeat_verified", now, state, detail=state["status"])
            except (GuardViolation, RotationError):
                trigger = "credential_guard_failed"
                assert prior is not None
                _guard_event(log, "guard_triggered", now, prior, detail=trigger)
                break
            if evaluator_code is not None:
                _guard_event(log, "evaluator_exited", now, state, detail=str(evaluator_code))
                break
            if supervisor_channel is not None and not _supervisor_channel_alive(supervisor_channel):
                trigger = "supervisor_channel_closed"
                assert prior is not None
                _guard_event(log, "guard_triggered", now, prior, detail=trigger)
                break
            clock.sleep(config.poll_seconds)
    except BaseException as error:
        pending_error = error
    finally:
        if process is not None:
            try:
                process_group_id = _process_group_id(process)
                leader_running = process.poll() is None
                group_running = process_group_exists(process_group_id)
                if leader_running or group_running:
                    terminate_process_group(process, config.termination_timeout_seconds)
                    evaluator_code = process.poll()
                    if not leader_running and trigger is None and pending_error is None:
                        pending_error = GuardViolation("evaluator_process_group_survived")
                if (leader_running or group_running) and prior is not None:
                    with contextlib.suppress(Exception):
                        _guard_event(
                            log,
                            "evaluator_terminated",
                            _integer_time(clock),
                            prior,
                            detail=trigger or "guard_shutdown",
                        )
            except BaseException as error:
                if pending_error is None:
                    pending_error = error
        if supervisor_channel is not None:
            try:
                supervisor_channel.close()
            except BaseException as error:
                if pending_error is None:
                    pending_error = error
        if evaluator_attempted and prior is not None:
            try:
                now = _integer_time(clock)
            except BaseException as error:
                now = last_wall if last_wall is not None else int(prior["heartbeat_at_unix"])
                if pending_error is None:
                    pending_error = error
            available = prior["expires_at_unix"] - now - config.final_safety_seconds
            cleanup_timeout = min(config.cleanup_timeout_seconds, available)
            with contextlib.suppress(Exception):
                _guard_event(log, "cleanup_started", now, prior)
            if cleanup_timeout < 1:
                cleanup_error = GuardViolation("cleanup_deadline_exhausted")
            else:
                try:
                    cleanup_returncode = _run_cleanup_command(
                        list(cleanup_command),
                        timeout=cleanup_timeout,
                        termination_timeout=config.termination_timeout_seconds,
                        process_factory=cleanup_process_factory,
                        group_exists=process_group_exists,
                        terminate_process_group=terminate_process_group,
                    )
                    now = _integer_time(clock)
                    if cleanup_returncode != 0 or now >= prior["expires_at_unix"] - config.final_safety_seconds:
                        raise GuardViolation("cleanup_failed")
                    cleanup_succeeded = True
                    with contextlib.suppress(Exception):
                        _guard_event(log, "cleanup_completed", now, prior, detail="0")
                except BaseException as error:
                    cleanup_error = GuardViolation("cleanup_failed")
                    cleanup_error.__cause__ = error
            with contextlib.suppress(Exception):
                _guard_event(
                    log,
                    "guard_stopped",
                    _integer_time(clock),
                    prior,
                    detail=(
                        "passed"
                        if pending_error is None
                        and cleanup_error is None
                        and trigger is None
                        and evaluator_code == 0
                        else "failed"
                    ),
                )
        try:
            log.close()
        except BaseException as error:
            if pending_error is None:
                pending_error = error
    if cleanup_error is not None:
        raise cleanup_error
    if pending_error is not None:
        raise pending_error
    if evaluator_attempted and not cleanup_succeeded:
        raise GuardViolation("cleanup_failed")
    if trigger is not None:
        return 86
    return int(evaluator_code or 0)


def _events(path: Path, expected_kind: str) -> tuple[list[dict[str, Any]], bytes]:
    try:
        raw = read_regular(path, max_bytes=MAX_EVENT_LOG_BYTES)
    except UnionContractError as error:
        raise RotationError("rotation_audit_log_invalid") from error
    if not raw or not raw.endswith(b"\n"):
        raise RotationError("rotation_audit_log_invalid")
    expected = {
        "schema_version",
        "kind",
        "event",
        "timestamp_unix",
        "generation",
        "issued_at_unix",
        "expires_at_unix",
        "detail",
    }
    events: list[dict[str, Any]] = []
    prior_time = -1
    details = (
        {
            "rotator_started": {"ok"},
            "token_replaced": {"ok"},
            "heartbeat": {"running", "degraded"},
            "mint_failed": {"prior_token_retained"},
            "rotator_stopped": {"ok"},
        }
        if expected_kind == "sandoq-ecr-rotation-event"
        else {
            "guard_started": {"ok"},
            "initial_read_verified": {"x86_64"},
            "evaluator_started": {"ok"},
            "generation_read_verified": {"ok"},
            "heartbeat_verified": {"running", "degraded"},
            "evaluator_exited": set(),
            "guard_triggered": {"credential_guard_failed", "guard_signal_requested"},
            "evaluator_terminated": {
                "credential_guard_failed",
                "guard_shutdown",
                "guard_signal_requested",
            },
            "cleanup_started": {"ok"},
            "cleanup_completed": {"0"},
            "guard_stopped": {"passed", "failed"},
        }
    )
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise RotationError("rotation_audit_log_invalid") from error
        if (
            not isinstance(value, dict)
            or set(value) != expected
            or value.get("schema_version") != 1
            or value.get("kind") != expected_kind
            or not isinstance(value.get("event"), str)
            or not isinstance(value.get("detail"), str)
            or value["event"] not in details
            or (
                value["event"] == "evaluator_exited"
                and not value["detail"].lstrip("-").isdigit()
            )
            or (
                value["event"] != "evaluator_exited"
                and value["detail"] not in details[value["event"]]
            )
            or not _plain_integer(value.get("timestamp_unix"))
            or value["timestamp_unix"] < prior_time
            or not _plain_integer(value.get("generation"))
            or (
                value.get("issued_at_unix") is not None
                and not _plain_integer(value.get("issued_at_unix"))
            )
            or (
                value.get("expires_at_unix") is not None
                and value.get("expires_at_unix") != value.get("issued_at_unix") + TOKEN_LIFETIME_SECONDS
            )
        ):
            raise RotationError("rotation_audit_log_invalid")
        prior_time = value["timestamp_unix"]
        events.append(value)
    return events, raw


def sha256_regular_streaming(path: Path, *, max_bytes: int = MAX_RESULTS_BYTES) -> str:
    """Hash a stable regular file without loading a potentially multi-GiB result."""
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RotationError("rotation_audit_run_binding_invalid") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise RotationError("rotation_audit_run_binding_invalid")
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(descriptor, 1 << 20):
            total += len(chunk)
            if total > max_bytes:
                raise RotationError("rotation_audit_run_binding_invalid")
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if identity(before) != identity(after) or total != before.st_size:
        raise RotationError("rotation_audit_run_binding_invalid")
    return digest.hexdigest()


def sanitize_rotation_audit(
    rotator_log: Path,
    guard_log: Path,
    *,
    eval_run_identity_sha256: str,
    results_sha256: str,
) -> dict[str, Any]:
    rotator, rotator_raw = _events(rotator_log, "sandoq-ecr-rotation-event")
    guard, guard_raw = _events(guard_log, "sandoq-ecr-guard-event")
    if (
        len(eval_run_identity_sha256) != 64
        or set(eval_run_identity_sha256) - frozenset("0123456789abcdef")
        or len(results_sha256) != 64
        or set(results_sha256) - frozenset("0123456789abcdef")
    ):
        raise RotationError("rotation_audit_not_passed")

    # A passed audit is deliberately stricter than merely finding one event of
    # each type.  It proves the complete normal-path state machine and rejects
    # injected, duplicated, missing, or out-of-order terminal events.
    if len(rotator) < 4 or rotator[0]["event"] != "rotator_started" or rotator[-1]["event"] != "rotator_stopped":
        raise RotationError("rotation_audit_not_passed")
    if any(event["event"] in {"rotator_started", "rotator_stopped"} for event in rotator[1:-1]):
        raise RotationError("rotation_audit_not_passed")
    if any(event["event"] == "mint_failed" for event in rotator):
        raise RotationError("rotation_audit_not_passed")
    replacements = [event for event in rotator if event["event"] == "token_replaced"]
    if not replacements:
        raise RotationError("rotation_audit_not_passed")
    current_generation = rotator[0]["generation"]
    current_issued = rotator[0]["issued_at_unix"]
    for event in rotator[1:]:
        if event["event"] == "token_replaced":
            if (
                event["generation"] != current_generation + 1
                or event["issued_at_unix"] != event["timestamp_unix"]
            ):
                raise RotationError("rotation_audit_not_passed")
            current_generation = event["generation"]
            current_issued = event["issued_at_unix"]
        elif (
            event["event"] not in {"heartbeat", "rotator_stopped"}
            or event["generation"] != current_generation
            or event["issued_at_unix"] != current_issued
        ):
            raise RotationError("rotation_audit_not_passed")

    guard_names = [event["event"] for event in guard]
    if (
        len(guard) < 9
        or guard_names[:3] != ["guard_started", "initial_read_verified", "evaluator_started"]
        or guard_names[-4:] != [
            "evaluator_exited",
            "cleanup_started",
            "cleanup_completed",
            "guard_stopped",
        ]
        or guard[-4]["detail"] != "0"
        or guard[-2]["detail"] != "0"
        or guard[-1]["detail"] != "passed"
        or any(
            name not in {"heartbeat_verified", "generation_read_verified"}
            for name in guard_names[3:-4]
        )
    ):
        raise RotationError("rotation_audit_not_passed")
    heartbeats = [event for event in guard if event["event"] == "heartbeat_verified"]
    if len(heartbeats) < 2:
        raise RotationError("rotation_audit_not_passed")
    start = guard[0]["timestamp_unix"]
    evaluator_start = guard[2]["timestamp_unix"]
    evaluator_end = guard[-4]["timestamp_unix"]
    end = guard[-1]["timestamp_unix"]
    if not (start <= evaluator_start <= evaluator_end <= guard[-3]["timestamp_unix"] <= guard[-2]["timestamp_unix"] <= end):
        raise RotationError("rotation_audit_not_passed")
    if rotator[0]["timestamp_unix"] > start or rotator[-1]["timestamp_unix"] < end:
        raise RotationError("rotation_audit_not_passed")

    relevant = [
        event
        for event in replacements
        if event["issued_at_unix"] <= end and event["expires_at_unix"] > start
    ]
    generations = [event["generation"] for event in relevant]
    issued = [event["issued_at_unix"] for event in relevant]
    replacement_by_generation = {
        event["generation"]: (event["issued_at_unix"], event["expires_at_unix"])
        for event in relevant
    }
    if (
        not relevant
        or generations != sorted(set(generations))
        or issued != sorted(set(issued))
        or relevant[0]["issued_at_unix"] > start
        or relevant[-1]["expires_at_unix"] <= end
        or any(
            replacement_by_generation.get(event["generation"])
            != (event["issued_at_unix"], event["expires_at_unix"])
            for event in guard
        )
    ):
        raise RotationError("rotation_audit_not_passed")
    gaps = [second - first for first, second in zip(issued, issued[1:], strict=False)]
    gaps.append(end - issued[-1])
    margins = [event["expires_at_unix"] - event["timestamp_unix"] for event in heartbeats]
    guard_times = [start, *(event["timestamp_unix"] for event in heartbeats), evaluator_end]
    heartbeat_gaps = [second - first for first, second in zip(guard_times, guard_times[1:], strict=False)]
    rotator_times = [event["timestamp_unix"] for event in rotator]
    rotator_event_gaps = [
        second - first for first, second in zip(rotator_times, rotator_times[1:], strict=False)
    ]
    run_duration = evaluator_end - evaluator_start
    successful = len(relevant)
    if (
        run_duration < 1
        or max(gaps) > REFRESH_INTERVAL_SECONDS
        or max(heartbeat_gaps) > DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
        or max(rotator_event_gaps) > DEFAULT_HEARTBEAT_TIMEOUT_SECONDS
        or min(margins) < DEFAULT_FAIL_CLOSED_BEFORE_EXPIRY_SECONDS
        or end >= guard[-1]["expires_at_unix"] - DEFAULT_FINAL_SAFETY_SECONDS
        or successful < run_duration // REFRESH_INTERVAL_SECONDS
    ):
        raise RotationError("rotation_audit_not_passed")
    return {
        "schema_version": 1,
        "kind": "sandoq-auth-rotation",
        "state": "passed",
        "refresh_source": "login-side-service",
        "token_path_policy": "private-mode-0600-atomic-replace",
        "atomic_same_path": True,
        "monitor_started_before_rollout": True,
        "monitor_stopped_after_rollout": True,
        "maximum_refresh_interval_seconds": REFRESH_INTERVAL_SECONDS,
        "fail_closed_before_expiry_seconds": DEFAULT_FAIL_CLOSED_BEFORE_EXPIRY_SECONDS,
        "run_duration_seconds": run_duration,
        "successful_replacements": successful,
        "maximum_observed_refresh_gap_seconds": max(gaps),
        "maximum_observed_heartbeat_gap_seconds": max(heartbeat_gaps),
        "minimum_observed_expiry_margin_seconds": min(margins),
        "batch_heartbeats": len(heartbeats),
        "liveness_failures": 0,
        "expired_observations": 0,
        "credential_payload_records": 0,
        "eval_run_identity_sha256": eval_run_identity_sha256,
        "results_sha256": results_sha256,
        "raw_rotator_log_sha256": sha256_bytes(rotator_raw),
        "raw_batch_guard_log_sha256": sha256_bytes(guard_raw),
    }


def _read_private_command_file(path: Path) -> bytes:
    if (
        not path.is_absolute()
        or path.name in {"", ".", ".."}
        or path != Path(os.path.normpath(path))
    ):
        raise RotationError("command_file_invalid")
    parent_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    try:
        parent_descriptor = os.open(path.parent, parent_flags)
    except OSError as error:
        raise RotationError("command_file_invalid") from error
    descriptor = -1
    try:
        parent_before = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_before.st_mode)
            or parent_before.st_uid != os.getuid()
            or stat.S_IMODE(parent_before.st_mode) != 0o700
        ):
            raise RotationError("command_file_invalid")
        descriptor = os.open(path.name, file_flags, dir_fd=parent_descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size > 64 * 1024
        ):
            raise RotationError("command_file_invalid")
        body = bytearray()
        while chunk := os.read(descriptor, 16 * 1024):
            body.extend(chunk)
            if len(body) > 64 * 1024:
                raise RotationError("command_file_invalid")
        after = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        parent_after = os.fstat(parent_descriptor)
    except (OSError, ValueError) as error:
        raise RotationError("command_file_invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_descriptor)
    file_identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_uid,
        item.st_nlink,
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )
    directory_identity = lambda item: (
        item.st_dev,
        item.st_ino,
        item.st_mode,
        item.st_uid,
        item.st_nlink,
    )
    if (
        file_identity(before) != file_identity(after)
        or file_identity(after) != file_identity(named)
        or directory_identity(parent_before) != directory_identity(parent_after)
        or len(body) != before.st_size
    ):
        raise RotationError("command_file_invalid")
    return bytes(body)


def _command_from_json(path: Path) -> list[str]:
    try:
        value = json.loads(_read_private_command_file(path))
    except json.JSONDecodeError as error:
        raise RotationError("command_file_invalid") from error
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item or "\x00" in item for item in value)
    ):
        raise RotationError("command_file_invalid")
    project_root = Path(__file__).resolve(strict=True).parents[3]
    cleanup_script = project_root / "user/tianhaowu/terminal_bench_vmvm/run_sandoq_verified_cleanup.py"
    provider_root = project_root / "deps/sandoq-provider"
    provider_cleanup = (
        provider_root / "recipes/sandoq_swerebench_v2_oci/verify_pool_cleanup.py"
    )
    if value[:3] != [sys.executable, "-B", os.fspath(cleanup_script)]:
        raise RotationError("command_file_invalid")
    arguments = value[3:]
    if len(arguments) % 2:
        raise RotationError("command_file_invalid")
    parsed: dict[str, str] = {}
    for option, argument in zip(arguments[::2], arguments[1::2], strict=True):
        if not option.startswith("--") or option in parsed:
            raise RotationError("command_file_invalid")
        parsed[option] = argument
    expected_options = {
        "--output-dir",
        "--provider-cleanup",
        "--base-url",
        "--owner",
        "--concurrency",
        "--event-log",
        "--wal",
        "--drain-marker",
        "--sanitized-output",
        "--project-root",
        "--provider-root",
        "--expected-prime-commit",
        "--expected-prime-tree",
        "--expected-self-sha256",
        "--expected-sanitizer-sha256",
        "--expected-provider-cleanup-sha256",
    }
    digest_options = {
        "--expected-self-sha256",
        "--expected-sanitizer-sha256",
        "--expected-provider-cleanup-sha256",
    }
    if (
        set(parsed) != expected_options
        or parsed["--project-root"] != os.fspath(project_root)
        or parsed["--provider-root"] != os.fspath(provider_root)
        or parsed["--provider-cleanup"] != os.fspath(provider_cleanup)
        or parsed["--base-url"] != VERIFIED_CLEANUP_BASE_URL
        or parsed["--concurrency"] != str(VERIFIED_CLEANUP_CONCURRENCY)
        or GIT_REVISION_RE.fullmatch(parsed["--expected-prime-commit"]) is None
        or GIT_REVISION_RE.fullmatch(parsed["--expected-prime-tree"]) is None
        or any(SHA256_RE.fullmatch(parsed[option]) is None for option in digest_options)
        or not parsed["--owner"]
        or any(character in parsed["--owner"] for character in "\r\n=")
    ):
        raise RotationError("command_file_invalid")
    required_environment = {
        "PRIME_RL_OUTPUT_DIR": "--output-dir",
        "SANDOQ_OWNER": "--owner",
        "OCI_RUNNER_POOL_EVENT_LOG": "--event-log",
        "OCI_RUNNER_POOL_WAL": "--wal",
    }
    if any(
        not os.environ.get(variable)
        or parsed[option] != os.environ[variable]
        for variable, option in required_environment.items()
    ):
        raise RotationError("command_file_invalid")
    pool_socket_value = os.environ.get("OCI_RUNNER_POOL_SOCKET")
    if not pool_socket_value or not pool_socket_value.endswith(".sock"):
        raise RotationError("command_file_invalid")
    expected_drain_marker = f"{pool_socket_value[:-5]}.drained.json"
    if parsed["--drain-marker"] != expected_drain_marker:
        raise RotationError("command_file_invalid")
    output_dir = Path(parsed["--output-dir"])
    try:
        resolved_output = output_dir.resolve(strict=True)
        output_metadata = output_dir.lstat()
    except OSError as error:
        raise RotationError("command_file_invalid") from error
    if (
        output_dir != resolved_output
        or output_dir.is_symlink()
        or not stat.S_ISDIR(output_metadata.st_mode)
        or output_metadata.st_uid != os.getuid()
        or stat.S_IMODE(output_metadata.st_mode) != 0o700
    ):
        raise RotationError("command_file_invalid")
    if path.parent != resolved_output / "control":
        raise RotationError("command_file_invalid")
    expected_output_paths = {
        "--event-log": resolved_output / "pool_events.jsonl",
        "--wal": resolved_output / "control/sandoq-pool.wal.jsonl",
        "--sanitized-output": resolved_output / "sandoq_cleanup_audit.json",
    }
    if any(Path(parsed[option]) != expected for option, expected in expected_output_paths.items()):
        raise RotationError("command_file_invalid")
    for option in ("--event-log", "--wal"):
        candidate = Path(parsed[option])
        try:
            resolved_candidate = candidate.resolve(strict=os.path.lexists(candidate))
            resolved_candidate.relative_to(resolved_output)
        except (OSError, ValueError) as error:
            raise RotationError("command_file_invalid") from error
        if candidate != resolved_candidate or candidate.is_symlink():
            raise RotationError("command_file_invalid")
        _validate_private_parent(candidate)
        _validate_existing_private_file(candidate, allow_missing=True)
    for option in ("--sanitized-output",):
        candidate = Path(parsed[option]).resolve(strict=False)
        try:
            candidate.relative_to(resolved_output)
        except ValueError as error:
            raise RotationError("command_file_invalid") from error
        if candidate.is_symlink() or os.path.lexists(candidate):
            raise RotationError("command_file_invalid")
    drain_marker = Path(parsed["--drain-marker"])
    pool_socket = Path(pool_socket_value)
    try:
        pool_parent = pool_socket.parent.resolve(strict=True)
        pool_parent_metadata = pool_socket.parent.lstat()
    except OSError as error:
        raise RotationError("command_file_invalid") from error
    if (
        not pool_socket.is_absolute()
        or pool_socket != pool_parent / pool_socket.name
        or pool_socket.parent.is_symlink()
        or not stat.S_ISDIR(pool_parent_metadata.st_mode)
        or pool_parent_metadata.st_uid != os.getuid()
        or stat.S_IMODE(pool_parent_metadata.st_mode) != 0o700
        or drain_marker != pool_parent / drain_marker.name
        or drain_marker.is_symlink()
        or os.path.lexists(drain_marker)
    ):
        raise RotationError("command_file_invalid")
    return value


def _install_stop_handlers(stop: threading.Event) -> None:
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    rotate = subparsers.add_parser("rotate")
    rotate.add_argument("--token-file", type=Path, required=True)
    rotate.add_argument("--state-file", type=Path, required=True)
    rotate.add_argument("--event-log", type=Path, required=True)
    rotate.add_argument("--ucloud-executable", default="ucloud")
    rotate.add_argument("--region", default="us-east-2")
    rotate.add_argument("--client-cert-path", type=Path)
    guard = subparsers.add_parser("guard")
    guard.add_argument("--token-file", type=Path, required=True)
    guard.add_argument("--state-file", type=Path, required=True)
    guard.add_argument("--event-log", type=Path, required=True)
    guard.add_argument("--cleanup-command-json", type=Path, required=True)
    guard.add_argument("evaluator", nargs=argparse.REMAINDER)
    supervised = subparsers.add_parser("exec-supervised")
    supervised.add_argument("evaluator", nargs=argparse.REMAINDER)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--rotator-log", type=Path, required=True)
    audit.add_argument("--guard-log", type=Path, required=True)
    audit.add_argument("--eval-run-identity", type=Path, required=True)
    audit.add_argument("--results", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "rotate":
            if platform.machine().lower() not in {"aarch64", "arm64"}:
                raise RotationError("rotation_service_requires_login_aarch64")
            stop = threading.Event()
            _install_stop_handlers(stop)
            run_rotation_service(
                RotationConfig(
                    token_file=args.token_file,
                    state_file=args.state_file,
                    event_log=args.event_log,
                    client_cert_path=args.client_cert_path,
                    ucloud_executable=args.ucloud_executable,
                    region=args.region,
                ),
                stop_requested=stop.is_set,
            )
        elif args.command == "guard":
            evaluator = list(args.evaluator)
            if evaluator and evaluator[0] == "--":
                evaluator.pop(0)
            stop = threading.Event()
            _install_stop_handlers(stop)
            code = supervise_rollout(
                GuardConfig(
                    token_file=args.token_file,
                    state_file=args.state_file,
                    event_log=args.event_log,
                ),
                evaluator,
                _command_from_json(args.cleanup_command_json),
                stop_requested=stop.is_set,
            )
            raise SystemExit(code)
        elif args.command == "exec-supervised":
            evaluator = list(args.evaluator)
            if evaluator and evaluator[0] == "--":
                evaluator.pop(0)
            exec_supervised_evaluator(evaluator)
        else:
            try:
                from eval_run_identity import EvalIdentityError, load_eval_run_identity

                identity_value = load_eval_run_identity(
                    args.eval_run_identity,
                    verify_references=True,
                )
                identity_sha256 = identity_value["eval_run_identity_sha256"]
                results_sha256 = sha256_regular_streaming(args.results)
            except (KeyError, EvalIdentityError, RotationError) as error:
                raise RotationError("rotation_audit_run_binding_invalid") from error
            value = sanitize_rotation_audit(
                args.rotator_log,
                args.guard_log,
                eval_run_identity_sha256=identity_sha256,
                results_sha256=results_sha256,
            )
            print(write_exclusive(args.output, value))
    except RotationError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
