#!/usr/bin/env python3
"""Fail closed unless the exact direct-Kimi workers outlive an extended run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from inference_route_generation import HOST_RE, SLURM_JOB_ID_RE, canonical_backend_identifier

EXPECTED_DEPLOYMENT = "shared-kimi-k3"
EXPECTED_CLUSTER = "fair-cw-use2-1"
EXPECTED_ENDPOINTS = 24
EXTENDED_PROFILE = "tb4-extended-c24-two-wave-v1"
C23_PROFILE = "tb4-c23-v1"
C23_MANIFEST_CAPACITY_PROFILE = "sandoq-c23-v1"
C23_MANIFEST_SELECTION_PROFILE = "exclude-one-from-c24-v1"
C23_SELECTED_ENDPOINTS = 23
EXTENDED_MINIMUM_REMAINING_SECONDS = 90 * 60 * 60
EXTENDED_REQUEST_TIMEOUT_SECONDS = 144_000
EXTENDED_ROUTER_CONCURRENCY = 24
RECEIPT_KIND = "direct-kimi-endpoint-walltime-gate"
RECEIPT_SCHEMA_VERSION = 1
C23_RECEIPT_SCHEMA_VERSION = 2
MAX_STATUS_BYTES = 8 * 1024 * 1024
MAX_SCHEDULER_BYTES = 1 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")
DEFAULT_SERVE_SH = Path("/storage/home/tianhaowu/ram_common/vllm_tools/serve_api_v2/serve.sh")
SACCT = Path("/usr/bin/sacct")
COMMAND_TIMEOUT_SECONDS = 60


class EndpointWalltimeGateError(RuntimeError):
    """The live endpoint allocation cannot authorize an extended rollout."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes = b""


@dataclass(frozen=True)
class EndpointRoute:
    job_id: str
    backend_sha256: str


@dataclass(frozen=True)
class StatusSnapshot:
    sha256: str
    routes: tuple[EndpointRoute, ...]


@dataclass(frozen=True)
class SchedulerObservation:
    job_id: str
    state: str
    restarts: int
    elapsed_seconds: int
    time_limit_seconds: int

    @property
    def remaining_seconds(self) -> int:
        return self.time_limit_seconds - self.elapsed_seconds


CommandRunner = Callable[[Sequence[str], int], CommandResult]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_command(argv: Sequence[str], timeout: int) -> CommandResult:
    environment = {key: value for key, value in os.environ.items() if not key.casefold().endswith("_proxy")}
    environment["PATH"] = "/usr/bin:/bin"
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            env=environment,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EndpointWalltimeGateError("scheduler_or_status_command_unavailable") from error
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _status_command(serve_sh: Path, deployment: str) -> tuple[str, ...]:
    try:
        resolved = serve_sh.resolve(strict=True)
    except OSError as error:
        raise EndpointWalltimeGateError("serve_status_source_unavailable") from error
    if not resolved.is_file() or resolved.name != "serve.sh":
        raise EndpointWalltimeGateError("serve_status_source_invalid")
    pythonpath = str(resolved.parent / "src")
    inherited = os.environ.get("PYTHONPATH")
    if inherited:
        pythonpath = os.pathsep.join((pythonpath, inherited))
    return (
        "/usr/bin/env",
        "PATH=/usr/bin:/bin",
        f"PYTHONPATH={pythonpath}",
        sys.executable,
        "-m",
        "serve_api_v2.cli.status",
        deployment,
        "--json",
    )


def _scheduler_command(job_ids: Sequence[str], cluster: str) -> tuple[str, ...]:
    return (
        str(SACCT),
        "-M",
        cluster,
        "-X",
        "-n",
        "-P",
        "-j",
        ",".join(job_ids),
        "-o",
        "JobIDRaw,State,Restarts,ElapsedRaw,TimelimitRaw",
    )


def parse_status_snapshot(raw: bytes, expected_backend_sha256s: Sequence[str]) -> StatusSnapshot:
    """Return only the endpoint/job binding from one status JSON snapshot."""

    if not raw or len(raw) > MAX_STATUS_BYTES:
        raise EndpointWalltimeGateError("deployment_status_size_invalid")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EndpointWalltimeGateError("deployment_status_invalid") from error
    summary = payload.get("endpoints_summary") if isinstance(payload, dict) else None
    endpoints = payload.get("endpoints") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 4
        or payload.get("deployment_id") != EXPECTED_DEPLOYMENT
        or payload.get("phase") != "serving"
        or not isinstance(summary, dict)
        or summary.get("desired") != EXPECTED_ENDPOINTS
        or summary.get("ready") != EXPECTED_ENDPOINTS
        or summary.get("running_not_ready") != 0
        or summary.get("pending") != 0
        or not isinstance(endpoints, list)
        or len(endpoints) != EXPECTED_ENDPOINTS
    ):
        raise EndpointWalltimeGateError("deployment_status_not_exactly_ready")

    routes: list[EndpointRoute] = []
    for endpoint in endpoints:
        if (
            not isinstance(endpoint, dict)
            or endpoint.get("slurm_state") != "RUNNING"
            or endpoint.get("sub_state") != "ready"
        ):
            raise EndpointWalltimeGateError("deployment_endpoint_not_ready")
        job_id = endpoint.get("jobid")
        host = endpoint.get("host")
        port = endpoint.get("port")
        if (
            not isinstance(job_id, str)
            or SLURM_JOB_ID_RE.fullmatch(job_id) is None
            or not isinstance(host, str)
            or HOST_RE.fullmatch(host) is None
            or not isinstance(port, int)
            or isinstance(port, bool)
            or not 1 <= port <= 65_535
        ):
            raise EndpointWalltimeGateError("deployment_endpoint_identity_invalid")
        backend = canonical_backend_identifier(f"http://{host}:{port}/v1")
        routes.append(EndpointRoute(job_id, backend.removeprefix("backend-sha256:")))

    routes.sort(key=lambda route: int(route.job_id))
    expected = tuple(sorted(expected_backend_sha256s))
    observed = tuple(sorted(route.backend_sha256 for route in routes))
    if (
        len(expected) != EXPECTED_ENDPOINTS
        or any(SHA256_RE.fullmatch(value) is None for value in expected)
        or len({route.job_id for route in routes}) != EXPECTED_ENDPOINTS
        or len({route.backend_sha256 for route in routes}) != EXPECTED_ENDPOINTS
        or observed != expected
    ):
        raise EndpointWalltimeGateError("deployment_endpoint_bundle_mismatch")
    return StatusSnapshot(_sha256(raw), tuple(routes))


def parse_scheduler_output(
    raw: bytes,
    expected_job_ids: Sequence[str],
    minimum_remaining_seconds: int,
    *,
    expected_endpoint_count: int = EXPECTED_ENDPOINTS,
) -> tuple[tuple[SchedulerObservation, ...], int, str]:
    """Validate exact sacct rows and return aggregate walltime evidence."""

    if not raw or len(raw) > MAX_SCHEDULER_BYTES:
        raise EndpointWalltimeGateError("scheduler_snapshot_size_invalid")
    if (
        not isinstance(minimum_remaining_seconds, int)
        or isinstance(minimum_remaining_seconds, bool)
        or minimum_remaining_seconds < EXTENDED_MINIMUM_REMAINING_SECONDS
    ):
        raise EndpointWalltimeGateError("minimum_remaining_seconds_invalid")
    expected = tuple(sorted(expected_job_ids, key=int))
    if (
        expected_endpoint_count not in (C23_SELECTED_ENDPOINTS, EXPECTED_ENDPOINTS)
        or len(expected) != expected_endpoint_count
        or len(set(expected)) != expected_endpoint_count
        or any(SLURM_JOB_ID_RE.fullmatch(value) is None for value in expected)
    ):
        raise EndpointWalltimeGateError("endpoint_job_set_invalid")

    try:
        lines = raw.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as error:
        raise EndpointWalltimeGateError("scheduler_snapshot_invalid") from error
    observations: list[SchedulerObservation] = []
    for line in lines:
        if not line:
            continue
        fields = line.split("|")
        if len(fields) != 5:
            raise EndpointWalltimeGateError("scheduler_snapshot_invalid")
        job_id, state, raw_restarts, raw_elapsed, raw_limit_minutes = fields
        if (
            SLURM_JOB_ID_RE.fullmatch(job_id) is None
            or not raw_restarts.isdigit()
            or not raw_elapsed.isdigit()
            or not raw_limit_minutes.isdigit()
        ):
            raise EndpointWalltimeGateError("scheduler_snapshot_invalid")
        observations.append(
            SchedulerObservation(
                job_id=job_id,
                state=state,
                restarts=int(raw_restarts),
                elapsed_seconds=int(raw_elapsed),
                time_limit_seconds=int(raw_limit_minutes) * 60,
            )
        )
    observations.sort(key=lambda item: int(item.job_id))
    if (
        tuple(item.job_id for item in observations) != expected
        or len({item.job_id for item in observations}) != expected_endpoint_count
    ):
        raise EndpointWalltimeGateError("scheduler_endpoint_job_set_mismatch")
    if any(item.state != "RUNNING" for item in observations):
        raise EndpointWalltimeGateError("scheduler_endpoint_not_running")
    if any(item.restarts != 0 for item in observations):
        raise EndpointWalltimeGateError("scheduler_endpoint_restarted")
    minimum = min(item.remaining_seconds for item in observations)
    if minimum < minimum_remaining_seconds:
        raise EndpointWalltimeGateError("scheduler_endpoint_walltime_insufficient")
    canonical = "".join(
        f"{item.job_id}|{item.state}|{item.restarts}|{item.elapsed_seconds}|"
        f"{item.time_limit_seconds}|{item.remaining_seconds}\n"
        for item in observations
    ).encode()
    return tuple(observations), minimum, _sha256(canonical)


def _validate_profile(profile: str, minimum_remaining_seconds: int) -> None:
    if profile not in (EXTENDED_PROFILE, C23_PROFILE):
        raise EndpointWalltimeGateError("endpoint_walltime_profile_invalid")
    if (
        not isinstance(minimum_remaining_seconds, int)
        or isinstance(minimum_remaining_seconds, bool)
        or minimum_remaining_seconds < EXTENDED_MINIMUM_REMAINING_SECONDS
    ):
        raise EndpointWalltimeGateError("minimum_remaining_seconds_invalid")


def _validate_task_count(task_count: int, *, profile: str = EXTENDED_PROFILE) -> None:
    lower_bound = EXTENDED_ROUTER_CONCURRENCY
    upper_bound = 2 * C23_SELECTED_ENDPOINTS if profile == C23_PROFILE else 2 * EXTENDED_ROUTER_CONCURRENCY
    if (
        profile not in (EXTENDED_PROFILE, C23_PROFILE)
        or not isinstance(task_count, int)
        or isinstance(task_count, bool)
        or not lower_bound < task_count <= upper_bound
    ):
        raise EndpointWalltimeGateError("extended_two_wave_task_count_invalid")


def _bundle_sha256(backend_sha256s: Sequence[str]) -> str:
    return _sha256("".join(f"{digest}\n" for digest in sorted(backend_sha256s)).encode())


def _load_manifest(
    path: Path,
    expected_sha256: str,
    *,
    profile: str = EXTENDED_PROFILE,
) -> dict[str, Any]:
    if SHA256_RE.fullmatch(expected_sha256) is None:
        raise EndpointWalltimeGateError("direct_worker_manifest_sha256_invalid")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise EndpointWalltimeGateError("direct_worker_manifest_unreadable") from error
    if _sha256(raw) != expected_sha256:
        raise EndpointWalltimeGateError("direct_worker_manifest_sha256_mismatch")
    try:
        from direct_kimi_workers import validate_saved_manifest

        manifest = validate_saved_manifest(path, body=raw)
    except (OSError, RuntimeError, ValueError) as error:
        raise EndpointWalltimeGateError("direct_worker_manifest_invalid") from error
    if not isinstance(manifest, dict):
        raise EndpointWalltimeGateError("direct_worker_manifest_invalid")
    router = manifest.get("router")
    common_router_invalid = (
        not isinstance(router, dict)
        or router.get("request_timeout_seconds") != EXTENDED_REQUEST_TIMEOUT_SECONDS
        or router.get("queue_timeout_seconds") != EXTENDED_REQUEST_TIMEOUT_SECONDS
        or router.get("retries") != 0
    )
    if profile == EXTENDED_PROFILE:
        invalid = (
            manifest.get("schema_version") != 1
            or common_router_invalid
            or "capacity_profile" in router
            or router.get("max_concurrent_requests") != EXTENDED_ROUTER_CONCURRENCY
            or router.get("queue_size") != EXTENDED_ROUTER_CONCURRENCY
        )
    elif profile == C23_PROFILE:
        workers = manifest.get("workers")
        excluded = manifest.get("excluded_worker")
        selected_backends = (
            [worker.get("backend_sha256") for worker in workers]
            if isinstance(workers, list) and all(isinstance(worker, dict) for worker in workers)
            else []
        )
        excluded_backend = excluded.get("backend_sha256") if isinstance(excluded, dict) else None
        full_backends = [*selected_backends, excluded_backend]
        invalid = (
            manifest.get("schema_version") != 4
            or common_router_invalid
            or router.get("capacity_profile") != C23_MANIFEST_CAPACITY_PROFILE
            or router.get("max_concurrent_requests") != C23_SELECTED_ENDPOINTS
            or router.get("queue_size") != C23_SELECTED_ENDPOINTS
            or manifest.get("selection_profile") != C23_MANIFEST_SELECTION_PROFILE
            or not isinstance(workers, list)
            or len(workers) != C23_SELECTED_ENDPOINTS
            or not isinstance(excluded, dict)
            or set(excluded) != {"backend_sha256", "model_sha256"}
            or len(selected_backends) != C23_SELECTED_ENDPOINTS
            or any(not isinstance(value, str) or SHA256_RE.fullmatch(value) is None for value in full_backends)
            or len(set(full_backends)) != EXPECTED_ENDPOINTS
            or selected_backends != sorted(selected_backends)
            or manifest.get("endpoint_bundle_sha256") != _bundle_sha256(selected_backends)
            or manifest.get("source_endpoint_bundle_sha256") != _bundle_sha256(full_backends)
        )
    else:
        raise EndpointWalltimeGateError("endpoint_walltime_profile_invalid")
    if invalid:
        raise EndpointWalltimeGateError("extended_router_manifest_invalid")
    return manifest


def capture_gate(
    *,
    manifest_path: Path,
    manifest_sha256: str,
    output: Path,
    profile: str,
    minimum_remaining_seconds: int,
    task_count: int,
    serve_sh: Path = DEFAULT_SERVE_SH,
    deployment: str = EXPECTED_DEPLOYMENT,
    cluster: str = EXPECTED_CLUSTER,
    runner: CommandRunner = _run_command,
    now: Callable[[], str] = _utc_now,
) -> dict[str, Any]:
    """Capture a double-read status/scheduler walltime attestation."""

    _validate_profile(profile, minimum_remaining_seconds)
    _validate_task_count(task_count, profile=profile)
    if deployment != EXPECTED_DEPLOYMENT or cluster != EXPECTED_CLUSTER:
        raise EndpointWalltimeGateError("deployment_or_cluster_invalid")
    manifest = _load_manifest(manifest_path, manifest_sha256, profile=profile)
    workers = manifest.get("workers") if isinstance(manifest, dict) else None
    selected_endpoint_count = C23_SELECTED_ENDPOINTS if profile == C23_PROFILE else EXPECTED_ENDPOINTS
    if not isinstance(workers, list) or len(workers) != selected_endpoint_count:
        raise EndpointWalltimeGateError("direct_worker_manifest_invalid")
    selected_backend_sha256s = tuple(
        str(worker.get("backend_sha256", "")) for worker in workers if isinstance(worker, dict)
    )
    if len(selected_backend_sha256s) != selected_endpoint_count:
        raise EndpointWalltimeGateError("direct_worker_manifest_invalid")
    excluded_backend_sha256: str | None = None
    if profile == C23_PROFILE:
        excluded = manifest.get("excluded_worker")
        excluded_backend_sha256 = excluded.get("backend_sha256") if isinstance(excluded, dict) else None
        if not isinstance(excluded_backend_sha256, str):
            raise EndpointWalltimeGateError("direct_worker_manifest_invalid")
        source_backend_sha256s = (*selected_backend_sha256s, excluded_backend_sha256)
    else:
        source_backend_sha256s = selected_backend_sha256s

    status_argv = _status_command(serve_sh, deployment)
    before_result = runner(status_argv, COMMAND_TIMEOUT_SECONDS)
    if before_result.returncode != 0 or before_result.stderr.strip():
        raise EndpointWalltimeGateError("deployment_status_command_failed")
    before = parse_status_snapshot(before_result.stdout, source_backend_sha256s)
    selected_backend_set = set(selected_backend_sha256s)
    selected_routes = tuple(route for route in before.routes if route.backend_sha256 in selected_backend_set)
    excluded_routes = tuple(route for route in before.routes if route.backend_sha256 not in selected_backend_set)
    if len(selected_routes) != selected_endpoint_count:
        raise EndpointWalltimeGateError("deployment_selected_endpoint_set_mismatch")
    if profile == C23_PROFILE:
        if len(excluded_routes) != 1 or excluded_routes[0].backend_sha256 != excluded_backend_sha256:
            raise EndpointWalltimeGateError("deployment_excluded_endpoint_mismatch")
    elif excluded_routes:
        raise EndpointWalltimeGateError("deployment_selected_endpoint_set_mismatch")
    job_ids = tuple(route.job_id for route in selected_routes)

    scheduler_result = runner(_scheduler_command(job_ids, cluster), COMMAND_TIMEOUT_SECONDS)
    if scheduler_result.returncode != 0 or scheduler_result.stderr.strip():
        raise EndpointWalltimeGateError("scheduler_snapshot_command_failed")
    observations, observed_minimum, scheduler_sha256 = parse_scheduler_output(
        scheduler_result.stdout,
        job_ids,
        minimum_remaining_seconds,
        expected_endpoint_count=selected_endpoint_count,
    )

    after_result = runner(status_argv, COMMAND_TIMEOUT_SECONDS)
    if after_result.returncode != 0 or after_result.stderr.strip():
        raise EndpointWalltimeGateError("deployment_status_command_failed")
    after = parse_status_snapshot(after_result.stdout, source_backend_sha256s)
    if before.routes != after.routes:
        raise EndpointWalltimeGateError("deployment_endpoint_generation_changed")

    canonical_jobs = "".join(f"{job_id}\n" for job_id in job_ids).encode()
    canonical_generation = "".join(
        f"{route.job_id}|{route.backend_sha256}\n" for route in selected_routes
    ).encode()
    receipt: dict[str, Any] = {
        "schema_version": C23_RECEIPT_SCHEMA_VERSION if profile == C23_PROFILE else RECEIPT_SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        "state": "passed",
        "profile": profile,
        "checked_at": now(),
        "deployment": deployment,
        "cluster": cluster,
        "endpoint_count": len(observations),
        "all_running": True,
        "all_restarts_zero": True,
        "minimum_remaining_seconds": minimum_remaining_seconds,
        "observed_minimum_remaining_seconds": observed_minimum,
        "task_count": task_count,
        "direct_worker_manifest_sha256": manifest_sha256,
        "endpoint_bundle_sha256": manifest["endpoint_bundle_sha256"],
        "endpoint_jobs_sha256": _sha256(canonical_jobs),
        "endpoint_generation_sha256": _sha256(canonical_generation),
        "status_snapshot_before_sha256": before.sha256,
        "status_snapshot_after_sha256": after.sha256,
        "scheduler_observation_sha256": scheduler_sha256,
    }
    if profile == C23_PROFILE:
        excluded_route = excluded_routes[0]
        excluded_job_sha256 = _sha256(f"{excluded_route.job_id}\n".encode())
        canonical_full_jobs = "".join(f"{route.job_id}\n" for route in before.routes).encode()
        canonical_full_generation = "".join(
            f"{route.job_id}|{route.backend_sha256}\n" for route in before.routes
        ).encode()
        receipt.update(
            {
                "live_endpoint_count": EXPECTED_ENDPOINTS,
                "excluded_endpoint_count": 1,
                "source_endpoint_bundle_sha256": manifest["source_endpoint_bundle_sha256"],
                "full_endpoint_jobs_sha256": _sha256(canonical_full_jobs),
                "full_endpoint_generation_sha256": _sha256(canonical_full_generation),
                "excluded_endpoint_job_sha256": excluded_job_sha256,
                "excluded_backend_sha256": excluded_route.backend_sha256,
                "excluded_endpoint_binding_sha256": _sha256(
                    f"{excluded_job_sha256}|{excluded_route.backend_sha256}\n".encode()
                ),
            }
        )
    receipt["receipt_sha256"] = _sha256(_canonical_json(receipt))
    validate_receipt(
        receipt,
        manifest_sha256=manifest_sha256,
        endpoint_bundle_sha256=manifest["endpoint_bundle_sha256"],
        profile=profile,
        minimum_remaining_seconds=minimum_remaining_seconds,
        task_count=task_count,
        source_endpoint_bundle_sha256=(
            manifest.get("source_endpoint_bundle_sha256") if profile == C23_PROFILE else None
        ),
        excluded_backend_sha256=excluded_backend_sha256,
    )
    _write_receipt(output, receipt)
    return receipt


def validate_receipt(
    value: object,
    *,
    manifest_sha256: str,
    endpoint_bundle_sha256: str,
    profile: str,
    minimum_remaining_seconds: int,
    task_count: int,
    source_endpoint_bundle_sha256: str | None = None,
    excluded_backend_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate the aggregate receipt without consulting mutable scheduler state."""

    _validate_profile(profile, minimum_remaining_seconds)
    _validate_task_count(task_count, profile=profile)
    expected_keys = {
        "schema_version",
        "kind",
        "state",
        "profile",
        "checked_at",
        "deployment",
        "cluster",
        "endpoint_count",
        "all_running",
        "all_restarts_zero",
        "minimum_remaining_seconds",
        "observed_minimum_remaining_seconds",
        "task_count",
        "direct_worker_manifest_sha256",
        "endpoint_bundle_sha256",
        "endpoint_jobs_sha256",
        "endpoint_generation_sha256",
        "status_snapshot_before_sha256",
        "status_snapshot_after_sha256",
        "scheduler_observation_sha256",
        "receipt_sha256",
    }
    if profile == C23_PROFILE:
        expected_keys.update(
            {
                "live_endpoint_count",
                "excluded_endpoint_count",
                "source_endpoint_bundle_sha256",
                "full_endpoint_jobs_sha256",
                "full_endpoint_generation_sha256",
                "excluded_endpoint_job_sha256",
                "excluded_backend_sha256",
                "excluded_endpoint_binding_sha256",
            }
        )
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_invalid")
    claimed = value.get("receipt_sha256")
    unsigned = dict(value)
    unsigned.pop("receipt_sha256")
    digests = (
        "direct_worker_manifest_sha256",
        "endpoint_bundle_sha256",
        "endpoint_jobs_sha256",
        "endpoint_generation_sha256",
        "status_snapshot_before_sha256",
        "status_snapshot_after_sha256",
        "scheduler_observation_sha256",
    )
    expected_schema_version = C23_RECEIPT_SCHEMA_VERSION if profile == C23_PROFILE else RECEIPT_SCHEMA_VERSION
    expected_endpoint_count = C23_SELECTED_ENDPOINTS if profile == C23_PROFILE else EXPECTED_ENDPOINTS
    if (
        value.get("schema_version") != expected_schema_version
        or value.get("kind") != RECEIPT_KIND
        or value.get("state") != "passed"
        or value.get("profile") != profile
        or value.get("deployment") != EXPECTED_DEPLOYMENT
        or value.get("cluster") != EXPECTED_CLUSTER
        or value.get("endpoint_count") != expected_endpoint_count
        or value.get("all_running") is not True
        or value.get("all_restarts_zero") is not True
        or value.get("minimum_remaining_seconds") != minimum_remaining_seconds
        or value.get("task_count") != task_count
        or not isinstance(value.get("observed_minimum_remaining_seconds"), int)
        or isinstance(value.get("observed_minimum_remaining_seconds"), bool)
        or value["observed_minimum_remaining_seconds"] < minimum_remaining_seconds
        or value.get("direct_worker_manifest_sha256") != manifest_sha256
        or value.get("endpoint_bundle_sha256") != endpoint_bundle_sha256
        or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in digests)
        or SHA256_RE.fullmatch(str(claimed or "")) is None
        or claimed != _sha256(_canonical_json(unsigned))
    ):
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_invalid")
    if profile == C23_PROFILE:
        c23_digests = (
            "source_endpoint_bundle_sha256",
            "full_endpoint_jobs_sha256",
            "full_endpoint_generation_sha256",
            "excluded_endpoint_job_sha256",
            "excluded_backend_sha256",
            "excluded_endpoint_binding_sha256",
        )
        observed_excluded_job_sha256 = value.get("excluded_endpoint_job_sha256")
        observed_excluded_backend_sha256 = value.get("excluded_backend_sha256")
        if (
            SHA256_RE.fullmatch(str(source_endpoint_bundle_sha256 or "")) is None
            or SHA256_RE.fullmatch(str(excluded_backend_sha256 or "")) is None
            or value.get("live_endpoint_count") != EXPECTED_ENDPOINTS
            or value.get("excluded_endpoint_count") != 1
            or value.get("source_endpoint_bundle_sha256") != source_endpoint_bundle_sha256
            or observed_excluded_backend_sha256 != excluded_backend_sha256
            or any(SHA256_RE.fullmatch(str(value.get(key, ""))) is None for key in c23_digests)
            or value.get("excluded_endpoint_binding_sha256")
            != _sha256(f"{observed_excluded_job_sha256}|{observed_excluded_backend_sha256}\n".encode())
        ):
            raise EndpointWalltimeGateError("endpoint_walltime_receipt_invalid")
    checked_at = value.get("checked_at")
    if not isinstance(checked_at, str):
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_invalid")
    try:
        datetime.strptime(checked_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_invalid") from error
    return value


def load_receipt(
    path: Path,
    *,
    manifest_sha256: str,
    endpoint_bundle_sha256: str,
    profile: str,
    minimum_remaining_seconds: int,
    task_count: int,
    source_endpoint_bundle_sha256: str | None = None,
    excluded_backend_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        before = path.lstat()
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_unreadable") from error
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.getuid()
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_unsafe")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_invalid") from error
    return validate_receipt(
        value,
        manifest_sha256=manifest_sha256,
        endpoint_bundle_sha256=endpoint_bundle_sha256,
        profile=profile,
        minimum_remaining_seconds=minimum_remaining_seconds,
        task_count=task_count,
        source_endpoint_bundle_sha256=source_endpoint_bundle_sha256,
        excluded_backend_sha256=excluded_backend_sha256,
    )


def _write_receipt(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_path_invalid")
    try:
        parent = path.parent.resolve(strict=True)
        parent_stat = parent.stat()
    except OSError as error:
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_parent_invalid") from error
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or stat.S_IMODE(parent_stat.st_mode) != 0o700
        or parent != path.parent
        or path.name in {"", ".", ".."}
    ):
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_parent_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise EndpointWalltimeGateError("endpoint_walltime_receipt_publish_failed") from error
    raw = _canonical_json(value) + b"\n"
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written < 1:
                raise EndpointWalltimeGateError("endpoint_walltime_receipt_publish_failed")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    os.close(descriptor)


def _manifest_endpoint_bundle(value: object) -> str:
    result = value.get("endpoint_bundle_sha256") if isinstance(value, dict) else None
    if not isinstance(result, str) or SHA256_RE.fullmatch(result) is None:
        raise EndpointWalltimeGateError("direct_worker_manifest_invalid")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    validate = subparsers.add_parser("validate")
    for command in (capture, validate):
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--manifest-sha256", required=True)
        command.add_argument("--profile", choices=(EXTENDED_PROFILE, C23_PROFILE), required=True)
        command.add_argument(
            "--minimum-remaining-seconds",
            type=int,
            default=EXTENDED_MINIMUM_REMAINING_SECONDS,
        )
        command.add_argument("--task-count", type=int, required=True)
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--serve-sh", type=Path, default=DEFAULT_SERVE_SH)
    capture.add_argument("--deployment", default=EXPECTED_DEPLOYMENT)
    capture.add_argument("--cluster", default=EXPECTED_CLUSTER)
    validate.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            receipt = capture_gate(
                manifest_path=args.manifest,
                manifest_sha256=args.manifest_sha256,
                output=args.output,
                profile=args.profile,
                minimum_remaining_seconds=args.minimum_remaining_seconds,
                task_count=args.task_count,
                serve_sh=args.serve_sh,
                deployment=args.deployment,
                cluster=args.cluster,
            )
        else:
            manifest = _load_manifest(args.manifest, args.manifest_sha256, profile=args.profile)
            excluded = manifest.get("excluded_worker") if args.profile == C23_PROFILE else None
            receipt = load_receipt(
                args.receipt,
                manifest_sha256=args.manifest_sha256,
                endpoint_bundle_sha256=_manifest_endpoint_bundle(manifest),
                profile=args.profile,
                minimum_remaining_seconds=args.minimum_remaining_seconds,
                task_count=args.task_count,
                source_endpoint_bundle_sha256=(
                    manifest.get("source_endpoint_bundle_sha256") if args.profile == C23_PROFILE else None
                ),
                excluded_backend_sha256=(
                    excluded.get("backend_sha256") if isinstance(excluded, dict) else None
                ),
            )
    except EndpointWalltimeGateError as error:
        print(f"endpoint_walltime_gate_error:{error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "endpoint_count": receipt["endpoint_count"],
                "minimum_remaining_seconds": receipt["observed_minimum_remaining_seconds"],
                "ok": True,
                "receipt_sha256": receipt["receipt_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
