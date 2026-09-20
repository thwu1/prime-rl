# Copyright (c) Meta Platforms, Inc. and affiliates.

"""vacli-based ToolBackend, side-by-side with the existing DES-backed VMVMBackend.

The DES backend (apps/rl/utils/container_backends/vmvm_backend.py) talks to the
cluster's VMVM pool via `des_exec_cloud`, which inlines every command argument
into argv. That bounds file transfer to ~128 KiB (Linux `MAX_ARG_STRLEN`) and
forces a fresh process per call. This backend leases the same VMVM pool via
`vacli` instead, exposes the VM over an SSH x2p tunnel, and runs every call
through a persistent SSH master connection. Transfers stream over stdin via
`tar`, so file size is bounded only by VM disk.

Drop-in compatibility: `VacliVMVMBackend` and `VacliVMVMBackend_NoServer`
implement the same `ToolBackend` Protocol (and the same concrete
`transfer_file(content, remote_path)` method that `paperbench_dev._SandboxBackend`
relies on) as their DES siblings. Nothing in `vmvm_backend.py`, `des_helper.py`,
or any env code is modified by importing this module.

Memory references this module honors:
- [[vmvm-transport-tar-wins]] — file transfers use tar+ssh, not rsync/scp.
- [[vacli-coreweave-stderr-noise]] — vacli/podman emit ODS telemetry on stderr
  on success; we check exit code only, never stderr content, when deciding
  success/failure of an operation.
- [[vmvm-transfer-arg-max-limit]] — the DES limit this backend exists to escape.
"""

from __future__ import annotations

import asyncio
import atexit
import ctypes
import errno
import fcntl
import functools
import hashlib
import io
import ipaddress
import json
import logging
import math
import os
import re
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from .concurrency_telemetry import TELEMETRY, LeaseStartConcurrencyLimiter
from .session import AsyncSession, SessionOutput
from .types import BackendInitError, BashResult

logger = logging.getLogger(__name__)


# Keep the default on the fleet-supported stable channel. Sealed launchers bind
# the resolved binary and digest so an alias rotation cannot change a live run.
# Keep an escape hatch so a rollout canary can test a candidate build explicitly.
VACLI_BIN = os.environ.get("VACLI_BIN", "/public/fbpkgs/x86_64/vacli/stable/vacli")
DEFAULT_TENANT = "async_2347641"
DEFAULT_LEASE_TTL = "500s"
DEFAULT_TUNNEL_READY_TIMEOUT = 120.0  # seconds to wait for vacli to print tunnel mapping
DEFAULT_SSHD_READY_TIMEOUT = 180.0  # seconds to wait for sshd inside the leased VM
DEFAULT_VACLI_CLEANUP_TIMEOUT = 45.0  # seconds to wait for vacli to release before SIGKILL (measured ~33s)
HOST_MEMORY_HEADROOM_MIB = 512
MAVEN_PROXY_OPTS = (
    "-Dmaven.wagon.http.ssl.insecure=true "
    "-Dmaven.wagon.http.ssl.allowall=true "
    "-Dmaven.wagon.http.ssl.ignore.validity.dates=true "
    "-Dmaven.wagon.http.retryHandler.count=8 "
    "-Dmaven.wagon.http.pool=false"
)

_PR_SET_PDEATHSIG = 1
_VACLI_SPAWN_OWNER_LIVENESS_POLL_SECONDS = 0.1
_VACLI_SPAWN_TIMEOUT_SECONDS = 30.0
_VACLI_FORCED_REAP_TIMEOUT_SECONDS = 5.0
_CONTROL_MASTER_EXIT_TIMEOUT_SECONDS = 10.0
_CONTROL_MASTER_ABSENCE_SECONDS = 2.0
_AF_UNIX_PATH_MAX_BYTES = 107
_ARTIFACT_MUTATION_SIGNALS = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM}
_PDEATHSIG_EXEC_WRAPPER = """\
import ctypes
import os
import signal
import sys

libc = ctypes.CDLL("libc.so.6", use_errno=True)
if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
    os._exit(126)
try:
    if os.getppid() != int(sys.argv[1]):
        raise ValueError
    with open(f"/proc/{int(sys.argv[1])}/task/{int(sys.argv[2])}/stat") as task_stat:
        fields = task_stat.read().rpartition(")")[2].split()
    if len(fields) <= 19 or int(fields[19]) != int(sys.argv[3]):
        raise ValueError
except (OSError, ValueError):
    os._exit(125)
os.execv(sys.argv[4], sys.argv[4:])
"""
try:
    _libc = ctypes.CDLL("libc.so.6", use_errno=True)
except OSError:
    _libc = None


def _child_pdeathsig() -> None:
    """preexec_fn for the vacli child: one prctl syscall (fork-safe).
    PR_SET_PDEATHSIG makes the kernel send this child SIGTERM the moment its
    parent (the process-lifetime spawn thread) dies -- even on a hard SIGKILL
    of the worker process -- so vacli's --release-on-exit fires and the VM is
    freed instead of orphaned.
    """
    if _libc is not None:
        _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)


@dataclass
class _LeaseConcurrencyPermit:
    limiter: Any
    _state: Literal["local", "owner", "lease", "released"] = "local"
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def transfer_to_owner(self) -> None:
        with self._lock:
            if self._state != "local":
                raise RuntimeError(f"cannot transfer {self._state} lease permit to spawn owner")
            self._state = "owner"

    def transfer_to_lease(self) -> None:
        with self._lock:
            if self._state not in ("local", "owner"):
                raise RuntimeError(f"cannot transfer {self._state} lease permit to lease")
            self._state = "lease"

    def release(self) -> None:
        with self._lock:
            if self._state == "released":
                return
            self._state = "released"
        self.limiter.release()

    @property
    def state(self) -> Literal["local", "owner", "lease", "released"]:
        with self._lock:
            return self._state


@dataclass
class _VacliSpawnRequest:
    command: list[str]
    kwargs: dict[str, Any]
    publish: Any
    permit: _LeaseConcurrencyPermit
    cleanup_timeout: float
    ready: threading.Event = field(default_factory=threading.Event)
    resolved: threading.Event = field(default_factory=threading.Event)
    abandoned: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    state: Literal["queued", "spawning", "publishing", "published", "resolved"] = "queued"
    published: bool = False
    process: Any = None
    error: BaseException | None = None


class _VacliSpawnOwner:
    """Own one real vacli child for its complete process lifetime."""

    def __init__(self, pid: int, popen_impl: Any = None) -> None:
        self.pid = pid
        self._popen_impl = subprocess.Popen if popen_impl is None else popen_impl
        self._thread: threading.Thread | None = None

    def popen(
        self,
        command: list[str],
        *,
        publish: Any,
        permit: _LeaseConcurrencyPermit,
        cleanup_timeout: float,
        spawn_timeout: float,
        **kwargs: Any,
    ) -> None:
        if os.getpid() != self.pid:
            _get_vacli_spawn_owner().popen(
                command,
                publish=publish,
                permit=permit,
                cleanup_timeout=cleanup_timeout,
                spawn_timeout=spawn_timeout,
                **kwargs,
            )
            return
        request = _VacliSpawnRequest(command, kwargs, publish, permit, cleanup_timeout)
        owner_thread = threading.Thread(
            target=self._run,
            args=(request,),
            name="vacli-spawn-owner",
            daemon=True,
        )
        self._thread = owner_thread
        deadline = time.monotonic() + spawn_timeout
        try:
            permit.transfer_to_owner()
            owner_thread.start()
            if not self._wait_until_ready(request, owner_thread, deadline):
                if not owner_thread.is_alive():
                    raise RuntimeError("vacli spawn owner exited before process creation completed")
                raise TimeoutError(f"vacli process creation exceeded {spawn_timeout}s")
            if request.error is not None:
                raise request.error
        except BaseException:
            self._abandon_and_wait(request, owner_thread, deadline)
            if not owner_thread.is_alive():
                permit.release()
            raise

    def _run(self, request: _VacliSpawnRequest) -> None:
        process = None
        try:
            with request.lock:
                if request.abandoned.is_set():
                    return
                request.state = "spawning"
            parent_tid = threading.get_native_id()
            parent_start_ticks = _task_start_ticks(self.pid, parent_tid)
            wrapped_command = _pdeathsig_exec_command(
                request.command,
                self.pid,
                parent_tid,
                parent_start_ticks,
            )
            process = self._popen_impl(wrapped_command, **request.kwargs)
            with request.lock:
                request.process = process
                request.state = "publishing"
            with request.lock:
                if not request.abandoned.is_set():
                    request.publish(process, request.permit)
                    request.published = True
                    request.state = "published"
            request.ready.set()
            if request.abandoned.is_set() or not request.published:
                _terminate_and_reap_spawned_vacli(process, request.cleanup_timeout)
                return
            while process.poll() is None:
                if request.abandoned.wait(_VACLI_SPAWN_OWNER_LIVENESS_POLL_SECONDS):
                    _terminate_and_reap_spawned_vacli(process, request.cleanup_timeout)
                    return
        except BaseException as error:
            request.error = error
            request.ready.set()
            if process is not None:
                _terminate_and_reap_spawned_vacli(process, request.cleanup_timeout)
        finally:
            with request.lock:
                request.state = "resolved"
            request.permit.release()
            request.ready.set()
            request.resolved.set()

    def _wait_until_ready(
        self,
        request: _VacliSpawnRequest,
        owner_thread: threading.Thread,
        deadline: float,
    ) -> bool:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return request.ready.is_set()
            if request.ready.wait(min(_VACLI_SPAWN_OWNER_LIVENESS_POLL_SECONDS, remaining)):
                return True
            if not owner_thread.is_alive():
                return request.ready.is_set()

    def _abandon_and_wait(
        self,
        request: _VacliSpawnRequest,
        owner_thread: threading.Thread,
        spawn_deadline: float,
    ) -> None:
        while True:
            try:
                with request.lock:
                    request.abandoned.set()
                break
            except BaseException:
                continue
        resolution_deadline = spawn_deadline
        cleanup_deadline_set = False
        while not request.resolved.is_set():
            if request.ready.is_set() and not cleanup_deadline_set:
                resolution_deadline = max(
                    resolution_deadline,
                    time.monotonic() + request.cleanup_timeout + _VACLI_FORCED_REAP_TIMEOUT_SECONDS,
                )
                cleanup_deadline_set = True
            remaining = resolution_deadline - time.monotonic()
            if remaining <= 0 or not owner_thread.is_alive():
                return
            try:
                request.resolved.wait(min(_VACLI_SPAWN_OWNER_LIVENESS_POLL_SECONDS, remaining))
            except BaseException:
                continue


def _task_start_ticks(pid: int, tid: int) -> int:
    fields = Path(f"/proc/{pid}/task/{tid}/stat").read_text().rpartition(")")[2].split()
    if len(fields) <= 19:
        raise RuntimeError("unable to read vacli spawn-owner thread identity")
    return int(fields[19])


def _pdeathsig_exec_command(
    command: list[str],
    parent_pid: int,
    parent_tid: int,
    parent_start_ticks: int | None = None,
) -> list[str]:
    if parent_start_ticks is None:
        parent_start_ticks = _task_start_ticks(parent_pid, parent_tid)
    return [
        sys.executable,
        "-I",
        "-S",
        "-B",
        "-c",
        _PDEATHSIG_EXEC_WRAPPER,
        str(parent_pid),
        str(parent_tid),
        str(parent_start_ticks),
        *command,
    ]


def _terminate_and_reap_spawned_vacli(process: Any, cleanup_timeout: float) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=max(0.0, cleanup_timeout))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=_VACLI_FORCED_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        logger.error("vacli spawn owner could not reap PID %d after SIGKILL", process.pid)


def _get_vacli_spawn_owner() -> _VacliSpawnOwner:
    return _VacliSpawnOwner(os.getpid())


def _popen_vacli(
    command: list[str],
    stdout: Any,
    subprocess_mod: Any,
    publish: Any,
    permit: _LeaseConcurrencyPermit,
    cleanup_timeout: float,
) -> None:
    kwargs = dict(stdout=stdout, stderr=subprocess_mod.STDOUT, process_group=0)
    if subprocess_mod is subprocess:
        _get_vacli_spawn_owner().popen(
            command,
            publish=publish,
            permit=permit,
            cleanup_timeout=cleanup_timeout,
            spawn_timeout=_VACLI_SPAWN_TIMEOUT_SECONDS,
            **kwargs,
        )
        return
    publish(subprocess_mod.Popen(command, **kwargs), permit)


# Cap concurrent in-flight vacli leases per process: bursts of simultaneous
# lease attempts trigger FAAS tunnel-setup timeouts. Tune via env if needed.
MAX_CONCURRENT_LEASES = int(os.environ.get("VACLI_MAX_CONCURRENT_LEASES", "16"))
# Retries for `podman pull` inside the VM when DockerHub returns 429
# (toomanyrequests). The vmvm-registry mirror path needs no retries; this only
# matters for the docker.io fallback used when an image is not yet mirrored.
MAX_PULL_RETRIES = int(os.environ.get("VACLI_MAX_PULL_RETRIES", "20"))
IMAGE_PULL_TIMEOUT_SECONDS = int(os.environ.get("VACLI_IMAGE_PULL_TIMEOUT_SECONDS", "350"))
CONTAINER_PRIVILEGED = os.environ.get("VACLI_CONTAINER_PRIVILEGED", "0") == "1"
if IMAGE_PULL_TIMEOUT_SECONDS <= 0:
    raise ValueError("VACLI_IMAGE_PULL_TIMEOUT_SECONDS must be positive")
# Retries for the vacli lease bring-up itself. Concurrent launches race on
# Configerator/JustKnobs init ("isConfigeratorAvailable() returned false" ->
# "vacli died before tunnel was ready"), a transient thundering-herd failure at
# high concurrency; jittered retry disperses the herd. See [[vacli-lease-race]].
MAX_LEASE_RETRIES = int(os.environ.get("VACLI_LEASE_RETRIES", "20"))


_THREADED_CHILD_WATCHER = None


def _install_threaded_child_watcher() -> None:
    """Make asyncio.get_child_watcher() return a stdlib ThreadedChildWatcher.

    prime-rl installs uvloop as the global policy. uvloop's policy.get_child_watcher()
    raises NotImplementedError, so a stdlib SelectorEventLoop (which we use for the
    session loops) cannot spawn subprocesses (_make_subprocess_transport calls the
    global get_child_watcher()). ThreadedChildWatcher is loop-agnostic and thread-safe
    (one waiter thread per child), so it drives our SelectorEventLoops at high
    concurrency. uvloop's own loops never call get_child_watcher(), so this is a
    no-op for them. Idempotent; installed once.
    """
    global _THREADED_CHILD_WATCHER
    if _THREADED_CHILD_WATCHER is not None:
        return
    _THREADED_CHILD_WATCHER = asyncio.ThreadedChildWatcher()

    def _get_watcher():
        return _THREADED_CHILD_WATCHER

    asyncio.events.get_child_watcher = _get_watcher
    asyncio.get_child_watcher = _get_watcher


_lease_concurrency = LeaseStartConcurrencyLimiter(MAX_CONCURRENT_LEASES, TELEMETRY)

# Tunnel mapping line emitted by vacli on stdout, e.g.:
# [{"vm_port":22,"local_port":10000}]
_TUNNEL_RE = re.compile(r'\[\s*\{[^]]*"vm_port"\s*:\s*22[^]]*\}\s*\]')

# Container IDs come from parsing untrusted stdout (podman over ssh); we
# interpolate them into shell commands below, so reject anything that isn't
# the expected hex form before storing.
_CONTAINER_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def _vacli_lease_identity_sha256(lease_response: str) -> str:
    """Hash only vacli's real session identity, never a container or local name."""
    try:
        response = json.loads(lease_response)
    except (json.JSONDecodeError, TypeError) as error:
        raise BackendInitError("vacli returned an invalid lease response") from error
    if not isinstance(response, dict) or not isinstance(response.get("auth_token"), dict):
        raise BackendInitError("vacli returned an invalid lease response")
    session_id = response.get("sessionId")
    if not isinstance(session_id, dict) or not session_id:
        raise BackendInitError("vacli returned an invalid session identity")
    try:
        canonical = json.dumps(
            session_id,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        raise BackendInitError("vacli returned an invalid session identity") from error
    return hashlib.sha256(b"vacli-session-identity-v1\0" + canonical).hexdigest()


def _extract_vacli_lease_response(line: str) -> tuple[str, str] | None:
    """Extract a complete LeaseVmResponse JSON object from one vacli log line."""
    decoder = json.JSONDecoder()
    for offset, character in enumerate(line):
        if character != "{":
            continue
        try:
            response, end = decoder.raw_decode(line, offset)
        except json.JSONDecodeError:
            continue
        if not isinstance(response, dict) or "sessionId" not in response or "auth_token" not in response:
            continue
        serialized = line[offset:end]
        return serialized, _vacli_lease_identity_sha256(serialized)
    return None


def _validate_container_id(cid: str) -> str:
    if not _CONTAINER_ID_RE.match(cid):
        raise BackendInitError(f"podman returned malformed container id (expected hex): {cid!r}")
    return cid


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VacliVMVMConfig:
    """Configuration for `VacliVMVMBackend` (server-backed equivalent of `VMVMConfig`).

    `image_url` is required to match `VMVMConfig`'s shape — a bare-VM variant
    (no podman, ssh directly) could be added later without breaking this signature.
    """

    image_url: str
    work_dir: str
    session_timeout: float
    # Secondary image tried if `image_url` fails to pull (docker.io fallback
    # for tasks not mirrored into vmvm-registry).
    fallback_image_url: str | None = None
    start_script: str = ""
    entrypoint_script: str = ""
    tenant_id: str = DEFAULT_TENANT
    lease_ttl: str = DEFAULT_LEASE_TTL
    tunnel_ready_timeout: float = DEFAULT_TUNNEL_READY_TIMEOUT
    sshd_ready_timeout: float = DEFAULT_SSHD_READY_TIMEOUT
    client_id: str = "cwm_rl"
    cpu: float | None = None
    memory_gb: float | None = None
    # Override the AsyncSession per-command stdout buffer cap (bytes). None
    # means use the AsyncSession default (480 KB). Bump this for callers that
    # legitimately need to read large bash outputs in one call — e.g.
    # paperbench_dev streams its submission tarball through `tar | base64` and
    # easily exceeds 480 KB for larger submissions. Setting this here doesn't
    # affect any other AsyncSession user (the cap is per-instance).
    max_session_buffer_size: int | None = None
    provisioning_cancel_event: threading.Event | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    # Test seam: lets unit tests inject a stub `subprocess`-shaped namespace
    # (must expose `Popen`, `run`, `PIPE`, `DEVNULL`, `STDOUT`, `TimeoutExpired`)
    # so we never spawn real vacli/ssh. Production: leave None → real subprocess.
    subprocess_mod: Any = None


@dataclass(frozen=True)
class VacliHostTunnel:
    gateway: str
    remote_port: int
    local_port: int
    relay_pid: int


@dataclass
class _VacliNetworkIsolation:
    """Host-side state for one workload's private Podman network."""

    network: str
    gateway: str
    subnet: str
    main_address: str
    firewall_chain: str
    containers: tuple[str, ...]
    active: bool = False
    firewall_active: bool = False
    allowed_tunnel_ports: set[int] = field(default_factory=set)


@dataclass
class _VacliRestartFlight:
    completed: threading.Event = field(default_factory=threading.Event)
    result: int | None = None


class _ArtifactCleanupError(RuntimeError):
    """A backend-owned local artifact could not be safely retired."""


class _ControlNotReady(_ArtifactCleanupError):
    """The creation-bound OpenSSH master has not published its socket yet."""


@dataclass
class _ControlBinding:
    identity: tuple[int, int, int, int, int]
    descriptor: int
    close_indeterminate: bool = False


@dataclass
class _OwnedControlArtifact:
    name: str
    ports: set[int] = field(default_factory=set)
    process: Any = None
    process_reaped: bool = False
    binding: _ControlBinding | None = None
    verified_absent: bool = False
    retained_inert: bool = False


@dataclass
class _LogBinding:
    identity: tuple[int, int, int, int, int]
    descriptor: int
    close_indeterminate: bool = False


@dataclass
class _OwnedLogArtifact:
    name: str
    binding: _LogBinding | None = None
    verified_absent: bool = False
    sanitized_retained: bool = False


def _close_artifact_descriptors(
    controls: dict[str, _OwnedControlArtifact],
    logs: dict[str, _OwnedLogArtifact],
) -> None:
    """Close only retained FDs when an abandoned registry becomes unreachable."""
    for record in controls.values():
        binding = record.binding
        if binding is None or binding.descriptor < 0:
            continue
        descriptor = binding.descriptor
        binding.descriptor = -1
        try:
            os.close(descriptor)
        except OSError:
            pass
    for record in logs.values():
        binding = record.binding
        if binding is None or binding.descriptor < 0:
            continue
        descriptor = binding.descriptor
        binding.descriptor = -1
        try:
            os.close(descriptor)
        except OSError:
            pass


class _VacliLocalArtifacts:
    """Own every local ControlMaster socket and vacli log for one backend."""

    def __init__(self, root: Path, subprocess_mod: Any) -> None:
        self.root = root.resolve(strict=True)
        self._sp = subprocess_mod
        self._lock = threading.RLock()
        self._sealed = False
        root_fd = self._open_root_unbound()
        try:
            info = os.fstat(root_fd)
            self._root_identity = (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid)
        finally:
            os.close(root_fd)
        control_leaf = f"vacli_ctl_{os.getpid()}_{'0' * 32}"
        self._control_root = self.root
        if len(os.fsencode(str(self._control_root / control_leaf))) > _AF_UNIX_PATH_MAX_BYTES:
            self._control_root = Path("/tmp").resolve(strict=True)
        if len(os.fsencode(str(self._control_root / control_leaf))) > _AF_UNIX_PATH_MAX_BYTES:
            raise _ArtifactCleanupError("vacli control path exceeds the AF_UNIX path limit")
        control_root_fd = self._open_root_unbound(self._control_root)
        try:
            info = os.fstat(control_root_fd)
            self._control_root_identity = (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid)
        finally:
            os.close(control_root_fd)
        self._controls: dict[str, _OwnedControlArtifact] = {}
        self._logs: dict[str, _OwnedLogArtifact] = {}
        self._descriptor_finalizer = weakref.finalize(
            self,
            _close_artifact_descriptors,
            self._controls,
            self._logs,
        )

    def _open_root_unbound(self, root: Path | None = None) -> int:
        selected_root = self.root if root is None else root
        try:
            descriptor = os.open(
                selected_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        except OSError as error:
            raise _ArtifactCleanupError("vacli artifact root is unavailable") from error
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            os.close(descriptor)
            raise _ArtifactCleanupError("vacli artifact root identity is invalid")
        return descriptor

    def _open_root(self) -> int:
        descriptor = self._open_root_unbound()
        info = os.fstat(descriptor)
        observed = (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid)
        if observed != self._root_identity:
            os.close(descriptor)
            raise _ArtifactCleanupError("vacli artifact root identity changed")
        return descriptor

    def _open_control_root(self) -> int:
        descriptor = self._open_root_unbound(self._control_root)
        info = os.fstat(descriptor)
        observed = (info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid)
        if observed != self._control_root_identity:
            os.close(descriptor)
            raise _ArtifactCleanupError("vacli control root identity changed")
        return descriptor

    def _name(self, path: Path | str) -> str:
        candidate = Path(path)
        if candidate.parent != self.root or not candidate.name or "/" in candidate.name:
            raise _ArtifactCleanupError("vacli artifact path escaped its root")
        return candidate.name

    def new_attempt_paths(self) -> tuple[str, Path]:
        with self._lock:
            if self._sealed:
                raise _ArtifactCleanupError("vacli artifact registry is sealed")
            nonce = uuid.uuid4().hex
            control = self._control_root / f"vacli_ctl_{os.getpid()}_{nonce}"
            log = self.root / f"vacli_lease_{os.getpid()}_{nonce}.log"
            if len(os.fsencode(str(control))) > _AF_UNIX_PATH_MAX_BYTES:
                raise _ArtifactCleanupError("vacli control path exceeds the AF_UNIX path limit")
            if str(control) in self._controls or str(log) in self._logs:
                raise _ArtifactCleanupError("vacli artifact nonce was reused")
            control_root_fd = self._open_control_root()
            log_root_fd = self._open_root()
            try:
                for descriptor, name in (
                    (control_root_fd, control.name),
                    (log_root_fd, log.name),
                ):
                    try:
                        os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    raise _ArtifactCleanupError("vacli artifact name already exists")
            finally:
                os.close(log_root_fd)
                os.close(control_root_fd)
            self._controls[str(control)] = _OwnedControlArtifact(control.name)
            self._logs[str(log)] = _OwnedLogArtifact(log.name)
            return str(control), log

    def new_control_path(self) -> str:
        with self._lock:
            if self._sealed:
                raise _ArtifactCleanupError("vacli artifact registry is sealed")
            for _attempt in range(8):
                control = self._control_root / f"vacli_ctl_{os.getpid()}_{uuid.uuid4().hex}"
                if len(os.fsencode(str(control))) > _AF_UNIX_PATH_MAX_BYTES:
                    raise _ArtifactCleanupError("vacli control path exceeds the AF_UNIX path limit")
                if str(control) in self._controls:
                    continue
                root_fd = self._open_control_root()
                try:
                    try:
                        os.stat(control.name, dir_fd=root_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        self._controls[str(control)] = _OwnedControlArtifact(control.name)
                        return str(control)
                finally:
                    os.close(root_fd)
            raise _ArtifactCleanupError("vacli control nonce allocation failed")

    def start_control(self, path: str, command: list[str]) -> Any:
        """Spawn and publish the exact foreground OpenSSH master we own."""
        with self._lock:
            if self._sealed:
                raise _ArtifactCleanupError("vacli artifact registry is sealed")
            record = self._controls.get(path)
            if record is None or record.process is not None or record.binding is not None:
                raise _ArtifactCleanupError("vacli control process was not reserved exactly once")
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _ARTIFACT_MUTATION_SIGNALS)
            process = None
            try:
                process = self._sp.Popen(
                    command,
                    stdin=self._sp.DEVNULL,
                    stdout=self._sp.DEVNULL,
                    stderr=self._sp.DEVNULL,
                    start_new_session=True,
                )
                if type(getattr(process, "pid", None)) is not int or process.pid <= 1 or process.pid == os.getpid():
                    raise _ArtifactCleanupError("vacli control process identity is invalid")
                record.process = process
                return process
            finally:
                cleanup_error: BaseException | None = None
                if process is not None and record.process is not process:
                    try:
                        if (
                            type(getattr(process, "pid", None)) is int
                            and process.pid > 1
                            and process.pid != os.getpid()
                        ):
                            process.kill()
                            process.wait(timeout=_CONTROL_MASTER_EXIT_TIMEOUT_SECONDS)
                    except (OSError, ProcessLookupError, self._sp.TimeoutExpired) as error:
                        cleanup_error = error
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
                except BaseException as error:
                    cleanup_error = cleanup_error or error
                if cleanup_error is not None:
                    raise cleanup_error

    @staticmethod
    def _control_peer_pid(descriptor: int) -> tuple[int, int]:
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            peer.settimeout(_CONTROL_MASTER_EXIT_TIMEOUT_SECONDS)
            peer.connect(f"/proc/self/fd/{descriptor}")
            raw = peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        except OSError as error:
            if error.errno in {errno.ECONNREFUSED, errno.ENOENT}:
                raise _ControlNotReady("vacli control master is not ready") from error
            raise _ArtifactCleanupError("vacli control master is unavailable") from error
        finally:
            peer.close()
        pid, uid, _gid = struct.unpack("3i", raw)
        if pid <= 1 or uid != os.getuid():
            raise _ArtifactCleanupError("vacli control master identity is invalid")
        return pid, uid

    def bind_control(self, path: str, *, required: bool = True) -> bool:
        """Bind the socket inode and owning process created by SSH."""
        with self._lock:
            if self._sealed:
                raise _ArtifactCleanupError("vacli artifact registry is sealed")
            record = self._controls.get(path)
            if record is None:
                raise _ArtifactCleanupError("vacli control path was not reserved")
            if record.verified_absent or record.retained_inert:
                if required:
                    raise _ArtifactCleanupError("vacli control path was already retired")
                root_fd = self._open_control_root()
                try:
                    if record.verified_absent:
                        if not self._stable_absence(root_fd, record.name):
                            raise _ArtifactCleanupError("vacli control path reappeared")
                    else:
                        self._validate_retained_control(root_fd, record)
                finally:
                    os.close(root_fd)
                return False
            process = record.process
            if process is None:
                root_fd = self._open_control_root()
                try:
                    if not required and self._stable_absence(root_fd, record.name):
                        return False
                finally:
                    os.close(root_fd)
                raise _ArtifactCleanupError("vacli control process was not started")
            if record.binding is not None:
                binding = record.binding
                current = self._control_identity(binding)
                if current[:4] != binding.identity[:4]:
                    raise _ArtifactCleanupError("vacli control binding changed")
                root_fd = self._open_control_root()
                try:
                    named = self._optional_stat(root_fd, record.name)
                    if current[4] == 0:
                        if named is not None:
                            raise _ArtifactCleanupError("vacli control path was replaced")
                    elif named is None or self._leaf_identity(named, stat.S_IFSOCK) != binding.identity:
                        raise _ArtifactCleanupError("vacli control path was replaced")
                finally:
                    os.close(root_fd)
                return True

            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _ARTIFACT_MUTATION_SIGNALS)
            root_fd = -1
            descriptor = -1
            binding: _ControlBinding | None = None
            try:
                root_fd = self._open_control_root()
                try:
                    descriptor = os.open(
                        record.name,
                        os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=root_fd,
                    )
                except FileNotFoundError:
                    if required:
                        raise _ArtifactCleanupError("vacli control socket was not created")
                    return False
                identity = self._leaf_identity(os.fstat(descriptor), stat.S_IFSOCK)
                named = os.stat(record.name, dir_fd=root_fd, follow_symlinks=False)
                if self._leaf_identity(named, stat.S_IFSOCK) != identity:
                    raise _ArtifactCleanupError("vacli control path was replaced")
                if process.poll() is not None:
                    raise _ArtifactCleanupError("vacli control master exited before binding")
                pid, _uid = self._control_peer_pid(descriptor)
                if pid != process.pid or process.poll() is not None:
                    raise _ArtifactCleanupError("vacli control master ownership mismatch")
                named = os.stat(record.name, dir_fd=root_fd, follow_symlinks=False)
                if self._leaf_identity(named, stat.S_IFSOCK) != identity:
                    raise _ArtifactCleanupError("vacli control path was replaced while binding")
                binding = _ControlBinding(identity, descriptor)
                record.binding = binding
                return True
            finally:
                cleanup_error: BaseException | None = None
                if (binding is None or record.binding is not binding) and descriptor >= 0:
                    descriptor_to_close = descriptor
                    descriptor = -1
                    try:
                        os.close(descriptor_to_close)
                    except OSError as error:
                        cleanup_error = error
                if root_fd >= 0:
                    root_to_close = root_fd
                    root_fd = -1
                    try:
                        os.close(root_to_close)
                    except OSError as error:
                        cleanup_error = cleanup_error or error
                try:
                    signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
                except BaseException as error:
                    cleanup_error = cleanup_error or error
                if cleanup_error is not None:
                    raise cleanup_error

    def register_resume_log(self, path: Path) -> None:
        with self._lock:
            if self._sealed:
                raise _ArtifactCleanupError("vacli artifact registry is sealed")
            name = self._name(path)
            if str(path) in self._logs:
                raise _ArtifactCleanupError("vacli log path was reused")
            self._logs[str(path)] = _OwnedLogArtifact(name)

    def open_log(self, path: Path) -> Any:
        with self._lock:
            if self._sealed:
                raise _ArtifactCleanupError("vacli artifact registry is sealed")
            record = self._logs.get(str(path))
            if record is None or record.binding is not None or record.verified_absent:
                raise _ArtifactCleanupError("vacli log path was not reserved exactly once")
            root_fd = self._open_root()
            descriptor = -1
            retained_descriptor = -1
            binding: _LogBinding | None = None
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _ARTIFACT_MUTATION_SIGNALS)
            try:
                descriptor = os.open(
                    record.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=root_fd,
                )
                info = os.fstat(descriptor)
                identity = self._leaf_identity(info, stat.S_IFREG, expected_mode=0o600)
                named = os.stat(record.name, dir_fd=root_fd, follow_symlinks=False)
                if self._leaf_identity(named, stat.S_IFREG, expected_mode=0o600) != identity:
                    raise _ArtifactCleanupError("vacli log identity is invalid")
                retained_descriptor = fcntl.fcntl(descriptor, fcntl.F_DUPFD_CLOEXEC, 0)
                binding = _LogBinding(identity, retained_descriptor)
                record.binding = binding
                stream = os.fdopen(descriptor, "wb")
                descriptor = -1
                return stream
            except BaseException:
                raise
            finally:
                cleanup_error: BaseException | None = None
                try:
                    if binding is None or record.binding is not binding:
                        if retained_descriptor >= 0:
                            retained_to_close = retained_descriptor
                            retained_descriptor = -1
                            try:
                                os.close(retained_to_close)
                            except OSError as error:
                                cleanup_error = error
                    if descriptor >= 0:
                        descriptor_to_close = descriptor
                        descriptor = -1
                        try:
                            os.close(descriptor_to_close)
                        except OSError as error:
                            cleanup_error = cleanup_error or error
                    root_to_close = root_fd
                    root_fd = -1
                    try:
                        os.close(root_to_close)
                    except OSError as error:
                        cleanup_error = cleanup_error or error
                finally:
                    try:
                        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
                    except BaseException as error:
                        cleanup_error = cleanup_error or error
                if cleanup_error is not None:
                    raise cleanup_error

    def record_control_port(self, path: str, port: int) -> None:
        with self._lock:
            if self._sealed or type(port) is not int or not 0 < port <= 65_535:
                raise _ArtifactCleanupError("vacli control endpoint is invalid")
            record = self._controls.get(path)
            if record is None:
                raise _ArtifactCleanupError("vacli control path was not reserved")
            record.ports.add(port)

    def seal(self) -> None:
        with self._lock:
            self._sealed = True

    @property
    def sealed(self) -> bool:
        with self._lock:
            return self._sealed

    @staticmethod
    def _leaf_identity(
        info: os.stat_result,
        expected_type: int,
        *,
        expected_mode: int | None = None,
    ) -> tuple[int, int, int, int, int]:
        identity = (
            info.st_dev,
            info.st_ino,
            stat.S_IMODE(info.st_mode),
            info.st_uid,
            info.st_nlink,
        )
        if (
            stat.S_IFMT(info.st_mode) != expected_type
            or identity[3:] != (os.getuid(), 1)
            or (expected_mode is not None and identity[2] != expected_mode)
        ):
            raise _ArtifactCleanupError("vacli artifact identity is invalid")
        return identity

    def _path_absent(self, root_fd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return True
        return False

    def _stable_absence(self, root_fd: int, name: str) -> bool:
        deadline = time.monotonic() + _CONTROL_MASTER_ABSENCE_SECONDS
        while time.monotonic() < deadline:
            if not self._path_absent(root_fd, name):
                return False
            time.sleep(min(0.1, deadline - time.monotonic()))
        return self._path_absent(root_fd, name)

    @staticmethod
    def _close_bound_descriptor(binding: _ControlBinding | _LogBinding) -> None:
        if binding.descriptor < 0 or binding.close_indeterminate:
            raise _ArtifactCleanupError("vacli artifact descriptor close state is indeterminate")
        descriptor = binding.descriptor
        binding.descriptor = -1
        binding.close_indeterminate = True
        try:
            os.close(descriptor)
        except OSError as error:
            raise _ArtifactCleanupError("vacli artifact descriptor close was not verified") from error
        binding.close_indeterminate = False

    def cleanup_controls(self, selected: set[str] | None = None) -> None:
        with self._lock:
            root_fd = self._open_control_root()
            try:
                for path, record in self._controls.items():
                    if selected is not None and path not in selected:
                        continue
                    if record.verified_absent:
                        if (
                            record.binding is not None
                            or (record.process is not None and not record.process_reaped)
                            or not self._stable_absence(root_fd, record.name)
                        ):
                            raise _ArtifactCleanupError("vacli control path reappeared")
                        continue
                    if record.retained_inert:
                        self._validate_retained_control(root_fd, record)
                        continue
                    self._cleanup_control_record(root_fd, record)
            finally:
                os.close(root_fd)

    def _stop_control_process(self, record: _OwnedControlArtifact) -> None:
        process = record.process
        if process is None:
            return
        if record.process_reaped:
            if process.poll() is None:
                raise _ArtifactCleanupError("vacli control master reap state changed")
            return
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _ARTIFACT_MUTATION_SIGNALS)
        try:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=_CONTROL_MASTER_EXIT_TIMEOUT_SECONDS)
            except self._sp.TimeoutExpired as error:
                raise _ArtifactCleanupError("vacli control master did not exit") from error
            if process.poll() is None:
                raise _ArtifactCleanupError("vacli control master exit was not verified")
            record.process_reaped = True
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    @staticmethod
    def _control_socket_accepts(path: str) -> bool:
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            peer.settimeout(0.25)
            peer.connect(path)
            return True
        except OSError as error:
            if error.errno in {errno.ECONNREFUSED, errno.ENOENT}:
                return False
            raise _ArtifactCleanupError("vacli control socket liveness is ambiguous") from error
        finally:
            peer.close()

    def _control_identity(self, binding: _ControlBinding) -> tuple[int, int, int, int, int]:
        if binding.descriptor < 0 or binding.close_indeterminate:
            raise _ArtifactCleanupError("vacli control descriptor is unavailable")
        info = os.fstat(binding.descriptor)
        identity = (
            info.st_dev,
            info.st_ino,
            stat.S_IMODE(info.st_mode),
            info.st_uid,
            info.st_nlink,
        )
        if stat.S_IFMT(info.st_mode) != stat.S_IFSOCK or info.st_uid != os.getuid() or info.st_nlink not in {0, 1}:
            raise _ArtifactCleanupError("vacli control socket identity is invalid")
        return identity

    def _validate_retained_control(self, root_fd: int, record: _OwnedControlArtifact) -> None:
        binding = record.binding
        if (
            binding is None
            or binding.descriptor >= 0
            or binding.close_indeterminate
            or not record.process_reaped
            or record.process is None
            or record.process.poll() is None
        ):
            raise _ArtifactCleanupError("vacli retained control master was not reaped")
        named = self._optional_stat(root_fd, record.name)
        if named is None:
            raise _ArtifactCleanupError("vacli retained control socket disappeared")
        if self._leaf_identity(named, stat.S_IFSOCK) != binding.identity:
            raise _ArtifactCleanupError("vacli retained control socket was replaced")
        path = str(self._control_root / record.name)
        if self._control_socket_accepts(path):
            raise _ArtifactCleanupError("vacli retained control socket is still active")
        repeated = os.stat(record.name, dir_fd=root_fd, follow_symlinks=False)
        if self._leaf_identity(repeated, stat.S_IFSOCK) != binding.identity:
            raise _ArtifactCleanupError("vacli retained control socket changed during validation")

    def _cleanup_control_record(
        self,
        root_fd: int,
        record: _OwnedControlArtifact,
    ) -> None:
        self._stop_control_process(record)
        binding = record.binding
        if binding is None:
            observed = self._optional_stat(root_fd, record.name)
            if observed is None:
                if self._stable_absence(root_fd, record.name):
                    record.verified_absent = True
                    return
                raise _ArtifactCleanupError("owned vacli control path disappeared")
            raise _ArtifactCleanupError("unbound vacli control occupied a reserved path")
        if not record.ports:
            raise _ArtifactCleanupError("vacli control endpoint was never recorded")
        current = self._control_identity(binding)
        if current[:4] != binding.identity[:4] or current[4] not in {0, 1}:
            raise _ArtifactCleanupError("vacli control socket identity changed")
        named = self._optional_stat(root_fd, record.name)
        if current[4] == 0:
            if named is not None or not self._stable_absence(root_fd, record.name):
                raise _ArtifactCleanupError("vacli control path was replaced")
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _ARTIFACT_MUTATION_SIGNALS)
            try:
                self._close_bound_descriptor(binding)
                record.binding = None
                record.verified_absent = True
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            return
        if named is None or self._leaf_identity(named, stat.S_IFSOCK) != binding.identity:
            raise _ArtifactCleanupError("vacli control path was replaced")
        path = str(self._control_root / record.name)
        if self._control_socket_accepts(path):
            raise _ArtifactCleanupError("vacli control socket remained active after owner reap")
        repeated = self._control_identity(binding)
        named = self._optional_stat(root_fd, record.name)
        if repeated != binding.identity or named is None:
            raise _ArtifactCleanupError("vacli control socket changed during retirement")
        if self._leaf_identity(named, stat.S_IFSOCK) != binding.identity:
            raise _ArtifactCleanupError("vacli control socket was replaced during retirement")
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _ARTIFACT_MUTATION_SIGNALS)
        try:
            self._close_bound_descriptor(binding)
            record.retained_inert = True
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    def cleanup_logs(self, selected: set[str] | None = None) -> None:
        with self._lock:
            root_fd = self._open_root()
            try:
                for path, record in self._logs.items():
                    if selected is not None and path not in selected:
                        continue
                    if record.verified_absent:
                        if not self._stable_absence(root_fd, record.name):
                            raise _ArtifactCleanupError("vacli log path reappeared")
                        continue
                    if record.sanitized_retained:
                        self._validate_sanitized_log(root_fd, record)
                        continue
                    if record.binding is None:
                        if self._stable_absence(root_fd, record.name):
                            record.verified_absent = True
                            continue
                        raise _ArtifactCleanupError("unowned vacli log occupied a reserved path")
                    self._cleanup_log_record(root_fd, record)
            finally:
                os.close(root_fd)

    def _optional_stat(self, root_fd: int, name: str) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def _validate_sanitized_log(self, root_fd: int, record: _OwnedLogArtifact) -> None:
        binding = record.binding
        if binding is None or binding.close_indeterminate:
            raise _ArtifactCleanupError("vacli sanitized log descriptor is unavailable")
        named = self._optional_stat(root_fd, record.name)
        if binding.descriptor >= 0:
            info = os.fstat(binding.descriptor)
            current = self._leaf_identity(info, stat.S_IFREG, expected_mode=0o600)
            if current != binding.identity or info.st_size != 0:
                raise _ArtifactCleanupError("vacli sanitized log descriptor changed")
        if (
            named is None
            or self._leaf_identity(named, stat.S_IFREG, expected_mode=0o600) != binding.identity
            or named.st_size != 0
        ):
            raise _ArtifactCleanupError("vacli sanitized log identity changed")

    def _cleanup_log_record(self, root_fd: int, record: _OwnedLogArtifact) -> None:
        binding = record.binding
        if binding is None or binding.descriptor < 0 or binding.close_indeterminate:
            raise _ArtifactCleanupError("owned vacli log descriptor is unavailable")
        before = os.fstat(binding.descriptor)
        if self._leaf_identity(before, stat.S_IFREG, expected_mode=0o600) != binding.identity:
            raise _ArtifactCleanupError("owned vacli log identity changed")
        os.ftruncate(binding.descriptor, 0)
        os.fsync(binding.descriptor)
        after = os.fstat(binding.descriptor)
        if self._leaf_identity(after, stat.S_IFREG, expected_mode=0o600) != binding.identity or after.st_size != 0:
            raise _ArtifactCleanupError("owned vacli log sanitization was not verified")
        named = self._optional_stat(root_fd, record.name)
        if named is None or self._leaf_identity(named, stat.S_IFREG, expected_mode=0o600) != binding.identity:
            raise _ArtifactCleanupError("owned vacli log was moved or replaced")
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, _ARTIFACT_MUTATION_SIGNALS)
        try:
            self._close_bound_descriptor(binding)
            record.sanitized_retained = True
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def _lifecycle_serialized(method: Any) -> Any:
    """Keep one admitted backend operation ahead of destructive teardown."""

    @functools.wraps(method)
    def locked(self: Any, *args: Any, **kwargs: Any) -> Any:
        destroy_requested = getattr(self, "_destroy_requested", None)
        if destroy_requested is not None and destroy_requested.is_set() and not getattr(self, "_destroying", False):
            raise RuntimeError("VMVM operation rejected while destruction is pending")
        with self._lifecycle_lock:
            if destroy_requested is not None and destroy_requested.is_set() and not getattr(self, "_destroying", False):
                raise RuntimeError("VMVM operation rejected while destruction is pending")
            cancel_requested = getattr(self, "_command_cancel_requested", None)
            if cancel_requested is not None and cancel_requested.is_set() and not getattr(self, "_destroying", False):
                raise RuntimeError("VMVM operation rejected while command cancellation is active")
            return method(self, *args, **kwargs)

    locked._vmvm_lifecycle_serialized = True
    return locked


# ---------------------------------------------------------------------------
# Lease + SSH helpers — small, reusable, easy to stub
# ---------------------------------------------------------------------------


class VacliLease:
    """Background `vacli` process holding a VMVM lease + an x2p SSH tunnel.

    Lifecycle:
      lease = VacliLease(tenant, log_path, subprocess_mod=...)
      lease.start()                  # spawns vacli; non-blocking
      port = lease.wait_for_tunnel() # blocks until JSON tunnel mapping appears
      ...
      lease.cleanup()                # SIGTERM → vacli's --release-on-exit fires

    `cleanup()` is registered with `atexit` at construction so an unhandled
    exception still releases the VM.
    """

    def __init__(
        self,
        tenant_id: str,
        log_path: Path,
        *,
        lease_ttl: str = DEFAULT_LEASE_TTL,
        tunnel_ready_timeout: float = DEFAULT_TUNNEL_READY_TIMEOUT,
        cleanup_timeout: float = DEFAULT_VACLI_CLEANUP_TIMEOUT,
        subprocess_mod: Any = None,
        image_url: str | None = None,
        cancel_event: threading.Event | None = None,
        artifact_registry: _VacliLocalArtifacts | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.log_path = log_path
        self.lease_ttl = lease_ttl
        self.tunnel_ready_timeout = tunnel_ready_timeout
        self.cleanup_timeout = cleanup_timeout
        self._sp = subprocess_mod or subprocess
        self._image_url = image_url
        self._cancel_event = cancel_event
        self._artifact_registry = artifact_registry
        self._owned_log_paths: set[str] = {str(log_path)}
        self.proc: Any = None
        self.ssh_port: int | None = None
        self._cleaned_up = False
        self._cleanup_requested = threading.Event()
        self._cleanup_lock = threading.Lock()
        self._pending_tunnel: tuple[Any, _LeaseConcurrencyPermit, Path] | None = None
        self._restart_state_lock = threading.Lock()
        self._restart_flight: _VacliRestartFlight | None = None
        # Raw LeaseVmResponse JSON (captured from the lease log) — input to
        # `--resume-with-session` when re-establishing a dropped tunnel.
        self.lease_response: str | None = None
        self.session_identity_sha256: str | None = None
        self._resume_count = 0
        self._cleanup_atexit_callback = self._cleanup_at_exit
        atexit.register(self._cleanup_atexit_callback)

    def _cleanup_at_exit(self) -> None:
        try:
            self.cleanup()
        except BaseException:
            logger.exception("vacli: non-fatal atexit cleanup failure")

    def _open_log(self, path: Path) -> Any:
        if self._artifact_registry is not None:
            return self._artifact_registry.open_log(path)
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            os.close(descriptor)
            raise BackendInitError("vacli log identity is invalid")
        return os.fdopen(descriptor, "wb")

    @property
    def owned_log_paths(self) -> set[str]:
        with self._cleanup_lock:
            return set(self._owned_log_paths)

    def _publish_process(
        self,
        process: Any,
        permit: _LeaseConcurrencyPermit,
        log_path: Path,
    ) -> None:
        permit.transfer_to_lease()
        self.proc = process
        self._pending_tunnel = (process, permit, log_path)

    def _lease_command(self) -> list[str]:
        # Standard VMVM images are pulled inside the VM. Specialized providers
        # may override this command to request a preloaded image tier.
        return [
            VACLI_BIN,
            "--x2p",
            "--faas-tenant-id",
            self.tenant_id,
            "lease",
            "--ttl",
            self.lease_ttl,
            "--auto-renew",
            "--tunnel-ports",
            "22",
            "--release-on-exit",
        ]

    def start(self) -> None:
        permit: _LeaseConcurrencyPermit | None = None
        try:
            permit = self._acquire_concurrency_slot()
            cmd = self._lease_command()
            logger.info(f"vacli: leasing VMVM (tenant={self.tenant_id}); log={self.log_path}")
            with self._cleanup_lock:
                if (
                    self._cleaned_up
                    or self._cleanup_requested.is_set()
                    or (self._cancel_event is not None and self._cancel_event.is_set())
                ):
                    raise BackendInitError("VMVM provisioning cancelled before lease start")
                # `with open(...)` closes the parent's fd after Popen returns;
                # the child has already inherited its own dup'd copy after Popen.
                log_path = self.log_path
                with self._open_log(log_path) as log_fh:
                    _popen_vacli(
                        cmd,
                        log_fh,
                        self._sp,
                        lambda process, owned_permit: self._publish_process(
                            process,
                            owned_permit,
                            log_path,
                        ),
                        permit,
                        self.cleanup_timeout,
                    )
                if self._cleanup_requested.is_set() or (self._cancel_event is not None and self._cancel_event.is_set()):
                    self._cleanup_locked()
                    raise BackendInitError("VMVM provisioning cancelled during lease start")
        except Exception:
            self._resolve_failed_spawn(permit)
            raise
        except BaseException:
            self._resolve_failed_spawn(permit)
            raise

    def wait_for_tunnel(self) -> int:
        """Poll the vacli log for the tunnel mapping; return the local port for vm_port=22.

        Per [[vacli-coreweave-stderr-noise]]: we look at stdout content, not
        exit code or stderr. The success signal is the JSON tunnel mapping
        being printed to stdout.
        """
        with self._cleanup_lock:
            process = self.proc
            pending = self._pending_tunnel
            if pending is not None and pending[0] is process:
                permit = pending[1]
                log_path = pending[2]
            else:
                permit = None
                log_path = self.log_path
            if process is None:
                raise BackendInitError("vacli lease never started; call .start() first")
        return self._wait_for_tunnel_process(process, permit, log_path)

    def _wait_for_tunnel_process(
        self,
        process: Any,
        permit: _LeaseConcurrencyPermit | None,
        log_path: Path,
    ) -> int:
        try:
            deadline = time.time() + self.tunnel_ready_timeout
            while time.time() < deadline:
                if self._cleanup_requested.is_set() or (self._cancel_event is not None and self._cancel_event.is_set()):
                    raise BackendInitError("VMVM provisioning cancelled while waiting for lease")
                # If vacli died, the lease is gone; surface a useful tail.
                if process.poll() is not None:
                    tail = self._log_tail(20, log_path)
                    raise BackendInitError(
                        f"vacli died before tunnel was ready (exit {process.returncode}). Tail of log:\n{tail}"
                    )
                try:
                    text = log_path.read_text(errors="replace")
                except FileNotFoundError:
                    text = ""
                # Capture the LeaseVmResponse once (needed later for resume).
                if self.lease_response is None:
                    for _line in text.splitlines():
                        captured = _extract_vacli_lease_response(_line)
                        if captured is not None:
                            self.lease_response, self.session_identity_sha256 = captured
                            break
                for match in _TUNNEL_RE.finditer(text):
                    try:
                        tunnels = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        continue
                    for t in tunnels:
                        if t.get("vm_port") == 22:
                            port = int(t["local_port"])
                            with self._cleanup_lock:
                                if (
                                    self._cleaned_up
                                    or self._cleanup_requested.is_set()
                                    or self.proc is not process
                                    or process.poll() is not None
                                ):
                                    raise BackendInitError("vacli tunnel became stale during readiness")
                                self.ssh_port = port
                            if TELEMETRY is not None:
                                TELEMETRY.lease_tunnel_became_ready()
                            logger.info(f"vacli: tunnel ready, ssh port = {port}")
                            return port
                if self._cancel_event is None:
                    time.sleep(1)
                elif self._cancel_event.wait(timeout=1):
                    raise BackendInitError("VMVM provisioning cancelled while waiting for lease")
            raise BackendInitError(
                f"vacli never printed tunnel mapping in {self.tunnel_ready_timeout}s. "
                f"Tail of log:\n{self._log_tail(30, log_path)}"
            )
        finally:
            with self._cleanup_lock:
                if (
                    self._pending_tunnel is not None
                    and self._pending_tunnel[0] is process
                    and self._pending_tunnel[1] is permit
                ):
                    self._pending_tunnel = None
            if permit is not None:
                permit.release()

    def restart_tunnel(self) -> "int | None":
        """Re-establish the x2p tunnel to the SAME VM after a dropped tunnel,
        via `lease --resume-with-session`, WITHOUT re-leasing — the VM, its
        podman container, and all on-disk state are preserved.

        The current vacli is SIGKILL'd first: `--release-on-exit` only fires on
        a *graceful* exit, so a hard kill leaves the VM leased (an un-resumed VM
        still reclaims when auto-renew stops at lease TTL — no permanent leak).
        Returns the new local ssh port, or None if the VM/lease is unrecoverable.

        Validated: SIGKILL keeps the VM alive and resume reconnects to it with
        files intact (see scripts/_resume_e2e_test.sh)."""
        with self._restart_state_lock:
            flight = self._restart_flight
            if flight is not None and not flight.completed.is_set():
                leader = False
            else:
                flight = _VacliRestartFlight()
                self._restart_flight = flight
                leader = True
        if not leader:
            flight.completed.wait()
            return flight.result
        try:
            result = self._restart_tunnel_once()
        except BaseException:
            flight.completed.set()
            raise
        flight.result = result
        flight.completed.set()
        return result

    def _restart_tunnel_once(self) -> int | None:
        if not self.lease_response:
            logger.warning("vacli.restart_tunnel: no LeaseVmResponse captured; cannot resume")
            return None
        cmd = [
            VACLI_BIN,
            "--x2p",
            "--faas-tenant-id",
            self.tenant_id,
            "lease",
            "--resume-with-session",
            self.lease_response,
            "--ttl",
            self.lease_ttl,
            "--auto-renew",
            "--tunnel-ports",
            "22",
            "--release-on-exit",
        ]
        # Respect the bring-up concurrency cap (released by wait_for_tunnel's finally).
        prior_process = self.proc
        permit: _LeaseConcurrencyPermit | None = None
        process = None
        log_path = self.log_path
        try:
            permit = self._acquire_concurrency_slot()
            with self._cleanup_lock:
                if self._cleaned_up or self._cleanup_requested.is_set():
                    raise BackendInitError("VMVM cleanup started before tunnel resume")
                # Hard-kill the current vacli (NOT SIGTERM: that would release the VM).
                if self.proc is not None and not self._stop_prior_for_resume_locked(self.proc):
                    raise BackendInitError("prior vacli process could not be reaped before tunnel resume")
                old_pending = self._take_pending_tunnel_locked(self.proc)
                if old_pending is not None:
                    old_pending.release()
                self.proc = None
                self.ssh_port = None
                self._resume_count += 1
                logger.info("vacli.restart_tunnel: resuming session (attempt %d)", self._resume_count)
                # Fresh log per resume so wait_for_tunnel() parses the new mapping.
                base = self.log_path.name.split(".resume")[0]
                log_path = self.log_path.with_name(f"{base}.resume{self._resume_count}.log")
                if self._artifact_registry is not None:
                    self._artifact_registry.register_resume_log(log_path)
                self._owned_log_paths.add(str(log_path))
                self.log_path = log_path
                with self._open_log(log_path) as log_fh:
                    _popen_vacli(
                        cmd,
                        log_fh,
                        self._sp,
                        lambda spawned_process, owned_permit: self._publish_process(
                            spawned_process,
                            owned_permit,
                            log_path,
                        ),
                        permit,
                        self.cleanup_timeout,
                    )
                process = self.proc
                if self._cleanup_requested.is_set():
                    self._cleanup_locked()
                    raise BackendInitError("VMVM cleanup started during tunnel resume")
        except Exception as e:
            self._resolve_failed_spawn(permit, prior_process)
            logger.warning("vacli.restart_tunnel: failed to spawn resume vacli: %s", e)
            return None
        except BaseException:
            self._resolve_failed_spawn(permit, prior_process)
            raise
        assert permit is not None
        assert process is not None
        try:
            return self.wait_for_tunnel()
        except BackendInitError as e:
            logger.warning("vacli.restart_tunnel: resume tunnel not ready: %s", e)
            return None

    def cleanup(self) -> None:
        self._cleanup_requested.set()
        with self._cleanup_lock:
            self._cleanup_locked()
            self._disarm_cleanup_at_exit_locked()

    def _disarm_cleanup_at_exit_locked(self) -> None:
        """Drop shutdown roots only after the lease is positively inactive."""
        callback = self._cleanup_atexit_callback
        if callback is not None:
            atexit.unregister(callback)
            self._cleanup_atexit_callback = None
        # A failed backend constructor may abandon its registry after local
        # artifact retirement becomes indeterminate.  Do not let a successfully
        # retired lease keep that registry (and its retained FDs) alive.
        self._artifact_registry = None

    def _cleanup_locked(self) -> None:
        pending_permit = self._take_pending_tunnel_locked()
        self._cleaned_up = True
        try:
            if self.proc is None or self.proc.poll() is not None:
                return
            logger.info("vacli: SIGTERM — releasing lease (--release-on-exit)")
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.proc.wait(timeout=self.cleanup_timeout)
            except self._sp.TimeoutExpired:
                logger.warning(f"vacli: alive after {self.cleanup_timeout}s; SIGKILL (lease will expire via TTL)")
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    self.proc.wait(timeout=5)  # reap so vacli doesn't linger as a zombie
                except self._sp.TimeoutExpired as error:
                    raise BackendInitError("vacli process could not be reaped during cleanup") from error
            if self.proc.poll() is None:
                raise BackendInitError("vacli process cleanup returned before reap")
        finally:
            if pending_permit is not None:
                pending_permit.release()

    def _acquire_concurrency_slot(self) -> _LeaseConcurrencyPermit:
        if not _lease_concurrency.acquire(cancel_event=self._cancel_event):
            raise BackendInitError("VMVM provisioning cancelled while waiting for lease capacity")
        return _LeaseConcurrencyPermit(_lease_concurrency)

    def _take_pending_tunnel_locked(self, process: Any = None) -> _LeaseConcurrencyPermit | None:
        pending = self._pending_tunnel
        if pending is None or (process is not None and pending[0] is not process):
            return None
        self._pending_tunnel = None
        return pending[1]

    def _stop_prior_for_resume_locked(self, process: Any) -> bool:
        try:
            if process.poll() is not None:
                return True
            process_group = os.getpgid(process.pid)
            os.killpg(process_group, signal.SIGKILL)
            process.wait(timeout=10)
            return process.poll() is not None
        except (ProcessLookupError, PermissionError, self._sp.TimeoutExpired):
            return False

    def _resolve_failed_spawn(
        self,
        permit: _LeaseConcurrencyPermit | None,
        prior_process: Any = None,
    ) -> None:
        if permit is None:
            return
        if permit.state == "owner":
            return
        if permit.state == "lease" and self.proc is not prior_process:
            self.cleanup()
            return
        permit.release()

    def _log_tail(self, n: int, log_path: Path | None = None) -> str:
        try:
            lines = (self.log_path if log_path is None else log_path).read_text(errors="replace").splitlines()
        except FileNotFoundError:
            return "(log file not found)"
        return "\n".join("  " + ln for ln in lines[-n:])


def _ssh_base_opts(
    port: int,
    *,
    connect_timeout: int = 5,
) -> list[str]:
    return [
        "/usr/bin/ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        # Keep the tunnel alive during long agent think times: ssh-level
        # heartbeats every 30s defeat NAT/firewall idle teardown and let us
        # detect a dead connection within ~90s instead of hanging in read.
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-p",
        str(port),
    ]


def _ssh_opts(
    port: int,
    control_path: str | None = None,
    *,
    connect_timeout: int = 5,
) -> list[str]:
    """Build a client-only SSH argv that can never publish a master."""
    path = "none" if control_path is None else control_path
    return _ssh_base_opts(port, connect_timeout=connect_timeout) + [
        "-o",
        "ControlMaster=no",
        "-o",
        f"ControlPath={path}",
        "-o",
        "ControlPersist=no",
        "-o",
        "ForkAfterAuthentication=no",
    ]


def _ssh_master_command(port: int, control_path: str) -> list[str]:
    command = _ssh_base_opts(port)
    return command + [
        "-o",
        "ControlMaster=yes",
        "-o",
        f"ControlPath={control_path}",
        "-o",
        "ControlPersist=no",
        "-o",
        "ForkAfterAuthentication=no",
        "-N",
        "root@localhost",
    ]


def _wait_for_sshd(
    port: int,
    *,
    timeout: float,
    control_path: str | None = None,
    subprocess_mod: Any = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Poll `ssh root@localhost true` until it returns 0 or `timeout` elapses."""
    sp = subprocess_mod or subprocess
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise BackendInitError("VMVM provisioning cancelled while waiting for sshd")
        rc = sp.run(
            _ssh_opts(port, control_path) + ["root@localhost", "true"],
            stdin=sp.DEVNULL,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
        ).returncode
        if rc == 0:
            return
        if cancel_event is None:
            time.sleep(1)
        elif cancel_event.wait(timeout=1):
            raise BackendInitError("VMVM provisioning cancelled while waiting for sshd")
    raise BackendInitError(f"sshd not ready on port {port} after {timeout}s")


def _bash_result(
    status: Literal["success", "error"],
    output: str,
    error_type: Literal["none", "timeout", "too_long", "exit", "broken_pipe", "other"] = "none",
    exit_code: int = 0,
) -> BashResult:
    """Build a BashResult TypedDict in the shape both backends already use.

    `exit_code` is required by downstream consumers (tool_types.make_python_plugin,
    swerl/tools.py, swerl/eval_backend/eval.py) which index `bash_result["exit_code"]`
    directly. Use -1 for cases where we don't have a real shell exit code
    (timeout, broken pipe, backend-internal errors) — matches the DES convention.
    """
    return BashResult(status=status, output=output, error_type=error_type, exit_code=exit_code)


def _pull_image_in_vm(sp, ssh_port, control_path, image, cancel_event=None):
    """Pull `image` inside the leased VM through a *login* shell.

    A login shell (`bash -l`) is required so /etc/profile.d/http_proxy.sh is
    sourced -- a non-login `ssh host cmd` shell does NOT inherit the VM's
    HTTP(S)_PROXY env, which podman needs to reach docker.io. Retries on
    DockerHub 429 (toomanyrequests); the vmvm-registry mirror succeeds on the
    first attempt so retries only bite the docker.io fallback.
    Returns (ok, last_output)."""
    inner = "podman pull --quiet=false " + shlex.quote(image)
    remote = "bash -l -c " + shlex.quote(inner)
    last = ""
    for attempt in range(MAX_PULL_RETRIES):
        if cancel_event is not None and cancel_event.is_set():
            raise BackendInitError("VMVM provisioning cancelled during image pull")
        r = sp.run(
            _ssh_opts(ssh_port, control_path) + ["root@localhost", remote],
            stdin=sp.DEVNULL,
            stdout=sp.PIPE,
            stderr=sp.STDOUT,
            timeout=IMAGE_PULL_TIMEOUT_SECONDS,
        )
        last = r.stdout.decode("utf-8", errors="replace") if r.stdout else ""
        if r.returncode == 0:
            return True, last
        # Retry ANY transient pull failure (rate-limit AND blob-copy/network drops,
        # which are common at high concurrency), not just 429. Longer backoff for
        # rate-limit; shorter for other transient errors.
        if attempt < MAX_PULL_RETRIES - 1:
            import random as _rnd

            rate_limited = "toomanyrequests" in last
            base = min(15 * (attempt + 1), 90) if rate_limited else min(5 * (attempt + 1), 30)
            wait = base + _rnd.uniform(0.0, base)  # jitter: disperse the 80-VM pull herd
            logger.warning(
                f"vacli: podman pull failed for {image} "
                f"(attempt {attempt + 1}/{MAX_PULL_RETRIES}, rate_limited={rate_limited}), "
                f"retrying in {wait}s"
            )
            if cancel_event is None:
                time.sleep(wait)
            elif cancel_event.wait(timeout=wait):
                raise BackendInitError("VMVM provisioning cancelled during image-pull backoff")
            continue
        return False, last
    return False, last


def _resolve_image_in_vm(
    sp,
    ssh_port,
    control_path,
    primary,
    fallback=None,
    cancel_event=None,
):
    """Pull `primary`, then `fallback` if given, returning the ref that worked.
    Raises BackendInitError if every candidate fails."""
    candidates = [primary]
    if fallback and fallback != primary:
        candidates.append(fallback)
    last_out = ""
    for img in candidates:
        if cancel_event is not None and cancel_event.is_set():
            raise BackendInitError("VMVM provisioning cancelled before image pull")
        ok, last_out = _pull_image_in_vm(
            sp,
            ssh_port,
            control_path,
            img,
            cancel_event=cancel_event,
        )
        if ok:
            return img
        logger.warning(f"vacli: pull failed for {img}; trying next candidate")
    raise BackendInitError(f"podman pull failed for all candidates {candidates}: {last_out[-800:]!r}")


def _ensure_python_in_container(sp, ssh_port, control_path, cid):
    """Symlink `python` -> python3 inside the container if absent.

    Matches DES VMVMBackend.prepare_server_container, which creates
    /usr/local/bin/python so the agent's `python ...` commands work. Without
    this, vacli's container only has `python3` and bare `python` exits 127 --
    a behavioral mismatch vs the DES baseline. Best-effort / non-fatal."""
    script = (
        "if ! command -v python >/dev/null 2>&1 && "
        "command -v python3 >/dev/null 2>&1; then "
        'ln -sf "$(command -v python3)" /usr/local/bin/python 2>/dev/null || '
        'ln -sf "$(command -v python3)" /tmp/python 2>/dev/null; fi'
    )
    remote = "podman exec --user 0 " + cid + " bash -lc " + shlex.quote(script)
    try:
        sp.run(
            _ssh_opts(ssh_port, control_path) + ["root@localhost", remote],
            stdin=sp.DEVNULL,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
            timeout=60,
        )
    except Exception:
        logger.warning("vacli: ensure-python symlink step failed (non-fatal)")


def _default_ipv4_gateway(output: bytes) -> str | None:
    for line in output.decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if fields[:1] != ["default"] or "via" not in fields:
            continue
        candidate = fields[fields.index("via") + 1]
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.version == 4:
            return str(address)
    return None


def _setup_bridge_proxy(sp, ssh_port, control_path, cid, extra_bypass=(), *, require_detected=False):
    """For a `--network bridge` container: detect the bridge gateway and write
    the egress proxy (now reachable at gateway:8080, not 0.0.0.0:8080) into
    /etc/profile.d so `bash -l` paths (e.g. test exec) get egress. Returns the
    gateway IP so the persistent (non-login) session can export it too. The
    container inherits http_proxy=0.0.0.0:8080 from the host, which is wrong once
    it has its own netns; gateway:8080 routes back to the host socat proxy.
    Best-effort; returns gateway IP (default 10.88.0.1)."""
    gw = None
    try:
        route = sp.run(
            _ssh_opts(ssh_port, control_path)
            + [
                "root@localhost",
                "pid=$(podman inspect --format '{{.State.Pid}}' "
                + cid
                + '); test "$pid" -gt 0; '
                + 'nsenter --target "$pid" --net ip -4 route show default',
            ],
            stdin=sp.DEVNULL,
            stdout=sp.PIPE,
            stderr=sp.DEVNULL,
            timeout=30,
        )
        if route.returncode == 0:
            gw = _default_ipv4_gateway(route.stdout or b"")
    except Exception:
        logger.warning("vacli: host-side bridge gateway detection failed")
    if gw is None:
        try:
            route = sp.run(
                _ssh_opts(ssh_port, control_path) + ["root@localhost", "podman exec --user 0 " + cid + " ip route"],
                stdin=sp.DEVNULL,
                stdout=sp.PIPE,
                stderr=sp.DEVNULL,
                timeout=30,
            )
            if route.returncode == 0:
                gw = _default_ipv4_gateway(route.stdout or b"")
        except Exception:
            logger.warning("vacli: in-container bridge gateway detection failed")
    if gw is None:
        if require_detected:
            raise BackendInitError("could not determine the Compose container bridge gateway")
        gw = "10.88.0.1"
        logger.warning("vacli: bridge gateway detection failed; using %s", gw)
    bypass_hosts = ["localhost", "127.0.0.1", gw]
    bypass_hosts.extend(
        host for host in extra_bypass if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", host) and host not in bypass_hosts
    )
    bypass = ",".join(bypass_hosts)
    exports = (
        "".join(
            "export %s=http://%s:8080\n" % (key, gw)
            for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
        )
        + f'export no_proxy="${{no_proxy:+$no_proxy,}}{bypass}"\n'
        + f'export NO_PROXY="${{NO_PROXY:+$NO_PROXY,}}{bypass}"\n'
    )
    exports += "export HF_HUB_DISABLE_XET=1\nexport HF_XET_DISABLE=1\n"
    exports += 'export MAVEN_OPTS="${MAVEN_OPTS:+$MAVEN_OPTS }' + MAVEN_PROXY_OPTS + '"\n'
    script = "cat > /etc/profile.d/zz_vacli_proxy.sh <<\x27VACLIEOF\x27\n" + exports + "VACLIEOF\n"
    remote = "podman exec --user 0 -i " + cid + " sh -c " + shlex.quote(script)
    try:
        sp.run(
            _ssh_opts(ssh_port, control_path) + ["root@localhost", remote],
            stdin=sp.DEVNULL,
            stdout=sp.DEVNULL,
            stderr=sp.DEVNULL,
            timeout=30,
        )
    except Exception:
        logger.warning("vacli: writing container proxy profile failed (non-fatal)")
    return gw


# ---------------------------------------------------------------------------
# Persistent-shell adapter
# ---------------------------------------------------------------------------


class VacliSession:
    """Sync wrapper around `AsyncSession` running on a private event-loop thread.

    The DES backend gets its persistent-shell semantics by running `AsyncSession`
    inside a python server on the VM and talking to it over TCP. We don't run
    such a server, so `AsyncSession` runs in our own process and we bridge its
    asyncio API to the sync `ToolBackend.run_bash` surface here.

    Lifetime:
      - `__init__` spawns a daemon thread running a private event loop. Daemon
        so a caller who forgets `stop()` doesn't hang interpreter shutdown.
      - `start()` launches the underlying bash subprocess on that loop. The
        process is loop-bound (`asyncio.subprocess.Process`), which is why the
        loop has to outlive every `communicate()` call.
      - `stop()` is the primary cleanup path: cancels the AsyncSession, stops
        the loop, joins the thread. The daemon flag is only a fallback.
    """

    def __init__(
        self,
        command_args: list[str],
        timeout: float,
        start_script: str | None = None,
        max_buffer_size: int | None = None,
    ) -> None:
        # Force the stdlib selector loop (NOT uvloop): prime-rl installs uvloop
        # globally, and many uvloop loops spawning subprocesses concurrently race
        # on uvloop's process-global child watcher ('Racing with another loop to
        # spawn a process') at high concurrency. SelectorEventLoop uses the
        # thread-safe ThreadedChildWatcher, so 128+ concurrent leases spawn cleanly.
        _install_threaded_child_watcher()
        self._loop = asyncio.SelectorEventLoop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="vacli-session-loop")
        self._thread.start()
        # AsyncSession must be constructed on the loop's thread because it
        # creates asyncio primitives (Locks, Futures) bound to the running loop.
        self._session: AsyncSession = self._submit(
            self._construct_session(
                ["setsid", *command_args],
                timeout,
                start_script,
                max_buffer_size,
            )
        )
        self._stopped = False

    @staticmethod
    async def _construct_session(
        command_args: list[str],
        timeout: float,
        start_script: str | None,
        max_buffer_size: int | None,
    ) -> AsyncSession:
        kwargs: dict[str, Any] = {
            "command_args": command_args,
            "timeout": timeout,
            "start_script": start_script,
        }
        if max_buffer_size is not None:
            kwargs["max_buffer_size"] = max_buffer_size
        return AsyncSession(**kwargs)

    def start(self) -> None:
        self._submit(self._session.start())

    def communicate(self, command: str, timeout: "float | None" = None) -> SessionOutput:
        return self._submit(self._session.communicate(command, timeout=timeout))

    def get_exitcode(self) -> int | None:
        return self._submit(self._session.get_exitcode())

    def interrupt(self, timeout: float | None = None) -> bool:
        """Terminate the subprocess while keeping its loop alive to drain communicate()."""
        if self._stopped:
            return not self._thread.is_alive()
        try:
            self._submit(self._interrupt_session_async(), timeout=timeout)
        except Exception:
            logger.exception("vacli session: error stopping AsyncSession")
            return False
        return True

    def stop(self, timeout: float | None = None) -> bool:
        if self._stopped:
            self._thread.join(timeout=5 if timeout is None else max(0.0, timeout))
            return not self._thread.is_alive()
        deadline = None if timeout is None else time.monotonic() + timeout
        stopped = self.interrupt(timeout)
        self._stopped = True
        # Keep the private loop alive until interrupt() has released any
        # communicate() waiter; only then stop and join the loop thread.
        self._loop.call_soon_threadsafe(self._loop.stop)
        remaining = 5.0 if deadline is None else max(0.0, deadline - time.monotonic())
        self._thread.join(timeout=remaining)
        if self._thread.is_alive():
            return False
        try:
            self._loop.close()
        except Exception:
            stopped = False
        return stopped

    async def _stop_session_async(self) -> None:
        self._session.stop()

    async def _interrupt_session_async(self) -> None:
        process = self._session.proc
        if process is not None and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
        self._session.stop()

    def _submit(self, coro: Any, timeout: float | None = None) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except BaseException:
            future.cancel()
            raise


# ---------------------------------------------------------------------------
# Backend classes
# ---------------------------------------------------------------------------


class VacliVMVMBackend:
    """vacli-backed equivalent of `VMVMBackend` with a persistent shell.

    Each instance:
      1. Leases a VMVM via vacli (--release-on-exit + atexit safety net).
      2. Owns a foreground OpenSSH master process for the full runtime.
      3. Pulls + runs a podman container for `image_url`.
      4. Runs all subsequent `run_bash` calls inside the container, reusing
         the SSH master so handshake cost is paid once.

    "Persistent shell" here means: a stable container (pid namespace, cwd,
    env vars set inside `start_script` persist), not a single bash process.
    The DES `VMVMBackend` keeps a single AsyncSession process; this one
    keeps a single container. Both preserve per-call state for callers that
    depend on `cd …` / `export …` semantics across calls.
    """

    def __init__(self, config: VacliVMVMConfig) -> None:
        self.config = config
        self._sp = config.subprocess_mod or subprocess
        self.init_start_time = time.perf_counter()
        self._destroyed = False
        self._destroying = False
        self._destroy_requested = threading.Event()
        self._destroy_atexit_callback: Any = None
        self._remote_cleanup_complete = False
        self._telemetry_runtime_active = False
        self._lifecycle_lock = threading.RLock()
        # Random nonces keep multiple backends on the same host from sharing
        # ssh control sockets / vacli log files.
        instance_nonce = uuid.uuid4().hex
        tmp = Path(tempfile.gettempdir())
        self._local_artifacts = _VacliLocalArtifacts(tmp, self._sp)
        self._control_path, self._vacli_log = self._local_artifacts.new_attempt_paths()

        self._lease = VacliLease(
            tenant_id=config.tenant_id,
            log_path=self._vacli_log,
            lease_ttl=config.lease_ttl,
            tunnel_ready_timeout=config.tunnel_ready_timeout,
            subprocess_mod=config.subprocess_mod,
            cancel_event=config.provisioning_cancel_event,
            artifact_registry=self._local_artifacts,
        )
        self._container_id: str | None = None
        self._compose_project: str | None = None
        self._compose_dir: str | None = None
        self._compose_services: tuple[str, ...] = ()
        self._session: VacliSession | None = None
        self._host_tunnels: set[VacliHostTunnel] = set()
        self._network_isolation: _VacliNetworkIsolation | None = None
        # FIFO-backed persistent shell state (v1). The shell lives INSIDE the
        # container behind a named pipe, so an x2p tunnel drop does not kill it:
        # cwd/env + any in-flight command survive, and restart_session() re-attaches
        # to the SAME shell. Set up in _open_session; falls back to the legacy
        # streamed session (_fifo_mode=False) only if the image lacks bash+mkfifo.
        self._tools: dict[str, bool] = {}
        self._fifo_mode = False
        self._sess_nonce = ""
        self._sess_dir = ""
        self._cmd_seq = 0
        # (seq, command, timeout) for a command SENT to the shell whose result was
        # not yet collected (tunnel dropped mid-wait). recover_last() re-reads it
        # WITHOUT re-executing. None => nothing in flight.
        self._pending: tuple[int, str, float, float] | None = None
        self._last_command: str | None = None
        self._last_timeout: float | None = None
        # ``VMVMRuntime`` runs this synchronous backend in ``asyncio.to_thread``.
        # Cancelling that await does not stop the worker thread, so track the one
        # in-flight shell command and give the async adapter a synchronous way to
        # interrupt and drain it before the runtime is used for grading.
        self._command_state_lock = threading.Lock()
        self._command_cancel_lock = threading.Lock()
        self._active_command_thread: int | None = None
        self._active_command_done = threading.Event()
        self._active_command_done.set()
        self._command_cancel_requested = threading.Event()
        self._command_cancel_failed = threading.Event()
        # Set by restart_session when it had to REBUILD a dead in-container shell
        # (state lost); recover_last() then declines transparent recovery.
        self._shell_was_reset = False
        # Structured record of transient bring-up retries (recovered) so the
        # rollout's jsonl can show how many re-leases it took to come up.
        self.bringup_retries: list = []
        if TELEMETRY is not None:
            TELEMETRY.vmvm_runtime_started()
            self._telemetry_runtime_active = True
        provisioning_done = threading.Event()

        def cancel_partial_lease() -> None:
            cancel_event = config.provisioning_cancel_event
            if cancel_event is None:
                return
            while not provisioning_done.is_set():
                if cancel_event.wait(timeout=0.1):
                    # Killing vacli closes the x2p tunnel and interrupts the
                    # current SSH/pull/run subprocess.  cleanup is idempotent and
                    # synchronized with constructor rollback/final handoff.
                    self._lease.cleanup()
                    return

        cancellation_watcher = threading.Thread(
            target=cancel_partial_lease,
            name=f"vmvm-provision-cancel-{instance_nonce}",
            daemon=True,
        )
        cancellation_watcher.start()
        try:
            # Retry lease bring-up with jittered backoff: concurrent launches
            # race on Configerator init -> "vacli died before tunnel was ready"
            # (transient). Fresh lease each attempt (old proc already died).
            import random as _random

            for _attempt in range(MAX_LEASE_RETRIES):
                self._raise_if_provisioning_cancelled()
                try:
                    self._lease.start()
                    self._ssh_port = self._lease.wait_for_tunnel()
                    self._local_artifacts.record_control_port(self._control_path, self._ssh_port)
                    self._raise_if_provisioning_cancelled()
                    # Full bring-up inside the retry envelope: sshd readiness and
                    # container pull/start are the ssh-dependent steps that saturate
                    # under high concurrency (the dominant env_error cause). A failure
                    # here abandons this VM and re-leases a FRESH one rather than
                    # failing the rollout. Previously these two steps were outside the
                    # loop -> a single slow sshd / dropped ssh handshake = instant 0.
                    _wait_for_sshd(
                        self._ssh_port,
                        timeout=config.sshd_ready_timeout,
                        control_path=None,
                        subprocess_mod=config.subprocess_mod,
                        cancel_event=config.provisioning_cancel_event,
                    )
                    self._start_control_master()
                    self._raise_if_provisioning_cancelled()
                    self._container_id = self._start_container()
                    self._raise_if_provisioning_cancelled()
                    break
                except BackendInitError as _e:
                    self._retire_failed_attempt()
                    self._container_id = None
                    self._raise_if_provisioning_cancelled()
                    if _attempt + 1 >= MAX_LEASE_RETRIES:
                        raise
                    _wait = min(2.0 * (2**_attempt), 20.0) + _random.uniform(0.0, 3.0)
                    logger.warning(
                        "vacli: bring-up failed (attempt %d/%d): %s -- retry in %.1fs"
                        % (_attempt + 1, MAX_LEASE_RETRIES, str(_e)[:150], _wait)
                    )
                    self.bringup_retries.append({"attempt": _attempt + 1, "detail": str(_e)[:300]})
                    cancel_event = config.provisioning_cancel_event
                    if cancel_event is None:
                        time.sleep(_wait)
                    elif cancel_event.wait(timeout=_wait):
                        raise BackendInitError("VMVM provisioning cancelled during retry backoff")
                    self._raise_if_provisioning_cancelled()
                    self._control_path, self._vacli_log = self._local_artifacts.new_attempt_paths()
                    self._lease = VacliLease(
                        tenant_id=config.tenant_id,
                        log_path=self._vacli_log,
                        lease_ttl=config.lease_ttl,
                        tunnel_ready_timeout=config.tunnel_ready_timeout,
                        subprocess_mod=config.subprocess_mod,
                        cancel_event=config.provisioning_cancel_event,
                        artifact_registry=self._local_artifacts,
                    )
            # Persistent bash inside the container, driven via stdin over the
            # SSH master. Non-interactive `bash` (NOT `bash -i`): interactive
            # mode echoes every command back, prints PS1 on every line, and
            # corrupts the sentinel-detection stream that AsyncSession reads.
            # `stdbuf -oL` defeats libc block-buffering so small-output reads
            # don't hang waiting for a 4KB flush. Matches DES, which spawns
            # AsyncSession with `["/bin/bash"]` (see remote/server.py callers).
            # Bridge networking: the inherited http_proxy=0.0.0.0:8080 is wrong
            # in the container netns. Export the gateway proxy as the first thing
            # the (non-login) session does, so solve.sh subprocesses inherit it.
            self._open_session(run_entrypoint=True)
            self._raise_if_provisioning_cancelled()
            if TELEMETRY is not None:
                TELEMETRY.vmvm_runtime_became_ready()
        except BaseException:
            # Roll back any partial state so an init failure doesn't leak a
            # leased VM.
            try:
                self.destroy()
            except BaseException as cleanup_error:
                raise _ArtifactCleanupError("VMVM constructor rollback was not verified") from cleanup_error
            raise
        finally:
            provisioning_done.set()
            cancellation_watcher.join(timeout=0.2)
        self._destroy_atexit_callback = self._destroy_at_exit
        atexit.register(self._destroy_atexit_callback)

    def _destroy_at_exit(self) -> None:
        try:
            self.destroy()
        except BaseException:
            logger.exception("vacli: non-fatal backend atexit cleanup failure")

    def _raise_if_provisioning_cancelled(self) -> None:
        cancel_event = self.config.provisioning_cancel_event
        if cancel_event is not None and cancel_event.is_set():
            raise BackendInitError("VMVM provisioning cancelled")

    def _start_control_master(self) -> None:
        process = self._local_artifacts.start_control(
            self._control_path,
            _ssh_master_command(self._ssh_port, self._control_path),
        )
        deadline = time.monotonic() + _CONTROL_MASTER_EXIT_TIMEOUT_SECONDS
        while True:
            self._raise_if_provisioning_cancelled()
            if process.poll() is not None:
                raise BackendInitError("OpenSSH control master exited during startup")
            try:
                if self._local_artifacts.bind_control(self._control_path, required=False):
                    return
            except _ControlNotReady:
                pass
            except _ArtifactCleanupError as error:
                raise BackendInitError("could not bind the SSH control master") from error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BackendInitError("OpenSSH control master did not publish its socket")
            cancel_event = self.config.provisioning_cancel_event
            if cancel_event is None:
                time.sleep(min(0.05, remaining))
            elif cancel_event.wait(timeout=min(0.05, remaining)):
                raise BackendInitError("VMVM provisioning cancelled while starting SSH control master")

    def _retire_control_master(self, path: str) -> None:
        bind_error: BaseException | None = None
        cleanup_error: BaseException | None = None
        try:
            self._local_artifacts.bind_control(path, required=False)
        except BaseException as error:
            bind_error = error
        try:
            self._local_artifacts.cleanup_controls({path})
        except BaseException as error:
            cleanup_error = error
        if bind_error is not None or cleanup_error is not None:
            raise _ArtifactCleanupError("OpenSSH control master retirement was not verified") from (
                cleanup_error or bind_error
            )

    def _retire_failed_attempt(self) -> None:
        errors: list[BaseException] = []
        try:
            self._retire_control_master(self._control_path)
        except BaseException as error:
            errors.append(error)
        try:
            self._lease.cleanup()
        except BaseException as error:
            errors.append(error)
        try:
            self._local_artifacts.cleanup_logs(self._lease.owned_log_paths)
        except BaseException as error:
            errors.append(error)
        if errors:
            raise _ArtifactCleanupError("VMVM failed-attempt retirement was not verified") from errors[0]

    @property
    def lease_identity_sha256(self) -> str:
        identity = self._lease.session_identity_sha256
        if not isinstance(identity, str) or _SHA256_RE.fullmatch(identity) is None:
            raise BackendInitError("vacli lease session identity is unavailable")
        return identity

    def _open_session(self, run_entrypoint: bool = True) -> None:
        """Set up the persistent shell for the current container.

        Prefers a FIFO-backed shell living INSIDE the container (survives x2p
        tunnel drops -- cwd/env + in-flight command persist). Falls back to the
        legacy SSH-streamed `podman exec -i bash` only if the image lacks
        bash+mkfifo+setsid. Called by __init__ (run_entrypoint=True). NOTE:
        restart_session() does NOT call this in fifo mode -- the in-container
        shell survives a drop, so we re-attach (verify alive) rather than rebuild.

        setsid is required (not just bash+mkfifo): the reader runs under setsid so
        a timed-out runaway command can be group-killed; without it we cannot
        guarantee the runaway dies, so we fall back to the legacy session.
        """
        self._tools = self._probe_tools()
        if self._tools.get("bash") and self._tools.get("mkfifo") and self._tools.get("setsid"):
            self._fifo_mode = True
            self._setup_fifo_shell(run_entrypoint=run_entrypoint, run_start_script=True)
            return

        # --- legacy fallback: image has no fifo-capable shell (no drop-recovery) ---
        self._fifo_mode = False
        logger.warning(
            "vacli: image lacks bash+mkfifo (%s); using legacy streamed session (no mid-rollout drop recovery)",
            self._tools,
        )
        config = self.config
        _gw = getattr(self, "_proxy_gateway", None)
        _bypass = ",".join(["localhost", "127.0.0.1", _gw, *self._compose_services]) if _gw else ""
        _proxy_pre = (
            (
                "export http_proxy=http://{gw}:8080 https_proxy=http://{gw}:8080 "
                "HTTP_PROXY=http://{gw}:8080 HTTPS_PROXY=http://{gw}:8080 "
                'no_proxy="${{no_proxy:+$no_proxy,}}{bypass}" '
                'NO_PROXY="${{NO_PROXY:+$NO_PROXY,}}{bypass}"; '.format(
                    gw=_gw,
                    bypass=_bypass,
                )
                if _gw
                else ""
            )
            + "export HF_HUB_DISABLE_XET=1 HF_XET_DISABLE=1; "
            + 'export MAVEN_OPTS="${MAVEN_OPTS:+$MAVEN_OPTS }'
            + MAVEN_PROXY_OPTS
            + '"'
        )
        _us = config.start_script or ""
        _eff = ("; ".join(x for x in (_proxy_pre, _us) if x)) or None
        self._session = VacliSession(
            command_args=_ssh_opts(self._ssh_port, self._control_path)
            + [
                "root@localhost",
                f"podman exec -i {self._container_id} stdbuf -oL bash",
            ],
            timeout=config.session_timeout,
            start_script=_eff,
            max_buffer_size=config.max_session_buffer_size,
        )
        self._session.start()
        if run_entrypoint and config.entrypoint_script:
            # Run through the session so any state it sets up persists for
            # subsequent run_bash calls.
            self._session.communicate(config.entrypoint_script)

    # -- FIFO-backed persistent shell (v1) ---------------------------------

    def _probe_tools(self) -> dict[str, bool]:
        """Check which shell tools the container image provides. bash+mkfifo are
        required for the FIFO shell; setsid is optional (enables clean group-kill
        of a runaway command on timeout)."""
        script = (
            'for t in bash mkfifo setsid; do command -v "$t" >/dev/null 2>&1 && echo "have $t" || echo "miss $t"; done'
        )
        try:
            r = self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " sh -c " + shlex.quote(script),
                timeout=60,
            )
            out = (r.stdout or b"").decode("utf-8", "replace")
        except Exception:
            out = ""
        return {t: (("have " + t) in out) for t in ("bash", "mkfifo", "setsid")}

    def _preamble(self) -> str:
        """Proxy + user start_script, applied once at shell setup so cwd/env it
        sets persist for every run_bash call (the bridge container netns needs the
        gateway proxy; the inherited 0.0.0.0:8080 is wrong)."""
        config = self.config
        gw = getattr(self, "_proxy_gateway", None)
        bypass = ",".join(["localhost", "127.0.0.1", gw, *self._compose_services]) if gw else ""
        proxy_pre = (
            (
                "export http_proxy=http://{gw}:8080 https_proxy=http://{gw}:8080 "
                "HTTP_PROXY=http://{gw}:8080 HTTPS_PROXY=http://{gw}:8080 "
                'no_proxy="${{no_proxy:+$no_proxy,}}{bypass}" '
                'NO_PROXY="${{NO_PROXY:+$NO_PROXY,}}{bypass}"; '.format(
                    gw=gw,
                    bypass=bypass,
                )
                if gw
                else ""
            )
            + "export HF_HUB_DISABLE_XET=1 HF_XET_DISABLE=1; "
            + 'export MAVEN_OPTS="${MAVEN_OPTS:+$MAVEN_OPTS }'
            + MAVEN_PROXY_OPTS
            + '"'
        )
        us = config.start_script or ""
        return "; ".join(x for x in (proxy_pre, us) if x)

    @staticmethod
    def _remaining_timeout(deadline: float | None, maximum: float) -> float:
        if deadline is None:
            return maximum
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("VMVM shell operation exceeded its cancellation deadline")
        return min(maximum, remaining)

    def _setup_fifo_shell(
        self,
        *,
        run_entrypoint: bool,
        run_start_script: bool = True,
        deadline: float | None = None,
    ) -> None:
        """Create the in-container persistent shell: a command FIFO, a held-writer
        keeping it open, and a detached `bash` LOOP that reads a command sequence
        number from the FIFO and `source`s the staged command body for that seq.

        Protocol (per command <seq>):
          * the body is staged out-of-band into c<seq> (atomic write+rename) so a
            torn FIFO write can never leave the reader mid-parse;
          * only a tiny integer token `<seq>` is pushed through the FIFO; the reader
            validates it is an integer (garbage/partial tokens are skipped), writes
            a `started` marker s<seq>, runs `source c<seq> </dev/null >o<seq> 2>&1`
            (current shell -> cwd/env persist; </dev/null -> a command reading stdin
            can't cannibalise the FIFO), then writes e<seq> (exit code) and d<seq>
            (done marker).
        Reads (_fifo_wait_read) are stateless/idempotent and recovery (recover_last)
        gates re-execution on the s<seq> marker, never on an ssh return code, so a
        drop can never double-execute a command.
        The reader runs under setsid (pgid==pid) so a runaway command can be
        group-killed on timeout. Requires bash+mkfifo+setsid (checked by caller)."""
        cid = str(self._container_id)
        nonce = uuid.uuid4().hex[:12]
        self._sess_nonce = nonce
        self._sess_dir = "/tmp/.vacli_sess_" + nonce
        self._cmd_seq = 0
        self._pending = None
        self._shell_was_reset = False
        D = self._sess_dir
        qD = shlex.quote(D)
        # 1) session dir + command fifo + (empty) reader log -- synchronous.
        setup = "set -e; rm -rf {D}; mkdir -p {D}; mkfifo {D}/cmd; : > {D}/log".format(D=qD)
        r = self._ssh_call_raw(
            "podman exec " + cid + " bash -c " + shlex.quote(setup),
            timeout=self._remaining_timeout(deadline, 60),
        )
        if r.returncode != 0:
            raise BackendInitError("fifo shell setup failed: " + (r.stdout or b"").decode("utf-8", "replace")[-400:])
        # 2) held-writer: keeps the fifo open for writing so the reader's `read`
        #    never sees EOF between commands. Records its pid for clean teardown.
        hold = ('D={D}; echo $$ > "$D/holdpid"; exec -a vacli_hold_{n} sleep 2147483647 > "$D/cmd"').format(
            D=qD, n=nonce
        )
        self._ssh_call_raw(
            "podman exec -d " + cid + " bash -c " + shlex.quote(hold),
            timeout=self._remaining_timeout(deadline, 30),
        )
        # 3) reader loop: records its pgid, then forever reads an integer seq from
        #    the fifo and runs the staged body for that seq in THIS shell.
        # Reader-internal vars are namespaced (__vacli_*) so a task command sourced in
        # THIS shell that uses common names (D, seq, last) cannot clobber the loop's
        # control state. __vacli_last is the AUTHORITATIVE exactly-once gate: it lives
        # in the reader's memory (not a file the command can delete/forge), and seq is
        # strictly increasing, so any re-pushed / torn-then-completed / duplicate token
        # for a seq <= the last STARTED seq is dropped -- a tunnel drop can never
        # double-execute a command no matter what recover_last re-pushes. `set +e` each
        # iteration neutralizes a prior body's `set -e` so a builtin returning non-zero
        # (e.g. the -le test, which is false on the normal path) can't kill the reader.
        reader = (
            '__vacli_d={D}; echo $$ > "$__vacli_d/pgid"; __vacli_last=0; '
            "while IFS= read -r __vacli_seq; do "
            "set +e; "
            'case "$__vacli_seq" in (""|*[!0-9]*) continue ;; esac; '
            'if [ "$__vacli_seq" -le "$__vacli_last" ] 2>/dev/null; then continue; fi; '
            '__vacli_last="$__vacli_seq"; '
            ': > "$__vacli_d/s$__vacli_seq"; '
            'source "$__vacli_d/c$__vacli_seq" < /dev/null > "$__vacli_d/o$__vacli_seq" 2>&1; '
            "__vacli_rc=$?; "
            'printf %s "$__vacli_rc" > "$__vacli_d/e$__vacli_seq"; '
            ': > "$__vacli_d/d$__vacli_seq"; '
            'done < "$__vacli_d/cmd"'
        ).format(D=qD)
        self._ssh_call_raw(
            "podman exec -d " + cid + " setsid bash -c " + shlex.quote(reader),
            timeout=self._remaining_timeout(deadline, 30),
        )
        # 4) wait for both the reader and held-writer processes to be live.
        ready_deadline = time.monotonic() + 30
        if deadline is not None:
            ready_deadline = min(ready_deadline, deadline)
        while time.monotonic() < ready_deadline:
            if self._fifo_shell_alive(timeout=self._remaining_timeout(ready_deadline, 30)):
                break
            remaining = ready_deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.3, remaining))
        else:
            raise BackendInitError("fifo reader/held-writer did not come up")
        # 5) preamble doubles as an end-to-end wiring probe (exercises stage+push+read).
        pre = self._preamble() if run_start_script else ""
        probe = self._fifo_run(pre or ":", timeout=30.0, deadline=deadline)
        if probe["error_type"] in ("broken_pipe", "timeout", "other"):
            raise BackendInitError("fifo shell wiring probe failed: %r" % (probe,))
        # 6) entrypoint, in the persistent shell so its state sticks.
        if run_entrypoint and self.config.entrypoint_script:
            self._fifo_run(
                self.config.entrypoint_script,
                timeout=self.config.session_timeout,
                deadline=deadline,
            )

    def _fifo_shell_alive(self, timeout: float = 30) -> bool:
        """True iff BOTH the in-container reader (by pgid) and the held-writer (by
        holdpid) are alive. If the held-writer died the reader would EOF and exit
        after the next command, so both must be checked."""
        if not self._sess_dir or self._container_id is None:
            return False
        chk = (
            'D={D}; r=$(cat "$D/pgid" 2>/dev/null); h=$(cat "$D/holdpid" 2>/dev/null); '
            '[ -n "$r" ] && kill -0 "$r" 2>/dev/null && '
            '[ -n "$h" ] && kill -0 "$h" 2>/dev/null && echo ALIVE'
        ).format(D=shlex.quote(self._sess_dir))
        try:
            r = self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(chk),
                timeout=timeout,
            )
        except Exception:
            return False
        return r.returncode == 0 and b"ALIVE" in (r.stdout or b"")

    def _teardown_fifo_shell(self, deadline: float | None = None) -> bool:
        """Kill the in-container reader (and its current foreground command, via
        group-kill on the setsid pgid) plus the held-writer (by recorded pid), and
        remove the session dir. Best-effort; used on timeout and on dead-shell
        recreate to reset state like the legacy backend."""
        if not self._sess_dir or self._container_id is None:
            return True
        script = (
            'D={D}; p=$(cat "$D/pgid" 2>/dev/null); h=$(cat "$D/holdpid" 2>/dev/null); '
            '[ -n "$p" ] && kill -KILL -"$p" 2>/dev/null; '
            '[ -n "$p" ] && kill -KILL "$p" 2>/dev/null; '
            '[ -n "$h" ] && kill -KILL "$h" 2>/dev/null; '
            'rm -rf "$D" 2>/dev/null; true'
        ).format(D=shlex.quote(self._sess_dir))
        try:
            result = self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
                timeout=self._remaining_timeout(deadline, 30),
            )
        except Exception:
            result = None
        self._sess_dir = ""
        self._pending = None
        return result is not None and result.returncode == 0

    def _interrupt_fifo_command(self, timeout: float) -> bool:
        """Stop the active FIFO command and wake its host-side waiter.

        The reader and the command it sourced share a process group.  Killing
        that group preserves the container filesystem while ensuring the agent
        cannot keep mutating it.  A synthetic exit marker wakes the separate
        ``podman exec`` waiter; the command is never replayed.
        """
        pending = self._pending
        if pending is None or not self._sess_dir or self._container_id is None:
            return False
        seq = pending[0]
        directory = shlex.quote(self._sess_dir)
        script = (
            'D={directory}; p=$(cat "$D/pgid" 2>/dev/null); '
            'h=$(cat "$D/holdpid" 2>/dev/null); '
            '[ -n "$p" ] && kill -KILL -"$p" 2>/dev/null || true; '
            '[ -n "$p" ] && kill -KILL "$p" 2>/dev/null || true; '
            '[ -n "$h" ] && kill -KILL "$h" 2>/dev/null || true; '
            'i=0; while [ "$i" -lt 50 ]; do '
            'alive=0; [ -n "$p" ] && kill -0 -"$p" 2>/dev/null && alive=1; '
            '[ -n "$p" ] && kill -0 "$p" 2>/dev/null && alive=1; '
            '[ -n "$h" ] && kill -0 "$h" 2>/dev/null && alive=1; '
            '[ "$alive" -eq 0 ] && break; i=$((i + 1)); sleep 0.1; done; '
            '[ "$alive" -eq 0 ] || exit 1; '
            'printf 130 > "$D/e{seq}"; : > "$D/d{seq}"'
        ).format(directory=directory, seq=seq)
        result = self._ssh_call_raw(
            "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
            timeout=min(30.0, timeout),
        )
        return result.returncode == 0

    def _begin_command(self) -> None:
        with self._command_state_lock:
            if self._active_command_thread is not None:
                raise RuntimeError("concurrent VMVM shell commands are forbidden")
            if self._command_cancel_requested.is_set():
                raise RuntimeError("VMVM command rejected while cancellation is active")
            self._active_command_thread = threading.get_ident()
            self._active_command_done.clear()

    def _end_command(self) -> None:
        with self._command_state_lock:
            self._active_command_thread = None
            self._active_command_done.set()

    def cancel_active_command(self, timeout: float) -> bool:
        """Interrupt and drain one active command, restoring a usable shell.

        Returns ``False`` if the command cannot be stopped and joined within the
        caller's grace period or if shell restoration fails.  The caller must
        destroy and invalidate the runtime on that fail-closed path.  This method
        interrupts before taking ``_lifecycle_lock`` because the active command
        holds it.  Once that command drains, the cancellation flag prevents new
        lifecycle operations from entering SSH while reset acquires the lock.
        """

        def poison() -> None:
            with self._command_state_lock:
                self._command_cancel_failed.set()
                self._command_cancel_requested.set()

        if timeout <= 0:
            poison()
            return False
        deadline = time.monotonic() + timeout
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._command_cancel_lock.acquire(timeout=remaining):
            poison()
            return False

        request_published = False
        succeeded = False
        try:
            with self._command_state_lock:
                if self._command_cancel_failed.is_set():
                    self._command_cancel_requested.set()
                    request_published = True
                    return False
                self._command_cancel_requested.set()
                request_published = True
                active = self._active_command_thread is not None or self._pending is not None
            if not active:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._lifecycle_lock.acquire(timeout=remaining):
                    return False
                try:
                    if self._destroyed:
                        return False
                    with self._command_state_lock:
                        if self._command_cancel_failed.is_set():
                            return False
                        self._command_cancel_requested.clear()
                        succeeded = True
                    return True
                finally:
                    self._lifecycle_lock.release()
            if self._destroyed:
                return False

            fifo_mode = self._fifo_mode
            session = self._session
            try:
                if fifo_mode:
                    if not self._interrupt_fifo_command(deadline - time.monotonic()):
                        remaining = deadline - time.monotonic()
                        if remaining > 0:
                            self._active_command_done.wait(remaining)
                        return False
                else:
                    if session is None:
                        return False
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not session.interrupt(timeout=remaining):
                        remaining = deadline - time.monotonic()
                        if remaining > 0:
                            self._active_command_done.wait(remaining)
                        return False
            except Exception:
                logger.exception("vacli: active command interruption failed")
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._active_command_done.wait(remaining):
                logger.error("vacli: active command did not stop within cancellation grace")
                return False
            if self._destroyed:
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._lifecycle_lock.acquire(timeout=remaining):
                return False
            try:
                if self._destroyed:
                    return False
                if not fifo_mode:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not session.stop(timeout=remaining):
                        return False
                    if self._session is session:
                        self._session = None
                    # Legacy streamed sessions cannot preserve a known-good shell
                    # state across interruption.  The command is drained, but the
                    # runtime must be invalidated so grading is never run on it.
                    return False

                try:
                    if not self._teardown_fifo_shell(deadline):
                        return False
                    self._setup_fifo_shell(
                        run_entrypoint=False,
                        run_start_script=True,
                        deadline=deadline,
                    )
                except Exception:
                    logger.exception("vacli: shell restoration after cancellation failed")
                    return False
                with self._command_state_lock:
                    if self._command_cancel_failed.is_set():
                        return False
                    self._command_cancel_requested.clear()
                    succeeded = True
                return True
            finally:
                self._lifecycle_lock.release()
        finally:
            if request_published and not succeeded:
                poison()
            self._command_cancel_lock.release()

    def _fifo_stage(self, seq: int, command: str, fresh: bool = False) -> bool:
        """Stage the command body into c<seq> atomically (write tmp + rename), via
        stdin so size is bounded only by VM disk. Idempotent. Returns ssh-ok.

        When `fresh` (initial run of a brand-new seq), first remove any pre-existing
        s/o/e/d<seq> markers so a task command that forged the NEXT seq's done/output
        files can't make _fifo_wait_read return stale/forged data before the reader
        runs. Recovery re-stages with fresh=False so it never wipes the real markers
        it needs to decide whether the command already ran."""
        body = command if command.strip() else ":"
        pre = ('rm -f "$D/s{s}" "$D/o{s}" "$D/e{s}" "$D/d{s}"; ' if fresh else "").format(s=seq)
        script = ("D={D}; " + pre + 'cat > "$D/c{s}.tmp" && mv -f "$D/c{s}.tmp" "$D/c{s}"').format(
            D=shlex.quote(self._sess_dir), s=seq
        )
        remote = "podman exec -i " + str(self._container_id) + " bash -c " + shlex.quote(script)
        argv = _ssh_opts(self._ssh_port, self._control_path) + ["root@localhost", remote]
        try:
            r = self._sp.run(
                argv,
                input=body.encode("utf-8"),
                stdout=self._sp.DEVNULL,
                stderr=self._sp.DEVNULL,
                timeout=60,
            )
        except Exception as e:
            logger.debug("fifo_stage failed: %s", e)
            return False
        return r.returncode == 0

    def _fifo_push(self, seq: int) -> bool:
        """Push the tiny trigger token `<seq>` into the FIFO (the reader then runs
        the staged body). A leading newline closes any partial line a prior torn
        write may have left. Returns ssh-ok (NOT proof of execution -- recovery
        keys off the s<seq> marker)."""
        script = 'D={D}; cat > "$D/cmd"'.format(D=shlex.quote(self._sess_dir))
        remote = "podman exec -i " + str(self._container_id) + " bash -c " + shlex.quote(script)
        argv = _ssh_opts(self._ssh_port, self._control_path) + ["root@localhost", remote]
        try:
            r = self._sp.run(
                argv,
                input=("\n%d\n" % seq).encode("ascii"),
                stdout=self._sp.DEVNULL,
                stderr=self._sp.DEVNULL,
                timeout=60,
            )
        except Exception as e:
            logger.debug("fifo_push failed: %s", e)
            return False
        return r.returncode == 0

    def _fifo_marker(self, seq: int, kind: str) -> "bool | None":
        """Tri-state existence check for marker file <kind><seq> inside the
        container: True (exists), False (definitely absent), None (ssh/tunnel
        failed -- unknown). Uses a unique echo token and the ssh rc so error text
        can't be misread as a verdict."""
        script = ('D={D}; if [ -e "$D/{k}{s}" ]; then echo VACLI_MARK_Y; else echo VACLI_MARK_N; fi').format(
            D=shlex.quote(self._sess_dir), k=kind, s=seq
        )
        try:
            r = self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
                timeout=30,
            )
        except Exception:
            return None
        if r.returncode != 0:
            return None
        out = r.stdout or b""
        if b"VACLI_MARK_Y" in out:
            return True
        if b"VACLI_MARK_N" in out:
            return False
        return None

    def _fifo_cleanup_seq(self, seq: int) -> None:
        """Remove the per-command files for a completed seq (bounded disk use)."""
        if not self._sess_dir or self._container_id is None:
            return
        script = 'D={D}; rm -f "$D/c{s}" "$D/o{s}" "$D/e{s}" "$D/d{s}" "$D/s{s}" 2>/dev/null; true'.format(
            D=shlex.quote(self._sess_dir), s=seq
        )
        try:
            self._ssh_call_raw(
                "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
                timeout=30,
            )
        except Exception:
            pass

    def _fifo_wait_read(self, seq: int, timeout: float) -> BashResult:
        """Block (in-container, no x2p round-trips) until command <seq> finishes or
        `timeout` elapses, then return its output + exit code. Frames the reply
        between a leading `__VACLI_STATUS__` line and a trailing `__VACLI_END__`
        line; if the trailing marker is missing or ssh failed, the reply was
        truncated by a drop -> broken_pipe (recovery re-reads). Resumable."""
        maxb = self.config.max_session_buffer_size or (480 * 1024)
        t = max(1, int(timeout if timeout else self.config.session_timeout))
        script = (
            "D={D}; s={s}; deadline=$(( $(date +%s) + {t} )); "
            "while :; do "
            '[ -e "$D/d$s" ] && {{ st=ok; break; }}; '
            '[ "$(date +%s)" -ge "$deadline" ] && {{ st=timeout; break; }}; '
            "sleep 0.1; done; "
            'printf "__VACLI_STATUS__ %s %s\\n" "$st" "$(cat "$D/e$s" 2>/dev/null)"; '
            'head -c {mb1} "$D/o$s" 2>/dev/null; '
            'printf "\\n__VACLI_END__\\n"'
        ).format(D=shlex.quote(self._sess_dir), s=seq, t=t, mb1=maxb + 1)
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            "podman exec " + str(self._container_id) + " bash -c " + shlex.quote(script),
        ]
        try:
            r = self._sp.run(
                argv,
                stdin=self._sp.DEVNULL,
                stdout=self._sp.PIPE,
                stderr=self._sp.DEVNULL,
                timeout=t + 40,
            )
        except Exception as e:
            return _bash_result("error", f"[vacli] connection lost during wait: {e}", "broken_pipe", exit_code=-1)
        return self._parse_fifo_reply(r.returncode, r.stdout or b"")

    def _parse_fifo_reply(self, returncode: int, raw: bytes) -> BashResult:
        """Parse a framed reply: a leading `__VACLI_STATUS__ <st> <ec>` line, the
        command output, then a trailing `__VACLI_END__` line. A nonzero ssh rc or a
        missing/truncated frame means a drop cut the reply -> broken_pipe (recovery
        re-reads). Shared by _fifo_wait_read (recovery) and _fifo_exec_combined (hot
        path)."""
        maxb = self.config.max_session_buffer_size or (480 * 1024)
        si = raw.find(b"__VACLI_STATUS__")
        ei = raw.rfind(b"\n__VACLI_END__")
        if returncode != 0 or si < 0 or ei < 0 or si >= ei:
            return _bash_result(
                "error",
                f"[vacli] connection lost (rc={returncode}, truncated reply)",
                "broken_pipe",
                exit_code=-1,
            )
        nl = raw.find(b"\n", si)
        if nl < 0 or nl > ei:
            return _bash_result("error", "[vacli] connection lost (malformed reply)", "broken_pipe", exit_code=-1)
        status_line = raw[si:nl].decode("utf-8", "replace")
        out_bytes = raw[nl + 1 : ei]
        parts = status_line.split()
        st = parts[1] if len(parts) > 1 else "timeout"
        ec_str = parts[2] if len(parts) > 2 else ""
        too_long = len(out_bytes) > maxb
        output = (out_bytes[:maxb] if too_long else out_bytes).decode("utf-8", errors="ignore")
        if st == "timeout":
            return _bash_result("error", output, "timeout", exit_code=-1)
        if too_long:
            return _bash_result("error", output, "too_long", exit_code=-1)
        try:
            ec = int(ec_str)
        except (ValueError, TypeError):
            ec = -1
        if ec != 0:
            return _bash_result("error", output, "exit", exit_code=ec)
        return _bash_result("success", output, "none", exit_code=ec)

    def _fifo_exec_combined(
        self,
        seq: int,
        command: str,
        timeout: float,
        deadline: float | None = None,
    ) -> BashResult:
        """Happy-path fast lane: stage body + push token + wait + emit in ONE
        `podman exec` (4 x2p round-trips -> 1; ~4x lower per-command latency). Also
        frees the previous seq's files so disk stays bounded. On any drop the framed
        reply is absent -> broken_pipe with _pending kept, and recover_last() finishes
        the command via the careful separate path (the in-memory monotonic reader
        guard makes a re-push safe -> still exactly-once). Staging failure aborts
        before the token is pushed (exit 91 -> broken_pipe -> recover re-stages)."""
        maxb = self.config.max_session_buffer_size or (480 * 1024)
        t = max(1, int(timeout if timeout else self.config.session_timeout))
        if deadline is not None:
            t = max(1, min(t, int(self._remaining_timeout(deadline, t))))
        body = command if command.strip() else ":"
        script = (
            "D={D}; s={s}; p={p}; "
            'rm -f "$D/c$p" "$D/o$p" "$D/e$p" "$D/d$p" "$D/s$p" 2>/dev/null; '  # bound disk: prev seq
            'rm -f "$D/s$s" "$D/o$s" "$D/e$s" "$D/d$s" 2>/dev/null; '  # fresh markers (anti-forge)
            'cat > "$D/c$s.tmp" && mv -f "$D/c$s.tmp" "$D/c$s" || exit 91; '  # stage body (stdin)
            'printf "\\n%s\\n" "$s" > "$D/cmd"; '  # push token
            "deadline=$(( $(date +%s) + {t} )); "
            "while :; do "
            '[ -e "$D/d$s" ] && {{ st=ok; break; }}; '
            '[ "$(date +%s)" -ge "$deadline" ] && {{ st=timeout; break; }}; '
            "sleep 0.1; done; "
            'printf "__VACLI_STATUS__ %s %s\\n" "$st" "$(cat "$D/e$s" 2>/dev/null)"; '
            'head -c {mb1} "$D/o$s" 2>/dev/null; '
            'printf "\\n__VACLI_END__\\n"'
        ).format(D=shlex.quote(self._sess_dir), s=seq, p=seq - 1, t=t, mb1=maxb + 1)
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            "podman exec -i " + str(self._container_id) + " bash -c " + shlex.quote(script),
        ]
        try:
            r = self._sp.run(
                argv,
                input=body.encode("utf-8"),
                stdout=self._sp.PIPE,
                stderr=self._sp.DEVNULL,
                timeout=self._remaining_timeout(deadline, t + 40),
            )
        except Exception as e:
            return _bash_result("error", f"[vacli] connection lost during exec: {e}", "broken_pipe", exit_code=-1)
        return self._parse_fifo_reply(r.returncode, r.stdout or b"")

    def _fifo_finish(self, seq: int, res: BashResult) -> BashResult:
        """Common post-read handling: clear pending, clean up per-command files,
        and on a real timeout reset the shell (legacy parity: kill the runaway +
        fresh cwd/env)."""
        self._pending = None
        self._fifo_cleanup_seq(seq)
        if res["error_type"] == "timeout":
            self._teardown_fifo_shell()
            try:
                self._setup_fifo_shell(run_entrypoint=False, run_start_script=True)
            except Exception as e:
                logger.warning("fifo: shell recreate after timeout failed: %s", e)
        return res

    def _fifo_run(
        self,
        command: str,
        timeout: float,
        deadline: float | None = None,
    ) -> BashResult:
        """Stage + trigger + collect one command in a SINGLE podman exec (hot path).
        On a tunnel drop the framed reply is absent -> broken_pipe with `_pending`
        kept, so recover_last() finishes it WITHOUT re-executing (the in-memory
        monotonic reader guard makes a re-push safe)."""
        self._cmd_seq += 1
        seq = self._cmd_seq
        start = time.monotonic()
        self._pending = (seq, command, timeout, start)
        res = self._fifo_exec_combined(seq, command, timeout, deadline)
        if res["error_type"] == "broken_pipe":
            return res  # _pending kept; recover_last() finishes it
        # Completed (success/exit/timeout/too_long): clear pending; on a real timeout
        # reset the shell (legacy parity: kill the runaway + fresh cwd/env). Per-command
        # files are freed by the NEXT command's combined call (prev-seq cleanup) and by
        # destroy()'s teardown, so no extra round-trip here.
        self._pending = None
        if res["error_type"] == "timeout":
            self._teardown_fifo_shell()
            try:
                self._setup_fifo_shell(run_entrypoint=False, run_start_script=True)
            except Exception as e:
                logger.warning("fifo: shell recreate after timeout failed: %s", e)
        return res

    @_lifecycle_serialized
    def recover_last(self) -> "BashResult | None":
        """After restart_session() re-establishes the tunnel, finish the command
        the drop interrupted -- WITHOUT re-running one that already executed. The
        in-container shell + its in-flight command survived the drop. Execution is
        gated on the in-container `started` marker s<seq>, never on an ssh return
        code, so re-pushing a token that already ran is impossible.

        Returns the recovered BashResult, or None when there is nothing to recover
        or the shell had to be rebuilt (so env.py uses its legacy 'shell was reset'
        contract -- the in-flight command is genuinely gone in that case)."""
        if self._destroyed or not self._fifo_mode:
            return None
        if self._shell_was_reset:
            # restart_session had to recreate a DEAD shell: state + the in-flight
            # command are gone. Don't pretend transparency.
            self._shell_was_reset = False
            self._pending = None
            self._last_command = None
            return None
        if self._pending is None:
            return None
        seq, command, timeout, start = self._pending
        # 1) ensure the body is staged (idempotent atomic overwrite).
        m_c = self._fifo_marker(seq, "c")
        if m_c is None:
            return _bash_result("error", "[vacli] connection lost (probe c)", "broken_pipe", exit_code=-1)
        if m_c is False and not self._fifo_stage(seq, command):
            return _bash_result("error", "[vacli] connection lost (re-stage)", "broken_pipe", exit_code=-1)
        # 2) has the reader already STARTED this seq? (s<seq>). Only push if not.
        #    A small settle closes the (sub-ms) window between the token landing and
        #    the reader writing s<seq>; restart_session latency already dwarfs it.
        m_s = self._fifo_marker(seq, "s")
        if m_s is None:
            return _bash_result("error", "[vacli] connection lost (probe s)", "broken_pipe", exit_code=-1)
        if m_s is False:
            time.sleep(1.0)
            m_s = self._fifo_marker(seq, "s")
            if m_s is None:
                return _bash_result("error", "[vacli] connection lost (probe s2)", "broken_pipe", exit_code=-1)
            if m_s is False and not self._fifo_push(seq):
                return _bash_result("error", "[vacli] connection lost (re-push)", "broken_pipe", exit_code=-1)
        # 3) wait, clamping the budget to the time remaining on the original cap so
        #    repeated reconnects can't multiply a command's runtime.
        rem = max(2, int(timeout - (time.monotonic() - start)))
        res = self._fifo_wait_read(seq, rem)
        if res["error_type"] == "broken_pipe":
            return res  # dropped again; _pending kept for the next reconnect
        return self._fifo_finish(seq, res)

    def restart_session(self) -> bool:
        """Recover from a dropped ssh channel (e.g. ConnectionResetError during
        grading) by re-attaching a fresh bash session to the SAME container over
        the SAME lease. Nothing is re-leased and the container is never removed,
        so the agent's full filesystem state is preserved and a subsequent
        re-grade is valid. Returns True iff a live session is re-established.

        Returns False (caller should give up and score env_error) when the box
        is genuinely gone — lease/sshd dead or the container no longer running —
        because there is then nothing to grade."""
        if self._destroy_requested.is_set():
            return False
        with self._lifecycle_lock:
            if self._destroy_requested.is_set() and not self._destroying:
                return False
            if self._command_cancel_requested.is_set() and not self._destroying:
                return False
            return self._restart_session_locked()

    def _restart_session_locked(self) -> bool:
        if self._destroyed or self._container_id is None:
            return False
        # Drop the dead session.
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:
                pass
            self._session = None
        # A recovery attempt may create a new OpenSSH master. Retire the exact
        # old master first and give the attempt a fresh random path so a late
        # unlink or a stale socket can never be mistaken for the new owner.
        try:
            self._retire_control_master(self._control_path)
        except _ArtifactCleanupError as cleanup_error:
            logger.warning("vacli.restart_session: control cleanup failed: %s", cleanup_error)
            return False
        self._control_path = self._local_artifacts.new_control_path()
        self._local_artifacts.record_control_port(self._control_path, self._ssh_port)
        try:
            _wait_for_sshd(
                self._ssh_port,
                # Wait on the ORIGINAL tunnel first (vacli not yet killed) so a
                # transient x2p blip can SELF-HEAL -- production data showed ~2/3 of
                # mid-rollout drops recover within ~60s if we just wait, vs failing
                # the SIGKILL+resume path ("sshd unreachable after resume") while the
                # blip is still ongoing. 60s matches v0's original-port wait; only
                # after it stays dead do we SIGKILL + resume below (the fallback for a
                # genuinely-gone VM). Costs up to ~60s extra on a truly-dead box, but
                # those rollouts are dropped anyway, and it converts the common
                # self-healing blips into clean seamless recoveries.
                timeout=min(float(self.config.sshd_ready_timeout), 60.0),
                control_path=None,
                subprocess_mod=self.config.subprocess_mod,
            )
            self._start_control_master()
        except BaseException as e:
            try:
                self._retire_control_master(self._control_path)
            except BaseException as cleanup_error:
                raise _ArtifactCleanupError("failed SSH recovery control was not retired") from cleanup_error
            if not isinstance(e, Exception):
                raise
            # sshd unreachable on the existing tunnel: the x2p tunnel (or the
            # vacli that owned it) is gone. Don't give up — the VM itself is
            # almost always still alive (we essentially never see the container
            # die). Re-establish a fresh tunnel to the SAME VM via resume.
            logger.warning("vacli.restart_session: sshd not reachable: %s -- resuming tunnel", e)
            new_port = self._lease.restart_tunnel()
            if new_port is None:
                logger.warning("vacli.restart_session: tunnel resume failed; box unrecoverable")
                return False
            self._control_path = self._local_artifacts.new_control_path()
            self._ssh_port = new_port
            self._local_artifacts.record_control_port(self._control_path, new_port)
            try:
                _wait_for_sshd(
                    self._ssh_port,
                    timeout=min(float(self.config.sshd_ready_timeout), 60.0),
                    control_path=None,
                    subprocess_mod=self.config.subprocess_mod,
                )
                self._start_control_master()
            except BaseException as e2:
                try:
                    self._retire_control_master(self._control_path)
                except BaseException as cleanup_error:
                    raise _ArtifactCleanupError("resumed SSH control was not retired") from cleanup_error
                if not isinstance(e2, Exception):
                    raise
                logger.warning("vacli.restart_session: sshd still unreachable after resume: %s", e2)
                return False
            logger.info(
                "vacli.restart_session: tunnel resumed to same VM on new port %d",
                self._ssh_port,
            )
        # The container must still be running, else the agent's work is gone.
        try:
            chk = self._ssh_call_raw(
                "podman inspect -f '{{.State.Running}}' " + str(self._container_id),
                timeout=30,
            )
        except Exception as e:
            logger.warning("vacli.restart_session: container check raised: %s", e)
            return False
        if chk.returncode != 0 or b"true" not in (chk.stdout or b"").lower():
            logger.warning(
                "vacli.restart_session: container %s not running (rc=%s) -- giving up",
                self._container_id,
                chk.returncode,
            )
            return False
        if not self._restore_host_tunnels():
            return False
        # FIFO mode: the persistent shell lives INSIDE the container, so it
        # survived the drop -- cwd/env + any in-flight command are intact. Do NOT
        # rebuild it (that would lose state); just verify it is still alive. Only
        # if it somehow died do we recreate a fresh one (state lost, box usable).
        if self._fifo_mode:
            if self._fifo_shell_alive():
                logger.info(
                    "vacli.restart_session: fifo shell survived drop on container %s (state intact)",
                    self._container_id,
                )
                return True
            logger.warning(
                "vacli.restart_session: fifo shell dead on container %s -- recreating",
                self._container_id,
            )
            # The shell (and any in-flight command) is genuinely gone: tear down the
            # orphaned reader/held-writer, then build a fresh shell. Flag it so
            # recover_last() declines transparent recovery (state was lost) and
            # env.py falls back to telling the agent the shell was reset.
            try:
                self._teardown_fifo_shell()
            except Exception:
                pass
            try:
                self._setup_fifo_shell(run_entrypoint=False, run_start_script=True)
            except Exception as e:
                logger.warning("vacli.restart_session: fifo shell recreate failed: %s", e)
                return False
            self._shell_was_reset = True
            return True
        # Legacy mode: re-attach a fresh bash to the same container; skip the task
        # entrypoint (state already exists) but re-apply the proxy/env preamble.
        try:
            self._open_session(run_entrypoint=False)
        except Exception as e:
            logger.warning("vacli.restart_session: re-open session failed: %s", e)
            return False
        logger.info(
            "vacli.restart_session: re-attached to container %s on same lease",
            self._container_id,
        )
        return True

    @property
    def duration(self) -> float:
        return time.perf_counter() - self.init_start_time

    def _compose_command(self, args: list[str], *, timeout: int) -> subprocess.CompletedProcess:
        if self._compose_project is None or self._compose_dir is None:
            raise RuntimeError("VMVM compose project is not initialized")
        command = [
            "podman",
            "compose",
            "--project-name",
            self._compose_project,
            "--project-directory",
            self._compose_dir,
            "-f",
            f"{self._compose_dir}/base.json",
            "-f",
            f"{self._compose_dir}/docker-compose.yaml",
            *args,
        ]
        return self._ssh_call_raw(shlex.join(command), timeout=timeout)

    def _write_host_file(self, path: str, content: bytes) -> None:
        parent = str(PurePosixPath(path).parent)
        prepared = self._ssh_call_raw(
            f"mkdir -p {shlex.quote(parent)}",
            timeout=30,
        )
        if prepared.returncode != 0:
            detail = (prepared.stdout or b"").decode("utf-8", errors="replace")
            raise BackendInitError(f"creating compose directory failed: {detail[-1000:]}")
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            f"cat > {shlex.quote(path)}",
        ]
        written = self._sp.run(
            argv,
            input=content,
            stdout=self._sp.PIPE,
            stderr=self._sp.STDOUT,
            timeout=60,
        )
        if written.returncode != 0:
            detail = (written.stdout or b"").decode("utf-8", errors="replace")
            raise BackendInitError(f"writing compose file failed: {detail[-1000:]}")

    @_lifecycle_serialized
    def start_compose(self, compose_yaml: bytes) -> str:
        """Replace the single task container with the task's Compose project.

        The lease and SSH control connection are retained. The generated base
        file matches Harbor's prebuilt environment: the task image is the main
        service and its command is a keepalive, while a task compose file may
        add sidecars or override main (including its image entrypoint).
        """
        if self._destroyed or self._container_id is None:
            raise RuntimeError("start_compose called before VMVM initialization")
        if self._compose_project is not None:
            raise RuntimeError("start_compose called more than once")

        old_container = self._container_id
        if self._session is not None:
            self._session.stop()
            self._session = None
        if self._fifo_mode:
            self._teardown_fifo_shell()
        self._fifo_mode = False
        self._sess_dir = ""
        removed = self._ssh_call_raw(f"podman rm -f {old_container}", timeout=30)
        if removed.returncode != 0:
            detail = (removed.stdout or b"").decode("utf-8", errors="replace")
            raise BackendInitError(f"removing bootstrap container failed: {detail[-1000:]}")
        self._container_id = None

        nonce = uuid.uuid4().hex[:12]
        self._compose_project = f"vf-{nonce}"
        self._compose_dir = f"/tmp/vmvm-compose-{nonce}"
        base = {
            "services": {
                "main": {
                    "image": self.config.image_url,
                    "command": ["sh", "-c", "sleep infinity"],
                    "privileged": CONTAINER_PRIVILEGED,
                }
            }
        }
        if self.config.cpu is not None:
            base["services"]["main"]["cpus"] = self.config.cpu
        if self.config.memory_gb is not None:
            base["services"]["main"]["mem_limit"] = f"{self.config.memory_gb}g"
        self._write_host_file(
            f"{self._compose_dir}/base.json",
            json.dumps(base, separators=(",", ":")).encode(),
        )
        self._write_host_file(
            f"{self._compose_dir}/docker-compose.yaml",
            compose_yaml,
        )

        try:
            timeout = max(300, int(self.config.session_timeout))
            api = self._ssh_call_raw(
                "mkdir -p /run/podman; "
                "if ! test -S /run/podman/podman.sock; then "
                "nohup podman system service --time=0 unix:///run/podman/podman.sock "
                ">/tmp/vmvm-podman-service.log 2>&1 </dev/null & "
                "fi; "
                "for i in $(seq 1 100); do test -S /run/podman/podman.sock && exit 0; sleep 0.1; done; "
                "cat /tmp/vmvm-podman-service.log 2>/dev/null; exit 1",
                timeout=30,
            )
            if api.returncode != 0:
                detail = (api.stdout or b"").decode("utf-8", errors="replace")
                raise BackendInitError(f"starting Podman API service failed: {detail[-1000:]}")
            logger.info(
                "vacli: starting Compose project %s; directory=%s",
                self._compose_project,
                self._compose_dir,
            )
            started = self._compose_command(
                ["up", "--detach", "--wait", "--wait-timeout", str(timeout)],
                timeout=timeout + 60,
            )
            if started.returncode != 0:
                detail = (started.stdout or b"").decode("utf-8", errors="replace")
                raise BackendInitError(f"podman compose up failed: {detail[-4000:]}")
            services_result = self._compose_command(["config", "--services"], timeout=30)
            services_output = (services_result.stdout or b"").decode("utf-8", errors="replace")
            services_output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", services_output)
            if services_result.returncode != 0:
                raise BackendInitError(f"podman compose service lookup failed: {services_output[-1000:]}")
            self._compose_services = tuple(
                line.strip()
                for line in services_output.splitlines()
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", line.strip())
            )
            resolved = self._compose_command(["ps", "-q", "main"], timeout=30)
            output = (resolved.stdout or b"").decode("utf-8", errors="replace")
            output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
            container_ids = [line.strip() for line in output.splitlines() if _CONTAINER_ID_RE.fullmatch(line.strip())]
            if resolved.returncode != 0 or not container_ids:
                detail = (resolved.stdout or b"").decode("utf-8", errors="replace")
                raise BackendInitError(f"podman compose main lookup failed: {detail[-1000:]}")
            self._container_id = _validate_container_id(container_ids[-1])
            _ensure_python_in_container(
                self._sp,
                self._ssh_port,
                self._control_path,
                self._container_id,
            )
            self._proxy_gateway = _setup_bridge_proxy(
                self._sp,
                self._ssh_port,
                self._control_path,
                self._container_id,
                self._compose_services,
                require_detected=True,
            )
            self._open_session(run_entrypoint=False)
            workdir = self.run_root_bash(
                f"mkdir -p {shlex.quote(self.config.work_dir)}",
                timeout=60,
            )
            if workdir["exit_code"] != 0:
                raise BackendInitError(f"creating Compose workdir failed: {workdir['output'][-1000:]}")
            logger.info(
                "vacli: Compose project %s ready; main=%s",
                self._compose_project,
                self._container_id,
            )
            return self._container_id
        except Exception:
            try:
                self._compose_command(
                    ["down", "--volumes", "--remove-orphans"],
                    timeout=120,
                )
            except Exception:
                logger.exception("vacli: failed to clean up partial compose project")
            raise

    @_lifecycle_serialized
    def run_service_bash(
        self,
        service: str,
        command: str,
        timeout: float = 60.0,
        env: dict[str, str] | None = None,
        user: str | int | None = None,
    ) -> BashResult:
        """Run one command in a Compose sidecar (or the persistent main shell)."""
        if self._destroyed:
            raise RuntimeError("run_service_bash called after destroy")
        if service in ("", "main"):
            return self.run_bash(command, timeout)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", service):
            raise ValueError(f"invalid compose service name: {service!r}")
        args = ["exec", "-T"]
        for key, value in (env or {}).items():
            args.extend(["--env", f"{key}={value}"])
        if user is not None:
            args.extend(["--user", str(user)])
        args.extend([service, "sh", "-c", command])
        try:
            result = self._compose_command(args, timeout=max(1, int(timeout)) + 30)
        except subprocess.TimeoutExpired:
            return _bash_result("error", "compose exec timed out", "timeout", exit_code=-1)
        output = (result.stdout or b"").decode("utf-8", errors="replace")
        if result.returncode == 255:
            return _bash_result("error", output, "broken_pipe", exit_code=-1)
        if result.returncode != 0:
            return _bash_result("error", output, "exit", exit_code=result.returncode)
        return _bash_result("success", output, "none", exit_code=0)

    @_lifecycle_serialized
    def run_root_bash(self, command: str, timeout: float = 60.0) -> BashResult:
        """Run one runtime-management command as root in the main container.

        Agent commands continue to use the image's declared user. This narrow
        path is for harness-owned staging into locations such as /tests and
        /solution, matching docker-copy semantics for non-root task images.
        """
        if self._destroyed or self._container_id is None:
            raise RuntimeError("run_root_bash called without a live container")
        remote = f"podman exec --user 0 {self._container_id} sh -c {shlex.quote(command)}"
        try:
            result = self._ssh_call_raw(remote, timeout=max(1, int(timeout)))
        except subprocess.TimeoutExpired:
            return _bash_result("error", "root command timed out", "timeout", exit_code=-1)
        output = (result.stdout or b"").decode("utf-8", errors="replace")
        if result.returncode == 255:
            return _bash_result("error", output, "broken_pipe", exit_code=-1)
        if result.returncode != 0:
            return _bash_result("error", output, "exit", exit_code=result.returncode)
        return _bash_result("success", output, "none", exit_code=0)

    @_lifecycle_serialized
    def read_service_file(self, service: str, remote_path: str | Path) -> bytes:
        """Read a file from a Compose sidecar without mixing stderr into bytes."""
        if self._destroyed:
            raise RuntimeError("read_service_file called after destroy")
        if service in ("", "main"):
            return self.read_file(remote_path)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", service):
            raise ValueError(f"invalid compose service name: {service!r}")
        if self._compose_project is None or self._compose_dir is None:
            raise RuntimeError("sidecar read requested without a Compose project")
        command = [
            "podman",
            "compose",
            "--project-name",
            self._compose_project,
            "--project-directory",
            self._compose_dir,
            "-f",
            f"{self._compose_dir}/base.json",
            "-f",
            f"{self._compose_dir}/docker-compose.yaml",
            "exec",
            "-T",
            "--user",
            "0",
            service,
            "cat",
            "--",
            str(remote_path),
        ]
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            shlex.join(command),
        ]
        result = self._sp.run(
            argv,
            stdin=self._sp.DEVNULL,
            stdout=self._sp.PIPE,
            stderr=self._sp.PIPE,
            timeout=int(self.config.session_timeout),
        )
        if result.returncode != 0:
            detail = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(f"reading {remote_path!s} from {service} failed: {detail[-1000:]}")
        return result.stdout or b""

    # -- public ToolBackend surface ----------------------------------------

    @_lifecycle_serialized
    def run_bash(self, command: str, timeout: float = 60.0) -> BashResult:
        """Run a command inside the container's persistent shell.

        `timeout` is the per-command cap. On expiry the running command is
        abandoned and the shell is reset for the next call. None falls back to the
        session_timeout.

        Shell state (cwd, env vars, sourced venvs, defined functions) persists
        across calls because every command runs in the same long-lived shell.
        In FIFO mode that shell lives inside the container, so a mid-rollout x2p
        tunnel drop does not destroy it: restart_session() re-attaches and
        recover_last() finishes the interrupted command.
        """
        self._begin_command()
        try:
            return self._run_bash_once(command, timeout)
        finally:
            self._end_command()

    @_lifecycle_serialized
    def run_bash_with_recovery(
        self,
        command: str,
        timeout: float,
        max_attempts: int,
    ) -> BashResult:
        """Run and recover one exact-once command under one cancellation scope."""
        self._begin_command()
        try:
            result = self._run_bash_once(command, timeout)
            for attempt in range(1, max_attempts + 1):
                if result["exit_code"] >= 0 or result["error_type"] != "broken_pipe":
                    break
                if self._command_cancel_requested.is_set():
                    return _bash_result("error", "", "exit", exit_code=130)
                logger.warning(
                    "vacli: transport dropped; recovering the in-flight command (%d/%d)",
                    attempt,
                    max_attempts,
                )
                try:
                    restarted = self.restart_session()
                except Exception as error:
                    raise RuntimeError(f"VMVM reconnect failed: {error}") from error
                if not restarted:
                    raise RuntimeError("VMVM reconnect failed: sandbox state is unavailable")
                if self._command_cancel_requested.is_set():
                    return _bash_result("error", "", "exit", exit_code=130)
                try:
                    recovered = self.recover_last()
                except Exception as error:
                    raise RuntimeError(f"VMVM command recovery failed: {error}") from error
                if recovered is None:
                    raise RuntimeError("VMVM command recovery failed: exact-once execution cannot be proven")
                result = recovered
                if self._command_cancel_requested.is_set():
                    return _bash_result("error", "", "exit", exit_code=130)
            return result
        finally:
            self._end_command()

    def _run_bash_once(self, command: str, timeout: float) -> BashResult:
        if self._destroyed:
            return _bash_result("error", "", "exit", exit_code=-1)
        # FIFO-backed persistent shell (the v1 drop-recovery path).
        if self._fifo_mode:
            if not self._sess_dir:
                return _bash_result("error", "session not initialized", "other", exit_code=-1)
            self._last_command = command
            self._last_timeout = timeout
            return self._fifo_run(command, timeout)
        # Legacy streamed session (image without bash+mkfifo).
        session = self._session
        if session is None:
            return _bash_result("error", "session not initialized", "other", exit_code=-1)
        t0 = time.perf_counter()
        logger.debug(f"vacli.run_bash starting (cmd_len={len(command)} head={command[:80]!r})")
        try:
            output = session.communicate(command, timeout=timeout)
        except Exception as e:
            logger.debug(f"vacli.run_bash raised after {time.perf_counter() - t0:.1f}s: {type(e).__name__}: {e}")
            return _bash_result("error", f"{type(e).__name__}: {e}", "other", exit_code=-1)
        # AsyncSession's `status` reports session-level health (timeout, broken
        # pipe, bash died). A user command exiting non-zero is NOT a session
        # failure — bash stays alive. But DES's convention is that a non-zero
        # exit is reported as status="error", error_type="exit". Match that so
        # downstream consumers (tool_types.make_python_plugin, swerl/tools.py,
        # swerl/eval_backend/eval.py) see the same shape from both backends.
        logger.debug(
            f"vacli.run_bash communicate returned in {time.perf_counter() - t0:.1f}s "
            f"status={output['status']!r} error_type={output['error_type']!r} "
            f"output_len={len(output['output'])}"
        )
        if output["status"] == "success":
            exit_code = session.get_exitcode()
            if exit_code is None:
                exit_code = -1
            if exit_code != 0:
                return _bash_result("error", output["output"], "exit", exit_code=exit_code)
            return _bash_result("success", output["output"], "none", exit_code=0)
        # Session-level error (timeout / broken_pipe / exit / too_long / other).
        # get_exitcode would itself try to talk to a dead session — skip it.
        return _bash_result(output["status"], output["output"], output["error_type"], exit_code=-1)

    def _checked_host_command(
        self,
        command: str,
        *,
        action: str,
        timeout: int = 30,
    ) -> str:
        result = self._ssh_call_raw(command, timeout=timeout)
        output = (result.stdout or b"").decode("utf-8", errors="replace")
        if result.returncode != 0:
            raise BackendInitError(f"{action} failed: {output[-2000:]}")
        return output.strip()

    def _compose_container(self, service: str) -> str:
        resolved = self._compose_command(["ps", "-q", service], timeout=30)
        output = (resolved.stdout or b"").decode("utf-8", errors="replace")
        output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output)
        container_ids = [line.strip() for line in output.splitlines() if _CONTAINER_ID_RE.fullmatch(line.strip())]
        if resolved.returncode != 0 or len(container_ids) != 1:
            raise BackendInitError(
                f"network isolation requires exactly one running {service!r} "
                f"Compose container; observed {len(container_ids)}"
            )
        return _validate_container_id(container_ids[0])

    def _network_targets(self) -> tuple[tuple[str, str], ...]:
        if self._container_id is None:
            raise RuntimeError("network policy configured without a live container")
        if self._compose_project is None:
            return (("main", self._container_id),)
        return tuple((service, self._compose_container(service)) for service in self._compose_services)

    def _container_networks(self, container_id: str) -> dict[str, dict[str, Any]]:
        output = self._checked_host_command(
            "podman inspect --format '{{json .NetworkSettings.Networks}}' " + container_id,
            action=f"inspecting networks for container {container_id}",
        )
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as error:
            raise BackendInitError(
                f"podman returned malformed network settings for {container_id}: {output[-1000:]!r}"
            ) from error
        if not isinstance(parsed, dict):
            raise BackendInitError(f"podman returned non-object network settings for {container_id}")
        networks: dict[str, dict[str, Any]] = {}
        for name, settings in parsed.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
                raise BackendInitError(f"podman returned invalid network name for {container_id}: {name!r}")
            if not isinstance(settings, dict):
                raise BackendInitError(f"podman returned invalid settings for network {name!r}")
            networks[name] = settings
        return networks

    @_lifecycle_serialized
    def prepare_network_isolation(self) -> None:
        """Attach all workload containers to one private internal network.

        Existing bridge networks remain attached during trusted harness setup.
        ``activate_network_isolation`` removes them immediately before the
        untrusted program runs.
        """
        if self._destroyed:
            raise RuntimeError("network policy configured after destroy")
        if self._network_isolation is not None:
            return

        self._checked_host_command(
            "command -v iptables >/dev/null && iptables -w 5 -L INPUT -n >/dev/null",
            action="checking VMVM network-isolation firewall support",
        )
        nonce = uuid.uuid4().hex[:12]
        network = f"vf-internal-{nonce}"
        firewall_chain = f"VFNI_{nonce.upper()}"
        created = self._ssh_call_raw(
            f"podman network create --internal {shlex.quote(network)}",
            timeout=30,
        )
        if created.returncode != 0:
            detail = (created.stdout or b"").decode("utf-8", errors="replace")
            raise BackendInitError(f"creating internal Podman network failed: {detail[-2000:]}")

        try:
            output = self._checked_host_command(
                f"podman network inspect {shlex.quote(network)}",
                action="inspecting internal Podman network",
            )
            try:
                inspected = json.loads(output)
                config = inspected[0]
                subnet_configs = config["subnets"]
                if not isinstance(subnet_configs, list) or len(subnet_configs) != 1:
                    raise TypeError("expected exactly one Podman subnet")
                subnet_config = subnet_configs[0]
                subnet = str(subnet_config["subnet"])
                gateway = str(subnet_config["gateway"])
            except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
                raise BackendInitError(
                    f"podman returned malformed internal network metadata: {output[-1000:]!r}"
                ) from error
            if config.get("internal") is not True:
                raise BackendInitError(f"Podman network {network!r} was not marked internal")
            if config.get("ipv6_enabled") is True:
                raise BackendInitError(f"Podman network {network!r} unexpectedly enabled IPv6")
            parsed_subnet = ipaddress.ip_network(subnet, strict=False)
            parsed_gateway = ipaddress.ip_address(gateway)
            if (
                parsed_subnet.version != 4
                or not parsed_subnet.is_private
                or parsed_gateway.version != 4
                or parsed_gateway not in parsed_subnet
            ):
                raise BackendInitError(f"invalid internal IPv4 network {subnet!r} gateway {gateway!r}")

            targets = self._network_targets()
            for service, container_id in targets:
                aliases = {service}
                for settings in self._container_networks(container_id).values():
                    declared_aliases = settings.get("Aliases") or settings.get("aliases")
                    if declared_aliases is None:
                        continue
                    if not isinstance(declared_aliases, list):
                        raise BackendInitError(f"podman returned invalid aliases for container {container_id}")
                    for alias in declared_aliases:
                        if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", alias):
                            raise BackendInitError(
                                f"podman returned invalid network alias for container {container_id}: {alias!r}"
                            )
                        aliases.add(alias)
                connect = ["podman", "network", "connect"]
                for alias in sorted(aliases):
                    connect.extend(["--alias", alias])
                connect.extend([network, container_id])
                self._checked_host_command(
                    shlex.join(connect),
                    action=f"attaching Compose service {service!r} to internal network",
                )
            main_network = self._container_networks(str(self._container_id)).get(network)
            main_address = (
                ""
                if main_network is None
                else str(main_network.get("IPAddress") or main_network.get("ip_address") or "")
            )
            parsed_main = ipaddress.ip_address(main_address)
            if parsed_main.version != 4 or parsed_main not in parsed_subnet:
                raise BackendInitError(f"invalid main-container address {main_address!r} on {network!r}")
            self._network_isolation = _VacliNetworkIsolation(
                network=network,
                gateway=str(parsed_gateway),
                subnet=str(parsed_subnet),
                main_address=str(parsed_main),
                firewall_chain=firewall_chain,
                containers=tuple(dict.fromkeys(container_id for _, container_id in targets)),
            )
            logger.info(
                "vacli: prepared internal workload network %s (%s)",
                network,
                parsed_subnet,
            )
        except Exception:
            self._ssh_call_raw(
                f"podman network rm -f {shlex.quote(network)} >/dev/null 2>&1 || true",
                timeout=30,
            )
            raise

    @staticmethod
    def _iptables_command(*args: str) -> str:
        return shlex.join(["iptables", "-w", "5", *args])

    def _cleanup_network_firewall(self) -> None:
        isolation = self._network_isolation
        if isolation is None or not isolation.firewall_active:
            return
        jump = [
            "-s",
            isolation.subnet,
            "-d",
            isolation.gateway,
            "-j",
            isolation.firewall_chain,
        ]
        command = (
            "while "
            + self._iptables_command("-C", "INPUT", *jump)
            + " >/dev/null 2>&1; do "
            + self._iptables_command("-D", "INPUT", *jump)
            + "; done; "
            + self._iptables_command("-F", isolation.firewall_chain)
            + " >/dev/null 2>&1 || true; "
            + self._iptables_command("-X", isolation.firewall_chain)
            + " >/dev/null 2>&1 || true"
        )
        result = self._ssh_call_raw(command, timeout=30)
        if result.returncode != 0:
            detail = (result.stdout or b"").decode("utf-8", errors="replace")
            logger.warning("vacli: network firewall cleanup failed: %s", detail[-1000:])
        isolation.firewall_active = False
        isolation.allowed_tunnel_ports.clear()

    def _allow_isolated_tunnel(self, remote_port: int) -> None:
        isolation = self._network_isolation
        if isolation is None or not isolation.firewall_active or remote_port in isolation.allowed_tunnel_ports:
            return
        command = self._iptables_command(
            "-I",
            isolation.firewall_chain,
            "1",
            "-s",
            f"{isolation.main_address}/32",
            "-p",
            "tcp",
            "--dport",
            str(remote_port),
            "-j",
            "ACCEPT",
        )
        self._checked_host_command(
            command,
            action=f"allowing isolated VMVM host tunnel port {remote_port}",
        )
        isolation.allowed_tunnel_ports.add(remote_port)

    def _remove_isolated_tunnel(self, remote_port: int) -> None:
        isolation = self._network_isolation
        if isolation is None or not isolation.firewall_active or remote_port not in isolation.allowed_tunnel_ports:
            return
        command = self._iptables_command(
            "-D",
            isolation.firewall_chain,
            "-s",
            f"{isolation.main_address}/32",
            "-p",
            "tcp",
            "--dport",
            str(remote_port),
            "-j",
            "ACCEPT",
        )
        result = self._ssh_call_raw(command, timeout=30)
        if result.returncode != 0:
            detail = (result.stdout or b"").decode("utf-8", errors="replace")
            logger.warning(
                "vacli: isolated tunnel firewall cleanup failed: %s",
                detail[-1000:],
            )
        isolation.allowed_tunnel_ports.discard(remote_port)

    @_lifecycle_serialized
    def activate_network_isolation(self) -> None:
        """Remove public networks and permit only internal DNS and host tunnels."""
        if self._destroyed:
            raise RuntimeError("network policy activated after destroy")
        isolation = self._network_isolation
        if isolation is None:
            raise RuntimeError("network isolation was not prepared")
        if isolation.active:
            return

        chain = isolation.firewall_chain
        jump = [
            "-s",
            isolation.subnet,
            "-d",
            isolation.gateway,
            "-j",
            chain,
        ]
        commands = [
            self._iptables_command("-N", chain),
            self._iptables_command("-A", chain, "-p", "udp", "--dport", "53", "-j", "ACCEPT"),
            self._iptables_command("-A", chain, "-p", "tcp", "--dport", "53", "-j", "ACCEPT"),
        ]
        for tunnel in sorted(self._host_tunnels, key=lambda item: item.remote_port):
            commands.append(
                self._iptables_command(
                    "-A",
                    chain,
                    "-s",
                    f"{isolation.main_address}/32",
                    "-p",
                    "tcp",
                    "--dport",
                    str(tunnel.remote_port),
                    "-j",
                    "ACCEPT",
                )
            )
        commands.extend(
            [
                self._iptables_command("-A", chain, "-j", "REJECT"),
                self._iptables_command("-I", "INPUT", "1", *jump),
            ]
        )
        firewall = self._ssh_call_raw("set -e; " + "; ".join(commands), timeout=30)
        if firewall.returncode != 0:
            detail = (firewall.stdout or b"").decode("utf-8", errors="replace")
            # The compound install may have failed after inserting the INPUT
            # jump. Mark it live so the normal idempotent teardown removes any
            # partial jump/chain before surfacing the failure.
            isolation.firewall_active = True
            self._cleanup_network_firewall()
            raise BackendInitError(f"installing VMVM network-isolation firewall failed: {detail[-2000:]}")
        isolation.firewall_active = True
        isolation.allowed_tunnel_ports.update(tunnel.remote_port for tunnel in self._host_tunnels)

        try:
            for container_id in isolation.containers:
                networks = self._container_networks(container_id)
                if isolation.network not in networks:
                    raise BackendInitError(f"container {container_id} lost internal network {isolation.network!r}")
                for network in networks:
                    if network == isolation.network:
                        continue
                    self._checked_host_command(
                        shlex.join(
                            [
                                "podman",
                                "network",
                                "disconnect",
                                "--force",
                                network,
                                container_id,
                            ]
                        ),
                        action=f"disconnecting public network {network!r}",
                    )
                remaining = self._container_networks(container_id)
                if set(remaining) != {isolation.network}:
                    raise BackendInitError(
                        f"container {container_id} retained unexpected networks: {sorted(remaining)}"
                    )
        except Exception:
            # Fail closed: a partially isolated workload must not keep running
            # while the rollout unwinds and releases the lease.
            self._ssh_call_raw(
                "podman pause " + " ".join(isolation.containers) + " >/dev/null 2>&1 || true",
                timeout=30,
            )
            self._cleanup_network_firewall()
            raise

        isolation.active = True
        logger.info(
            "vacli: workload network isolated on %s; gateway permits DNS and %d host tunnel(s)",
            isolation.network,
            len(isolation.allowed_tunnel_ports),
        )

    def destroy(self) -> None:
        # Cancellation may be rebuilding the persistent shell.  Serialize lease
        # destruction with that state transition so teardown never races a reset.
        self._destroy_requested.set()
        with self._command_cancel_lock:
            with self._lifecycle_lock:
                self._destroy_locked()
                callback = getattr(self, "_destroy_atexit_callback", None)
                if callback is not None:
                    atexit.unregister(callback)
                    self._destroy_atexit_callback = None

    def _destroy_locked(self) -> None:
        self._destroyed = True
        self._destroying = True
        try:
            registry_error: BaseException | None = None
            remote_error: BaseException | None = None
            lease_error: BaseException | None = None
            if not getattr(self, "_remote_cleanup_complete", False):
                try:
                    self._destroy_remote_resources()
                except BaseException as error:
                    remote_error = error
                finally:
                    self._remote_cleanup_complete = True
            if not self._local_artifacts.sealed:
                try:
                    self._local_artifacts.bind_control(self._control_path, required=False)
                    self._local_artifacts.seal()
                except BaseException as error:
                    registry_error = error
            try:
                self._lease.cleanup()
            except BaseException as error:
                lease_error = error
            if lease_error is None:
                for cleanup in (
                    self._local_artifacts.cleanup_controls,
                    self._local_artifacts.cleanup_logs,
                ):
                    try:
                        cleanup()
                    except BaseException as error:
                        registry_error = registry_error or error
            if lease_error is not None or registry_error is not None:
                cleanup_error = _ArtifactCleanupError("VMVM local artifact cleanup was not verified")
                if remote_error is not None:
                    cleanup_error.add_note(f"remote teardown also failed: {type(remote_error).__name__}")
                raise cleanup_error from (lease_error or registry_error)
            if remote_error is not None:
                raise remote_error
        finally:
            self._destroying = False

    def _destroy_remote_resources(self) -> None:
        # Teardown remains re-entrant even though public remote operations are
        # lifecycle-serialized. A second call rechecks remote state and every
        # previously retired local artifact instead of trusting an old result.
        if getattr(self, "_telemetry_runtime_active", False):
            self._telemetry_runtime_active = False
            if TELEMETRY is not None:
                TELEMETRY.vmvm_runtime_stopped()
        for tunnel in list(self._host_tunnels):
            try:
                self.close_host_tunnel(tunnel)
            except Exception:
                logger.exception("vacli: host tunnel teardown failed")
        try:
            self._cleanup_network_firewall()
        except Exception:
            logger.exception("vacli: network firewall teardown failed")
        # Stop the persistent session first so its bash + ssh subprocess exit
        # cleanly before we yank the container out from under them.
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:
                logger.exception("vacli: session stop failed")
        # FIFO mode: kill the in-container reader + held-writer explicitly. `podman
        # rm -f` below would also nuke them, but this is cheap insurance if rm fails.
        if self._fifo_mode:
            try:
                self._teardown_fifo_shell()
            except Exception:
                pass
        if self._compose_project is not None:
            try:
                result = self._compose_command(
                    ["down", "--volumes", "--remove-orphans"],
                    timeout=120,
                )
                if result.returncode == 0:
                    self._container_id = None
                else:
                    detail = (result.stdout or b"").decode("utf-8", errors="replace")
                    logger.warning("vacli: compose teardown failed: %s", detail[-1000:])
            except Exception:
                logger.exception("vacli: compose teardown failed")
            if self._compose_dir is not None:
                try:
                    self._ssh_call_raw(
                        f"rm -rf -- {shlex.quote(self._compose_dir)}",
                        timeout=30,
                    )
                except Exception:
                    logger.exception("vacli: compose directory cleanup failed")
            self._compose_project = None
            self._compose_dir = None
            self._compose_services = ()
        # Best-effort container teardown; failures here shouldn't block lease release.
        if self._container_id:
            try:
                self._sp.run(
                    _ssh_opts(self._ssh_port, self._control_path)
                    + ["root@localhost", f"podman rm -f {self._container_id}"],
                    stdin=self._sp.DEVNULL,
                    stdout=self._sp.DEVNULL,
                    stderr=self._sp.DEVNULL,
                    timeout=30,
                )
            except Exception:
                logger.exception("vacli: container teardown failed")
        if self._network_isolation is not None:
            try:
                result = self._ssh_call_raw(
                    "podman network rm -f " + shlex.quote(self._network_isolation.network),
                    timeout=30,
                )
                if result.returncode != 0:
                    detail = (result.stdout or b"").decode("utf-8", errors="replace")
                    logger.warning(
                        "vacli: internal network teardown failed: %s",
                        detail[-1000:],
                    )
            except Exception:
                logger.exception("vacli: internal network teardown failed")
            self._network_isolation = None

    @_lifecycle_serialized
    def transfer_file(self, file_content: str | bytes, remote_path: str | Path) -> None:
        """Stream a file's bytes into the container via tar over the SSH master.

        Bytes flow through stdin pipes the whole way — no argv inlining — so
        this is bounded only by VM disk, not by `MAX_ARG_STRLEN`.
        """
        if self._destroyed:
            raise RuntimeError("transfer_file called after destroy")
        if self._container_id is None:
            raise RuntimeError("transfer_file called before container init")
        data = file_content.encode("utf-8") if isinstance(file_content, str) else file_content
        rp = Path(remote_path)
        remote_dir = rp.parent.as_posix() or "/"
        remote_name = rp.name
        # Build a single-file tar in memory keyed at the destination basename;
        # extract it in the destination directory inside the container.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=remote_name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        tar_bytes = buf.getvalue()

        # `ssh ... podman exec -i cid sh -c 'mkdir -p DIR && tar -C DIR -xf -'`
        # The bytes go via stdin, not argv.
        remote_cmd = f"mkdir -p {shlex.quote(remote_dir)} && tar -C {shlex.quote(remote_dir)} -xf -"
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            f"podman exec --user 0 -i {self._container_id} sh -c {shlex.quote(remote_cmd)}",
        ]
        result = self._sp.run(
            argv,
            input=tar_bytes,
            stdout=self._sp.PIPE,
            stderr=self._sp.PIPE,
            timeout=self.config.session_timeout,
        )
        # Per [[vacli-coreweave-stderr-noise]]: stderr is unreliable; trust exit code only.
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(f"transfer_file failed (rc={result.returncode}, path={remote_path}): {err}")

    @_lifecycle_serialized
    def read_file(self, remote_path: str | Path) -> bytes:
        """Read a file from the container without mixing SSH stderr into its bytes."""
        if self._destroyed:
            raise RuntimeError("read_file called after destroy")
        if self._container_id is None:
            raise RuntimeError("read_file called before container init")
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            f"podman exec --user 0 {self._container_id} cat -- {shlex.quote(str(remote_path))}",
        ]
        result = self._sp.run(
            argv,
            stdin=self._sp.DEVNULL,
            stdout=self._sp.PIPE,
            stderr=self._sp.PIPE,
            timeout=self.config.session_timeout,
        )
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(f"read_file failed (rc={result.returncode}, path={remote_path}): {err}")
        return result.stdout or b""

    @_lifecycle_serialized
    def open_host_tunnel(self, local_port: int) -> tuple[VacliHostTunnel, str]:
        """Make a host-local TCP service reachable from the VMVM container.

        Reverse-forward creation and its readiness probe share the process-wide
        vacli setup limit with lease bring-up. The slot is released before the
        live tunnel is returned and is not held for the tunnel lifetime.
        """
        if self._destroyed:
            raise RuntimeError("open_host_tunnel called after destroy")
        if self._container_id is None:
            raise RuntimeError("open_host_tunnel called before container init")
        if not 1 <= local_port <= 65535:
            raise ValueError(f"invalid local port: {local_port}")
        with _lease_concurrency.unmeasured_permit():
            return self._open_host_tunnel(local_port)

    def _open_host_tunnel(self, local_port: int) -> tuple[VacliHostTunnel, str]:
        isolation = self._network_isolation
        gateway = isolation.gateway if isolation is not None else self._proxy_gateway
        forward = f"127.0.0.1:0:127.0.0.1:{local_port}"
        result = self._sp.run(
            _ssh_opts(self._ssh_port, self._control_path) + ["-O", "forward", "-R", forward, "root@localhost"],
            stdin=self._sp.DEVNULL,
            stdout=self._sp.PIPE,
            stderr=self._sp.PIPE,
            timeout=30,
        )
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")
            raise BackendInitError(f"could not expose host port {local_port} to VMVM container: {err}")
        output = (result.stdout or b"").decode("utf-8", errors="replace").strip()
        try:
            remote_port = int(output.splitlines()[-1])
        except (IndexError, ValueError) as error:
            raise BackendInitError(f"SSH did not report an allocated reverse-forward port: {output!r}") from error
        if not 1 <= remote_port <= 65535:
            raise BackendInitError(f"SSH allocated an invalid reverse-forward port: {remote_port}")

        relay_log = f"/tmp/vacli_host_tunnel_{remote_port}.log"
        relay_command = (
            "set -e; command -v socat >/dev/null; "
            f"nohup socat TCP-LISTEN:{remote_port},bind={gateway},reuseaddr,fork "
            f"TCP:127.0.0.1:{remote_port} >{shlex.quote(relay_log)} 2>&1 </dev/null & "
            'pid=$!; kill -0 "$pid"; printf "__VACLIPID=%s\\n" "$pid"'
        )
        relay = self._ssh_call_raw(relay_command, timeout=30)
        match = re.search(rb"__VACLIPID=(\d+)", relay.stdout or b"")
        if relay.returncode != 0 or match is None:
            self._cancel_host_forward(remote_port, local_port)
            detail = (relay.stdout or b"").decode("utf-8", errors="replace").strip()
            raise BackendInitError(f"could not start VMVM bridge relay: {detail}")

        tunnel = VacliHostTunnel(gateway, remote_port, local_port, int(match.group(1)))
        self._host_tunnels.add(tunnel)
        try:
            self._allow_isolated_tunnel(remote_port)
        except Exception:
            self.close_host_tunnel(tunnel)
            raise
        probe_script = f"import socket; socket.create_connection(({gateway!r}, {remote_port}), timeout=1).close()"
        # TB4 images are intentionally heterogeneous: some expose `python3`,
        # some only `python`, and a few contain neither.  Probe the actual
        # container-to-host route with the first available TCP/HTTP client
        # instead of assuming a `python` executable.  If an ultra-minimal
        # image has no probe utility, retain the already-established SSH
        # forward and bridge relay; the intercepted model call is the
        # authoritative connectivity check and the rollout retry policy will
        # still classify a real failure as infrastructure.
        probe_shell = (
            "if command -v python3 >/dev/null 2>&1; then "
            f"exec python3 -c {shlex.quote(probe_script)}; "
            "elif command -v python >/dev/null 2>&1; then "
            f"exec python -c {shlex.quote(probe_script)}; "
            "elif command -v nc >/dev/null 2>&1; then "
            f"exec nc -z -w 1 {shlex.quote(gateway)} {remote_port}; "
            "elif command -v busybox >/dev/null 2>&1; then "
            f"exec busybox nc -z -w 1 {shlex.quote(gateway)} {remote_port}; "
            "elif command -v curl >/dev/null 2>&1; then "
            f"exec curl -sS --connect-timeout 1 --max-time 2 -o /dev/null "
            f"http://{gateway}:{remote_port}/; "
            "elif command -v wget >/dev/null 2>&1; then "
            f"exec wget -q -T 2 -O /dev/null http://{gateway}:{remote_port}/; "
            "else printf '__VACLI_NO_TCP_PROBE__\\n'; exit 125; fi"
        )
        probe_command = f"podman exec {self._container_id} sh -c {shlex.quote(probe_shell)}"
        deadline = time.monotonic() + 10
        last_error = "reverse forward was not reachable"
        while time.monotonic() < deadline:
            probe = self._ssh_call_raw(probe_command, timeout=5)
            if probe.returncode == 0:
                url = f"http://{gateway}:{remote_port}"
                logger.info("vacli: host tunnel up at %s", url)
                return tunnel, url
            if b"__VACLI_NO_TCP_PROBE__" in (probe.stdout or b""):
                url = f"http://{gateway}:{remote_port}"
                logger.warning(
                    "vacli: container has no TCP probe utility; "
                    "deferring host tunnel validation to the intercepted request"
                )
                return tunnel, url
            last_error = (probe.stdout or b"").decode("utf-8", errors="replace").strip()
            relay_status = self._ssh_call_raw(
                f"kill -0 {tunnel.relay_pid} 2>/dev/null || {{ cat {shlex.quote(relay_log)} 2>/dev/null; exit 1; }}",
                timeout=5,
            )
            if relay_status.returncode != 0:
                relay_error = (relay_status.stdout or b"").decode("utf-8", errors="replace").strip()
                if relay_error:
                    last_error = f"{last_error}; bridge relay exited: {relay_error[-1000:]}"
                break
            time.sleep(0.2)

        self.close_host_tunnel(tunnel)
        raise BackendInitError(f"could not expose host port {local_port} to VMVM container: {last_error}")

    def _restore_host_tunnels(self) -> bool:
        """Restore reverse forwards after the SSH control master is replaced."""
        for tunnel in self._host_tunnels:
            relay = self._ssh_call_raw(f"kill -0 {tunnel.relay_pid}", timeout=30)
            if relay.returncode != 0:
                logger.warning(
                    "vacli.restart_session: host bridge relay %d is not running",
                    tunnel.relay_pid,
                )
                return False
            forward = f"127.0.0.1:{tunnel.remote_port}:127.0.0.1:{tunnel.local_port}"
            result = self._sp.run(
                _ssh_opts(self._ssh_port, self._control_path) + ["-O", "forward", "-R", forward, "root@localhost"],
                stdin=self._sp.DEVNULL,
                stdout=self._sp.PIPE,
                stderr=self._sp.PIPE,
                timeout=30,
            )
            if result.returncode != 0:
                detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
                logger.warning(
                    "vacli.restart_session: could not restore host tunnel on port %d: %s",
                    tunnel.remote_port,
                    detail,
                )
                return False
            logger.info(
                "vacli.restart_session: restored host tunnel on port %d",
                tunnel.remote_port,
            )
        return True

    @_lifecycle_serialized
    def close_host_tunnel(self, tunnel: object) -> None:
        if not isinstance(tunnel, VacliHostTunnel):
            raise TypeError(f"unexpected VMVM host tunnel: {type(tunnel).__name__}")
        if self._destroyed and not self._destroying:
            raise RuntimeError("close_host_tunnel called after destroy")
        self._host_tunnels.discard(tunnel)
        self._remove_isolated_tunnel(tunnel.remote_port)
        relay_log = f"/tmp/vacli_host_tunnel_{tunnel.remote_port}.log"
        relay = self._ssh_call_raw(
            f"kill {tunnel.relay_pid} 2>/dev/null || true; rm -f {shlex.quote(relay_log)}",
            timeout=30,
        )
        if relay.returncode != 0:
            detail = (relay.stdout or b"").decode("utf-8", errors="replace").strip()
            logger.warning("vacli: host bridge relay teardown failed: %s", detail)
        result = self._cancel_host_forward(tunnel.remote_port, tunnel.local_port)
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            logger.warning("vacli: host tunnel teardown failed: %s", err)
            return
        logger.info("vacli: host tunnel down (port=%d)", tunnel.remote_port)

    def _cancel_host_forward(self, remote_port: int, local_port: int) -> subprocess.CompletedProcess:
        forward = f"127.0.0.1:{remote_port}:127.0.0.1:{local_port}"
        result = self._sp.run(
            _ssh_opts(self._ssh_port, self._control_path) + ["-O", "cancel", "-R", forward, "root@localhost"],
            stdin=self._sp.DEVNULL,
            stdout=self._sp.DEVNULL,
            stderr=self._sp.PIPE,
            timeout=30,
        )
        return result

    def get_debugging_info(self) -> dict[str, Any]:
        return {
            "config": str(self.config),
            "container_id": self._container_id,
            "ssh_port": self._ssh_port,
            "vacli_log": str(self._vacli_log),
            "control_path": self._control_path,
        }

    # -- internals ---------------------------------------------------------

    def _start_container(self) -> str:
        """Pull the image (vmvm-registry mirror, then docker.io fallback) and
        start a long-running detached container."""
        self._raise_if_provisioning_cancelled()
        self._ensure_host_memory()
        self._raise_if_provisioning_cancelled()
        used = _resolve_image_in_vm(
            self._sp,
            self._ssh_port,
            self._control_path,
            self.config.image_url,
            getattr(self.config, "fallback_image_url", None),
            cancel_event=self.config.provisioning_cancel_event,
        )
        self._raise_if_provisioning_cancelled()
        run_argv = ["podman", "run", "-d", "--network", "bridge"]
        if CONTAINER_PRIVILEGED:
            run_argv.append("--privileged")
        if self.config.cpu is not None:
            run_argv.extend(["--cpus", str(self.config.cpu)])
            run_argv.extend(["--env", f"GOMAXPROCS={math.ceil(self.config.cpu)}"])
        if self.config.memory_gb is not None:
            run_argv.extend(["--memory", f"{self.config.memory_gb}g"])
        run_argv.extend(["--entrypoint", "/bin/bash", used, "-c", "tail -f /dev/null"])
        run = self._ssh_call_raw(
            shlex.join(run_argv),
            timeout=int(self.config.session_timeout),
        )
        self._raise_if_provisioning_cancelled()
        if run.returncode != 0:
            raise BackendInitError(f"podman run failed: rc={run.returncode} stderr={run.stderr!r}")
        cid = run.stdout.decode("utf-8", errors="replace").strip()
        if not cid:
            raise BackendInitError(f"podman run returned empty container id; stderr={run.stderr!r}")
        cid = _validate_container_id(cid)
        _ensure_python_in_container(self._sp, self._ssh_port, self._control_path, cid)
        self._raise_if_provisioning_cancelled()
        # --network bridge gives the container its own netns so task workloads
        # can bind :8080 (the host egress proxy occupies :8080 in the *host*
        # netns). Repoint http_proxy at the bridge gateway so egress still works.
        self._proxy_gateway = _setup_bridge_proxy(self._sp, self._ssh_port, self._control_path, cid)
        self._raise_if_provisioning_cancelled()
        return cid

    def _ensure_host_memory(self) -> None:
        """Back task memory above the VM tier's RAM with per-lease host swap."""
        if self.config.memory_gb is None:
            return
        required_mib = math.ceil(self.config.memory_gb * 1024) + HOST_MEMORY_HEADROOM_MIB
        script = f"""
set -eu
required_mib={required_mib}
current_mib=$(awk '/^(MemTotal|SwapTotal):/ {{ total += $2 }} END {{ print int(total / 1024) }}' /proc/meminfo)
if [ "$current_mib" -ge "$required_mib" ]; then
    exit 0
fi
swap_mib=$((required_mib - current_mib))
swap_path=/var/lib/containers/storage/vmvm-runtime.swap
if grep -q "^$swap_path " /proc/swaps; then
    exit 0
fi
rm -f "$swap_path"
: > "$swap_path"
if command -v chattr >/dev/null 2>&1; then
    chattr +C "$swap_path" 2>/dev/null || :
fi
dd if=/dev/zero of="$swap_path" bs=1M count="$swap_mib" status=none
chmod 600 "$swap_path"
mkswap "$swap_path" >/dev/null
swapon "$swap_path"
""".strip()
        result = self._ssh_call_raw(
            "bash -c " + shlex.quote(script),
            timeout=180,
        )
        if result.returncode != 0:
            detail = (result.stdout or b"").decode("utf-8", errors="replace").strip()
            raise BackendInitError(f"VMVM host swap setup failed: {detail[-1000:]}")

    def _ssh_call_raw(self, remote_cmd: str, *, timeout: int) -> subprocess.CompletedProcess:
        """Issue one ssh invocation that runs `remote_cmd` on the VM. Combines
        the VM's stderr into stdout (the agent and the BashResult shape both
        expect a single text stream)."""
        argv = _ssh_opts(self._ssh_port, self._control_path) + [
            "root@localhost",
            remote_cmd,
        ]
        return self._sp.run(
            argv,
            stdin=self._sp.DEVNULL,
            stdout=self._sp.PIPE,
            stderr=self._sp.STDOUT,
            timeout=timeout,
        )
