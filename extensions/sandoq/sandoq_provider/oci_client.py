"""Prime sandbox client backed by a nested Podman container in a Sandoq lease."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import math
import os
import posixpath
import random
import re
import shlex
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prime_sandboxes import BackgroundJob, BackgroundJobStatus, CommandResponse, FileUploadResponse, ReadFileResponse
from prime_sandboxes.exceptions import APIError, CommandTimeoutError, SandboxFileNotFoundError

from sandoq_provider import registry
from sandoq_provider.client import (
    SandoqAsyncSandboxClient,
    _ensure_renewer,
    _Sandbox,
    _upload_ok,
)
from sandoq_provider.ecr import (
    ECRConfig,
    ECRCredentialCache,
    authenticated_ecr_registry,
    is_configured_ecr_image,
    resolve_pull_image,
)
from sandoq_provider.gateway import SandoqHttpResponse, SandoqHttpTransportError, get_gateway_adapter
from sandoq_provider.secrets import read_secret_file
from sandoq_provider.utils import duration_seconds

_DEFAULT_BASE_URL = "https://sandoq.eks-prod.cf.aws.metafb.cloud"
_DEFAULT_ENVIRONMENT = "oci-runner-firecracker"
_DEFAULT_TOKEN_FILE = "~/.config/oci-runner/firecracker-token"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_DIGEST_AND_SIZE = re.compile(r"(sha256:[0-9a-f]{64})\s+([0-9]+)")
_IMAGE_SIZE = re.compile(r"OCI_IMAGE_SIZE_BYTES=([0-9]+)")
_EXPECTED_COMMIT_ENV = "OCI_EXPECTED_BASE_COMMIT"
_EXPECTED_INSTANCE_ENV = "OCI_EXPECTED_INSTANCE_ID"
_EXPECTED_WORKDIR_ENV = "OCI_EXPECTED_WORKDIR"
_DEFAULT_WORKDIR = "/testbed"
_TRANSFER_DIR = ".prime-rl-transfer"
_DOCKERHUB_REGISTRY = "docker.io"
_DOCKERHUB_AUTH_FILE = "/home/runner/.config/containers/dockerhub-auth.json"
_ECR_AUTH_FILE = "/home/runner/.config/containers/ecr-auth.json"
_PULL_POLL_INTERVAL_SECONDS = 2.0
_PULL_REQUEST_TIMEOUT_SECONDS = 30
_ECR_UPSTREAM_AUTH_FAILURE = "authentication to the upstream registry failed"
_DEFAULT_GATEWAY_RETRY_ATTEMPTS = 15
_DEFAULT_GATEWAY_RETRY_INTERVAL_SECONDS = 2.0
_TRANSIENT_GATEWAY_EXIT_CODE = 75
_DEFAULT_EXEC_TIMEOUT_CEILING_SECONDS = 270
_DEFAULT_TASK_PIDS_LIMIT = 512
_DISK_HEADROOM_BYTES = 5 * 1024**3
_MIN_MEMORY_HEADROOM_BYTES = 2 * 1024**3
_IMAGE_MOUNT_TARGET = re.compile(r"^/[A-Za-z0-9._/-]+$")
_BACKGROUND_OUTPUT_TAIL_BYTES = 2 * 1024 * 1024
# Each base64 chunk becomes one ``bash -lc`` argument. Stay below Linux's
# MAX_ARG_STRLEN (128 KiB), including the surrounding shell command.
_STAGING_CHUNK_BYTES = 64 * 1024
# Keep encoded download responses comfortably below the Sandoq exec-response
# limit. A single 20 MiB grader log otherwise arrives as truncated base64.
_STAGING_DOWNLOAD_CHUNK_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class OCIRunnerConfig:
    base_url: str
    environment: str
    task_network: str
    token_file: Path
    lease_duration: str
    create_deadline_s: float
    owner: str
    pull_timeout_s: int
    pull_poll_max_errors: int
    gateway_retry_attempts: int
    gateway_retry_interval_s: float
    exec_timeout_ceiling_s: int
    require_resource_limits: bool
    task_pids_limit: int
    observability: bool
    session_reuse: bool
    pool_size: int
    pool_min_size: int
    pool_socket: Path
    pool_drain_timeout_s: float
    dockerhub_username: str | None
    dockerhub_token_file: Path | None
    require_dockerhub_auth: bool
    podman_ignore_chown_errors: bool
    ecr: ECRConfig
    allow_dockerhub_fallback: bool = True
    managed_shell_recovery: bool = False

    @property
    def dockerhub_auth_enabled(self) -> bool:
        return self.dockerhub_username is not None and self.dockerhub_token_file is not None


class OCIRunnerStageError(APIError):
    """OCI readiness/cleanup failure with machine-readable stage context."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        timings: dict[str, float] | None = None,
        attempts: int | None = None,
        failure_reason: str | None = None,
        timeout_category: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.timings = dict(timings or {})
        self.attempts = attempts
        self.failure_reason = failure_reason or stage
        self.cause_stage = stage
        self.timeout_category = timeout_category


class OCIRunnerCommandTimeoutError(CommandTimeoutError):
    """A command timeout with a stable retry classification."""

    def __init__(
        self,
        sandbox_id: str,
        command: str,
        timeout: int,
        *,
        failure_reason: str,
        timeout_category: str,
        cause_stage: str = "shell_exec",
    ) -> None:
        super().__init__(sandbox_id, command, timeout)
        self.failure_reason = failure_reason
        self.cause_stage = cause_stage
        self.timeout_category = timeout_category


class OCIRunnerResourceAdmissionError(OCIRunnerStageError):
    """The outer session cannot safely honor the task's requested resources."""

    def __init__(self, message: str) -> None:
        super().__init__("resource_admission", message, failure_reason="resource_admission_failure")


@dataclass(frozen=True)
class TaskResourceRequest:
    cpu_count: int
    memory_bytes: int
    disk_bytes: int

    def as_dict(self) -> dict[str, int]:
        return {
            "cpu_count": self.cpu_count,
            "memory_bytes": self.memory_bytes,
            "disk_bytes": self.disk_bytes,
        }


class OCIRunnerTransientGatewayError(OCIRunnerStageError):
    """A trusted idempotent operation exhausted transient gateway recovery."""

    def __init__(
        self,
        operation: str,
        *,
        http_status: int | None,
        attempts: int,
        timings: dict[str, float],
        delivery_state: str = "unknown",
        cleanup_result: dict[str, object] | None = None,
    ) -> None:
        status = f"HTTP {http_status}" if http_status is not None else "transport failure"
        super().__init__(
            operation,
            f"OCI runner gateway unavailable during {operation}: {status} after {attempts} attempts",
            timings=timings,
            attempts=attempts,
            failure_reason=(
                "pre_delivery_gateway_failure" if delivery_state == "not_sent" else "gateway_command_outcome_unknown"
            ),
        )
        self.operation = operation
        self.cause_stage = operation
        self.http_status = http_status
        self.delivery_state = delivery_state
        self.cleanup_result = dict(cleanup_result) if cleanup_result is not None else None

    def attach_cleanup_result(self, cleanup_result: dict[str, object]) -> None:
        self.cleanup_result = dict(cleanup_result)


def _remaining_seconds(deadline: float) -> float:
    return max(deadline - time.monotonic(), 0.0)


def _request_timeout(deadline: float, requested: float) -> float:
    remaining = _remaining_seconds(deadline)
    if remaining <= 0:
        raise TimeoutError("OCI operation deadline expired")
    return min(requested, remaining)


async def _sleep_before_deadline(delay: float, deadline: float) -> None:
    remaining = _remaining_seconds(deadline)
    if remaining <= 0:
        return
    await asyncio.sleep(min(delay, remaining))


def _validated_workdir(value: object | None) -> str:
    """Return the trusted nested-container workdir, preserving the V1 default."""
    workdir = str(value or _DEFAULT_WORKDIR)
    if (
        not workdir.startswith("/")
        or workdir.startswith("//")
        or workdir == "/"
        or posixpath.normpath(workdir) != workdir
        or any(character in workdir for character in ("\x00", "\n", "\r"))
    ):
        raise APIError(f"OCI expected workdir must be a normalized absolute path below root: {workdir!r}")
    return workdir


def _positive_resource(value: object, name: str) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise OCIRunnerResourceAdmissionError(f"task {name} request must be numeric, got {value!r}") from exc
    if not math.isfinite(normalized) or normalized <= 0:
        raise OCIRunnerResourceAdmissionError(f"task {name} request must be positive, got {value!r}")
    return normalized


def _requested_resources(request: Any, context: dict[str, object]) -> TaskResourceRequest:
    cpu_value = context.get("cpu", getattr(request, "cpu_cores", 1.0))
    memory_value = context.get("memory", getattr(request, "memory_gb", 1.0))
    disk_value = context.get("disk", getattr(request, "disk_size_gb", 5.0))
    cpu = _positive_resource(cpu_value, "CPU")
    if not cpu.is_integer():
        raise OCIRunnerResourceAdmissionError(f"task CPU request must be a whole core count, got {cpu}")
    memory_gb = _positive_resource(memory_value, "memory")
    disk_gb = _positive_resource(disk_value, "disk")
    return TaskResourceRequest(
        cpu_count=int(cpu),
        memory_bytes=math.ceil(memory_gb * 1024**3),
        disk_bytes=math.ceil(disk_gb * 1024**3),
    )


def _expand_cpuset(value: str) -> list[int]:
    cpus: list[int] = []
    for component in value.strip().split(","):
        component = component.strip()
        if not component:
            continue
        start_text, separator, end_text = component.partition("-")
        try:
            start = int(start_text)
            end = int(end_text) if separator else start
        except ValueError as exc:
            raise OCIRunnerResourceAdmissionError(f"invalid effective CPU set: {value!r}") from exc
        if start < 0 or end < start:
            raise OCIRunnerResourceAdmissionError(f"invalid effective CPU set: {value!r}")
        cpus.extend(range(start, end + 1))
    if not cpus:
        raise OCIRunnerResourceAdmissionError("outer session has no effective CPUs")
    return list(dict.fromkeys(cpus))


def _resource_probe_command() -> str:
    """Read limits from the process's actual cgroup, not the mount root."""
    return r"""
set -eu
cgroup2_path=$(awk -F: '$1 == "0" {print $3; exit}' /proc/self/cgroup)
if [ -n "$cgroup2_path" ]; then
  case "$cgroup2_path" in /*) ;; *) cgroup2_path="/$cgroup2_path" ;; esac
  cgroup_dir="/sys/fs/cgroup${cgroup2_path%/}"
  cpuset_file="$cgroup_dir/cpuset.cpus.effective"
  [ -r "$cpuset_file" ] || cpuset_file=/sys/fs/cgroup/cpuset.cpus.effective
  memory_file="$cgroup_dir/memory.max"
  [ -r "$memory_file" ] || memory_file=/sys/fs/cgroup/memory.max
else
  cpuset_path=$(awk -F: '$2 ~ /(^|,)cpuset(,|$)/ {print $3; exit}' /proc/self/cgroup)
  memory_path=$(awk -F: '$2 ~ /(^|,)memory(,|$)/ {print $3; exit}' /proc/self/cgroup)
  cpuset_file="/sys/fs/cgroup/cpuset${cpuset_path%/}/cpuset.cpus"
  memory_file="/sys/fs/cgroup/memory${memory_path%/}/memory.limit_in_bytes"
fi
printf 'OCI_CPUSET_EFFECTIVE=%s\n' "$(cat "$cpuset_file" 2>/dev/null || printf unavailable)"
printf 'OCI_OUTER_MEMORY_MAX=%s\n' "$(cat "$memory_file" 2>/dev/null || printf unavailable)"
printf 'OCI_GUEST_MEMORY_TOTAL=%s\n' "$(awk '/^MemTotal:/ {printf "%.0f", $2 * 1024; exit}' /proc/meminfo)"
printf 'OCI_DISK_AVAILABLE=%s\n' "$(df -PB1 /home/runner/shared | awk 'NR==2 {print $4}')"
"""


def _managed_workdir(info: registry.SessionInfo) -> str:
    return _validated_workdir(info.env_vars.get(_EXPECTED_WORKDIR_ENV))


def _image_mounts(value: object, ecr: ECRConfig) -> list[dict[str, str]]:
    """Validate recipe-requested read-only OCI image mounts.

    The trusted task context is still treated as data at the shell boundary: image
    references go through the same resolver as the task image and mount targets must
    be normalized absolute paths below ``/``.  ``podman --mount type=image`` exposes
    the image root read-only without copying it into the task image.
    """

    if value is None:
        return []
    if not isinstance(value, list):
        raise APIError("OCI image_mounts task context must be a list")
    mounts: list[dict[str, str]] = []
    targets: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise APIError("each OCI image mount must be an object")
        source = str(raw.get("image") or "").strip()
        target = str(raw.get("target") or "").strip()
        image = resolve_pull_image(source, ecr)
        if "," in image:
            raise APIError("OCI image mount source contains unsupported characters")
        if not _IMAGE_MOUNT_TARGET.fullmatch(target) or target == "/" or posixpath.normpath(target) != target:
            raise APIError("OCI image mount target must be a normalized absolute path below root")
        if target in targets:
            raise APIError(f"duplicate OCI image mount target: {target!r}")
        targets.add(target)
        mounts.append({"source_image": source, "image": image, "target": target})
    return mounts


def _mounted_images(info: registry.SessionInfo) -> list[dict[str, str]]:
    mounts = info.metadata.get("image_mounts")
    if not isinstance(mounts, list):
        return []
    return [
        mount
        for mount in mounts
        if isinstance(mount, dict) and isinstance(mount.get("image"), str) and isinstance(mount.get("target"), str)
    ]


def _pull_images(info: registry.SessionInfo) -> list[str]:
    images = [info.requested_image] if info.requested_image else []
    images.extend(mount["image"] for mount in _mounted_images(info))
    return list(dict.fromkeys(images))


def get_oci_config() -> OCIRunnerConfig:
    token_path = os.environ.get("OCI_RUNNER_TOKEN_FILE", _DEFAULT_TOKEN_FILE)
    environment = os.environ.get("OCI_RUNNER_ENVIRONMENT", _DEFAULT_ENVIRONMENT)
    task_network = os.environ.get("OCI_RUNNER_TASK_NETWORK", "none").strip().lower()
    dockerhub_username = os.environ.get("OCI_RUNNER_DOCKERHUB_USERNAME", "").strip() or None
    dockerhub_token_path = os.environ.get("OCI_RUNNER_DOCKERHUB_TOKEN_FILE", "").strip() or None
    require_dockerhub_auth = os.environ.get("OCI_RUNNER_REQUIRE_DOCKERHUB_AUTH") == "1"
    allow_dockerhub_fallback_value = os.environ.get("OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK", "1")
    if allow_dockerhub_fallback_value not in {"0", "1"}:
        raise APIError("OCI_RUNNER_ALLOW_DOCKERHUB_FALLBACK must be '0' or '1'")
    if dockerhub_username is not None and ("\n" in dockerhub_username or "\r" in dockerhub_username):
        raise APIError("OCI_RUNNER_DOCKERHUB_USERNAME must be a single line")
    if (dockerhub_username is None) != (dockerhub_token_path is None):
        raise APIError("OCI_RUNNER_DOCKERHUB_USERNAME and OCI_RUNNER_DOCKERHUB_TOKEN_FILE must be configured together")
    if require_dockerhub_auth and dockerhub_username is None:
        raise APIError("Docker Hub authentication is required but its username and token file are not configured")
    exec_timeout_ceiling_s = int(
        duration_seconds(
            os.environ.get("OCI_RUNNER_EXEC_TIMEOUT_CEILING"),
            _DEFAULT_EXEC_TIMEOUT_CEILING_SECONDS,
        )
    )
    task_pids_limit = int(os.environ.get("OCI_RUNNER_TASK_PIDS_LIMIT", str(_DEFAULT_TASK_PIDS_LIMIT)))
    if not 1 <= exec_timeout_ceiling_s < 300:
        raise APIError("OCI_RUNNER_EXEC_TIMEOUT_CEILING must be between 1 and 299 seconds")
    if task_pids_limit < 1:
        raise APIError("OCI_RUNNER_TASK_PIDS_LIMIT must be positive")
    if task_network not in {"none", "host"}:
        raise APIError("OCI_RUNNER_TASK_NETWORK must be 'none' or 'host'")
    if task_network == "host" and not environment.startswith("oci-runner-firecracker"):
        raise APIError("OCI_RUNNER_TASK_NETWORK=host is supported only by Firecracker environments")
    managed_shell_recovery = os.environ.get("SANDOQ_LEASE_PROFILE") == "kimi-tb4-long"
    declared_shell_recovery = os.environ.get("OCI_RUNNER_MANAGED_SHELL_RECOVERY")
    if declared_shell_recovery is not None and declared_shell_recovery != ("1" if managed_shell_recovery else "0"):
        raise APIError("OCI_RUNNER_MANAGED_SHELL_RECOVERY disagrees with SANDOQ_LEASE_PROFILE")
    from sandoq_provider.pool import default_socket_path

    pool_socket = os.environ.get("OCI_RUNNER_POOL_SOCKET")
    return OCIRunnerConfig(
        base_url=os.environ.get("OCI_RUNNER_BASE_URL", _DEFAULT_BASE_URL).rstrip("/"),
        environment=environment,
        task_network=task_network,
        token_file=Path(token_path).expanduser(),
        lease_duration=os.environ.get("OCI_RUNNER_LEASE_DURATION", "1h"),
        create_deadline_s=duration_seconds(os.environ.get("OCI_RUNNER_CREATE_DEADLINE"), 300.0),
        owner=os.environ.get("SANDOQ_OWNER") or os.environ.get("USER") or "prime-rl",
        pull_timeout_s=int(duration_seconds(os.environ.get("OCI_RUNNER_PULL_TIMEOUT"), 1200.0)),
        pull_poll_max_errors=max(1, int(os.environ.get("OCI_RUNNER_PULL_POLL_MAX_ERRORS", "10"))),
        gateway_retry_attempts=max(
            1,
            int(os.environ.get("OCI_RUNNER_GATEWAY_RETRY_ATTEMPTS", str(_DEFAULT_GATEWAY_RETRY_ATTEMPTS))),
        ),
        gateway_retry_interval_s=max(
            0.0,
            duration_seconds(
                os.environ.get("OCI_RUNNER_GATEWAY_RETRY_INTERVAL"),
                _DEFAULT_GATEWAY_RETRY_INTERVAL_SECONDS,
            ),
        ),
        exec_timeout_ceiling_s=exec_timeout_ceiling_s,
        require_resource_limits=os.environ.get("OCI_RUNNER_REQUIRE_RESOURCE_LIMITS") == "1",
        task_pids_limit=task_pids_limit,
        observability=os.environ.get("OCI_RUNNER_OBSERVABILITY") == "1",
        session_reuse=os.environ.get("OCI_RUNNER_SESSION_REUSE", "1") != "0",
        pool_size=int(os.environ.get("OCI_RUNNER_POOL_SIZE", "32")),
        pool_min_size=int(os.environ.get("OCI_RUNNER_POOL_MIN_SIZE", "0")),
        pool_socket=Path(pool_socket).expanduser() if pool_socket else default_socket_path(),
        pool_drain_timeout_s=duration_seconds(os.environ.get("OCI_RUNNER_POOL_DRAIN_TIMEOUT"), 240.0),
        dockerhub_username=dockerhub_username,
        dockerhub_token_file=Path(dockerhub_token_path).expanduser() if dockerhub_token_path else None,
        require_dockerhub_auth=require_dockerhub_auth,
        allow_dockerhub_fallback=allow_dockerhub_fallback_value == "1",
        podman_ignore_chown_errors=os.environ.get("OCI_RUNNER_PODMAN_IGNORE_CHOWN_ERRORS") == "1",
        ecr=ECRConfig.from_env(),
        managed_shell_recovery=managed_shell_recovery,
    )


def _read_secret_file(path: Path, label: str) -> str:
    return read_secret_file(path, label, APIError)


def read_token_file(path: Path) -> str:
    """Read a rotatable bearer token without allowing group/other access."""
    return _read_secret_file(path, "OCI runner token")


def read_dockerhub_token_file(path: Path) -> str:
    """Read a Docker Hub PAT without retaining it in provider state."""
    return _read_secret_file(path, "Docker Hub token")


def normalize_command_response(body: dict[str, Any]) -> tuple[str, str, int, bool]:
    result = body.get("result") if isinstance(body.get("result"), dict) else body
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    exit_code = result.get("exit_code", result.get("exitCode", result.get("code")))
    timed_out = bool(result.get("timed_out", result.get("timedOut", False))) or exit_code == -1
    if not isinstance(exit_code, int):
        raise APIError(f"OCI command response has no integer exit code (keys={sorted(result)})")
    return stdout, stderr, exit_code, timed_out


def delete_outer_sync(
    base_url: str,
    sandbox_id: str,
    timeout: float = 60.0,
    *,
    observability: bool = False,
) -> dict[str, object]:
    """Delete an outer lease and synchronously confirm it is gone."""
    cleanup_started = time.monotonic()
    cfg = get_oci_config()
    try:
        deletion = get_gateway_adapter(base_url, cfg.owner).delete_session(
            sandbox_id,
            timeout=timeout,
            prime=True,
        )
    except Exception as exc:
        if observability:
            raise OCIRunnerStageError(
                "deletion_verification",
                f"OCI runner session {sandbox_id} deletion was not confirmed by typed HTTP 404: {exc}",
                timings={"cleanup": time.monotonic() - cleanup_started},
            ) from exc
        raise APIError(f"OCI runner session {sandbox_id} deletion was not confirmed by typed HTTP 404: {exc}") from exc
    response: dict[str, object] = {
        "status": "deleted",
        "sandbox_id": sandbox_id,
        "verified_http_status": deletion.verified_http_status,
    }
    if observability:
        response["timings"] = {
            "cleanup": deletion.cleanup_seconds,
            "deletion_verification": deletion.verification_seconds,
        }
    return response


def delete_registered_sessions_sync(timeout: float = 60.0) -> dict[str, object]:
    """Best-effort synchronous cleanup for interpreter signal teardown."""
    deleted: list[str] = []
    failed: dict[str, str] = {}
    environment = get_oci_config().environment
    for sandbox_id in registry.all_ids():
        info = registry.get(sandbox_id)
        if info is None or info.environment != environment:
            continue
        try:
            if info.session_reuse:
                from sandoq_provider.pool import get_pool_client

                get_pool_client().release(sandbox_id, poison=True, reason="signal_cleanup")
            else:
                base_url = info.outer_base_url or get_oci_config().base_url
                delete_outer_sync(base_url, info.outer_session_id or sandbox_id, timeout)
        except BaseException as exc:
            failed[sandbox_id] = str(exc)
            continue
        registry.unregister(sandbox_id)
        deleted.append(sandbox_id)
        print(f"OCI runner signal cleanup: {sandbox_id}", flush=True)
    if get_oci_config().session_reuse:
        try:
            from sandoq_provider.pool import depart_pool_client

            depart_pool_client()
        except BaseException as exc:
            failed["pool_client_departure"] = str(exc)
    return {"deleted": deleted, "failed": failed}


class OCIRunnerAsyncSandboxClient(SandoqAsyncSandboxClient):
    """Lease ``oci-runner`` and expose only the verified nested task container."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        self._oci_cfg = get_oci_config()
        self._base = self._oci_cfg.base_url
        self._direct_ecr_credentials = {
            registry_host: ECRCredentialCache(self._oci_cfg.ecr, registry_host)
            for registry_host in self._oci_cfg.ecr.authenticated_registries
        }
        if self._oci_cfg.dockerhub_auth_enabled:
            assert self._oci_cfg.dockerhub_token_file is not None
            read_dockerhub_token_file(self._oci_cfg.dockerhub_token_file)

    async def _timed_stage(self, info: registry.SessionInfo, stage: str, operation: Any) -> Any:
        started = time.monotonic()
        try:
            result = await operation
        except asyncio.CancelledError:
            raise
        except OCIRunnerStageError as exc:
            elapsed = time.monotonic() - started
            timings = info.metadata.setdefault("oci_timings", {})
            assert isinstance(timings, dict)
            timings[stage] = elapsed
            timings.update(exc.timings)
            info.metadata.update(
                cause_stage=exc.cause_stage,
                failure_reason=exc.failure_reason,
            )
            if exc.timeout_category is not None:
                info.metadata["timeout_category"] = exc.timeout_category
            raise
        except Exception as exc:
            elapsed = time.monotonic() - started
            timings = info.metadata.setdefault("oci_timings", {})
            assert isinstance(timings, dict)
            timings[stage] = elapsed
            raise OCIRunnerStageError(stage, str(exc), timings=timings) from exc
        elapsed = time.monotonic() - started
        timings = info.metadata.setdefault("oci_timings", {})
        assert isinstance(timings, dict)
        timings[stage] = elapsed
        return result

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {read_token_file(self._oci_cfg.token_file)}"}

    async def _request_json(
        self,
        info: registry.SessionInfo,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
    ):
        base_url = info.outer_base_url or self._base
        return await get_gateway_adapter(base_url, self._oci_cfg.owner).request_json_async(
            method,
            info.exec_url + path,
            body=body,
            headers=headers,
            timeout=min(timeout, float(self._oci_cfg.exec_timeout_ceiling_s)),
        )

    async def _managed_shell_request(
        self,
        info: registry.SessionInfo,
        *,
        body: dict[str, object],
        timeout: float,
    ) -> SandoqHttpResponse:
        """Serialize long-Kimi managed-shell calls with broker-owned recovery."""
        if not info.session_reuse or not self._oci_cfg.managed_shell_recovery:
            return await self._request_json(
                info,
                "POST",
                "v1/exec",
                body=body,
                headers=self._auth_headers(),
                timeout=timeout,
            )
        from sandoq_provider.pool import get_pool_client

        pool = get_pool_client()
        admission_deadline = time.monotonic() + min(max(timeout + 30.0, 30.0), 300.0)
        while True:
            shell_id = info.shell_id
            if not shell_id:
                raise self._poisoned_shell_error(
                    info,
                    "missing_shell",
                    "persistent shell is unavailable",
                    failure_reason="managed_shell_lost",
                )
            body["shellId"] = shell_id
            result = await asyncio.to_thread(
                pool.managed_shell_request,
                info.session_id,
                shell_id,
                body=dict(body),
                request_timeout_seconds=timeout,
                admission_deadline_monotonic=admission_deadline,
            )
            if isinstance(result, SandoqHttpResponse):
                return result
            status = result.get("status")
            if status == "shell_replaced":
                replacement = result.get("shell_id")
                if not isinstance(replacement, str) or not replacement:
                    raise self._poisoned_shell_error(
                        info,
                        "invalid_replacement",
                        "managed shell replacement metadata is invalid",
                        failure_reason="managed_shell_lost",
                    )
                info.shell_id = replacement
                info.metadata["shell_id"] = replacement
                body["shellId"] = replacement
                continue
            if status == "terminal_failure":
                raise self._poisoned_shell_error(
                    info,
                    str(result.get("failure_status") or "managed_shell_lost"),
                    "managed shell recovery previously failed",
                    failure_reason="managed_shell_lost",
                )
            raise self._poisoned_shell_error(
                info,
                "broker_response_invalid",
                "managed shell broker response is invalid",
                failure_reason="managed_shell_lost",
            )

    async def _recover_managed_shell(self, info: registry.SessionInfo, expected_shell_id: str) -> None:
        if not info.session_reuse or not self._oci_cfg.managed_shell_recovery:
            raise self._poisoned_shell_error(
                info,
                "managed_shell_lost",
                "managed shell expired and recovery is disabled",
                failure_reason="managed_shell_lost",
            )
        from sandoq_provider.pool import get_pool_client

        try:
            recovered = await asyncio.to_thread(
                get_pool_client().recover_managed_shell,
                info.session_id,
                expected_shell_id,
                workdir=_managed_workdir(info),
            )
        except Exception as error:
            raise self._poisoned_shell_error(
                info,
                "managed_shell_recovery_failed",
                "managed shell recovery failed",
                failure_reason="managed_shell_lost",
            ) from error
        shell_id = recovered.get("shell_id")
        shell_generation = recovered.get("shell_generation")
        if (
            recovered.get("status") not in {"recovered", "already_recovered"}
            or not isinstance(shell_id, str)
            or not isinstance(shell_generation, int)
            or shell_generation < 1
        ):
            raise self._poisoned_shell_error(
                info,
                "managed_shell_recovery_invalid",
                "managed shell recovery returned invalid metadata",
                failure_reason="managed_shell_lost",
            )
        info.shell_id = shell_id
        info.metadata["shell_id"] = shell_id
        info.metadata["shell_generation"] = shell_generation
        info.metadata["managed_shell_recovery_count"] = int(info.metadata.get("managed_shell_recovery_count", 0)) + (
            1 if recovered["status"] == "recovered" else 0
        )

    @staticmethod
    def _stage_error(info: registry.SessionInfo, stage: str, message: str) -> OCIRunnerStageError:
        timings = info.metadata.get("oci_timings")
        return OCIRunnerStageError(stage, message, timings=timings if isinstance(timings, dict) else None)

    @staticmethod
    def _record_not_sent_retry(info: registry.SessionInfo) -> None:
        info.metadata["pre_request_retry_count"] = int(info.metadata.get("pre_request_retry_count", 0)) + 1
        info.metadata["transport_delivery_state"] = "not_sent"

    @staticmethod
    def _record_not_sent_recovery(info: registry.SessionInfo) -> None:
        info.metadata["pre_request_retry_recovered_count"] = (
            int(info.metadata.get("pre_request_retry_recovered_count", 0)) + 1
        )

    @staticmethod
    def _record_not_sent_exhaustion(info: registry.SessionInfo) -> None:
        info.metadata["pre_request_retry_exhausted_count"] = (
            int(info.metadata.get("pre_request_retry_exhausted_count", 0)) + 1
        )
        info.metadata["transport_delivery_state"] = "not_sent"

    async def _request_json_with_gateway_retries(
        self,
        info: registry.SessionInfo,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: float,
        operation: str,
        replay_safe: bool,
        deadline: float | None = None,
    ) -> SandoqHttpResponse:
        """Retry a request only when delivery is proved absent or replay is explicitly safe."""
        attempts = self._oci_cfg.gateway_retry_attempts
        absolute_deadline = deadline or (
            time.monotonic() + timeout + self._oci_cfg.gateway_retry_interval_s * max(attempts - 1, 0)
        )
        started = time.monotonic()
        attempted = 0
        not_sent_retries = 0
        last_status: int | None = None
        last_delivery_state = "unknown"
        for attempt in range(attempts):
            remaining = _remaining_seconds(absolute_deadline)
            if remaining <= 0:
                break
            attempted = attempt + 1
            try:
                response = await self._request_json(
                    info,
                    method,
                    path,
                    body=body,
                    headers=headers,
                    timeout=min(timeout, remaining),
                )
            except SandoqHttpTransportError as exc:
                last_status = exc.http_status
                last_delivery_state = exc.delivery_state
                safe_not_sent = exc.delivery_state == "not_sent" and exc.retryable
                if not safe_not_sent:
                    if exc.delivery_state == "not_sent":
                        self._record_not_sent_exhaustion(info)
                        raise OCIRunnerTransientGatewayError(
                            operation,
                            http_status=last_status,
                            attempts=attempted,
                            timings={operation: time.monotonic() - started},
                            delivery_state=last_delivery_state,
                        ) from None
                    raise
                if attempt + 1 >= attempts or _remaining_seconds(absolute_deadline) <= 0:
                    if safe_not_sent:
                        self._record_not_sent_exhaustion(info)
                    raise OCIRunnerTransientGatewayError(
                        operation,
                        http_status=last_status,
                        attempts=attempted,
                        timings={operation: time.monotonic() - started},
                        delivery_state=last_delivery_state,
                    ) from None
                if safe_not_sent:
                    not_sent_retries += 1
                    self._record_not_sent_retry(info)
                else:
                    info.metadata["idempotent_gateway_retry_count"] = (
                        int(info.metadata.get("idempotent_gateway_retry_count", 0)) + 1
                    )
                await _sleep_before_deadline(self._oci_cfg.gateway_retry_interval_s, absolute_deadline)
                continue
            if not_sent_retries:
                self._record_not_sent_recovery(info)
            return response
        if last_delivery_state == "not_sent":
            self._record_not_sent_exhaustion(info)
        raise OCIRunnerTransientGatewayError(
            operation,
            http_status=last_status,
            attempts=attempted,
            timings={operation: time.monotonic() - started},
            delivery_state=last_delivery_state,
        )

    async def create(self, request: Any, *, deadline: float | None = None) -> _Sandbox:
        lease_started = time.monotonic()
        runtime_name = str(getattr(request, "name", "") or "")
        source_image = str(getattr(request, "docker_image", "") or "").strip()
        if not source_image:
            raise APIError("OCI runner requires CreateSandboxRequest.docker_image")
        image = resolve_pull_image(source_image, self._oci_cfg.ecr)
        environment_vars = dict(getattr(request, "environment_vars", None) or {})
        task_context = registry.current_task_context()
        image_mounts = _image_mounts(task_context.get("image_mounts"), self._oci_cfg.ecr)
        resources = _requested_resources(request, task_context)
        expected_environment = {
            _EXPECTED_COMMIT_ENV: str(task_context["base_commit"]) if task_context.get("base_commit") else None,
            _EXPECTED_INSTANCE_ENV: str(task_context["instance_id"]) if task_context.get("instance_id") else None,
            _EXPECTED_WORKDIR_ENV: str(task_context["working_dir"]) if task_context.get("working_dir") else None,
        }
        for key, value in expected_environment.items():
            if value is None:
                continue
            configured = environment_vars.get(key)
            if configured is not None and configured != value:
                raise APIError(f"OCI task context disagrees with request environment for {key}")
            environment_vars[key] = value
        expected_image = str(task_context["requested_image"]) if task_context.get("requested_image") else None
        if expected_image is not None and source_image != expected_image:
            raise APIError("OCI task context disagrees with the resolved task image")
        managed_workdir = _validated_workdir(environment_vars.get(_EXPECTED_WORKDIR_ENV))
        environment_vars[_EXPECTED_WORKDIR_ENV] = managed_workdir
        if self._oci_cfg.session_reuse:
            return await self._create_from_pool(
                source_image,
                image,
                environment_vars,
                lease_started,
                runtime_name=runtime_name,
                resources=resources,
                image_mounts=image_mounts,
                deadline=deadline,
            )
        request_id = uuid.uuid4().hex
        gateway = get_gateway_adapter(self._base, self._oci_cfg.owner)
        try:
            create_timeout = self._oci_cfg.create_deadline_s
            if deadline is not None:
                create_timeout = _request_timeout(deadline, create_timeout)
            session = await gateway.create_session_async(
                self._oci_cfg.environment,
                self._oci_cfg.lease_duration,
                request_id,
                timeout=create_timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._oci_cfg.observability:
                raise OCIRunnerStageError(
                    "lease_acquisition",
                    f"OCI runner lease failed for environment {self._oci_cfg.environment!r}: {exc}",
                    timings={"lease_acquisition": time.monotonic() - lease_started},
                ) from exc
            raise APIError(f"OCI runner lease failed for environment {self._oci_cfg.environment!r}: {exc}") from exc

        session_id = session.session_id
        exec_url = session.port_urls.get("exec")
        attempt = int(session.raw.get("_retry_count", 0)) + 1
        if not session_id or not exec_url:
            if session_id:
                await self._delete_outer(str(session_id), timeout=30.0)
            if self._oci_cfg.observability:
                raise OCIRunnerStageError(
                    "lease_acquisition",
                    f"OCI runner lease returned no sessionId/exec portUrl: {session.raw}",
                    timings={"lease_acquisition": time.monotonic() - lease_started},
                    attempts=attempt,
                )
            raise APIError(f"OCI runner lease returned no sessionId/exec portUrl: {session.raw}")
        if not exec_url.endswith("/"):
            exec_url += "/"
        info = registry.SessionInfo(
            session_id=str(session_id),
            exec_url=str(exec_url),
            environment=self._oci_cfg.environment,
            runtime_name=runtime_name,
            env_vars=environment_vars,
            lease_duration=self._oci_cfg.lease_duration,
            port_urls=dict(session.port_urls),
            outer_base_url=self._base,
            source_image=source_image,
            requested_image=image,
            metadata={
                "environment": self._oci_cfg.environment,
                "requested_image": source_image,
                "pull_image": image,
                "image_mounts": image_mounts,
                "image_reference_rewritten": source_image != image,
                "allow_dockerhub_fallback": self._oci_cfg.allow_dockerhub_fallback,
                "resolved_digest": None,
                "nested_ready": False,
                "shell_id": None,
                "shell_generation": 0,
                "managed_shell_recovery_count": 0,
                "shell_failure_status": None,
                "assignment_poisoned": False,
                "assignment_poison_reason": None,
                "shell_command_mode": "contained_bash",
                "task_network": self._oci_cfg.task_network,
                "managed_workdir": managed_workdir,
                "requested_resources": resources.as_dict(),
                "sandoq_session": dict(session.raw),
                "sandoq_expires_at": session.expires_at,
            },
            readiness_started_at=lease_started if self._oci_cfg.observability else None,
            outer_session_id=str(session_id),
        )
        if self._oci_cfg.observability:
            info.metadata["oci_timings"] = {"lease_acquisition": time.monotonic() - lease_started}
            info.metadata["oci_stage_attempts"] = {"lease_acquisition": attempt}
        registry.register(info)
        print(
            f"OCI runner session leased: {info.session_id} environment={info.environment} "
            f"image={source_image} pull_image={image}",
            flush=True,
        )
        _ensure_renewer(self._base, self._oci_cfg.owner, self._oci_cfg.lease_duration, 600.0)
        return _Sandbox(id=str(session_id))

    async def _create_from_pool(
        self,
        source_image: str,
        image: str,
        environment_vars: dict[str, str],
        lease_started: float,
        *,
        runtime_name: str,
        resources: TaskResourceRequest,
        image_mounts: list[dict[str, str]],
        deadline: float | None,
    ) -> _Sandbox:
        from sandoq_provider.pool import get_pool_client

        assignment = await asyncio.to_thread(get_pool_client().acquire, image, deadline=deadline)
        assignment_id = str(assignment["assignment_id"])
        exec_url = str(assignment["exec_url"])
        if not exec_url.endswith("/"):
            exec_url += "/"
        metadata: dict[str, object] = {
            "environment": self._oci_cfg.environment,
            "assignment_id": assignment_id,
            "outer_session_id": str(assignment["outer_session_id"]),
            "slot_id": int(assignment["slot_id"]),
            "generation": int(assignment["generation"]),
            "reuse_count": int(assignment["reuse_count"]),
            "reuse_threshold": int(assignment["reuse_threshold"]),
            "pool_wait_seconds": float(assignment["pool_wait_seconds"]),
            "outer_age_seconds": float(assignment["outer_age_seconds"])
            if assignment.get("outer_age_seconds") is not None
            else None,
            "requested_image": source_image,
            "pull_image": image,
            "image_mounts": image_mounts,
            "image_reference_rewritten": source_image != image,
            "allow_dockerhub_fallback": self._oci_cfg.allow_dockerhub_fallback,
            "resolved_digest": None,
            "nested_ready": False,
            "shell_id": None,
            "shell_generation": 0,
            "managed_shell_recovery_count": 0,
            "shell_failure_status": None,
            "assignment_poisoned": False,
            "assignment_poison_reason": None,
            "shell_command_mode": "contained_bash",
            "task_network": self._oci_cfg.task_network,
            "managed_workdir": _validated_workdir(environment_vars.get(_EXPECTED_WORKDIR_ENV)),
            "requested_resources": resources.as_dict(),
        }
        if self._oci_cfg.observability:
            metadata["oci_timings"] = {"pool_wait": float(assignment["pool_wait_seconds"])}
        info = registry.SessionInfo(
            session_id=assignment_id,
            exec_url=exec_url,
            environment=self._oci_cfg.environment,
            runtime_name=runtime_name,
            env_vars=environment_vars,
            lease_duration=self._oci_cfg.lease_duration,
            port_urls=dict(assignment.get("port_urls") or {}),
            outer_base_url=self._base,
            source_image=source_image,
            requested_image=image,
            metadata=metadata,
            readiness_started_at=lease_started if self._oci_cfg.observability else None,
            outer_session_id=str(assignment["outer_session_id"]),
            slot_id=int(assignment["slot_id"]),
            generation=int(assignment["generation"]),
            reuse_count=int(assignment["reuse_count"]),
            pool_wait_seconds=float(assignment["pool_wait_seconds"]),
            session_reuse=True,
        )
        registry.register(info)
        print(
            "OCI runner assignment acquired: "
            f"assignment={assignment_id} outer={info.outer_session_id} slot={info.slot_id} "
            f"generation={info.generation} reuse={info.reuse_count} image={source_image} pull_image={image}",
            flush=True,
        )
        return _Sandbox(id=assignment_id)

    async def wait_for_creation(self, sandbox_id: str, max_attempts: int = 120, **kwargs: Any) -> None:
        del max_attempts, kwargs
        info = self._info(sandbox_id)
        try:
            if self._oci_cfg.observability:
                await self._timed_stage(info, "command_server_readiness", self._wait_for_command_server(info))
                await self._timed_stage(info, "authentication", self._verify_authentication(info))
                bootstrap_deadline = time.monotonic() + self._oci_cfg.pull_timeout_s
                if self._registry_authentication_enabled(info):
                    await self._timed_stage(
                        info,
                        "registry_authentication",
                        self._ensure_registry_authentication(info, bootstrap_deadline),
                    )
            else:
                await self._wait_for_command_server(info)
                await self._verify_authentication(info)
                bootstrap_deadline = time.monotonic() + self._oci_cfg.pull_timeout_s
                if self._registry_authentication_enabled(info):
                    await self._ensure_registry_authentication(info, bootstrap_deadline)
            digest = await self._bootstrap_nested(info, bootstrap_deadline)
            shell_started = time.monotonic()
            try:
                shell_id = await self._create_shell(info)
                info.shell_id = shell_id
                info.metadata["shell_id"] = shell_id
                if info.session_reuse:
                    from sandoq_provider.pool import get_pool_client

                    await asyncio.to_thread(get_pool_client().update, sandbox_id, shell_id=shell_id)
                await self._initialize_shell(info)
            finally:
                shell_start_seconds = time.monotonic() - shell_started
                info.metadata["shell_start_seconds"] = shell_start_seconds
                if self._oci_cfg.observability:
                    timings = info.metadata["oci_timings"]
                    assert isinstance(timings, dict)
                    timings["shell_start"] = shell_start_seconds
            if self._oci_cfg.observability:
                await self._timed_stage(
                    info,
                    "container_validation",
                    self._validate_nested(info, bootstrap_deadline),
                )
            else:
                await self._validate_nested(info, bootstrap_deadline)
            info.resolved_digest = digest
            info.nested_ready = True
            info.metadata.update(
                resolved_digest=digest,
                nested_ready=True,
                shell_id=shell_id,
                shell_start_seconds=shell_start_seconds,
            )
            if info.session_reuse:
                from sandoq_provider.pool import get_pool_client

                await asyncio.to_thread(
                    get_pool_client().update,
                    sandbox_id,
                    resolved_digest=digest,
                    cached_images=_pull_images(info),
                    ready=True,
                )
            if self._oci_cfg.observability and info.readiness_started_at is not None:
                timings = info.metadata["oci_timings"]
                assert isinstance(timings, dict)
                timings["sandbox_readiness"] = time.monotonic() - info.readiness_started_at
        except BaseException as initialization_error:
            cleanup_error: BaseException | None = None
            try:
                if info.session_reuse:
                    from sandoq_provider.pool import get_pool_client

                    cleanup_response = await asyncio.shield(
                        asyncio.to_thread(
                            get_pool_client().release,
                            sandbox_id,
                            poison=True,
                            reason="initialization_failure",
                            shell_failure_status=info.shell_failure_status,
                        )
                    )
                else:
                    cleanup_response = await asyncio.shield(
                        self._delete_outer(info.outer_session_id or sandbox_id, timeout=60.0)
                    )
                cleanup_timings = cleanup_response.get("timings")
                timings = info.metadata.get("oci_timings")
                if isinstance(cleanup_timings, dict) and isinstance(timings, dict):
                    timings.update(cleanup_timings)
                if isinstance(initialization_error, OCIRunnerTransientGatewayError):
                    initialization_error.attach_cleanup_result(cleanup_response)
                else:
                    setattr(initialization_error, "cleanup_result", dict(cleanup_response))
                self._record_cleanup_receipt(info, cleanup_response)
            except BaseException as exc:
                cleanup_error = exc
                self._record_cleanup_receipt(info, {}, error=exc)
            if cleanup_error is None:
                registry.unregister(sandbox_id)
            if cleanup_error is not None:
                if isinstance(cleanup_error, OCIRunnerStageError):
                    raise cleanup_error from initialization_error
                raise APIError(
                    f"OCI runner initialization failed and session cleanup also failed: {cleanup_error}"
                ) from initialization_error
            if isinstance(initialization_error, OCIRunnerStageError):
                timings = info.metadata.get("oci_timings")
                if isinstance(timings, dict):
                    initialization_error.timings.update(timings)
            raise

    async def _wait_for_command_server(self, info: registry.SessionInfo) -> None:
        deadline = time.monotonic() + self._oci_cfg.create_deadline_s
        attempts = 0
        delay = 1.0
        last_status: int | None = None
        last_transport_error: str | None = None
        while time.monotonic() < deadline:
            attempts += 1
            try:
                response = await self._request_json(
                    info,
                    "GET",
                    "healthz",
                    timeout=min(5.0, max(deadline - time.monotonic(), 0.1)),
                )
                last_status = response.status_code
                last_transport_error = None
                if response.status_code == 200 and response.body.get("status") == "ok":
                    stage_attempts = info.metadata.setdefault("oci_stage_attempts", {})
                    assert isinstance(stage_attempts, dict)
                    stage_attempts["command_server_readiness"] = attempts
                    info.metadata["command_server_readiness"] = {
                        "attempts": attempts,
                        "final_status": "ready",
                        "last_http_status": last_status,
                        "last_transport_error": None,
                    }
                    return
            except SandoqHttpTransportError as exc:
                last_status = exc.http_status
                last_transport_error = type(exc).__name__
            except Exception as exc:
                last_transport_error = type(exc).__name__
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(delay * random.uniform(0.8, 1.2), remaining))
            delay = min(delay * 2.0, 8.0)
        stage_attempts = info.metadata.setdefault("oci_stage_attempts", {})
        assert isinstance(stage_attempts, dict)
        stage_attempts["command_server_readiness"] = attempts
        info.metadata["command_server_readiness"] = {
            "attempts": attempts,
            "final_status": "timeout",
            "last_http_status": last_status,
            "last_transport_error": last_transport_error,
        }
        detail = f", last transport error={last_transport_error}" if last_transport_error else ""
        error = OCIRunnerStageError(
            "command_server_readiness",
            f"OCI runner command server for {info.session_id} was not ready in time after {attempts} attempts{detail}",
            attempts=attempts,
        )
        error.final_status = "timeout"
        error.last_http_status = last_status
        error.last_transport_error = last_transport_error
        raise error

    async def _verify_authentication(self, info: registry.SessionInfo) -> None:
        response = await self._request_json_with_gateway_retries(
            info,
            "POST",
            "v1/exec",
            body={"command": ["bash", "-lc", "true"], "timeout": 5},
            timeout=10.0,
            operation="authentication",
            replay_safe=True,
        )
        status_code = response.status_code
        if status_code in (502, 503, 504, 404, 410):
            await self._collect_terminal_diagnostics(info)
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}",
                f"authentication probe returned terminal HTTP {status_code}",
                stage="authentication",
                failure_reason="proxy_deadline_breach" if status_code == 504 else "gateway_command_outcome_unknown",
                timeout_category="proxy_deadline_breach" if status_code == 504 else None,
            )
        if status_code != 401:
            raise APIError(f"unauthenticated OCI runner /v1/exec returned HTTP {status_code}, expected 401")
        info.metadata["authentication_probe_http_status"] = status_code
        info.metadata["authentication_probe_expected"] = True
        response = await self._request_json_with_gateway_retries(
            info,
            "GET",
            "v1/shells",
            headers=self._auth_headers(),
            timeout=10.0,
            operation="authentication",
            replay_safe=True,
        )
        shell_status = response.status_code
        if shell_status != 200:
            diagnostics = (
                await self._collect_terminal_diagnostics(info) if shell_status in (408, 502, 503, 504, 404, 410) else {}
            )
            raise self._poisoned_shell_error(
                info,
                f"capability_http_{shell_status}",
                f"authenticated /v1/shells returned HTTP {shell_status}, expected 200; diagnostics={diagnostics}",
                stage="authentication",
                failure_reason=(
                    "proxy_deadline_breach"
                    if shell_status in (408, 504)
                    else ("outer_session_lost" if shell_status in (404, 410) else "gateway_command_outcome_unknown")
                ),
                timeout_category="proxy_deadline_breach" if shell_status in (408, 504) else None,
            )
        result = await self._outer_exec_idempotent(info, "true", timeout=5, operation="authentication")
        if result.exit_code != 0:
            raise APIError("authenticated OCI runner command probe failed")
        info.metadata["authenticated_api"] = True
        info.metadata["unauthenticated_exec_status"] = status_code
        info.metadata["shell_capability_status"] = shell_status

    async def _create_shell(self, info: registry.SessionInfo) -> str:
        try:
            response = await self._request_json_with_gateway_retries(
                info,
                "POST",
                "v1/shells",
                body={"container": "task"},
                headers=self._auth_headers(),
                timeout=30.0,
                operation="shell_start",
                replay_safe=False,
            )
            status_code, body = response.status_code, response.body
        except SandoqHttpTransportError as exc:
            await self._collect_terminal_diagnostics(info)
            raise self._poisoned_shell_error(
                info,
                "transport_error",
                f"persistent shell creation had an uncertain transport failure: {exc}",
                stage="shell_start",
            ) from exc
        if status_code in (408, 502, 503, 504, 404, 410):
            diagnostics = await self._collect_terminal_diagnostics(info)
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}",
                f"persistent shell creation returned terminal HTTP {status_code}; diagnostics={diagnostics}",
                stage="shell_start",
                failure_reason=(
                    "proxy_deadline_breach"
                    if status_code in (408, 504)
                    else ("outer_session_lost" if status_code in (404, 410) else "gateway_command_outcome_unknown")
                ),
                timeout_category="proxy_deadline_breach" if status_code in (408, 504) else None,
            )
        shell_id = body.get("shellId", body.get("id"))
        if status_code not in (200, 201) or not shell_id:
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}" if status_code not in (200, 201) else "invalid_response",
                f"persistent shell creation failed on {info.session_id}: HTTP {status_code}: {body}",
                stage="shell_start",
            )
        return str(shell_id)

    async def _initialize_shell(self, info: registry.SessionInfo) -> None:
        workdir = _managed_workdir(info)
        initialization = await self._nested_exec_argv(
            info,
            ["cd", workdir],
            timeout=30,
            stage="shell_start",
        )
        if initialization.exit_code != 0:
            raise self._poisoned_shell_error(
                info,
                "initialization_command_failed",
                f"persistent shell initialization returned exit_code={initialization.exit_code}",
                stage="shell_start",
            )

    def _registry_authentication_enabled(self, info: registry.SessionInfo) -> bool:
        return (
            any(authenticated_ecr_registry(image, self._oci_cfg.ecr) for image in _pull_images(info))
            or self._oci_cfg.dockerhub_auth_enabled
        )

    async def _ensure_registry_authentication(
        self,
        info: registry.SessionInfo,
        deadline: float | None = None,
    ) -> None:
        deadline = deadline if deadline is not None else time.monotonic() + self._oci_cfg.pull_timeout_s
        images = _pull_images(info)
        registries = list(
            dict.fromkeys(
                registry_host
                for image in images
                if (registry_host := authenticated_ecr_registry(image, self._oci_cfg.ecr)) is not None
            )
        )
        for registry_host in registries:
            await self._ensure_ecr_authentication(info, registry_host, deadline)
        if self._oci_cfg.dockerhub_auth_enabled and any(
            authenticated_ecr_registry(image, self._oci_cfg.ecr) is None for image in images
        ):
            await self._ensure_dockerhub_authentication(info, deadline)

    async def _ensure_ecr_authentication(
        self,
        info: registry.SessionInfo,
        registry_host: str,
        deadline: float | None = None,
    ) -> None:
        deadline = deadline if deadline is not None else time.monotonic() + self._oci_cfg.pull_timeout_s
        if registry_host not in self._oci_cfg.ecr.authenticated_registries:
            raise APIError(f"ECR authentication is not configured for {registry_host!r}")
        if info.session_reuse:
            from sandoq_provider.pool import get_pool_client

            async with asyncio.timeout_at(deadline):
                credential = await asyncio.to_thread(
                    get_pool_client().ecr_credential,
                    info.session_id,
                    registry_host,
                )
        else:
            async with asyncio.timeout_at(deadline):
                credential = await asyncio.to_thread(self._direct_ecr_credentials[registry_host].get)
        password = credential.pop("password", None)
        if not isinstance(password, str) or not password:
            raise APIError("ECR credential provider returned no password")
        login = await self._outer_exec_idempotent(
            info,
            "\n".join(
                [
                    "set -eu",
                    "install -d -m 700 /home/runner/.config/containers",
                    f"auth_file={shlex.quote(_ECR_AUTH_FILE)}",
                    'printf %s "$OCI_RUNNER_ECR_PASSWORD" | podman login '
                    '--authfile "$auth_file" --username AWS --password-stdin '
                    f"{shlex.quote(registry_host)} >/dev/null",
                    'chmod 600 "$auth_file"',
                    f'test "$(podman login --authfile "$auth_file" --get-login {shlex.quote(registry_host)})" = AWS',
                ]
            ),
            timeout=60,
            env={"OCI_RUNNER_ECR_PASSWORD": password},
            deadline=deadline,
            operation="registry_authentication",
        )
        if login.exit_code != 0:
            raise APIError("ECR authentication failed inside OCI runner")
        authentication = info.metadata.setdefault("ecr_authentication", {})
        if isinstance(authentication, dict):
            authentication[registry_host] = {
                "credential_source": credential.get("source"),
                "credential_generation": credential.get("generation"),
                "credential_reused": credential.get("reused"),
                "credential_age_seconds": credential.get("age_seconds"),
            }
        # Preserve the original scalar receipt fields for dashboards consuming
        # the primary pull-through registry's authentication metadata.
        if registry_host == self._oci_cfg.ecr.registry:
            info.metadata.update(
                ecr_authenticated=True,
                ecr_registry=registry_host,
                ecr_credential_source=credential.get("source"),
                ecr_credential_generation=credential.get("generation"),
                ecr_credential_reused=credential.get("reused"),
                ecr_credential_age_seconds=credential.get("age_seconds"),
            )

    async def _ensure_dockerhub_authentication(
        self,
        info: registry.SessionInfo,
        deadline: float | None = None,
    ) -> None:
        deadline = deadline if deadline is not None else time.monotonic() + self._oci_cfg.pull_timeout_s
        username = self._oci_cfg.dockerhub_username
        token_file = self._oci_cfg.dockerhub_token_file
        if username is None or token_file is None:
            if self._oci_cfg.require_dockerhub_auth:
                raise APIError("Docker Hub authentication is required but not configured")
            return

        check = await self._outer_exec_idempotent(
            info,
            "\n".join(
                [
                    f"auth_file={shlex.quote(_DOCKERHUB_AUTH_FILE)}",
                    'login="$(podman login --authfile "$auth_file" --get-login '
                    f'{_DOCKERHUB_REGISTRY} 2>/dev/null || true)"',
                    'if [ "$login" = "$OCI_RUNNER_DOCKERHUB_USERNAME" ]; then',
                    "  printf 'authenticated\\n'",
                    "else",
                    "  printf 'missing\\n'",
                    "fi",
                ]
            ),
            timeout=30,
            env={"OCI_RUNNER_DOCKERHUB_USERNAME": username},
            deadline=deadline,
            operation="registry_authentication",
        )
        if check.exit_code != 0:
            raise APIError("could not inspect Docker Hub authentication inside OCI runner")
        if check.stdout.strip() == "authenticated":
            info.metadata["dockerhub_authenticated"] = True
            info.metadata["dockerhub_auth_reused"] = True
            return
        if check.stdout.strip() != "missing":
            raise APIError("Docker Hub authentication probe returned an unexpected response")

        token = read_dockerhub_token_file(token_file)
        login = await self._outer_exec_idempotent(
            info,
            "\n".join(
                [
                    "set -eu",
                    "install -d -m 700 /home/runner/.config/containers",
                    f"auth_file={shlex.quote(_DOCKERHUB_AUTH_FILE)}",
                    'printf %s "$OCI_RUNNER_DOCKERHUB_TOKEN" | podman login '
                    f'--authfile "$auth_file" --username "$OCI_RUNNER_DOCKERHUB_USERNAME" '
                    f"--password-stdin {_DOCKERHUB_REGISTRY} >/dev/null",
                    'chmod 600 "$auth_file"',
                    'test "$(podman login --authfile "$auth_file" --get-login '
                    f'{_DOCKERHUB_REGISTRY})" = "$OCI_RUNNER_DOCKERHUB_USERNAME"',
                ]
            ),
            timeout=60,
            env={
                "OCI_RUNNER_DOCKERHUB_USERNAME": username,
                "OCI_RUNNER_DOCKERHUB_TOKEN": token,
            },
            deadline=deadline,
            operation="registry_authentication",
        )
        if login.exit_code != 0:
            raise APIError("Docker Hub authentication failed inside OCI runner")
        info.metadata["dockerhub_authenticated"] = True
        info.metadata["dockerhub_auth_reused"] = False

    def _podman_pull_command(self, requested_image: str, *, storage_driver: str | None = None) -> str:
        command = ["podman"]
        if self._oci_cfg.podman_ignore_chown_errors:
            if storage_driver not in {"overlay", "vfs"}:
                raise APIError(
                    "rootless ownership squashing requires Podman storage driver "
                    f"'overlay' or 'vfs', got {storage_driver!r}"
                )
            command.extend(("--storage-opt", f"{storage_driver}.ignore_chown_errors=true"))
        command.extend(("pull", "--quiet"))
        if authenticated_ecr_registry(requested_image, self._oci_cfg.ecr) is not None:
            command.extend(("--authfile", _ECR_AUTH_FILE))
        elif self._oci_cfg.dockerhub_auth_enabled:
            command.extend(("--authfile", _DOCKERHUB_AUTH_FILE))
        command.append(requested_image)
        return shlex.join(command)

    async def _pull_image(
        self,
        info: registry.SessionInfo,
        requested_image: str,
        *,
        deadline: float | None = None,
        allow_ecr_fallback: bool = True,
    ) -> None:
        """Retry one registry source once after typed transient exhaustion."""
        deadline = deadline if deadline is not None else time.monotonic() + self._oci_cfg.pull_timeout_s
        pull_id = uuid.uuid4().hex
        for source_attempt in range(2):
            try:
                await self._pull_image_once(
                    info,
                    requested_image,
                    deadline=deadline,
                    pull_id=pull_id,
                    allow_ecr_fallback=allow_ecr_fallback,
                )
                return
            except OCIRunnerTransientGatewayError:
                if source_attempt == 1 or _remaining_seconds(deadline) <= 0:
                    raise
                info.metadata["image_pull_transient_source_retries"] = (
                    int(info.metadata.get("image_pull_transient_source_retries", 0)) + 1
                )

    async def _pull_mounted_images(
        self,
        info: registry.SessionInfo,
        *,
        deadline: float,
    ) -> None:
        for mount in _mounted_images(info):
            # Auxiliary images are already resolved independently.  In
            # particular, never apply the task image's Docker Hub fallback to a
            # toolbox image hosted in a different registry.
            await self._pull_image(
                info,
                mount["image"],
                deadline=deadline,
                allow_ecr_fallback=False,
            )

    async def _pull_image_once(
        self,
        info: registry.SessionInfo,
        requested_image: str,
        *,
        deadline: float,
        pull_id: str,
        allow_ecr_fallback: bool,
    ) -> None:
        """Launch a pull in the outer runner and poll it with short exec requests."""
        storage_driver: str | None = None
        if self._oci_cfg.podman_ignore_chown_errors:
            detected_driver = info.metadata.get("podman_storage_driver")
            if isinstance(detected_driver, str):
                storage_driver = detected_driver
            else:
                detection = await self._outer_exec_idempotent(
                    info,
                    "podman info --format '{{.Store.GraphDriverName}}'",
                    timeout=_PULL_REQUEST_TIMEOUT_SECONDS,
                    deadline=deadline,
                    operation="image_pull",
                )
                if detection.exit_code != 0:
                    raise APIError(
                        "failed to detect Podman storage driver before enabling rootless ownership squashing: "
                        f"{(detection.stderr or detection.stdout)[-2000:]}"
                    )
                storage_driver = detection.stdout.strip()
                if storage_driver not in {"overlay", "vfs"}:
                    raise APIError(
                        f"rootless ownership squashing is unsupported for Podman storage driver {storage_driver!r}"
                    )
                info.metadata["podman_storage_driver"] = storage_driver
        pull_command = self._podman_pull_command(requested_image, storage_driver=storage_driver)
        pull_dir = f"/home/runner/shared/{_TRANSFER_DIR}/pull-{pull_id}"
        log_path = f"{pull_dir}/pull.log"
        rc_path = f"{pull_dir}/pull.rc"
        pid_path = f"{pull_dir}/pull.pid"
        inner_command = "\n".join(
            [
                "set +e",
                f"{pull_command} >{shlex.quote(log_path)} 2>&1",
                "pull_rc=$?",
                f"printf '%s\\n' \"$pull_rc\" >{shlex.quote(rc_path)}.tmp",
                f"mv -f {shlex.quote(rc_path)}.tmp {shlex.quote(rc_path)}",
            ]
        )
        launch_command = "\n".join(
            [
                "set -eu",
                f"mkdir -p {shlex.quote(pull_dir)}",
                f"if [ -f {shlex.quote(rc_path)} ] || [ -f {shlex.quote(pid_path)} ]; then",
                f"  pull_pid=$(cat {shlex.quote(pid_path)} 2>/dev/null || printf finished)",
                f"elif mkdir {shlex.quote(pull_dir + '/launch.claim')} 2>/dev/null; then",
                f"  nohup setsid bash -lc {shlex.quote(inner_command)} </dev/null >/dev/null 2>&1 &",
                "  pull_pid=$!",
                f"  printf '%s\\n' \"$pull_pid\" >{shlex.quote(pid_path)}.tmp",
                f"  mv -f {shlex.quote(pid_path)}.tmp {shlex.quote(pid_path)}",
                "else",
                f"  for _ in $(seq 1 100); do test -f {shlex.quote(pid_path)} && break; sleep 0.1; done",
                f"  test -f {shlex.quote(pid_path)}",
                f"  pull_pid=$(cat {shlex.quote(pid_path)})",
                "fi",
                "printf 'LAUNCHED:%s\\n' \"$pull_pid\"",
            ]
        )
        info.metadata.update(
            image_pull_mode="background_poll",
            image_pull_job_id=pull_id,
            image_pull_timeout_seconds=self._oci_cfg.pull_timeout_s,
            podman_ignore_chown_errors=self._oci_cfg.podman_ignore_chown_errors,
        )
        try:
            launch = await self._outer_exec_idempotent(
                info,
                launch_command,
                timeout=_PULL_REQUEST_TIMEOUT_SECONDS,
                deadline=deadline,
                operation="image_pull",
            )
        except OCIRunnerTransientGatewayError:
            info.metadata["image_pull_status"] = "gateway_unavailable"
            raise
        except Exception as exc:
            info.metadata["image_pull_status"] = "launch_uncertain"
            raise APIError(
                "background image-pull launch had an uncertain response; the command was not replayed"
            ) from exc
        if launch.exit_code != 0 or "LAUNCHED:" not in launch.stdout:
            info.metadata["image_pull_status"] = "launch_failed"
            raise APIError(f"background image-pull launch failed: {(launch.stderr or launch.stdout)[-2000:]}")

        poll_command = "\n".join(
            [
                f"if [ -f {shlex.quote(rc_path)} ]; then",
                f"  pull_rc=$(cat {shlex.quote(rc_path)})",
                "  printf 'FINISHED:%s\\n' \"$pull_rc\"",
                '  if [ "$pull_rc" -ne 0 ]; then',
                f"    tail -c 2000 {shlex.quote(log_path)} 2>/dev/null || true",
                "  fi",
                f'elif [ -f {shlex.quote(pid_path)} ] && kill -0 "$(cat {shlex.quote(pid_path)})" 2>/dev/null; then',
                "  printf 'RUNNING\\n'",
                "else",
                "  printf 'LOST\\n'",
                "fi",
            ]
        )
        poll_count = 0
        consecutive_errors = 0
        poll_error_count = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                info.metadata.update(image_pull_status="timed_out", image_pull_poll_count=poll_count)
                stopped = await self._terminate_outer_process_group(info, pid_path)
                if not stopped:
                    raise self._poisoned_shell_error(
                        info,
                        "image_pull_process_group_alive",
                        "image pull timed out and its process group could not be verified stopped",
                        stage="image_pull",
                        failure_reason="command_timeout_cleanup_unverified",
                        timeout_category="image_pull_budget",
                    )
                info.metadata.update(
                    failure_reason="command_budget_exhausted",
                    timeout_category="image_pull_budget",
                )
                raise OCIRunnerCommandTimeoutError(
                    info.session_id,
                    pull_command,
                    self._oci_cfg.pull_timeout_s,
                    failure_reason="command_budget_exhausted",
                    timeout_category="image_pull_budget",
                    cause_stage="image_pull",
                )
            try:
                poll = await self._outer_exec_idempotent(
                    info,
                    poll_command,
                    timeout=min(_PULL_REQUEST_TIMEOUT_SECONDS, max(1, int(remaining))),
                    deadline=deadline,
                    operation="image_pull",
                )
                poll_count += 1
                consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except OCIRunnerTransientGatewayError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                poll_error_count += 1
                info.metadata["image_pull_last_poll_error"] = str(exc)[:2000]
                info.metadata["image_pull_poll_error_count"] = poll_error_count
                if consecutive_errors >= self._oci_cfg.pull_poll_max_errors:
                    info.metadata.update(image_pull_status="poll_failed", image_pull_poll_count=poll_count)
                    raise APIError(
                        f"background image-pull status polling failed {consecutive_errors} consecutive times"
                    ) from exc
                await _sleep_before_deadline(_PULL_POLL_INTERVAL_SECONDS, deadline)
                continue
            status = poll.stdout.strip()
            if status.startswith("FINISHED:"):
                first_line, _, details = status.partition("\n")
                try:
                    pull_exit_code = int(first_line.removeprefix("FINISHED:"))
                except ValueError as exc:
                    info.metadata.update(image_pull_status="invalid_status", image_pull_poll_count=poll_count)
                    raise APIError(f"background image-pull returned invalid status: {first_line!r}") from exc
                info.metadata.update(
                    image_pull_status="completed" if pull_exit_code == 0 else "failed",
                    image_pull_poll_count=poll_count,
                    image_pull_exit_code=pull_exit_code,
                )
                if pull_exit_code != 0:
                    if (
                        allow_ecr_fallback
                        and self._oci_cfg.allow_dockerhub_fallback
                        and _ECR_UPSTREAM_AUTH_FAILURE in details.lower()
                        and is_configured_ecr_image(requested_image, self._oci_cfg.ecr)
                        and (info.source_image or "").startswith(
                            ("docker.io/", "index.docker.io/", "registry-1.docker.io/")
                        )
                    ):
                        source_image = str(info.source_image)
                        info.metadata.update(
                            image_pull_primary_status="ecr_upstream_auth_failed",
                            image_pull_fallback="direct_dockerhub",
                        )
                        await self._ensure_dockerhub_authentication(info, deadline=deadline)
                        await self._pull_image(
                            info,
                            source_image,
                            deadline=deadline,
                            allow_ecr_fallback=False,
                        )
                        tag = await self._outer_exec_idempotent(
                            info,
                            shlex.join(["podman", "tag", source_image, requested_image]),
                            timeout=60,
                            deadline=deadline,
                            operation="image_pull",
                        )
                        if tag.exit_code != 0:
                            raise APIError(
                                f"direct Docker Hub fallback tag failed: {(tag.stderr or tag.stdout)[-2000:]}"
                            )
                        info.metadata["image_pull_status"] = "completed"
                        return
                    raise APIError(f"podman pull failed: {details[-2000:]}")
                return
            if status != "RUNNING":
                info.metadata.update(image_pull_status="lost", image_pull_poll_count=poll_count)
                stopped = await self._terminate_outer_process_group(info, pid_path)
                if not stopped:
                    raise self._poisoned_shell_error(
                        info,
                        "image_pull_process_group_alive",
                        "lost image-pull process group could not be verified stopped",
                        stage="image_pull",
                        failure_reason="command_timeout_cleanup_unverified",
                    )
                raise APIError(f"background image-pull process was lost: {status[-2000:]}")
            await _sleep_before_deadline(_PULL_POLL_INTERVAL_SECONDS, deadline)

    async def _terminate_outer_process_group(
        self,
        info: registry.SessionInfo,
        pid_path: str,
        *,
        grace_seconds: int = 10,
    ) -> bool:
        command = "\n".join(
            [
                "set +e",
                f"pid=$(cat {shlex.quote(pid_path)} 2>/dev/null) || exit 1",
                'case "$pid" in ""|*[!0-9]*) exit 1 ;; esac',
                'if kill -0 -- "-$pid" 2>/dev/null; then kill -TERM -- "-$pid" 2>/dev/null; fi',
                f"deadline=$((SECONDS + {grace_seconds}))",
                'while kill -0 -- "-$pid" 2>/dev/null && [ "$SECONDS" -lt "$deadline" ]; do sleep 0.2; done',
                'if kill -0 -- "-$pid" 2>/dev/null; then kill -KILL -- "-$pid" 2>/dev/null; fi',
                'for _ in $(seq 1 20); do kill -0 -- "-$pid" 2>/dev/null || break; sleep 0.1; done',
                'kill -0 -- "-$pid" 2>/dev/null && exit 1',
                "bash -lc true",
            ]
        )
        try:
            result = await self._outer_exec(
                info,
                command,
                timeout=grace_seconds + 20,
            )
        except Exception:
            return False
        return result.exit_code == 0

    async def _admit_task_resources(self, info: registry.SessionInfo, deadline: float) -> None:
        requested = info.metadata.get("requested_resources")
        if not isinstance(requested, dict):
            return
        probe = await self._outer_exec_idempotent(
            info,
            _resource_probe_command(),
            timeout=30,
            deadline=deadline,
            operation="resource_admission",
        )
        if probe.exit_code != 0:
            raise OCIRunnerResourceAdmissionError(
                f"failed to inspect outer-session resources: {(probe.stderr or probe.stdout)[-1000:]}"
            )
        values = dict(
            line.split("=", 1) for line in probe.stdout.splitlines() if line.startswith("OCI_") and "=" in line
        )
        cpuset = _expand_cpuset(values.get("OCI_CPUSET_EFFECTIVE", ""))
        cpu_count = int(requested["cpu_count"])
        if len(cpuset) < cpu_count:
            raise OCIRunnerResourceAdmissionError(
                f"task requests {cpu_count} CPUs but the outer session exposes only {len(cpuset)}"
            )
        memory_text = values.get("OCI_OUTER_MEMORY_MAX", "")
        memory_source = "cgroup"
        if memory_text in {"", "max", "unavailable"}:
            if not info.environment.startswith("oci-runner-firecracker"):
                raise OCIRunnerResourceAdmissionError("outer-session memory limit is unlimited or unavailable")
            memory_text = values.get("OCI_GUEST_MEMORY_TOTAL", "")
            memory_source = "firecracker_guest"
        try:
            outer_memory_bytes = int(memory_text)
            disk_available_bytes = int(values.get("OCI_DISK_AVAILABLE", ""))
        except ValueError as exc:
            raise OCIRunnerResourceAdmissionError(
                "outer-session resource probe returned invalid values: "
                f"memory={memory_text!r} disk={values.get('OCI_DISK_AVAILABLE')!r}"
            ) from exc
        memory_bytes = int(requested["memory_bytes"])
        disk_bytes = int(requested["disk_bytes"])
        memory_headroom_bytes = max(_MIN_MEMORY_HEADROOM_BYTES, math.ceil(outer_memory_bytes * 0.10))
        if memory_bytes + memory_headroom_bytes > outer_memory_bytes:
            raise OCIRunnerResourceAdmissionError(
                "task memory request leaves insufficient outer-session headroom: "
                f"requested={memory_bytes} outer={outer_memory_bytes} required_headroom={memory_headroom_bytes}"
            )
        if disk_bytes + _DISK_HEADROOM_BYTES > disk_available_bytes:
            raise OCIRunnerResourceAdmissionError(
                "task disk request leaves insufficient outer-session headroom: "
                f"requested={disk_bytes} available={disk_available_bytes} required_headroom={_DISK_HEADROOM_BYTES}"
            )
        allocated_cpus = cpuset[:cpu_count]
        info.metadata["effective_resources"] = {
            "cpu_count": cpu_count,
            "cpuset_cpus": ",".join(str(cpu) for cpu in allocated_cpus),
            "memory_bytes": memory_bytes,
            "memory_swap_bytes": memory_bytes,
            "memory_headroom_bytes": memory_headroom_bytes,
            "outer_memory_bytes": outer_memory_bytes,
            "outer_memory_source": memory_source,
            "disk_requested_bytes": disk_bytes,
            "disk_available_bytes": disk_available_bytes,
            "disk_headroom_bytes": _DISK_HEADROOM_BYTES,
            "disk_enforcement": "admission_only",
            "pids_limit": self._oci_cfg.task_pids_limit,
        }

    def _nested_run_command(self, info: registry.SessionInfo, image: str) -> str:
        effective = info.metadata.get("effective_resources")
        if not isinstance(effective, dict):
            if self._oci_cfg.require_resource_limits:
                raise OCIRunnerResourceAdmissionError("task resource admission did not produce effective limits")
            arguments = ["podman", "run", "--detach", "--name", "task"]
            if info.environment.startswith("oci-runner-firecracker"):
                arguments.extend(("--network", self._oci_cfg.task_network))
            else:
                arguments.extend(("--runtime", "runsc"))
            for mount in _mounted_images(info):
                arguments.extend(
                    (
                        "--mount",
                        f"type=image,source={mount['image']},target={mount['target']}",
                    )
                )
            arguments.extend(
                (
                    "--volume",
                    "/home/runner/shared:/shared",
                    "--entrypoint",
                    "/bin/bash",
                    image,
                    "-lc",
                    "trap : TERM INT; sleep infinity & wait",
                )
            )
            return shlex.join(arguments) + " >/dev/null"
        cpu_count = int(effective["cpu_count"])
        arguments = [
            "podman",
            "run",
            "--detach",
            "--name",
            "task",
        ]
        if info.environment.startswith("oci-runner-firecracker"):
            arguments.extend(("--network", self._oci_cfg.task_network))
        else:
            arguments.extend(("--runtime", "runsc"))
        for mount in _mounted_images(info):
            arguments.extend(
                (
                    "--mount",
                    f"type=image,source={mount['image']},target={mount['target']}",
                )
            )
        arguments.extend(
            (
                "--cpuset-cpus",
                str(effective["cpuset_cpus"]),
                "--memory",
                str(effective["memory_bytes"]),
                "--memory-swap",
                str(effective["memory_swap_bytes"]),
                "--pids-limit",
                str(effective["pids_limit"]),
                "--env",
                f"PYTEST_XDIST_AUTO_NUM_WORKERS={cpu_count}",
                "--env",
                f"OMP_NUM_THREADS={cpu_count}",
                "--env",
                f"MKL_NUM_THREADS={cpu_count}",
                "--env",
                f"OPENBLAS_NUM_THREADS={cpu_count}",
                "--volume",
                "/home/runner/shared:/shared",
                "--entrypoint",
                "/bin/bash",
                image,
                "-lc",
                "trap : TERM INT; sleep infinity & wait",
            )
        )
        return shlex.join(arguments) + " >/dev/null"

    async def _verify_task_resource_limits(self, info: registry.SessionInfo, deadline: float) -> None:
        effective = info.metadata.get("effective_resources")
        if not isinstance(effective, dict):
            return
        inspection = await self._outer_exec_idempotent(
            info,
            "podman inspect task --format '{{json .HostConfig}}'",
            timeout=30,
            deadline=deadline,
            operation="resource_validation",
        )
        try:
            host = json.loads(inspection.stdout)
        except json.JSONDecodeError as exc:
            raise OCIRunnerResourceAdmissionError("podman returned invalid resource inspection JSON") from exc
        observed = {
            "cpuset_cpus": host.get("CpusetCpus", host.get("CpuSetCpus")),
            "memory_bytes": host.get("Memory"),
            "memory_swap_bytes": host.get("MemorySwap"),
            "pids_limit": host.get("PidsLimit"),
        }
        expected = {
            "cpuset_cpus": effective["cpuset_cpus"],
            "memory_bytes": effective["memory_bytes"],
            "memory_swap_bytes": effective["memory_swap_bytes"],
            "pids_limit": effective["pids_limit"],
        }
        enforced = all(str(observed[key]) == str(value) for key, value in expected.items())
        effective["limits_enforced"] = enforced
        effective["podman_inspection"] = observed
        if self._oci_cfg.require_resource_limits and not enforced:
            raise OCIRunnerResourceAdmissionError(
                f"podman did not honor required task resource limits: expected={expected}, observed={observed}"
            )

    async def _bootstrap_nested(self, info: registry.SessionInfo, deadline: float | None = None) -> str:
        deadline = deadline if deadline is not None else time.monotonic() + self._oci_cfg.pull_timeout_s
        if self._oci_cfg.observability:
            return await self._bootstrap_nested_observed(info, deadline)
        requested_image = info.requested_image
        if requested_image is None:
            raise APIError("OCI runner session has no requested image")
        image = shlex.quote(requested_image)
        await self._admit_task_resources(info, deadline)
        await self._pull_image(info, requested_image, deadline=deadline)
        await self._pull_mounted_images(info, deadline=deadline)
        bootstrap = f"""
set -eu
mkdir -p /home/runner/shared/{_TRANSFER_DIR}
digest=$(podman image inspect {image} --format '{{{{.Digest}}}}')
case "$digest" in sha256:*) ;; *) echo "invalid image digest: $digest" >&2; exit 70 ;; esac
size=$(podman image inspect {image} --format '{{{{.Size}}}}')
case "$size" in ''|*[!0-9]*) echo "invalid image size: $size" >&2; exit 70 ;; esac
podman rm -f task >/dev/null 2>&1 || true
{self._nested_run_command(info, requested_image)}
state=$(podman inspect task --format '{{{{.State.Status}}}}')
[ "$state" = running ] || {{ echo "nested task container state=$state" >&2; podman logs task >&2 || true; exit 71; }}
actual=$(podman image inspect "$(podman inspect task --format '{{{{.Image}}}}')" --format '{{{{.Digest}}}}')
test "$actual" = "$digest"
printf 'OCI_RESOLVED_DIGEST=%s\n' "$digest"
printf 'OCI_IMAGE_SIZE_BYTES=%s\n' "$size"
"""
        result = await self._outer_exec_idempotent(
            info,
            bootstrap,
            timeout=max(1, min(self._oci_cfg.pull_timeout_s, int(_remaining_seconds(deadline)))),
            deadline=deadline,
            operation="nested_container_start",
        )
        if result.exit_code != 0:
            raise APIError(f"OCI image pull or nested startup failed: {(result.stderr or result.stdout)[-2000:]}")
        matches = _DIGEST.findall(result.stdout)
        sizes = _IMAGE_SIZE.findall(result.stdout)
        if len(matches) != 1 or len(sizes) != 1:
            raise APIError(f"OCI bootstrap returned an invalid resolved digest: {result.stdout[-1000:]}")
        digest = matches[0]
        info.metadata["image_size_bytes"] = int(sizes[0])
        await self._verify_task_resource_limits(info, deadline)
        return digest

    async def _bootstrap_nested_observed(
        self,
        info: registry.SessionInfo,
        deadline: float | None = None,
    ) -> str:
        deadline = deadline if deadline is not None else time.monotonic() + self._oci_cfg.pull_timeout_s
        requested_image = info.requested_image
        if requested_image is None:
            raise self._stage_error(info, "image_pull", "OCI runner session has no requested image")
        image = shlex.quote(requested_image)
        has_resource_request = isinstance(info.metadata.get("requested_resources"), dict)
        if has_resource_request:
            await self._timed_stage(info, "resource_admission", self._admit_task_resources(info, deadline))
        await self._timed_stage(
            info,
            "image_pull",
            self._pull_image(info, requested_image, deadline=deadline),
        )
        if _mounted_images(info):
            await self._timed_stage(
                info,
                "image_mount_pull",
                self._pull_mounted_images(info, deadline=deadline),
            )

        inspection = await self._timed_stage(
            info,
            "digest_inspection",
            self._outer_exec_idempotent(
                info,
                f"podman image inspect {image} --format '{{{{.Digest}}}} {{{{.Size}}}}'",
                timeout=60,
                deadline=deadline,
                operation="digest_inspection",
            ),
        )
        matches = _DIGEST_AND_SIZE.findall(inspection.stdout)
        if inspection.exit_code != 0 or len(matches) != 1:
            raise self._stage_error(info, "digest_inspection", inspection.stdout[-1000:])
        digest, size = matches[0]
        info.metadata["image_size_bytes"] = int(size)

        start = await self._timed_stage(
            info,
            "nested_container_start",
            self._outer_exec_idempotent(
                info,
                "\n".join(
                    [
                        "podman rm -f task >/dev/null 2>&1 || true",
                        self._nested_run_command(info, requested_image),
                        "state=$(podman inspect task --format '{{.State.Status}}')",
                        '[ "$state" = running ] || '
                        '{ echo "nested task container state=$state" >&2; podman logs task >&2 || true; exit 71; }',
                        f'test "$(podman image inspect "$(podman inspect task --format \'{{{{.Image}}}}\')" '
                        f"--format '{{{{.Digest}}}}')\" = {shlex.quote(digest)}",
                    ]
                ),
                timeout=self._oci_cfg.pull_timeout_s,
                deadline=deadline,
                operation="nested_container_start",
            ),
        )
        if start.exit_code != 0:
            raise self._stage_error(info, "nested_container_start", (start.stderr or start.stdout)[-2000:])

        if has_resource_request:
            await self._timed_stage(info, "resource_validation", self._verify_task_resource_limits(info, deadline))

        return digest

    async def _validate_nested(self, info: registry.SessionInfo, deadline: float | None = None) -> None:
        deadline = deadline if deadline is not None else time.monotonic() + self._oci_cfg.pull_timeout_s
        expected_commit = info.env_vars.get(_EXPECTED_COMMIT_ENV)
        expected_instance = info.env_vars.get(_EXPECTED_INSTANCE_ENV)
        workdir = _managed_workdir(info)
        quoted_workdir = shlex.quote(workdir)
        checks = [
            "set -eu",
            "command -v bash >/dev/null 2>&1 || { echo 'missing bash' >&2; exit 72; }",
            f"test -d {quoted_workdir} || {{ echo 'missing managed workdir' >&2; exit 72; }}",
            "test -d /shared || { echo 'missing /shared' >&2; exit 72; }",
            f"test \"$(pwd -P)\" = {quoted_workdir} || {{ echo 'unexpected working directory' >&2; exit 72; }}",
        ]
        if expected_commit:
            quoted_commit = shlex.quote(expected_commit)
            quoted_commit_object = shlex.quote(f"{expected_commit}^{{commit}}")
            checks.extend(
                [
                    "actual_commit=$(git rev-parse HEAD) || "
                    "{ echo 'cannot resolve current base commit' >&2; exit 73; }",
                    "base_commit_repaired=0",
                    f'if [ "$actual_commit" != {quoted_commit} ]; then',
                    f"  git cat-file -e {quoted_commit_object} || "
                    "{ echo 'expected base commit is absent from image' >&2; exit 74; }",
                    f"  git checkout --detach --force {quoted_commit} >/dev/null 2>&1 || "
                    "{ echo 'failed to check out expected base commit' >&2; exit 75; }",
                    "  base_commit_repaired=1",
                    "fi",
                    "final_commit=$(git rev-parse HEAD) || { echo 'cannot resolve final base commit' >&2; exit 76; }",
                    f'if [ "$final_commit" != {quoted_commit} ]; then',
                    "  echo 'final base commit does not match dataset' >&2",
                    "  exit 76",
                    "fi",
                    "printf 'OCI_BASE_COMMIT_ORIGINAL=%s\\n' \"$actual_commit\"",
                    "printf 'OCI_BASE_COMMIT_FINAL=%s\\n' \"$final_commit\"",
                    "printf 'OCI_BASE_COMMIT_REPAIRED=%s\\n' \"$base_commit_repaired\"",
                ]
            )
        validation = await self._nested_exec_argv(
            info,
            ["bash", "-c", "\n".join(checks)],
            working_dir=workdir,
            timeout=60,
            stage="container_validation",
            retry_gateway_unavailable=True,
            deadline=deadline,
        )
        if validation.exit_code != 0:
            label = f" for {expected_instance}" if expected_instance else ""
            details = (validation.stderr or validation.stdout)[-2000:]
            raise APIError(f"nested task validation failed{label}: {details}")
        commit_metadata = {}
        for line in validation.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator and key.startswith("OCI_BASE_COMMIT_"):
                commit_metadata[key] = value
        if expected_commit:
            info.metadata.update(
                base_commit_original=commit_metadata.get("OCI_BASE_COMMIT_ORIGINAL"),
                base_commit_final=commit_metadata.get("OCI_BASE_COMMIT_FINAL", expected_commit),
                base_commit_repaired=commit_metadata.get("OCI_BASE_COMMIT_REPAIRED") == "1",
            )

    @staticmethod
    def _poisoned_shell_error(
        info: registry.SessionInfo,
        status: str,
        message: str,
        *,
        stage: str = "shell_exec",
        failure_reason: str = "shell_state_lost",
        timeout_category: str | None = None,
    ) -> OCIRunnerStageError:
        info.assignment_poisoned = True
        info.assignment_poison_reason = (
            "shell_start_failure" if stage in {"authentication", "shell_start"} else failure_reason
        )
        info.shell_failure_status = status
        info.metadata.update(
            assignment_poisoned=True,
            assignment_poison_reason=info.assignment_poison_reason,
            shell_failure_status=status,
            failure_reason=failure_reason,
            timeout_category=timeout_category,
        )
        timings = info.metadata.get("oci_timings")
        return OCIRunnerStageError(
            stage,
            f"OCI runner {message}; assignment is poisoned and the command was not replayed",
            timings=timings if isinstance(timings, dict) else None,
            failure_reason=failure_reason,
            timeout_category=timeout_category,
        )

    async def _collect_terminal_diagnostics(self, info: registry.SessionInfo) -> dict[str, object]:
        diagnostics: dict[str, object] = {}
        for name, method, path, headers in (
            ("health", "GET", "healthz", None),
            ("shell", "GET", "v1/shells", self._auth_headers()),
        ):
            try:
                response = await self._request_json(info, method, path, headers=headers, timeout=5.0)
            except Exception as exc:
                diagnostics[f"{name}_error"] = type(exc).__name__
            else:
                diagnostics[f"{name}_http_status"] = response.status_code
        info.metadata["terminal_diagnostics"] = diagnostics
        return diagnostics

    async def _verify_shell_usable(self, info: registry.SessionInfo) -> bool:
        if info.shell_id is None:
            return False
        try:
            response = await self._managed_shell_request(
                info,
                body={"command": ["true"], "shellId": info.shell_id, "timeout": 5},
                timeout=10.0,
            )
        except Exception:
            return False
        if response.status_code != 200:
            return False
        try:
            _, _, exit_code, timed_out = normalize_command_response(response.body)
        except APIError:
            return False
        return exit_code == 0 and not timed_out

    async def _outer_exec(
        self,
        info: registry.SessionInfo,
        command: str,
        timeout: int,
        env: dict[str, str] | None = None,
        *,
        deadline: float | None = None,
        allow_not_sent_retry: bool = False,
        allow_ambiguous_retry: bool = False,
    ) -> CommandResponse:
        command_timeout = min(timeout, self._oci_cfg.exec_timeout_ceiling_s - 1)
        request_timeout = min(float(command_timeout) + 30.0, float(self._oci_cfg.exec_timeout_ceiling_s))
        if deadline is not None:
            remaining = _remaining_seconds(deadline)
            if remaining <= 0:
                raise TimeoutError("OCI outer exec deadline expired")
            command_timeout = max(1, min(command_timeout, int(remaining)))
            request_timeout = min(float(command_timeout) + 30.0, remaining, self._oci_cfg.exec_timeout_ceiling_s)
        payload: dict[str, object] = {"command": ["bash", "-lc", command], "timeout": command_timeout}
        sensitive_env = False
        if env:
            payload["env"] = env
            sensitive_env = any(
                fragment in key.upper()
                for key in env
                for fragment in ("PASSWORD", "SECRET", "TOKEN", "CREDENTIAL", "AUTH")
            )
        try:
            response = await self._request_json(
                info,
                "POST",
                "v1/exec",
                body=payload,
                headers=self._auth_headers(),
                timeout=request_timeout,
            )
            status_code, body = response.status_code, response.body
        except SandoqHttpTransportError as exc:
            # Callers opt into this only for commands whose replay is safe
            # even when the transport cannot prove whether the first request
            # reached the guest (for example, read-only background status or
            # an idempotent process-group termination).
            if allow_ambiguous_retry:
                raise
            if exc.timed_out:
                info.assignment_poisoned = True
                info.assignment_poison_reason = "proxy_deadline_breach"
                info.shell_failure_status = "transport_timeout_unknown"
                info.metadata.update(
                    assignment_poisoned=True,
                    assignment_poison_reason=info.assignment_poison_reason,
                    shell_failure_status=info.shell_failure_status,
                    timeout_category="proxy_deadline_breach",
                )
                raise OCIRunnerCommandTimeoutError(
                    info.session_id,
                    command,
                    timeout,
                    failure_reason="proxy_deadline_breach",
                    timeout_category="proxy_deadline_breach",
                ) from exc
            if allow_not_sent_retry and exc.delivery_state == "not_sent" and exc.retryable:
                raise
            if exc.delivery_state == "not_sent":
                info.assignment_poisoned = True
                info.assignment_poison_reason = "pre_delivery_gateway_failure"
                info.metadata.update(
                    assignment_poisoned=True,
                    assignment_poison_reason=info.assignment_poison_reason,
                    failure_reason="pre_delivery_gateway_failure",
                    transport_delivery_state="not_sent",
                )
                raise OCIRunnerTransientGatewayError(
                    "outer_exec",
                    http_status=exc.http_status,
                    attempts=1,
                    timings={"outer_exec": 0.0},
                    delivery_state="not_sent",
                ) from exc
            await self._collect_terminal_diagnostics(info)
            raise self._poisoned_shell_error(
                info,
                "transport_error",
                f"blocking exec had an uncertain transport failure: {exc}",
                failure_reason="gateway_command_outcome_unknown",
            ) from exc
        if status_code in (408, 504):
            await self._collect_terminal_diagnostics(info)
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}",
                f"blocking exec reached HTTP {status_code} with an unknown command outcome",
                failure_reason="proxy_deadline_breach",
                timeout_category="proxy_deadline_breach",
            )
        if status_code in (502, 503, 404, 410):
            await self._collect_terminal_diagnostics(info)
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}",
                f"blocking exec reached terminal HTTP {status_code}",
                failure_reason="outer_session_lost" if status_code in (404, 410) else "gateway_command_outcome_unknown",
            )
        if status_code != 200:
            details = "response omitted because the request contained sensitive environment values"
            if not sensitive_env:
                details = str(body)[-1000:]
            raise APIError(f"OCI runner /v1/exec failed on {info.session_id}: HTTP {status_code}: {details}")
        stdout, stderr, exit_code, timed_out = normalize_command_response(body)
        if timed_out:
            if await self._verify_shell_usable(info):
                info.metadata["timeout_category"] = "oci_command_budget"
                return CommandResponse(stdout=stdout, stderr=stderr, exit_code=124)
            raise self._poisoned_shell_error(
                info,
                "timeout_shell_unusable",
                "blocking exec timed out and the persistent shell did not recover",
                failure_reason="command_timeout_cleanup_unverified",
                timeout_category="oci_command_budget",
            )
        return CommandResponse(stdout=stdout, stderr=stderr, exit_code=exit_code)

    async def _outer_exec_idempotent(
        self,
        info: registry.SessionInfo,
        command: str,
        timeout: int,
        env: dict[str, str] | None = None,
        *,
        deadline: float | None = None,
        operation: str = "outer_exec",
        retry_ambiguous_transport: bool = False,
    ) -> CommandResponse:
        """Retry a trusted idempotent outer command on transient gateway unavailability."""
        absolute_deadline = deadline if deadline is not None else time.monotonic() + timeout
        started = time.monotonic()
        attempts = 0
        last_status: int | None = None
        last_delivery_state = "unknown"
        not_sent_retries = 0
        for attempt in range(self._oci_cfg.gateway_retry_attempts):
            remaining = _remaining_seconds(absolute_deadline)
            if remaining <= 0:
                break
            attempts = attempt + 1
            safe_not_sent = False
            try:
                command_timeout = max(1, min(timeout, int(remaining)))
                result = await self._outer_exec(
                    info,
                    command,
                    command_timeout,
                    env=env,
                    deadline=absolute_deadline,
                    allow_not_sent_retry=True,
                    allow_ambiguous_retry=retry_ambiguous_transport,
                )
                if not_sent_retries:
                    self._record_not_sent_recovery(info)
                return result
            except SandoqHttpTransportError as exc:
                last_status = exc.http_status
                last_delivery_state = exc.delivery_state
                safe_not_sent = exc.delivery_state == "not_sent" and exc.retryable
                if not safe_not_sent and not retry_ambiguous_transport:
                    raise
            if attempt + 1 >= self._oci_cfg.gateway_retry_attempts:
                break
            if safe_not_sent:
                not_sent_retries += 1
                self._record_not_sent_retry(info)
            info.metadata["idempotent_gateway_retry_count"] = (
                int(info.metadata.get("idempotent_gateway_retry_count", 0)) + 1
            )
            await _sleep_before_deadline(self._oci_cfg.gateway_retry_interval_s, absolute_deadline)
        elapsed = time.monotonic() - started
        if last_delivery_state == "not_sent":
            self._record_not_sent_exhaustion(info)
        raise OCIRunnerTransientGatewayError(
            operation,
            http_status=last_status,
            attempts=attempts,
            timings={operation: elapsed},
            delivery_state=last_delivery_state,
        )

    async def _nested_exec_argv(
        self,
        info: registry.SessionInfo,
        argv: Sequence[str],
        *,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 60,
        stage: str = "shell_exec",
        retry_gateway_unavailable: bool = False,
        deadline: float | None = None,
        _managed_shell_recovery_attempted: bool = False,
    ) -> CommandResponse:
        command = list(argv)
        if not command:
            raise ValueError("persistent shell argv must not be empty")
        if info.shell_id is None:
            raise self._poisoned_shell_error(
                info,
                "missing_shell",
                "persistent shell is unavailable",
                stage=stage,
            )
        command_timeout = min(timeout, self._oci_cfg.exec_timeout_ceiling_s - 1)
        payload: dict[str, object] = {
            "command": command,
            "shellId": info.shell_id,
            "timeout": command_timeout,
        }
        if working_dir is not None:
            payload["workdir"] = working_dir
        if env:
            payload["env"] = env
        absolute_deadline = (
            deadline
            if deadline is not None
            else time.monotonic()
            + min(
                command_timeout + (0.0 if retry_gateway_unavailable else 30.0),
                self._oci_cfg.exec_timeout_ceiling_s,
            )
        )
        attempts = self._oci_cfg.gateway_retry_attempts
        started = time.monotonic()
        attempted = 0
        last_status: int | None = None
        last_delivery_state = "unknown"
        transient_exhausted = False
        not_sent_retries = 0
        not_sent_exhaustion_recorded = False
        for attempt in range(attempts):
            remaining = _remaining_seconds(absolute_deadline)
            if remaining <= 0:
                break
            attempted = attempt + 1
            request_command_timeout = max(1, min(command_timeout, int(remaining)))
            request_timeout = _request_timeout(
                absolute_deadline,
                min(float(request_command_timeout) + 30.0, self._oci_cfg.exec_timeout_ceiling_s),
            )
            payload["timeout"] = request_command_timeout
            try:
                response = await self._managed_shell_request(
                    info,
                    body=payload,
                    timeout=request_timeout,
                )
                status_code, body = response.status_code, response.body
            except SandoqHttpTransportError as exc:
                last_status = exc.http_status
                last_delivery_state = exc.delivery_state
                transient_exhausted = True
                safe_not_sent = exc.delivery_state == "not_sent" and exc.retryable
                can_retry = safe_not_sent
                if can_retry and attempt + 1 < attempts and _remaining_seconds(absolute_deadline) > 0:
                    if safe_not_sent:
                        not_sent_retries += 1
                        self._record_not_sent_retry(info)
                    await _sleep_before_deadline(self._oci_cfg.gateway_retry_interval_s, absolute_deadline)
                    continue
                if can_retry:
                    if safe_not_sent:
                        self._record_not_sent_exhaustion(info)
                        not_sent_exhaustion_recorded = True
                    break
                if exc.delivery_state == "not_sent":
                    self._record_not_sent_exhaustion(info)
                    not_sent_exhaustion_recorded = True
                    break
                await self._collect_terminal_diagnostics(info)
                raise self._poisoned_shell_error(
                    info,
                    "transport_error",
                    f"persistent shell exec had an uncertain transport failure: {exc}",
                    stage=stage,
                    failure_reason="gateway_command_outcome_unknown",
                ) from exc
            if status_code in (502, 503):
                last_status = status_code
                last_delivery_state = "unknown"
                transient_exhausted = True
                info.metadata["transient_gateway_response_count"] = (
                    int(info.metadata.get("transient_gateway_response_count", 0)) + 1
                )
            else:
                transient_exhausted = False
            break
        if not transient_exhausted and not_sent_retries:
            self._record_not_sent_recovery(info)
        if attempted == 0 or transient_exhausted and last_delivery_state == "not_sent":
            if last_delivery_state == "not_sent" and not not_sent_exhaustion_recorded:
                self._record_not_sent_exhaustion(info)
            raise OCIRunnerTransientGatewayError(
                stage,
                http_status=last_status,
                attempts=attempted,
                timings={stage: time.monotonic() - started},
                delivery_state=last_delivery_state,
            )
        if status_code in (502, 503):
            await self._collect_terminal_diagnostics(info)
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}",
                f"persistent shell exec returned terminal HTTP {status_code}",
                stage=stage,
                failure_reason="gateway_command_outcome_unknown",
            )
        if status_code in (408, 504):
            await self._collect_terminal_diagnostics(info)
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}",
                f"persistent shell exec crossed the proxy deadline with HTTP {status_code} and an unknown outcome",
                stage=stage,
                failure_reason="proxy_deadline_breach",
                timeout_category="proxy_deadline_breach",
            )
        if status_code in (404, 410):
            diagnostics = await self._collect_terminal_diagnostics(info)
            if (
                self._oci_cfg.managed_shell_recovery
                and not _managed_shell_recovery_attempted
                and diagnostics.get("health_http_status") == 200
                and diagnostics.get("shell_http_status") == 200
            ):
                expired_shell_id = info.shell_id
                if expired_shell_id is None:
                    raise self._poisoned_shell_error(
                        info,
                        "missing_shell",
                        "managed shell disappeared before recovery",
                        stage=stage,
                        failure_reason="managed_shell_lost",
                    )
                await self._recover_managed_shell(info, expired_shell_id)
                return await self._nested_exec_argv(
                    info,
                    command,
                    working_dir=working_dir,
                    env=env,
                    timeout=timeout,
                    stage=stage,
                    retry_gateway_unavailable=retry_gateway_unavailable,
                    deadline=deadline,
                    _managed_shell_recovery_attempted=True,
                )
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}",
                f"persistent shell was lost with HTTP {status_code}; diagnostics={diagnostics}",
                stage=stage,
                failure_reason=(
                    "managed_shell_lost"
                    if self._oci_cfg.managed_shell_recovery
                    and diagnostics.get("health_http_status") == 200
                    and diagnostics.get("shell_http_status") == 200
                    else "outer_session_lost"
                ),
            )
        if status_code != 200:
            raise self._poisoned_shell_error(
                info,
                f"http_{status_code}",
                f"persistent shell exec failed with HTTP {status_code}: {body}",
                stage=stage,
            )
        try:
            stdout, stderr, exit_code, timed_out = normalize_command_response(body)
        except APIError as exc:
            raise self._poisoned_shell_error(info, "invalid_response", str(exc), stage=stage) from exc
        if timed_out:
            if await self._verify_shell_usable(info):
                info.metadata["timeout_category"] = "oci_command_budget"
                return CommandResponse(stdout=stdout, stderr=stderr, exit_code=124)
            raise self._poisoned_shell_error(
                info,
                "timeout_shell_unusable",
                "persistent shell returned a timeout and did not recover",
                stage=stage,
                failure_reason="command_timeout_cleanup_unverified",
                timeout_category="oci_command_budget",
            )
        return CommandResponse(stdout=stdout, stderr=stderr, exit_code=exit_code)

    async def execute_command(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str | None = None,
        env: dict | None = None,
        timeout: int | None = None,
    ) -> CommandResponse:
        info = self._info(sandbox_id)
        if not info.nested_ready:
            raise APIError(f"nested task container is not ready for {sandbox_id}")
        return await self._nested_exec_argv(
            info,
            ["bash", "-c", command],
            working_dir=working_dir,
            env=env,
            timeout=int(timeout or 60),
        )

    async def execute_persistent_argv(
        self,
        sandbox_id: str,
        argv: Sequence[str],
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> CommandResponse:
        """Execute trusted bootstrap argv directly in the managed shell."""
        if not argv:
            raise ValueError("persistent shell argv must not be empty")
        info = self._info(sandbox_id)
        if not info.nested_ready:
            raise APIError(f"nested task container is not ready for {sandbox_id}")
        return await self._nested_exec_argv(
            info,
            argv,
            working_dir=working_dir,
            env=env,
            timeout=int(timeout or 60),
        )

    async def execute_idempotent_command(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str | None = None,
        env: dict | None = None,
        timeout: int | None = None,
        *,
        deadline: float | None = None,
        operation: str = "shell_exec",
    ) -> CommandResponse:
        """Execute trusted idempotent recipe code, retrying only proven non-delivery."""
        info = self._info(sandbox_id)
        if not info.nested_ready:
            raise APIError(f"nested task container is not ready for {sandbox_id}")
        return await self._nested_exec_argv(
            info,
            ["bash", "-c", command],
            working_dir=working_dir,
            env=env,
            timeout=int(timeout or 60),
            stage=operation,
            retry_gateway_unavailable=True,
            deadline=deadline,
        )

    async def _stage_upload(
        self,
        info: registry.SessionInfo,
        outer_path: str,
        data: bytes,
        timeout: int,
        deadline: float | None = None,
    ) -> None:
        deadline = deadline if deadline is not None else time.monotonic() + timeout
        encoded = base64.b64encode(data).decode()
        quoted_path = shlex.quote(outer_path)
        setup = await self._outer_exec_idempotent(
            info,
            f"mkdir -p {shlex.quote(os.path.dirname(outer_path))}",
            timeout=30,
            deadline=deadline,
            operation="file_upload",
        )
        if setup.exit_code != 0:
            raise APIError(f"OCI staging setup failed for {outer_path}: {setup.stderr[-1000:]}")
        chunk_paths: list[str] = []
        for index, offset in enumerate(range(0, len(encoded), _STAGING_CHUNK_BYTES)):
            chunk = encoded[offset : offset + _STAGING_CHUNK_BYTES]
            chunk_path = f"{outer_path}.b64.{index:08d}"
            chunk_paths.append(chunk_path)
            append = await self._outer_exec_idempotent(
                info,
                f"printf %s {shlex.quote(chunk)} > {shlex.quote(chunk_path)}",
                timeout=timeout,
                deadline=deadline,
                operation="file_upload",
            )
            if append.exit_code != 0:
                raise APIError(f"OCI staging append failed for {outer_path}: {append.stderr[-1000:]}")
        temporary_path = f"{outer_path}.tmp"
        if chunk_paths:
            decode_command = (
                f"cat {' '.join(shlex.quote(path) for path in chunk_paths)} | "
                f"base64 -d > {shlex.quote(temporary_path)} && mv -f {shlex.quote(temporary_path)} {quoted_path}"
            )
        else:
            decode_command = f": > {quoted_path}"
        decode = await self._outer_exec_idempotent(
            info,
            decode_command,
            timeout=timeout,
            deadline=deadline,
            operation="file_upload",
        )
        if decode.exit_code != 0:
            raise APIError(f"OCI staging decode failed for {outer_path}: {decode.stderr[-1000:]}")

    async def _stage_download(
        self,
        info: registry.SessionInfo,
        outer_path: str,
        timeout: int,
        deadline: float | None = None,
    ) -> bytes:
        deadline = deadline if deadline is not None else time.monotonic() + timeout
        size_result = await self._outer_exec_idempotent(
            info,
            f"wc -c < {shlex.quote(outer_path)}",
            timeout=timeout,
            deadline=deadline,
            operation="file_download",
        )
        if size_result.exit_code != 0:
            raise SandboxFileNotFoundError(f"staged file not found in {info.session_id}: {outer_path}")
        try:
            size = int(size_result.stdout.strip())
        except ValueError as exc:
            raise APIError(f"OCI staging download returned invalid size for {outer_path}") from exc
        if size < 0:
            raise APIError(f"OCI staging download returned invalid size for {outer_path}")

        data = bytearray()
        for offset in range(0, size, _STAGING_DOWNLOAD_CHUNK_BYTES):
            count = min(_STAGING_DOWNLOAD_CHUNK_BYTES, size - offset)
            result = await self._outer_exec_idempotent(
                info,
                f"dd if={shlex.quote(outer_path)} iflag=skip_bytes,count_bytes "
                f"skip={offset} count={count} status=none | base64 -w0",
                timeout=timeout,
                deadline=deadline,
                operation="file_download",
            )
            if result.exit_code != 0:
                raise SandboxFileNotFoundError(f"staged file not found in {info.session_id}: {outer_path}")
            try:
                data.extend(base64.b64decode(result.stdout, validate=True))
            except ValueError as exc:
                raise APIError(f"OCI staging download returned invalid base64 for {outer_path}") from exc
        if len(data) != size:
            raise APIError(f"OCI staging download returned {len(data)} bytes for {outer_path}; expected {size}")
        return bytes(data)

    async def upload_bytes(
        self,
        sandbox_id: str,
        file_path: str,
        file_bytes: bytes,
        filename: str | None = None,
        timeout: int | None = None,
        *,
        deadline: float | None = None,
    ) -> FileUploadResponse:
        del filename
        info = self._info(sandbox_id)
        transfer_id = uuid.uuid4().hex
        outer_path = f"/home/runner/shared/{_TRANSFER_DIR}/{transfer_id}"
        nested_path = f"/shared/{_TRANSFER_DIR}/{transfer_id}"
        request_timeout = int(timeout or 120)
        absolute_deadline = deadline if deadline is not None else time.monotonic() + request_timeout
        await self._stage_upload(info, outer_path, file_bytes, request_timeout, absolute_deadline)
        parent = os.path.dirname(file_path) or "."
        command = f"mkdir -p {shlex.quote(parent)} && cp {shlex.quote(nested_path)} {shlex.quote(file_path)}"
        try:
            result = await self._nested_exec_argv(
                info,
                ["bash", "-c", command],
                timeout=request_timeout,
                stage="file_upload",
                retry_gateway_unavailable=True,
                deadline=absolute_deadline,
            )
            if result.exit_code != 0:
                raise APIError(f"nested upload copy failed for {file_path}: {result.stderr[-1000:]}")
        finally:
            await self._outer_exec_idempotent(
                info,
                f"rm -f -- {shlex.quote(outer_path)} {shlex.quote(outer_path + '.tmp')} "
                f"{shlex.quote(outer_path + '.b64.')}*",
                timeout=30,
                deadline=absolute_deadline,
                operation="file_upload_cleanup",
            )
        return _upload_ok(file_path, len(file_bytes))

    async def upload_file(
        self,
        sandbox_id: str,
        file_path: str,
        local_file_path: str,
        timeout: int | None = None,
    ) -> FileUploadResponse:
        data = await asyncio.to_thread(Path(local_file_path).read_bytes)
        return await self.upload_bytes(sandbox_id, file_path, data, timeout=timeout)

    async def _download_bytes(
        self,
        sandbox_id: str,
        file_path: str,
        timeout: int,
        deadline: float | None = None,
    ) -> bytes:
        info = self._info(sandbox_id)
        transfer_id = uuid.uuid4().hex
        outer_path = f"/home/runner/shared/{_TRANSFER_DIR}/{transfer_id}"
        nested_path = f"/shared/{_TRANSFER_DIR}/{transfer_id}"
        absolute_deadline = deadline if deadline is not None else time.monotonic() + timeout
        result = await self._nested_exec_argv(
            info,
            ["bash", "-c", f"cp {shlex.quote(file_path)} {shlex.quote(nested_path)}"],
            timeout=timeout,
            stage="file_download",
            retry_gateway_unavailable=True,
            deadline=absolute_deadline,
        )
        if result.exit_code != 0:
            raise SandboxFileNotFoundError(f"file not found in {sandbox_id}: {file_path}")
        try:
            return await self._stage_download(info, outer_path, timeout, absolute_deadline)
        finally:
            await self._outer_exec_idempotent(
                info,
                f"rm -f -- {shlex.quote(outer_path)}",
                timeout=30,
                deadline=absolute_deadline,
                operation="file_download_cleanup",
            )

    async def read_file(
        self,
        sandbox_id: str,
        file_path: str,
        timeout: int | None = None,
        *,
        deadline: float | None = None,
    ) -> ReadFileResponse:
        data = await self._download_bytes(sandbox_id, file_path, int(timeout or 60), deadline)
        content = data.decode(errors="replace")
        return ReadFileResponse(content=content, size=len(data))

    async def download_file(
        self,
        sandbox_id: str,
        file_path: str,
        local_file_path: str,
        timeout: int | None = None,
    ) -> None:
        data = await self._download_bytes(sandbox_id, file_path, int(timeout or 60))
        local_path = Path(local_file_path)
        await asyncio.to_thread(local_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(local_path.write_bytes, data)

    @staticmethod
    def _background_job_paths(info: registry.SessionInfo, job_id: str) -> tuple[str, str]:
        if re.fullmatch(r"job-[0-9a-f]{32}", job_id) is None:
            raise APIError(f"invalid background job id: {job_id!r}")
        assignment_id = re.sub(r"[^a-zA-Z0-9_.-]", "-", info.session_id)
        relative = f".assignments/{assignment_id}/jobs/{job_id}"
        return f"/home/runner/shared/{relative}", f"/shared/{relative}"

    async def start_background_job(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str | None = None,
        env: dict | None = None,
    ) -> BackgroundJob:
        """Launch a nested command without holding one proxy request open."""
        info = self._info(sandbox_id)
        if not info.nested_ready:
            raise APIError(f"nested task container is not ready for {sandbox_id}")
        job_id = "job-" + uuid.uuid4().hex
        outer_dir, nested_dir = self._background_job_paths(info, job_id)
        workdir = working_dir or _managed_workdir(info)
        environment = {**info.env_vars, **{str(key): str(value) for key, value in (env or {}).items()}}
        invalid_keys = [key for key in environment if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)]
        if invalid_keys:
            raise APIError(f"background job environment contains invalid names: {sorted(invalid_keys)}")
        inner_lines = [
            "#!/usr/bin/env bash",
            "set +e",
            f"cd {shlex.quote(workdir)} || exit 127",
            f"setsid bash -lc {shlex.quote(command)} &",
            "child=$!",
            f'printf "%s\\n" "$child" >{shlex.quote(nested_dir + "/nested.pgid.tmp")}',
            f"mv -f {shlex.quote(nested_dir + '/nested.pgid.tmp')} {shlex.quote(nested_dir + '/nested.pgid')}",
            'wait "$child"',
            "exit $?",
        ]
        encoded = base64.b64encode(("\n".join(inner_lines) + "\n").encode()).decode()
        podman_env = " ".join(f"--env {shlex.quote(key)}" for key in sorted(environment))
        supervisor_lines = [
            "#!/usr/bin/env bash",
            "set +e",
            f"job_dir={shlex.quote(outer_dir)}",
            "before_oom=$(podman exec task awk '$1 == \"oom_kill\" {print $2}' "
            "/sys/fs/cgroup/memory.events 2>/dev/null || printf 0)",
            f"podman exec {podman_env} task bash {shlex.quote(nested_dir + '/command.sh')} "
            ' >"$job_dir/stdout.log" 2>"$job_dir/stderr.log"',
            "rc=$?",
            "after_oom=$(podman exec task awk '$1 == \"oom_kill\" {print $2}' "
            "/sys/fs/cgroup/memory.events 2>/dev/null || printf 0)",
            "memory_peak=$(podman exec task cat /sys/fs/cgroup/memory.peak 2>/dev/null || printf unknown)",
            "disk_bytes=$(podman inspect --size task --format '{{.SizeRw}}' 2>/dev/null || printf unknown)",
            "oom_killed=$(podman inspect task --format '{{.State.OOMKilled}}' 2>/dev/null || printf unknown)",
            'printf "%s\\n" "$after_oom" >"$job_dir/memory_oom_kill"',
            'printf "%s\\n" "$memory_peak" >"$job_dir/memory_peak"',
            'printf "%s\\n" "$disk_bytes" >"$job_dir/disk_bytes"',
            'if [ "$oom_killed" = true ] || { [ "$after_oom" -gt "$before_oom" ] 2>/dev/null; }; then',
            '  printf nested_oom >"$job_dir/failure_reason.tmp"',
            '  mv -f "$job_dir/failure_reason.tmp" "$job_dir/failure_reason"',
            "fi",
            'printf "%s\\n" "$rc" >"$job_dir/result.tmp"',
            'mv -f "$job_dir/result.tmp" "$job_dir/result"',
        ]
        supervisor_encoded = base64.b64encode(("\n".join(supervisor_lines) + "\n").encode()).decode()
        launch_command = "\n".join(
            [
                "set -eu",
                f"job_dir={shlex.quote(outer_dir)}",
                'mkdir -p "$job_dir"',
                f'printf %s {shlex.quote(encoded)} | base64 -d >"$job_dir/command.sh"',
                'chmod 700 "$job_dir/command.sh"',
                f'printf %s {shlex.quote(supervisor_encoded)} | base64 -d >"$job_dir/supervisor.sh"',
                'chmod 700 "$job_dir/supervisor.sh"',
                'setsid bash "$job_dir/supervisor.sh" </dev/null >"$job_dir/supervisor.log" 2>&1 &',
                'printf "%s\\n" "$!" >"$job_dir/supervisor.pid"',
                'printf "OCI_BACKGROUND_JOB_LAUNCHED=%s\\n" "$!"',
            ]
        )
        launch = await self._outer_exec(info, launch_command, timeout=30, env=environment)
        if launch.exit_code != 0 or "OCI_BACKGROUND_JOB_LAUNCHED=" not in launch.stdout:
            raise OCIRunnerStageError(
                "shell_exec",
                f"failed to launch nested background job: {(launch.stderr or launch.stdout)[-1000:]}",
                failure_reason="command_launch_failed",
            )
        return BackgroundJob(
            job_id=job_id,
            sandbox_id=sandbox_id,
            stdout_log_file=f"{outer_dir}/stdout.log",
            stderr_log_file=f"{outer_dir}/stderr.log",
            exit_file=f"{outer_dir}/result",
        )

    async def _read_outer_tail(self, info: registry.SessionInfo, path: str) -> tuple[str, bool]:
        result = await self._outer_exec_idempotent(
            info,
            f"size=$(wc -c < {shlex.quote(path)}); printf '%s\\n' \"$size\"; "
            f"tail -c {_BACKGROUND_OUTPUT_TAIL_BYTES} {shlex.quote(path)} | base64 -w0",
            timeout=60,
            operation="background_output",
            retry_ambiguous_transport=True,
        )
        if result.exit_code != 0:
            return "", False
        size_text, separator, encoded = result.stdout.partition("\n")
        if not separator:
            raise APIError(f"background output returned invalid size for {path}")
        try:
            size = int(size_text)
            output = base64.b64decode(encoded, validate=True).decode(errors="replace")
        except (ValueError, binascii.Error) as exc:
            raise APIError(f"background output returned invalid data for {path}") from exc
        return output, size > _BACKGROUND_OUTPUT_TAIL_BYTES

    async def get_background_job(
        self,
        sandbox_id: str,
        job: Any,
        timeout: int | None = None,
    ) -> BackgroundJobStatus:
        info = self._info(sandbox_id)
        job_id = str(getattr(job, "job_id", None) or (job.get("job_id") if isinstance(job, dict) else ""))
        if not job_id:
            raise APIError("background job has no job_id")
        outer_dir, _ = self._background_job_paths(info, job_id)
        status = await self._outer_exec_idempotent(
            info,
            "\n".join(
                [
                    f"job_dir={shlex.quote(outer_dir)}",
                    'if [ -f "$job_dir/result" ]; then',
                    '  printf "FINISHED:%s\\n" "$(cat "$job_dir/result")"',
                    '  test ! -f "$job_dir/failure_reason" || cat "$job_dir/failure_reason"',
                    '  printf "OCI_MEMORY_OOM_KILL=%s\\n" "$(cat "$job_dir/memory_oom_kill" 2>/dev/null || printf unknown)"',
                    '  printf "OCI_MEMORY_PEAK=%s\\n" "$(cat "$job_dir/memory_peak" 2>/dev/null || printf unknown)"',
                    '  printf "OCI_TASK_DISK_BYTES=%s\\n" "$(cat "$job_dir/disk_bytes" 2>/dev/null || printf unknown)"',
                    'elif [ -f "$job_dir/supervisor.pid" ] && kill -0 "$(cat "$job_dir/supervisor.pid")" 2>/dev/null; then',
                    "  printf 'RUNNING\\n'",
                    "else",
                    "  printf 'LOST\\n'",
                    "fi",
                ]
            ),
            timeout=min(int(timeout or 30), 60),
            operation="background_job_status",
            retry_ambiguous_transport=True,
        )
        lines = status.stdout.splitlines()
        state = lines[0] if lines else ""
        if state == "RUNNING":
            return BackgroundJobStatus(job_id=job_id, completed=False)
        if state == "LOST":
            raise self._poisoned_shell_error(
                info,
                "background_job_lost",
                f"background job {job_id} was lost",
                failure_reason="command_outcome_unknown",
            )
        if not state.startswith("FINISHED:"):
            raise self._poisoned_shell_error(
                info,
                "invalid_background_status",
                f"background job {job_id} returned invalid status {state!r}",
                failure_reason="command_outcome_unknown",
            )
        try:
            exit_code = int(state.removeprefix("FINISHED:"))
        except ValueError as exc:
            raise self._poisoned_shell_error(
                info,
                "invalid_background_status",
                f"background job {job_id} returned invalid exit status {state!r}",
                failure_reason="command_outcome_unknown",
            ) from exc
        failure_reason = lines[1] if len(lines) > 1 and not lines[1].startswith("OCI_") else None
        values = dict(line.split("=", 1) for line in lines[1:] if line.startswith("OCI_") and "=" in line)
        if (oom_kills := values.get("OCI_MEMORY_OOM_KILL", "")).isdigit():
            info.metadata["cgroup_memory_events"] = {"oom_kill": int(oom_kills)}
        if (memory_peak := values.get("OCI_MEMORY_PEAK", "")).isdigit():
            info.metadata["cgroup_memory_peak_bytes"] = int(memory_peak)
        if (disk_bytes := values.get("OCI_TASK_DISK_BYTES", "")).isdigit():
            info.metadata["task_disk_peak_bytes"] = int(disk_bytes)
        if failure_reason == "nested_oom":
            diagnostics = await self._collect_terminal_diagnostics(info)
            outer_healthy = diagnostics.get("health_http_status") == 200
            info.metadata["outer_healthy_after_nested_oom"] = outer_healthy
            if not outer_healthy:
                info.assignment_poisoned = True
                info.assignment_poison_reason = "nested_oom_outer_health_unverified"
                info.metadata.update(
                    assignment_poisoned=True,
                    assignment_poison_reason=info.assignment_poison_reason,
                )
            info.metadata["failure_reason"] = "nested_oom"
            raise OCIRunnerStageError(
                "shell_exec",
                f"nested task container was OOM-killed while running {job_id}",
                failure_reason="nested_oom",
            )
        stdout, stdout_truncated = await self._read_outer_tail(info, f"{outer_dir}/stdout.log")
        stderr, stderr_truncated = await self._read_outer_tail(info, f"{outer_dir}/stderr.log")
        truncated_streams = [
            stream
            for stream, truncated in (
                ("stdout", stdout_truncated),
                ("stderr", stderr_truncated),
            )
            if truncated
        ]
        if truncated_streams:
            info.metadata.update(
                background_output_truncated=True,
                background_output_truncated_streams=truncated_streams,
            )
        return BackgroundJobStatus(
            job_id=job_id,
            completed=True,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    async def _terminate_background_job(
        self,
        info: registry.SessionInfo,
        job_id: str,
        *,
        grace_seconds: int = 10,
    ) -> bool:
        outer_dir, _ = self._background_job_paths(info, job_id)
        command = "\n".join(
            [
                "set +e",
                f"job_dir={shlex.quote(outer_dir)}",
                'supervisor=$(cat "$job_dir/supervisor.pid" 2>/dev/null)',
                'nested=$(cat "$job_dir/nested.pgid" 2>/dev/null)',
                'case "$supervisor" in ""|*[!0-9]*) supervisor= ;; esac',
                'case "$nested" in ""|*[!0-9]*) nested= ;; esac',
                "nested_alive() {",
                '  [ -n "$nested" ] || return 1',
                '  podman exec task bash -lc \'kill -0 -- "-$1" 2>/dev/null\' bash "$nested" >/dev/null 2>&1',
                "}",
                "if nested_alive; then podman exec task bash -lc 'kill -TERM -- \"-$1\" 2>/dev/null' "
                'bash "$nested" >/dev/null 2>&1; fi',
                'if [ -n "$supervisor" ] && kill -0 -- "-$supervisor" 2>/dev/null; then',
                '  kill -TERM -- "-$supervisor" 2>/dev/null',
                "fi",
                f"deadline=$((SECONDS + {grace_seconds}))",
                'while { nested_alive || { [ -n "$supervisor" ] && kill -0 -- "-$supervisor" 2>/dev/null; }; } '
                '&& [ "$SECONDS" -lt "$deadline" ]; do sleep 0.2; done',
                "if nested_alive; then podman exec task bash -lc 'kill -KILL -- \"-$1\" 2>/dev/null' "
                'bash "$nested" >/dev/null 2>&1; fi',
                'if [ -n "$supervisor" ] && kill -0 -- "-$supervisor" 2>/dev/null; then',
                '  kill -KILL -- "-$supervisor" 2>/dev/null',
                "fi",
                "for _ in $(seq 1 20); do",
                '  if ! nested_alive && { [ -z "$supervisor" ] || ! kill -0 -- "-$supervisor" 2>/dev/null; }; then break; fi',
                "  sleep 0.1",
                "done",
                "nested_alive && exit 1",
                '[ -n "$supervisor" ] && kill -0 -- "-$supervisor" 2>/dev/null && exit 1',
                "bash -lc true",
            ]
        )
        try:
            result = await self._outer_exec_idempotent(
                info,
                command,
                timeout=grace_seconds + 20,
                operation="background_job_terminate",
                retry_ambiguous_transport=True,
            )
        except Exception:
            return False
        return result.exit_code == 0 and await self._verify_shell_usable(info)

    async def _finish_background_termination(
        self,
        info: registry.SessionInfo,
        job_id: str,
    ) -> tuple[bool, asyncio.CancelledError | None]:
        """Finish one termination attempt even under repeated caller cancellation."""
        termination = asyncio.create_task(self._terminate_background_job(info, job_id))
        deferred_cancellation = None
        while not termination.done():
            try:
                await asyncio.shield(termination)
            except asyncio.CancelledError as error:
                deferred_cancellation = deferred_cancellation or error
            except Exception:
                break
        try:
            terminated = termination.result()
        except BaseException:
            terminated = False
        return terminated, deferred_cancellation

    def _background_cleanup_error(
        self,
        info: registry.SessionInfo,
        status: str,
        message: str,
        *,
        failure_reason: str,
        timeout_category: str | None = None,
    ) -> OCIRunnerStageError:
        return self._poisoned_shell_error(
            info,
            status,
            message,
            failure_reason=failure_reason,
            timeout_category=timeout_category,
        )

    async def run_background_job(
        self,
        sandbox_id: str,
        command: str,
        timeout: int | None = None,
        working_dir: str | None = None,
        env: dict | None = None,
        poll_interval: int = 3,
    ) -> CommandResponse:
        info = self._info(sandbox_id)
        launch = asyncio.create_task(
            self.start_background_job(
                sandbox_id,
                command,
                working_dir=working_dir,
                env=env,
            )
        )
        launch_cancellation = None
        while not launch.done():
            try:
                await asyncio.shield(launch)
            except asyncio.CancelledError as error:
                launch_cancellation = launch_cancellation or error
            except Exception:
                break
        try:
            job = launch.result()
        except BaseException as error:
            if launch_cancellation is not None:
                raise self._background_cleanup_error(
                    info,
                    "background_launch_cancelled",
                    "background launch did not settle safely after cancellation",
                    failure_reason="command_outcome_unknown",
                ) from error
            raise
        if launch_cancellation is not None:
            terminated, _ = await self._finish_background_termination(info, str(job.job_id))
            if not terminated:
                raise self._background_cleanup_error(
                    info,
                    "background_launch_cancellation_cleanup_unverified",
                    "cancelled background launch could not be terminated and joined",
                    failure_reason="command_cancellation_cleanup_unverified",
                ) from launch_cancellation
            raise launch_cancellation
        deadline = time.monotonic() + timeout if timeout is not None else None
        delay = min(0.1, max(float(poll_interval), 0.1))
        try:
            while True:
                status = await self.get_background_job(sandbox_id, job, timeout=30)
                if status.completed:
                    return CommandResponse(
                        stdout=status.stdout or "",
                        stderr=status.stderr or "",
                        exit_code=(status.exit_code if status.exit_code is not None else -1),
                    )
                if deadline is not None and time.monotonic() >= deadline:
                    terminated, deferred_cancellation = await self._finish_background_termination(info, str(job.job_id))
                    if not terminated:
                        raise self._background_cleanup_error(
                            info,
                            "background_timeout_cleanup_unverified",
                            "timed-out background command could not be terminated and joined",
                            failure_reason="command_timeout_cleanup_unverified",
                            timeout_category="client_command_budget",
                        )
                    if deferred_cancellation is not None:
                        raise deferred_cancellation
                    info.metadata.update(
                        failure_reason="command_budget_exhausted",
                        timeout_category="client_command_budget",
                    )
                    return CommandResponse(
                        stdout="",
                        stderr="SANDOQ_COMMAND_TIMEOUT=1\n",
                        exit_code=124,
                    )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max(float(poll_interval), 0.1))
        except asyncio.CancelledError as cancellation:
            terminated, _ = await self._finish_background_termination(info, str(job.job_id))
            if not terminated:
                raise self._background_cleanup_error(
                    info,
                    "background_cancellation_cleanup_unverified",
                    "cancelled background command could not be terminated and joined",
                    failure_reason="command_cancellation_cleanup_unverified",
                ) from cancellation
            raise
        except Exception as error:
            terminated, deferred_cancellation = await self._finish_background_termination(info, str(job.job_id))
            if not terminated:
                raise self._background_cleanup_error(
                    info,
                    "background_error_cleanup_unverified",
                    "failed background command could not be terminated and joined",
                    failure_reason="command_error_cleanup_unverified",
                ) from error
            if deferred_cancellation is not None:
                raise deferred_cancellation
            raise

    async def session_metadata(self, sandbox_id: str) -> dict[str, object]:
        return dict(self._info(sandbox_id).metadata)

    async def _collect_resource_metrics(self, info: registry.SessionInfo) -> None:
        if info.assignment_poisoned or not info.nested_ready:
            return
        command = """
set +e
podman exec task sh -c '
for name in memory.current memory.peak memory.max; do
  path=/sys/fs/cgroup/$name
  [ -r "$path" ] && printf "OCI_CGROUP_%s=%s\\n" "${name#memory.}" "$(cat "$path")"
done
if [ -r /sys/fs/cgroup/memory.events ]; then
  awk '\''{printf "OCI_MEMORY_EVENT_%s=%s\\n", toupper($1), $2}'\'' /sys/fs/cgroup/memory.events
fi
' 2>/dev/null
podman inspect --size task --format 'OCI_TASK_DISK_BYTES={{.SizeRw}}' 2>/dev/null
true
"""
        try:
            result = await self._outer_exec_idempotent(
                info,
                command,
                timeout=30,
                operation="resource_telemetry",
            )
        except Exception as exc:
            info.metadata["resource_telemetry_error"] = type(exc).__name__
            return
        values = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if line.startswith("OCI_") and "=" in line
        )
        for key in ("OCI_CGROUP_CURRENT", "OCI_CGROUP_PEAK", "OCI_CGROUP_MAX", "OCI_TASK_DISK_BYTES"):
            value = values.get(key)
            if value is not None and value.isdigit():
                info.metadata[
                    {
                        "OCI_CGROUP_CURRENT": "cgroup_memory_current_bytes",
                        "OCI_CGROUP_PEAK": "cgroup_memory_peak_bytes",
                        "OCI_CGROUP_MAX": "cgroup_memory_max_bytes",
                        "OCI_TASK_DISK_BYTES": "task_disk_peak_bytes",
                    }[key]
                ] = int(value)
        memory_events = {
            key.removeprefix("OCI_MEMORY_EVENT_").lower(): int(value)
            for key, value in values.items()
            if key.startswith("OCI_MEMORY_EVENT_") and value.isdigit()
        }
        if memory_events:
            info.metadata["cgroup_memory_events"] = memory_events
        if memory_events.get("oom_kill", 0) > 0:
            info.metadata["failure_reason"] = "nested_oom"

    async def poison_assignment(
        self,
        sandbox_id: str,
        *,
        reason: str,
        shell_failure_status: str | None = None,
    ) -> None:
        """Force setup recovery to retire the current assignment before reacquisition."""
        info = self._info(sandbox_id)
        info.assignment_poisoned = True
        info.assignment_poison_reason = reason
        if shell_failure_status is not None:
            info.shell_failure_status = shell_failure_status
        info.metadata.update(
            assignment_poisoned=True,
            assignment_poison_reason=reason,
            shell_failure_status=info.shell_failure_status,
        )

    async def _delete_outer(self, sandbox_id: str, timeout: float) -> dict[str, object]:
        try:
            deletion = await get_gateway_adapter(self._base, self._oci_cfg.owner).delete_session_async(
                sandbox_id,
                timeout=timeout,
                prime=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._oci_cfg.observability:
                raise OCIRunnerStageError(
                    "deletion_verification",
                    f"OCI runner session {sandbox_id} deletion was not confirmed by typed HTTP 404: {exc}",
                ) from exc
            raise APIError(
                f"OCI runner session {sandbox_id} deletion was not confirmed by typed HTTP 404: {exc}"
            ) from exc
        response: dict[str, object] = {
            "status": "deleted",
            "sandbox_id": sandbox_id,
            "verified_http_status": deletion.verified_http_status,
        }
        if self._oci_cfg.observability:
            response["timings"] = {
                "cleanup": deletion.cleanup_seconds,
                "deletion_verification": deletion.verification_seconds,
            }
        return response

    async def delete(self, sandbox_id: str, timeout: float | None = None) -> dict[str, object]:
        info = registry.get(sandbox_id)
        try:
            if info is not None:
                await self._collect_resource_metrics(info)
            if info is not None and info.session_reuse:
                from sandoq_provider.pool import get_pool_client

                response = await asyncio.to_thread(
                    get_pool_client().release,
                    sandbox_id,
                    poison=info.assignment_poisoned,
                    reason=info.assignment_poison_reason or "rollout_complete",
                    shell_failure_status=info.shell_failure_status,
                )
            else:
                outer_id = info.outer_session_id if info is not None else None
                response = await self._delete_outer(outer_id or sandbox_id, float(timeout or 60.0))
                if info is not None:
                    response.update(
                        poisoned=info.assignment_poisoned,
                        shell_id=info.shell_id,
                        shell_failure_status=info.shell_failure_status,
                    )
        except BaseException as exc:
            if info is not None:
                self._record_cleanup_receipt(info, {}, error=exc)
            raise
        if self._oci_cfg.observability and info is not None:
            response_timings = response.get("timings")
            timings = info.metadata.setdefault("oci_timings", {})
            if isinstance(response_timings, dict) and isinstance(timings, dict):
                timings.update(response_timings)
                response["timings"] = dict(timings)
        if info is not None:
            self._record_cleanup_receipt(info, response)
        registry.unregister(sandbox_id)
        if info is not None and info.session_reuse:
            print(
                f"OCI runner assignment released: {sandbox_id} "
                f"nested_recycle_verified={response.get('nested_recycle_verified')}",
                flush=True,
            )
        else:
            print(f"OCI runner session deleted: {sandbox_id} verified_http_status=404", flush=True)
        return response

    @staticmethod
    def _record_cleanup_receipt(
        info: registry.SessionInfo,
        response: dict[str, object],
        *,
        error: BaseException | None = None,
    ) -> None:
        metadata = info.metadata
        nested_recycle_verified = bool(response.get("nested_recycle_verified"))
        poisoned_cleanup_verified = bool(response.get("poisoned")) and (
            response.get("outer_deletion_verified_http_status") == 404
        )
        direct_cleanup_verified = response.get("verified_http_status") == 404
        receipt: dict[str, object] = {
            "schema_version": 3,
            "runtime_name": info.runtime_name,
            "assignment_id": info.session_id,
            "outer_session_id": info.outer_session_id,
            "slot_id": info.slot_id,
            "slot_generation": info.generation,
            "reuse_count": info.reuse_count,
            "reuse_threshold": metadata.get("reuse_threshold"),
            "requested_image": info.source_image,
            "resolved_digest": info.resolved_digest or metadata.get("resolved_digest"),
            "image_mounts": list(metadata.get("image_mounts") or []),
            "image_size_bytes": metadata.get("image_size_bytes"),
            "pool_wait_seconds": info.pool_wait_seconds,
            "outer_age_seconds": metadata.get("outer_age_seconds"),
            "ecr_registry": metadata.get("ecr_registry"),
            "ecr_credential_source": metadata.get("ecr_credential_source"),
            "ecr_authentication": dict(metadata.get("ecr_authentication") or {}),
            "base_commit_original": metadata.get("base_commit_original"),
            "base_commit_final": metadata.get("base_commit_final"),
            "base_commit_repaired": metadata.get("base_commit_repaired"),
            "shell_id": info.shell_id,
            "shell_generation": response.get("shell_generation", info.metadata.get("shell_generation", 0)),
            "managed_shell_recovery_count": response.get(
                "managed_shell_recovery_count",
                metadata.get("managed_shell_recovery_count", 0),
            ),
            "shell_failure_status": info.shell_failure_status,
            "shell_command_mode": metadata.get("shell_command_mode"),
            "image_pull_fallback": metadata.get("image_pull_fallback"),
            "allow_dockerhub_fallback": metadata.get("allow_dockerhub_fallback"),
            "podman_storage_driver": metadata.get("podman_storage_driver"),
            "podman_ignore_chown_errors": metadata.get("podman_ignore_chown_errors"),
            "failure_reason": metadata.get("failure_reason"),
            "requested_resources": metadata.get("requested_resources"),
            "effective_resources": metadata.get("effective_resources"),
            "cgroup_memory_current_bytes": metadata.get("cgroup_memory_current_bytes"),
            "cgroup_memory_peak_bytes": metadata.get("cgroup_memory_peak_bytes"),
            "cgroup_memory_max_bytes": metadata.get("cgroup_memory_max_bytes"),
            "cgroup_memory_events": metadata.get("cgroup_memory_events"),
            "outer_healthy_after_nested_oom": metadata.get("outer_healthy_after_nested_oom"),
            "task_disk_peak_bytes": metadata.get("task_disk_peak_bytes"),
            "timeout_category": metadata.get("timeout_category"),
            "cause_stage": metadata.get("cause_stage"),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "wandb_run_id": os.environ.get("WANDB_SHARED_RUN_ID"),
            "idempotent_gateway_retry_count": metadata.get("idempotent_gateway_retry_count", 0),
            "transient_gateway_response_count": metadata.get("transient_gateway_response_count", 0),
            "pre_request_retry_count": metadata.get("pre_request_retry_count", 0),
            "pre_request_retry_recovered_count": metadata.get("pre_request_retry_recovered_count", 0),
            "pre_request_retry_exhausted_count": metadata.get("pre_request_retry_exhausted_count", 0),
            "transport_delivery_state": metadata.get("transport_delivery_state"),
            "command_server_readiness": metadata.get("command_server_readiness"),
            "authentication_probe_http_status": metadata.get("authentication_probe_http_status"),
            "authentication_probe_expected": metadata.get("authentication_probe_expected"),
            "cleanup_gateway_retry_count": response.get("cleanup_gateway_retry_count", 0),
            "cleanup_gateway_retry_exhausted_count": response.get("cleanup_gateway_retry_exhausted_count", 0),
            "nested_recycle_verified": nested_recycle_verified,
            "shell_deleted": bool(response.get("shell_deleted")),
            "assignment_poisoned": bool(info.assignment_poisoned or response.get("poisoned")),
            "verified_http_status": response.get("verified_http_status"),
            "outer_deletion_verified_http_status": response.get("outer_deletion_verified_http_status"),
            "timings": dict(response.get("timings") or metadata.get("oci_timings") or {}),
            "cleanup_verified": nested_recycle_verified or poisoned_cleanup_verified or direct_cleanup_verified,
        }
        if error is not None:
            receipt["cleanup_error_type"] = type(error).__name__
        registry.record_cleanup_receipt(info.runtime_name or "", receipt)

    def teardown(self, wait: bool = True) -> None:
        """Match the SandboxEnv client lifecycle without owning an executor."""
        del wait

    async def drain_pool(self) -> dict[str, object]:
        if not self._oci_cfg.session_reuse:
            return {"drained": True, "deleted": [], "failures": {}}
        from sandoq_provider.pool import get_pool_client

        return await asyncio.to_thread(get_pool_client().drain)


__all__ = [
    "OCIRunnerAsyncSandboxClient",
    "OCIRunnerConfig",
    "OCIRunnerStageError",
    "OCIRunnerTransientGatewayError",
    "delete_outer_sync",
    "delete_registered_sessions_sync",
    "get_oci_config",
    "normalize_command_response",
    "read_token_file",
]
