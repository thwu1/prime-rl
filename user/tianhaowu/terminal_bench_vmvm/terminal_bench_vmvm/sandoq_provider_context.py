"""Supervise the host-side Sandoq provider environment.

The context either delegates transport selection to the official client or
owns a loopback-only CONNECT proxy for its child's complete lifetime. It
records no credential values and never opens either token file.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import re
import select
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
BASE_URL = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
ENVIRONMENT = "oci-runner"
LEASE_PROFILES = {"standard": "1h", "kimi-tb4-long": "12h"}
DEFAULT_TOKEN_FILE = Path("/home/tianhaowu/.config/oci-runner/token")
PROXY_ENVIRONMENT_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
CONTEXT_ACTIVE = "SANDOQ_PROVIDER_CONTEXT_ACTIVE"
CONTEXT_RECEIPT = "SANDOQ_PROVIDER_CONTEXT_RECEIPT"
MAX_RECEIPT_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PR_SET_CHILD_SUBREAPER = 36
_PR_GET_CHILD_SUBREAPER = 37


class ProviderContextError(RuntimeError):
    """Stable provider-context failure."""


def _fail(code: str, error: BaseException | None = None) -> None:
    if error is None:
        raise ProviderContextError(code)
    raise ProviderContextError(code) from error


@dataclass(frozen=True)
class ProviderContextProfile:
    cluster_identifier: str
    transport_mode: str
    effective_task_network: str
    provider_token_file: Path
    sha256: str


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _process_start_ticks(pid: int) -> int:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().split()
        value = int(fields[21])
    except (OSError, ValueError, IndexError) as error:
        _fail("provider_context_process_invalid", error)
    if value < 1:
        _fail("provider_context_process_invalid")
    return value


def _validate_absolute_path(value: str, code: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        _fail(code)
    return path


def _proxy_url(port: int) -> str:
    if not 1 <= port <= 65_535:
        _fail("provider_proxy_invalid")
    return f"http://127.0.0.1:{port}"


def _parse_loopback_proxy(value: str) -> tuple[str, int]:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as error:
        _fail("provider_proxy_invalid", error)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65_535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        _fail("provider_proxy_invalid")
    return parsed.hostname, port


def load_provider_profile(path: Path, expected_sha256: str) -> ProviderContextProfile:
    if not path.is_absolute() or path != Path(os.path.normpath(path)) or _SHA256_RE.fullmatch(expected_sha256) is None:
        _fail("provider_context_profile_invalid")
    try:
        if path.resolve(strict=True) != path:
            _fail("provider_context_profile_invalid")
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        _fail("provider_context_profile_invalid", error)
    try:
        opened = os.fstat(descriptor)
        body = bytearray()
        while chunk := os.read(descriptor, 4096):
            body.extend(chunk)
            if len(body) > MAX_RECEIPT_BYTES:
                _fail("provider_context_profile_invalid")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or bool(before.st_mode & 0o022)
        or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or _sha256(bytes(body)) != expected_sha256
    ):
        _fail("provider_context_profile_invalid")
    try:
        value = json.loads(bytes(body))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("provider_context_profile_invalid", error)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "cluster_identifier",
            "transport_mode",
            "effective_task_network",
            "base_url",
            "environment",
            "provider_token_file",
        }
        or bytes(body) != _canonical_json(value)
        or value["schema_version"] != SCHEMA_VERSION
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,127}", str(value["cluster_identifier"])) is None
        or value["transport_mode"] not in {"auto", "loopback"}
        or value["effective_task_network"] != "public"
        or value["base_url"] != BASE_URL
        or value["environment"] != ENVIRONMENT
    ):
        _fail("provider_context_profile_invalid")
    provider_token_file = _validate_absolute_path(
        str(value["provider_token_file"]),
        "provider_context_profile_invalid",
    )
    return ProviderContextProfile(
        cluster_identifier=str(value["cluster_identifier"]),
        transport_mode=str(value["transport_mode"]),
        effective_task_network=str(value["effective_task_network"]),
        provider_token_file=provider_token_file,
        sha256=expected_sha256,
    )


class _ConnectServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True


class _ConnectHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        header = bytearray()
        self.request.settimeout(30)
        while b"\r\n\r\n" not in header:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            header.extend(chunk)
            if len(header) > 64 * 1024:
                return
        try:
            request_line = bytes(header).split(b"\r\n", 1)[0].decode("ascii")
            method, authority, version = request_line.split(" ", 2)
            host, separator, raw_port = authority.rpartition(":")
            port = int(raw_port)
        except (UnicodeDecodeError, ValueError):
            self.request.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        if (
            method != "CONNECT"
            or version not in {"HTTP/1.0", "HTTP/1.1"}
            or not separator
            or host.strip("[]").lower() != urllib.parse.urlsplit(BASE_URL).hostname
            or port != 443
        ):
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return
        try:
            upstream = socket.create_connection((host.strip("[]"), port), timeout=30)
        except OSError:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        with upstream:
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            sockets = (self.request, upstream)
            while True:
                readable, _, _ = select.select(sockets, (), (), 60)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(64 * 1024)
                    if not data:
                        return
                    destination = upstream if source is self.request else self.request
                    destination.sendall(data)


class DirectConnectProxy:
    """Loopback proxy restricted to the single approved Sandoq gateway."""

    def __init__(self) -> None:
        self._server = _ConnectServer(("127.0.0.1", 0), _ConnectHandler)
        self._server.timeout = 0.25
        self._stopping = False

    @property
    def url(self) -> str:
        return _proxy_url(int(self._server.server_address[1]))

    def request_stop(self) -> None:
        self._stopping = True

    def serve_once(self) -> None:
        if not self._stopping:
            self._server.handle_request()

    def close(self) -> None:
        self._stopping = True
        self._server.server_close()

    def __enter__(self) -> DirectConnectProxy:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def _context_contract(
    *,
    cluster_identifier: str,
    transport_mode: str,
    concurrency: int,
    lease_create_cap: int,
    startup_timeout_seconds: int,
    lease_profile: str,
    provider_token_file: Path,
    ecr_token_file: Path,
    ecr_token_metadata: Path,
) -> dict[str, Any]:
    lease_duration = LEASE_PROFILES.get(lease_profile)
    if lease_duration is None:
        _fail("provider_context_configuration_invalid")
    return {
        "schema_version": SCHEMA_VERSION,
        "base_url": BASE_URL,
        "cluster_identifier": cluster_identifier,
        "environment": ENVIRONMENT,
        "transport_mode": transport_mode,
        "effective_task_network": "public",
        "provider_token_file_path_sha256": _sha256(str(provider_token_file).encode()),
        "ecr_token_file_path_sha256": _sha256(str(ecr_token_file).encode()),
        "ecr_token_metadata_path_sha256": _sha256(str(ecr_token_metadata).encode()),
        "concurrency": concurrency,
        "lease_create_cap": lease_create_cap,
        "startup_timeout_seconds": startup_timeout_seconds,
        "lease_profile": lease_profile,
        "lease_duration": lease_duration,
        "pool_renew_interval": "5m",
        "session_reuse": 1,
        "pool_max_reuse_count": 1,
        "image_cache_max_entries": 0,
        "podman_fuse_overlayfs": 1,
        "fuse_overlayfs_path": "/usr/bin/fuse-overlayfs",
        "libfuse3_path": "/lib/x86_64-linux-gnu/libfuse3.so.3",
        "pull_timeout": f"{startup_timeout_seconds}s",
        "pull_poll_max_errors": 20,
        "proxy": {
            "bind_host": "127.0.0.1",
            "target_host": urllib.parse.urlsplit(BASE_URL).hostname,
            "target_port": 443,
            "environment_names": ["HTTPS_PROXY", "https_proxy"],
            "starts_before_child": True,
            "lives_through_child_cleanup": True,
        },
    }


def build_provider_environment(
    base: Mapping[str, str],
    *,
    cluster_identifier: str,
    transport_mode: str,
    proxy_url: str | None,
    concurrency: int,
    lease_create_cap: int,
    startup_timeout_seconds: int,
    lease_profile: str = "standard",
    provider_token_file: Path,
    ecr_token_file: Path,
    ecr_token_metadata: Path,
    project_root: Path,
    sandoq_site: Path,
) -> dict[str, str]:
    if (
        transport_mode not in {"auto", "loopback"}
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,127}", cluster_identifier) is None
        or (transport_mode == "loopback" and proxy_url is None)
        or (transport_mode == "auto" and proxy_url is not None)
        or not 1 <= concurrency <= 64
        or not 1 <= lease_create_cap <= concurrency
        or startup_timeout_seconds != 3_600
        or lease_profile not in LEASE_PROFILES
    ):
        _fail("provider_context_configuration_invalid")
    if proxy_url is not None:
        _parse_loopback_proxy(proxy_url)
    for path in (provider_token_file, ecr_token_file, ecr_token_metadata, project_root, sandoq_site):
        _validate_absolute_path(str(path), "provider_context_configuration_invalid")
    environment = dict(base)
    owner = environment.get("USER", "")
    if re.fullmatch(r"[A-Za-z0-9._-]+", owner) is None:
        _fail("provider_context_configuration_invalid")
    for name in PROXY_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    environment.pop("OCI_RUNNER_TASK_NETWORK", None)
    environment.pop("OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK", None)
    environment.pop("VF_SANDBOX_PROVIDER", None)
    environment.pop("FIRECRACKER_KEY", None)
    python_paths = [
        str(project_root),
        str(project_root / "environments/vmvm_tb_v2"),
        str(project_root / "extensions/sandoq"),
        str(sandoq_site),
    ]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(python_paths),
            "MODAL_DISABLE_API_PROXY": "1",
            "SANDOQ_OWNER": owner,
            "OCI_RUNNER_BASE_URL": BASE_URL,
            "OCI_RUNNER_ENVIRONMENT": ENVIRONMENT,
            "SANDOQ_TRANSPORT_MODE": transport_mode,
            "SANDOQ_CLUSTER_IDENTIFIER": cluster_identifier,
            "SANDOQ_EFFECTIVE_TASK_NETWORK": "public",
            "SANDOQ_LEASE_PROFILE": lease_profile,
            "OCI_RUNNER_TOKEN_FILE": str(provider_token_file),
            "OCI_RUNNER_OBSERVABILITY": "1",
            "OCI_RUNNER_CREATE_DEADLINE": "30m",
            "OCI_RUNNER_LEASE_DURATION": LEASE_PROFILES[lease_profile],
            "OCI_RUNNER_SESSION_REUSE": "1",
            "OCI_RUNNER_POOL_MAX_REUSE_COUNT": "1",
            "OCI_RUNNER_POOL_REUSE_JITTER": "0",
            "OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES": "0",
            "OCI_RUNNER_PODMAN_FUSE_OVERLAYFS": "1",
            "OCI_RUNNER_FUSE_OVERLAYFS_PATH": "/usr/bin/fuse-overlayfs",
            "OCI_RUNNER_LIBFUSE3_PATH": "/lib/x86_64-linux-gnu/libfuse3.so.3",
            "OCI_RUNNER_PULL_TIMEOUT": f"{startup_timeout_seconds}s",
            "OCI_RUNNER_PULL_POLL_MAX_ERRORS": "20",
            "OCI_RUNNER_GATEWAY_RETRY_ATTEMPTS": "15",
            "OCI_RUNNER_GATEWAY_RETRY_INTERVAL": "2s",
            "OCI_RUNNER_PODMAN_IGNORE_CHOWN_ERRORS": "1",
            "OCI_RUNNER_REQUIRE_RESOURCE_LIMITS": "1",
            "OCI_RUNNER_EXEC_TIMEOUT_CEILING": "270",
            "OCI_RUNNER_TASK_PIDS_LIMIT": "512",
            "OCI_RUNNER_POOL_HEARTBEAT_TIMEOUT": "45s",
            "OCI_RUNNER_SECRET_CACHE_TTL": "5s",
            "OCI_RUNNER_POOL_RENEW_INTERVAL": "5m",
            "OCI_RUNNER_POOL_SIZE": str(concurrency),
            "OCI_RUNNER_POOL_MIN_SIZE": "0",
            "OCI_RUNNER_POOL_CREATE_WORKERS": str(lease_create_cap),
            "OCI_RUNNER_POOL_BOOTSTRAP_WORKERS": str(concurrency),
            "OCI_RUNNER_POOL_BOOTSTRAP_PER_IMAGE": str(min(concurrency, 8)),
            "OCI_RUNNER_POOL_DRAIN_WORKERS": str(min(concurrency, 32)),
            "OCI_RUNNER_POOL_DRAIN_TIMEOUT": "240",
            "OCI_RUNNER_POOL_RENEW_WORKERS": str(min(concurrency, 16)),
            "OCI_RUNNER_USE_ECR": "1",
            "OCI_RUNNER_ECR_REGISTRY": "168653207203.dkr.ecr.us-east-2.amazonaws.com",
            "OCI_RUNNER_ECR_REGION": "us-east-2",
            "OCI_RUNNER_ECR_PULL_THROUGH_PREFIX": "pt_dockerio",
            "OCI_RUNNER_ECR_TOKEN_FILE": str(ecr_token_file),
            "OCI_RUNNER_ECR_TOKEN_METADATA_PATH": str(ecr_token_metadata),
        }
    )
    if proxy_url is not None:
        environment["HTTPS_PROXY"] = proxy_url
        environment["https_proxy"] = proxy_url
    return environment


def _publish_receipt(path: Path, value: Mapping[str, Any]) -> None:
    if path.parent.name == "" or path.name != "provider-context.json":
        _fail("provider_context_receipt_invalid")
    payload = _canonical_json(value)
    temporary = path.parent / f".{path.name}.{os.urandom(16).hex()}"
    descriptor = -1
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        _fail("provider_context_receipt_invalid", error)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with contextlib.suppress(OSError):
            temporary.unlink()


def _load_receipt(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path != Path(os.path.normpath(path)):
        _fail("provider_context_receipt_invalid")
    try:
        if path.resolve(strict=True) != path or path.parent.resolve(strict=True) != path.parent:
            _fail("provider_context_receipt_invalid")
        parent = path.parent.lstat()
        listed = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        _fail("provider_context_receipt_invalid", error)
    try:
        opened = os.fstat(descriptor)
        body = bytearray()
        while chunk := os.read(descriptor, 4096):
            body.extend(chunk)
            if len(body) > MAX_RECEIPT_BYTES:
                _fail("provider_context_receipt_invalid")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or not stat.S_ISREG(listed.st_mode)
        or listed.st_uid != os.geteuid()
        or listed.st_nlink != 1
        or stat.S_IMODE(listed.st_mode) != 0o600
        or (listed.st_dev, listed.st_ino) != (opened.st_dev, opened.st_ino)
        or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        _fail("provider_context_receipt_invalid")
    try:
        value = json.loads(bytes(body))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("provider_context_receipt_invalid", error)
    if not isinstance(value, dict) or bytes(body) != _canonical_json(value):
        _fail("provider_context_receipt_invalid")
    return value


def provider_context_is_active(environment: Mapping[str, str]) -> bool:
    try:
        if environment.get(CONTEXT_ACTIVE) != "1":
            return False
        receipt_path = _validate_absolute_path(
            environment.get(CONTEXT_RECEIPT, ""),
            "provider_context_receipt_invalid",
        )
        receipt = _load_receipt(receipt_path)
        expected_keys = {
            "schema_version",
            "state",
            "supervisor_pid",
            "supervisor_start_ticks",
            "proxy_url",
            "contract_sha256",
        }
        if set(receipt) != expected_keys:
            return False
        pid = receipt["supervisor_pid"]
        start_ticks = receipt["supervisor_start_ticks"]
        proxy_url = receipt["proxy_url"]
        transport_mode = environment.get("SANDOQ_TRANSPORT_MODE")
        cluster_identifier = environment.get("SANDOQ_CLUSTER_IDENTIFIER")
        if (
            receipt["schema_version"] != SCHEMA_VERSION
            or receipt["state"] != "active"
            or type(pid) is not int
            or pid < 1
            or type(start_ticks) is not int
            or start_ticks < 1
            or transport_mode not in {"auto", "loopback"}
            or not isinstance(cluster_identifier, str)
            or re.fullmatch(r"[a-z][a-z0-9_-]{0,127}", cluster_identifier) is None
            or not (proxy_url is None or isinstance(proxy_url, str))
            or _SHA256_RE.fullmatch(str(receipt["contract_sha256"])) is None
            or environment.get("OCI_RUNNER_BASE_URL") != BASE_URL
            or environment.get("OCI_RUNNER_ENVIRONMENT") != ENVIRONMENT
            or environment.get("SANDOQ_EFFECTIVE_TASK_NETWORK") != "public"
            or environment.get("OCI_RUNNER_TASK_NETWORK")
            or environment.get("OCI_RUNNER_POOL_MIN_SIZE") != "0"
            or environment.get("OCI_RUNNER_SESSION_REUSE") != "1"
            or environment.get("OCI_RUNNER_POOL_MAX_REUSE_COUNT") != "1"
            or environment.get("OCI_RUNNER_IMAGE_CACHE_MAX_ENTRIES") != "0"
            or environment.get("OCI_RUNNER_PODMAN_FUSE_OVERLAYFS") != "1"
            or environment.get("OCI_RUNNER_FUSE_OVERLAYFS_PATH") != "/usr/bin/fuse-overlayfs"
            or environment.get("OCI_RUNNER_LIBFUSE3_PATH") != "/lib/x86_64-linux-gnu/libfuse3.so.3"
            or environment.get("SANDOQ_LEASE_PROFILE") not in LEASE_PROFILES
            or environment.get("OCI_RUNNER_LEASE_DURATION") != LEASE_PROFILES[environment["SANDOQ_LEASE_PROFILE"]]
            or environment.get("OCI_RUNNER_POOL_RENEW_INTERVAL") != "5m"
            or environment.get("OCI_RUNNER_PULL_TIMEOUT") != "3600s"
            or environment.get("OCI_RUNNER_PULL_POLL_MAX_ERRORS") != "20"
            or environment.get("OCI_RUNNER_OBSERVABILITY") != "1"
            or environment.get("VF_SANDBOX_PROVIDER")
            or environment.get("FIRECRACKER_KEY")
            or _process_start_ticks(pid) != start_ticks
        ):
            return False
        if transport_mode == "loopback":
            if (
                not isinstance(proxy_url, str)
                or environment.get("HTTPS_PROXY") != proxy_url
                or environment.get("https_proxy") != proxy_url
                or any(environment.get(name) for name in ("HTTP_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"))
            ):
                return False
        elif proxy_url is not None or any(environment.get(name) for name in PROXY_ENVIRONMENT_NAMES):
            return False
        contract = _context_contract(
            cluster_identifier=cluster_identifier,
            transport_mode=transport_mode,
            concurrency=int(environment["OCI_RUNNER_POOL_SIZE"]),
            lease_create_cap=int(environment["OCI_RUNNER_POOL_CREATE_WORKERS"]),
            startup_timeout_seconds=3_600,
            lease_profile=environment["SANDOQ_LEASE_PROFILE"],
            provider_token_file=_validate_absolute_path(
                environment["OCI_RUNNER_TOKEN_FILE"],
                "provider_context_receipt_invalid",
            ),
            ecr_token_file=_validate_absolute_path(
                environment["OCI_RUNNER_ECR_TOKEN_FILE"],
                "provider_context_receipt_invalid",
            ),
            ecr_token_metadata=_validate_absolute_path(
                environment["OCI_RUNNER_ECR_TOKEN_METADATA_PATH"],
                "provider_context_receipt_invalid",
            ),
        )
        if receipt["contract_sha256"] != _sha256(_canonical_json(contract)):
            return False
        if proxy_url is not None:
            host, port = _parse_loopback_proxy(proxy_url)
            with socket.create_connection((host, port), timeout=1):
                pass
        return True
    except (KeyError, OSError, ProviderContextError, ValueError):
        return False


def _group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _set_child_subreaper(enabled: bool) -> bool:
    libc = ctypes.CDLL(None, use_errno=True)
    current = ctypes.c_int()
    if libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(current), 0, 0, 0) != 0:
        _fail("provider_context_subreaper_failed", OSError(ctypes.get_errno(), "prctl"))
    if libc.prctl(_PR_SET_CHILD_SUBREAPER, int(enabled), 0, 0, 0) != 0:
        _fail("provider_context_subreaper_failed", OSError(ctypes.get_errno(), "prctl"))
    return bool(current.value)


def _reap_group_children(process: subprocess.Popen[bytes]) -> None:
    process.poll()
    while True:
        try:
            child_pid, _ = os.waitpid(-process.pid, os.WNOHANG)
        except ChildProcessError:
            return
        if child_pid == 0:
            return


def _terminate_group(process: subprocess.Popen[bytes], grace_seconds: float = 10) -> bool:
    pgid = process.pid
    if not _group_exists(pgid):
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=0)
        return True
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        _reap_group_children(process)
        if not _group_exists(pgid):
            with contextlib.suppress(ChildProcessError):
                process.wait()
            return True
        time.sleep(0.05)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGKILL)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        _reap_group_children(process)
        if not _group_exists(pgid):
            with contextlib.suppress(ChildProcessError):
                process.wait()
            return True
        time.sleep(0.05)
    return False


def supervise(
    command: Sequence[str],
    *,
    cluster_identifier: str,
    transport_mode: str,
    concurrency: int,
    lease_create_cap: int,
    startup_timeout_seconds: int,
    lease_profile: str = "standard",
    provider_token_file: Path,
    ecr_token_file: Path,
    ecr_token_metadata: Path,
    project_root: Path,
    sandoq_site: Path,
) -> int:
    if not command or any(not isinstance(item, str) or "\x00" in item for item in command):
        _fail("provider_context_command_invalid")
    runtime_parent = Path(os.environ.get("SLURM_TMPDIR", "/tmp"))
    if not runtime_parent.is_absolute():
        _fail("provider_context_runtime_invalid")
    runtime_root: Path | None = None
    receipt_path: Path | None = None
    child: subprocess.Popen[bytes] | None = None
    received_signal: int | None = None
    prior_subreaper = _set_child_subreaper(True)

    def request_stop(signum: int, _frame: object) -> None:
        nonlocal received_signal
        if received_signal is None:
            received_signal = signum

    previous_handlers: dict[int, Any] = {}
    try:
        runtime_root = Path(tempfile.mkdtemp(prefix="sandoq-provider-context-", dir=runtime_parent))
        runtime_root.chmod(0o700)
        receipt_path = runtime_root / "provider-context.json"
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, request_stop)
        proxy_context: contextlib.AbstractContextManager[DirectConnectProxy | None]
        if transport_mode == "loopback":
            proxy_context = DirectConnectProxy()
        elif transport_mode == "auto":
            proxy_context = contextlib.nullcontext(None)
        else:
            _fail("provider_context_configuration_invalid")
        with proxy_context as proxy:
            proxy_url = proxy.url if proxy is not None else None
            contract = _context_contract(
                cluster_identifier=cluster_identifier,
                transport_mode=transport_mode,
                concurrency=concurrency,
                lease_create_cap=lease_create_cap,
                startup_timeout_seconds=startup_timeout_seconds,
                lease_profile=lease_profile,
                provider_token_file=provider_token_file,
                ecr_token_file=ecr_token_file,
                ecr_token_metadata=ecr_token_metadata,
            )
            environment = build_provider_environment(
                os.environ,
                cluster_identifier=cluster_identifier,
                transport_mode=transport_mode,
                proxy_url=proxy_url,
                concurrency=concurrency,
                lease_create_cap=lease_create_cap,
                startup_timeout_seconds=startup_timeout_seconds,
                lease_profile=lease_profile,
                provider_token_file=provider_token_file,
                ecr_token_file=ecr_token_file,
                ecr_token_metadata=ecr_token_metadata,
                project_root=project_root,
                sandoq_site=sandoq_site,
            )
            receipt = {
                "schema_version": SCHEMA_VERSION,
                "state": "active",
                "supervisor_pid": os.getpid(),
                "supervisor_start_ticks": _process_start_ticks(os.getpid()),
                "proxy_url": proxy_url,
                "contract_sha256": _sha256(_canonical_json(contract)),
            }
            _publish_receipt(receipt_path, receipt)
            environment[CONTEXT_ACTIVE] = "1"
            environment[CONTEXT_RECEIPT] = str(receipt_path)
            child = subprocess.Popen(command, env=environment, start_new_session=True)
            while child.poll() is None and received_signal is None:
                if proxy is None:
                    time.sleep(0.25)
                else:
                    proxy.serve_once()
            if received_signal is not None:
                if not _terminate_group(child):
                    _fail("provider_context_child_cleanup_failed")
                return 128 + received_signal
            return_code = child.wait()
            if _group_exists(child.pid) and not _terminate_group(child):
                _fail("provider_context_child_cleanup_failed")
            return return_code
    finally:
        cleanup_failed = False
        if child is not None and _group_exists(child.pid):
            if not _terminate_group(child):
                cleanup_failed = True
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                cleanup_failed = True
        try:
            _set_child_subreaper(prior_subreaper)
        except ProviderContextError:
            cleanup_failed = True
        if receipt_path is not None:
            try:
                receipt_path.unlink(missing_ok=True)
            except OSError:
                cleanup_failed = True
        if runtime_root is not None:
            try:
                runtime_root.rmdir()
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            _fail("provider_context_cleanup_failed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    supervise_parser = subparsers.add_parser("supervise")
    supervise_parser.add_argument("--profile", type=Path, required=True)
    supervise_parser.add_argument("--profile-sha256", required=True)
    supervise_parser.add_argument("--concurrency", type=int, required=True)
    supervise_parser.add_argument("--lease-create-cap", type=int, required=True)
    supervise_parser.add_argument("--startup-timeout-seconds", type=int, required=True)
    supervise_parser.add_argument("--lease-profile", choices=tuple(LEASE_PROFILES), default="standard")
    supervise_parser.add_argument("--ecr-token-file", type=Path, required=True)
    supervise_parser.add_argument("--ecr-token-metadata", type=Path, required=True)
    supervise_parser.add_argument("--project-root", type=Path, required=True)
    supervise_parser.add_argument("--sandoq-site", type=Path, required=True)
    supervise_parser.add_argument("command", nargs=argparse.REMAINDER)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command_name == "verify":
            environment = dict(os.environ)
            environment[CONTEXT_RECEIPT] = str(arguments.receipt)
            if not provider_context_is_active(environment):
                _fail("provider_context_not_active")
            return 0
        command = arguments.command
        if command and command[0] == "--":
            command = command[1:]
        profile = load_provider_profile(arguments.profile, arguments.profile_sha256)
        return supervise(
            command,
            cluster_identifier=profile.cluster_identifier,
            transport_mode=profile.transport_mode,
            concurrency=arguments.concurrency,
            lease_create_cap=arguments.lease_create_cap,
            startup_timeout_seconds=arguments.startup_timeout_seconds,
            lease_profile=arguments.lease_profile,
            provider_token_file=profile.provider_token_file,
            ecr_token_file=arguments.ecr_token_file,
            ecr_token_metadata=arguments.ecr_token_metadata,
            project_root=arguments.project_root,
            sandoq_site=arguments.sandoq_site,
        )
    except Exception:
        print("Sandoq provider context failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
